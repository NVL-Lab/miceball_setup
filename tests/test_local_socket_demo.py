import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import PersistentStorageManager


class LocalSocketDemoTests(unittest.TestCase):
    def test_live_localhost_socket_demo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            demo_dir = Path(temporary_directory)
            accepted_records_path = demo_dir / "accepted_records.jsonl"
            receiver_script = (
                ROOT / "scripts" / "demo_socket_ingestor_receiver.py"
            )
            sender_script = ROOT / "scripts" / "demo_socket_acquisition_sender.py"
            host = "127.0.0.1"
            port = self._available_local_port(host)

            receiver = subprocess.Popen(
                [
                    sys.executable,
                    str(receiver_script),
                    host,
                    str(port),
                    str(accepted_records_path),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            receiver_lines = []
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    line = receiver.stdout.readline()
                    if line:
                        receiver_lines.append(line)
                        if line.startswith("listening="):
                            break
                    elif receiver.poll() is not None:
                        break
                self.assertTrue(
                    any(line.startswith("listening=") for line in receiver_lines),
                    "receiver did not report that it was listening",
                )

                sender = subprocess.run(
                    [
                        sys.executable,
                        str(sender_script),
                        host,
                        str(port),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                receiver_stdout, receiver_stderr = receiver.communicate(timeout=10)
            finally:
                if receiver.poll() is None:
                    receiver.kill()
                    receiver.communicate(timeout=10)

            receiver_output = "".join(receiver_lines) + receiver_stdout
            storage = PersistentStorageManager(records_path=accepted_records_path)
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

            self.assertEqual(receiver.returncode, 0, receiver_stderr)
            self.assertTrue(accepted_records_path.exists())
            self.assertIn("envelopes_sent=4", sender.stdout)
            self.assertIn("envelopes_received=4", receiver_output)
            self.assertIn("accepted_envelopes_stored=4", receiver_output)
            self.assertIn("ingest_audit_records=4", receiver_output)
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

    def _available_local_port(self, host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
            return probe.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
