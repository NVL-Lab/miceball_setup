import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceDeclaration,
    DeviceManager,
    DeviceAdapterState,
    InMemoryIngestor,
    OpenCVCameraConfig,
    PersistentStorageManager,
    SeeedIMX219OpenCVCameraAdapter,
    Session,
    SessionConfig,
    SessionState,
    SynchronizationManager,
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
    def test_camera_metadata_flows_through_acquisition_and_persistent_storage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_cv2 = FakeCV2(
                frames=[
                    FakeFrame(shape=(480, 640, 3), dtype="uint8"),
                    FakeFrame(shape=(480, 640, 3), dtype="uint8"),
                ]
            )
            declaration = DeviceDeclaration(
                device_id="seeed-imx219-001",
                device_type="seeed_imx219_camera",
                enabled=True,
                required=True,
                declared_capabilities=["camera_frame_metadata"],
            )
            configuration = SessionConfig(
                session_id="session-camera-001",
                selected_devices=[declaration],
                storage_location=str(temporary_directory),
                protocol_plan={"name": "camera-metadata-only"},
                device_configurations={
                    "seeed-imx219-001": {
                        "camera_source": 0,
                        "api_preference": FakeCV2.CAP_V4L2,
                        "frames_per_collect": 2,
                    }
                },
            )
            session = Session(
                session_id="session-camera-001",
                configuration=configuration,
            )
            camera_config = OpenCVCameraConfig(
                camera_source=0,
                api_preference=FakeCV2.CAP_V4L2,
                frames_per_collect=2,
                frame_width=640,
                frame_height=480,
                fps=30.0,
            )
            adapter = SeeedIMX219OpenCVCameraAdapter(
                device_id="seeed-imx219-001",
                device_type="seeed_imx219_camera",
                declared_capabilities=["camera_frame_metadata"],
                required=True,
                cv2_module=fake_cv2,
            )
            manager = DeviceManager(adapters=[adapter])
            synchronization = SynchronizationManager()
            records_path = Path(temporary_directory) / "accepted_records.jsonl"
            storage = PersistentStorageManager(records_path=records_path)
            ingestor = InMemoryIngestor(storage_manager=storage)
            acquisition_node = AcquisitionNode(
                session_id=session.session_id,
                device_manager=manager,
                synchronization_manager=synchronization,
                ingestor=ingestor,
            )

            manager.initialize_all(config=camera_config)
            acquisition_readiness = acquisition_node.check_ready()
            session.initialize(
                device_readiness_summary=acquisition_readiness["device_readiness"],
                service_readiness=(
                    *acquisition_readiness["service_readiness"],
                    storage.check_ready(),
                ),
            )
            session.start()
            acquisition_node.start_acquisition()
            iteration = acquisition_node.run_one_iteration()
            stop_result = acquisition_node.stop_acquisition()
            session.stop(reason="camera metadata acquired")
            session.complete(reason="camera metadata acquired")

            stored_envelopes = storage.read_envelopes()
            camera_envelopes = [
                envelope
                for envelope in stored_envelopes
                if envelope.source_device_id == "seeed-imx219-001"
            ]
            camera_rows = [
                row
                for envelope in camera_envelopes
                for row in envelope.records
            ]
            capture = fake_cv2.captures[0]
            final_status = manager.collect_statuses()[0]

            self.assertIs(session.current_state, SessionState.COMPLETED)
            self.assertEqual(iteration.collections_seen, 1)
            self.assertEqual(iteration.envelopes_sent, 1)
            self.assertEqual(iteration.accepted_count, 1)
            self.assertEqual(iteration.rejected_count, 0)
            self.assertEqual(stop_result["device_shutdown_results"][0].succeeded, True)
            self.assertEqual(len(camera_envelopes), 1)
            self.assertEqual(camera_envelopes[0].record_kind, "camera_frame_metadata")
            self.assertEqual(len(camera_rows), 2)
            self.assertEqual([row["frame_index"] for row in camera_rows], [0, 1])
            self.assertTrue(all(row["width"] == 640 for row in camera_rows))
            self.assertTrue(all(row["height"] == 480 for row in camera_rows))
            self.assertTrue(all(row["channels"] == 3 for row in camera_rows))
            self.assertTrue(all(row["dtype"] == "uint8" for row in camera_rows))
            self.assertTrue(all(row["read_success"] is True for row in camera_rows))
            self.assertTrue(all(row["backend"] == "FAKE_OPENCV" for row in camera_rows))
            self.assertTrue(
                all(row["device_local_time"] == 123.456 for row in camera_rows)
            )
            self.assertTrue(all("session_time_s" in row for row in camera_rows))
            self.assertTrue(all("image" not in row for row in camera_rows))
            self.assertTrue(all("frame" not in row for row in camera_rows))
            self.assertTrue(all("bytes" not in row for row in camera_rows))
            self.assertEqual(
                capture.properties_set,
                [
                    (FakeCV2.CAP_PROP_FRAME_WIDTH, 640),
                    (FakeCV2.CAP_PROP_FRAME_HEIGHT, 480),
                    (FakeCV2.CAP_PROP_FPS, 30.0),
                ],
            )
            self.assertTrue(capture.released)
            self.assertIs(final_status.state, DeviceAdapterState.SHUTDOWN)
            self.assertFalse(final_status.failed)
            self.assertTrue(final_status.shutdown)


if __name__ == "__main__":
    unittest.main()
