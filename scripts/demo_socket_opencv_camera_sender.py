"""Send OpenCV camera adapter metadata envelopes to a localhost receiver."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    AcquisitionRecordEnvelope,
    DeviceAdapterState,
    DeviceManager,
    OpenCVCameraConfig,
    SeeedIMX219OpenCVCameraAdapter,
    ServiceReadiness,
    SynchronizationManager,
)


class FakeFrame:
    """Tiny fake frame object with only metadata used by the adapter."""

    def __init__(self, shape: tuple[int, ...], dtype: str) -> None:
        self.shape = shape
        self.dtype = dtype


class FakeVideoCapture:
    """Small local fake for OpenCV VideoCapture used by the demo sender."""

    def __init__(self, source: int | str, api_preference: int, frames: list[FakeFrame]):
        self.source = source
        self.api_preference = api_preference
        self._frames = list(frames)
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def set(self, _property_id: int, _value: Any) -> bool:
        return True

    def read(self) -> tuple[bool, FakeFrame | None]:
        if not self._frames:
            return False, None
        return True, self._frames.pop(0)

    def get(self, property_id: int) -> float:
        if property_id == FakeCV2.CAP_PROP_POS_MSEC:
            return 123.456
        return 0.0

    def getBackendName(self) -> str:
        return "FAKE_OPENCV"

    def release(self) -> None:
        self._opened = False


class FakeCV2:
    """Minimal fake cv2 module for local socket validation."""

    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    CAP_V4L2 = 200

    def __init__(self) -> None:
        self._frames = [
            FakeFrame(shape=(480, 640, 3), dtype="uint8"),
            FakeFrame(shape=(480, 640, 3), dtype="uint8"),
        ]

    def VideoCapture(
        self,
        source: int | str,
        api_preference: int,
    ) -> FakeVideoCapture:
        return FakeVideoCapture(source, api_preference, self._frames)


@dataclass(frozen=True)
class SocketSendResult:
    """Minimal result returned to AcquisitionNode after a socket send."""

    accepted: bool
    reason: str


class SocketEnvelopeBoundary:
    """Script-local Ingestor-like boundary that sends envelopes over a socket."""

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self._envelopes_sent = 0
        self._camera_metadata_records_sent = 0

    @property
    def envelopes_sent(self) -> int:
        return self._envelopes_sent

    @property
    def camera_metadata_records_sent(self) -> int:
        return self._camera_metadata_records_sent

    def check_ready(self) -> ServiceReadiness:
        return ServiceReadiness(
            component_id="socket_envelope_boundary",
            component_type="demo_socket_sender",
            required=True,
            ready=True,
            reason="ready",
        )

    def receive_envelope(
        self,
        envelope: AcquisitionRecordEnvelope,
    ) -> SocketSendResult:
        self._writer.write(json.dumps(envelope.to_dict()))
        self._writer.write("\n")
        self._writer.flush()
        self._envelopes_sent += 1
        if envelope.record_kind == "camera_frame_metadata":
            self._camera_metadata_records_sent += len(envelope.records)
        return SocketSendResult(accepted=True, reason="sent")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run an OpenCV camera adapter through AcquisitionNode and send "
            "metadata-only envelopes over localhost."
        )
    )
    parser.add_argument("host", help="Receiver host, for example 127.0.0.1.")
    parser.add_argument("port", type=int, help="Receiver TCP port.")
    parser.add_argument(
        "--real-cv2",
        action="store_true",
        help="Use installed cv2 and a real VideoCapture instead of FakeCV2.",
    )
    parser.add_argument(
        "--camera-source",
        type=_camera_source,
        default=0,
        help="OpenCV camera index or source string (default: 0).",
    )
    parser.add_argument(
        "--api-preference",
        type=int,
        default=None,
        help=(
            "OpenCV capture API integer (default: FakeCV2.CAP_V4L2 in fake "
            "mode, cv2.CAP_ANY in real mode)."
        ),
    )
    parser.add_argument("--frames-per-collect", type=int, default=2)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args()

    if args.real_cv2:
        try:
            import cv2
        except ImportError as error:
            parser.error(f"OpenCV is required with --real-cv2: {error}")
        cv2_module = cv2
        default_api_preference = int(cv2.CAP_ANY)
    else:
        cv2_module = FakeCV2()
        default_api_preference = FakeCV2.CAP_V4L2

    api_preference = (
        args.api_preference
        if args.api_preference is not None
        else default_api_preference
    )

    with socket.create_connection((args.host, args.port), timeout=5) as client_socket:
        writer = client_socket.makefile("w", encoding="utf-8", newline="\n")
        socket_boundary = SocketEnvelopeBoundary(writer=writer)
        adapter = SeeedIMX219OpenCVCameraAdapter(
            device_id="seeed-imx219-001",
            device_type="seeed_imx219_camera",
            declared_capabilities=["camera_frame_metadata"],
            required=True,
            cv2_module=cv2_module,
        )
        manager = DeviceManager(adapters=[adapter])
        synchronization = SynchronizationManager()
        acquisition_node = AcquisitionNode(
            session_id="demo-opencv-camera-session-001",
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=socket_boundary,
        )
        camera_config = OpenCVCameraConfig(
            camera_source=args.camera_source,
            api_preference=api_preference,
            frames_per_collect=args.frames_per_collect,
            frame_width=args.width,
            frame_height=args.height,
            fps=args.fps,
        )

        try:
            manager.initialize_all(config=camera_config)
            readiness = acquisition_node.check_ready()
            if not readiness["ready"]:
                raise RuntimeError("OpenCV camera demo sender was not ready")

            acquisition_node.start_acquisition()
            acquisition_node.run_one_iteration()
            acquisition_node.stop_acquisition()
        finally:
            if acquisition_node.status()["is_running"]:
                try:
                    acquisition_node.stop_acquisition()
                except Exception:
                    pass

            if synchronization.is_running:
                synchronization.stop()
            if adapter.state is DeviceAdapterState.READY:
                manager.start_all()
            if adapter.state is DeviceAdapterState.RUNNING:
                manager.stop_all()
            if adapter.state is DeviceAdapterState.STOPPED:
                manager.shutdown_all()
            writer.close()

    print(f"target={args.host}:{args.port}")
    print(f"envelopes_sent={socket_boundary.envelopes_sent}")
    print(
        "camera_metadata_records_sent="
        f"{socket_boundary.camera_metadata_records_sent}"
    )
    return 0


def _camera_source(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


if __name__ == "__main__":
    raise SystemExit(main())
