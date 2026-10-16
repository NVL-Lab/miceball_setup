"""Minimal Synchronization Manager for Phase 1 Session Time."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from copy import deepcopy
from math import isfinite
from threading import RLock
from time import get_clock_info, monotonic
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
class SynchronizationConfiguration:
    """Explicit bounds and policy for measured distributed synchronization."""

    exchanges: int
    initial_scale: float
    clock_rate_error_bound: float
    max_uncertainty_s: float
    max_mapping_age_s: float
    assessment_interval_s: float
    result_window_s: float
    quality_interpretation: str

    def __post_init__(self):
        if type(self.exchanges) is not int or self.exchanges < 2:
            raise ValueError("Synchronization requires at least two measured exchanges")
        for name in ("initial_scale", "max_uncertainty_s", "max_mapping_age_s",
                     "assessment_interval_s", "result_window_s"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if (type(self.clock_rate_error_bound) not in (int, float)
                or not isfinite(self.clock_rate_error_bound)
                or not 0 <= self.clock_rate_error_bound < self.initial_scale):
            raise ValueError("clock_rate_error_bound must be finite, nonnegative and below initial_scale")
        if self.quality_interpretation not in {"informational", "warning", "recoverable_failure",
                "experiment_failure", "session_failure", "operator_required", "uninterpreted"}:
            raise ValueError("Unsupported timing-quality interpretation")

    def to_dict(self) -> dict[str, Any]:
        return dict(vars(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynchronizationConfiguration:
        return cls(**data)


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
        self._publication_session_id: str | None = None
        self._mapping_publication_evidence: dict[int, RuntimeEvidenceMessage] = {}
        self._distributed_configuration: SynchronizationConfiguration | None = None
        self._measured_mapping_quality: dict[str, dict[str, Any]] = {}
        self._distributed_evidence: list[RuntimeEvidenceMessage] = []

    @service_operation(new_work=True)
    def configure_distributed_session(self, session_id: str, configuration: dict[str, Any]) -> None:
        """Bind explicit measurement bounds without creating another clock owner."""
        config = SynchronizationConfiguration.from_dict(configuration)
        with self._mapping_lock:
            if self._prepared_session_id != session_id:
                raise RuntimeError("Synchronization configuration Session mismatch")
            if self._distributed_configuration not in (None, config):
                raise ValueError("Conflicting Session synchronization configuration")
            self._distributed_configuration = config

    @property
    def distributed_configuration(self) -> SynchronizationConfiguration | None:
        return self._distributed_configuration

    @service_operation(new_work=True)
    def start_distributed_session(self, session_id: str) -> float:
        """Start the single Session clock once; repeated requests never reset it."""
        with self._mapping_lock:
            if self._prepared_session_id != session_id or self._distributed_configuration is None:
                raise RuntimeError("Configured synchronization Session is required")
            if self._stopped_session_time_s is not None:
                raise RuntimeError("Stopped Session Time cannot restart")
            if not self.is_running:
                self.start()
            return self.current_session_time_s

    @service_operation()
    def assess_cross_clock_exchanges(self, session_id: str, node_id: str,
                                    exchanges: list[dict[str, Any]], *, replace_mapping: bool,
                                    source_id: str) -> dict[str, Any]:
        """Bound clock offset by causal exchanges; never assume symmetric delay."""
        with self._mapping_lock:
            config = self._distributed_configuration
            if (self._prepared_session_id != session_id or config is None or not self.is_running
                    or self._publication_session_id == session_id):
                raise RuntimeError("Current distributed Session Time is unavailable")
            if not isinstance(node_id, str) or not node_id or len(exchanges) != config.exchanges:
                raise ValueError("Complete node-specific cross-clock exchanges are required")
            intervals = []
            previous_end = None
            for sample in exchanges:
                values = [sample[k] for k in ("sent_session_time_s", "received_local_time_s",
                                              "sent_local_time_s", "received_session_time_s")]
                if any(type(v) not in (float, int) or not isfinite(v) for v in values):
                    raise ValueError("Cross-clock samples must be finite numbers")
                s0, n1, n2, s3 = values
                resolution = sample.get("local_clock_resolution_s")
                if type(resolution) not in (int, float) or not isfinite(resolution) or resolution < 0:
                    raise ValueError("Measured local clock resolution is required")
                rounding = 2 * get_clock_info("monotonic").resolution + config.initial_scale * resolution
                if n2 < n1 or s3 < s0 or (previous_end is not None and s0 < previous_end):
                    raise ValueError("Invalid cross-clock ordering")
                previous_end = s3
                mid = (n1 + n2) / 2
                lower = s0 + (config.initial_scale - config.clock_rate_error_bound) * (mid - n1) - rounding
                upper = s3 - (config.initial_scale - config.clock_rate_error_bound) * (n2 - mid) + rounding
                if lower > upper:
                    raise ValueError("Cross-clock exchange contradicts the configured clock-rate bound")
                intervals.append((mid, lower, upper))
            anchor = intervals[-1][0]
            # Intersect causal bounds, widening for the explicit clock-rate assumption.
            lower = max(lo + config.initial_scale * (anchor - n)
                        - config.clock_rate_error_bound * abs(anchor - n) for n, lo, _ in intervals)
            upper = min(hi + config.initial_scale * (anchor - n)
                        + config.clock_rate_error_bound * abs(anchor - n) for n, _, hi in intervals)
            if not isfinite(lower) or not isfinite(upper) or lower > upper:
                raise ValueError("Measured clock exchanges are inconsistent")
            center, uncertainty = (lower + upper) / 2, (upper - lower) / 2
            mapping = self.get_active_mapping(session_id, node_id)
            old = self._measured_mapping_quality.get(node_id)
            if mapping is not None and not replace_mapping:
                if old is None:
                    raise RuntimeError("Active mapping has no verified measurement provenance")
                projected = mapping.session_time_anchor_s + mapping.scale * (anchor - mapping.local_time_anchor_s)
                uncertainty += abs(projected - center)
                age = self.current_session_time_s - mapping.created_session_time_s
                uncertainty = max(uncertainty, old["uncertainty_s"] +
                                  config.clock_rate_error_bound * abs(anchor - old["measured_local_time_s"]))
            else:
                age = 0.0
            acceptable = uncertainty <= config.max_uncertainty_s and age < config.max_mapping_age_s
            if replace_mapping and acceptable:
                method = self.replace_active_mapping if mapping is not None else self.create_and_activate_mapping
                mapping = method(session_id, node_id, anchor, center, config.initial_scale,
                    "measured_cross_clock_exchange", {"exchanges": deepcopy(exchanges),
                    "uncertainty_s": uncertainty, "configuration": config.to_dict()})
            remaining = max(0.0, config.max_mapping_age_s - age) / (config.initial_scale + config.clock_rate_error_bound)
            if config.clock_rate_error_bound:
                remaining = min(remaining, max(0.0, config.max_uncertainty_s - uncertainty)
                                / config.clock_rate_error_bound)
            quality = {"session_id": session_id, "acquisition_node_id": node_id,
                "assessment_sequence": len(self._distributed_evidence) + 1,
                "acceptable": acceptable and mapping is not None,
                "mapping": mapping.to_dict() if mapping else None,
                "measured_local_time_s": anchor, "uncertainty_s": uncertainty,
                "valid_until_local_time_s": anchor + remaining,
                "configuration": config.to_dict(), "exchanges": deepcopy(exchanges)}
            self._measured_mapping_quality[node_id] = deepcopy(quality)
            self._distributed_evidence.append(RuntimeEvidenceMessage(uuid4().hex, session_id,
                "timing_quality_observation", source_id, deepcopy(quality), True))
            return quality

    def session_timing_evidence(self, session_id: str, source_id: str) -> tuple[RuntimeEvidenceMessage, ...]:
        """Return stable timing publication identities without closing the Session clock."""
        with self._mapping_lock:
            messages = []
            for update in self._mapping_update_evidence:
                if update.session_id == session_id:
                    message = self._mapping_publication_evidence.get(id(update))
                    if message is None:
                        message = update.to_runtime_evidence_message(uuid4().hex, source_id)
                        self._mapping_publication_evidence[id(update)] = message
                    if message.source_id != source_id:
                        raise ValueError("Timing evidence publisher identity changed")
                    messages.append(message)
            messages.extend(m for m in self._distributed_evidence if m.session_id == session_id)
            return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(message.to_dict())) for message in messages)

    @service_operation()
    def mark_synchronization_unavailable(self, session_id: str, node_id: str,
                                         source_id: str, reason: str) -> dict[str, Any]:
        """Retain a failed assessment without fabricating a new clock relationship."""
        with self._mapping_lock:
            if self._prepared_session_id != session_id or node_id not in self._measured_mapping_quality:
                raise RuntimeError("No measured mapping is available for this Session/node")
            quality = deepcopy(self._measured_mapping_quality[node_id])
            quality.update(acceptable=False, reason=reason, assessment_sequence=len(self._distributed_evidence) + 1)
            self._measured_mapping_quality[node_id] = quality
            self._distributed_evidence.append(RuntimeEvidenceMessage(uuid4().hex, session_id,
                "timing_quality_observation", source_id, deepcopy(quality), True))
            return deepcopy(quality)

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
    async def complete_session_evidence_publication(
        self, session_id: str, *, source_id: str,
        publisher: Callable[[RuntimeEvidenceMessage], Awaitable[None]],
    ) -> None:
        """Finish a prepared Session's timing work and durably publish its retained evidence."""
        with self._mapping_lock:
            if self._prepared_session_id != session_id:
                raise RuntimeError("Synchronization publication Session mismatch")
            self.stop()
            for identity, node_id in tuple(self._active_mappings):
                if identity == session_id:
                    self.retire_active_mapping(session_id, node_id, "acquisition_closeout")
            messages = []
            for update in self._mapping_update_evidence:
                if update.session_id != session_id:
                    continue
                message = self._mapping_publication_evidence.get(id(update))
                if message is None:
                    message = update.to_runtime_evidence_message(uuid4().hex, source_id)
                    self._mapping_publication_evidence[id(update)] = message
                if message.source_id != source_id:
                    raise RuntimeError("Synchronization publication source changed")
                messages.append(message)
            messages.extend(m for m in self._timing_reconciliation_evidence
                            if m.session_id == session_id)
            messages.extend(m for m in self._distributed_evidence if m.session_id == session_id)
            self._publication_session_id = session_id
        for message in messages:
            await publisher(message)

    @service_operation()
    def abort_session_initialization(self, session_id: str) -> bool:
        """Clear only preparation binding, preserving all established timing evidence."""
        with self._mapping_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Synchronization initialization abort requires session_id")
            if self._prepared_session_id not in {None, session_id}:
                raise RuntimeError("Synchronization initialization abort Session mismatch")
            if self._distributed_configuration is not None and self.is_running:
                raise RuntimeError("Started distributed timing requires preservation before binding release")
            self._prepared_session_id = None
            return True

    @service_operation()
    def release_session(self, session_id: str, *, ingestor: InMemoryIngestor | None = None,
                        accepted_evidence: tuple[RuntimeEvidenceMessage, ...] | None = None) -> bool:
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
            distributed = [message for message in self._distributed_evidence if message.session_id == session_id]
            if evidence or distributed:
                if ingestor is None and accepted_evidence is None:
                    raise RuntimeError("Synchronization evidence preservation confirmation is required before release")
                confirmed = (lambda message: ingestor.has_durable_runtime_evidence(message)) if ingestor is not None else (
                    lambda message: any(candidate.to_dict() == message.to_dict() for candidate in accepted_evidence))
                available = [message for message in (ingestor.accepted_runtime_evidence if ingestor is not None else accepted_evidence)
                             if message.session_id == session_id
                             and message.evidence_type == MAPPING_UPDATE_EVIDENCE_TYPE
                             and message.is_persistent]
                for update in evidence:
                    match = next((message for message in available
                                  if message.payload == update.to_dict()
                                  and confirmed(message)), None)
                    if match is None:
                        raise RuntimeError("Synchronization evidence durable acceptance is unconfirmed")
                    available.remove(match)
                if any(not confirmed(message) for message in distributed):
                    raise RuntimeError("Synchronization quality evidence durable acceptance is unconfirmed")
            self._mapping_update_evidence = tuple(
                item for item in self._mapping_update_evidence if item.session_id != session_id)
            self._mapping_publication_evidence = {
                key: message for key, message in self._mapping_publication_evidence.items()
                if message.session_id != session_id}
            self._publication_session_id = None
            self._distributed_configuration = None
            self._measured_mapping_quality.clear()
            self._distributed_evidence = [m for m in self._distributed_evidence if m.session_id != session_id]
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
            if session_id == self._publication_session_id:
                raise RuntimeError("Session timing publication boundary is closed")
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
            if session_id == self._publication_session_id:
                raise RuntimeError("Session timing publication boundary is closed")
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
            if session_id == self._publication_session_id:
                raise RuntimeError("Session timing publication boundary is closed")
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
            if self._prepared_session_id is not None and self._prepared_session_id == self._publication_session_id:
                raise RuntimeError("Session timing publication boundary is closed")
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
        if any(not ingestor.has_durable_runtime_evidence(message) for message in self._distributed_evidence):
            blockers.append("Unpreserved synchronization quality evidence")
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
