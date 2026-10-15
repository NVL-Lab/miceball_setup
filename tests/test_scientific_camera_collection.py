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


class ScientificCameraCollectionTests(unittest.TestCase):
    def product(self):
        from lab_sync_acquisition import ScientificProductDeclaration
        return ScientificProductDeclaration("frames", "camera_frames",
            {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5")

    def adapter(self, frames, count=1, properties=None):
        backend = FakeCV2(frames, properties)
        adapter = SeeedIMX219OpenCVCameraAdapter("camera", "camera", ("camera_frames",), True,
                                               cv2_module=backend)
        adapter.initialize(OpenCVCameraConfig(0, 0, count))
        adapter.check_ready()
        adapter.start()
        self.addCleanup(adapter.shutdown)
        self.addCleanup(adapter.stop)
        return adapter, backend.capture

    def collect(self, adapter, products):
        return adapter.collect_products(products, session_id="session", experiment_id="experiment",
                                        acquisition_node_id="node")

    def test_selected_frames_preserve_identity_and_metadata_in_one_read(self):
        frames = [np.full((2, 4, 3), value, dtype=np.uint16) for value in (1, 2)]
        adapter, capture = self.adapter(frames, count=2, properties={0: 123.4})
        result = self.collect(adapter, (self.product(),))
        self.assertEqual(capture.read_count, 2)
        self.assertEqual(result["operational_evidence"], [])
        rows = result["scientific_products"]["frames"]
        self.assertEqual([row["frame_index"] for row in rows], [0, 1])
        for row, frame in zip(rows, frames):
            np.testing.assert_array_equal(row["frame"], frame)
            self.assertEqual(row["device_local_time"], 123.4)
            self.assertTrue(row["read_success"])

    def test_no_selected_product_does_not_read_camera(self):
        adapter, capture = self.adapter([])
        self.assertEqual(self.collect(adapter, ())["scientific_products"], {})
        self.assertEqual(capture.read_count, 0)

    def test_unavailable_optional_timestamp_is_not_fabricated(self):
        adapter, _ = self.adapter([np.zeros((2, 4, 3), dtype=np.uint16)])
        row, = self.collect(adapter, (self.product(),))["scientific_products"]["frames"]
        self.assertNotIn("device_local_time", row)

    def test_failed_later_read_retains_completed_frame(self):
        from lab_sync_acquisition.device_adapter import _PartialScientificCollectionError
        frame = np.zeros((2, 4, 3), dtype=np.uint16)
        adapter, capture = self.adapter([frame, None], count=2)
        with self.assertRaises(_PartialScientificCollectionError) as caught:
            self.collect(adapter, (self.product(),))
        self.assertEqual(capture.read_count, 2)
        rows = caught.exception.partial_collection["scientific_products"]["frames"]
        self.assertEqual(len(rows), 1)
        np.testing.assert_array_equal(rows[0]["frame"], frame)

    def test_wrong_product_is_rejected_before_acquisition(self):
        from lab_sync_acquisition import ScientificProductDeclaration
        adapter, capture = self.adapter([])
        with self.assertRaises(ValueError):
            self.collect(adapter, (ScientificProductDeclaration("events", "event", {}, "jsonl"),))
        self.assertEqual(capture.read_count, 0)


if __name__ == "__main__":
    unittest.main()
