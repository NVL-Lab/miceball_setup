"""Closed intake remains verifiable from permanent products without its journal."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, PersistentStorageManager, RuntimeCommandResultMessage,
    RuntimeEvidenceMessage, RuntimeParticipant,
)
from tests import test_storage as records


class CloseoutFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.journals = self.root / "journals"
        self.storage_root = self.root / "storage"
        self.storage = PersistentStorageManager(self.storage_root)
        self.intake = InMemoryIngestor(self.storage, recovery_journal_root=self.journals)
        self.directory = self.storage_root / "session_saved"
        self.summary = self.directory / "evidence" / "compilation_summary.json"
        self.journal = self.journals / "session_saved.jsonl"

    def preserve(self, *, kill=False, release=True):
        self.intake.prepare_session("saved")
        for identity, persistent in (("persistent", True), ("temporary", False)):
            self.intake.receive_runtime_evidence(RuntimeEvidenceMessage(
                identity, "saved", "health", "node", {}, persistent))
        marker = RuntimeEvidenceMessage(
            "marker", "saved", "acquisition_evidence_completion", "controller", {}, True)
        if kill:
            self.intake.admit_kill_closeout("saved")
        else:
            self.intake.receive_runtime_evidence(marker)
            self.intake.finalize_acquisition_intake(marker, {
                "session_id": "saved", "evidence_id": "marker", "marker_stream_sequence": 3,
                "durable_receipt_confirmed": True, "reason": "contiguous_durable_receipt",
                "acknowledged_stream_sequence": 3, "acknowledged_consumer_sequence": 3})
        record = records.PersistentStorageManagerTests._minimal_session_record_evidence("saved")
        record["lifecycle_evidence"] = [{"to_state": "aborted" if kill else "stopping"}]
        if kill:
            record["final_session_status"] = {"state": "aborted"}
        # Seed a valid empty handoff fixture. This reader/retirement suite does
        # not test initial hard-link handoff publication (sandbox restricted).
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "artifact_collection_handoff.json").write_text(
            json.dumps(self.intake.compile_artifact_collection_handoff("saved")), encoding="utf-8")
        result = self.intake.preserve_session_closeout(
            "saved", mode="kill" if kill else "normal", session_record=record,
            controller_evidence=[] if kill else [marker.to_dict()],
            uncertainties=[{"cleanup_confirmed": False}] if kill else [])
        if not kill:
            record["lifecycle_evidence"].append({"to_state": "completed"})
            record["final_session_status"] = {"state": "completed"}
            result = self.intake.preserve_terminal_session_record("saved", record)
        if release:
            self.assertTrue(self.intake.release_session("saved"))
        return result

    def unavailable(self):
        self.journal.rename(self.journal.with_suffix(".unavailable"))

    def change_summary(self, change):
        summary = json.loads(self.summary.read_text(encoding="utf-8"))
        change(summary)
        self.summary.write_text(json.dumps(summary), encoding="utf-8")


class PermanentCloseoutTests(CloseoutFixture, unittest.TestCase):
    def test_normal_closeout_survives_missing_journal_and_owner_restart(self):
        expected = self.preserve()
        self.unavailable()
        self.assertEqual(self.intake.read_session_closeout("saved"), expected)
        fresh = InMemoryIngestor(PersistentStorageManager(self.storage_root), recovery_journal_root=self.journals)
        self.assertEqual(fresh.read_session_closeout("saved"), expected)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            fresh.prepare_session("saved")

    def test_partial_kill_readback_does_not_claim_complete_receipt(self):
        expected = self.preserve(kill=True)
        self.unavailable()
        result = self.intake.read_session_closeout("saved")
        self.assertEqual(result, expected)
        self.assertFalse(result["acquisition_preservation_eligible"])
        self.assertIsNone(result["finalized_intake"])
        self.assertFalse(result["compilation_summary"]["kill_preservation"]["complete_receipt_confirmed"])

    def test_conflicting_permanent_receipt_rejects_readback(self):
        self.preserve()
        self.unavailable()
        self.change_summary(lambda s: s["acquisition_evidence_completion"]["receipt"].update(evidence_id="wrong"))
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_missing_receipt_cannot_be_inferred_from_summary_flags(self):
        self.preserve()
        self.unavailable()
        self.change_summary(lambda s: s["acquisition_evidence_completion"].pop("receipt"))
        with self.assertRaises((RuntimeError, OSError)):
            self.intake.read_session_closeout("saved")

    def test_acknowledgment_floor_before_marker_cannot_confirm_permanent_receipt(self):
        self.preserve()
        self.unavailable()
        self.change_summary(lambda s: s["acquisition_evidence_completion"]["receipt"].update(
            acknowledged_stream_sequence=2))
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_corrupt_permanent_evidence_rejects_readback(self):
        self.preserve()
        self.unavailable()
        (self.directory / "evidence" / "runtime_evidence.jsonl").write_bytes(b"corrupt\n")
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_incomplete_intake_audit_rejects_readback(self):
        self.preserve()
        self.unavailable()
        (self.directory / "evidence" / "ingest_audit.jsonl").write_bytes(b"")
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_nonterminal_record_cannot_establish_post_release_closeout(self):
        self.preserve()
        self.unavailable()
        path = self.directory / "session_record_final.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["final_session_status"] = {"state": "running"}
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_missing_handoff_rejects_permanent_closeout(self):
        self.preserve()
        self.unavailable()
        (self.directory / "artifact_collection_handoff.json").unlink()
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_unreleased_intake_still_requires_its_journal(self):
        self.preserve(release=False)
        self.unavailable()
        with self.assertRaises(RuntimeError):
            self.intake.read_session_closeout("saved")

    def test_older_archive_keeps_journal_backed_readback_without_rewriting(self):
        self.preserve()
        self.change_summary(lambda s: s["acquisition_evidence_completion"].pop("receipt"))
        before = self.summary.read_bytes()
        self.assertTrue(self.intake.read_session_closeout("saved")["preservation_confirmed"])
        self.assertEqual(self.summary.read_bytes(), before)


class JournalRetirementTests(CloseoutFixture, unittest.TestCase):
    def test_retirement_preserves_all_permanent_products_and_rejects_late_evidence(self):
        expected = self.preserve()
        permanent = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        ledger = self.journals / "closed_sessions" / "records.json"
        ledger_before = ledger.read_bytes()
        framework = self.journals / "framework.jsonl"
        framework.write_bytes(b"framework history\n")
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        self.assertFalse(self.journal.exists())
        self.assertEqual({p: p.read_bytes() for p in permanent}, permanent)
        self.assertEqual(ledger.read_bytes(), ledger_before)
        self.assertEqual(framework.read_bytes(), b"framework history\n")
        self.assertEqual(self.intake.read_session_closeout("saved"), expected)
        for identity in ("persistent", "late"):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                self.intake.receive_runtime_evidence(RuntimeEvidenceMessage(
                    identity, "saved", "health", "node", {}, True))

    def test_unreleased_terminal_session_retains_journal(self):
        self.preserve(release=False)
        before = self.journal.read_bytes()
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_active_session_retains_journal(self):
        self.intake.prepare_session("saved")
        before = self.journal.read_bytes()
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_retirement_retries_after_owner_restart_require_current_proof(self):
        expected = self.preserve()
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        fresh = InMemoryIngestor(PersistentStorageManager(self.storage_root), recovery_journal_root=self.journals)
        self.assertTrue(fresh.retire_recovery_journal("saved"))
        self.assertEqual(fresh.read_session_closeout("saved"), expected)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            fresh.prepare_session("saved")
        self.summary.write_text("corrupt", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            fresh.retire_recovery_journal("saved")

    def test_partial_kill_retirement_preserves_explicit_uncertainty(self):
        expected = self.preserve(kill=True)
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        result = self.intake.read_session_closeout("saved")
        self.assertEqual(result, expected)
        self.assertFalse(result["acquisition_preservation_eligible"])
        self.assertIsNone(result["finalized_intake"])
        self.assertEqual(result["compilation_summary"]["kill_preservation"]["uncertainties"],
                         [{"cleanup_confirmed": False}])

    def test_retirement_does_not_rewrite_permanently_closed_archive(self):
        self.preserve()
        self.storage.close_session_evidence_archive("saved")
        before = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        self.assertTrue(self.intake.read_session_closeout("saved")["compilation_summary"]["archive_closed"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_unrelated_active_session_is_unchanged(self):
        self.preserve()
        self.intake.prepare_session("next")
        message = RuntimeEvidenceMessage("next-first", "next", "health", "node", {}, True)
        self.intake.receive_runtime_evidence(message)
        path = self.intake.recovery_journal_path
        before = path.read_bytes()
        self.assertTrue(self.intake.retire_recovery_journal("saved"))
        self.assertEqual(self.intake.session_id, "next")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.intake.accepted_runtime_evidence, (message,))

    def test_missing_permanent_receipt_retains_journal(self):
        self.preserve()
        self.change_summary(lambda s: s["acquisition_evidence_completion"].pop("receipt"))
        before = self.journal.read_bytes()
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_corrupt_journal_is_not_automatically_terminally_deleted(self):
        self.preserve()
        self.journal.write_bytes(b"corrupt\n")
        with self.assertRaises((RuntimeError, ValueError)):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), b"corrupt\n")

    def test_corrupt_permanent_archive_retains_journal(self):
        self.preserve()
        before = self.journal.read_bytes()
        (self.directory / "evidence" / "runtime_evidence.jsonl").write_bytes(b"corrupt\n")
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_unconfirmed_preservation_durability_retains_journal(self):
        self.preserve()
        before = self.journal.read_bytes()
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("unconfirmed")):
            with self.assertRaises(RuntimeError):
                self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_failed_closure_publication_cannot_authorize_retirement(self):
        self.preserve(release=False)
        before = self.journal.read_bytes()
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=OSError("publication failed")):
            with self.assertRaises(OSError):
                self.intake.release_session("saved")
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertTrue(self.intake.release_session("saved"))
        self.assertTrue(self.intake.retire_recovery_journal("saved"))

    def test_failed_unlink_retains_journal_and_explicit_retry_succeeds(self):
        self.preserve()
        original = Path.unlink

        def unavailable(path, *args, **kwargs):
            if path == self.journal:
                raise PermissionError("unavailable")
            return original(path, *args, **kwargs)

        before = self.journal.read_bytes()
        with patch.object(Path, "unlink", new=unavailable):
            with self.assertRaises(PermissionError):
                self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertTrue(self.intake.retire_recovery_journal("saved"))

    def test_interruption_after_unlink_keeps_closeout_verifiable_and_retry_safe(self):
        expected = self.preserve()
        original = Path.unlink

        def interrupted(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == self.journal:
                raise asyncio.CancelledError
            return result

        with patch.object(Path, "unlink", new=interrupted):
            with self.assertRaises(asyncio.CancelledError):
                self.intake.retire_recovery_journal("saved")
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.intake.read_session_closeout("saved"), expected)
        self.assertTrue(self.intake.retire_recovery_journal("saved"))

    def test_stale_admission_lock_retains_journal(self):
        self.preserve()
        lock = self.journals / "closed_sessions" / "publication.lock"
        lock.write_bytes(b"unresolved")
        before = self.journal.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertEqual(lock.read_bytes(), b"unresolved")

    def test_missing_closed_session_proof_retains_journal(self):
        self.preserve()
        before = self.journal.read_bytes()
        (self.journals / "closed_sessions" / "records.json").write_bytes(b"{}")
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)

    def test_published_closure_with_unreleased_binding_cannot_retire_journal(self):
        self.preserve(release=False)
        original = os.replace

        def interrupted(*args):
            original(*args)
            raise OSError("publication outcome unconfirmed")

        before = self.journal.read_bytes()
        with patch("lab_sync_acquisition.ingestor.os.replace", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.intake.release_session("saved")
        self.assertEqual(self.intake.session_id, "saved")
        with self.assertRaises(RuntimeError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertTrue(self.intake.release_session("saved"))
        self.assertTrue(self.intake.retire_recovery_journal("saved"))

    def test_post_unlink_sync_failure_is_not_reported_as_success(self):
        expected = self.preserve()
        with patch.object(InMemoryIngestor, "_sync_closed_session_directory", side_effect=OSError("sync failed")):
            with self.assertRaises(OSError):
                self.intake.retire_recovery_journal("saved")
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.intake.read_session_closeout("saved"), expected)
        self.assertTrue(self.intake.retire_recovery_journal("saved"))

    def test_well_formed_other_session_history_is_not_deleted(self):
        self.preserve()
        lines = self.journal.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["session_id"] = "other"
        lines[0] = json.dumps(first)
        self.journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
        before = self.journal.read_bytes()
        with self.assertRaises(ValueError):
            self.intake.retire_recovery_journal("saved")
        self.assertEqual(self.journal.read_bytes(), before)


class ControllerCloseoutReadbackTests(CloseoutFixture, unittest.IsolatedAsyncioTestCase):
    async def test_lost_reply_retries_controller_reconciliation_after_retirement_and_restart(self):
        expected = self.preserve()
        self.intake.retire_recovery_journal("saved")
        intake = InMemoryIngestor(PersistentStorageManager(self.storage_root), recovery_journal_root=self.journals)
        controller = Controller(component_id="controller")
        fixture = self

        class ReadbackCommunication:
            def __init__(self):
                self.requests = 0

            async def request_persistence_command(self, target, operation, session_id, payload, window, *, command_id):
                fixture.assertEqual(target.component_type, "ingestor")
                fixture.assertEqual(operation, "read_session_closeout")
                proof = intake.read_session_closeout(session_id)
                self.requests += 1
                if self.requests == 1:
                    return None  # Authoritative read completed, but its reply was lost.
                return RuntimeCommandResultMessage("result", command_id, session_id,
                    "ingestor", "controller", "succeeded", True, None,
                    proof)

        communication = ReadbackCommunication()
        unconfirmed = await controller.reconcile_session_closeout("saved", communication=communication,
            ingestor_participant=RuntimeParticipant("ingestor", "ingestor"),
            storage_participant=RuntimeParticipant("storage_manager", self.storage._component_id),
            result_window_s=0.1)
        self.assertFalse(unconfirmed.succeeded)
        result = await controller.reconcile_session_closeout("saved", communication=communication,
            ingestor_participant=RuntimeParticipant("ingestor", "ingestor"),
            storage_participant=RuntimeParticipant("storage_manager", self.storage._component_id),
            result_window_s=0.1)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details, expected)
        self.assertFalse(self.journal.exists())
