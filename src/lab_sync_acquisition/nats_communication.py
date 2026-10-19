"""NATS communication boundary for Phase 10 runtime messages."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from copy import deepcopy
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from time import get_clock_info, monotonic
from typing import Any
from uuid import uuid4

from nats.aio.client import Client as NATS
from nats.aio.subscription import Subscription
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig
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
    parse_runtime_subject,
    aggregate_group_command_results,
    build_group_command_messages,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.controller import Controller, ControllerActionDecision
from lab_sync_acquisition.session import ScientificOutputSelection, ExperimentConfiguration
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.synchronization import SynchronizationManager
from lab_sync_acquisition.experiment_runtime import ActiveExperimentRuntimeContext, ExperimentRuntimeHealthMapping
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.service_maintenance import service_operation
from lab_sync_acquisition.communication import DEPENDENT_MAINTENANCE_COMMANDS
from lab_sync_acquisition.storage import PersistentStorageManager


RuntimeResultCallback = Callable[[RuntimeCommandResultMessage], Awaitable[None]]
RuntimeEvidenceCallback = Callable[[RuntimeEvidenceMessage], Awaitable[None]]
ControllerDecisionCallback = Callable[[ControllerActionDecision | dict[str, Any]], Awaitable[Any]]
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
        self._close_task: asyncio.Task[None] | None = None
        self._dependency_result_observer = None
        self.maintenance_command_handled: Callable[[RuntimeCommandMessage, RuntimeCommandResultMessage], None] | None = None
        self._pending_dependent_deliveries = {}

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

        if self._client is not None:
            raise RuntimeError("Close the owned NATS client before starting another connection")
        # Own the client before its handshake can open a transport or be cancelled.
        self._client = NATS()
        self._jetstream = None
        try:
            await self._client.connect(servers=list(self.servers), allow_reconnect=False)
            self._jetstream = self._client.jetstream()
        except BaseException as error:
            await self.close()
            if isinstance(error, Exception):
                raise ConnectionError(f"NATS startup connection failed: {error}") from error
            raise

    async def close(self) -> None:
        """Finish owned cleanup before releasing references or propagating cancellation."""

        client = self._client
        if client is None:
            return
        if self._close_task is None:
            operation = client.close if self._jetstream is None or client.is_closed else client.drain
            self._close_task = asyncio.create_task(operation())
        task = self._close_task
        cancellation = None
        # nats-py sets is_closed before closing its transport. Join the original
        # operation, including after repeated caller cancellation, rather than
        # starting a second close that would return early on that flag.
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError as error:
                if task.cancelled():
                    raise
                cancellation = error
        if self._close_task is task and self._client is client:
            self._client = None
            self._jetstream = None
            self._close_task = None
        if cancellation is not None:
            raise cancellation

    async def flush(self) -> None:
        """Synchronize pending Core NATS protocol operations with the server."""

        await self._require_client().flush()

    async def ensure_streams(self) -> None:
        """Provision disjoint runtime filters without replacing existing streams."""

        jetstream = self._require_jetstream()
        streams = (
            ("LAB_COMMANDS", "command", LAB_COMMANDS),
            ("LAB_COMMAND_RESULTS", "command_result", LAB_COMMAND_RESULTS),
            ("LAB_EVIDENCE", "evidence", LAB_EVIDENCE),
        )
        existing = {}
        # Narrow all known legacy filters before adding participant coverage:
        # a five-token filter can otherwise overlap another stream's legacy >.
        for stream_name, message_class, legacy_subject in streams:
            try:
                info = await jetstream.stream_info(stream_name)
            except NotFoundError:
                continue
            replacements = {legacy_subject: f"messages.*.{message_class}.*.*.*",
                            f"messages.{message_class}.>": f"messages.{message_class}.*.*.*"}
            narrowed = list(dict.fromkeys(replacements.get(subject, subject)
                                         for subject in (info.config.subjects or [])))
            config = replace(info.config, subjects=narrowed)
            if narrowed != info.config.subjects:
                await jetstream.update_stream(config=config)
            existing[stream_name] = config

        for stream_name, message_class, _ in streams:
            subjects = [f"messages.*.{message_class}.*.*.*",
                        f"messages.{message_class}.*.*.*"]
            if stream_name not in existing:
                await jetstream.add_stream(
                    config=StreamConfig(
                        name=stream_name, subjects=subjects,
                        storage=StorageType.FILE,
                    )
                )
            else:
                config = existing[stream_name]
                updated = list(config.subjects)
                updated.extend(subject for subject in subjects if subject not in updated)
                if updated != config.subjects:
                    await jetstream.update_stream(config=replace(config, subjects=updated))

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
        self._health_receivers: dict[str, list[dict[str, Any]]] = {}
        self._runtime_stop_commands: dict[tuple, RuntimeCommandMessage] = {}
        self._unpublished_evidence: dict[str, RuntimeEvidenceMessage] = {}

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

    async def request_persistence_command(
        self, participant: RuntimeParticipant, command_type: str, session_id: str | None,
        payload: dict[str, Any], result_window_s: float, *, command_id: str,
    ) -> RuntimeCommandResultMessage | None:
        """Request current owner readback without accepting history or an earlier attempt's reply."""
        supported = {"storage_manager": {"read_session_preservation",
                                        "get_saved_session_collection_status", "collect_saved_artifacts",
                                        "close_session_evidence_archive"},
                     "ingestor": {"compile_session_evidence", "verify_acquisition_receipt",
                                  "read_runtime_evidence_acceptance", "admit_session_kill",
                                  "preserve_session_acquisition", "read_session_closeout",
                                  "preserve_session_terminal_record", "release_session", "preserve_service_evidence"}}
        if (not isinstance(participant, RuntimeParticipant)
                or command_type not in supported.get(participant.component_type, set())
                or "request_nonce" in payload
                or (command_type == "preserve_service_evidence" and session_id is not None)
                or (command_type != "preserve_service_evidence" and (not isinstance(session_id, str) or not session_id))):
            raise ValueError("Unsupported scoped persistence request")
        nonce = uuid4().hex
        requests = NatsControllerCommunication(self._boundary)
        subscription = await requests.subscribe_command_results(session_id, new_only=True,
            result_filter=lambda result: result.payload.get("request_nonce") == nonce)
        try:
            return await requests.request_command(participant, command_type, session_id,
                {**deepcopy(payload), "request_nonce": nonce}, result_window_s, command_id=command_id)
        finally:
            await subscription.unsubscribe()

    async def request_maintenance_readback(self, participant, operation, payload, result_window_s):
        """Request fresh instance/dependency confirmation through existing scoped command/results."""
        from math import isfinite
        if (operation not in DEPENDENT_MAINTENANCE_COMMANDS or "request_nonce" in payload
                or type(result_window_s) not in {int, float} or not isfinite(result_window_s) or result_window_s <= 0):
            raise ValueError("Unsupported dependent maintenance request")
        nonce = uuid4().hex
        requests = NatsControllerCommunication(self._boundary)
        subscription = await requests.subscribe_command_results(None, new_only=True,
            participant=participant, command_type=operation,
            result_filter=lambda result: result.payload.get("request_nonce") == nonce)
        try:
            return await asyncio.wait_for(requests.request_command(participant, operation, None,
                {**deepcopy(payload), "request_nonce": nonce}, result_window_s), result_window_s)
        except TimeoutError:
            return None
        finally:
            await subscription.unsubscribe()

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
            if command_type == "stop_runtime":
                self._runtime_stop_commands[(session_id, participant.component_type,
                                             participant.component_id)] = command
            if command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES):
                from copy import deepcopy
                if any(previous["command_id"] == command_id and previous != command.to_dict()
                       for previous in self._maintenance_requests):
                    raise ValueError("Conflicting administrative command identity")
                self._maintenance_requests.append(deepcopy(command.to_dict()))
            await self.publish_command(command, participant.component_type)

            def matches_attempt(reply):
                return (reply.command_id == command_id and reply.session_id == session_id
                    and reply.source_id == participant.component_id
                    and reply.target_id == self._boundary.component_id
                    and reply.payload.get("request_nonce") == payload.get("request_nonce")
                    and reply.status in {"succeeded", "failed"})

            deadline = asyncio.get_running_loop().time() + result_window_s
            while not any(matches_attempt(reply) for reply in self._command_results):
                event.clear()
                await asyncio.wait_for(event.wait(), max(0, deadline - asyncio.get_running_loop().time()))
            replies = [reply for reply in self._command_results if matches_attempt(reply)]
            # Delivery/result IDs may differ on duplicate publication, but the
            # owner's resolution of one attempt must remain identical.
            resolutions = {json.dumps([reply.status, reply.success, reply.reason, reply.payload],
                sort_keys=True, separators=(",", ":"), allow_nan=False) for reply in replies}
            if (len(resolutions) != 1 or any(type(reply.success) is not bool
                    or reply.success != (reply.status == "succeeded") for reply in replies)):
                logger.warning("Conflicting or invalid command resolutions command_id=%s", command_id)
                return None
            result = replies[0]
            return result
        except TimeoutError:
            return None
        finally:
            self._command_result_events.pop(command_id, None)
            await self._notify_dependency_result(observation, command_type, result)

    async def request_runtime_command(self, participant: RuntimeParticipant, command_type: str,
                                      session_id: str, payload: dict[str, Any], result_window_s: float,
                                      *, command_id: str | None = None) -> RuntimeCommandResultMessage | None:
        """Issue scoped runtime work with fresh per-attempt reply correlation."""
        if (not isinstance(session_id, str) or not session_id or "request_nonce" in payload
                or not isinstance(participant, RuntimeParticipant)):
            raise ValueError("An explicit Session, participant and caller payload are required")
        if command_type == "stop_runtime":
            self._runtime_stop_commands.pop((session_id, participant.component_type, participant.component_id), None)
        nonce = uuid4().hex
        requests = NatsControllerCommunication(self._boundary)
        subscription = await requests.subscribe_command_results(session_id, new_only=True,
            participant=participant, command_type=command_type,
            result_filter=lambda result: (result.payload.get("request_nonce") == nonce
                and result.source_id == participant.component_id and result.session_id == session_id))
        try:
            result = await requests.request_command(participant, command_type, session_id,
                {**deepcopy(payload), "request_nonce": nonce}, result_window_s, command_id=command_id)
            if result is not None:
                self._runtime_stop_commands.update(requests._runtime_stop_commands)
                self._command_results += (result,)
            return result
        finally:
            await subscription.unsubscribe()

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
        *, new_only: bool = False,
        result_filter: Callable[[RuntimeCommandResultMessage], bool] | None = None,
        participant: RuntimeParticipant | None = None,
        command_type: str | None = None,
        invalid_result_callback: Callable[[str], None] | None = None,
    ) -> Subscription:
        """Consume durable results addressed to this command issuer."""

        subject = "messages.command_result.*.*.*" if session_id is None else f"messages.{session_id}.command_result.*.*.*"
        if (participant is None) != (command_type is None):
            raise ValueError("Result subject scoping requires both participant and command type")
        if participant is not None:
            subject = build_runtime_subject(session_id, "command_result", participant.component_type,
                                            participant.component_id, command_type)

        async def receive(message: Any) -> None:
            try:
                result = RuntimeCommandResultMessage.from_dict(
                    json.loads(message.data.decode("utf-8"))
                )
            except (ValueError, TypeError, KeyError, AttributeError):
                if invalid_result_callback is None:
                    raise
                invalid_result_callback("Malformed command result")
                await message.ack()
                return
            if result.target_id != self._boundary.component_id:
                if invalid_result_callback is not None:
                    invalid_result_callback("Command result addressed to another requester")
                await message.ack()
                return
            if result_filter is not None and not result_filter(result):
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
            **({"config": ConsumerConfig(deliver_policy=DeliverPolicy.NEW,
                                         ack_policy=AckPolicy.EXPLICIT)} if new_only else {}),
        )

    async def subscribe_experiment_expiry_evidence(self, session_id: str, controller: Controller):
        """Deliver node expiry proof through existing evidence subjects, never lifecycle commands."""
        async def receive(message):
            evidence = RuntimeEvidenceMessage.from_dict(json.loads(message.data.decode("utf-8")))
            route = parse_runtime_subject(message.subject)
            if (route["session_id"] != session_id or evidence.session_id != session_id
                    or route["component_type"] != "acquisition_node" or route["component_id"] != evidence.source_id
                    or route["message_type"] != "experiment_duration_expired"):
                raise ValueError("Expiry evidence subject/body mismatch")
            controller.accept_experiment_expiry(evidence)
            await message.ack()
        return await self._boundary._require_jetstream().subscribe(
            f"messages.{session_id}.evidence.acquisition_node.*.experiment_duration_expired",
            cb=receive, manual_ack=True, config=ConsumerConfig(deliver_policy=DeliverPolicy.NEW))

    async def subscribe_health_interpretation_evidence(
        self,
        session_id: str,
        controller: Controller,
        callback: ControllerDecisionCallback | None = None,
    ) -> Subscription:
        """Consume decision-relevant evidence without relaying or republishing it."""

        subject = f"messages.{session_id}.evidence.*.*.*"
        state = {"controller": controller, "session": controller._session,
                 "processed": {}, "inflight": {}, "active": 0}
        state["decisions"] = next((receiver["decisions"]
            for receiver in self._health_receivers.get(session_id, ())
            if receiver["controller"] is controller and receiver["session"] is controller._session), {})
        self._health_receivers.setdefault(session_id, []).append(state)

        async def receive(message: Any) -> None:
            evidence_message = RuntimeEvidenceMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            if evidence_message.evidence_type not in {"health_interpretation", "timing_quality_interpretation"}:
                await message.ack()
                return
            if evidence_message.session_id != session_id or controller._session is not state["session"]:
                raise RuntimeError("Controller health subscription Session binding changed")
            route = parse_runtime_subject(message.subject)
            if (route["session_id"] != session_id
                    or route["component_id"] != evidence_message.source_id
                    or route["message_type"] != evidence_message.evidence_type):
                raise ValueError("Controller health subject/body mismatch")
            if controller._launch_communication is not None and (
                    route["component_type"] != "acquisition_node"
                    or evidence_message.source_id not in {p.component_id for p in controller._reserved_participants}):
                raise ValueError("Health interpretation source is not a reserved AcquisitionNode")
            content = json.dumps(evidence_message.to_dict(), sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
            previous = state["processed"].get(evidence_message.evidence_id,
                state["inflight"].get(evidence_message.evidence_id))
            if previous is not None:
                if previous != content:
                    raise ValueError("Conflicting Controller health evidence identity")
                await message.ack()
                return
            state["active"] += 1
            state["inflight"][evidence_message.evidence_id] = content
            try:
                recorded = state["decisions"].get(evidence_message.evidence_id)
                if recorded is not None:
                    if recorded[0] != content:
                        raise ValueError("Conflicting Controller health evidence identity")
                    decision = recorded[1]
                elif evidence_message.evidence_type == "timing_quality_interpretation":
                    decision = controller.process_timing_quality_interpretation(evidence_message)
                else:
                    interpretation = HealthInterpretationEvidence.from_dict(evidence_message.payload)
                    decision = controller.process_health_interpretation(interpretation)
                state["decisions"][evidence_message.evidence_id] = (content, decision)
                if callback is not None:
                    outcome = await callback(decision)
                    details = getattr(outcome, "details", None)
                    if isinstance(details, dict) and details.get("health_processing_confirmed") is False:
                        raise RuntimeError("Fatal health evidence or canonical consequence remains unconfirmed")
                await message.ack()
                state["processed"][evidence_message.evidence_id] = content
            finally:
                state["inflight"].pop(evidence_message.evidence_id, None)
                state["active"] -= 1

        return await self._boundary._require_jetstream().subscribe(
            subject,
            cb=receive,
            manual_ack=True,
        )

    async def confirm_session_health_processing(self, session_id: str, controller: Controller) -> bool:
        """Read back published health inputs; unfinished callbacks cannot close publication."""
        states = self._health_receivers.get(session_id, ())
        if not states:
            return True
        if any(state["controller"] is not controller or state["active"] for state in states):
            return False
        broker = self._boundary._require_jetstream()
        info = await broker.stream_info("LAB_EVIDENCE")
        if info.state.messages and (info.state.first_seq != 1 or info.state.num_deleted):
            return False
        sequence = 1
        while sequence <= info.state.last_seq:
            try:
                record = await broker.get_msg("LAB_EVIDENCE", seq=sequence,
                    subject=f"messages.{session_id}.evidence.*.*.*", next=True)
            except NotFoundError:
                break
            if record.seq < sequence or record.seq > info.state.last_seq:
                return False
            evidence = RuntimeEvidenceMessage.from_dict(json.loads(record.data))
            if evidence.evidence_type not in {"health_interpretation", "timing_quality_interpretation"}:
                sequence = record.seq + 1
                continue
            content = json.dumps(evidence.to_dict(), sort_keys=True,
                                 separators=(",", ":"), allow_nan=False)
            if evidence.session_id != session_id or any(
                    state["processed"].get(evidence.evidence_id) != content for state in states):
                return False
            sequence = record.seq + 1
        current = await broker.stream_info("LAB_EVIDENCE")
        return (current.created == info.created and current.state == info.state
                and all(not state["active"] for state in states))

    def session_acquisition_completion(self, participant: RuntimeParticipant,
                                       session_id: str) -> RuntimeCommandResultMessage | None:
        """Read the successful result for this issuer's latest correlated runtime stop."""
        command = self._runtime_stop_commands.get(
            (session_id, participant.component_type, participant.component_id))
        if command is None:
            return None
        results = [result for result in self._command_results
                   if result.command_id == command.command_id
                   and result.session_id == session_id
                   and result.source_id == participant.component_id
                   and result.target_id == command.source_id]
        if not results or results[-1].status != "succeeded" or results[-1].success is not True:
            return None
        return results[-1]

    async def publish_evidence(self, message: RuntimeEvidenceMessage) -> None:
        """Publish Controller-owned evidence with the existing durable stream acknowledgment."""
        self._boundary._validate_source_id(message.source_id)
        previous = self._unpublished_evidence.get(message.evidence_id)
        if previous is not None and json.dumps(previous.to_dict(), sort_keys=True) != json.dumps(message.to_dict(), sort_keys=True):
            raise ValueError("Conflicting retained Controller evidence identity")
        retained = RuntimeEvidenceMessage.from_dict(deepcopy(message.to_dict()))
        self._unpublished_evidence[message.evidence_id] = retained
        await self._boundary.publish_evidence(retained)
        self._unpublished_evidence.pop(message.evidence_id, None)

    def unpublished_session_evidence(self, session_id: str) -> tuple[RuntimeEvidenceMessage, ...]:
        """Read retained unconfirmed Controller publications for one Session only."""
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict()))
                     for m in self._unpublished_evidence.values() if m.session_id == session_id)


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
            "read_local_time", "accept_synchronization_quality", "activate_experiment_runtime",
            "finalize_experiment_scientific_outputs",
            "check_experiment_capacity", "read_experiment_expiry",
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
        self._commands_by_id: dict[str, dict[str, Any]] = {}
        self._published_runtime_evidence_count = 0
        self._published_artifact_manifest_count = 0
        self._runtime_publication_lock = asyncio.Lock()
        self._artifact_manifest_publication_lock = asyncio.Lock()
        self._unpublished_evidence: dict[str, RuntimeEvidenceMessage] = {}
        self._sustained_acquisition_enabled = False
        self._acquisition_task: asyncio.Task | None = None
        self._acquisition_execution_lock = asyncio.Lock()

    @property
    def acquisition_execution_active(self) -> bool:
        """Whether this adapter owns an unfinished sustained acquisition task."""
        return self._acquisition_task is not None and not self._acquisition_task.done()

    async def start_acquisition_execution(self) -> None:
        """Enable service-local iteration scheduling for active scientific Experiments."""
        self._sustained_acquisition_enabled = True
        await self._refresh_acquisition_execution()

    async def stop_acquisition_execution(self) -> None:
        """Disable scheduling and join its owned task; this does not finalize devices."""
        self._sustained_acquisition_enabled = False
        async with self._acquisition_execution_lock:
            await self._finish_acquisition_execution()

    async def _finish_acquisition_execution(self) -> None:
        task = self._acquisition_task
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        finally:
            if task.done() and self._acquisition_task is task:
                self._acquisition_task = None

    async def _refresh_acquisition_execution(self) -> None:
        async with self._acquisition_execution_lock:
            if self._sustained_acquisition_enabled and self._acquisition_node.experiment_runtime_active:
                if not self.acquisition_execution_active:
                    self._acquisition_task = asyncio.create_task(self._run_acquisition())
            else:
                await self._finish_acquisition_execution()

    async def _run_acquisition(self) -> None:
        # Bounded synchronous iterations and lifecycle commands share the service
        # event loop: finalization cannot overlap a camera read or local append.
        while self._sustained_acquisition_enabled and self._acquisition_node.experiment_runtime_active:
            failed = False
            try:
                if not self._acquisition_node.expire_experiment_if_due():
                    if self._acquisition_node.scientific_acquisition_active:
                        self._acquisition_node.run_one_iteration()
            except Exception:
                failed = True
                logger.exception("sustained_acquisition_failed")
                try:
                    self._acquisition_node.stop_runtime()
                except Exception:
                    logger.exception("sustained_acquisition_cleanup_unconfirmed")
            try:
                if self._acquisition_node.experiment_runtime_active:
                    await asyncio.wait_for(self._publish_acquisition_evidence(),
                        timeout=self._acquisition_node.experiment_deadline_remaining_s)
                else:
                    await self._publish_acquisition_evidence()
            except asyncio.TimeoutError:
                # An unconfirmed publication cannot hold the recording deadline open.
                try:
                    expired = self._acquisition_node.expire_experiment_if_due()
                except Exception:
                    logger.exception("experiment_expiry_finalization_failed")
                    try:
                        self._acquisition_node.stop_runtime()
                    except Exception:
                        logger.exception("sustained_acquisition_cleanup_unconfirmed")
                    return
                if not expired and self._acquisition_node.experiment_runtime_active:
                    # The transport can time out before the Experiment does.
                    # Retry only through the deadline-bounded path above.
                    await asyncio.sleep(0)
                    continue
                # Recording is now quiescent. Publish its terminal evidence once
                # through existing transport timeouts, retaining failures for retry.
                try:
                    await self._publish_acquisition_evidence()
                except Exception:
                    logger.exception("sustained_acquisition_publication_unconfirmed")
            except Exception:
                # Existing cursors and producer retention keep unconfirmed evidence;
                # communication failure is not an acquisition-stop authorization.
                logger.exception("sustained_acquisition_publication_unconfirmed")
            if failed:
                return
            if (self._acquisition_node.experiment_runtime_active
                    and not self._acquisition_node.scientific_acquisition_active):
                await asyncio.sleep(self._acquisition_node.experiment_deadline_remaining_s)
            await asyncio.sleep(0)

    async def _publish_acquisition_evidence(self):
        await self.publish_new_artifact_manifest_evidence()
        await self.publish_new_runtime_evidence()

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Consume commands routed to this AcquisitionNode instance."""

        subjects = (f"messages.*.command.acquisition_node.{self._boundary.component_id}.*",
                    f"messages.command.acquisition_node.{self._boundary.component_id}.*")

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
                          if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES | DEPENDENT_MAINTENANCE_COMMANDS) else self.execute_command(command))
                await self._refresh_acquisition_execution()
                await self.publish_new_artifact_manifest_evidence()
                if command.session_id is not None:
                    await self.publish_new_runtime_evidence()
                    for pending in tuple(self._unpublished_evidence.values()):
                        if pending.session_id == command.session_id:
                            await self.publish_evidence(pending)
                if "request_nonce" in command.payload:
                    result = replace(result, payload={**result.payload, "request_nonce": command.payload["request_nonce"]})
                await self._boundary.publish_command_result(result, command.command_type)
                logger.info("command_result_published command_id=%s status=%s",
                            result.command_id, result.status)
                await message.ack()
                await _complete_maintenance_delivery(self._boundary, command, result)
            except Exception:
                logger.exception("command_delivery_processing_failed")
                raise

        subscriptions = []
        for subject in subjects:
            subscriptions.append(await self._boundary._require_jetstream().subscribe(subject, cb=receive, manual_ack=True,
                config=ConsumerConfig(deliver_policy=DeliverPolicy.NEW)))
        return tuple(subscriptions)

    def execute_command(
        self,
        command: RuntimeCommandMessage,
    ) -> RuntimeCommandResultMessage:
        """Execute one supported command once and return explicit result evidence."""

        previous = self._results_by_command_id.get(command.command_id)
        identity = command.to_dict()
        identity["payload"] = {k: v for k, v in command.payload.items() if k != "request_nonce"}
        if previous is not None:
            if self._commands_by_id.get(command.command_id) != identity:
                return self._result(command, "failed", False, "Conflicting runtime command identity", {})
            if command.command_type != "read_local_time":
                return previous

        logger.info(
            "execute_command_entered command_id=%s command_type=%s",
            command.command_id,
            command.command_type,
        )

        try:
            if command.target_id != self._boundary.component_id:
                raise ValueError("Command target does not match participant")
            if command.command_type not in {"check_readiness", "get_inventory", "reserve", "release_reservation", "initialize_session", "abort_session_initialization"}:
                AcquisitionNode._validate_session_id(command.session_id)
            if command.command_type not in {"check_readiness", "get_inventory", "reserve", "release_reservation", "initialize_session", "abort_session_initialization"} and command.session_id != self._acquisition_node.status()["session_id"]:
                raise RuntimeError("Command session_id does not match AcquisitionNode")
            if command.command_type == "get_inventory":
                payload = self._acquisition_node.get_inventory()
                if "request_nonce" in command.payload:
                    payload["request_nonce"] = command.payload["request_nonce"]
            elif command.command_type == "read_local_time":
                payload = {"received_local_time_s": monotonic(), "sent_local_time_s": monotonic(),
                           "acquisition_node_id": self._boundary.component_id,
                           "local_clock_resolution_s": get_clock_info("monotonic").resolution}
            elif command.command_type == "accept_synchronization_quality":
                self._acquisition_node.accept_synchronization_quality(command.session_id, command.source_id,
                                                                     command.payload["quality"])
                payload = {"confirmed": True}
            elif command.command_type == "activate_experiment_runtime":
                context = ActiveExperimentRuntimeContext.from_dict(command.payload["context"])
                deadline = self._acquisition_node.activate_experiment_runtime(context,
                    tuple(ExperimentRuntimeHealthMapping.from_dict(m) for m in command.payload["health_mapping"]))
                payload = {"confirmed": True, "experiment_id": context.experiment_id, "deadline": deadline}
            elif command.command_type == "finalize_experiment_scientific_outputs":
                experiment_id = command.payload["experiment_id"]
                if (not isinstance(experiment_id, str) or not experiment_id
                        or experiment_id not in self._acquisition_node._prepared_scientific_outputs):
                    raise ValueError("Unknown Experiment scientific outputs")
                manifests = self._acquisition_node.finalize_experiment_scientific_outputs(experiment_id)
                payload = {"experiment_id": experiment_id, "manifests": [m.to_dict() for m in manifests],
                           "confirmed": True}
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
                                         for item in command.payload["scientific_outputs"]),
                    configuration=ExperimentConfiguration.from_dict(command.payload["configuration"]))
                payload = {"experiment_id": experiment_id, "preparation": preparation.to_dict()}
                if preparation.required and not preparation.ready:
                    result = self._result(command, "failed", False, preparation.reason, payload)
                    self._results_by_command_id[command.command_id] = result
                    self._commands_by_id[command.command_id] = deepcopy(identity)
                    return result
            elif command.command_type == "check_experiment_capacity":
                payload = {"capacity": self._acquisition_node.check_experiment_capacity(
                    tuple(ScientificOutputSelection.from_dict(item) for item in command.payload["scientific_outputs"]),
                    ExperimentConfiguration.from_dict(command.payload["configuration"]))}
            elif command.command_type == "read_experiment_expiry":
                evidence = self._acquisition_node.read_experiment_expiry(command.payload["experiment_id"])
                payload = {"expiry_evidence": evidence.to_dict() if evidence is not None else None}
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
                    "scientific_observations": summary.scientific_observations,
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
        self._commands_by_id[command.command_id] = deepcopy(identity)
        return result

    async def publish_new_artifact_manifest_evidence(self) -> None:
        """Publish produced manifest lifecycle evidence through the existing boundary."""
        async with self._artifact_manifest_publication_lock:
            evidence = getattr(self._acquisition_node, "artifact_manifest_evidence", ())
            for message in evidence[self._published_artifact_manifest_count:]:
                await self.publish_evidence(message)
                self._published_artifact_manifest_count += 1

    async def publish_new_runtime_evidence(self) -> None:
        """Publish retained operational evidence once per confirmed cursor entry."""
        async with self._runtime_publication_lock:
            messages = self._acquisition_node.runtime_evidence
            for message in messages[self._published_runtime_evidence_count:]:
                await self.publish_evidence(message)
                self._published_runtime_evidence_count += 1

    async def publish_evidence(self, message: RuntimeEvidenceMessage) -> None:
        """Publish AcquisitionNode-owned durable runtime evidence."""

        if message.source_id != self._boundary.component_id:
            raise ValueError("Runtime evidence source_id does not match AcquisitionNode")
        previous = self._unpublished_evidence.get(message.evidence_id)
        if previous is not None and json.dumps(previous.to_dict(), sort_keys=True) != json.dumps(message.to_dict(), sort_keys=True):
            raise ValueError("Conflicting retained AcquisitionNode evidence identity")
        retained = RuntimeEvidenceMessage.from_dict(deepcopy(message.to_dict()))
        self._unpublished_evidence[message.evidence_id] = retained
        await self._boundary.publish_evidence(retained)
        self._unpublished_evidence.pop(message.evidence_id, None)

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


SESSION_CLOSEOUT_OPERATIONS = frozenset({"admit_session_kill", "preserve_session_acquisition",
    "read_session_closeout", "preserve_session_terminal_record", "release_session"})


def read_closeout_result(boundary, record, operation):
    """Validate owner and attempt identity before reusing a closeout resolution."""
    data = json.loads(record.data)
    required = {"result_id", "command_id", "session_id", "source_id", "target_id", "status", "success", "reason", "payload"}
    if not isinstance(data, dict) or not required.issubset(data) or not isinstance(data["payload"], dict):
        raise ValueError("Incomplete closeout result history")
    result = RuntimeCommandResultMessage.from_dict(data)
    route = parse_runtime_subject(record.subject)
    if (any(not isinstance(value, str) or not value for value in
            (result.result_id, result.command_id, result.session_id, result.source_id, result.target_id))
            or route != parse_runtime_subject(build_runtime_subject(result.session_id, "command_result",
                boundary.component_type, boundary.component_id, operation))
            or result.source_id != boundary.component_id
            or result.command_id != json.dumps([result.session_id, operation], separators=(",", ":"))
            or type(result.success) is not bool or result.status not in {"succeeded", "failed"}
            or result.success != (result.status == "succeeded")
            or (result.reason is not None and not isinstance(result.reason, str))
            or not isinstance(result.payload.get("request_nonce"), str) or not result.payload["request_nonce"]
            or not isinstance(result.payload.get("request_payload"), dict)
            or result.payload["request_payload"].get("request_nonce") != result.payload["request_nonce"]):
        raise ValueError("Closeout result history has inconsistent correlation")
    if result.success:
        if result.payload.get("session_id") != result.session_id:
            raise ValueError("Closeout result Session mismatch")
        if operation == "admit_session_kill" and result.payload.get("kill_admitted") is not True:
            raise ValueError("Kill admission is unconfirmed")
        if operation == "release_session" and result.payload.get("released") is not True:
            raise ValueError("Binding release is unconfirmed")
        if operation in {"read_session_closeout", "preserve_session_acquisition", "preserve_session_terminal_record"}:
            if (result.payload.get("preservation_confirmed") is not True
                    or not isinstance(result.payload.get("compilation_summary"), dict)
                    or result.payload["compilation_summary"].get("session_id") != result.session_id):
                raise ValueError("Closeout preservation history is unconfirmed")
    return result


async def read_scoped_result_history(boundary, command, validate):
    """Read the complete retained owner/Session/operation history before mutation or reuse."""
    jetstream = boundary._require_jetstream()
    history = await jetstream.stream_info("LAB_COMMAND_RESULTS")
    if not NatsIngestorCommunication._receiving_history_intact(history):
        raise RuntimeError("Command-result history is unconfirmed")
    subject = build_runtime_subject(command.session_id, "command_result",
        boundary.component_type, boundary.component_id, command.command_type)
    sequence, matched, resolutions = 1, None, {}
    while sequence <= history.state.last_seq:
        try:
            record = await jetstream.get_msg("LAB_COMMAND_RESULTS", seq=sequence, subject=subject, next=True)
        except NotFoundError:
            break
        if record.seq > history.state.last_seq:
            break
        if record.subject != subject or record.seq < sequence:
            raise ValueError("Command-result history is inconsistent")
        previous = validate(record)
        nonce = previous.payload["request_nonce"]
        content = previous.to_dict()
        if nonce in resolutions and resolutions[nonce] != content:
            raise ValueError("Command-result history contains conflicting attempt resolutions")
        resolutions[nonce] = content
        if nonce == command.payload["request_nonce"]:
            if (previous.command_id != command.command_id or previous.target_id != command.source_id
                    or ("request_payload" in previous.payload and previous.payload["request_payload"] != command.payload)):
                raise ValueError("Command-result history contains conflicting same-attempt identity")
            matched = previous
        sequence = record.seq + 1
    current = await jetstream.stream_info("LAB_COMMAND_RESULTS")
    if (current.created != history.created or current.state.last_seq < history.state.last_seq
            or not NatsIngestorCommunication._receiving_history_intact(current)):
        raise RuntimeError("Command-result history changed during admission")
    return matched


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
        self._closeout_lock = asyncio.Lock()
        self._pending_closeout_results = {}

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Receive readiness and Session preparation over the existing command stream."""
        async def receive(message: Any) -> RuntimeCommandResultMessage | None:
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            if command.command_type in SESSION_CLOSEOUT_OPERATIONS:
                async with self._closeout_lock:
                    key = json.dumps(command.to_dict(), sort_keys=True)
                    retained = self._pending_closeout_results.get(key)
                    try:
                        _validate_owner_request(self._boundary, command)
                        for pending in self._pending_closeout_results.values():
                            if (pending.session_id == command.session_id
                                    and pending.payload.get("request_nonce") == command.payload.get("request_nonce")
                                    and (pending.command_id != command.command_id
                                        or pending.target_id != command.source_id
                                        or pending.payload.get("request_payload") != command.payload)):
                                raise ValueError("Retained closeout resolution conflicts with attempt identity")
                        matched = await read_scoped_result_history(self._boundary, command,
                            lambda record: read_closeout_result(self._boundary, record, command.command_type))
                        if retained is not None and matched is not None and retained.to_dict() != matched.to_dict():
                            raise ValueError("Persisted history conflicts with retained closeout resolution")
                        if matched is not None and not matched.success:
                            result = matched
                        elif retained is not None and not retained.success:
                            result = retained
                        else:
                            result = await self._execute_closeout_command(command)
                            if result.success and (matched is not None or retained is not None):
                                result = matched if matched is not None else retained
                    except Exception as error:
                        result = _participant_result(self._boundary, command, False, str(error),
                            {"request_nonce": command.payload.get("request_nonce"), "request_payload": deepcopy(command.payload)})
                    self._pending_closeout_results[key] = deepcopy(result)
                    await self._boundary.publish_command_result(result, command.command_type)
                    self._pending_closeout_results.pop(key, None)
                    await message.ack()
                return
            result = (await self._execute_evidence_readback(command)
                      if command.command_type in {"compile_session_evidence", "verify_acquisition_receipt",
                                                 "read_runtime_evidence_acceptance", "preserve_service_evidence"} else
                      await _execute_maintenance_command(self._boundary, self._ingestor, command)
                      if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES | DEPENDENT_MAINTENANCE_COMMANDS) else
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
            return result
        return await _subscribe_participant_commands(self._boundary, receive)

    async def _execute_closeout_command(self, command):
        nonce = command.payload.get("request_nonce")
        try:
            _validate_owner_request(self._boundary, command)
            if command.command_id != json.dumps([command.session_id, command.command_type], separators=(",", ":")):
                raise ValueError("Closeout command identity must match Session and operation")
            intake = self._ingestor
            operation = command.command_type
            supplied = set(command.payload) - {"request_nonce"}
            if operation == "admit_session_kill":
                if supplied != {"operator_authorized"} or command.payload["operator_authorized"] is not True:
                    raise ValueError("Kill admission requires explicit operator authorization")
                if intake.session_id is None:
                    saved = intake.read_session_closeout(command.session_id)
                    if saved["acquisition_preservation_eligible"]:
                        raise RuntimeError("Kill cannot replace finalized Normal Stop")
                else:
                    intake.admit_kill_closeout(command.session_id)
                payload = {"session_id": command.session_id, "kill_admitted": True}
            elif operation == "preserve_session_acquisition":
                if supplied != {"mode", "marker", "session_record", "controller_evidence", "uncertainties"}:
                    raise ValueError("Closeout preservation payload is incomplete")
                mode = command.payload["mode"]
                if mode not in {"normal", "kill"}:
                    raise ValueError("Unknown closeout mode")
                if intake.session_id is None:
                    payload = intake.read_session_closeout(command.session_id)
                    if (payload["session_record"]["accepted_session_config"] != command.payload["session_record"]["accepted_session_config"]
                            or (mode == "normal" and (not payload["acquisition_preservation_eligible"]
                                or payload["finalized_intake"]["marker"] != command.payload["marker"]))
                            or (mode == "kill" and payload["acquisition_preservation_eligible"])):
                        raise RuntimeError("Saved closeout does not match the requested operation")
                    return _participant_result(self._boundary, command, True, None,
                        {**payload, "request_nonce": nonce, "request_payload": deepcopy(command.payload)})
                if mode == "normal":
                    marker = RuntimeEvidenceMessage.from_dict(command.payload["marker"])
                    receipt = await self.verify_acquisition_evidence_receipt(marker)
                    if not receipt.get("durable_receipt_confirmed"):
                        raise RuntimeError(f"Complete acquisition receipt is unconfirmed: {receipt.get('reason')}")
                    intake.finalize_acquisition_intake(marker, receipt)
                payload = intake.preserve_session_closeout(command.session_id, mode=mode,
                    session_record=command.payload["session_record"],
                    controller_evidence=command.payload["controller_evidence"],
                    uncertainties=command.payload["uncertainties"])
            elif operation == "preserve_session_terminal_record":
                if supplied != {"session_record"}:
                    raise ValueError("Terminal persistence requires the Controller Session Record")
                payload = intake.preserve_terminal_session_record(command.session_id, command.payload["session_record"])
            elif operation == "read_session_closeout":
                if supplied:
                    raise ValueError("Closeout readback accepts only a Session identity")
                payload = intake.read_session_closeout(command.session_id)
            elif operation == "release_session":
                if supplied:
                    raise ValueError("Session release accepts only its Session identity")
                if intake.session_id == command.session_id:
                    intake.release_session(command.session_id)
                elif intake.session_id is not None:
                    raise RuntimeError("Release cannot retire another Session binding")
                else:
                    preserved = intake.read_session_closeout(command.session_id)
                    if ((preserved["session_record"].get("final_session_status") or {}).get("state")
                            not in {"completed", "failed", "aborted"}):
                        raise RuntimeError("Prior binding release is unconfirmed")
                subscription = self._evidence_subscriptions.get(command.session_id)
                if subscription is not None:
                    await subscription.unsubscribe()
                    self._evidence_subscriptions.pop(command.session_id, None)
                payload = {"session_id": command.session_id, "released": True}
            else:
                raise ValueError("Unsupported closeout operation")
            return _participant_result(self._boundary, command, True, None,
                {**payload, "request_nonce": nonce, "request_payload": deepcopy(command.payload)})
        except Exception as error:
            return _participant_result(self._boundary, command, False, str(error),
                {"request_nonce": nonce, "request_payload": deepcopy(command.payload)})


    async def _execute_evidence_readback(self, command):
        nonce = command.payload.get("request_nonce")
        try:
            if command.command_type == "preserve_service_evidence":
                if (command.session_id is not None or command.target_id != self._boundary.component_id
                        or self._boundary.component_id != self._ingestor._component_id
                        or any(not isinstance(v, str) or not v for v in
                               (nonce, command.command_id, command.source_id))
                        or set(command.payload) != {"evidence", "acceptance_window_s", "request_nonce"}
                        or not self._boundary.check_ready().ready):
                    raise ValueError("Producer preservation requires exact framework request identities")
                window = command.payload["acceptance_window_s"]
                from math import isfinite
                if type(window) not in {int, float} or not isfinite(window) or window < 0:
                    raise ValueError("A finite nonnegative acceptance window is required")

                def validate(record):
                    previous = RuntimeCommandResultMessage.from_dict(json.loads(record.data))
                    request = previous.payload.get("request_payload")
                    previous_nonce = previous.payload.get("request_nonce")
                    if (record.subject != build_runtime_subject(None, "command_result", "ingestor",
                            self._boundary.component_id, command.command_type)
                            or previous.session_id is not None or previous.source_id != self._boundary.component_id
                            or any(not isinstance(v, str) or not v for v in
                                   (previous.result_id, previous.command_id, previous.target_id, previous_nonce))
                            or type(previous.success) is not bool or previous.status not in {"succeeded", "failed"}
                            or previous.success != (previous.status == "succeeded")
                            or not isinstance(request, dict) or request.get("request_nonce") != previous_nonce):
                        raise ValueError("Producer preservation history correlation is unconfirmed")
                    if previous.command_id == command.command_id:
                        if (previous.target_id != command.source_id or
                                {k: v for k, v in request.items() if k != "request_nonce"} !=
                                {k: v for k, v in command.payload.items() if k != "request_nonce"}):
                            raise ValueError("Conflicting producer preservation command identity")
                    if previous.success and (previous.payload.get("acceptance_confirmed") is not True
                            or previous.payload.get("archival_confirmed") is not True
                            or previous.payload.get("evidence") != request.get("evidence")):
                        raise ValueError("Producer history lacks exact preservation coverage")
                    return previous

                async with self._closeout_lock:
                    for retained in self._pending_closeout_results.values():
                        if retained.session_id is None and retained.payload.get("request_nonce") == nonce and (
                                retained.command_id != command.command_id or retained.target_id != command.source_id
                                or retained.payload.get("request_payload") != command.payload):
                            raise ValueError("Retained producer preservation conflicts with request identity")
                    matched = await read_scoped_result_history(self._boundary, command, validate)
                    key = json.dumps(command.to_dict(), sort_keys=True)
                    pending = self._pending_closeout_results.get(key)
                    if pending is not None and matched is not None and pending.to_dict() != matched.to_dict():
                        raise ValueError("Producer preservation history conflicts with retained result")
                    previous = matched if matched is not None else pending
                    if previous is not None and not previous.success:
                        return previous
                    payload = await self._ingestor.preserve_service_evidence(
                        command.payload["evidence"], command.source_id, window)
                    result = previous if previous is not None else _participant_result(self._boundary, command, True, None,
                        {**payload, "request_nonce": nonce, "request_payload": deepcopy(command.payload)})
                    self._pending_closeout_results[key] = deepcopy(result)
                    return result
            _validate_owner_request(self._boundary, command)
            if self._boundary.component_id != self._ingestor._component_id:
                raise ValueError("Ingestor communication identity differs from its owner")
            if command.command_type == "read_runtime_evidence_acceptance":
                if set(command.payload) != {"evidence", "request_nonce"}:
                    raise ValueError("Acceptance readback requires exactly one runtime evidence message")
                evidence = RuntimeEvidenceMessage.from_dict(command.payload["evidence"])
                if evidence.session_id != command.session_id:
                    raise ValueError("Evidence does not match the requested Session")
                journal = self._ingestor.recovery_journal_path
                confirmed = False
                if journal is not None:
                    with self._ingestor.durable_runtime_evidence_history_guard(
                            command.session_id, journal, (evidence,)) as confirmed:
                        payload = {"evidence_id": evidence.evidence_id,
                                   "durable_acceptance_confirmed": confirmed,
                                   "request_nonce": nonce}
                else:
                    if self._ingestor.session_id is None:
                        self._ingestor.read_session_closeout(command.session_id)
                        confirmation = self._ingestor._storage_manager.get_persisted_session_preservation_confirmation(command.session_id)
                        confirmed = (evidence.evidence_id in confirmation["compilation_summary"]["runtime_evidence_origins"]["ingestor"]
                            and evidence.to_dict() in confirmation["runtime_evidence"])
                    payload = {"evidence_id": evidence.evidence_id,
                               "durable_acceptance_confirmed": confirmed, "request_nonce": nonce}
                return _participant_result(self._boundary, command, confirmed,
                    None if confirmed else "Exact journal-backed evidence acceptance is unconfirmed", payload)
            if command.command_type == "compile_session_evidence":
                if set(command.payload) != {"request_nonce"}:
                    raise ValueError("Compilation accepts only the requested Session identity")
                payload = self._ingestor.compile_durable_session_evidence(command.session_id)
                return _participant_result(self._boundary, command, True, None, {**payload, "request_nonce": nonce})
            if set(command.payload) != {"marker", "request_nonce"} or not isinstance(command.payload["marker"], dict):
                raise ValueError("Receipt verification requires exactly one completion marker")
            marker = RuntimeEvidenceMessage.from_dict(command.payload["marker"])
            if marker.session_id != command.session_id:
                raise ValueError("Completion marker does not match the requested Session")
            proof = await self.verify_acquisition_evidence_receipt(marker)
            confirmed = proof.get("durable_receipt_confirmed") is True
            return _participant_result(self._boundary, command, confirmed,
                None if confirmed else proof.get("reason"), {**proof, "request_nonce": nonce})
        except Exception as error:
            return _participant_result(self._boundary, command, False, str(error),
                {"request_nonce": nonce, **({"request_payload": deepcopy(command.payload)}
                    if command.command_type == "preserve_service_evidence" else {})})

    async def subscribe_evidence(
        self,
        session_id: str | None,
        callback: RuntimeEvidenceCallback | None = None,
    ) -> Subscription:
        """Consume Session evidence with restart-safe explicit ACK progress."""

        if session_id is None:
            self._ingestor.compile_framework_runtime_evidence()
        elif self._ingestor.recovery_journal_path is None or self._ingestor.session_id != session_id:
            raise ValueError("Broker evidence intake requires the matching Session recovery journal")
        subject = "messages.evidence.*.*.*" if session_id is None else f"messages.{session_id}.evidence.*.*.*"
        jetstream = self._boundary._require_jetstream()
        options = {}
        journal = self._ingestor.recovery_journal_path
        if session_id is not None:
            stream = await jetstream.stream_info("LAB_EVIDENCE")
            durable = self._session_consumer_name(session_id)
            try:
                consumer = await jetstream.consumer_info("LAB_EVIDENCE", durable)
            except NotFoundError:
                # Only a fresh journal and intact stream establish a new receiving
                # origin. Missing old broker state cannot be silently reconstructed.
                origin_known = (not self._ingestor.accepted_runtime_evidence
                                and self._receiving_history_intact(stream))
                config = ConsumerConfig(
                    durable_name=durable, deliver_policy=DeliverPolicy.ALL,
                    ack_policy=AckPolicy.EXPLICIT, max_ack_pending=1,
                    filter_subject=subject, mem_storage=False,
                    metadata={"session_id": session_id,
                              "stream_created": stream.created.isoformat(),
                              "receiving_origin_verified": str(origin_known).lower()},
                )
            else:
                self._validate_session_consumer(consumer, stream, session_id)
                # Reusing broker ACK state does not establish local journal continuity;
                # receipt confirmation reconciles the retained histories separately.
                config = consumer.config
            if (self._ingestor.session_id != session_id
                    or self._ingestor.recovery_journal_path != journal):
                raise RuntimeError("Session binding changed during evidence subscription")
            options = {"durable": durable, "stream": "LAB_EVIDENCE", "config": config}

        async def receive(message: Any) -> None:
            if session_id is not None and (
                    self._ingestor.session_id != session_id
                    or self._ingestor.recovery_journal_path != journal):
                raise RuntimeError("Session binding changed before evidence intake")
            evidence = RuntimeEvidenceMessage.from_dict(
                json.loads(message.data.decode("utf-8"))
            )
            tokens = message.subject.split(".")
            component_index = 2 if session_id is None else 3
            if (len(tokens) != component_index + 3 or evidence.session_id != session_id
                    or message.subject != build_runtime_subject(session_id, "evidence",
                        tokens[component_index], evidence.source_id, evidence.evidence_type)):
                raise ValueError("Runtime evidence Session/source/type identity does not match its NATS subject")
            audit = self._ingestor.receive_runtime_evidence(evidence)
            if audit.reason == "acquisition_intake_finalized":
                if self._ingestor.session_id != session_id or self._ingestor.recovery_journal_path != journal:
                    raise RuntimeError("Finalized Session binding changed before discard acknowledgment")
                await message.ack_sync()
                return
            if session_id is not None and (not audit.accepted
                    or not self._ingestor.has_durable_runtime_evidence(evidence)):
                raise ValueError("Session evidence was not durably accepted")
            if callback is not None and audit.accepted and audit.reason != "already_accepted":
                await callback(evidence)
            if session_id is None:
                await message.ack()
            else:
                if (self._ingestor.session_id != session_id
                        or self._ingestor.recovery_journal_path != journal):
                    raise RuntimeError("Session binding changed before evidence acknowledgment")
                await message.ack_sync()

        subscription = await jetstream.subscribe(
            subject,
            cb=receive,
            manual_ack=True,
            **options,
        )
        if session_id is not None and (
                self._ingestor.session_id != session_id
                or self._ingestor.recovery_journal_path != journal):
            await subscription.unsubscribe()
            raise RuntimeError("Session binding changed during evidence subscription")
        return subscription

    @staticmethod
    def _session_consumer_name(session_id: str) -> str:
        return "ingestor-session-" + sha256(session_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _receiving_history_intact(stream: Any) -> bool:
        state = stream.state
        # With no trusted narrower Session start boundary, require retained history
        # from stream origin. Stream cardinality detects holes here; it is not
        # a producer evidence-count registry or a substitute for ACK progress.
        return (stream.config.storage == StorageType.FILE
                and stream.config.retention == RetentionPolicy.LIMITS
                and stream.config.first_seq in (None, 0, 1)
                and (state.first_seq == 1 or state.first_seq == state.last_seq == 0)
                and state.last_seq >= 0
                and state.num_deleted in (None, 0) and not state.lost
                and state.messages == state.last_seq)

    @classmethod
    def _validate_session_consumer(cls, consumer: Any, stream: Any, session_id: str) -> None:
        config = consumer.config
        metadata = config.metadata or {}
        if (consumer.stream_name != "LAB_EVIDENCE"
                or consumer.name != cls._session_consumer_name(session_id)
                or config.durable_name != consumer.name
                or config.deliver_policy != DeliverPolicy.ALL
                or config.ack_policy != AckPolicy.EXPLICIT
                or config.max_ack_pending != 1 or config.mem_storage
                or config.filter_subject != f"messages.{session_id}.evidence.*.*.*"
                or config.filter_subjects
                or config.deliver_group or config.max_deliver not in (None, -1)
                or metadata.get("session_id") != session_id
                or metadata.get("stream_created") != stream.created.isoformat()
                or metadata.get("receiving_origin_verified") not in {"true", "false"}):
            raise ValueError("Session receiving state is invalid or has changed")

    @staticmethod
    def _acknowledgment_progress_valid(consumer: Any, last_sequence: int) -> bool:
        floor, delivered = consumer.ack_floor, consumer.delivered
        return (floor is not None and delivered is not None
                and all(type(value) is int for value in (
                    floor.consumer_seq, floor.stream_seq,
                    delivered.consumer_seq, delivered.stream_seq))
                and (floor.consumer_seq == 0) == (floor.stream_seq == 0)
                and 0 <= floor.consumer_seq <= delivered.consumer_seq
                and 0 <= floor.stream_seq <= delivered.stream_seq <= last_sequence)

    async def verify_acquisition_evidence_receipt(
        self, marker: RuntimeEvidenceMessage,
    ) -> dict[str, Any]:
        """Check journal-backed receipt through a marker, not Normal Stop completion."""
        result = {"session_id": marker.session_id, "evidence_id": marker.evidence_id,
                  "durable_receipt_confirmed": False, "reason": "unverifiable_progress"}
        session_id = marker.session_id
        finalized = self._ingestor.finalized_acquisition_intake(session_id)
        if finalized is not None:
            if finalized["marker"] != marker.to_dict():
                result["reason"] = "finalized_marker_mismatch"
                return result
            return deepcopy(finalized["receipt"])
        if (session_id is None or self._ingestor.session_id != session_id
                or marker.evidence_type != "acquisition_evidence_completion"
                or not self._ingestor.has_durable_runtime_evidence(marker)):
            result["reason"] = "marker_not_durably_accepted"
            return result
        journal = self._ingestor.recovery_journal_path
        try:
            canonical_content = self._ingestor._evidence_content
            marker_content = canonical_content(marker)
            jetstream = self._boundary._require_jetstream()
            stream = await jetstream.stream_info("LAB_EVIDENCE")
            consumer = await jetstream.consumer_info(
                "LAB_EVIDENCE", self._session_consumer_name(session_id))
            self._validate_session_consumer(consumer, stream, session_id)
            if (consumer.config.metadata["receiving_origin_verified"] != "true"
                    or not self._receiving_history_intact(stream)):
                result["reason"] = "missing_history_or_receiving_origin"
                return result
            subject = build_runtime_subject(session_id, "evidence", "controller",
                                            marker.source_id, marker.evidence_type)
            published = await jetstream.get_last_msg("LAB_EVIDENCE", subject)
            if (published.subject != subject or published.seq <= 0
                    or canonical_content(RuntimeEvidenceMessage.from_dict(json.loads(published.data))) != marker_content):
                result["reason"] = "marker_publication_unconfirmed"
                return result
            if not self._acknowledgment_progress_valid(consumer, stream.state.last_seq):
                return result
            floor = consumer.ack_floor
            if floor.stream_seq < published.seq:
                result["reason"] = "incomplete_acknowledgment_progress"
                return result
            required = {}
            sequence = 1
            while sequence <= published.seq:
                record = await jetstream.get_msg(
                    "LAB_EVIDENCE", seq=sequence,
                    subject=f"messages.{session_id}.evidence.*.*.*", next=True)
                routing = parse_runtime_subject(record.subject)
                if (type(record.seq) is not int or not sequence <= record.seq <= published.seq
                        or routing["session_id"] != session_id or routing["message_class"] != "evidence"):
                    raise ValueError("Session publication history is unverifiable")
                item = RuntimeEvidenceMessage.from_dict(json.loads(record.data))
                if item.session_id != session_id:
                    raise ValueError("Published evidence does not match the Session")
                content = canonical_content(item)
                previous = required.get(item.evidence_id)
                if previous is not None and canonical_content(previous) != content:
                    raise ValueError("Conflicting evidence identity in publication history")
                required[item.evidence_id] = item
                if record.seq == published.seq and content != marker_content:
                    raise ValueError("Completion marker changed during history readback")
                sequence = record.seq + 1
            # Recheck history after asynchronous readback; publication and journal
            # acceptance are separate from the broker's contiguous ACK floor.
            current = await jetstream.stream_info("LAB_EVIDENCE")
            current_consumer = await jetstream.consumer_info(
                "LAB_EVIDENCE", self._session_consumer_name(session_id))
            # Cover history changes during consumer readback as well as the scan.
            current = await jetstream.stream_info("LAB_EVIDENCE")
            self._validate_session_consumer(current_consumer, current, session_id)
            if (current.created != stream.created or not self._receiving_history_intact(current)
                    or current_consumer.created != consumer.created
                    or not self._acknowledgment_progress_valid(current_consumer, current.state.last_seq)
                    or current_consumer.ack_floor.stream_seq < published.seq
                    or self._ingestor.session_id != session_id
                    or self._ingestor.recovery_journal_path != journal
                    or not self._ingestor.has_durable_runtime_evidence(marker)):
                return result
            with self._ingestor.durable_runtime_evidence_history_guard(
                    session_id, journal, required.values()) as confirmed:
                if not confirmed:
                    result["reason"] = "journal_history_unconfirmed"
                    return result
                result.update(durable_receipt_confirmed=True, reason="contiguous_durable_receipt",
                              marker_stream_sequence=published.seq,
                              acknowledged_stream_sequence=floor.stream_seq,
                              acknowledged_consumer_sequence=floor.consumer_seq)
                return result
        except Exception as error:
            result["reason"] = f"unverifiable_progress: {error}"
        return result


def _validate_owner_request(boundary, command) -> None:
    if (command.target_id != boundary.component_id
            or any(not isinstance(value, str) or not value for value in
                   (command.command_id, command.source_id, command.session_id))):
        raise ValueError("Owner request requires matching target, command, requester, and Session identities")
    if not isinstance(command.payload.get("request_nonce"), str) or not command.payload["request_nonce"]:
        raise ValueError("Owner request requires current-request reply correlation")
    if not boundary.check_ready().ready:
        raise ConnectionError("Required NATS connection is not ready")


class NatsStorageManagerCommunication:
    """Route Session-scoped persistence and current readback to one authoritative storage owner."""

    def __init__(self, boundary: NatsCommunicationBoundary, storage_manager: PersistentStorageManager):
        if (not isinstance(storage_manager, PersistentStorageManager)
                or boundary.component_type != "storage_manager"
                or boundary.component_id != storage_manager._component_id):
            raise ValueError("Storage communication must match its authoritative owner")
        self._boundary = boundary
        self._storage_manager = storage_manager
        self._collection_command_lock = asyncio.Lock()
        self._pending_collection_results = {}

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        """Receive existing command envelopes; publish owner results before acknowledging delivery."""
        async def receive(message):
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            if command.command_type in {"collect_saved_artifacts", "close_session_evidence_archive"}:
                async with self._collection_command_lock:
                    identity = json.dumps(command.to_dict(), sort_keys=True)
                    result = self._pending_collection_results.get(identity)
                    if result is None:
                        result = await self._execute_saved_session_attempt(command)
                        self._pending_collection_results[identity] = deepcopy(result)
                    elif result.success and command.command_type == "close_session_evidence_archive":
                        result = await self._execute_saved_session_attempt(command, retained_result=result)
                    await self._boundary.publish_command_result(result, command.command_type)
                    self._pending_collection_results.pop(identity, None)
            else:
                result = (await _execute_maintenance_command(self._boundary, self._storage_manager, command)
                          if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"}
                                                     | SERVICE_RECOVERY_COMMAND_TYPES | DEPENDENT_MAINTENANCE_COMMANDS)
                          else self.execute_command(command))
                await self._boundary.publish_command_result(result, command.command_type)
            await message.ack()
            return result
        return await _subscribe_participant_commands(self._boundary, receive)

    def _validate_saved_session_request(self, command):
        _validate_owner_request(self._boundary, command)
        if command.command_type == "close_session_evidence_archive":
            if (set(command.payload) != {"request_nonce"}
                    or command.command_id != json.dumps(
                        [command.session_id, command.command_type], separators=(",", ":"))):
                raise ValueError("Archive closure requires its canonical Session/operation identity and reply correlation")
            return
        if (set(command.payload) != {"request_nonce", "evidence_id"}
                or not isinstance(command.payload["evidence_id"], str) or not command.payload["evidence_id"]):
            raise ValueError("Saved collection requires only a stable evidence identity and reply correlation")
        if command.command_id != json.dumps(
                [command.session_id, command.payload["evidence_id"]], separators=(",", ":")):
            raise ValueError("Collection command identity must match its Session and evidence identity")

    async def _execute_saved_session_attempt(self, command, *, retained_result=None):
        # No storage lock is borrowed across broker readback. The caller keeps
        # attempt resolution and result publication serialized together.
        try:
            self._validate_saved_session_request(command)
            matched = await read_scoped_result_history(self._boundary, command,
                lambda record: self._read_saved_session_result(record, command.command_type))
            if retained_result is not None:
                if matched is not None and matched.to_dict() != retained_result.to_dict():
                    raise ValueError("Collection result history conflicts with the retained attempt resolution")
                return self._reconfirm_archive_closure(command, retained_result)
            if matched is not None:
                if matched.success and command.command_type == "close_session_evidence_archive":
                    return self._reconfirm_archive_closure(command, matched)
                return matched
            return self.execute_command(command)
        except Exception as error:
            return _participant_result(self._boundary, command, False, str(error),
                {"request_nonce": command.payload.get("request_nonce")})

    def _reconfirm_archive_closure(self, command, result):
        confirmation = self._storage_manager.get_persisted_session_preservation_confirmation(command.session_id)
        if (confirmation is None
                or confirmation["compilation_summary"].get("archive_closed") is not True
                or confirmation["compilation_summary"] != result.payload["compilation_summary"]):
            raise RuntimeError("Closed archive history lacks matching current preservation")
        return self.execute_command(command)

    def _read_saved_session_result(self, record, operation):
        """Validate scoped persisted correlation before treating a result as unrelated."""
        data = json.loads(record.data)
        required = {"result_id", "command_id", "session_id", "source_id", "target_id",
                    "status", "success", "reason", "payload"}
        if (not isinstance(data, dict) or not required.issubset(data)
                or not isinstance(data["payload"], dict)):
            raise ValueError("Collection result history lacks required result fields")
        result = RuntimeCommandResultMessage.from_dict(data)
        if (any(not isinstance(value, str) or not value for value in
                (result.result_id, result.command_id, result.session_id, result.source_id, result.target_id))
                or not isinstance(result.payload.get("request_nonce"), str)
                or not result.payload["request_nonce"]
                or type(result.success) is not bool
                or result.status not in {"succeeded", "failed"}
                or result.success != (result.status == "succeeded")
                or (result.reason is not None and not isinstance(result.reason, str))):
            raise ValueError("Collection result history has invalid correlation or final status")
        routing = parse_runtime_subject(record.subject)
        if (routing["session_id"] != result.session_id
                or routing["message_class"] != "command_result"
                or routing["component_type"] != self._boundary.component_type
                or routing["component_id"] != result.source_id
                or result.source_id != self._boundary.component_id
                or routing["message_type"] != operation):
            raise ValueError("Collection result history disagrees with its NATS subject")
        identity = json.loads(result.command_id)
        if (not isinstance(identity, list) or len(identity) != 2
                or identity[0] != result.session_id
                or not isinstance(identity[1], str) or not identity[1]
                or result.command_id != json.dumps(identity, separators=(",", ":"))):
            raise ValueError("Collection result history has inconsistent Session/evidence command identity")
        if "session_id" in result.payload and result.payload["session_id"] != result.session_id:
            raise ValueError("Collection result payload disagrees with its Session")
        if operation == "close_session_evidence_archive":
            if identity[1] != operation:
                raise ValueError("Closure result history has inconsistent operation identity")
            if result.success:
                closure = result.payload.get("closure_outcome")
                summary = result.payload.get("compilation_summary")
                if (not isinstance(closure, dict) or closure.get("session_id") != result.session_id
                        or closure.get("archive_closed") is not True
                        or closure.get("archival_confirmed") is not True
                        or not isinstance(summary, dict) or summary.get("session_id") != result.session_id
                        or summary.get("archive_closed") is not True):
                    raise ValueError("Successful closure history lacks confirmed archive preservation")
            return result
        if "collection_status" in result.payload:
            status = result.payload["collection_status"]
            if not isinstance(status, dict) or status.get("session_id") != result.session_id:
                raise ValueError("Collection status history disagrees with its Session")
        if "collection_outcome" in result.payload:
            outcome = result.payload["collection_outcome"]
            if not isinstance(outcome, dict):
                raise ValueError("Collection result history has an invalid outcome")
            evidence = RuntimeEvidenceMessage.from_dict(outcome["collection_evidence"])
            if (outcome.get("session_id") != result.session_id
                    or evidence.session_id != result.session_id
                    or evidence.evidence_id != identity[1] or evidence.source_id != result.source_id):
                raise ValueError("Collection result history has inconsistent collection evidence identity")
        if result.success and (not isinstance(result.payload.get("collection_outcome"), dict)
                or result.payload["collection_outcome"].get("archival_confirmed") is not True
                or result.payload["collection_outcome"].get("artifact_collection_result", {}).get("succeeded") is not True):
            raise ValueError("Successful collection result lacks confirmed collection preservation")
        return result

    def execute_command(self, command: RuntimeCommandMessage) -> RuntimeCommandResultMessage:
        """Execute scoped owner persistence/readback, never recovery or arbitrary remote method calls."""
        nonce = command.payload.get("request_nonce")
        try:
            if command.command_type == "check_readiness":
                return _execute_service_command(self._boundary, self._storage_manager, command, {})
            _validate_owner_request(self._boundary, command)
            if command.command_type == "check_experiment_capacity":
                payload = {"capacity": self._storage_manager.check_experiment_capacity(command.payload.get("required_bytes"))}
            elif command.command_type in {"get_saved_session_collection_status", "collect_saved_artifacts"}:
                collecting = command.command_type == "collect_saved_artifacts"
                expected = {"request_nonce", "evidence_id"} if collecting else {"request_nonce"}
                if set(command.payload) != expected:
                    raise ValueError("Saved collection accepts only Session and stable evidence identity")
                if collecting:
                    self._validate_saved_session_request(command)
                status = self._storage_manager.get_saved_session_collection_status(command.session_id)
                payload = {"session_id": command.session_id, "collection_status": status}
                if collecting:
                    if not status["eligible"] or not status["collection_available"]:
                        return _participant_result(self._boundary, command, False,
                            status["availability_reason"] or status["eligibility_reason"],
                            {**payload, "request_nonce": nonce})
                    # The owner revalidates under its collection/preservation guards;
                    # this status snapshot never authorizes retrieval on its own.
                    outcome = self._storage_manager.collect_saved_artifacts(command.session_id,
                        evidence_id=command.payload["evidence_id"], require_eligible=True)
                    payload["collection_outcome"] = outcome
                    confirmed = (outcome["archival_confirmed"] is True
                                 and outcome["artifact_collection_result"]["succeeded"] is True)
                    return _participant_result(self._boundary, command, confirmed,
                        None if confirmed else "Collection or collection-evidence preservation is incomplete",
                        {**payload, "request_nonce": nonce})
            elif command.command_type == "close_session_evidence_archive":
                self._validate_saved_session_request(command)
                closure = self._storage_manager.close_session_evidence_archive(command.session_id)
                confirmation = self._storage_manager.get_persisted_session_preservation_confirmation(command.session_id)
                if (confirmation is None or confirmation["compilation_summary"].get("archive_closed") is not True):
                    raise RuntimeError("Current permanent closure preservation is unconfirmed")
                payload = {"session_id": command.session_id, "closure_outcome": closure,
                           "compilation_summary": confirmation["compilation_summary"]}
            elif command.command_type == "read_session_preservation":
                if set(command.payload) != {"request_nonce"}:
                    raise ValueError("Preservation readback accepts only the requested Session identity")
                confirmation = self._storage_manager.get_persisted_session_preservation_confirmation(command.session_id)
                payload = {"session_id": command.session_id, "archival_confirmed": confirmation is not None,
                           "confirmation": confirmation}
                if confirmation is None:
                    return _participant_result(self._boundary, command, False,
                        "Current persisted Session preservation is unconfirmed", {**payload, "request_nonce": nonce})
            else:
                raise ValueError("Unsupported StorageManager persistence/readback command")
            return _participant_result(self._boundary, command, True, None, {**payload, "request_nonce": nonce})
        except Exception as error:
            return _participant_result(self._boundary, command, False, str(error), {"request_nonce": nonce})


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


async def _complete_maintenance_delivery(boundary, command, result):
    """Join dependent confirmation only for the exact result already published and ACKed."""
    if (command.session_id is not None or command.target_id != boundary.component_id
            or command.command_type not in {"stop", "kill", "cancel", "prepare_stop"}):
        return
    interface = getattr(boundary, "_maintenance_owner", None)
    if (interface is not None and result is not None and result.success
            and command.command_type in {"stop", "kill"}
            and result.payload.get("termination_confirmed") is True):
        boundary._pending_dependent_deliveries[command.command_id] = (command, result)
        await interface.deliver_dependency_release(command, result)
    observer = getattr(boundary, "maintenance_command_handled", None)
    if observer is not None:
        observer(command, result)
    retained = boundary._pending_dependent_deliveries.get(command.command_id)
    if (retained is not None and result is not None and retained[0].to_dict() == command.to_dict()
            and retained[1].to_dict() == result.to_dict()):
        boundary._pending_dependent_deliveries.pop(command.command_id, None)


async def _subscribe_participant_commands(boundary: NatsCommunicationBoundary, receive: Callable) -> tuple[Subscription, Subscription]:
    async def handled(message):
        result = await receive(message)
        command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
        await _complete_maintenance_delivery(boundary, command, result)

    subscriptions = []
    for subject in (f"messages.*.command.{boundary.component_type}.{boundary.component_id}.*",
                    f"messages.command.{boundary.component_type}.{boundary.component_id}.*"):
        options = {"config": ConsumerConfig(deliver_policy=DeliverPolicy.NEW)}
        subscriptions.append(await boundary._require_jetstream().subscribe(subject, cb=handled, manual_ack=True, **options))
    return tuple(subscriptions)


class NatsSynchronizationManagerCommunication:
    """Measure clocks over NATS; SynchronizationManager retains all timing decisions."""

    def __init__(self, boundary: NatsCommunicationBoundary, synchronization_manager: SynchronizationManager) -> None:
        self._boundary = boundary
        self._synchronization_manager = synchronization_manager
        self._results_by_command_id = {}
        self._commands_by_id = {}
        self._command_lock = asyncio.Lock()
        self._runtime_lock = asyncio.Lock()
        self._assessment_task = None
        self._subscriptions = ()

    async def _measure_node(self, session_id, node_id, *, replace_mapping):
        owner = self._synchronization_manager
        config = owner.distributed_configuration
        requester = NatsControllerCommunication(self._boundary)
        node = RuntimeParticipant("acquisition_node", node_id)
        exchanges = []
        for _ in range(config.exchanges):
            sent = owner.current_session_time_s
            result = await requester.request_runtime_command(node, "read_local_time", session_id,
                                                            {}, config.result_window_s)
            received = owner.current_session_time_s
            if (result is None or result.success is not True
                    or result.payload.get("acquisition_node_id") != node_id):
                raise RuntimeError(f"Cross-clock exchange unconfirmed: {node_id}")
            exchanges.append({"sent_session_time_s": sent,
                "received_local_time_s": result.payload["received_local_time_s"],
                "sent_local_time_s": result.payload["sent_local_time_s"],
                "local_clock_resolution_s": result.payload["local_clock_resolution_s"],
                "received_session_time_s": received})
        quality = owner.assess_cross_clock_exchanges(session_id, node_id, exchanges,
                        replace_mapping=replace_mapping, source_id=self._boundary.component_id)
        await self._deliver_quality(session_id, node, quality)
        return quality

    async def _deliver_quality(self, session_id, node, quality):
        result = await NatsControllerCommunication(self._boundary).request_runtime_command(
            node, "accept_synchronization_quality", session_id, {"quality": quality},
            self._synchronization_manager.distributed_configuration.result_window_s)
        if result is None or result.success is not True or result.payload.get("confirmed") is not True:
            raise RuntimeError("Node mapping/quality acceptance is unconfirmed")

    async def _publish_timing(self, session_id):
        for message in self._synchronization_manager.session_timing_evidence(session_id, self._boundary.component_id):
            await self._boundary.publish_evidence(message)

    async def _periodic_assessment(self, session_id, node_ids):
        owner = self._synchronization_manager
        while owner.is_running and owner._prepared_session_id == session_id:
            await asyncio.sleep(owner.distributed_configuration.assessment_interval_s)
            try:
                async with self._runtime_lock:
                    if not owner.is_running or owner._prepared_session_id != session_id:
                        return
                    for node_id in node_ids:
                        try:
                            await self._measure_node(session_id, node_id, replace_mapping=False)
                        except Exception as error:
                            quality = owner.mark_synchronization_unavailable(session_id, node_id,
                                self._boundary.component_id, str(error))
                            try:
                                await self._deliver_quality(session_id, RuntimeParticipant("acquisition_node", node_id), quality)
                            except Exception:
                                logger.warning("Synchronization quality delivery unconfirmed for %s", node_id)
                    await self._publish_timing(session_id)
            except Exception:
                logger.exception("Periodic synchronization cycle failed; evidence retained for the next configured assessment")

    async def close(self) -> None:
        """Release transport subscriptions and assessment tasks without altering Session lifecycle."""
        if self._assessment_task is not None:
            self._assessment_task.cancel()
            try:
                await self._assessment_task
            except asyncio.CancelledError:
                pass
            self._assessment_task = None
        for subscription in self._subscriptions:
            await subscription.unsubscribe()
        self._subscriptions = ()

    async def subscribe_commands(self) -> tuple[Subscription, Subscription]:
        async def execute(message: Any) -> RuntimeCommandResultMessage | None:
            command = RuntimeCommandMessage.from_dict(json.loads(message.data.decode("utf-8")))
            if command.target_id != self._boundary.component_id:
                await message.ack()
                return
            owner = self._synchronization_manager
            identity = command.to_dict()
            identity["payload"] = {k: v for k, v in command.payload.items() if k != "request_nonce"}
            try:
                previous = self._results_by_command_id.get(command.command_id)
                if previous is not None and self._commands_by_id.get(command.command_id) != identity:
                    raise ValueError("Conflicting synchronization command identity")
                if command.command_type == "stop_runtime" and previous is None:
                    if command.session_id != owner._prepared_session_id:
                        raise ValueError("Synchronization command Session mismatch")
                    # The periodic task may own the runtime lock while awaiting NATS.
                    # Serialize commands, but leave that lock free until cancellation finishes.
                    task = self._assessment_task
                    if task is not None:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        self._assessment_task = None
                async with self._runtime_lock:
                    if previous is not None and command.command_type != "read_session_time":
                        result = previous
                    elif command.command_type in {"start_runtime", "assess_synchronization", "resynchronize"}:
                        if owner._prepared_session_id != command.session_id:
                            raise ValueError("Synchronization command Session mismatch")
                        if command.command_type == "start_runtime":
                            owner.start_distributed_session(command.session_id)
                        node_ids = command.payload["node_ids"]
                        if (not isinstance(node_ids, list) or not node_ids or len(set(node_ids)) != len(node_ids)
                                or any(not isinstance(n, str) or not n for n in node_ids)):
                            raise ValueError("Explicit unique AcquisitionNode identities are required")
                        qualities = []
                        for node_id in node_ids:
                            qualities.append(await self._measure_node(command.session_id, node_id,
                                replace_mapping=command.command_type != "assess_synchronization"))
                        await self._publish_timing(command.session_id)
                        result = _participant_result(self._boundary, command, all(q["acceptable"] for q in qualities),
                            None if all(q["acceptable"] for q in qualities) else "Synchronization quality is unacceptable",
                            {"qualities": qualities, "session_time_s": owner.current_session_time_s})
                        if (command.command_type == "start_runtime" and result.success
                                and (self._assessment_task is None or self._assessment_task.done())):
                            self._assessment_task = asyncio.create_task(self._periodic_assessment(command.session_id, tuple(node_ids)))
                    elif command.command_type == "read_session_time":
                        if owner._prepared_session_id != command.session_id or not owner.is_running:
                            raise RuntimeError("Current Session clock is unavailable")
                        result = _participant_result(self._boundary, command, True, None,
                            {"session_time_s": owner.current_session_time_s})
                    elif command.command_type == "stop_runtime":
                        await owner.complete_session_evidence_publication(command.session_id,
                            source_id=self._boundary.component_id, publisher=self._boundary.publish_evidence)
                        result = _participant_result(self._boundary, command, True, None,
                                                     {"session_time_s": owner.current_session_time_s})
                    elif command.command_type == "release_session":
                        if set(command.payload) != {"request_nonce", "ingestor_participant", "result_window_s"}:
                            raise ValueError("Synchronization release requires an explicit receiving owner")
                        from math import isfinite
                        window = command.payload["result_window_s"]
                        if type(window) not in {int, float} or not isfinite(window) or window <= 0:
                            raise ValueError("Synchronization release requires a positive finite result window")
                        participant = RuntimeParticipant.from_dict(command.payload["ingestor_participant"])
                        if participant.component_type != "ingestor":
                            raise ValueError("Synchronization release requires the Ingestor identity")
                        messages = tuple(m for m in (*owner._mapping_publication_evidence.values(),
                            *owner._distributed_evidence) if m.session_id == command.session_id)
                        requests = NatsControllerCommunication(self._boundary)
                        for evidence in messages:
                            acceptance = await requests.request_persistence_command(participant,
                                "read_runtime_evidence_acceptance", command.session_id,
                                {"evidence": evidence.to_dict()}, command.payload["result_window_s"],
                                command_id=json.dumps([command.session_id, evidence.evidence_id]))
                            if (acceptance is None or not acceptance.success
                                    or acceptance.payload.get("durable_acceptance_confirmed") is not True):
                                raise RuntimeError("Synchronization evidence durable acceptance is unconfirmed")
                        released = owner.release_session(command.session_id, accepted_evidence=messages)
                        result = _participant_result(self._boundary, command, released, None,
                            {"session_id": command.session_id, "released": released})
                    elif command.command_type == "initialize_session" and "synchronization_configuration" in command.payload:
                        preparation = owner.prepare_session(command.session_id)
                        owner.configure_distributed_session(command.session_id, command.payload["synchronization_configuration"])
                        report = preparation.to_dict()
                        report.update(component_id=self._boundary.component_id, component_type=self._boundary.component_type)
                        result = _participant_result(self._boundary, command, preparation.ready, preparation.reason,
                                                     {"preparation": report})
                    else:
                        result = (await _execute_maintenance_command(self._boundary, owner, command)
                            if command.command_type in ({"stop", "kill", "cancel", "prepare_stop", "check_stop_readiness"} | SERVICE_RECOVERY_COMMAND_TYPES | DEPENDENT_MAINTENANCE_COMMANDS)
                            else _execute_service_command(self._boundary, owner, command, self._results_by_command_id))
                    self._results_by_command_id[command.command_id] = result
                    self._commands_by_id[command.command_id] = deepcopy(identity)
            except Exception as error:
                result = _participant_result(self._boundary, command, False, f"{type(error).__name__}: {error}", {})
            if "request_nonce" in command.payload:
                result = replace(result, payload={**result.payload, "request_nonce": command.payload["request_nonce"]})
            await self._boundary.publish_command_result(result, command.command_type)
            await message.ack()
            return result

        async def receive(message: Any) -> RuntimeCommandResultMessage | None:
            async with self._command_lock:
                return await execute(message)

        self._subscriptions = await _subscribe_participant_commands(self._boundary, receive)
        return self._subscriptions


async def _execute_maintenance_command(boundary, service, command):
    interface = getattr(service, "_maintenance", None)
    if interface is not None:
        boundary._maintenance_owner = interface
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
        boundary._maintenance_owner = maintenance
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
            return result
        return await _subscribe_participant_commands(self._boundary, receive)
