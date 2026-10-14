"""Explicit Kill preserves partial evidence independently of participant cleanup."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from threading import Event
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (AcquisitionRecordEnvelope, Controller, InMemoryIngestor,
                                 PersistentStorageManager, ScientificOutputSelection,
                                 RuntimeParticipant, ServiceMaintenanceInterface, SshRetrievalEndpoint)
from tests import test_normal_stop as normal
from tests import test_authorized_recovery as recovery
from tests import test_storage as records
from tests import test_artifact_retrieval as retrieval


class KillSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.normal = normal.NormalStopTests()
        self.normal.setUp()
        self.addCleanup(self.normal.doCleanups)
        self.fixture = self.normal.fixture
        self.storage = self.normal.storage

    async def running(self):
        await self.normal.running()
        self.sid = self.normal.sid

    async def asyncTearDown(self):
        for node in self.fixture.nodes.values():
            if node.local_storage_manager is not None:
                node.local_storage_manager.cleanup()

    async def kill(self, authorized=True):
        return await self.fixture.controller.kill_session(
            communication=self.fixture.communication, result_window_s=1,
            operator_authorized=authorized, reason="operator abort")

    def baseline(self):
        return self.storage.get_persisted_session_preservation_confirmation(self.sid)

    async def test_explicit_kill_preserves_partial_archive_without_collection_or_release(self):
        await self.running()
        self.assertFalse((await self.kill(False)).succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "running")
        with patch.object(self.storage, "collect_saved_artifacts", side_effect=AssertionError("collection")), \
                patch.object(self.storage, "close_session_evidence_archive", side_effect=AssertionError("closure")):
            result = await self.kill()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["session_state"], "aborted")
        self.assertFalse(result.details["stage_a_complete"])
        self.assertFalse(result.details["archive_closed"])
        saved = self.baseline()
        self.assertIsNotNone(saved)
        self.assertTrue(saved["session_record"]["cleanup_evidence"]["cleanup_occurred"])
        self.assertEqual(saved["session_record"]["final_session_status"]["state"], "aborted")
        self.assertFalse(saved["compilation_summary"]["kill_preservation"]["complete_receipt_confirmed"])
        node = self.fixture.nodes["node-a"]
        self.assertEqual(node.reserved_for_session_id, self.sid)
        restored = PersistentStorageManager(self.fixture.root / "accepted_records.jsonl")
        self.assertEqual(restored.get_persisted_session_preservation_confirmation(self.sid), saved)
        before = self.normal.products()
        self.assertTrue((await self.kill()).succeeded)
        self.assertEqual(self.normal.products(), before)
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)
        self.assertTrue((await self.fixture.controller.release_session()).succeeded)

    async def test_active_experiment_aborts_without_reopening_scientific_files(self):
        f = self.fixture
        await f.services()
        node, declaration, _ = await f.node()
        f.controller = Controller(node, ingestor=f.ingestor, storage_manager=self.storage,
                                  synchronization_manager=f.sync)
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded)
        self.sid = launched.details["session_id"]
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        self.assertTrue(f.controller.start_experiment("experiment", scientific_outputs=(
            ScientificOutputSelection(declaration.device_id, "node-a", "events"),)).succeeded)
        result = await self.kill()
        self.assertTrue(result.succeeded, result.error)
        events = self.baseline()["session_record"]["experiment_lifecycle_evidence"]
        self.assertEqual([e["event_type"] for e in events], ["experiment_start", "experiment_abort"])
        self.assertIsNone(node.status()["active_experiment_runtime_context"])

    async def test_cleanup_failure_does_not_prevent_abort_or_falsely_release_reservation(self):
        await self.running()
        node = self.fixture.nodes["node-a"]
        with patch.object(node, "stop_runtime", side_effect=OSError("hardware unavailable")):
            result = await self.kill()
        self.assertTrue(result.succeeded, result.error)
        self.assertFalse(result.details["participant_cleanup_confirmed"])
        self.assertEqual(node.reserved_for_session_id, self.sid)
        self.assertFalse(node.release_reservation(self.sid))
        self.assertTrue(any(item.get("cleanup_confirmed") is False
            for item in self.baseline()["compilation_summary"]["kill_preservation"]["uncertainties"]))
        self.assertTrue(self.baseline()["artifact_collection_handoff"]["artifacts"][0]["missing_finalization_evidence"])

    async def test_cancelled_kill_retains_abort_binding_partial_evidence_and_command_identity(self):
        await self.running()
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.fixture.communication.request_command
        identities = []
        async def pause(*args, **kwargs):
            identities.append(kwargs.get("command_id"))
            entered.set()
            await resume.wait()
            return await original(*args, **kwargs)
        with patch.object(self.fixture.communication, "request_command", side_effect=pause):
            task = asyncio.create_task(self.kill())
            await asyncio.wait_for(entered.wait(), 2)
            self.assertFalse((await self.kill()).succeeded)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "aborted")
        self.assertEqual(self.fixture.ingestor.session_id, self.sid)
        self.assertIsNotNone(self.baseline())
        self.assertFalse(self.fixture.controller.finalize_session().succeeded)

    async def test_failed_persistence_preserves_journal_and_refuses_unsafe_retry(self):
        await self.running()
        journal = self.fixture.ingestor.recovery_journal_path
        with patch("lab_sync_acquisition.storage._write_jsonl", side_effect=OSError("disk unavailable")):
            result = await self.kill()
        self.assertFalse(result.succeeded)
        self.assertTrue(journal.exists())
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "aborted")
        self.assertIsNone(self.baseline())
        self.assertFalse((await self.kill()).succeeded)

    async def test_handoff_publication_failure_retries_without_repeating_cleanup_or_archive(self):
        await self.running()
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("handoff unavailable")):
            self.assertFalse((await self.kill()).succeeded)
        directory = self.fixture.root / f"session_{self.sid}"
        before = {path: path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        with patch.object(self.fixture.nodes["node-a"], "stop_runtime", side_effect=AssertionError("repeated cleanup")), \
                patch.object(self.storage, "write_evidence_archive", side_effect=AssertionError("archive rewrite")):
            self.assertTrue((await self.kill()).succeeded)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    async def test_failed_kill_handoff_blocks_ingestor_release_until_matching_durable_retry(self):
        await self.running()
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("handoff unavailable")):
            self.assertFalse((await self.kill()).succeeded)
        intake = self.fixture.ingestor
        retained = intake.accepted_runtime_evidence
        audit = intake.runtime_evidence_audit
        journal_path = intake.recovery_journal_path
        journal = journal_path.read_bytes()
        historical = self.normal.products()
        with self.assertRaisesRegex(RuntimeError, "handoff"):
            intake.release_session(self.sid, storage_manager=self.storage)
        self.assertEqual(intake.session_id, self.sid)
        self.assertEqual(intake.accepted_runtime_evidence, retained)
        self.assertEqual(intake.runtime_evidence_audit, audit)
        self.assertEqual(journal_path.read_bytes(), journal)
        self.assertEqual(self.normal.products(), historical)
        self.assertTrue((await self.kill()).succeeded)
        self.assertTrue((await self.fixture.controller.release_session()).succeeded)
        self.assertTrue(intake.release_session(self.sid, storage_manager=self.storage))
        self.assertIsNone(intake.session_id)
        self.assertEqual(journal_path.read_bytes(), journal)

    async def test_late_accepted_acquisition_blocks_kill_reconfirmation_and_release(self):
        await self._exercise_late_kill_acquisition_intake(accepted=True)

    async def test_partial_kill_with_empty_runtime_intake_still_requires_its_handoff(self):
        self.sid = self.normal.sid = await self.normal.producer.running(two=False, artifacts=False)
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("handoff unavailable")):
            self.assertFalse((await self.kill()).succeeded)
        intake = self.fixture.ingestor
        self.assertFalse(intake.accepted_runtime_evidence)
        self.assertFalse(intake.runtime_evidence_audit)
        with self.assertRaisesRegex(RuntimeError, "handoff"):
            intake.release_session(self.sid, storage_manager=self.storage)
        self.assertEqual(intake.session_id, self.sid)
        self.assertTrue((await self.kill()).succeeded)
        self.assertTrue(intake.release_session(self.sid, storage_manager=self.storage))

    async def test_late_rejected_acquisition_audit_blocks_kill_reconfirmation_and_release(self):
        await self._exercise_late_kill_acquisition_intake(accepted=False)

    async def _exercise_late_kill_acquisition_intake(self, *, accepted):
        intake = InMemoryIngestor(self.storage, recovery_journal_root=self.fixture.root / "late-journals")
        self.fixture.ingestor = intake
        self.fixture.controller = Controller(ingestor=intake, storage_manager=self.storage,
                                             synchronization_manager=self.fixture.sync)
        await self.running()
        self.assertTrue((await self.kill()).succeeded)
        historical = self.normal.products()
        envelope = AcquisitionRecordEnvelope(self.sid, "node-a-device", "event",
            ({"session_time_s": 0.0, "event_type": "late-after-kill"},) if accepted else
            ({"event_type": "missing-session-time"},), source_node_id="node-a")
        audit = intake.receive_envelope(envelope)
        self.assertIs(audit.accepted, accepted)
        retained = (intake.accepted_envelopes, intake.ingest_audit, intake.accepted_runtime_evidence,
                    intake.runtime_evidence_audit, intake.recovery_journal_path.read_bytes())
        with patch.object(self.storage, "write_final_session_record", side_effect=AssertionError("historical rewrite")):
            retry = await self.kill()
            self.assertFalse(retry.succeeded)
            self.assertFalse(retry.details["preservation_confirmed"])
            self.assertIn("acquisition-envelope and audit preservation", retry.error)
            self.assertFalse((await self.fixture.controller.release_session()).succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "aborted")
        self.assertEqual(intake.session_id, self.sid)
        self.assertEqual(self.normal.products(), historical)
        self.assertEqual((intake.accepted_envelopes, intake.ingest_audit, intake.accepted_runtime_evidence,
            intake.runtime_evidence_audit, intake.recovery_journal_path.read_bytes()), retained)

    async def test_kill_retry_after_permanent_closure_reports_current_state_without_mutation(self):
        await self.running()
        self.assertTrue((await self.kill()).succeeded)
        self.assertTrue(self.storage.close_session_evidence_archive(self.sid)["archive_closed"])
        historical = self.normal.products()
        with patch.object(self.storage, "write_kill_acquisition_stage", side_effect=AssertionError("archive rewrite")), \
                patch.object(self.storage, "write_artifact_collection_handoff", side_effect=AssertionError("handoff rewrite")):
            retry = await self.kill()
        self.assertTrue(retry.succeeded, retry.error)
        self.assertTrue(retry.details["archive_closed"])
        self.assertTrue(retry.details["preservation_confirmed"])
        self.assertEqual(self.normal.products(), historical)
        restored = PersistentStorageManager(self.fixture.root / "accepted_records.jsonl")
        self.assertTrue(restored.get_persisted_session_preservation_confirmation(self.sid)
                        ["compilation_summary"]["archive_closed"])

    async def test_acquisition_during_kill_release_unsubscription_keeps_binding_and_record(self):
        intake = InMemoryIngestor(self.storage, recovery_journal_root=self.fixture.root / "release-journals")
        self.fixture.ingestor = intake
        self.fixture.controller = Controller(ingestor=intake, storage_manager=self.storage,
                                             synchronization_manager=self.fixture.sync)
        await self.running()
        self.assertTrue((await self.kill()).succeeded)
        historical = self.normal.products()
        subscription = self.fixture.controller._launch_subscriptions[0]
        original = subscription.unsubscribe
        received = []
        envelope = AcquisitionRecordEnvelope(self.sid, "node-a-device", "event",
            ({"session_time_s": 0.0, "event_type": "during-unsubscribe"},), source_node_id="node-a")
        async def late_intake():
            audit = await asyncio.wait_for(asyncio.to_thread(intake.receive_envelope, envelope), 3)
            received.append(audit.accepted)
            await original()
        with patch.object(subscription, "unsubscribe", side_effect=late_intake):
            result = await self.fixture.controller.release_session()
        self.assertEqual(received, [True])
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_state"], "aborted")
        self.assertEqual(intake.session_id, self.sid)
        self.assertIn(envelope, intake.accepted_envelopes)
        self.assertEqual(self.normal.products(), historical)

    async def test_multiple_nodes_preserve_independent_cleanup_results(self):
        await self.normal.running(two=True)
        self.sid = self.normal.sid
        with patch.object(self.fixture.nodes["node-b"], "stop_runtime", side_effect=OSError("node-b unavailable")):
            result = await self.kill()
        self.assertTrue(result.succeeded, result.error)
        outcomes = {item["participant"]["component_id"]: item["cleanup_confirmed"]
                    for item in result.details["participants"]}
        self.assertTrue(outcomes["node-a"])
        self.assertFalse(outcomes["node-b"])
        handoff = result.details["artifact_collection_handoff"]["artifacts"]
        manifests = {item["artifact_manifest"]["acquisition_node_id"]: item for item in handoff}
        self.assertFalse(manifests["node-a"]["missing_finalization_evidence"])
        self.assertTrue(manifests["node-b"]["missing_finalization_evidence"])
        self.assertEqual(self.fixture.nodes["node-b"].reserved_for_session_id, self.sid)

    async def test_partial_archive_allows_later_failed_collection_and_freezes_handoff(self):
        await self.running()
        self.assertTrue((await self.kill()).succeeded)
        historical = self.normal.products()
        # No endpoint is configured: failure is a legitimate durable outcome.
        result = self.storage.collect_saved_artifacts(self.sid, evidence_id="later-collection")
        self.assertTrue(result["archival_confirmed"], result["preservation_warning"])
        self.assertFalse(result["artifact_collection_result"]["succeeded"])
        for path, contents in historical.items():
            if path.name == "runtime_evidence.jsonl":
                self.assertTrue(path.read_bytes().startswith(contents))
            elif path.name != "compilation_summary.json":
                self.assertEqual(path.read_bytes(), contents)
        self.assertTrue(self.baseline()["compilation_summary"]["collection_started"])
        with self.assertRaises(RuntimeError):
            self.storage.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.fixture.ingestor)
        again = self.storage.collect_saved_artifacts(self.sid, evidence_id="later-collection")
        self.assertEqual(again, result)


class PartialHandoffRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recovery = recovery.AuthorizedRecoveryTests()
        self.recovery.setUp()
        self.addCleanup(self.recovery.doCleanups)
        self.storage, self.intake = self.recovery.storage, self.recovery.ingestor
        self.sid = "session-a"
        self.node, _, self.interface = self.recovery.prepared_node()
        self.obligation = self.recovery.interrupted_local_artifact(self.node)
        self.storage.write_kill_acquisition_stage(self.sid, self.intake.compile_persistent_runtime_evidence(),
            uncertainties=[{"reason": "finalization unavailable"}],
            **records.PersistentStorageManagerTests._minimal_session_record_evidence(self.sid))
        self.storage.write_artifact_collection_handoff(self.sid, self.intake.compile_artifact_collection_handoff(self.sid))

    async def asyncTearDown(self):
        self.node.local_storage_manager.cleanup()

    def baseline(self, storage=None):
        return (storage or self.storage).get_persisted_session_preservation_confirmation(self.sid)

    async def recover_manifest(self):
        command = await self.recovery.authorize("preserve_scientific_artifact", self.obligation,
            interface=self.interface)
        result = await self.interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        return result.payload["confirmation"]["artifact_manifest"]

    async def test_authorized_manifest_refresh_preserves_history_and_supports_restart_collection(self):
        files = self.recovery.root / f"session_{self.sid}"
        record = (files / "session_record_final.json").read_bytes()
        evidence = (files / "evidence/runtime_evidence.jsonl").read_bytes()
        audit = (files / "evidence/ingest_audit.jsonl").read_bytes()
        manifest = await self.recover_manifest()
        artifact = Path(manifest["local_storage_path"]).read_bytes()
        refreshed = self.storage.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
        self.assertFalse(refreshed["artifacts"][0]["missing_finalization_evidence"])
        self.assertEqual(refreshed["artifacts"][0]["artifact_manifest"], manifest)
        self.assertTrue((files / "evidence/runtime_evidence.jsonl").read_bytes().startswith(evidence))
        self.assertTrue((files / "evidence/ingest_audit.jsonl").read_bytes().startswith(audit))
        self.assertEqual((files / "session_record_final.json").read_bytes(), record)
        self.assertFalse(self.baseline()["compilation_summary"]["stage_a_complete"])
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("redundant rewrite")):
            self.assertEqual(self.storage.refresh_partial_artifact_collection_handoff(self.sid,
                ingestor=self.intake), refreshed)
        restored = PersistentStorageManager(self.recovery.root / "records.jsonl",
            global_artifact_root=self.recovery.root / "global",
            retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "user")})
        self.assertEqual(restored.read_artifact_collection_handoff(self.sid), refreshed)
        # Use the existing narrow SFTP fake only; the restarted owner performs collection.
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(
            retrieval.SftpDouble({manifest["local_storage_path"]: artifact}))
        with transport:
            result = restored.collect_saved_artifacts(self.sid, evidence_id="recovered-collection")
        self.assertTrue(result["archival_confirmed"], result["preservation_warning"])
        self.assertEqual(result["artifact_collection_result"]["artifact_results"][0]["outcome"], "success")
        self.assertEqual(Path(manifest["local_storage_path"]).read_bytes(), artifact)
        with self.assertRaises(RuntimeError):
            restored.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)

    async def test_unapproved_manifest_change_is_refused_without_archive_mutation(self):
        self.node.finalize_experiment_scientific_outputs("experiment")
        before = {p: p.read_bytes() for p in self.recovery.root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(RuntimeError, "authorized recovery"):
            self.storage.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    async def test_interrupted_refresh_requires_authorized_archive_repair_then_safe_retry(self):
        await self.recover_manifest()
        with patch.object(self.storage, "_publish_preservation_summary", side_effect=OSError("summary unavailable")):
            with self.assertRaises(OSError):
                self.storage.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
        self.assertIsNone(self.baseline())
        with self.assertRaises(RuntimeError):
            self.storage.collect_saved_artifacts(self.sid, evidence_id="not-authorized-refetch")
        restored = PersistentStorageManager(self.recovery.root / "records.jsonl")
        interface = ServiceMaintenanceInterface(restored, RuntimeParticipant("storage_manager", "storage"),
            ingestor=self.intake, storage_manager=restored, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        command = await self.recovery.authorize("recover_archive_write", {"session_id": self.sid},
            identity="repair-refresh", interface=interface)
        result = await interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        refreshed = restored.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
        self.assertFalse(refreshed["artifacts"][0]["missing_finalization_evidence"])
        self.assertIsNotNone(self.baseline(restored))

    async def test_started_but_interrupted_collection_freezes_partial_handoff_after_restart(self):
        with patch.object(self.storage, "_collect_artifacts", side_effect=KeyboardInterrupt("interrupted")):
            with self.assertRaises(KeyboardInterrupt):
                self.storage.collect_saved_artifacts(self.sid, evidence_id="interrupted-collection")
        restored = PersistentStorageManager(self.recovery.root / "records.jsonl")
        with self.assertRaises(RuntimeError):
            restored.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
        outcome = restored.collect_saved_artifacts(self.sid, evidence_id="interrupted-collection")
        self.assertEqual(outcome["artifact_collection_result"]["artifact_results"][0]["outcome"], "unknown")

    async def test_concurrent_restart_owner_cannot_refresh_or_close_during_collection(self):
        collector = PersistentStorageManager(self.recovery.root / "records.jsonl")
        peer = PersistentStorageManager(self.recovery.root / "records.jsonl")
        entered, resume = Event(), Event()
        original = collector._collect_artifacts
        def pause(*args):
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("Test did not release collection")
            return original(*args)
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(collector, "_collect_artifacts", side_effect=pause):
            future = pool.submit(collector.collect_saved_artifacts, self.sid, evidence_id="concurrent")
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises((OSError, RuntimeError)):
                    peer.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)
                with self.assertRaises((OSError, RuntimeError)):
                    peer.close_session_evidence_archive(self.sid)
            finally:
                resume.set()
            self.assertTrue(future.result(5)["archival_confirmed"])
        with self.assertRaises(RuntimeError):
            peer.refresh_partial_artifact_collection_handoff(self.sid, ingestor=self.intake)

    async def test_partial_final_record_is_immutable_and_normal_stage_a_still_requires_receipt(self):
        path = self.recovery.root / f"session_{self.sid}" / "session_record_final.json"
        before = path.read_bytes()
        with self.assertRaises(RuntimeError):
            self.storage.write_final_session_record(self.sid,
                **records.PersistentStorageManagerTests._minimal_session_record_evidence(self.sid))
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.storage.write_acquisition_stage(self.sid,
                self.intake.compile_persistent_runtime_evidence(), receipt=None,
                **records.PersistentStorageManagerTests._minimal_session_record_evidence(self.sid))


