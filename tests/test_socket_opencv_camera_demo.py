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


class SocketOpenCVCameraDemoTests(unittest.TestCase):
    def test_opencv_camera_adapter_metadata_crosses_live_socket_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            demo_dir = Path(temporary_directory)
            accepted_records_path = demo_dir / "accepted_records.jsonl"
            receiver_script = ROOT / "scripts" / "demo_socket_ingestor_receiver.py"
            sender_script = ROOT / "scripts" / "demo_socket_opencv_camera_sender.py"
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
            camera_envelopes = [
                envelope
                for envelope in read_back
                if envelope.record_kind == "camera_frame_metadata"
            ]
            camera_rows = [
                row
                for envelope in camera_envelopes
                for row in envelope.records
            ]

            self.assertEqual(receiver.returncode, 0, receiver_stderr)
            self.assertTrue(accepted_records_path.exists())
            self.assertIn(f"target={host}:{port}", sender.stdout)
            self.assertIn("envelopes_sent=3", sender.stdout)
            self.assertIn("camera_metadata_records_sent=2", sender.stdout)
            self.assertIn("envelopes_received=3", receiver_output)
            self.assertIn("accepted_envelopes_stored=3", receiver_output)
            self.assertIn("ingest_audit_records=3", receiver_output)
            self.assertEqual(len(read_back), 3)
            self.assertEqual(len(camera_envelopes), 1)
            self.assertEqual(len(camera_rows), 2)
            self.assertEqual(
                {
                    row["event_type"]
                    for row in event_rows
                    if row.get("event_category") == "session_lifecycle"
                },
                {"session_start", "session_stop"},
            )
            self.assertTrue(all("frame_index" in row for row in camera_rows))
            self.assertTrue(all("width" in row for row in camera_rows))
            self.assertTrue(all("height" in row for row in camera_rows))
            self.assertTrue(all("channels" in row for row in camera_rows))
            self.assertTrue(all("dtype" in row for row in camera_rows))
            self.assertTrue(all("session_time_s" in row for row in camera_rows))
            self.assertEqual([row["frame_index"] for row in camera_rows], [0, 1])
            self.assertTrue(all(row["width"] == 640 for row in camera_rows))
            self.assertTrue(all(row["height"] == 480 for row in camera_rows))
            self.assertTrue(all(row["channels"] == 3 for row in camera_rows))
            self.assertTrue(all(row["dtype"] == "uint8" for row in camera_rows))
            self.assertTrue(all("image" not in row for row in camera_rows))
            self.assertTrue(all("frame" not in row for row in camera_rows))
            self.assertTrue(all("bytes" not in row for row in camera_rows))

    def _available_local_port(self, host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
            return probe.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
