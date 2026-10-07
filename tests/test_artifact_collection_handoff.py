import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    ArtifactManifest, InMemoryIngestor, NatsAcquisitionNodeCommunication,
    NatsCommunicationBoundary, NatsIngestorCommunication, RuntimeCommandMessage,
    RuntimeEvidenceMessage,
)
from tests import test_scientific_output_preparation as preparation_tests


class ArtifactCollectionHandoffTests(unittest.TestCase):
    def workflow(self, root):
        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        product = fixture.product("events", "jsonl", {"value": "number"})
        controller, node, _ = fixture.fixture(Path(root), products=(product,))
        fixture.start_session(controller, node)
        return fixture, controller, node

    def test_initial_and_final_manifest_evidence_preserves_authoritative_identity(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            self.assertTrue(controller.start_experiment(
                "first", scientific_outputs=(fixture.output("events"),)).succeeded)
            initial = node.artifact_manifest_evidence[0]
            self.assertEqual(initial.payload, node.local_storage_manager.manifests[0].to_dict())
            self.assertEqual(initial.evidence_type, "artifact_manifest")
            self.assertTrue(initial.is_persistent)
            self.assertTrue(controller.stop_experiment("first").succeeded)
            finalized = node.artifact_manifest_evidence[1]
            self.assertEqual(finalized.payload, node.local_storage_manager.manifests[0].to_dict())
            for field in ("session_id", "experiment_id", "artifact_manifest_id", "acquisition_node_id"):
                self.assertEqual(initial.payload[field], finalized.payload[field])
            self.assertEqual(initial.payload["lifecycle_state"], "open")
            self.assertEqual(finalized.payload["lifecycle_state"], "finalized")
            node.finalize_experiment_scientific_outputs("first")
            self.assertEqual(len(node.artifact_manifest_evidence), 2)
            self.assertTrue(controller.stop_session().succeeded)
            result = controller.finalize_session()
            self.assertTrue(result.succeeded, result.error)
            handoff = result.details["artifact_collection_handoff"]
            self.assertEqual(handoff, {"session_id": "session-001", "artifacts": [
                {"artifact_manifest": finalized.payload, "missing_finalization_evidence": False}]})
            archive = Path(result.details["evidence_archive_paths"]["runtime_evidence"])
            self.assertEqual([json.loads(line) for line in archive.read_text().splitlines()],
                             [initial.to_dict(), finalized.to_dict()])
            record = json.loads(Path(result.details["session_record_path"]).read_text())
            self.assertEqual([event["event_type"] for event in record["experiment_lifecycle_evidence"]],
                             ["experiment_start", "experiment_stop"])
            self.assertNotIn("artifact_collection_handoff", record)

    def test_handoff_groups_artifacts_experiments_and_sessions_preferring_finalized(self):
        ingestor = InMemoryIngestor()
        first = ArtifactManifest("one", "session", "experiment-a", "node", "camera",
                                 "frames", "open", "storage-one", "frames.h5", None,
                                 ("frames.h5", "metadata.json"), {"shape": [2, 3]})
        second = replace(first, artifact_manifest_id="two", experiment_id="experiment-b")
        finalized = replace(first, lifecycle_state="finalized", details={"row_count": 3})
        other = replace(first, session_id="other", artifact_manifest_id="other-artifact")
        for index, manifest in enumerate((first, second, finalized, first, finalized, other)):
            ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                str(index), manifest.session_id, "artifact_manifest", "node", manifest.to_dict(), True))
        ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
            "unrelated", "session", "other_evidence", "node", {}, True))
        self.assertEqual(ingestor.compile_artifact_collection_handoff("session"), {
            "session_id": "session", "artifacts": [
                {"artifact_manifest": finalized.to_dict(), "missing_finalization_evidence": False},
                {"artifact_manifest": second.to_dict(), "missing_finalization_evidence": True}]})
        self.assertEqual(len(ingestor.compile_artifact_collection_handoff("other")["artifacts"]), 1)
        self.assertEqual(ingestor.compile_artifact_collection_handoff("empty")["artifacts"], [])
        self.assertEqual(len(ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]), 7)

    def test_initial_only_handoff_preserves_complete_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            self.assertTrue(controller.start_experiment(
                "first", scientific_outputs=(fixture.output("events"),)).succeeded)
            ingestor = InMemoryIngestor()
            ingestor.receive_runtime_evidence(node.artifact_manifest_evidence[0])
            entry = ingestor.compile_artifact_collection_handoff("session-001")["artifacts"][0]
            self.assertTrue(entry["missing_finalization_evidence"])
            self.assertEqual(entry["artifact_manifest"], node.local_storage_manager.manifests[0].to_dict())
            self.assertTrue(controller.stop_session().succeeded)

    def test_remote_preparation_and_stop_publish_manifests_through_jetstream(self):
        async def run(fixture, node):
            subscriptions = {}
            published = []

            async def subscribe(subject, cb, **kwargs):
                subscriptions[subject] = cb
                return subject

            async def publish(subject, data, stream):
                published.append((subject, json.loads(data), stream))
                for filter_subject, callback in tuple(subscriptions.items()):
                    if (".evidence." in subject and ".evidence." in filter_subject
                            or ".command." in subject and ".command." in filter_subject):
                        await callback(SimpleNamespace(data=data, ack=AsyncMock()))
                return SimpleNamespace(stream=stream)

            jetstream = SimpleNamespace(subscribe=subscribe, publish=publish)
            client = SimpleNamespace(jetstream=lambda: jetstream, is_connected=True)
            boundary = NatsCommunicationBoundary("acquisition_node", "node-001")
            sender = NatsCommunicationBoundary("controller", "controller")
            receiver_boundary = NatsCommunicationBoundary("ingestor", "receiver")
            receiver = InMemoryIngestor(session_id="session-001", recovery_journal_path=Path(root) / "receiver-recovery.jsonl")
            with patch("lab_sync_acquisition.nats_communication.nats.connect", AsyncMock(return_value=client)):
                for connection in (boundary, sender, receiver_boundary):
                    await connection.connect()
                await NatsIngestorCommunication(receiver_boundary, receiver).subscribe_evidence("session-001")
                communication = NatsAcquisitionNodeCommunication(boundary, node)
                await communication.subscribe_commands()
                await sender.publish_command(RuntimeCommandMessage(
                    "prepare", "session-001", "prepare_experiment_scientific_outputs", "controller", "node-001",
                    {"experiment_id": "remote", "scientific_outputs": [fixture.output("events").to_dict()]}),
                    "acquisition_node")
                await sender.publish_command(RuntimeCommandMessage(
                    "stop", "session-001", "stop_runtime", "controller", "node-001", {}), "acquisition_node")
                await communication.publish_new_artifact_manifest_evidence()
            messages = receiver.accepted_runtime_evidence
            self.assertEqual(len(messages), 2)
            self.assertEqual([message.payload["lifecycle_state"] for message in messages], ["open", "finalized"])
            self.assertEqual(messages[1].payload, node.local_storage_manager.manifests[0].to_dict())
            self.assertEqual([stream for subject, _, stream in published if ".evidence." in subject],
                             ["LAB_EVIDENCE", "LAB_EVIDENCE"])
            self.assertFalse(receiver.compile_artifact_collection_handoff("session-001")["artifacts"][0]
                             ["missing_finalization_evidence"])

        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            asyncio.run(run(fixture, node))
            self.assertTrue(controller.stop_session().succeeded)


if __name__ == "__main__":
    unittest.main()
