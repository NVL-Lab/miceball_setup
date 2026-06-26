"""Storage boundaries for retained acquisition envelopes."""

from __future__ import annotations

import json
from pathlib import Path
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


class PersistentStorageManager:
    """Stores accepted acquisition envelopes as JSONL for v1 persistence."""

    def __init__(self, records_path: str | Path) -> None:
        self._records_path = Path(records_path)

    @property
    def records_path(self) -> Path:
        """JSONL file path used for accepted acquisition records."""

        return self._records_path

    @property
    def stored_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Read stored acquisition envelopes from JSONL."""

        return self.read_envelopes()

    def check_ready(self) -> ServiceReadiness:
        """Return readiness for the persistent storage service."""

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
        """Append accepted acquisition envelopes to the JSONL records file."""

        self._records_path.parent.mkdir(parents=True, exist_ok=True)
        with self._records_path.open("a", encoding="utf-8") as records_file:
            for envelope in envelopes:
                records_file.write(json.dumps(envelope.to_dict()))
                records_file.write("\n")

    def read_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Read all stored acquisition envelopes from JSONL."""

        if not self._records_path.exists():
            return ()

        envelopes = []
        with self._records_path.open("r", encoding="utf-8") as records_file:
            for line in records_file:
                if line.strip():
                    envelopes.append(
                        AcquisitionRecordEnvelope.from_dict(json.loads(line))
                    )
        return tuple(envelopes)

    def get_envelopes_for_session(
        self,
        session_id: str,
    ) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Return stored envelopes for one session."""

        return tuple(
            envelope
            for envelope in self.read_envelopes()
            if envelope.session_id == session_id
        )

    def get_envelopes_for_source(
        self,
        source_device_id: str,
    ) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Return stored envelopes for one source device."""

        return tuple(
            envelope
            for envelope in self.read_envelopes()
            if envelope.source_device_id == source_device_id
        )
