"""Decision accounting remains independent of Session closeout ownership."""

import asyncio
from dataclasses import replace
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import ControllerActionDecision, ExperimentConfiguration, RuntimeEvidenceMessage
from tests import test_controller_action_decision as local_fixtures
from tests import test_closeout_attempt_ownership as attempt_fixtures
from tests.test_producer_publication_completion import interpretation


class LocalDecisionAccountingTests(unittest.TestCase):
    def test_two_accepted_fatal_decisions_have_one_terminal_consequence(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = local_fixtures.ControllerActionDecisionTests()
            controller, node, _, _ = fixture._running_controller(Path(directory))
            self.assertTrue(controller.start_experiment("experiment-001",
                configuration=ExperimentConfiguration(60, {}, 1000000)).succeeded)
            decisions = [controller.process_health_interpretation(
                fixture._evidence(i, "session_failure")) for i in (1, 2)]
            for decision in decisions:
                result = controller.execute_controller_action_decision(decision)
                self.assertTrue(result.succeeded, result.error)
                self.assertTrue(result.details["health_processing_confirmed"])
            self.assertEqual(controller.get_status()["session_state"], "failed")
            events = controller.get_status()["experiment_lifecycle_evidence"]
            self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
            self.assertEqual(len(controller.controller_action_decision_evidence), 2)
            for message in controller.controller_action_decision_evidence:
                self.assertTrue(controller._ingestor.has_durable_runtime_evidence(message))
            node.local_storage_manager.cleanup()


class HealthCloseoutAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fixtures = attempt_fixtures.InterruptedNormalStopTests()
        fixtures.addCleanup = self.addCleanup
        fixtures.addAsyncCleanup = self.addAsyncCleanup
        # Reuse the existing verified-handoff fixture. Its pre-existing JSON
        # exercises production disk readback, not Windows hard-link promotion.
        self.workflow = await fixtures.workflow()
        self.f = self.workflow.fixture

    def fatal(self, identity):
        return ControllerActionDecision(identity, self.f.sid, "experiment", "source", "policy",
                                        "session_failure", "session_fail", None)

    def delivery(self, identity):
        import json
        evidence = RuntimeEvidenceMessage(identity, self.f.sid, "health_interpretation", "node",
            replace(interpretation(identity), interpretation_label="session_failure").to_dict(), True)
        message = SimpleNamespace(subject=f"messages.{self.f.sid}.evidence.acquisition_node.node.health_interpretation",
                                  data=json.dumps(evidence.to_dict()).encode(), ack=AsyncMock())
        callback = next(s.callback for s in self.f.broker.subscriptions
            if "subscribe_health_interpretation_evidence" in s.callback.__qualname__)
        return callback, message

    async def test_multiple_preaccepted_decisions_survive_experiment_termination(self):
        controller = self.f.controller
        decisions = [controller.process_health_interpretation(replace(interpretation(identity),
            interpretation_label="session_failure")) for identity in ("first", "second")]
        for decision in decisions:
            result = await controller.execute_launched_controller_action_decision(decision)
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["health_processing_confirmed"])
        self.assertEqual(controller.get_status()["session_state"], "failed")
        self.assertEqual([e.event_type for e in controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])
        self.assertEqual(len([c for c in self.f.broker.commands
            if c["target_id"] == "node" and c["command_type"] == "stop_runtime"]), 1)
        rejected = await controller.execute_launched_controller_action_decision(self.fatal("new-late"))
        self.assertFalse(rejected.succeeded)
        self.assertEqual(len(controller.controller_action_decision_evidence), 2)

    async def test_preaccepted_fatal_does_not_displace_first_admitted_normal_stop(self):
        local = self.f.node.local_storage_manager
        decision = self.f.controller.process_health_interpretation(replace(interpretation("queued"),
            interpretation_label="session_failure"))
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.f.communication.request_runtime_command

        async def pause(participant, operation, *args, **kwargs):
            if operation == "stop_runtime" and participant.component_type == "acquisition_node":
                entered.set()
                await resume.wait()
            return await original(participant, operation, *args, **kwargs)

        with patch.object(self.f.communication, "request_runtime_command", new=pause):
            closing = asyncio.create_task(self.workflow.stop())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                result = await self.f.controller.execute_launched_controller_action_decision(decision)
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(result.details["cleanup_owner"], "normal_stop")
                self.assertNotEqual(self.f.controller.get_status()["session_state"], "failed")
            finally:
                resume.set()
                stopped = await closing
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertEqual(self.f.controller.get_status()["session_state"], "completed")
        decision_message, = self.f.controller.controller_action_decision_evidence
        self.assertIn(decision_message.to_dict(), stopped.details["runtime_evidence"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in local.manifests))

    async def test_fatal_closeout_cannot_be_displaced_by_normal_stop(self):
        result = await self.f.controller.execute_launched_controller_action_decision(self.fatal("fatal-first"))
        self.assertTrue(result.succeeded, result.error)
        stopped = await self.workflow.stop()
        self.assertFalse(stopped.succeeded)
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")

    async def test_late_failed_readback_does_not_modify_replacement_session(self):
        controller = self.f.controller
        old = controller._session
        before = controller.get_status()["last_command"]
        history = tuple(controller._command_results)
        original = self.f.communication.request_persistence_command

        async def late(*args, **kwargs):
            result = await original(*args, **kwargs)
            controller._session = replace_session = type(old)("replacement", old.configuration)
            self.replacement = replace_session
            raise OSError("late original-Session readback failure")

        with patch.object(self.f.communication, "request_persistence_command", new=late):
            result = await controller.execute_launched_controller_action_decision(self.fatal("late"))
        self.assertFalse(result.succeeded)
        self.assertIs(controller.get_status()["last_command"], before)
        self.assertEqual(tuple(controller._command_results), history)
        self.assertEqual(self.replacement.current_state.value, "created")
        controller._session = old

    async def test_cutoff_rejects_new_but_preserves_preaccepted_decisions(self):
        controller = self.f.controller
        decision = controller.process_health_interpretation(replace(interpretation("before-cutoff"),
            interpretation_label="session_failure"))
        result = await self.workflow.stop()
        self.assertFalse(result.succeeded)
        self.assertIn("require durable accounting", result.error)
        with self.assertRaises(RuntimeError):
            controller.process_health_interpretation(replace(interpretation("after-cutoff"),
                interpretation_label="session_failure"))
        accounted = await controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(accounted.succeeded, accounted.error)
        with patch.object(self.workflow.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            result = await self.workflow.stop()
        self.assertFalse(result.succeeded)
        self.assertIn("archive unavailable", result.error)
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertTrue(controller._acquisition_marker_confirmed)
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)

    async def test_cutoff_rejects_new_delivery_but_allows_verified_original_redelivery(self):
        callback, original = self.delivery("accepted-before-cutoff")
        controller = self.f.controller
        # Accept through the public interpretation API before closeout; callback
        # delivery is delayed until after cutoff and Experiment termination.
        controller.process_health_interpretation(replace(interpretation("accepted-before-cutoff"),
            interpretation_label="session_failure"))
        stopped = await self.workflow.stop()
        self.assertFalse(stopped.succeeded)
        self.assertIn("require durable accounting", stopped.error)
        _, late = self.delivery("new-after-cutoff")
        with self.assertRaises(RuntimeError):
            await callback(late)
        late.ack.assert_not_awaited()
        await callback(original)
        original.ack.assert_awaited_once()
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)
        self.assertEqual(controller.get_status()["session_state"], "stopping")

    async def test_pending_duplicate_cancellation_and_redelivery_keep_one_cleanup(self):
        callback, message = self.delivery("pending-fatal")
        entered, resume = asyncio.Event(), asyncio.Event()
        request = self.f.communication.request_persistence_command

        async def readback(*args, **kwargs):
            entered.set()
            await resume.wait()
            return await request(*args, **kwargs)

        with patch.object(self.f.communication, "request_persistence_command", new=readback):
            processing = asyncio.create_task(callback(message))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with self.assertRaises(RuntimeError):
                    await callback(message)
                message.ack.assert_not_awaited()
                processing.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await processing
            finally:
                resume.set()
                await asyncio.gather(processing, return_exceptions=True)
        message.ack.assert_not_awaited()
        await callback(message)
        message.ack.assert_awaited_once()
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertEqual(len([c for c in self.f.broker.commands
            if c["target_id"] == "node" and c["command_type"] == "stop_runtime"]), 1)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))

    async def test_late_success_and_cancellation_leave_replacement_diagnostics_unchanged(self):
        controller = self.f.controller
        old = controller._session
        decision = self.fatal("original-operation")
        original = self.f.communication.request_persistence_command
        for cancellation in (False, True):
            with self.subTest(cancellation=cancellation):
                before = controller.get_status()["last_command"]
                history = tuple(controller._command_results)

                async def replaced(*args, **kwargs):
                    result = await original(*args, **kwargs)
                    controller._session = type(old)("replacement", old.configuration)
                    if cancellation:
                        raise asyncio.CancelledError
                    return result

                with patch.object(self.f.communication, "request_persistence_command", new=replaced):
                    if cancellation:
                        with self.assertRaises(asyncio.CancelledError):
                            await controller.execute_launched_controller_action_decision(decision)
                    else:
                        result = await controller.execute_launched_controller_action_decision(decision)
                        self.assertFalse(result.succeeded)
                self.assertIs(controller.get_status()["last_command"], before)
                self.assertEqual(tuple(controller._command_results), history)
                self.assertEqual(controller.get_status()["session_state"], "created")
                controller._session = old
