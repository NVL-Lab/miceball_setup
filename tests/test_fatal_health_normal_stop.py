"""Fatal health accounting while the existing Normal Stop owns remote cleanup."""

import asyncio
import json
from dataclasses import replace
import unittest
from unittest.mock import patch

from lab_sync_acquisition import RuntimeEvidenceMessage
from lab_sync_acquisition.nats_communication import DurablePublicationError
from tests import test_distributed_session_closeout as closeout_fixtures
from tests.test_producer_publication_completion import interpretation


class FatalHealthNormalStopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.closeout = closeout_fixtures.DistributedSessionCloseoutTests()
        self.closeout.addCleanup = self.addCleanup
        self.closeout.addAsyncCleanup = self.addAsyncCleanup
        await self.closeout.asyncSetUp()
        await self.closeout.running()
        self.f = self.closeout.fixture
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()
        self.stopping = None
        self.missing_stop = False
        self.pause_operation = "stop_runtime"
        self.pause_component = "acquisition_node"
        original = self.f.communication.request_runtime_command

        async def pause(participant, operation, *args, **kwargs):
            if operation == self.pause_operation and participant.component_type == self.pause_component:
                self.entered.set()
                await self.resume.wait()
                if self.missing_stop:
                    return None
            return await original(participant, operation, *args, **kwargs)

        self.patch = patch.object(self.f.communication, "request_runtime_command", new=pause)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addAsyncCleanup(self.finish_stop)
        health = replace(interpretation("fatal-overlap"), interpretation_label="session_failure")
        self.evidence = RuntimeEvidenceMessage("fatal-overlap", self.f.sid,
            "health_interpretation", "node", health.to_dict(), True)

    async def finish_stop(self):
        self.resume.set()
        if self.stopping is not None:
            await asyncio.wait_for(self.stopping, 3)

    async def begin_stop(self):
        self.stopping = asyncio.create_task(self.closeout.stop())
        await asyncio.wait_for(self.entered.wait(), 2)

    async def fatal(self):
        await self.f.handler.publish_evidence(self.evidence)

    def node_stops(self):
        return [c for c in self.f.broker.commands
                if c["target_id"] == "node" and c["command_type"] == "stop_runtime"]

    async def reject_wrong_synchronization_reply(self, *, fatal):
        original = self.f.broker.publish

        async def redirect(subject, data, stream):
            command = json.loads(data)
            if (stream == "LAB_COMMANDS" and command["command_type"] == "stop_runtime"
                    and command["target_id"] == "sync"):
                command["command_type"] = "check_readiness"
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                data = json.dumps(command).encode()
            return await original(subject, data, stream)

        with patch.object(self.f.sync, "complete_session_evidence_publication",
                          wraps=self.f.sync.complete_session_evidence_publication) as publication:
            with patch.object(self.f.broker, "publish", new=redirect):
                await self.begin_stop()
                if fatal:
                    await self.fatal()
                self.resume.set()
                result = await self.stopping
            publication.assert_not_awaited()
            self.assertFalse(result.succeeded)
            self.assertFalse(result.details["preservation_confirmed"])
            self.assertFalse(self.f.controller._acquisition_marker_confirmed)
            self.assertIsNone(self.f.controller._acquisition_marker)
            self.assertIsNotNone(self.f.controller._session)
            self.assertEqual(self.f.controller.get_status()["session_state"], "failed" if fatal else "stopping")
            self.assertEqual(len(self.node_stops()), 1)
            self.assertFalse(any(c["command_type"] == "kill" for c in self.f.broker.commands))
            with patch.object(self.closeout.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
                retried = await self.closeout.stop()
            publication.assert_awaited_once()
            self.assertTrue(self.f.controller._acquisition_marker_confirmed)
            self.assertFalse(retried.succeeded)
            self.assertFalse(retried.details["preservation_confirmed"])
            self.assertEqual(len(self.node_stops()), 1)

    async def test_wrong_synchronization_operation_cannot_confirm_normal_stop(self):
        await self.reject_wrong_synchronization_reply(fatal=False)

    async def test_wrong_synchronization_operation_cannot_confirm_fatal_closeout(self):
        await self.reject_wrong_synchronization_reply(fatal=True)

    async def test_contradictory_synchronization_results_prevent_marker(self):
        original = self.f.broker.publish

        async def conflict(subject, data, stream):
            acknowledgment = await original(subject, data, stream)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".sync.stop_runtime"):
                reply = json.loads(data)
                reply.update(result_id="conflicting-sync-result", status="failed", success=False,
                             reason="Contradictory synchronization result")
                await original(subject, json.dumps(reply).encode(), stream)
            return acknowledgment

        with patch.object(self.f.broker, "publish", new=conflict):
            await self.begin_stop()
            self.resume.set()
            result = await self.stopping
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertFalse(self.f.controller._acquisition_marker_confirmed)
        self.assertIsNotNone(self.f.controller._session)

    async def test_wrong_node_operation_cannot_authorize_reservation_release(self):
        original = self.f.broker.publish

        async def redirect(subject, data, stream):
            command = json.loads(data)
            if (stream == "LAB_COMMANDS" and command["command_type"] == "stop_runtime"
                    and command["target_id"] == "node"):
                command["command_type"] = "check_readiness"
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                data = json.dumps(command).encode()
            return await original(subject, data, stream)

        with patch.object(self.f.broker, "publish", new=redirect):
            await self.begin_stop()
            self.resume.set()
            result = await self.stopping
        self.assertFalse(result.succeeded)
        self.assertFalse(self.f.controller._runtime_cleanup_confirmed)
        self.assertFalse(self.f.controller._acquisition_marker_confirmed)
        self.assertTrue(self.f.node.status()["is_running"])
        self.assertIsNotNone(self.f.controller._session)
        self.assertFalse(any(c["command_type"] == "release_reservation" for c in self.f.broker.commands))

    async def test_durable_fatal_accounting_does_not_compete_with_cleanup(self):
        await self.begin_stop()
        await self.fatal()
        self.assertTrue(self.f.node.status()["is_running"])
        self.assertEqual(self.node_stops(), [])
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_fail")
        self.assertTrue(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))
        decision, = self.f.controller.controller_action_decision_evidence
        with self.f.ingestor.durable_runtime_evidence_history_guard(
                self.f.sid, self.f.ingestor.recovery_journal_path, (decision,)) as confirmed:
            self.assertTrue(confirmed)
        with patch.object(self.closeout.storage, "write_acquisition_stage", side_effect=OSError("injected archival failure")):
            self.resume.set()
            result = await self.stopping
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertEqual(len(self.node_stops()), 1)
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertIsNotNone(self.f.controller._session)

    async def test_failed_decision_publication_is_not_marked_processed(self):
        await self.begin_stop()
        with patch.object(self.f.communication, "publish_evidence", side_effect=ConnectionError("publication unavailable")):
            with self.assertRaises(DurablePublicationError):
                await self.fatal()
        self.assertFalse(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        await self.fatal()
        self.assertTrue(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))
        self.assertEqual(len(self.f.controller.controller_action_decisions), 1)

    async def test_missing_acceptance_confirmation_is_not_marked_processed(self):
        await self.begin_stop()
        with patch.object(self.f.communication, "request_persistence_command", return_value=None):
            with self.assertRaises(DurablePublicationError):
                await self.fatal()
        self.assertFalse(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))
        await self.fatal()
        self.assertTrue(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))

    async def test_missing_cleanup_keeps_failed_outcome_and_binding(self):
        self.missing_stop = True
        await self.begin_stop()
        await self.fatal()
        self.resume.set()
        result = await self.stopping
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertTrue(self.f.node.status()["is_running"])
        self.assertFalse(self.f.controller._runtime_cleanup_confirmed)
        self.assertIsNotNone(self.f.controller._session)

    async def test_cancelled_cleanup_retains_fatal_consequence_for_explicit_retry(self):
        await self.begin_stop()
        await self.fatal()
        self.stopping.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.stopping
        self.stopping = None
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertTrue(self.f.node.status()["is_running"])
        self.assertEqual(self.node_stops(), [])
        with patch.object(self.closeout.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            self.resume.set()
            result = await self.closeout.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(len(self.node_stops()), 1)
        self.assertFalse(self.f.node.status()["is_running"])
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")

    async def test_timing_failure_uses_the_same_normal_stop_owner(self):
        await self.begin_stop()
        timing = RuntimeEvidenceMessage("fatal-timing-overlap", self.f.sid,
            "timing_quality_interpretation", "node", {
                "interpretation_label": "session_failure", "experiment_id": "experiment"}, True)
        decision = self.f.controller.process_timing_quality_interpretation(timing)
        result = await self.f.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["durable_acceptance_confirmed"])
        self.assertEqual(self.node_stops(), [])
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")

    async def test_fatal_during_experiment_end_time_does_not_record_stale_stop(self):
        self.pause_operation = None
        original = self.f.communication.request_runtime_command

        async def pause_time(participant, operation, *args, **kwargs):
            if operation == "read_session_time":
                self.entered.set()
                await self.resume.wait()
            return await original(participant, operation, *args, **kwargs)

        with patch.object(self.f.communication, "request_runtime_command", new=pause_time):
            await self.begin_stop()
            await self.fatal()
            with patch.object(self.closeout.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
                self.resume.set()
                result = await self.stopping
        self.assertFalse(result.succeeded)
        self.assertTrue(self.f.controller._runtime_cleanup_confirmed)
        self.assertEqual(len(self.node_stops()), 1)
        endings = [item.event_type for item in self.f.controller._session.experiment_lifecycle_evidence
                   if item.event_type in {"experiment_stop", "experiment_fail"}]
        self.assertEqual(endings, ["experiment_fail"])

    async def test_verified_closeout_preserves_failed_terminal_outcome_and_retries(self):
        await self.begin_stop()
        await self.fatal()
        self.resume.set()
        result = await self.stopping
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["session_state"], "failed")
        self.assertTrue(result.details["preservation_confirmed"])
        preserved = self.f.ingestor.read_session_closeout(self.f.sid)
        self.assertEqual(preserved["session_record"]["final_session_status"]["state"], "failed")
        self.assertTrue(all(message.to_dict() in preserved["runtime_evidence"]
                            for message in self.f.controller.controller_action_decision_evidence))
        before = self.closeout.archive()
        self.assertTrue((await self.closeout.stop()).succeeded)
        self.assertEqual(self.closeout.archive(), before)
        self.assertEqual(len(self.node_stops()), 1)

    async def test_normal_stop_without_fatal_decision_still_completes(self):
        await self.begin_stop()
        self.resume.set()
        result = await self.stopping
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["session_state"], "completed")
        self.assertEqual(len(self.node_stops()), 1)
