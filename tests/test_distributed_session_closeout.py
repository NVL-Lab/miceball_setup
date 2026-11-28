"""Session closeout with independent Controller, timing, node and intake owners."""

import asyncio
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, NatsCommunicationBoundary, NatsControllerCommunication,
    NatsIngestorCommunication, NatsStorageManagerCommunication, PersistentStorageManager,
    RuntimeEvidenceMessage, RuntimeParticipant, ScientificOutputSelection,
)
from tests import test_distributed_synchronization as timing
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker
from tests.test_producer_publication_completion import PublicationBroker
from tests.test_producer_publication_completion import interpretation
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


class CloseoutBroker(PublicationBroker):
    """Keep evidence receipts and command resolution history independently."""

    def __init__(self):
        super().__init__()
        self.result_history = EvidenceReceiptBroker()

    async def stream_info(self, name):
        if name == "LAB_COMMAND_RESULTS":
            return await self.result_history.stream_info(name)
        return await super().stream_info(name)

    async def get_msg(self, stream, **options):
        if stream == "LAB_COMMAND_RESULTS":
            return await self.result_history.get_msg(stream, **options)
        return await super().get_msg(stream, **options)

    async def publish(self, subject, data, stream=None, reply=""):
        if stream == "LAB_COMMAND_RESULTS":
            await self.result_history.publish(subject, data, stream)
        return await super().publish(subject, data, stream, reply=reply)


class ReleaseSubscription:
    """Wrap broker interest with non-idempotent unsubscribe and controlled failures."""

    def __init__(self, subscription):
        self.subscription = subscription
        self.attempts = 0
        self.released = False
        self.before_unsubscribe = None

    async def unsubscribe(self):
        self.attempts += 1
        if self.released:
            raise RuntimeError("Subscription already unsubscribed")
        if self.before_unsubscribe is not None:
            await self.before_unsubscribe()
        await self.subscription.unsubscribe()
        self.released = True


class DistributedSessionCloseoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = timing.DistributedSynchronizationTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.addAsyncCleanup = self.addAsyncCleanup

        def intake(**configuration):
            root = Path(configuration["recovery_journal_root"]).parent
            self.storage = PersistentStorageManager(root, global_artifact_root=root / "artifacts")
            return InMemoryIngestor(storage_manager=self.storage, **configuration)

        with patch.object(timing, "_Broker", CloseoutBroker), patch.object(timing, "InMemoryIngestor", intake):
            await self.fixture.asyncSetUp()
        self.storage_participant = RuntimeParticipant("storage_manager", "storage")

    async def running(self):
        f = self.fixture
        await f.start()
        topic = f"messages.{f.sid}.evidence.*.*.*"
        self.durable = next(name for name, consumer in f.broker.consumers.items()
                            if consumer.config.filter_subject == topic)
        f.broker.callbacks[self.durable] = next(s.callback for s in f.broker.subscriptions if s.subject == topic)

        async def acknowledge_marker(subject, payload):
            if payload.get("evidence_type") == "acquisition_evidence_completion":
                await self.acknowledge()

        f.broker.after_publication = acknowledge_marker
        await f.experiment()
        self.assertTrue((await f.request(f.participants[-1], "run_one_iteration")).success)

    async def acknowledge(self):
        for sequence in sorted(self.fixture.broker.records):
            await self.fixture.broker.deliver(self.durable, sequence)

    async def stop(self):
        f = self.fixture
        return await f.controller.normal_stop_session(communication=f.communication,
            storage_participant=self.storage_participant, result_window_s=0.05)

    def archive(self):
        return {str(p): p.read_bytes() for p in (self.fixture.root / f"session_{self.fixture.sid}").rglob("*") if p.is_file()}

    def release_subscriptions(self):
        subscriptions = tuple(ReleaseSubscription(s) for s in self.fixture.controller._launch_subscriptions)
        self.fixture.controller._launch_subscriptions = subscriptions
        self.assertGreaterEqual(len(subscriptions), 2)
        return subscriptions

    async def _normal_stop_with_delayed_controller_ack(self, *, pending_health):
        await self.running()
        f = self.fixture
        self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
        health = next(s for s in f.controller._launch_subscriptions
                      if "subscribe_health_interpretation_evidence" in s.callback.__qualname__)
        receive = health.callback
        deferred_acks = []
        entered, resume = asyncio.Event(), asyncio.Event()

        async def delay_ack(message):
            kind = json.loads(message.data)["evidence_type"]
            acknowledge = message.ack
            if kind == "controller_action_decision":
                async def defer():
                    deferred_acks.append(acknowledge)
                message.ack = defer
            elif pending_health and kind == "health_interpretation":
                async def wait_for_processing():
                    entered.set()
                    await resume.wait()
                    await acknowledge()
                message.ack = wait_for_processing
            await receive(message)

        health.callback = delay_ack
        local = f.node.local_storage_manager
        warning = RuntimeEvidenceMessage("closeout-warning", f.sid, "health_interpretation",
                                        "node", interpretation().to_dict(), True)
        delivery = asyncio.create_task(f.handler._boundary.publish_evidence(warning))
        try:
            if pending_health:
                await asyncio.wait_for(entered.wait(), 2)
                failed = await self.stop()
                self.assertFalse(failed.succeeded)
                self.assertIn("Controller Session health processing is unconfirmed", failed.error)
                self.assertEqual(f.controller.get_status()["session_state"], "stopping")
                self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
                self.assertFalse(any(data.get("evidence_type") == "acquisition_evidence_completion"
                                     for _, data in f.broker.events))
                resume.set()
            await delivery
            self.assertTrue(await f.communication.confirm_session_health_processing(f.sid, f.controller))
            manifest, = local.manifests
            path = Path(manifest.local_storage_path)
            scientific_bytes = path.read_bytes()
            accepted = {m.evidence_id: m.to_dict() for m in f.ingestor.accepted_runtime_evidence}

            # The callback returns, but native ACK accounting remains outstanding.
            # Initial processing is clear; only Controller publication creates it.
            result = await self.stop()
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(deferred_acks)
            self.assertGreater((await health.consumer_info()).num_ack_pending, 0)
            self.assertTrue(health.active)
            self.assertEqual(f.controller.get_status()["session_state"], "completed")
            self.assertTrue(result.details["preservation_confirmed"])
            self.assertTrue(result.details["acquisition_preservation_eligible"])
            self.assertTrue(result.details["compilation_summary"]["stage_a_complete"])
            marker, = [data for _, data in f.broker.events
                       if data.get("evidence_type") == "acquisition_evidence_completion"]
            self.assertIsNotNone(f.ingestor.finalized_acquisition_intake(f.sid))
            saved = f.ingestor.read_session_closeout(f.sid)
            self.assertTrue(saved["preservation_confirmed"])
            self.assertEqual(path.read_bytes(), scientific_bytes)
            actual = {m.evidence_id: m.to_dict() for m in f.ingestor.accepted_runtime_evidence}
            self.assertTrue(all(actual.get(key) == value for key, value in accepted.items()))
            decision, = f.controller.controller_action_decision_evidence
            self.assertIn(decision.to_dict(), result.details["runtime_evidence"])
            for acknowledge in deferred_acks:
                await acknowledge()
            self.assertEqual((await health.consumer_info()).num_ack_pending, 0)
            released = await f.controller.release_session(communication=f.communication, result_window_s=.05)
            self.assertTrue(released.succeeded, released.error)
            self.assertFalse(health.active)
            self.assertFalse(any(data.get("evidence_type") == "acquisition_evidence_completion"
                                 and data != marker for _, data in f.broker.events))
        finally:
            resume.set()
            await delivery

    async def test_normal_stop_does_not_wait_for_its_own_nonhealth_ack(self):
        await self._normal_stop_with_delayed_controller_ack(pending_health=False)

    async def test_health_processing_then_explicit_stop_continuation_preserves_science(self):
        await self._normal_stop_with_delayed_controller_ack(pending_health=True)

    async def test_release_retains_native_consumer_until_controller_evidence_ack(self):
        from nats.js.errors import NotFoundError

        await self.running()
        f = self.fixture
        warning = RuntimeEvidenceMessage("release-warning", f.sid, "health_interpretation",
                                        "node", interpretation().to_dict(), True)
        await f.handler._boundary.publish_evidence(warning)
        decision, = f.controller.controller_action_decision_evidence
        # Reuse the fixture's disposable authority server, with a real evidence
        # recipient so release exercises the SDK/native consumer retirement guard.
        url = f.communication._boundary._client.connected_url.geturl()
        boundary = NatsCommunicationBoundary("controller", "controller", (url,))
        await boundary.connect()
        self.addAsyncCleanup(boundary.close)
        await boundary.ensure_streams()
        pending, received = [], asyncio.Event()
        subscribe = boundary._subscribe_jetstream

        async def defer_ack(subject, callback, **options):
            async def receive(message):
                async def defer():
                    pending.append(message)
                    received.set()
                message.ack = defer
                await callback(message)
            return await subscribe(subject, receive, **options)

        with patch.object(boundary, "_subscribe_jetstream", side_effect=defer_ack):
            subscription = await NatsControllerCommunication(boundary).subscribe_health_interpretation_evidence(
                f.sid, f.controller)
        f.controller._launch_subscriptions += (subscription,)
        await boundary.publish_evidence(decision)
        await asyncio.wait_for(received.wait(), 2)
        info = await subscription.consumer_info()
        self.assertEqual(info.num_ack_pending, 1)
        stopped = await self.stop()
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertTrue(stopped.details["preservation_confirmed"])
        refused = await f.controller.release_session(communication=f.communication, result_window_s=.05)
        self.assertFalse(refused.succeeded)
        self.assertIn("Session consumer still has unresolved deliveries", refused.error)
        self.assertEqual(f.controller.get_status()["session_id"], f.sid)
        js = boundary._require_jetstream()
        self.assertEqual((await js.consumer_info("LAB_EVIDENCE", info.name)).num_ack_pending, 1)
        await pending[0].ack_sync()
        self.assertEqual((await subscription.consumer_info()).num_ack_pending, 0)
        released = await f.controller.release_session(communication=f.communication, result_window_s=.05)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(f.controller.get_status()["session_id"])
        with self.assertRaises(NotFoundError):
            await js.consumer_info("LAB_EVIDENCE", info.name)

    async def test_normal_stop_preserves_science_and_releases_independent_services(self):
        await self.running()
        f = self.fixture
        local = f.node.local_storage_manager
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertTrue(result.details["acquisition_preservation_eligible"])
        self.assertFalse(result.details["compilation_summary"]["archive_closed"])
        manifest, = local.manifests
        self.assertEqual(len(Path(manifest.local_storage_path).read_text().splitlines()), 1)
        before = self.archive()
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(self.archive(), before)
        released = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(f.ingestor.session_id)

    async def test_normal_stop_quiesces_sustained_recording_before_finalized_intake(self):
        f = self.fixture
        await f.handler.start_acquisition_execution()
        self.addAsyncCleanup(f.handler.stop_acquisition_execution)
        await self.running()
        for _ in range(100):
            if f.node.status()["iteration_count"] >= 4:
                break
            await asyncio.sleep(0)
        self.assertGreaterEqual(f.node.status()["iteration_count"], 4)
        local = f.node.local_storage_manager
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["acquisition_preservation_eligible"])
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertFalse(f.handler.acquisition_execution_active)
        manifest, = local.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        self.assertGreaterEqual(len(Path(manifest.local_storage_path).read_text().splitlines()), 4)
        before = self.archive()
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(self.archive(), before)
        self.assertTrue((await f.controller.release_session(
            communication=f.communication, result_window_s=0.05)).succeeded)
        self.assertIsNone(f.ingestor.session_id)
        self.assertFalse(f.handler.acquisition_execution_active)

    async def test_finalized_intake_discards_late_and_duplicate_delivery_without_audit_changes(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        journal = f.ingestor.recovery_journal_path.read_bytes()
        audit = f.ingestor.runtime_evidence_audit
        evidence = f.ingestor.accepted_runtime_evidence[0]
        late = deepcopy(evidence.to_dict())
        late["evidence_id"] = "late-observation"
        await f.handler._boundary.publish_evidence(evidence)
        await f.handler._boundary.publish_evidence(RuntimeEvidenceMessage.from_dict(late))
        self.assertEqual(f.ingestor.runtime_evidence_audit, audit)
        self.assertEqual(f.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertEqual(self.archive(), before)

    async def test_restart_verifies_finalized_preservation_without_restoring_a_session(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        storage = PersistentStorageManager(f.root)
        restored = InMemoryIngestor(storage_manager=storage, recovery_journal_root=f.root / "journals")
        saved = restored.read_session_closeout(f.sid)
        self.assertTrue(saved["acquisition_preservation_eligible"])
        self.assertIsNone(restored.session_id)
        bound = InMemoryIngestor(session_id=f.sid, storage_manager=storage,
            recovery_journal_path=f.ingestor.recovery_journal_path)
        self.assertEqual(bound.compile_persistent_runtime_evidence()["ingest_audit"],
                         f.ingestor.compile_persistent_runtime_evidence()["ingest_audit"])
        self.assertTrue(bound.read_session_closeout(f.sid)["preservation_confirmed"])
        self.assertEqual(self.archive(), before)

    async def test_incomplete_receipt_blocks_completion_until_explicit_retry(self):
        await self.running()
        f = self.fixture
        f.broker.after_publication = None
        result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(f.controller.get_status()["session_state"], "stopping")
        self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
        await self.acknowledge()
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

    async def test_normal_stop_waits_for_independently_delayed_marker_intake(self):
        await self.running()
        f = self.fixture
        tasks = []
        waiting = asyncio.Event()
        original_wait = f.ingestor.await_durable_runtime_evidence
        async def observe_wait(*args):
            waiting.set()
            return await original_wait(*args)
        subscription = next(s for s in f.broker.subscriptions if s.subject == f"messages.{f.sid}.evidence.*.*.*")
        receive = subscription.callback
        async def delay_marker(message):
            if json.loads(message.data).get("evidence_type") == "acquisition_evidence_completion":
                async def deliver():
                    await waiting.wait()
                    await receive(message)
                    await self.acknowledge()
                tasks.append(asyncio.create_task(deliver()))
            else:
                await receive(message)
        subscription.callback = delay_marker
        f.broker.after_publication = None
        try:
            with patch.object(f.ingestor, "await_durable_runtime_evidence", side_effect=observe_wait):
                result = await f.controller.normal_stop_session(communication=f.communication,
                    storage_participant=self.storage_participant, result_window_s=1)
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["acquisition_preservation_eligible"])
            request = next(command for command in f.broker.commands if command['command_type'] == 'preserve_session_acquisition')
            self.assertEqual(request['payload']['acceptance_window_s'], .5)
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_invalid_marker_or_journal_fails_without_waiting(self):
        await self.fixture.start()
        f = self.fixture
        marker = RuntimeEvidenceMessage("test-marker", f.sid, "acquisition_evidence_completion", "controller", {}, True)
        async def request(value, **changes):
            payload = dict(mode="normal", marker=value, session_record={}, controller_evidence=[],
                uncertainties=[], acceptance_window_s=.1, **changes)
            return await f.communication.request_persistence_command(f.participants[0], "preserve_session_acquisition",
                f.sid, payload, 1, command_id=json.dumps([f.sid, "preserve_session_acquisition"], separators=(",", ":")))
        from dataclasses import replace
        for value, reason in ((replace(marker, session_id="another"), "session_mismatch"),
                (replace(marker, source_id="another"), "marker_source_mismatch"),
                (replace(marker, evidence_type="another"), "invalid_completion_marker")):
            with self.subTest(reason=reason), patch.object(f.ingestor, "await_durable_runtime_evidence", new_callable=AsyncMock) as wait:
                result = await request(value.to_dict())
                self.assertFalse(result.success)
                self.assertIn(reason, result.reason)
                wait.assert_not_awaited()
        f.ingestor.receive_runtime_evidence(marker)
        for attribute, value, reason in (("_recovery_journal_path", None, "journal_unavailable"),
                ("_journal_failed", True, "journal_failed")):
            with self.subTest(reason=reason), patch.object(f.ingestor, attribute, value), patch.object(
                    f.ingestor, "await_durable_runtime_evidence", new_callable=AsyncMock) as wait:
                result = await request(marker.to_dict())
                self.assertFalse(result.success)
                self.assertIn(reason, result.reason)
                wait.assert_not_awaited()
        result = await request(replace(marker, payload={"conflicting": True}).to_dict())
        self.assertIn("conflicting_marker_contents", result.reason)

    async def test_acceptance_timeout_and_cancel_retain_explicit_retry(self):
        await self.running()
        f = self.fixture
        subscription = next(s for s in f.broker.subscriptions if s.subject == f"messages.{f.sid}.evidence.*.*.*")
        receive = subscription.callback
        pending = []
        async def withhold(message):
            if json.loads(message.data).get("evidence_type") == "acquisition_evidence_completion":
                pending.append(message)
            else:
                await receive(message)
        subscription.callback = withhold
        f.broker.after_publication = None
        failed = await f.controller.normal_stop_session(communication=f.communication,
            storage_participant=self.storage_participant, result_window_s=.2)
        self.assertFalse(failed.succeeded)
        self.assertIn("durable_acceptance_deadline_expired", failed.error)
        self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
        waiting = asyncio.Event()
        original_wait = f.ingestor.await_durable_runtime_evidence
        async def observe_wait(*args):
            waiting.set()
            return await original_wait(*args)
        with patch.object(f.ingestor, "await_durable_runtime_evidence", side_effect=observe_wait):
            task = asyncio.create_task(f.controller.normal_stop_session(communication=f.communication,
                storage_participant=self.storage_participant, result_window_s=2))
            await asyncio.wait_for(waiting.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(f.ingestor.session_id, f.sid)
        self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
        subscription.callback = receive
        await self.acknowledge()
        retry = await self.stop()
        self.assertTrue(retry.succeeded, retry.error)

    async def test_preservation_failure_retains_finality_and_blocks_release(self):
        await self.running()
        f = self.fixture
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("disk unavailable")):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertIsNotNone(f.ingestor.finalized_acquisition_intake(f.sid))
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        self.assertEqual(f.ingestor.session_id, f.sid)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

    async def test_kill_preserves_partial_evidence_without_confirming_missing_cleanup(self):
        await self.running()
        f = self.fixture
        f.broker.drop_results.add(("node", "stop_runtime"))
        result = await f.controller.kill_session(communication=f.communication,
            storage_participant=self.storage_participant, result_window_s=0.05, operator_authorized=True)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(f.controller.get_status()["session_state"], "aborted")
        self.assertFalse(result.details["acquisition_preservation_eligible"])
        self.assertFalse(result.details["participant_cleanup_confirmed"])
        self.assertEqual(f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_abort")
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        self.assertEqual(f.node.reserved_for_session_id, f.sid)

    async def test_health_during_normal_stop_is_preserved_before_last_call(self):
        await self.running()
        f = self.fixture
        reached, resume = asyncio.Event(), asyncio.Event()

        async def pause(subject, payload):
            if payload.get("command_type") == "stop_runtime" and payload.get("target_id") == "node":
                reached.set()
                await resume.wait()

        f.broker.before_publication = pause
        task = asyncio.create_task(self.stop())
        try:
            await asyncio.wait_for(reached.wait(), 2)
            decision = f.controller.process_health_interpretation(interpretation("during-stop"))
            timing_evidence = RuntimeEvidenceMessage("during-stop-timing", f.sid,
                "timing_quality_interpretation", "node", {"interpretation_label": "warning"}, True)
            f.controller.process_timing_quality_interpretation(timing_evidence)
            self.assertIsNone(f.controller._acquisition_marker)
        finally:
            resume.set()
            result = await task
            f.broker.before_publication = None
        self.assertTrue(result.succeeded, result.error)
        messages = result.details["runtime_evidence"]
        self.assertTrue(any(m["payload"].get("originating_observation_id") == decision.originating_observation_id
                            for m in messages if m["evidence_type"] == "controller_action_decision"))
        self.assertTrue(any(m["payload"].get("originating_observation_id") == timing_evidence.evidence_id
                            for m in messages if m["evidence_type"] == "controller_action_decision"))
        before = self.archive()
        with self.assertRaises(RuntimeError):
            f.controller.process_health_interpretation(interpretation("after-marker"))
        with self.assertRaises(RuntimeError):
            f.controller.process_timing_quality_interpretation(RuntimeEvidenceMessage("after-marker-timing", f.sid,
                "timing_quality_interpretation", "node", {"interpretation_label": "warning"}, True))
        self.assertEqual(self.archive(), before)

    async def test_new_health_during_publication_is_rejected_after_cutoff(self):
        await self.running()
        f = self.fixture
        f.controller.process_health_interpretation(interpretation("first"))
        acknowledge_marker = f.broker.after_publication
        injected = False

        async def add_health(subject, payload):
            nonlocal injected
            if payload.get("evidence_type") == "controller_action_decision" and not injected:
                injected = True
                f.controller.process_health_interpretation(interpretation("during-publication"))
            await acknowledge_marker(subject, payload)

        f.broker.after_publication = add_health
        result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertIn("admission is closed", result.error)
        self.assertIsNone(f.controller._acquisition_marker)
        f.broker.after_publication = acknowledge_marker
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["acquisition_preservation_eligible"])
        observations = {m["payload"].get("originating_observation_id") for m in result.details["runtime_evidence"]
                        if m["evidence_type"] == "controller_action_decision"}
        self.assertIn("first", observations)
        self.assertNotIn("during-publication", observations)

    async def test_post_completion_rejection_blocks_remote_release(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        rejection = await f.controller.start_launched_experiment("too-late")
        self.assertFalse(rejection.succeeded)
        self.assertTrue(rejection.details["rejection_evidence"]["is_persistent"])
        released = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertFalse(released.succeeded)
        self.assertIn("Controller-owned evidence", released.error)
        self.assertEqual(f.ingestor.session_id, f.sid)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertEqual(self.archive(), before)
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)

    async def test_evidence_created_during_participant_release_retains_controller_binding(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        reached, resume = asyncio.Event(), asyncio.Event()

        async def pause(subject, payload):
            if payload.get("command_type") == "release_session" and payload.get("target_id") == "sync":
                reached.set()
                await resume.wait()

        f.broker.before_publication = pause
        task = asyncio.create_task(f.controller.release_session(communication=f.communication, result_window_s=0.05))
        try:
            await asyncio.wait_for(reached.wait(), 2)
            rejected = await f.controller.start_launched_experiment("during-release")
            self.assertFalse(rejected.succeeded)
        finally:
            resume.set()
            released = await task
            f.broker.before_publication = None
        self.assertFalse(released.succeeded)
        self.assertIn("Controller-owned evidence", released.error)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertEqual(f.ingestor.session_id, f.sid)
        self.assertEqual(self.archive(), before)
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)

    async def test_new_evidence_during_final_readback_blocks_retirement(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        reads = 0
        rejected = None

        async def reject_during_readback(subject, payload):
            nonlocal reads, rejected
            if payload.get("command_type") == "read_session_closeout":
                reads += 1
                if reads == 2:
                    rejected = await f.controller.start_launched_experiment("during-final-readback")

        f.broker.before_publication = reject_during_readback
        try:
            result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        finally:
            f.broker.before_publication = None
        self.assertIsNotNone(rejected)
        self.assertFalse(rejected.succeeded)
        self.assertFalse(result.succeeded)
        self.assertIn("Controller-owned evidence", result.error)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertEqual(self.archive(), before)
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)

    async def test_unconfirmed_release_readback_allows_explicit_verified_retry(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        f.broker.drop_results.add(("ingestor", "read_session_closeout"))
        result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertFalse(result.succeeded)
        self.assertEqual(f.ingestor.session_id, f.sid)
        f.broker.drop_results.clear()
        result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.archive(), before)

    async def test_cancelled_release_retries_with_fresh_verified_preservation(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        subscriptions = self.release_subscriptions()
        reached, resume = asyncio.Event(), asyncio.Event()
        reads = 0

        async def pause(subject, payload):
            nonlocal reads
            if payload.get("command_type") == "read_session_closeout":
                reads += 1
                if reads == 2:
                    reached.set()
                    await resume.wait()

        f.broker.before_publication = pause
        task = asyncio.create_task(f.controller.release_session(communication=f.communication, result_window_s=0.05))
        try:
            await asyncio.wait_for(reached.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            resume.set()
            f.broker.before_publication = None
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        released = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(released.succeeded, released.error)
        self.assertEqual(self.archive(), before)
        self.assertTrue(all(s.released and s.attempts == 1 for s in subscriptions))

    async def test_missing_final_readback_retries_without_repeating_unsubscribe(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        subscriptions = self.release_subscriptions()
        reads = 0

        async def lose_final_readback(subject, payload):
            nonlocal reads
            if payload.get("command_type") == "read_session_closeout":
                reads += 1
                if reads == 2:
                    f.broker.drop_results.add(("ingestor", "read_session_closeout"))

        f.broker.before_publication = lose_final_readback
        try:
            result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        finally:
            f.broker.before_publication = None
            f.broker.drop_results.clear()
        self.assertFalse(result.succeeded)
        self.assertEqual(reads, 2)
        self.assertIn("missing response", result.error)
        self.assertIsNone(f.ingestor.session_id)
        self.assertTrue(all(s.released and s.attempts == 1 for s in subscriptions))
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertEqual(self.archive(), before)
        result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(all(s.attempts == 1 for s in subscriptions))
        self.assertIsNone(f.controller.get_status()["session_state"])
        self.assertEqual(self.archive(), before)

    async def check_interrupted_unsubscribe(self, *, cancelled):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        subscriptions = self.release_subscriptions()
        reached, resume = asyncio.Event(), asyncio.Event()

        async def interrupt():
            reached.set()
            if cancelled:
                await resume.wait()
            raise RuntimeError("Unsubscribe unavailable")

        subscriptions[1].before_unsubscribe = interrupt
        task = asyncio.create_task(f.controller.release_session(
            communication=f.communication, result_window_s=0.05))
        try:
            await asyncio.wait_for(reached.wait(), 2)
            if cancelled:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                self.assertFalse((await task).succeeded)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(subscriptions[0].released)
        self.assertFalse(subscriptions[1].released)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertEqual(self.archive(), before)
        subscriptions[1].before_unsubscribe = None
        result = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(subscriptions[0].attempts, 1)
        self.assertEqual(subscriptions[1].attempts, 2)
        self.assertTrue(all(s.released for s in subscriptions))
        self.assertEqual(self.archive(), before)

    async def test_failed_unsubscribe_retries_only_pending_release_work(self):
        await self.check_interrupted_unsubscribe(cancelled=False)

    async def test_cancelled_unsubscribe_retries_only_pending_release_work(self):
        await self.check_interrupted_unsubscribe(cancelled=True)

    async def test_cancelled_preservation_keeps_binding_and_allows_explicit_retry(self):
        await self.running()
        f = self.fixture
        reached = asyncio.Event()
        release = asyncio.Event()

        async def pause(subject, payload):
            if payload.get("command_type") == "preserve_session_acquisition":
                reached.set()
                await release.wait()

        f.broker.before_publication = pause
        task = asyncio.create_task(self.stop())
        await asyncio.wait_for(reached.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        f.broker.before_publication = None
        self.assertEqual(f.ingestor.session_id, f.sid)
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)


def run_closeout_owner(url, directory, lost_reply, ready, stop):
    """Run the paired intake/storage owners; optionally lose one terminal reply."""
    async def run():
        root = Path(directory)
        intake_boundary = NatsCommunicationBoundary("ingestor", "ingestor", servers=[url])
        storage_boundary = NatsCommunicationBoundary("storage_manager", "storage", servers=[url])
        await intake_boundary.connect()
        try:
            await storage_boundary.connect()
            try:
                await intake_boundary.ensure_streams()
                storage = PersistentStorageManager(root)
                intake = InMemoryIngestor(storage, recovery_journal_root=root / "journals")
                receiver = NatsIngestorCommunication(intake_boundary, intake)
                storage_handler = NatsStorageManagerCommunication(storage_boundary, storage)
                publish = intake_boundary.publish_command_result

                async def publish_result(result, operation):
                    if (lost_reply is not None and not lost_reply.is_set() and result.success
                            and operation == "preserve_session_terminal_record"):
                        lost_reply.set()
                        raise ConnectionError("Injected lost terminal preservation reply")
                    await publish(result, operation)

                intake_boundary.publish_command_result = publish_result
                await receiver.subscribe_commands()
                await storage_handler.subscribe_commands()
                ready.send(True)
                await asyncio.to_thread(stop.wait)
            finally:
                await storage_boundary.close()
        finally:
            await intake_boundary.close()
            ready.close()
    asyncio.run(run())


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class JetStreamSessionCloseoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.url = await self.enterAsyncContext(temporary_jetstream_server())
        self.boundary = NatsCommunicationBoundary("controller", "controller", servers=[self.url])
        await self.boundary.connect()
        self.addAsyncCleanup(self.boundary.close)
        await self.boundary.ensure_streams()
        self.communication = NatsControllerCommunication(self.boundary)
        self.controller = Controller()
        self.context = multiprocessing.get_context("spawn")
        self.workers = []
        self.addAsyncCleanup(self.stop_workers)
        self.intake = RuntimeParticipant("ingestor", "ingestor")
        self.storage = RuntimeParticipant("storage_manager", "storage")
        self.clock = RuntimeParticipant("synchronization_manager", "sync")
        self.node = RuntimeParticipant("acquisition_node", "node")

    async def start_worker(self, target, *arguments):
        parent, child = self.context.Pipe()
        stop = self.context.Event()
        process = self.context.Process(target=target, args=(*arguments, child, stop))
        try:
            process.start()
            self.workers.append((process, stop))
            child.close()
            self.assertTrue(await asyncio.to_thread(parent.poll, 20), "Participant did not start")
            self.assertTrue(parent.recv())
        finally:
            parent.close()
            child.close()
        return process, stop

    async def stop_worker(self, worker):
        process, stop = worker
        stop.set()
        await asyncio.to_thread(process.join, 15)
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5)
        self.assertEqual(process.exitcode, 0, "Participant did not shut down cleanly")

    async def stop_workers(self):
        for _, stop in self.workers:
            stop.set()
        for worker in self.workers:
            with self.subTest(worker=worker[0].name):
                try:
                    await self.stop_worker(worker)
                finally:
                    worker[0].close()

    async def running(self, *, lost_reply=None):
        # Spawned workers exchange only NATS traffic; the parent owns no services
        # other than Controller. Only the intake/storage pair share an address space.
        self.owner_worker = await self.start_worker(run_closeout_owner, self.url, str(self.root), lost_reply)
        await self.start_worker(timing.run_participant, "synchronization_manager", self.url, str(self.root))
        self.node_worker = await self.start_worker(timing.run_participant, "acquisition_node", self.url, str(self.root))
        result = await self.controller.launch_session({"node": (timing.declaration(),)},
            communication=self.communication, participants=(self.intake, self.clock, self.node),
            config_parameters={"storage_location": str(self.root / "records"),
                "protocol_plan": {"name": "test"}, "error_evidence_location": str(self.root / "errors"),
                "synchronization_configuration": timing.configuration()}, result_window_s=5)
        self.assertTrue(result.succeeded, result.error)
        self.sid = result.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        result = await self.controller.start_launched_experiment("experiment",
            scientific_outputs=(ScientificOutputSelection("device", "node", "events"),))
        self.assertTrue(result.succeeded, result.error)
        result = await self.communication.request_runtime_command(self.node, "run_one_iteration", self.sid, {}, 5)
        self.assertIsNotNone(result)
        self.assertTrue(result.success, result.reason)

    async def wait_for_receipt(self, sequence):
        """Wait on actual consumer acknowledgment, not an arbitrary delivery delay."""
        jetstream = self.boundary._require_jetstream()
        async with asyncio.timeout(10):
            while True:
                consumers = await jetstream.consumers_info("LAB_EVIDENCE")
                consumer = next(c for c in consumers if c.config.filter_subject == f"messages.{self.sid}.evidence.*.*.*")
                if consumer.ack_floor.stream_seq >= sequence:
                    return
                await asyncio.sleep(.01)

    async def normal_stop(self):
        result = await self.controller.normal_stop_session(communication=self.communication,
            storage_participant=self.storage, result_window_s=2)
        # Producer publication can precede the receiver's server-confirmed ACK.
        # Only that specific unconfirmed result permits this explicit retry.
        if not result.succeeded and "receipt is unconfirmed" in result.error:
            marker = await self.boundary._require_jetstream().get_last_msg("LAB_EVIDENCE",
                f"messages.{self.sid}.evidence.controller.controller.acquisition_evidence_completion")
            await self.wait_for_receipt(marker.seq)
            result = await self.controller.normal_stop_session(communication=self.communication,
                storage_participant=self.storage, result_window_s=2)
        return result

    def products(self):
        directory = self.root / f"session_{self.sid}"
        return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}

    async def reconcile(self, controller=None):
        result = await (controller or self.controller).reconcile_session_closeout(self.sid,
            communication=self.communication, ingestor_participant=self.intake,
            storage_participant=self.storage, result_window_s=5)
        self.assertTrue(result.succeeded, result.error)
        return result.details

    async def test_normal_stop_freezes_intake_and_releases_independent_services(self):
        await self.running()
        result = await self.normal_stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "completed")
        preserved = await self.reconcile()
        self.assertTrue(preserved["preservation_confirmed"])
        self.assertTrue(preserved["acquisition_preservation_eligible"])
        self.assertTrue(preserved["compilation_summary"]["stage_a_complete"])
        self.assertFalse(preserved["compilation_summary"]["archive_closed"])
        marker = await self.boundary._require_jetstream().get_last_msg("LAB_EVIDENCE",
            f"messages.{self.sid}.evidence.controller.controller.acquisition_evidence_completion")
        self.assertEqual(preserved["finalized_intake"]["receipt"]["marker_stream_sequence"], marker.seq)
        self.assertTrue(preserved["finalized_intake"]["receipt"]["durable_receipt_confirmed"])
        artifact, = preserved["artifact_collection_handoff"]["artifacts"]
        self.assertEqual(artifact["artifact_manifest"]["lifecycle_state"], "finalized")
        scientific = Path(artifact["artifact_manifest"]["local_storage_path"])
        science = scientific.read_bytes()
        row, = [json.loads(line) for line in science.splitlines()]
        self.assertEqual(row["value"], 1)
        before = self.products()
        journal = self.root / "journals" / f"session_{self.sid}.jsonl"
        original_journal = journal.read_bytes()
        original = next(json.loads(line) for line in before[str(Path("evidence") / "runtime_evidence.jsonl")].splitlines()
                        if json.loads(line)["source_id"] == "node")
        producer = NatsCommunicationBoundary("acquisition_node", "node", servers=[self.url])
        await producer.connect()
        try:
            previous_sequence = (await producer._require_jetstream().stream_info("LAB_EVIDENCE")).state.last_seq
            await producer.publish_evidence(RuntimeEvidenceMessage.from_dict(original))
            late = {**deepcopy(original), "evidence_id": "late-operational-evidence"}
            await producer.publish_evidence(RuntimeEvidenceMessage.from_dict(late))
            sequence = (await producer._require_jetstream().stream_info("LAB_EVIDENCE")).state.last_seq
            self.assertEqual(sequence, previous_sequence + 2)
            await self.wait_for_receipt(sequence)
        finally:
            await producer.close()
        self.assertEqual(self.products(), before)
        self.assertEqual(journal.read_bytes(), original_journal)
        self.assertEqual((await self.reconcile())["finalized_intake"], preserved["finalized_intake"])
        released = await self.controller.release_session(communication=self.communication, result_window_s=5)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(self.controller.get_status()["session_state"])
        self.assertTrue(all(process.is_alive() for process, _ in self.workers))
        jetstream = self.boundary._require_jetstream()
        for participant, operation, flag in ((self.clock, "release_session", "released"),
                (self.intake, "release_session", "released"), (self.node, "release_reservation", "confirmed")):
            response = await jetstream.get_last_msg("LAB_COMMAND_RESULTS",
                f"messages.{self.sid}.command_result.{participant.component_type}.{participant.component_id}.{operation}")
            payload = json.loads(response.data)
            self.assertTrue(payload["success"])
            self.assertTrue(payload["payload"][flag])
        self.assertEqual(self.products(), before)
        self.assertEqual(scientific.read_bytes(), science)

    async def test_kill_preserves_available_evidence_but_retains_unconfirmed_cleanup(self):
        await self.running()
        # A real unavailable participant, not a mocked cleanup confirmation.
        await self.stop_worker(self.node_worker)
        result = await self.controller.kill_session(communication=self.communication,
            storage_participant=self.storage, result_window_s=2, operator_authorized=True)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "aborted")
        self.assertFalse(result.details["participant_cleanup_confirmed"])
        preserved = await self.reconcile()
        self.assertTrue(preserved["preservation_confirmed"])
        self.assertFalse(preserved["acquisition_preservation_eligible"])
        summary = preserved["compilation_summary"]
        self.assertFalse(summary["stage_a_complete"])
        self.assertFalse(summary["archive_closed"])
        self.assertFalse(summary["kill_preservation"]["complete_receipt_confirmed"])
        self.assertTrue(any(item.get("participant") == self.node.to_dict()
            and item.get("cleanup_confirmed") is False for item in summary["kill_preservation"]["uncertainties"]))
        record = preserved["session_record"]
        self.assertEqual(record["final_session_status"]["state"], "aborted")
        self.assertEqual(record["experiment_lifecycle_evidence"][-1]["event_type"], "experiment_abort")
        artifact, = preserved["artifact_collection_handoff"]["artifacts"]
        scientific = Path(artifact["artifact_manifest"]["local_storage_path"])
        row, = [json.loads(line) for line in scientific.read_bytes().splitlines()]
        self.assertEqual(row["value"], 1)
        before = self.products()
        released = await self.controller.release_session(communication=self.communication, result_window_s=2)
        self.assertFalse(released.succeeded)
        self.assertEqual(self.controller.get_status()["session_state"], "aborted")
        self.assertEqual(self.products(), before)

    async def test_lost_preservation_reply_and_owner_restart_reuse_finalized_products(self):
        lost_reply = self.context.Event()
        await self.running(lost_reply=lost_reply)
        result = await self.normal_stop()
        self.assertTrue(lost_reply.is_set(), result.error)
        self.assertFalse(result.succeeded)
        self.assertIn("preserve_session_terminal_record", result.error)
        self.assertFalse((await self.controller.release_session(
            communication=self.communication, result_window_s=2)).succeeded)
        before = self.products()
        journal = self.root / "journals" / f"session_{self.sid}.jsonl"
        original_journal = journal.read_bytes()
        await self.stop_worker(self.owner_worker)
        await self.start_worker(run_closeout_owner, self.url, str(self.root), None)
        restarted_controller = Controller()
        preserved = await self.reconcile(restarted_controller)
        self.assertTrue(preserved["acquisition_preservation_eligible"])
        self.assertEqual(preserved["session_record"]["final_session_status"]["state"], "completed")
        self.assertIsNone(restarted_controller.get_status()["session_state"])
        result = await self.normal_stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.products(), before)
        self.assertEqual(journal.read_bytes(), original_journal)
        released = await self.controller.release_session(communication=self.communication, result_window_s=5)
        self.assertTrue(released.succeeded, released.error)
        self.assertEqual(self.products(), before)
        self.assertEqual(journal.read_bytes(), original_journal)

