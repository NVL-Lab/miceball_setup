"""Minimal Synchronization Manager for Phase 1 Session Time."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from lab_sync_acquisition.communication import (
    MAPPING_UPDATE_EVIDENCE_TYPE,
    RuntimeEvidenceMessage,
)
from lab_sync_acquisition.service_readiness import ServiceReadiness


@dataclass(frozen=True)
class SynchronizationMapping:
    """Immutable local-to-Session timing relationship owned by synchronization."""

    session_id: str
    acquisition_node_id: str
    local_time_anchor_s: float
    session_time_anchor_s: float
    scale: float
    created_session_time_s: float

    def to_dict(self) -> dict[str, Any]:
        """Return the mapping as JSON-like plain data."""

        return {
            "session_id": self.session_id,
            "acquisition_node_id": self.acquisition_node_id,
            "local_time_anchor_s": self.local_time_anchor_s,
            "session_time_anchor_s": self.session_time_anchor_s,
            "scale": self.scale,
            "created_session_time_s": self.created_session_time_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynchronizationMapping:
        """Reconstruct an immutable mapping from plain data."""

        return cls(
            session_id=data["session_id"],
            acquisition_node_id=data["acquisition_node_id"],
            local_time_anchor_s=data["local_time_anchor_s"],
            session_time_anchor_s=data["session_time_anchor_s"],
            scale=data["scale"],
            created_session_time_s=data["created_session_time_s"],
        )


@dataclass(frozen=True)
class AcquisitionNodeLocalTimeReport:
    """Plain local-time sample reported to SynchronizationManager."""

    session_id: str
    acquisition_node_id: str
    acquisition_node_local_time_s: float
    reported_reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return the local-time report as JSON-like plain data."""

        return {
            "session_id": self.session_id,
            "acquisition_node_id": self.acquisition_node_id,
            "acquisition_node_local_time_s": self.acquisition_node_local_time_s,
            "reported_reason": self.reported_reason,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcquisitionNodeLocalTimeReport:
        """Reconstruct a local-time report from plain data."""

        return cls(
            session_id=data["session_id"],
            acquisition_node_id=data["acquisition_node_id"],
            acquisition_node_local_time_s=data[
                "acquisition_node_local_time_s"
            ],
            reported_reason=data["reported_reason"],
            details=dict(data["details"]),
        )


@dataclass(frozen=True)
class MappingUpdateEvidence:
    """SynchronizationManager-owned evidence of active mapping lifecycle."""

    session_id: str
    acquisition_node_id: str
    update_type: str
    previous_mapping: SynchronizationMapping | None
    new_mapping: SynchronizationMapping | None
    created_session_time_s: float
    reason: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if self.update_type not in {"created", "replaced", "retired"}:
            raise ValueError(
                f"Unsupported mapping update type: {self.update_type}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return mapping lifecycle evidence as JSON-like plain data."""

        return {
            "session_id": self.session_id,
            "acquisition_node_id": self.acquisition_node_id,
            "update_type": self.update_type,
            "previous_mapping": (
                self.previous_mapping.to_dict()
                if self.previous_mapping is not None
                else None
            ),
            "new_mapping": (
                self.new_mapping.to_dict()
                if self.new_mapping is not None
                else None
            ),
            "created_session_time_s": self.created_session_time_s,
            "reason": self.reason,
            "details": dict(self.details),
        }

    def to_runtime_evidence_message(
        self,
        evidence_id: str,
        source_id: str,
    ) -> RuntimeEvidenceMessage:
        """Wrap this timing evidence in the existing durable runtime message."""

        return RuntimeEvidenceMessage(
            evidence_id=evidence_id,
            session_id=self.session_id,
            evidence_type=MAPPING_UPDATE_EVIDENCE_TYPE,
            source_id=source_id,
            payload=self.to_dict(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MappingUpdateEvidence:
        """Reconstruct mapping lifecycle evidence from plain data."""

        previous = data["previous_mapping"]
        new = data["new_mapping"]
        return cls(
            session_id=data["session_id"],
            acquisition_node_id=data["acquisition_node_id"],
            update_type=data["update_type"],
            previous_mapping=(
                SynchronizationMapping.from_dict(previous)
                if previous is not None
                else None
            ),
            new_mapping=(
                SynchronizationMapping.from_dict(new)
                if new is not None
                else None
            ),
            created_session_time_s=data["created_session_time_s"],
            reason=data["reason"],
            details=dict(data["details"]),
        )


class SynchronizationManager:
    """Owns the Phase 1 session clock and reports Session Time in seconds."""

    def __init__(self) -> None:
        self._started_at_monotonic_s: float | None = None
        self._stopped_session_time_s: float | None = None
        self._active_mappings: dict[
            tuple[str, str], SynchronizationMapping
        ] = {}
        self._mapping_update_evidence: tuple[MappingUpdateEvidence, ...] = ()

    @property
    def mapping_update_evidence(self) -> tuple[MappingUpdateEvidence, ...]:
        """Mapping lifecycle evidence in creation order."""

        return self._mapping_update_evidence

    def get_active_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
    ) -> SynchronizationMapping | None:
        """Return the active immutable mapping for one AcquisitionNode."""

        return self._active_mappings.get((session_id, acquisition_node_id))

    def create_and_activate_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        local_time_anchor_s: float,
        session_time_anchor_s: float,
        scale: float,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> SynchronizationMapping:
        """Create and activate an initial mapping for one AcquisitionNode."""

        key = (session_id, acquisition_node_id)
        if key in self._active_mappings:
            raise RuntimeError("An active synchronization mapping already exists")
        mapping = self._new_mapping(
            session_id,
            acquisition_node_id,
            local_time_anchor_s,
            session_time_anchor_s,
            scale,
        )
        self._active_mappings[key] = mapping
        self._record_mapping_update(
            mapping=mapping,
            previous=None,
            update_type="created",
            reason=reason,
            details=details,
        )
        return mapping

    def replace_active_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        local_time_anchor_s: float,
        session_time_anchor_s: float,
        scale: float,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> SynchronizationMapping:
        """Atomically replace one active mapping and preserve update evidence."""

        key = (session_id, acquisition_node_id)
        previous = self._active_mappings.get(key)
        if previous is None:
            raise RuntimeError("No active synchronization mapping exists")
        mapping = self._new_mapping(
            session_id,
            acquisition_node_id,
            local_time_anchor_s,
            session_time_anchor_s,
            scale,
        )
        self._active_mappings[key] = mapping
        self._record_mapping_update(
            mapping=mapping,
            previous=previous,
            update_type="replaced",
            reason=reason,
            details=details,
        )
        return mapping

    def retire_active_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> MappingUpdateEvidence:
        """Retire one active mapping and preserve update evidence."""

        key = (session_id, acquisition_node_id)
        previous = self._active_mappings.pop(key, None)
        if previous is None:
            raise RuntimeError("No active synchronization mapping exists")
        return self._record_mapping_update(
            mapping=None,
            previous=previous,
            update_type="retired",
            reason=reason,
            details=details,
        )

    def _new_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        local_time_anchor_s: float,
        session_time_anchor_s: float,
        scale: float,
    ) -> SynchronizationMapping:
        return SynchronizationMapping(
            session_id=session_id,
            acquisition_node_id=acquisition_node_id,
            local_time_anchor_s=local_time_anchor_s,
            session_time_anchor_s=session_time_anchor_s,
            scale=scale,
            created_session_time_s=self.current_session_time_s,
        )

    def _record_mapping_update(
        self,
        mapping: SynchronizationMapping | None,
        previous: SynchronizationMapping | None,
        update_type: str,
        reason: str,
        details: dict[str, Any] | None,
    ) -> MappingUpdateEvidence:
        reference = mapping if mapping is not None else previous
        if reference is None:
            raise RuntimeError("Mapping update evidence requires mapping context")
        evidence = MappingUpdateEvidence(
            session_id=reference.session_id,
            acquisition_node_id=reference.acquisition_node_id,
            update_type=update_type,
            previous_mapping=previous,
            new_mapping=mapping,
            created_session_time_s=self.current_session_time_s,
            reason=reason,
            details=dict(details) if details is not None else {},
        )
        self._mapping_update_evidence += (evidence,)
        return evidence

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
