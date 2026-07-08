"""Minimal in-memory record receiver for acquisition envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.communication import RuntimeEvidenceMessage
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.storage import (
    InMemoryStorageManager,
    PersistentStorageManager,
)


@dataclass(frozen=True)
class IngestAuditRecord:
    """Audit evidence for one received acquisition envelope."""

    ingest_order: int
    ingest_received_at: float
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "ingest_order": self.ingest_order,
            "ingest_received_at": self.ingest_received_at,
            "accepted": self.accepted,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeEvidenceAuditRecord:
    """Audit evidence for one received durable runtime evidence message."""

    ingest_order: int
    ingest_received_at: float
    evidence_id: str
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return plain runtime evidence intake audit data."""

        return {
            "ingest_order": self.ingest_order,
            "ingest_received_at": self.ingest_received_at,
            "evidence_id": self.evidence_id,
            "accepted": self.accepted,
            "reason": self.reason,
        }


class InMemoryIngestor:
    """Receives acquisition envelopes and forwards accepted ones to storage."""

    def __init__(
        self,
        storage_manager: InMemoryStorageManager
        | PersistentStorageManager
        | None = None,
    ) -> None:
        self._storage_manager = storage_manager
        self._accepted_envelopes: tuple[AcquisitionRecordEnvelope, ...] = ()
        self._ingest_audit: tuple[IngestAuditRecord, ...] = ()
        self._accepted_runtime_evidence: tuple[RuntimeEvidenceMessage, ...] = ()
        self._runtime_evidence_audit: tuple[RuntimeEvidenceAuditRecord, ...] = ()

    @property
    def accepted_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Accepted acquisition envelopes for inspection."""

        return self._accepted_envelopes

    @property
    def ingest_audit(self) -> tuple[IngestAuditRecord, ...]:
        """Audit records for received acquisition envelopes."""

        return self._ingest_audit

    @property
    def accepted_runtime_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Accepted durable runtime evidence in intake order."""

        return self._accepted_runtime_evidence

    @property
    def runtime_evidence_audit(self) -> tuple[RuntimeEvidenceAuditRecord, ...]:
        """Audit records for durable runtime evidence intake."""

        return self._runtime_evidence_audit

    def receive_runtime_evidence(
        self,
        evidence: RuntimeEvidenceMessage,
    ) -> RuntimeEvidenceAuditRecord:
        """Receive and audit one durable runtime evidence message."""

        accepted = bool(
            evidence.evidence_id
            and evidence.session_id
            and evidence.evidence_type
            and evidence.source_id
        )
        audit = RuntimeEvidenceAuditRecord(
            ingest_order=len(self._runtime_evidence_audit) + 1,
            ingest_received_at=time(),
            evidence_id=evidence.evidence_id,
            accepted=accepted,
            reason="accepted" if accepted else "missing_required_identity",
        )
        self._runtime_evidence_audit += (audit,)
        if accepted:
            self._accepted_runtime_evidence += (evidence,)
        return audit

    def check_ready(self) -> ServiceReadiness:
        """Return readiness for the in-memory ingestor service."""

        return ServiceReadiness(
            component_id="ingestor",
            component_type="ingestor",
            required=True,
            ready=True,
            reason="ready",
        )

    def receive_envelope(
        self,
        envelope: AcquisitionRecordEnvelope,
    ) -> IngestAuditRecord:
        """Receive one acquisition envelope and forward it if accepted."""

        accepted, reason = self._validate_envelope(envelope)
        audit = IngestAuditRecord(
            ingest_order=len(self._ingest_audit) + 1,
            ingest_received_at=time(),
            accepted=accepted,
            reason=reason,
        )
        self._ingest_audit = self._ingest_audit + (audit,)

        if accepted:
            self._accepted_envelopes = self._accepted_envelopes + (envelope,)
            if self._storage_manager is not None:
                self._storage_manager.store_envelopes((envelope,))

        return audit

    def _validate_envelope(self, envelope: AcquisitionRecordEnvelope) -> tuple[bool, str]:
        if not envelope.session_id:
            return False, "missing_session_id"
        if not envelope.source_device_id:
            return False, "missing_source_device_id"
        if not envelope.record_kind:
            return False, "missing_record_kind"
        if envelope.records is None:
            return False, "missing_records"
        for row in envelope.records:
            if not self._row_has_session_time(row):
                return False, "missing_session_time"
        return True, "accepted"

    def _row_has_session_time(self, row: Any) -> bool:
        try:
            return "session_time_s" in row or "session_time" in row
        except TypeError:
            return False
