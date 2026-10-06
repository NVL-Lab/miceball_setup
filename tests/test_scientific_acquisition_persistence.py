from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, DeviceDeclaration, InMemoryIngestor,
    PersistentStorageManager, ScientificOutputSelection, ScientificProductDeclaration,
    SessionConfig, SynchronizationManager, OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter,
    LocalStorageManager,
)
from tests.test_scientific_camera_collection import FakeCV2
from tests.fakes import ReadyFakeAdapter


class ScientificEventAdapter(ReadyFakeAdapter):
    def __init__(self, product_id="events", experiment_id=None, device_id="camera"):
        super().__init__(device_id, "fake", ("events",), True)
        self.product_id = product_id
        self.experiment_id = experiment_id
        self.scientific_calls = 0
        self.runtime_calls = 0

    def collect_records(self):
        self.runtime_calls += 1
        return {"record_kind": "events", "records": ({"value": 7},)}

    def collect_scientific_records(self):
        self.scientific_calls += 1
        row = {"value": 7, "data_product_id": self.product_id}
        if self.experiment_id is not None:
            row["experiment_id"] = self.experiment_id
        return {"runtime_records": {"record_kind": "events", "records": ({"value": 7},)},
                "scientific_records": {"record_kind": "events", "records": (row,)}}


class ScientificAcquisitionPersistenceTests(unittest.TestCase):
    @contextmanager
    def workflow(self, *, frames=None, properties=None, count=1, adapter=None,
                 products=None, selected=True, select_all=False, max_buffered_rows=None,
                 additional_adapters=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = None
            if adapter is None:
                cv2 = FakeCV2(frames if frames is not None else [np.arange(24, dtype=np.uint16).reshape(2, 4, 3)], properties)
                capture = cv2.capture
                adapter = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", ("camera_frames",), True, cv2_module=cv2)
                adapter.initialize(OpenCVCameraConfig(0, 0, count))
            else:
                adapter.initialize({})
            products = products if products is not None else (
                ScientificProductDeclaration("frames", "camera_frames",
                                             {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),)
            config = SessionConfig(
                [DeviceDeclaration("camera", "camera", True, True, ("camera_frames",), products)],
                str(root / "runtime.jsonl"), {}, str(root / "errors"), session_id="session",
            )
            for additional_adapter in additional_adapters:
                additional_adapter.initialize({})
            manager = DeviceManager((adapter, *additional_adapters))
            storage = PersistentStorageManager(root / "runtime.jsonl")
            ingestor = InMemoryIngestor(storage)
            sync = SynchronizationManager()
            node = AcquisitionNode("session", manager, sync, ingestor, node_id="node",
                                   error_evidence_location=config.error_evidence_location,
                                   default_local_storage_root=root / "local")
            controller = Controller(node, ingestor, storage, root / "session.json", synchronization_manager=sync)
            if max_buffered_rows is not None:
                node.attach_local_storage_manager(LocalStorageManager(
                    root / "local", "session", "node", max_buffered_rows=max_buffered_rows,
                ), config.selected_devices)
            self.assertTrue(controller.create_session(config).succeeded)
            readiness = node.check_ready()
            self.assertTrue(controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]).succeeded)
            start = controller.start_session()
            self.assertTrue(start.succeeded, start.error)
            outputs = tuple(ScientificOutputSelection("camera", "node", product.data_product_id)
                            for product in (products if select_all else products[:1])) if selected else ()
            self.assertTrue(controller.start_experiment("experiment", scientific_outputs=outputs).succeeded)
            try:
                yield controller, node, ingestor, capture
            finally:
                if node.status()["is_running"]:
                    node.stop_runtime()
                node.local_storage_manager.cleanup()

    def test_frames_and_runtime_metadata_share_timing_without_duplicate_reads(self):
        frames = [np.arange(24, dtype=np.uint16).reshape(2, 4, 3),
                  np.full((2, 4, 3), 60000, dtype=np.uint16)]
        with self.workflow(frames=frames, count=2, properties={0: 123.4}) as (controller, node, ingestor, capture):
            origin = node.status()["active_experiment_runtime_context"].experiment_start_session_time_s
            with patch("lab_sync_acquisition.acquisition_node.monotonic", side_effect=[10.0, 11.0]):
                self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertEqual(capture.read_count, 2)
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            runtime = [row for envelope in ingestor.accepted_envelopes
                       if envelope.record_kind == "camera_frame_metadata" for row in envelope.records]
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack(frames))
                self.assertEqual(artifact["frames"].dtype, np.dtype("uint16"))
                for index, metadata in enumerate(runtime):
                    saved = json.loads(artifact["record_metadata_json"][index])
                    for field in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status"):
                        self.assertEqual(saved[field], metadata[field])
                    self.assertAlmostEqual(saved["experiment_time_s"], saved["session_time_s"] - origin)
                    self.assertEqual(saved["timestamp_status"], "runtime_timestamped")
                    self.assertEqual(saved["device_local_time"], 123.4)
                    self.assertEqual(saved["experiment_id"], "experiment")
                self.assertGreater(artifact["acquisition_node_local_time_s"][1], artifact["acquisition_node_local_time_s"][0])
            for envelope in ingestor.accepted_envelopes:
                json.dumps(envelope.to_dict())
                self.assertTrue(all("frame" not in row for row in envelope.records))

    def test_missing_device_native_timing_is_not_fabricated(self):
        with self.workflow() as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                self.assertNotIn("device_local_time", json.loads(artifact["record_metadata_json"][0]))

    def test_optional_timestamp_failure_preserves_persistence_and_running_lifecycle(self):
        frames = [np.full((2, 4, 3), value, dtype=np.uint16) for value in (50, 150)]
        with self.workflow(frames=frames, properties={5: 29.5, 15: -4, 14: 2}) as (controller, node, ingestor, capture):
            origin = node.status()["active_experiment_runtime_context"].experiment_start_session_time_s
            get_property = capture.get

            def get_optional_property(property_id):
                if property_id == FakeCV2.CAP_PROP_POS_MSEC:
                    raise OSError("native timestamp unavailable")
                return get_property(property_id)

            with patch.object(capture, "get", side_effect=get_optional_property):
                for _ in frames:
                    result = controller.run_one_iteration()
                    self.assertTrue(result.succeeded, result.error)
                    self.assertEqual(controller.get_status()["session_state"], "running")
                    self.assertEqual(node.status()["active_experiment_runtime_context"].experiment_id, "experiment")
                    self.assertTrue(node.status()["is_running"])
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            metadata = [row for envelope in ingestor.accepted_envelopes
                        if envelope.record_kind == "camera_frame_metadata" for row in envelope.records]
            self.assertEqual(capture.read_count, 2)
            self.assertEqual(len(metadata), 2)
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack(frames))
                self.assertEqual(artifact["frames"].dtype, np.dtype("uint16"))
                self.assertEqual(artifact["frames"].shape, (2, 2, 4, 3))
                self.assertEqual(list(artifact["frame_index"][:]), [0, 1])
                for index, runtime_row in enumerate(metadata):
                    saved = json.loads(artifact["record_metadata_json"][index])
                    self.assertNotIn("device_local_time", saved)
                    self.assertNotIn("device_local_time", runtime_row)
                    self.assertTrue(runtime_row["read_success"])
                    self.assertEqual(saved["experiment_id"], "experiment")
                    self.assertEqual(saved["reported_fps"], 29.5)
                    self.assertEqual(saved["exposure"], -4)
                    self.assertEqual(saved["gain"], 2)
                    for field in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status"):
                        self.assertEqual(saved[field], runtime_row[field])
                    self.assertAlmostEqual(saved["experiment_time_s"], saved["session_time_s"] - origin)
                    self.assertEqual(saved["timestamp_status"], "runtime_timestamped")

    def test_other_optional_property_failures_preserve_scientific_acquisition(self):
        properties = {0: 123.4, 5: 29.5, 15: -4, 14: 2}
        optional = ((FakeCV2.CAP_PROP_FPS, "reported_fps"),
                    (FakeCV2.CAP_PROP_EXPOSURE, "exposure"), (FakeCV2.CAP_PROP_GAIN, "gain"))
        for property_id, missing in optional:
            with self.subTest(property=missing), self.workflow(properties=properties) as (controller, node, _, capture):
                get_property = capture.get

                def get_optional_property(requested_id):
                    if requested_id == property_id:
                        raise OSError("optional camera property unavailable")
                    return get_property(requested_id)

                with patch.object(capture, "get", side_effect=get_optional_property):
                    result = controller.run_one_iteration()
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(controller.get_status()["session_state"], "running")
                self.assertEqual(node.status()["active_experiment_runtime_context"].experiment_id, "experiment")
                manifest, = node.local_storage_manager.manifests
                node.local_storage_manager.flush(manifest.storage_id)
                with h5py.File(manifest.local_storage_path, "r") as artifact:
                    np.testing.assert_array_equal(artifact["frames"][0], np.arange(24, dtype=np.uint16).reshape(2, 4, 3))
                    saved = json.loads(artifact["record_metadata_json"][0])
                    self.assertNotIn(missing, saved)
                    self.assertEqual(saved["device_local_time"], 123.4)
                    for available_id, available in optional:
                        if available != missing:
                            self.assertEqual(saved[available], properties[available_id])

    def test_multiple_iterations_append_to_same_prepared_stream(self):
        frames = [np.full((2, 4, 3), value, dtype=np.uint16) for value in (1, 2, 3)]
        with self.workflow(frames=frames) as (controller, node, _, capture):
            for _ in frames:
                self.assertTrue(controller.run_one_iteration().succeeded)
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            self.assertEqual(capture.read_count, 3)
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack(frames))
                self.assertEqual(list(artifact["frame_index"][:]), [0, 1, 2])

    def test_metadata_only_camera_experiment_creates_no_scientific_artifact(self):
        with self.workflow(selected=False) as (controller, node, ingestor, capture):
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertEqual(capture.read_count, 1)
            self.assertEqual(node.local_storage_manager.manifests, ())
            self.assertTrue(any(e.record_kind == "camera_frame_metadata" for e in ingestor.accepted_envelopes))

    def test_jsonl_scientific_product_persists_with_framework_timing(self):
        product = ScientificProductDeclaration("events", "events", {"value": "number"}, "jsonl")
        with self.workflow(adapter=ScientificEventAdapter(), products=(product,)) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            row = json.loads(Path(manifest.local_storage_path).read_text().strip())
            self.assertEqual(row["value"], 7)
            self.assertEqual(row["experiment_id"], "experiment")
            for field in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status"):
                self.assertIn(field, row)

    def test_known_unselected_product_is_not_persisted(self):
        products = tuple(ScientificProductDeclaration(name, "events", {}, "jsonl") for name in ("selected", "unselected"))
        with self.workflow(adapter=ScientificEventAdapter("unselected"), products=products) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            manifest, = node.local_storage_manager.manifests
            node.local_storage_manager.flush(manifest.storage_id)
            self.assertEqual(Path(manifest.local_storage_path).read_text(), "")

    def test_unknown_product_and_wrong_experiment_are_rejected(self):
        product = ScientificProductDeclaration("events", "events", {}, "jsonl")
        for adapter in (ScientificEventAdapter("unknown"), ScientificEventAdapter(experiment_id="other")):
            with self.subTest(adapter=adapter), self.workflow(adapter=adapter, products=(product,)) as (controller, _, _, _):
                result = controller.run_one_iteration()
                self.assertFalse(result.succeeded)
                self.assertTrue(result.error)

    def test_missing_storage_mapping_fails_without_lazy_stream_creation(self):
        with self.workflow() as (controller, node, _, _):
            # Fault injection simulates loss of a prepared runtime write handle.
            with patch.object(node, "_scientific_output_storage_ids", {}):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("no prepared storage mapping", result.error)
            self.assertEqual(len(node.local_storage_manager.manifests), 1)

    def test_scientific_write_failure_is_not_successful_acquisition(self):
        with self.workflow() as (controller, node, _, _):
            with patch.object(node.local_storage_manager, "append_rows", side_effect=OSError("disk failed")):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("disk failed", result.error)

    def test_unselected_device_uses_only_existing_runtime_collection(self):
        adapter = ScientificEventAdapter()
        product = ScientificProductDeclaration("events", "events", {}, "jsonl")
        with self.workflow(adapter=adapter, products=(product,), selected=False) as (controller, _, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertEqual(adapter.runtime_calls, 1)
            self.assertEqual(adapter.scientific_calls, 0)

    def test_selected_and_unselected_devices_are_each_collected_once(self):
        selected = ScientificEventAdapter()
        unselected = ScientificEventAdapter(device_id="other")
        manager = DeviceManager((selected, unselected))
        manager.initialize_all({})
        manager.check_readiness()
        manager.start_all()
        try:
            results = manager.collect_scientific_records(scientific_source_device_ids=("camera",))
            self.assertIsNotNone(results[0].scientific_records)
            self.assertIsNone(results[1].scientific_records)
            self.assertEqual((selected.scientific_calls, selected.runtime_calls), (1, 0))
            self.assertEqual((unselected.scientific_calls, unselected.runtime_calls), (0, 1))
        finally:
            manager.stop_all()
            manager.shutdown_all()

    def test_ambiguous_product_kind_requires_explicit_product_id(self):
        products = tuple(ScientificProductDeclaration(
            name, "camera_frames", {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5")
            for name in ("frames", "other-frames"))
        with self.workflow(products=products) as (controller, _, _, _):
            result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("ambiguous", result.error)


if __name__ == "__main__":
    unittest.main()
