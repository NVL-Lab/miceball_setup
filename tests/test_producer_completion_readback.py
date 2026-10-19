"""Late Stop replies cannot replace or resurrect scoped producer confirmation."""

from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nats.aio.subscription import Subscription

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
        self.during_marker = False
        self.after_durable_marker = False
        self.fatal_presented = False
        self.marker_publications = []
        self.real_callback_loop = False
        self.original_publish = self.f.broker.publish

    async def present_fatal(self):
        self.fatal_presented = True
        health = replace(interpretation("fatal-readback"), interpretation_label="session_failure")
        await self.f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-readback", self.f.sid,
            "health_interpretation", "node", health.to_dict(), True))

    async def inject(self):
        self.injected = True
        if self.fatal and not self.fatal_presented:
            await self.present_fatal()
        subject, original = self.saved
        reply = deepcopy(original)
        if self.mode == "fresh_attempt":
            retried = await self.f.communication.request_runtime_command(self.participant, "stop_runtime",
                self.f.sid, {}, 0.05, command_id=original["command_id"])
            self.assertIsNotNone(retried)
            self.assertNotEqual(retried.payload["request_nonce"], original["payload"]["request_nonce"])
            return
        if self.mode in {"nan_failure", "nan_success", "stale_nan", "unrelated_nan"}:
            reply["result_id"] = "nonfinite-resolution"
            reply["payload"]["diagnostic"] = float("nan")
            if self.mode == "nan_failure":
                reply.update(status="failed", success=False, reason="Stop failed")
            elif self.mode == "stale_nan":
                reply["payload"]["request_nonce"] = "stale-attempt"
            elif self.mode == "unrelated_nan":
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
            if self.real_callback_loop:
                await self.deliver_through_nats_loop(subject, json.dumps(reply).encode())
            else:
                await self.original_publish(subject, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")
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

    async def deliver_through_nats_loop(self, subject, data):
        callback = next(s.callback for s in self.f.broker.subscriptions if s.active
                        and s.subject == f"messages.{self.f.sid}.command_result.*.*.*")
        subscription = object.__new__(Subscription)
        subscription._cb = callback
        subscription._pending_queue = asyncio.Queue()
        subscription._pending_size = len(data)
        subscription._max_msgs = 0
        message = SimpleNamespace(subject=subject, data=data, ack=AsyncMock())
        await subscription._pending_queue.put(message)
        errors = []

        async def error_callback(error):
            errors.append(error)

        task = asyncio.create_task(subscription._wait_for_msgs(error_callback))
        try:
            await asyncio.wait_for(subscription._pending_queue.join(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(errors, [])
        message.ack.assert_awaited_once()

    async def deliver(self, subject, data, stream):
        body = json.loads(data)
        marker = stream == "LAB_EVIDENCE" and body.get("evidence_type") == "acquisition_evidence_completion"
        if marker:
            self.marker_publications.append(deepcopy(body))
        if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
            self.saved = (subject, deepcopy(body))
        if (not self.injected and not self.after_initial_readback and stream == "LAB_COMMANDS"
                and body["command_type"] == "release_reservation" and body["target_id"] == "node"):
            if self.during_marker:
                if self.fatal:
                    await self.present_fatal()
            else:
                await self.inject()
        if marker and self.during_marker and not self.after_durable_marker and not self.injected:
            await asyncio.sleep(0)
            await self.inject()
        ack = await self.original_publish(subject, data, stream)
        if marker and self.during_marker and self.after_durable_marker and not self.injected:
            self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(RuntimeEvidenceMessage.from_dict(body)))
            await self.inject()
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
        with patch.object(self.f.broker, "publish", new=self.deliver), patch.object(
                self.workflow.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
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

    async def test_valid_duplicate_during_marker_publication_is_confirmed(self):
        self.during_marker = True
        await self.closeout(confirmed=True)

    async def test_fresh_attempt_during_publication_does_not_confirm_old_admission(self):
        self.during_marker = True
        self.mode = "fresh_attempt"
        with patch.object(self.f.node, "stop_runtime", wraps=self.f.node.stop_runtime) as cleanup, \
                patch.object(self.f.broker, "publish", new=self.deliver), \
                patch.object(self.workflow.storage, "write_acquisition_stage") as write:
            result = await self.workflow.stop()
        self.assertFalse(result.succeeded)
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertFalse(self.f.controller._acquisition_marker_confirmed)
        self.assertIsNotNone(self.f.communication.session_acquisition_completion(self.participant, self.f.sid))
        self.assertEqual(self.f.controller._acquisition_marker.to_dict(), self.marker_publications[0])
        cleanup.assert_called_once()
        write.assert_not_called()

    async def test_failure_during_marker_publication_is_unconfirmed(self):
        self.during_marker = True
        self.mode = "failure"
        await self.closeout(confirmed=False)

    async def test_failure_then_success_during_marker_publication_is_unconfirmed(self):
        self.during_marker = True
        self.mode = "failure_duplicate"
        await self.closeout(confirmed=False)

    async def test_fatal_overlap_publication_failure_is_unconfirmed(self):
        self.during_marker = True
        self.fatal = True
        self.mode = "failure"
        await self.closeout(confirmed=False)

    async def test_fatal_overlap_publication_failure_then_duplicate_is_unconfirmed(self):
        self.during_marker = True
        self.fatal = True
        self.mode = "failure_duplicate"
        await self.closeout(confirmed=False)

    async def test_published_marker_and_journal_survive_invalidation_and_fresh_retry(self):
        self.during_marker = True
        self.after_durable_marker = True
        self.mode = "failure_duplicate"
        await self.explicit_retry()
        self.assertEqual(len(self.marker_publications), 2)
        self.assertEqual(self.marker_publications[0], self.marker_publications[1])
        marker = self.f.controller._acquisition_marker
        self.assertEqual(marker.to_dict(), self.marker_publications[0])
        with self.f.ingestor.durable_runtime_evidence_history_guard(
                self.f.sid, self.f.ingestor.recovery_journal_path, (marker,)) as confirmed:
            self.assertTrue(confirmed)

    async def test_cached_marker_confirmation_cannot_hide_later_invalidation(self):
        await self.closeout(confirmed=True)
        retained = self.f.controller._acquisition_marker.to_dict()
        subject, reply = self.saved
        failed = deepcopy(reply)
        failed.update(result_id="after-published-marker", status="failed", success=False, reason="Late conflict")
        await self.original_publish(subject, json.dumps(failed).encode(), "LAB_COMMAND_RESULTS")
        before = len(self.f.broker.events)
        result = await self.f.controller.publish_acquisition_evidence_completion(
            communication=self.f.communication, result_window_s=0.05)
        self.assertFalse(result.succeeded)
        self.assertFalse(self.f.controller._acquisition_marker_confirmed)
        self.assertEqual(self.f.controller._acquisition_marker.to_dict(), retained)
        self.assertEqual(len(self.f.broker.events), before)
        self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(RuntimeEvidenceMessage.from_dict(retained)))

    async def test_correlated_nan_failure_invalidates_confirmation(self):
        self.mode = "nan_failure"
        await self.closeout(confirmed=False)

    async def test_correlated_nan_success_invalidates_confirmation(self):
        self.mode = "nan_success"
        await self.closeout(confirmed=False)

    async def test_stale_nan_does_not_invalidate_current_confirmation(self):
        self.mode = "stale_nan"
        await self.closeout(confirmed=True)

    async def test_unrelated_nan_does_not_invalidate_current_confirmation(self):
        self.mode = "unrelated_nan"
        await self.closeout(confirmed=True)

    async def test_nan_failure_is_invalidated_through_real_nats_callback_loop(self):
        self.mode = "nan_failure"
        self.real_callback_loop = True
        await self.closeout(confirmed=False)
