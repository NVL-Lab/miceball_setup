import unittest

import lab_sync_acquisition.communication as communication
from lab_sync_acquisition import (
    ARTIFACT_MANIFEST_EVIDENCE_TYPE,
    COMMAND_RESULT_STATUSES,
    GroupCommandOutcome,
    LAB_COMMAND_RESULTS,
    LAB_COMMANDS,
    LAB_EVIDENCE,
    RUNTIME_CONTROL_COMMAND_RESULT_STATUSES,
    RuntimeCommandMessage,
    RuntimeCommandResultMessage,
    RuntimeEvidenceMessage,
    RuntimeParticipant,
    RuntimeTelemetryMessage,
    UnresolvedCommandOutcome,
    aggregate_group_command_results,
    build_group_command_messages,
    build_runtime_subject,
    parse_runtime_subject,
)


class RuntimeCommunicationTests(unittest.TestCase):
    def test_group_command_fans_out_to_configured_component_group(self):
        participants = (
            RuntimeParticipant("acquisition_node", "node-001"),
            RuntimeParticipant("ingestor", "ingestor-001"),
            RuntimeParticipant("acquisition_node", "node-002"),
        )

        messages = build_group_command_messages(
            command_id="command-group-001",
            session_id="session-001",
            command_type="check_readiness",
            source_id="controller-001",
            component_type="acquisition_node",
            expected_participants=participants,
            payload={},
        )

        self.assertEqual([item.target_id for item in messages], ["node-001", "node-002"])
        self.assertEqual({item.command_id for item in messages}, {"command-group-001"})

    def test_issuer_aggregation_records_missing_result_as_unresolved(self):
        participants = (
            RuntimeParticipant("acquisition_node", "node-001"),
            RuntimeParticipant("acquisition_node", "node-002"),
        )
        result = RuntimeCommandResultMessage(
            result_id="result-001",
            command_id="command-group-001",
            session_id="session-001",
            source_id="node-001",
            target_id="controller-001",
            status="succeeded",
            success=True,
            reason=None,
            payload={"ready": True},
        )

        outcome = aggregate_group_command_results(
            command_id="command-group-001",
            session_id="session-001",
            command_type="check_readiness",
            component_type="acquisition_node",
            expected_participants=participants,
            command_results=(result,),
        )

        self.assertEqual(outcome.outcome, "unresolved")
        self.assertEqual(outcome.command_results, (result,))
        self.assertEqual(len(outcome.unresolved_outcomes), 1)
        self.assertEqual(
            outcome.unresolved_outcomes[0].expected_target_id,
            "node-002",
        )
        self.assertEqual(outcome.unresolved_outcomes[0].outcome, "unresolved")
        self.assertEqual(GroupCommandOutcome.from_dict(outcome.to_dict()), outcome)
        self.assertEqual(
            UnresolvedCommandOutcome.from_dict(
                outcome.unresolved_outcomes[0].to_dict()
            ),
            outcome.unresolved_outcomes[0],
        )

    def test_artifact_manifest_round_trips_as_runtime_evidence(self):
        manifest = RuntimeEvidenceMessage(
            evidence_id="artifact-manifest-001",
            session_id="session-001",
            evidence_type=ARTIFACT_MANIFEST_EVIDENCE_TYPE,
            source_id="node-001",
            payload={
                "artifact_id": "camera-video-001",
                "artifact_type": "video",
                "lifecycle_moment": "closed",
                "local_reference": "camera/video-001",
            },
        )

        reconstructed = RuntimeEvidenceMessage.from_dict(manifest.to_dict())

        self.assertEqual(reconstructed, manifest)
        self.assertEqual(
            reconstructed.evidence_type,
            ARTIFACT_MANIFEST_EVIDENCE_TYPE,
        )

    def test_artifact_manifest_rejects_artifact_bytes(self):
        with self.assertRaisesRegex(ValueError, "JSON-like plain data"):
            RuntimeEvidenceMessage(
                evidence_id="artifact-manifest-bytes",
                session_id="session-001",
                evidence_type=ARTIFACT_MANIFEST_EVIDENCE_TYPE,
                source_id="node-001",
                payload={"artifact_bytes": b"not-control-plane-data"},
            )

    def test_runtime_participant_round_trips_as_plain_configuration(self):
        participant = RuntimeParticipant(
            component_type="acquisition_node",
            component_id="node-001",
        )

        self.assertEqual(
            RuntimeParticipant.from_dict(participant.to_dict()),
            participant,
        )

    def test_runtime_messages_round_trip_as_plain_data(self):
        messages = (
            RuntimeCommandMessage(
                command_id="command-001",
                session_id="session-001",
                command_type="start_runtime",
                source_id="controller-001",
                target_id="acquisition-node-001",
                payload={"requested": True, "options": [1, None, "bounded"]},
            ),
            RuntimeCommandResultMessage(
                result_id="result-001",
                command_id="command-001",
                session_id="session-001",
                source_id="acquisition-node-001",
                target_id="controller-001",
                status="succeeded",
                success=True,
                reason=None,
                payload={"runtime_active": True},
            ),
            RuntimeEvidenceMessage(
                evidence_id="evidence-001",
                session_id="session-001",
                evidence_type="health_interpretation",
                source_id="acquisition-node-001",
                payload={"session_time_s": 1.25, "required": True},
            ),
            RuntimeTelemetryMessage(
                session_id="session-001",
                telemetry_type="camera_preview_status",
                source_id="acquisition-node-001",
                payload={"frames_seen": 10, "preview": None},
            ),
        )

        for message in messages:
            plain_data = message.to_dict()
            reconstructed = type(message).from_dict(plain_data)
            self.assertEqual(reconstructed, message)
            self.assertIsInstance(plain_data, dict)

    def test_payload_rejects_non_plain_runtime_objects(self):
        with self.assertRaisesRegex(ValueError, "JSON-like plain data"):
            RuntimeEvidenceMessage(
                evidence_id="evidence-001",
                session_id="session-001",
                evidence_type="invalid",
                source_id="source-001",
                payload={"live_object": object()},
            )

    def test_runtime_subject_builds_and_parses_routing_fields(self):
        subject = build_runtime_subject(
            session_id="session-001",
            message_class="command_result",
            component_type="acquisition_node",
            component_id="node-001",
            message_type="start_runtime",
        )

        self.assertEqual(
            subject,
            "messages.session-001.command_result."
            "acquisition_node.node-001.start_runtime",
        )
        self.assertEqual(
            parse_runtime_subject(subject),
            {
                "session_id": "session-001",
                "message_class": "command_result",
                "component_type": "acquisition_node",
                "component_id": "node-001",
                "message_type": "start_runtime",
            },
        )

    def test_runtime_subject_rejects_invalid_message_class(self):
        with self.assertRaisesRegex(ValueError, "Unsupported runtime message class"):
            build_runtime_subject(
                "session-001",
                "artifact",
                "acquisition_node",
                "node-001",
                "artifact_bytes",
            )

    def test_stream_subject_constants_exclude_telemetry(self):
        self.assertEqual(LAB_COMMANDS, "messages.*.command.>")
        self.assertEqual(
            LAB_COMMAND_RESULTS,
            "messages.*.command_result.>",
        )
        self.assertEqual(LAB_EVIDENCE, "messages.*.evidence.>")
        self.assertFalse(
            any(
                "TELEMETRY" in name
                for name in vars(communication)
                if name.isupper()
            )
        )

    def test_command_result_status_vocabulary_is_validated(self):
        self.assertEqual(
            COMMAND_RESULT_STATUSES,
            frozenset({"accepted", "progress", "succeeded", "failed"}),
        )
        self.assertEqual(
            RUNTIME_CONTROL_COMMAND_RESULT_STATUSES,
            frozenset({"succeeded", "failed"}),
        )
        for status in COMMAND_RESULT_STATUSES:
            RuntimeCommandResultMessage(
                result_id=f"result-{status}",
                command_id="command-001",
                session_id="session-001",
                source_id="node-001",
                target_id="controller-001",
                status=status,
                success=status == "succeeded",
                reason=None,
                payload={},
            )
        with self.assertRaisesRegex(ValueError, "Unsupported command result status"):
            RuntimeCommandResultMessage(
                result_id="result-invalid",
                command_id="command-001",
                session_id="session-001",
                source_id="node-001",
                target_id="controller-001",
                status="timed_out",
                success=False,
                reason="not part of Phase 10 status vocabulary",
                payload={},
            )


if __name__ == "__main__":
    unittest.main()
