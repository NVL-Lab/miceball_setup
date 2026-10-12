"""NATS communication boundary for Phase 10 runtime messages."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import nats
from nats.aio.client import Client as NATS
from nats.aio.subscription import Subscription
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, StorageType, StreamConfig
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError

from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.acquisition_health import HealthInterpretationEvidence
from lab_sync_acquisition.communication import (
    SERVICE_RECOVERY_COMMAND_TYPES,
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
from lab_sync_acquisition.session import ScientificOutputSelection
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.synchronization import SynchronizationManager
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.service_maintenance import service_operation


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
        self._dependency_result_observer = None

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

        try:
            self._client = await nats.connect(servers=list(self.servers), allow_reconnect=False)
        except Exception as error:
            raise ConnectionError(f"NATS startup connection failed: {error}") from error
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
                info = await jetstream.stream_info(stream_name)
                if stream_name in {"LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"}:
                    extra = {"LAB_COMMANDS": "messages.command.>", "LAB_COMMAND_RESULTS": "messages.command_result.>",
                             "LAB_EVIDENCE": "messages.evidence.>"}[stream_name]
                    if extra not in info.config.subjects:
                        info.config.subjects = [*info.config.subjects, extra]
                        await jetstream.update_stream(config=info.config)
            except NotFoundError:
                await jetstream.add_stream(
                    config=StreamConfig(
                        name=stream_name,
                        subjects=[subject, {"LAB_COMMANDS": "messages.command.>",
                            "LAB_COMMAND_RESULTS": "messages.command_result.>",
                            "LAB_EVIDENCE": "messages.evidence.>"}[stream_name]],
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

    async def subscribe_readiness_announcements(
        self, participant: RuntimeParticipant, callback: RuntimeEvidenceCallback,
    ) -> Subscription:
        """Consume only newly published dependency announcements, never historical readiness."""
        subject = build_runtime_subject(None, "evidence", participant.component_type,
                                        participant.component_id, "service_readiness")

        async def receive(message):
            evidence = RuntimeEvidenceMessage.from_dict(json.loads(message.data.decode("utf-8")))
            await callback(evidence)

        return await self._require_jetstream().subscribe(
            subject, cb=receive, manual_ack=True, deliver_policy=DeliverPolicy.NEW,
            config=ConsumerConfig(ack_policy=AckPolicy.NONE))

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
        self._maintenance_requests: list[dict[str, Any]] = []

    @property
    def maintenance_requests(self) -> tuple[dict[str, Any], ...]:
        """Administrative attempt identities and authorization retained at the issuer."""
        from copy import deepcopy
        return tuple(deepcopy(self._maintenance_requests))

    @property
    def command_results(self) -> tuple[RuntimeCommandResultMessage, ...]:
        """Command results received in delivery order."""

        return self._command_results

    def check_ready(self) -> ServiceReadiness:
        return self._boundary.check_ready()

    async def request_command(self, participant: RuntimeParticipant, command_type: str,
                              session_id: str | None, payload: dict[str, Any],
                              result_window_s: float, *, command_id: str | None = None) -> RuntimeCommandResultMessage | None:
        """Issue once and await the correlated final result; missing remains unconfirmed."""
        from uuid import uuid4
        from math import isfinite
        if not isinstance(result_window_s, (int, float)) or not isfinite(result_window_s) or result_window_s < 0:
            raise ValueError("result_window_s must be finite and nonnegative")
        command_id = uuid4().hex if command_id is None else command_id
        if not isinstance(command_id, str) or not command_id or command_id in self._command_result_events:
            raise ValueError("A nonempty, non-overlapping command identity is required")
        event = self._command_result_events.setdefault(command_id, asyncio.Event())
        observer = getattr(self._boundary, "_dependency_result_observer", None)
        observation = observer(participant, command_type) if observer is not None else None
        result = None
        try:
            command = RuntimeCommandMessage(command_id, session_id, command_type,
                self._boundary.component_id, participant.component_id, payload)
            if command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES):
                from copy import deepcopy
                if any(previous["command_id"] == command_id and previous != command.to_dict()
                       for previous in self._maintenance_requests):
                    raise ValueError("Conflicting administrative command identity")
                self._maintenance_requests.append(deepcopy(command.to_dict()))
            await self.publish_command(command, participant.component_type)
            if not any(r.command_id == command_id for r in self._command_results):
                await asyncio.wait_for(event.wait(), result_window_s)
            result = next((r for r in self._command_results if r.command_id == command_id
                and r.session_id == session_id and r.source_id == participant.component_id
                and r.target_id == self._boundary.component_id and r.status in {"succeeded", "failed"}
                and type(r.success) is bool and r.success == (r.status == "succeeded")), None)
            return result
        except TimeoutError:
            return None
        finally:
            self._command_result_events.pop(command_id, None)
            await self._notify_dependency_result(observation, command_type, result)

    @staticmethod
    async def _notify_dependency_result(observation, command_type, result):
        if observation is not None:
            try:
                await observation(command_type, result)
            except Exception as error:
                logger.warning("Dependency readiness observation could not be recorded: %s", error)

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
        observer = getattr(self._boundary, "_dependency_result_observer", None)
        for message in messages:
            participant = RuntimeParticipant(component_type, message.target_id)
            observation = observer(participant, command_type) if observer is not None else None
            try:
                await self._boundary.publish_command(message, component_type)
            except BaseException:
                await self._notify_dependency_result(observation, command_type, None)
                raise
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
        observer = getattr(self._boundary, "_dependency_result_observer", None)
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
        outcome = aggregate_group_command_results(
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
        for unresolved in outcome.unresolved_outcomes:
            participant = RuntimeParticipant(unresolved.expected_target_type, unresolved.expected_target_id)
            observation = observer(participant, command_type) if observer is not None else None
            await self._notify_dependency_result(observation, command_type, None)
        return outcome

    async def subscribe_command_results(
        self,
        session_id: str | None,
        callback: RuntimeResultCallback | None = None,
    ) -> Subscription:
        """Consume durable results addressed to this command issuer."""

        subject = "messages.command_result.>" if session_id is None else f"messages.{session_id}.command_result.>"

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
            "get_inventory", "reserve", "release_reservation",
            "initialize_session", "abort_session_initialization",
            "prepare_experiment_scientific_outputs",
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
        self._published_artifact_manifest_count = 0

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Consume commands routed to this AcquisitionNode instance."""

        subjects = (f"messages.*.command.acquisition_node.{self._boundary.component_id}.>",
                    f"messages.command.acquisition_node.{self._boundary.component_id}.>")

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
                result = (await _execute_maintenance_command(self._boundary, self._acquisition_node, command)
                          if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES) else self.execute_command(command))
                await self._boundary.publish_command_result(
                    result,
                    command.command_type,
                )
                logger.info(
                    "command_result_published command_id=%s status=%s",
                    result.command_id,
                    result.status,
                )
                await self.publish_new_artifact_manifest_evidence()
                if command.session_id is not None:
                    await self.publish_new_health_interpretation_evidence(command.session_id)
                await message.ack()
            except Exception:
                logger.exception("command_delivery_processing_failed")
                raise

        subscriptions = []
        for subject in subjects:
            subscriptions.append(await self._boundary._require_jetstream().subscribe(subject, cb=receive, manual_ack=True))
        return tuple(subscriptions)

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
            if command.target_id != self._boundary.component_id:
                raise ValueError("Command target does not match participant")
            if command.command_type not in {"check_readiness", "get_inventory", "reserve", "release_reservation", "initialize_session", "abort_session_initialization"} and command.session_id != self._acquisition_node.status()["session_id"]:
                raise RuntimeError("Command session_id does not match AcquisitionNode")
            if command.command_type == "get_inventory":
                payload = {"devices": [d.to_dict() for d in self._acquisition_node.declared_devices]}
            elif command.command_type in {"reserve", "release_reservation", "abort_session_initialization"}:
                succeeded = getattr(self._acquisition_node, command.command_type)(command.session_id)
                payload = {"confirmed": succeeded}
                if not succeeded:
                    raise RuntimeError(f"Node rejected {command.command_type}")
            elif command.command_type == "initialize_session":
                preparation = self._acquisition_node.initialize_session(command.session_id,
                    tuple(DeviceDeclaration.from_dict(d) for d in command.payload["selected_devices"]),
                    command.payload.get("device_configurations"),
                    tuple(ScientificOutputSelection.from_dict(s) for s in command.payload.get("scientific_outputs", ())))
                payload = {"preparation": preparation.to_dict()}
                if not preparation.ready:
                    raise RuntimeError(preparation.reason)
            elif command.command_type == "check_readiness":
                readiness = self._acquisition_node.check_node_readiness((self._boundary.check_ready(),))
                payload = {
                    "acquisition_node_readiness": readiness.to_dict(),
                }
                maintenance = getattr(self._acquisition_node, "_maintenance", None)
                if maintenance is not None:
                    payload.update(maintenance._diagnostic_payload())
                elif callable(getattr(self._acquisition_node, "maintenance_diagnostics", None)):
                    try:
                        payload["service_diagnostics"] = self._acquisition_node.maintenance_diagnostics(
                            self._acquisition_node._ingestor, None)
                    except Exception as error:
                        payload["diagnostics_unconfirmed"] = str(error)
            elif command.command_type == "prepare_experiment_scientific_outputs":
                experiment_id = command.payload["experiment_id"]
                preparation = self._acquisition_node.prepare_experiment_scientific_outputs(
                    experiment_id, tuple(ScientificOutputSelection.from_dict(item)
                                         for item in command.payload["scientific_outputs"]))
                payload = {"experiment_id": experiment_id, "preparation": preparation.to_dict()}
                if preparation.required and not preparation.ready:
                    result = self._result(command, "failed", False, preparation.reason, payload)
                    self._results_by_command_id[command.command_id] = result
                    return result
            elif command.command_type == "start_runtime":
                outcome = self._acquisition_node.start_runtime()
                if any(not item.succeeded for item in outcome.get("device_start_results", ())):
                    raise RuntimeError("Device runtime start failed")
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
                if any(not item.succeeded for item in (*outcome.get("device_stop_results", ()), *outcome.get("device_shutdown_results", ()))):
                    raise RuntimeError("Device stop/shutdown did not confirm successful cleanup")
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

    async def publish_new_artifact_manifest_evidence(self) -> None:
        """Publish produced manifest lifecycle evidence through the existing boundary."""
        evidence = getattr(self._acquisition_node, "artifact_manifest_evidence", ())
        for message in evidence[self._published_artifact_manifest_count:]:
            await self.publish_evidence(message)
            self._published_artifact_manifest_count += 1

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
        self._results_by_command_id = {}
        self._evidence_subscriptions: dict[str, Subscription] = {}

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Receive readiness and Session preparation over the existing command stream."""
        async def receive(message: Any) -> None:
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            result = (await _execute_maintenance_command(self._boundary, self._ingestor, command)
                      if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES) else
                      _execute_service_command(self._boundary, self._ingestor, command, self._results_by_command_id))
            if result.success and command.command_type == "initialize_session" and command.session_id not in self._evidence_subscriptions:
                try:
                    self._evidence_subscriptions[command.session_id] = await self.subscribe_evidence(command.session_id)
                except Exception as error:
                    result = _participant_result(self._boundary, command, False, str(error), {})
                    self._results_by_command_id[command.command_id] = result
            if result.success and command.command_type == "abort_session_initialization":
                subscription = self._evidence_subscriptions.get(command.session_id)
                if subscription is not None:
                    try:
                        await subscription.unsubscribe()
                        del self._evidence_subscriptions[command.session_id]
                    except Exception as error:
                        result = _participant_result(self._boundary, command, False, str(error), {})
                        self._results_by_command_id[command.command_id] = result
            await self._boundary.publish_command_result(result, command.command_type)
            await message.ack()
        return await _subscribe_participant_commands(self._boundary, receive)

    async def subscribe_evidence(
        self,
        session_id: str | None,
        callback: RuntimeEvidenceCallback | None = None,
    ) -> Subscription:
        """Consume and audit durable runtime evidence for one Session."""

        if session_id is None:
            self._ingestor.compile_framework_runtime_evidence()
        elif self._ingestor.recovery_journal_path is None or self._ingestor.session_id != session_id:
            raise ValueError("Broker evidence intake requires the matching Session recovery journal")
        subject = "messages.evidence.>" if session_id is None else f"messages.{session_id}.evidence.>"

        async def receive(message: Any) -> None:
            evidence = RuntimeEvidenceMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            audit = self._ingestor.receive_runtime_evidence(evidence)
            if callback is not None and audit.accepted and audit.reason != "already_accepted":
                await callback(evidence)
            await message.ack()

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )


def _participant_result(boundary: NatsCommunicationBoundary, command: RuntimeCommandMessage,
                        success: bool, reason: str | None, payload: dict[str, Any]) -> RuntimeCommandResultMessage:
    return RuntimeCommandResultMessage(f"result-{boundary.component_id}-{command.command_id}",
        command.command_id, command.session_id, boundary.component_id, command.source_id,
        "succeeded" if success else "failed", success, reason, payload)


def _execute_service_command(boundary: NatsCommunicationBoundary, service: Any,
                             command: RuntimeCommandMessage, results: dict) -> RuntimeCommandResultMessage:
    if command.command_id in results:
        return results[command.command_id]
    try:
        if command.target_id != boundary.component_id:
            raise ValueError("Command target does not match participant")
        if not boundary.check_ready().ready:
            raise ConnectionError("Required NATS connection is not ready")
        if command.command_type == "check_readiness":
            report = service.check_ready().to_dict()
            report.update(component_id=boundary.component_id, component_type=boundary.component_type)
            payload = {"service_readiness": report}
            maintenance = getattr(service, "_maintenance", None)
            if maintenance is not None:
                payload.update(maintenance._diagnostic_payload())
                payload["participant"] = maintenance.participant.to_dict()
                payload["operational_retirement_confirmed"] = maintenance.terminated
        elif command.command_type == "initialize_session":
            preparation = service.prepare_session(command.session_id)
            if not preparation.ready:
                raise RuntimeError(preparation.reason)
            report = preparation.to_dict()
            report.update(component_id=boundary.component_id, component_type=boundary.component_type)
            payload = {"preparation": report}
        elif command.command_type == "abort_session_initialization":
            payload = {"confirmed": service.abort_session_initialization(command.session_id)}
            if payload["confirmed"] is not True:
                raise RuntimeError("Participant cleanup is unconfirmed")
        else:
            raise ValueError(f"Unsupported service command: {command.command_type}")
        result = _participant_result(boundary, command, True, None, payload)
    except Exception as error:
        result = _participant_result(boundary, command, False, str(error), {})
    results[command.command_id] = result
    return result


async def _subscribe_participant_commands(boundary: NatsCommunicationBoundary, receive: Callable) -> tuple[Subscription, Subscription]:
    subscriptions = []
    for subject in (f"messages.*.command.{boundary.component_type}.{boundary.component_id}.>",
                    f"messages.command.{boundary.component_type}.{boundary.component_id}.>"):
        subscriptions.append(await boundary._require_jetstream().subscribe(subject, cb=receive, manual_ack=True))
    return tuple(subscriptions)


class NatsSynchronizationManagerCommunication:
    """Routes preparation commands; SynchronizationManager retains timing ownership."""

    def __init__(self, boundary: NatsCommunicationBoundary, synchronization_manager: SynchronizationManager) -> None:
        self._boundary = boundary
        self._synchronization_manager = synchronization_manager
        self._results_by_command_id = {}

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        async def receive(message: Any) -> None:
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            result = (await _execute_maintenance_command(self._boundary, self._synchronization_manager, command)
                      if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES) else
                      _execute_service_command(self._boundary, self._synchronization_manager, command, self._results_by_command_id))
            await self._boundary.publish_command_result(result, command.command_type)
            await message.ack()
        return await _subscribe_participant_commands(self._boundary, receive)


async def _execute_maintenance_command(boundary, service, command):
    interface = getattr(service, "_maintenance", None)
    if interface is None:
        from uuid import uuid4
        return RuntimeCommandResultMessage(uuid4().hex, command.command_id, command.session_id,
                    command.target_id, command.source_id, "failed", False,
                    "Individual-service maintenance is not configured", {"outcome": "failed", "termination_confirmed": False})
    if interface.evidence_publisher is None:
        interface.evidence_publisher = boundary.publish_evidence
    return await interface.execute_command(command)


class NatsServiceMaintenanceCommunication:
    """Service-owned startup/readiness integration and participant-scoped maintenance."""

    def __init__(self, boundary: NatsCommunicationBoundary, maintenance, *,
                 startup_participants: Iterable[RuntimeParticipant] | None = None,
                 startup_result_window_s: float | None = None):
        if (maintenance.participant.component_id != boundary.component_id
                or maintenance.participant.component_type != boundary.component_type):
            raise ValueError("Maintenance participant does not match communication boundary")
        self._boundary = boundary
        self._maintenance = maintenance
        self._readiness_subscriptions = ()
        self._request_subscription = None
        self._requests = NatsControllerCommunication(boundary)
        self._startup_status = None
        self._subscription_lock = asyncio.Lock()
        self._result_observer = None
        if maintenance.participant.component_type != "controller" and (
                startup_participants is not None or startup_result_window_s is not None):
            raise ValueError("Startup participant reconciliation belongs to Controller")
        self._startup_participants = (tuple(maintenance.dependency_readiness)
            if startup_participants is None else tuple(startup_participants))
        self._startup_result_window_s = startup_result_window_s
        if maintenance.evidence_publisher is None:
            maintenance.evidence_publisher = boundary.publish_evidence

    async def start(self) -> dict[str, Any]:
        """Subscribe/announce startup and reconcile Controller's known remote participants."""
        async with self._subscription_lock:
            return await self._start()

    async def _start(self):
        if self._maintenance.participant.component_type == "controller":
            self._maintenance.service._validate_participant_reconciliation(
                self._startup_participants, self._startup_result_window_s)
        if not self._boundary.check_ready().ready:
            raise ConnectionError("Required NATS startup connection is not ready")
        if self._maintenance.terminated or self._maintenance._closeout_started:
            raise RuntimeError("Service must satisfy existing operational reuse protections")
        if self._request_subscription is not None or self._readiness_subscriptions:
            if self._startup_status is None:
                raise RuntimeError("Subscription cleanup remains unconfirmed")
            from copy import deepcopy
            return deepcopy(self._startup_status)
        subscriptions = []
        observer = None
        try:
            for participant in self._maintenance.dependency_readiness:
                async def receive(evidence, participant=participant):
                    if getattr(self._boundary, "_dependency_result_observer", None) is not observer:
                        return
                    if (evidence.session_id is not None or evidence.evidence_type != "service_readiness"
                            or evidence.source_id != participant.component_id
                            or evidence.payload.get("participant") != participant.to_dict()):
                        report = None
                    else:
                        report = self._readiness_report(participant, evidence.payload.get("service_readiness"))
                    if self._maintenance.receive_dependency_readiness(participant, report):
                        await self.publish_readiness()
                subscriptions.append(await self._boundary.subscribe_readiness_announcements(participant, receive))
                self._readiness_subscriptions = tuple(subscriptions)
            self._request_subscription = await self._requests.subscribe_command_results(None)
            subscription = self._request_subscription

            def observer(participant, command_type):
                with self._maintenance._admission_lock:
                    if (self._request_subscription is not subscription
                            or getattr(self._boundary, "_dependency_result_observer", None) is not observer):
                        return None
                    # Later checks also supersede earlier pending checks, regardless of delivery order.
                    if (command_type == "check_readiness"
                            and participant in self._maintenance._dependency_readiness_versions):
                        self._maintenance._dependency_readiness_versions[participant] += 1
                    version = self._maintenance._dependency_readiness_versions.get(participant)

                async def observe(command_type, result):
                    if (self._request_subscription is subscription
                            and getattr(self._boundary, "_dependency_result_observer", None) is observer):
                        await self._observe_dependency_result(participant, command_type, result, version)
                return observe

            self._result_observer = observer
            self._boundary._dependency_result_observer = observer
            self._startup_status = await self._maintenance.announce_readiness(startup=True)
            await self.publish_readiness()
            if self._maintenance.participant.component_type == "controller":
                self._startup_status["reconciliation"] = await self._maintenance.service.reconcile_outcomes(
                    participants=self._startup_participants, communication=self._requests,
                    result_window_s=self._startup_result_window_s)
            return self._startup_status
        except BaseException:
            try:
                await self._close()
            except Exception as error:
                logger.warning("Startup subscription cleanup remains unconfirmed: %s", error)
            raise

    async def close(self) -> None:
        """Release these communication subscriptions without terminating or restarting a service."""
        async with self._subscription_lock:
            await self._close()

    async def _close(self):
        self._startup_status = None
        try:
            for subscription in self._readiness_subscriptions:
                await subscription.unsubscribe()
                self._readiness_subscriptions = tuple(s for s in self._readiness_subscriptions if s is not subscription)
            if self._request_subscription is not None:
                await self._request_subscription.unsubscribe()
                self._request_subscription = None
        finally:
            if getattr(self._boundary, "_dependency_result_observer", None) is self._result_observer:
                self._boundary._dependency_result_observer = None
                for participant in self._maintenance.dependency_readiness:
                    self._maintenance.receive_dependency_readiness(participant, None)

    async def publish_readiness(self) -> dict[str, Any] | None:
        """Publish meaningful changes using the service's existing producer-evidence path."""
        if (self._startup_status is None or self._maintenance.terminated
                or self._maintenance._closeout_started or self._maintenance._attempt is not None
                or getattr(self._maintenance.service, "_framework_shutdown_active", False)):
            return None
        return await self._maintenance.announce_readiness()

    @staticmethod
    def _readiness_report(participant, data):
        if not isinstance(data, dict):
            return None
        try:
            report = ServiceReadiness(**data)
        except TypeError:
            return None
        if (report.component_id != participant.component_id or report.component_type != participant.component_type
                or type(report.ready) is not bool or type(report.required) is not bool or not isinstance(report.reason, str)):
            return None
        return report

    @service_operation(new_work=True)
    async def request_dependency_command(
        self, participant: RuntimeParticipant, command_type: str,
        session_id: str | None, payload: dict[str, Any], result_window_s: float,
    ) -> RuntimeCommandResultMessage | None:
        """Reuse correlated requests; unconfirmed communication invalidates only current availability."""
        if participant not in self._maintenance.dependency_readiness:
            raise ValueError("Dependency is not configured for this service")
        if self._request_subscription is None or self._startup_status is None:
            raise RuntimeError("Startup communication subscriptions are not active")
        subscription = self._request_subscription
        result = await self._requests.request_command(participant, command_type, session_id, payload, result_window_s)
        if self._request_subscription is not subscription:
            raise RuntimeError("Dependency request belongs to an earlier communication binding")
        return result

    async def _observe_dependency_result(self, participant, command_type, result, observation_version):
        if participant not in self._maintenance.dependency_readiness:
            return
        if result is None or command_type == "check_readiness":
            report = None
            if result is not None and result.success:
                data = result.payload.get("service_readiness")
                if participant.component_type == "acquisition_node":
                    node = result.payload.get("acquisition_node_readiness")
                    if isinstance(node, dict) and node.get("node_id") == participant.component_id and type(node.get("ready")) is bool:
                        data = ServiceReadiness(participant.component_id, participant.component_type,
                            True, node["ready"], "ready" if node["ready"] else "node_prerequisites_unready").to_dict()
                report = self._readiness_report(participant, data)
            with self._maintenance._admission_lock:
                # A confirmed response must not replace observations made since its request began.
                if (report is not None and observation_version !=
                        self._maintenance._dependency_readiness_versions[participant]):
                    return
                changed = self._maintenance.receive_dependency_readiness(participant, report)
            if changed:
                await self.publish_readiness()

    async def check_dependency_readiness(self, participant: RuntimeParticipant,
                                         result_window_s: float) -> ServiceReadiness | None:
        """Explicit operational check; never triggered redundantly by a fresh announcement."""
        await self.request_dependency_command(participant, "check_readiness", None, {}, result_window_s)
        return self._maintenance.dependency_readiness[participant]

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Use existing JetStream command subscriptions and command-result publication."""
        async def receive(message):
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            if command.command_type == "check_readiness":
                try:
                    if not self._boundary.check_ready().ready:
                        raise ConnectionError("Required NATS connection is not ready")
                    payload = self._maintenance._readiness_payload()
                    if payload["service_readiness"] is None:
                        raise RuntimeError(payload.get("readiness_error", "Current readiness is unknown"))
                    result = _participant_result(self._boundary, command, True, None, payload)
                except Exception as error:
                    result = _participant_result(self._boundary, command, False, str(error), {})
            else:
                result = await self._maintenance.execute_command(command)
            await self._boundary.publish_command_result(result, command.command_type)
            await message.ack()
        return await _subscribe_participant_commands(self._boundary, receive)
