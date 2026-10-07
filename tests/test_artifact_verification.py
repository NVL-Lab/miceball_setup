import errno
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import h5py

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import InMemoryIngestor, RuntimeEvidenceMessage
from tests import test_artifact_retrieval as retrieval_tests
from tests import test_local_storage_hdf5 as hdf5_tests


class ArtifactVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.retrieval = retrieval_tests.ArtifactRetrievalTests()
        self.writer = hdf5_tests.HDF5ScientificPersistenceTests()

    def artifact(self, count=2, initial_only=False):
        local = self.writer.manager(self.root / "local")
        initial = self.writer.stream(local)
        local.append_rows(initial.storage_id, (self.writer.row(i) for i in range(count)))
        finalized = local.finalize_all().manifests[0]
        return initial if initial_only else finalized

    def collect(self, *manifests, failure_sources=()):
        ingestor = InMemoryIngestor()
        files = {}
        for manifest in manifests:
            ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                manifest.artifact_manifest_id, manifest.session_id, "artifact_manifest",
                manifest.acquisition_node_id, manifest.to_dict(), True))
            source = manifest.external_artifact_path or manifest.local_storage_path
            files[source] = Path(manifest.local_storage_path).read_bytes()
        sftp = retrieval_tests.SftpDouble(files, failures=failure_sources)
        mock_ssh, _ = self.retrieval.ssh(sftp)
        with mock_ssh:
            result = self.retrieval.storage(self.root).collect_artifacts(
                ingestor.compile_artifact_collection_handoff("session"))
        self.assertFalse(list((self.root / "global").rglob(".incomplete-*")))
        for manifest in manifests:
            source = manifest.external_artifact_path or manifest.local_storage_path
            self.assertEqual(Path(manifest.local_storage_path).read_bytes(), files[source])
        return result

    def assert_invalid(self, manifest, information):
        before = Path(manifest.local_storage_path).read_bytes()
        result = self.collect(manifest)
        item = result.artifact_results[0]
        self.assertEqual(item.outcome, "success")
        self.assertEqual(item.verification_outcome, "structurally_invalid")
        self.assertIn(information, item.verification_information)
        self.assertFalse(result.succeeded)
        self.assertEqual(Path(item.global_destination).read_bytes(), before)
        return result

    def test_supported_copy_is_verified_and_serializes_separate_outcomes(self):
        manifest = self.artifact()
        result = self.collect(manifest)
        self.assertTrue(result.succeeded)
        item = result.artifact_results[0]
        self.assertEqual(item.outcome, "success")
        self.assertEqual(item.verification_outcome, "verified")
        self.assertEqual(item.to_dict()["verification_outcome"], "verified")
        self.assertIsNone(item.to_dict()["verification_information"])

    def test_zero_record_artifact_is_verified(self):
        self.assertTrue(self.collect(self.artifact(count=0)).succeeded)

    def test_missing_required_datasets_are_structurally_invalid(self):
        for name in ("frames", "session_time_s", "experiment_time_s",
                     "acquisition_node_local_time_s", "frame_index",
                     "timestamp_status", "record_metadata_json"):
            with self.subTest(dataset=name):
                manifest = self.artifact()
                with h5py.File(manifest.local_storage_path, "r+") as artifact:
                    del artifact[name]
                self.assert_invalid(manifest, "Missing required dataset")

    def test_dataset_length_mismatch_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            artifact["frame_index"].resize(1, axis=0)
        self.assert_invalid(manifest, "dataset-length mismatch")

    def test_missing_embedded_identity_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            del artifact.attrs["artifact_manifest_id"]
        self.assert_invalid(manifest, "Missing embedded")

    def test_mismatched_embedded_identity_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            artifact.attrs["artifact_manifest_id"] = "other"
        self.assert_invalid(manifest, "identity mismatch")

    def test_embedded_persisted_count_mismatch_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            artifact.attrs["persisted_frame_count"] = 3
        self.assert_invalid(manifest, "embedded persisted_frame_count")

    def test_missing_embedded_persisted_count_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            del artifact.attrs["persisted_frame_count"]
        self.assert_invalid(manifest, "embedded persisted_frame_count")

    def test_finalized_manifest_count_mismatch_is_structurally_invalid(self):
        manifest = self.artifact()
        manifest = replace(manifest, details={**manifest.details, "persisted_frame_count": 9})
        self.assert_invalid(manifest, "Finalized manifest persisted-count mismatch")

    def test_initial_only_manifest_does_not_invent_finalized_count(self):
        manifest = self.artifact(initial_only=True)
        self.assertNotIn("persisted_frame_count", manifest.details)
        self.assertTrue(self.collect(manifest).succeeded)

    def test_nonfinalized_count_is_not_an_authoritative_expectation(self):
        manifest = self.artifact(initial_only=True)
        manifest = replace(manifest, details={**manifest.details, "persisted_frame_count": 99})
        self.assertTrue(self.collect(manifest).succeeded)

    def test_invalid_hdf5_bytes_are_structurally_invalid_not_operational_failure(self):
        manifest = self.artifact()
        Path(manifest.local_storage_path).write_bytes(b"not an HDF5 file")
        self.assert_invalid(manifest, "could not be opened as valid HDF5")

    def test_zero_byte_file_is_structurally_invalid(self):
        manifest = self.artifact()
        Path(manifest.local_storage_path).write_bytes(b"")
        self.assert_invalid(manifest, "zero byte size")

    def test_operational_access_failure_preserves_completed_copy(self):
        manifest = self.artifact()
        real_open = Path.open

        def inaccessible(path, *args, **kwargs):
            if self.root / "global" in path.parents:
                raise PermissionError(errno.EACCES, "verification access denied")
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", inaccessible):
            result = self.collect(manifest)
        item = result.artifact_results[0]
        self.assertEqual(item.outcome, "success")
        self.assertEqual(item.verification_outcome, "verification_failed")
        self.assertIn("access denied", item.verification_information)
        self.assertFalse(result.succeeded)
        self.assertEqual(Path(item.global_destination).read_bytes(), Path(manifest.local_storage_path).read_bytes())

    def test_operational_hdf5_read_failure_is_not_invalid_structure(self):
        manifest = self.artifact()
        with patch("h5py.File", side_effect=OSError(errno.EIO, "read failed")):
            result = self.collect(manifest)
        self.assertEqual(result.artifact_results[0].verification_outcome, "verification_failed")
        self.assertFalse(result.succeeded)
        self.assertTrue(Path(result.artifact_results[0].global_destination).exists())

    def test_jsonl_is_copied_unverified(self):
        manifest = self.artifact()
        manifest = replace(manifest, details={"storage_format": "jsonl"})
        item = self.collect(manifest).artifact_results[0]
        self.assertEqual(item.outcome, "success")
        self.assertEqual(item.verification_outcome, "copied_unverified")

    def test_operational_hdf5_error_without_errno_is_not_invalid_structure(self):
        manifest = self.artifact()
        real_open = Path.open

        def read_failed(*args):
            raise OSError("unable to read file: I/O failure")

        def failing_read(path, *args, **kwargs):
            source = real_open(path, *args, **kwargs)
            if self.root / "global" not in path.parents:
                return source
            failing = MagicMock(wraps=source)
            failing.__enter__.return_value = failing
            failing.__exit__.side_effect = source.__exit__
            failing.readinto.side_effect = read_failed
            failing.read.side_effect = read_failed
            return failing

        # Exercise real h5py callbacks, not an undifferentiated mocked format error.
        with patch.object(Path, "open", failing_read):
            result = self.collect(manifest)
        self.assertEqual(result.artifact_results[0].verification_outcome, "verification_failed")
        self.assertIn("I/O failure", result.artifact_results[0].verification_information)
        self.assertEqual(result.artifact_results[0].outcome, "success")
        self.assertEqual(Path(result.artifact_results[0].global_destination).read_bytes(),
                         Path(manifest.local_storage_path).read_bytes())

    def test_truncated_hdf5_is_structurally_invalid(self):
        manifest = self.artifact()
        path = Path(manifest.local_storage_path)
        path.write_bytes(path.read_bytes()[:200])
        self.assert_invalid(manifest, "could not be opened as valid HDF5")

    def test_corrupt_hdf5_address_width_is_structurally_invalid_and_preserved(self):
        manifest = self.artifact()
        path = Path(manifest.local_storage_path)
        data = bytearray(path.read_bytes())
        self.assertEqual(data[:8], b"\x89HDF\r\n\x1a\n")
        self.assertEqual(data[8], 0)  # The current writer uses a version-zero superblock.
        data[13] = 3  # Three bytes is not a valid HDF5 address width.
        path.write_bytes(data)
        self.assert_invalid(manifest, "could not be opened as valid HDF5")

    def test_hdf5_filename_without_format_contract_is_copied_unverified(self):
        manifest = replace(self.artifact(), details={})
        result = self.collect(manifest)
        self.assertEqual(result.artifact_results[0].verification_outcome, "copied_unverified")
        self.assertFalse(result.succeeded)

    def test_external_hdf5_is_not_assumed_to_use_local_writer_layout(self):
        manifest = self.artifact()
        manifest = replace(manifest, external_artifact_path="/external/recording.h5")
        self.assertEqual(self.collect(manifest).artifact_results[0].verification_outcome, "copied_unverified")

    def test_contract_is_not_selected_by_camera_device_identity(self):
        manifest = replace(self.artifact(), source_component_id="other-device", artifact_type="other-product")
        self.assertTrue(self.collect(manifest).succeeded)

    def test_retrieval_failure_has_no_verification_and_later_artifact_is_verified(self):
        first, second = self.artifact(), self.artifact()
        with patch("h5py.File", wraps=h5py.File) as opened:
            result = self.collect(first, second, failure_sources=(first.local_storage_path,))
        self.assertEqual(opened.call_count, 1)
        self.assertFalse(result.succeeded)
        self.assertEqual([item.outcome for item in result.artifact_results], ["failure", "success"])
        self.assertIsNone(result.artifact_results[0].verification_outcome)
        self.assertNotIn("verification_outcome", result.artifact_results[0].to_dict())
        self.assertEqual(result.artifact_results[1].verification_outcome, "verified")

    def test_mixed_verification_results_prevent_complete_verified_success(self):
        first, second = self.artifact(), self.artifact()
        second = replace(second, details={})
        result = self.collect(first, second)
        self.assertFalse(result.succeeded)
        self.assertEqual([item.verification_outcome for item in result.artifact_results],
                         ["verified", "copied_unverified"])

    def test_verification_uses_metadata_without_reading_scientific_datasets(self):
        manifest = self.artifact()
        with patch.object(h5py.Dataset, "__getitem__", side_effect=AssertionError("bulk data read")):
            self.assertTrue(self.collect(manifest).succeeded)

    def test_group_in_place_of_required_dataset_is_structurally_invalid(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            del artifact["frames"]
            artifact.create_group("frames")
        self.assert_invalid(manifest, "record dataset is invalid")
