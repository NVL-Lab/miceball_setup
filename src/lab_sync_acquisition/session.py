"""Runtime session lifecycle model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


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
    """Explicit declarations required to initialize a session."""

    selected_devices: list[str] | None
    storage_location: str | None
    protocol_plan: Any | None


@dataclass(frozen=True)
class ReadinessCheck:
    """Recorded result for a lifecycle readiness condition."""

    name: str
    status: str
    reason: str
    sequence: int


@dataclass(frozen=True)
class LifecycleTransition:
    """Recorded lifecycle state transition."""

    from_state: SessionState
    to_state: SessionState
    sequence: int
    reason: str | None = None


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
    _sequence: int = field(default=0, init=False, repr=False)

    _ALLOWED_TRANSITIONS: ClassVar[set[tuple[SessionState, SessionState]]] = {
        (SessionState.CREATED, SessionState.INITIALIZED),
        (SessionState.INITIALIZED, SessionState.RUNNING),
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

    def initialize(self) -> None:
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
        failures = self._record_checks(checks)
        if failures:
            failed_names = ", ".join(failures)
            raise SessionLifecycleError(
                f"Session cannot initialize; missing declarations: {failed_names}"
            )

        self._transition_to(SessionState.INITIALIZED)

    def start(self) -> None:
        """Move from initialized to running and record scoped readiness checks."""

        self._ensure_transition_allowed(SessionState.RUNNING)
        checks = [
            ("devices_required", True, "out_of_scope_for_this_slice"),
            ("ingestor_required", True, "out_of_scope_for_this_slice"),
            ("storage_required", True, "out_of_scope_for_this_slice"),
            ("synchronization_required", True, "out_of_scope_for_this_slice"),
            ("session_start_event_required", True, "out_of_scope_for_this_slice"),
        ]
        self._record_checks(checks)
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
        self._cleanup()
        self.final_status = {
            "state": terminal_state.value,
            "reason": reason,
            "cleanup_occurred": self.cleanup_occurred,
            "sequence": self._next_sequence(),
        }
        self._transition_to(terminal_state, reason=reason)

    def _cleanup(self) -> None:
        if self.current_state != SessionState.STOPPING:
            raise SessionLifecycleError(
                f"Cleanup requires state 'stopping', got '{self.current_state.value}'"
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

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence
