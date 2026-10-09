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
from tests.fakes import ReadyFakeAdapter


def fake_adapter() -> ReadyFakeAdapter:
    return ReadyFakeAdapter(
        device_id="camera-001",
        device_type="camera",
        declared_capabilities=["reports_health"],
        required=True,
    )


class ResourceAdapter(ReadyFakeAdapter):
    def __init__(self):
        super().__init__("resource", "simulated", ("records",), True)
        self.cleanup_fails = False
        self.cleanup_attempts = 0
        self.cleanup_states = []

    def _shutdown_resources(self):
        self.cleanup_attempts += 1
        self.cleanup_states.append(self.state)
        if self.cleanup_fails:
            raise OSError("resource cleanup failed")


class DeviceAdapterTests(unittest.TestCase):
    def test_retained_adapter_reuses_declared_lifecycle_with_independent_configuration(self):
        adapter = ResourceAdapter()
        for config in ({"rate": 1}, {"rate": 2}):
            self.assertTrue(adapter.check_ready().ready)
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
            self.assertFalse(adapter.get_status().ready)
            adapter.initialize(config)
            self.assertEqual(adapter.initialization_config, config)
            self.assertFalse(adapter.get_status().shutdown)
            adapter.check_ready()
            adapter.start()
            adapter.stop()
            adapter.shutdown()
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
            self.assertIsNone(adapter.initialization_config)
            self.assertTrue(adapter.get_status().shutdown)
            adapter.shutdown()
        self.assertEqual(adapter.cleanup_attempts, 2)
        self.assertEqual(adapter.cleanup_states, [DeviceAdapterState.STOPPED] * 2)

    def test_failed_device_cleanup_blocks_reinitialization_until_cleanup_succeeds(self):
        adapter = ResourceAdapter()
        adapter.initialize({"rate": 1})
        adapter.cleanup_fails = True
        for _ in range(2):
            with self.assertRaisesRegex(OSError, "resource cleanup failed"):
                adapter.shutdown()
            self.assertEqual(adapter.state, DeviceAdapterState.FAILED)
            self.assertFalse(adapter.get_status().shutdown)
            with self.assertRaises(DeviceAdapterLifecycleError):
                adapter.initialize({"rate": 2})
        self.assertEqual(adapter.cleanup_attempts, 2)
        adapter.cleanup_fails = False
        adapter.shutdown()
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
        adapter.initialize({"rate": 2})
        self.assertEqual(adapter.initialization_config, {"rate": 2})

    def test_declared_readiness_does_not_authorize_acquisition_or_repeated_initialization(self):
        adapter = fake_adapter()
        self.assertTrue(adapter.check_ready().ready)
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
        with self.assertRaises(DeviceAdapterLifecycleError):
            adapter.start()
        other = fake_adapter()
        other.initialize({})
        with self.assertRaises(DeviceAdapterLifecycleError):
            other.initialize({})

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
        self.assertIs(shutdown_status.state, DeviceAdapterState.DECLARED)
        self.assertTrue(shutdown_status.shutdown)
        self.assertFalse(shutdown_status.stopped)

    def test_adapter_rejects_invalid_lifecycle_order(self) -> None:
        cases = [
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
