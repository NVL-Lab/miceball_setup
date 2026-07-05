import unittest

from lab_sync_acquisition import HealthInterpretationEvidence


class HealthInterpretationEvidenceTests(unittest.TestCase):
    def test_interpretation_evidence_round_trips_as_plain_data(self):
        evidence = HealthInterpretationEvidence(
            originating_observation_id="health-observation-1",
            experiment_id="experiment-001",
            live_source_id="camera-source-001",
            expected_participant_id="camera-001",
            observation_type="first_evidence_missing",
            acquisition_health_policy="critical-camera",
            interpretation_label="experiment_failure",
            required=True,
            session_time_s=1.25,
            details={"observed_record_count": 0},
        )

        plain_data = evidence.to_dict()
        reconstructed = HealthInterpretationEvidence.from_dict(plain_data)

        self.assertEqual(
            plain_data,
            {
                "originating_observation_id": "health-observation-1",
                "experiment_id": "experiment-001",
                "live_source_id": "camera-source-001",
                "expected_participant_id": "camera-001",
                "observation_type": "first_evidence_missing",
                "acquisition_health_policy": "critical-camera",
                "interpretation_label": "experiment_failure",
                "required": True,
                "session_time_s": 1.25,
                "details": {"observed_record_count": 0},
            },
        )
        self.assertEqual(reconstructed, evidence)


if __name__ == "__main__":
    unittest.main()
