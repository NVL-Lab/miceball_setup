"""Operator selection from independently validated saved Session information."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests import test_stage_b_collection as stages
from tests import test_storage as records
from lab_sync_acquisition import Controller


class SavedSessionSelectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = stages.StageBCollectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.storage = self.fixture.storage
        self.root = self.fixture.root
        self.terminal("session")

    def terminal(self, sid, state="completed"):
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence(sid)
        evidence["lifecycle_evidence"] = ({"from_state": "stopping", "to_state": state,
                                           "sequence": 1, "reason": None},)
        evidence["final_session_status"] = {"state": state} if state != "stopping" else None
        self.storage.write_final_session_record(sid, **evidence)

    def saved_baseline(self, sid):
        manager = self.fixture.writer.manager

        def tracked_manager(*args, **kwargs):
            local = manager(*args, **kwargs)
            self.addCleanup(local.cleanup)
            return local

        with patch.object(self.fixture.writer, "manager", side_effect=tracked_manager):
            self.fixture.baseline(sid)

    async def test_enumeration_keeps_incomplete_and_conflicting_candidates_after_restart(self):
        (self.root / "session_missing").mkdir()
        (self.root / "unrelated").mkdir()
        self.storage.write_final_session_record("conflict",
            **records.PersistentStorageManagerTests._minimal_session_record_evidence("another"))
        items = {i["session_id"]: i for i in self.fixture.new_storage().list_saved_sessions()}
        self.assertEqual(set(items), {"session", "missing", "conflict"})
        self.assertTrue(items["session"]["collection_available"])
        for sid in ("missing", "conflict"):
            self.assertFalse(items[sid]["eligible"])
            self.assertFalse(items[sid]["collection_available"])
            self.assertTrue(items[sid]["availability_reason"])

    async def test_terminal_states_qualify_without_participant_cleanup(self):
        for state in ("completed", "failed", "aborted", "stopping"):
            with self.subTest(state=state):
                self.terminal("session", state)
                status = self.fixture.new_storage().get_saved_session_collection_status("session")
                self.assertEqual(status["lifecycle_state"], state)
                self.assertEqual(status["eligible"], state != "stopping")
                self.assertEqual(status["collection_available"], state != "stopping")

    async def test_missing_scientific_source_is_available_but_actual_collection_fails(self):
        self.fixture.files.clear()
        status = self.storage.get_saved_session_collection_status("session")
        self.assertTrue(status["collection_available"])
        controller = Controller(storage_manager=self.storage)
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = controller.collect_selected_session_artifacts({"session": "missing-source"})
        self.assertFalse(result.succeeded)
        item = result.details["session_results"][0]
        self.assertTrue(item["eligible"])
        self.assertTrue(item["collection_available"])
        self.assertTrue(item["collection_outcome"]["archival_confirmed"])

    async def test_corrupt_scientific_bytes_do_not_block_attempt(self):
        self.fixture.files[self.fixture.manifest.local_storage_path] = b"not HDF5"
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = Controller(storage_manager=self.storage).collect_selected_session_artifacts(
                {"session": "invalid-file"})
        item = result.details["session_results"][0]
        self.assertTrue(item["collection_available"])
        self.assertEqual(item["collection_outcome"]["artifact_collection_result"]["artifact_results"][0]
                         ["verification_outcome"], "structurally_invalid")

    async def test_corrupted_or_missing_preservation_blocks_not_eligibility(self):
        path = self.root / "session_session" / "evidence" / "ingest_audit.jsonl"
        before = path.read_bytes()
        for contents in (b"invalid JSON", b""):
            path.write_bytes(contents)
            status = self.fixture.new_storage().get_saved_session_collection_status("session")
            self.assertTrue(status["eligible"])
            self.assertFalse(status["collection_available"])
            self.assertTrue(status["availability_reason"])
        path.write_bytes(before)
        (self.root / "session_session" / "artifact_collection_handoff.json").unlink()
        self.assertFalse(self.storage.get_saved_session_collection_status("session")["collection_available"])

    async def test_closed_archive_is_visible_eligible_and_unavailable(self):
        self.storage.close_session_evidence_archive("session")
        before = self.fixture.products()
        restored = self.fixture.new_storage()
        status = restored.list_saved_sessions()[0]
        self.assertTrue(status["eligible"])
        self.assertFalse(status["collection_available"])
        result = Controller(storage_manager=restored).collect_selected_session_artifacts({"session": "closed"})
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.products(), before)

    async def test_interrupted_evidence_blocks_selection_without_recovery_or_refetch(self):
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("interrupted")):
            outcome = self.fixture.collect()
        self.assertFalse(outcome["archival_confirmed"])
        restored = self.fixture.new_storage()
        status = restored.get_saved_session_collection_status("session")
        self.assertTrue(status["eligible"])
        self.assertFalse(status["collection_available"])
        opened = list(self.fixture.sftp.opened)
        result = Controller(storage_manager=restored).collect_selected_session_artifacts({"session": "collection"})
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.details["session_results"][0]["collection_outcome"])
        self.assertEqual(self.fixture.sftp.opened, opened)

    async def test_mixed_selection_continues_after_failure_and_blocks_unavailable(self):
        self.saved_baseline("good")
        self.terminal("good", "aborted")
        self.terminal("stopping", "stopping")
        self.terminal("unavailable", "failed")
        self.fixture.files.clear()
        controller = Controller(storage_manager=self.fixture.new_storage())
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = controller.collect_selected_session_artifacts({"session": "failure", "stopping": "no",
                                                                    "unavailable": "no", "good": "success"})
        self.assertEqual(result.details["summary"], "partial_success")
        items = result.details["session_results"]
        self.assertEqual([item["succeeded"] for item in items], [False, False, False, True])
        self.assertIsNone(items[1]["collection_outcome"])
        self.assertIsNone(items[2]["collection_outcome"])
        self.assertIsNone(controller.get_status()["session_id"])

    async def test_repeated_success_is_idempotent_and_rechecks_lifecycle_before_transfer(self):
        controller = Controller(storage_manager=self.storage)
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            first = controller.collect_selected_session_artifacts({"session": "stable"})
            second = controller.collect_selected_session_artifacts({"session": "stable"})
        self.assertTrue(first.succeeded, first.error)
        self.assertTrue(second.succeeded, second.error)
        self.assertEqual(first.details, second.details)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        self.saved_baseline("changed")
        self.terminal("changed")
        status = self.storage.get_saved_session_collection_status("changed")
        self.terminal("changed", "stopping")
        with patch.object(self.storage, "get_saved_session_collection_status", return_value=status):
            rejected = controller.collect_selected_session_artifacts({"changed": "late"})
        self.assertFalse(rejected.succeeded)
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_collection_exception_does_not_prevent_other_selected_session(self):
        self.saved_baseline("good")
        self.terminal("good")
        collect = self.storage.collect_saved_artifacts

        def fail_one(sid, **kwargs):
            if sid == "session":
                raise OSError("transport unavailable")
            return collect(sid, **kwargs)

        with patch.object(self.storage, "collect_saved_artifacts", side_effect=fail_one):
            result = Controller(storage_manager=self.storage).collect_selected_session_artifacts(
                {"session": "failed-request", "good": "confirmed"})
        self.assertEqual(result.details["summary"], "partial_success")
        self.assertIn("transport unavailable", result.details["session_results"][0]["error"])
        self.assertTrue(result.details["session_results"][1]["succeeded"])


if __name__ == "__main__":
    unittest.main()
