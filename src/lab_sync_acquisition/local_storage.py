"""Local persistence for one co-located AcquisitionNode."""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import stat
from dataclasses import dataclass, field, replace
from copy import deepcopy
from pathlib import Path
from time import monotonic, time
from typing import Any, Iterable
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


def _local_filesystem_identity(path: Path) -> list[str]:
    """Do not mistake a remotely shared mount for independent host-local capacity."""
    host = socket.gethostname()
    if not host:
        raise RuntimeError("Filesystem host identity is unavailable")
    resolved = path.resolve()
    if os.name == "nt":
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor))
        if drive_type not in (2, 3, 6):
            raise RuntimeError("Independent capacity of a remote or unknown volume is unconfirmed")
    else:
        # Known local mounts can be distinguished using the OS's existing mount
        # description; unknown/shared backing is not assigned a fabricated identity.
        mounts = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields, filesystem = line.split(" - ", 1)
            mount = Path(fields.split()[4].replace("\\040", " "))
            if resolved.is_relative_to(mount):
                mounts.append((len(str(mount)), filesystem.split()[0]))
        if not mounts or max(mounts)[1] not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "tmpfs", "overlay", "zfs"}:
            raise RuntimeError("Independent capacity of this filesystem is unconfirmed")
    return [host, str(resolved.stat().st_dev)]


def inspect_storage_capacity(root_path: str | Path, required_bytes: int) -> dict[str, Any]:
    """Inspect one writable destination without treating unknown capacity as ready."""
    report = {"destination": str(root_path), "required_bytes": required_bytes,
              "available_bytes": None, "filesystem_id": None, "ready": False}
    try:
        if type(required_bytes) is not int or required_bytes < 0:
            raise ValueError("An authoritative nonnegative byte budget is required")
        path = Path(root_path)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".capacity-{uuid4().hex}"
        try:
            with probe.open("xb") as output:
                output.write(b"capacity")
        finally:
            probe.unlink(missing_ok=True)
        free = shutil.disk_usage(path).free
        if type(free) is not int or free < 0:
            raise RuntimeError("Filesystem capacity or identity is indeterminate")
        report.update(available_bytes=free, filesystem_id=_local_filesystem_identity(path),
                      ready=free >= required_bytes,
                      reason="ready" if free >= required_bytes else "insufficient_storage_capacity")
    except Exception as error:
        report["reason"] = f"storage_capacity_unconfirmed: {type(error).__name__}"
    return report


def validate_storage_capacity(reports: Iterable[dict[str, Any]]) -> None:
    """Require complete owner reports and sum distinct writes sharing a filesystem."""
    groups = {}
    for report in reports:
        if "destinations" in report:
            if report.get("ready") is not True or not report["destinations"]:
                raise RuntimeError(f"Storage capacity unconfirmed: {report}")
            destinations = report["destinations"]
        else:
            destinations = (report,)
        for destination in destinations:
            _accumulate_storage_capacity(destination, groups)
    if any(required > available for required, available in groups.values()):
        raise RuntimeError("Insufficient shared-filesystem capacity for recording and preservation")


def _accumulate_storage_capacity(report, groups):
    """Accumulate one concrete destination, never aggregate free space twice."""
    identity = report.get("filesystem_id")
    if (report.get("ready") is not True or not isinstance(identity, list) or len(identity) != 2
            or any(not isinstance(value, str) or not value for value in identity)
            or type(report.get("required_bytes")) is not int or report["required_bytes"] < 0
            or type(report.get("available_bytes")) is not int or report["available_bytes"] < 0):
        raise RuntimeError(f"Storage capacity unconfirmed: {report}")
    key = tuple(identity)
    required, available = groups.get(key, (0, report["available_bytes"]))
    groups[key] = required + report["required_bytes"], min(available, report["available_bytes"])


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
    rows_file: Any
    row_count: int = 0
    finalized: bool = False
    buffered_rows: list[Any] = field(default_factory=list)
    last_flush_monotonic_s: float = field(default_factory=monotonic)
    persisted_frame_count: int = 0
    frame_bounds: dict[str, Any] = field(default_factory=dict)
    write_failed: bool = False
    written_row_count: int = 0
    durable_row_count: int = 0


def _historical_path(path: Path, root: Path) -> Path:
    """Reject escaped or aliased persisted paths rather than remapping originals."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("path_outside_storage_root")
    if resolved != path.absolute():
        raise ValueError("path_alias_unresolved")
    return resolved


def _read_inventory_record(path: Path) -> dict[str, Any]:
    """Read plain JSON without accepting ambiguous keys or nonfinite values."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("record_not_regular_file")

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_record_field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"nonfinite_record_value: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields,
                       parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("record_must_be_an_object")
    return value


def _deletion_record_path(root: Path, operation_id: str) -> Path:
    if (not isinstance(operation_id, str) or not operation_id.strip()
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in operation_id)):
        raise ValueError("Deletion operation_id must be a nonempty safe identifier")
    return _historical_path(root / "deletion_operations" / (operation_id + ".json"), root)


def _sync_deletion_directories(path: Path) -> None:
    """Confirm local operation-file directory entries on platforms supporting directory fsync."""
    if os.name == "posix":
        for directory in (path.parent, path.parent.parent):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _write_deletion_record(path: Path, record: dict, *, initial=False) -> None:
    """Fsync intent before unlink; atomically replace outcomes without losing intent."""
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(".pending")
    _historical_path(temporary, path.parent.parent)
    destination = path if initial else temporary
    with destination.open("x" if initial else "w", encoding="utf-8") as output:
        json.dump(record, output, sort_keys=True, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    if not initial:
        os.replace(temporary, path)
    _sync_deletion_directories(path)
    if _read_inventory_record(path) != record:
        raise RuntimeError("Deletion operation readback differs from durable intent/outcome")


def _read_deletion_record(root: Path, node_id: str, path: Path) -> dict:
    record = _read_inventory_record(_historical_path(path, root))
    if (record.get("acquisition_node_id") != node_id
            or path != _deletion_record_path(root, record.get("operation_id"))
            or not isinstance(record.get("request"), dict)
            or not isinstance(record.get("files"), list)
            or type(record.get("finished")) is not bool
            or type(record.get("recorded_at")) not in (int, float)
            or not math.isfinite(record["recorded_at"])
            or record.get("admission") != {"exact_originals_confirmed": True, "local_safety_confirmed": True}):
        raise ValueError("Invalid deletion operation record")
    seen = set()
    for item in record["files"]:
        manifest = ArtifactManifest.from_dict(item["artifact_manifest"])
        identity = manifest.artifact_manifest_id
        if (identity in seen or item["status"] not in {
                "pending", "deleted", "missing_deletion_unconfirmed", "failed", "unconfirmed"}
                or item["artifact_manifest"]["session_id"] != record["request"]["session_id"]
                or item["artifact_manifest"]["acquisition_node_id"] != node_id):
            raise ValueError("Invalid deletion per-file scope or outcome")
        seen.add(identity)
        original = _historical_path(Path(item["original_path"]), root)
        source = manifest.external_artifact_path or manifest.local_storage_path
        if (original != _historical_path(Path(source), root)
                or (record["request"].get("experiment_ids") is not None
                    and manifest.experiment_id not in record["request"]["experiment_ids"])):
            raise ValueError("Deletion record target identity mismatch")
        if item["status"] == "deleted" and original.exists():
            raise ValueError("A confirmed deleted original has reappeared")
    return record


def _register_historical_source(entry, manifest_path: Path, root: Path, node_id: str, sources: dict) -> Path:
    """Retain a safely scoped source claim independently of artifact completeness."""
    data = entry["manifest"]
    expected = tuple(data.get(key) for key in ("session_id", "experiment_id", "storage_id"))
    if (manifest_path.parent.relative_to(root).parts != expected
            or data.get("acquisition_node_id") != node_id):
        raise ValueError("manifest_location_or_owner_mismatch")
    external = data["external_artifact_path"]
    source = data.get("local_storage_path") if external is None else external
    if not isinstance(source, str) or not source.strip():
        raise ValueError("invalid_scientific_source")
    original = _historical_path(Path(source), root)
    if external is None and original.parent != manifest_path.parent:
        raise ValueError("inconsistent_local_scientific_source")
    entry["original_path"] = str(original)
    sources.setdefault(("path", str(original)), []).append(entry)
    try:
        info = original.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("original_not_regular_file")
        entry["file_status"] = "present"
        if info.st_ino:
            sources.setdefault(("file", info.st_dev, info.st_ino), []).append(entry)
    except FileNotFoundError:
        entry["file_status"] = "missing"
        entry["issues"].append("missing_original")
    return original


def _read_historical_artifact(entry, root: Path, node_id: str, claims: dict, sources: dict) -> None:
    """Retain safe claims first; only a complete manifest/sidecar can confirm identity."""
    manifest_path = _historical_path(Path(entry["manifest_path"]), root)
    if not manifest_path.exists():
        raise ValueError("missing_manifest")
    data = _read_inventory_record(manifest_path)
    entry["manifest"] = data
    for field in ("artifact_manifest_id", "storage_id"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            claims.setdefault((field, value), []).append(entry)
    original = _register_historical_source(entry, manifest_path, root, node_id, sources)

    fields = ("artifact_manifest_id", "source_component_id", "artifact_type", "lifecycle_state",
              "local_storage_path")
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in fields):
        raise ValueError("invalid_manifest_identity")
    paths = data.get("local_managed_paths")
    if (not isinstance(paths, list) or not paths
            or any(not isinstance(p, str) or not p.strip() for p in paths)
            or not isinstance(data.get("details"), dict)):
        raise ValueError("invalid_manifest_structure")
    manifest = ArtifactManifest.from_dict(data)
    if manifest.lifecycle_state not in {"open", "finalized"}:
        raise ValueError("unknown_artifact_lifecycle_state")
    metadata_path = _historical_path(manifest_path.with_name("metadata.json"), root)
    managed = [_historical_path(Path(p), root) for p in manifest.local_managed_paths]
    if manifest_path not in managed or metadata_path not in managed or len(set(managed)) != len(managed):
        raise ValueError("inconsistent_managed_paths")
    if manifest.external_artifact_path is None and original not in managed:
        raise ValueError("inconsistent_local_scientific_source")
    metadata = _read_inventory_record(metadata_path)
    entry["metadata"] = metadata
    if any(metadata.get(key) != data[key] for key in (
            "session_id", "experiment_id", "acquisition_node_id", "source_component_id", "artifact_type")):
        raise ValueError("metadata_identity_mismatch")
    if (not isinstance(metadata.get("data_product_id"), str) or not metadata["data_product_id"].strip()
            or not isinstance(metadata.get("schema"), dict) or not isinstance(metadata.get("details"), dict)
            or metadata.get("storage_format") not in {"jsonl", "hdf5"}
            or any(data["details"].get(key) != value for key, value in metadata["details"].items())):
        raise ValueError("invalid_or_inconsistent_scientific_metadata")
    entry["identity_confirmed"] = True
    if manifest.lifecycle_state != "finalized":
        entry["issues"].append("not_finalized")


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

    @staticmethod
    def read_historical_artifacts(
        root_path: str | Path,
        acquisition_node_id: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Inspect persisted manifests without creating or attaching a Session owner.

        Identity confirmation cross-checks disk records, not scientific contents,
        durability, recording membership or eligibility for collection/deletion.
        Missing originals retain their recorded identity and explicit missing status.
        Paths are not relocated; aliases and sources outside this root are unresolved.
        The result is a point-in-time inventory, not an atomic filesystem snapshot.
        Each artifact includes partial manifest/metadata, identity_confirmed,
        original_path, file_status (present/missing/unconfirmed), issues and an
        unresolved recording_id. Top-level issues describe discovery failures.
        """
        if not isinstance(acquisition_node_id, str) or not acquisition_node_id.strip():
            raise ValueError("A configured acquisition_node_id is required")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()
                or session_id in {".", ".."} or any(c in session_id for c in "/\\\x00")):
            raise ValueError("session_id must be one nonempty path component")
        root = Path(root_path)
        report = {"acquisition_node_id": acquisition_node_id, "root_path": str(root),
                  "artifacts": [], "issues": [],
                  "recording_associations": "unresolved: manifests identify files, not logical recordings"}
        try:
            root = root.resolve()
            report["root_path"] = str(root)
            if not root.is_dir():
                raise ValueError("storage_root_unavailable")
        except (OSError, ValueError, RuntimeError) as error:
            report["issues"].append({"path": str(root), "reason": str(error)})
            return report
        administrative = {root / "local_storage_evidence.jsonl"}
        operation_directory = root / "deletion_operations"
        if operation_directory.is_dir() and not operation_directory.is_symlink() and not operation_directory.is_junction():
            administrative.update(operation_directory.iterdir())
        entries = report["artifacts"]
        claims: dict[tuple, list] = {}
        sources: dict[tuple, list] = {}

        def scan_error(error):
            report["issues"].append({"path": str(error.filename), "reason": str(error)})

        # Walk directories only to discover persisted records, never to infer
        # scientific membership from data filenames or directory contents.
        for directory, children, files in os.walk(root, followlinks=False, onerror=scan_error):
            location = Path(directory)
            for name in children[:]:
                child = location / name
                if child.is_symlink() or child.is_junction():
                    children.remove(name)
                    report["issues"].append({"path": str(child), "reason": "directory_alias_not_followed"})
            depth = len(location.relative_to(root).parts)
            if depth != 3 and not {"artifact_manifest.json", "metadata.json"}.intersection(files):
                continue
            entry = {"manifest_path": str(location / "artifact_manifest.json"),
                     "manifest": None, "metadata": None, "identity_confirmed": False,
                     "original_path": None, "file_status": "unconfirmed", "recording_id": None,
                     "issues": []}
            entries.append(entry)
            administrative.update((location / "artifact_manifest.json", location / "metadata.json"))
            try:
                _read_historical_artifact(entry, root, acquisition_node_id, claims, sources)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                entry["issues"].append(str(error))

        # Reconcile all claims before filtering: a conflicting historical record
        # outside the requested Session must not turn a duplicate into a unique ID.
        for key, owners in claims.items():
            if len(owners) > 1:
                for entry in owners:
                    entry["issues"].append(f"duplicate_{key[0]}")
                    entry["identity_confirmed"] = False
        admin_files = set()
        for path in administrative:
            try:
                info = path.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_ino:
                    admin_files.add((info.st_dev, info.st_ino))
            except OSError:
                pass
        for key, owners in sources.items():
            if len(owners) > 1 or (key[0] == "file" and key[1:] in admin_files):
                for entry in owners:
                    entry["issues"].append("aliased_original")
                    entry["identity_confirmed"] = False
        for entry in entries:
            if entry["original_path"] is not None and Path(entry["original_path"]) in administrative:
                entry["issues"].append("administrative_source")
                entry["identity_confirmed"] = False
            if not entry["identity_confirmed"]:
                entry["original_path"] = None
                entry["file_status"] = "unconfirmed"
        if session_id is not None:
            report["artifacts"] = [entry for entry in entries
                if Path(entry["manifest_path"]).relative_to(root).parts[0] == session_id]
        report["artifacts"].sort(key=lambda entry: entry["manifest_path"])
        return report

    @staticmethod
    def read_deletion_operations(root_path: str | Path, acquisition_node_id: str,
                                 *, session_id: str | None = None) -> dict[str, Any]:
        """Read durable outcomes; interrupted unlink is uncertainty, never automatic retry."""
        root = Path(root_path).resolve()
        directory = _historical_path(root / "deletion_operations", root)
        report = {"operations": [], "issues": [], "reconciliation": []}
        if not directory.exists():
            return report
        for path in sorted(directory.glob("*.json")):
            try:
                record = _read_deletion_record(root, acquisition_node_id, path)
                if session_id is None or record["request"]["session_id"] == session_id:
                    report["operations"].append(record)
                    for item in record["files"]:
                        if item["status"] == "pending":
                            original = _historical_path(Path(item["original_path"]), root)
                            report["reconciliation"].append({"operation_id": record["operation_id"],
                                "artifact_manifest_id": item["artifact_manifest"]["artifact_manifest_id"],
                                "status": "not_deleted" if original.is_file() else "missing_deletion_unconfirmed"})
            except (OSError, ValueError, KeyError, TypeError) as error:
                report["issues"].append({"path": str(path), "reason": str(error)})
        return report

    @staticmethod
    def delete_original_artifacts(root_path: str | Path, acquisition_node_id: str, *,
                                  operation_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Execute one admitted exact scope; the AcquisitionNode serializes local safety.

        Duplicate operation IDs only read outcomes. A new linked explicit request is
        required to retry remaining originals after failure, interruption or restart.
        """
        root = Path(root_path).resolve(strict=True)
        path = _deletion_record_path(root, operation_id)
        request = deepcopy(request)
        sid = request.get("session_id")
        experiments = request.get("experiment_ids")
        if (not isinstance(sid, str) or not sid or any(c in sid for c in "/\\\x00") or sid in {".", ".."}
                or (experiments is not None and (not isinstance(experiments, list) or not experiments
                    or any(not isinstance(e, str) or not e for e in experiments)
                    or len(set(experiments)) != len(experiments)))
                or request.get("confirmed") is not True or request.get("warning_acknowledged") is not True
                or type(request.get("administrator_mode")) is not bool
                or (not request["administrator_mode"] and (
                    not isinstance(request.get("experimenter_name"), str) or not request["experimenter_name"].strip()))
                or request.get("policy") not in {"manual", "after_collection"}):
            raise ValueError("Explicit deletion scope, operator, confirmation, warning and policy are required")
        if path.exists():
            record = _read_deletion_record(root, acquisition_node_id, path)
            if record["request"] != request:
                raise ValueError("Conflicting deletion operation identity")
            with path.open("r+b") as saved:
                os.fsync(saved.fileno())
            _sync_deletion_directories(path)
            if _read_deletion_record(root, acquisition_node_id, path) != record:
                raise RuntimeError("Deletion outcome changed during durability confirmation")
            return record
        history = LocalStorageManager.read_deletion_operations(root, acquisition_node_id)
        if history["issues"]:
            raise RuntimeError("Deletion operation history is damaged; outcomes are unconfirmed")
        prior_id = request.get("retry_of")
        prior = next((r for r in history["operations"] if r["operation_id"] == prior_id), None)
        if prior_id is not None and (prior is None or any(prior["request"].get(k) != request.get(k)
                for k in ("session_id", "experiment_ids"))):
            raise ValueError("Explicit retry must link the same original scope")
        inventory = LocalStorageManager.read_historical_artifacts(root, acquisition_node_id, session_id=sid)
        if inventory["issues"]:
            raise RuntimeError("Original discovery is incomplete")
        selected = [e for e in inventory["artifacts"] if experiments is None
                    or Path(e["manifest_path"]).relative_to(root).parts[1] in experiments]
        if (not selected or (experiments is not None and set(experiments) != {
                (e.get("manifest") or {}).get("experiment_id") for e in selected})
                or any(not e["identity_confirmed"] for e in selected)):
            raise RuntimeError("Exact original scope is incomplete, inconsistent or ambiguous")
        targets = []
        for entry in selected:
            manifest = entry["manifest"]
            item = {"artifact_manifest": manifest, "original_path": entry["original_path"],
                    "status": "pending", "error": None, "file_identity": None}
            prior_files = [f for r in history["operations"] for f in r["files"]
                           if f["artifact_manifest"]["artifact_manifest_id"] == manifest["artifact_manifest_id"]]
            if any(f["status"] == "deleted" for f in prior_files):
                if entry["file_status"] != "missing":
                    raise RuntimeError("A previously deleted original has reappeared")
                continue
            unresolved = [r for r in history["operations"] if any(
                f["artifact_manifest"]["artifact_manifest_id"] == manifest["artifact_manifest_id"]
                for f in r["files"])]
            if unresolved and (prior is None or prior not in unresolved):
                raise RuntimeError("Outstanding deletion requires a new linked explicit retry")
            if prior is not None and not any(f["artifact_manifest"] == manifest for f in prior["files"]):
                raise RuntimeError("Retry original targets changed; renewed exact selection is required")
            if entry["file_status"] == "present":
                info = Path(entry["original_path"]).stat()
                item["file_identity"] = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
                if prior is not None:
                    original_claim = next(f for f in prior["files"] if f["artifact_manifest"] == manifest)
                    if original_claim["file_identity"] != item["file_identity"]:
                        raise RuntimeError("Retry original file changed; its identity is unconfirmed")
            else:
                item["status"] = "missing_deletion_unconfirmed"
            targets.append(item)
        if request["policy"] == "after_collection":
            proof = request.get("collection_proof")
            if (not isinstance(proof, dict) or proof.get("session_id") != sid
                    or proof.get("archival_confirmed") is not True
                    or proof.get("verification_confirmed") is not True):
                raise ValueError("Post-collection deletion requires verified preservation")
            for item in targets:
                if proof.get("exact_originals", []).count(item["artifact_manifest"]) != 1:
                    raise ValueError("Collection proof does not cover each exact original")
        record = {"operation_id": operation_id, "acquisition_node_id": acquisition_node_id,
                  "request": request, "files": targets, "finished": False, "recorded_at": time(),
                  "admission": {"exact_originals_confirmed": True, "local_safety_confirmed": True}}
        _write_deletion_record(path, record, initial=True)
        for item in record["files"]:
            if item["status"] != "pending":
                continue
            try:
                original = _historical_path(Path(item["original_path"]), root)
                info = original.stat()
                if [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns] != item["file_identity"]:
                    raise RuntimeError("Original changed after admission")
                original.unlink()
                if os.name == "posix":
                    descriptor = os.open(original.parent, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                item["status"] = "deleted"
            except FileNotFoundError:
                item["status"] = "missing_deletion_unconfirmed"
            except OSError as error:
                item.update(status="failed", error=str(error))
            except RuntimeError as error:
                item.update(status="unconfirmed", error=str(error))
            _write_deletion_record(path, record)
        record["finished"] = True
        _write_deletion_record(path, record)
        return record

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

    def check_capacity(self, required_bytes: int) -> dict[str, Any]:
        """Preserve local writability readiness while checking the explicit byte budget."""
        readiness = self.check_ready()
        if not readiness.ready:
            return {"ready": False, "reason": readiness.reason, "destination": str(self.root_path)}
        return inspect_storage_capacity(self.root_path, required_bytes)

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
        storage_format: str = "jsonl",
    ) -> ArtifactManifest:
        """Create one stream, its stable metadata, and its manifest."""

        if acquisition_node_id != self._acquisition_node_id:
            raise ValueError("acquisition_node_id does not match LocalStorageManager")
        if session_id != self._session_id:
            raise ValueError("session_id does not match LocalStorageManager")
        if storage_format not in {"jsonl", "hdf5"}:
            raise ValueError("storage_format must be jsonl or hdf5")
        storage_id = uuid4().hex
        manifest_id = uuid4().hex
        stream_dir = self._root_path / session_id / experiment_id / storage_id
        rows_path = stream_dir / ("frames.h5" if storage_format == "hdf5" else "rows.jsonl")
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
            "storage_format": storage_format,
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
            external_artifact_path=None,
            local_managed_paths=(
                str(metadata_path),
                str(rows_path),
                str(manifest_path),
            ),
            details={**(details or {}), **({"storage_format": "hdf5"} if storage_format == "hdf5" else {})},
        )
        rows_file: IO[str] | None = None
        try:
            stream_dir.mkdir(parents=True, exist_ok=False)
            metadata_path.write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )
            rows_file = (
                self._create_hdf5_file(rows_path, metadata, manifest)
                if storage_format == "hdf5"
                else rows_path.open("a", encoding="utf-8")
            )
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
            if rows_file is not None:
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
        """Incrementally append timestamped JSONL rows or HDF5 frame rows."""

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
            if stream.write_failed:
                reason = f"{stream.metadata['storage_format'].upper()} stream has a recorded persistence failure"
                self._record_failure_evidence(
                    "write_failure", reason,
                    manifest=stream.manifest, details={"operation": "row_append"},
                )
                raise RuntimeError(reason)
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
                serialized_row = (
                    self._prepare_hdf5_row(stream, row)
                    if stream.metadata["storage_format"] == "hdf5"
                    else json.dumps(row)
                )
            except (TypeError, ValueError) as error:
                self._record_failure_evidence(
                    "write_failure",
                    str(error),
                    manifest=stream.manifest,
                    details={"operation": "row_serialization"},
                )
                raise

            if stream.metadata["storage_format"] == "hdf5":
                stream.buffered_rows.append(serialized_row)
                stream.row_count += 1
                if len(stream.buffered_rows) >= (self._max_buffered_rows or 1):
                    self.flush(storage_id)
                if self._flush_interval_elapsed(stream):
                    self.flush(storage_id)
                continue
            stream.row_count += 1
            if self._max_buffered_rows is None:
                self._write_serialized_row(stream, serialized_row)
            else:
                stream.buffered_rows.append(serialized_row)
                if len(stream.buffered_rows) >= self._max_buffered_rows:
                    self.flush(storage_id)
            if self._flush_interval_elapsed(stream):
                self.flush(storage_id)

    def flush(self, storage_id: str) -> None:
        """Flush current writes without finalizing the stream."""

        stream = self._require_stream(storage_id)
        if stream.rows_file is None:
            return
        try:
            if stream.write_failed:
                raise RuntimeError(f"{stream.metadata['storage_format'].upper()} stream has a recorded persistence failure")
            if stream.metadata["storage_format"] == "hdf5":
                self._flush_hdf5(stream)
                stream.last_flush_monotonic_s = monotonic()
                return
            while stream.buffered_rows:
                serialized_row = stream.buffered_rows[0]
                self._write_serialized_row(stream, serialized_row)
                del stream.buffered_rows[0]
            try:
                stream.rows_file.flush()
            except (OSError, ValueError) as error:
                # A failed file flush may have written an incomplete tail.
                stream.write_failed = True
                raise
            os.fsync(stream.rows_file.fileno())
            stream.durable_row_count = stream.written_row_count
            stream.last_flush_monotonic_s = monotonic()
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            if stream.metadata["storage_format"] == "hdf5":
                stream.write_failed = True
                stream.finalized = False
            self._record_failure_evidence(
                "write_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "flush", **self._jsonl_completion_details(stream)},
            )
            raise

    def finalize_stream(self, storage_id: str) -> ArtifactManifest:
        """Close one stream and finalize its immutable manifest."""

        stream = self._require_stream(storage_id)
        if stream.finalized:
            return stream.manifest
        try:
            self.flush(storage_id)
            if stream.write_failed:
                raise RuntimeError(f"{stream.metadata['storage_format'].upper()} stream has a recorded persistence failure")
            if stream.rows_file is not None:
                stream.rows_file.close()
                stream.rows_file = None
            finalized_manifest = replace(
                stream.manifest,
                lifecycle_state="finalized",
                details={
                    **{name: value for name, value in stream.manifest.details.items()
                       if name != "finalization_error"},
                    "row_count": stream.row_count,
                    **self._jsonl_completion_details(stream),
                    **self._hdf5_completion_details(stream),
                    "finalization_outcome": "finalized",
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
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            stream.finalized = False
            if stream.metadata["storage_format"] == "hdf5":
                stream.write_failed = True
            # Attempt closure even when flush failed; never claim finalization.
            if stream.write_failed and stream.rows_file is not None:
                try:
                    stream.rows_file.close()
                    stream.rows_file = None
                except Exception as close_error:
                    self._record_failure_evidence(
                        "finalization_failure", str(close_error),
                        manifest=stream.manifest, details={"operation": "close"},
                    )
            self._record_failure_evidence(
                "finalization_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "stream_finalization"},
            )
            stream.manifest = replace(
                stream.manifest, lifecycle_state="open", details={
                    **stream.manifest.details,
                    **self._jsonl_completion_details(stream),
                    **self._hdf5_completion_details(stream),
                    "finalization_error": str(error),
                    "finalization_outcome": "failed",
                },
            )
            try:
                self._write_manifest(stream.manifest)
            except (OSError, ValueError, TypeError) as manifest_error:
                self._record_failure_evidence(
                    "write_failure", str(manifest_error), manifest=stream.manifest,
                    details={"operation": "failure_manifest"},
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
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                if stream.metadata["storage_format"] == "hdf5" or stream.write_failed:
                    try:
                        stream.rows_file.close()
                        stream.rows_file = None
                    except Exception as close_error:
                        failures.append(f"{storage_id}: {close_error}")
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
                **self._jsonl_completion_details(stream),
                **self._hdf5_completion_details(stream),
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

    def _create_hdf5_file(
        self, path: Path, metadata: dict[str, Any], manifest: ArtifactManifest,
    ) -> Any:
        import h5py
        import numpy as np

        shape = tuple(metadata["schema"]["frame_shape"])
        if len(shape) not in {2, 3} or any(
            isinstance(size, bool) or not isinstance(size, int) or size < 1
            for size in shape
        ):
            raise ValueError("frame_shape must contain two or three positive dimensions")
        dtype = np.dtype(metadata["schema"]["frame_dtype"])
        if dtype.kind not in "biuf":
            raise ValueError("frame_dtype must be a supported numeric image dtype")
        artifact = h5py.File(path, "w")
        try:
            artifact.attrs["metadata_json"] = json.dumps(metadata)
            artifact.attrs["artifact_manifest_id"] = manifest.artifact_manifest_id
            artifact.attrs["persisted_frame_count"] = 0
            artifact.create_dataset(
                "frames", shape=(0, *shape), maxshape=(None, *shape),
                chunks=(1, *shape), dtype=dtype,
            )
            for name in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s"):
                artifact.create_dataset(name, shape=(0,), maxshape=(None,), dtype="f8")
            artifact.create_dataset("frame_index", shape=(0,), maxshape=(None,), dtype="i8")
            for name in ("timestamp_status", "record_metadata_json"):
                artifact.create_dataset(name, shape=(0,), maxshape=(None,), dtype=h5py.string_dtype("utf-8"))
            artifact.flush()
            return artifact
        except Exception:
            artifact.close()
            raise

    def _prepare_hdf5_row(self, stream: _OpenStream, row: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        frame = row.get("frame")
        if not isinstance(frame, np.ndarray):
            raise TypeError("HDF5 frame must be a NumPy array")
        if frame.shape != tuple(stream.metadata["schema"]["frame_shape"]):
            raise ValueError("frame shape does not match stream schema")
        if frame.dtype != np.dtype(stream.metadata["schema"]["frame_dtype"]):
            raise ValueError("frame dtype does not match stream schema")
        index = row.get("frame_index")
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)):
            raise ValueError("frame_index must be an integer")
        if not -(2**63) <= int(index) < 2**63:
            raise ValueError("frame_index is outside int64 range")
        for name in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s"):
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if not isinstance(row["timestamp_status"], str) or "\x00" in row["timestamp_status"]:
            raise ValueError("timestamp_status must be a string without null characters")
        record_metadata = {name: value for name, value in row.items() if name != "frame"}
        record_metadata["frame_index"] = int(index)
        metadata_json = json.dumps(record_metadata, allow_nan=False)
        return {**record_metadata, "frame": frame.copy(), "record_metadata_json": metadata_json}

    def _flush_hdf5(self, stream: _OpenStream) -> None:
        artifact = stream.rows_file
        start = stream.persisted_frame_count
        rows = stream.buffered_rows
        try:
            for dataset in artifact.values():
                dataset.resize(start + len(rows), axis=0)
            for offset, row in enumerate(rows, start):
                for name, dataset in artifact.items():
                    dataset[offset] = row["frame"] if name == "frames" else row[name]
            artifact.attrs["persisted_frame_count"] = start + len(rows)
            artifact.flush()
        except Exception:
            # Restore aligned dataset lengths to the last successful flush.
            for dataset in artifact.values():
                dataset.resize(start, axis=0)
            artifact.attrs["persisted_frame_count"] = start
            artifact.flush()
            raise
        for row in rows:
            if stream.persisted_frame_count == 0:
                stream.frame_bounds["first_frame_index"] = row["frame_index"]
                for name in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s"):
                    stream.frame_bounds[f"first_{name}"] = row[name]
            stream.frame_bounds["last_frame_index"] = row["frame_index"]
            for name in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s"):
                stream.frame_bounds[f"last_{name}"] = row[name]
            stream.persisted_frame_count += 1
        rows.clear()

    def _hdf5_completion_details(self, stream: _OpenStream) -> dict[str, Any]:
        if stream.metadata["storage_format"] != "hdf5":
            return {}
        bounds = stream.frame_bounds
        return {
            "accepted_frame_count": stream.row_count,
            "persisted_frame_count": stream.persisted_frame_count,
            "first_frame_index": bounds.get("first_frame_index"),
            "last_frame_index": bounds.get("last_frame_index"),
            "first_session_time_s": bounds.get("first_session_time_s"),
            "last_session_time_s": bounds.get("last_session_time_s"),
            "first_experiment_time_s": bounds.get("first_experiment_time_s"),
            "last_experiment_time_s": bounds.get("last_experiment_time_s"),
            "first_acquisition_node_local_time_s": bounds.get("first_acquisition_node_local_time_s"),
            "last_acquisition_node_local_time_s": bounds.get("last_acquisition_node_local_time_s"),
            "duration_s": (bounds["last_session_time_s"] - bounds["first_session_time_s"] if bounds else None),
            "finalization_outcome": "finalized" if stream.finalized else "failed" if stream.write_failed else "open",
        }

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
            text = serialized_row + "\n"
            if stream.rows_file.write(text) != len(text):
                raise OSError("Incomplete JSONL row write")
            stream.written_row_count += 1
        except (OSError, ValueError) as error:
            stream.write_failed = True
            self._record_failure_evidence(
                "write_failure",
                str(error),
                manifest=stream.manifest,
                details={"operation": "row_append", **self._jsonl_completion_details(stream)},
            )
            raise

    def _jsonl_completion_details(self, stream: _OpenStream) -> dict[str, Any]:
        if stream.metadata["storage_format"] != "jsonl":
            return {}
        return {
            "row_count": None if stream.write_failed else stream.written_row_count,
            "accepted_row_count": stream.row_count,
            "buffered_row_count": len(stream.buffered_rows),
            "written_row_count": stream.written_row_count,
            "durable_row_count": stream.durable_row_count,
            "write_status": "uncertain" if stream.write_failed else "complete_rows",
        }

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
