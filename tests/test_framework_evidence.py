"""Deployment-scoped evidence uses the existing intake and archive infrastructure."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage, build_runtime_subject, parse_runtime_subject


class FrameworkEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.journal = self.root / "intake" / "framework.jsonl"
        self.storage = PersistentStorageManager(self.root)
        self.ingestor = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.journal)

    def message(self, identity="evidence-1", persistent=True):
        return RuntimeEvidenceMessage(identity, None, "service_maintenance_evidence", "controller", {"value": 1}, persistent)

    def archive(self):
        return self.storage.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())

    def test_framework_message_round_trip_and_subject_have_no_fake_session(self):
        message = self.message()
        data = json.loads(json.dumps(message.to_dict()))
        self.assertIsNone(data["session_id"])
        self.assertEqual(RuntimeEvidenceMessage.from_dict(data), message)
        subject = build_runtime_subject(None, "evidence", "controller", "controller", message.evidence_type)
        self.assertEqual(subject, "messages.evidence.controller.controller.service_maintenance_evidence")
        self.assertIsNone(parse_runtime_subject(subject)["session_id"])

    def test_framework_and_session_intake_are_independent(self):
        ingestor = InMemoryIngestor(recovery_journal_root=self.root / "sessions", framework_recovery_journal_path=self.root / "second-framework.jsonl")
        ingestor.prepare_session("session-a")
        session = RuntimeEvidenceMessage("session-evidence", "session-a", "warning", "node", {}, True)
        ingestor.receive_runtime_evidence(session)
        ingestor.receive_runtime_evidence(self.message())
        ingestor.receive_runtime_evidence(self.message("transient", False))
        self.assertEqual(ingestor.session_id, "session-a")
        self.assertEqual(ingestor.compile_persistent_runtime_evidence()["runtime_evidence"], (session,))
        compiled = ingestor.compile_framework_runtime_evidence()
        self.assertEqual(compiled["runtime_evidence"], (self.message(),))
        self.assertEqual(len(compiled["ingest_audit"]), 2)

    def test_framework_journal_preserves_duplicate_and_rejected_audit_on_recovery(self):
        message = self.message()
        self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
        duplicate = self.ingestor.receive_runtime_evidence(message)
        self.assertEqual(duplicate.reason, "already_accepted")
        rejected = RuntimeEvidenceMessage("bad", None, "", "source", {}, True)
        self.assertFalse(self.ingestor.receive_runtime_evidence(rejected).accepted)
        before = self.ingestor.compile_framework_runtime_evidence()
        recovered = InMemoryIngestor(framework_recovery_journal_path=self.journal)
        after = recovered.compile_framework_runtime_evidence()
        self.assertEqual(after["ingest_audit"][:3], before["ingest_audit"])
        self.assertEqual(after["runtime_evidence"][0], message)
        self.assertTrue(recovered.has_durable_runtime_evidence(message))
        self.assertIsNone(recovered.session_id)

    def test_framework_archive_has_exact_products_and_no_session_record(self):
        self.ingestor.receive_runtime_evidence(self.message())
        paths = self.archive()
        directory = paths["runtime_evidence"].parent
        self.assertEqual(directory.parent, self.root / "framework" / "evidence")
        self.assertRegex(directory.name, r"^\d{4}-\d{2}$")
        self.assertEqual(set(paths.values()), {directory / "runtime_evidence.jsonl", directory / "ingest_audit.jsonl", directory / "compilation_summary.json"})
        self.assertFalse(list(self.root.glob("session_*")))
        with self.ingestor.framework_preservation_guard(self.storage) as confirmation:
            self.assertNotIn("session_record", confirmation)
            self.assertEqual(confirmation["runtime_evidence"], [self.message().to_dict()])
            self.assertEqual(confirmation["compilation_summary"]["ingest_audit_count"], 1)

    def test_late_duplicate_intake_invalidates_older_coverage(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.ingestor.receive_runtime_evidence(self.message())
        with self.assertRaises(RuntimeError):
            with self.ingestor.framework_preservation_guard(self.storage):
                pass
        self.archive()
        with self.ingestor.framework_preservation_guard(self.storage):
            pass

    def test_actual_archive_changes_invalidate_confirmation(self):
        self.ingestor.receive_runtime_evidence(self.message())
        paths = self.archive()
        paths["runtime_evidence"].write_text("", encoding="utf-8")
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())

    def test_partial_rewrite_invalidates_previous_confirmation(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.ingestor.receive_runtime_evidence(self.message("new-before-interruption"))
        original = Path.open
        def fail_summary(path, *args, **kwargs):
            if path.name == "compilation_summary.json" and args and args[0] == "w":
                raise OSError("disk full")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail_summary), self.assertRaises(OSError):
            self.archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())

    def test_journal_write_failure_does_not_establish_acceptance(self):
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("journal disk full")):
            with self.assertRaises(OSError):
                self.ingestor.receive_runtime_evidence(self.message())
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(self.message()))
        self.assertEqual(self.ingestor.compile_framework_runtime_evidence()["runtime_evidence"], ())
        with self.assertRaises(RuntimeError):
            self.ingestor.receive_runtime_evidence(self.message("new"))

    def test_preservation_guard_serializes_later_intake_and_archival_through_commit(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        started, finished = Event(), Event()
        def rewrite():
            started.set()
            self.ingestor.receive_runtime_evidence(self.message("later"))
            self.archive()
            finished.set()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.ingestor.framework_preservation_guard(self.storage):
                future = executor.submit(rewrite)
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.is_set())
            future.result(timeout=2)
        with self.ingestor.framework_preservation_guard(self.storage) as confirmation:
            self.assertEqual(len(confirmation["runtime_evidence"]), 2)

    def test_framework_intake_survives_session_release_and_successive_binding(self):
        ingestor = InMemoryIngestor(recovery_journal_root=self.root / "sessions", framework_recovery_journal_path=self.root / "binding-framework.jsonl")
        ingestor.prepare_session("session-a")
        ingestor.receive_runtime_evidence(self.message())
        before = ingestor.compile_framework_runtime_evidence()
        self.assertTrue(ingestor.release_session("session-a"))
        ingestor.prepare_session("session-b")
        self.assertEqual(ingestor.compile_framework_runtime_evidence(), before)
        self.assertEqual(ingestor.session_id, "session-b")

    def test_framework_archive_rejects_session_scoped_messages(self):
        message = RuntimeEvidenceMessage("session-evidence", "session-a", "warning", "node", {}, True)
        with self.assertRaises(ValueError):
            self.storage.write_framework_evidence_archive({"runtime_evidence": (message,), "ingest_audit": ()})
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
