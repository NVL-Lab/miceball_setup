"""Normal Stop composes the validated producer, receipt, archival, and handoff owners."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope, Controller, InMemoryIngestor,
    PersistentStorageManager, ScientificOutputSelection,
)
from tests import test_producer_publication_completion as producers


class NormalStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.producer = producers.ProducerPublicationCompletionTests()
        self.producer.setUp()
        self.addCleanup(self.producer.doCleanups)
        self.fixture = self.producer.fixture
        self.storage = PersistentStorageManager(self.fixture.root / "accepted_records.jsonl")
        self.fixture.controller = Controller(ingestor=self.fixture.ingestor,
            storage_manager=self.storage, synchronization_manager=self.fixture.sync)

    async def asyncTearDown(self):
        if self.fixture.controller.get_status()["session_state"] == "running":
            await self.fixture.controller.stop_launched_session()

    async def running(self, *, two=False):
        self.sid = await self.producer.running(two=two, optional=two)
        self.connect_receipt()

    def connect_receipt(self):
        self.receiver = self.fixture.ingestor_handler
        self.durable = next(iter(self.fixture.broker.consumers))
        topic = f"messages.{self.sid}.evidence.*.*.*"
        self.fixture.broker.callbacks[self.durable] = next(
            s.callback for s in self.fixture.broker.subscriptions if s.subject == topic)

        async def accept(subject, payload):
            if payload.get("evidence_type") == "acquisition_evidence_completion":
                await self.acknowledge()

        self.fixture.broker.after_publication = accept

    async def acknowledge(self):
        for sequence in sorted(self.fixture.broker.records):
            await self.fixture.broker.deliver(self.durable, sequence)

    async def stop(self):
        return await self.fixture.controller.normal_stop_session(
            communication=self.fixture.communication, receiving=self.receiver,
            result_window_s=1)

    def products(self):
        directory = self.fixture.root / f"session_{self.sid}"
        return {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}

    async def test_successful_two_node_stop_preserves_before_completion_and_never_collects(self):
        await self.running(two=True)
        self.fixture.controller.process_health_interpretation(producers.interpretation())
        self.fixture.sync.create_and_activate_mapping(self.sid, "node-a", 0, 0, 1, "initial")
        with patch.object(self.storage, "collect_saved_artifacts", side_effect=AssertionError("unexpected collection")), \
                patch.object(self.storage, "close_session_evidence_archive", side_effect=AssertionError("unexpected closure")):
            result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "completed")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertFalse(self.fixture.sync.is_running)
        handoff = self.storage.read_artifact_collection_handoff(self.sid)
        self.assertEqual(len(handoff["artifacts"]), 2)
        self.assertTrue(all(a["artifact_manifest"]["lifecycle_state"] == "finalized" for a in handoff["artifacts"]))
        summary = self.storage.get_acquisition_stage_preservation_confirmation(self.sid)["compilation_summary"]
        self.assertTrue(summary["stage_a_complete"])
        self.assertFalse(summary["archive_closed"])
        events = self.fixture.broker.events
        marker_index = next(i for i, (_, p) in enumerate(events) if p.get("evidence_type") == "acquisition_evidence_completion")
        for node in self.fixture.nodes.values():
            self.assertIsNone(node.reserved_for_session_id)
            self.assertFalse(node.status()["is_running"])
            final_index = next(i for i, (_, p) in enumerate(events) if p.get("evidence_type") == "artifact_manifest"
                and p["source_id"] == node.node_id and p["payload"]["lifecycle_state"] == "finalized")
            self.assertLess(final_index, marker_index)
        before, event_count = self.products(), len(events)
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(self.products(), before)
        self.assertEqual(len(events), event_count)
        self.assertTrue(self.fixture.sync.release_session(self.sid, ingestor=self.fixture.ingestor))
        self.assertTrue((await self.fixture.controller.release_session()).succeeded)
        self.assertTrue(self.fixture.ingestor.release_session(self.sid, storage_manager=self.storage))
        restored = PersistentStorageManager(self.fixture.root / "accepted_records.jsonl")
        self.assertEqual(restored.read_artifact_collection_handoff(self.sid), handoff)

    async def test_incomplete_receipt_withholds_completion_and_explicit_retry_succeeds(self):
        await self.running()
        self.fixture.broker.after_publication = None
        failed = await self.stop()
        self.assertFalse(failed.succeeded)
        self.assertIn("receipt is unconfirmed", failed.error)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertFalse((self.fixture.root / f"session_{self.sid}/evidence").exists())
        commands = len(self.fixture.broker.commands)
        await self.acknowledge()
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(len(self.fixture.broker.commands), commands)
        self.assertEqual(len(self.producer.published("acquisition_evidence_completion")), 1)

    async def test_failed_producer_publication_cannot_complete_or_release_reservation(self):
        await self.running()

        async def fail(subject, payload):
            if payload.get("evidence_type") == "artifact_manifest" and payload["payload"]["lifecycle_state"] == "finalized":
                raise ConnectionError("finalized publication unavailable")

        self.fixture.broker.before_publication = fail
        result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.fixture.nodes["node-a"].reserved_for_session_id, self.sid)
        self.assertEqual(self.producer.published("acquisition_evidence_completion"), [])
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))

    async def test_partial_persistence_keeps_journal_binding_and_refuses_unsafe_retry(self):
        await self.running()
        with patch.object(self.storage, "write_final_session_record", side_effect=OSError("record unavailable")):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        journal = self.fixture.ingestor.recovery_journal_path.read_bytes()
        retry = await self.stop()
        self.assertFalse(retry.succeeded)
        self.assertEqual(self.fixture.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.assertFalse((await self.fixture.controller.release_session()).succeeded)

    async def test_handoff_interruption_retries_without_refinalizing_scientific_files(self):
        await self.running()
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("handoff interrupted")):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        manifests = [m["payload"] for m in self.storage.get_acquisition_stage_preservation_confirmation(self.sid)["runtime_evidence"]
                     if m["evidence_type"] == "artifact_manifest" and m["payload"]["lifecycle_state"] == "finalized"]
        files = {Path(m["local_storage_path"]): Path(m["local_storage_path"]).read_bytes() for m in manifests}
        self.assertTrue(files)
        commands = len(self.fixture.broker.commands)
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(len(self.fixture.broker.commands), commands)
        self.assertEqual({p: p.read_bytes() for p in files}, files)

    async def test_cancellation_and_overlap_preserve_stopping_binding_and_retry(self):
        await self.running()
        entered, proceed = asyncio.Event(), asyncio.Event()
        verify = self.receiver.verify_acquisition_evidence_receipt

        async def paused(marker):
            entered.set()
            await proceed.wait()
            return await verify(marker)

        with patch.object(self.receiver, "verify_acquisition_evidence_receipt", new=paused):
            task = asyncio.create_task(self.stop())
            await entered.wait()
            self.assertFalse((await self.stop()).succeeded)
            self.assertFalse(self.fixture.controller.finalize_session().succeeded)
            self.assertFalse((await self.fixture.controller.release_session()).succeeded)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertTrue((await self.stop()).succeeded)

    async def test_changed_current_archive_between_handoff_and_completion_is_rejected(self):
        await self.running()
        preserve = self.fixture.controller.preserve_artifact_collection_handoff

        def corrupt():
            result = preserve()
            self.assertTrue(result.succeeded, result.error)
            path = self.fixture.root / f"session_{self.sid}/evidence/ingest_audit.jsonl"
            path.write_text("[]\n")
            return result

        with patch.object(self.fixture.controller, "preserve_artifact_collection_handoff", side_effect=corrupt):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))

    async def test_cancellation_before_marker_cannot_fall_back_to_legacy_completion(self):
        await self.running()
        entered, proceed = asyncio.Event(), asyncio.Event()
        request = self.fixture.communication.request_command

        async def paused(participant, command_type, *args, **kwargs):
            if participant.component_type == "synchronization_manager" and command_type == "stop_runtime":
                entered.set()
                await proceed.wait()
            return await request(participant, command_type, *args, **kwargs)

        with patch.object(self.fixture.communication, "request_command", new=paused):
            task = asyncio.create_task(self.stop())
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        journal = self.fixture.ingestor.recovery_journal_path.read_bytes()
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.producer.published("acquisition_evidence_completion"), [])
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertFalse((await self.fixture.controller.release_session()).succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertEqual(self.fixture.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertFalse((self.fixture.root / f"session_{self.sid}/artifact_collection_handoff.json").exists())
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(len(self.producer.published("acquisition_evidence_completion")), 1)
        self.assertIsNotNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.assertEqual(self.storage.read_artifact_collection_handoff(self.sid)["session_id"], self.sid)

    async def test_failed_synchronization_confirmation_cannot_fall_back_to_legacy_completion(self):
        await self.running()
        self.fixture.broker.drop_results.add(("sync", "stop_runtime"))
        self.assertFalse((await self.stop()).succeeded)
        self.assertEqual(self.producer.published("acquisition_evidence_completion"), [])
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.fixture.broker.drop_results.clear()
        self.assertTrue((await self.stop()).succeeded)

    async def test_late_acquisition_intake_requires_preserved_record_coverage_before_completion(self):
        await self._exercise_late_acquisition_intake(accepted=True)

    async def test_late_rejected_acquisition_intake_requires_preserved_audit_before_completion(self):
        await self._exercise_late_acquisition_intake(accepted=False)

    async def _exercise_late_acquisition_intake(self, *, accepted):
        intake = InMemoryIngestor(self.storage,
            recovery_journal_root=self.fixture.root / "late-intake-journals")
        self.fixture.ingestor = intake
        self.fixture.controller = Controller(ingestor=intake, storage_manager=self.storage,
            synchronization_manager=self.fixture.sync)
        await self.running()
        preserve = self.fixture.controller.preserve_artifact_collection_handoff
        envelope = AcquisitionRecordEnvelope(self.sid, "node-a-device", "event",
            ({"session_time_s": 1.0, "event_type": "late-acquisition-event"},) if accepted else
            ({"event_type": "missing-session-time"},), source_node_id="node-a")
        baseline = {}
        with ThreadPoolExecutor(max_workers=1) as workers:
            def late_intake():
                result = preserve()
                self.assertTrue(result.succeeded, result.error)
                baseline.update(self.products())
                received = workers.submit(intake.receive_envelope, envelope).result(timeout=3)
                self.assertIs(received.accepted, accepted)
                return result

            with patch.object(self.fixture.controller, "preserve_artifact_collection_handoff", side_effect=late_intake):
                failed = await self.stop()
        self.assertFalse(failed.succeeded)
        self.assertIn("acquisition-envelope and audit preservation", failed.error)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(intake.session_id, self.sid)
        self.assertEqual(self.products(), baseline)
        record = self.storage.get_acquisition_stage_preservation_confirmation(self.sid)["session_record"]
        self.assertEqual(record["accepted_acquisition_envelopes"], [])
        self.assertEqual(record["ingest_audit_records"], [])
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertFalse((await self.fixture.controller.release_session()).succeeded)
        commands = len(self.fixture.broker.commands)
        journal = intake.recovery_journal_path.read_bytes()
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(len(self.fixture.broker.commands), commands)
        self.assertEqual(intake.recovery_journal_path.read_bytes(), journal)
        record = self.storage.get_acquisition_stage_preservation_confirmation(self.sid)["session_record"]
        self.assertEqual(record["accepted_acquisition_envelopes"], [item.to_dict() for item in intake.accepted_envelopes])
        self.assertEqual(record["ingest_audit_records"], [item.to_dict() for item in intake.ingest_audit])
        self.assertTrue((await self.fixture.controller.release_session()).succeeded)
        self.assertTrue(intake.release_session(self.sid, storage_manager=self.storage))
        self.assertTrue(self.fixture.sync.release_session(self.sid))

    async def test_q019_finalization_reuses_stage_a_without_rewriting_summary(self):
        await self.running()
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.producer.marker()).succeeded)
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertTrue((await self.fixture.controller.archive_acquisition_evidence(communication=self.receiver)).succeeded)
        self.assertTrue(self.fixture.controller.preserve_artifact_collection_handoff().succeeded)
        before = self.products()
        result = self.fixture.controller.finalize_session()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.products(), before)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "completed")

    async def test_active_experiment_ends_without_reopening_node_finalized_files(self):
        f = self.fixture
        await f.services()
        node, declaration, _ = await f.node()
        f.controller = Controller(node, ingestor=f.ingestor,
            storage_manager=self.storage, synchronization_manager=f.sync)
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.sid = launched.details["session_id"]
        self.connect_receipt()
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        started = f.controller.start_experiment("experiment", scientific_outputs=(
            ScientificOutputSelection(declaration.device_id, "node-a", "events"),))
        self.assertTrue(started.succeeded, started.error)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        record = self.storage.get_acquisition_stage_preservation_confirmation(self.sid)["session_record"]
        events = record["experiment_lifecycle_evidence"]
        self.assertEqual([e["event_type"] for e in events], ["experiment_start", "experiment_stop"])
        manifests = self.producer.published("artifact_manifest")
        self.assertEqual([m["payload"]["lifecycle_state"] for m in manifests], ["open", "finalized"])

    async def test_journal_accepted_marker_without_publication_ack_cannot_use_legacy_finalizer(self):
        await self.running()

        async def interrupted_ack(subject, payload):
            if payload.get("evidence_type") == "acquisition_evidence_completion":
                await self.acknowledge()
                raise ConnectionError("marker acknowledgment interrupted")

        self.fixture.broker.after_publication = interrupted_ack
        result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertTrue(any(m.evidence_type == "acquisition_evidence_completion"
                            for m in self.fixture.ingestor.accepted_runtime_evidence))
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertFalse((self.fixture.root / f"session_{self.sid}/evidence").exists())

    async def test_invalid_window_refuses_before_any_shutdown_work(self):
        await self.running()
        before = len(self.fixture.broker.commands)
        for window in (True, 0, float("nan")):
            result = await self.fixture.controller.normal_stop_session(
                communication=self.fixture.communication, receiving=self.receiver, result_window_s=window)
            self.assertFalse(result.succeeded)
        self.assertEqual(len(self.fixture.broker.commands), before)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "running")
        self.assertEqual(self.fixture.nodes["node-a"].reserved_for_session_id, self.sid)


if __name__ == "__main__":
    unittest.main()
