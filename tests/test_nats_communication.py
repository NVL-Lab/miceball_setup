import asyncio
import json
import unittest

from lab_sync_acquisition import (
    ARTIFACT_MANIFEST_EVIDENCE_TYPE,
    Controller,
    DurablePublicationError,
    InMemoryIngestor,
    NatsAcquisitionNodeCommunication,
    NatsCommunicationBoundary,
    RuntimeCommandMessage,
    RuntimeEvidenceMessage,
    RuntimeParticipant,
    RuntimeTelemetryMessage,
    NatsControllerCommunication,
    NatsIngestorCommunication,
    Session,
    SessionConfig,
    SessionLifecycleError,
)


class NatsCommunicationUnitTests(unittest.TestCase):
    def test_controller_fans_group_intent_out_through_jetstream(self):
        jetstream = _PublishingJetStream(stream="LAB_COMMANDS")
        boundary = _PublishingBoundary("controller", "controller-001", jetstream)
        communication = NatsControllerCommunication(boundary)
        participants = (
            RuntimeParticipant("acquisition_node", "node-001"),
            RuntimeParticipant("ingestor", "ingestor-001"),
            RuntimeParticipant("acquisition_node", "node-002"),
        )

        messages = asyncio.run(
            communication.publish_group_command(
                command_id="group-readiness-001",
                session_id="session-001",
                command_type="check_readiness",
                component_type="acquisition_node",
                expected_participants=participants,
                payload={},
            )
        )

        self.assertEqual(jetstream.publish_count, 2)
        self.assertEqual([item.target_id for item in messages], ["node-001", "node-002"])
        self.assertEqual({item.command_id for item in messages}, {"group-readiness-001"})

        results = tuple(
            NatsAcquisitionNodeCommunication(
                _BoundaryIdentity("acquisition_node", message.target_id),
                _CountingAcquisitionNode(),
            ).execute_command(message)
            for message in messages
        )
        self.assertEqual([item.source_id for item in results], ["node-001", "node-002"])
        self.assertTrue(all(item.success for item in results))

    def test_missing_readiness_response_is_unresolved_at_issuer(self):
        communication = NatsControllerCommunication(
            _BoundaryIdentity("controller", "controller-001")
        )
        participants = (
            RuntimeParticipant("acquisition_node", "node-001"),
        )

        outcome = asyncio.run(
            communication.await_group_command_outcome(
                command_id="group-readiness-001",
                session_id="session-001",
                command_type="check_readiness",
                component_type="acquisition_node",
                expected_participants=participants,
                result_window_s=0,
            )
        )

        self.assertEqual(outcome.outcome, "unresolved")
        self.assertEqual(len(outcome.unresolved_outcomes), 1)
        self.assertEqual(outcome.unresolved_outcomes[0].outcome, "unresolved")

    def test_artifact_manifest_uses_evidence_stream_and_ingestor_intake(self):
        jetstream = _PublishingJetStream(stream="LAB_EVIDENCE")
        boundary = _PublishingBoundary(
            "acquisition_node",
            "node-001",
            jetstream,
        )
        node_communication = NatsAcquisitionNodeCommunication(
            boundary,
            _CountingAcquisitionNode(),
        )
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
            is_persistent=True,
        )

        asyncio.run(node_communication.publish_evidence(manifest))
        ingestor = InMemoryIngestor()
        audit = ingestor.receive_runtime_evidence(manifest)

        self.assertEqual(jetstream.publish_count, 1)
        self.assertEqual(jetstream.requested_stream, "LAB_EVIDENCE")
        self.assertEqual(
            jetstream.subject,
            "messages.session-001.evidence.acquisition_node."
            "node-001.artifact_manifest",
        )
        self.assertNotIn("artifact_bytes", jetstream.data["payload"])
        self.assertTrue(jetstream.data["is_persistent"])
        self.assertTrue(audit.accepted)
        self.assertEqual(ingestor.accepted_runtime_evidence, (manifest,))
        self.assertEqual(ingestor.accepted_envelopes, ())
    def test_ingestor_and_controller_consume_evidence_independently(self):
        jetstream = _EvidenceConsumerJetStream()
        controller_boundary = _ConsumerBoundary(
            "controller", "controller-001", jetstream
        )
        ingestor_boundary = _ConsumerBoundary(
            "ingestor", "ingestor-001", jetstream
        )
        controller = Controller(
            _ControllerNode(),
            None,
            None,
            "unused-session-record.json",
        )
        self.assertTrue(controller.create_session(self._session_config()).succeeded)
        controller_communication = NatsControllerCommunication(controller_boundary)
        ingestor = InMemoryIngestor()
        ingestor_communication = NatsIngestorCommunication(
            ingestor_boundary,
            ingestor,
        )
        asyncio.run(
            controller_communication.subscribe_health_interpretation_evidence(
                "session-001",
                controller,
            )
        )
        asyncio.run(
            ingestor_communication.subscribe_evidence("session-001")
        )
        evidence = self._health_interpretation_message()

        delivered = asyncio.run(jetstream.deliver(evidence))

        self.assertEqual(delivered, 2)
        self.assertEqual(len(controller.controller_action_decisions), 1)
        self.assertEqual(
            controller.controller_action_decisions[0].controller_decision,
            "record_warning",
        )
        self.assertEqual(ingestor.accepted_runtime_evidence, (evidence,))
        self.assertEqual(len(ingestor.runtime_evidence_audit), 1)
        self.assertEqual(jetstream.publish_count, 0)

    def test_telemetry_uses_core_nats_without_authoritative_side_effects(self):
        client = _CoreNatsClient()
        boundary = _CoreNatsBoundary(
            "acquisition_node",
            "node-001",
            client,
        )
        controller = Controller(
            _ControllerNode(),
            None,
            None,
            "unused-session-record.json",
        )
        self.assertTrue(controller.create_session(self._session_config()).succeeded)
        ingestor = InMemoryIngestor()
        telemetry_received = []

        async def receive(telemetry):
            telemetry_received.append(telemetry)

        asyncio.run(
            boundary.subscribe_telemetry(
                "messages.session-001.telemetry.>",
                receive,
            )
        )
        telemetry = RuntimeTelemetryMessage(
            session_id="session-001",
            telemetry_type="preview_status",
            source_id="node-001",
            payload={"visible": True},
        )
        asyncio.run(boundary.publish_telemetry(telemetry))
        asyncio.run(client.deliver(telemetry))

        self.assertEqual(telemetry_received, [telemetry])
        self.assertEqual(client.publish_count, 1)
        self.assertEqual(controller.controller_action_decisions, ())
        self.assertEqual(controller.get_status()["session_state"], "created")
        self.assertEqual(ingestor.accepted_runtime_evidence, ())
        self.assertEqual(ingestor.runtime_evidence_audit, ())

    def test_successful_durable_publication_requires_intended_stream_ack(self):
        jetstream = _PublishingJetStream(stream="LAB_COMMANDS")
        boundary = _PublishingBoundary("controller", "controller-001", jetstream)
        message = self._command_message()

        result = asyncio.run(
            boundary.publish_command(message, "acquisition_node")
        )

        self.assertIsNone(result)
        self.assertEqual(jetstream.publish_count, 1)
        self.assertEqual(jetstream.requested_stream, "LAB_COMMANDS")

    def test_failed_durable_publication_reports_debugging_context(self):
        jetstream = _PublishingJetStream(error=ConnectionError("broker unavailable"))
        boundary = _PublishingBoundary("controller", "controller-001", jetstream)
        message = self._command_message()

        with self.assertRaises(DurablePublicationError) as caught:
            asyncio.run(boundary.publish_command(message, "acquisition_node"))

        error = caught.exception
        self.assertEqual(error.message_class, "command")
        self.assertEqual(error.message_id, "command-publication")
        self.assertEqual(
            error.subject,
            "messages.session-001.command.acquisition_node."
            "node-001.start_runtime",
        )
        self.assertEqual(error.intended_stream, "LAB_COMMANDS")
        self.assertEqual(error.reason, "broker unavailable")
        self.assertIn("broker unavailable", str(error))

    def test_failed_publication_attempts_once_and_leaves_message_with_caller(self):
        jetstream = _PublishingJetStream(error=RuntimeError("publish rejected"))
        boundary = _PublishingBoundary("controller", "controller-001", jetstream)
        message = self._command_message()
        original_data = message.to_dict()

        with self.assertRaises(DurablePublicationError):
            asyncio.run(boundary.publish_command(message, "acquisition_node"))

        self.assertEqual(jetstream.publish_count, 1)
        self.assertEqual(message.to_dict(), original_data)

    def test_wrong_stream_ack_is_failed_publication(self):
        boundary = _PublishingBoundary(
            "controller",
            "controller-001",
            _PublishingJetStream(stream="UNEXPECTED_STREAM"),
        )

        with self.assertRaisesRegex(
            DurablePublicationError,
            "unexpected stream UNEXPECTED_STREAM",
        ):
            asyncio.run(
                boundary.publish_command(
                    self._command_message(),
                    "acquisition_node",
                )
            )

    def test_session_config_is_authoritative_for_expected_runtime_participants(self):
        participant = RuntimeParticipant("acquisition_node", "node-001")
        config = SessionConfig(
            session_id="session-001",
            selected_devices=[],
            storage_location="placeholder://session",
            protocol_plan={"name": "phase-10-readiness"},
            error_evidence_location="placeholder://errors",
            expected_runtime_participants=(participant,),
        )
        controller = Controller(None, None, None, "unused-session-record.json")

        result = controller.create_session(config)

        self.assertTrue(result.succeeded)
        self.assertEqual(controller.expected_runtime_participants, (participant,))
        self.assertEqual(
            config.to_dict()["expected_runtime_participants"],
            [participant.to_dict()],
        )

    def test_readiness_command_returns_existing_node_readiness_evidence(self):
        node = _CountingAcquisitionNode()
        adapter = NatsAcquisitionNodeCommunication(
            _BoundaryIdentity("acquisition_node", "node-001"),
            node,
        )

        result = adapter.execute_command(
            RuntimeCommandMessage(
                command_id="command-readiness",
                session_id="session-001",
                command_type="check_readiness",
                source_id="controller-001",
                target_id="node-001",
                payload={},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(
            result.payload["acquisition_node_readiness"],
            {
                "node_id": "node-001",
                "session_id": "session-001",
                "role": "acquisition_node",
                "device_readiness": [],
                "service_readiness": [],
                "ready": True,
            },
        )

    def test_disconnected_nats_readiness_blocks_session_initialization(self):
        session = Session("session-001", self._session_config())
        readiness = NatsCommunicationBoundary(
            "controller", "controller-001"
        ).check_ready()

        with self.assertRaises(SessionLifecycleError):
            session.initialize(service_readiness=(readiness,))

        self.assertFalse(readiness.ready)

    def test_connected_nats_readiness_allows_existing_session_gate(self):
        session = Session("session-001", self._session_config())
        readiness = _ConnectedBoundary(
            "controller", "controller-001"
        ).check_ready()

        session.initialize(service_readiness=(readiness,))

        self.assertTrue(readiness.ready)
        self.assertEqual(session.current_state.value, "initialized")

    def test_boundary_rejects_message_source_identity_mismatch(self):
        boundary = NatsCommunicationBoundary("controller", "controller-001")

        with self.assertRaisesRegex(ValueError, "source_id does not match"):
            asyncio.run(
                boundary.publish_command(
                    RuntimeCommandMessage(
                        command_id="command-identity",
                        session_id="session-001",
                        command_type="start_runtime",
                        source_id="different-controller",
                        target_id="node-001",
                        payload={},
                    ),
                    "acquisition_node",
                )
            )

    def test_ingestor_accepts_and_audits_runtime_evidence_separately(self):
        ingestor = InMemoryIngestor()
        evidence = RuntimeEvidenceMessage(
            evidence_id="evidence-001",
            session_id="session-001",
            evidence_type="health_interpretation",
            source_id="node-001",
            payload={"interpretation_label": "warning"},
        )

        audit = ingestor.receive_runtime_evidence(evidence)

        self.assertTrue(audit.accepted)
        self.assertEqual(ingestor.accepted_runtime_evidence, (evidence,))
        self.assertEqual(ingestor.runtime_evidence_audit, (audit,))
        self.assertEqual(ingestor.accepted_envelopes, ())
        self.assertEqual(
            ingestor.compile_persistent_runtime_evidence(),
            {
                "runtime_evidence": (),
                "ingest_audit": (audit,),
            },
        )

    def test_ingestor_compiles_only_flagged_persistent_runtime_evidence(self):
        ingestor = InMemoryIngestor()
        nonpersistent = RuntimeEvidenceMessage(
            evidence_id="evidence-nonpersistent",
            session_id="session-001",
            evidence_type="runtime_note",
            source_id="node-001",
            payload={},
        )
        persistent = RuntimeEvidenceMessage(
            evidence_id="evidence-persistent",
            session_id="session-001",
            evidence_type="mapping_update_evidence",
            source_id="synchronization",
            payload={"update_type": "created"},
            is_persistent=True,
        )

        first_audit = ingestor.receive_runtime_evidence(nonpersistent)
        second_audit = ingestor.receive_runtime_evidence(persistent)

        self.assertTrue(first_audit.accepted)
        self.assertTrue(second_audit.accepted)
        self.assertEqual(
            ingestor.accepted_runtime_evidence,
            (nonpersistent, persistent),
        )
        self.assertEqual(
            ingestor.compile_persistent_runtime_evidence(),
            {
                "runtime_evidence": (persistent,),
                "ingest_audit": (first_audit, second_audit),
            },
        )

    def test_command_duplicate_detection_reuses_previous_result(self):
        node = _CountingAcquisitionNode()
        adapter = NatsAcquisitionNodeCommunication(
            _BoundaryIdentity("acquisition_node", "node-001"),
            node,
        )
        command = RuntimeCommandMessage(
            command_id="command-001",
            session_id="session-001",
            command_type="start_runtime",
            source_id="controller-001",
            target_id="node-001",
            payload={},
        )

        first = adapter.execute_command(command)
        duplicate = adapter.execute_command(command)

        self.assertEqual(duplicate, first)
        self.assertEqual(node.start_count, 1)

    def test_command_subscription_is_scoped_to_acquisition_node_session(self):
        boundary = _SubscribingBoundary("acquisition_node", "node-001")
        adapter = NatsAcquisitionNodeCommunication(
            boundary,
            _CountingAcquisitionNode(),
        )

        subject = asyncio.run(adapter.subscribe_commands())

        self.assertEqual(
            subject,
            "messages.session-001.command.acquisition_node.node-001.>",
        )

    def test_unsupported_command_returns_failed_result(self):
        adapter = NatsAcquisitionNodeCommunication(
            _BoundaryIdentity("acquisition_node", "node-001"),
            _CountingAcquisitionNode(),
        )

        result = adapter.execute_command(
            RuntimeCommandMessage(
                command_id="command-unsupported",
                session_id="session-001",
                command_type="experiment_abort",
                source_id="controller-001",
                target_id="node-001",
                payload={},
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertIn("Unsupported AcquisitionNode command", result.reason)

    def test_stop_runtime_result_preserves_final_session_time(self):
        adapter = NatsAcquisitionNodeCommunication(
            _BoundaryIdentity("acquisition_node", "node-001"),
            _CountingAcquisitionNode(),
        )

        result = adapter.execute_command(
            RuntimeCommandMessage(
                command_id="command-stop",
                session_id="session-001",
                command_type="stop_runtime",
                source_id="controller-001",
                target_id="node-001",
                payload={},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.payload, {"final_session_time_s": 1.0})

    @staticmethod
    def _session_config():
        return SessionConfig(
            session_id="session-001",
            selected_devices=[],
            storage_location="placeholder://session",
            protocol_plan={"name": "phase-10-readiness"},
            error_evidence_location="placeholder://errors",
            expected_runtime_participants=(
                RuntimeParticipant("acquisition_node", "node-001"),
            ),
        )

    @staticmethod
    def _command_message():
        return RuntimeCommandMessage(
            command_id="command-publication",
            session_id="session-001",
            command_type="start_runtime",
            source_id="controller-001",
            target_id="node-001",
            payload={},
        )

    @staticmethod
    def _health_interpretation_message():
        return RuntimeEvidenceMessage(
            evidence_id="evidence-health-001",
            session_id="session-001",
            evidence_type="health_interpretation",
            source_id="node-001",
            payload={
                "originating_observation_id": "observation-001",
                "experiment_id": "experiment-001",
                "live_source_id": "camera-source-001",
                "expected_participant_id": "camera-001",
                "observation_type": "frame_gap",
                "acquisition_health_policy": "camera-policy",
                "interpretation_label": "warning",
                "required": True,
                "session_time_s": 1.25,
                "details": {"gap_s": 2.0},
            },
            is_persistent=True,
        )


class _BoundaryIdentity:
    def __init__(self, component_type, component_id):
        self.component_type = component_type
        self.component_id = component_id


class _ConnectedBoundary(NatsCommunicationBoundary):
    @property
    def connected(self):
        return True


class _PublishingBoundary(NatsCommunicationBoundary):
    def __init__(self, component_type, component_id, jetstream):
        super().__init__(component_type, component_id)
        self._publishing_jetstream = jetstream

    def _require_jetstream(self):
        return self._publishing_jetstream


class _ConsumerBoundary(_BoundaryIdentity):
    def __init__(self, component_type, component_id, jetstream):
        super().__init__(component_type, component_id)
        self._consumer_jetstream = jetstream

    def _require_jetstream(self):
        return self._consumer_jetstream


class _EvidenceConsumerJetStream:
    def __init__(self):
        self.callbacks = []
        self.publish_count = 0

    async def subscribe(self, _subject, cb, **_options):
        self.callbacks.append(cb)
        return len(self.callbacks)

    async def deliver(self, evidence):
        for callback in self.callbacks:
            await callback(_DeliveredMessage(evidence.to_dict()))
        return len(self.callbacks)


class _DeliveredMessage:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")
        self.acknowledged = False

    async def ack(self):
        self.acknowledged = True


class _CoreNatsBoundary(NatsCommunicationBoundary):
    def __init__(self, component_type, component_id, client):
        super().__init__(component_type, component_id)
        self._core_client = client

    def _require_client(self):
        return self._core_client


class _CoreNatsClient:
    def __init__(self):
        self.callback = None
        self.publish_count = 0

    async def subscribe(self, _subject, cb):
        self.callback = cb
        return "core-subscription"

    async def publish(self, _subject, _data):
        self.publish_count += 1

    async def deliver(self, telemetry):
        await self.callback(_DeliveredMessage(telemetry.to_dict()))


class _PublishingJetStream:
    def __init__(self, stream=None, error=None):
        self.stream = stream
        self.error = error
        self.publish_count = 0
        self.requested_stream = None
        self.subject = None
        self.data = None

    async def publish(self, subject, payload, stream):
        self.publish_count += 1
        self.requested_stream = stream
        self.subject = subject
        self.data = json.loads(payload.decode("utf-8"))
        if self.error is not None:
            raise self.error
        return _PublishAcknowledgement(self.stream)


class _PublishAcknowledgement:
    def __init__(self, stream):
        self.stream = stream


class _SubscribingBoundary(_BoundaryIdentity):
    def __init__(self, component_type, component_id):
        super().__init__(component_type, component_id)
        self._jetstream = _CapturingJetStream()

    def _require_jetstream(self):
        return self._jetstream


class _CapturingJetStream:
    async def subscribe(self, subject, **_options):
        return subject


class _Summary:
    iteration_index = 1
    collections_seen = 0
    envelopes_sent = 0
    accepted_count = 0
    rejected_count = 0


class _CountingAcquisitionNode:
    def __init__(self):
        self.start_count = 0
        self.health_interpretation_evidence = ()

    def status(self):
        return {"session_id": "session-001"}

    def start_runtime(self):
        self.start_count += 1
        return {"session_time_s": 0.0}

    def check_node_readiness(self):
        return _ReadyNodeEvidence()

    def run_one_iteration(self):
        return _Summary()

    def stop_runtime(self):
        return {"final_session_time_s": 1.0}


class _ControllerNode:
    def status(self):
        return {"session_id": "session-001", "is_running": False}


class _ReadyNodeEvidence:
    def to_dict(self):
        return {
            "node_id": "node-001",
            "session_id": "session-001",
            "role": "acquisition_node",
            "device_readiness": [],
            "service_readiness": [],
            "ready": True,
        }


if __name__ == "__main__":
    unittest.main()
