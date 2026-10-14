"""Session preservation remains usable through restart, collection, recovery, and closure."""

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, NatsControllerCommunication, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeParticipant, ScientificOutputSelection,
    ServiceMaintenanceInterface, SshRetrievalEndpoint,
)
from tests import test_session_launch as launch
from tests import test_normal_stop as normal
from tests import test_producer_publication_completion as producers
from tests import test_artifact_retrieval as retrieval


class _ScientificEventAdapter(launch._CollectingAdapter):
    def collect_scientific_records(self):
        return {"runtime_records": self.collect_records(),
                "scientific_records": {"record_kind": "event",
                    "records": [{"data_product_id": "events", "value": 1}]}}


class SessionPreservationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = launch.SessionLaunchTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.fixture.broker = producers.PublicationBroker()
        self.fixture.communication = NatsControllerCommunication(
            launch._Boundary("controller", "controller", self.fixture.broker))
        self.records = self.fixture.root / "accepted_records.jsonl"
        self.storage = self.restored_storage()
        self.stop = normal.NormalStopTests()
        self.stop.fixture = self.fixture
        self.stop.storage = self.storage

    async def asyncTearDown(self):
        if self.fixture.controller.get_status()["session_state"] == "running":
            await self.fixture.controller.stop_launched_session()
        for node in self.fixture.nodes.values():
            if node.local_storage_manager is not None:
                node.local_storage_manager.cleanup()

    def restored_storage(self):
        return PersistentStorageManager(self.records,
            global_artifact_root=self.fixture.root / "global",
            retrieval_endpoints={"node-a": SshRetrievalEndpoint("fake", "reader")})

    async def start(self, *, scientific=True, reuse=False):
        f = self.fixture
        if not reuse:
            await f.services()
            with patch.object(launch, "_CollectingAdapter", _ScientificEventAdapter):
                node, self.declaration, _ = await f.node()
            f.controller = Controller(node, ingestor=f.ingestor, storage_manager=self.storage,
                                      synchronization_manager=f.sync)
        launched = await f.launch({"node-a": [self.declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        self.stop.sid = sid
        self.stop.connect_receipt()
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        outputs = (ScientificOutputSelection(self.declaration.device_id, "node-a", "events"),) if scientific else ()
        started = f.controller.start_experiment("experiment", scientific_outputs=outputs)
        self.assertTrue(started.succeeded, started.error)
        if scientific:
            iteration = await f.communication.request_command(RuntimeParticipant("acquisition_node", "node-a"),
                "run_one_iteration", sid, {}, 1)
            self.assertTrue(iteration.success, iteration.reason)
        return sid

    async def complete_normal_stop(self):
        sid = await self.start()
        result = await self.stop.stop()
        self.assertTrue(result.succeeded, result.error)
        summary = self.storage.get_acquisition_stage_preservation_confirmation(sid)["compilation_summary"]
        self.assertTrue(summary["stage_a_complete"])
        self.assertFalse(summary["archive_closed"])
        marker = next(message for message in self.fixture.ingestor.accepted_runtime_evidence
                      if message.evidence_type == "acquisition_evidence_completion")
        self.assertTrue(self.fixture.ingestor.has_durable_runtime_evidence(marker))
        self.assertEqual(summary["acquisition_evidence_completion"]["evidence_id"], marker.evidence_id)
        self.assertGreater(summary["acquisition_evidence_completion"]["marker_stream_sequence"], 0)
        finalized = [message for message in self.fixture.ingestor.accepted_runtime_evidence
                     if message.evidence_type == "artifact_manifest" and message.payload["lifecycle_state"] == "finalized"]
        self.assertTrue(finalized)
        self.assertTrue(all(self.fixture.ingestor.has_durable_runtime_evidence(message) for message in finalized))
        self.assertTrue(self.fixture.sync.release_session(sid, ingestor=self.fixture.ingestor))
        released = await self.fixture.controller.release_session()
        self.assertTrue(released.succeeded, released.error)
        self.assertTrue(self.fixture.ingestor.release_session(sid, storage_manager=self.storage))
        return sid

    def products(self, sid):
        directory = self.fixture.root / f"session_{sid}"
        return {name: (directory / name).read_bytes() for name in (
            "evidence/runtime_evidence.jsonl", "evidence/ingest_audit.jsonl",
            "session_record_final.json", "artifact_collection_handoff.json")}

    def scientific_files(self, sid):
        handoff = self.storage.read_artifact_collection_handoff(sid)
        return {entry["artifact_manifest"]["local_storage_path"]:
                Path(entry["artifact_manifest"]["local_storage_path"]).read_bytes()
                for entry in handoff["artifacts"]}

    async def test_normal_stop_and_kill_preservation_support_saved_collection(self):
        completed = await self.complete_normal_stop()
        original = self.products(completed)
        files = self.scientific_files(completed)
        self.assertTrue(files)
        self.assertTrue(all(contents for contents in files.values()))
        aborted = await self.start(scientific=False, reuse=True)
        killed = await self.fixture.controller.kill_session(communication=self.fixture.communication,
            result_window_s=1, operator_authorized=True, reason="operator abort")
        self.assertTrue(killed.succeeded, killed.error)
        self.assertFalse(killed.details["stage_a_complete"])
        kill_record = self.storage.get_persisted_session_preservation_confirmation(aborted)["session_record"]
        self.assertEqual([e["event_type"] for e in kill_record["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_abort"])
        self.assertEqual(kill_record["final_session_status"]["state"], "aborted")
        self.assertEqual(self.fixture.nodes["node-a"].reserved_for_session_id, aborted)
        restored = self.restored_storage()
        listed = {item["session_id"]: item for item in restored.list_saved_sessions()}
        self.assertEqual(set(listed), {completed, aborted})
        self.assertTrue(all(item["eligible"] and item["collection_available"] for item in listed.values()))
        self.assertEqual(listed[completed]["lifecycle_state"], "completed")
        self.assertEqual(listed[aborted]["lifecycle_state"], "aborted")
        operator = Controller(storage_manager=restored)
        sftp = retrieval.SftpDouble(files)
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(sftp)
        with transport:
            single = operator.collect_saved_session_artifacts(completed, evidence_id="normal-collection")
            # Existing JSONL has no light-verification contract: copied_unverified is not full success.
            self.assertFalse(single.succeeded)
            self.assertTrue(single.details["archival_confirmed"])
            mixed = operator.collect_selected_session_artifacts({completed: "normal-collection", aborted: "kill-collection"})
        self.assertEqual(mixed.details["summary"], "partial_success")
        self.assertEqual([item["succeeded"] for item in mixed.details["session_results"]], [False, True])
        self.assertEqual(len(sftp.opened), len(files))
        current = self.products(completed)
        self.assertTrue(current["evidence/runtime_evidence.jsonl"].startswith(original["evidence/runtime_evidence.jsonl"]))
        for name in original.keys() - {"evidence/runtime_evidence.jsonl"}:
            self.assertEqual(current[name], original[name])
        for source, contents in files.items():
            self.assertEqual(Path(source).read_bytes(), contents)
        for sid in (completed, aborted):
            closed = restored.close_session_evidence_archive(sid)
            self.assertTrue(closed["archive_closed"])
            self.assertTrue(closed["archival_confirmed"])
        restarted = self.restored_storage()
        self.assertTrue(all(item["eligible"] and not item["collection_available"] for item in restarted.list_saved_sessions()))
        snapshot = {sid: self.products(sid) for sid in (completed, aborted)}
        blocked = Controller(storage_manager=restarted).collect_selected_session_artifacts(
            {completed: "normal-collection", aborted: "kill-collection"})
        self.assertEqual(blocked.details["summary"], "failure")
        self.assertEqual({sid: self.products(sid) for sid in snapshot}, snapshot)
        self.assertEqual(self.fixture.nodes["node-a"].reserved_for_session_id, aborted)

    async def test_authorized_recovery_preserves_collection_without_refetch(self):
        sid = await self.complete_normal_stop()
        original = self.products(sid)
        files = self.scientific_files(sid)
        sftp = retrieval.SftpDouble(files)
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(sftp)
        with transport, patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary interrupted")):
            interrupted = Controller(storage_manager=self.restored_storage()).collect_saved_session_artifacts(
                sid, evidence_id="stable-collection")
        self.assertFalse(interrupted.succeeded)
        self.assertTrue(interrupted.details["outcome_durable"])
        self.assertFalse(interrupted.details["archival_confirmed"])
        restored = self.restored_storage()
        status = restored.get_saved_session_collection_status(sid)
        self.assertTrue(status["eligible"])
        self.assertFalse(status["collection_available"])
        self.assertFalse(Controller(storage_manager=restored).collect_saved_session_artifacts(
            sid, evidence_id="stable-collection").succeeded)
        with self.assertRaises(RuntimeError):
            restored.close_session_evidence_archive(sid)
        intake = InMemoryIngestor(framework_recovery_journal_path=self.fixture.root / "framework-journal.jsonl")
        interface = ServiceMaintenanceInterface(restored, RuntimeParticipant("storage_manager", "storage"),
            ingestor=intake, storage_manager=restored, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        obligation = {"session_id": sid, "evidence_id": "stable-collection"}
        refused = await interface.execute_command(RuntimeCommandMessage("unauthorized", None,
            "recover_archive_write", "operator", "storage", {"obligation": obligation}))
        self.assertFalse(refused.success)
        decision = await interface.record_administrator_decision("administrator", "resume",
            {"operation": "recover_archive_write", "obligation": obligation, "command_id": "authorized"})
        recovered = await interface.execute_command(RuntimeCommandMessage("authorized", None,
            "recover_archive_write", "operator", "storage",
            {"authorization_evidence_id": decision["evidence"]["evidence_id"], "obligation": obligation}))
        self.assertTrue(recovered.success, recovered.reason)
        restarted = self.restored_storage()
        self.assertTrue(restarted.get_saved_session_collection_status(sid)["collection_available"])
        with patch.object(restarted, "_collect_artifacts", side_effect=AssertionError("unauthorized refetch")):
            repeated = Controller(storage_manager=restarted).collect_saved_session_artifacts(sid, evidence_id="stable-collection")
        self.assertTrue(repeated.details["archival_confirmed"])
        self.assertEqual(len(sftp.opened), len(files))
        current = self.products(sid)
        self.assertTrue(current["evidence/runtime_evidence.jsonl"].startswith(original["evidence/runtime_evidence.jsonl"]))
        for name in original.keys() - {"evidence/runtime_evidence.jsonl"}:
            self.assertEqual(current[name], original[name])
        self.assertTrue(restarted.close_session_evidence_archive(sid)["archive_closed"])
        self.assertFalse(self.restored_storage().get_saved_session_collection_status(sid)["collection_available"])


if __name__ == "__main__":
    unittest.main()
