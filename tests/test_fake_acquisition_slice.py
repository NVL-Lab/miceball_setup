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
    InMemoryIngestor,
    Session,
    SessionConfig,
    SessionState,
)
from tests.fakes import ReadyFakeAdapter


class TinyStreamFakeAdapter(ReadyFakeAdapter):
    """Test-only adapter that produces a tiny in-memory stream."""

    def produce_tiny_stream(self):
        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("Tiny stream requires a running fake adapter")

        return [
            {"session_time": 0.0, "value": 10},
            {"session_time": 0.1, "value": 11},
            {"session_time": 0.2, "value": 12},
        ]


class FakeAcquisitionSliceTests(unittest.TestCase):
    def test_fake_records_cross_manager_and_ingestor_boundaries(self) -> None:
        declaration = DeviceDeclaration(
            device_id="declared-camera-001",
            device_type="camera",
            enabled=True,
            required=True,
            declared_capabilities=["tiny_stream"],
        )
        configuration = SessionConfig(
            selected_devices=[declaration],
            storage_location="placeholder://session",
            protocol_plan={"name": "no-op"},
        )
        session = Session(session_id="session-001", configuration=configuration)
        adapter = TinyStreamFakeAdapter(
            device_id="adapter-camera-001",
            device_type="camera",
            declared_capabilities=["tiny_stream"],
            required=True,
        )
        manager = DeviceManager(adapters=[adapter])
        ingestor = InMemoryIngestor()

        manager.initialize_all(config={"mode": "fake"})
        readiness = manager.check_readiness()
        session.initialize(device_readiness_summary=readiness)
        session.start()
        manager.start_all()
        record_collections = manager.collect_records("produce_tiny_stream")
        rows = record_collections[0].records
        ingestor.receive_records(record_collections)
        session.stop(reason="fake acquisition complete")
        session.complete(reason="fake acquisition complete")
        manager.stop_all()
        manager.shutdown_all()
        status = manager.collect_statuses()
        received_collection = ingestor.received_records[0]

        self.assertEqual(len(record_collections), 1)
        self.assertEqual(record_collections[0].device_id, "adapter-camera-001")
        self.assertEqual(len(ingestor.received_records), 1)
        self.assertEqual(received_collection.device_id, "adapter-camera-001")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(received_collection.records), 3)
        self.assertTrue(all("session_time" in row for row in received_collection.records))
        self.assertTrue(
            all(
                received_row is manager_row
                for received_row, manager_row in zip(received_collection.records, rows)
            )
        )
        self.assertIs(session.current_state, SessionState.COMPLETED)
        self.assertTrue(
            all(
                adapter_status.state is DeviceAdapterState.SHUTDOWN
                for adapter_status in status
            )
        )
        self.assertTrue(all(not adapter_status.failed for adapter_status in status))
        self.assertTrue(all(adapter_status.shutdown for adapter_status in status))


if __name__ == "__main__":
    unittest.main()
