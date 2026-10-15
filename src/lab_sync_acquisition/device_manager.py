"""Device Manager coordination for already-created live adapters."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Iterable, Iterator

from lab_sync_acquisition.device import ScientificProductDeclaration

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
class DeviceCollectionResult:
    """Product-keyed scientific rows and separately identified operational evidence."""

    source_device_id: str
    scientific_products: dict[str, tuple[dict[str, Any], ...]]
    operational_evidence: tuple[Any, ...]


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
                    ready=False,
                    reason=str(error),
                    capabilities_available=adapter.declared_capabilities,
                )
            if not isinstance(readiness, DeviceReadiness) or readiness.device_id != adapter.device_id or type(readiness.ready) is not bool:
                readiness = DeviceReadiness(adapter.device_id, False,
                    "invalid_device_readiness", adapter.declared_capabilities)
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

    def collect_products(
        self, products_by_device: Mapping[str, Iterable[ScientificProductDeclaration]], *,
        session_id: str, experiment_id: str | None,
        acquisition_node_id: str,
    ) -> tuple[DeviceCollectionResult, ...]:
        """Collect selected products once per device, retaining completed partial results."""
        if set(products_by_device) - {adapter.device_id for adapter in self._adapters}:
            raise ValueError("Selected product source has no adapter")
        results = []
        for adapter in self._adapters:
            products = tuple(products_by_device.get(adapter.device_id, ()))
            try:
                collected = adapter.collect_products(products, session_id=session_id,
                    experiment_id=experiment_id, acquisition_node_id=acquisition_node_id)
                results.append(self._product_collection_result(adapter, products, collected))
            except _PartialScientificCollectionError as error:
                try:
                    partial = self._product_collection_result(adapter, products, error.partial_collection)
                except Exception as invalid:
                    combined = ExceptionGroup(
                        f"{error.original_error}; invalid partial product result: {invalid}",
                        [error.original_error, invalid])
                    raise _PartialDeviceCollectionError(combined, tuple(results)) from error
                results.append(partial)
                raise _PartialDeviceCollectionError(error.original_error, tuple(results)) from error
            except Exception as error:
                raise _PartialDeviceCollectionError(error, tuple(results)) from error
        return tuple(results)

    def _product_collection_result(self, adapter, products, collected) -> DeviceCollectionResult:
        if not isinstance(collected, dict) or set(collected) != {"scientific_products", "operational_evidence"}:
            raise ValueError("Adapter must separate product rows from operational evidence")
        rows = collected["scientific_products"]
        selected_ids = {product.data_product_id for product in products}
        if not isinstance(rows, dict) or not set(rows).issubset(selected_ids):
            raise ValueError("Adapter produced an unselected scientific product")
        rows = {identity: tuple(values) for identity, values in rows.items()}
        if any(not isinstance(row, dict) for values in rows.values() for row in values):
            raise ValueError("Scientific observations must be plain row dictionaries")
        return DeviceCollectionResult(adapter.device_id, rows,
            tuple(collected["operational_evidence"]))

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
