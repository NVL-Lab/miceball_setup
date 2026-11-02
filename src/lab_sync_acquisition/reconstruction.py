"""Read-only scientific timing reconstruction from preserved Session products."""

from collections import Counter
from copy import deepcopy
from math import inf, isfinite, nextafter, ulp
from pathlib import Path
import stat

from lab_sync_acquisition.communication import MAPPING_UPDATE_EVIDENCE_TYPE
from lab_sync_acquisition.local_storage import LocalStorageManager
from lab_sync_acquisition.synchronization import (
    MappingUpdateEvidence, SynchronizationConfiguration, SynchronizationMapping,
    project_clock_interval, clock_exchange_interval,
)


def _number(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def _object(value, label):
    """Require an actual decoded object, without normalizing arrays into dictionaries."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _quality(value, session_id, node_id):
    """Validate the nested assessment consumed by both owners and node snapshots."""
    quality = _object(value, "Synchronization assessment")
    if quality.get("session_id") != session_id or quality.get("acquisition_node_id") != node_id:
        raise ValueError("Assessment scope mismatch")
    if type(quality.get("assessment_sequence")) is not int or quality["assessment_sequence"] < 1:
        raise ValueError("Invalid assessment sequence")
    configuration = _object(quality["configuration"], "Synchronization configuration")
    if any(not _number(v) for k, v in configuration.items() if k not in {"quality_interpretation", "exchanges"}):
        raise ValueError("Invalid numeric synchronization configuration")
    SynchronizationConfiguration.from_dict(configuration)
    if any(type(quality.get(k)) is not bool for k in ("measurement_valid", "acceptable")):
        raise ValueError("Explicit measurement validity and quality are required")
    if quality.get("mapping") is not None:
        _mapping(quality["mapping"], session_id, node_id)
        if (any(not _number(quality.get(k)) for k in
                ("measured_local_time_s", "uncertainty_s", "valid_until_local_time_s"))
                or quality["uncertainty_s"] < 0):
            raise ValueError("Invalid preserved quality bounds")
    if "estimator" in quality:
        estimator = _object(quality["estimator"], "Estimator")
        if (type(estimator.get("refinement_accepted")) is not bool
                or not isinstance(estimator.get("disposition"), str)
                or not _number(estimator.get("scale")) or estimator["scale"] <= 0):
            raise ValueError("Malformed estimator fields")
        bounds = estimator.get("rate_bounds")
        if (not isinstance(bounds, list) or len(bounds) != 2 or not all(_number(v) for v in bounds)
                or not 0 < bounds[0] <= bounds[1]):
            raise ValueError("Malformed estimator rate bounds")
    elif quality["measurement_valid"]:
        raise ValueError("Valid measurement lacks estimator evidence")
    return quality


def _mapping(value, session_id, node_id):
    _object(value, "Synchronization mapping")
    mapping = SynchronizationMapping.from_dict(value)
    if (mapping.session_id != session_id or mapping.acquisition_node_id != node_id
            or not all(_number(v) for v in (mapping.local_time_anchor_s, mapping.session_time_anchor_s,
                                           mapping.scale, mapping.created_session_time_s)) or mapping.scale <= 0):
        raise ValueError("Conflicting or malformed runtime mapping")
    return mapping.to_dict()


def _mapped(mapping, local):
    return mapping["session_time_anchor_s"] + mapping["scale"] * (local - mapping["local_time_anchor_s"])


def _measurement(quality):
    """Recover a conservative measured interval, not an estimator-confidence bound."""
    config = SynchronizationConfiguration.from_dict(quality["configuration"])
    samples = quality["exchanges"]
    if not isinstance(samples, list) or len(samples) != config.exchanges:
        raise ValueError("Incomplete bounded cross-clock measurement")
    ends = None
    intervals = []
    session_resolution = quality.get("session_clock_resolution_s", 0.)
    if not _number(session_resolution) or session_resolution < 0:
        raise ValueError("Invalid preserved Session clock resolution")
    for sample in samples:
        _object(sample, "Clock exchange")
        s0, n1, n2, s3 = [sample[k] for k in ("sent_session_time_s", "received_local_time_s",
                                             "sent_local_time_s", "received_session_time_s")]
        resolution = sample["local_clock_resolution_s"]
        rate_min = config.initial_scale - config.clock_rate_error_bound
        intervals.append(clock_exchange_interval((s0, n1, n2, s3), resolution, session_resolution,
                                                rate_min, config.initial_scale + config.clock_rate_error_bound))
        if ends is not None and (s0 < ends[0] or n1 < ends[1]):
            raise ValueError("Invalid cross-clock measurement boundaries")
        ends = s3, n2
    anchor = n1 + (n2 - n1) / 2
    uncertainty = quality["uncertainty_s"]
    if (quality["measured_local_time_s"] != anchor or not _number(uncertainty) or uncertainty < 0):
        raise ValueError("Measurement anchor or uncertainty is inconsistent")
    center = _mapped(quality["mapping"], anchor)
    raw = [project_clock_interval(anchor, mid, lo, hi, rate_min,
                                   config.initial_scale + config.clock_rate_error_bound)
           for mid, lo, hi in intervals]
    lo, hi = max(p[0] for p in raw), min(p[1] for p in raw)
    if not all(_number(v) for v in (center, lo, hi, center - uncertainty, center + uncertainty)):
        raise ValueError("Measurement bounds are nonfinite")
    tolerance = sum(ulp(float(v)) for v in (center, uncertainty, lo, hi))
    if lo > hi and "session_clock_resolution_s" not in quality:
        raise ValueError("Legacy measurement lacks Session clock resolution needed to verify quantization")
    if lo > hi or center - uncertainty > lo + tolerance or center + uncertainty < hi - tolerance:
        raise ValueError("Preserved uncertainty contradicts the original clock exchanges")
    # The preserved applied-mapping bound already includes clock quantization and
    # causal exchange delay. Never substitute the offline machine's clock precision.
    return {"anchor": anchor, "lower": center - uncertainty, "upper": center + uncertainty,
            "rate_min": config.initial_scale - config.clock_rate_error_bound,
            "rate_max": config.initial_scale + config.clock_rate_error_bound,
            "start_local": samples[0]["received_local_time_s"], "end_local": n2,
            "start_session": samples[0]["sent_session_time_s"], "end_session": s3}


def _project_measurement(bound, local):
    """Apply the shared rate-envelope calculation with outward offline roundoff bounds."""
    lo, hi = project_clock_interval(local, bound["anchor"], bound["lower"], bound["upper"],
                                    bound["rate_min"], bound["rate_max"])
    if not all(_number(v) for v in (lo, hi)):
        raise ValueError("Projected clock bounds are nonfinite")
    error = ((ulp(float(local)) + ulp(float(bound["anchor"]))) * bound["rate_max"]
             + sum(ulp(float(v)) for v in (lo, hi, bound["lower"], bound["upper"])))
    return nextafter(lo - error, -inf), nextafter(hi + error, inf)


class ReconstructionManager:
    """Compute offline timing; StorageManager remains the persistence owner.

    local_storage_roots optionally identifies accessible original node stores.
    Otherwise only destinations in confirmed archived collection outcomes are read.
    No devices, reservations, live clocks or service owners are created.
    """

    def __init__(self, storage_manager, *, local_storage_roots=None):
        self._storage = storage_manager
        self._local_roots = {node: Path(root) for node, root in (local_storage_roots or {}).items()}

    def reconstruct_session(self, session_id: str, *, version: str) -> dict:
        """Reconstruct and preserve an explicit version, reporting unavailable inputs."""
        # Validate identities before attempting readback or creating any output.
        if version is None:
            raise ValueError("An explicit reconstruction version is required")
        self._storage._timing_reconstruction_path(session_id, version)
        result = {"format": "offline_timing_v1", "algorithm": "bounded_clock_envelopes_v1",
                  "session_id": session_id, "version": version, "archive_sha256": {},
                  "input_evidence_ids": [], "artifacts": [], "issues": []}
        try:
            inputs = self._storage.read_timing_reconstruction_inputs(session_id)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            result["issues"].append(f"Preserved Session inputs are unconfirmed: {error}")
        else:
            result["archive_sha256"] = inputs["archive_sha256"]
            if inputs["compilation_summary"].get("stage_a_complete") is not True:
                result["issues"].append("Acquisition evidence preservation is partial: "
                    + str(inputs["compilation_summary"].get("kill_preservation")))
            evidence = inputs["runtime_evidence"]
            result["input_evidence_ids"] = [m["evidence_id"] for m in evidence]
            contexts = self._timing_contexts(session_id, evidence, result["issues"])
            inventories = {node: LocalStorageManager.read_historical_artifacts(root, node, session_id=session_id)
                           for node, root in self._local_roots.items()}
            for node, inventory in inventories.items():
                result["issues"].extend(f"{node}: inventory discovery: {item}" for item in inventory["issues"])
            for entry in inputs["artifact_collection_handoff"]["artifacts"]:
                manifest = entry["artifact_manifest"]
                artifact = {"manifest": deepcopy(manifest), "observations": [], "issues": []}
                result["artifacts"].append(artifact)
                if entry["missing_finalization_evidence"]:
                    artifact["issues"].append("Artifact finalization is unconfirmed")
                if (type(manifest["details"].get("row_count")) is not int
                        or manifest["details"]["row_count"] < 0
                        or manifest["details"].get("write_status") == "uncertain"
                        or manifest["details"].get("finalization_outcome", "finalized") != "finalized"):
                    artifact["issues"].append("Original observation completeness is unconfirmed")
                try:
                    path, metadata = self._artifact_source(manifest, inputs["collection_evidence"], inventories)
                    artifact["read_path"] = str(path)
                    rows = self._read_observations(path, manifest, metadata)
                    context = contexts.get(manifest["acquisition_node_id"])
                    for position, row in rows:
                        artifact["observations"].append(self._reconstruct_observation(
                            manifest, position, row, context))
                    original = [r["original_timing"] for r in artifact["observations"]]
                    for previous, current in zip(original, original[1:]):
                        if current["acquisition_node_local_time_s"] < previous["acquisition_node_local_time_s"]:
                            artifact["issues"].append("Nonchronological original observation times")
                        if "frame_index" in current and "frame_index" in previous:
                            if current["frame_index"] != previous["frame_index"] + 1:
                                artifact["issues"].append("Noncontinuous original frame indices")
                    count = manifest["details"].get("row_count")
                    if count is not None and count != len(artifact["observations"]):
                        raise ValueError("Observation count contradicts finalized manifest")
                except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as error:
                    artifact["issues"].append(str(error))
                    # Partial parsing cannot certify the complete artifact.
                    for row in artifact["observations"]:
                        row["reconstructed"] = None
                        row["quality"] = "unavailable"
                        row["issues"].append("Artifact readback is incomplete or inconsistent")
        rows = [row for artifact in result["artifacts"] for row in artifact["observations"]]
        counts = Counter(row["quality"] for row in rows)
        result["quality"] = {"observation_count": len(rows), "by_status": dict(counts),
            "reconstructed_count": sum(row["reconstructed"] is not None for row in rows),
            "complete": bool(rows) and not result["issues"]
                and not any(a["issues"] for a in result["artifacts"])
                and all(row["quality"] == "refined" for row in rows)}
        self._storage.write_timing_reconstruction(result)
        return result

    def _timing_contexts(self, session_id, evidence, issues):
        """Join preserved owner assessments, mapping updates and node applications."""
        contexts = {}
        for message in evidence:
            payload = message["payload"]
            node = payload.get("acquisition_node_id")
            if message["evidence_type"] not in {MAPPING_UPDATE_EVIDENCE_TYPE, "mapping_activation",
                                                "timing_quality_observation"}:
                continue
            if not isinstance(node, str) or not node:
                issues.append("Timing evidence has no valid AcquisitionNode identity")
                continue
            context = contexts.setdefault(node, {"mappings": [], "assessments": {}, "activations": [],
                                                 "applications": [], "segments": [], "issues": []})
            try:
                if message["session_id"] != session_id or payload.get("session_id") != session_id:
                    raise ValueError("Timing evidence Session mismatch")
                kind = message["evidence_type"]
                if kind == MAPPING_UPDATE_EVIDENCE_TYPE:
                    _object(payload["details"], "Mapping-update details")
                    if not isinstance(payload["update_type"], str):
                        raise ValueError("Mapping-update type must be a string")
                    update = MappingUpdateEvidence.from_dict(payload)
                    if update.previous_mapping is not None:
                        _mapping(update.previous_mapping.to_dict(), session_id, node)
                    if update.new_mapping is not None:
                        mapping = _mapping(update.new_mapping.to_dict(), session_id, node)
                        context["mappings"].append((mapping, message))
                elif kind == "mapping_activation":
                    if message["source_id"] != node or not _number(payload["activated_local_time_s"]):
                        raise ValueError("Mapping activation owner or boundary mismatch")
                    _mapping(payload["mapping"], session_id, node)
                    context["activations"].append(message)
                elif "quality" in payload:
                    if message["source_id"] != node or not _number(payload["applied_local_time_s"]):
                        raise ValueError("Quality application owner or boundary mismatch")
                    context["applications"].append(message)
                else:
                    _quality(payload, session_id, node)
                    sequence = payload["assessment_sequence"]
                    if type(sequence) is not int or sequence < 1 or sequence in context["assessments"]:
                        raise ValueError("Duplicate or conflicting assessment sequence")
                    context["assessments"][sequence] = message
            except (KeyError, TypeError, ValueError) as error:
                context["issues"].append(str(error))
        for node, context in contexts.items():
            try:
                owners = {m["source_id"] for _, m in context["mappings"]}
                owners.update(m["source_id"] for m in context["assessments"].values())
                if len(owners) != 1:
                    raise ValueError("Synchronization evidence authority is missing or conflicting")
                for name, boundary in (("activations", "activated_local_time_s"),
                                       ("applications", "applied_local_time_s")):
                    context[name].sort(key=lambda m: m["payload"][boundary])
                    boundaries = [m["payload"][boundary] for m in context[name]]
                    if len(set(boundaries)) != len(boundaries):
                        raise ValueError("Ambiguous node-local application boundaries")
                    sequences = []
                    for message in context[name]:
                        payload = message["payload"]
                        quality = _quality(payload["measurement" if name == "activations" else "quality"], session_id, node)
                        owner = context["assessments"].get(quality["assessment_sequence"])
                        if owner is None or owner["payload"] != quality:
                            raise ValueError("Applied quality lacks exact owner evidence")
                        if name == "activations" and payload["mapping"] != quality["mapping"]:
                            raise ValueError("Activation mapping contradicts its measurement")
                        sequences.append(quality["assessment_sequence"])
                    if any(b <= a for a, b in zip(sequences, sequences[1:])):
                        raise ValueError("Stale or conflicting applied assessment ordering")
                previous = None
                segment = None
                configuration = None
                for sequence, message in sorted(context["assessments"].items()):
                    quality = message["payload"]
                    mapping = quality.get("mapping")
                    if mapping is not None and not any(mapping == m for m, _ in context["mappings"]):
                        raise ValueError("Assessment mapping lacks preserved mapping-update evidence")
                    if configuration is not None and configuration != quality["configuration"]:
                        raise ValueError("Conflicting synchronization configuration")
                    configuration = quality["configuration"]
                    if quality.get("measurement_valid") is not True:
                        issues.append(f"{node}: unavailable measurement {message['evidence_id']}")
                        continue
                    if mapping is None:
                        issues.append(f"{node}: measurement has no authorized mapping {message['evidence_id']}")
                        continue
                    bound = _measurement(quality)
                    if quality.get("estimator", {}).get("refinement_accepted") is not True:
                        issues.append(f"{node}: rejected refinement {message['evidence_id']}")
                        continue
                    if previous and (bound["start_local"] < previous["end_local"]
                                     or bound["start_session"] < previous["end_session"]
                                     or bound["anchor"] <= previous["anchor"]):
                        raise ValueError("Overlapping or stale accepted measurements")
                    if segment is None or quality["estimator"].get("disposition") == "sustained_change":
                        segment = []
                        context["segments"].append(segment)
                    bound["evidence_id"] = message["evidence_id"]
                    segment.append(bound)
                    previous = bound
            except (KeyError, TypeError, ValueError) as error:
                context["issues"].append(str(error))
            issues.extend(f"{node}: {issue}" for issue in context["issues"])
        return contexts

    def _artifact_source(self, manifest, evidence, inventories):
        """Choose only an exact inventoried original or an archived collection destination."""
        if manifest.get("external_artifact_path") is not None:
            raise ValueError("Unsupported external artifact or unresolved observation/index association")
        node = manifest["acquisition_node_id"]
        if node in inventories:
            matches = [a for a in inventories[node]["artifacts"]
                       if (a.get("manifest") or {}).get("artifact_manifest_id") == manifest["artifact_manifest_id"]]
            if (len(matches) != 1 or not matches[0]["identity_confirmed"]
                    or matches[0]["manifest"] != manifest):
                raise ValueError("Original artifact inventory is missing, ambiguous or inconsistent")
            entry = matches[0]
            if entry["file_status"] != "present":
                raise ValueError("Original scientific file is missing or unconfirmed")
            path, metadata = Path(entry["original_path"]), entry["metadata"]
            root = self._local_roots[node]
        else:
            outcomes = [r for message in evidence if message["evidence_type"] == "global_artifact_collection_evidence"
                        for r in message["payload"]["artifact_results"]
                        if r["artifact_manifest_id"] == manifest["artifact_manifest_id"]
                        and r["collection_status"] == "success"
                        and r["verification_status"] in {"verified", "copied_unverified"}]
            destinations = {r.get("global_artifact_locator") for r in outcomes}
            if len(destinations) != 1 or None in destinations or self._storage._global_artifact_root is None:
                raise ValueError("No unique preserved collection destination; supply accessible original node storage")
            path, metadata = Path(destinations.pop()), None
            root = self._storage._global_artifact_root
            relative = path.absolute().relative_to(root.absolute())
            scope = (manifest["session_id"], manifest["experiment_id"], node, manifest["artifact_manifest_id"])
            if len(relative.parts) != 5 or relative.parts[:4] != scope:
                raise ValueError("Collected scientific file scope contradicts its manifest")
            sizes = {r.get("file_size_copied") for r in outcomes}
            if None not in sizes and sizes != {path.stat().st_size}:
                raise ValueError("Collected file size contradicts its archived outcome")
        path, root = path.absolute(), root.absolute()
        if not path.is_relative_to(root):
            raise ValueError("Scientific source escapes its configured storage root")
        for parent in reversed((path, *path.parents)):
            info = parent.lstat()
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError("Aliased scientific source")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Scientific source is not an exclusively identified regular file")
        return path, metadata

    def _read_observations(self, path, manifest, metadata):
        """Read timing and row metadata only; never load HDF5 image pixels."""
        before = path.stat()
        storage_format = metadata["storage_format"] if metadata else manifest["details"].get("storage_format", "jsonl")
        if storage_format == "hdf5":
            import h5py

            with h5py.File(path, "r") as source:
                embedded = _object(self._storage._read_preservation_json(source.attrs["metadata_json"]), "HDF5 metadata")
                if (source.attrs["artifact_manifest_id"] != manifest["artifact_manifest_id"]
                        or any(embedded[k] != manifest[k] for k in (
                            "session_id", "experiment_id", "acquisition_node_id", "source_component_id", "artifact_type"))):
                    raise ValueError("HDF5 identity contradicts its manifest")
                names = ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "frame_index",
                         "timestamp_status", "record_metadata_json")
                if any(not isinstance(source[name], h5py.Dataset) for name in ("frames", *names)):
                    raise ValueError("HDF5 scientific/timing objects must be datasets")
                if source["frames"].ndim < 1:
                    raise ValueError("HDF5 frames require an observation dimension")
                if (any(source[name].dtype.kind not in "iuf" for name in names[:4])
                        or any(h5py.check_string_dtype(source[name].dtype) is None for name in names[4:])):
                    raise ValueError("HDF5 timing/metadata dataset types are invalid")
                count = len(source["frames"])
                if (source.attrs["persisted_frame_count"] != count
                        or any(source[name].shape != (count,) for name in names)):
                    raise ValueError("HDF5 timing datasets are incomplete or misaligned")
                for index in range(count):
                    row = _checked_observation(self._storage._read_preservation_json(source["record_metadata_json"].asstr()[index]))
                    for name in names[:-1]:
                        value = source[name].asstr()[index] if name == "timestamp_status" else source[name][index].item()
                        if row.get(name) != value:
                            raise ValueError("HDF5 timing and row metadata disagree")
                    yield {"dataset": "frames", "index": index}, row
        elif storage_format == "jsonl":
            with path.open(encoding="utf-8") as source:
                for index, line in enumerate(source):
                    if not line.endswith("\n"):
                        raise ValueError("Incomplete JSONL observation")
                    row = self._storage._read_preservation_json(line.encode())
                    yield {"line": index + 1}, _checked_observation(row)
        else:
            raise ValueError("Unsupported scientific storage format")
        after = path.stat()
        if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
            raise ValueError("Scientific source changed during reconstruction")

    def _reconstruct_observation(self, manifest, position, row, context):
        result = {"position": position, "original_timing": {k: deepcopy(v) for k, v in row.items()
                    if k in {"session_time_s", "experiment_time_s", "acquisition_node_local_time_s",
                             "timestamp_status", "frame_index", "device_local_time"}},
                  "runtime": None, "reconstructed": None, "quality": "unavailable", "issues": [],
                  "provenance": {k: manifest[k] for k in ("session_id", "experiment_id", "acquisition_node_id",
                                                         "source_component_id", "artifact_manifest_id", "storage_id")}}
        try:
            if context is None or context["issues"]:
                raise ValueError("Timing context is missing or conflicting")
            for name in ("session_id", "experiment_id", "acquisition_node_id", "source_component_id"):
                if name in row and row[name] != manifest[name]:
                    raise ValueError("Observation identity conflicts with artifact")
            local = row["acquisition_node_local_time_s"]
            activation = next((m for m in reversed(context["activations"])
                               if m["payload"]["activated_local_time_s"] <= local), None)
            application = next((m for m in reversed(context["applications"])
                                if m["payload"]["applied_local_time_s"] <= local), None)
            if activation is None or application is None:
                raise ValueError("No applicable preserved mapping/quality activation")
            mapping, quality = activation["payload"]["mapping"], application["payload"]["quality"]
            if quality["mapping"] != mapping or _mapped(mapping, local) != row["session_time_s"]:
                raise ValueError("Runtime timing conflicts with its applicable authorized mapping")
            updates = [m for value, m in context["mappings"] if value == mapping]
            if len(updates) != 1:
                raise ValueError("Runtime mapping update identity is ambiguous")
            owner = context["assessments"][quality["assessment_sequence"]]
            result["provenance"].update(runtime_mapping=deepcopy(mapping),
                mapping_update_evidence_id=updates[0]["evidence_id"],
                mapping_activation_evidence_id=activation["evidence_id"],
                quality_application_evidence_id=application["evidence_id"],
                quality_assessment_evidence_id=owner["evidence_id"])
            degraded = (quality.get("acceptable") is not True or quality.get("measurement_valid") is not True
                        or local > quality["valid_until_local_time_s"]
                        or row.get("timestamp_status") != "runtime_timestamped")
            result["runtime"] = {"session_time_s": row["session_time_s"], "uncertainty_s": None,
                                 "quality": "degraded" if degraded else "acceptable"}
            if quality.get("measurement_valid") is True:
                bound = _measurement(quality)
                lo, hi = _project_measurement(bound, local)
                result["runtime"]["uncertainty_s"] = nextafter(max(abs(row["session_time_s"] - lo),
                                                                            abs(hi - row["session_time_s"])), inf)
            segment = next((s for s in context["segments"] if s[0]["anchor"] <= local <= s[-1]["anchor"]), None)
            if segment is None:
                raise ValueError("No bracketed offline measurements for this observation")
            bounds = [_project_measurement(b, local) for b in segment]
            lo, hi = max(b[0] for b in bounds), min(b[1] for b in bounds)
            if not _number(lo) or not _number(hi) or lo > hi:
                raise ValueError("Offline measurement constraints conflict")
            center = lo + (hi - lo) / 2
            uncertainty = nextafter(max(center - lo, hi - center) + ulp(center), inf)
            result["reconstructed"] = {"session_time_s": center, "uncertainty_s": uncertainty,
                                       "lower_session_time_s": nextafter(lo, -inf),
                                       "upper_session_time_s": nextafter(hi, inf)}
            result["provenance"]["refinement_evidence_ids"] = [b["evidence_id"] for b in segment]
            result["quality"] = "refined_runtime_degraded" if degraded else "refined"
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            result["issues"].append(str(error))
        return result


def _checked_observation(row):
    """Reject unreadable timing without inspecting scientific payload suitability."""
    _object(row, "Scientific observation")
    if not isinstance(row.get("timestamp_status"), str):
        raise ValueError("Original timestamp status must be a string")
    if not all(_number(row.get(k)) for k in (
            "session_time_s", "experiment_time_s", "acquisition_node_local_time_s")):
        raise ValueError("Original observation timing is missing or nonfinite")
    for name in ("device_local_time", "frame_index"):
        if name in row and not _number(row[name]):
            raise ValueError("Original native timing/index cannot be represented")
    return row
