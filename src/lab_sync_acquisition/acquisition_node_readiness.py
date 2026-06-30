"""Readiness evidence for one acquisition-capable system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from lab_sync_acquisition.device_manager import DeviceReadinessSummary
from lab_sync_acquisition.service_readiness import ServiceReadiness


@dataclass(frozen=True)
class AcquisitionNodeReadiness:
    """Aggregates existing readiness evidence with explicit node identity."""

    node_id: str
    session_id: str
    role: str
    device_readiness: DeviceReadinessSummary
    service_readiness: tuple[ServiceReadiness, ...]
    ready: bool

    def __init__(
        self,
        node_id: str,
        session_id: str,
        role: str,
        device_readiness: DeviceReadinessSummary,
        service_readiness: Iterable[ServiceReadiness],
    ) -> None:
        services = tuple(service_readiness)
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "device_readiness", device_readiness)
        object.__setattr__(self, "service_readiness", services)
        object.__setattr__(
            self,
            "ready",
            all(
                not item.required or item.ready
                for item in device_readiness.results
            )
            and all(not item.required or item.ready for item in services),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return plain node readiness evidence for inspection or storage."""

        return {
            "node_id": self.node_id,
            "session_id": self.session_id,
            "role": self.role,
            "device_readiness": [
                item.to_dict() for item in self.device_readiness.results
            ],
            "service_readiness": [item.to_dict() for item in self.service_readiness],
            "ready": self.ready,
        }
