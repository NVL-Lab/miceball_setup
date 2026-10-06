import contextlib
import io
import json
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
    def run_smoke(self, root, frames, *, scientific=True, cv2=None):
        cv2 = cv2 or FakeCV2(frames)
        cv2.CAP_ANY = 0
        output, errors = io.StringIO(), io.StringIO()
        arguments = ["--output-dir", str(root)]
        if scientific:
            arguments += ["--scientific", "--duration", "1", "--width", "4", "--height", "2",
                          "--frame-dtype", "uint16", "--max-buffered-rows", "1"]
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


if __name__ == "__main__":
    unittest.main()
