import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    DeviceAdapterState,
    DeviceDeclaration,
    DeviceManager,
    Session,
    SessionConfig,
    SessionState,
)
from tests.fakes import ReadyFakeAdapter


class FakeEndToEndLifecycleTests(unittest.TestCase):
    def test_manual_declaration_to_adapter_bridge_can_complete_fake_lifecycle(
        self,
    ) -> None:
        declarations = [
            DeviceDeclaration(
                device_id="declared-camera-001",
                device_type="camera",
                enabled=True,
                required=True,
                declared_capabilities=["reports_health"],
            ),
            DeviceDeclaration(
                device_id="declared-encoder-001",
                device_type="encoder",
                enabled=True,
                required=True,
                declared_capabilities=["reports_health"],
            ),
        ]
        configuration = SessionConfig(
            selected_devices=declarations,
            storage_location="placeholder://session",
            protocol_plan={"name": "no-op"},
            error_evidence_location="placeholder://errors",
        )
        session = Session(
            session_id="session-001",
            configuration=configuration,
        )
        adapters = [
            ReadyFakeAdapter(
                device_id="adapter-camera-001",
                device_type="camera",
                declared_capabilities=["reports_health"],
                required=True,
            ),
            ReadyFakeAdapter(
                device_id="adapter-encoder-001",
                device_type="encoder",
                declared_capabilities=["reports_health"],
                required=True,
            ),
        ]
        manager = DeviceManager(adapters=adapters)

        manager.initialize_all(config={"mode": "fake"})
        readiness = manager.check_readiness()
        session.initialize(device_readiness_summary=readiness)
        session.start()
        manager.start_all()
        manager.stop_all()
        session.stop(reason="fake lifecycle complete")
        session.complete(reason="fake lifecycle complete")
        manager.shutdown_all()
        status = manager.collect_statuses()

        self.assertIs(session.current_state, SessionState.COMPLETED)
        self.assertEqual(
            session.device_readiness_summary,
            readiness.results,
        )
        self.assertTrue(
            all(
                adapter_status.state is DeviceAdapterState.SHUTDOWN
                for adapter_status in status
            )
        )
        self.assertTrue(all(not adapter_status.failed for adapter_status in status))
        self.assertTrue(all(adapter_status.shutdown for adapter_status in status))
        self.assertEqual(
            [declaration.device_id for declaration in declarations],
            ["declared-camera-001", "declared-encoder-001"],
        )
        self.assertEqual(
            [readiness_record.device_id for readiness_record in readiness],
            ["adapter-camera-001", "adapter-encoder-001"],
        )


if __name__ == "__main__":
    unittest.main()


