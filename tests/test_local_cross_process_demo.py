import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import PersistentStorageManager


class LocalCrossProcessDemoTests(unittest.TestCase):
    def test_shell_to_shell_jsonl_handoff_demo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            demo_dir = Path(temporary_directory)
            handoff_path = demo_dir / "handoff.jsonl"
            accepted_records_path = demo_dir / "accepted_records.jsonl"
            writer_script = (
                ROOT / "scripts" / "demo_cross_process_acquisition_writer.py"
            )
            reader_script = (
                ROOT / "scripts" / "demo_cross_process_ingestor_reader.py"
            )

            writer = subprocess.run(
                [sys.executable, str(writer_script), str(handoff_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            reader = subprocess.run(
                [
                    sys.executable,
                    str(reader_script),
                    str(handoff_path),
                    str(accepted_records_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            storage = PersistentStorageManager(
                records_path=accepted_records_path
            )
            read_back = storage.read_envelopes()
            event_rows = [
                row
                for envelope in read_back
                if envelope.record_kind == "event"
                for row in envelope.records
            ]
            record_kinds = {
                envelope.record_kind
                for envelope in read_back
            }
            rows = [
                row
                for envelope in read_back
                for row in envelope.records
            ]

            self.assertTrue(handoff_path.exists())
            self.assertTrue(accepted_records_path.exists())
            self.assertIn("wrote_handoff_envelopes=4", writer.stdout)
            self.assertIn("handoff_envelopes_read=4", reader.stdout)
            self.assertIn("accepted_envelopes_stored=4", reader.stdout)
            self.assertIn("ingest_audit_records=4", reader.stdout)
            self.assertEqual(len(read_back), 4)
            self.assertEqual(
                {
                    row["event_type"]
                    for row in event_rows
                    if row.get("event_category") == "session_lifecycle"
                },
                {"session_start", "session_stop"},
            )
            self.assertIn("camera_stream", record_kinds)
            self.assertIn("lick_event", record_kinds)
            self.assertTrue(
                all("session_time_s" in row for row in rows)
            )


if __name__ == "__main__":
    unittest.main()
