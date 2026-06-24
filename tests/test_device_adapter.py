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
    )


class DeviceAdapterTests(unittest.TestCase):
    def test_fake_adapter_initializes(self) -> None:
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

    def test_fake_adapter_reports_readiness(self) -> None:
        adapter = fake_adapter()
        adapter.initialize(config={})

        readiness = adapter.check_ready()

        status = adapter.get_status()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason, "ready")
        self.assertIs(status.state, DeviceAdapterState.READY)
        self.assertTrue(status.ready)
        self.assertFalse(status.running)

    def test_direct_state_mutation_is_not_allowed(self) -> None:
        adapter = fake_adapter()

        with self.assertRaises(AttributeError):
            adapter.state = DeviceAdapterState.RUNNING
        with self.assertRaises(AttributeError):
            adapter.initialization_config = {}

        self.assertIs(adapter.get_status().state, DeviceAdapterState.DECLARED)

    def test_base_adapter_readiness_does_not_silently_pass(self) -> None:
        adapter = DeviceAdapter(
            device_id="base-001",
            device_type="base",
            declared_capabilities=[],
        )
        adapter.initialize(config={})

        with self.assertRaises(DeviceReadinessNotImplementedError):
            adapter.check_ready()

        status = adapter.get_status()
        self.assertIs(status.state, DeviceAdapterState.FAILED)
        self.assertTrue(status.failed)

    def test_fake_adapter_starts_stops_and_shuts_down_in_allowed_order(self) -> None:
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

    def test_invalid_lifecycle_order_fails(self) -> None:
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

    def test_status_reflects_declared_initialized_ready_running_stopped_failed(
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

    def test_no_data_acquisition_methods_are_introduced(self) -> None:
        forbidden_methods = [
            "read_sample",
            "read_frame",
            "emit_event",
            "write_file",
            "send_command",
            "trigger",
            "calibrate",
            "reconnect",
        ]

        for method_name in forbidden_methods:
            with self.subTest(method_name=method_name):
                self.assertFalse(hasattr(DeviceAdapter, method_name))


if __name__ == "__main__":
    unittest.main()
