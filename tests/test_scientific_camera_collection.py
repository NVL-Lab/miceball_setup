import json
import unittest
from unittest.mock import patch

import numpy as np

from lab_sync_acquisition import (
    DeviceAdapter, DeviceCollectionResult, DeviceManager,
    OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter,
)


class FakeCapture:
    def __init__(self, frames, properties):
        self.frames = iter(frames)
        self.properties = properties
        self.read_count = 0
        self.opened = True
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        self.read_count += 1
        frame = next(self.frames, None)
        return frame is not None, frame

    def get(self, property_id):
        return self.properties.get(property_id, 0)

    def set(self, property_id, value):
        return True

    def getBackendName(self):
        return "SYNTHETIC"

    def release(self):
        self.released = True
        self.opened = False


class FakeCV2:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    CAP_PROP_EXPOSURE = 15
    CAP_PROP_GAIN = 14

    def __init__(self, frames, properties=None):
        self.capture = FakeCapture(frames, properties or {})

    def VideoCapture(self, source, api_preference):
        return self.capture


class LightweightAdapter(DeviceAdapter):
    def collect_records(self):
        return {"record_kind": "event", "records": ({"value": 1},)}


class ScientificCameraCollectionTests(unittest.TestCase):
    def camera(self, frames, count=2, properties=None):
        cv2 = FakeCV2(frames, properties)
        adapter = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frame_metadata", "camera_frames"),
            True, cv2_module=cv2,
        )
        adapter.initialize(OpenCVCameraConfig(0, 0, count, fps=30))
        self.assertTrue(adapter.check_ready().ready)
        adapter.start()
        self.addCleanup(self.close_camera, adapter)
        return adapter, cv2.capture

    def close_camera(self, adapter):
        if adapter.get_status().running:
            adapter.stop()
        if not adapter.get_status().shutdown:
            adapter.shutdown()

    def test_scientific_collection_preserves_arrays_and_aligned_metadata_in_one_read(self):
        frames = [np.arange(36, dtype=np.uint16).reshape(3, 4, 3),
                  np.full((3, 4, 3), 1000, dtype=np.uint16)]
        adapter, capture = self.camera(frames, properties={0: 123.4, 5: 29.5, 15: -4, 14: 2})
        result = DeviceManager([adapter]).collect_scientific_records()[0]
        self.assertIsInstance(result, DeviceCollectionResult)
        scientific = result.scientific_records
        runtime = result.runtime_records
        self.assertEqual(scientific.source_device_id, "camera")
        self.assertEqual(scientific.record_kind, "camera_frames")
        self.assertEqual(runtime.record_kind, "camera_frame_metadata")
        self.assertEqual(capture.read_count, 2)
        for index, (row, metadata) in enumerate(zip(scientific.records, runtime.records)):
            self.assertIs(row["frame"], frames[index])
            np.testing.assert_array_equal(row["frame"], frames[index])
            self.assertEqual(row["frame"].dtype, np.dtype("uint16"))
            self.assertEqual(row["frame"].shape, (3, 4, 3))
            self.assertEqual(row["frame_index"], index)
            self.assertEqual(metadata["frame_index"], index)
            self.assertEqual(row["device_local_time"], 123.4)
            self.assertEqual(row["reported_fps"], 29.5)
            self.assertEqual(row["configured_fps"], 30)
            self.assertEqual(row["exposure"], -4)
            self.assertEqual(row["gain"], 2)
            self.assertEqual(row["backend"], "SYNTHETIC")
        # The lightweight half remains directly JSON serializable.
        json.dumps(runtime.records)

    def test_default_collection_is_metadata_only_and_indices_continue(self):
        frames = [np.zeros((2, 3), dtype=np.uint8), np.ones((2, 3), dtype=np.uint8)]
        adapter, capture = self.camera(frames, count=1)
        manager = DeviceManager([adapter])
        first = manager.collect_records()[0]
        self.assertEqual(first.record_kind, "camera_frame_metadata")
        self.assertEqual(first.records[0]["frame_index"], 0)
        self.assertNotIn("frame", first.records[0])
        json.dumps(first.records)
        second = manager.collect_scientific_records()[0]
        self.assertEqual(second.scientific_records.records[0]["frame_index"], 1)
        self.assertEqual(second.scientific_records.records[0]["frame"].shape, (2, 3))
        self.assertEqual(capture.read_count, 2)

    def test_unavailable_optional_metadata_is_absent(self):
        adapter, _ = self.camera([np.zeros((2, 2, 3), dtype=np.uint8)], count=1)
        row = adapter.collect_scientific_records()["scientific_records"]["records"][0]
        for name in ("device_local_time", "reported_fps", "exposure", "gain"):
            self.assertNotIn(name, row)
        self.assertEqual(row["configured_fps"], 30)

    def test_optional_timestamp_query_exception_keeps_frames_and_metadata(self):
        frames = [np.full((2, 3), value, dtype=np.uint16) for value in (50, 150)]
        adapter, capture = self.camera(frames, count=1, properties={5: 29.5, 15: -4, 14: 2})
        get_property = capture.get

        def get_optional_property(property_id):
            if property_id == FakeCV2.CAP_PROP_POS_MSEC:
                raise OSError("native timestamp unavailable")
            return get_property(property_id)

        with patch.object(capture, "get", side_effect=get_optional_property):
            metadata, = adapter.collect_records()["records"]
            scientific = adapter.collect_scientific_records()["scientific_records"]["records"][0]
        self.assertTrue(metadata["read_success"])
        self.assertEqual(metadata["frame_index"], 0)
        self.assertEqual(scientific["frame_index"], 1)
        self.assertNotIn("device_local_time", metadata)
        self.assertNotIn("device_local_time", scientific)
        np.testing.assert_array_equal(scientific["frame"], frames[1])
        self.assertEqual(scientific["frame"].dtype, np.dtype("uint16"))
        self.assertEqual(scientific["frame"].shape, (2, 3))
        self.assertEqual(scientific["reported_fps"], 29.5)
        self.assertEqual(scientific["exposure"], -4)
        self.assertEqual(scientific["gain"], 2)
        self.assertEqual(capture.read_count, 2)
        self.assertTrue(adapter.get_status().running)

    def test_failed_reads_remain_metadata_without_fabricated_frames(self):
        frame = np.zeros((2, 2), dtype=np.float32)
        adapter, capture = self.camera([None, frame], count=2)
        result = DeviceManager([adapter]).collect_scientific_records()[0]
        self.assertEqual(len(result.runtime_records.records), 2)
        self.assertFalse(result.runtime_records.records[0]["read_success"])
        self.assertEqual(len(result.scientific_records.records), 1)
        self.assertIs(result.scientific_records.records[0]["frame"], frame)
        self.assertEqual(result.scientific_records.records[0]["frame_index"], 0)
        self.assertEqual(capture.read_count, 2)

    def test_other_adapters_keep_existing_collection_with_no_scientific_data(self):
        adapter = LightweightAdapter("sensor", "sensor", (), False)
        result = DeviceManager([adapter]).collect_scientific_records()[0]
        self.assertIsNone(result.scientific_records)
        self.assertEqual(result.runtime_records.source_device_id, "sensor")
        self.assertEqual(result.runtime_records.record_kind, "event")
        self.assertEqual(result.runtime_records.records, ({"value": 1},))

    def test_grayscale_float_frames_preserve_values_and_array_layout(self):
        frame = np.arange(24, dtype=np.float32).reshape(4, 6)[:, ::2]
        adapter, _ = self.camera([frame], count=1)
        result = adapter.collect_scientific_records()
        row = result["scientific_records"]["records"][0]
        self.assertIs(row["frame"], frame)
        self.assertEqual(row["frame"].strides, frame.strides)
        np.testing.assert_array_equal(row["frame"], frame)
        self.assertEqual(row["channels"], 1)
        self.assertEqual(row["dtype"], "float32")

    def test_scientific_collection_retains_normal_shutdown(self):
        adapter, capture = self.camera([np.zeros((2, 2), dtype=np.uint8)], count=1)
        manager = DeviceManager([adapter])
        manager.collect_scientific_records()
        self.assertTrue(manager.stop_all()[0].succeeded)
        self.assertTrue(manager.shutdown_all()[0].succeeded)
        self.assertTrue(capture.released)
        self.assertTrue(adapter.get_status().shutdown)


if __name__ == "__main__":
    unittest.main()
