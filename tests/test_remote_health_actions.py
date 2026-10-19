"""Health consequences against independently owned nodes through brokered commands."""

import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import ControllerActionDecision, RuntimeEvidenceMessage
from lab_sync_acquisition.nats_communication import DurablePublicationError
from tests import test_distributed_synchronization as distributed
from tests.test_producer_publication_completion import interpretation


class RemoteHealthActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = distributed.DistributedSynchronizationTests()
        self.f.addCleanup = self.addCleanup
        self.f.addAsyncCleanup = self.addAsyncCleanup
        await self.f.asyncSetUp()
        await self.f.start()
        await self.f.experiment()

    def decision(self, action, experiment="experiment"):
        return ControllerActionDecision("observation", self.f.sid, experiment,
            "source", "policy", "experiment_failure", action, None)

    async def test_non_mutating_actions_do_not_command_nodes(self):
        before = list(self.f.broker.commands)
        for action in ("record_only", "record_warning", "record_recoverable_failure", "operator_required"):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision(action))
            self.assertTrue(result.succeeded, result.error)
            self.assertFalse(result.details["lifecycle_mutated"])
        self.assertEqual(before, self.f.broker.commands)
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_remote_experiment_failure_finalizes_without_stopping_session(self):
        self.assertIsNone(self.f.controller._acquisition_node)
        await self.f.request(self.f.participants[-1], "run_one_iteration")
        result = await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail"))
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["event_type"], "experiment_fail")
        self.assertEqual(self.f.controller.get_status()["session_state"], "running")
        self.assertIsNone(self.f.controller.get_status()["active_experiment_id"])
        self.assertFalse(self.f.node.experiment_runtime_active)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))
        await self.f.experiment("next")

    async def test_missing_finalization_reply_is_unconfirmed_and_retryable(self):
        original = self.f.communication.request_runtime_command

        async def lost(target, operation, *args, **kwargs):
            result = await original(target, operation, *args, **kwargs)
            return None if operation == "finalize_experiment_scientific_outputs" else result

        decision = self.decision("experiment_fail")
        with patch.object(self.f.communication, "request_runtime_command", new=lost):
            result = await self.f.controller.execute_launched_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertTrue(result.details["outcome_unconfirmed"])
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "experiment")
        result = await self.f.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(len(self.f.controller.controller_action_decisions), 1)

    async def test_remote_session_failure_retains_preservation_and_binding(self):
        local = self.f.node.local_storage_manager
        result = await self.f.controller.execute_launched_controller_action_decision(self.decision("session_fail"))
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["session_state"], "failed")
        self.assertTrue(result.details["cleanup_confirmed"])
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertTrue(result.details["binding_retained"])
        self.assertFalse(self.f.node.status()["is_running"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in local.manifests))
        self.assertEqual(self.f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_fail")

    async def test_failed_session_stop_does_not_confirm_cleanup(self):
        original = self.f.communication.request_runtime_command

        async def unavailable(target, operation, *args, **kwargs):
            if operation == "stop_runtime" and target.component_type == "acquisition_node":
                return None
            return await original(target, operation, *args, **kwargs)

        with patch.object(self.f.communication, "request_runtime_command", new=unavailable):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("session_fail"))
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertTrue(self.f.node.status()["is_running"])

    async def test_health_subscription_executes_once_and_rejects_conflicting_delivery(self):
        health = replace(interpretation(), interpretation_label="experiment_failure")
        message = RuntimeEvidenceMessage("health", self.f.sid, "health_interpretation", "node", health.to_dict(), True)
        await self.f.handler.publish_evidence(message)
        count = len(self.f.controller.controller_action_decisions)
        await self.f.handler.publish_evidence(message)
        self.assertEqual(len(self.f.controller.controller_action_decisions), count)
        self.assertEqual(self.f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_fail")
        with self.assertRaises(DurablePublicationError):
            await self.f.handler.publish_evidence(replace(message, payload={**health.to_dict(), "required": False}))

    async def test_timing_interpretation_uses_same_failure_executor(self):
        message = RuntimeEvidenceMessage("timing-health", self.f.sid, "timing_quality_interpretation", "node",
            {"experiment_id": "experiment", "interpretation_label": "experiment_failure"}, True)
        await self.f.handler.publish_evidence(message)
        self.assertEqual(self.f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_fail")
        self.assertFalse(self.f.node.experiment_runtime_active)

    async def test_cancelled_remote_action_never_claims_completion(self):
        async def interrupted(*args, **kwargs):
            raise asyncio.CancelledError

        with patch.object(self.f.communication, "request_runtime_command", new=interrupted):
            with self.assertRaises(asyncio.CancelledError):
                await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail"))
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "experiment")
        self.assertFalse(self.f.controller.get_status()["last_command"].succeeded)

    async def test_wrong_experiment_cannot_fail_current_recording(self):
        result = await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail", "old"))
        self.assertFalse(result.succeeded)
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_delayed_session_health_cannot_fail_a_successive_experiment(self):
        await self.f.controller.stop_launched_experiment("experiment")
        await self.f.experiment("next")
        result = await self.f.controller.execute_launched_controller_action_decision(self.decision("session_fail"))
        self.assertFalse(result.succeeded)
        self.assertEqual(self.f.controller.get_status()["session_state"], "running")
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "next")

    async def test_stalled_command_publication_is_bounded_without_false_finalization(self):
        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        self.f.controller._launch_result_window_s = 0.01
        with patch.object(self.f.communication, "request_runtime_command", new=stalled):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail"))
        self.assertFalse(result.succeeded)
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_mismatched_finalization_confirmation_is_not_success(self):
        original = self.f.communication.request_runtime_command

        async def mismatched(target, operation, *args, **kwargs):
            result = await original(target, operation, *args, **kwargs)
            if operation == "finalize_experiment_scientific_outputs":
                return replace(result, payload={**result.payload, "experiment_id": "different"})
            return result

        with patch.object(self.f.communication, "request_runtime_command", new=mismatched):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail"))
        self.assertFalse(result.succeeded)
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "experiment")

    async def test_owner_rejection_does_not_resolve_experiment(self):
        with patch.object(self.f.node, "finalize_experiment_scientific_outputs",
                          side_effect=RuntimeError("local storage unavailable")):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("experiment_fail"))
        self.assertFalse(result.succeeded)
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "experiment")
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_timing_operator_required_does_not_mutate_lifecycle(self):
        message = RuntimeEvidenceMessage("timing-operator", self.f.sid, "timing_quality_interpretation", "node",
            {"experiment_id": "experiment", "interpretation_label": "operator_required"}, True)
        await self.f.handler.publish_evidence(message)
        self.assertTrue(self.f.node.experiment_runtime_active)
        self.assertFalse(self.f.controller.get_status()["last_command"].details["lifecycle_mutated"])

    async def test_readiness_reply_cannot_confirm_remote_session_cleanup(self):
        original = self.f.broker.publish

        async def redirected(subject, data, stream):
            command = json.loads(data)
            if (stream == "LAB_COMMANDS" and command["command_type"] == "stop_runtime"
                    and command["target_id"] == "node"):
                command["command_type"] = "check_readiness"
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                data = json.dumps(command).encode()
            return await original(subject, data, stream)

        self.f.controller._launch_result_window_s = 0.05
        with patch.object(self.f.broker, "publish", new=redirected):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("session_fail"))
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertTrue(result.details["binding_retained"])
        self.assertTrue(self.f.node.status()["is_running"])
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_contradictory_stop_resolutions_prevent_cleanup_confirmation(self):
        original = self.f.broker.publish

        async def contradictory(subject, data, stream):
            acknowledgment = await original(subject, data, stream)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                result = json.loads(data)
                result.update(result_id="contradictory-result", status="failed", success=False,
                              reason="Contradictory owner resolution")
                await original(subject, json.dumps(result).encode(), stream)
            return acknowledgment

        local = self.f.node.local_storage_manager
        with patch.object(self.f.broker, "publish", new=contradictory):
            result = await self.f.controller.execute_launched_controller_action_decision(self.decision("session_fail"))
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertTrue(result.details["binding_retained"])
        self.assertFalse(self.f.node.status()["is_running"])
        self.assertTrue(all(manifest.lifecycle_state == "finalized" for manifest in local.manifests))
