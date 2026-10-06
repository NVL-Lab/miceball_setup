import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager,
    InMemoryIngestor, LocalStorageManager, PersistentStorageManager,
    ScientificOutputSelection, ScientificProductDeclaration,
    Session, SessionConfig, SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class ScientificOutputPreparationTests(unittest.TestCase):
    @contextmanager
    def temporary_directory(self):
        self.nodes = []
        with tempfile.TemporaryDirectory() as directory:
            try:
                yield directory
            finally:
                for node in self.nodes:
                    if node.local_storage_manager is not None:
                        node.local_storage_manager.cleanup()

    def product(self, name="frames", storage_format="hdf5", schema=None):
        return ScientificProductDeclaration(
            name, "camera_frames" if storage_format == "hdf5" else "events",
            schema if schema is not None else {"frame_shape": [4, 6, 3], "frame_dtype": "uint8"},
            storage_format, storage_requirements={"lossy": False},
        )

    def output(self, product="frames", device="camera-001", node="node-001"):
        return ScientificOutputSelection(device, node, product)

    def fixture(self, root, *, products=None, default=True, override=None, session_id="session-001"):
        products = (self.product(),) if products is None else products
        config = SessionConfig(
            selected_devices=[DeviceDeclaration("camera-001", "camera", True, True,
                                               ("stream",), products)],
            storage_location=str(root / "records.jsonl"), protocol_plan={},
            error_evidence_location=str(root / "errors"), session_id=session_id,
            local_storage_roots={"node-001": str(override)} if override is not None else None,
        )
        manager = DeviceManager((ReadyFakeAdapter("camera-001", "camera", ("stream",), True),))
        storage = PersistentStorageManager(root / "records.jsonl")
        ingestor = InMemoryIngestor(storage_manager=storage)
        sync = SynchronizationManager()
        node = AcquisitionNode(session_id, manager, sync, ingestor, node_id="node-001",
                               error_evidence_location=config.error_evidence_location,
                               default_local_storage_root=root / "default" if default else None)
        controller = Controller(node, ingestor, storage, root / "session_record.json",
                                synchronization_manager=sync)
        manager.initialize_all(config={})
        self.assertTrue(controller.create_session(config).succeeded)
        self.nodes.append(node)
        return controller, node, config

    def start_session(self, controller, node):
        readiness = node.check_ready()
        self.assertTrue(controller.initialize_session(
            readiness["device_readiness"], readiness["service_readiness"]).succeeded)
        self.assertTrue(controller.start_session().succeeded)

    def test_session_initialization_attaches_storage_with_default_root(self):
        with self.temporary_directory() as directory:
            root = Path(directory)
            controller, node, config = self.fixture(root)
            self.assertTrue(controller.initialize_session().succeeded)
            local = node.local_storage_manager
            self.assertEqual(local.root_path, root / "default")
            self.assertEqual(local.session_id, config.session_id)
            self.assertEqual(local.acquisition_node_id, "node-001")

    def test_session_override_leaves_default_available_for_later_session(self):
        with self.temporary_directory() as directory:
            root = Path(directory)
            controller, node, _ = self.fixture(root, override=root / "override")
            self.assertTrue(controller.initialize_session().succeeded)
            self.assertEqual(node.local_storage_manager.root_path, root / "override")
            self.assertEqual(node.default_local_storage_root, root / "default")
            other, other_node, _ = self.fixture(root, session_id="session-002")
            self.assertTrue(other.initialize_session().succeeded)
            self.assertEqual(other_node.local_storage_manager.root_path, node.default_local_storage_root)

    def test_session_reuses_attached_manager_on_readiness_retry(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory))
            with patch.object(LocalStorageManager, "check_ready", side_effect=OSError("unavailable")):
                self.assertFalse(controller.initialize_session().succeeded)
            local = node.local_storage_manager
            self.assertTrue(controller.initialize_session().succeeded)
            self.assertIs(node.local_storage_manager, local)

    def test_one_selected_product_prepares_zero_frame_artifact_and_manifest(self):
        import h5py
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory))
            self.start_session(controller, node)
            self.assertTrue(controller.start_experiment("experiment-001",
                            scientific_outputs=(self.output(),)).succeeded)
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.lifecycle_state, "open")
            self.assertTrue(Path(manifest.local_managed_paths[2]).exists())
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                self.assertEqual(artifact["frames"].shape, (0, 4, 6, 3))
            self.assertEqual(node.scientific_output_storage_ids,
                             {("experiment-001", "camera-001", "frames"): manifest.storage_id})
            controller.stop_experiment("experiment-001")
            controller.stop_session()

    def test_multiple_products_use_declaration_owned_formats(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory), products=(
                self.product(), self.product("events", "jsonl", {"value": "number"})))
            self.start_session(controller, node)
            self.assertTrue(controller.start_experiment("experiment-001", scientific_outputs=(
                self.output(), self.output("events"))).succeeded)
            manifests = node.local_storage_manager.manifests
            self.assertEqual(len(manifests), 2)
            self.assertEqual([Path(m.local_storage_path).suffix for m in manifests], [".h5", ".jsonl"])
            metadata = json.loads(Path(manifests[1].local_storage_path).with_name("metadata.json").read_text())
            self.assertEqual(metadata["schema"], {"value": "number"})
            self.assertEqual(metadata["details"]["storage_requirements"], {"lossy": False})
            controller.stop_experiment("experiment-001")
            controller.stop_session()

    def test_unknown_node_device_and_product_prevent_start(self):
        for output in (self.output(node="unknown"), self.output(device="unknown"), self.output("unknown")):
            with self.subTest(output=output), self.temporary_directory() as directory:
                controller, node, _ = self.fixture(Path(directory))
                self.start_session(controller, node)
                result = controller.start_experiment("experiment-001", scientific_outputs=(output,))
                self.assertFalse(result.succeeded)
                self.assertTrue(result.error)
                self.assertIsNone(node.status()["active_experiment_runtime_context"])
                self.assertEqual(node.local_storage_manager.manifests, ())
                self.assertEqual(controller.get_status()["session_state"], "running")
                controller.stop_session()

    def test_missing_storage_root_prevents_initialization(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory), default=False)
            self.assertFalse(controller.initialize_session().succeeded)
            self.assertIsNone(node.local_storage_manager)

    def test_incompatible_hdf5_schema_prevents_start(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory), products=(self.product(schema={}),))
            self.start_session(controller, node)
            self.assertFalse(controller.start_experiment("experiment-001",
                             scientific_outputs=(self.output(),)).succeeded)
            self.assertTrue(any(e.evidence_type == "write_failure" for e in node.local_storage_manager.evidence))
            controller.stop_session()

    def test_partial_preparation_finalizes_created_stream_and_preserves_evidence(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory))
            self.start_session(controller, node)
            result = controller.start_experiment("experiment-001", scientific_outputs=(
                self.output(), self.output("unknown")))
            self.assertFalse(result.succeeded)
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.lifecycle_state, "finalized")
            self.assertTrue(Path(manifest.local_storage_path).exists())
            self.assertTrue(any(e.evidence_type == "stream_finalized" for e in node.local_storage_manager.evidence))
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertFalse(controller.stop_experiment("experiment-001").succeeded)
            controller.stop_session()

    def test_stream_creation_failure_is_explicit(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory))
            self.start_session(controller, node)
            with patch.object(node.local_storage_manager, "create_stream", side_effect=OSError("disk unavailable")):
                result = controller.start_experiment("experiment-001", scientific_outputs=(self.output(),))
            self.assertFalse(result.succeeded)
            self.assertIn("disk unavailable", result.error)
            controller.stop_session()

    def test_metadata_only_experiment_without_storage_remains_compatible(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory), products=(), default=False)
            self.start_session(controller, node)
            self.assertIsNone(node.local_storage_manager)
            self.assertTrue(controller.start_experiment("metadata-only").succeeded)
            self.assertTrue(controller.stop_experiment("metadata-only").succeeded)
            controller.stop_session()

    def test_repeated_preparation_reuses_stream_and_manifest(self):
        with self.temporary_directory() as directory:
            controller, node, _ = self.fixture(Path(directory))
            self.assertTrue(controller.initialize_session().succeeded)
            outputs = (self.output(),)
            self.assertTrue(node.prepare_experiment_scientific_outputs("experiment-001", outputs).ready)
            original = node.scientific_output_storage_ids
            self.assertTrue(node.prepare_experiment_scientific_outputs("experiment-001", outputs).ready)
            self.assertEqual(node.scientific_output_storage_ids, original)
            self.assertEqual(len(node.local_storage_manager.manifests), 1)

    def test_attached_manager_identity_is_validated(self):
        with self.temporary_directory() as directory:
            _, node, config = self.fixture(Path(directory))
            wrong = LocalStorageManager(directory, "another-session", "node-001")
            with self.assertRaisesRegex(ValueError, "identity"):
                node.attach_local_storage_manager(wrong, config.selected_devices)


if __name__ == "__main__":
    unittest.main()
