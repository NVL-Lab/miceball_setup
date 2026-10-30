"""Administrative UTC partitioning through journal-backed framework workflows."""

from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage


class MonthlyFrameworkArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journal = self.root / "framework.jsonl"
        self.storage = PersistentStorageManager(self.root / "storage")
        self.intake = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.journal)
        self.clock = patch("lab_sync_acquisition.storage.time", return_value=self.stamp(2025, 12))
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    @staticmethod
    def stamp(year, month):
        return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()

    def accept(self, identity, *, persistent=True):
        message = RuntimeEvidenceMessage(identity, None, "service_maintenance_evidence", "control",
            {"stop_attempt_id": "same-operation", "event_time": 1.0}, persistent)
        self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)
        return message

    def archive(self):
        return self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())

    @staticmethod
    def snapshot(directory):
        return {p.name: p.read_bytes() for p in directory.iterdir()}

    def restart(self):
        self.storage = PersistentStorageManager(self.root / "storage")
        self.intake = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.journal)
        return self.intake.continue_framework_evidence_archive()

    def test_december_to_january_keeps_operation_identity_and_prior_bytes(self):
        first = self.accept("stop-start")
        december = self.archive()["runtime_evidence"].parent
        prior = self.snapshot(december)
        self.now.return_value = self.stamp(2026, 1)
        last = self.accept("stop-completed")
        january = self.archive()["runtime_evidence"].parent
        self.assertEqual(december.name, "2025-12")
        self.assertEqual(january.name, "2026-01")
        self.assertEqual(prior, self.snapshot(december))
        rows = [json.loads(line) for line in (january / "runtime_evidence.jsonl").read_text().splitlines()]
        self.assertEqual(rows, [last.to_dict()])
        with self.intake.framework_preservation_guard(self.storage) as saved:
            self.assertEqual(saved["runtime_evidence"], [first.to_dict(), last.to_dict()])
            self.assertEqual({m["payload"]["stop_attempt_id"] for m in saved["runtime_evidence"]}, {"same-operation"})

    def test_exact_utc_boundary_uses_write_time_not_event_or_receipt(self):
        self.now.return_value = self.stamp(2026, 3) - 0.001
        self.accept("before")
        self.assertEqual(self.archive()["runtime_evidence"].parent.name, "2026-02")
        delayed = self.accept("delayed")
        audit = self.intake.compile_framework_runtime_evidence()["ingest_audit"][-1].to_dict()
        self.now.return_value = self.stamp(2026, 3)
        path = self.archive()["runtime_evidence"]
        self.assertEqual(path.parent.name, "2026-03")
        self.assertEqual(json.loads(path.read_text()), delayed.to_dict())
        self.assertEqual(json.loads(path.with_name("ingest_audit.jsonl").read_text()), audit)

    def test_repeated_restart_archives_new_recovery_evidence_only_in_current_month(self):
        original = self.accept("old")
        december = self.archive()["runtime_evidence"].parent
        prior = self.snapshot(december)
        for month in (1, 2, 3):
            self.now.return_value = self.stamp(2026, month)
            saved = self.restart()
            self.assertEqual(saved["runtime_evidence"][0], original.to_dict())
            self.assertEqual(len(saved["runtime_evidence"]), month + 1)
            self.assertEqual(saved["runtime_evidence"][-1]["evidence_type"], "ingestor_recovery_evidence")
            self.assertEqual(prior, self.snapshot(december))
        self.assertEqual(len(self.intake.compile_framework_runtime_evidence()["runtime_evidence"]), 4)

    def test_month_is_sampled_after_historical_validation_before_new_write(self):
        self.accept("old")
        old_path = self.archive()["runtime_evidence"]
        self.accept("new")
        original = Path.open
        reads = []

        def advance_during_validation(path, *args, **kwargs):
            if path == old_path and kwargs.get("encoding") == "utf-8":
                reads.append(path)
                if len(reads) == 2:
                    self.now.return_value = self.stamp(2026, 1)
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", advance_during_validation):
            self.assertEqual(self.archive()["runtime_evidence"].parent.name, "2026-01")

    def test_retry_and_duplicate_delivery_never_rearchive_evidence_in_later_month(self):
        message = self.accept("once")
        december = self.archive()["runtime_evidence"].parent
        prior = self.snapshot(december)
        self.now.return_value = self.stamp(2026, 1)
        self.assertEqual(self.intake.receive_runtime_evidence(message).reason, "already_accepted")
        paths = self.archive()
        self.assertEqual(paths["runtime_evidence"].read_bytes(), b"")
        self.assertEqual(prior, self.snapshot(december))
        again = self.snapshot(paths["runtime_evidence"].parent)
        self.archive()
        self.assertEqual(again, self.snapshot(paths["runtime_evidence"].parent))
        self.assertEqual(len(self.storage.get_framework_preservation_confirmation()["runtime_evidence"]), 1)

    def test_clock_failure_and_invalid_values_retain_journal_and_allow_retry(self):
        self.accept("pending")
        journal = self.journal.read_bytes()
        for value in (None, False, float("nan"), float("inf"), -1, 1e100):
            self.now.return_value = value
            with self.subTest(value=value), self.assertRaises((ValueError, OverflowError, OSError)):
                self.archive()
            self.assertEqual(journal, self.journal.read_bytes())
            self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.now.side_effect = OSError("clock unavailable")
        with self.assertRaises(OSError):
            self.archive()
        self.now.side_effect = None
        self.now.return_value = self.stamp(2026, 1)
        self.assertEqual(self.archive()["runtime_evidence"].parent.name, "2026-01")

    def test_backward_clock_cannot_reopen_historical_partition(self):
        self.accept("december")
        december = self.archive()["runtime_evidence"].parent
        self.now.return_value = self.stamp(2026, 1)
        self.accept("january")
        self.archive()
        before = self.snapshot(december)
        self.now.return_value = self.stamp(2025, 12)
        pending = self.accept("pending")
        with self.assertRaises(RuntimeError):
            self.archive()
        self.assertEqual(before, self.snapshot(december))
        self.assertTrue(self.intake.has_durable_runtime_evidence(pending))
        self.now.return_value = self.stamp(2026, 2)
        self.archive()

    def test_clock_failure_cannot_confirm_new_obligations_using_old_preservation(self):
        self.accept("preserved")
        self.archive()
        self.accept("still-pending")
        self.now.return_value = float("nan")
        with self.assertRaises(ValueError):
            self.archive()
        with self.assertRaises(RuntimeError):
            with self.intake.framework_preservation_guard(self.storage):
                pass
        self.now.return_value = self.stamp(2026, 1)
        self.archive()
        with self.intake.framework_preservation_guard(self.storage) as saved:
            self.assertEqual(saved["compilation_summary"]["runtime_evidence_count"], 2)

    def test_partial_write_blocks_retry_and_restart_without_mutating_prior_month(self):
        self.accept("confirmed")
        december = self.archive()["runtime_evidence"].parent
        prior = self.snapshot(december)
        self.now.return_value = self.stamp(2026, 1)
        self.accept("unconfirmed")
        original = Path.open

        def fail_summary(path, *args, **kwargs):
            if path.name == "compilation_summary.json" and args and args[0] == "w":
                raise OSError("interrupted summary write")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", fail_summary), self.assertRaises(OSError):
            self.archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.now.return_value = self.stamp(2026, 2)
        with self.assertRaises(RuntimeError):
            self.archive()
        with self.assertRaises((OSError, RuntimeError)):
            self.restart()
        self.assertEqual(prior, self.snapshot(december))
        self.assertFalse((december.parent / "2026-02").exists())
        with self.assertRaises(RuntimeError):
            self.archive()

    def test_complete_unconfirmed_write_is_reconciled_before_new_month_append(self):
        self.accept("once")
        original = self.intake.accept_framework_write_record
        def fail_completion(record):
            if record["kind"] == "completion":
                raise OSError("completion acceptance unavailable after product verification")
            return original(record)
        with patch.object(self.intake, "accept_framework_write_record", fail_completion), self.assertRaises(OSError):
            self.archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        directory = self.root / "storage/framework/evidence/2025-12"
        prior = self.snapshot(directory)
        self.now.return_value = self.stamp(2026, 1)
        saved = self.restart()
        self.assertEqual([r["evidence_id"] for r in saved["runtime_evidence"]].count("once"), 1)
        self.assertEqual(prior, self.snapshot(directory))

    def test_missing_historical_partition_retains_operational_journal_and_blocks_confirmation(self):
        message = self.accept("unfinished")
        directory = self.archive()["runtime_evidence"].parent
        self.now.return_value = self.stamp(2026, 1)
        self.accept("continuing")
        self.archive()
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        with self.assertRaises(ValueError):
            self.restart()
        self.assertTrue(self.intake.has_durable_runtime_evidence(message))
        self.assertTrue(self.journal.exists())

    def test_corrupted_historical_products_fail_closed_without_repair(self):
        self.accept("original")
        path = self.archive()["runtime_evidence"]
        path.write_text("corrupted\n")
        before = path.read_bytes()
        self.now.return_value = self.stamp(2026, 1)
        with self.assertRaises(ValueError):
            self.restart()
        self.assertEqual(before, path.read_bytes())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        with self.assertRaises(RuntimeError):
            self.archive()

    def test_nonpersistent_and_rejected_audit_remain_complete_across_months(self):
        self.accept("transient", persistent=False)
        self.archive()
        self.now.return_value = self.stamp(2026, 1)
        bad = RuntimeEvidenceMessage("invalid", None, "", "control", {}, True)
        self.assertFalse(self.intake.receive_runtime_evidence(bad).accepted)
        self.accept("persistent")
        self.archive()
        with self.intake.framework_preservation_guard(self.storage) as saved:
            self.assertEqual(saved["compilation_summary"]["ingest_audit_count"], 3)
            self.assertEqual(saved["compilation_summary"]["runtime_evidence_ids"], ["persistent"])

    def test_empty_new_month_does_not_rewrite_or_duplicate_history(self):
        self.accept("one")
        paths = self.archive()
        before = self.snapshot(paths["runtime_evidence"].parent)
        self.now.return_value = self.stamp(2026, 1)
        self.assertEqual(paths, self.archive())
        self.assertEqual(before, self.snapshot(paths["runtime_evidence"].parent))

    def test_existing_shared_archive_is_read_only_prefix_not_republished_history(self):
        message = self.accept("legacy")
        directory = self.archive()["runtime_evidence"].parent
        summary_path = directory / "compilation_summary.json"
        summary = json.loads(summary_path.read_text())
        for name in ("framework_archive_month", "framework_evidence_start", "framework_audit_start"):
            del summary[name]
        summary_path.write_text(json.dumps(summary))
        for path in directory.iterdir():
            path.rename(directory.parent / path.name)
        directory.rmdir()
        prior = self.snapshot(directory.parent)
        self.now.return_value = self.stamp(2026, 1)
        saved = self.restart()
        self.assertEqual(saved["runtime_evidence"][0], message.to_dict())
        for name, content in prior.items():
            self.assertEqual((directory.parent / name).read_bytes(), content)
        new_rows = (directory.parent / "2026-01/runtime_evidence.jsonl").read_text().splitlines()
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(json.loads(new_rows[0])["evidence_type"], "ingestor_recovery_evidence")

    def test_failed_reconciliation_fsync_cannot_confirm_or_rewrite_history(self):
        self.accept("original")
        directory = self.archive()["runtime_evidence"].parent
        prior = self.snapshot(directory)
        self.now.return_value = self.stamp(2026, 1)
        self.storage = PersistentStorageManager(self.root / "storage")
        self.intake = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.journal)
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("fsync unavailable")):
            with self.assertRaises(OSError):
                self.intake.continue_framework_evidence_archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertEqual(prior, self.snapshot(directory))
        with self.assertRaises(RuntimeError):
            self.archive()
        self.assertIsNotNone(self.intake.continue_framework_evidence_archive())

    def test_cancellation_during_write_requires_reconciliation_without_false_success(self):
        self.accept("pending")
        original = Path.open

        def cancel_summary(path, *args, **kwargs):
            if path.name == "compilation_summary.json" and args and args[0] == "w":
                raise asyncio.CancelledError()
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", cancel_summary), self.assertRaises(asyncio.CancelledError):
            self.archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertTrue(self.intake.has_durable_runtime_evidence(
            RuntimeEvidenceMessage("pending", None, "service_maintenance_evidence", "control",
                {"stop_attempt_id": "same-operation", "event_time": 1.0}, True)))
        self.now.return_value = self.stamp(2026, 1)
        with self.assertRaises(RuntimeError):
            self.archive()
        with self.assertRaises((OSError, RuntimeError)):
            self.restart()
        self.assertFalse((self.root / "storage/framework/evidence/2026-01").exists())


if __name__ == "__main__":
    unittest.main()
