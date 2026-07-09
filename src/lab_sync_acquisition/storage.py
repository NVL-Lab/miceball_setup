"""Storage boundaries for retained acquisition envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

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

    def write_session_record(
        self,
        session_record_path: str | Path,
        *,
        accepted_session_config: Any,
        lifecycle_evidence: Iterable[Any],
        readiness_evidence: Iterable[Any],
        device_readiness_evidence: Iterable[Any],
        service_readiness_evidence: Iterable[Any],
        accepted_acquisition_envelopes: Iterable[AcquisitionRecordEnvelope],
        ingest_audit_records: Iterable[Any],
        final_session_status: dict[str, Any] | None,
        cleanup_evidence: dict[str, Any],
        warnings_or_failures: Iterable[Any] = (),
        experiment_lifecycle_evidence: Iterable[Any] = (),
        experiment_descriptors: Iterable[Any] = (),
        runtime_evidence: Iterable[Any] = (),
        runtime_evidence_audit: Iterable[Any] = (),
    ) -> None:
        """Write a minimal v1 Session Record JSON evidence package."""

        path = Path(session_record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        session_record = _session_record_from_evidence(
            accepted_session_config=accepted_session_config,
            lifecycle_evidence=lifecycle_evidence,
            readiness_evidence=readiness_evidence,
            device_readiness_evidence=device_readiness_evidence,
            service_readiness_evidence=service_readiness_evidence,
            accepted_acquisition_envelopes=accepted_acquisition_envelopes,
            ingest_audit_records=ingest_audit_records,
            final_session_status=final_session_status,
            cleanup_evidence=cleanup_evidence,
            warnings_or_failures=warnings_or_failures,
            experiment_lifecycle_evidence=experiment_lifecycle_evidence,
            experiment_descriptors=experiment_descriptors,
            runtime_evidence=runtime_evidence,
            runtime_evidence_audit=runtime_evidence_audit,
        )
        with path.open("w", encoding="utf-8") as session_record_file:
            json.dump(session_record, session_record_file, indent=2)

    def write_initial_session_record(
        self,
        session_id: str,
        **session_record_evidence: Any,
    ) -> Path:
        """Write the initial Phase 13 Session Record to its accepted path."""

        path = self._session_directory(session_id) / "session_record_initial.json"
        self.write_session_record(path, **session_record_evidence)
        return path

    def write_final_session_record(
        self,
        session_id: str,
        **session_record_evidence: Any,
    ) -> Path:
        """Write the final Phase 13 Session Record to its accepted path."""

        path = self._session_directory(session_id) / "session_record_final.json"
        self.write_session_record(path, **session_record_evidence)
        return path

    def write_evidence_archive(
        self,
        session_id: str,
        compiled_runtime_evidence: dict[str, Iterable[Any]],
    ) -> dict[str, Path]:
        """Write the Phase 13 Evidence Archive from Ingestor compilation."""

        archive_directory = self._session_directory(session_id) / "evidence"
        archive_directory.mkdir(parents=True, exist_ok=True)
        runtime_evidence = tuple(
            compiled_runtime_evidence.get("runtime_evidence", ())
        )
        ingest_audit = tuple(compiled_runtime_evidence.get("ingest_audit", ()))
        runtime_evidence_path = archive_directory / "runtime_evidence.jsonl"
        ingest_audit_path = archive_directory / "ingest_audit.jsonl"
        compilation_summary_path = archive_directory / "compilation_summary.json"

        _write_jsonl(runtime_evidence_path, runtime_evidence)
        _write_jsonl(ingest_audit_path, ingest_audit)
        summary = {
            "session_id": session_id,
            "runtime_evidence_count": len(runtime_evidence),
            "ingest_audit_count": len(ingest_audit),
            "runtime_evidence_ids": [
                _plain_field(evidence, "evidence_id")
                for evidence in runtime_evidence
            ],
            "ingest_audit_evidence_ids": [
                _plain_field(audit, "evidence_id")
                for audit in ingest_audit
            ],
        }
        with compilation_summary_path.open(
            "w", encoding="utf-8"
        ) as summary_file:
            json.dump(summary, summary_file, indent=2)
        return {
            "runtime_evidence": runtime_evidence_path,
            "ingest_audit": ingest_audit_path,
            "compilation_summary": compilation_summary_path,
        }

    def read_session_record(
        self,
        session_record_path: str | Path,
    ) -> dict[str, Any]:
        """Read a minimal v1 Session Record JSON evidence package."""

        path = Path(session_record_path)
        with path.open("r", encoding="utf-8") as session_record_file:
            return json.load(session_record_file)

    def _session_directory(self, session_id: str) -> Path:
        return self._records_path.parent / f"session_{session_id}"


def _to_plain_data(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {
            key: _to_plain_data(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _to_plain_data(item)
            for item in value
        ]
    return value


def _session_record_from_evidence(
    *,
    accepted_session_config: Any,
    lifecycle_evidence: Iterable[Any],
    readiness_evidence: Iterable[Any],
    device_readiness_evidence: Iterable[Any],
    service_readiness_evidence: Iterable[Any],
    accepted_acquisition_envelopes: Iterable[AcquisitionRecordEnvelope],
    ingest_audit_records: Iterable[Any],
    final_session_status: dict[str, Any] | None,
    cleanup_evidence: dict[str, Any],
    warnings_or_failures: Iterable[Any] = (),
    experiment_lifecycle_evidence: Iterable[Any] = (),
    experiment_descriptors: Iterable[Any] = (),
    runtime_evidence: Iterable[Any] = (),
    runtime_evidence_audit: Iterable[Any] = (),
) -> dict[str, Any]:
    return {
        "accepted_session_config": _to_plain_data(accepted_session_config),
        "session_lifecycle_evidence": _to_plain_data(lifecycle_evidence),
        "readiness_evidence": _to_plain_data(readiness_evidence),
        "device_readiness_evidence": _to_plain_data(
            device_readiness_evidence
        ),
        "service_readiness_evidence": _to_plain_data(
            service_readiness_evidence
        ),
        "accepted_acquisition_envelopes": _to_plain_data(
            accepted_acquisition_envelopes
        ),
        "ingest_audit_records": _to_plain_data(ingest_audit_records),
        "runtime_evidence": _to_plain_data(runtime_evidence),
        "runtime_evidence_audit": _to_plain_data(runtime_evidence_audit),
        "final_session_status": _to_plain_data(final_session_status),
        "cleanup_evidence": _to_plain_data(cleanup_evidence),
        "warnings_or_failures": _to_plain_data(warnings_or_failures),
        "experiment_lifecycle_evidence": _to_plain_data(
            experiment_lifecycle_evidence
        ),
        "experiment_descriptors": _to_plain_data(experiment_descriptors),
    }


def _write_jsonl(path: Path, items: Iterable[Any]) -> None:
    with path.open("w", encoding="utf-8") as jsonl_file:
        for item in items:
            jsonl_file.write(json.dumps(_to_plain_data(item)))
            jsonl_file.write("\n")


def _plain_field(value: Any, field_name: str) -> Any:
    plain = _to_plain_data(value)
    if isinstance(plain, dict):
        return plain.get(field_name)
    return None
