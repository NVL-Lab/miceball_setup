"""Remote Experiment accounting requires scientific-owner confirmation."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lab_sync_acquisition import ExperimentConfiguration, RuntimeEvidenceMessage, RuntimeParticipant
from tests import test_health_closeout_accounting as fixtures
from tests.test_producer_publication_completion import interpretation


class RemoteFinalizationProofTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = fixtures.HealthCloseoutAccountingTests()
        self.owner.addCleanup = self.addCleanup
        self.owner.addAsyncCleanup = self.addAsyncCleanup
        await self.owner.asyncSetUp()
        self.f = self.owner.f
        self.controller = self.f.controller

    async def fail_session_with_unfinished_science(self):
        callback, message = self.owner.delivery("experiment-failure")
        body = json.loads(message.data)
        body["payload"]["interpretation_label"] = "experiment_failure"
        message.data = json.dumps(body).encode()
        decision = self.controller.process_health_interpretation(RuntimeEvidenceMessage.from_dict(body))
        second = self.controller.process_health_interpretation(replace(interpretation("second-failure"),
            interpretation_label="experiment_failure"))
        session = self.controller.process_health_interpretation(replace(interpretation("session-failure"),
            interpretation_label="session_failure"))
        with patch.object(self.f.node, "stop_runtime", side_effect=OSError("cleanup unavailable")):
            result = await self.controller.execute_launched_controller_action_decision(session)
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertTrue(any(m.lifecycle_state == "open" for m in self.f.node.local_storage_manager.manifests))
        return callback, message, decision, second

    async def test_terminal_event_cannot_confirm_failed_remote_scientific_finalization(self):
        callback, message, decision, second = await self.fail_session_with_unfinished_science()
        manager = self.f.node.local_storage_manager
        with patch.object(manager, "finalize_stream", side_effect=OSError("disk unavailable")):
            for accepted in (decision, second):
                result = await self.controller.execute_launched_controller_action_decision(accepted)
                self.assertFalse(result.succeeded, result.details)
                self.assertFalse((result.details or {}).get("health_processing_confirmed", False))
            with self.assertRaises(RuntimeError):
                await callback(message)
        message.ack.assert_not_awaited()
        self.assertTrue(any(m.lifecycle_state == "open" for m in manager.manifests))
        await callback(message)
        message.ack.assert_awaited_once()
        with patch.object(manager, "flush", wraps=manager.flush) as flush:
            result = await self.controller.execute_launched_controller_action_decision(second)
            self.assertTrue(result.succeeded, result.error)
            flush.assert_not_called()
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in manager.manifests))
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertIsNotNone(self.controller.get_status()["session_id"])
        self.assertFalse(self.controller._runtime_cleanup_confirmed)
        self.assertEqual([e.event_type for e in self.controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])

    async def test_missing_cancelled_or_lost_finalization_response_never_authorizes_ack(self):
        callback, message, _, _ = await self.fail_session_with_unfinished_science()
        request = self.f.communication.request_runtime_command
        for mode in ("missing", "cancelled", "stalled", "lost"):
            with self.subTest(mode=mode):
                async def unavailable(target, operation, *args, **kwargs):
                    if operation == "finalize_experiment_scientific_outputs":
                        if mode == "cancelled":
                            raise asyncio.CancelledError
                        if mode == "stalled":
                            await asyncio.Event().wait()
                        if mode == "lost":
                            await request(target, operation, *args, **kwargs)
                        return None
                    return await request(target, operation, *args, **kwargs)
                with patch.object(self.f.communication, "request_runtime_command", new=unavailable):
                    with self.assertRaises(asyncio.CancelledError if mode == "cancelled" else RuntimeError):
                        await callback(message)
                message.ack.assert_not_awaited()
                self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))
        await callback(message)
        message.ack.assert_awaited_once()

    async def test_local_only_execution_rejects_missing_owner_before_mutation(self):
        decision = self.controller.process_health_interpretation(replace(interpretation("local-misroute"),
            interpretation_label="experiment_failure"))
        before = self.controller.get_status()
        result = self.controller.stop_experiment("experiment")
        self.assertFalse(result.succeeded)
        result = self.controller.execute_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        after = self.controller.get_status()
        self.assertEqual(before["experiment_lifecycle_evidence"], after["experiment_lifecycle_evidence"])
        self.assertEqual(after["active_experiment_id"], "experiment")
        self.assertEqual(after["session_state"], "running")
        self.assertTrue(self.f.node.experiment_runtime_active)
        self.assertTrue(any(m.lifecycle_state == "open" for m in self.f.node.local_storage_manager.manifests))
        result = await self.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)

    async def test_readiness_response_cannot_confirm_remote_finalization(self):
        callback, message, _, _ = await self.fail_session_with_unfinished_science()
        publish = self.f.broker.publish

        async def redirect(subject, data, stream):
            body = json.loads(data)
            if stream == "LAB_COMMANDS" and body.get("command_type") == "finalize_experiment_scientific_outputs":
                body["command_type"] = "check_readiness"
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                data = json.dumps(body).encode()
            return await publish(subject, data, stream)

        with patch.object(self.f.broker, "publish", new=redirect):
            with self.assertRaises(RuntimeError):
                await callback(message)
        message.ack.assert_not_awaited()
        self.assertTrue(any(m.lifecycle_state == "open" for m in self.f.node.local_storage_manager.manifests))
        await callback(message)
        message.ack.assert_awaited_once()
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))

    async def test_rechecking_old_remote_finalization_preserves_later_experiment(self):
        decisions = [self.controller.process_health_interpretation(replace(interpretation(identity),
            interpretation_label="experiment_failure")) for identity in ("old-first", "old-second")]
        self.assertTrue((await self.controller.execute_launched_controller_action_decision(decisions[0])).succeeded)
        old = {m.local_storage_path: Path(m.local_storage_path).read_bytes()
               for m in self.f.node.local_storage_manager.manifests}
        await self.f.experiment("later")
        for decision in decisions:
            result = await self.controller.execute_launched_controller_action_decision(decision)
            self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "later")
        self.assertEqual(self.f.node._active_experiment_runtime_context.experiment_id, "later")
        self.assertEqual(old, {path: Path(path).read_bytes() for path in old})
        self.assertTrue(any(m.experiment_id == "later" and m.lifecycle_state == "open"
                            for m in self.f.node.local_storage_manager.manifests))

    async def test_owner_confirms_experiment_with_no_selected_scientific_products(self):
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        result = await self.controller.start_launched_experiment("empty",
            configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(result.succeeded, result.error)
        decision = self.controller.process_health_interpretation(replace(interpretation("empty-failure"),
            experiment_id="empty", interpretation_label="experiment_failure"))
        result = await self.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertFalse(self.f.node.experiment_runtime_active)
        self.assertFalse(any(m.experiment_id == "empty" for m in self.f.node.local_storage_manager.manifests))
