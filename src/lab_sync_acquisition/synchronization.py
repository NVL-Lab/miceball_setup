"""Minimal Synchronization Manager for Phase 1 Session Time."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from lab_sync_acquisition.communication import (
    MAPPING_UPDATE_EVIDENCE_TYPE,
    RuntimeEvidenceMessage,
)
from lab_sync_acquisition.service_readiness import ServiceReadiness, apply_dependency_readiness
from lab_sync_acquisition.service_maintenance import service_operation

if TYPE_CHECKING:
    from lab_sync_acquisition.ingestor import InMemoryIngestor


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
            is_persistent=True,
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
        self._service_operation_lock = RLock()
        self._active_service_operations = 0
        self._mapping_lock = RLock()
        self._prepared_session_id: str | None = None
        self._started_at_monotonic_s: float | None = None
        self._stopped_session_time_s: float | None = None
        self._active_mappings: dict[
            tuple[str, str], SynchronizationMapping
        ] = {}
        self._mapping_update_evidence: tuple[MappingUpdateEvidence, ...] = ()
        self._timing_reconciliation_evidence: list[RuntimeEvidenceMessage] = []

    @service_operation(new_work=True)
    def prepare_session(self, session_id: str) -> ServiceReadiness:
        """Prepare one Session's synchronization state without changing timing evidence."""
        with self._mapping_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Synchronization preparation requires session_id")
            if self._prepared_session_id not in {None, session_id}:
                raise RuntimeError("SynchronizationManager already prepared for another Session")
            self._prepared_session_id = session_id
            return self.check_ready()

    @service_operation()
    def abort_session_initialization(self, session_id: str) -> bool:
        """Clear only preparation binding, preserving all established timing evidence."""
        with self._mapping_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Synchronization initialization abort requires session_id")
            if self._prepared_session_id not in {None, session_id}:
                raise RuntimeError("Synchronization initialization abort Session mismatch")
            self._prepared_session_id = None
            return True

    @service_operation()
    def release_session(self, session_id: str, *, ingestor: InMemoryIngestor | None = None) -> bool:
        """Release stopped preparation after mappings retire and evidence is durably handed off."""
        with self._mapping_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Synchronization release requires session_id")
            if self._prepared_session_id != session_id:
                raise RuntimeError("Synchronization release Session mismatch")
            if self.is_running:
                raise RuntimeError("Session Time must stop before Session release")
            if any(key[0] == session_id for key in self._active_mappings):
                raise RuntimeError("Active mappings remain; retirement/preservation confirmation is required")
            evidence = [item for item in self._mapping_update_evidence if item.session_id == session_id]
            if evidence:
                if ingestor is None:
                    raise RuntimeError("Synchronization evidence preservation confirmation is required before release")
                available = [message for message in ingestor.accepted_runtime_evidence
                             if message.session_id == session_id
                             and message.evidence_type == MAPPING_UPDATE_EVIDENCE_TYPE
                             and message.is_persistent]
                for update in evidence:
                    match = next((message for message in available
                                  if message.payload == update.to_dict()
                                  and ingestor.has_durable_runtime_evidence(message)), None)
                    if match is None:
                        raise RuntimeError("Synchronization evidence durable acceptance is unconfirmed")
                    available.remove(match)
            self._mapping_update_evidence = tuple(
                item for item in self._mapping_update_evidence if item.session_id != session_id)
            self._prepared_session_id = None
            self._started_at_monotonic_s = None
            self._stopped_session_time_s = None
            return True

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

    @service_operation(new_work=True)
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

        with self._mapping_lock:
            key = (session_id, acquisition_node_id)
            if key in self._active_mappings:
                raise RuntimeError("An active synchronization mapping already exists")
            mapping = self._new_mapping(
                session_id, acquisition_node_id, local_time_anchor_s, session_time_anchor_s, scale,
            )
            self._active_mappings[key] = mapping
            self._record_mapping_update(
                mapping=mapping, previous=None, update_type="created", reason=reason, details=details,
            )
            return mapping

    @service_operation()
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

        with self._mapping_lock:
            key = (session_id, acquisition_node_id)
            previous = self._active_mappings.get(key)
            if previous is None:
                raise RuntimeError("No active synchronization mapping exists")
            mapping = self._new_mapping(
                session_id, acquisition_node_id, local_time_anchor_s, session_time_anchor_s, scale,
            )
            self._active_mappings[key] = mapping
            self._record_mapping_update(
                mapping=mapping, previous=previous, update_type="replaced", reason=reason, details=details,
            )
            return mapping

    @service_operation()
    def retire_active_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> MappingUpdateEvidence:
        """Retire one active mapping and preserve update evidence."""

        with self._mapping_lock:
            key = (session_id, acquisition_node_id)
            if session_id in self._lost_time_scopes():
                raise RuntimeError("Historical mappings must remain intact while Session Time continuity is unconfirmed")
            previous = self._active_mappings.pop(key, None)
            if previous is None:
                raise RuntimeError("No active synchronization mapping exists")
            return self._record_mapping_update(
                mapping=None, previous=previous, update_type="retired", reason=reason, details=details,
            )

    def _new_mapping(
        self,
        session_id: str,
        acquisition_node_id: str,
        local_time_anchor_s: float,
        session_time_anchor_s: float,
        scale: float,
    ) -> SynchronizationMapping:
        if session_id in self._lost_time_scopes():
            raise RuntimeError("Active Session Time continuity is unconfirmed; no clock restoration is authorized")
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
    @service_operation()
    def current_session_time_s(self) -> float:
        """Current Session Time in seconds since acquisition session start."""

        lost = self._lost_time_scopes()
        if lost and (self._prepared_session_id is None or self._prepared_session_id in lost):
            raise RuntimeError("No trustworthy current Session Time is available for the interrupted scope")
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

        return apply_dependency_readiness(self, ServiceReadiness(
            component_id="synchronization",
            component_type="synchronization_manager",
            required=True,
            ready=not getattr(getattr(self, "_maintenance", None), "terminated", False),
            reason="ready",
        ))

    @service_operation(new_work=True)
    def start(self) -> float:
        """Start the session clock and return the initial Session Time."""

        with self._mapping_lock:
            lost = self._lost_time_scopes()
            if lost and (self._prepared_session_id is None or self._prepared_session_id in lost):
                raise RuntimeError("Cannot restart Session Time at zero for an interrupted ongoing Session")
            self._started_at_monotonic_s = monotonic()
            self._stopped_session_time_s = None
            return 0.0

    @service_operation()
    def stop(self) -> float:
        """Stop the session clock and freeze the final Session Time."""

        with self._mapping_lock:
            self._stopped_session_time_s = self.current_session_time_s
            return self._stopped_session_time_s

    @property
    def timing_reconciliation_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict()))
                     for m in self._timing_reconciliation_evidence)

    def _lost_time_scopes(self) -> set[str]:
        return {m.payload["findings"]["session_id"] for m in self._timing_reconciliation_evidence
                if m.payload["findings"]["active_session"] and m.payload["findings"]["continuity_gap"]
                and m.payload["findings"]["evidence_context_confirmed"]}

    @service_operation()
    async def reconcile_timing(self, session_id: str, *, active_session: bool, ingestor: InMemoryIngestor) -> dict:
        """Report journal-backed history and uncertainty without restoring time or mappings."""
        if not isinstance(session_id, str) or not session_id or type(active_session) is not bool:
            raise ValueError("A real Session identity and explicit active-Session context are required")
        interface = getattr(self, "_maintenance", None)
        source = interface.participant.component_id if interface else "synchronization"
        findings = {"session_id": session_id, "active_session": active_session,
                    "evidence_context_confirmed": ingestor.session_id == session_id,
                    "historical_mapping_updates": [], "warnings": []}
        if ingestor.session_id != session_id:
            findings["warnings"].append("Known-Session evidence intake does not match the requested Session")
        else:
            for message in ingestor.accepted_runtime_evidence:
                if message.session_id != session_id or message.evidence_type != MAPPING_UPDATE_EVIDENCE_TYPE:
                    continue
                if not ingestor.has_durable_runtime_evidence(message):
                    findings["warnings"].append(f"Mapping evidence acceptance unconfirmed: {message.evidence_id}")
                    continue
                try:
                    update = MappingUpdateEvidence.from_dict(message.payload)
                    if update.session_id != session_id:
                        raise ValueError("Mapping evidence Session identity conflicts")
                    findings["historical_mapping_updates"].append({"evidence_id": message.evidence_id,
                                                                  "mapping_update": update.to_dict()})
                except (KeyError, ValueError, TypeError) as error:
                    findings["warnings"].append(f"Mapping evidence cannot be reconciled: {error}")
        with self._mapping_lock:
            current = self._prepared_session_id == session_id and self.is_running
            findings["time_reference_confirmed"] = current
            findings["continuity_gap"] = active_session and not current
            findings["current_active_mappings"] = [m.to_dict() for key, m in self._active_mappings.items()
                                                  if key[0] == session_id]
            findings["active_synchronization_available"] = current if active_session else None
            findings["recovery_performed"] = False
            findings["uncertainty"] = ("Session Time continuity cannot be confirmed; scientific timing may be degraded. "
                                       "No active-Session clock-restoration mechanism is authorized."
                                       if findings["continuity_gap"] else None)
            previous = next((m for m in reversed(self._timing_reconciliation_evidence)
                             if m.payload["findings"]["session_id"] == session_id), None)
            unchanged = previous is not None and previous.payload["findings"] == findings
            message = previous if unchanged else RuntimeEvidenceMessage(
                uuid4().hex, None, "synchronization_reconciliation", source,
                {"findings": deepcopy(findings)}, True)
            if not unchanged:
                self._timing_reconciliation_evidence.append(message)
        storage = interface.storage_manager if interface else None
        confirmation = storage.get_framework_preservation_confirmation() if storage else None
        if unchanged:
            preserved = bool(confirmation and previous.to_dict() in confirmation["runtime_evidence"])
            return {"findings": findings, "evidence": previous.to_dict(), "unchanged": True,
                    "archival_confirmed": preserved, "preservation_warning": None if preserved
                    else "Current timing-reconciliation archival is unconfirmed"}
        if interface is None:
            return {"findings": findings, "evidence": message.to_dict(), "unchanged": False,
                    "archival_confirmed": False, "preservation_warning": "Framework evidence interface is not configured"}
        status = await interface._record_framework_evidence(message,
            archive=storage._framework_evidence_write_safe(), require_existing_archive=True)
        return {"findings": findings, **status, "unchanged": False}

    def maintenance_blockers(self, ingestor, storage_manager) -> list[str]:
        """Report only timing, mapping, and synchronization evidence obligations."""
        blockers = []
        if self.is_running:
            blockers.append("Session Time is running")
        if self._active_mappings:
            blockers.append("Active synchronization mappings")
        latest = {}
        for message in self._timing_reconciliation_evidence:
            latest[message.payload["findings"]["session_id"]] = message.payload["findings"]
        if any(report["active_session"] and report["continuity_gap"] for report in latest.values()):
            blockers.append("Active Session timing continuity is unresolved")
        if self._timing_reconciliation_evidence:
            confirmation = storage_manager.get_framework_preservation_confirmation()
            if (confirmation is None or any(not ingestor.has_durable_runtime_evidence(message)
                    or message.to_dict() not in confirmation["runtime_evidence"]
                    for message in self._timing_reconciliation_evidence)):
                blockers.append("Unpreserved synchronization reconciliation evidence")
        available = ingestor.accepted_runtime_evidence
        for update in self._mapping_update_evidence:
            if not any(message.is_persistent and message.evidence_type == MAPPING_UPDATE_EVIDENCE_TYPE
                       and message.payload == update.to_dict() and ingestor.has_durable_runtime_evidence(message)
                       for message in available):
                blockers.append("Unpreserved mapping evidence")
                break
        return blockers

    def maintenance_diagnostics(self, ingestor, storage_manager) -> dict:
        """Report clock/mapping obligations without retiring or repairing them."""
        with self._mapping_lock:
            session_id = self._prepared_session_id
            running = self.is_running
            stopped = self._stopped_session_time_s is not None
            mappings = [mapping.to_dict() for mapping in self._active_mappings.values()]
            updates = self._mapping_update_evidence
            scopes = {key[0] for key in self._active_mappings}
        interface = getattr(self, "_maintenance", None)
        available = ingestor.accepted_runtime_evidence
        blockers = self.maintenance_blockers(ingestor, storage_manager)
        if blockers:
            scopes.update(update.session_id for update in updates)
            if session_id:
                scopes.add(session_id)
        return {
            "prepared_session_id": session_id,
            "administrative_outcome": (interface._administrative_outcome({"session_id": session_id})
                                        if interface and session_id else None),
            "clock_stop_outcome": "unresolved" if running else "completed" if stopped else None,
            "active_mappings": mappings,
            "mapping_handoffs": [{"session_id": update.session_id,
                "acquisition_node_id": update.acquisition_node_id,
                "update_type": update.update_type,
                "handoff_outcome": "completed" if any(message.is_persistent
                    and message.evidence_type == MAPPING_UPDATE_EVIDENCE_TYPE
                    and message.payload == update.to_dict() and ingestor.has_durable_runtime_evidence(message)
                    for message in available) else "unresolved"}
                for update in updates],
            "restricted_timing_scopes": sorted(scopes) if blockers else [],
            "broader_timing_restriction": bool(blockers and (not scopes or running and session_id is None)),
            "recovery_assessment": "administrator_intervention" if blockers else None,
            "blocking_conditions": blockers,
        }

    async def _close_maintenance_resources(self, force: bool) -> None:
        if self.is_running:
            self.stop()
