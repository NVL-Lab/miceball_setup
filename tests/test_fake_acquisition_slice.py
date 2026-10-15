"""Historical intake validation; node collection now uses explicit products."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import AcquisitionRecordEnvelope, InMemoryIngestor, InMemoryStorageManager


class FakeAcquisitionSliceTests(unittest.TestCase):
    def test_ingestor_rejects_envelope_without_session_time(self):
        storage = InMemoryStorageManager()
        ingestor = InMemoryIngestor(storage_manager=storage)
        envelope = AcquisitionRecordEnvelope(
            session_id="session-001", source_device_id="adapter-camera-001",
            record_kind="tiny_stream", records=[{"value": 10}])
        audit = ingestor.receive_envelope(envelope)
        self.assertFalse(audit.accepted)
        self.assertEqual(audit.reason, "missing_session_time")
        self.assertEqual(audit.ingest_order, 1)
        self.assertEqual(len(ingestor.ingest_audit), 1)
        self.assertEqual(ingestor.accepted_envelopes, ())
        self.assertEqual(storage.stored_envelopes, ())


if __name__ == "__main__":
    unittest.main()
