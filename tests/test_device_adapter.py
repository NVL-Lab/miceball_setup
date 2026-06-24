import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    DeviceAdapter,
    DeviceAdapterLifecycleError,
    DeviceAdapterState,
    DeviceReadinessNotImplementedError,
)


class FakeDeviceAdapter(DeviceAdapter):
    """Test-only adapter for exercising the minimum lifecycle interface."""

    def check_ready(self):
        return self._mark_ready()


def fake_adapter() -> FakeDeviceAdapter:
    return FakeDeviceAdapter(
        device_id="camera-001",
        device_type="camera",
        declared_capabilities=["reports_health"],
        required=True,
    )


class DeviceAdapterTests(unittest.TestCase):
    def test_adapter_can_be_initialized(self) -> None:
        adapter = fake_adapter()

        adapter.initialize(config={"exposure_ms": 10})

        status = adapter.get_status()
        self.assertIs(status.state, DeviceAdapterState.INITIALIZED)
        self.assertTrue(status.initialized)
        self.assertFalse(status.ready)
        self.assertFalse(status.running)
        self.assertFalse(status.stopped)
        self.assertFalse(status.failed)
        self.assertEqual(status.device_id, "camera-001")
        self.assertEqual(status.device_type, "camera")
        self.assertEqual(status.declared_capabilities, ("reports_health",))

    def test_adapter_can_report_readiness(self) -> None:
        adapter = fake_adapter()
        adapter.initialize(config={})

        readiness = adapter.check_ready()

        status = adapter.get_status()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason, "ready")
        self.assertIs(status.state, DeviceAdapterState.READY)
        self.assertTrue(status.ready)
        self.assertFalse(status.running)

    def test_adapter_runtime_state_is_read_only(self) -> None:
        adapter = fake_adapter()

        with self.assertRaises(AttributeError):
            adapter.state = DeviceAdapterState.RUNNING
        with self.assertRaises(AttributeError):
            adapter.initialization_config = {}

        self.assertIs(adapter.get_status().state, DeviceAdapterState.DECLARED)

    def test_base_adapter_requires_concrete_readiness(self) -> None:
        adapter = DeviceAdapter(
            device_id="base-001",
            device_type="base",
            declared_capabilities=[],
            required=True,
        )
        adapter.initialize(config={})

        with self.assertRaises(DeviceReadinessNotImplementedError):
            adapter.check_ready()

        status = adapter.get_status()
        self.assertIs(status.state, DeviceAdapterState.FAILED)
        self.assertTrue(status.failed)

    def test_adapter_can_start_stop_and_shutdown(self) -> None:
        adapter = fake_adapter()

        adapter.initialize(config={})
        adapter.check_ready()
        adapter.start()

        running_status = adapter.get_status()
        self.assertIs(running_status.state, DeviceAdapterState.RUNNING)
        self.assertTrue(running_status.running)

        adapter.stop()
        stopped_status = adapter.get_status()
        self.assertIs(stopped_status.state, DeviceAdapterState.STOPPED)
        self.assertTrue(stopped_status.stopped)
        self.assertFalse(stopped_status.running)

        adapter.shutdown()
        shutdown_status = adapter.get_status()
        self.assertIs(shutdown_status.state, DeviceAdapterState.SHUTDOWN)
        self.assertTrue(shutdown_status.shutdown)
        self.assertTrue(shutdown_status.stopped)

    def test_adapter_rejects_invalid_lifecycle_order(self) -> None:
        cases = [
            ("check_ready_before_initialize", lambda adapter: adapter.check_ready()),
            ("start_before_ready", lambda adapter: adapter.start()),
            ("stop_before_start", lambda adapter: adapter.stop()),
            ("shutdown_before_stop", lambda adapter: adapter.shutdown()),
        ]

        for name, operation in cases:
            with self.subTest(name=name):
                adapter = fake_adapter()

                with self.assertRaises(DeviceAdapterLifecycleError):
                    operation(adapter)

                status = adapter.get_status()
                self.assertIs(status.state, DeviceAdapterState.FAILED)
                self.assertTrue(status.failed)

    def test_adapter_status_tracks_lifecycle_progress(
        self,
    ) -> None:
        adapter = fake_adapter()
        self.assertIs(adapter.get_status().state, DeviceAdapterState.DECLARED)

        adapter.initialize(config={})
        self.assertIs(adapter.get_status().state, DeviceAdapterState.INITIALIZED)

        adapter.check_ready()
        self.assertIs(adapter.get_status().state, DeviceAdapterState.READY)

        adapter.start()
        self.assertIs(adapter.get_status().state, DeviceAdapterState.RUNNING)

        adapter.stop()
        self.assertIs(adapter.get_status().state, DeviceAdapterState.STOPPED)

        failed_adapter = fake_adapter()
        with self.assertRaises(DeviceAdapterLifecycleError):
            failed_adapter.start()
        self.assertIs(failed_adapter.get_status().state, DeviceAdapterState.FAILED)

if __name__ == "__main__":
    unittest.main()
