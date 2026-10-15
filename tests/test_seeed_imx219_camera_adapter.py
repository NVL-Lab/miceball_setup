import numpy as np
import unittest
from unittest.mock import patch
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    ScientificProductDeclaration,
    DeviceManager,
    DeviceAdapterState,
    DeviceAdapterLifecycleError,
    OpenCVCameraConfig,
    SeeedIMX219OpenCVCameraAdapter,
)


class FakeFrame:
    def __init__(self, shape, dtype):
        self.shape = shape
        self.dtype = dtype


class FakeVideoCapture:
    def __init__(self, source, api_preference, frames):
        self.source = source
        self.api_preference = api_preference
        self._frames = list(frames)
        self._opened = True
        self._released = False
        self.properties_set = []

    def isOpened(self):
        return self._opened

    def set(self, property_id, value):
        self.properties_set.append((property_id, value))
        return True

    def read(self):
        if not self._frames:
            return False, None
        return True, self._frames.pop(0)

    def get(self, property_id):
        if property_id == FakeCV2.CAP_PROP_POS_MSEC:
            return 123.456
        return 0

    def getBackendName(self):
        return "FAKE_OPENCV"

    def release(self):
        self._released = True
        self._opened = False

    @property
    def released(self):
        return self._released


class FakeCV2:
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    CAP_V4L2 = 200

    def __init__(self, frames):
        self._frames = frames
        self.captures = []

    def VideoCapture(self, source, api_preference):
        capture = FakeVideoCapture(source, api_preference, self._frames)
        self.captures.append(capture)
        return capture


class SeeedIMX219OpenCVCameraAdapterTests(unittest.TestCase):
    def test_camera_setup_failure_releases_partial_capture_before_reuse(self):
        for operation in ("set", "isOpened"):
            with self.subTest(operation=operation):
                cv2 = FakeCV2([np.zeros((3, 4, 3), dtype=np.uint8)])
                adapter = SeeedIMX219OpenCVCameraAdapter(
                    "camera", "opencv", ("camera_frame_metadata",), True, cv2_module=cv2)
                with patch.object(FakeVideoCapture, "release", autospec=True,
                                  side_effect=FakeVideoCapture.release) as release:
                    with patch.object(FakeVideoCapture, operation,
                                      side_effect=OSError("camera setup failed")):
                        with self.assertRaisesRegex(OSError, "camera setup failed"):
                            adapter.initialize(OpenCVCameraConfig(0, 0, 1, frame_width=640))
                    self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
                    self.assertFalse(adapter.get_status().shutdown)
                    self.assertTrue(cv2.captures[0].released)
                    adapter.shutdown()
                    adapter.shutdown()
                    self.assertEqual(release.call_count, 1)
                self.assertFalse(cv2.captures[0].isOpened())
                self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
                self.assertTrue(adapter.get_status().shutdown)
                self.assertTrue(adapter.check_ready().ready)
                adapter.initialize(OpenCVCameraConfig(1, 0, 1))
                self.assertTrue(adapter.check_ready().ready)
                adapter.start()
                self.assertEqual(len(adapter.collect_products((ScientificProductDeclaration("frames", "camera_frames",
                    {"frame_shape": [3, 4, 3], "frame_dtype": "uint8"}, "hdf5"),),
                    session_id="session", experiment_id="experiment", acquisition_node_id="node")["scientific_products"]["frames"]), 1)
                adapter.stop()
                adapter.shutdown()
                self.assertTrue(cv2.captures[1].released)

    def test_partial_camera_release_failure_blocks_reuse_until_cleanup_succeeds(self):
        for operation in ("set", "isOpened"):
            with self.subTest(operation=operation):
                cv2 = FakeCV2([])
                adapter = SeeedIMX219OpenCVCameraAdapter(
                    "camera", "opencv", ("camera_frame_metadata",), True, cv2_module=cv2)
                manager = DeviceManager([adapter])
                with patch.object(FakeVideoCapture, "release",
                                  side_effect=OSError("camera release failed")) as release:
                    with patch.object(FakeVideoCapture, operation,
                                      side_effect=OSError("camera setup failed")):
                        with self.assertRaisesRegex(OSError, "camera release failed"):
                            adapter.initialize(OpenCVCameraConfig(0, 0, 1, frame_width=640))
                    self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
                    capture = cv2.captures[0]
                    for _ in range(2):
                        with self.assertRaisesRegex(OSError, "camera release failed"):
                            adapter.shutdown()
                        self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
                        self.assertFalse(adapter.get_status().shutdown)
                        self.assertFalse(manager.check_readiness().all_ready)
                        self.assertTrue(capture.isOpened())
                        self.assertFalse(capture.released)
                        with self.assertRaises(DeviceAdapterLifecycleError):
                            adapter.initialize(OpenCVCameraConfig(1, 0, 1))
                    self.assertEqual(release.call_count, 3)
                    self.assertEqual(len(cv2.captures), 1)
                with patch.object(capture, "release", wraps=capture.release) as release:
                    adapter.shutdown()
                    adapter.shutdown()
                    self.assertEqual(release.call_count, 1)
                self.assertTrue(capture.released)
                self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
                self.assertTrue(manager.check_readiness().all_ready)
                adapter.initialize(OpenCVCameraConfig(1, 0, 1))
                self.assertTrue(adapter.check_ready().ready)
                adapter.shutdown()
                self.assertTrue(cv2.captures[1].released)

    def test_camera_reopens_same_adapter_with_new_session_configuration(self):
        cv2 = FakeCV2([np.zeros((3, 4, 3), dtype=np.uint8)])
        adapter = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", ("camera_frame_metadata",), True, cv2_module=cv2)
        for source in (0, 1):
            self.assertTrue(adapter.check_ready().ready)
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
            self.assertFalse(adapter.get_status().ready)
            adapter.initialize({"camera_source": source, "api_preference": 0, "frames_per_collect": 1})
            self.assertTrue(adapter.check_ready().ready)
            adapter.start()
            self.assertEqual(len(adapter.collect_products((ScientificProductDeclaration("frames", "camera_frames",
                    {"frame_shape": [3, 4, 3], "frame_dtype": "uint8"}, "hdf5"),),
                    session_id="session", experiment_id="experiment", acquisition_node_id="node")["scientific_products"]["frames"]), 1)
            adapter.stop()
            adapter.shutdown()
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
            self.assertIsNone(adapter.initialization_config)
            self.assertTrue(cv2.captures[-1].released)
        self.assertEqual([capture.source for capture in cv2.captures], [0, 1])

    def test_failed_capture_release_remains_failed_until_shutdown_succeeds(self):
        for started in (False, True):
            with self.subTest(started=started):
                cv2 = FakeCV2([])
                adapter = SeeedIMX219OpenCVCameraAdapter(
                    "camera", "opencv", ("camera_frame_metadata",), True,
                    cv2_module=cv2,
                )
                adapter.initialize(OpenCVCameraConfig(0, 0, 1))
                self.assertTrue(adapter.check_ready().ready)
                if started:
                    adapter.start()
                    adapter.stop()
                capture = cv2.captures[0]
                with patch.object(capture, "release", side_effect=OSError("camera release failed")) as release:
                    for _ in range(2):
                        with self.assertRaisesRegex(OSError, "camera release failed"):
                            adapter.shutdown()
                        self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
                        self.assertFalse(adapter.get_status().shutdown)
                        self.assertTrue(capture.isOpened())
                        self.assertFalse(capture.released)
                    self.assertEqual(release.call_count, 2)
                with patch.object(capture, "release", wraps=capture.release) as release:
                    adapter.shutdown()
                    self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
                    self.assertTrue(adapter.get_status().shutdown)
                    self.assertTrue(capture.released)
                    self.assertFalse(capture.isOpened())
                    adapter.shutdown()
                    self.assertEqual(release.call_count, 1)

    def test_shutdown_rejects_running_camera_without_releasing_capture(self):
        cv2 = FakeCV2([])
        adapter = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frame_metadata",), True,
            cv2_module=cv2,
        )
        adapter.initialize(OpenCVCameraConfig(0, 0, 1))
        self.assertTrue(adapter.check_ready().ready)
        adapter.start()
        capture = cv2.captures[0]
        with self.assertRaises(DeviceAdapterLifecycleError):
            adapter.shutdown()
        self.assertTrue(capture.isOpened())
        self.assertFalse(capture.released)
        adapter.shutdown()
        self.assertTrue(capture.released)


if __name__ == "__main__":
    unittest.main()
