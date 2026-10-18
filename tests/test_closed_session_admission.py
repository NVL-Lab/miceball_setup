"""Released terminal Sessions cannot be reopened, independently of their journals."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import Event, get_ident
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage, Session, SessionConfig,
)
from tests import test_storage as records


class ClosedSessionAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journals = self.root / "journals"
        self.storage = PersistentStorageManager(self.root / "storage")
        self.intake = InMemoryIngestor(self.storage, recovery_journal_root=self.journals)
        self.intake.prepare_session("saved")
        self.message = RuntimeEvidenceMessage("first", "saved", "health", "node", {}, True)
        self.intake.receive_runtime_evidence(self.message)
        self.journal = self.intake.recovery_journal_path
        self.before = self.journal.read_bytes()
        self.ledger = self.journals / "closed_sessions" / "records.json"

    def preserve_terminal(self):
        session = Session("saved", SessionConfig([], "storage", [], "errors", session_id="saved"))
        session.initialize()
        session.start()
        session.stop()
        session.complete()
        self.storage.write_evidence_archive("saved", self.intake.compile_persistent_runtime_evidence())
        self.storage.write_final_session_record(
            "saved", accepted_session_config=session.configuration,
            lifecycle_evidence=session.transition_history, readiness_evidence=session.readiness_checks,
            device_readiness_evidence=(), service_readiness_evidence=(),
            final_session_status=session.final_status,
            cleanup_evidence={"cleanup_occurred": session.cleanup_occurred})

    def test_complete_finalized_intake_closes_only_after_stage_a_and_terminal_preservation(self):
        marker = RuntimeEvidenceMessage(
            "marker", "saved", "acquisition_evidence_completion", "controller", {}, True)
        self.intake.receive_runtime_evidence(marker)
        self.intake.finalize_acquisition_intake(marker, {
            "session_id": "saved", "evidence_id": "marker",
            "durable_receipt_confirmed": True, "marker_stream_sequence": 2})
        before = self.journal.read_bytes()
        record = records.PersistentStorageManagerTests._minimal_session_record_evidence("saved")
        record["lifecycle_evidence"] = [{"to_state": "stopping"}]
        self.intake.preserve_session_closeout(
            "saved", mode="normal", session_record=record,
            controller_evidence=[marker.to_dict()], uncertainties=[])
        record["lifecycle_evidence"].append({"to_state": "completed"})
        record["final_session_status"] = {"state": "completed"}
        self.intake.preserve_terminal_session_record("saved", record)
        self.assertTrue(self.intake.release_session("saved"))
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.intake.prepare_session("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_terminal_release_permanently_rejects_preparation_and_redelivery(self):
        self.preserve_terminal()
        self.assertTrue(self.intake.release_session("saved"))
        self.assertIsNone(self.intake.session_id)
        for message in (self.message, RuntimeEvidenceMessage(
                "late", "saved", "health", "node", {}, True)):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                self.intake.receive_runtime_evidence(message)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.intake.prepare_session("saved")
        self.assertEqual(self.journal.read_bytes(), self.before)

    def test_deployment_restart_rejects_closed_session_without_temporary_journal(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        # Simulate a future separately authorized journal retirement, not a W070A action.
        self.journal.unlink()
        for _ in range(2):
            fresh = InMemoryIngestor(PersistentStorageManager(self.root / "storage"),
                                    recovery_journal_root=self.journals)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                fresh.prepare_session("saved")
            with self.assertRaisesRegex(RuntimeError, "closed"):
                fresh.receive_runtime_evidence(self.message)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                InMemoryIngestor(session_id="saved", recovery_journal_path=self.journal)
        self.assertFalse(self.journal.exists())

    def test_new_session_remains_usable_after_terminal_release(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        self.intake.prepare_session("next")
        message = RuntimeEvidenceMessage("next-first", "next", "health", "node", {}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)
        self.assertEqual(self.journal.read_bytes(), self.before)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.intake.receive_runtime_evidence(self.message)

    def test_failed_closure_publication_retains_binding_and_allows_explicit_retry(self):
        self.preserve_terminal()
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertTrue(self.intake.release_session("saved"))

    def test_interrupted_closure_write_never_reports_release(self):
        self.preserve_terminal()
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertTrue(self.intake.release_session("saved"))

    def test_failed_closure_fsync_retains_binding(self):
        self.preserve_terminal()
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("unconfirmed")):
            with self.assertRaises(OSError):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertTrue(self.intake.release_session("saved"))

    def test_failed_readback_after_publication_retains_binding_and_retry_reconfirms(self):
        self.preserve_terminal()
        original_replace = os.replace
        original_read = Path.read_text
        published = False

        def publish(*args):
            nonlocal published
            original_replace(*args)
            published = True

        def unavailable(path, *args, **kwargs):
            if published and path == self.ledger:
                raise OSError("readback unavailable")
            return original_read(path, *args, **kwargs)

        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=publish), \
                patch.object(Path, "read_text", new=unavailable):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.intake.receive_runtime_evidence(self.message)
        self.assertTrue(self.intake.release_session("saved"))
        self.assertEqual(self.journal.read_bytes(), self.before)

    def test_unpreserved_intake_does_not_close_session(self):
        with self.assertRaises(RuntimeError):
            self.intake.release_session("saved")
        restored = InMemoryIngestor(session_id="saved", recovery_journal_path=self.journal)
        self.assertEqual(restored.accepted_runtime_evidence[0], self.message)

    def test_closed_status_corruption_blocks_live_and_restart_admission(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        self.ledger.write_text('{"sessions":[]}', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            self.intake.prepare_session("next")
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            InMemoryIngestor(recovery_journal_root=self.journals)
        self.assertEqual(self.journal.read_bytes(), self.before)

    def test_conflicting_closed_identity_records_are_not_repaired_or_reopened(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        sessions = ["saved", "saved"]
        content = json.dumps(sessions, separators=(",", ":"))
        self.ledger.write_text(json.dumps({"version": 1, "sessions": sessions,
            "sha256": hashlib.sha256(content.encode("ascii")).hexdigest()}), encoding="utf-8")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            self.intake.prepare_session("saved")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_missing_closed_status_is_not_recreated_on_restart(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        self.ledger.unlink()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            InMemoryIngestor(recovery_journal_root=self.journals)
        self.assertFalse(self.ledger.exists())

    def test_missing_store_directory_is_not_treated_as_new_deployment(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        self.ledger.unlink()
        self.ledger.parent.rmdir()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            InMemoryIngestor(recovery_journal_root=self.journals)
        self.assertFalse(self.ledger.parent.exists())

    def test_missing_initialization_marker_blocks_restart(self):
        self.preserve_terminal()
        self.intake.release_session("saved")
        (self.journals / "closed_sessions.initialized").unlink()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            InMemoryIngestor(recovery_journal_root=self.journals)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_terminal_empty_intake_is_closed_unlike_aborted_initialization(self):
        fresh = InMemoryIngestor(self.storage, recovery_journal_root=self.journals)
        fresh.prepare_session("empty")
        session = Session("empty", SessionConfig([], "storage", [], "errors", session_id="empty"))
        session.initialize()
        session.start()
        session.stop()
        session.complete()
        self.storage.write_evidence_archive("empty", fresh.compile_persistent_runtime_evidence())
        self.storage.write_final_session_record(
            "empty", accepted_session_config=session.configuration,
            lifecycle_evidence=session.transition_history, readiness_evidence=session.readiness_checks,
            device_readiness_evidence=(), service_readiness_evidence=(),
            final_session_status=session.final_status,
            cleanup_evidence={"cleanup_occurred": session.cleanup_occurred})
        self.assertTrue(fresh.release_session("empty"))
        with self.assertRaisesRegex(RuntimeError, "closed"):
            fresh.prepare_session("empty")

    def test_changed_journal_prevents_closure_despite_matching_cached_compilation(self):
        self.preserve_terminal()
        with self.journal.open("ab") as output:
            output.write(b'{"inconsistent":"history"}\n')
        with self.assertRaisesRegex(RuntimeError, "journal coverage"):
            self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")

    def test_unfinished_terminal_record_cannot_close_session(self):
        self.storage.write_evidence_archive("saved", self.intake.compile_persistent_runtime_evidence())
        with self.assertRaises(RuntimeError):
            self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")

    def test_unreadable_closure_information_blocks_release(self):
        self.preserve_terminal()
        original = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == self.ledger:
                raise PermissionError("unreadable")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=unreadable):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        self.assertTrue(self.intake.release_session("saved"))

    def test_session_identity_cannot_escape_journal_directory(self):
        fresh = InMemoryIngestor(recovery_journal_root=self.root / "other")
        for identity in ("../escape", "..\\escape", "a/b", "a:b", "..", "trailing."):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                fresh.prepare_session(identity)
        self.assertIsNone(fresh.session_id)

    def test_empty_initialization_release_is_not_terminal_closure(self):
        fresh = InMemoryIngestor(recovery_journal_root=self.root / "other")
        fresh.prepare_session("empty")
        self.assertTrue(fresh.release_session("empty"))
        self.assertTrue(fresh.prepare_session("empty").ready)

    def pause_admission_before_commit(self, operation, *, skip_reads=0):
        """Hold a real ledger read after its snapshot, before public admission commits."""
        checked, resume = Event(), Event()
        main_thread = get_ident()
        original = Path.read_text
        remaining = skip_reads
        journal_before = self.journal.read_bytes()
        ledger_before = self.ledger.read_bytes()

        def pause(path, *args, **kwargs):
            nonlocal remaining
            content = original(path, *args, **kwargs)
            if path == self.ledger and get_ident() != main_thread:
                if remaining:
                    remaining -= 1
                elif not checked.is_set():
                    checked.set()
                    if not resume.wait(5):
                        raise AssertionError("Admission was not resumed")
            return content

        with ThreadPoolExecutor(max_workers=1) as workers, patch.object(Path, "read_text", new=pause):
            pending = workers.submit(operation)
            try:
                self.assertTrue(checked.wait(5), "Admission never reached its ledger check")
                with self.assertRaisesRegex(RuntimeError, "unresolved"):
                    self.intake.release_session("saved")
                self.assertEqual(self.intake.session_id, "saved")
                self.assertEqual(self.journal.read_bytes(), journal_before)
                self.assertEqual(self.ledger.read_bytes(), ledger_before)
            finally:
                resume.set()
            return pending.result(timeout=5)

    def test_preparation_excludes_closure_between_ledger_check_and_recovery(self):
        self.preserve_terminal()
        other = InMemoryIngestor(self.storage, recovery_journal_root=self.journals)
        result = self.pause_admission_before_commit(lambda: other.prepare_session("saved"))
        self.assertTrue(result.ready)
        self.assertEqual(other.session_id, "saved")
        # Newly recovered evidence must now be covered before closure can proceed.
        with self.assertRaisesRegex(RuntimeError, "journal coverage"):
            self.intake.release_session("saved")

    def test_constructor_excludes_closure_through_recovery_evidence_acceptance(self):
        self.preserve_terminal()
        other = self.pause_admission_before_commit(
            lambda: InMemoryIngestor(self.storage, session_id="saved", recovery_journal_path=self.journal),
            skip_reads=1)  # Skip the initial store-integrity read, not the admission check.
        self.assertEqual(other.session_id, "saved")
        self.assertEqual(other.accepted_runtime_evidence[-1].evidence_type, "ingestor_recovery_evidence")
        with self.assertRaisesRegex(RuntimeError, "journal coverage"):
            self.intake.release_session("saved")

    def test_intake_excludes_closure_between_ledger_check_and_journal_acceptance(self):
        other = self.intake
        self.intake = InMemoryIngestor(self.storage, session_id="saved", recovery_journal_path=self.journal)
        self.preserve_terminal()
        message = RuntimeEvidenceMessage("concurrent", "saved", "health", "node", {}, True)
        result = self.pause_admission_before_commit(lambda: other.receive_runtime_evidence(message))
        self.assertTrue(result.accepted)
        self.assertIn(message, other.accepted_runtime_evidence)
        with self.assertRaisesRegex(RuntimeError, "journal coverage"):
            self.intake.release_session("saved")

    def test_published_closure_excludes_other_owners_until_readback_and_release_complete(self):
        other = self.intake
        other.prepare_framework_evidence(self.root / "framework.jsonl")
        self.intake = InMemoryIngestor(self.storage, session_id="saved", recovery_journal_path=self.journal)
        self.preserve_terminal()
        before = self.journal.read_bytes()
        published, resume = Event(), Event()
        original = os.replace

        def pause(source, destination):
            original(source, destination)
            if Path(destination) == self.ledger:
                published.set()
                if not resume.wait(5):
                    raise AssertionError("Closure was not resumed")

        late = RuntimeEvidenceMessage("late", "saved", "health", "node", {}, True)
        with ThreadPoolExecutor(max_workers=1) as workers, \
                patch("lab_sync_acquisition.ingestor.os.replace", side_effect=pause):
            closing = workers.submit(self.intake.release_session, "saved")
            try:
                self.assertTrue(published.wait(5), "Closure was not published")
                for operation in (
                    lambda: other.receive_runtime_evidence(late),
                    lambda: other.prepare_session("saved"),
                    lambda: other.admit_kill_closeout("saved"),
                    lambda: InMemoryIngestor(session_id="saved", recovery_journal_path=self.journal),
                ):
                    with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, "unresolved"):
                        operation()
                framework = RuntimeEvidenceMessage("framework", None, "health", "node", {}, True)
                self.assertTrue(other.receive_runtime_evidence(framework).accepted)
                self.assertEqual(self.journal.read_bytes(), before)
            finally:
                resume.set()
            self.assertTrue(closing.result(timeout=5))
        for message in (late, self.message):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                other.receive_runtime_evidence(message)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            other.prepare_session("saved")
        fresh = InMemoryIngestor(recovery_journal_root=self.journals)
        self.assertTrue(fresh.prepare_session("next").ready)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_stale_root_lock_is_never_reclaimed_by_admission_or_release(self):
        self.preserve_terminal()
        self.intake.prepare_framework_evidence(self.root / "framework.jsonl")
        lock = self.ledger.parent / "publication.lock"
        lock.write_bytes(b"interrupted owner")
        ledger_before = self.ledger.read_bytes()
        for operation in (
            lambda: self.intake.prepare_session("saved"),
            lambda: self.intake.receive_runtime_evidence(self.message),
            lambda: self.intake.release_session("saved"),
            lambda: InMemoryIngestor(session_id="saved", recovery_journal_path=self.journal),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, "unresolved"):
                operation()
        self.assertEqual(lock.read_bytes(), b"interrupted owner")
        self.assertEqual(self.ledger.read_bytes(), ledger_before)
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertEqual(self.intake.session_id, "saved")
        framework = RuntimeEvidenceMessage("framework", None, "health", "node", {}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(framework).accepted)
        unrelated = InMemoryIngestor(recovery_journal_root=self.root / "unrelated")
        self.assertTrue(unrelated.prepare_session("other").ready)

    def test_cancelled_admission_releases_its_own_exclusion_without_changing_journal(self):
        self.preserve_terminal()
        original = Path.read_text

        def interrupt(path, *args, **kwargs):
            if path == self.ledger:
                raise asyncio.CancelledError
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=interrupt):
            with self.assertRaises(asyncio.CancelledError):
                self.intake.receive_runtime_evidence(self.message)
        self.assertFalse((self.ledger.parent / "publication.lock").exists())
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertEqual(self.intake.session_id, "saved")
        self.assertTrue(self.intake.release_session("saved"))

    def test_cancelled_closure_retains_binding_and_allows_explicit_retry(self):
        self.preserve_terminal()
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                self.intake.release_session("saved")
        self.assertFalse((self.ledger.parent / "publication.lock").exists())
        self.assertEqual(self.journal.read_bytes(), self.before)
        self.assertEqual(self.intake.session_id, "saved")
        self.assertTrue(self.intake.release_session("saved"))
