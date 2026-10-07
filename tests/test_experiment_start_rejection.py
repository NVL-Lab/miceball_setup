import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    RuntimeCommandMessage, RuntimeCommandResultMessage, RuntimeEvidenceMessage,
    RuntimeParticipant, ServiceReadiness, aggregate_group_command_results,
    NatsAcquisitionNodeCommunication, NatsCommunicationBoundary, NatsIngestorCommunication,
    InMemoryIngestor, InMemoryStorageManager,
)
from tests import test_scientific_output_preparation as preparation_tests


class ExperimentStartRejectionTests(unittest.TestCase):
    def workflow(self, root):
        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        controller, node, _ = fixture.fixture(Path(root))
        fixture.start_session(controller, node)
        return fixture, controller, node

    def finalize(self, controller, node):
        context = node.status()["active_experiment_runtime_context"]
        if context is not None:
            self.assertTrue(controller.stop_experiment(context.experiment_id).succeeded)
        self.assertTrue(controller.stop_session().succeeded)
        result = controller.finalize_session()
        self.assertTrue(result.succeeded, result.error)
        node.local_storage_manager.cleanup()
        return result

    def test_required_preparation_success_records_one_canonical_start(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            result = controller.start_experiment("experiment", scientific_outputs=(fixture.output(),))
            self.assertTrue(result.succeeded, result.error)
            paths = self.finalize(controller, node).details
            record = json.loads(Path(paths["session_record_path"]).read_text())
            self.assertEqual(sum(item["event_type"] == "experiment_start"
                                 for item in record["experiment_lifecycle_evidence"]), 1)

    def test_storage_failure_rejection_is_persistent_once_and_reaches_archive(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            with patch.object(node.local_storage_manager, "create_stream", side_effect=OSError("disk unavailable")):
                result = controller.start_experiment("experiment", scientific_outputs=(fixture.output(),))
            self.assertFalse(result.succeeded)
            message = RuntimeEvidenceMessage.from_dict(result.details["rejection_evidence"])
            self.assertTrue(message.is_persistent)
            self.assertEqual(message.evidence_type, "experiment_start_rejected")
            self.assertEqual(message.payload["experiment_id"], "experiment")
            self.assertIn("disk unavailable", message.payload["preparations"][0]["reason"])
            self.assertIsInstance(message.payload["session_time_s"], float)
            self.assertNotIn("experiment_time_s", message.payload)
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertEqual(controller.get_status()["session_state"], "running")
            paths = self.finalize(controller, node).details
            evidence = [json.loads(line) for line in Path(paths["evidence_archive_paths"]["runtime_evidence"]).read_text().splitlines()]
            self.assertEqual([item for item in evidence if item["evidence_type"] == "experiment_start_rejected"], [message.to_dict()])
            record = json.loads(Path(paths["session_record_path"]).read_text())
            self.assertEqual(record["experiment_lifecycle_evidence"], [])

    def test_optional_service_failure_is_preserved_without_blocking_required_preparation(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            checks = (ServiceReadiness("optional", "preparation", False, False, "unavailable"),
                      ServiceReadiness("required", "preparation", True, True, "ready"))
            result = controller.start_experiment("experiment", scientific_outputs=(fixture.output(),),
                                                 preparation_readiness=checks)
            self.assertTrue(result.succeeded, result.error)
            paths = self.finalize(controller, node).details
            record = json.loads(Path(paths["session_record_path"]).read_text())
            self.assertIn("unavailable", json.dumps(record))

    def test_required_service_failure_blocks_start(self):
        with tempfile.TemporaryDirectory() as root:
            _, controller, node = self.workflow(root)
            result = controller.start_experiment("experiment", preparation_readiness=(
                ServiceReadiness("required", "preparation", True, False, "device unavailable"),))
            self.assertFalse(result.succeeded)
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertIn("device unavailable", json.dumps(result.details))
            self.finalize(controller, node)

    def remote_outcome(self, results=()):
        return aggregate_group_command_results(
            command_id="prepare-1", session_id="session-001",
            command_type="prepare_experiment_scientific_outputs", component_type="acquisition_node",
            expected_participants=(RuntimeParticipant("acquisition_node", "remote-node"),),
            command_results=results, unresolved_reason="missing required response")

    def test_missing_required_remote_result_stays_unresolved_and_blocks_start(self):
        with tempfile.TemporaryDirectory() as root:
            _, controller, node = self.workflow(root)
            outcome = self.remote_outcome()
            result = controller.start_experiment("experiment", preparation_outcomes=(outcome,))
            self.assertFalse(result.succeeded)
            recorded = result.details["rejection_evidence"]["payload"]["command_outcomes"][0]
            self.assertEqual(recorded["outcome"], "unresolved")
            self.assertEqual(recorded["command_results"], [])
            self.assertEqual(recorded["unresolved_outcomes"][0]["command_id"], "prepare-1")
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.finalize(controller, node)

    def test_only_correlated_final_remote_success_allows_start(self):
        for status, experiment, expected in (("progress", "experiment", False),
                                              ("accepted", "experiment", False),
                                              ("succeeded", "other", False),
                                              ("succeeded", "experiment", True)):
            with self.subTest(status=status, experiment=experiment), tempfile.TemporaryDirectory() as root:
                _, controller, node = self.workflow(root)
                response = RuntimeCommandResultMessage("result", "prepare-1", "session-001", "remote-node",
                    "controller", status, True, None, {"experiment_id": experiment,
                    "preparation": ServiceReadiness("remote-node", "scientific_output_preparation", True, True, "ready").to_dict()})
                result = controller.start_experiment("experiment", preparation_outcomes=(self.remote_outcome((response,)),))
                self.assertEqual(result.succeeded, expected, result.error)
                self.finalize(controller, node)

    def test_remote_dispatch_prepares_without_starting_experiment_and_keeps_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, controller, node = self.workflow(root)
            receiver = NatsAcquisitionNodeCommunication(NatsCommunicationBoundary("acquisition_node", "node-001"), node)
            command = RuntimeCommandMessage("prepare-1", "session-001", "prepare_experiment_scientific_outputs",
                "controller", "node-001", {"experiment_id": "experiment", "scientific_outputs": [fixture.output().to_dict()]})
            result = receiver.execute_command(command)
            self.assertTrue(result.success, result.reason)
            self.assertTrue(result.payload["preparation"]["required"])
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertEqual(receiver.execute_command(command), result)
            self.assertEqual(len(node.local_storage_manager.manifests), 1)
            failed = receiver.execute_command(RuntimeCommandMessage("prepare-2", "session-001",
                "prepare_experiment_scientific_outputs", "controller", "node-001",
                {"experiment_id": "other", "scientific_outputs": [fixture.output("unknown").to_dict()]}))
            self.assertFalse(failed.success)
            self.assertIn("Unknown scientific product", failed.payload["preparation"]["reason"])
            self.finalize(controller, node)

    def test_metadata_only_overlap_and_terminal_identity_rules_remain_intact(self):
        with tempfile.TemporaryDirectory() as root:
            _, controller, node = self.workflow(root)
            self.assertTrue(controller.start_experiment("first").succeeded)
            self.assertFalse(controller.start_experiment("overlap").succeeded)
            self.assertTrue(controller.stop_experiment("first").succeeded)
            self.assertFalse(controller.start_experiment("first").succeeded)
            self.assertTrue(controller.start_experiment("second").succeeded)
            self.finalize(controller, node)

    def test_rejection_message_uses_existing_jetstream_evidence_intake(self):
        async def transfer(message):
            callbacks = []

            async def subscribe(subject, cb, **options):
                callbacks.append(cb)
                return subject

            async def publish(subject, data, stream):
                self.assertEqual(stream, "LAB_EVIDENCE")
                self.assertEqual(subject, "messages.session-001.evidence.controller.controller.experiment_start_rejected")
                for callback in callbacks:
                    await callback(SimpleNamespace(data=data, ack=AsyncMock()))
                return SimpleNamespace(stream=stream)

            jetstream = SimpleNamespace(subscribe=subscribe, publish=publish)
            client = SimpleNamespace(jetstream=lambda: jetstream, is_connected=True)
            publisher = NatsCommunicationBoundary("controller", "controller")
            consumer_boundary = NatsCommunicationBoundary("ingestor", "ingestor")
            ingestor = InMemoryIngestor(InMemoryStorageManager(), session_id=message.session_id,
                                       recovery_journal_path=Path(root) / "rejection-recovery.jsonl")
            with patch("lab_sync_acquisition.nats_communication.nats.connect", AsyncMock(return_value=client)):
                await publisher.connect()
                await consumer_boundary.connect()
                await NatsIngestorCommunication(consumer_boundary, ingestor).subscribe_evidence(message.session_id)
                await publisher.publish_evidence(message)
            self.assertEqual(ingestor.accepted_runtime_evidence, (message,))
            self.assertEqual(ingestor.compile_persistent_runtime_evidence()["runtime_evidence"], (message,))

        with tempfile.TemporaryDirectory() as root:
            _, controller, node = self.workflow(root)
            result = controller.start_experiment("experiment", preparation_readiness=(
                ServiceReadiness("required", "preparation", True, False, "not ready"),))
            asyncio.run(transfer(RuntimeEvidenceMessage.from_dict(result.details["rejection_evidence"])))
            self.finalize(controller, node)


if __name__ == "__main__":
    unittest.main()
