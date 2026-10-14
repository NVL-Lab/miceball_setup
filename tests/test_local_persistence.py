"""Retained intake persists through distinct owners in one process."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope, InMemoryIngestor, PersistentStorageManager,
    RuntimeEvidenceMessage,
)
from tests import test_nats_persistence as persistence_fixtures


class LocalPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root / "records.jsonl", component_id="storage")
        self.ingestor = InMemoryIngestor(self.storage, session_id="session",
            recovery_journal_path=self.root / "journal.jsonl", component_id="intake",
            correlated_persistence=True)
        self.envelope = AcquisitionRecordEnvelope("session", "device", "event",
            [{"session_time_s": 1.0, "value": 7}], "node")
        self.assertTrue(self.ingestor.receive_envelope(self.envelope).accepted)

    async def persist(self, command_id="write", envelope=None):
        return await self.ingestor.persist_accepted_envelope(
            envelope or self.envelope, command_id=command_id)

    async def test_local_persistence_and_retry_use_exact_owner_readback(self):
        self.assertEqual(self.storage.read_envelopes(), ())
        first = await self.persist()
        self.assertTrue(first["durable_persistence_confirmed"])
        self.assertEqual(first["envelope"], self.envelope.to_dict())
        self.assertEqual((first["requester_id"], first["storage_manager_id"]), ("intake", "storage"))
        before = self.storage.records_path.read_bytes()
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual(self.storage.records_path.read_bytes(), before)
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))
        self.assertEqual(len(self.ingestor.ingest_audit), 1)

    async def test_restarted_pair_reconfirms_stable_command(self):
        evidence = RuntimeEvidenceMessage("note", "session", "note", "node", {}, True)
        self.ingestor.receive_runtime_evidence(evidence)
        await self.persist()
        before = self.storage.records_path.read_bytes()
        self.storage = PersistentStorageManager(self.storage.records_path, component_id="storage")
        self.ingestor = InMemoryIngestor(self.storage, session_id="session",
            recovery_journal_path=self.root / "journal.jsonl", component_id="intake",
            correlated_persistence=True)
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(evidence))
        # Acquisition intake reconstruction is separate; the caller resupplies intake.
        self.ingestor.receive_envelope(self.envelope)
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual(self.storage.records_path.read_bytes(), before)

    async def test_conflicting_command_is_refused_without_changing_history(self):
        await self.persist()
        before = self.storage.records_path.read_bytes()
        other = AcquisitionRecordEnvelope("session", "device", "event",
            [{"session_time_s": 2.0, "value": 8}], "node")
        self.assertTrue(self.ingestor.receive_envelope(other).accepted)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            await self.persist(envelope=other)
        self.assertEqual(self.storage.records_path.read_bytes(), before)
        self.assertTrue((await self.persist("other", other))["durable_persistence_confirmed"])

    async def test_concurrent_requests_append_once(self):
        def write():
            return asyncio.run(self.persist())
        first, second = await asyncio.gather(asyncio.to_thread(write), asyncio.to_thread(write))
        self.assertTrue(first["durable_persistence_confirmed"])
        self.assertTrue(second["durable_persistence_confirmed"])
        self.assertEqual(sum(result["already_persisted"] for result in (first, second)), 1)
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))

    async def test_binding_abort_waits_for_local_persistence(self):
        entered, finish, abort_requested, persisted, aborted = (Event() for _ in range(5))
        owner_persist = self.storage.persist_envelope

        def coordinated_persist(*args, **kwargs):
            entered.set()
            if not finish.wait(5):
                raise TimeoutError("Persistence coordination was not released")
            confirmation = owner_persist(*args, **kwargs)
            persisted.set()
            return confirmation

        def abort_binding():
            abort_requested.set()
            result = self.ingestor.abort_session_initialization("session")
            self.assertTrue(persisted.is_set(), "Binding abort overtook owner persistence")
            aborted.set()
            return result

        # Pause the owner call, not its locks; both threads execute real owner methods.
        with ThreadPoolExecutor(max_workers=2) as workers:
            with patch.object(self.storage, "persist_envelope", side_effect=coordinated_persist):
                writing = workers.submit(lambda: asyncio.run(self.persist()))
                try:
                    self.assertTrue(entered.wait(5))
                    aborting = workers.submit(abort_binding)
                    self.assertTrue(abort_requested.wait(5))
                    self.assertFalse(aborted.is_set())
                    self.assertFalse(persisted.is_set())
                finally:
                    finish.set()
                confirmation = writing.result(timeout=5)
                self.assertTrue(aborting.result(timeout=5))

        self.assertTrue(confirmation["durable_persistence_confirmed"])
        self.assertEqual(confirmation["session_id"], "session")
        self.assertTrue(aborted.is_set())
        before = self.storage.records_path.read_bytes()
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))
        with self.assertRaisesRegex(RuntimeError, "prepared Ingestor Session"):
            await self.persist()
        self.assertEqual(self.storage.records_path.read_bytes(), before)

    async def test_failed_durability_retains_intake_for_idempotent_retry(self):
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("fsync unavailable")):
            with self.assertRaisesRegex(OSError, "fsync unavailable"):
                await self.persist()
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))

    async def test_unconfirmed_readback_retains_intake_without_duplicate_retry(self):
        with patch.object(self.storage, "get_envelope_persistence_confirmation", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                await self.persist()
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))

    async def test_damaged_correlation_cannot_be_retried_or_repaired(self):
        await self.persist()
        original = json.loads(self.storage.records_path.read_text())
        for metadata in (None, {}, {"command_id": "write", "source_id": "intake"}):
            with self.subTest(metadata=metadata):
                self.storage.records_path.write_text(json.dumps({**original,
                    "persistence_command": metadata}) + "\n")
                before = self.storage.records_path.read_bytes()
                with self.assertRaisesRegex(ValueError, "persistence_command correlation"):
                    await self.persist()
                self.assertEqual(self.storage.records_path.read_bytes(), before)

    async def test_legacy_history_is_preserved_by_correlated_writes(self):
        self.storage.store_envelopes((self.envelope,))
        legacy = self.storage.records_path.read_bytes()
        await self.persist()
        before = self.storage.records_path.read_bytes()
        self.assertTrue(before.startswith(legacy))
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual(self.storage.records_path.read_bytes(), before)
        self.assertEqual(self.storage.read_envelopes(), (self.envelope, self.envelope))

    async def test_closed_archive_rejects_new_write_but_allows_identical_readback(self):
        await self.persist()
        persistence_fixtures.NatsPersistenceTests.preserve_session(self)
        self.storage.close_session_evidence_archive("session")
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with self.assertRaises((ValueError, RuntimeError)):
            await self.persist("late")
        self.assertTrue((await self.persist())["already_persisted"])
        self.assertEqual({str(path): path.read_bytes() for path in self.root.rglob("*")
                          if path.is_file()}, before)

    async def test_local_mode_refuses_transport_or_missing_identity(self):
        with self.assertRaises(ValueError):
            await self.ingestor.persist_accepted_envelope(self.envelope)
        with self.assertRaises(ValueError):
            await self.ingestor.persist_accepted_envelope(self.envelope,
                command_id="write", persist=self.persist)
        self.assertEqual(self.storage.read_envelopes(), ())

    async def test_unconfirmed_journal_blocks_local_persistence(self):
        evidence = RuntimeEvidenceMessage("note", "session", "note", "node", {}, True)
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("journal unavailable")):
            with self.assertRaisesRegex(OSError, "journal unavailable"):
                self.ingestor.receive_runtime_evidence(evidence)
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(evidence))
        with self.assertRaisesRegex(RuntimeError, "prepared Ingestor Session"):
            await self.persist()
        self.assertEqual(self.storage.read_envelopes(), ())
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))


if __name__ == "__main__":
    unittest.main()
