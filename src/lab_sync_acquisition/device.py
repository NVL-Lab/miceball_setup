"""Device declaration records used by session configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DeviceDeclaration:
    """Persistent configuration declaration for an intended session device."""

    device_id: str | None
    device_type: str | None
    enabled: bool
    required: bool
    declared_capabilities: tuple[str, ...] | None

    def __init__(
        self,
        device_id: str | None,
        device_type: str | None,
        enabled: bool,
        required: bool,
        declared_capabilities: Iterable[str] | None,
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
