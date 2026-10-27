"""Read historical scientific originals without reattaching their Session."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import h5py
import numpy as np

from lab_sync_acquisition import AcquisitionNode, DeviceManager, LocalStorageManager
from tests.fakes import ReadyFakeAdapter


class HistoricalArtifactInventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "originals"
        self.adapter = ReadyFakeAdapter("camera", "camera", ("frames",), True)
        self.node = AcquisitionNode(
            device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.root)

    def stream(self, manager, product="frames", artifact_type="camera_frames"):
        manifest = manager.create_stream(
            session_id=manager.session_id, experiment_id="experiment",
            acquisition_node_id="node", source_component_id="camera",
            data_product_id=product, artifact_type=artifact_type, schema={})
        manager.append_rows(manifest.storage_id, [{
            "session_time_s": 1.0, "experiment_time_s": 0.0,
            "acquisition_node_local_time_s": 2.0,
            "timestamp_status": "runtime_timestamped", "experiment_id": "experiment",
            "payload": {"frame": 1}}])
        return manifest

    def saved(self):
        manager = LocalStorageManager(self.root, "old", "node")
        manifest = self.stream(manager)
        manager.finalize_all()
        return manager, manifest

    def inventory(self, session_id=None):
        return self.node.read_historical_artifacts(session_id=session_id)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def edit_manifest(self, manifest, **changes):
        path = Path(manifest.local_managed_paths[2])
        value = json.loads(path.read_text())
        value.update(changes)
        path.write_text(json.dumps(value))

    def test_readback_after_release_and_during_replacement_session(self):
        self.assertTrue(self.node.reserve("old"))
        self.node.initialize_session("old", self.node.declared_devices)
        manager = self.node.local_storage_manager
        manifest = self.stream(manager)
        manager.finalize_all()
        self.assertTrue(self.node.abort_session_initialization("old"))
        self.assertTrue(self.node.release_reservation("old"))
        before = self.snapshot()
        report = self.inventory("old")
        self.assertIsNone(self.node.local_storage_manager)
        self.assertEqual(report["artifacts"][0]["original_path"], manifest.local_storage_path)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.node.reserve("new"))
        self.node.initialize_session("new", self.node.declared_devices)
        current = self.node.local_storage_manager
        current_manifest = self.stream(current)
        current.flush(current_manifest.storage_id)
        before = self.snapshot()
        evidence = current.evidence
        adapter_status = self.adapter.get_status()
        report = self.inventory("old")
        self.assertEqual(len(report["artifacts"]), 1)
        self.assertTrue(report["artifacts"][0]["identity_confirmed"])
        self.assertIs(self.node.local_storage_manager, current)
        self.assertEqual(self.node.reserved_for_session_id, "new")
        self.assertEqual(current.evidence, evidence)
        self.assertEqual(self.adapter.get_status(), adapter_status)
        self.assertEqual(current.manifests[0].lifecycle_state, "open")
        self.assertEqual(self.snapshot(), before)
        current.finalize_all()
        self.node.abort_session_initialization("new")
        self.node.release_reservation("new")

    def test_hdf5_readback_preserves_pixels_timing_manifest_and_metadata(self):
        manager = LocalStorageManager(self.root, "old", "node")
        manifest = manager.create_stream(
            session_id="old", experiment_id="experiment", acquisition_node_id="node",
            source_component_id="camera", data_product_id="frames", artifact_type="camera_frames",
            schema={"frame_shape": [2, 3], "frame_dtype": "uint8"}, storage_format="hdf5")
        manager.append_rows(manifest.storage_id, [{
            "session_time_s": 1.0, "experiment_time_s": 0.0,
            "acquisition_node_local_time_s": 2.0, "timestamp_status": "runtime_timestamped",
            "experiment_id": "experiment", "frame_index": 0,
            "frame": np.full((2, 3), 7, dtype="uint8")}])
        manager.finalize_all()
        before = self.snapshot()
        artifact = self.inventory()["artifacts"][0]
        self.assertTrue(artifact["identity_confirmed"])
        self.assertEqual(artifact["file_status"], "present")
        with h5py.File(artifact["original_path"], "r") as recording:
            np.testing.assert_array_equal(recording["frames"][0], np.full((2, 3), 7, dtype="uint8"))
        artifact["manifest"]["details"]["row_count"] = -1
        artifact["metadata"]["schema"].clear()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.inventory()["artifacts"][0]["manifest"]["details"]["row_count"], 1)

    def test_separate_scientific_timing_and_index_artifacts_are_not_grouped(self):
        manager = LocalStorageManager(self.root, "old", "node")
        originals = [self.stream(manager, product, kind) for product, kind in (
            ("frames", "camera_frames"), ("timing", "timing"), ("index", "index"))]
        manager.finalize_all()
        before = self.snapshot()
        report = self.inventory()
        self.assertEqual({a["original_path"] for a in report["artifacts"]},
                         {m.local_storage_path for m in originals})
        self.assertTrue(all(a["identity_confirmed"] for a in report["artifacts"]))
        self.assertTrue(all(a["recording_id"] is None for a in report["artifacts"]))
        self.assertIn("unresolved", report["recording_associations"])
        self.assertEqual(self.snapshot(), before)

    def test_open_missing_and_unidentified_artifacts_are_explicit(self):
        manager = LocalStorageManager(self.root, "old", "node")
        manifest = self.stream(manager)
        manager.flush(manifest.storage_id)
        report = self.inventory()
        self.assertIn("not_finalized", report["artifacts"][0]["issues"])
        manager.finalize_all()
        Path(manifest.local_storage_path).unlink()
        artifact = self.inventory()["artifacts"][0]
        self.assertTrue(artifact["identity_confirmed"])
        self.assertEqual(artifact["file_status"], "missing")
        self.assertIn("missing_original", artifact["issues"])
        Path(manifest.local_managed_paths[2]).unlink()
        artifact = self.inventory()["artifacts"][0]
        self.assertFalse(artifact["identity_confirmed"])
        self.assertIsNone(artifact["original_path"])
        self.assertIn("missing_manifest", artifact["issues"])

    def test_damaged_or_inconsistent_metadata_never_confirms_identity(self):
        for damage in ("missing", "malformed", "wrong_session", "wrong_product", "duplicate_key"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                manager = LocalStorageManager(directory, "old", "node")
                manifest = self.stream(manager)
                manager.finalize_all()
                path = Path(manifest.local_managed_paths[0])
                metadata = json.loads(path.read_text())
                if damage == "missing":
                    path.unlink()
                elif damage == "malformed":
                    path.write_text("{")
                elif damage == "wrong_session":
                    path.write_text(json.dumps({**metadata, "session_id": "other"}))
                elif damage == "wrong_product":
                    path.write_text(json.dumps({**metadata, "data_product_id": None}))
                else:
                    path.write_text('{"session_id":"other",' + path.read_text()[1:])
                before = {p: p.read_bytes() for p in Path(directory).rglob("*") if p.is_file()}
                report = LocalStorageManager.read_historical_artifacts(directory, "node")
                artifact = report["artifacts"][0]
                self.assertFalse(artifact["identity_confirmed"])
                self.assertIsNone(artifact["original_path"])
                self.assertTrue(artifact["issues"])
                self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_manifest_identity_and_shape_are_checked(self):
        _, manifest = self.saved()
        path = Path(manifest.local_managed_paths[2])
        original = path.read_bytes()
        for changes in ({"session_id": "other"}, {"experiment_id": "other"},
                        {"acquisition_node_id": "other"}, {"storage_id": "other"},
                        {"artifact_manifest_id": ""}, {"local_managed_paths": "not-a-list"},
                        {"details": []}, {"lifecycle_state": "made_up"}):
            with self.subTest(changes=changes):
                path.write_bytes(original)
                self.edit_manifest(manifest, **changes)
                artifact = self.inventory()["artifacts"][0]
                self.assertFalse(artifact["identity_confirmed"])
                self.assertIsNone(artifact["original_path"])

    def test_damaged_manifest_does_not_guess_files_from_directory_contents(self):
        _, manifest = self.saved()
        path = Path(manifest.local_managed_paths[2])
        original = path.read_text()
        for contents in ("{", "[]", original.replace('"details": {', '"details": {"bad": NaN,'),
                         '{"session_id":"duplicate",' + original[1:]):
            with self.subTest(contents=contents[:24]):
                path.write_text(contents)
                artifact = self.inventory()["artifacts"][0]
                self.assertFalse(artifact["identity_confirmed"])
                self.assertIsNone(artifact["original_path"])
                self.assertEqual(artifact["file_status"], "unconfirmed")
                self.assertTrue(artifact["issues"])

    def test_duplicate_and_conflicting_identities_invalidate_all_claims(self):
        _, first = self.saved()
        other = LocalStorageManager(self.root, "other", "node")
        second = self.stream(other)
        other.finalize_all()
        self.edit_manifest(second, artifact_manifest_id=first.artifact_manifest_id)
        report = self.inventory()
        self.assertEqual(len(report["artifacts"]), 2)
        for artifact in report["artifacts"]:
            self.assertFalse(artifact["identity_confirmed"])
            self.assertIn("duplicate_artifact_manifest_id", artifact["issues"])
        self.assertFalse(self.inventory("old")["artifacts"][0]["identity_confirmed"])
        # Even a damaged competing record must not make the first claim unique.
        self.edit_manifest(second, details=[])
        self.assertFalse(self.inventory("old")["artifacts"][0]["identity_confirmed"])

    def test_duplicate_storage_identity_is_not_hidden_by_directory_mismatch(self):
        manager, first = self.saved()
        second = self.stream(manager, "timing", "timing")
        manager.finalize_all()
        self.edit_manifest(second, storage_id=first.storage_id)
        for artifact in self.inventory()["artifacts"]:
            self.assertFalse(artifact["identity_confirmed"])
            self.assertIn("duplicate_storage_id", artifact["issues"])

    def test_exact_external_source_is_separate_from_auxiliary_managed_paths(self):
        _, manifest = self.saved()
        external = Path(manifest.local_storage_path).with_name("camera.bin")
        external.write_bytes(b"external camera output")
        self.edit_manifest(manifest, external_artifact_path=str(external))
        artifact = self.inventory()["artifacts"][0]
        self.assertTrue(artifact["identity_confirmed"])
        self.assertEqual(artifact["original_path"], str(external))

    def test_outside_and_administrative_paths_are_never_scientific_targets(self):
        _, manifest = self.saved()
        path = Path(manifest.local_managed_paths[2])
        original = path.read_bytes()
        outside = self.root.parent / "outside.bin"
        outside.write_bytes(b"untouched")
        for field in ("local_storage_path", "external_artifact_path"):
            for source in (outside, Path(manifest.local_managed_paths[0]), path,
                           self.root / "local_storage_evidence.jsonl", path.parent):
                with self.subTest(source=source, field=field):
                    path.write_bytes(original)
                    self.edit_manifest(manifest, **{field: str(source)})
                    artifact = self.inventory()["artifacts"][0]
                    self.assertFalse(artifact["identity_confirmed"])
                    self.assertIsNone(artifact["original_path"])
        self.assertEqual(outside.read_bytes(), b"untouched")

    def test_administrative_and_unmanifested_files_are_not_inferred_as_artifacts(self):
        _, manifest = self.saved()
        for name in ("deletion_operation.json", "evidence.jsonl", "unidentified_camera.bin"):
            (Path(manifest.local_storage_path).parent / name).write_bytes(b"not a manifested original")
        before = self.snapshot()
        report = self.inventory()
        self.assertEqual([a["original_path"] for a in report["artifacts"]], [manifest.local_storage_path])
        self.assertEqual(self.snapshot(), before)

    def test_administrative_hard_link_is_not_a_scientific_original(self):
        _, manifest = self.saved()
        source = Path(manifest.local_storage_path)
        source.unlink()
        os.link(manifest.local_managed_paths[0], source)
        before = self.snapshot()
        artifact = self.inventory()["artifacts"][0]
        self.assertFalse(artifact["identity_confirmed"])
        self.assertIn("aliased_original", artifact["issues"])
        self.assertEqual(self.snapshot(), before)

    def test_hard_link_aliases_cannot_establish_two_originals(self):
        manager, first = self.saved()
        second = self.stream(manager, "timing", "timing")
        manager.finalize_all()
        target = Path(second.local_storage_path)
        target.unlink()
        os.link(first.local_storage_path, target)
        for artifact in self.inventory()["artifacts"]:
            self.assertFalse(artifact["identity_confirmed"])
            self.assertIn("aliased_original", artifact["issues"])

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    def test_windows_junction_is_not_followed(self):
        _, manifest = self.saved()
        link = self.root / "alias"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.root / "old")],
                       check=True, capture_output=True)
        before = self.snapshot()
        report = self.inventory()
        self.assertEqual(len(report["artifacts"]), 1)
        self.assertTrue(report["artifacts"][0]["identity_confirmed"])
        self.assertEqual(report["artifacts"][0]["original_path"], manifest.local_storage_path)
        self.assertIn({"path": str(link), "reason": "directory_alias_not_followed"}, report["issues"])
        self.assertEqual(self.snapshot(), before)

    def test_symlink_directory_and_original_are_reported_without_following(self):
        _, manifest = self.saved()
        link = self.root / "alias"
        try:
            link.symlink_to(self.root / "old", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")
        report = self.inventory()
        self.assertEqual(len(report["artifacts"]), 1)
        self.assertTrue(report["issues"])
        data = Path(manifest.local_storage_path)
        contents = data.read_bytes()
        data.unlink()
        external = self.root.parent / "outside.bin"
        external.write_bytes(contents)
        data.symlink_to(external)
        self.assertFalse(self.inventory()["artifacts"][0]["identity_confirmed"])
        self.assertEqual(external.read_bytes(), contents)

    def test_absent_or_unconfigured_root_is_not_created(self):
        report = self.inventory()
        self.assertTrue(report["issues"])
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            self.inventory("../escape")
        node = AcquisitionNode(device_manager=DeviceManager([
            ReadyFakeAdapter("camera", "camera", ("frames",), True)]), node_id="node",
                               synchronization_source_id="sync")
        with self.assertRaisesRegex(ValueError, "configured"):
            node.read_historical_artifacts()


if __name__ == "__main__":
    unittest.main()
