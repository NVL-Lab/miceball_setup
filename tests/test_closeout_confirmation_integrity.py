"""Scoped owner proof remains authoritative throughout active Session closeout."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nats.aio.subscription import Subscription

from lab_sync_acquisition import NatsControllerCommunication, RuntimeEvidenceMessage, RuntimeParticipant
from tests import test_distributed_session_closeout as closeout
from tests import test_normal_stop as local_closeout
from tests.test_producer_publication_completion import interpretation
from tests.test_session_launch import _Boundary, _Broker


async def _deliver_result(callback, subject, data):
    """Use nats-py's callback dispatch without real sockets or a live broker."""
    subscription = object.__new__(Subscription)
    subscription._cb = callback
    subscription._pending_queue = asyncio.Queue()
    subscription._pending_size = len(data)
    subscription._max_msgs = 0
    ack = AsyncMock()
    await subscription._pending_queue.put(SimpleNamespace(data=data, subject=subject, ack=ack))
    errors = []

    async def error_callback(error):
        errors.append(error)

    task = asyncio.create_task(subscription._wait_for_msgs(error_callback))
    try:
        await asyncio.wait_for(subscription._pending_queue.join(), 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return errors, ack.await_count


class CloseoutConfirmationIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, boundary, *, fatal=False, mode="failure", kill=False, cancel=False):
        workflow = closeout.DistributedSessionCloseoutTests()
        workflow.addCleanup = self.addCleanup
        workflow.addAsyncCleanup = self.addAsyncCleanup
        await workflow.asyncSetUp()
        await workflow.running()
        f = workflow.fixture
        participant = RuntimeParticipant("acquisition_node", "node")
        publish = f.broker.publish
        request = f.communication.request_persistence_command
        saved = {}
        injected = False
        cancelled = False
        markers = []

        async def invalidate():
            nonlocal injected
            if injected:
                return
            injected = True
            if mode == "superseding":
                self.assertIsNotNone(await f.communication.request_runtime_command(participant,
                    "stop_runtime", f.sid, {}, 0.05, command_id=saved["body"]["command_id"]))
                return
            body = deepcopy(saved["body"])
            body["result_id"] += "-late"
            if mode == "payload":
                body["payload"]["changed_resolution"] = True
            elif mode == "malformed":
                body.pop("reason")
            elif mode != "duplicate":
                body.update(status="failed", success=False, reason="Conflicting owner resolution")
            if mode == "malformed":
                callback = next(s.callback for s in f.broker.subscriptions if s.active
                    and s.subject == f"messages.{f.sid}.command_result.*.*.*")
                errors, acknowledgments = await _deliver_result(callback, saved["subject"], json.dumps(body).encode())
                self.assertEqual(errors, [])
                self.assertEqual(acknowledgments, 1)
            else:
                await publish(saved["subject"], json.dumps(body).encode(), "LAB_COMMAND_RESULTS")
            duplicate = deepcopy(saved["body"])
            duplicate["result_id"] += "-duplicate"
            await publish(saved["subject"], json.dumps(duplicate).encode(), "LAB_COMMAND_RESULTS")

        async def wire(subject, data, stream):
            body = json.loads(data)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                saved.update(subject=subject, body=deepcopy(body))
            if fatal and stream == "LAB_COMMANDS" and subject.endswith(".node.release_reservation"):
                health = replace(interpretation("fatal-integrity"), interpretation_label="session_failure")
                await f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-integrity", f.sid,
                    "health_interpretation", "node", health.to_dict(), True))
            marker = body.get("evidence_type") == "acquisition_evidence_completion"
            if marker:
                markers.append(deepcopy(body))
            trigger = ((boundary == "before_marker" and stream == "LAB_COMMANDS"
                        and subject.endswith(".sync.stop_runtime"))
                or (boundary == "marker" and marker)
                or (boundary == "before_preserve" and stream == "LAB_COMMANDS"
                    and subject.endswith(".preserve_session_acquisition"))
                or (boundary == "preserve_reply" and stream == "LAB_COMMAND_RESULTS"
                    and subject.endswith(".preserve_session_acquisition"))
                or (boundary == "terminal" and stream == "LAB_COMMANDS"
                    and subject.endswith(".preserve_session_terminal_record"))
                or (boundary == "terminal_reply" and stream == "LAB_COMMAND_RESULTS"
                    and subject.endswith(".preserve_session_terminal_record")))
            if trigger:
                await invalidate()
            return await publish(subject, data, stream)

        async def readback(*args, **kwargs):
            nonlocal cancelled
            result = await request(*args, **kwargs)
            if args[1] == "preserve_session_acquisition":
                if boundary == "after_preserve":
                    await invalidate()
                if cancel and not cancelled:
                    cancelled = True
                    raise asyncio.CancelledError()
            if boundary == "final_result" and args[1] == "preserve_session_terminal_record":
                await invalidate()
            return result

        # Exercise production validation/readback of an already-published identical
        # handoff, without depending on platform-specific initial hard-link creation.
        handoff = workflow.storage.write_artifact_collection_handoff

        def existing_handoff(session_id, contents):
            path = workflow.storage._artifact_collection_handoff_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(contents, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
            return handoff(session_id, contents)

        with patch.object(f.broker, "publish", side_effect=wire), \
                patch.object(f.communication, "request_persistence_command", side_effect=readback), \
                patch.object(workflow.storage, "write_artifact_collection_handoff", side_effect=existing_handoff), \
                patch.object(f.node, "stop_runtime", wraps=f.node.stop_runtime) as physical_stop:
            if cancel:
                with self.assertRaises(asyncio.CancelledError):
                    await workflow.stop()
                self.assertEqual(f.controller.get_status()["session_state"], "stopping")
                self.assertIsNotNone(f.controller.get_status()["session_id"])
                result = await workflow.stop()
            elif kill:
                result = await f.controller.kill_session(communication=f.communication,
                    storage_participant=workflow.storage_participant, result_window_s=0.05,
                    operator_authorized=True)
            else:
                result = await workflow.stop()
            if fatal:
                self.assertTrue(await f.communication.confirm_session_health_processing(f.sid, f.controller))
                for decision in f.controller.controller_action_decision_evidence:
                    with f.ingestor.durable_runtime_evidence_history_guard(
                            f.sid, f.ingestor.recovery_journal_path, (decision,)) as accepted:
                        self.assertTrue(accepted)
            if cancel or mode == "duplicate" or boundary == "control":
                self.assertTrue(result.succeeded, result.error)
                if boundary == "control":
                    # A fresh requester has no volatile Stop cache; permanent
                    # historical verification must still work after closeout.
                    requester = NatsControllerCommunication(f.communication._boundary)
                    intake = next(p for p in f.controller._session.configuration.expected_runtime_participants
                                  if p.component_type == "ingestor")
                    reconciled = await f.controller.reconcile_session_closeout(f.sid,
                        communication=requester, ingestor_participant=intake,
                        storage_participant=workflow.storage_participant, result_window_s=0.05)
                    self.assertTrue(reconciled.succeeded, reconciled.error)
            elif kill:
                self.assertTrue(result.succeeded, result.error)
                self.assertTrue(result.details["preservation_confirmed"])
                self.assertFalse(result.details["participant_cleanup_confirmed"])
                self.assertEqual(result.details["session_state"], "aborted")
                self.assertFalse((await f.controller.release_session(
                    communication=f.communication, result_window_s=0.05)).succeeded)
                retried = await f.controller.kill_session(communication=f.communication,
                    storage_participant=workflow.storage_participant, result_window_s=0.05,
                    operator_authorized=True)
                self.assertTrue(retried.succeeded, retried.error)
                self.assertTrue(retried.details["participant_cleanup_confirmed"])
            else:
                self.assertTrue(injected)
                self.assertFalse(result.succeeded)
                self.assertIsNotNone(f.controller.get_status()["session_id"])
                self.assertFalse(result.details.get("preservation_confirmed", False))
                state = f.controller.get_status()["session_state"]
                self.assertEqual(state, "failed" if fatal else (
                    "completed" if boundary in {"terminal", "terminal_reply", "final_result"} else "stopping"))
                if boundary not in {"before_marker", "marker"}:
                    before = workflow.archive()
                    # Retry cannot consume the invalidated cached marker.
                    if mode != "superseding":
                        rejected = await workflow.stop()
                        self.assertFalse(rejected.succeeded)
                        self.assertEqual(workflow.archive(), before)
                        self.assertIsNotNone(await f.communication.request_runtime_command(participant,
                            "stop_runtime", f.sid, {}, 0.05, command_id=saved["body"]["command_id"]))
                    retried = await workflow.stop()
                    self.assertTrue(retried.succeeded, retried.error)
                    self.assertEqual(retried.details["session_state"], "failed" if fatal else "completed")
                    if markers:
                        self.assertTrue(all(marker == markers[0] for marker in markers))
            self.assertEqual(physical_stop.call_count, 1)
            self.assertFalse(any(c["command_type"] == "kill" for c in f.broker.commands))

    async def test_normal_stop_checks_each_active_closeout_boundary(self):
        for boundary in ("before_marker", "marker", "before_preserve", "preserve_reply",
                         "after_preserve", "terminal", "terminal_reply", "final_result"):
            with self.subTest(boundary=boundary):
                await self.scenario(boundary)

    async def test_fatal_overlap_checks_each_boundary_without_competing_cleanup(self):
        for boundary in ("before_marker", "marker", "before_preserve", "preserve_reply",
                         "after_preserve", "terminal", "terminal_reply", "final_result"):
            with self.subTest(boundary=boundary):
                await self.scenario(boundary, fatal=True)

    async def test_valid_and_duplicate_success_preserve_normal_completion(self):
        await self.scenario("control")
        await self.scenario("preserve_reply", mode="duplicate")

    async def test_changed_payload_and_superseding_attempt_cannot_authorize_active_closeout(self):
        await self.scenario("after_preserve", mode="payload")
        await self.scenario("after_preserve", mode="superseding")

    async def test_malformed_callback_delivery_cannot_authorize_normal_or_fatal_closeout(self):
        await self.scenario("after_preserve", mode="malformed")
        await self.scenario("after_preserve", mode="malformed", fatal=True)

    async def test_kill_retains_partial_preservation_without_stale_cleanup_confirmation(self):
        await self.scenario("before_preserve", kill=True)

    async def test_cancelled_preservation_retains_binding_and_reuses_durable_marker(self):
        # Cancel once; the explicit second invocation uses the same preserved boundary.
        await self.scenario("control", cancel=True)

    async def test_local_owner_closeout_checks_receipt_boundary_and_allows_initial_completion(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                workflow = local_closeout.NormalStopTests()
                workflow.addCleanup = self.addCleanup
                workflow.addAsyncCleanup = self.addAsyncCleanup
                workflow.setUp()
                await workflow.running()
                f = workflow.fixture
                saved = {}
                publish = f.broker.publish
                receipt = workflow.receiver.verify_acquisition_evidence_receipt
                handoff = workflow.storage.write_artifact_collection_handoff

                async def wire(subject, data, stream):
                    if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node-a.stop_runtime"):
                        saved.update(subject=subject, body=json.loads(data))
                    return await publish(subject, data, stream)

                async def receive(marker):
                    result = await receipt(marker)
                    if invalid:
                        body = deepcopy(saved["body"])
                        body.update(status="failed", success=False, reason="Late contradiction")
                        await publish(saved["subject"], json.dumps(body).encode(), "LAB_COMMAND_RESULTS")
                    return result

                def existing_handoff(session_id, contents):
                    path = workflow.storage._artifact_collection_handoff_path(session_id)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if not path.exists():
                        path.write_text(json.dumps(contents, sort_keys=True, indent=2), encoding="utf-8")
                    return handoff(session_id, contents)

                with patch.object(f.broker, "publish", side_effect=wire), \
                        patch.object(workflow.receiver, "verify_acquisition_evidence_receipt", side_effect=receive), \
                        patch.object(workflow.storage, "write_artifact_collection_handoff", side_effect=existing_handoff):
                    result = await workflow.stop()
                self.assertEqual(result.succeeded, not invalid, result.error)
                self.assertEqual(f.controller.get_status()["session_state"], "stopping" if invalid else "completed")


class StopEnvelopeIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.broker = _Broker()
        self.boundary = _Boundary("controller", "controller", self.broker)
        self.communication = NatsControllerCommunication(self.boundary)
        self.participant = RuntimeParticipant("acquisition_node", "node")
        self.subscription = await self.communication.subscribe_command_results("session")
        self.addAsyncCleanup(self.subscription.unsubscribe)
        self.original_publish = self.broker.publish
        self.reply = None
        self.subject = "messages.session.command_result.acquisition_node.node.stop_runtime"

        async def publish(subject, data, stream):
            result = await self.original_publish(subject, data, stream)
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                self.reply = dict(result_id="result", command_id=command["command_id"], session_id="session",
                    source_id="node", target_id="controller", status="succeeded", success=True, reason=None,
                    payload={"request_nonce": command["payload"]["request_nonce"]})
                await self.original_publish(self.subject, json.dumps(self.reply).encode(), "LAB_COMMAND_RESULTS")
            return result

        self.broker.publish = publish

    async def request(self):
        return await self.communication.request_runtime_command(self.participant, "stop_runtime",
            "session", {}, 0.02, command_id="stable-stop")

    async def deliver(self, data, subject=None, callback=None):
        callback = self.subscription.callback if callback is None else callback
        return await _deliver_result(callback, subject or self.subject, data)

    async def test_malformed_correlated_results_invalidate_and_duplicates_cannot_restore(self):
        mutations = ({"reason": ...}, {"result_id": ...}, {"status": "unsupported"}, {"status": []},
            {"success": "true"}, {"reason": []}, {"result_id": []}, {"status": ...},
            {"payload_extra": float("nan")}, {"payload_extra": float("inf")},
            {"payload_extra": {"nested": [float("nan")]}})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertIsNotNone(await self.request())
                good = deepcopy(self.reply)
                bad = deepcopy(good)
                for key, value in mutation.items():
                    if key == "payload_extra":
                        bad["payload"]["diagnostic"] = value
                    elif value is ...:
                        bad.pop(key)
                    else:
                        bad[key] = value
                errors, acknowledgments = await self.deliver(json.dumps(bad).encode())
                self.assertEqual(errors, [])
                self.assertEqual(acknowledgments, 1)
                self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))
                await self.deliver(json.dumps(good).encode())
                self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))
                self.assertIsNotNone(await self.request())

    async def test_unrelated_and_uncorrelatable_malformed_results_do_not_poison_current_proof(self):
        for mismatch in ("session_id", "source_id", "target_id", "command_id", "request_nonce",
                         "operation", "participant", "json", "payload"):
            with self.subTest(mismatch=mismatch):
                accepted = await self.request()
                bad = deepcopy(self.reply)
                bad.pop("reason")
                subject = self.subject
                if mismatch in {"session_id", "source_id", "target_id", "command_id"}:
                    bad[mismatch] = "unrelated"
                elif mismatch == "request_nonce":
                    bad["payload"]["request_nonce"] = "stale"
                elif mismatch == "operation":
                    subject = subject.replace("stop_runtime", "check_readiness")
                elif mismatch == "participant":
                    subject = subject.replace("acquisition_node", "controller")
                elif mismatch == "payload":
                    bad["payload"] = None
                await self.deliver(b"{" if mismatch == "json" else json.dumps(bad).encode(), subject)
                self.assertEqual(self.communication.session_acquisition_completion(self.participant, "session"), accepted)

    async def test_malformed_resolution_during_request_cannot_be_hidden_by_valid_success(self):
        original = self.broker.publish

        async def malformed_first(subject, data, stream):
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                bad = dict(command_id=command["command_id"], session_id="session", source_id="node",
                    target_id="controller", payload={"request_nonce": command["payload"]["request_nonce"]})
                for subscription in tuple(self.broker.subscriptions):
                    if subscription.active:
                        await self.deliver(json.dumps(bad).encode(), callback=subscription.callback)
            return await original(subject, data, stream)

        with patch.object(self.broker, "publish", side_effect=malformed_first):
            self.assertIsNone(await self.request())

    async def test_conflict_during_dependency_notification_cannot_escape_request_handover(self):
        async def observation(operation, result):
            bad = deepcopy(result.to_dict())
            bad.update(status="failed", success=False, reason="Late owner failure")
            await self.original_publish(self.subject, json.dumps(bad).encode(), "LAB_COMMAND_RESULTS")

        self.boundary._dependency_result_observer = lambda participant, operation: observation
        self.assertIsNone(await self.request())
        self.assertIsNone(await self.communication.request_command(self.participant, "stop_runtime",
            "session", {"request_nonce": "direct-attempt"}, 0.02))

    async def test_exact_attempt_retry_cannot_clear_malformed_invalidation(self):
        async def direct(nonce):
            return await self.communication.request_command(self.participant, "stop_runtime",
                "session", {"request_nonce": nonce}, 0.02, command_id="direct-stop")

        self.assertIsNotNone(await direct("original"))
        bad = deepcopy(self.reply)
        bad.pop("reason")
        await self.deliver(json.dumps(bad).encode())
        self.assertIsNone(await direct("original"))
        self.assertIsNotNone(await direct("fresh-explicit-attempt"))
