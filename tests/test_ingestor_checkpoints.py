"""Verified archival boundaries accelerate normal Ingestor recovery."""

import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage
from tests.test_journal_retirement import CloseoutFixture


class IngestorCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journal = self.root / "framework.jsonl"
        self.checkpoint = self.root / "framework.jsonl.checkpoint.json"
        self.clock = patch("lab_sync_acquisition.storage.time", return_value=
            datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.restart()

    def restart(self):
        self.storage = PersistentStorageManager(self.root / "archive")
        self.intake = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.journal)

    def accept(self, identity, persistent=True, payload=None):
        message = RuntimeEvidenceMessage(identity, None, "warning", "source", payload or {}, persistent)
        self.intake.receive_runtime_evidence(message)
        return message

    def archive(self):
        return self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())

    def test_archive_qualifies_checkpoint_and_recovers_suffix_and_exact_duplicates(self):
        original = self.accept("persistent")
        temporary = self.accept("temporary", False)
        self.intake.receive_runtime_evidence(original)
        self.archive()
        state = json.loads(self.checkpoint.read_bytes())["state"]
        self.assertEqual(state["boundary"], self.journal.stat().st_size)
        self.assertEqual(len(state["audit"]), 3)
        self.accept("suffix")
        self.restart()
        self.assertEqual([m.evidence_id for m in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]][:2],
                         ["persistent", "suffix"])
        self.assertEqual(self.intake.receive_runtime_evidence(temporary).reason, "already_accepted")
        self.assertEqual(self.intake.receive_runtime_evidence(original).reason, "already_accepted")
        with self.assertRaises(ValueError):
            self.accept("persistent", payload={"changed": True})
        audit = self.intake.compile_framework_runtime_evidence()["ingest_audit"]
        self.assertEqual([a.ingest_order for a in audit], list(range(1, len(audit) + 1)))

    def test_valid_checkpoint_skips_prefix_reads_during_restart_and_continuation(self):
        self.accept("original")
        self.archive()
        boundary = self.journal.stat().st_size
        opened = Path.open
        reads = []

        class Reader:
            def __init__(self, stream):
                self.stream = stream
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def readline(self, *args):
                reads.append(self.stream.tell())
                if self.stream.tell() < boundary:
                    raise AssertionError("Completed journal prefix was replayed")
                return self.stream.readline(*args)
            def __iter__(self):
                return self
            def __next__(self):
                line = self.readline()
                if not line:
                    raise StopIteration
                return line

        def observe(path, *args, **kwargs):
            stream = opened(path, *args, **kwargs)
            return Reader(stream) if path == self.journal and args and args[0] in ("rb", "r+b") else stream

        with patch.object(Path, "open", observe):
            self.restart()
            self.now.return_value = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
            self.assertIsNotNone(self.intake.continue_framework_evidence_archive())
        self.assertTrue(reads)
        self.assertTrue(all(position >= boundary for position in reads))

    def test_failed_archive_does_not_advance_checkpoint(self):
        self.accept("first")
        self.archive()
        previous = self.checkpoint.read_bytes()
        self.accept("second")
        original = self.intake.accept_framework_write_record

        def interrupt(record):
            if record["kind"] == "completion":
                raise OSError("Interrupted completion")
            return original(record)

        with patch.object(self.intake, "accept_framework_write_record", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.archive()
        self.assertEqual(self.checkpoint.read_bytes(), previous)
        self.restart()
        self.now.return_value = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
        self.assertIsNotNone(self.intake.continue_framework_evidence_archive())
        records = self.intake.read_framework_write_records()
        self.assertEqual({r["write_attempt_id"] for r in records if r["kind"] == "intent"},
                         {r["write_attempt_id"] for r in records if r["kind"] == "completion"})

    def test_interrupted_publication_retains_previous_checkpoint(self):
        self.accept("first")
        self.archive()
        previous = self.checkpoint.read_bytes()
        self.accept("second")
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=OSError("Interrupted publication")):
            with self.assertRaises(OSError):
                self.archive()
        self.assertEqual(previous, self.checkpoint.read_bytes())
        self.assertEqual(list(self.root.glob(".incomplete-checkpoint-*")), [])
        self.restart()
        self.assertIn("second", [r.evidence_id for r in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]])

    def test_missing_corrupt_and_inconsistent_checkpoints_fall_back(self):
        self.accept("original")
        self.archive()
        good = self.checkpoint.read_bytes()
        for damaged in (b"{", b"null", b"[]", b'{"state":{}}'):
            with self.subTest(damaged=damaged):
                self.checkpoint.write_bytes(damaged)
                self.restart()
                self.assertIn("original", [r.evidence_id for r in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]])
        self.checkpoint.write_bytes(good)
        self.checkpoint.unlink()
        self.restart()
        self.assertIn("original", [r.evidence_id for r in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]])

    def test_replaced_journal_cannot_use_old_checkpoint(self):
        self.accept("original")
        self.archive()
        contents = self.journal.read_bytes()
        self.journal.rename(self.root / "previous.jsonl")
        self.journal.write_bytes(contents)
        self.restart()
        self.assertIn("original", [r.evidence_id for r in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]])

    def test_corrupt_completed_suffix_fails_closed(self):
        self.accept("original")
        self.archive()
        with self.journal.open("ab") as stream:
            stream.write(b'{"damaged":\n')
        with self.assertRaisesRegex(ValueError, "corrupt completed"):
            self.restart()

    def test_interrupted_suffix_recovers_and_old_month_is_immutable(self):
        self.accept("original")
        paths = self.archive()
        original = {name: path.read_bytes() for name, path in paths.items()}
        with self.journal.open("ab") as stream:
            stream.write(b'{"runtime_evidence":')
        self.restart()
        self.now.return_value = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
        self.assertIsNotNone(self.intake.continue_framework_evidence_archive())
        self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, original)
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())

    def test_intake_alone_does_not_create_checkpoint(self):
        self.accept("unarchived")
        self.assertFalse(self.checkpoint.exists())

    def test_inconsistent_checkpoint_state_cannot_hide_valid_journal_history(self):
        self.accept("original")
        self.archive()
        good = json.loads(self.checkpoint.read_bytes())
        from copy import deepcopy
        for field, value in (("boundary", self.journal.stat().st_size + 1), ("audit", []),
                             ("writes", []), ("journal_identity", [0, 0]),
                             ("content", []), ("qualification", {})):
            with self.subTest(field=field):
                damaged = deepcopy(good)
                damaged["state"][field] = value
                damaged["sha256"] = hashlib.sha256(json.dumps(damaged["state"], sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                self.checkpoint.write_text(json.dumps(damaged))
                self.restart()
                self.assertIn("original", [m.evidence_id for m in
                    self.intake.compile_framework_runtime_evidence()["runtime_evidence"]])

    def test_explicit_archive_integrity_still_detects_physical_changes(self):
        self.accept("original")
        paths = self.archive()
        self.restart()
        self.intake.continue_framework_evidence_archive()
        paths["runtime_evidence"].write_bytes(b"damaged\n")
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())


class SessionCheckpointTests(CloseoutFixture, unittest.TestCase):
    def test_confirmed_session_archival_recovers_finality_without_replaying_prefix(self):
        self.preserve(release=False)
        checkpoint = self.journal.with_suffix(".jsonl.checkpoint.json")
        self.assertTrue(checkpoint.exists())
        original = self.journal.read_bytes()
        restored = InMemoryIngestor(PersistentStorageManager(self.storage_root),
            session_id="saved", recovery_journal_path=self.journal)
        self.assertEqual(restored.finalized_acquisition_intake("saved"),
                         self.intake.finalized_acquisition_intake("saved"))
        self.assertEqual(restored.runtime_evidence_audit, self.intake.runtime_evidence_audit)
        self.assertEqual(original, self.journal.read_bytes())

    def test_successful_completion_keeps_closed_session_admission_and_retirement(self):
        self.preserve()
        checkpoint = self.journal.with_suffix(".jsonl.checkpoint.json")
        state = json.loads(checkpoint.read_bytes())["state"]
        self.assertEqual(state["qualification"]["state"], "completed")
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        fresh = InMemoryIngestor(PersistentStorageManager(self.storage_root), recovery_journal_root=self.journals)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            fresh.prepare_session("saved")

    def test_partial_kill_checkpoint_retains_uncertain_obligations(self):
        self.preserve(kill=True, release=False)
        restored = InMemoryIngestor(PersistentStorageManager(self.storage_root),
            session_id="saved", recovery_journal_path=self.journal)
        self.assertIsNone(restored.finalized_acquisition_intake("saved"))
        # Restart evidence extends the still-open Kill boundary; it must be
        # preserved before the old archive can confirm current closeout.
        with self.assertRaisesRegex(RuntimeError, "does not cover intake"):
            restored.read_session_closeout("saved")
        with self.assertRaises(RuntimeError):
            restored.release_session("saved")

    def test_failed_session_archival_cannot_create_checkpoint(self):
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("Unavailable archive")):
            with self.assertRaises(OSError):
                self.preserve(release=False)
        self.assertFalse(self.journal.with_suffix(".jsonl.checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
