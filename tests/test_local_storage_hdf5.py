import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import LocalStorageManager


class HDF5ScientificPersistenceTests(unittest.TestCase):
    def manager(self, directory, batch=2, interval=None):
        return LocalStorageManager(
            directory, "session", "node", max_buffered_rows=batch,
            max_flush_interval_s=interval,
        )

    def stream(self, manager, shape=(3, 4, 3), dtype="uint16"):
        return manager.create_stream(
            session_id="session", experiment_id="experiment",
            acquisition_node_id="node", source_component_id="camera",
            data_product_id="frames", artifact_type="camera_frames",
            schema={"frame_shape": list(shape), "frame_dtype": dtype},
            details={"backend": "synthetic", "fps": 30, "exposure": 4.5},
            storage_format="hdf5",
        )

    def row(self, index, shape=(3, 4, 3), dtype="uint16"):
        return {
            "frame": np.full(shape, index if dtype == "uint8" else index + 256, dtype=dtype),
            "frame_index": index, "experiment_id": "experiment",
            "session_time_s": 10.0 + index / 2,
            "experiment_time_s": index / 2,
            "acquisition_node_local_time_s": 100.0 + index / 2,
            "timestamp_status": "runtime_timestamped",
        }

    def test_multiple_batches_round_trip_pixels_dtype_timing_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manifest = self.stream(manager)
            rows = [self.row(i) for i in range(5)]
            rows[0]["device_local_time"] = 12.75
            manager.append_rows(manifest.storage_id, iter(rows[:3]))
            manager.append_rows(manifest.storage_id, iter(rows[3:]))
            summary = manager.finalize_all()
            with h5py.File(manifest.local_storage_path) as artifact:
                np.testing.assert_array_equal(artifact["frames"][:], np.stack([r["frame"] for r in rows]))
                self.assertEqual(artifact["frames"].dtype, np.dtype("uint16"))
                self.assertIsNone(artifact["frames"].compression)
                for key in ("frame_index", "session_time_s", "experiment_time_s", "acquisition_node_local_time_s"):
                    np.testing.assert_array_equal(artifact[key][:], [r[key] for r in rows])
                self.assertEqual(list(artifact["timestamp_status"].asstr()[:]), [r["timestamp_status"] for r in rows])
                metadata = [json.loads(v) for v in artifact["record_metadata_json"].asstr()[:]]
                self.assertEqual(metadata[0]["device_local_time"], 12.75)
                self.assertNotIn("device_local_time", metadata[1])
                self.assertEqual(json.loads(artifact.attrs["metadata_json"])["details"]["exposure"], 4.5)
                self.assertEqual(artifact.attrs["artifact_manifest_id"], manifest.artifact_manifest_id)
            details = summary.manifests[0].details
            self.assertEqual(details["persisted_frame_count"], 5)
            self.assertEqual(details["accepted_frame_count"], 5)
            self.assertEqual((details["first_frame_index"], details["last_frame_index"]), (0, 4))
            self.assertEqual(details["duration_s"], 2.0)
            self.assertEqual(details["finalization_outcome"], "finalized")
            self.assertEqual(summary.streams[0]["persisted_frame_count"], 5)

    def test_batch_one_explicit_flush_then_append(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=1)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            manager.flush(manifest.storage_id)
            self.assertEqual(manager.manifests[0].lifecycle_state, "open")
            manager.append_rows(manifest.storage_id, [self.row(1)])
            manager.finalize_all()
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact["frames"].shape, (2, 3, 4, 3))

    def test_buffered_frames_are_copied_and_partial_batch_finalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=20)
            manifest = self.stream(manager)
            row = self.row(0)
            expected = row["frame"].copy()
            manager.append_rows(manifest.storage_id, [row])
            row["frame"][:] = 0
            summary = manager.finalize_all()
            self.assertEqual(summary.streams[0]["persisted_frame_count"], 1)
            with h5py.File(manifest.local_storage_path) as artifact:
                np.testing.assert_array_equal(artifact["frames"][0], expected)

    def test_empty_stream_finalizes_with_manifest_and_zero_datasets(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manifest = self.stream(manager)
            self.assertTrue(Path(manifest.local_storage_path).exists())
            summary = manager.finalize_all()
            self.assertEqual(summary.stream_count, 1)
            self.assertEqual(summary.streams[0]["persisted_frame_count"], 0)
            self.assertIsNone(summary.streams[0]["first_frame_index"])
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact["frames"].shape, (0, 3, 4, 3))

    def test_append_checks_flush_interval_without_background_work(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("lab_sync_acquisition.local_storage.monotonic", return_value=0):
                manager = self.manager(directory, batch=20, interval=1)
                manifest = self.stream(manager)
            with patch("lab_sync_acquisition.local_storage.monotonic", return_value=2):
                manager.append_rows(manifest.storage_id, [self.row(0)])
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact.attrs["persisted_frame_count"], 1)
            manager.finalize_all()
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact.attrs["persisted_frame_count"], 1)

    def test_invalid_frame_is_rejected_with_evidence_and_prior_frames_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=1)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            for row in (self.row(1, shape=(2, 2)), self.row(1, dtype="uint8")):
                with self.assertRaises(ValueError):
                    manager.append_rows(manifest.storage_id, [row])
                self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            manager.finalize_all()
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(len(artifact["frames"]), 1)

    def test_partial_write_failure_restores_alignment_and_cannot_claim_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=1)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            original = h5py.Dataset.__setitem__

            def fail_timing(dataset, key, value):
                if dataset.name == "/session_time_s":
                    raise OSError("disk write failure")
                return original(dataset, key, value)

            with patch.object(h5py.Dataset, "__setitem__", fail_timing):
                with self.assertRaisesRegex(OSError, "disk write failure"):
                    manager.append_rows(manifest.storage_id, [self.row(1)])
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            with self.assertRaises(RuntimeError):
                manager.finalize_stream(manifest.storage_id)
            self.assertEqual(manager.evidence[-1].evidence_type, "finalization_failure")
            self.assertEqual(manager.manifests[0].details["persisted_frame_count"], 1)
            self.assertEqual(manager.manifests[0].details["accepted_frame_count"], 2)
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertTrue(all(len(dataset) == 1 for dataset in artifact.values()))

    def test_close_failure_records_failed_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            with patch.object(h5py.File, "close", side_effect=OSError("close failed")):
                with self.assertRaisesRegex(OSError, "close failed"):
                    manager.finalize_stream(manifest.storage_id)
            self.assertEqual(manager.manifests[0].details["finalization_outcome"], "failed")
            self.assertEqual(manager.manifests[0].lifecycle_state, "open")
            with self.assertRaises(RuntimeError):
                manager.cleanup()

    def test_grayscale_dtype_and_missing_timing_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manifest = self.stream(manager, shape=(3, 4), dtype="float32")
            row = self.row(0, shape=(3, 4), dtype="float32")
            invalid = dict(row)
            del invalid["experiment_time_s"]
            with self.assertRaises(ValueError):
                manager.append_rows(manifest.storage_id, [invalid])
            manager.append_rows(manifest.storage_id, [row])
            manager.finalize_all()
            with h5py.File(manifest.local_storage_path) as artifact:
                np.testing.assert_array_equal(artifact["frames"][0], row["frame"])

    def test_buffer_count_triggers_flush_and_finalization_persists_remainder(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=2)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact.attrs["persisted_frame_count"], 0)
            manager.append_rows(manifest.storage_id, [self.row(1), self.row(2)])
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(artifact.attrs["persisted_frame_count"], 2)
            summary = manager.finalize_all()
            self.assertEqual(summary.streams[0]["persisted_frame_count"], 3)

    def test_flush_failure_records_evidence_and_never_finalizes_successfully(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=20)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            with patch.object(h5py.File, "flush", side_effect=OSError("flush failed")):
                with self.assertRaisesRegex(OSError, "flush failed"):
                    manager.flush(manifest.storage_id)
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            with self.assertRaises(RuntimeError):
                manager.finalize_stream(manifest.storage_id)
            self.assertEqual(manager.manifests[0].details["persisted_frame_count"], 0)
            self.assertEqual(manager.manifests[0].details["finalization_outcome"], "failed")

    def test_cleanup_preserves_pending_frames_without_claiming_finalization(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory, batch=20)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            manager.cleanup()
            self.assertEqual(manager.evidence[-1].evidence_type, "cleanup_completed")
            self.assertEqual(manager.manifests[0].lifecycle_state, "open")
            with h5py.File(manifest.local_storage_path) as artifact:
                self.assertEqual(len(artifact["frames"]), 1)

    def test_finalization_evidence_failure_does_not_leave_successful_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            manifest = self.stream(manager)
            manager.append_rows(manifest.storage_id, [self.row(0)])
            with patch.object(Path, "open", side_effect=OSError("evidence write failed")):
                with self.assertRaisesRegex(OSError, "evidence write failed"):
                    manager.finalize_stream(manifest.storage_id)
            self.assertEqual(manager.manifests[0].lifecycle_state, "open")
            self.assertEqual(manager.manifests[0].details["finalization_outcome"], "failed")
            with self.assertRaises(RuntimeError):
                manager.finalize_stream(manifest.storage_id)


if __name__ == "__main__":
    unittest.main()
