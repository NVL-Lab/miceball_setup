import json
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

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceManager,
    InMemoryIngestor,
    PersistentStorageManager,
    ServiceReadiness,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class RemoteRecordFakeAdapter(ReadyFakeAdapter):
    def collect_records(self):
        return {
            "record_kind": "remote_fake_stream",
            "records": ({"sample_index": 0, "value": 10},),
        }


class RemoteAcquisitionNodeTests(unittest.TestCase):
    def test_phase2_caller_does_not_start_when_required_service_is_not_ready(
        self,
    ) -> None:
        adapter = RemoteRecordFakeAdapter(
            "remote-device-001",
            "remote_fake_device",
            ["remote_fake_stream"],
            True,
        )
        manager = DeviceManager(adapters=(adapter,))
        manager.initialize_all(config={})
        node = AcquisitionNode(
            session_id="remote-session-001",
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(),
            node_id="jetson-like-001",
            role="acquisition_node",
            error_evidence_location=tempfile.gettempdir(),
        )
        storage_not_ready = ServiceReadiness(
            component_id="node_storage",
            component_type="local_storage",
            required=True,
            ready=False,
            reason="path_unavailable",
        )

        readiness = node.check_node_readiness(
            additional_service_readiness=(storage_not_ready,)
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.node_id, "jetson-like-001")
        self.assertEqual(readiness.session_id, "remote-session-001")
        self.assertEqual(readiness.role, "acquisition_node")
        self.assertEqual(readiness.device_readiness.results[0].device_id, "remote-device-001")
        self.assertIn(storage_not_ready, readiness.service_readiness)

        started = False
        if readiness.ready:
            node.start_acquisition()
            started = True

        self.assertFalse(started)
        self.assertFalse(node.status()["is_running"])

        manager.start_all()
        manager.stop_all()
        manager.shutdown_all()

    def test_simulated_remote_node_sends_identified_envelopes_to_computer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            accepted_path = root / "accepted_records.jsonl"
            failure_path = root / "sender_failures.jsonl"
            host = "127.0.0.1"
            port = self._available_local_port(host)
            receiver = self._start_receiver(host, port, accepted_path)
            receiver_lines = self._wait_until_listening(receiver)

            try:
                sender = subprocess.run(
                    self._sender_command(host, port, failure_path),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                receiver_stdout, receiver_stderr = receiver.communicate(timeout=10)
            finally:
                if receiver.poll() is None:
                    receiver.kill()
                    receiver.communicate(timeout=10)

            receiver_output = "".join(receiver_lines) + receiver_stdout
            envelopes = PersistentStorageManager(accepted_path).read_envelopes()
            stream_rows = [
                row
                for envelope in envelopes
                if envelope.record_kind == "remote_fake_stream"
                for row in envelope.records
            ]

            self.assertEqual(sender.returncode, 0, sender.stderr)
            self.assertEqual(receiver.returncode, 0, receiver_stderr)
            self.assertIn("envelopes_sent=3", sender.stdout)
            self.assertIn("cleanup_completed=True", sender.stdout)
            self.assertIn("envelopes_received=3", receiver_output)
            self.assertIn("ingest_audit_records=3", receiver_output)
            self.assertEqual(len(envelopes), 3)
            self.assertTrue(
                all(envelope.source_node_id == "jetson-like-001" for envelope in envelopes)
            )
            self.assertTrue(
                all(envelope.session_id == "remote-session-001" for envelope in envelopes)
            )
            self.assertTrue(all("session_time_s" in row for row in stream_rows))
            self.assertFalse(failure_path.read_text(encoding="utf-8").strip())

    def test_connection_failure_is_recorded_locally_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            failure_path = Path(temporary_directory) / "sender_failures.jsonl"
            host = "127.0.0.1"
            unavailable_port = self._available_local_port(host)

            sender = subprocess.run(
                self._sender_command(host, unavailable_port, failure_path),
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )

            evidence_lines = failure_path.read_text(encoding="utf-8").splitlines()
            evidence = json.loads(evidence_lines[0])
            self.assertNotEqual(sender.returncode, 0)
            self.assertEqual(len(evidence_lines), 1)
            self.assertEqual(evidence["evidence_kind"], "remote_acquisition_failure")
            self.assertEqual(evidence["node_id"], "jetson-like-001")
            self.assertEqual(evidence["session_id"], "remote-session-001")
            self.assertEqual(evidence["role"], "acquisition_node")
            self.assertTrue(evidence["cleanup"]["completed"])
            self.assertIn("remote_acquisition_failure", sender.stderr)

    def _sender_command(
        self,
        host: str,
        port: int,
        failure_path: Path,
    ) -> list[str]:
        return [
            sys.executable,
            str(ROOT / "scripts" / "demo_remote_acquisition_node_sender.py"),
            host,
            str(port),
            "--node-id",
            "jetson-like-001",
            "--session-id",
            "remote-session-001",
            "--role",
            "acquisition_node",
            "--failure-evidence-path",
            str(failure_path),
        ]

    def _start_receiver(
        self,
        host: str,
        port: int,
        accepted_path: Path,
    ) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts" / "demo_socket_ingestor_receiver.py"),
                host,
                str(port),
                str(accepted_path),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _wait_until_listening(self, receiver: subprocess.Popen) -> list[str]:
        lines = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            line = receiver.stdout.readline()
            if line:
                lines.append(line)
                if line.startswith("listening="):
                    return lines
            elif receiver.poll() is not None:
                break
        self.fail("receiver did not report that it was listening")

    def _available_local_port(self, host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
            return probe.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
