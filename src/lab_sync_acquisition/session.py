"""Runtime session lifecycle model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Iterable

from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.device_adapter import DeviceReadiness
from lab_sync_acquisition.service_readiness import ServiceReadiness


class SessionState(str, Enum):
    """Accepted Phase 1 session lifecycle states."""

    CREATED = "created"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class SessionConfig:
    """Accepted configuration for one Session run."""

    selected_devices: list[DeviceDeclaration] | None
    storage_location: str | None
    protocol_plan: Any | None
    error_evidence_location: str
    session_id: str | None = None
    session_parameters: dict[str, Any] | None = None
    device_configurations: dict[str, Any] | None = None
    synchronization_configuration: dict[str, Any] | None = None
    acquisition_configuration: dict[str, Any] | None = None
    ingestion_configuration: dict[str, Any] | None = None
    storage_configuration: dict[str, Any] | None = None
    protocol_reference: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "session_id": self.session_id,
            "selected_devices": (
                [
                    device.to_dict()
                    for device in self.selected_devices
                ]
                if self.selected_devices is not None
                else None
            ),
            "storage_location": self.storage_location,
            "protocol_plan": self.protocol_plan,
            "error_evidence_location": self.error_evidence_location,
            "session_parameters": self.session_parameters,
            "device_configurations": self.device_configurations,
            "synchronization_configuration": self.synchronization_configuration,
            "acquisition_configuration": self.acquisition_configuration,
            "ingestion_configuration": self.ingestion_configuration,
            "storage_configuration": self.storage_configuration,
            "protocol_reference": self.protocol_reference,
        }


@dataclass(frozen=True)
class ReadinessCheck:
    """Recorded result for a lifecycle readiness condition."""

    name: str
    status: str
    reason: str
    sequence: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class LifecycleTransition:
    """Recorded lifecycle state transition."""

    from_state: SessionState
    to_state: SessionState
    sequence: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "sequence": self.sequence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExpectedParticipant:
    """Plain-data declaration of expected Experiment contribution."""

    participant_id: str
    participant_type: str
    expected_contribution: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "participant_id": self.participant_id,
            "participant_type": self.participant_type,
            "expected_contribution": self.expected_contribution,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedParticipant:
        """Reconstruct a declaration from its plain-data representation."""

        return cls(
            participant_id=data["participant_id"],
            participant_type=data["participant_type"],
            expected_contribution=data["expected_contribution"],
            required=data["required"],
        )


@dataclass(frozen=True)
class ExperimentDescriptor:
    """Persistent scientific identity for one Experiment in a Session."""

    experiment_id: str
    details: dict[str, Any] | None = None
    expected_participants: tuple[ExpectedParticipant, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "experiment_id": self.experiment_id,
            "details": self.details,
            "expected_participants": [
                participant.to_dict()
                for participant in self.expected_participants
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentDescriptor:
        """Reconstruct a descriptor from its plain-data representation."""

        return cls(
            experiment_id=data["experiment_id"],
            details=dict(data["details"]) if data.get("details") is not None else None,
            expected_participants=tuple(
                ExpectedParticipant.from_dict(participant)
                for participant in data.get("expected_participants", ())
            ),
        )


@dataclass(frozen=True)
class ExperimentLifecycleEvidence:
    """Canonical Session-owned evidence for one Experiment lifecycle event."""

    experiment_id: str
    event_type: str
    session_time_s: float | None
    sequence: int
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "experiment_id": self.experiment_id,
            "event_type": self.event_type,
            "session_time_s": self.session_time_s,
            "sequence": self.sequence,
            "details": self.details,
        }


class SessionLifecycleError(Exception):
    """Raised when a session lifecycle operation is not allowed."""


@dataclass
class Session:
    """Owns lifecycle state and in-memory lifecycle records for one session."""

    session_id: str | None
    configuration: SessionConfig | None
    current_state: SessionState = field(default=SessionState.CREATED, init=False)
    cleanup_occurred: bool = field(default=False, init=False)
    cleanup_sequence: int | None = field(default=None, init=False)
    final_status: dict[str, Any] | None = field(default=None, init=False)
    _transition_history: list[LifecycleTransition] = field(
        default_factory=list, init=False, repr=False
    )
    _readiness_checks: list[ReadinessCheck] = field(
        default_factory=list, init=False, repr=False
    )
    _device_readiness_summary: list[DeviceReadiness] = field(
        default_factory=list, init=False, repr=False
    )
    _service_readiness_checks: list[ServiceReadiness] = field(
        default_factory=list, init=False, repr=False
    )
    _experiment_lifecycle_evidence: list[ExperimentLifecycleEvidence] = field(
        default_factory=list, init=False, repr=False
    )
    _experiment_descriptors: list[ExperimentDescriptor] = field(
        default_factory=list, init=False, repr=False
    )
    _sequence: int = field(default=0, init=False, repr=False)

    _ALLOWED_TRANSITIONS: ClassVar[set[tuple[SessionState, SessionState]]] = {
        (SessionState.CREATED, SessionState.INITIALIZED),
        (SessionState.INITIALIZED, SessionState.RUNNING),
        (SessionState.INITIALIZED, SessionState.FAILED),
        (SessionState.RUNNING, SessionState.STOPPING),
        (SessionState.STOPPING, SessionState.COMPLETED),
        (SessionState.STOPPING, SessionState.FAILED),
        (SessionState.STOPPING, SessionState.ABORTED),
    }
    _TERMINAL_STATES: ClassVar[set[SessionState]] = {
        SessionState.COMPLETED,
        SessionState.FAILED,
        SessionState.ABORTED,
    }

    @property
    def transition_history(self) -> tuple[LifecycleTransition, ...]:
        """Recorded lifecycle transitions in sequence order."""

        return tuple(self._transition_history)

    @property
    def readiness_checks(self) -> tuple[ReadinessCheck, ...]:
        """Recorded readiness checks in sequence order."""

        return tuple(self._readiness_checks)

    @property
    def device_readiness_summary(self) -> tuple[DeviceReadiness, ...]:
        """Recorded device readiness evidence supplied during initialization."""

        return tuple(self._device_readiness_summary)

    @property
    def service_readiness_checks(self) -> tuple[ServiceReadiness, ...]:
        """Recorded service readiness evidence supplied during initialization."""

        return tuple(self._service_readiness_checks)

    @property
    def experiment_lifecycle_evidence(
        self,
    ) -> tuple[ExperimentLifecycleEvidence, ...]:
        """Canonical Experiment lifecycle evidence in Session timeline order."""

        return tuple(self._experiment_lifecycle_evidence)

    @property
    def experiment_descriptors(self) -> tuple[ExperimentDescriptor, ...]:
        """Experiment descriptors in first-start order."""

        return tuple(self._experiment_descriptors)

    def ensure_experiment_descriptor(
        self,
        experiment_id: str,
        details: dict[str, Any] | None = None,
        expected_participants: Iterable[ExpectedParticipant] = (),
    ) -> ExperimentDescriptor:
        """Create one descriptor for an Experiment or return the existing one."""

        for descriptor in self._experiment_descriptors:
            if descriptor.experiment_id == experiment_id:
                return descriptor

        descriptor = ExperimentDescriptor(
            experiment_id=experiment_id,
            details=dict(details) if details is not None else None,
            expected_participants=tuple(expected_participants),
        )
        self._experiment_descriptors.append(descriptor)
        return descriptor

    def record_experiment_lifecycle(
        self,
        experiment_id: str,
        event_type: str,
        session_time_s: float | None,
        details: dict[str, Any] | None = None,
    ) -> ExperimentLifecycleEvidence:
        """Record canonical Experiment lifecycle evidence while Session runs."""

        if self.current_state != SessionState.RUNNING:
            raise SessionLifecycleError(
                "Experiment lifecycle evidence requires Session state 'running'"
            )
        if event_type not in {"experiment_start", "experiment_stop"}:
            raise ValueError(f"Unsupported Experiment lifecycle event: {event_type}")
        evidence = ExperimentLifecycleEvidence(
            experiment_id=experiment_id,
            event_type=event_type,
            session_time_s=session_time_s,
            sequence=self._next_sequence(),
            details=dict(details) if details is not None else None,
        )
        self._experiment_lifecycle_evidence.append(evidence)
        return evidence

    def initialize(
        self,
        device_readiness_summary: Iterable[DeviceReadiness] | None = None,
        service_readiness: Iterable[ServiceReadiness] | None = None,
    ) -> None:
        """Move from created to initialized after declaration checks pass."""

        self._ensure_transition_allowed(SessionState.INITIALIZED)
        checks = [
            (
                "session_id_exists",
                self.session_id is not None and self.session_id != "",
                "session_id_declared",
            ),
            (
                "configuration_exists",
                self.configuration is not None,
                "configuration_declared",
            ),
            (
                "selected_devices_declared",
                self.configuration is not None
                and self.configuration.selected_devices is not None,
                "selected_devices_declared",
            ),
            (
                "storage_location_declared",
                self.configuration is not None
                and self.configuration.storage_location is not None,
                "storage_location_declared",
            ),
            (
                "protocol_plan_declared",
                self.configuration is not None
                and self.configuration.protocol_plan is not None,
                "protocol_plan_declared",
            ),
        ]
        checks.extend(self._selected_device_declaration_checks())
        device_readiness_failures = self._record_device_readiness_summary(
            device_readiness_summary
        )
        service_readiness_failures = self._record_service_readiness(service_readiness)
        failures = self._record_checks(checks)
        failures.extend(device_readiness_failures)
        failures.extend(service_readiness_failures)
        if failures:
            failed_names = ", ".join(failures)
            raise SessionLifecycleError(
                f"Session cannot initialize; readiness failed: {failed_names}"
            )

        self._transition_to(SessionState.INITIALIZED)

    def start(self) -> None:
        """Move from initialized to running."""

        self._ensure_transition_allowed(SessionState.RUNNING)
        self._transition_to(SessionState.RUNNING)

    def stop(self, reason: str | None = None) -> None:
        """Move from running to stopping."""

        self._transition_to(SessionState.STOPPING, reason=reason)

    def complete(self, reason: str | None = None) -> None:
        """Finalize cleanup and mark the session completed."""

        self._finish(SessionState.COMPLETED, reason)

    def fail(self, reason: str | None = None) -> None:
        """Finalize cleanup and mark the session failed."""

        self._finish(SessionState.FAILED, reason)

    def abort(self, reason: str | None = None) -> None:
        """Finalize cleanup and mark the session aborted."""

        self._finish(SessionState.ABORTED, reason)

    def _finish(self, terminal_state: SessionState, reason: str | None) -> None:
        self._cleanup(terminal_state)
        self.final_status = {
            "state": terminal_state.value,
            "reason": reason,
            "cleanup_occurred": self.cleanup_occurred,
            "sequence": self._next_sequence(),
        }
        self._transition_to(terminal_state, reason=reason)

    def _cleanup(self, terminal_state: SessionState) -> None:
        cleanup_allowed = self.current_state == SessionState.STOPPING or (
            self.current_state == SessionState.INITIALIZED
            and terminal_state == SessionState.FAILED
        )
        if not cleanup_allowed:
            raise SessionLifecycleError(
                "Cleanup requires state 'stopping', or 'initialized' for a "
                f"pre-running failure; got '{self.current_state.value}'"
            )
        if not self.cleanup_occurred:
            self.cleanup_occurred = True
            self.cleanup_sequence = self._next_sequence()

    def _transition_to(
        self, new_state: SessionState, reason: str | None = None
    ) -> None:
        self._ensure_transition_allowed(new_state)

        record = LifecycleTransition(
            from_state=self.current_state,
            to_state=new_state,
            sequence=self._next_sequence(),
            reason=reason,
        )
        self._transition_history.append(record)
        self.current_state = new_state

    def _ensure_transition_allowed(self, new_state: SessionState) -> None:
        if self.current_state in self._TERMINAL_STATES:
            raise SessionLifecycleError(
                f"Terminal session state '{self.current_state.value}' cannot transition"
            )

        transition = (self.current_state, new_state)
        if transition not in self._ALLOWED_TRANSITIONS:
            raise SessionLifecycleError(
                f"Transition '{self.current_state.value}' -> '{new_state.value}' "
                "is not allowed"
            )

    def _record_checks(
        self, checks: list[tuple[str, bool, str]]
    ) -> list[str]:
        failures = []
        for name, passed, reason in checks:
            self._readiness_checks.append(
                ReadinessCheck(
                    name=name,
                    status="PASS" if passed else "FAIL",
                    reason=reason if passed else "missing_required_declaration",
                    sequence=self._next_sequence(),
                )
            )
            if not passed:
                failures.append(name)
        return failures

    def _selected_device_declaration_checks(
        self,
    ) -> list[tuple[str, bool, str]]:
        if self.configuration is None or self.configuration.selected_devices is None:
            return []

        checks = []
        for index, device in enumerate(self.configuration.selected_devices):
            prefix = f"selected_devices[{index}]"
            checks.extend(
                [
                    (
                        f"{prefix}.device_id_exists",
                        device.device_id is not None and device.device_id != "",
                        "device_id_declared",
                    ),
                    (
                        f"{prefix}.device_type_exists",
                        device.device_type is not None and device.device_type != "",
                        "device_type_declared",
                    ),
                    (
                        f"{prefix}.enabled_is_boolean",
                        isinstance(device.enabled, bool),
                        "enabled_declared_as_boolean",
                    ),
                    (
                        f"{prefix}.required_is_boolean",
                        isinstance(device.required, bool),
                        "required_declared_as_boolean",
                    ),
                    (
                        f"{prefix}.declared_capabilities_declared",
                        device.declared_capabilities is not None,
                        "declared_capabilities_declared",
                    ),
                ]
            )
        return checks

    def _record_device_readiness_summary(
        self,
        device_readiness_summary: Iterable[DeviceReadiness] | None,
    ) -> list[str]:
        if device_readiness_summary is None:
            return []

        failures = []
        for record in device_readiness_summary:
            self._device_readiness_summary.append(record)
            if record.required and not record.ready:
                failures.append(f"device_readiness[{record.device_id}]")
        return failures

    def _record_service_readiness(
        self,
        service_readiness: Iterable[ServiceReadiness] | None,
    ) -> list[str]:
        if service_readiness is None:
            return []

        failures = []
        for record in service_readiness:
            self._service_readiness_checks.append(record)
            if record.required and not record.ready:
                failures.append(f"service_readiness[{record.component_id}]")
        return failures

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence
