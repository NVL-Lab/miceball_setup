"""Device declaration records used by session configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class DeviceDeclaration:
    """Persistent configuration declaration for an intended session device."""

    device_id: str | None
    device_type: str | None
    enabled: bool
    required: bool
    declared_capabilities: tuple[str, ...] | None
    acquisition_health_policy: str | None

    def __init__(
        self,
        device_id: str | None,
        device_type: str | None,
        enabled: bool,
        required: bool,
        declared_capabilities: Iterable[str] | None,
        acquisition_health_policy: str | None = None,
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "device_type", device_type)
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "required", required)
        if declared_capabilities is None:
            capabilities = None
        else:
            capabilities = tuple(declared_capabilities)
        object.__setattr__(self, "declared_capabilities", capabilities)
        object.__setattr__(
            self, "acquisition_health_policy", acquisition_health_policy
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "enabled": self.enabled,
            "required": self.required,
            "declared_capabilities": (
                list(self.declared_capabilities)
                if self.declared_capabilities is not None
                else None
            ),
            "acquisition_health_policy": self.acquisition_health_policy,
        }
