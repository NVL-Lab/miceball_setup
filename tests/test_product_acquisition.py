"""Selected scientific products stay local; operational evidence uses the evidence plane."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    AcquisitionNode, ActiveExperimentRuntimeContext, DeviceDeclaration, DeviceManager,
    InMemoryIngestor, NatsAcquisitionNodeCommunication, NatsIngestorCommunication,
    RuntimeEvidenceMessage, ScientificOutputSelection, ScientificProductDeclaration,
    SynchronizationManager, NatsControllerCommunication, RuntimeParticipant,
    DurablePublicationError,
)
from lab_sync_acquisition.device_adapter import _PartialScientificCollectionError
from tests.fakes import ReadyFakeAdapter
from tests.test_session_launch import _Boundary, _Broker


class ProductAdapter(ReadyFakeAdapter):
    def __init__(self, *args, fail=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected = []
        self.fail = fail

    def collect_products(self, products, *, session_id, experiment_id, acquisition_node_id):
        self.selected.append(tuple(product.data_product_id for product in products))
        rows = {product.data_product_id: [{"observation_index": 0, "value": 7,
                "device_local_time": 12.5, "metadata": {"unit": "arbitrary"}}] for product in products}
        result = {"scientific_products": rows, "operational_evidence": ()}
        if self.fail and products:
            raise _PartialScientificCollectionError(OSError("later read failed"), result)
        return result


class ProductAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def node(self, *, selected=True, fail=False, session_id="session", ingestor=None, policies=()):
        products = (ScientificProductDeclaration("events", "event", {"value": "int"}, "jsonl"),
                    ScientificProductDeclaration("other", "event", {"value": "int"}, "jsonl"))
        declaration = DeviceDeclaration("device", "fake", True, True, ("event",), products)
        adapter = ProductAdapter("device", "fake", ("event",), True, fail=fail)
        adapter.initialize({})
        adapter.check_ready()
        sync = SynchronizationManager()
        node = AcquisitionNode(session_id, DeviceManager([adapter]), sync, ingestor,
            node_id="node", role="acquisition", error_evidence_location=str(self.root / "errors"),
            acquisition_health_policies=policies, device_declarations=(declaration,))
        manager = node.prepare_local_storage(session_id, (declaration,), self.root / session_id)
        self.assertTrue(manager.check_ready().ready)
        self.addCleanup(manager.cleanup)
        self.addCleanup(lambda: node.stop_runtime() if node.status()["is_running"] else None)
        outputs = (ScientificOutputSelection("device", "node", "events"),) if selected else ()
        self.assertTrue(node.prepare_experiment_scientific_outputs("experiment", outputs).ready)
        node.start_runtime()
        node.activate_experiment_runtime_context(ActiveExperimentRuntimeContext("experiment", 0.0))
        return node, adapter

    async def test_selected_observations_and_metadata_stay_local(self):
        intake = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "journal")
        node, adapter = self.node(ingestor=intake)
        result = node.run_one_iteration()
        self.assertEqual(result.scientific_observations, 1)
        self.assertEqual(adapter.selected, [("events",)])
        self.assertEqual(intake.accepted_envelopes, ())
        node.stop_runtime()
        manifest, = node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        row = json.loads(Path(manifest.local_storage_path).read_text())
        self.assertEqual(row["observation_index"], 0)
        self.assertEqual(row["metadata"], {"unit": "arbitrary"})
        self.assertEqual(row["device_local_time"], 12.5)
        self.assertEqual((row["session_id"], row["experiment_id"]), ("session", "experiment"))
        self.assertIn("session_time_s", row)
        self.assertIn("experiment_time_s", row)
        self.assertEqual([message.payload["event_type"] for message in node.runtime_evidence],
                         ["session_start", "session_stop"])

    async def test_no_selection_does_not_acquire_scientific_data(self):
        node, adapter = self.node(selected=False)
        self.assertEqual(node.run_one_iteration().scientific_observations, 0)
        self.assertEqual(adapter.selected, [()])
        node.stop_runtime()
        self.assertEqual(node.local_storage_manager.manifests, ())

    async def test_session_cannot_redeclare_installed_products(self):
        installed = DeviceDeclaration("device", "fake", True, True, ("event",), (
            ScientificProductDeclaration("events", "event", {}, "jsonl"),))
        substituted = DeviceDeclaration("device", "fake", True, True, ("event",), (
            ScientificProductDeclaration("uninstalled", "event", {}, "jsonl"),))
        node = AcquisitionNode("session", DeviceManager([ProductAdapter("device", "fake", (), True)]),
            SynchronizationManager(), node_id="node", device_declarations=(installed,))
        with self.assertRaisesRegex(ValueError, "installed device declarations"):
            node.prepare_local_storage("session", (substituted,), self.root / "local")
        self.assertIsNone(node.local_storage_manager)

    async def test_adapter_operational_evidence_retains_its_identity_and_snapshot(self):
        node, adapter = self.node()
        payload = {"event_type": "device_status", "device_id": "device", "ready": True}
        message = RuntimeEvidenceMessage("device-status", "session", "event", "node", payload, True)
        collect = adapter.collect_products

        def produce(products, **context):
            result = collect(products, **context)
            result["operational_evidence"] = (message,)
            return result

        with patch.object(adapter, "collect_products", side_effect=produce):
            self.assertEqual(node.run_one_iteration().scientific_observations, 1)
        payload["ready"] = False
        retained, = [item for item in node.runtime_evidence if item.evidence_id == "device-status"]
        self.assertTrue(retained.payload["ready"])
        self.assertEqual(retained.source_id, "node")
        self.assertNotIn("value", retained.payload)
        retained.payload["ready"] = False
        self.assertTrue(node.runtime_evidence[-1].payload["ready"])
        node.stop_runtime()

    async def test_partial_collection_preserves_completed_observation_and_failure(self):
        node, _ = self.node(fail=True)
        with self.assertRaisesRegex(RuntimeError, "later read failed"):
            node.run_one_iteration()
        node.stop_runtime()
        manifest, = node.local_storage_manager.manifests
        self.assertEqual(json.loads(Path(manifest.local_storage_path).read_text())["value"], 7)
        failure, = [message for message in node.runtime_evidence
                    if message.payload.get("event_type") == "acquisition_failure"]
        self.assertIn("later read failed", failure.payload["error"])
        self.assertNotIn("value", failure.payload)

    async def test_operational_publication_is_durable_and_reconstructs_without_scientific_intake(self):
        broker = _Broker()
        intake = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "journal")
        receiver = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", broker), intake)
        subscription = await receiver.subscribe_evidence("session")
        self.addAsyncCleanup(subscription.unsubscribe)
        node, _ = self.node()
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), node)
        node.run_one_iteration()
        node.stop_runtime()
        await handler.publish_new_artifact_manifest_evidence()
        await handler.publish_new_runtime_evidence()
        before = intake.recovery_journal_path.read_bytes()
        await handler.publish_new_runtime_evidence()
        self.assertEqual(intake.recovery_journal_path.read_bytes(), before)
        self.assertEqual(intake.accepted_envelopes, ())
        for message in node.runtime_evidence:
            self.assertTrue(intake.has_durable_runtime_evidence(message))
        restored = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "journal")
        self.assertEqual(restored.accepted_envelopes, ())
        for message in node.runtime_evidence:
            self.assertTrue(restored.has_durable_runtime_evidence(message))

    async def test_health_observation_and_interpretation_are_not_duplicated(self):
        from lab_sync_acquisition import AcquisitionHealthPolicy, ExperimentRuntimeHealthMapping
        policy = AcquisitionHealthPolicy(
            "policy", {"first_evidence": {"record_kind": "event", "grace_window_s": 0}},
            {"expected_acquisition_evidence_missing": "warning"})
        node, _ = self.node(selected=False, policies=(policy,))
        node.activate_experiment_runtime_health_mapping("experiment", (
            ExperimentRuntimeHealthMapping("device", "node", "policy", True, "events"),))
        node.run_one_iteration()
        node.run_one_iteration()
        self.assertEqual(len(node.experiment_scoped_health_observations), 1)
        self.assertEqual(len(node.health_interpretation_evidence), 1)
        self.assertEqual(sum(message.evidence_type == "health_interpretation"
                             for message in node.runtime_evidence), 1)
        self.assertEqual(sum(message.payload.get("event_category") == "acquisition_health"
                             for message in node.runtime_evidence), 1)
        node.stop_runtime()

    async def test_camera_frames_and_all_metadata_persist_locally(self):
        import h5py
        import numpy as np
        from lab_sync_acquisition import OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter
        from tests.test_scientific_camera_collection import FakeCV2
        frame = np.full((2, 4, 3), 500, dtype=np.uint16)
        backend = FakeCV2([frame], {0: 123.4})
        camera = SeeedIMX219OpenCVCameraAdapter("device", "camera", ("camera_frames",), True,
                                               cv2_module=backend)
        camera.initialize(OpenCVCameraConfig(0, 0, 1))
        camera.check_ready()
        product = ScientificProductDeclaration("frames", "camera_frames",
            {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5")
        declaration = DeviceDeclaration("device", "camera", True, True, ("camera_frames",), (product,))
        node = AcquisitionNode("session", DeviceManager([camera]), SynchronizationManager(),
            node_id="node", error_evidence_location=str(self.root / "errors"),
            device_declarations=(declaration,))
        manager = node.prepare_local_storage("session", (declaration,), self.root / "local")
        self.addCleanup(manager.cleanup)
        self.addCleanup(lambda: node.stop_runtime() if node.status()["is_running"] else None)
        self.assertTrue(node.prepare_experiment_scientific_outputs("experiment", (
            ScientificOutputSelection("device", "node", "frames"),)).ready)
        node.start_runtime()
        node.activate_experiment_runtime_context(ActiveExperimentRuntimeContext("experiment", 0.0))
        self.assertEqual(node.run_one_iteration().scientific_observations, 1)
        node.stop_runtime()
        manifest, = manager.manifests
        with h5py.File(manifest.local_storage_path, "r") as artifact:
            np.testing.assert_array_equal(artifact["frames"][0], frame)
            metadata = json.loads(artifact["record_metadata_json"][0])
            self.assertEqual(metadata["device_local_time"], 123.4)
            self.assertEqual(metadata["frame_index"], 0)
            self.assertEqual(metadata["session_id"], "session")
            self.assertIn("experiment_time_s", metadata)
        self.assertEqual(backend.capture.read_count, 1)
        self.assertTrue(backend.capture.released)

    async def test_failed_or_cancelled_publication_retries_identical_evidence_before_response(self):
        from tests.test_producer_publication_completion import PublicationBroker

        for mode in ("failure", "cancellation"):
            with self.subTest(mode=mode):
                broker = PublicationBroker()
                node, _ = self.node(selected=False, session_id=mode)
                handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), node)
                subscriptions = await handler.subscribe_commands()
                for subscription in subscriptions:
                    self.addAsyncCleanup(subscription.unsubscribe)
                controller = NatsControllerCommunication(_Boundary("controller", "controller", broker))
                result_subscription = await controller.subscribe_command_results(mode)
                self.addAsyncCleanup(result_subscription.unsubscribe)
                entered, release = asyncio.Event(), asyncio.Event()
                original = node.runtime_evidence

                async def pause(subject, data):
                    if data.get("payload", {}).get("event_category") == "session_lifecycle":
                        entered.set()
                        await release.wait()
                        if mode == "failure":
                            raise ConnectionError("durable publication unavailable")

                broker.before_publication = pause
                request = asyncio.create_task(controller.request_command(
                    RuntimeParticipant("acquisition_node", "node"), "run_one_iteration",
                    mode, {}, 2, command_id="iteration"))
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    self.assertFalse(broker.results)
                    if mode == "failure":
                        release.set()
                        with self.assertRaises(DurablePublicationError):
                            await request
                    else:
                        request.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await request
                finally:
                    release.set()
                    if not request.done():
                        request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
                self.assertFalse(broker.results)
                self.assertEqual(node.runtime_evidence, original)
                broker.before_publication = None
                result = await controller.request_command(RuntimeParticipant("acquisition_node", "node"),
                    "run_one_iteration", mode, {}, 2, command_id="iteration")
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.payload["iteration_index"], 1)
                messages = [data for _, data in broker.events
                            if data.get("payload", {}).get("event_category") == "session_lifecycle"]
                self.assertEqual(messages, [message.to_dict() for message in original])
                evidence_index = next(i for i, (_, data) in enumerate(broker.events) if data in messages)
                result_index = next(i for i, (_, data) in enumerate(broker.events) if "result_id" in data)
                self.assertLess(evidence_index, result_index)
                node.stop_runtime()

    async def test_finalization_failure_retains_unconfirmed_stop_evidence(self):
        node, _ = self.node()
        node.run_one_iteration()
        with patch.object(node.local_storage_manager, "finalize_stream", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(RuntimeError, "disk unavailable"):
                node.stop_runtime()
        stop = node.runtime_evidence[-1]
        self.assertEqual(stop.payload["event_type"], "session_stop")
        self.assertFalse(stop.payload["participant_cleanup_confirmed"])
        self.assertIn("disk unavailable", str(stop.payload["errors"]))
        self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "open")
        # Explicit retry finalizes retained bytes; it does not replace the failed-attempt evidence.
        node.stop_runtime()
        self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
        self.assertEqual(node.runtime_evidence[-2], stop)


if __name__ == "__main__":
    unittest.main()
