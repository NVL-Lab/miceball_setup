"""Minimal in-memory record receiver for acquisition envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.storage import InMemoryStorageManager


@dataclass(frozen=True)
class IngestAuditRecord:
    """Audit evidence for one received acquisition envelope."""

    ingest_order: int
    ingest_received_at: float
    accepted: bool
    reason: str


class InMemoryIngestor:
    """Receives acquisition envelopes and forwards accepted ones to storage."""

    def __init__(self, storage_manager: InMemoryStorageManager | None = None) -> None:
        self._storage_manager = storage_manager
        self._accepted_envelopes: tuple[AcquisitionRecordEnvelope, ...] = ()
        self._ingest_audit: tuple[IngestAuditRecord, ...] = ()

    @property
    def accepted_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Accepted acquisition envelopes for inspection."""

        return self._accepted_envelopes

    @property
    def ingest_audit(self) -> tuple[IngestAuditRecord, ...]:
        """Audit records for received acquisition envelopes."""

        return self._ingest_audit

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
