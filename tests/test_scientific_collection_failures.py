import json
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import ScientificProductDeclaration
from tests import test_scientific_acquisition_persistence as persistence_tests
from tests.fakes import ReadyFakeAdapter
from tests.test_scientific_camera_collection import FakeCV2


class FailingCollectionAdapter(ReadyFakeAdapter):
    def __init__(self, required=True):
        super().__init__("other", "fake", (), required)

    def collect_records(self):
        raise OSError("later device collection failed")


class IndexedFramesAdapter(ReadyFakeAdapter):
    def __init__(self, scientific_rows, runtime_rows):
        super().__init__("camera", "fake", ("camera_frames",), True)
        self.scientific_rows = scientific_rows
        self.runtime_rows = runtime_rows

    def collect_scientific_records(self):
        return {
            "runtime_records": {"record_kind": "camera_frame_metadata", "records": self.runtime_rows},
            "scientific_records": {"record_kind": "camera_frames", "records": self.scientific_rows},
        }


class ScientificCollectionFailureTests(unittest.TestCase):
    workflow = persistence_tests.ScientificAcquisitionPersistenceTests.workflow

    def frame(self, value, index=0, product=None):
        row = {"frame_index": index, "frame": np.full((2, 4, 3), value, dtype=np.uint16)}
        if product is not None:
            row["data_product_id"] = product
        return row

    def runtime_rows(self, ingestor):
        return [row for envelope in ingestor.accepted_envelopes
                if envelope.record_kind == "camera_frame_metadata" for row in envelope.records]

    def assert_preserved_frame(self, node, ingestor, expected):
        manifest, = node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        self.assertEqual(manifest.details["persisted_frame_count"], 1)
        metadata, = self.runtime_rows(ingestor)
        with h5py.File(manifest.local_storage_path, "r") as artifact:
            np.testing.assert_array_equal(artifact["frames"][:], expected[None, ...])
            self.assertEqual(list(artifact["frame_index"][:]), [0])
            saved = json.loads(artifact["record_metadata_json"][0])
            self.assertEqual(saved["session_id"], "session")
            self.assertEqual(saved["experiment_id"], "experiment")
            for field in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status"):
                self.assertEqual(saved[field], metadata[field])
        self.assertNotIn("frame", metadata)

    def test_camera_read_exception_preserves_prior_frame_and_metadata(self):
        expected = np.full((2, 4, 3), 50, dtype=np.uint16)
        with self.workflow(frames=[expected], count=2, max_buffered_rows=20) as (controller, node, ingestor, capture):
            read = capture.read
            def failing_read():
                if capture.read_count == 1:
                    raise OSError("second camera read failed")
                return read()
            with patch.object(capture, "read", side_effect=failing_read):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("second camera read failed", result.error)
            self.assertEqual(capture.read_count, 1)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assert_preserved_frame(node, ingestor, expected)
            self.assertFalse(controller.start_experiment("experiment").succeeded)

    def test_optional_timestamp_failure_does_not_hide_later_read_exception(self):
        expected = np.full((2, 4, 3), 50, dtype=np.uint16)
        with self.workflow(frames=[expected], count=2, max_buffered_rows=20) as (controller, node, ingestor, capture):
            read = capture.read
            get_property = capture.get

            def get_optional_property(property_id):
                if property_id == FakeCV2.CAP_PROP_POS_MSEC:
                    raise OSError("native timestamp unavailable")
                return get_property(property_id)

            def failing_read():
                if capture.read_count == 1:
                    raise OSError("second camera read failed")
                return read()

            with patch.object(capture, "get", side_effect=get_optional_property), \
                    patch.object(capture, "read", side_effect=failing_read) as read_mock:
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("second camera read failed", result.error)
            self.assertNotIn("native timestamp unavailable", result.error)
            self.assertEqual(read_mock.call_count, 2)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assert_preserved_frame(node, ingestor, expected)
            self.assertNotIn("device_local_time", self.runtime_rows(ingestor)[0])

    def test_later_device_failure_preserves_prior_camera_collection(self):
        expected = np.full((2, 4, 3), 150, dtype=np.uint16)
        for required in (True, False):
            with self.subTest(required=required), self.workflow(
                frames=[expected], max_buffered_rows=20,
                additional_adapters=(FailingCollectionAdapter(required),),
            ) as (controller, node, ingestor, capture):
                result = controller.run_one_iteration()
                self.assertFalse(result.succeeded)
                self.assertIn("later device collection failed", result.error)
                self.assertEqual(capture.read_count, 1)
                # Collection exceptions keep the existing Controller failure path,
                # regardless of required/optional readiness participation.
                self.assertEqual(controller.get_status()["session_state"], "failed")
                self.assert_preserved_frame(node, ingestor, expected)

    def test_six_frames_survive_seventh_read_exception_in_ten_frame_request(self):
        frames = [np.full((2, 4, 3), index, dtype=np.uint16) for index in range(6)]
        with self.workflow(frames=frames, count=10, max_buffered_rows=20) as (controller, node, ingestor, capture):
            origin = node.status()["active_experiment_runtime_context"].experiment_start_session_time_s
            read = capture.read
            attempts = []
            def failing_read():
                attempts.append(1)
                if capture.read_count == 6:
                    raise OSError("seventh read failed")
                return read()
            with patch.object(capture, "read", side_effect=failing_read):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("seventh read failed", result.error)
            self.assertEqual(len(attempts), 7)
            metadata = self.runtime_rows(ingestor)
            self.assertEqual([row["frame_index"] for row in metadata], list(range(6)))
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.details["persisted_frame_count"], 6)
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack(frames))
                for index, row in enumerate(metadata):
                    self.assertAlmostEqual(row["experiment_time_s"], row["session_time_s"] - origin)
                    self.assertEqual(artifact["session_time_s"][index], row["session_time_s"])

    def test_collection_and_partial_persistence_failures_both_remain_visible(self):
        with self.workflow(additional_adapters=(FailingCollectionAdapter(),)) as (controller, node, _, _):
            with patch.object(node.local_storage_manager, "append_rows", side_effect=OSError("partial disk failure")):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("later device collection failed", result.error)
            self.assertIn("partial disk failure", result.error)
            self.assertEqual(node.local_storage_manager.manifests[0].details["row_count"], 0)

    def test_duplicate_scientific_indices_are_rejected_before_any_frame_write(self):
        adapter = IndexedFramesAdapter(
            (self.frame(50), self.frame(150)), ({"frame_index": 0, "read_success": True},),
        )
        with self.workflow(adapter=adapter) as (controller, node, ingestor, _):
            result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("Ambiguous", result.error)
            manifest, = node.local_storage_manager.manifests
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                self.assertEqual(len(artifact["frames"]), 0)
            self.assertEqual(self.runtime_rows(ingestor), [])

    def test_duplicate_runtime_metadata_is_rejected_before_frame_write(self):
        adapter = IndexedFramesAdapter(
            (self.frame(50),), ({"frame_index": 0, "read_success": True},) * 2,
        )
        with self.workflow(adapter=adapter) as (controller, node, _, _):
            result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("Ambiguous", result.error)
            with h5py.File(node.local_storage_manager.manifests[0].local_storage_path, "r") as artifact:
                self.assertEqual(len(artifact["frames"]), 0)

    def test_later_ambiguous_collection_preserves_earlier_completed_frame(self):
        expected = self.frame(50)
        adapter = IndexedFramesAdapter((expected,), ({"frame_index": 0, "read_success": True},))
        with self.workflow(adapter=adapter, max_buffered_rows=20) as (controller, node, ingestor, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            adapter.scientific_rows = (self.frame(100, index=1), self.frame(150, index=1))
            adapter.runtime_rows = ({"frame_index": 1, "read_success": True},)
            result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("Ambiguous", result.error)
            self.assert_preserved_frame(node, ingestor, expected["frame"])

    def test_same_index_in_distinct_products_uses_product_specific_metadata(self):
        products = tuple(ScientificProductDeclaration(
            name, "camera_frames", {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5",
        ) for name in ("first", "second"))
        adapter = IndexedFramesAdapter(
            (self.frame(50, product="first"), self.frame(150, product="second")),
            tuple({"frame_index": 0, "read_success": True, "data_product_id": name} for name in ("first", "second")),
        )
        with self.workflow(adapter=adapter, products=products, select_all=True) as (controller, node, ingestor, _):
            result = controller.run_one_iteration()
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            metadata = self.runtime_rows(ingestor)
            self.assertEqual(len(metadata), 2)
            for index, manifest in enumerate(node.local_storage_manager.manifests):
                with h5py.File(manifest.local_storage_path, "r") as artifact:
                    self.assertEqual(list(artifact["frame_index"][:]), [0])
                    self.assertEqual(artifact["frames"][0, 0, 0, 0], (50, 150)[index])
                    self.assertEqual(artifact["session_time_s"][0], metadata[index]["session_time_s"])


if __name__ == "__main__":
    unittest.main()
