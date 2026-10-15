"""Stage A through real Controller, Ingestor, and persistence owners."""

import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, NatsIngestorCommunication,
    PersistentStorageManager, RuntimeEvidenceMessage,
)
from tests import test_producer_publication_completion as producers


class AcquisitionStageArchivalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.producer = producers.ProducerPublicationCompletionTests()
        self.producer.setUp()
        self.addCleanup(self.producer.doCleanups)
        self.fixture = self.producer.fixture
        self.storage = PersistentStorageManager(self.fixture.root)
        self.fixture.controller = Controller(ingestor=self.fixture.ingestor,
            storage_manager=self.storage, synchronization_manager=self.fixture.sync)

    async def prepare(self):
        self.session_id = await self.producer.running(two=False)
        self.fixture.controller.process_health_interpretation(producers.interpretation())
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        published = await self.producer.marker()
        self.assertTrue(published.succeeded, published.error)
        self.marker = RuntimeEvidenceMessage.from_dict(published.details["marker"])
        self.receiver = self.fixture.ingestor_handler
        self.durable = next(iter(self.fixture.broker.consumers))
        topic = f"messages.{self.session_id}.evidence.*.*.*"
        self.fixture.broker.callbacks[self.durable] = next(
            subscription.callback for subscription in self.fixture.broker.subscriptions
            if subscription.subject == topic)

    async def acknowledge(self, *, omit_first=False):
        sequences = sorted(self.fixture.broker.records)
        for index, sequence in enumerate(sequences):
            if index == 0 and omit_first:
                with self.assertRaises(ConnectionError):
                    await self.fixture.broker.deliver(self.durable, sequence, acknowledge=False)
            else:
                await self.fixture.broker.deliver(self.durable, sequence)

    async def archive(self):
        return await self.fixture.controller.archive_acquisition_evidence(communication=self.receiver)

    def read_products(self, result):
        paths = {name: Path(path) for name, path in result.details["paths"].items()}
        evidence = [json.loads(line) for line in paths["runtime_evidence"].read_text().splitlines()]
        audit = [json.loads(line) for line in paths["ingest_audit"].read_text().splitlines()]
        summary = json.loads(paths["compilation_summary"].read_text())
        record = self.storage.read_session_record(paths["session_record"])
        return paths, evidence, audit, summary, record

    async def test_verified_stage_a_persists_all_products_and_leaves_archive_open(self):
        await self.prepare()
        intake = self.fixture.ingestor
        note = RuntimeEvidenceMessage("transient-note", self.session_id, "runtime_note", "node-a", {})
        intake.receive_runtime_evidence(note)
        intake.receive_runtime_evidence(self.marker)
        rejected = intake.receive_runtime_evidence(RuntimeEvidenceMessage("", self.session_id, "runtime_note", "node-a", {}))
        self.assertFalse(rejected.accepted)
        local = RuntimeEvidenceMessage("local-recovery", self.session_id, "ingestor_recovery_evidence", "ingestor", {}, True)
        intake.receive_runtime_evidence(local)
        await self.acknowledge()
        expected = intake.compile_persistent_runtime_evidence()
        journal_before = intake.recovery_journal_path.read_bytes()
        result = await self.archive()
        self.assertTrue(result.succeeded, result.error)
        paths, evidence, audit, summary, record = self.read_products(result)
        directory = self.fixture.root / f"session_{self.session_id}"
        self.assertEqual(paths["session_record"], directory / "session_record_final.json")
        self.assertEqual(paths["runtime_evidence"], directory / "evidence/runtime_evidence.jsonl")
        self.assertEqual(evidence, [m.to_dict() for m in expected["runtime_evidence"]])
        self.assertEqual(audit, [a.to_dict() for a in expected["ingest_audit"]])
        self.assertNotIn(note.to_dict(), evidence)
        self.assertIn(local.to_dict(), evidence)
        self.assertTrue(summary["stage_a_complete"])
        self.assertIs(summary["archive_closed"], False)
        self.assertEqual(summary["runtime_evidence_count"], len(evidence))
        self.assertEqual(summary["ingest_audit_count"], len(audit))
        self.assertEqual(summary["acquisition_evidence_completion"]["evidence_id"], self.marker.evidence_id)
        self.assertEqual(summary["runtime_evidence_origins"]["ingestor"], [m["evidence_id"] for m in evidence])
        self.assertEqual(record["accepted_session_config"]["session_id"], self.session_id)
        self.assertEqual(record["runtime_evidence"], [])
        self.assertEqual(record["runtime_evidence_audit"], [])
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(intake.recovery_journal_path.read_bytes(), journal_before)
        self.assertIsNotNone(self.storage.get_acquisition_stage_preservation_confirmation(self.session_id))

    async def test_incomplete_acknowledgment_refuses_writes_and_explicit_retry_succeeds(self):
        await self.prepare()
        await self.acknowledge(omit_first=True)
        result = await self.archive()
        self.assertFalse(result.succeeded)
        self.assertIn("receipt is unconfirmed", result.error)
        self.assertFalse((self.fixture.root / f"session_{self.session_id}/evidence").exists())
        await self.acknowledge()
        retry = await self.archive()
        self.assertTrue(retry.succeeded, retry.error)

    async def test_verified_receipt_cannot_substitute_for_a_lost_current_journal(self):
        await self.prepare()
        await self.acknowledge()
        verify = self.receiver.verify_acquisition_evidence_receipt

        async def lose_journal(marker):
            receipt = await verify(marker)
            self.assertTrue(receipt["durable_receipt_confirmed"])
            self.fixture.ingestor.recovery_journal_path.write_bytes(b"")
            return receipt

        with patch.object(self.receiver, "verify_acquisition_evidence_receipt", new=lose_journal):
            result = await self.archive()
        self.assertFalse(result.succeeded)
        self.assertIn("journal coverage is unconfirmed", result.error)
        self.assertFalse((self.fixture.root / f"session_{self.session_id}/evidence").exists())

    async def test_partial_archive_write_remains_unconfirmed_and_requires_authorized_recovery(self):
        await self.prepare()
        await self.acknowledge()
        original_open = Path.open

        def fail_audit(path, *args, **kwargs):
            if path.name == "ingest_audit.jsonl" and args and args[0] == "w":
                raise OSError("audit write unavailable")
            return original_open(path, *args, **kwargs)

        journal = self.fixture.ingestor.recovery_journal_path.read_bytes()
        with patch.object(Path, "open", new=fail_audit):
            result = await self.archive()
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.session_id))
        self.assertEqual(self.fixture.ingestor.recovery_journal_path.read_bytes(), journal)
        retry = await self.archive()
        self.assertFalse(retry.succeeded)
        self.assertIn("authorized recovery", retry.error)
        self.assertEqual(self.fixture.controller.get_status()["session_id"], self.session_id)

    async def test_failed_final_record_cannot_confirm_stage_a(self):
        await self.prepare()
        await self.acknowledge()
        with patch.object(self.storage, "write_final_session_record", side_effect=OSError("record unavailable")):
            result = await self.archive()
        self.assertFalse(result.succeeded)
        summary = json.loads((self.fixture.root / f"session_{self.session_id}/evidence/compilation_summary.json").read_text())
        self.assertNotIn("stage_a_complete", summary)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.session_id))
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")

    async def test_failed_stage_summary_persistence_cannot_confirm_stage_a(self):
        await self.prepare()
        await self.acknowledge()
        write = self.storage._write_record_contents

        def fail_summary(path, contents):
            if path.name == "compilation_summary.json":
                raise OSError("summary fsync unavailable")
            write(path, contents)

        with patch.object(self.storage, "_write_record_contents", side_effect=fail_summary):
            result = await self.archive()
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.session_id))

    async def test_current_corrupt_archive_is_not_repaired_by_stage_a_retry(self):
        await self.prepare()
        await self.acknowledge()
        result = await self.archive()
        self.assertTrue(result.succeeded, result.error)
        path = Path(result.details["paths"]["ingest_audit"])
        path.write_text("[]\n")
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.session_id))
        retry = await self.archive()
        self.assertFalse(retry.succeeded)
        self.assertEqual(path.read_text(), "[]\n")

    async def test_repeated_healthy_stage_a_preserves_identity_and_open_status(self):
        await self.prepare()
        await self.acknowledge()
        first = await self.archive()
        second = await self.archive()
        self.assertTrue(first.succeeded, first.error)
        self.assertTrue(second.succeeded, second.error)
        self.assertEqual(self.read_products(first)[1:4], self.read_products(second)[1:4])
        self.assertEqual(self.producer.published("acquisition_evidence_completion"), [self.marker.to_dict()])

    async def test_cancellation_and_overlap_during_receipt_verification_do_not_write(self):
        await self.prepare()
        await self.acknowledge()
        entered, resume = asyncio.Event(), asyncio.Event()
        verify = self.receiver.verify_acquisition_evidence_receipt

        async def pause(marker):
            entered.set()
            await resume.wait()
            return await verify(marker)

        with patch.object(self.receiver, "verify_acquisition_evidence_receipt", new=pause):
            task = asyncio.create_task(self.archive())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertFalse((await self.archive()).succeeded)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse((self.fixture.root / f"session_{self.session_id}/evidence").exists())
            finally:
                resume.set()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue((await self.archive()).succeeded)

    async def test_receiver_for_another_ingestor_cannot_authorize_session_archival(self):
        await self.prepare()
        other = NatsIngestorCommunication(self.receiver._boundary, InMemoryIngestor())
        result = await self.fixture.controller.archive_acquisition_evidence(communication=other)
        self.assertFalse(result.succeeded)
        self.assertFalse((self.fixture.root / f"session_{self.session_id}/evidence").exists())
