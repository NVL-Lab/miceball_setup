"""Device Manager coordination for already-created live adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from lab_sync_acquisition.device_adapter import (
    DeviceAdapter,
    DeviceReadiness,
    DeviceStatus,
)


@dataclass(frozen=True)
class DeviceLifecycleResult:
    """Result from a Device Manager lifecycle call for one adapter."""

    device_id: str
    operation: str
    succeeded: bool
    error: str | None = None


@dataclass(frozen=True)
class DeviceReadinessSummary:
    """Aggregated readiness results from already-created adapters."""

    results: tuple[DeviceReadiness, ...]
    all_ready: bool


class DeviceManager:
    """Coordinates lifecycle calls for already-created Device Adapters."""

    def __init__(self, adapters: Iterable[DeviceAdapter]) -> None:
        self._adapters = tuple(adapters)
        if not self._adapters:
            raise ValueError("DeviceManager requires at least one DeviceAdapter")

    @property
    def adapters(self) -> tuple[DeviceAdapter, ...]:
        """Already-created adapters owned by this manager."""

        return self._adapters

    def initialize_all(self, config: Any) -> tuple[DeviceLifecycleResult, ...]:
        """Initialize each already-created adapter with the provided config."""

        return tuple(
            self._call_lifecycle(adapter, "initialize", config)
            for adapter in self._adapters
        )

    def check_readiness(self) -> DeviceReadinessSummary:
        """Collect readiness from each already-created adapter."""

        results = []
        for adapter in self._adapters:
            try:
                readiness = adapter.check_ready()
            except Exception as error:
                readiness = DeviceReadiness(
                    device_id=adapter.device_id,
                    ready=False,
                    reason=str(error),
                )
            results.append(readiness)
        readiness_results = tuple(results)
        return DeviceReadinessSummary(
            results=readiness_results,
            all_ready=all(result.ready for result in readiness_results),
        )

    def start_all(self) -> tuple[DeviceLifecycleResult, ...]:
        """Start each already-created adapter."""

        return tuple(
            self._call_lifecycle(adapter, "start") for adapter in self._adapters
        )

    def stop_all(self) -> tuple[DeviceLifecycleResult, ...]:
        """Stop each already-created adapter."""

        return tuple(
            self._call_lifecycle(adapter, "stop") for adapter in self._adapters
        )

    def shutdown_all(self) -> tuple[DeviceLifecycleResult, ...]:
        """Shut down each already-created adapter."""

        return tuple(
            self._call_lifecycle(adapter, "shutdown") for adapter in self._adapters
        )

    def collect_statuses(self) -> tuple[DeviceStatus, ...]:
        """Collect status snapshots from each already-created adapter."""

        return tuple(adapter.get_status() for adapter in self._adapters)

    def _call_lifecycle(
        self,
        adapter: DeviceAdapter,
        operation: str,
        *args: Any,
    ) -> DeviceLifecycleResult:
        try:
            getattr(adapter, operation)(*args)
        except Exception as error:
            return DeviceLifecycleResult(
                device_id=adapter.device_id,
                operation=operation,
                succeeded=False,
                error=str(error),
            )
        return DeviceLifecycleResult(
            device_id=adapter.device_id,
            operation=operation,
            succeeded=True,
        )
