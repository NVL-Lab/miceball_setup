"""Shared readiness records for framework services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceReadiness:
    """Readiness result for a framework service."""

    component_id: str
    component_type: str
    required: bool
    ready: bool
    reason: str
