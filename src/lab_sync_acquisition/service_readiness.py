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
