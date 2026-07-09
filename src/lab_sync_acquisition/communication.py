"""Plain-data runtime communication messages and routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any


MESSAGE_CLASSES = frozenset(
    {"command", "command_result", "evidence", "telemetry"}
)
COMMAND_RESULT_STATUSES = frozenset(
    {"accepted", "progress", "succeeded", "failed"}
)
RUNTIME_CONTROL_COMMAND_RESULT_STATUSES = frozenset({"succeeded", "failed"})
ARTIFACT_MANIFEST_EVIDENCE_TYPE = "artifact_manifest"
MAPPING_UPDATE_EVIDENCE_TYPE = "mapping_update_evidence"

LAB_COMMANDS = "messages.*.command.>"
LAB_COMMAND_RESULTS = "messages.*.command_result.>"
LAB_EVIDENCE = "messages.*.evidence.>"


@dataclass(frozen=True)
class RuntimeParticipant:
    """Plain Session configuration identity for one expected runtime component."""

    component_type: str
    component_id: str

    def to_dict(self) -> dict[str, str]:
        """Return the expected participant as plain configuration data."""

        return {
            "component_type": self.component_type,
            "component_id": self.component_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> RuntimeParticipant:
        """Reconstruct an expected participant from plain data."""

        return cls(
            component_type=data["component_type"],
            component_id=data["component_id"],
        )


@dataclass(frozen=True)
class UnresolvedCommandOutcome:
    """Issuer evidence that one expected target produced no command result."""

    command_id: str
    session_id: str
    command_type: str
    expected_target_type: str
    expected_target_id: str
    outcome: str
    reason: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if self.outcome != "unresolved":
            raise ValueError("Unresolved command outcome must be 'unresolved'")
        _validate_plain_data(self.details, "details")

    def to_dict(self) -> dict[str, Any]:
        """Return unresolved outcome evidence as JSON-like plain data."""

        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command_type": self.command_type,
            "expected_target_type": self.expected_target_type,
            "expected_target_id": self.expected_target_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnresolvedCommandOutcome:
        """Reconstruct unresolved outcome evidence from plain data."""

        return cls(
            command_id=data["command_id"],
            session_id=data["session_id"],
            command_type=data["command_type"],
            expected_target_type=data["expected_target_type"],
            expected_target_id=data["expected_target_id"],
            outcome=data["outcome"],
            reason=data["reason"],
            details=dict(data["details"]),
        )


@dataclass(frozen=True)
class GroupCommandOutcome:
    """Issuer-owned aggregate of results expected from one component group."""

    command_id: str
    session_id: str
    command_type: str
    component_type: str
    outcome: str
    command_results: tuple[RuntimeCommandResultMessage, ...]
    unresolved_outcomes: tuple[UnresolvedCommandOutcome, ...]

    def __post_init__(self) -> None:
        if self.outcome not in {"succeeded", "failed", "unresolved"}:
            raise ValueError(f"Unsupported group command outcome: {self.outcome}")

    def to_dict(self) -> dict[str, Any]:
        """Return the issuer aggregate as JSON-like plain data."""

        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command_type": self.command_type,
            "component_type": self.component_type,
            "outcome": self.outcome,
            "command_results": [item.to_dict() for item in self.command_results],
            "unresolved_outcomes": [
                item.to_dict() for item in self.unresolved_outcomes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupCommandOutcome:
        """Reconstruct an issuer aggregate from plain data."""

        return cls(
            command_id=data["command_id"],
            session_id=data["session_id"],
            command_type=data["command_type"],
            component_type=data["component_type"],
            outcome=data["outcome"],
            command_results=tuple(
                RuntimeCommandResultMessage.from_dict(item)
                for item in data["command_results"]
            ),
            unresolved_outcomes=tuple(
                UnresolvedCommandOutcome.from_dict(item)
                for item in data["unresolved_outcomes"]
            ),
        )


def _validate_plain_data(value: Any, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_plain_data(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} dictionary keys must be strings")
            _validate_plain_data(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain only JSON-like plain data")


def _validate_subject_token(name: str, value: str) -> None:
    if not value or "." in value or value in {"*", ">"}:
        raise ValueError(f"{name} must be one concrete NATS subject token")


def build_runtime_subject(
    session_id: str,
    message_class: str,
    component_type: str,
    component_id: str,
    message_type: str,
) -> str:
    """Build one concrete Session-scoped runtime routing subject."""

    if message_class not in MESSAGE_CLASSES:
        raise ValueError(f"Unsupported runtime message class: {message_class}")
    for name, value in (
        ("session_id", session_id),
        ("component_type", component_type),
        ("component_id", component_id),
        ("message_type", message_type),
    ):
        _validate_subject_token(name, value)
    return (
        f"messages.{session_id}.{message_class}."
        f"{component_type}.{component_id}.{message_type}"
    )


def parse_runtime_subject(subject: str) -> dict[str, str]:
    """Parse one concrete runtime subject into routing-only fields."""

    parts = subject.split(".")
    if len(parts) != 6 or parts[0] != "messages":
        raise ValueError(f"Invalid runtime message subject: {subject}")
    session_id, message_class, component_type, component_id, message_type = parts[1:]
    build_runtime_subject(
        session_id,
        message_class,
        component_type,
        component_id,
        message_type,
    )
    return {
        "session_id": session_id,
        "message_class": message_class,
        "component_type": component_type,
        "component_id": component_id,
        "message_type": message_type,
    }


@dataclass(frozen=True)
class RuntimeCommandMessage:
    """Plain-data command intent routed to one component or component group."""

    command_id: str
    session_id: str
    command_type: str
    source_id: str
    target_id: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the command as JSON-like plain data."""

        return {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command_type": self.command_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeCommandMessage:
        """Reconstruct a command from plain data."""

        return cls(
            command_id=data["command_id"],
            session_id=data["session_id"],
            command_type=data["command_type"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            payload=dict(data["payload"]),
        )


@dataclass(frozen=True)
class RuntimeCommandResultMessage:
    """Plain-data result produced after processing one runtime command."""

    result_id: str
    command_id: str
    session_id: str
    source_id: str
    target_id: str
    status: str
    success: bool
    reason: str | None
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in COMMAND_RESULT_STATUSES:
            raise ValueError(f"Unsupported command result status: {self.status}")
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the command result as JSON-like plain data."""

        return {
            "result_id": self.result_id,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "status": self.status,
            "success": self.success,
            "reason": self.reason,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeCommandResultMessage:
        """Reconstruct a command result from plain data."""

        return cls(
            result_id=data["result_id"],
            command_id=data["command_id"],
            session_id=data["session_id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            status=data["status"],
            success=data["success"],
            reason=data["reason"],
            payload=dict(data["payload"]),
        )


def build_group_command_messages(
    command_id: str,
    session_id: str,
    command_type: str,
    source_id: str,
    component_type: str,
    expected_participants: Iterable[RuntimeParticipant],
    payload: dict[str, Any],
) -> tuple[RuntimeCommandMessage, ...]:
    """Fan one issuer command intent out to its configured component group."""

    return tuple(
        RuntimeCommandMessage(
            command_id=command_id,
            session_id=session_id,
            command_type=command_type,
            source_id=source_id,
            target_id=participant.component_id,
            payload=dict(payload),
        )
        for participant in expected_participants
        if participant.component_type == component_type
    )


def aggregate_group_command_results(
    command_id: str,
    session_id: str,
    command_type: str,
    component_type: str,
    expected_participants: Iterable[RuntimeParticipant],
    command_results: Iterable[RuntimeCommandResultMessage],
    unresolved_reason: str = "Expected command result was not received",
) -> GroupCommandOutcome:
    """Aggregate one component group's results at the command issuer boundary."""

    expected = tuple(
        participant
        for participant in expected_participants
        if participant.component_type == component_type
    )
    matching_results = tuple(
        result
        for result in command_results
        if result.command_id == command_id and result.session_id == session_id
    )
    responding_ids = {result.source_id for result in matching_results}
    unresolved = tuple(
        UnresolvedCommandOutcome(
            command_id=command_id,
            session_id=session_id,
            command_type=command_type,
            expected_target_type=component_type,
            expected_target_id=participant.component_id,
            outcome="unresolved",
            reason=unresolved_reason,
            details={},
        )
        for participant in expected
        if participant.component_id not in responding_ids
    )
    if unresolved:
        outcome = "unresolved"
    elif any(not result.success for result in matching_results):
        outcome = "failed"
    else:
        outcome = "succeeded"
    return GroupCommandOutcome(
        command_id=command_id,
        session_id=session_id,
        command_type=command_type,
        component_type=component_type,
        outcome=outcome,
        command_results=matching_results,
        unresolved_outcomes=unresolved,
    )


@dataclass(frozen=True)
class RuntimeEvidenceMessage:
    """Plain-data wrapper for one durable framework evidence record."""

    evidence_id: str
    session_id: str
    evidence_type: str
    source_id: str
    payload: dict[str, Any]
    is_persistent: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.is_persistent, bool):
            raise ValueError("RuntimeEvidenceMessage is_persistent must be boolean")
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the evidence message as JSON-like plain data."""

        return {
            "evidence_id": self.evidence_id,
            "session_id": self.session_id,
            "evidence_type": self.evidence_type,
            "source_id": self.source_id,
            "payload": dict(self.payload),
            "is_persistent": self.is_persistent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeEvidenceMessage:
        """Reconstruct an evidence message from plain data."""

        return cls(
            evidence_id=data["evidence_id"],
            session_id=data["session_id"],
            evidence_type=data["evidence_type"],
            source_id=data["source_id"],
            payload=dict(data["payload"]),
            is_persistent=data.get("is_persistent", False),
        )


@dataclass(frozen=True)
class RuntimeTelemetryMessage:
    """Plain-data transient telemetry for display and monitoring."""

    session_id: str
    telemetry_type: str
    source_id: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the telemetry message as JSON-like plain data."""

        return {
            "session_id": self.session_id,
            "telemetry_type": self.telemetry_type,
            "source_id": self.source_id,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeTelemetryMessage:
        """Reconstruct telemetry from plain data."""

        return cls(
            session_id=data["session_id"],
            telemetry_type=data["telemetry_type"],
            source_id=data["source_id"],
            payload=dict(data["payload"]),
        )
