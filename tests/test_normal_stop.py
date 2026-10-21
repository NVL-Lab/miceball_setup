"""Normal Stop composes the validated producer, receipt, archival, and handoff owners."""

import asyncio
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import Controller, InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage, ScientificOutputSelection, RuntimeParticipant, NatsStorageManagerCommunication
from tests import test_producer_publication_completion as producers
from tests.test_distributed_session_closeout import CloseoutBroker
from tests.test_session_launch import _Boundary


class NormalStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.producer = producers.ProducerPublicationCompletionTests()
        self.producer.addCleanup = self.addCleanup
        self.producer.addAsyncCleanup = self.addAsyncCleanup
        self.producer.setUp()
        self.fixture = self.producer.fixture
        self.fixture.broker = CloseoutBroker()
        self.fixture.communication = producers.NatsControllerCommunication(
            _Boundary("controller", "controller", self.fixture.broker))
        self.storage = PersistentStorageManager(self.fixture.root)
        self.storage_participant = RuntimeParticipant("storage_manager", "storage")
        self.fixture.ingestor = InMemoryIngestor(storage_manager=self.storage,
            recovery_journal_root=self.fixture.root / "journals")
        self.fixture.controller = Controller()
        services = self.fixture.services

        async def independent_services(**options):
            await services(**options)
            await NatsStorageManagerCommunication(
                _Boundary("storage_manager", "storage", self.fixture.broker),
                self.storage).subscribe_commands()

        self.fixture.services = independent_services

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
            communication=self.fixture.communication,
            storage_participant=RuntimeParticipant("storage_manager", "storage"),
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
        before = self.products()
        evidence_before = [item for item in events if item[1].get("evidence_type")]
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(self.products(), before)
        self.assertEqual([item for item in events if item[1].get("evidence_type")], evidence_before)
        self.assertTrue((await self.fixture.controller.release_session(
            communication=self.fixture.communication, result_window_s=1)).succeeded)
        restored = PersistentStorageManager(self.fixture.root)
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
        self.assertFalse((await self.fixture.controller.release_session(communication=self.fixture.communication, result_window_s=1)).succeeded)

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
            self.assertFalse((await self.fixture.controller.release_session(communication=self.fixture.communication, result_window_s=1)).succeeded)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertTrue((await self.stop()).succeeded)

    async def test_changed_current_archive_between_handoff_and_completion_is_rejected(self):
        await self.running()
        preserve = self.storage.write_artifact_collection_handoff

        def corrupt(*args, **kwargs):
            result = preserve(*args, **kwargs)
            path = self.fixture.root / f"session_{self.sid}/evidence/ingest_audit.jsonl"
            path.write_text("[]\n")
            return result

        with patch.object(self.storage, "write_artifact_collection_handoff", side_effect=corrupt):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))

    async def test_cancellation_before_marker_cannot_fall_back_to_legacy_completion(self):
        await self.running()
        entered, proceed = asyncio.Event(), asyncio.Event()
        request = self.fixture.communication.request_runtime_command

        async def paused(participant, command_type, *args, **kwargs):
            if participant.component_type == "synchronization_manager" and command_type == "stop_runtime":
                entered.set()
                await proceed.wait()
            return await request(participant, command_type, *args, **kwargs)

        with patch.object(self.fixture.communication, "request_runtime_command", new=paused):
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
        self.assertFalse((await self.fixture.controller.release_session(communication=self.fixture.communication, result_window_s=1)).succeeded)
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

    async def test_q019_finalization_reuses_stage_a_without_rewriting_summary(self):
        await self.running()
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.producer.marker()).succeeded)
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertFalse((await self.fixture.controller.archive_acquisition_evidence(communication=self.receiver)).succeeded)
        self.assertFalse(self.fixture.controller.preserve_artifact_collection_handoff().succeeded)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.products()
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(self.products(), before)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "completed")

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
