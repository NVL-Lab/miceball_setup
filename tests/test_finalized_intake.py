"""Durable final intake retains its exact evidence and audit across restart."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage
from tests import test_storage as records


class FinalizedIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "journal.jsonl"
        self.intake = InMemoryIngestor(session_id="session", recovery_journal_path=self.path)
        self.marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        self.intake.receive_runtime_evidence(self.marker)
        self.receipt = {"session_id": "session", "evidence_id": "marker",
                        "durable_receipt_confirmed": True, "marker_stream_sequence": 1}

    def test_finalized_intake_retains_exact_audit_after_restart(self):
        finality = self.intake.finalize_acquisition_intake(self.marker, self.receipt)
        before = self.path.read_bytes()
        restored = InMemoryIngestor(session_id="session", recovery_journal_path=self.path)
        self.assertEqual(restored.finalized_acquisition_intake("session"), finality)
        self.assertEqual(restored.runtime_evidence_audit, self.intake.runtime_evidence_audit)
        self.assertEqual(self.path.read_bytes(), before)

    def test_late_evidence_and_duplicates_do_not_mutate_finalized_intake(self):
        self.intake.finalize_acquisition_intake(self.marker, self.receipt)
        before = self.path.read_bytes()
        compiled = self.intake.compile_persistent_runtime_evidence()
        for evidence in (self.marker, RuntimeEvidenceMessage("late", "session", "health", "node", {}, True)):
            audit = self.intake.receive_runtime_evidence(evidence)
            self.assertFalse(audit.accepted)
            self.assertEqual(audit.reason, "acquisition_intake_finalized")
        self.assertEqual(self.intake.compile_persistent_runtime_evidence(), compiled)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unconfirmed_receipt_cannot_finalize_intake(self):
        receipt = {**self.receipt, "durable_receipt_confirmed": False}
        with self.assertRaises(RuntimeError):
            self.intake.finalize_acquisition_intake(self.marker, receipt)
        self.assertIsNone(self.intake.finalized_acquisition_intake("session"))

    def test_failed_finality_write_does_not_confirm_completion(self):
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.intake.finalize_acquisition_intake(self.marker, self.receipt)
        self.assertIsNone(self.intake.finalized_acquisition_intake("session"))

    def test_different_marker_cannot_replace_finalized_boundary(self):
        self.intake.finalize_acquisition_intake(self.marker, self.receipt)
        other = RuntimeEvidenceMessage("other", "session", "acquisition_evidence_completion", "controller", {}, True)
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.intake.finalize_acquisition_intake(other, {**self.receipt, "evidence_id": "other"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_kill_obligation_survives_restart_and_blocks_empty_release(self):
        path = self.path.parent / "empty.jsonl"
        intake = InMemoryIngestor(session_id="empty", recovery_journal_path=path)
        intake.admit_kill_closeout("empty")
        restored = InMemoryIngestor(session_id="empty", recovery_journal_path=path)
        with self.assertRaises(RuntimeError):
            restored.release_session("empty")
        self.assertEqual(restored.session_id, "empty")

    def test_changed_finalized_journal_cannot_confirm_receipt(self):
        self.intake.finalize_acquisition_intake(self.marker, self.receipt)
        with self.path.open("ab") as journal:
            journal.write(b'{"unexpected":"history"}\n')
        with self.assertRaises(RuntimeError):
            self.intake.finalized_acquisition_intake("session")
        with self.assertRaises(ValueError):
            InMemoryIngestor(session_id="session", recovery_journal_path=self.path)

    def test_complete_preservation_and_terminal_record_are_readable_after_restart(self):
        storage = PersistentStorageManager(self.path.parent)
        intake = InMemoryIngestor(storage, session_id="saved", recovery_journal_path=self.path.parent / "session_saved.jsonl")
        marker = RuntimeEvidenceMessage("saved-marker", "saved", "acquisition_evidence_completion", "controller", {}, True)
        intake.receive_runtime_evidence(marker)
        intake.finalize_acquisition_intake(marker, {**self.receipt, "session_id": "saved", "evidence_id": marker.evidence_id})
        record = records.PersistentStorageManagerTests._minimal_session_record_evidence("saved")
        record["lifecycle_evidence"] = [{"to_state": "stopping"}]
        initial = intake.preserve_session_closeout("saved", mode="normal", session_record=record,
            controller_evidence=[marker.to_dict()], uncertainties=[])
        self.assertTrue(initial["acquisition_preservation_eligible"])
        record["lifecycle_evidence"].append({"to_state": "completed"})
        record["final_session_status"] = {"state": "completed"}
        terminal = intake.preserve_terminal_session_record("saved", record)
        self.assertEqual(terminal["session_record"]["final_session_status"], {"state": "completed"})
        restored = InMemoryIngestor(PersistentStorageManager(self.path.parent), recovery_journal_root=self.path.parent)
        self.assertEqual(restored.read_session_closeout("saved"), terminal)
        self.assertIsNone(restored.session_id)

    def test_partial_kill_preservation_remains_independently_verifiable(self):
        storage = PersistentStorageManager(self.path.parent)
        intake = InMemoryIngestor(storage, session_id="killed", recovery_journal_path=self.path.parent / "session_killed.jsonl")
        intake.admit_kill_closeout("killed")
        record = records.PersistentStorageManagerTests._minimal_session_record_evidence("killed")
        record.update(lifecycle_evidence=[{"to_state": "aborted"}], final_session_status={"state": "aborted"})
        result = intake.preserve_session_closeout("killed", mode="kill", session_record=record,
            controller_evidence=[], uncertainties=[{"cleanup_confirmed": False}])
        self.assertTrue(result["preservation_confirmed"])
        self.assertFalse(result["acquisition_preservation_eligible"])
        restored = InMemoryIngestor(PersistentStorageManager(self.path.parent), recovery_journal_root=self.path.parent)
        self.assertEqual(restored.read_session_closeout("killed"), result)
        self.assertTrue(intake.release_session("killed"))

