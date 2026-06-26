"""Transferable acquisition record envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class AcquisitionRecordEnvelope:
    """Message-like envelope for acquisition records crossing into ingestion."""

    session_id: str | None
    source_device_id: str | None
    record_kind: str | None
    records: tuple[Any, ...] | None

    def __init__(
        self,
        session_id: str | None,
        source_device_id: str | None,
        record_kind: str | None,
        records: Iterable[Any] | None,
    ) -> None:
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "source_device_id", source_device_id)
        object.__setattr__(self, "record_kind", record_kind)
        object.__setattr__(
            self,
            "records",
            tuple(records) if records is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation of this envelope."""

        return {
            "session_id": self.session_id,
            "source_device_id": self.source_device_id,
            "record_kind": self.record_kind,
            "records": list(self.records) if self.records is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AcquisitionRecordEnvelope":
        """Create an envelope from a JSON-like plain-data representation."""

        return cls(
            session_id=data.get("session_id"),
            source_device_id=data.get("source_device_id"),
            record_kind=data.get("record_kind"),
            records=data.get("records"),
        )
