"""Run metadata smoke checks or opt-in scientific HDF5 camera validation."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    Controller,
    DeviceDeclaration,
    DeviceAdapterState,
    DeviceManager,
    InMemoryIngestor,
    InMemoryStorageManager,
    LocalStorageManager,
    OpenCVCameraConfig,
    SeeedIMX219OpenCVCameraAdapter,
    SynchronizationManager,
    PersistentStorageManager,
    ScientificOutputSelection,
    ScientificProductDeclaration,
    SessionConfig,
)


def _camera_source(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def verify_scientific_artifact(manifest, experiment_start_session_time_s: float,
                               frame_shape: tuple[int, ...], frame_dtype: str) -> dict:
    """Reopen a finalized camera artifact and validate aligned data and timing."""
    import h5py
    import numpy as np

    path = Path(manifest.local_storage_path)
    saved_manifest = json.loads((path.parent / "artifact_manifest.json").read_text())
    if saved_manifest != manifest.to_dict() or manifest.lifecycle_state != "finalized":
        raise ValueError("Artifact manifest is not consistently finalized")
    if manifest.details.get("finalization_outcome") != "finalized":
        raise ValueError("Artifact finalization failed")
    with h5py.File(path, "r") as artifact:
        required = ("frames", "frame_index", "session_time_s", "experiment_time_s",
                    "acquisition_node_local_time_s", "timestamp_status", "record_metadata_json")
        if any(name not in artifact for name in required):
            raise ValueError("Artifact is missing required datasets")
        frames = artifact["frames"]
        count = len(frames)
        if count == 0:
            raise ValueError("Empty acquisition: no scientific frames persisted")
        if any(len(artifact[name]) != count for name in required):
            raise ValueError("Artifact dataset lengths disagree")
        if (count != manifest.details["persisted_frame_count"]
                or count != manifest.details["accepted_frame_count"]
                or count != artifact.attrs["persisted_frame_count"]):
            raise ValueError("Artifact frame count disagrees with manifest")
        if frames.shape[1:] != frame_shape or frames.dtype != np.dtype(frame_dtype):
            raise ValueError("Artifact frame shape/dtype disagrees with declared product")
        if artifact.attrs["artifact_manifest_id"] != manifest.artifact_manifest_id:
            raise ValueError("Artifact identity disagrees with manifest")
        indices = artifact["frame_index"][:]
        if indices.dtype.kind not in "iu" or np.any(indices < 0) or np.any(np.diff(indices) <= 0):
            raise ValueError("Frame indices are invalid or unordered")
        times = {name: artifact[name][:] for name in required[2:5]}
        if any(not np.all(np.isfinite(values)) or np.any(np.diff(values) < 0)
               for values in times.values()):
            raise ValueError("Runtime timing is nonfinite or unordered")
        if not np.allclose(times["experiment_time_s"],
                           times["session_time_s"] - experiment_start_session_time_s,
                           rtol=0, atol=1e-9) or np.any(times["experiment_time_s"] < 0):
            raise ValueError("Session and Experiment Time disagree")
        for index in range(count):
            # Read one frame at a time, rather than loading the full acquisition.
            frames[index]
            row = json.loads(artifact["record_metadata_json"][index])
            if row["experiment_id"] != manifest.experiment_id or row["frame_index"] != indices[index]:
                raise ValueError("Frame metadata identity/index disagrees")
            status = artifact["timestamp_status"].asstr()[index]
            if status != "runtime_timestamped" or row["timestamp_status"] != status:
                raise ValueError("Frame timestamp status disagrees")
            if any(row[name] != values[index] for name, values in times.items()):
                raise ValueError("Frame metadata timing disagrees with datasets")
        return {"artifact_path": str(path), "experiment_id": manifest.experiment_id,
                "frame_count": count, "frame_shape": frame_shape, "frame_dtype": str(frames.dtype),
                "frame_indices": (int(indices[0]), int(indices[-1])),
                "session_time_range_s": (float(times["session_time_s"][0]), float(times["session_time_s"][-1])),
                "experiment_time_range_s": (float(times["experiment_time_s"][0]), float(times["experiment_time_s"][-1])),
                "manifest_status": manifest.lifecycle_state, "finalization": "finalized"}


def _require_success(result):
    if not result.succeeded:
        raise RuntimeError(f"{result.command} failed: {result.error}")
    return result


def _cleanup(node, manager, adapter):
    """Attempt each independent cleanup without replacing the primary error."""
    errors = []
    try:
        if node.status()["is_running"]:
            result = node.stop_runtime()
            for key in ("device_stop_results", "device_shutdown_results"):
                for item in result.get(key, ()):
                    if not item.succeeded:
                        errors.append(str(item))
        elif adapter.state in (DeviceAdapterState.READY, DeviceAdapterState.RUNNING,
                               DeviceAdapterState.STOPPED):
            # The adapter lifecycle permits shutdown only after start/stop.
            if adapter.state is DeviceAdapterState.READY:
                adapter.start()
            if adapter.state is DeviceAdapterState.RUNNING:
                adapter.stop()
            adapter.shutdown()
    except Exception as error:
        errors.append(str(error))
    if node.local_storage_manager is not None:
        try:
            node.local_storage_manager.cleanup()
        except Exception as error:
            errors.append(str(error))
    for error in errors:
        print(f"cleanup_error={error}", file=sys.stderr)
    return errors


def _run_scientific(args, adapter, manager, config) -> int:
    session_id = f"camera-smoke-{uuid4().hex}"
    root = args.output_dir.resolve() / session_id
    shape = (args.height or 480, args.width or 640)
    if args.channels != 1:
        shape += (args.channels,)
    product = ScientificProductDeclaration("frames", "camera_frames",
        {"frame_shape": list(shape), "frame_dtype": args.frame_dtype}, "hdf5")
    session_config = SessionConfig(
        [DeviceDeclaration(adapter.device_id, adapter.device_type, True, True,
                           ("camera_frame_metadata",), (product,))],
        str(root / "runtime.jsonl"), {}, args.error_evidence_location,
        session_id=session_id)
    storage = PersistentStorageManager(root / "runtime.jsonl")
    ingestor = InMemoryIngestor(storage)
    sync = SynchronizationManager()
    node = AcquisitionNode(session_id, manager, sync, ingestor, node_id="camera-node",
        error_evidence_location=args.error_evidence_location,
        default_local_storage_root=root / "scientific")
    controller = Controller(node, ingestor, storage, root / "session.json",
                            synchronization_manager=sync)
    primary_error = None
    interrupted = False
    report = None
    print(f"camera_device={args.camera_source}")
    print(f"output_directory={root}")
    try:
        initialization = manager.initialize_all(config)
        if not all(result.succeeded for result in initialization):
            raise RuntimeError(f"Camera initialization failed: {initialization}")
        node.attach_local_storage_manager(LocalStorageManager(
            root / "scientific", session_id, node.node_id,
            max_buffered_rows=args.max_buffered_rows), session_config.selected_devices)
        _require_success(controller.create_session(session_config))
        readiness = node.check_ready()
        _require_success(controller.initialize_session(readiness["device_readiness"],
                                                        readiness["service_readiness"]))
        _require_success(controller.start_session())
        experiment_id = "camera-validation"
        start = _require_success(controller.start_experiment(experiment_id,
            scientific_outputs=(ScientificOutputSelection(adapter.device_id, node.node_id, "frames"),)))
        origin = start.details["session_time_s"]
        deadline = monotonic() + args.duration
        while monotonic() < deadline:
            _require_success(controller.run_one_iteration())
        _require_success(controller.stop_experiment(experiment_id))
        _require_success(controller.stop_session())
        _require_success(controller.finalize_session())
        manifest, = node.local_storage_manager.manifests
        report = verify_scientific_artifact(manifest, origin, shape, args.frame_dtype)
    except (Exception, KeyboardInterrupt) as error:
        primary_error = error
        interrupted = isinstance(error, KeyboardInterrupt)
        print(f"acquisition_or_verification_error={type(error).__name__}: {error}", file=sys.stderr)
    finally:
        cleanup_errors = _cleanup(node, manager, adapter)
        if node.local_storage_manager is not None:
            for manifest in node.local_storage_manager.manifests:
                print(f"preserved_artifact={manifest.local_storage_path}")
    if primary_error is not None or cleanup_errors:
        print("validation=FAIL")
        return 130 if interrupted else 1
    for key, value in report.items():
        print(f"{key}={value}")
    print("validation=PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll one metadata batch, or acquire and verify scientific HDF5 frames."
        )
    )
    parser.add_argument(
        "--error-evidence-location",
        default=None,
        help="Failure evidence directory (default: <output-dir>/errors).",
    )
    parser.add_argument(
        "camera_source",
        nargs="?",
        default=0,
        type=_camera_source,
        help="OpenCV camera index or source string.",
    )
    parser.add_argument(
        "--api-preference",
        type=int,
        default=None,
        help="OpenCV video capture API preference integer (default: cv2.CAP_ANY).",
    )
    parser.add_argument("--frames-per-collect", type=int, default=1)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--scientific", action="store_true", help="Acquire and verify scientific HDF5 frames.")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--output-dir", type=Path, default=Path("camera_smoke_output"))
    parser.add_argument("--channels", type=int, choices=(1, 3, 4), default=3)
    parser.add_argument("--frame-dtype", default="uint8")
    parser.add_argument("--max-buffered-rows", type=int, default=20)
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration must be finite and positive")
    if any(value is not None and value <= 0 for value in
           (args.width, args.height, args.frames_per_collect, args.max_buffered_rows)):
        parser.error("dimensions, collection size and buffer size must be positive")
    args.error_evidence_location = args.error_evidence_location or str(args.output_dir / "errors")
    if args.scientific:
        args.width = args.width or 640
        args.height = args.height or 480

    try:
        import cv2
    except ImportError as error:
        parser.error(f"OpenCV is required for this manual smoke check: {error}")

    api_preference = (
        args.api_preference
        if args.api_preference is not None
        else int(cv2.CAP_ANY)
    )
    adapter = SeeedIMX219OpenCVCameraAdapter(
        device_id="manual-opencv-camera",
        device_type="seeed_imx219_camera",
        declared_capabilities=("camera_frame_metadata",),
        required=True,
        cv2_module=cv2,
    )
    manager = DeviceManager(adapters=(adapter,))
    config = OpenCVCameraConfig(
        camera_source=args.camera_source,
        api_preference=api_preference,
        frames_per_collect=args.frames_per_collect,
        frame_width=args.width,
        frame_height=args.height,
        fps=args.fps,
    )
    if args.scientific:
        return _run_scientific(args, adapter, manager, config)

    storage = InMemoryStorageManager()
    ingestor = InMemoryIngestor(storage_manager=storage)
    acquisition_node = AcquisitionNode(
        session_id="manual-opencv-camera-smoke",
        device_manager=manager,
        synchronization_manager=SynchronizationManager(),
        ingestor=ingestor,
        error_evidence_location=args.error_evidence_location,
    )
    exit_code = 0
    try:
        initialization = manager.initialize_all(config=config)
        if not all(result.succeeded for result in initialization):
            raise RuntimeError(f"Camera initialization failed: {initialization}")

        readiness = acquisition_node.check_ready()
        if not readiness["ready"]:
            raise RuntimeError(f"Camera readiness failed: {readiness}")

        start_result = acquisition_node.start_runtime()
        if not all(
            result.succeeded for result in start_result["device_start_results"]
        ):
            raise RuntimeError(
                f"Camera start failed: {start_result['device_start_results']}"
            )
        summary = acquisition_node.run_one_iteration()
        camera_envelopes = tuple(
            envelope
            for envelope in storage.stored_envelopes
            if envelope.record_kind == "camera_frame_metadata"
        )
        for envelope in camera_envelopes:
            for record in envelope.records:
                print(record)
        print(f"metadata_records={sum(len(item.records) for item in camera_envelopes)}")
        print(f"iteration={summary.iteration_index}")
    except (Exception, KeyboardInterrupt) as error:
        print(f"acquisition_error={type(error).__name__}: {error}", file=sys.stderr)
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        cleanup_errors = _cleanup(acquisition_node, manager, adapter)
    return exit_code or (1 if cleanup_errors else 0)


if __name__ == "__main__":
    raise SystemExit(main())
