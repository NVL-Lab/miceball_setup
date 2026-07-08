import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionNode,
    ActiveExperimentRuntimeContext,
    Controller,
    DeviceManager,
    ExperimentRuntimeHealthMapping,
    InMemoryIngestor,
    PersistentStorageManager,
    ServiceReadiness,
    SessionConfig,
)
from tests.fakes import ReadyFakeAdapter


class RuntimeTimestampAdapter(ReadyFakeAdapter):
    def __init__(self):
        super().__init__("source-001", "fake", ("stream",), True)
        self.original_rows = [
            {"sample_index": 1},
            {"sample_index": 2},
            {"sample_index": 3},
        ]
        self._remaining_rows = list(self.original_rows)

    def collect_records(self):
        row = self._remaining_rows.pop(0) if self._remaining_rows else None
        return {
            "record_kind": "stream",
            "records": () if row is None else (row,),
        }


class ControlledSynchronizationManager:
    def __init__(self):
        self.current = 0.0
        self.is_running = False

    @property
    def current_session_time_s(self):
        return self.current

    def start(self):
        self.current = 0.0
        self.is_running = True
        return self.current

    def stop(self):
        self.is_running = False
        return self.current

    def set_time(self, value):
        self.current = float(value)

    def check_ready(self):
        return ServiceReadiness(
            component_id="synchronization",
            component_type="synchronization_manager",
            required=True,
            ready=True,
            reason="ready",
        )


class Phase11RuntimeTimestampingTests(unittest.TestCase):
    def test_active_experiment_runtime_context_round_trips_as_plain_data(self):
        context = ActiveExperimentRuntimeContext("experiment-001", 2.0)

        self.assertEqual(
            ActiveExperimentRuntimeContext.from_dict(context.to_dict()),
            context,
        )

    def test_controller_handoff_scopes_analysis_ready_runtime_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = RuntimeTimestampAdapter()
            manager = DeviceManager((adapter,))
            synchronization = ControlledSynchronizationManager()
            storage = PersistentStorageManager(root / "records.jsonl")
            ingestor = InMemoryIngestor(storage_manager=storage)
            node = AcquisitionNode(
                session_id="phase11-session",
                device_manager=manager,
                synchronization_manager=synchronization,
                ingestor=ingestor,
                error_evidence_location=str(root / "errors"),
            )
            controller = Controller(
                node,
                ingestor,
                storage,
                root / "session-record.json",
                synchronization_manager=synchronization,
            )
            health_mapping = (
                ExperimentRuntimeHealthMapping(
                    live_source_id="source-001",
                    expected_participant_id="device-001",
                    acquisition_health_policy="observe",
                    required=True,
                    expected_contribution="stream",
                ),
            )
            manager.initialize_all(config={})
            readiness = node.check_ready()
            controller.create_session(
                SessionConfig(
                    session_id="phase11-session",
                    selected_devices=[],
                    storage_location=str(root / "records.jsonl"),
                    protocol_plan={"name": "phase11-runtime-timing"},
                    error_evidence_location=str(root / "errors"),
                )
            )
            controller.initialize_session(
                readiness["device_readiness"],
                readiness["service_readiness"],
            )
            controller.start_session()

            with patch(
                "lab_sync_acquisition.acquisition_node.monotonic",
                side_effect=(10.0, 11.0, 12.0),
            ):
                synchronization.set_time(1.0)
                controller.run_one_iteration()

                synchronization.set_time(2.0)
                started = controller.start_experiment(
                    "experiment-001",
                    runtime_health_mapping=health_mapping,
                )
                active_status = node.status()

                synchronization.set_time(2.5)
                controller.run_one_iteration()

                synchronization.set_time(3.0)
                controller.stop_experiment("experiment-001")
                cleared_status = node.status()

                synchronization.set_time(3.5)
                controller.run_one_iteration()

            rows = [
                row
                for envelope in storage.read_envelopes()
                if envelope.record_kind == "stream"
                for row in envelope.records
            ]

            self.assertTrue(started.succeeded, started.error)
            self.assertEqual(
                active_status["active_experiment_runtime_context"],
                ActiveExperimentRuntimeContext("experiment-001", 2.0),
            )
            self.assertEqual(
                active_status["active_experiment_runtime_health_mapping"],
                health_mapping,
            )
            self.assertIsNone(
                cleared_status["active_experiment_runtime_context"]
            )
            self.assertEqual(
                cleared_status["active_experiment_runtime_health_mapping"],
                (),
            )
            self.assertEqual(
                [row["session_time_s"] for row in rows],
                [1.0, 2.5, 3.5],
            )
            self.assertEqual(
                [row["acquisition_node_local_time_s"] for row in rows],
                [10.0, 11.0, 12.0],
            )
            self.assertTrue(
                all(row["timestamp_status"] == "runtime_timestamped" for row in rows)
            )
            self.assertNotIn("experiment_time_s", rows[0])
            self.assertEqual(rows[1]["experiment_time_s"], 0.5)
            self.assertNotIn("experiment_time_s", rows[2])
            self.assertTrue(
                all("session_time_s" not in row for row in adapter.original_rows)
            )


if __name__ == "__main__":
    unittest.main()
