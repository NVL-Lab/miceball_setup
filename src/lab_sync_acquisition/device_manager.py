"""Device Manager coordination for already-created live adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from lab_sync_acquisition.device_adapter import (
    DeviceAdapter,
    DeviceReadiness,
    DeviceStatus,
    _PartialScientificCollectionError,
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

    def __iter__(self) -> Iterator[DeviceReadiness]:
        return iter(self.results)


@dataclass(frozen=True)
class DeviceRecordCollection:
    """Records collected from one already-created adapter."""

    source_device_id: str
    record_kind: str
    records: tuple[Any, ...]


@dataclass(frozen=True)
class DeviceCollectionResult:
    """Separate lightweight runtime records from local-only scientific data."""

    runtime_records: DeviceRecordCollection
    scientific_records: DeviceRecordCollection | None


class _PartialDeviceCollectionError(RuntimeError):
    """Preserve completed device collections alongside their original failure."""

    def __init__(self, original_error: Exception, partial_results: tuple[DeviceCollectionResult, ...]) -> None:
        super().__init__(f"{type(original_error).__name__}: {original_error}")
        self.original_error = original_error
        self.partial_results = partial_results


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
                    required=adapter.required,
                    ready=False,
                    reason=str(error),
                    capabilities_available=adapter.declared_capabilities,
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

    def collect_records(self) -> tuple[DeviceRecordCollection, ...]:
        """Collect acquisition records exposed by each already-created adapter."""

        collections = []
        for adapter in self._adapters:
            adapter_records = adapter.collect_records()
            collections.append(
                DeviceRecordCollection(
                    source_device_id=adapter.device_id,
                    record_kind=adapter_records["record_kind"],
                    records=tuple(adapter_records["records"]),
                )
            )
        return tuple(collections)

    def collect_scientific_records(
        self, *, scientific_source_device_ids: Iterable[str] | None = None,
    ) -> tuple[DeviceCollectionResult, ...]:
        """Explicitly request local scientific data and its lightweight records.

        Each adapter is collected once. Scientific collections are local data,
        not acquisition envelopes or messages for ingestion.
        """

        selected = set(scientific_source_device_ids) if scientific_source_device_ids is not None else None
        results = []
        for adapter in self._adapters:
            try:
                collected = (
                    adapter.collect_scientific_records()
                    if selected is None or adapter.device_id in selected
                    else {"runtime_records": adapter.collect_records(), "scientific_records": None}
                )
                results.append(self._scientific_collection_result(adapter, collected))
            except _PartialScientificCollectionError as error:
                results.append(self._scientific_collection_result(adapter, error.partial_collection))
                raise _PartialDeviceCollectionError(error.original_error, tuple(results)) from error
            except Exception as error:
                raise _PartialDeviceCollectionError(error, tuple(results)) from error
        return tuple(results)

    def _scientific_collection_result(
        self, adapter: DeviceAdapter, collected: dict[str, Any],
    ) -> DeviceCollectionResult:
        runtime = collected["runtime_records"]
        scientific = collected["scientific_records"]
        return DeviceCollectionResult(
            runtime_records=DeviceRecordCollection(adapter.device_id, runtime["record_kind"], tuple(runtime["records"])),
            scientific_records=(
                DeviceRecordCollection(adapter.device_id, scientific["record_kind"], tuple(scientific["records"]))
                if scientific is not None else None
            ),
        )

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
