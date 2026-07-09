"""NATS communication boundary for Phase 10 runtime messages."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import nats
from nats.aio.client import Client as NATS
from nats.aio.subscription import Subscription
from nats.js.api import StorageType, StreamConfig
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError

from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.acquisition_health import HealthInterpretationEvidence
from lab_sync_acquisition.communication import (
    GroupCommandOutcome,
    LAB_COMMAND_RESULTS,
    LAB_COMMANDS,
    LAB_EVIDENCE,
    RuntimeCommandMessage,
    RuntimeCommandResultMessage,
    RuntimeEvidenceMessage,
    RuntimeParticipant,
    RuntimeTelemetryMessage,
    build_runtime_subject,
    aggregate_group_command_results,
    build_group_command_messages,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.controller import Controller, ControllerActionDecision
from lab_sync_acquisition.service_readiness import ServiceReadiness


RuntimeResultCallback = Callable[[RuntimeCommandResultMessage], Awaitable[None]]
RuntimeEvidenceCallback = Callable[[RuntimeEvidenceMessage], Awaitable[None]]
ControllerDecisionCallback = Callable[[ControllerActionDecision], Awaitable[None]]
RuntimeTelemetryCallback = Callable[[RuntimeTelemetryMessage], Awaitable[None]]

logger = logging.getLogger(__name__)


class DurablePublicationError(RuntimeError):
    """Explicit failure to obtain intended JetStream stream acceptance."""

    def __init__(
        self,
        message_class: str,
        message_id: str,
        subject: str,
        intended_stream: str,
        reason: str,
    ) -> None:
        self.message_class = message_class
        self.message_id = message_id
        self.subject = subject
        self.intended_stream = intended_stream
        self.reason = reason
        super().__init__(
            "Durable publication failed: "
            f"message_class={message_class}, message_id={message_id}, "
            f"subject={subject}, intended_stream={intended_stream}, "
            f"reason={reason}"
        )


class NatsCommunicationBoundary:
    """Own NATS connection, serialization, routing, and acknowledgement mechanics."""

    def __init__(
        self,
        component_type: str,
        component_id: str,
        servers: tuple[str, ...] = ("nats://127.0.0.1:4222",),
    ) -> None:
        self.component_type = component_type
        self.component_id = component_id
        self.servers = servers
        self._client: NATS | None = None
        self._jetstream: JetStreamContext | None = None

    @property
    def connected(self) -> bool:
        """Whether the underlying NATS client is connected."""

        return self._client is not None and self._client.is_connected

    def check_ready(self) -> ServiceReadiness:
        """Report NATS availability through the existing service contract."""

        ready = self.connected
        return ServiceReadiness(
            component_id="nats",
            component_type="communication",
            required=True,
            ready=ready,
            reason="connected" if ready else "not_connected",
        )

    async def connect(self) -> None:
        """Connect to NATS without adding reconnect or recovery policy."""

        self._client = await nats.connect(
            servers=list(self.servers),
            allow_reconnect=False,
        )
        self._jetstream = self._client.jetstream()

    async def close(self) -> None:
        """Drain and close the current NATS connection."""

        if self._client is not None and not self._client.is_closed:
            await self._client.drain()
        self._client = None
        self._jetstream = None

    async def flush(self) -> None:
        """Synchronize pending Core NATS protocol operations with the server."""

        await self._require_client().flush()

    async def ensure_streams(self) -> None:
        """Create the three accepted durable streams when absent."""

        jetstream = self._require_jetstream()
        for stream_name, subject in (
            ("LAB_COMMANDS", LAB_COMMANDS),
            ("LAB_COMMAND_RESULTS", LAB_COMMAND_RESULTS),
            ("LAB_EVIDENCE", LAB_EVIDENCE),
        ):
            try:
                await jetstream.stream_info(stream_name)
            except NotFoundError:
                await jetstream.add_stream(
                    config=StreamConfig(
                        name=stream_name,
                        subjects=[subject],
                        storage=StorageType.FILE,
                    )
                )

    async def publish_command(
        self,
        message: RuntimeCommandMessage,
        target_component_type: str,
    ) -> None:
        """Publish a durable command and require JetStream acceptance."""

        self._validate_source_id(message.source_id)
        subject = build_runtime_subject(
            message.session_id,
            "command",
            target_component_type,
            message.target_id,
            message.command_type,
        )
        await self._publish_durable(
            subject,
            message.to_dict(),
            "LAB_COMMANDS",
            "command",
            message.command_id,
        )
        logger.info(
            "command_published command_id=%s subject=%s",
            message.command_id,
            subject,
        )

    async def publish_command_result(
        self,
        message: RuntimeCommandResultMessage,
        message_type: str,
    ) -> None:
        """Publish a durable command result and require stream acceptance."""

        self._validate_source_id(message.source_id)
        subject = build_runtime_subject(
            message.session_id,
            "command_result",
            self.component_type,
            self.component_id,
            message_type,
        )
        await self._publish_durable(
            subject,
            message.to_dict(),
            "LAB_COMMAND_RESULTS",
            "command_result",
            message.result_id,
        )

    async def publish_evidence(self, message: RuntimeEvidenceMessage) -> None:
        """Publish durable evidence once through the evidence stream."""

        self._validate_source_id(message.source_id)
        subject = build_runtime_subject(
            message.session_id,
            "evidence",
            self.component_type,
            self.component_id,
            message.evidence_type,
        )
        await self._publish_durable(
            subject,
            message.to_dict(),
            "LAB_EVIDENCE",
            "evidence",
            message.evidence_id,
        )

    async def publish_telemetry(self, message: RuntimeTelemetryMessage) -> None:
        """Publish transient telemetry through Core NATS only."""

        self._validate_source_id(message.source_id)
        client = self._require_client()
        subject = build_runtime_subject(
            message.session_id,
            "telemetry",
            self.component_type,
            self.component_id,
            message.telemetry_type,
        )
        await client.publish(subject, self._encode(message.to_dict()))

    async def subscribe_telemetry(
        self,
        subject: str,
        callback: RuntimeTelemetryCallback,
    ) -> Subscription:
        """Subscribe to transient telemetry without JetStream persistence."""

        async def receive(message: Any) -> None:
            telemetry = RuntimeTelemetryMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            await callback(telemetry)

        return await self._require_client().subscribe(subject, cb=receive)

    async def _publish_durable(
        self,
        subject: str,
        data: dict[str, Any],
        stream: str,
        message_class: str,
        message_id: str,
    ) -> None:
        try:
            acknowledgement = await self._require_jetstream().publish(
                subject,
                self._encode(data),
                stream=stream,
            )
        except Exception as error:
            raise DurablePublicationError(
                message_class=message_class,
                message_id=message_id,
                subject=subject,
                intended_stream=stream,
                reason=str(error),
            ) from error
        if acknowledgement.stream != stream:
            raise DurablePublicationError(
                message_class=message_class,
                message_id=message_id,
                subject=subject,
                intended_stream=stream,
                reason=(
                    "JetStream acknowledged unexpected stream "
                    f"{acknowledgement.stream}"
                ),
            )

    def _require_client(self) -> NATS:
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("NATS communication boundary is not connected")
        return self._client

    def _require_jetstream(self) -> JetStreamContext:
        self._require_client()
        if self._jetstream is None:
            raise RuntimeError("JetStream context is unavailable")
        return self._jetstream

    @staticmethod
    def _encode(data: dict[str, Any]) -> bytes:
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

    def _validate_source_id(self, source_id: str) -> None:
        if source_id != self.component_id:
            raise ValueError(
                "Runtime message source_id does not match communication boundary"
            )


class NatsControllerCommunication:
    """Controller-side command publication and command-result consumption."""

    def __init__(self, boundary: NatsCommunicationBoundary) -> None:
        self._boundary = boundary
        self._command_results: tuple[RuntimeCommandResultMessage, ...] = ()
        self._command_result_events: dict[str, asyncio.Event] = {}

    @property
    def command_results(self) -> tuple[RuntimeCommandResultMessage, ...]:
        """Command results received in delivery order."""

        return self._command_results

    async def publish_command(
        self,
        message: RuntimeCommandMessage,
        target_component_type: str = "acquisition_node",
    ) -> None:
        """Publish one Controller-created command through JetStream."""

        await self._boundary.publish_command(message, target_component_type)

    async def publish_group_command(
        self,
        command_id: str,
        session_id: str,
        command_type: str,
        component_type: str,
        expected_participants: tuple[RuntimeParticipant, ...],
        payload: dict[str, Any],
    ) -> tuple[RuntimeCommandMessage, ...]:
        """Fan one command intent out to configured members of a component group."""

        messages = build_group_command_messages(
            command_id=command_id,
            session_id=session_id,
            command_type=command_type,
            source_id=self._boundary.component_id,
            component_type=component_type,
            expected_participants=expected_participants,
            payload=payload,
        )
        for message in messages:
            await self._boundary.publish_command(message, component_type)
        return messages

    async def await_group_command_outcome(
        self,
        command_id: str,
        session_id: str,
        command_type: str,
        component_type: str,
        expected_participants: tuple[RuntimeParticipant, ...],
        result_window_s: float,
    ) -> GroupCommandOutcome:
        """Wait the issuer-defined result window and record missing targets."""

        if result_window_s < 0:
            raise ValueError("result_window_s must be non-negative")
        expected_ids = {
            participant.component_id
            for participant in expected_participants
            if participant.component_type == component_type
        }
        deadline = asyncio.get_running_loop().time() + result_window_s
        event = self._command_result_events.setdefault(command_id, asyncio.Event())
        while not expected_ids.issubset(
            {
                result.source_id
                for result in self._command_results
                if result.command_id == command_id
                and result.session_id == session_id
            }
        ):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except TimeoutError:
                break
        return aggregate_group_command_results(
            command_id=command_id,
            session_id=session_id,
            command_type=command_type,
            component_type=component_type,
            expected_participants=expected_participants,
            command_results=self._command_results,
            unresolved_reason=(
                "Expected command result was not received within "
                f"the issuer-defined {result_window_s} second window"
            ),
        )

    async def subscribe_command_results(
        self,
        session_id: str,
        callback: RuntimeResultCallback | None = None,
    ) -> Subscription:
        """Consume durable results addressed to this command issuer."""

        subject = f"messages.{session_id}.command_result.>"

        async def receive(message: Any) -> None:
            result = RuntimeCommandResultMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            if result.target_id != self._boundary.component_id:
                await message.ack()
                return
            self._command_results = self._command_results + (result,)
            event = self._command_result_events.get(result.command_id)
            if event is not None:
                event.set()
            logger.info(
                "command_result_received command_id=%s status=%s",
                result.command_id,
                result.status,
            )
            if callback is not None:
                await callback(result)
            await message.ack()

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )

    async def subscribe_health_interpretation_evidence(
        self,
        session_id: str,
        controller: Controller,
        callback: ControllerDecisionCallback | None = None,
    ) -> Subscription:
        """Consume decision-relevant evidence without relaying or republishing it."""

        subject = f"messages.{session_id}.evidence.>"

        async def receive(message: Any) -> None:
            evidence_message = RuntimeEvidenceMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            if evidence_message.evidence_type != "health_interpretation":
                await message.ack()
                return
            interpretation = HealthInterpretationEvidence.from_dict(
                evidence_message.payload
            )
            decision = controller.process_health_interpretation(interpretation)
            if callback is not None:
                await callback(decision)
            await message.ack()

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )


class NatsAcquisitionNodeCommunication:
    """NATS adapter that invokes supported public AcquisitionNode commands."""

    SUPPORTED_COMMAND_TYPES = frozenset(
        {
            "check_readiness",
            "start_runtime",
            "run_one_iteration",
            "stop_runtime",
        }
    )

    def __init__(
        self,
        boundary: NatsCommunicationBoundary,
        acquisition_node: AcquisitionNode,
    ) -> None:
        self._boundary = boundary
        self._acquisition_node = acquisition_node
        self._results_by_command_id: dict[str, RuntimeCommandResultMessage] = {}
        self._published_health_interpretation_count = 0

    async def subscribe_commands(self) -> Subscription:
        """Consume commands routed to this AcquisitionNode instance."""

        session_id = self._acquisition_node.status()["session_id"]
        subject = (
            f"messages.{session_id}.command.acquisition_node."
            f"{self._boundary.component_id}.>"
        )

        async def receive(message: Any) -> None:
            try:
                command = RuntimeCommandMessage.from_dict(
                    json.loads(message.data.decode("utf-8"))
                )
                logger.info(
                    "command_received command_id=%s command_type=%s",
                    command.command_id,
                    command.command_type,
                )
                if command.target_id != self._boundary.component_id:
                    await message.ack()
                    return
                result = self.execute_command(command)
                await self._boundary.publish_command_result(
                    result,
                    command.command_type,
                )
                logger.info(
                    "command_result_published command_id=%s status=%s",
                    result.command_id,
                    result.status,
                )
                await self.publish_new_health_interpretation_evidence(
                    command.session_id
                )
                await message.ack()
            except Exception:
                logger.exception("command_delivery_processing_failed")
                raise

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )

    def execute_command(
        self,
        command: RuntimeCommandMessage,
    ) -> RuntimeCommandResultMessage:
        """Execute one supported command once and return explicit result evidence."""

        previous = self._results_by_command_id.get(command.command_id)
        if previous is not None:
            return previous

        logger.info(
            "execute_command_entered command_id=%s command_type=%s",
            command.command_id,
            command.command_type,
        )

        try:
            if command.session_id != self._acquisition_node.status()["session_id"]:
                raise RuntimeError("Command session_id does not match AcquisitionNode")
            if command.command_type == "check_readiness":
                readiness = self._acquisition_node.check_node_readiness()
                payload = {
                    "acquisition_node_readiness": readiness.to_dict(),
                }
            elif command.command_type == "start_runtime":
                outcome = self._acquisition_node.start_runtime()
                payload = {"session_time_s": outcome["session_time_s"]}
            elif command.command_type == "run_one_iteration":
                summary = self._acquisition_node.run_one_iteration()
                payload = {
                    "iteration_index": summary.iteration_index,
                    "collections_seen": summary.collections_seen,
                    "envelopes_sent": summary.envelopes_sent,
                    "accepted_count": summary.accepted_count,
                    "rejected_count": summary.rejected_count,
                }
            elif command.command_type == "stop_runtime":
                outcome = self._acquisition_node.stop_runtime()
                payload = {
                    "final_session_time_s": outcome["final_session_time_s"]
                }
            else:
                raise ValueError(
                    f"Unsupported AcquisitionNode command: {command.command_type}"
                )
            result = self._result(command, "succeeded", True, None, payload)
        except Exception as error:
            result = self._result(command, "failed", False, str(error), {})
        self._results_by_command_id[command.command_id] = result
        return result

    async def publish_new_health_interpretation_evidence(
        self,
        session_id: str,
    ) -> None:
        """Publish newly produced interpretation evidence without changing semantics."""

        all_evidence = self._acquisition_node.health_interpretation_evidence
        new_evidence = all_evidence[self._published_health_interpretation_count :]
        for evidence in new_evidence:
            message = RuntimeEvidenceMessage(
                evidence_id=(
                    f"health-interpretation-{evidence.originating_observation_id}"
                ),
                session_id=session_id,
                evidence_type="health_interpretation",
                source_id=self._boundary.component_id,
                payload=evidence.to_dict(),
                is_persistent=True,
            )
            await self._boundary.publish_evidence(message)
            self._published_health_interpretation_count += 1

    async def publish_evidence(self, message: RuntimeEvidenceMessage) -> None:
        """Publish AcquisitionNode-owned durable runtime evidence."""

        if message.source_id != self._boundary.component_id:
            raise ValueError("Runtime evidence source_id does not match AcquisitionNode")
        await self._boundary.publish_evidence(message)

    def _result(
        self,
        command: RuntimeCommandMessage,
        status: str,
        success: bool,
        reason: str | None,
        payload: dict[str, Any],
    ) -> RuntimeCommandResultMessage:
        return RuntimeCommandResultMessage(
            result_id=f"result-{self._boundary.component_id}-{command.command_id}",
            command_id=command.command_id,
            session_id=command.session_id,
            source_id=self._boundary.component_id,
            target_id=command.source_id,
            status=status,
            success=success,
            reason=reason,
            payload=payload,
        )


class NatsIngestorCommunication:
    """NATS evidence consumer that hands durable evidence to Ingestor."""

    def __init__(
        self,
        boundary: NatsCommunicationBoundary,
        ingestor: InMemoryIngestor,
    ) -> None:
        self._boundary = boundary
        self._ingestor = ingestor

    async def subscribe_evidence(
        self,
        session_id: str,
        callback: RuntimeEvidenceCallback | None = None,
    ) -> Subscription:
        """Consume and audit durable runtime evidence for one Session."""

        subject = f"messages.{session_id}.evidence.>"

        async def receive(message: Any) -> None:
            evidence = RuntimeEvidenceMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            self._ingestor.receive_runtime_evidence(evidence)
            if callback is not None:
                await callback(evidence)
            await message.ack()

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )
