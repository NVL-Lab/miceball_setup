import json
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


class RecordFakeAdapter(ReadyFakeAdapter):
    def __init__(self, *args, record_kind="event", records=()):
        super().__init__(*args)
        self._record_kind = record_kind
        self._records = tuple(records)

    def collect_records(self):
        records, self._records = self._records, ()
        return {"record_kind": self._record_kind, "records": records}


class SelectivelyFailingIngestor(InMemoryIngestor):
    def receive_envelope(self, envelope):
        if envelope.source_device_id != "acquisition_node":
            raise ConnectionError("handoff unavailable")
        return super().receive_envelope(envelope)


class AcquisitionNodeHandoffFailureTests(unittest.TestCase):
    def test_must_preserve_records_failed_envelope_in_session_error_location(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                acquisition_configuration={
                    "handoff_failure_policy": "must_preserve",
                    "handoff_failure_policies": {
                        "must_preserve": {"preserve_failed_envelope": True}
                    },
                },
            )

            summary = node.run_one_iteration()
            node.stop_acquisition()

            evidence = self._read_evidence(temporary_directory)
            self.assertEqual(summary.rejected_count, 1)
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["policy_name"], "must_preserve")
            self.assertEqual(evidence[0]["action_taken"], "preserved_failed_envelope")
            self.assertTrue(evidence[0]["preserved_envelope"])
            self.assertEqual(evidence[0]["envelope"]["records"][0]["value"], 7)

    def test_best_effort_records_drop_without_envelope_payload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                acquisition_configuration={
                    "handoff_failure_policy": "best_effort",
                    "handoff_failure_policies": {
                        "best_effort": {"preserve_failed_envelope": False}
                    },
                },
            )

            node.run_one_iteration()
            node.stop_acquisition()

            evidence = self._read_evidence(temporary_directory)
            self.assertEqual(evidence[0]["policy_name"], "best_effort")
            self.assertEqual(evidence[0]["action_taken"], "recorded_drop_and_continued")
            self.assertFalse(evidence[0]["preserved_envelope"])
            self.assertNotIn("envelope", evidence[0])

    def test_invalid_policy_uses_safe_must_preserve_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                acquisition_configuration={"handoff_failure_policy": "unknown"},
            )
            node.run_one_iteration()
            node.stop_acquisition()

            evidence = self._read_evidence(temporary_directory)
            self.assertEqual(evidence[0]["policy_name"], "must_preserve")
            self.assertIn("envelope", evidence[0])

    def test_failed_handoff_without_error_location_fails_loudly(self):
        node = self._running_node(error_evidence_location=None)

        with self.assertRaisesRegex(RuntimeError, "error_evidence_location"):
            node.run_one_iteration()

    def test_successful_handoff_writes_no_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                ingestor=InMemoryIngestor(),
            )
            node.run_one_iteration()
            node.stop_acquisition()

            self.assertFalse(
                (Path(temporary_directory) / "sender_handoff_failures.jsonl").exists()
            )

    def test_batched_stream_uses_the_same_failure_evidence_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                record_kind="stream",
                records=({"value": 7}, {"value": 8}),
                acquisition_configuration={
                    "batch_policy": "type_1",
                    "batch_policies": {"type_1": {"max_records": 2}},
                },
            )
            node.run_one_iteration()
            node.stop_acquisition()

            evidence = self._read_evidence(temporary_directory)
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["record_kind"], "stream")
            self.assertEqual(evidence[0]["record_count"], 2)

    def _running_node(
        self,
        error_evidence_location,
        acquisition_configuration=None,
        ingestor=None,
        record_kind="event",
        records=({"value": 7},),
    ):
        adapter = RecordFakeAdapter(
            "handoff-device-001",
            "fake_device",
            [record_kind],
            True,
            record_kind=record_kind,
            records=records,
        )
        manager = DeviceManager((adapter,))
        manager.initialize_all(config={"mode": "handoff-test"})
        manager.check_readiness()
        node = AcquisitionNode(
            session_id="handoff-session-001",
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=ingestor or SelectivelyFailingIngestor(),
            node_id="handoff-node-001",
            acquisition_configuration=acquisition_configuration,
            error_evidence_location=error_evidence_location,
        )
        node.start_acquisition()
        return node

    def _read_evidence(self, directory):
        path = Path(directory) / "sender_handoff_failures.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
