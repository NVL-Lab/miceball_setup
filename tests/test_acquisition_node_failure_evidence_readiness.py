import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceManager,
    InMemoryIngestor,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class CountingRecordAdapter(ReadyFakeAdapter):
    def __init__(self):
        super().__init__("readiness-device-001", "fake_device", ("stream",), True)
        self.collect_count = 0

    def collect_records(self):
        self.collect_count += 1
        return {"record_kind": "stream", "records": ()}


class AcquisitionNodeFailureEvidenceReadinessTests(unittest.TestCase):
    def test_acquisition_starts_with_writable_failure_evidence_location(self):
        with tempfile.TemporaryDirectory() as directory:
            node, adapter = self._initialized_node(directory)

            readiness = node.check_ready()
            start_result = node.start_runtime()

            failure_evidence = next(
                item
                for item in readiness["service_readiness"]
                if item.component_id == "failure_evidence"
            )
            self.assertTrue(readiness["ready"])
            self.assertTrue(failure_evidence.ready)
            self.assertTrue(node.status()["is_running"])
            self.assertEqual(start_result["session_time_s"], 0.0)
            self.assertEqual(adapter.collect_count, 0)
            stop_result = node.stop_runtime()
            self.assertTrue(
                all(result.succeeded for result in stop_result["device_stop_results"])
            )
            self.assertTrue(
                all(
                    result.succeeded
                    for result in stop_result["device_shutdown_results"]
                )
            )
            self.assertFalse(node.status()["is_running"])

    def test_acquisition_does_not_start_with_unavailable_evidence_location(self):
        with tempfile.TemporaryDirectory() as directory:
            unavailable_path = Path(directory) / "not-a-directory"
            unavailable_path.write_text("occupied", encoding="utf-8")
            node, adapter = self._initialized_node(str(unavailable_path))

            readiness = node.check_ready()
            with self.assertRaisesRegex(
                RuntimeError,
                "failure evidence location is not writable",
            ):
                node.start_acquisition()

            self.assertFalse(readiness["ready"])
            self.assertFalse(node.status()["is_running"])
            self.assertEqual(node.status()["iteration_count"], 0)
            self.assertEqual(adapter.collect_count, 0)

    def _initialized_node(self, error_evidence_location):
        adapter = CountingRecordAdapter()
        manager = DeviceManager((adapter,))
        manager.initialize_all(config={"mode": "failure-evidence-readiness-test"})
        node = AcquisitionNode(
            session_id="failure-evidence-readiness-session",
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(),
            error_evidence_location=error_evidence_location,
        )
        return node, adapter


if __name__ == "__main__":
    unittest.main()
