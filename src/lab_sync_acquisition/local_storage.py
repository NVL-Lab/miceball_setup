"""Local persistence for one co-located AcquisitionNode."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic
from typing import Any, IO, Iterable
from uuid import uuid4

from lab_sync_acquisition.service_readiness import ServiceReadiness


REQUIRED_SCIENTIFIC_ROW_FIELDS = frozenset(
    {
        "session_time_s",
        "experiment_time_s",
        "acquisition_node_local_time_s",
        "timestamp_status",
        "experiment_id",
    }
)


@dataclass(frozen=True)
class ArtifactManifest:
    """Authoritative local discovery record for one scientific artifact."""

    artifact_manifest_id: str
    session_id: str
    experiment_id: str
    acquisition_node_id: str
    source_component_id: str
    artifact_type: str
    lifecycle_state: str
    storage_id: str
    local_storage_path: str
    external_artifact_path: str | None
    local_managed_paths: tuple[str, ...]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_manifest_id": self.artifact_manifest_id,
            "session_id": self.session_id,
            "experiment_id": self.experiment_id,
            "acquisition_node_id": self.acquisition_node_id,
            "source_component_id": self.source_component_id,
            "artifact_type": self.artifact_type,
            "lifecycle_state": self.lifecycle_state,
            "storage_id": self.storage_id,
            "local_storage_path": self.local_storage_path,
            "external_artifact_path": self.external_artifact_path,
            "local_managed_paths": list(self.local_managed_paths),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactManifest:
        return cls(
            artifact_manifest_id=data["artifact_manifest_id"],
            session_id=data["session_id"],
            experiment_id=data["experiment_id"],
            acquisition_node_id=data["acquisition_node_id"],
            source_component_id=data["source_component_id"],
            artifact_type=data["artifact_type"],
            lifecycle_state=data["lifecycle_state"],
            storage_id=data["storage_id"],
            local_storage_path=data["local_storage_path"],
            external_artifact_path=data["external_artifact_path"],
            local_managed_paths=tuple(data["local_managed_paths"]),
            details=dict(data["details"]),
        )


@dataclass(frozen=True)
class LocalStorageEvidence:
    """LocalStorageManager-owned evidence about one persistence operation."""

    evidence_type: str
    session_id: str
    acquisition_node_id: str
    storage_id: str | None
    artifact_manifest_id: str | None
    reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "session_id": self.session_id,
            "acquisition_node_id": self.acquisition_node_id,
            "storage_id": self.storage_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "reason": self.reason,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalStorageEvidence:
        return cls(
            evidence_type=data["evidence_type"],
            session_id=data["session_id"],
            acquisition_node_id=data["acquisition_node_id"],
            storage_id=data["storage_id"],
            artifact_manifest_id=data["artifact_manifest_id"],
            reason=data["reason"],
            details=dict(data["details"]),
        )


@dataclass(frozen=True)
class LocalStorageCompletionSummary:
    """Plain-data summary of local finalization only."""

    session_id: str
    acquisition_node_id: str
    finalized: bool
    stream_count: int
    manifest_count: int
    evidence_count: int
    streams: tuple[dict[str, Any], ...]
    manifests: tuple[ArtifactManifest, ...]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "acquisition_node_id": self.acquisition_node_id,
            "finalized": self.finalized,
            "stream_count": self.stream_count,
            "manifest_count": self.manifest_count,
            "evidence_count": self.evidence_count,
            "streams": [dict(stream) for stream in self.streams],
            "manifests": [manifest.to_dict() for manifest in self.manifests],
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalStorageCompletionSummary:
        return cls(
            session_id=data["session_id"],
            acquisition_node_id=data["acquisition_node_id"],
            finalized=data["finalized"],
            stream_count=data["stream_count"],
            manifest_count=data["manifest_count"],
            evidence_count=data["evidence_count"],
            streams=tuple(dict(stream) for stream in data["streams"]),
            manifests=tuple(
                ArtifactManifest.from_dict(manifest)
                for manifest in data["manifests"]
            ),
            details=dict(data["details"]),
        )


@dataclass
class _OpenStream:
    metadata: dict[str, Any]
    manifest: ArtifactManifest
    rows_file: IO[str] | None
    row_count: int = 0
    finalized: bool = False
    buffered_rows: list[str] = field(default_factory=list)
    last_flush_monotonic_s: float = field(default_factory=monotonic)


class LocalStorageManager:
    """Incrementally persists scientific streams for one AcquisitionNode."""

    def __init__(
        self,
        root_path: str | Path,
        session_id: str,
        acquisition_node_id: str,
        max_buffered_rows: int | None = None,
        max_flush_interval_s: float | None = None,
    ) -> None:
        if max_buffered_rows is not None and (
            isinstance(max_buffered_rows, bool)
            or not isinstance(max_buffered_rows, int)
            or max_buffered_rows < 1
        ):
            raise ValueError("max_buffered_rows must be a positive integer")
        if max_flush_interval_s is not None and (
            isinstance(max_flush_interval_s, bool)
            or not isinstance(max_flush_interval_s, (int, float))
            or not math.isfinite(max_flush_interval_s)
            or max_flush_interval_s <= 0
        ):
            raise ValueError("max_flush_interval_s must be positive")
        self._root_path = Path(root_path)
        self._session_id = session_id
        self._acquisition_node_id = acquisition_node_id
        self._max_buffered_rows = max_buffered_rows
        self._max_flush_interval_s = max_flush_interval_s
        self._streams: dict[str, _OpenStream] = {}
        self._evidence: tuple[LocalStorageEvidence, ...] = ()

    @property
    def root_path(self) -> Path:
        return self._root_path

    @property
    def acquisition_node_id(self) -> str:
        return self._acquisition_node_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def evidence(self) -> tuple[LocalStorageEvidence, ...]:
        return self._evidence

    @property
    def manifests(self) -> tuple[ArtifactManifest, ...]:
        return tuple(stream.manifest for stream in self._streams.values())

    def check_ready(self) -> ServiceReadiness:
        """Verify that the configured local root can preserve data."""

        try:
            self._root_path.mkdir(parents=True, exist_ok=True)
            probe = self._root_path / f".readiness-{uuid4().hex}"
            probe.write_text("ready", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            return ServiceReadiness(
                component_id=self._acquisition_node_id,
                component_type="local_storage_manager",
                required=True,
                ready=False,
                reason=str(error),
            )
        return ServiceReadiness(
            component_id=self._acquisition_node_id,
            component_type="local_storage_manager",
            required=True,
            ready=True,
            reason="ready",
        )

    def create_stream(
        self,
        *,
        session_id: str,
        experiment_id: str,
        acquisition_node_id: str,
        source_component_id: str,
        data_product_id: str,
        artifact_type: str,
        schema: dict[str, Any],
        details: dict[str, Any] | None = None,
        external_artifact_path: str | None = None,
    ) -> ArtifactManifest:
        """Create one stream, its stable metadata, and its manifest."""

        if acquisition_node_id != self._acquisition_node_id:
            raise ValueError("acquisition_node_id does not match LocalStorageManager")
        if session_id != self._session_id:
            raise ValueError("session_id does not match LocalStorageManager")
        storage_id = uuid4().hex
        manifest_id = uuid4().hex
        stream_dir = self._root_path / session_id / experiment_id / storage_id
        rows_path = stream_dir / "rows.jsonl"
        metadata_path = stream_dir / "metadata.json"
        manifest_path = stream_dir / "artifact_manifest.json"
        metadata = {
            "session_id": session_id,
            "experiment_id": experiment_id,
            "acquisition_node_id": acquisition_node_id,
            "source_component_id": source_component_id,
            "data_product_id": data_product_id,
            "artifact_type": artifact_type,
            "schema": dict(schema),
            "details": dict(details) if details is not None else {},
        }
        manifest = ArtifactManifest(
            artifact_manifest_id=manifest_id,
            session_id=session_id,
            experiment_id=experiment_id,
            acquisition_node_id=acquisition_node_id,
            source_component_id=source_component_id,
            artifact_type=artifact_type,
            lifecycle_state="open",
            storage_id=storage_id,
            local_storage_path=str(rows_path),
            external_artifact_path=external_artifact_path,
            local_managed_paths=(
                str(metadata_path),
                str(rows_path),
                str(manifest_path),
            ),
            details=dict(details) if details is not None else {},
        )
        rows_file: IO[str] | None = None
        try:
            stream_dir.mkdir(parents=True, exist_ok=False)
            metadata_path.write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )
            rows_file = rows_path.open("a", encoding="utf-8")
            self._write_manifest(manifest)
            self._streams[storage_id] = _OpenStream(
                metadata,
                manifest,
                rows_file,
                last_flush_monotonic_s=monotonic(),
            )
            self._record_evidence(
                "stream_created", "created", manifest=manifest
            )
            self._record_evidence(
                "manifest_created", "created", manifest=manifest
            )
            return manifest
        except Exception as error:
            if rows_file is not None and not rows_file.closed:
                rows_file.close()
            self._record_failure_evidence(
                "write_failure",
                str(error),
                storage_id=storage_id,
                artifact_manifest_id=manifest_id,
                details={"operation": "stream_creation"},
            )
            raise

    def append_rows(
        self,
        storage_id: str,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        """Append validated timestamped rows immediately to JSONL."""

        stream = self._require_stream(storage_id)
        if stream.finalized or stream.rows_file is None:
            self._record_failure_evidence(
                "write_failure",
                "stream is finalized",
                manifest=stream.manifest,
                details={"operation": "row_append"},
            )
            raise RuntimeError("Cannot append to a finalized local stream")
        for supplied_row in rows:
            try:
                row = dict(supplied_row)
                missing = REQUIRED_SCIENTIFIC_ROW_FIELDS.difference(row)
                if missing:
                    raise ValueError(
                        "missing required fields: "
                        + ", ".join(sorted(missing))
                    )
                if row["experiment_id"] != stream.manifest.experiment_id:
                    raise ValueError("row experiment_id does not match stream")
                serialized_row = json.dumps(row)
            except (TypeError, ValueError) as error:
                self._record_failure_evidence(
                    "write_failure",
                    str(error),
                    manifest=stream.manifest,
                    details={"operation": "row_serialization"},
                )
                raise

            if self._max_buffered_rows is None:
                self._write_serialized_row(stream, serialized_row)
            else:
                stream.buffered_rows.append(serialized_row)
                if len(stream.buffered_rows) >= self._max_buffered_rows:
                    self.flush(storage_id)
            stream.row_count += 1
            if self._flush_interval_elapsed(stream):
                self.flush(storage_id)

    def flush(self, storage_id: str) -> None:
        """Flush current writes without finalizing the stream."""

        stream = self._require_stream(storage_id)
        if stream.rows_file is None:
            return
        try:
            while stream.buffered_rows:
                serialized_row = stream.buffered_rows[0]
                stream.rows_file.write(serialized_row)
                stream.rows_file.write("\n")
                del stream.buffered_rows[0]
            stream.rows_file.flush()
            os.fsync(stream.rows_file.fileno())
            stream.last_flush_monotonic_s = monotonic()
        except (OSError, ValueError) as error:
            self._record_failure_evidence(
                "write_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "flush"},
            )
            raise

    def finalize_stream(self, storage_id: str) -> ArtifactManifest:
        """Close one stream and finalize its immutable manifest."""

        stream = self._require_stream(storage_id)
        if stream.finalized:
            return stream.manifest
        try:
            self.flush(storage_id)
            if stream.rows_file is not None:
                stream.rows_file.close()
                stream.rows_file = None
            finalized_manifest = replace(
                stream.manifest,
                lifecycle_state="finalized",
                details={
                    **stream.manifest.details,
                    "row_count": stream.row_count,
                },
            )
            self._write_manifest(finalized_manifest)
            stream.manifest = finalized_manifest
            stream.finalized = True
            self._record_evidence(
                "stream_finalized", "finalized", manifest=stream.manifest
            )
            self._record_evidence(
                "manifest_finalized", "finalized", manifest=stream.manifest
            )
            return stream.manifest
        except (OSError, ValueError, TypeError) as error:
            self._record_failure_evidence(
                "finalization_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "stream_finalization"},
            )
            raise

    def cleanup(self) -> None:
        """Flush and close open resources without deleting local records."""

        failures: list[str] = []
        for storage_id, stream in self._streams.items():
            if stream.rows_file is None:
                continue
            try:
                self.flush(storage_id)
                stream.rows_file.close()
                stream.rows_file = None
            except (OSError, ValueError) as error:
                failures.append(f"{storage_id}: {error}")
        if failures:
            reason = "; ".join(failures)
            self._record_failure_evidence(
                "cleanup_failed",
                reason,
                details={"operation": "cleanup"},
            )
            raise RuntimeError(f"Local storage cleanup failed: {reason}")
        self._record_evidence(
            "cleanup_completed",
            reason="completed",
            details={"operation": "cleanup"},
        )

    def finalize_all(self) -> LocalStorageCompletionSummary:
        """Finalize every stream and return local completion only."""

        for storage_id in tuple(self._streams):
            self.finalize_stream(storage_id)
        manifests = self.manifests
        streams = tuple(
            {
                "storage_id": storage_id,
                "data_product_id": stream.metadata["data_product_id"],
                "row_count": stream.row_count,
                "lifecycle_state": stream.manifest.lifecycle_state,
            }
            for storage_id, stream in self._streams.items()
        )
        return LocalStorageCompletionSummary(
            session_id=self._session_id,
            acquisition_node_id=self._acquisition_node_id,
            finalized=all(stream.finalized for stream in self._streams.values()),
            stream_count=len(self._streams),
            manifest_count=len(manifests),
            evidence_count=len(self._evidence),
            streams=streams,
            manifests=manifests,
            details={"scope": "local_completion_only"},
        )

    def _require_stream(self, storage_id: str) -> _OpenStream:
        try:
            return self._streams[storage_id]
        except KeyError as error:
            raise KeyError(f"Unknown local storage_id: {storage_id}") from error

    def _write_manifest(self, manifest: ArtifactManifest) -> None:
        manifest_path = Path(manifest.local_managed_paths[2])
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8"
        )

    def _write_serialized_row(
        self,
        stream: _OpenStream,
        serialized_row: str,
    ) -> None:
        if stream.rows_file is None:
            raise RuntimeError("Local stream has no open rows file")
        try:
            stream.rows_file.write(serialized_row)
            stream.rows_file.write("\n")
        except (OSError, ValueError) as error:
            self._record_failure_evidence(
                "write_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "row_append"},
            )
            raise

    def _flush_interval_elapsed(self, stream: _OpenStream) -> bool:
        return (
            self._max_flush_interval_s is not None
            and monotonic() - stream.last_flush_monotonic_s
            >= self._max_flush_interval_s
        )

    def _record_evidence(
        self,
        evidence_type: str,
        reason: str,
        manifest: ArtifactManifest | None = None,
        storage_id: str | None = None,
        artifact_manifest_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        evidence = LocalStorageEvidence(
            evidence_type=evidence_type,
            session_id=self._session_id,
            acquisition_node_id=self._acquisition_node_id,
            storage_id=(manifest.storage_id if manifest else storage_id),
            artifact_manifest_id=(
                manifest.artifact_manifest_id
                if manifest
                else artifact_manifest_id
            ),
            reason=reason,
            details=dict(details) if details is not None else {},
        )
        self._evidence += (evidence,)
        evidence_path = self._root_path / "local_storage_evidence.jsonl"
        with evidence_path.open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(evidence.to_dict()))
            evidence_file.write("\n")

    def _record_failure_evidence(
        self,
        evidence_type: str,
        reason: str,
        manifest: ArtifactManifest | None = None,
        storage_id: str | None = None,
        artifact_manifest_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._record_evidence(
                evidence_type,
                reason,
                manifest,
                storage_id,
                artifact_manifest_id,
                details,
            )
        except (OSError, TypeError, ValueError):
            # Evidence is appended in memory before local evidence-file writing.
            pass
