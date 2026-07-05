import unittest

from lab_sync_acquisition import AcquisitionHealthPolicy, SessionConfig


class AcquisitionHealthPolicyTests(unittest.TestCase):
    def test_session_config_owns_serialized_policy_definitions(self):
        policy = self._policy()
        configuration = SessionConfig(
            selected_devices=[],
            storage_location=None,
            protocol_plan=None,
            error_evidence_location="errors",
            acquisition_health_policies=(policy,),
        )

        self.assertEqual(
            configuration.to_dict()["acquisition_health_policies"],
            [policy.to_dict()],
        )

    def test_policy_round_trips_with_optional_evaluation_fields(self):
        policy = AcquisitionHealthPolicy(
            policy_id="camera-soft",
            evaluation_rules={
                "first_evidence": {
                    "record_kind": "camera_frame_metadata",
                    "grace_window_s": 1.5,
                },
            },
            interpretation={
                "expected_acquisition_evidence_missing": "warning",
            },
        )

        plain_data = policy.to_dict()
        reconstructed = AcquisitionHealthPolicy.from_dict(plain_data)

        self.assertEqual(
            plain_data,
            {
                "policy_id": "camera-soft",
                "evaluation_rules": {
                    "first_evidence": {
                        "record_kind": "camera_frame_metadata",
                        "grace_window_s": 1.5,
                    },
                },
                "interpretation": {
                    "expected_acquisition_evidence_missing": "warning",
                },
            },
        )
        self.assertEqual(reconstructed, policy)

    def test_policy_validates_supported_observation_names(self):
        policy = self._policy()

        policy.validate_supported_observations(
            {"expected_acquisition_evidence_missing"}
        )

    def test_policy_rejects_unsupported_observation_names(self):
        policy = self._policy()

        with self.assertRaisesRegex(
            ValueError,
            "unsupported observations: expected_acquisition_evidence_missing",
        ):
            policy.validate_supported_observations({"acquisition_rate_below"})

    def test_policy_rejects_unknown_consequence_label(self):
        with self.assertRaisesRegex(ValueError, "Unsupported.*labels: stop_camera"):
            AcquisitionHealthPolicy(
                policy_id="invalid-policy",
                evaluation_rules={},
                interpretation={
                    "expected_acquisition_evidence_missing": "stop_camera",
                },
            )

    def _policy(self):
        return AcquisitionHealthPolicy(
            policy_id="camera-required",
            evaluation_rules={
                "first_evidence": {
                    "record_kind": "stream",
                    "grace_window_s": 1.0,
                },
                "gap": {"record_kind": "stream", "max_gap_s": 2.0},
                "rate": {"record_kind": "stream", "minimum_rate_hz": 20.0},
            },
            interpretation={
                "expected_acquisition_evidence_missing": "experiment_failure",
            },
        )


if __name__ == "__main__":
    unittest.main()
