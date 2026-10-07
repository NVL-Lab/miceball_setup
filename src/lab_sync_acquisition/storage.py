"""Storage boundaries for retained acquisition envelopes."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile
from time import time
from typing import Any, Iterable, Mapping
from uuid import uuid4

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.local_storage import ArtifactManifest
from lab_sync_acquisition.communication import RuntimeEvidenceMessage


@dataclass(frozen=True)
class SshRetrievalEndpoint:
    """Deployment-local SSH configuration, never portable Session evidence."""

    host: str
    username: str
    port: int = 22
    key_filename: str | None = None
    known_hosts_path: str | None = None


@dataclass(frozen=True)
class ArtifactRetrievalResult:
    """StorageManager outcome associated with one handoff manifest."""

    artifact_manifest_id: str | None
    outcome: str
    global_destination: str | None = None
    failure_information: str | None = None
    verification_outcome: str | None = None
    verification_information: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"artifact_manifest_id": self.artifact_manifest_id, "outcome": self.outcome}
        if self.outcome == "success":
            result["global_destination"] = self.global_destination
        else:
            result["failure_information"] = self.failure_information
        if self.verification_outcome is not None:
            result["verification_outcome"] = self.verification_outcome
            result["verification_information"] = self.verification_information
        return result


@dataclass(frozen=True)
class ArtifactCollectionResult:
    """Aggregate collection outcome without Session lifecycle interpretation."""

    artifact_results: tuple[ArtifactRetrievalResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(result.outcome == "success" and result.verification_outcome == "verified"
                   for result in self.artifact_results)

    def to_dict(self) -> dict[str, Any]:
        return {"succeeded": self.succeeded,
                "artifact_results": [result.to_dict() for result in self.artifact_results]}


class _VerificationReader:
    """Retain file-access failures separately from HDF5 format rejection."""

    def __init__(self, source: Any) -> None:
        self._source = source
        self.io_failed = False
        self.failure_information: str | None = None

    def _call(self, operation: str, failed_result: Any, *args: Any) -> Any:
        if self.io_failed:
            return failed_result
        try:
            return getattr(self._source, operation)(*args)
        except OSError as error:
            self.io_failed = True
            self.failure_information = f"{type(error).__name__}: {error}"
            # Signal an unsuccessful read to HDF5 without an exception crossing
            # its native callback boundary; Python reports the I/O failure below.
            return failed_result

    def read(self, size: int = -1) -> bytes:
        return self._call("read", b"", size)

    def readinto(self, buffer: Any) -> int:
        return self._call("readinto", 0, buffer)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._call("seek", 0, offset, whence)

    def tell(self) -> int:
        return self._call("tell", 0)

    def flush(self) -> None:
        self._call("flush", None)


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

    def __init__(
        self, records_path: str | Path, *,
        global_artifact_root: str | Path | None = None,
        retrieval_endpoints: Mapping[str, SshRetrievalEndpoint] | None = None,
        evidence_publisher: Callable[[RuntimeEvidenceMessage], Awaitable[None]] | None = None,
        component_id: str = "storage",
    ) -> None:
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("StorageManager component_id must be a nonempty string")
        self._records_path = Path(records_path)
        self._evidence_publisher = evidence_publisher
        self._component_id = component_id
        self._global_artifact_root = (
            Path(global_artifact_root) if global_artifact_root is not None else None
        )
        self._retrieval_endpoints = dict(retrieval_endpoints or {})

    def collect_artifacts(self, handoff: dict[str, Any]) -> ArtifactCollectionResult:
        """Independently pull and lightly verify completed global artifact copies."""
        if self._evidence_publisher is not None:
            raise RuntimeError("Configured evidence publication requires await collect_artifacts_with_evidence()")
        return self._collect_artifacts(handoff)

    async def collect_artifacts_with_evidence(self, handoff: dict[str, Any]) -> ArtifactCollectionResult:
        """Collect a completed pass and await existing durable evidence publication."""
        if self._evidence_publisher is None:
            raise RuntimeError("Artifact collection evidence requires a durable evidence publisher")
        if (not isinstance(handoff, dict) or not isinstance(handoff.get("session_id"), str)
                or not handoff["session_id"] or not isinstance(handoff.get("artifacts"), (list, tuple))):
            raise ValueError("Malformed artifact collection handoff")
        started_at = time()
        evidence_results: list[dict[str, Any]] = []
        result = self._collect_artifacts(handoff, evidence_results)
        message = RuntimeEvidenceMessage(
            evidence_id=uuid4().hex,
            session_id=handoff["session_id"],
            evidence_type="global_artifact_collection_evidence",
            source_id=self._component_id,
            payload={"started_at": started_at, "finished_at": time(),
                     "artifact_results": evidence_results},
            is_persistent=True,
        )
        await self._evidence_publisher(message)
        return result

    def _collect_artifacts(
        self, handoff: dict[str, Any], evidence_results: list[dict[str, Any]] | None = None,
    ) -> ArtifactCollectionResult:
        results = []
        if (not isinstance(handoff, dict) or not isinstance(handoff.get("session_id"), str)
                or not isinstance(handoff.get("artifacts"), (list, tuple))):
            return ArtifactCollectionResult((ArtifactRetrievalResult(
                None, "failure", failure_information="Malformed artifact collection handoff"),))
        for entry in handoff["artifacts"]:
            manifest_id = None
            manifest = None
            data = None
            try:
                data = entry["artifact_manifest"]
                if isinstance(data, dict) and isinstance(data.get("artifact_manifest_id"), str):
                    manifest_id = data["artifact_manifest_id"]
                manifest = ArtifactManifest.from_dict(data)
                if manifest.session_id != handoff["session_id"]:
                    raise ValueError("Artifact Session does not match handoff")
                destination, copied_size = self._retrieve_artifact(manifest)
            except Exception as error:
                item = ArtifactRetrievalResult(
                    manifest_id, "failure", failure_information=f"{type(error).__name__}: {error}")
                results.append(item)
                if evidence_results is not None:
                    evidence_results.append(self._collection_evidence_result(manifest, data, item))
                continue
            # Verification cannot reclassify a completed transfer as retrieval failure.
            try:
                verification, information = self._verify_artifact(manifest, destination)
            except Exception as error:
                verification, information = "verification_failed", f"{type(error).__name__}: {error}"
            item = ArtifactRetrievalResult(
                manifest_id, "success", str(destination),
                verification_outcome=verification, verification_information=information)
            results.append(item)
            if evidence_results is not None:
                evidence_results.append(self._collection_evidence_result(manifest, data, item, copied_size))
        return ArtifactCollectionResult(tuple(results))

    @staticmethod
    def _collection_evidence_result(
        manifest: ArtifactManifest | None, data: Any, result: ArtifactRetrievalResult,
        copied_size: int | None = None,
    ) -> dict[str, Any]:
        identity = manifest.to_dict() if manifest is not None else (data if isinstance(data, dict) else {})
        return {
            "artifact_manifest_id": result.artifact_manifest_id,
            "experiment_id": identity.get("experiment_id"),
            "acquisition_node_id": identity.get("acquisition_node_id"),
            "artifact_type": identity.get("artifact_type"),
            "collection_status": result.outcome,
            "verification_status": result.verification_outcome,
            "global_artifact_locator": result.global_destination,
            "file_size_copied": copied_size if result.outcome == "success" else None,
            "failure_information": result.failure_information or result.verification_information,
        }

    def _verify_artifact(self, manifest: ArtifactManifest, destination: Path) -> tuple[str, str | None]:
        # Only the current framework-managed HDF5 writer declares this contract.
        if manifest.external_artifact_path is not None or manifest.details.get("storage_format") != "hdf5":
            return "copied_unverified", "No applicable light-verification contract"
        import h5py

        with destination.open("rb") as source:
            if os.fstat(source.fileno()).st_size == 0:
                return "structurally_invalid", "Expected HDF5 file has zero byte size"
            reader = _VerificationReader(source)
            try:
                try:
                    artifact = h5py.File(reader, "r")
                except OSError as error:
                    if error.errno is not None:
                        raise
                    return "structurally_invalid", f"Expected HDF5 could not be opened as valid HDF5: {error}"
                with artifact:
                    if "artifact_manifest_id" not in artifact.attrs:
                        return "structurally_invalid", "Missing embedded artifact_manifest_id"
                    identity = artifact.attrs["artifact_manifest_id"]
                    if not isinstance(identity, str) or identity != manifest.artifact_manifest_id:
                        return "structurally_invalid", "Embedded artifact identity mismatch"
                    lengths = []
                    for name in ("frames", "session_time_s", "experiment_time_s",
                                 "acquisition_node_local_time_s", "frame_index",
                                 "timestamp_status", "record_metadata_json"):
                        if name not in artifact:
                            return "structurally_invalid", f"Missing required dataset: {name}"
                        dataset = artifact[name]
                        if not isinstance(dataset, h5py.Dataset) or not dataset.shape:
                            return "structurally_invalid", f"Required record dataset is invalid: {name}"
                        lengths.append(dataset.shape[0])
                    if any(length != lengths[0] for length in lengths):
                        return "structurally_invalid", "Required dataset-length mismatch"
                    count = artifact.attrs.get("persisted_frame_count")
                    if isinstance(count, bool) or not isinstance(count, Integral) or count != lengths[0]:
                        return "structurally_invalid", "Missing or inconsistent embedded persisted_frame_count"
                    if manifest.lifecycle_state == "finalized" and "persisted_frame_count" in manifest.details:
                        expected = manifest.details["persisted_frame_count"]
                        if isinstance(expected, bool) or not isinstance(expected, Integral) or expected != count:
                            return "structurally_invalid", "Finalized manifest persisted-count mismatch"
            finally:
                if reader.io_failed:
                    raise OSError(f"Operational verification file-access failure: {reader.failure_information}")
        return "verified", None

    def _retrieve_artifact(self, manifest: ArtifactManifest) -> tuple[Path, int | None]:
        if self._global_artifact_root is None:
            raise ValueError("global_artifact_root is not configured")
        parts = (manifest.session_id, manifest.experiment_id,
                 manifest.acquisition_node_id, manifest.artifact_manifest_id)
        for part in parts:
            if (not isinstance(part, str) or not part or part in {".", ".."}
                    or any(character in part for character in '/\\\x00:')):
                raise ValueError("Artifact destination identity must be a single path component")
        source = (manifest.external_artifact_path if manifest.external_artifact_path is not None
                  else manifest.local_storage_path)
        if (not isinstance(source, str) or not source or "\x00" in source
                or source.endswith(("/", "\\"))):
            raise ValueError("Invalid artifact source file path")
        source_path = PureWindowsPath(source) if "\\" in source else PurePosixPath(source)
        filename = source_path.name
        if filename in {"", ".", ".."} or ":" in filename:
            raise ValueError("Invalid artifact source filename")
        endpoint = self._retrieval_endpoints.get(manifest.acquisition_node_id)
        if not isinstance(endpoint, SshRetrievalEndpoint):
            raise ValueError("AcquisitionNode retrieval endpoint is not configured")
        destination = self._global_artifact_root.joinpath(*parts, filename)
        if os.path.lexists(destination):
            raise FileExistsError("Deterministic artifact destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(dir=destination.parent, prefix=".incomplete-", delete=False) as output:
                temporary = Path(output.name)
                self._pull_sftp_file(endpoint, source, output)
                try:
                    copied_size = output.tell()
                except (OSError, ValueError):
                    copied_size = None  # Optional evidence metadata must not reclassify the copy.
            # Linking a closed temporary file promotes atomically without ever
            # replacing an existing destination, including a concurrent collision.
            os.link(temporary, destination)
            return destination, copied_size
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Cleanup must not replace the primary retrieval outcome.

    def _pull_sftp_file(self, endpoint: SshRetrievalEndpoint, source: str, output: Any) -> None:
        import paramiko

        with paramiko.SSHClient() as client:
            client.load_system_host_keys()
            if endpoint.known_hosts_path is not None:
                client.load_host_keys(endpoint.known_hosts_path)
            client.connect(hostname=endpoint.host, username=endpoint.username,
                           port=endpoint.port, key_filename=endpoint.key_filename)
            with client.open_sftp() as sftp:
                # Open directly: convenience download methods may stat first.
                with sftp.open(source, "rb") as remote:
                    shutil.copyfileobj(remote, output, length=1024 * 1024)

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
