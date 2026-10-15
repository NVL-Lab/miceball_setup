import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests import test_scientific_acquisition_persistence as persistence_tests
from tests.fakes import ReadyFakeAdapter
from tests.test_scientific_camera_collection import FakeCV2
from lab_sync_acquisition.device_adapter import _PartialScientificCollectionError


class FailingCollectionAdapter(ReadyFakeAdapter):
    def __init__(self, required=True):
        super().__init__("other", "fake", (), required)

    def collect_products(self, products, **context):
        raise OSError("later device collection failed")


class ScientificCollectionFailureTests(unittest.TestCase):
    workflow = persistence_tests.ScientificAcquisitionPersistenceTests.workflow
    saved_metadata = persistence_tests.ScientificAcquisitionPersistenceTests.saved_metadata

    def test_invalid_later_partial_result_preserves_earlier_device_observations(self):
        other = FailingCollectionAdapter()
        expected = np.ones((2, 4, 3), dtype=np.uint16)

        def fail(products, **context):
            raise _PartialScientificCollectionError(OSError("later device read failed"), {
                "scientific_products": {"unselected": ({"value": 1},)}, "operational_evidence": ()})

        with self.workflow(frames=[expected], additional_adapters=(other,)) as (controller, node, ingestor, _):
            with patch.object(other, "collect_products", side_effect=fail):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("later device read failed", result.error)
            self.assertIn("unselected scientific product", result.error)
            self.assert_preserved_frame(node, ingestor, expected)

    def assert_preserved_frame(self, node, ingestor, expected):
        manifest, = node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        self.assertEqual(manifest.details["persisted_frame_count"], 1)
        metadata, = self.saved_metadata(node)
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
            self.assertNotIn("device_local_time", self.saved_metadata(node)[0])

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
            metadata = self.saved_metadata(node)
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



if __name__ == "__main__":
    unittest.main()
