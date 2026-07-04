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
    ExperimentRuntimeHealthMapping,
    InMemoryIngestor,
    InMemoryStorageManager,
    ServiceReadiness,
    SessionConfig,
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
        self.assertFalse(node.status()["failed"])
        node.stop_acquisition()

    def test_first_record_policy_emits_health_evidence_after_grace_window(self):
        node, storage, synchronization = self._running_node(
            batches=((), ()),
            runtime_health_mapping=self._runtime_mapping("live-camera-001"),
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        self.assertEqual(
            self._health_rows(storage),
            [
                {
                    "event_category": "acquisition_health",
                    "event_type": "health_policy_failed",
                    "source_device_id": "live-camera-001",
                    "policy_name": "camera-first-record",
                    "policy_kind": "first_record_within_grace_window",
                    "expected_record_kind": "stream",
                    "grace_window_s": 1.0,
                    "observed_record_count": 0,
                    "session_time_s": 1.0,
                }
            ],
        )
        self.assertFalse(node.status()["failed"])
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

    def test_declared_health_policy_is_preserved_as_session_config_data(self):
        declaration = DeviceDeclaration(
            device_id="declared-camera-001",
            device_type="camera",
            enabled=True,
            required=True,
            declared_capabilities=("stream",),
            acquisition_health_policy="camera-first-record",
        )
        configuration = SessionConfig(
            selected_devices=[declaration],
            storage_location="placeholder://storage",
            protocol_plan={"name": "health-policy-test"},
            error_evidence_location="placeholder://errors",
            acquisition_configuration=self._health_configuration(),
        )

        plain_data = configuration.to_dict()

        self.assertEqual(declaration.acquisition_health_policy, "camera-first-record")
        self.assertEqual(
            plain_data["selected_devices"][0]["acquisition_health_policy"],
            "camera-first-record",
        )

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
            error_evidence_location=tempfile.gettempdir(),
        )
        manager.initialize_all(config={"mode": "mapped-health-test"})
        manager.check_readiness()
        node.start_runtime()
        node.activate_experiment_runtime_health_mapping(
            self._runtime_mapping("mapped-camera-001")
        )

        node.run_one_iteration()
        synchronization.set_session_time(1.0)
        node.run_one_iteration()

        self.assertEqual(
            [row["source_device_id"] for row in self._health_rows(storage)],
            ["mapped-camera-001"],
        )
        node.stop_runtime()

    def _running_node(self, batches, runtime_health_mapping=()):
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
            error_evidence_location=tempfile.gettempdir(),
        )
        manager.initialize_all(config={"mode": "health-test"})
        manager.check_readiness()
        node.start_runtime()
        node.activate_experiment_runtime_health_mapping(runtime_health_mapping)
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
        return {
            "acquisition_health_policies": {
                "camera-first-record": {
                    "kind": "first_record_within_grace_window",
                    "record_kind": "stream",
                    "grace_window_s": 1.0,
                }
            }
        }

    def _health_rows(self, storage):
        return [
            row
            for envelope in storage.stored_envelopes
            for row in envelope.records
            if row.get("event_category") == "acquisition_health"
        ]


if __name__ == "__main__":
    unittest.main()
