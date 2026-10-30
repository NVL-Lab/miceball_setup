"""Explicit service-owned recovery through existing administrative commands."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, DeviceDeclaration, DeviceManager, InMemoryIngestor, LocalStorageManager,
    PersistentStorageManager, RuntimeCommandMessage, RuntimeEvidenceMessage, RuntimeParticipant,
    ServiceMaintenanceInterface, SshRetrievalEndpoint, SynchronizationManager,
    ScientificOutputSelection, ScientificProductDeclaration, DeviceAdapterState,
)
from tests.fakes import ReadyFakeAdapter
from tests import test_storage as storage_fixtures
from tests import test_artifact_retrieval as retrieval_fixtures


class AuthorizedRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        async def publish(message):
            self.ingestor.receive_runtime_evidence(message)
        self.storage = PersistentStorageManager(self.root,
            global_artifact_root=self.root / "global", retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "user")},
            evidence_publisher=publish)
        self.ingestor = InMemoryIngestor(self.storage, session_id="session-a",
            recovery_journal_path=self.root / "session.jsonl", framework_recovery_journal_path=self.root / "framework.jsonl")
        self.interface = ServiceMaintenanceInterface(self.storage, RuntimeParticipant("storage_manager", "storage"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))

    async def authorize(self, operation, obligation, *, identity="recovery", interface=None):
        interface = interface or self.interface
        result = await interface.record_administrator_decision("administrator", "resume",
            {"operation": operation, "obligation": obligation, "command_id": identity, "reason": "explicit recovery attempt"})
        return RuntimeCommandMessage(identity, None, operation, "operator", interface.participant.component_id,
            {"authorization_evidence_id": result["evidence"]["evidence_id"], "obligation": obligation})

    def interrupt_archive(self, *, framework=True):
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("original", None if framework else "session-a",
            "warning", "source", {}, True))
        original = Path.open
        def interrupt(path, mode="r", *args, **kwargs):
            if "w" in mode and path.name in {"runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"}:
                raise OSError("archive interrupted")
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, "open", interrupt):
            with self.assertRaises(OSError):
                if framework:
                    self.storage.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())
                else:
                    self.storage.write_evidence_archive("session-a", self.ingestor.compile_persistent_runtime_evidence())

    async def test_archive_repair_requires_durable_authorization_and_attempt_before_write(self):
        self.interrupt_archive()
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            command = await self.authorize("recover_archive_write", {"session_id": None})
        original = self.storage._write_framework_evidence_archive
        writes = []
        def verify_acceptance(compiled, **kwargs):
            messages = self.ingestor.compile_framework_runtime_evidence()["runtime_evidence"]
            auth = next(m for m in messages if m.evidence_id == command.payload["authorization_evidence_id"])
            attempt = next(m for m in messages if m.evidence_type == "service_recovery_evidence"
                and m.payload.get("checkpoint") == "attempt_recorded")
            self.assertTrue(self.ingestor.has_durable_runtime_evidence(auth))
            self.assertTrue(self.ingestor.has_durable_runtime_evidence(attempt))
            writes.append(compiled)
            return original(compiled, **kwargs)
        with patch.object(self.storage, "_write_framework_evidence_archive", side_effect=verify_acceptance):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await self.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
        self.assertTrue(result.payload["preservation"]["archival_confirmed"])
        self.assertEqual(len(writes), 2)
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())

    async def test_failed_journal_acceptance_refuses_repair_and_preserves_obligation(self):
        self.interrupt_archive()
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("journal unavailable")):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                command = await self.authorize("recover_archive_write", {"session_id": None})
        with patch.object(self.storage, "write_framework_evidence_archive", wraps=self.storage.write_framework_evidence_archive) as writer:
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await self.interface.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(result.payload["actual_outcome"], "refused")
        writer.assert_not_called()
        self.assertIn(None, self.storage.maintenance_diagnostics(self.ingestor, self.storage)["unfinished_archive_scopes"])

    async def test_prior_month_interrupted_write_is_not_implicitly_reassigned_by_authorized_retry(self):
        with patch("lab_sync_acquisition.storage.time", return_value=datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp()):
            self.interrupt_archive()
        with patch("lab_sync_acquisition.storage.time", return_value=datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                command = await self.authorize("recover_archive_write", {"session_id": None})
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await self.interface.execute_command(command)
        self.assertFalse(result.success)
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertFalse((self.root / "framework/evidence/2026-01").exists())
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(next(
            m for m in self.ingestor.compile_framework_runtime_evidence()["runtime_evidence"]
            if m.evidence_id == "original")))

    async def test_mismatched_scope_and_command_authorization_cannot_write(self):
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        altered = RuntimeCommandMessage("different-command", None, command.command_type, "operator", "storage", command.payload)
        result = await self.interface.execute_command(altered)
        self.assertEqual(result.payload["actual_outcome"], "refused")
        self.assertIn("session-a", self.storage.maintenance_diagnostics(self.ingestor, self.storage)["unfinished_archive_scopes"])

    async def test_duplicate_command_returns_original_result_without_second_attempt(self):
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        first = await self.interface.execute_command(command)
        self.assertTrue(first.success, first.reason)
        journal = (self.root / "framework.jsonl").read_bytes()
        second = await self.interface.execute_command(command)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual((self.root / "framework.jsonl").read_bytes(), journal)

    async def test_actual_write_success_is_distinct_from_outcome_archival_failure(self):
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        original = self.storage.write_framework_evidence_archive
        calls = []
        def fail_outcome(compiled):
            calls.append(compiled)
            if len(calls) == 2:
                raise OSError("outcome archive unavailable")
            return original(compiled)
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=fail_outcome):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await self.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
        self.assertFalse(result.payload["preservation"]["archival_confirmed"])
        self.assertTrue(result.payload["preservation"]["preservation_warning"])
        self.assertTrue(any(m.payload.get("actual_outcome") == "succeeded" for m in self.interface.evidence))

    async def test_session_record_repair_uses_retained_exact_inputs_without_lifecycle_change(self):
        evidence = storage_fixtures.PersistentStorageManagerTests._minimal_session_record_evidence("session-a")
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("record interrupted")):
            with self.assertRaises(OSError):
                self.storage.write_final_session_record("session-a", **evidence)
        command = await self.authorize("recover_session_record_write", {"session_id": "session-a", "record_kind": "final"})
        result = await self.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        record = self.storage.read_session_record(result.payload["confirmation"]["path"])
        self.assertEqual(record["accepted_session_config"]["session_id"], "session-a")
        self.assertEqual(record["final_session_status"], evidence["final_session_status"])
        self.assertEqual(self.storage.maintenance_diagnostics(self.ingestor, self.storage)["unfinished_record_paths"], [])

    async def test_missing_complete_record_inputs_are_refused(self):
        with self.assertRaises(TypeError):
            self.storage.write_final_session_record("session-a")
        command = await self.authorize("recover_session_record_write", {"session_id": "session-a", "record_kind": "final"})
        result = await self.interface.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(result.payload["actual_outcome"], "refused")

    async def test_later_abandonment_invalidates_an_earlier_authorization(self):
        self.interrupt_archive(framework=False)
        obligation = {"session_id": "session-a"}
        command = await self.authorize("recover_archive_write", obligation)
        await self.interface.record_administrator_decision("administrator", "drop", {"obligation": obligation})
        result = await self.interface.execute_command(command)
        self.assertEqual(result.payload["actual_outcome"], "refused")
        self.assertIn("superseded", result.reason)

    async def test_fresh_transfer_reuses_source_manifest_and_nonoverwriting_verification(self):
        local = LocalStorageManager(self.root / "local", "session-a", "node")
        manifest = local.create_stream(session_id="session-a", experiment_id="experiment", acquisition_node_id="node",
            source_component_id="camera", data_product_id="frames", artifact_type="camera_frames",
            schema={"frame_shape": [2, 3], "frame_dtype": "uint8"}, storage_format="hdf5")
        final = local.finalize_stream(manifest.storage_id)
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("manifest", "session-a", "artifact_manifest", "node", final.to_dict(), True))
        files = {final.local_storage_path: Path(final.local_storage_path).read_bytes()}
        fixture = retrieval_fixtures.ArtifactRetrievalTests()
        with fixture.ssh(retrieval_fixtures.SftpDouble(files, failures=(final.local_storage_path,)))[0]:
            original = await self.storage.collect_artifacts_with_evidence(self.ingestor.compile_artifact_collection_handoff("session-a"))
        self.assertFalse(original.succeeded)
        previous = next(m for m in self.ingestor.accepted_runtime_evidence if m.evidence_type == "global_artifact_collection_evidence")
        command = await self.authorize("recover_artifact_transfer", {"session_id": "session-a", "evidence_id": previous.evidence_id,
            "artifact_manifest_id": final.artifact_manifest_id})
        with fixture.ssh(retrieval_fixtures.SftpDouble(files))[0]:
            result = await self.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        copied = result.payload["confirmation"]["artifact_results"][0]
        self.assertEqual(copied["verification_outcome"], "verified")
        evidence = [m for m in self.ingestor.accepted_runtime_evidence
                    if m.evidence_type == "global_artifact_collection_evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(result.payload["collection_evidence_id"], evidence[-1].evidence_id)
        self.assertTrue(result.payload["collection_evidence_submission"]["acceptance_confirmed"])
        self.assertEqual(Path(copied["global_destination"]).read_bytes(), files[final.local_storage_path])
        self.assertEqual(Path(final.local_storage_path).read_bytes(), files[final.local_storage_path])
        self.assertFalse(list((self.root / "global").rglob(".incomplete-*")))
        again = await self.authorize("recover_artifact_transfer", command.payload["obligation"], identity="new-attempt")
        refused = await self.interface.execute_command(again)
        self.assertFalse(refused.success)
        self.assertEqual(Path(copied["global_destination"]).read_bytes(), files[final.local_storage_path])

    def prepared_node(self):
        adapter = ReadyFakeAdapter("device", "fake", (), True)
        declaration = DeviceDeclaration("device", "fake", True, True, (),
            (ScientificProductDeclaration("events", "events", {}, "jsonl"),))
        node = AcquisitionNode(device_manager=DeviceManager((adapter,)),
            synchronization_manager=SynchronizationManager(), ingestor=self.ingestor, node_id="node", role="acquisition",
            default_local_storage_root=self.root / "node-data", device_declarations=(declaration,))
        self.assertTrue(node.reserve("session-a"))
        self.assertTrue(node.initialize_session("session-a", (declaration,)).ready)
        interface = ServiceMaintenanceInterface(node, RuntimeParticipant("acquisition_node", "node"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        return node, adapter, interface

    def interrupted_local_artifact(self, node):
        self.assertTrue(node.prepare_experiment_scientific_outputs("experiment",
            (ScientificOutputSelection("device", "node", "events"),)).ready)
        local = node.local_storage_manager
        manifest, = local.manifests
        local.append_rows(manifest.storage_id, ({"session_time_s": 2.0, "experiment_time_s": 1.0,
            "acquisition_node_local_time_s": 5.0, "timestamp_status": "runtime_timestamped",
            "experiment_id": "experiment", "value": 42},))
        with patch("lab_sync_acquisition.local_storage.os.fsync", side_effect=OSError("flush interrupted")):
            with self.assertRaises(RuntimeError):
                node.finalize_experiment_scientific_outputs("experiment")
        self.addCleanup(local.cleanup)
        return {"session_id": "session-a", "experiment_id": "experiment",
                "storage_id": manifest.storage_id, "artifact_manifest_id": manifest.artifact_manifest_id}

    async def test_device_cleanup_and_artifact_preservation_confirm_independently(self):
        node, adapter, interface = self.prepared_node()
        obligation = self.interrupted_local_artifact(node)
        before = Path(node.local_storage_manager.manifests[0].local_storage_path).read_bytes()
        cleanup = await self.authorize("cleanup_device_resources", {"session_id": "session-a", "device_ids": ["device"]}, interface=interface)
        cleaned = await interface.execute_command(cleanup)
        self.assertTrue(cleaned.success, cleaned.reason)
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
        self.assertFalse(cleaned.payload["confirmation"]["node_cleanup_confirmed"])
        self.assertFalse(node.release_reservation("session-a"))
        preserve = await self.authorize("preserve_scientific_artifact", obligation, identity="preserve", interface=interface)
        result = await interface.execute_command(preserve)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["node_cleanup_confirmed"])
        final = result.payload["confirmation"]["artifact_manifest"]
        self.assertEqual(final["artifact_manifest_id"], obligation["artifact_manifest_id"])
        self.assertEqual(Path(final["local_storage_path"]).read_bytes(), before)
        self.assertEqual(node.reserved_for_session_id, "session-a")
        self.assertTrue(node.release_reservation("session-a"))

    async def test_failed_device_release_retains_protection_and_requires_new_explicit_attempt(self):
        node, adapter, interface = self.prepared_node()
        obligation = {"session_id": "session-a", "device_ids": ["device"]}
        command = await self.authorize("cleanup_device_resources", obligation, interface=interface)
        with patch.object(adapter, "_shutdown_resources", side_effect=OSError("release failed")):
            result = await interface.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(result.payload["actual_outcome"], "failed")
        self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
        self.assertFalse(node.release_reservation("session-a"))
        restored = await self.authorize("cleanup_device_resources", obligation, identity="explicit-second", interface=interface)
        success = await interface.execute_command(restored)
        self.assertTrue(success.success, success.reason)
        self.assertTrue(node.release_reservation("session-a"))

    async def test_local_finalization_success_remains_visible_when_manifest_acceptance_fails(self):
        node, _, interface = self.prepared_node()
        obligation = self.interrupted_local_artifact(node)
        command = await self.authorize("preserve_scientific_artifact", obligation, interface=interface)
        original = self.ingestor.receive_runtime_evidence
        def fail_manifest(message):
            if message.evidence_type == "artifact_manifest" and message.payload["lifecycle_state"] == "finalized":
                raise ConnectionError("manifest acceptance unavailable")
            return original(message)
        with patch.object(self.ingestor, "receive_runtime_evidence", side_effect=fail_manifest):
            result = await interface.execute_command(command)
        self.assertFalse(result.success)
        self.assertTrue(result.payload["confirmation"]["local_finalization_confirmed"])
        self.assertFalse(result.payload["confirmation"]["manifest_acceptance_confirmed"])
        self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
        self.assertEqual(node.reserved_for_session_id, "session-a")

        retained = node.artifact_manifest_evidence[-1].to_dict()
        artifact = Path(retained["payload"]["local_storage_path"])
        before = artifact.read_bytes()
        second = await self.authorize("preserve_scientific_artifact", obligation,
            identity="still-unavailable", interface=interface)
        with patch.object(self.ingestor, "receive_runtime_evidence", side_effect=fail_manifest), \
                patch.object(node.local_storage_manager, "finalize_stream", wraps=node.local_storage_manager.finalize_stream) as finalize:
            failed = await interface.execute_command(second)
        self.assertFalse(failed.success)
        self.assertEqual(failed.payload["actual_outcome"], "failed")
        self.assertTrue(failed.payload["confirmation"]["local_finalization_confirmed"])
        self.assertFalse(failed.payload["confirmation"]["manifest_acceptance_confirmed"])
        finalize.assert_not_called()
        self.assertEqual(node.artifact_manifest_evidence[-1].to_dict(), retained)
        self.assertEqual(artifact.read_bytes(), before)
        self.assertEqual(node.reserved_for_session_id, "session-a")

    async def test_new_authorized_artifact_recovery_resubmits_identical_manifest_without_refinalizing(self):
        node, adapter, interface = self.prepared_node()
        obligation = self.interrupted_local_artifact(node)
        first = await self.authorize("preserve_scientific_artifact", obligation, identity="first", interface=interface)
        original = self.ingestor.receive_runtime_evidence
        def fail_manifest(message):
            if message.evidence_type == "artifact_manifest" and message.payload["lifecycle_state"] == "finalized":
                raise ConnectionError("manifest intake unavailable")
            return original(message)
        with patch.object(self.ingestor, "receive_runtime_evidence", side_effect=fail_manifest):
            failed = await interface.execute_command(first)
        self.assertFalse(failed.success)
        retained = node.artifact_manifest_evidence[-1]
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(retained))
        evidence = retained.to_dict()
        local = node.local_storage_manager
        paths = {Path(path): Path(path).read_bytes() for path in local.manifests[0].local_managed_paths}
        local_evidence = local.evidence
        device_state = adapter.state
        second = await self.authorize("preserve_scientific_artifact", obligation, identity="second", interface=interface)
        self.assertNotEqual(first.payload["authorization_evidence_id"], second.payload["authorization_evidence_id"])
        with patch.object(self.ingestor, "receive_runtime_evidence", wraps=original) as intake, \
                patch.object(local, "finalize_stream", wraps=local.finalize_stream) as finalize:
            recovered = await interface.execute_command(second)
        self.assertTrue(recovered.success, recovered.reason)
        self.assertTrue(recovered.payload["confirmation"]["local_finalization_confirmed"])
        self.assertTrue(recovered.payload["confirmation"]["manifest_acceptance_confirmed"])
        finalize.assert_not_called()
        submitted = [call.args[0] for call in intake.call_args_list if call.args[0].evidence_type == "artifact_manifest"]
        self.assertEqual([message.to_dict() for message in submitted], [evidence])
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(retained))
        self.assertEqual(node.artifact_manifest_evidence[-1].to_dict(), evidence)
        self.assertEqual(local.evidence, local_evidence)
        self.assertEqual({path: path.read_bytes() for path in paths}, paths)
        self.assertEqual(adapter.state, device_state)
        self.assertEqual(self.ingestor.session_id, "session-a")
        self.assertEqual(node.reserved_for_session_id, "session-a")
        handoff = self.ingestor.compile_artifact_collection_handoff("session-a")
        self.assertEqual(handoff["artifacts"], [{"artifact_manifest": evidence["payload"], "missing_finalization_evidence": False}])
        self.assertEqual(sum(m.evidence_id == retained.evidence_id for m in self.ingestor.accepted_runtime_evidence), 1)
        self.assertFalse(node.prepare_experiment_scientific_outputs("experiment",
            (ScientificOutputSelection("device", "node", "events"),)).ready)

    async def test_artifact_recovery_rejects_in_memory_acceptance_without_manifest_durability(self):
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework-only.jsonl")
        node, _, interface = self.prepared_node()
        obligation = self.interrupted_local_artifact(node)
        first = await self.authorize("preserve_scientific_artifact", obligation, identity="no-journal-first", interface=interface)
        failed = await interface.execute_command(first)
        self.assertFalse(failed.success)
        self.assertTrue(failed.payload["confirmation"]["local_finalization_confirmed"])
        self.assertFalse(failed.payload["confirmation"]["manifest_acceptance_confirmed"])
        retained = node.artifact_manifest_evidence[-1]
        self.assertIn(retained, self.ingestor.accepted_runtime_evidence)
        second = await self.authorize("preserve_scientific_artifact", obligation, identity="no-journal-second", interface=interface)
        with patch.object(node.local_storage_manager, "finalize_stream", wraps=node.local_storage_manager.finalize_stream) as finalize:
            still_failed = await interface.execute_command(second)
        finalize.assert_not_called()
        self.assertFalse(still_failed.success)
        self.assertEqual(still_failed.payload["actual_outcome"], "failed")
        self.assertFalse(still_failed.payload["confirmation"]["manifest_acceptance_confirmed"])
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(retained))
        self.assertEqual(sum(m.evidence_id == retained.evidence_id for m in self.ingestor.accepted_runtime_evidence), 1)

    async def test_durable_manifest_needs_no_resubmission_during_normal_finalization_or_authorized_recovery(self):
        node, adapter, interface = self.prepared_node()
        self.assertTrue(node.prepare_experiment_scientific_outputs("experiment",
            (ScientificOutputSelection("device", "node", "events"),)).ready)
        local = node.local_storage_manager
        self.addCleanup(local.cleanup)
        finalized, = node.finalize_experiment_scientific_outputs("experiment")
        retained = node.artifact_manifest_evidence[-1]
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(retained))
        evidence = [message.to_dict() for message in node.artifact_manifest_evidence]
        self.assertEqual([m["payload"]["lifecycle_state"] for m in evidence], ["open", "finalized"])
        paths = {Path(path): Path(path).read_bytes() for path in finalized.local_managed_paths}
        device_state = adapter.state
        with patch.object(self.ingestor, "receive_runtime_evidence", wraps=self.ingestor.receive_runtime_evidence) as intake:
            self.assertEqual(node.finalize_experiment_scientific_outputs("experiment"), (finalized,))
        intake.assert_not_called()
        command = await self.authorize("preserve_scientific_artifact", {
            "session_id": "session-a", "experiment_id": "experiment", "storage_id": finalized.storage_id,
            "artifact_manifest_id": finalized.artifact_manifest_id}, interface=interface)
        with patch.object(self.ingestor, "receive_runtime_evidence", wraps=self.ingestor.receive_runtime_evidence) as intake, \
                patch.object(local, "finalize_stream", wraps=local.finalize_stream) as finalize:
            result = await interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["manifest_acceptance_confirmed"])
        finalize.assert_not_called()
        self.assertFalse(any(call.args[0].evidence_type == "artifact_manifest" for call in intake.call_args_list))
        self.assertEqual([message.to_dict() for message in node.artifact_manifest_evidence], evidence)
        self.assertEqual({path: path.read_bytes() for path in paths}, paths)
        self.assertEqual(node.reserved_for_session_id, "session-a")
        self.assertEqual(adapter.state, device_state)

    async def test_binding_change_during_attempt_publication_refuses_stale_cleanup(self):
        node, adapter, interface = self.prepared_node()
        obligation = {"session_id": "session-a", "device_ids": ["device"]}
        command = await self.authorize("cleanup_device_resources", obligation, interface=interface)
        started, finish = asyncio.Event(), asyncio.Event()
        async def publish(message):
            if message.payload.get("checkpoint") == "attempt_recorded":
                started.set()
                await finish.wait()
            self.ingestor.receive_runtime_evidence(message)
        interface.evidence_publisher = publish
        task = asyncio.create_task(interface.execute_command(command))
        try:
            await asyncio.wait_for(started.wait(), 5)
            self.assertTrue(node.abort_session_initialization("session-a"))
            self.assertTrue(node.release_reservation("session-a"))
            self.assertTrue(node.reserve("session-b"))
            finish.set()
            result = await task
            self.assertEqual(result.payload["actual_outcome"], "refused")
            self.assertEqual(node.reserved_for_session_id, "session-b")
        finally:
            finish.set()
            await task

    async def test_cancelled_attempt_cannot_be_replayed_by_duplicate_command(self):
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        entered = asyncio.Event()
        async def publish(message):
            if message.payload.get("checkpoint") == "attempt_recorded":
                entered.set()
                await asyncio.Event().wait()
            self.ingestor.receive_runtime_evidence(message)
        self.interface.evidence_publisher = publish
        task = asyncio.create_task(self.interface.execute_command(command))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            with patch.object(self.storage, "write_evidence_archive", wraps=self.storage.write_evidence_archive) as writer:
                result = await self.interface.execute_command(command)
            writer.assert_not_called()
            self.assertFalse(result.success)
            self.assertEqual(result.payload["actual_outcome"], "failed")
            self.assertEqual(result.payload["actions"], [])
            self.assertIn("session-a", self.storage.maintenance_diagnostics(self.ingestor, self.storage)["unfinished_archive_scopes"])
            self.assertTrue(any(m.payload.get("actual_outcome") == "failed" for m in self.interface.evidence))
        finally:
            if not task.done():
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_cancellation_after_confirmed_action_retains_outcome_without_reexecution(self):
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        entered = asyncio.Event()
        async def publish(message):
            if message.payload.get("actual_outcome") == "succeeded":
                entered.set()
                await asyncio.Event().wait()
            self.ingestor.receive_runtime_evidence(message)
        self.interface.evidence_publisher = publish
        task = asyncio.create_task(self.interface.execute_command(command))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with patch.object(self.storage, "write_evidence_archive", wraps=self.storage.write_evidence_archive) as writer:
                result = await self.interface.execute_command(command)
            writer.assert_not_called()
            self.assertTrue(result.success)
            self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
            self.assertFalse(result.payload["preservation"]["archival_confirmed"])
            self.assertTrue(result.payload["preservation"]["preservation_warning"])
            self.assertTrue(any(m.payload.get("actual_outcome") == "succeeded" for m in self.interface.evidence))
        finally:
            if not task.done():
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

    async def test_authorized_recovery_uses_existing_nats_command_and_evidence_paths(self):
        from lab_sync_acquisition import NatsControllerCommunication, NatsIngestorCommunication, NatsServiceMaintenanceCommunication
        from tests.test_session_launch import _Boundary, _Broker
        self.interrupt_archive(framework=False)
        command = await self.authorize("recover_archive_write", {"session_id": "session-a"})
        broker = _Broker()
        intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", broker), self.ingestor)
        subscription = await intake.subscribe_evidence(None)
        self.addAsyncCleanup(subscription.unsubscribe)
        handler = NatsServiceMaintenanceCommunication(_Boundary("storage_manager", "storage", broker), self.interface)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        issuer = NatsControllerCommunication(_Boundary("controller", "operator", broker))
        self.addAsyncCleanup((await issuer.subscribe_command_results(None)).unsubscribe)
        result = await issuer.request_command(self.interface.participant, command.command_type, None,
            command.payload, 1, command_id=command.command_id)
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.command_id, command.command_id)
        self.assertTrue(result.payload["preservation"]["publication_confirmed"])
        self.assertTrue(result.payload["preservation"]["acceptance_confirmed"])
        self.assertTrue(result.payload["preservation"]["archival_confirmed"])
