"""Known-Session Stage B through real persistence and authorized recovery owners."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope, Controller, InMemoryIngestor, PersistentStorageManager, RuntimeCommandMessage,
    RuntimeEvidenceMessage, RuntimeParticipant, ServiceMaintenanceInterface, SshRetrievalEndpoint,
)
from tests import test_artifact_retrieval as retrieval
from tests import test_local_storage_hdf5 as hdf5
from tests import test_storage as records
from tests import test_acquisition_stage_archival as stages
from tests import test_authorized_recovery as recovery


class StageBCollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = self.new_storage()
        self.writer = hdf5.HDF5ScientificPersistenceTests()
        self.retrieval = retrieval.ArtifactRetrievalTests()
        self.baseline("session")

    def new_storage(self):
        return PersistentStorageManager(self.root / "records.jsonl", global_artifact_root=self.root / "global",
            retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "reader")})

    def baseline(self, session_id):
        intake = InMemoryIngestor(session_id=session_id,
            recovery_journal_path=self.root / f"journal-{session_id}.jsonl")
        local = self.writer.manager(self.root / f"local-{session_id}")
        self.addCleanup(local.finalize_all)
        manifest = self.writer.stream(local)
        # The HDF5 test helper's stream belongs to Session 'session'. Other Sessions need no artifacts.
        if session_id == "session":
            local.append_rows(manifest.storage_id, [self.writer.row(0), self.writer.row(1)])
            finalized = local.finalize_stream(manifest.storage_id)
            intake.receive_runtime_evidence(RuntimeEvidenceMessage("initial", session_id,
                "artifact_manifest", "node", manifest.to_dict(), True))
            intake.receive_runtime_evidence(RuntimeEvidenceMessage("finalized", session_id,
                "artifact_manifest", "node", finalized.to_dict(), True))
            manifests = [finalized]
            if getattr(self, "two_artifacts", False):
                second = local.create_stream(session_id="session", experiment_id="experiment",
                    acquisition_node_id="node", source_component_id="camera", data_product_id="frames-second",
                    artifact_type="camera_frames", schema={"frame_shape": [3, 4, 3], "frame_dtype": "uint16"},
                    storage_format="hdf5")
                local.append_rows(second.storage_id, [self.writer.row(0)])
                second = local.finalize_stream(second.storage_id)
                manifests.append(second)
                intake.receive_runtime_evidence(RuntimeEvidenceMessage("second-finalized", session_id,
                    "artifact_manifest", "node", second.to_dict(), True))
        marker = RuntimeEvidenceMessage("marker-" + session_id, session_id,
            "acquisition_evidence_completion", "controller", {}, True)
        intake.receive_runtime_evidence(RuntimeEvidenceMessage("transient", session_id, "note", "node", {}))
        intake.receive_runtime_evidence(RuntimeEvidenceMessage("", session_id, "note", "node", {}))
        intake.receive_runtime_evidence(marker)
        intake.receive_runtime_evidence(marker)
        self.storage.write_acquisition_stage(session_id, intake.compile_persistent_runtime_evidence(),
            receipt={"session_id": session_id, "durable_receipt_confirmed": True,
                     "evidence_id": marker.evidence_id, "marker_stream_sequence": 3},
            **records.PersistentStorageManagerTests._minimal_session_record_evidence(session_id))
        self.storage.write_artifact_collection_handoff(session_id, intake.compile_artifact_collection_handoff(session_id))
        if session_id == "session":
            self.intake = intake
            self.manifest = finalized
            self.manifests = manifests
            self.files = {m.local_storage_path: Path(m.local_storage_path).read_bytes() for m in manifests}
            self.sftp = retrieval.SftpDouble(self.files)

    def products(self):
        directory = self.root / "session_session"
        return {name: (directory / name).read_bytes() for name in (
            "evidence/runtime_evidence.jsonl", "evidence/ingest_audit.jsonl",
            "session_record_final.json", "artifact_collection_handoff.json")}

    def collect(self, storage=None, identity="collection"):
        transport, _ = self.retrieval.ssh(self.sftp)
        with transport:
            # Exercise the existing internal Stage B/recovery contract, not operator selection.
            return (storage or self.storage).collect_saved_artifacts(
                "session", evidence_id=identity, require_eligible=False)

    async def recover(self, storage=None, *, identity="recovery", evidence_id="collection"):
        storage = storage or self.storage
        intake = InMemoryIngestor(framework_recovery_journal_path=self.root / "framework-journal.jsonl")
        interface = ServiceMaintenanceInterface(storage, RuntimeParticipant("storage_manager", "storage"),
            ingestor=intake, storage_manager=storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        obligation = {"session_id": "session", "evidence_id": evidence_id}
        decision = await interface.record_administrator_decision("administrator", "resume",
            {"operation": "recover_archive_write", "obligation": obligation, "command_id": identity})
        command = RuntimeCommandMessage(identity, None, "recover_archive_write", "operator", "storage",
            {"authorization_evidence_id": decision["evidence"]["evidence_id"], "obligation": obligation})
        result = await interface.execute_command(command)
        return result, interface

    async def test_successful_direct_archival_preserves_stage_a_and_does_not_publish(self):
        before = self.products()
        journal = self.intake.recovery_journal_path.read_bytes()
        self.storage._evidence_publisher = AsyncMock(side_effect=AssertionError("Stage B must not publish"))
        result = self.collect()
        self.assertTrue(result["artifact_collection_result"]["succeeded"])
        self.assertTrue(result["outcome_durable"])
        self.assertTrue(result["archival_confirmed"])
        self.assertFalse(result["archive_closed"])
        self.assertIsNone(result["preservation_warning"])
        after = self.products()
        self.assertTrue(after["evidence/runtime_evidence.jsonl"].startswith(before["evidence/runtime_evidence.jsonl"]))
        for name in before.keys() - {"evidence/runtime_evidence.jsonl"}:
            self.assertEqual(before[name], after[name])
        self.assertEqual(self.intake.recovery_journal_path.read_bytes(), journal)
        self.storage._evidence_publisher.assert_not_called()
        confirmation = self.storage.get_persisted_session_preservation_confirmation("session")
        summary = confirmation["compilation_summary"]
        self.assertEqual(summary["runtime_evidence_origins"]["storage_manager"], ["collection"])
        self.assertEqual(confirmation["runtime_evidence"][-1], result["collection_evidence"])
        final = Path(result["artifact_collection_result"]["artifact_results"][0]["global_destination"])
        self.assertEqual(final.read_bytes(), self.files[self.manifest.local_storage_path])
        self.assertFalse((self.root / "session_session/artifact_collection_outcome.json").exists())

    async def test_restart_and_other_session_archival_do_not_require_cached_confirmation(self):
        self.baseline("another")
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation("session"))
        self.assertIsNotNone(self.storage.get_persisted_session_preservation_confirmation("session"))
        self.assertTrue(self.collect()["archival_confirmed"])
        restored = self.new_storage()
        self.assertIsNotNone(restored.get_persisted_session_preservation_confirmation("session"))
        before = self.products()
        repeat = self.collect(restored)
        self.assertTrue(repeat["archival_confirmed"])
        self.assertEqual(len(self.sftp.opened), 1)
        self.assertEqual(before, self.products())

    async def test_concurrent_identical_requests_do_not_refetch_or_duplicate_evidence(self):
        transport, _ = self.retrieval.ssh(self.sftp)
        with transport, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.storage.collect_saved_artifacts, "session", evidence_id="collection")
            second = pool.submit(self.storage.collect_saved_artifacts, "session", evidence_id="collection")
            self.assertTrue(first.result()["archival_confirmed"])
            self.assertTrue(second.result()["archival_confirmed"])
        self.assertEqual(len(self.sftp.opened), 1)
        saved = self.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertEqual(saved["compilation_summary"]["runtime_evidence_ids"].count("collection"), 1)

    async def test_later_attempt_keeps_previous_evidence_and_actual_nonoverwriting_failure(self):
        first = self.collect()
        before = self.products()
        second = self.collect(identity="second-collection")
        self.assertFalse(second["artifact_collection_result"]["succeeded"])
        self.assertTrue(second["archival_confirmed"])
        self.assertEqual(second["artifact_collection_result"]["artifact_results"][0]["outcome"], "failure")
        self.assertEqual(len(self.sftp.opened), 1)
        self.assertTrue(self.products()["evidence/runtime_evidence.jsonl"].startswith(before["evidence/runtime_evidence.jsonl"]))
        saved = self.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertIn(first["collection_evidence"], saved["runtime_evidence"])
        with self.assertRaises(RuntimeError):
            self.storage.write_evidence_archive("session", self.intake.compile_persistent_runtime_evidence())
        with self.assertRaises(RuntimeError):
            self.storage.write_final_session_record("session",
                **records.PersistentStorageManagerTests._minimal_session_record_evidence("session"))

    async def test_missing_corrupt_or_inconsistent_products_refuse_before_transfer(self):
        directory = self.root / "session_session"
        corruptions = {
            "evidence/runtime_evidence.jsonl": b"not json\n",
            "evidence/ingest_audit.jsonl": b"[]\n",
            "evidence/compilation_summary.json": b'{"stage_a_complete":true}',
            "session_record_final.json": b'{"accepted_session_config":{"session_id":"unrelated"}}',
            "artifact_collection_handoff.json": b'{"session_id":"session","artifacts":[]}',
        }
        for name, invalid in corruptions.items():
            path = directory / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(invalid)
                restored = self.new_storage()
                self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    self.collect(restored)
                self.assertEqual(path.read_bytes(), invalid)
                path.unlink()
                with self.assertRaises(OSError):
                    self.collect(restored)
                path.write_bytes(original)
        self.assertEqual(self.sftp.opened, [])

    async def test_closed_archive_and_identity_collision_refuse_without_changes(self):
        summary_path = self.root / "session_session/evidence/compilation_summary.json"
        original = summary_path.read_bytes()
        summary = json.loads(original)
        summary["archive_closed"] = True
        summary_path.write_text(json.dumps(summary))
        before = self.products()
        with self.assertRaises(RuntimeError):
            self.collect()
        with self.assertRaises(RuntimeError):
            self.storage.write_evidence_archive("session", self.intake.compile_persistent_runtime_evidence())
        self.assertEqual(self.products(), before)
        summary_path.write_bytes(original)
        with self.assertRaises(ValueError):
            self.collect(identity="finalized")
        self.assertEqual(self.sftp.opened, [])

    async def test_summary_interruption_requires_authorized_restart_recovery_without_refetch(self):
        before = self.products()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary unavailable")):
            failed = self.collect()
        self.assertTrue(failed["artifact_collection_result"]["succeeded"])
        self.assertTrue(failed["outcome_durable"])
        self.assertFalse(failed["archival_confirmed"])
        pending = self.root / "session_session/artifact_collection_outcome.json"
        self.assertTrue(pending.exists())
        restored = self.new_storage()
        repeat = self.collect(restored)
        self.assertFalse(repeat["archival_confirmed"])
        self.assertEqual(repeat["collection_evidence"], failed["collection_evidence"])
        self.assertEqual(len(self.sftp.opened), 1)
        with self.assertRaises(RuntimeError):
            self.collect(restored, identity="another-attempt")
        recovered, interface = await self.recover(restored)
        self.assertTrue(recovered.success, recovered.reason)
        self.assertFalse(recovered.payload["confirmation"]["artifact_refetch_performed"])
        self.assertFalse(pending.exists())
        self.assertEqual(len(self.sftp.opened), 1)
        self.assertTrue(self.collect(self.new_storage())["archival_confirmed"])
        after = self.products()
        for name in before.keys() - {"evidence/runtime_evidence.jsonl"}:
            self.assertEqual(after[name], before[name])

    async def test_partial_append_recovery_keeps_confirmed_prefix_and_rejects_conflict(self):
        before = self.products()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary unavailable")):
            failed = self.collect()
        path = self.root / "session_session/evidence/runtime_evidence.jsonl"
        appended = path.read_bytes()[len(before["evidence/runtime_evidence.jsonl"]):]
        path.write_bytes(before["evidence/runtime_evidence.jsonl"] + appended[:25])
        recovered, _ = await self.recover(self.new_storage())
        self.assertTrue(recovered.success, recovered.reason)
        self.assertTrue(path.read_bytes().startswith(before["evidence/runtime_evidence.jsonl"]))
        self.assertEqual(len(self.sftp.opened), 1)
        self.assertEqual(self.new_storage().get_persisted_session_preservation_confirmation("session")[
            "runtime_evidence"][-1], failed["collection_evidence"])

    async def test_conflicting_pending_suffix_cannot_be_repaired_or_refetched(self):
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary unavailable")):
            self.collect()
        path = self.root / "session_session/evidence/runtime_evidence.jsonl"
        path.write_bytes(path.read_bytes() + b"unowned conflicting bytes")
        before = path.read_bytes()
        recovered, _ = await self.recover(self.new_storage())
        self.assertFalse(recovered.success)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((self.root / "session_session/artifact_collection_outcome.json").exists())
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_pending_outcome_write_failure_retains_results_without_refetch(self):
        before = self.products()
        real_link = os.link
        def interrupt_outcome(source, target):
            if target.name == "artifact_collection_outcome.json":
                raise OSError("outcome publication unavailable")
            return real_link(source, target)
        with patch("lab_sync_acquisition.storage.os.link", side_effect=interrupt_outcome):
            failed = self.collect()
        self.assertTrue(failed["artifact_collection_result"]["succeeded"])
        self.assertFalse(failed["outcome_durable"])
        self.assertFalse(failed["archival_confirmed"])
        self.assertEqual(before, self.products())
        repeated = self.collect()
        self.assertFalse(repeated["archival_confirmed"])
        self.assertEqual(len(self.sftp.opened), 1)
        recovered, _ = await self.recover()
        self.assertTrue(recovered.success, recovered.reason)
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_interrupted_transfer_records_unknown_without_automatic_replay(self):
        def interrupted_open(source, mode):
            self.sftp.opened.append((source, mode))
            raise asyncio.CancelledError()
        with patch.object(self.sftp, "open", side_effect=interrupted_open):
            with self.assertRaises(asyncio.CancelledError):
                self.collect()
        repeat = self.collect(self.new_storage())
        self.assertTrue(repeat["archival_confirmed"])
        item = repeat["artifact_collection_result"]["artifact_results"][0]
        self.assertEqual(item["outcome"], "unknown")
        self.assertNotIn("global_destination", item)
        self.assertFalse(repeat["artifact_collection_result"]["succeeded"])
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_controller_without_session_binding_coordinates_saved_collection(self):
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["lifecycle_evidence"] = ({"from_state": "stopping", "to_state": "completed"},)
        evidence["final_session_status"] = {"state": "completed"}
        self.storage.write_final_session_record("session", **evidence)
        controller = Controller(storage_manager=self.new_storage())
        before = controller.get_status()
        transport, _ = self.retrieval.ssh(self.sftp)
        with transport:
            result = controller.collect_saved_session_artifacts("session", evidence_id="collection")
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["archival_confirmed"])
        self.assertEqual(controller.get_status()["session_id"], before["session_id"])
        self.assertEqual(controller.get_status()["session_state"], before["session_state"])

    async def test_failure_does_not_prevent_next_artifact_and_is_durably_recorded(self):
        fixture = StageBCollectionTests()
        fixture.two_artifacts = True
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.sftp.failures.add(fixture.manifests[0].local_storage_path)
        result = fixture.collect()
        self.assertTrue(result["archival_confirmed"])
        self.assertFalse(result["artifact_collection_result"]["succeeded"])
        attempts = result["artifact_collection_result"]["artifact_results"]
        self.assertEqual([item["outcome"] for item in attempts], ["failure", "success"])
        self.assertNotIn("global_destination", attempts[0])
        self.assertEqual(attempts[1]["verification_outcome"], "verified")
        self.assertEqual(fixture.sftp.opened, [(m.local_storage_path, "rb") for m in fixture.manifests])
        self.assertEqual(Path(attempts[1]["global_destination"]).read_bytes(),
                         fixture.files[fixture.manifests[1].local_storage_path])
        self.assertEqual(list((fixture.root / "global").rglob(".incomplete-*")), [])
        saved = fixture.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertEqual(saved["runtime_evidence"][-1], result["collection_evidence"])

    async def test_counts_audit_and_provenance_are_checked_not_only_stage_a_flag(self):
        directory = self.root / "session_session/evidence"
        summary_path = directory / "compilation_summary.json"
        original = summary_path.read_bytes()
        for field, value in (("runtime_evidence_count", 0), ("ingest_audit_count", 0),
                             ("runtime_evidence_origins", {"ingestor": []}),
                             ("acquisition_evidence_completion", {"evidence_id": "wrong", "marker_stream_sequence": 3})):
            with self.subTest(field=field):
                summary = json.loads(original)
                summary[field] = value
                summary_path.write_text(json.dumps(summary))
                self.assertIsNone(self.new_storage().get_persisted_session_preservation_confirmation("session"))
                with self.assertRaises(ValueError):
                    self.collect(self.new_storage())
        summary_path.write_bytes(original)
        audit_path = directory / "ingest_audit.jsonl"
        audit = [json.loads(line) for line in audit_path.read_bytes().splitlines()]
        for item in audit:
            if item["evidence_id"] == "finalized":
                item["accepted"] = False
        audit_path.write_text("".join(json.dumps(item) + "\n" for item in audit))
        self.assertIsNone(self.new_storage().get_persisted_session_preservation_confirmation("session"))
        self.assertEqual(self.sftp.opened, [])

    async def test_archive_change_during_transfer_retains_outcome_without_overwriting_it(self):
        path = self.root / "session_session/evidence/ingest_audit.jsonl"
        original_open = self.sftp.open
        def change_audit(source, mode):
            path.write_bytes(b"corrupt audit\n")
            return original_open(source, mode)
        with patch.object(self.sftp, "open", side_effect=change_audit):
            result = self.collect()
        self.assertTrue(result["artifact_collection_result"]["succeeded"])
        self.assertTrue(result["outcome_durable"])
        self.assertFalse(result["archival_confirmed"])
        self.assertEqual(path.read_bytes(), b"corrupt audit\n")
        recovered, _ = await self.recover(self.new_storage())
        self.assertFalse(recovered.success)
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_complete_append_with_failed_durability_confirmation_needs_authorized_recovery(self):
        sync = self.storage._sync_artifact_handoff_directory
        def interrupted_sync(path):
            if path.name == "compilation_summary.json":
                raise OSError("directory durability unavailable")
            sync(path)
        with patch.object(self.storage, "_sync_artifact_handoff_directory", side_effect=interrupted_sync):
            failed = self.collect()
        self.assertFalse(failed["archival_confirmed"])
        self.assertTrue(failed["outcome_durable"])
        restored = self.new_storage()
        self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
        self.assertFalse(self.collect(restored)["archival_confirmed"])
        self.assertIn("session", restored.maintenance_diagnostics(None, restored)["unfinished_archive_scopes"])
        recovered, _ = await self.recover(restored)
        self.assertTrue(recovered.success, recovered.reason)
        confirmation = self.new_storage().get_persisted_session_preservation_confirmation("session")
        self.assertEqual(confirmation["compilation_summary"]["runtime_evidence_ids"].count("collection"), 1)
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_pending_outcome_corruption_or_wrong_authorization_is_not_silently_accepted(self):
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary unavailable")):
            self.collect()
        pending = self.root / "session_session/artifact_collection_outcome.json"
        original = pending.read_bytes()
        result, _ = await self.recover(self.new_storage(), evidence_id="unrelated")
        self.assertFalse(result.success)
        self.assertEqual(pending.read_bytes(), original)
        pending.write_bytes(b"invalid outcome")
        with self.assertRaises(ValueError):
            self.collect(self.new_storage())
        result, _ = await self.recover(self.new_storage(), identity="second-recovery")
        self.assertFalse(result.success)
        self.assertEqual(pending.read_bytes(), b"invalid outcome")
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_interruption_keeps_prior_success_and_marks_only_unconfirmed_outcomes_unknown(self):
        fixture = StageBCollectionTests()
        fixture.two_artifacts = True
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        open_source = fixture.sftp.open
        def interrupt_second(source, mode):
            if source == fixture.manifests[1].local_storage_path:
                raise KeyboardInterrupt()
            return open_source(source, mode)
        with patch.object(fixture.sftp, "open", side_effect=interrupt_second):
            with self.assertRaises(KeyboardInterrupt):
                fixture.collect()
        result = fixture.collect(fixture.new_storage())
        items = result["artifact_collection_result"]["artifact_results"]
        self.assertEqual([item["outcome"] for item in items], ["success", "unknown"])
        self.assertEqual(Path(items[0]["global_destination"]).read_bytes(),
                         fixture.files[fixture.manifests[0].local_storage_path])
        self.assertTrue(result["archival_confirmed"])
        self.assertEqual(fixture.sftp.opened, [(fixture.manifests[0].local_storage_path, "rb")])

    async def test_empty_saved_handoff_records_empty_pass_without_inventing_artifacts(self):
        self.baseline("empty-session")
        result = self.new_storage().collect_saved_artifacts(
            "empty-session", evidence_id="empty-collection", require_eligible=False)
        self.assertTrue(result["archival_confirmed"])
        self.assertEqual(result["artifact_collection_result"], {"succeeded": True, "artifact_results": []})
        self.assertEqual(self.sftp.opened, [])
        self.assertIsNotNone(self.new_storage().get_persisted_session_preservation_confirmation("empty-session"))

    async def test_known_prior_collection_cannot_be_lost_by_replacing_archive_with_older_compilation(self):
        path = self.root / "session_session/evidence"
        original = {name: (path / name).read_bytes() for name in (
            "runtime_evidence.jsonl", "compilation_summary.json")}
        self.assertTrue(self.collect()["archival_confirmed"])
        for name, contents in original.items():
            (path / name).write_bytes(contents)
        self.assertIsNone(self.storage.get_persisted_session_preservation_confirmation("session"))
        with self.assertRaises(ValueError):
            self.collect(identity="second-collection")
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_unconfirmed_baseline_durability_cannot_start_collection(self):
        before = self.products()
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("baseline durability unavailable")):
            restored = self.new_storage()
            self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
            with self.assertRaises(OSError):
                self.collect(restored)
        self.assertEqual(self.products(), before)
        self.assertEqual(self.sftp.opened, [])

    async def test_actual_w043_w044_closeout_is_usable_without_original_bindings(self):
        stage = stages.AcquisitionStageArchivalTests()
        stage.addCleanup = self.addCleanup
        stage.setUp()
        await stage.prepare()
        await stage.acknowledge()
        result = await stage.archive()
        self.assertTrue(result.succeeded, result.error)
        saved = stage.fixture.controller.preserve_artifact_collection_handoff()
        self.assertTrue(saved.succeeded, saved.error)
        restored = PersistentStorageManager(stage.storage._records_path, global_artifact_root=self.root / "w043-global",
            retrieval_endpoints={"node-a": SshRetrievalEndpoint("fake", "reader")})
        handoff = restored.read_artifact_collection_handoff(stage.session_id)
        files = {entry["artifact_manifest"]["local_storage_path"]: b"" for entry in handoff["artifacts"]}
        sftp = retrieval.SftpDouble(files)
        transport, _ = self.retrieval.ssh(sftp)
        with transport:
            # Stage A preservation alone is not ordinary terminal-Session operator selection.
            collected = restored.collect_saved_artifacts(
                stage.session_id, evidence_id="collection", require_eligible=False)
        self.assertTrue(collected["archival_confirmed"])
        self.assertEqual(collected["artifact_collection_result"]["artifact_results"][0][
            "verification_outcome"], "copied_unverified")
        self.assertEqual(stage.fixture.controller.get_status()["session_state"], "stopping")

    async def test_missing_storage_provenance_cannot_authorize_destructive_replacement(self):
        collected = self.collect()
        self.assertTrue(collected["archival_confirmed"])
        summary_path = self.root / "session_session/evidence/compilation_summary.json"
        original = summary_path.read_bytes()
        for variant in ("missing_storage_origin", "missing_all_origins", "falsely_ingestor_owned"):
            with self.subTest(variant=variant):
                summary = json.loads(original)
                if variant == "missing_storage_origin":
                    summary["runtime_evidence_origins"].pop("storage_manager")
                elif variant == "missing_all_origins":
                    summary.pop("runtime_evidence_origins")
                else:
                    summary["runtime_evidence_origins"] = {"ingestor": summary["runtime_evidence_ids"]}
                summary_path.write_text(json.dumps(summary), encoding="utf-8")
                before, before_summary = self.products(), summary_path.read_bytes()
                for storage in (self.storage, self.new_storage()):
                    self.assertIsNone(storage.get_persisted_session_preservation_confirmation("session"))
                    with self.assertRaises(RuntimeError):
                        storage.write_evidence_archive("session", self.intake.compile_persistent_runtime_evidence())
                    with self.assertRaises(RuntimeError):
                        storage.write_final_session_record("session",
                            **records.PersistentStorageManagerTests._minimal_session_record_evidence("session"))
                    self.assertEqual(self.products(), before)
                    self.assertEqual(summary_path.read_bytes(), before_summary)
                self.assertIn(collected["collection_evidence"]["evidence_id"].encode(),
                              before["evidence/runtime_evidence.jsonl"])
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_incomplete_stage_b_archive_cannot_be_replaced(self):
        self.assertTrue(self.collect()["archival_confirmed"])
        directory = self.root / "session_session/evidence"
        for name in ("runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"):
            path = directory / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.unlink()
                restored = self.new_storage()
                before = {p.name: p.read_bytes() for p in directory.iterdir()}
                with self.assertRaises(RuntimeError):
                    restored.write_evidence_archive("session", self.intake.compile_persistent_runtime_evidence())
                self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
                path.write_bytes(original)
        self.assertEqual(len(self.sftp.opened), 1)

    async def test_cross_session_envelope_in_final_record_cannot_confirm_baseline(self):
        evidence = records.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["accepted_acquisition_envelopes"] = (AcquisitionRecordEnvelope(
            "session", "device", "events", [], "node"),)
        path = self.storage.write_final_session_record("session", **evidence)
        original = path.read_bytes()
        self.assertIsNotNone(self.new_storage().get_persisted_session_preservation_confirmation("session"))
        record = json.loads(original)
        record["accepted_acquisition_envelopes"][0]["session_id"] = "unrelated-session"
        path.write_text(json.dumps(record), encoding="utf-8")
        before = self.products()
        restored = self.new_storage()
        self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
        with self.assertRaises(ValueError):
            self.collect(restored)
        controller = Controller(storage_manager=restored)
        rejected = controller.collect_saved_session_artifacts("session", evidence_id="collection")
        self.assertFalse(rejected.succeeded)
        self.assertEqual(controller.get_status()["session_id"], None)
        self.assertEqual(self.products(), before)
        self.assertEqual(self.sftp.opened, [])
        self.assertFalse((path.parent / "artifact_collection_outcome.json").exists())
        path.write_bytes(original)
        self.assertTrue(self.collect(restored)["archival_confirmed"])

    async def test_incomplete_intake_audit_cannot_confirm_baseline(self):
        path = self.root / "session_session/evidence/ingest_audit.jsonl"
        original = path.read_bytes()
        for missing in (("ingest_received_at",), ("reason",), ("ingest_received_at", "reason")):
            with self.subTest(missing=missing):
                audit = [json.loads(line) for line in original.splitlines()]
                for item in audit:
                    for field in missing:
                        item.pop(field)
                path.write_text("".join(json.dumps(item) + "\n" for item in audit), encoding="utf-8")
                before = self.products()
                restored = self.new_storage()
                self.assertIsNone(restored.get_persisted_session_preservation_confirmation("session"))
                with self.assertRaises(ValueError):
                    self.collect(restored)
                with self.assertRaises(ValueError):
                    restored.write_evidence_archive("session", self.intake.compile_persistent_runtime_evidence())
                self.assertEqual(self.products(), before)
                self.assertEqual(self.sftp.opened, [])
                self.assertFalse((path.parent.parent / "artifact_collection_outcome.json").exists())
        path.write_bytes(original)
        self.assertTrue(self.collect(self.new_storage())["archival_confirmed"])

    async def test_partial_acquisition_archive_still_requires_and_allows_authorized_repair(self):
        fixture = recovery.AuthorizedRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = RuntimeEvidenceMessage("original", "session-a", "note", "source", {}, True)
        fixture.ingestor.receive_runtime_evidence(original)
        compilation = fixture.ingestor.compile_persistent_runtime_evidence()
        original_open = Path.open
        def fail_audit(path, *args, **kwargs):
            if (path.name == "ingest_audit.jsonl" and path.parent.parent.name == "session_session-a"
                    and args and args[0] == "w"):
                raise OSError("audit write interrupted")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", new=fail_audit):
            with self.assertRaises(OSError):
                fixture.storage.write_evidence_archive("session-a", compilation)
        runtime_path = fixture.root / "session_session-a/evidence/runtime_evidence.jsonl"
        initial_bytes = runtime_path.read_bytes()
        with self.assertRaises(RuntimeError):
            fixture.storage.write_evidence_archive("session-a", compilation)
        self.assertEqual(runtime_path.read_bytes(), initial_bytes)
        command = await fixture.authorize("recover_archive_write", {"session_id": "session-a"})
        result = await fixture.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
        self.assertEqual(runtime_path.read_bytes(), initial_bytes)
        audit_path = runtime_path.parent / "ingest_audit.jsonl"
        self.assertEqual([json.loads(line) for line in audit_path.read_bytes().splitlines()],
                         [item.to_dict() for item in compilation["ingest_audit"]])


if __name__ == "__main__":
    unittest.main()
