"""Concrete OpenCV adapter for a Seeed IMX219 camera."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from lab_sync_acquisition.device_adapter import (
    DeviceAdapter,
    DeviceAdapterLifecycleError,
    DeviceAdapterState,
    DeviceReadiness,
    _PartialScientificCollectionError,
)


@dataclass(frozen=True)
class OpenCVCameraConfig:
    """Explicit OpenCV camera configuration for a concrete camera adapter."""

    camera_source: int | str
    api_preference: int
    frames_per_collect: int
    frame_width: int | None = None
    frame_height: int | None = None
    fps: float | None = None


class SeeedIMX219OpenCVCameraAdapter(DeviceAdapter):
    """OpenCV-backed adapter that emits lightweight frame metadata records."""

    def __init__(
        self,
        device_id: str,
        device_type: str,
        declared_capabilities: Iterable[str],
        required: bool,
        cv2_module: Any | None = None,
    ) -> None:
        super().__init__(
            device_id=device_id,
            device_type=device_type,
            declared_capabilities=declared_capabilities,
            required=required,
        )
        self._cv2 = cv2_module
        self._capture: Any | None = None
        self._camera_config: OpenCVCameraConfig | None = None
        self._frame_index = 0
        self._backend_name: str | None = None

    @property
    def frame_index(self) -> int:
        """Number of successful acquired frames across both collection paths."""

        return self._frame_index

    def initialize(self, config: OpenCVCameraConfig) -> None:
        """Open the OpenCV camera capture using explicit camera configuration."""

        if not isinstance(config, OpenCVCameraConfig):
            raise TypeError("SeeedIMX219OpenCVCameraAdapter requires OpenCVCameraConfig")
        if config.frames_per_collect < 1:
            raise ValueError("frames_per_collect must be at least 1")

        super().initialize(config=config)
        self._camera_config = config

        try:
            cv2 = self._cv2 if self._cv2 is not None else self._import_cv2()
            capture = cv2.VideoCapture(config.camera_source, config.api_preference)
            self._apply_requested_properties(cv2, capture, config)
            if not capture.isOpened():
                self._set_state(DeviceAdapterState.FAILED)
                raise DeviceAdapterLifecycleError("OpenCV camera capture did not open")
            self._capture = capture
            self._backend_name = self._read_backend_name(capture)
        except Exception:
            self._release_capture()
            if self.state is not DeviceAdapterState.FAILED:
                self._set_state(DeviceAdapterState.FAILED)
            raise

    def check_ready(self) -> DeviceReadiness:
        """Report ready only when the OpenCV capture is open."""

        self._require_state(DeviceAdapterState.INITIALIZED)
        if self._capture is None or not self._capture.isOpened():
            self._set_state(DeviceAdapterState.FAILED)
            return DeviceReadiness(
                device_id=self.device_id,
                required=self.required,
                ready=False,
                reason="opencv_capture_not_open",
                capabilities_available=self.declared_capabilities,
            )
        return self._mark_ready()

    def collect_records(self) -> dict[str, Any]:
        """Poll configured frame count and return metadata-only records."""

        return self._collect_camera_records(include_frames=False)["runtime_records"]

    def collect_scientific_records(self) -> dict[str, Any]:
        """Return local NumPy frames and separate metadata from the same reads."""

        return self._collect_camera_records(include_frames=True)

    def _collect_camera_records(self, *, include_frames: bool) -> dict[str, Any]:

        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("OpenCV camera records require a running adapter")
        if self._capture is None or self._camera_config is None:
            raise RuntimeError("OpenCV camera capture is not initialized")

        records = []
        scientific_records = []
        result = {
            "runtime_records": {
                "record_kind": "camera_frame_metadata",
                "records": records,
            },
            "scientific_records": (
                {"record_kind": "camera_frames", "records": scientific_records}
                if include_frames else None
            ),
        }
        try:
            for _ in range(self._camera_config.frames_per_collect):
                read_success, frame = self._capture.read()
                if not read_success:
                    records.append(
                        {"frame_index": self._frame_index, "read_success": False, "backend": self._backend_name}
                    )
                    continue

                metadata = self._metadata_from_frame(frame)
                metadata.update(
                    {"frame_index": self._frame_index, "read_success": True, "backend": self._backend_name}
                )
                records.append(metadata)
                if include_frames:
                    import numpy as np

                    if not isinstance(frame, np.ndarray):
                        raise TypeError("Scientific camera frames must be NumPy arrays")
                    scientific_records.append(
                        {**metadata, **self._available_camera_metadata(), "frame": frame}
                    )
                self._frame_index += 1
        except Exception as error:
            if include_frames:
                raise _PartialScientificCollectionError(error, result) from error
            raise
        result["runtime_records"]["records"] = tuple(records)
        if include_frames:
            result["scientific_records"]["records"] = tuple(scientific_records)
        return result

    def _available_camera_metadata(self) -> dict[str, Any]:
        metadata = {}
        if self._camera_config.fps is not None:
            metadata["configured_fps"] = self._camera_config.fps
        for name, property_name in (
            ("reported_fps", "CAP_PROP_FPS"),
            ("exposure", "CAP_PROP_EXPOSURE"),
            ("gain", "CAP_PROP_GAIN"),
        ):
            property_id = getattr(self._cv2, property_name, None)
            if property_id is None:
                continue
            try:
                value = self._capture.get(property_id)
                if value is not None and isfinite(value) and value != 0:
                    metadata[name] = value
            except Exception:
                # Optional backend properties may be unsupported.
                continue
        return metadata

    def stop(self) -> None:
        """Stop acquisition while keeping capture available for shutdown."""

        super().stop()

    def shutdown(self) -> None:
        """Release the OpenCV camera capture after acquisition stops."""

        super().shutdown()
        self._release_capture()

    def _apply_requested_properties(
        self,
        cv2: Any,
        capture: Any,
        config: OpenCVCameraConfig,
    ) -> None:
        if config.frame_width is not None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.frame_width)
        if config.frame_height is not None:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.frame_height)
        if config.fps is not None:
            capture.set(cv2.CAP_PROP_FPS, config.fps)

    def _metadata_from_frame(self, frame: Any) -> dict[str, Any]:
        shape = getattr(frame, "shape", ())
        height = int(shape[0]) if len(shape) >= 1 else None
        width = int(shape[1]) if len(shape) >= 2 else None
        channels = int(shape[2]) if len(shape) >= 3 else 1
        dtype = str(getattr(frame, "dtype", "unknown"))
        metadata = {
            "width": width,
            "height": height,
            "channels": channels,
            "dtype": dtype,
        }
        device_local_time = self._read_device_local_time()
        if device_local_time is not None:
            metadata["device_local_time"] = device_local_time
        return metadata

    def _read_device_local_time(self) -> float | None:
        if self._cv2 is None or self._capture is None:
            return None
        property_id = getattr(self._cv2, "CAP_PROP_POS_MSEC", None)
        if property_id is None:
            return None
        try:
            value = self._capture.get(property_id)
            if value in (None, 0):
                return None
            return float(value)
        except Exception:
            # Optional backend timing metadata may be unavailable.
            return None

    def _read_backend_name(self, capture: Any) -> str | None:
        get_backend_name = getattr(capture, "getBackendName", None)
        if get_backend_name is None:
            return None
        try:
            return str(get_backend_name())
        except Exception:
            return None

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _import_cv2(self) -> Any:
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError as error:
            raise DeviceAdapterLifecycleError(
                "OpenCV is required to use SeeedIMX219OpenCVCameraAdapter"
            ) from error
        self._cv2 = cv2
        return cv2
