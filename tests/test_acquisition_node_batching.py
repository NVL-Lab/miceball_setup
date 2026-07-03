import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceDeclaration,
    DeviceManager,
    InMemoryIngestor,
    InMemoryStorageManager,
    ServiceReadiness,
    SessionConfig,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class BatchingFakeAdapter(ReadyFakeAdapter):
    def __init__(self, *args, record_kind, batches):
        super().__init__(*args)
        self._record_kind = record_kind
        self._batches = iter(batches)

    def collect_records(self):
        return {
            "record_kind": self._record_kind,
            "records": tuple(next(self._batches)),
        }


class ControlledSynchronizationManager:
    def __init__(self):
        self._session_time_s = 0.0
        self._running = False

    @property
    def current_session_time_s(self):
        return self._session_time_s

    @property
    def is_running(self):
        return self._running

    def check_ready(self):
        return ServiceReadiness(
            component_id="synchronization",
            component_type="synchronization_manager",
            required=True,
            ready=True,
            reason="ready",
        )

    def start(self):
        self._session_time_s = 0.0
        self._running = True
        return 0.0

    def stop(self):
        self._running = False
        return self._session_time_s

    def set_session_time(self, session_time_s):
        self._session_time_s = float(session_time_s)


class AcquisitionNodeBatchingTests(unittest.TestCase):
    def test_stream_batches_flush_by_count_and_before_session_stop(self) -> None:
        acquisition_configuration = {
            "batch_policy": "type_1",
            "batch_policies": {"type_1": {"max_records": 3}},
        }
        configuration = self._session_config(acquisition_configuration)
        node, storage = self._running_node(
            configuration=configuration,
            record_kind="stream",
            batches=(
                ({"sample_index": 0}, {"sample_index": 1}),
                ({"sample_index": 2}, {"sample_index": 3}),
                ({"sample_index": 4},),
            ),
        )

        first = node.run_one_iteration()
        second = node.run_one_iteration()
        third = node.run_one_iteration()

        stream_envelopes_before_stop = tuple(
            envelope
            for envelope in storage.stored_envelopes
            if envelope.record_kind == "stream"
        )
        self.assertEqual(first.envelopes_sent, 0)
        self.assertEqual(second.envelopes_sent, 1)
        self.assertEqual(third.envelopes_sent, 0)
        self.assertEqual(len(stream_envelopes_before_stop), 1)
        self.assertEqual(len(stream_envelopes_before_stop[0].records), 3)
        self.assertLess(len(stream_envelopes_before_stop), 3)

        node.stop_acquisition()

        stored_envelopes = storage.stored_envelopes
        stream_envelopes = tuple(
            envelope
            for envelope in stored_envelopes
            if envelope.record_kind == "stream"
        )
        self.assertEqual(
            [envelope.record_kind for envelope in stored_envelopes],
            ["event", "stream", "stream", "event"],
        )
        self.assertEqual([len(envelope.records) for envelope in stream_envelopes], [3, 2])
        self.assertEqual(
            [row["sample_index"] for envelope in stream_envelopes for row in envelope.records],
            [0, 1, 2, 3, 4],
        )
        self.assertTrue(
            all(
                "session_time_s" in row
                for envelope in stream_envelopes
                for row in envelope.records
            )
        )
        self.assertEqual(
            stored_envelopes[-1].records[0]["event_type"],
            "session_stop",
        )

    def test_non_stream_records_continue_to_send_immediately(self) -> None:
        configuration = self._session_config(
            {
                "batch_policy": "type_1",
                "batch_policies": {"type_1": {"max_records": 3}},
            }
        )
        node, storage = self._running_node(
            configuration=configuration,
            record_kind="event",
            batches=(({"event_type": "lick"},),),
        )

        summary = node.run_one_iteration()

        device_events = tuple(
            envelope
            for envelope in storage.stored_envelopes
            if envelope.source_device_id == "batch-device-001"
        )
        self.assertEqual(summary.envelopes_sent, 1)
        self.assertEqual(len(device_events), 1)
        self.assertEqual(device_events[0].records[0]["event_type"], "lick")
        node.stop_acquisition()

    def test_partial_stream_batch_flushes_by_session_time_age(self) -> None:
        synchronization = ControlledSynchronizationManager()
        configuration = self._session_config(
            {
                "batch_policy": "type_1",
                "batch_policies": {
                    "type_1": {"max_records": 10, "max_batch_age_s": 1.0}
                },
            }
        )
        node, storage = self._running_node(
            configuration=configuration,
            record_kind="stream",
            batches=(({"sample_index": 0},), ()),
            synchronization_manager=synchronization,
        )

        first = node.run_one_iteration()
        synchronization.set_session_time(1.0)
        second = node.run_one_iteration()

        stream_envelopes = tuple(
            envelope
            for envelope in storage.stored_envelopes
            if envelope.record_kind == "stream"
        )
        self.assertEqual(first.envelopes_sent, 0)
        self.assertEqual(second.envelopes_sent, 1)
        self.assertEqual(len(stream_envelopes), 1)
        self.assertEqual(len(stream_envelopes[0].records), 1)
        self.assertEqual(stream_envelopes[0].records[0]["session_time_s"], 0.0)
        node.stop_acquisition()

    def test_invalid_age_configuration_preserves_count_batching(self) -> None:
        invalid_ages = (None, 0, -1, float("nan"), "one-second")
        for max_batch_age_s in invalid_ages:
            with self.subTest(max_batch_age_s=max_batch_age_s):
                policy = {"max_records": 2}
                if max_batch_age_s is not None:
                    policy["max_batch_age_s"] = max_batch_age_s
                configuration = self._session_config(
                    {
                        "batch_policy": "type_1",
                        "batch_policies": {"type_1": policy},
                    }
                )
                node, storage = self._running_node(
                    configuration=configuration,
                    record_kind="stream",
                    batches=(({"sample_index": 0},), ({"sample_index": 1},)),
                )

                first = node.run_one_iteration()
                second = node.run_one_iteration()

                self.assertEqual(first.envelopes_sent, 0)
                self.assertEqual(second.envelopes_sent, 1)
                self.assertEqual(
                    len(
                        tuple(
                            envelope
                            for envelope in storage.stored_envelopes
                            if envelope.record_kind == "stream"
                        )
                    ),
                    1,
                )
                node.stop_acquisition()

    def test_invalid_count_configuration_preserves_age_batching(self) -> None:
        for max_records in (None, 1, "five-hundred"):
            with self.subTest(max_records=max_records):
                synchronization = ControlledSynchronizationManager()
                policy = {"max_batch_age_s": 0.5}
                if max_records is not None:
                    policy["max_records"] = max_records
                configuration = self._session_config(
                    {
                        "batch_policy": "type_1",
                        "batch_policies": {"type_1": policy},
                    }
                )
                node, storage = self._running_node(
                    configuration=configuration,
                    record_kind="stream",
                    batches=(({"sample_index": 0},), ()),
                    synchronization_manager=synchronization,
                )

                node.run_one_iteration()
                synchronization.set_session_time(0.5)
                summary = node.run_one_iteration()

                self.assertEqual(summary.envelopes_sent, 1)
                self.assertEqual(
                    len(
                        tuple(
                            envelope
                            for envelope in storage.stored_envelopes
                            if envelope.record_kind == "stream"
                        )
                    ),
                    1,
                )
                node.stop_acquisition()

    def test_count_flush_leftover_starts_new_age_window(self) -> None:
        synchronization = ControlledSynchronizationManager()
        configuration = self._session_config(
            {
                "batch_policy": "type_1",
                "batch_policies": {
                    "type_1": {"max_records": 3, "max_batch_age_s": 1.0}
                },
            }
        )
        node, storage = self._running_node(
            configuration=configuration,
            record_kind="stream",
            batches=(
                ({"sample_index": 0}, {"sample_index": 1}),
                ({"sample_index": 2}, {"sample_index": 3}),
                (),
                (),
            ),
            synchronization_manager=synchronization,
        )

        node.run_one_iteration()
        synchronization.set_session_time(0.8)
        count_flush = node.run_one_iteration()
        synchronization.set_session_time(1.1)
        before_new_age = node.run_one_iteration()
        synchronization.set_session_time(1.8)
        age_flush = node.run_one_iteration()

        stream_envelopes = tuple(
            envelope
            for envelope in storage.stored_envelopes
            if envelope.record_kind == "stream"
        )
        self.assertEqual(count_flush.envelopes_sent, 1)
        self.assertEqual(before_new_age.envelopes_sent, 0)
        self.assertEqual(age_flush.envelopes_sent, 1)
        self.assertEqual([len(envelope.records) for envelope in stream_envelopes], [3, 1])
        self.assertEqual(stream_envelopes[1].records[0]["sample_index"], 3)
        node.stop_acquisition()

    def test_invalid_batching_configuration_preserves_immediate_envelopes(self) -> None:
        invalid_configurations = (
            None,
            {},
            {"batch_policy": "type_1"},
            {"batch_policy": "unsupported", "batch_policies": {}},
            {"batch_policy": "type_1", "batch_policies": {"type_1": {}}},
            {
                "batch_policy": "type_1",
                "batch_policies": {"type_1": {"max_records": 1}},
            },
        )
        for acquisition_configuration in invalid_configurations:
            with self.subTest(acquisition_configuration=acquisition_configuration):
                configuration = self._session_config(acquisition_configuration)
                node, storage = self._running_node(
                    configuration=configuration,
                    record_kind="stream",
                    batches=(({"sample_index": 0}, {"sample_index": 1}),),
                )

                summary = node.run_one_iteration()

                stream_envelopes = tuple(
                    envelope
                    for envelope in storage.stored_envelopes
                    if envelope.record_kind == "stream"
                )
                self.assertEqual(summary.envelopes_sent, 1)
                self.assertEqual(len(stream_envelopes), 1)
                self.assertEqual(len(stream_envelopes[0].records), 2)
                node.stop_acquisition()

    def _session_config(self, acquisition_configuration):
        return SessionConfig(
            selected_devices=[
                DeviceDeclaration(
                    device_id="declared-batch-device-001",
                    device_type="batch_device",
                    enabled=True,
                    required=True,
                    declared_capabilities=["stream"],
                )
            ],
            storage_location="placeholder://batching",
            protocol_plan={"name": "batching-v1"},
            error_evidence_location="placeholder://errors",
            acquisition_configuration=acquisition_configuration,
        )

    def _running_node(
        self,
        configuration,
        record_kind,
        batches,
        synchronization_manager=None,
    ):
        adapter = BatchingFakeAdapter(
            "batch-device-001",
            "batch_device",
            [record_kind],
            True,
            record_kind=record_kind,
            batches=batches,
        )
        manager = DeviceManager(adapters=(adapter,))
        storage = InMemoryStorageManager()
        synchronization = synchronization_manager or SynchronizationManager()
        node = AcquisitionNode(
            session_id="batch-session-001",
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=InMemoryIngestor(storage_manager=storage),
            node_id="batch-node-001",
            acquisition_configuration=configuration.acquisition_configuration,
            error_evidence_location=tempfile.gettempdir(),
        )
        manager.initialize_all(config={"mode": "batching-test"})
        manager.check_readiness()
        node.start_acquisition()
        return node, storage


if __name__ == "__main__":
    unittest.main()


