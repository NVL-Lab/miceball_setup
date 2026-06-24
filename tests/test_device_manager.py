import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    DeviceAdapter,
    DeviceAdapterState,
    DeviceManager,
)
from tests.fakes import ReadyFakeAdapter


class FailingReadinessAdapter(DeviceAdapter):
    """Test-only adapter that fails readiness explicitly."""

    def check_ready(self):
        raise RuntimeError("readiness unavailable")


class FailingStartAdapter(ReadyFakeAdapter):
    """Test-only adapter that fails start explicitly."""

    def start(self) -> None:
        raise RuntimeError("start unavailable")


def fake_adapter(device_id: str, *, required: bool = True) -> ReadyFakeAdapter:
    return ReadyFakeAdapter(
        device_id=device_id,
        device_type="camera",
        declared_capabilities=["reports_health"],
        required=required,
    )


class DeviceManagerTests(unittest.TestCase):
    def test_manager_requires_at_least_one_adapter(self) -> None:
        with self.assertRaises(ValueError):
            DeviceManager(adapters=[])

    def test_manager_can_coordinate_an_already_created_adapter(self) -> None:
        adapter = fake_adapter("camera-001")

        manager = DeviceManager(adapters=[adapter])

        self.assertIs(manager.adapters[0], adapter)

    def test_manager_can_initialize_adapters(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        config = {"shared": "config"}

        results = manager.initialize_all(config=config)

        self.assertTrue(all(result.succeeded for result in results))
        self.assertEqual([result.operation for result in results], ["initialize", "initialize"])
        self.assertTrue(
            all(adapter.get_status().state is DeviceAdapterState.INITIALIZED for adapter in adapters)
        )
        self.assertTrue(all(adapter.initialization_config is config for adapter in adapters))

    def test_manager_passes_supplied_config_to_each_adapter(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        config = {"nested": {"threshold": 3}}

        manager.initialize_all(config=config)

        self.assertIs(adapters[0].initialization_config, config)
        self.assertIs(adapters[1].initialization_config, config)
        self.assertEqual(config, {"nested": {"threshold": 3}})

    def test_manager_can_check_and_aggregate_readiness(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        manager.initialize_all(config={})

        summary = manager.check_readiness()

        self.assertTrue(summary.all_ready)
        self.assertEqual([result.device_id for result in summary.results], ["camera-001", "camera-002"])
        self.assertTrue(all(result.ready for result in summary.results))
        self.assertTrue(all(adapter.get_status().ready for adapter in adapters))

    def test_manager_records_not_ready_results(self) -> None:
        adapter = DeviceAdapter(
            device_id="base-001",
            device_type="base",
            declared_capabilities=[],
            required=True,
        )
        manager = DeviceManager(adapters=[adapter])
        manager.initialize_all(config={})

        summary = manager.check_readiness()

        self.assertFalse(summary.all_ready)
        self.assertEqual(len(summary.results), 1)
        self.assertEqual(summary.results[0].device_id, "base-001")
        self.assertTrue(summary.results[0].required)
        self.assertFalse(summary.results[0].ready)
        self.assertEqual(summary.results[0].capabilities_available, ())

    def test_manager_continues_readiness_checks_after_failure(self) -> None:
        failing_adapter = FailingReadinessAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=[],
            required=True,
        )
        ready_adapter = fake_adapter("camera-002")
        manager = DeviceManager(adapters=[failing_adapter, ready_adapter])
        manager.initialize_all(config={})

        summary = manager.check_readiness()

        self.assertFalse(summary.all_ready)
        self.assertEqual([result.device_id for result in summary.results], ["camera-001", "camera-002"])
        self.assertTrue(summary.results[0].required)
        self.assertFalse(summary.results[0].ready)
        self.assertEqual(summary.results[0].reason, "readiness unavailable")
        self.assertEqual(summary.results[0].capabilities_available, ())
        self.assertTrue(summary.results[1].ready)
        self.assertIs(ready_adapter.get_status().state, DeviceAdapterState.READY)

    def test_manager_can_start_adapters(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        manager.initialize_all(config={})
        manager.check_readiness()

        results = manager.start_all()

        self.assertTrue(all(result.succeeded for result in results))
        self.assertTrue(
            all(adapter.get_status().state is DeviceAdapterState.RUNNING for adapter in adapters)
        )

    def test_manager_continues_lifecycle_operations_after_failure(self) -> None:
        failing_adapter = FailingStartAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=[],
            required=True,
        )
        running_adapter = fake_adapter("camera-002")
        manager = DeviceManager(adapters=[failing_adapter, running_adapter])
        manager.initialize_all(config={})
        manager.check_readiness()

        results = manager.start_all()

        self.assertEqual([result.device_id for result in results], ["camera-001", "camera-002"])
        self.assertFalse(results[0].succeeded)
        self.assertEqual(results[0].operation, "start")
        self.assertEqual(results[0].error, "start unavailable")
        self.assertTrue(results[1].succeeded)
        self.assertIs(running_adapter.get_status().state, DeviceAdapterState.RUNNING)

    def test_manager_can_stop_adapters(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        manager.initialize_all(config={})
        manager.check_readiness()
        manager.start_all()

        results = manager.stop_all()

        self.assertTrue(all(result.succeeded for result in results))
        self.assertTrue(
            all(adapter.get_status().state is DeviceAdapterState.STOPPED for adapter in adapters)
        )

    def test_manager_can_shut_down_adapters(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)
        manager.initialize_all(config={})
        manager.check_readiness()
        manager.start_all()
        manager.stop_all()

        results = manager.shutdown_all()

        self.assertTrue(all(result.succeeded for result in results))
        self.assertTrue(
            all(adapter.get_status().state is DeviceAdapterState.SHUTDOWN for adapter in adapters)
        )

    def test_manager_can_collect_status_summaries(self) -> None:
        adapters = [fake_adapter("camera-001"), fake_adapter("camera-002")]
        manager = DeviceManager(adapters=adapters)

        statuses = manager.collect_statuses()

        self.assertEqual([status.device_id for status in statuses], ["camera-001", "camera-002"])
        self.assertTrue(
            all(status.state is DeviceAdapterState.DECLARED for status in statuses)
        )

if __name__ == "__main__":
    unittest.main()
