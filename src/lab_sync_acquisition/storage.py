"""Minimal in-memory storage boundary for retained acquisition envelopes."""

from __future__ import annotations

from typing import Iterable

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.service_readiness import ServiceReadiness


class InMemoryStorageManager:
    """Stores accepted acquisition envelopes in memory for read-back."""

    def __init__(self) -> None:
        self._stored_envelopes: tuple[AcquisitionRecordEnvelope, ...] = ()

    @property
    def stored_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Stored acquisition envelopes for verification."""

        return self._stored_envelopes

    def check_ready(self) -> ServiceReadiness:
        """Return readiness for the in-memory storage service."""

        return ServiceReadiness(
            component_id="storage",
            component_type="storage_manager",
            required=True,
            ready=True,
            reason="ready",
        )

    def store_envelopes(
        self,
        envelopes: Iterable[AcquisitionRecordEnvelope],
    ) -> None:
        """Store accepted acquisition envelopes without transforming them."""

        self._stored_envelopes = self._stored_envelopes + tuple(envelopes)

    def get_envelopes_for_session(
        self,
        session_id: str,
    ) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Return stored envelopes for one session."""

        return tuple(
            envelope
            for envelope in self._stored_envelopes
            if envelope.session_id == session_id
        )

    def get_envelopes_for_source(
        self,
        source_device_id: str,
    ) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Return stored envelopes for one source device."""

        return tuple(
            envelope
            for envelope in self._stored_envelopes
            if envelope.source_device_id == source_device_id
        )
