import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import LocalStorageManager


class PartialWriteFile:
    def __init__(self, file, fail_on_write=1):
        self.file = file
        self.fail_on_write = fail_on_write
        self.write_count = 0

    def write(self, text):
        self.write_count += 1
        if self.write_count == self.fail_on_write:
            self.file.write(text[:len(text) // 2])
            self.file.flush()
            raise OSError("partial JSONL write failed")
        return self.file.write(text)

    def __getattr__(self, name):
        return getattr(self.file, name)


class LocalStorageAccountingTests(unittest.TestCase):
    def stream(self, directory, batch=2):
        manager = LocalStorageManager(directory, "session", "node", max_buffered_rows=batch)
        manifest = manager.create_stream(
            session_id="session", experiment_id="experiment", acquisition_node_id="node",
            source_component_id="sensor", data_product_id="events", artifact_type="events", schema={},
        )
        return manager, manifest

    def row(self, value):
        return dict(session_time_s=1.0, experiment_time_s=0.0, acquisition_node_local_time_s=100.0,
                    timestamp_status="runtime_timestamped", experiment_id="experiment", value=value)

    def test_failed_fsync_does_not_undercount_or_claim_durability(self):
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            manager, manifest = self.stream(directory)
            stack.callback(manager.cleanup)
            manager.append_rows(manifest.storage_id, (self.row(1),))
            with patch("lab_sync_acquisition.local_storage.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaisesRegex(OSError, "fsync failed"):
                    manager.append_rows(manifest.storage_id, (self.row(2),))
            failure = manager.evidence[-1]
            self.assertEqual(failure.evidence_type, "write_failure")
            self.assertEqual(failure.details["written_row_count"], 2)
            self.assertEqual(failure.details["durable_row_count"], 0)
            self.assertEqual(failure.details["accepted_row_count"], 2)
            manager.flush(manifest.storage_id)
            manager.flush(manifest.storage_id)
            summary = manager.finalize_all()
            rows = [json.loads(line) for line in Path(manifest.local_storage_path).read_text().splitlines()]
            self.assertEqual([row["value"] for row in rows], [1, 2])
            final = manager.manifests[0]
            saved = json.loads(Path(final.local_managed_paths[2]).read_text())
            self.assertEqual(saved["details"], final.details)
            for details in (final.details, summary.streams[0]):
                self.assertEqual(details["row_count"], len(rows))
                self.assertEqual(details["written_row_count"], 2)
                self.assertEqual(details["durable_row_count"], 2)
                self.assertEqual(details["buffered_row_count"], 0)
            self.assertTrue(summary.finalized)

    def test_failed_finalization_fsync_can_be_explicitly_completed_without_duplicate_rows(self):
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            manager, manifest = self.stream(directory, batch=20)
            stack.callback(manager.cleanup)
            manager.append_rows(manifest.storage_id, (self.row(i) for i in range(3)))
            with patch("lab_sync_acquisition.local_storage.os.fsync", side_effect=OSError("final fsync failed")):
                with self.assertRaisesRegex(OSError, "final fsync failed"):
                    manager.finalize_stream(manifest.storage_id)
            failed, = manager.manifests
            self.assertEqual(failed.lifecycle_state, "open")
            self.assertEqual(failed.details["written_row_count"], 3)
            self.assertEqual(failed.details["durable_row_count"], 0)
            self.assertEqual(failed.details["finalization_outcome"], "failed")
            summary = manager.finalize_all()
            self.assertEqual(summary.manifests[0].details["finalization_outcome"], "finalized")
            self.assertNotIn("finalization_error", summary.manifests[0].details)
            self.assertEqual(summary.streams[0]["durable_row_count"], 3)
            self.assertEqual(len(Path(manifest.local_storage_path).read_text().splitlines()), 3)

    def test_partial_write_preserves_artifact_and_rejects_replay_of_uncertain_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            original_open = Path.open
            def open_file(path, *args, **kwargs):
                file = original_open(path, *args, **kwargs)
                return PartialWriteFile(file) if path.name == "rows.jsonl" and args and args[0] == "a" else file
            with patch.object(Path, "open", open_file):
                manager, manifest = self.stream(directory, batch=1)
            with self.assertRaisesRegex(OSError, "partial JSONL write failed"):
                manager.append_rows(manifest.storage_id, (self.row(1),))
            partial = Path(manifest.local_storage_path).read_bytes()
            self.assertTrue(partial)
            with self.assertRaises(RuntimeError):
                manager.flush(manifest.storage_id)
            with self.assertRaises(RuntimeError):
                manager.append_rows(manifest.storage_id, (self.row(2),))
            with self.assertRaises(RuntimeError):
                manager.finalize_stream(manifest.storage_id)
            self.assertEqual(Path(manifest.local_storage_path).read_bytes(), partial)
            final = manager.manifests[0]
            self.assertEqual(final.lifecycle_state, "open")
            self.assertEqual(final.details["written_row_count"], 0)
            self.assertEqual(final.details["durable_row_count"], 0)
            self.assertEqual(final.details["accepted_row_count"], 1)
            self.assertIsNone(final.details["row_count"])
            self.assertTrue(any(e.evidence_type == "finalization_failure" for e in manager.evidence))
            manager.cleanup()

    def test_partial_later_row_write_preserves_complete_prefix_and_uncertain_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            original_open = Path.open
            def open_file(path, *args, **kwargs):
                file = original_open(path, *args, **kwargs)
                return PartialWriteFile(file, fail_on_write=2) if path.name == "rows.jsonl" and args and args[0] == "a" else file
            with patch.object(Path, "open", open_file):
                manager, manifest = self.stream(directory)
            manager.append_rows(manifest.storage_id, (self.row(1),))
            with self.assertRaisesRegex(OSError, "partial JSONL write failed"):
                manager.append_rows(manifest.storage_id, (self.row(2),))
            with self.assertRaises(RuntimeError):
                manager.finalize_stream(manifest.storage_id)
            lines = Path(manifest.local_storage_path).read_text().splitlines()
            self.assertEqual(json.loads(lines[0])["value"], 1)
            self.assertEqual(len(lines), 2)
            failed = manager.manifests[0]
            self.assertIsNone(failed.details["row_count"])
            self.assertEqual(failed.details["accepted_row_count"], 2)
            self.assertEqual(failed.details["written_row_count"], 1)
            self.assertEqual(failed.details["durable_row_count"], 0)
            self.assertEqual(failed.details["write_status"], "uncertain")
            manager.cleanup()

    def test_successful_buffering_and_finalization_report_matching_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, manifest = self.stream(directory)
            manager.append_rows(manifest.storage_id, (self.row(i) for i in range(5)))
            summary = manager.finalize_all()
            self.assertEqual(len(Path(manifest.local_storage_path).read_text().splitlines()), 5)
            self.assertEqual(summary.streams[0]["row_count"], 5)
            self.assertEqual(summary.streams[0]["accepted_row_count"], 5)
            self.assertEqual(summary.streams[0]["durable_row_count"], 5)


if __name__ == "__main__":
    unittest.main()
