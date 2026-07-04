import unittest

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceManager,
    ExperimentRuntimeHealthMapping,
    InMemoryIngestor,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class ExperimentRuntimeHealthMappingTests(unittest.TestCase):
    def test_mapping_entry_round_trips_through_plain_data(self):
        mapping = ExperimentRuntimeHealthMapping(
            live_source_id="camera-adapter-source-17",
            expected_participant_id="camera-001",
            acquisition_health_policy="camera_frames_required",
            required=True,
            expected_contribution="camera_frame_metadata",
        )

        plain_data = mapping.to_dict()
        reconstructed = ExperimentRuntimeHealthMapping.from_dict(plain_data)

        self.assertEqual(
            plain_data,
            {
                "live_source_id": "camera-adapter-source-17",
                "expected_participant_id": "camera-001",
                "acquisition_health_policy": "camera_frames_required",
                "required": True,
                "expected_contribution": "camera_frame_metadata",
            },
        )
        self.assertEqual(reconstructed, mapping)

    def test_acquisition_node_stores_replaces_and_clears_active_mapping(self):
        node = AcquisitionNode(
            session_id="mapping-session-001",
            device_manager=DeviceManager(
                [ReadyFakeAdapter("live-source-001", "fake", ("stream",), True)]
            ),
            synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(),
        )
        first_mapping = (
            ExperimentRuntimeHealthMapping(
                live_source_id="camera-source-001",
                expected_participant_id="camera-001",
                acquisition_health_policy="camera_frames_required",
                required=True,
                expected_contribution="camera_frame_metadata",
            ),
            ExperimentRuntimeHealthMapping(
                live_source_id="decoder-source-001",
                expected_participant_id="decoder-001",
                acquisition_health_policy="decoder_predictions_optional",
                required=False,
                expected_contribution="decoder_predictions",
            ),
        )
        replacement = (
            ExperimentRuntimeHealthMapping(
                live_source_id="event-source-001",
                expected_participant_id="lick-001",
                acquisition_health_policy="lick_events_required",
                required=True,
                expected_contribution="lick_events",
            ),
        )

        node.activate_experiment_runtime_health_mapping(first_mapping)
        self.assertEqual(
            node.status()["active_experiment_runtime_health_mapping"],
            first_mapping,
        )

        node.activate_experiment_runtime_health_mapping(replacement)
        self.assertEqual(
            node.status()["active_experiment_runtime_health_mapping"],
            replacement,
        )

        node.clear_experiment_runtime_health_mapping()
        self.assertEqual(
            node.status()["active_experiment_runtime_health_mapping"],
            (),
        )


if __name__ == "__main__":
    unittest.main()
