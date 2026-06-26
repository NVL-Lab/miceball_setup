"""Minimal Synchronization Manager for Phase 1 Session Time."""

from __future__ import annotations

from time import monotonic

from lab_sync_acquisition.service_readiness import ServiceReadiness


class SynchronizationManager:
    """Owns the Phase 1 session clock and reports Session Time in seconds."""

    def __init__(self) -> None:
        self._started_at_monotonic_s: float | None = None
        self._stopped_session_time_s: float | None = None

    @property
    def current_session_time_s(self) -> float:
        """Current Session Time in seconds since acquisition session start."""

        if self._stopped_session_time_s is not None:
            return self._stopped_session_time_s
        if self._started_at_monotonic_s is None:
            return 0.0
        return max(0.0, monotonic() - self._started_at_monotonic_s)

    @property
    def is_running(self) -> bool:
        """Whether the session clock is currently running."""

        return (
            self._started_at_monotonic_s is not None
            and self._stopped_session_time_s is None
        )

    def check_ready(self) -> ServiceReadiness:
        """Return readiness for the synchronization service."""

        return ServiceReadiness(
            component_id="synchronization",
            component_type="synchronization_manager",
            required=True,
            ready=True,
            reason="ready",
        )

    def start(self) -> float:
        """Start the session clock and return the initial Session Time."""

        self._started_at_monotonic_s = monotonic()
        self._stopped_session_time_s = None
        return 0.0

    def stop(self) -> float:
        """Stop the session clock and freeze the final Session Time."""

        self._stopped_session_time_s = self.current_session_time_s
        return self._stopped_session_time_s
