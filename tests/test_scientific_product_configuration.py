import json
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager,
    ExperimentDescriptor, InMemoryIngestor, PersistentStorageManager,
    ScientificOutputSelection, ScientificProductDeclaration,
    Session, SessionConfig, SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class ScientificProductConfigurationTests(unittest.TestCase):
    def product(self, product_id="frames", storage_format="hdf5"):
        return ScientificProductDeclaration(
            product_id, "camera_frames", {"frame_shape": [4, 6, 3], "frame_dtype": "uint8",
            "metadata": {"backend": "opencv"}}, storage_format,
        )

    def selection(self, product_id="frames"):
        return ScientificOutputSelection("camera-001", "node-001", product_id)

    def device(self, products=()):
        return DeviceDeclaration("camera-001", "camera", True, True, ("stream",), products)

    def config(self, root, devices=()):
        return SessionConfig(
            list(devices), str(root), {}, str(root / "errors"), session_id="session-001",
        )

    def test_device_declares_multiple_products_in_order(self):
        products = (self.product(), self.product("events", "jsonl"))
        device = self.device(products)
        self.assertEqual(device.scientific_products, products)
        restored = DeviceDeclaration.from_dict(json.loads(json.dumps(device.to_dict())))
        self.assertEqual(restored, device)

    def test_product_round_trip_preserves_all_fields(self):
        product = ScientificProductDeclaration(
            "frames", "camera_frames", {"shape": [4, 6, 3], "dtype": "uint8"},
            "hdf5", expected_data_size_bytes=1024, expected_acquisition_rate_hz=25.0,
            storage_requirements={"compression": None, "custom": {"value": 7}},
        )
        self.assertEqual(ScientificProductDeclaration.from_dict(
            json.loads(json.dumps(product.to_dict()))), product)

    def test_unknown_size_and_rate_are_none(self):
        product = self.product()
        self.assertIsNone(product.expected_data_size_bytes)
        self.assertIsNone(product.expected_acquisition_rate_hz)
        self.assertIsNone(product.to_dict()["expected_data_size_bytes"])
        self.assertIsNone(product.to_dict()["expected_acquisition_rate_hz"])

    def test_existing_device_construction_and_old_dict_remain_compatible(self):
        device = self.device()
        self.assertEqual(device.scientific_products, ())
        data = device.to_dict()
        data.pop("scientific_products")
        self.assertEqual(DeviceDeclaration.from_dict(data), device)

    def test_duplicate_product_ids_are_rejected_within_device(self):
        with self.assertRaisesRegex(ValueError, "Duplicate scientific product"):
            self.device((self.product(), self.product(storage_format="jsonl")))

    def test_product_schema_is_copied_and_models_are_frozen(self):
        schema = {"shape": [4, 6]}
        product = ScientificProductDeclaration("frames", "camera_frames", schema, "hdf5")
        schema["shape"].append(3)
        product.to_dict()["schema"]["shape"].append(9)
        self.assertEqual(product.schema, {"shape": [4, 6]})
        for model, field in ((product, "storage_format"), (self.selection(), "data_product_id")):
            with self.assertRaises(FrozenInstanceError):
                setattr(model, field, "changed")

    def test_descriptor_round_trip_preserves_ordered_selections(self):
        outputs = (self.selection(), self.selection("events"))
        descriptor = ExperimentDescriptor("experiment-001", scientific_outputs=outputs)
        self.assertEqual(ExperimentDescriptor.from_dict(
            json.loads(json.dumps(descriptor.to_dict()))), descriptor)
        self.assertEqual(descriptor.scientific_outputs, outputs)

    def test_duplicate_selections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate scientific output"):
            ExperimentDescriptor("experiment-001", scientific_outputs=(self.selection(),) * 2)

    def test_selection_references_identities_without_format_override(self):
        self.assertEqual(self.selection().to_dict(), {
            "source_device_id": "camera-001", "source_node_id": "node-001",
            "data_product_id": "frames",
        })
        with self.assertRaises(TypeError):
            ScientificOutputSelection.from_dict({**self.selection().to_dict(),
                                                 "storage_format": "jsonl"})

    def test_existing_descriptor_construction_and_old_dict_remain_compatible(self):
        descriptor = ExperimentDescriptor("experiment-001")
        self.assertEqual(descriptor.scientific_outputs, ())
        self.assertEqual(ExperimentDescriptor.from_dict({"experiment_id": "experiment-001"}), descriptor)

    def test_session_preserves_outputs_without_live_device_declarations(self):
        session = Session("session-001", None)
        outputs = (self.selection(),)
        descriptor = session.ensure_experiment_descriptor("experiment-001", scientific_outputs=outputs)
        self.assertEqual(descriptor.scientific_outputs, outputs)
        self.assertIs(session.ensure_experiment_descriptor("experiment-001"), descriptor)
        with self.assertRaisesRegex(ValueError, "conflict"):
            session.ensure_experiment_descriptor("experiment-001", scientific_outputs=(self.selection("events"),))

    def test_controller_preserves_explicit_outputs_in_persistent_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root, (self.device((self.product(),)),))
            adapter = ReadyFakeAdapter("camera-001", "camera", ("stream",), True)
            manager = DeviceManager((adapter,))
            storage = PersistentStorageManager(root / "records.jsonl")
            ingestor = InMemoryIngestor(storage_manager=storage)
            synchronization = SynchronizationManager()
            node = AcquisitionNode(
                session_id=config.session_id, device_manager=manager,
                synchronization_manager=synchronization, ingestor=ingestor,
                error_evidence_location=config.error_evidence_location,
                node_id="node-001", default_local_storage_root=root / "local",
            )
            controller = Controller(node, ingestor, storage, root / "session_record.json",
                                    synchronization_manager=synchronization)
            manager.initialize_all(config={})
            readiness = node.check_ready()
            self.assertTrue(controller.create_session(config).succeeded)
            self.assertTrue(controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]).succeeded)
            self.assertTrue(controller.start_session().succeeded)
            self.assertTrue(controller.start_experiment(
                "experiment-001", scientific_outputs=(self.selection(),)).succeeded)
            self.assertTrue(controller.stop_experiment("experiment-001").succeeded)
            self.assertTrue(controller.stop_session().succeeded)
            self.assertTrue(controller.finalize_session().succeeded)
            record = json.loads((root / "session_session-001" / "session_record_final.json").read_text())
            self.assertEqual(record["experiment_descriptors"][0]["scientific_outputs"],
                             [self.selection().to_dict()])
            self.assertEqual(config.to_dict()["selected_devices"][0]["scientific_products"],
                             [self.product().to_dict()])
            node.local_storage_manager.cleanup()


if __name__ == "__main__":
    unittest.main()
