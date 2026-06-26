import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope,
    DeviceAdapterState,
    DeviceDeclaration,
    DeviceManager,
    InMemoryIngestor,
    InMemoryStorageManager,
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
    def test_fake_records_cross_plain_data_envelope_boundary(self) -> None:
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
        storage = InMemoryStorageManager()
        ingestor = InMemoryIngestor(storage_manager=storage)

        manager.initialize_all(config={"mode": "fake"})
        manager_readiness = manager.check_readiness()
        ingestor_ready = ingestor.check_ready()
        storage_ready = storage.check_ready()
        session.initialize(
            device_readiness_summary=manager_readiness,
            service_readiness=[ingestor_ready, storage_ready],
        )
        session.start()
        manager.start_all()
        record_collections = manager.collect_records("produce_tiny_stream")
        rows = record_collections[0].records
        envelope = AcquisitionRecordEnvelope(
            session_id=session.session_id,
            source_device_id=record_collections[0].device_id,
            record_kind="tiny_stream",
            records=rows,
        )
        envelope_data = envelope.to_dict()
        reconstructed_envelope = AcquisitionRecordEnvelope.from_dict(envelope_data)
        audit = ingestor.receive_envelope(reconstructed_envelope)
        session.stop(reason="fake acquisition complete")
        session.complete(reason="fake acquisition complete")
        manager.stop_all()
        manager.shutdown_all()
        status = manager.collect_statuses()
        accepted_envelope = ingestor.accepted_envelopes[0]
        stored_envelope = storage.stored_envelopes[0]
        session_envelopes = storage.get_envelopes_for_session("session-001")
        source_envelopes = storage.get_envelopes_for_source("adapter-camera-001")

        self.assertEqual(len(record_collections), 1)
        self.assertEqual(record_collections[0].device_id, "adapter-camera-001")
        self.assertEqual(session.device_readiness_summary, manager_readiness.results)
        self.assertEqual(
            session.service_readiness_checks,
            (ingestor_ready, storage_ready),
        )
        self.assertEqual(ingestor_ready.component_id, "ingestor")
        self.assertEqual(storage_ready.component_id, "storage")
        self.assertEqual(
            set(envelope_data),
            {"session_id", "source_device_id", "record_kind", "records"},
        )
        self.assertEqual(envelope_data["session_id"], "session-001")
        self.assertEqual(envelope_data["source_device_id"], "adapter-camera-001")
        self.assertEqual(envelope_data["record_kind"], "tiny_stream")
        self.assertIsInstance(envelope_data["records"], list)
        self.assertTrue(audit.accepted)
        self.assertEqual(audit.reason, "accepted")
        self.assertEqual(audit.ingest_order, 1)
        self.assertEqual(len(ingestor.ingest_audit), 1)
        self.assertEqual(ingestor.ingest_audit[0], audit)
        self.assertEqual(len(ingestor.accepted_envelopes), 1)
        self.assertEqual(accepted_envelope.source_device_id, "adapter-camera-001")
        self.assertEqual(len(storage.stored_envelopes), 1)
        self.assertEqual(stored_envelope.source_device_id, "adapter-camera-001")
        self.assertEqual(stored_envelope.session_id, "session-001")
        self.assertEqual(stored_envelope.record_kind, "tiny_stream")
        self.assertEqual(session_envelopes, (stored_envelope,))
        self.assertEqual(source_envelopes, (stored_envelope,))
        self.assertEqual(storage.get_envelopes_for_session("other-session"), ())
        self.assertEqual(storage.get_envelopes_for_source("other-source"), ())
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(reconstructed_envelope.records), 3)
        self.assertEqual(len(accepted_envelope.records), 3)
        self.assertEqual(len(stored_envelope.records), 3)
        self.assertTrue(all("session_time" in row for row in stored_envelope.records))
        self.assertTrue(
            all(
                reconstructed_row is manager_row
                for reconstructed_row, manager_row in zip(
                    reconstructed_envelope.records,
                    rows,
                )
            )
        )
        self.assertTrue(
            all(
                accepted_row is reconstructed_row
                for accepted_row, reconstructed_row in zip(
                    accepted_envelope.records,
                    reconstructed_envelope.records,
                )
            )
        )
        self.assertTrue(
            all(
                stored_row is accepted_row
                for stored_row, accepted_row in zip(
                    stored_envelope.records,
                    accepted_envelope.records,
                )
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

    def test_ingestor_rejects_envelope_without_session_time(self) -> None:
        storage = InMemoryStorageManager()
        ingestor = InMemoryIngestor(storage_manager=storage)
        envelope = AcquisitionRecordEnvelope(
            session_id="session-001",
            source_device_id="adapter-camera-001",
            record_kind="tiny_stream",
            records=[{"value": 10}],
        )

        audit = ingestor.receive_envelope(envelope)

        self.assertFalse(audit.accepted)
        self.assertEqual(audit.reason, "missing_session_time")
        self.assertEqual(audit.ingest_order, 1)
        self.assertEqual(len(ingestor.ingest_audit), 1)
        self.assertEqual(ingestor.accepted_envelopes, ())
        self.assertEqual(storage.stored_envelopes, ())


if __name__ == "__main__":
    unittest.main()
