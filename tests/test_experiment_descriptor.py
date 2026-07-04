import unittest

from lab_sync_acquisition import ExperimentDescriptor, ExpectedParticipant


class ExperimentDescriptorTests(unittest.TestCase):
    def test_expected_participants_round_trip_as_ordered_plain_data(self):
        participants = (
            ExpectedParticipant(
                participant_id="camera-001",
                participant_type="device",
                expected_contribution="camera_frame_metadata",
                required=True,
            ),
            ExpectedParticipant(
                participant_id="decoder-001",
                participant_type="decoder",
                expected_contribution="decoder_predictions",
                required=False,
            ),
        )
        descriptor = ExperimentDescriptor(
            experiment_id="baseline-001",
            details={"protocol": "baseline"},
            expected_participants=participants,
        )

        plain_data = descriptor.to_dict()
        reconstructed = ExperimentDescriptor.from_dict(plain_data)

        self.assertEqual(reconstructed, descriptor)
        self.assertEqual(reconstructed.expected_participants, participants)
        self.assertEqual(
            plain_data["expected_participants"],
            [participant.to_dict() for participant in participants],
        )


if __name__ == "__main__":
    unittest.main()
