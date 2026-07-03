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
    def __init__(self, *args, record_kind="event", records=(), batches=None):
        super().__init__(*args)
        self._record_kind = record_kind
        self._records = tuple(records)
        self._batches = iter(batches) if batches is not None else None

    def collect_records(self):
        if self._batches is not None:
            records = tuple(next(self._batches, ()))
        else:
            records, self._records = self._records, ()
        return {"record_kind": self._record_kind, "records": records}


class SelectivelyFailingIngestor(InMemoryIngestor):
    def receive_envelope(self, envelope):
        if envelope.source_device_id != "acquisition_node":
            raise ConnectionError("handoff unavailable")
        return super().receive_envelope(envelope)


class SequencedIngestor(InMemoryIngestor):
    def __init__(self, device_handoff_outcomes):
        super().__init__()
        self._device_handoff_outcomes = iter(device_handoff_outcomes)

    def receive_envelope(self, envelope):
        if envelope.source_device_id != "acquisition_node":
            succeeds = next(self._device_handoff_outcomes, True)
            if not succeeds:
                raise ConnectionError("handoff unavailable")
        return super().receive_envelope(envelope)


class CleanupFailingIngestor(InMemoryIngestor):
    def __init__(self):
        super().__init__()
        self.attempted_envelopes = []

    def receive_envelope(self, envelope):
        self.attempted_envelopes.append(envelope)
        if envelope.source_device_id != "acquisition_node":
            raise ConnectionError("device handoff unavailable")
        event_type = envelope.records[0].get("event_type")
        if event_type == "session_stop":
            raise ConnectionError("session_stop handoff unavailable")
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

    def test_missing_error_location_prevents_acquisition_start(self):
        with self.assertRaisesRegex(RuntimeError, "failure evidence location"):
            self._running_node(error_evidence_location=None)

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

    def test_must_preserve_threshold_marks_node_failed_after_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                ingestor=SequencedIngestor((False, False)),
                batches=(({"value": 1},), ({"value": 2},)),
                acquisition_configuration=self._must_preserve_configuration(2),
            )

            node.run_one_iteration()
            node.run_one_iteration()

            status = node.status()
            evidence = self._read_evidence(temporary_directory)
            self.assertTrue(status["failed"])
            self.assertFalse(status["is_running"])
            self.assertEqual(status["consecutive_must_preserve_handoff_failures"], 2)
            self.assertEqual(len(evidence), 2)
            self.assertEqual(evidence[-1]["envelope"]["records"][0]["value"], 2)
            with self.assertRaisesRegex(
                RuntimeError,
                "AcquisitionNode has failed and cannot run new iterations",
            ):
                node.run_one_iteration()
            node.stop_acquisition()

    def test_successful_handoff_resets_consecutive_failure_count(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            node = self._running_node(
                error_evidence_location=temporary_directory,
                ingestor=SequencedIngestor((False, True, False)),
                batches=(({"value": 1},), ({"value": 2},), ({"value": 3},)),
                acquisition_configuration=self._must_preserve_configuration(2),
            )

            node.run_one_iteration()
            node.run_one_iteration()
            node.run_one_iteration()

            status = node.status()
            self.assertFalse(status["failed"])
            self.assertEqual(status["consecutive_must_preserve_handoff_failures"], 1)
            node.stop_acquisition()

    def test_best_effort_failures_do_not_count_toward_threshold(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            configuration = self._must_preserve_configuration(1)
            configuration["handoff_failure_policy"] = "best_effort"
            configuration["handoff_failure_policies"]["best_effort"] = {
                "preserve_failed_envelope": False
            }
            node = self._running_node(
                error_evidence_location=temporary_directory,
                ingestor=SequencedIngestor((False, False)),
                batches=(({"value": 1},), ({"value": 2},)),
                acquisition_configuration=configuration,
            )

            node.run_one_iteration()
            node.run_one_iteration()

            status = node.status()
            self.assertFalse(status["failed"])
            self.assertEqual(status["consecutive_must_preserve_handoff_failures"], 0)
            node.stop_acquisition()

    def test_missing_or_invalid_threshold_does_not_mark_node_failed(self):
        invalid_thresholds = (None, 0, -1, True, 1.5, "three")
        for threshold in invalid_thresholds:
            with self.subTest(threshold=threshold), tempfile.TemporaryDirectory() as directory:
                configuration = self._must_preserve_configuration(threshold)
                node = self._running_node(
                    error_evidence_location=directory,
                    ingestor=SequencedIngestor((False, False)),
                    batches=(({"value": 1},), ({"value": 2},)),
                    acquisition_configuration=configuration,
                )

                node.run_one_iteration()
                node.run_one_iteration()

                self.assertFalse(node.status()["failed"])
                node.stop_acquisition()

    def test_failed_node_flushes_and_attempts_full_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stream_adapter = RecordFakeAdapter(
                "stream-device-001",
                "fake_stream",
                ["stream"],
                True,
                record_kind="stream",
                records=({"sample_index": 1},),
            )
            event_adapter = RecordFakeAdapter(
                "event-device-001",
                "fake_event",
                ["event"],
                True,
                record_kind="event",
                records=({"event_type": "trigger_failure"},),
            )
            manager = DeviceManager((stream_adapter, event_adapter))
            manager.initialize_all(config={"mode": "failed-cleanup-test"})
            manager.check_readiness()
            ingestor = CleanupFailingIngestor()
            configuration = self._must_preserve_configuration(1)
            configuration.update(
                {
                    "batch_policy": "type_1",
                    "batch_policies": {"type_1": {"max_records": 10}},
                }
            )
            node = AcquisitionNode(
                session_id="failed-cleanup-session-001",
                device_manager=manager,
                synchronization_manager=SynchronizationManager(),
                ingestor=ingestor,
                node_id="failed-cleanup-node-001",
                acquisition_configuration=configuration,
                error_evidence_location=temporary_directory,
            )
            node.start_acquisition()

            node.run_one_iteration()
            self.assertTrue(node.status()["failed"])
            with self.assertRaisesRegex(
                RuntimeError,
                "AcquisitionNode has failed and cannot run new iterations",
            ):
                node.run_one_iteration()

            stop_result = node.stop_acquisition()

            attempted = ingestor.attempted_envelopes
            evidence = self._read_evidence(temporary_directory)
            self.assertTrue(
                any(envelope.source_device_id == "stream-device-001" for envelope in attempted)
            )
            self.assertTrue(
                any(
                    envelope.records[0].get("event_type") == "session_stop"
                    for envelope in attempted
                    if envelope.source_device_id == "acquisition_node"
                )
            )
            self.assertTrue(
                all(result.succeeded for result in stop_result["device_stop_results"])
            )
            self.assertTrue(
                all(result.succeeded for result in stop_result["device_shutdown_results"])
            )
            self.assertTrue(all(status.shutdown for status in manager.collect_statuses()))
            self.assertEqual(len(evidence), 3)
            self.assertEqual(
                evidence[-1]["envelope"]["records"][0]["event_type"],
                "session_stop",
            )

    def _running_node(
        self,
        error_evidence_location,
        acquisition_configuration=None,
        ingestor=None,
        record_kind="event",
        records=({"value": 7},),
        batches=None,
    ):
        adapter = RecordFakeAdapter(
            "handoff-device-001",
            "fake_device",
            [record_kind],
            True,
            record_kind=record_kind,
            records=records,
            batches=batches,
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

    def _must_preserve_configuration(self, threshold):
        policy = {"preserve_failed_envelope": True}
        if threshold is not None:
            policy["consecutive_failure_threshold"] = threshold
        return {
            "handoff_failure_policy": "must_preserve",
            "handoff_failure_policies": {"must_preserve": policy},
        }

    def _read_evidence(self, directory):
        path = Path(directory) / "sender_handoff_failures.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
