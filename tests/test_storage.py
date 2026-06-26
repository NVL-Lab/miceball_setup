import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope,
    InMemoryIngestor,
    PersistentStorageManager,
)


class PersistentStorageManagerTests(unittest.TestCase):
    def test_persistent_storage_writes_and_reads_accepted_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            records_path = Path(temporary_directory) / "accepted_records.jsonl"
            storage = PersistentStorageManager(records_path=records_path)
            ingestor = InMemoryIngestor(storage_manager=storage)
            envelope = AcquisitionRecordEnvelope(
                session_id="session-001",
                source_device_id="adapter-camera-001",
                record_kind="tiny_stream",
                records=[
                    {
                        "device_time_s": 100.0,
                        "session_time_s": 0.5,
                        "value": 10,
                    }
                ],
            )

            readiness = storage.check_ready()
            audit = ingestor.receive_envelope(envelope)
            read_back = storage.read_envelopes()

            self.assertEqual(storage.records_path, records_path)
            self.assertEqual(readiness.component_id, "storage")
            self.assertEqual(readiness.component_type, "storage_manager")
            self.assertTrue(readiness.required)
            self.assertTrue(readiness.ready)
            self.assertTrue(audit.accepted)
            self.assertEqual(len(ingestor.ingest_audit), 1)
            self.assertEqual(ingestor.accepted_envelopes, (envelope,))
            self.assertEqual(len(read_back), 1)
            self.assertEqual(read_back[0].session_id, "session-001")
            self.assertEqual(read_back[0].source_device_id, "adapter-camera-001")
            self.assertEqual(read_back[0].record_kind, "tiny_stream")
            self.assertEqual(
                read_back[0].records,
                (
                    {
                        "device_time_s": 100.0,
                        "session_time_s": 0.5,
                        "value": 10,
                    },
                ),
            )
            self.assertEqual(storage.stored_envelopes, read_back)
            self.assertEqual(
                storage.get_envelopes_for_session("session-001"),
                read_back,
            )
            self.assertEqual(
                storage.get_envelopes_for_source("adapter-camera-001"),
                read_back,
            )

            lines = records_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertNotIn("ingest_order", lines[0])
            self.assertNotIn("ingest_received_at", lines[0])


if __name__ == "__main__":
    unittest.main()
