"""Storage boundaries for retained acquisition envelopes."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile
from threading import RLock
from time import time
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.service_readiness import ServiceReadiness, apply_dependency_readiness
from lab_sync_acquisition.local_storage import ArtifactManifest
from lab_sync_acquisition.communication import RuntimeEvidenceMessage
from lab_sync_acquisition.service_maintenance import service_operation


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
        self._service_operation_lock = RLock()
        self._active_service_operations = 0
        self._preservation_lock = RLock()
        self._archive_confirmation: dict[str, Any] | None = None
        self._framework_archive_confirmation: dict[str, Any] | None = None
        self._framework_closeout_compilation: dict[str, Any] | None = None
        self._unfinished_archive_scopes: set[str | None] = set()
        self._unfinished_record_paths: set[Path] = set()
        self._final_record_confirmation: tuple[str, Path, str] | None = None
        self._evidence_publisher = evidence_publisher
        self._collection_evidence: list[RuntimeEvidenceMessage] = []
        self._component_id = component_id
        self._unfinished_record_contents: dict[Path, str] = {}
        self._last_written_record: tuple[Path, str] | None = None
        self._global_artifact_root = (
            Path(global_artifact_root) if global_artifact_root is not None else None
        )
        self._retrieval_endpoints = dict(retrieval_endpoints or {})

    @service_operation(new_work=True)
    def collect_artifacts(self, handoff: dict[str, Any]) -> ArtifactCollectionResult:
        """Independently pull and lightly verify completed global artifact copies."""
        if self._evidence_publisher is not None:
            raise RuntimeError("Configured evidence publication requires await collect_artifacts_with_evidence()")
        return self._collect_artifacts(handoff)

    @service_operation(new_work=True)
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
        message = self._record_collection_evidence(handoff["session_id"], started_at, evidence_results)
        await self._evidence_publisher(message)
        return result

    def _record_collection_evidence(self, session_id: str, started_at: float, evidence_results: list[dict]) -> RuntimeEvidenceMessage:
        message = RuntimeEvidenceMessage(
            evidence_id=uuid4().hex,
            session_id=session_id,
            evidence_type="global_artifact_collection_evidence",
            source_id=self._component_id,
            payload={"started_at": started_at, "finished_at": time(),
                     "artifact_results": evidence_results},
            is_persistent=True,
        )
        self._collection_evidence.append(message)
        return message

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

        return apply_dependency_readiness(self, ServiceReadiness(
            component_id="storage",
            component_type="storage_manager",
            required=True,
            ready=not getattr(getattr(self, "_maintenance", None), "terminated", False),
            reason="ready",
        ))

    @service_operation()
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

    @service_operation()
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
        with self._preservation_lock:
            self._unfinished_record_paths.add(path)
            self._unfinished_record_contents.pop(path, None)
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
        with self._preservation_lock:
            serialized = json.dumps(session_record, indent=2)
            self._unfinished_record_contents[path] = serialized
            self._write_record_contents(path, serialized)
            self._last_written_record = (path, serialized)
            self._unfinished_record_paths.discard(path)
            self._unfinished_record_contents.pop(path, None)

    @staticmethod
    def _write_record_contents(path: Path, serialized: str) -> None:
        with path.open("w", encoding="utf-8") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        if os.name == "posix":
            for directory in (path.parent, path.parent.parent):
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

    @service_operation(new_work=True)
    def write_initial_session_record(
        self,
        session_id: str,
        **session_record_evidence: Any,
    ) -> Path:
        """Write the initial Phase 13 Session Record to its accepted path."""

        path = self._session_directory(session_id) / "session_record_initial.json"
        self.write_session_record(path, **session_record_evidence)
        return path

    @service_operation()
    def write_final_session_record(
        self,
        session_id: str,
        **session_record_evidence: Any,
    ) -> Path:
        """Write the final Phase 13 Session Record to its accepted path."""

        with self._preservation_lock:
            self._final_record_confirmation = None
            path = self._session_directory(session_id) / "session_record_final.json"
            self.write_session_record(path, **session_record_evidence)
            self._final_record_confirmation = (session_id, path, self._last_written_record[1])
            return path

    @service_operation()
    def write_evidence_archive(
        self,
        session_id: str,
        compiled_runtime_evidence: dict[str, Iterable[Any]],
    ) -> dict[str, Path]:
        """Write the Phase 13 Evidence Archive from Ingestor compilation."""

        with self._preservation_lock:
            # A failed rewrite must never leave an earlier receipt authorizing release.
            self._archive_confirmation = None
            self._unfinished_archive_scopes.add(session_id)
            runtime_evidence = deepcopy([
                _to_plain_data(item) for item in compiled_runtime_evidence.get("runtime_evidence", ())
            ])
            ingest_audit = deepcopy([
                _to_plain_data(item) for item in compiled_runtime_evidence.get("ingest_audit", ())
            ])
            archive_directory = self._session_directory(session_id) / "evidence"
            archive_directory.mkdir(parents=True, exist_ok=True)
            runtime_evidence_path = archive_directory / "runtime_evidence.jsonl"
            ingest_audit_path = archive_directory / "ingest_audit.jsonl"
            compilation_summary_path = archive_directory / "compilation_summary.json"

            _write_jsonl(runtime_evidence_path, runtime_evidence)
            _write_jsonl(ingest_audit_path, ingest_audit)
            summary = {
                "session_id": session_id,
                "runtime_evidence_count": len(runtime_evidence),
                "ingest_audit_count": len(ingest_audit),
                "runtime_evidence_ids": [item.get("evidence_id") for item in runtime_evidence],
                "ingest_audit_evidence_ids": [item.get("evidence_id") for item in ingest_audit],
            }
            with compilation_summary_path.open("w", encoding="utf-8") as summary_file:
                json.dump(summary, summary_file, indent=2)
                summary_file.flush()
                os.fsync(summary_file.fileno())
            if os.name == "posix":
                for directory in (archive_directory, archive_directory.parent, self._records_path.parent):
                    descriptor = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            self._archive_confirmation = {
                "session_id": session_id,
                "runtime_evidence": runtime_evidence,
                "ingest_audit": ingest_audit,
                "compilation_summary": deepcopy(summary),
            }
            self._unfinished_archive_scopes.discard(session_id)
            return {
                "runtime_evidence": runtime_evidence_path,
                "ingest_audit": ingest_audit_path,
                "compilation_summary": compilation_summary_path,
            }

    @service_operation()
    def write_acquisition_stage(
        self, session_id: str, compiled_runtime_evidence: dict[str, Iterable[Any]],
        *, receipt: Mapping[str, Any], **session_record_evidence: Any,
    ) -> dict[str, Path]:
        """Preserve verified acquisition compilation and its record without closing the archive."""
        with self._preservation_lock:
            evidence = deepcopy([_to_plain_data(item) for item in compiled_runtime_evidence["runtime_evidence"]])
            audit = deepcopy([_to_plain_data(item) for item in compiled_runtime_evidence["ingest_audit"]])
            marker_id = receipt.get("evidence_id")
            sequence = receipt.get("marker_stream_sequence")
            if (receipt.get("durable_receipt_confirmed") is not True
                    or receipt.get("session_id") != session_id
                    or not isinstance(marker_id, str) or not marker_id
                    or type(sequence) is not int or sequence <= 0
                    or not any(item.get("evidence_id") == marker_id for item in evidence)
                    or any(item.get("session_id") != session_id for item in evidence)):
                raise ValueError("Matching verified acquisition receipt and compilation are required")
            config = _to_plain_data(session_record_evidence.get("accepted_session_config"))
            if not isinstance(config, dict) or config.get("session_id") != session_id:
                raise ValueError("Final Session Record identity does not match acquisition compilation")
            directory = self._session_directory(session_id) / "evidence"
            final_path = directory.parent / "session_record_final.json"
            if session_id in self._unfinished_archive_scopes or final_path in self._unfinished_record_paths:
                raise RuntimeError("Interrupted persistence requires existing authorized recovery")
            if any((directory / name).exists() for name in (
                    "runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json")):
                if self._archive_confirmation is None or self._archive_confirmation["session_id"] != session_id:
                    raise RuntimeError("Existing Session archive preservation is unconfirmed")
                expected = {name: self._archive_confirmation[name]
                            for name in ("runtime_evidence", "ingest_audit", "compilation_summary")}
                actual = self._read_archive_products(directory)
                if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                    raise RuntimeError("Existing Session archive preservation is unconfirmed")
                if actual["compilation_summary"].get("archive_closed") is True:
                    raise RuntimeError("A closed Evidence Archive cannot accept Stage A writes")
            if final_path.exists() and self.get_session_preservation_confirmation(session_id) is None:
                raise RuntimeError("Existing final Session Record preservation is unconfirmed")
            self._unfinished_archive_scopes.add(session_id)
            try:
                paths = self.write_evidence_archive(session_id,
                    {"runtime_evidence": evidence, "ingest_audit": audit})
                # Keep the operation unresolved until all products, including the record, are confirmed.
                self._unfinished_archive_scopes.add(session_id)
                paths["session_record"] = self.write_final_session_record(session_id, **session_record_evidence)
                if self.get_session_preservation_confirmation(session_id) is None:
                    raise RuntimeError("Acquisition archive and final Session Record readback is unconfirmed")
                summary = deepcopy(self._archive_confirmation["compilation_summary"])
                summary.update(stage_a_complete=True, archive_closed=False,
                    acquisition_evidence_completion={"evidence_id": marker_id, "marker_stream_sequence": sequence},
                    runtime_evidence_origins={"ingestor": list(summary["runtime_evidence_ids"])})
                self._write_record_contents(paths["compilation_summary"], json.dumps(summary, indent=2))
                self._archive_confirmation["compilation_summary"] = summary
                if self.get_acquisition_stage_preservation_confirmation(session_id) is None:
                    raise RuntimeError("Stage A preservation readback is unconfirmed")
                self._unfinished_archive_scopes.discard(session_id)
                return paths
            except BaseException:
                self._archive_confirmation = None
                self._unfinished_archive_scopes.add(session_id)
                raise

    def get_acquisition_stage_preservation_confirmation(self, session_id: str) -> dict[str, Any] | None:
        """Confirm current Stage A products and final record, not a summary flag alone."""
        with self._preservation_lock:
            confirmation = self.get_session_preservation_confirmation(session_id)
            if confirmation is None:
                return None
            summary = confirmation["compilation_summary"]
            if summary.get("stage_a_complete") is not True or summary.get("archive_closed") is not False:
                return None
            return confirmation

    @staticmethod
    def _validate_artifact_collection_handoff(session_id: str, handoff: Any) -> dict[str, Any]:
        """Validate the existing portable handoff without interpreting scientific data."""
        plain = json.loads(json.dumps(_to_plain_data(handoff), allow_nan=False))
        if (not isinstance(plain, dict) or plain.get("session_id") != session_id
                or not isinstance(plain.get("artifacts"), list)):
            raise ValueError("Artifact handoff must identify the requested Session and its artifacts")
        identities = set()
        for entry in plain["artifacts"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("artifact_manifest"), dict):
                raise ValueError("Artifact handoff entry requires a complete manifest")
            data = entry["artifact_manifest"]
            if not isinstance(data.get("local_managed_paths"), list) or not isinstance(data.get("details"), dict):
                raise ValueError("Artifact handoff manifest requires structured paths and details")
            manifest = ArtifactManifest.from_dict(data)
            if (manifest.session_id != session_id or any(
                    not isinstance(value, str) or not value for value in (
                        manifest.artifact_manifest_id, manifest.experiment_id,
                        manifest.acquisition_node_id, manifest.source_component_id,
                        manifest.storage_id, manifest.artifact_type, manifest.lifecycle_state))
                    or not isinstance(manifest.local_storage_path, str)
                    or (manifest.external_artifact_path is not None
                        and not isinstance(manifest.external_artifact_path, str))
                    or not all(isinstance(path, str) for path in manifest.local_managed_paths)):
                raise ValueError("Artifact handoff contains inconsistent manifest identities or paths")
            missing = entry.get("missing_finalization_evidence")
            if type(missing) is not bool or missing != (manifest.lifecycle_state != "finalized"):
                raise ValueError("Artifact handoff finalization information is inconsistent")
            if manifest.artifact_manifest_id in identities:
                raise ValueError("Artifact handoff contains duplicate artifact identities")
            identities.add(manifest.artifact_manifest_id)
        return plain

    def _artifact_collection_handoff_path(self, session_id: str) -> Path:
        if (not isinstance(session_id, str) or not session_id or session_id in {".", ".."}
                or any(character in session_id for character in '/\\\x00:')):
            raise ValueError("Handoff Session identity must be a single path component")
        return self._session_directory(session_id) / "artifact_collection_handoff.json"

    @staticmethod
    def _sync_artifact_handoff_directory(path: Path) -> None:
        if os.name == "posix":
            for directory in (path.parent, path.parent.parent):
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

    def _read_artifact_collection_handoff_contents(self, session_id: str, path: Path) -> dict[str, Any]:
        def unique_fields(pairs):
            fields = {}
            for name, value in pairs:
                if name in fields:
                    raise ValueError("Artifact handoff contains conflicting duplicate JSON fields")
                fields[name] = value
            return fields

        with path.open(encoding="utf-8") as source:
            return self._validate_artifact_collection_handoff(
                session_id, json.load(source, object_pairs_hook=unique_fields))

    @service_operation()
    def write_artifact_collection_handoff(self, session_id: str, handoff: dict[str, Any]) -> Path:
        """Publish one durable handoff; identical retries never overwrite existing contents."""
        with self._preservation_lock:
            path = self._artifact_collection_handoff_path(session_id)
            expected = self._validate_artifact_collection_handoff(session_id, handoff)
            serialized = json.dumps(expected, sort_keys=True, indent=2, allow_nan=False)
            temporary = None
            self._unfinished_record_paths.add(path)
            try:
                if os.path.lexists(path):
                    actual = self._read_artifact_collection_handoff_contents(session_id, path)
                    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                        raise ValueError("Existing artifact handoff differs from the trusted compilation")
                    with path.open("r+b") as source:
                        os.fsync(source.fileno())
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with NamedTemporaryFile(dir=path.parent, prefix=".incomplete-handoff-", delete=False) as output:
                        temporary = Path(output.name)
                    self._write_record_contents(temporary, serialized)
                    os.link(temporary, path)
                    temporary.unlink()
                    temporary = None
                self._sync_artifact_handoff_directory(path)
                actual = self._read_artifact_collection_handoff_contents(session_id, path)
                if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                    raise RuntimeError("Artifact handoff preservation readback is unconfirmed")
                self._unfinished_record_paths.discard(path)
                return path
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    @service_operation()
    def read_artifact_collection_handoff(self, session_id: str) -> dict[str, Any]:
        """Read a validated saved handoff without any original runtime Session binding."""
        with self._preservation_lock:
            path = self._artifact_collection_handoff_path(session_id)
            if path in self._unfinished_record_paths:
                raise RuntimeError("Artifact handoff persistence remains unconfirmed")
            return self._read_artifact_collection_handoff_contents(session_id, path)

    def get_session_preservation_confirmation(self, session_id: str) -> dict[str, Any] | None:
        """Verify current archive products and read the successfully written final Session Record."""
        with self._preservation_lock:
            if (self._archive_confirmation is None
                    or self._archive_confirmation["session_id"] != session_id
                    or self._final_record_confirmation is None
                    or self._final_record_confirmation[0] != session_id):
                return None
            confirmation = deepcopy(self._archive_confirmation)
            expected = {name: confirmation[name] for name in ("runtime_evidence", "ingest_audit")}
            expected["compilation_summary"] = confirmation["compilation_summary"]
            try:
                actual = self._read_archive_products(self._session_directory(session_id) / "evidence")
                if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                    return None
                record = self.read_session_record(self._final_record_confirmation[1])
                if json.dumps(record, sort_keys=True) != json.dumps(json.loads(self._final_record_confirmation[2]), sort_keys=True):
                    return None
                confirmation["session_record"] = record
            except (OSError, ValueError):
                return None
            return confirmation

    @service_operation()
    def write_framework_evidence_archive(self, compiled_runtime_evidence: dict[str, Iterable[Any]]) -> dict[str, Path]:
        """Persist deployment-scoped evidence/audit/summary without a Session Record."""
        with self._preservation_lock:
            self._framework_archive_confirmation = None
            self._unfinished_archive_scopes.add(None)
            evidence = deepcopy([_to_plain_data(item) for item in compiled_runtime_evidence.get("runtime_evidence", ())])
            audit = deepcopy([_to_plain_data(item) for item in compiled_runtime_evidence.get("ingest_audit", ())])
            if any(item.get("session_id") is not None for item in evidence):
                raise ValueError("Framework archive cannot contain Session-scoped evidence")
            directory = self._records_path.parent / "framework" / "evidence"
            directory.mkdir(parents=True, exist_ok=True)
            summary = {
                "session_id": None, "runtime_evidence_count": len(evidence), "ingest_audit_count": len(audit),
                "runtime_evidence_ids": [item["evidence_id"] for item in evidence],
                "ingest_audit_evidence_ids": [item["evidence_id"] for item in audit],
            }
            contents = {"runtime_evidence": evidence, "ingest_audit": audit, "compilation_summary": summary}
            paths = {}
            for name, data in contents.items():
                path = directory / (name + (".json" if name == "compilation_summary" else ".jsonl"))
                with path.open("w", encoding="utf-8") as output:
                    if name == "compilation_summary":
                        json.dump(data, output, indent=2, allow_nan=False)
                    else:
                        for item in data:
                            output.write(json.dumps(item, allow_nan=False) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
                paths[name] = path
            if os.name == "posix":
                for parent in (directory, directory.parent, self._records_path.parent):
                    descriptor = os.open(parent, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            self._framework_archive_confirmation = contents
            self._unfinished_archive_scopes.discard(None)
            return paths

    def get_framework_preservation_confirmation(self) -> dict[str, Any] | None:
        """Confirm exact current durable products, not a historical publication result."""
        with self._preservation_lock:
            expected = self._framework_archive_confirmation
            if expected is None:
                return None
            directory = self._records_path.parent / "framework" / "evidence"
            try:
                actual = self._read_archive_products(directory)
            except (OSError, ValueError):
                return None
            return deepcopy(actual) if actual == expected else None

    @staticmethod
    def _read_archive_products(directory: Path) -> dict[str, Any]:
        products = {}
        for name in ("runtime_evidence", "ingest_audit"):
            with (directory / (name + ".jsonl")).open(encoding="utf-8") as source:
                products[name] = [json.loads(line) for line in source]
        with (directory / "compilation_summary.json").open(encoding="utf-8") as source:
            products["compilation_summary"] = json.load(source)
        return products

    @contextmanager
    def framework_preservation_guard(self, *, require_closeout: bool = False):
        """Keep current archival and optional final intake coverage stable through commit."""
        with self._preservation_lock:
            confirmation = self.get_framework_preservation_confirmation()
            if require_closeout and (
                    self._framework_closeout_compilation is None or confirmation is None
                    or any(confirmation[name] != required
                           for name, required in self._framework_closeout_compilation.items())):
                confirmation = None
            yield confirmation

    def _framework_evidence_write_safe(self) -> bool:
        """Permit initial creation or append to confirmed products, never implicit repair."""
        with self._preservation_lock:
            if None in self._unfinished_archive_scopes:
                return False
            if self._framework_archive_confirmation is not None:
                return self.get_framework_preservation_confirmation() is not None
            directory = self._records_path.parent / "framework" / "evidence"
            return not any((directory / name).exists() for name in (
                "runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"))

    def _retain_framework_closeout_compilation(self, compilation):
        """Retain Ingestor's final required coverage, independently of archive rewrites."""
        with self._preservation_lock:
            self._framework_closeout_compilation = {
                name: deepcopy([_to_plain_data(item) for item in compilation[name]])
                for name in ("runtime_evidence", "ingest_audit")
            }

    @contextmanager
    def session_preservation_guard(self, session_id: str) -> Iterator[dict[str, Any] | None]:
        """Keep current preservation confirmation stable through a synchronous release commit."""
        with self._preservation_lock:
            yield self.get_session_preservation_confirmation(session_id)

    def read_session_record(
        self,
        session_record_path: str | Path,
    ) -> dict[str, Any]:
        """Read a minimal v1 Session Record JSON evidence package."""

        path = Path(session_record_path)
        with path.open("r", encoding="utf-8") as session_record_file:
            return json.load(session_record_file)

    def maintenance_blockers(self, ingestor, storage_manager) -> list[str]:
        """Active operations are tracked by admission; future collection is not a blocker."""
        with self._preservation_lock:
            blockers = ["Unfinished persistence"] if self._unfinished_archive_scopes or self._unfinished_record_paths else []
            for message in self._collection_evidence:
                confirmation = self.get_session_preservation_confirmation(message.session_id)
                if confirmation is None or message.to_dict() not in confirmation["runtime_evidence"]:
                    blockers.append("Unpreserved collection evidence")
                    break
            return blockers

    def _recover_archive_write(self, command, authorization, attempt) -> dict:
        interface = self._maintenance
        interface._require_recovery_authorization(command)
        scope = command.payload["obligation"].get("session_id")
        if scope not in self._unfinished_archive_scopes:
            raise ValueError("No identified interrupted archive write remains")
        intake = interface.ingestor
        if scope is None:
            compiled = intake.compile_framework_runtime_evidence()
        else:
            if intake.session_id != scope or intake._journal_failed:
                raise ValueError("Complete trustworthy compilation for this Session is unavailable")
            compiled = intake.compile_persistent_runtime_evidence()
        attempt["actions"].append("archive_write_attempted")
        paths = (self.write_framework_evidence_archive(compiled) if scope is None
                 else self.write_evidence_archive(scope, compiled))
        actual = self._read_archive_products(paths["runtime_evidence"].parent)
        expected = {name: [_to_plain_data(item) for item in compiled[name]]
                    for name in ("runtime_evidence", "ingest_audit")}
        expected["compilation_summary"] = {"session_id": scope,
            "runtime_evidence_count": len(expected["runtime_evidence"]),
            "ingest_audit_count": len(expected["ingest_audit"]),
            "runtime_evidence_ids": [m.get("evidence_id") for m in expected["runtime_evidence"]],
            "ingest_audit_evidence_ids": [m.get("evidence_id") for m in expected["ingest_audit"]]}
        if any(actual[name] != expected[name] for name in expected):
            self._unfinished_archive_scopes.add(scope)
            raise RuntimeError("Recovered archive contents differ from the trusted compilation")
        attempt["actions"].append("archive_write_confirmed")
        return {"actual_write_confirmed": True, "session_id": scope,
                "paths": {name: str(path) for name, path in paths.items()}}

    def _recover_session_record_write(self, command, authorization, attempt) -> dict:
        self._maintenance._require_recovery_authorization(command)
        obligation = command.payload["obligation"]
        scope, kind = obligation.get("session_id"), obligation.get("record_kind")
        if not isinstance(scope, str) or not scope or kind not in {"initial", "final"}:
            raise ValueError("Identified initial/final Session Record scope is required")
        path = self._session_directory(scope) / f"session_record_{kind}.json"
        serialized = self._unfinished_record_contents.get(path)
        if path not in self._unfinished_record_paths or serialized is None:
            raise ValueError("Complete trustworthy inputs for this interrupted write are unavailable")
        expected = json.loads(serialized)
        if expected.get("accepted_session_config", {}).get("session_id") != scope:
            raise ValueError("Retained Session Record inputs have a conflicting Session identity")
        attempt["actions"].append("session_record_write_attempted")
        self._write_record_contents(path, serialized)
        if json.dumps(self.read_session_record(path), sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise RuntimeError("Recovered Session Record differs from its retained inputs")
        self._unfinished_record_paths.discard(path)
        self._unfinished_record_contents.pop(path, None)
        if kind == "final":
            self._final_record_confirmation = (scope, path, serialized)
        attempt["actions"].append("session_record_write_confirmed")
        return {"actual_write_confirmed": True, "session_id": scope, "path": str(path)}

    def _recover_artifact_transfer(self, command, authorization, attempt) -> dict:
        self._maintenance._require_recovery_authorization(command)
        obligation = command.payload["obligation"]
        original = next((m for m in self._collection_evidence
                         if m.evidence_id == obligation.get("evidence_id")), None)
        if original is None or original.session_id != obligation.get("session_id"):
            raise ValueError("Original owned transfer obligation is unavailable or has a different Session")
        identity = obligation.get("artifact_manifest_id")
        failed = [r for r in original.payload["artifact_results"]
                  if r["artifact_manifest_id"] == identity and r["collection_status"] == "failure"]
        if len(failed) != 1:
            raise ValueError("No unique original failed artifact transfer is identified")
        intake = self._maintenance.ingestor
        if intake.session_id != original.session_id or intake._journal_failed:
            raise ValueError("Trustworthy original artifact handoff is unavailable")
        candidates = [e for e in intake.compile_artifact_collection_handoff(original.session_id)["artifacts"]
                      if e["artifact_manifest"]["artifact_manifest_id"] == identity]
        if len(candidates) != 1:
            raise ValueError("Authoritative artifact manifest is unavailable or ambiguous")
        manifest = candidates[0]["artifact_manifest"]
        if any(manifest[key] != failed[0][key] for key in ("experiment_id", "acquisition_node_id")):
            raise ValueError("Original transfer and authoritative manifest identities conflict")
        # Existing retrieval checks endpoint/source/destination and never overwrites a final copy.
        attempt["actions"].append("fresh_transfer_attempted")
        evidence_results = []
        started_at = time()
        result = self._collect_artifacts({"session_id": original.session_id, "artifacts": candidates}, evidence_results)
        message = self._record_collection_evidence(original.session_id, started_at, evidence_results)
        attempt["collection_evidence_id"] = message.evidence_id
        attempt["confirmation"] = result.to_dict()
        if not result.succeeded:
            raise RuntimeError("Fresh transfer or existing light verification did not succeed")
        attempt["actions"].append("fresh_transfer_verified")
        return result.to_dict()

    def maintenance_diagnostics(self, ingestor, storage_manager) -> dict[str, Any]:
        """Report unfinished persistence and original collection evidence by existing identities."""
        with self._preservation_lock:
            messages = tuple(self._collection_evidence)
            scopes = sorted(self._unfinished_archive_scopes, key=lambda value: value or "")
            paths = sorted(str(path) for path in self._unfinished_record_paths)
        interface = getattr(self, "_maintenance", None)
        blockers = self.maintenance_blockers(ingestor, storage_manager)
        evidence = []
        for message in messages:
            confirmation = self.get_session_preservation_confirmation(message.session_id)
            preserved = confirmation is not None and message.to_dict() in confirmation["runtime_evidence"]
            evidence.append({"session_id": message.session_id, "evidence_id": message.evidence_id,
                "archival_outcome": "completed" if preserved else "unresolved",
                "administrative_outcome": interface._administrative_outcome({"evidence_id": message.evidence_id}) if interface else None,
                "recovery_assessment": (None if preserved else "potentially_recoverable"
                    if ingestor.has_durable_runtime_evidence(message) else "administrator_intervention"),
                "artifact_results": deepcopy(message.payload["artifact_results"])})
        return {
            "unfinished_archive_scopes": scopes,
            "unfinished_record_paths": paths,
            "collection_evidence": evidence,
            "restricted_persistence_scopes": ("recorded paths/archive scopes; consistency unconfirmed where unfinished"
                                               if blockers else None),
            "blocking_conditions": blockers,
        }

    async def _close_maintenance_resources(self, force: bool) -> None:
        # Files and SFTP resources are closed by the operations that opened them.
        pass

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
        jsonl_file.flush()
        os.fsync(jsonl_file.fileno())


def _plain_field(value: Any, field_name: str) -> Any:
    plain = _to_plain_data(value)
    if isinstance(plain, dict):
        return plain.get(field_name)
    return None
