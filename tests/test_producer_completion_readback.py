"""Late Stop replies cannot replace or resurrect scoped producer confirmation."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import RuntimeEvidenceMessage, RuntimeParticipant
from tests import test_distributed_session_closeout as closeout
from tests.test_producer_publication_completion import interpretation


class ProducerCompletionReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workflow = closeout.DistributedSessionCloseoutTests()
        self.workflow.addCleanup = self.addCleanup
        self.workflow.addAsyncCleanup = self.addAsyncCleanup
        await self.workflow.asyncSetUp()
        await self.workflow.running()
        self.f = self.workflow.fixture
        self.participant = RuntimeParticipant("acquisition_node", "node")
        self.saved = None
        self.injected = False
        self.mode = "duplicate"
        self.fatal = False
        self.after_initial_readback = False
        self.original_publish = self.f.broker.publish

    async def inject(self):
        self.injected = True
        if self.fatal:
            health = replace(interpretation("fatal-readback"), interpretation_label="session_failure")
            await self.f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-readback", self.f.sid,
                "health_interpretation", "node", health.to_dict(), True))
        subject, original = self.saved
        reply = deepcopy(original)
        if self.mode in {"failure", "failure_duplicate", "payload_conflict"}:
            if self.mode == "payload_conflict":
                reply["payload"]["unexpected_resolution"] = True
            else:
                reply.update(status="failed", success=False, reason="Conflicting Stop resolution")
            reply["result_id"] = "late-conflict"
            await self.original_publish(subject, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")
        if self.mode != "failure":
            reply = deepcopy(original)
            reply["result_id"] = "late-success"
            if self.mode == "stale_nonce":
                reply["payload"]["request_nonce"] = "another-attempt"
            elif self.mode == "wrong_operation":
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                reply["payload"]["unrelated"] = True
            await self.original_publish(subject, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")

    async def deliver(self, subject, data, stream):
        body = json.loads(data)
        if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
            self.saved = (subject, deepcopy(body))
        if (not self.injected and not self.after_initial_readback and stream == "LAB_COMMANDS"
                and body["command_type"] == "release_reservation" and body["target_id"] == "node"):
            await self.inject()
        ack = await self.original_publish(subject, data, stream)
        if (not self.injected and self.after_initial_readback and stream == "LAB_COMMAND_RESULTS"
                and subject.endswith(".sync.stop_runtime")):
            await self.inject()
        return ack

    async def closeout(self, *, confirmed):
        with patch.object(self.f.broker, "publish", new=self.deliver), patch.object(
                self.workflow.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")) as write:
            result = await self.workflow.stop()
        self.assertTrue(self.injected)
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertEqual(self.f.controller._acquisition_marker_confirmed, confirmed)
        self.assertEqual(write.call_count, int(confirmed))
        self.assertIsNotNone(self.f.controller._session)
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed" if self.fatal else "stopping")
        self.assertEqual(sum(c["command_type"] == "stop_runtime" and c["target_id"] == "node"
                             for c in self.f.broker.commands), 1)
        self.assertFalse(any(c["command_type"] == "kill" for c in self.f.broker.commands))
        completion = self.f.communication.session_acquisition_completion(self.participant, self.f.sid)
        self.assertEqual(completion is not None, confirmed)
        if completion is not None:
            self.assertEqual(completion.to_dict(), self.saved[1])
        return result

    async def test_identical_late_duplicate_keeps_confirmation(self):
        await self.closeout(confirmed=True)

    async def test_late_failure_blocks_confirmation(self):
        self.mode = "failure"
        await self.closeout(confirmed=False)

    async def test_duplicate_success_cannot_erase_received_failure(self):
        self.mode = "failure_duplicate"
        await self.closeout(confirmed=False)

    async def test_fatal_overlap_retains_failure_and_one_cleanup_owner(self):
        self.mode = "failure_duplicate"
        self.fatal = True
        await self.closeout(confirmed=False)
        self.assertTrue(await self.f.communication.confirm_session_health_processing(self.f.sid, self.f.controller))

    async def test_conflicting_success_payload_cannot_be_erased(self):
        self.mode = "payload_conflict"
        await self.closeout(confirmed=False)

    async def test_stale_nonce_cannot_replace_current_confirmation(self):
        self.mode = "stale_nonce"
        await self.closeout(confirmed=True)

    async def test_wrong_operation_cannot_replace_current_confirmation(self):
        self.mode = "wrong_operation"
        await self.closeout(confirmed=True)

    async def test_conflict_during_synchronization_wait_blocks_marker_admission(self):
        self.mode = "failure_duplicate"
        self.after_initial_readback = True
        await self.closeout(confirmed=False)

    async def explicit_retry(self):
        self.mode = "failure_duplicate"
        await self.closeout(confirmed=False)
        old_subject, old_result = self.saved
        with patch.object(self.f.node, "stop_runtime", side_effect=AssertionError("duplicate cleanup")):
            retried = await self.f.communication.request_runtime_command(self.participant, "stop_runtime",
                self.f.sid, {}, 0.05, command_id=old_result["command_id"])
        self.assertIsNotNone(retried)
        self.assertNotEqual(retried.payload["request_nonce"], old_result["payload"]["request_nonce"])
        stale = deepcopy(old_result)
        stale.update(status="failed", success=False, reason="Old attempt", result_id="old-attempt-failure")
        await self.original_publish(old_subject, json.dumps(stale).encode(), "LAB_COMMAND_RESULTS")
        self.assertEqual(self.f.communication.session_acquisition_completion(self.participant, self.f.sid), retried)
        with patch.object(self.workflow.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            resumed = await self.workflow.stop()
        self.assertTrue(self.f.controller._acquisition_marker_confirmed)
        self.assertFalse(resumed.succeeded)
        self.assertFalse(resumed.details["preservation_confirmed"])
        self.assertIsNotNone(self.f.controller._session)
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed" if self.fatal else "stopping")

    async def test_explicit_fresh_retry_reuses_owner_outcome_without_cleanup(self):
        await self.explicit_retry()

    async def test_explicit_fresh_retry_preserves_fatal_outcome(self):
        self.fatal = True
        await self.explicit_retry()
