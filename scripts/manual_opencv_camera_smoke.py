"""Run one bounded metadata-only acquisition against a real OpenCV camera."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceAdapterState,
    DeviceManager,
    InMemoryIngestor,
    InMemoryStorageManager,
    OpenCVCameraConfig,
    SeeedIMX219OpenCVCameraAdapter,
    SynchronizationManager,
)


def _camera_source(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll one bounded batch from a real OpenCV camera and print "
            "metadata-only acquisition records."
        )
    )
    parser.add_argument(
        "camera_source",
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
    args = parser.parse_args()

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
    storage = InMemoryStorageManager()
    ingestor = InMemoryIngestor(storage_manager=storage)
    acquisition_node = AcquisitionNode(
        session_id="manual-opencv-camera-smoke",
        device_manager=manager,
        synchronization_manager=SynchronizationManager(),
        ingestor=ingestor,
    )
    config = OpenCVCameraConfig(
        camera_source=args.camera_source,
        api_preference=api_preference,
        frames_per_collect=args.frames_per_collect,
        frame_width=args.width,
        frame_height=args.height,
        fps=args.fps,
    )

    try:
        initialization = manager.initialize_all(config=config)
        if not all(result.succeeded for result in initialization):
            raise RuntimeError(f"Camera initialization failed: {initialization}")

        readiness = acquisition_node.check_ready()
        if not readiness["ready"]:
            raise RuntimeError(f"Camera readiness failed: {readiness}")

        start_result = acquisition_node.start_acquisition()
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
        return 0
    finally:
        if adapter.state is DeviceAdapterState.RUNNING:
            acquisition_node.stop_acquisition()
        elif adapter.state is DeviceAdapterState.STOPPED:
            manager.shutdown_all()


if __name__ == "__main__":
    raise SystemExit(main())
