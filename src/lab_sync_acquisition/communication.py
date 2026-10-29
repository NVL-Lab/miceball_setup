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
DEPENDENT_MAINTENANCE_COMMANDS = frozenset({
    "read_operational_instance", "register_operational_dependent", "confirm_dependent_release",
})

LAB_COMMANDS = "messages.*.command.>"
LAB_COMMAND_RESULTS = "messages.*.command_result.>"
LAB_EVIDENCE = "messages.*.evidence.>"


@dataclass(frozen=True)
class RuntimeParticipant:
    """Deployment identity, also reused to declare expected Session participation."""

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
    if not isinstance(value, str) or not value or any(c.isspace() for c in value) or "." in value or value in {"*", ">"}:
        raise ValueError(f"{name} must be one concrete NATS subject token")


def build_runtime_subject(
    session_id: str | None,
    message_class: str,
    component_type: str,
    component_id: str,
    message_type: str,
) -> str:
    """Build one concrete Session-scoped runtime routing subject."""

    if message_class not in MESSAGE_CLASSES:
        raise ValueError(f"Unsupported runtime message class: {message_class}")
    if session_id is None:
        if message_class not in {"command", "command_result", "evidence"}:
            raise ValueError("Only participant commands/results and framework evidence may omit Session identity")
        for name, value in (("component_type", component_type), ("component_id", component_id), ("message_type", message_type)):
            _validate_subject_token(name, value)
        return f"messages.{message_class}.{component_type}.{component_id}.{message_type}"
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


def parse_runtime_subject(subject: str) -> dict[str, str | None]:
    """Parse one concrete runtime subject into routing-only fields."""

    parts = subject.split(".")
    if len(parts) not in {5, 6} or parts[0] != "messages":
        raise ValueError(f"Invalid runtime message subject: {subject}")
    if len(parts) == 5:
        session_id = None
        message_class, component_type, component_id, message_type = parts[1:]
    else:
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


SERVICE_RECOVERY_COMMAND_TYPES = frozenset({
    "recover_archive_write", "recover_session_record_write", "recover_artifact_transfer",
    "preserve_scientific_artifact", "cleanup_device_resources",
})


@dataclass(frozen=True)
class RuntimeCommandMessage:
    """Plain-data command intent routed to one component or component group."""

    command_id: str
    session_id: str | None
    command_type: str
    source_id: str
    target_id: str
    payload: dict[str, Any]
    issuer_type: str | None = None
    controller_instance_id: str | None = None
    controller_claim_revision: int | None = None
    receiver_instance_id: str | None = None

    def __post_init__(self) -> None:
        if self.session_id is None and self.command_type not in ({"register_controller", "read_controller_admission", "check_readiness", "get_inventory", "list_storage_sessions", "stop", "kill", "cancel", "check_stop_readiness", "prepare_stop", "preserve_service_evidence"} | SERVICE_RECOVERY_COMMAND_TYPES | DEPENDENT_MAINTENANCE_COMMANDS):
            raise ValueError("Session-specific command requires session_id")
        if self.session_id is not None:
            _validate_subject_token("session_id", self.session_id)
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the command as JSON-like plain data."""

        data = {
            "command_id": self.command_id,
            "session_id": self.session_id,
            "command_type": self.command_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "payload": dict(self.payload),
        }
        for name in ("issuer_type", "controller_instance_id", "controller_claim_revision", "receiver_instance_id"):
            if getattr(self, name) is not None:
                data[name] = getattr(self, name)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeCommandMessage:
        """Reconstruct a command from plain data."""

        return cls(
            command_id=data["command_id"],
            session_id=data.get("session_id"),
            command_type=data["command_type"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            payload=dict(data["payload"]),
            issuer_type=data.get("issuer_type"),
            controller_instance_id=data.get("controller_instance_id"),
            controller_claim_revision=data.get("controller_claim_revision"),
            receiver_instance_id=data.get("receiver_instance_id"),
        )


@dataclass(frozen=True)
class RuntimeCommandResultMessage:
    """Plain-data result produced after processing one runtime command."""

    result_id: str
    command_id: str
    session_id: str | None
    source_id: str
    target_id: str
    status: str
    success: bool
    reason: str | None
    payload: dict[str, Any]
    controller_instance_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in COMMAND_RESULT_STATUSES:
            raise ValueError(f"Unsupported command result status: {self.status}")
        if self.controller_instance_id is not None and (not isinstance(self.controller_instance_id, str) or not self.controller_instance_id):
            raise ValueError("Controller result identity must be nonempty")
        _validate_plain_data(self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the command result as JSON-like plain data."""

        data = {
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
        if self.controller_instance_id is not None:
            data["controller_instance_id"] = self.controller_instance_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeCommandResultMessage:
        """Reconstruct a command result from plain data."""

        return cls(
            result_id=data["result_id"],
            command_id=data["command_id"],
            session_id=data.get("session_id"),
            source_id=data["source_id"],
            target_id=data["target_id"],
            status=data["status"],
            success=data["success"],
            reason=data["reason"],
            payload=dict(data["payload"]),
            controller_instance_id=data.get("controller_instance_id"),
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
    session_id: str | None
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


@dataclass(frozen=True)
class ExternalSessionLaunchRequest:
    """One logical launch request, addressed before Controller allocates a Session."""

    controller_id: str
    client_id: str
    request_id: str
    selections: dict[str, list[dict[str, Any]]]
    config_parameters: dict[str, Any]
    scientific_outputs: list[dict[str, Any]]

    def __post_init__(self):
        for name in ("controller_id", "client_id", "request_id"):
            _validate_subject_token(name, getattr(self, name))
        if not isinstance(self.selections, dict) or not self.selections:
            raise ValueError("Launch requires explicit node selections")
        if not isinstance(self.config_parameters, dict) or not isinstance(self.scientific_outputs, list):
            raise ValueError("Launch requires configuration and scientific-output list")
        from lab_sync_acquisition.device import DeviceDeclaration
        from lab_sync_acquisition.session import ScientificOutputSelection
        for node, devices in self.selections.items():
            _validate_subject_token("node_id", node)
            if not isinstance(devices, list) or not devices:
                raise ValueError("Node selections require device declarations")
            for device in devices:
                DeviceDeclaration.from_dict(device)
        for output in self.scientific_outputs:
            ScientificOutputSelection.from_dict(output)
        _validate_plain_data(self.to_dict())
        import json
        json.dumps(self.to_dict(), allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        """Return detached JSON-compatible request parameters."""
        from copy import deepcopy
        return deepcopy({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalSessionLaunchRequest:
        """Reject unknown fields and reconstruct a detached request."""
        from copy import deepcopy
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid external Session-launch envelope")
        return cls(**deepcopy(data))


@dataclass(frozen=True)
class ExternalSessionLaunchResult:
    """External request outcome; uncertain is client-side transport uncertainty only."""

    controller_id: str
    client_id: str
    request_id: str
    status: str
    outcome: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self):
        for name in ("controller_id", "client_id", "request_id"):
            _validate_subject_token(name, getattr(self, name))
        if self.status not in {"pending", "succeeded", "failed", "rejected", "uncertain"}:
            raise ValueError("Invalid external launch status")
        if self.outcome is not None and not isinstance(self.outcome, dict):
            raise ValueError("Invalid external launch outcome")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("Invalid external launch error")
        if self.status == "succeeded":
            details = (self.outcome or {}).get("details")
            if (not isinstance(details, dict) or not isinstance(details.get("session_id"), str)
                    or not details["session_id"] or self.outcome.get("succeeded") is not True
                    or self.outcome.get("command") != "launch_session"):
                raise ValueError("Successful launch requires its Controller outcome and Session identity")
        elif self.status in {"pending", "rejected", "uncertain"} and self.outcome is not None:
            raise ValueError("Unconfirmed launch cannot contain a completed outcome")
        elif self.status == "failed" and self.outcome is not None and self.outcome.get("succeeded") is not False:
            raise ValueError("Failed launch cannot contain a successful outcome")
        _validate_plain_data(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return detached external outcome data."""
        from copy import deepcopy
        return deepcopy({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalSessionLaunchResult:
        """Reconstruct one strictly shaped external outcome."""
        from copy import deepcopy
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid external Session-launch result")
        return cls(**deepcopy(data))


# Fixed external operations and their existing Controller result names, not RPC.
EXTERNAL_CONTROLLER_OPERATIONS = {
    "read_session_configuration": "read_session_configuration",
    "start_launched_session": "start_session",
    "start_launched_experiment": "start_experiment",
    "stop_launched_experiment": "stop_experiment",
    "reconcile_launched_experiment_expiry": "reconcile_launched_experiment_expiry",
    "normal_stop_session": "normal_stop_session",
    "collect_saved_session_artifacts_remote": "collect_saved_session_artifacts_remote",
    "release_session": "release_session",
    "read_storage_sessions": "read_storage_sessions",
    "read_storage_session": "read_storage_session",
    "delete_original_artifacts": "delete_original_artifacts",
}


@dataclass(frozen=True)
class ExternalControllerRequest:
    """One explicitly supported operation on an existing or saved Session."""

    controller_id: str
    client_id: str
    request_id: str
    operation: str
    session_id: str | None
    parameters: dict[str, Any]

    def __post_init__(self):
        for name in ("controller_id", "client_id", "request_id"):
            _validate_subject_token(name, getattr(self, name))
        if self.operation == "read_storage_sessions":
            if self.session_id is not None:
                raise ValueError("Storage enumeration has no selected Session")
        else:
            _validate_subject_token("session_id", self.session_id)
        if self.operation not in EXTERNAL_CONTROLLER_OPERATIONS:
            raise ValueError("Unsupported external Controller operation")
        schemas = {
            "read_session_configuration": (set(), set()),
            "start_launched_session": (set(), set()),
            "start_launched_experiment": ({"experiment_id", "configuration", "scientific_outputs"}, {"details", "runtime_health_mapping"}),
            "stop_launched_experiment": ({"experiment_id"}, {"details"}),
            "reconcile_launched_experiment_expiry": ({"experiment_id"}, set()),
            "normal_stop_session": (set(), {"reason"}),
            "collect_saved_session_artifacts_remote": ({"evidence_id", "experimenter_name", "administrator_mode"}, {"deletion"}),
            "release_session": (set(), set()),
            "read_storage_sessions": ({"experimenter_name", "administrator_mode"}, set()),
            "read_storage_session": ({"experimenter_name", "administrator_mode"}, set()),
            "delete_original_artifacts": ({"experimenter_name", "administrator_mode", "operation_id",
                "experiment_ids", "confirmed", "warning_acknowledged"}, {"retry_of", "policy"}),
        }
        required, optional = schemas[self.operation]
        if (not isinstance(self.parameters, dict) or not required <= self.parameters.keys()
                or self.parameters.keys() - required - optional):
            raise ValueError("Invalid parameters for external Controller operation")
        if "administrator_mode" in self.parameters:
            name = self.parameters["experimenter_name"]
            if (type(self.parameters["administrator_mode"]) is not bool
                    or (name is not None and (not isinstance(name, str) or not name.strip()))
                    or (name is None and not self.parameters["administrator_mode"])):
                raise ValueError("Explicit cooperative Storage operator context is required")
        if "deletion" in self.parameters:
            deletion = self.parameters["deletion"]
            fields = {"operation_id", "experiment_ids", "confirmed", "warning_acknowledged"}
            if (not isinstance(deletion, dict) or not fields <= deletion.keys()
                    or deletion.keys() - fields - {"retry_of"}):
                raise ValueError("Optional deletion must contain only an explicit scope and confirmations")
        for name in ("experiment_id", "evidence_id"):
            if name in self.parameters and (not isinstance(self.parameters[name], str) or not self.parameters[name]):
                raise ValueError(f"Explicit {name} is required")
        if self.parameters.get("details") is not None and not isinstance(self.parameters["details"], dict):
            raise ValueError("Operation details must be an object")
        if self.parameters.get("reason") is not None and not isinstance(self.parameters["reason"], str):
            raise ValueError("Operation reason must be a string")
        if self.operation == "start_launched_experiment":
            from lab_sync_acquisition.session import ExperimentConfiguration, ScientificOutputSelection
            from lab_sync_acquisition.experiment_runtime import ExperimentRuntimeHealthMapping
            ExperimentConfiguration.from_dict(self.parameters["configuration"])
            outputs = self.parameters["scientific_outputs"]
            if not isinstance(outputs, list):
                raise ValueError("Scientific outputs must be explicit")
            for output in outputs:
                ScientificOutputSelection.from_dict(output)
            mapping = self.parameters.get("runtime_health_mapping")
            if mapping is not None:
                if not isinstance(mapping, dict) or any(not isinstance(values, list) for values in mapping.values()):
                    raise ValueError("Health mappings must identify nodes and mapping lists")
                for values in mapping.values():
                    for value in values:
                        ExperimentRuntimeHealthMapping.from_dict(value)
        _validate_plain_data(self.to_dict())
        import json
        json.dumps(self.to_dict(), allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize detached parameters without service collaborators."""
        from copy import deepcopy
        return deepcopy({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalControllerRequest:
        """Read only the explicit external-operation envelope."""
        from copy import deepcopy
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid external Controller envelope")
        return cls(**deepcopy(data))


@dataclass(frozen=True)
class ExternalControllerResult:
    """Correlated operation result; success is the existing method's outcome."""

    controller_id: str
    client_id: str
    request_id: str
    operation: str
    session_id: str | None
    status: str
    outcome: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self):
        for name in ("controller_id", "client_id", "request_id"):
            _validate_subject_token(name, getattr(self, name))
        if self.operation == "read_storage_sessions":
            if self.session_id is not None:
                raise ValueError("Storage enumeration result has no selected Session")
        else:
            _validate_subject_token("session_id", self.session_id)
        if self.operation not in EXTERNAL_CONTROLLER_OPERATIONS:
            raise ValueError("Unsupported external Controller result")
        if self.status not in {"pending", "succeeded", "failed", "rejected", "uncertain"}:
            raise ValueError("Invalid external Controller status")
        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("Invalid external Controller error")
        if self.outcome is not None:
            if (not isinstance(self.outcome, dict)
                    or self.outcome.get("command") != EXTERNAL_CONTROLLER_OPERATIONS[self.operation]
                    or type(self.outcome.get("succeeded")) is not bool):
                raise ValueError("Operation outcome does not match the requested operation")
        if self.status == "succeeded" and (self.outcome is None or self.outcome["succeeded"] is not True):
            raise ValueError("Successful operation requires its Controller outcome")
        if self.status == "failed" and self.outcome is not None and self.outcome["succeeded"] is not False:
            raise ValueError("Failed operation cannot confirm success")
        if self.status in {"pending", "rejected", "uncertain"} and self.outcome is not None:
            raise ValueError("Unconfirmed operation cannot contain a completed outcome")
        _validate_plain_data(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return detached operation identity and outcome."""
        from copy import deepcopy
        return deepcopy({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalControllerResult:
        """Reject malformed or mismatched operation outcomes."""
        from copy import deepcopy
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid external Controller result envelope")
        return cls(**deepcopy(data))
