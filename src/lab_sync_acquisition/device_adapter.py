"""Minimum live device adapter lifecycle interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class DeviceAdapterState(str, Enum):
    """Minimum lifecycle states for a live device adapter."""

    DECLARED = "declared"
    INITIALIZED = "initialized"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    SHUTDOWN = "shutdown"
    FAILED = "failed"


@dataclass(frozen=True)
class DeviceReadiness:
    """Readiness result reported by a live device adapter."""

    device_id: str
    ready: bool
    reason: str
    capabilities_available: tuple[str, ...]

    def __init__(
        self,
        device_id: str,
        ready: bool,
        reason: str,
        capabilities_available: Iterable[str],
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "ready", ready)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "capabilities_available",
            tuple(capabilities_available),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "device_id": self.device_id,
            "ready": self.ready,
            "reason": self.reason,
            "capabilities_available": list(self.capabilities_available),
        }


@dataclass(frozen=True)
class DeviceStatus:
    """Status snapshot for a live device adapter."""

    device_id: str
    device_type: str
    declared_capabilities: tuple[str, ...]
    state: DeviceAdapterState
    initialized: bool
    ready: bool
    running: bool
    stopped: bool
    failed: bool
    shutdown: bool


class DeviceAdapterLifecycleError(Exception):
    """Raised when a live device adapter lifecycle operation is invalid."""


class DeviceReadinessNotImplementedError(DeviceAdapterLifecycleError):
    """Raised when a live adapter has no concrete readiness implementation."""


class _PartialScientificCollectionError(RuntimeError):
    """Carry completed native records without disguising collection failure."""

    def __init__(self, original_error: Exception, partial_collection: dict[str, Any]) -> None:
        super().__init__(f"{type(original_error).__name__}: {original_error}")
        self.original_error = original_error
        self.partial_collection = partial_collection


@dataclass
class DeviceAdapter:
    """Minimum live runtime control interface for one device adapter."""

    device_id: str
    device_type: str
    declared_capabilities: tuple[str, ...]
    required: bool
    _state: DeviceAdapterState = field(
        default=DeviceAdapterState.DECLARED, init=False, repr=False
    )
    _initialization_config: Any | None = field(default=None, init=False, repr=False)

    def __init__(
        self,
        device_id: str,
        device_type: str,
        declared_capabilities: Iterable[str],
        required: bool,
    ) -> None:
        self.device_id = device_id
        self.device_type = device_type
        self.declared_capabilities = tuple(declared_capabilities)
        self.required = required
        self._state = DeviceAdapterState.DECLARED
        self._initialization_config = None
        self._shutdown_completed = False

    @property
    def state(self) -> DeviceAdapterState:
        """Current adapter lifecycle state."""

        return self._state

    @property
    def initialization_config(self) -> Any | None:
        """Configuration supplied during initialization."""

        return self._initialization_config

    def initialize(self, config: Any) -> None:
        """Initialize the live adapter with explicit configuration."""

        self._require_state(DeviceAdapterState.DECLARED)
        self._shutdown_completed = False
        self._initialization_config = config
        self._set_state(DeviceAdapterState.INITIALIZED)

    def check_ready(self) -> DeviceReadiness:
        """Report declared eligibility or concrete initialized acquisition readiness."""

        if self.state == DeviceAdapterState.DECLARED:
            return self._mark_ready()
        self._require_state(DeviceAdapterState.INITIALIZED)
        self._set_state(DeviceAdapterState.FAILED)
        raise DeviceReadinessNotImplementedError(
            "DeviceAdapter.check_ready requires a concrete readiness implementation"
        )

    def start(self) -> None:
        """Start the live adapter after it reports ready."""

        self._require_state(DeviceAdapterState.READY)
        self._set_state(DeviceAdapterState.RUNNING)

    def stop(self) -> None:
        """Stop the live adapter after it has started."""

        self._require_state(DeviceAdapterState.RUNNING)
        self._set_state(DeviceAdapterState.STOPPED)

    def shutdown(self) -> None:
        """Complete device cleanup before returning the retained adapter to DECLARED."""

        if self.state == DeviceAdapterState.DECLARED and self._shutdown_completed:
            return
        if self.state not in {
            DeviceAdapterState.INITIALIZED,
            DeviceAdapterState.READY,
            DeviceAdapterState.FAILED,
            DeviceAdapterState.SHUTDOWN,
        }:
            self._require_state(DeviceAdapterState.STOPPED)
        try:
            self._shutdown_resources()
        except Exception:
            self._set_state(DeviceAdapterState.FAILED)
            raise
        self._initialization_config = None
        self._shutdown_completed = True
        self._set_state(DeviceAdapterState.DECLARED)

    def _shutdown_resources(self) -> None:
        """Release adapter-specific resources before the generic cleanup transition."""

    def get_status(self) -> DeviceStatus:
        """Return a status snapshot for the live adapter."""

        return DeviceStatus(
            device_id=self.device_id,
            device_type=self.device_type,
            declared_capabilities=self.declared_capabilities,
            state=self._state,
            initialized=self._state
            in {
                DeviceAdapterState.INITIALIZED,
                DeviceAdapterState.READY,
                DeviceAdapterState.RUNNING,
                DeviceAdapterState.STOPPED,
                DeviceAdapterState.SHUTDOWN,
            },
            ready=self._state
            in {
                DeviceAdapterState.READY,
                DeviceAdapterState.RUNNING,
                DeviceAdapterState.STOPPED,
                DeviceAdapterState.SHUTDOWN,
            },
            running=self._state is DeviceAdapterState.RUNNING,
            stopped=self._state
            in {
                DeviceAdapterState.STOPPED,
                DeviceAdapterState.SHUTDOWN,
            },
            failed=self._state is DeviceAdapterState.FAILED,
            shutdown=(
                self._state is DeviceAdapterState.SHUTDOWN
                or (self._state is DeviceAdapterState.DECLARED and self._shutdown_completed)
            ),
        )

    def collect_records(self) -> Any:
        """Expose adapter-produced acquisition records for DeviceManager collection."""

        raise NotImplementedError(
            "DeviceAdapter.collect_records requires a concrete acquisition "
            "record implementation"
        )

    def collect_scientific_records(self) -> dict[str, Any]:
        """Collect once, keeping local scientific data separate from runtime records.

        Adapters without a scientific collection implementation retain their
        existing lightweight collection behavior and return no scientific data.
        """

        return {
            "runtime_records": self.collect_records(),
            "scientific_records": None,
        }

    def _require_state(self, expected_state: DeviceAdapterState) -> None:
        if self._state is not expected_state:
            actual_state = self._state
            self._set_state(DeviceAdapterState.FAILED)
            raise DeviceAdapterLifecycleError(
                f"DeviceAdapter operation requires state "
                f"'{expected_state.value}', got '{actual_state.value}'"
            )

    def _mark_ready(self) -> DeviceReadiness:
        if self.state == DeviceAdapterState.DECLARED:
            return DeviceReadiness(
                self.device_id, True, "declared_for_initialization", self.declared_capabilities
            )
        if self.state not in {DeviceAdapterState.READY, DeviceAdapterState.RUNNING}:
            self._require_state(DeviceAdapterState.INITIALIZED)
        if self.state != DeviceAdapterState.RUNNING:
            self._set_state(DeviceAdapterState.READY)
        return DeviceReadiness(
            device_id=self.device_id,
            ready=True,
            reason="ready",
            capabilities_available=self.declared_capabilities,
        )

    def _set_state(self, state: DeviceAdapterState) -> None:
        self._state = state
