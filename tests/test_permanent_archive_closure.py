"""Explicit permanent closure through existing Stage A/B persistence owners."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

from lab_sync_acquisition import PersistentStorageManager
from tests import test_stage_b_collection as collection
from tests import test_storage as records


class PermanentArchiveClosureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = collection.StageBCollectionTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.directory = self.fixture.root / "session_session"
        self.summary_path = self.directory / "evidence/compilation_summary.json"

    def snapshot(self):
        return {**self.fixture.products(), "evidence/compilation_summary.json": self.summary_path.read_bytes()}

    async def test_only_explicit_closure_changes_summary_and_preserves_all_other_products(self):
        collected = self.fixture.collect()
        self.assertTrue(collected["archival_confirmed"])
        self.assertFalse(collected["archive_closed"])
        before = self.snapshot()
        self.fixture.baseline("another")
        result = self.fixture.new_storage().close_session_evidence_archive("session")
        self.assertTrue(result["archive_closed"])
        self.assertTrue(result["archival_confirmed"])
        self.assertEqual(result["session_id"], "session")
        self.assertEqual(set(result["paths"]), {"runtime_evidence", "ingest_audit", "compilation_summary",
                                               "session_record", "artifact_collection_handoff"})
        after = self.snapshot()
        for name in before.keys() - {"evidence/compilation_summary.json"}:
            self.assertEqual(after[name], before[name])
        expected = json.loads(before["evidence/compilation_summary.json"])
        expected["archive_closed"] = True
        self.assertEqual(json.loads(after["evidence/compilation_summary.json"]), expected)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        for source, content in self.fixture.files.items():
            self.assertEqual(Path(source).read_bytes(), content)

    async def test_failed_retrieval_can_close_when_its_outcome_is_preserved(self):
        self.fixture.sftp.failures.add(self.fixture.manifest.local_storage_path)
        collected = self.fixture.collect()
        self.assertFalse(collected["artifact_collection_result"]["succeeded"])
        self.assertTrue(collected["archival_confirmed"])
        self.assertEqual(collected["artifact_collection_result"]["artifact_results"][0]["outcome"], "failure")
        before = self.fixture.products()
        self.assertTrue(self.fixture.storage.close_session_evidence_archive("session")["archive_closed"])
        self.assertEqual(self.fixture.products(), before)

    async def test_failed_verification_can_close_without_changing_the_global_copy(self):
        self.fixture.sftp.files = {self.fixture.manifest.local_storage_path: b"invalid HDF5"}
        collected = self.fixture.collect()
        item = collected["artifact_collection_result"]["artifact_results"][0]
        self.assertEqual(item["verification_outcome"], "structurally_invalid")
        self.assertFalse(collected["artifact_collection_result"]["succeeded"])
        destination = Path(item["global_destination"])
        self.assertTrue(self.fixture.storage.close_session_evidence_archive("session")["archival_confirmed"])
        self.assertEqual(destination.read_bytes(), b"invalid HDF5")

    async def test_durably_recorded_unknown_outcome_can_close_without_refetch(self):
        with patch.object(self.fixture.sftp, "open", side_effect=asyncio.CancelledError()):
            with self.assertRaises(asyncio.CancelledError):
                self.fixture.collect()
        preserved = self.fixture.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertEqual(preserved["runtime_evidence"][-1]["payload"]["artifact_results"][0][
            "collection_status"], "unknown")
        before = self.fixture.products()
        self.assertTrue(self.fixture.new_storage().close_session_evidence_archive("session")["archive_closed"])
        self.assertEqual(self.fixture.products(), before)
        self.assertEqual(self.fixture.sftp.opened, [])

    async def test_pending_evidence_blocks_closure_until_authorized_recovery(self):
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary interrupted")):
            collected = self.fixture.collect()
        self.assertTrue(collected["outcome_durable"])
        self.assertFalse(collected["archival_confirmed"])
        before = self.snapshot()
        for storage in (self.fixture.storage, self.fixture.new_storage()):
            with self.assertRaises(RuntimeError):
                storage.close_session_evidence_archive("session")
            self.assertEqual(self.snapshot(), before)
        restored = self.fixture.new_storage()
        recovered, _ = await self.fixture.recover(restored)
        self.assertTrue(recovered.success, recovered.reason)
        self.assertTrue(restored.close_session_evidence_archive("session")["archive_closed"])
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_retained_outcome_without_durability_cannot_be_omitted_by_closure(self):
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("outcome unavailable")):
            collected = self.fixture.collect()
        self.assertFalse(collected["outcome_durable"])
        before = self.snapshot()
        with self.assertRaises(RuntimeError):
            self.fixture.storage.close_session_evidence_archive("session")
        self.assertEqual(self.snapshot(), before)

    async def test_inconsistent_or_missing_products_cannot_confirm_closure(self):
        self.fixture.collect()
        originals = self.snapshot()
        for name, original in originals.items():
            path = self.directory / name
            with self.subTest(product=name):
                path.write_bytes(b"corrupt")
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    self.fixture.new_storage().close_session_evidence_archive("session")
                self.assertEqual(path.read_bytes(), b"corrupt")
                path.unlink()
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    self.fixture.new_storage().close_session_evidence_archive("session")
                path.write_bytes(original)
        self.assertEqual(self.snapshot(), originals)

    async def test_unconfirmed_final_record_write_prevents_closure(self):
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("record unconfirmed")):
            with self.assertRaises(OSError):
                self.fixture.storage.write_final_session_record("session", **evidence)
        before = self.snapshot()
        with self.assertRaises(RuntimeError):
            self.fixture.storage.close_session_evidence_archive("session")
        self.assertEqual(self.snapshot(), before)

    async def test_closed_flag_cannot_confirm_corrupted_products_or_authorize_repair(self):
        self.fixture.collect()
        self.fixture.storage.close_session_evidence_archive("session")
        runtime_path = self.directory / "evidence/runtime_evidence.jsonl"
        original = runtime_path.read_bytes()
        runtime_path.write_bytes(original + b"corrupt\n")
        before = self.snapshot()
        restored = self.fixture.new_storage()
        self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
        with self.assertRaises((RuntimeError, ValueError)):
            restored.close_session_evidence_archive("session")
        self.assertEqual(self.snapshot(), before)
        runtime_path.write_bytes(original)
        self.assertTrue(restored.close_session_evidence_archive("session")["archival_confirmed"])

    async def test_missing_closure_summary_cannot_authorize_record_or_handoff_replacement(self):
        self.fixture.collect()
        self.fixture.storage.close_session_evidence_archive("session")
        summary = self.summary_path.read_bytes()
        self.summary_path.unlink()
        before = self.fixture.products()
        restored = self.fixture.new_storage()
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        with self.assertRaises(RuntimeError):
            restored.write_session_record(self.directory / "session_record_final.json", **evidence)
        with self.assertRaises(RuntimeError):
            restored.write_artifact_collection_handoff("session", self.fixture.intake.compile_artifact_collection_handoff("session"))
        recovered, _ = await self.fixture.recover(restored)
        self.assertFalse(recovered.success)
        self.assertEqual(self.fixture.products(), before)
        self.assertFalse(self.summary_path.exists())
        self.assertFalse((self.directory / "artifact_collection_outcome.json").exists())
        self.summary_path.write_bytes(summary)
        self.assertTrue(restored.close_session_evidence_archive("session")["archival_confirmed"])

    async def test_closure_serializes_with_a_generic_record_write_using_a_path_alias(self):
        serializing, finish_serializing, closure_entered = Event(), Event(), Event()
        class PausedLifecycle:
            def to_dict(self):
                serializing.set()
                if not finish_serializing.wait(5):
                    raise AssertionError("record writer was not released")
                return {"state": "stopping"}
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["lifecycle_evidence"] = (PausedLifecycle(),)
        alias = self.directory / ".." / self.directory.name / "session_record_final.json"
        before = self.snapshot()
        def close():
            closure_entered.set()
            return self.fixture.storage.close_session_evidence_archive("session")
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(self.fixture.storage.write_session_record, alias, **evidence)
            try:
                self.assertTrue(serializing.wait(5))
                closing = pool.submit(close)
                self.assertTrue(closure_entered.wait(5))
                self.assertFalse(closing.done())
                self.assertEqual(self.snapshot(), before)
            finally:
                finish_serializing.set()
            writing.result(timeout=5)
            self.assertTrue(closing.result(timeout=5)["archival_confirmed"])

    async def test_closed_final_record_rejects_nested_parent_alias_after_restart(self):
        self.fixture.collect()
        self.fixture.storage.close_session_evidence_archive("session")
        (self.directory / "nested").mkdir()
        (self.fixture.root / "root-alias").mkdir()
        target = self.directory / "session_record_final.json"
        alias = self.directory / "nested" / ".." / target.name
        self.assertEqual(alias.resolve(), target.resolve())
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["warnings_or_failures"] = ("must not be written after closure",)
        before = self.snapshot()
        storages = (
            self.fixture.storage,
            self.fixture.new_storage(),
            PersistentStorageManager(self.fixture.root / "root-alias" / ".."),
        )
        for storage in storages:
            with self.subTest(storage=storage):
                with self.assertRaises(RuntimeError):
                    storage.write_session_record(alias, **evidence)
                self.assertEqual(self.snapshot(), before)
                self.assertTrue(storage.close_session_evidence_archive("session")["archival_confirmed"])
                self.assertEqual(self.snapshot(), before)

    async def test_preclosure_nested_path_and_storage_root_alias_support_record_writing(self):
        (self.directory / "nested").mkdir()
        (self.fixture.root / "root-alias").mkdir()
        alias = self.directory / "nested" / ".." / "session_record_final.json"
        storage = PersistentStorageManager(self.fixture.root / "root-alias" / "..")
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["warnings_or_failures"] = ("legitimate pre-closure record",)
        storage.write_session_record(alias, **evidence)
        record = storage.read_session_record(self.directory / "session_record_final.json")
        self.assertEqual(record["warnings_or_failures"], list(evidence["warnings_or_failures"]))
        self.assertFalse(json.loads(self.summary_path.read_bytes())["archive_closed"])

    async def test_repeated_closure_and_restart_reconfirm_without_rewriting(self):
        self.fixture.collect()
        first = self.fixture.storage.close_session_evidence_archive("session")
        before = self.snapshot()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("closed archive rewrite")):
            self.assertEqual(self.fixture.storage.close_session_evidence_archive("session"), first)
            restored = self.fixture.new_storage()
            self.assertEqual(restored.close_session_evidence_archive("session"), first)
            self.assertTrue(restored.get_persisted_session_preservation_confirmation("session")[
                "compilation_summary"]["archive_closed"])
        self.assertEqual(self.snapshot(), before)

    async def test_interruption_before_publication_preserves_open_archive_and_allows_retry(self):
        self.fixture.collect()
        before = self.snapshot()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("publication interrupted")):
            with self.assertRaises(OSError):
                self.fixture.storage.close_session_evidence_archive("session")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list((self.directory / "evidence").glob(".incomplete-*")), [])
        self.assertTrue(self.fixture.new_storage().close_session_evidence_archive("session")["archival_confirmed"])

    async def test_failed_postpublication_durability_requires_reconfirmation_not_reopening(self):
        self.fixture.collect()
        before = self.fixture.products()
        published = False
        replace, fsync = os.replace, os.fsync
        def publish(source, target):
            nonlocal published
            replace(source, target)
            published = True
        def fail_after_publication(descriptor):
            if published:
                raise OSError("closure durability unconfirmed")
            return fsync(descriptor)
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=publish), \
                patch("lab_sync_acquisition.storage.os.fsync", side_effect=fail_after_publication):
            with self.assertRaises(OSError):
                self.fixture.storage.close_session_evidence_archive("session")
            self.assertIsNone(self.fixture.storage.get_persisted_session_preservation_confirmation("session"))
        self.assertTrue(json.loads(self.summary_path.read_bytes())["archive_closed"])
        self.assertEqual(self.fixture.products(), before)
        restored = self.fixture.new_storage()
        with self.assertRaises(RuntimeError):
            self.fixture.collect(restored, identity="later")
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("must only reconfirm")):
            self.assertTrue(restored.close_session_evidence_archive("session")["archival_confirmed"])

    async def test_closed_archive_refuses_owner_writes_and_authorized_recovery_after_restart(self):
        self.fixture.collect()
        self.fixture.storage.close_session_evidence_archive("session")
        before = self.snapshot()
        restored = self.fixture.new_storage()
        compiled = self.fixture.intake.compile_persistent_runtime_evidence()
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        handoff = self.fixture.intake.compile_artifact_collection_handoff("session")
        operations = (
            lambda: self.fixture.collect(restored, identity="later"),
            lambda: restored.write_evidence_archive("session", compiled),
            lambda: restored.write_final_session_record("session", **evidence),
            lambda: restored.write_session_record(self.directory / "session_record_final.json", **evidence),
            lambda: restored.write_artifact_collection_handoff("session", handoff),
            lambda: restored.write_acquisition_stage("session", compiled,
                receipt={"session_id": "session", "durable_receipt_confirmed": True,
                         "evidence_id": "marker-session", "marker_stream_sequence": 3}, **evidence),
        )
        for operation in operations:
            with self.assertRaises(RuntimeError):
                operation()
            self.assertEqual(self.snapshot(), before)
        recovered, _ = await self.fixture.recover(restored)
        self.assertFalse(recovered.success)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.directory / "artifact_collection_outcome.json").exists())
        self.assertTrue(restored.close_session_evidence_archive("session")["archival_confirmed"])

    async def test_closure_waits_for_admitted_collection_and_includes_its_evidence(self):
        transfer_entered, release_transfer, closure_entered = Event(), Event(), Event()
        original = self.fixture.sftp.open
        def paused_open(source, mode):
            transfer_entered.set()
            if not release_transfer.wait(5):
                raise AssertionError("collection was not released")
            return original(source, mode)
        def close():
            closure_entered.set()
            return self.fixture.storage.close_session_evidence_archive("session")
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport, patch.object(self.fixture.sftp, "open", side_effect=paused_open), \
                ThreadPoolExecutor(max_workers=2) as pool:
            collecting = pool.submit(self.fixture.storage.collect_saved_artifacts, "session", evidence_id="collection", require_eligible=False)
            try:
                self.assertTrue(transfer_entered.wait(5))
                closing = pool.submit(close)
                self.assertTrue(closure_entered.wait(5))
                self.assertFalse(closing.done())
            finally:
                release_transfer.set()
            collected = collecting.result(timeout=5)
            self.assertTrue(closing.result(timeout=5)["archival_confirmed"])
        preserved = self.fixture.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertIn(collected["collection_evidence"], preserved["runtime_evidence"])
        self.assertTrue(preserved["compilation_summary"]["archive_closed"])

    async def test_overlapping_closure_requests_publish_only_once(self):
        self.fixture.collect()
        publishing, release_publication, second_entered = Event(), Event(), Event()
        replace = os.replace
        publications = []
        def paused_replace(source, target):
            publications.append(target)
            publishing.set()
            if not release_publication.wait(5):
                raise AssertionError("closure was not released")
            replace(source, target)
        def second_close():
            second_entered.set()
            return self.fixture.storage.close_session_evidence_archive("session")
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=paused_replace), \
                ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.fixture.storage.close_session_evidence_archive, "session")
            try:
                self.assertTrue(publishing.wait(5))
                second = pool.submit(second_close)
                self.assertTrue(second_entered.wait(5))
                self.assertFalse(second.done())
            finally:
                release_publication.set()
            self.assertEqual(first.result(timeout=5), second.result(timeout=5))
        self.assertEqual(len(publications), 1)


if __name__ == "__main__":
    unittest.main()
