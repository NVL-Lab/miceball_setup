"""Shared readiness records for framework services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceReadiness:
    """Readiness result for a framework service."""

    component_id: str
    component_type: str
    required: bool
    ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "component_id": self.component_id,
            "component_type": self.component_type,
            "required": self.required,
            "ready": self.ready,
            "reason": self.reason,
        }


def dependency_readiness_reports(service: Any) -> tuple[ServiceReadiness, ...]:
    """Read existing service-owned dependency reports without inventing unknown records."""
    interface = getattr(service, "_maintenance", None)
    return () if interface is None else interface.dependency_reports()


def apply_dependency_readiness(service: Any, readiness: ServiceReadiness) -> ServiceReadiness:
    """Combine confirmed required dependencies; absent reports remain unknown."""
    if not readiness.ready:
        return readiness
    for dependency in dependency_readiness_reports(service):
        if dependency.required and not dependency.ready:
            return ServiceReadiness(
                readiness.component_id, readiness.component_type, readiness.required,
                False, f"dependency_unready: {dependency.component_type}/{dependency.component_id}: {dependency.reason}",
            )
    return readiness
