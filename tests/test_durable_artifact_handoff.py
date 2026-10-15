"""Durable closeout handoffs through existing compilation and persistence owners."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, LocalStorageManager, PersistentStorageManager, RuntimeEvidenceMessage, SessionConfig
from tests import test_acquisition_stage_archival as stage_fixtures


class DurableArtifactHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root)
        self.ingestor = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "journal.jsonl")
        self.local = LocalStorageManager(self.root / "local", "session", "node")
        self.addCleanup(self.local.finalize_all)
        self.manifest = self.local.create_stream(session_id="session", experiment_id="experiment",
            acquisition_node_id="node", source_component_id="device", artifact_type="events",
            data_product_id="events", schema={"value": "number"})
        self.record(self.manifest, "initial")

    def record(self, manifest, identity):
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
            identity, "session", "artifact_manifest", "node", manifest.to_dict(), True))

    def handoff(self):
        return self.ingestor.compile_artifact_collection_handoff("session")

    def test_finalized_handoff_roundtrip_and_restart_without_original_bindings(self):
        finalized = self.local.finalize_stream(self.manifest.storage_id)
        self.record(finalized, "finalized")
        expected = self.handoff()
        journal = self.ingestor.recovery_journal_path.read_bytes()
        path = self.storage.write_artifact_collection_handoff("session", expected)
        self.assertEqual(path, self.root / "session_session/artifact_collection_handoff.json")
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertEqual(expected["artifacts"], [{"artifact_manifest": finalized.to_dict(),
                                                "missing_finalization_evidence": False}])
        restored = PersistentStorageManager(self.root)
        self.assertEqual(restored.read_artifact_collection_handoff("session"), expected)
        self.assertEqual(self.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertFalse((path.parent / "evidence").exists())
        self.assertFalse((path.parent / "session_record_final.json").exists())

    def test_missing_and_uncertain_finalization_remain_explicit(self):
        uncertain = replace(self.manifest, artifact_manifest_id="uncertain", experiment_id="second",
                            details={"finalization_error": "device unavailable"})
        self.record(uncertain, "uncertain")
        expected = self.handoff()
        self.storage.write_artifact_collection_handoff("session", expected)
        actual = self.storage.read_artifact_collection_handoff("session")
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual["artifacts"]), 2)
        self.assertTrue(all(entry["missing_finalization_evidence"] for entry in actual["artifacts"]))
        self.assertEqual(actual["artifacts"][1]["artifact_manifest"]["details"], uncertain.details)

    def test_empty_handoff_does_not_invent_artifacts(self):
        empty = self.ingestor.compile_artifact_collection_handoff("empty")
        self.storage.write_artifact_collection_handoff("empty", empty)
        self.assertEqual(self.storage.read_artifact_collection_handoff("empty"), empty)
        with self.assertRaises(FileNotFoundError):
            self.storage.read_artifact_collection_handoff("unrelated")

    def test_identical_and_concurrent_retries_do_not_replace_the_file(self):
        expected = self.handoff()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.storage.write_artifact_collection_handoff("session", expected), range(2)))
        path = results[0]
        self.assertEqual(results, [path, path])
        contents, before = path.read_bytes(), path.stat()
        self.assertEqual(self.storage.write_artifact_collection_handoff("session", expected), path)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(list(path.parent.glob(".incomplete-handoff-*")), [])

    def test_conflicting_and_corrupt_existing_handoffs_are_not_overwritten(self):
        path = self.storage.write_artifact_collection_handoff("session", self.handoff())
        contents = path.read_bytes()
        changed = deepcopy(self.handoff())
        changed["artifacts"][0]["artifact_manifest"]["details"]["new_information"] = True
        with self.assertRaisesRegex(ValueError, "differs"):
            self.storage.write_artifact_collection_handoff("session", changed)
        self.assertEqual(path.read_bytes(), contents)
        path.write_text("{interrupted", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.storage.write_artifact_collection_handoff("session", self.handoff())
        self.assertEqual(path.read_text(), "{interrupted")
        restored = PersistentStorageManager(self.root)
        with self.assertRaises(ValueError):
            restored.read_artifact_collection_handoff("session")

    def test_failed_temporary_write_and_publication_allow_safe_explicit_retry(self):
        expected = self.handoff()
        path = self.root / "session_session/artifact_collection_handoff.json"
        for target in ("lab_sync_acquisition.storage.os.fsync", "lab_sync_acquisition.storage.os.link"):
            with self.subTest(target=target):
                with patch(target, side_effect=OSError("persistence interrupted")):
                    with self.assertRaises(OSError):
                        self.storage.write_artifact_collection_handoff("session", expected)
                self.assertFalse(path.exists())
                self.assertEqual(list(path.parent.glob(".incomplete-handoff-*")), [])
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            self.storage.read_artifact_collection_handoff("session")
        self.storage.write_artifact_collection_handoff("session", expected)
        self.assertEqual(self.storage.read_artifact_collection_handoff("session"), expected)

    def test_interruption_after_publication_does_not_confirm_until_durable_retry(self):
        expected = self.handoff()
        with patch.object(self.storage, "_sync_artifact_handoff_directory", side_effect=OSError("directory sync interrupted")):
            with self.assertRaises(OSError):
                self.storage.write_artifact_collection_handoff("session", expected)
        path = self.root / "session_session/artifact_collection_handoff.json"
        contents = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            self.storage.read_artifact_collection_handoff("session")
        self.storage.write_artifact_collection_handoff("session", expected)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(self.storage.read_artifact_collection_handoff("session"), expected)

    def test_inconsistent_identity_and_finalization_information_are_refused(self):
        cases = []
        wrong_session = deepcopy(self.handoff())
        wrong_session["artifacts"][0]["artifact_manifest"]["session_id"] = "unrelated"
        cases.append(wrong_session)
        wrong_flag = deepcopy(self.handoff())
        wrong_flag["artifacts"][0]["missing_finalization_evidence"] = False
        cases.append(wrong_flag)
        duplicate = deepcopy(self.handoff())
        duplicate["artifacts"] *= 2
        cases.append(duplicate)
        for malformed in cases:
            with self.subTest(handoff=malformed), self.assertRaises(ValueError):
                self.storage.write_artifact_collection_handoff("session", malformed)
        with self.assertRaises(ValueError):
            self.storage.read_artifact_collection_handoff("../unrelated")
        self.assertFalse((self.root / "session_session").exists())

    def test_independent_writer_cannot_overwrite_a_competing_publication(self):
        entered, resume = Event(), Event()
        write = self.storage._write_record_contents

        def pause(path, contents):
            write(path, contents)
            entered.set()
            if not resume.wait(5):
                raise TimeoutError("test publication was not released")

        other = PersistentStorageManager(self.root)
        competing = deepcopy(self.handoff())
        competing["artifacts"][0]["artifact_manifest"]["details"]["diagnostic"] = "competing input"
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(self.storage, "_write_record_contents", side_effect=pause):
            future = pool.submit(self.storage.write_artifact_collection_handoff, "session", self.handoff())
            try:
                self.assertTrue(entered.wait(5))
                path = other.write_artifact_collection_handoff("session", competing)
                contents = path.read_bytes()
            finally:
                resume.set()
            with self.assertRaises(FileExistsError):
                future.result(timeout=5)
        self.assertEqual(path.read_bytes(), contents)
        self.assertEqual(other.read_artifact_collection_handoff("session"), competing)
        with self.assertRaisesRegex(ValueError, "differs"):
            self.storage.write_artifact_collection_handoff("session", self.handoff())
        self.assertEqual(path.read_bytes(), contents)

    def test_readback_rejects_duplicate_json_fields_and_malformed_manifest_collections(self):
        path = self.storage.write_artifact_collection_handoff("session", self.handoff())
        for contents in ('{"session_id":"other","session_id":"session","artifacts":[]}',
                         json.dumps({"session_id": "session", "artifacts": None})):
            with self.subTest(contents=contents):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.storage.read_artifact_collection_handoff("session")
        wrong_paths = self.handoff()
        wrong_paths["artifacts"][0]["artifact_manifest"]["local_managed_paths"] = "not a path list"
        path.write_text(json.dumps(wrong_paths), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.storage.read_artifact_collection_handoff("session")


class CloseoutArtifactHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stage = stage_fixtures.AcquisitionStageArchivalTests()
        self.stage.setUp()
        self.addCleanup(self.stage.doCleanups)
        self.fixture = self.stage.fixture
        self.storage = self.stage.storage

    async def prepare(self):
        await self.stage.prepare()
        await self.stage.acknowledge()
        archived = await self.stage.archive()
        self.assertTrue(archived.succeeded, archived.error)
        return archived

    async def test_explicit_handoff_step_preserves_stage_a_and_unchanged_lifecycle(self):
        archived = await self.prepare()
        paths = [Path(value) for value in archived.details["paths"].values()]
        before = {path: path.read_bytes() for path in paths}
        expected = self.fixture.ingestor.compile_artifact_collection_handoff(self.stage.session_id)
        result = self.fixture.controller.preserve_artifact_collection_handoff()
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["handoff_preservation_confirmed"])
        self.assertEqual(self.storage.read_artifact_collection_handoff(self.stage.session_id), expected)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertIsNotNone(self.storage.get_acquisition_stage_preservation_confirmation(self.stage.session_id))
        repeated = self.fixture.controller.preserve_artifact_collection_handoff()
        self.assertTrue(repeated.succeeded, repeated.error)

    async def test_missing_stage_a_and_lost_journal_cannot_authorize_handoff(self):
        await self.stage.prepare()
        early = self.fixture.controller.preserve_artifact_collection_handoff()
        self.assertFalse(early.succeeded)
        await self.stage.acknowledge()
        self.assertTrue((await self.stage.archive()).succeeded)
        self.fixture.ingestor.recovery_journal_path.write_bytes(b"")
        result = self.fixture.controller.preserve_artifact_collection_handoff()
        self.assertFalse(result.succeeded)
        self.assertIn("journal coverage", result.error)
        self.assertEqual(self.fixture.controller.get_status()["session_id"], self.stage.session_id)

    async def test_handoff_failure_retains_binding_and_stage_a_and_can_retry(self):
        await self.prepare()
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("publication unavailable")):
            failed = self.fixture.controller.preserve_artifact_collection_handoff()
        self.assertFalse(failed.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "stopping")
        self.assertEqual(self.fixture.ingestor.session_id, self.stage.session_id)
        self.assertIsNotNone(self.storage.get_acquisition_stage_preservation_confirmation(self.stage.session_id))
        self.assertTrue(self.fixture.controller.preserve_artifact_collection_handoff().succeeded)

    async def test_q019_release_requires_current_handoff_and_later_read_needs_no_binding(self):
        await self.prepare()
        self.assertTrue(self.fixture.controller.preserve_artifact_collection_handoff().succeeded)
        sid = self.stage.session_id
        expected = self.storage.read_artifact_collection_handoff(sid)
        path = self.fixture.root / f"session_{sid}/artifact_collection_handoff.json"
        self.assertTrue(self.fixture.controller.finalize_session().succeeded)
        # Existing finalization is used only to exercise the existing terminal release API.
        # Full Q019 Normal Stop orchestration remains a separate implementation slice.
        good = path.read_bytes()
        alias = deepcopy(expected)
        self.assertEqual(alias["artifacts"][0]["artifact_manifest"]["details"]["row_count"], 0)
        alias["artifacts"][0]["artifact_manifest"]["details"]["row_count"] = False
        for contents in ("{}", json.dumps(alias)):
            path.write_text(contents, encoding="utf-8")
            self.assertFalse((await self.fixture.controller.release_session()).succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_id"], sid)
        path.write_bytes(good)
        released = await self.fixture.controller.release_session()
        self.assertTrue(released.succeeded, released.error)
        for contents in ("{}", json.dumps(alias)):
            path.write_text(contents, encoding="utf-8")
            with self.assertRaises((ValueError, RuntimeError)):
                self.fixture.ingestor.release_session(sid, storage_manager=self.storage)
        self.assertEqual(self.fixture.ingestor.session_id, sid)
        path.write_bytes(good)
        self.assertTrue(self.fixture.ingestor.release_session(sid, storage_manager=self.storage))
        restored = PersistentStorageManager(self.fixture.root)
        self.assertIsNone(self.fixture.controller.get_status()["session_id"])
        self.assertIsNone(self.fixture.ingestor.session_id)
        self.assertEqual(restored.read_artifact_collection_handoff(sid), expected)

    async def test_delayed_handoff_request_cannot_record_failure_in_a_new_binding(self):
        await self.prepare()
        controller, intake = self.fixture.controller, self.fixture.ingestor
        self.assertTrue(controller.preserve_artifact_collection_handoff().succeeded)
        self.assertTrue(controller.finalize_session().succeeded)
        original_session = self.stage.session_id
        history = intake.durable_runtime_evidence_history_guard
        entered, resume = Event(), Event()

        @contextmanager
        def paused(*args):
            entered.set()
            if not resume.wait(5):
                raise TimeoutError("test handoff request was not resumed")
            with history(*args) as confirmed:
                yield confirmed

        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(intake, "durable_runtime_evidence_history_guard", new=paused):
            future = pool.submit(controller.preserve_artifact_collection_handoff)
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue((await controller.release_session()).succeeded)
                self.assertTrue(intake.release_session(original_session, storage_manager=self.storage))
                created = controller.create_session(SessionConfig(None, None, None,
                    str(self.fixture.root / "errors"), session_id="session-b"))
                self.assertTrue(created.succeeded, created.error)
                self.assertTrue(intake.prepare_session("session-b").ready)
                before = controller.get_status()
            finally:
                resume.set()
            stale = future.result(timeout=5)
        self.assertFalse(stale.succeeded)
        self.assertEqual(stale.details["session_id"], original_session)
        self.assertEqual(controller.get_status(), before)
        self.assertEqual(intake.session_id, "session-b")
