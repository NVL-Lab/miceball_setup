import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionHealthPolicy,
    AcquisitionNode,
    DeviceManager,
    ExperimentRuntimeHealthMapping,
    InMemoryIngestor,
    InMemoryStorageManager,
    ServiceReadiness,
)
from tests.fakes import ReadyFakeAdapter


class HealthFakeAdapter(ReadyFakeAdapter):
    def __init__(self, *args, record_kind="stream", batches=()):
        super().__init__(*args)
        self._record_kind = record_kind
        self._batches = iter(batches)

    def collect_records(self):
        return {
            "record_kind": self._record_kind,
            "records": tuple(next(self._batches, ())),
        }


class ControlledSynchronizationManager:
    def __init__(self):
        self._session_time_s = 0.0

    @property
    def current_session_time_s(self):
        return self._session_time_s

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
        return self._session_time_s

    def stop(self):
        return self._session_time_s

    def set_session_time(self, session_time_s):
        self._session_time_s = float(session_time_s)


class AcquisitionHealthTests(unittest.TestCase):
    def test_unmapped_required_source_is_not_health_checked(self):
        node, storage, synchronization = self._running_node(
            batches=((), ()),
        )

        node.run_one_iteration()
        synchronization.set_session_time(2.0)
        node.run_one_iteration()

        self.assertEqual(self._health_rows(storage), [])
        self.assertEqual(node.experiment_scoped_health_observations, ())
        self.assertFalse(node.status()["failed"])
        node.stop_acquisition()

    def test_missing_expected_evidence_records_health_observation(self):
        node, storage, synchronization = self._running_node(
            batches=((), ()),
            runtime_health_mapping=self._runtime_mapping("live-camera-001"),
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        expected_observation = {
            "observation_id": "health-observation-1",
            "experiment_id": "experiment-001",
            "live_source_id": "live-camera-001",
            "expected_participant_id": "camera-001",
            "expected_contribution": "camera_frame_metadata",
            "acquisition_health_policy": "camera-first-record",
            "observation_type": "expected_acquisition_evidence_missing",
            "required": True,
            "session_time_s": 1.0,
            "details": {
                "policy_kind": "first_evidence",
                "expected_record_kind": "stream",
                "grace_window_s": 1.0,
                "observed_record_count": 0,
            },
        }
        self.assertEqual(self._health_rows(storage), [expected_observation])
        self.assertEqual(
            [
                observation.to_dict()
                for observation in node.experiment_scoped_health_observations
            ],
            [expected_observation],
        )
        self.assertFalse(node.status()["failed"])
        self.assertTrue(node.status()["is_running"])
        node.stop_acquisition()

    def test_matching_record_within_grace_window_avoids_failure_evidence(self):
        node, storage, synchronization = self._running_node(
            batches=(({"sample_index": 1},), ()),
            runtime_health_mapping=self._runtime_mapping("live-camera-001"),
        )

        synchronization.set_session_time(0.5)
        node.run_one_iteration()
        synchronization.set_session_time(1.5)
        node.run_one_iteration()

        self.assertEqual(self._health_rows(storage), [])
        node.stop_acquisition()

    def test_missing_evidence_is_immediately_interpreted(self):
        node, storage, synchronization = self._running_node(
            batches=((), ()),
            runtime_health_mapping=self._runtime_mapping("live-camera-001"),
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        observation = node.experiment_scoped_health_observations[0]
        interpretation = node.health_interpretation_evidence[0]
        self.assertEqual(
            interpretation.originating_observation_id,
            observation.observation_id,
        )
        self.assertEqual(interpretation.interpretation_label, "experiment_failure")
        self.assertEqual(len(self._interpretation_rows(storage)), 1)
        self.assertTrue(node.status()["is_running"])
        self.assertFalse(node.status()["failed"])
        node.stop_runtime()

    def test_missing_policy_interpretation_is_recorded_as_uninterpreted(self):
        node, storage, synchronization = self._running_node(
            batches=((), ()),
            runtime_health_mapping=self._runtime_mapping("live-camera-001"),
            acquisition_health_policies=self._health_policies({}),
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        self.assertEqual(
            node.health_interpretation_evidence[0].interpretation_label,
            "uninterpreted",
        )
        self.assertEqual(
            self._interpretation_rows(storage)[0]["interpretation_label"],
            "uninterpreted",
        )
        self.assertTrue(node.status()["is_running"])
        self.assertFalse(node.status()["failed"])
        node.stop_runtime()

    def test_active_mapping_ignores_unmapped_session_ready_source(self):
        mapped_adapter = HealthFakeAdapter(
            "mapped-camera-001",
            "fake_camera",
            ("stream",),
            True,
            batches=((), ()),
        )
        unmapped_adapter = HealthFakeAdapter(
            "unmapped-camera-001",
            "fake_camera",
            ("stream",),
            True,
            batches=((), ()),
        )
        manager = DeviceManager((mapped_adapter, unmapped_adapter))
        storage = InMemoryStorageManager()
        synchronization = ControlledSynchronizationManager()
        node = AcquisitionNode(
            session_id="health-session-002",
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=InMemoryIngestor(storage_manager=storage),
            acquisition_configuration=self._health_configuration(),
            acquisition_health_policies=self._health_policies(),
            error_evidence_location=tempfile.gettempdir(),
        )
        manager.initialize_all(config={"mode": "mapped-health-test"})
        manager.check_readiness()
        node.start_runtime()
        node.activate_experiment_runtime_health_mapping(
            "experiment-002",
            self._runtime_mapping("mapped-camera-001")
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        self.assertEqual(
            [row["live_source_id"] for row in self._health_rows(storage)],
            ["mapped-camera-001"],
        )
        node.stop_runtime()

    def _running_node(
        self,
        batches,
        runtime_health_mapping=(),
        acquisition_health_policies=None,
    ):
        adapter = HealthFakeAdapter(
            "live-camera-001",
            "fake_camera",
            ("stream",),
            True,
            batches=batches,
        )
        manager = DeviceManager((adapter,))
        storage = InMemoryStorageManager()
        synchronization = ControlledSynchronizationManager()
        node = AcquisitionNode(
            session_id="health-session-001",
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=InMemoryIngestor(storage_manager=storage),
            node_id="health-node-001",
            acquisition_configuration=self._health_configuration(),
            acquisition_health_policies=(
                self._health_policies()
                if acquisition_health_policies is None
                else acquisition_health_policies
            ),
            error_evidence_location=tempfile.gettempdir(),
        )
        manager.initialize_all(config={"mode": "health-test"})
        manager.check_readiness()
        node.start_runtime()
        if runtime_health_mapping:
            node.activate_experiment_runtime_health_mapping(
                "experiment-001",
                runtime_health_mapping,
            )
        return node, storage, synchronization

    def _runtime_mapping(self, live_source_id):
        return (
            ExperimentRuntimeHealthMapping(
                live_source_id=live_source_id,
                expected_participant_id="camera-001",
                acquisition_health_policy="camera-first-record",
                required=True,
                expected_contribution="camera_frame_metadata",
            ),
        )

    def _health_configuration(self):
        return {}

    def _health_policies(self, interpretation=None):
        return (
            AcquisitionHealthPolicy(
                policy_id="camera-first-record",
                evaluation_rules={
                    "first_evidence": {
                        "record_kind": "stream",
                        "grace_window_s": 1.0,
                    }
                },
                interpretation=(
                    {
                        "expected_acquisition_evidence_missing": (
                            "experiment_failure"
                        )
                    }
                    if interpretation is None
                    else interpretation
                ),
            ),
        )

    def _health_rows(self, storage):
        return [
            row
            for envelope in storage.stored_envelopes
            for row in envelope.records
            if "observation_id" in row
        ]

    def _interpretation_rows(self, storage):
        return [
            row
            for envelope in storage.stored_envelopes
            for row in envelope.records
            if "originating_observation_id" in row
        ]


if __name__ == "__main__":
    unittest.main()
