import contextlib
import io
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import ArtifactManifest
from scripts import manual_opencv_camera_smoke as smoke
from tests.test_scientific_camera_collection import FakeCV2


class ManualOpenCVCameraSmokeTests(unittest.TestCase):
    def run_smoke(self, root, frames, *, scientific=True, cv2=None, extra_args=()):
        cv2 = cv2 or FakeCV2(frames)
        cv2.CAP_ANY = 0
        output, errors = io.StringIO(), io.StringIO()
        arguments = ["--output-dir", str(root)]
        if scientific:
            arguments += ["--scientific", "--duration", "1", "--width", "4", "--height", "2",
                          "--frame-dtype", "uint16", "--max-buffered-rows", "1"]
        arguments.extend(extra_args)
        with patch.dict("sys.modules", {"cv2": cv2}), \
                patch.object(smoke, "monotonic", side_effect=[0, 0, 0.5, 1]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = smoke.main(arguments)
        return result, output.getvalue(), errors.getvalue(), cv2.capture

    def frames(self):
        return [np.arange(24, dtype=np.uint16).reshape(2, 4, 3),
                np.full((2, 4, 3), 65000, dtype=np.uint16)]

    def manifest(self, root):
        path, = Path(root).rglob("artifact_manifest.json")
        return ArtifactManifest.from_dict(json.loads(path.read_text()))

    def test_default_metadata_smoke_remains_one_iteration_without_images(self):
        with tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, self.frames(), scientific=False)
            self.assertEqual(result, 0, errors)
            self.assertIn("metadata_records=1", output)
            self.assertIn("iteration=1", output)
            self.assertEqual(capture.read_count, 1)
            self.assertTrue(capture.released)
            self.assertEqual(list(Path(root).rglob("*.h5")), [])

    def test_scientific_workflow_finalizes_reopens_and_preserves_frames_without_native_time(self):
        with tempfile.TemporaryDirectory() as root:
            frames = self.frames()
            result, output, errors, capture = self.run_smoke(root, frames)
            self.assertEqual(result, 0, errors)
            self.assertIn("validation=PASS", output)
            self.assertIn("frame_count=2", output)
            self.assertTrue(capture.released)
            manifest = self.manifest(root)
            self.assertEqual(manifest.lifecycle_state, "finalized")
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack(frames))
                np.testing.assert_array_equal(artifact["frame_index"][:], [0, 1])
                for metadata in artifact["record_metadata_json"]:
                    self.assertNotIn("device_local_time", json.loads(metadata))
            self.assertEqual(len(list(Path(root).rglob("session_record_final.json"))), 1)
            runtime, = Path(root).rglob("runtime.jsonl")
            self.assertNotIn('"frame":', runtime.read_text())

    def test_verification_rejects_missing_and_inconsistent_datasets(self):
        for corruption in ("missing", "count", "timing", "metadata", "indices"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as root:
                result, output, errors, _ = self.run_smoke(root, self.frames())
                self.assertEqual(result, 0, errors)
                manifest = self.manifest(root)
                with h5py.File(manifest.local_storage_path, "r+") as artifact:
                    origin = float(artifact["session_time_s"][0] - artifact["experiment_time_s"][0])
                    if corruption == "missing":
                        del artifact["timestamp_status"]
                    elif corruption == "count":
                        artifact.attrs["persisted_frame_count"] = 99
                    elif corruption == "timing":
                        artifact["experiment_time_s"][0] = 100
                    elif corruption == "metadata":
                        artifact["record_metadata_json"][0] = "not-json"
                    else:
                        artifact["frame_index"][1] = artifact["frame_index"][0]
                with self.assertRaises((ValueError, KeyError)):
                    smoke.verify_scientific_artifact(manifest, origin, (2, 4, 3), "uint16")

    def test_empty_acquisition_is_failure_and_camera_is_closed(self):
        with tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, [])
            self.assertNotEqual(result, 0)
            self.assertIn("validation=FAIL", output)
            self.assertIn("Empty acquisition", errors)
            self.assertTrue(capture.released)
            self.assertEqual(self.manifest(root).lifecycle_state, "finalized")

    def test_read_failure_preserves_partial_artifact_and_original_error(self):
        cv2 = FakeCV2([])
        with patch.object(cv2.capture, "read", side_effect=[(True, self.frames()[0]), OSError("camera unplugged")]), \
                tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, [], cv2=cv2)
            self.assertEqual(result, 1)
            self.assertIn("camera unplugged", errors)
            self.assertIn("preserved_artifact=", output)
            self.assertTrue(capture.released)
            with h5py.File(self.manifest(root).local_storage_path, "r") as artifact:
                self.assertEqual(len(artifact["frames"]), 1)

    def test_interruption_closes_camera_and_reports_failure(self):
        cv2 = FakeCV2([])
        with patch.object(cv2.capture, "read", side_effect=KeyboardInterrupt), \
                tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, [], cv2=cv2)
            self.assertEqual(result, 130)
            self.assertIn("KeyboardInterrupt", errors)
            self.assertIn("validation=FAIL", output)
            self.assertTrue(capture.released)

    def test_initialization_failure_reports_original_error(self):
        cv2 = FakeCV2([])
        with patch.object(cv2, "VideoCapture", side_effect=OSError("camera unavailable")), \
                tempfile.TemporaryDirectory() as root:
            result, output, errors, _ = self.run_smoke(root, [], cv2=cv2)
            self.assertEqual(result, 1)
            self.assertIn("camera unavailable", errors)
            self.assertIn("validation=FAIL", output)

    def test_cleanup_failure_does_not_hide_acquisition_failure(self):
        cv2 = FakeCV2([])
        with patch.object(cv2.capture, "read", side_effect=OSError("read broke")), \
                patch.object(smoke.LocalStorageManager, "cleanup", side_effect=OSError("cleanup broke")), \
                tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, [], cv2=cv2)
            self.assertEqual(result, 1)
            self.assertIn("read broke", errors)
            self.assertIn("cleanup_error=cleanup broke", errors)
            self.assertIn("validation=FAIL", output)
            self.assertTrue(capture.released)

    def test_declared_shape_mismatch_fails_without_losing_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            result, output, errors, capture = self.run_smoke(root, [np.zeros((3, 4, 3), dtype=np.uint16)])
            self.assertEqual(result, 1)
            self.assertIn("validation=FAIL", output)
            self.assertIn("shape", errors)
            self.assertIn("preserved_artifact=", output)
            self.assertTrue(capture.released)

    def test_matplotlib_is_not_required_for_acquisition_without_visualization(self):
        with patch.dict("sys.modules", {"matplotlib": None}), tempfile.TemporaryDirectory() as root:
            result, output, errors, _ = self.run_smoke(root, self.frames())
            self.assertEqual(result, 0, errors)
            self.assertIn("validation=PASS", output)


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "optional Matplotlib not installed")
class CameraFrameInspectionTests(unittest.TestCase):
    def setUp(self):
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        self.plt = plt

    def recording(self, root, frames):
        path = Path(root) / "frames.h5"
        with h5py.File(path, "w") as artifact:
            artifact.create_dataset("frames", data=frames)
            artifact.create_dataset("frame_index", data=np.arange(len(frames)) * 2 + 50)
        return path

    def test_headless_view_selects_six_frames_converts_bgr_and_leaves_hdf5_unchanged(self):
        from matplotlib.axes import Axes
        frames = np.zeros((11, 2, 3, 3), dtype=np.uint8)
        frames[..., 0], frames[..., 1], frames[..., 2] = 10, 20, 200
        images, labels, reads = [], [], []
        original_getitem = h5py.Dataset.__getitem__
        original_imshow = Axes.imshow
        original_title = Axes.set_title

        def read(dataset, key, *args, **kwargs):
            if dataset.name == "/frames":
                reads.append(key)
            return original_getitem(dataset, key, *args, **kwargs)

        def imshow(axis, data, *args, **kwargs):
            images.append(np.array(data))
            return original_imshow(axis, data, *args, **kwargs)

        def title(axis, label, *args, **kwargs):
            if label.startswith("Frame "):
                labels.append(label)
            return original_title(axis, label, *args, **kwargs)

        with tempfile.TemporaryDirectory() as root:
            path = self.recording(root, frames)
            original_bytes = path.read_bytes()
            output = io.StringIO()
            with patch.object(h5py.Dataset, "__getitem__", read), \
                    patch.object(Axes, "imshow", imshow), patch.object(Axes, "set_title", title), \
                    contextlib.redirect_stdout(output):
                contact_sheet = smoke.view_hdf5_frames(path)
            self.assertEqual(reads, [0, 2, 4, 6, 8, 10])
            self.assertEqual(labels, [f"Frame {index}" for index in (50, 54, 58, 62, 66, 70)])
            for image in images:
                np.testing.assert_array_equal(image[0, 0], [200, 20, 10])
            self.assertEqual(contact_sheet, path.with_name("frames_contact_sheet.png"))
            self.assertTrue(contact_sheet.read_bytes().startswith(b"\x89PNG"))
            self.assertIn(str(contact_sheet), output.getvalue())
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_view_existing_recording_needs_neither_opencv_nor_session(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.recording(root, np.zeros((2, 2, 3), dtype=np.uint16))
            with patch.dict("sys.modules", {"cv2": None}), \
                    patch.object(smoke, "Controller", side_effect=AssertionError("Session must not start")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.main(["--view-hdf5", str(path)]), 0)
            self.assertTrue(path.with_name("frames_contact_sheet.png").is_file())

    def test_grayscale_single_channel_and_wide_color_are_supported(self):
        for shape in ((2, 3), (2, 3, 1), (2, 3, 3), (2, 3, 4)):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as root:
                frames = np.full((1, *shape), 65535, dtype=np.uint16)
                path = self.recording(root, frames)
                with contextlib.redirect_stdout(io.StringIO()):
                    sheet = smoke.view_hdf5_frames(path)
                self.assertTrue(sheet.is_file())

    def test_empty_or_missing_frame_recording_returns_failure(self):
        for count in (0, 1):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as root:
                path = self.recording(root, np.zeros((count, 2, 3), dtype=np.uint8))
                if count:
                    with h5py.File(path, "r+") as artifact:
                        del artifact["frame_index"]
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(smoke.main(["--view-hdf5", str(path)]), 1)

    def test_missing_optional_matplotlib_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.recording(root, np.zeros((1, 2, 3), dtype=np.uint8))
            errors = io.StringIO()
            with patch.dict("sys.modules", {"matplotlib": None}), contextlib.redirect_stderr(errors):
                self.assertEqual(smoke.main(["--view-hdf5", str(path)]), 1)
            self.assertIn("pip install matplotlib", errors.getvalue())

    def test_show_frames_runs_after_scientific_validation_and_camera_cleanup(self):
        fixture = ManualOpenCVCameraSmokeTests()
        cv2 = FakeCV2(fixture.frames())
        original_view = smoke.view_hdf5_frames
        inspected = []

        def view(path):
            self.assertTrue(cv2.capture.released)
            with h5py.File(path, "r") as artifact:
                self.assertEqual(len(artifact["frames"]), 2)
            inspected.append(path)
            return original_view(path)

        with tempfile.TemporaryDirectory() as root, patch.object(smoke, "view_hdf5_frames", side_effect=view):
            result, output, errors, _ = fixture.run_smoke(root, [], cv2=cv2, extra_args=["--show-frames"])
            self.assertEqual(result, 0, errors)
            self.assertEqual(len(inspected), 1)
            self.assertLess(output.index("validation=PASS"), output.index("contact_sheet="))

    def test_graphical_backend_displays_frames_and_falls_back_on_display_failure(self):
        import matplotlib
        # Initialize Agg before simulating the public graphical-backend behavior.
        figure = self.plt.figure()
        self.plt.close(figure)
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                path = self.recording(root, np.zeros((1, 2, 3), dtype=np.uint8))
                with patch.object(matplotlib, "get_backend", return_value="TkAgg"), \
                        patch.object(self.plt, "show", side_effect=RuntimeError("no display") if failure else None) as show, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    sheet = smoke.view_hdf5_frames(path)
                show.assert_called_once()
                self.assertEqual(sheet is not None, failure)


if __name__ == "__main__":
    unittest.main()
