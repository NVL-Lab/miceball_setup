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
    required: bool
    ready: bool
    reason: str
    capabilities_available: tuple[str, ...]

    def __init__(
        self,
        device_id: str,
        required: bool,
        ready: bool,
        reason: str,
        capabilities_available: Iterable[str],
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "ready", ready)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(
            self,
            "capabilities_available",
            tuple(capabilities_available),
        )


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
        self._initialization_config = config
        self._set_state(DeviceAdapterState.INITIALIZED)

    def check_ready(self) -> DeviceReadiness:
        """Check whether the initialized adapter is ready to start."""

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
        """Shut down the live adapter after it has stopped."""

        self._require_state(DeviceAdapterState.STOPPED)
        self._set_state(DeviceAdapterState.SHUTDOWN)

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
            shutdown=self._state is DeviceAdapterState.SHUTDOWN,
        )

    def collect_records(self) -> Any:
        """Expose adapter-produced acquisition records for DeviceManager collection."""

        raise NotImplementedError(
            "DeviceAdapter.collect_records requires a concrete acquisition "
            "record implementation"
        )

    def _require_state(self, expected_state: DeviceAdapterState) -> None:
        if self._state is not expected_state:
            actual_state = self._state
            self._set_state(DeviceAdapterState.FAILED)
            raise DeviceAdapterLifecycleError(
                f"DeviceAdapter operation requires state "
                f"'{expected_state.value}', got '{actual_state.value}'"
            )

    def _mark_ready(self) -> DeviceReadiness:
        self._require_state(DeviceAdapterState.INITIALIZED)
        self._set_state(DeviceAdapterState.READY)
        return DeviceReadiness(
            device_id=self.device_id,
            required=self.required,
            ready=True,
            reason="ready",
            capabilities_available=self.declared_capabilities,
        )

    def _set_state(self, state: DeviceAdapterState) -> None:
        self._state = state
