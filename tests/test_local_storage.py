import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from lab_sync_acquisition import (
    ArtifactManifest,
    LocalStorageCompletionSummary,
    LocalStorageEvidence,
    LocalStorageManager,
)


def _timestamped_row(experiment_id: str, payload: object) -> dict[str, object]:
    return {
        "session_time_s": 1.5,
        "experiment_time_s": 0.5,
        "acquisition_node_local_time_s": 12.0,
        "timestamp_status": "runtime_timestamped",
        "experiment_id": experiment_id,
        "payload": payload,
    }


class LocalStorageManagerTests(unittest.TestCase):
    def _manager(
        self,
        root: str | Path,
        *,
        max_buffered_rows: int | None = None,
        max_flush_interval_s: float | None = None,
    ) -> LocalStorageManager:
        return LocalStorageManager(
            root,
            "session-001",
            "node-001",
            max_buffered_rows=max_buffered_rows,
            max_flush_interval_s=max_flush_interval_s,
        )

    def _create_stream(self, manager: LocalStorageManager) -> ArtifactManifest:
        return manager.create_stream(
            session_id="session-001",
            experiment_id="experiment-001",
            acquisition_node_id="node-001",
            source_component_id="camera-001",
            data_product_id="camera-frame-metadata",
            artifact_type="framework_scientific_stream",
            schema={"payload": "plain_data"},
            details={"purpose": "test"},
        )

    def test_writable_local_root_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            readiness = self._manager(directory).check_ready()
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.component_type, "local_storage_manager")

    def test_file_path_is_not_a_writable_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-a-directory"
            root.write_text("occupied", encoding="utf-8")
            readiness = self._manager(root).check_ready()
        self.assertFalse(readiness.ready)

    def test_invalid_buffering_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "max_buffered_rows"):
                self._manager(directory, max_buffered_rows=1.5)  # type: ignore[arg-type]
            with self.assertRaisesRegex(ValueError, "max_flush_interval_s"):
                self._manager(directory, max_flush_interval_s=float("nan"))

    def test_stream_creation_owns_distinct_manifest_and_storage_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            self.assertNotEqual(manifest.storage_id, manifest.artifact_manifest_id)
            self.assertEqual(manager.manifests, (manifest,))
            self.assertEqual(
                [e.evidence_type for e in manager.evidence],
                ["stream_created", "manifest_created"],
            )
            self.assertTrue(Path(manifest.local_storage_path).exists())
            self.assertTrue(Path(manifest.local_managed_paths[0]).exists())
            self.assertTrue(Path(manifest.local_managed_paths[2]).exists())
            manager.finalize_all()

    def test_rows_append_incrementally_without_payload_interpretation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            manager.append_rows(
                manifest.storage_id,
                [
                    _timestamped_row("experiment-001", {"frame": 1}),
                    _timestamped_row("experiment-001", "external:frame-2"),
                ],
            )
            manager.flush(manifest.storage_id)
            rows = [
                json.loads(line)
                for line in Path(manifest.local_storage_path)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(rows[0]["payload"], {"frame": 1})
            self.assertEqual(rows[1]["payload"], "external:frame-2")
            self.assertEqual(manager.manifests[0].lifecycle_state, "open")
            manager.finalize_all()

    def test_generator_rows_are_consumed_and_written_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)

            def rows():
                yield _timestamped_row("experiment-001", "first")
                raise RuntimeError("producer stopped")

            with self.assertRaisesRegex(RuntimeError, "producer stopped"):
                manager.append_rows(manifest.storage_id, rows())
            manager.flush(manifest.storage_id)
            stored = Path(manifest.local_storage_path).read_text(
                encoding="utf-8"
            )
            self.assertIn('"payload": "first"', stored)
            manager.finalize_all()

    def test_bounded_buffer_flushes_at_configured_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory, max_buffered_rows=2)
            manifest = self._create_stream(manager)
            path = Path(manifest.local_storage_path)
            manager.append_rows(
                manifest.storage_id,
                [_timestamped_row("experiment-001", "first")],
            )
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            manager.append_rows(
                manifest.storage_id,
                [_timestamped_row("experiment-001", "second")],
            )
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)
            manager.finalize_all()

    def test_flush_interval_is_checked_during_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "lab_sync_acquisition.local_storage.monotonic",
                side_effect=[0.0, 0.5, 1.1, 1.1],
            ):
                manager = self._manager(
                    directory,
                    max_buffered_rows=10,
                    max_flush_interval_s=1.0,
                )
                manifest = self._create_stream(manager)
                manager.append_rows(
                    manifest.storage_id,
                    [
                        _timestamped_row("experiment-001", "first"),
                        _timestamped_row("experiment-001", "second"),
                    ],
                )
            self.assertEqual(
                len(
                    Path(manifest.local_storage_path)
                    .read_text(encoding="utf-8")
                    .splitlines()
                ),
                2,
            )
            manager.finalize_all()

    def test_missing_timing_is_rejected_with_write_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            row = _timestamped_row("experiment-001", 1)
            del row["session_time_s"]
            with self.assertRaisesRegex(ValueError, "session_time_s"):
                manager.append_rows(manifest.storage_id, [row])
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            manager.finalize_all()

    def test_serialization_failure_records_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            with self.assertRaises(TypeError):
                manager.append_rows(
                    manifest.storage_id,
                    [_timestamped_row("experiment-001", {"not-json"})],
                )
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            self.assertEqual(
                manager.evidence[-1].details["operation"],
                "row_serialization",
            )
            manager.finalize_all()

    def test_stream_creation_failure_records_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            with patch.object(
                Path,
                "write_text",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self._create_stream(manager)
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            self.assertEqual(
                manager.evidence[-1].details["operation"],
                "stream_creation",
            )

    def test_manifest_persistence_failure_records_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            with patch.object(
                manager,
                "_write_manifest",
                side_effect=OSError("manifest write failed"),
            ):
                with self.assertRaisesRegex(OSError, "manifest write failed"):
                    self._create_stream(manager)
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")
            self.assertEqual(
                manager.evidence[-1].details["operation"],
                "stream_creation",
            )

    def test_finalization_closes_stream_and_rejects_later_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            finalized = manager.finalize_stream(manifest.storage_id)
            self.assertEqual(finalized.lifecycle_state, "finalized")
            self.assertEqual(finalized.details["row_count"], 0)
            with self.assertRaisesRegex(RuntimeError, "finalized"):
                manager.append_rows(
                    manifest.storage_id,
                    [_timestamped_row("experiment-001", 1)],
                )
            self.assertEqual(manager.evidence[-1].evidence_type, "write_failure")

    def test_zero_row_stream_and_no_stream_have_distinct_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            empty_manager = self._manager(Path(directory) / "empty")
            empty_manager.check_ready()
            no_stream_summary = empty_manager.finalize_all()
            manager = self._manager(Path(directory) / "stream")
            manager.check_ready()
            self._create_stream(manager)
            empty_stream_summary = manager.finalize_all()
            self.assertEqual(no_stream_summary.stream_count, 0)
            self.assertEqual(empty_stream_summary.stream_count, 1)
            self.assertEqual(empty_stream_summary.streams[0]["row_count"], 0)

    def test_cleanup_closes_resources_and_records_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory, max_buffered_rows=10)
            manifest = self._create_stream(manager)
            manager.append_rows(
                manifest.storage_id,
                [_timestamped_row("experiment-001", "buffered")],
            )
            manager.cleanup()
            self.assertEqual(
                manager.evidence[-1].evidence_type,
                "cleanup_completed",
            )
            self.assertIn(
                '"payload": "buffered"',
                Path(manifest.local_storage_path).read_text(encoding="utf-8"),
            )

    def test_cleanup_failure_records_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            self._create_stream(manager)
            with patch.object(
                manager,
                "flush",
                side_effect=OSError("flush failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                    manager.cleanup()
            self.assertEqual(
                manager.evidence[-1].evidence_type,
                "cleanup_failed",
            )
            manager.cleanup()

    def test_plain_data_records_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            manifest = self._create_stream(manager)
            summary = manager.finalize_all()
            evidence = manager.evidence[0]
            self.assertEqual(
                ArtifactManifest.from_dict(manifest.to_dict()), manifest
            )
            self.assertEqual(
                LocalStorageEvidence.from_dict(evidence.to_dict()), evidence
            )
            self.assertEqual(
                LocalStorageCompletionSummary.from_dict(summary.to_dict()),
                summary,
            )
            with self.assertRaises(FrozenInstanceError):
                manifest.lifecycle_state = "changed"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
