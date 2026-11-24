"""Software recordings and public Expected size preparation workflows."""
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition.local_storage import LocalStorageManager
from lab_sync_acquisition.local_storage import camera_storage_estimate, validate_storage_capacity
from lab_sync_acquisition import AcquisitionNode, DeviceManager, DeviceDeclaration, ScientificProductDeclaration
from lab_sync_acquisition.opencv_camera import SeeedIMX219OpenCVCameraAdapter, OpenCVCameraConfig
from lab_sync_acquisition.session import ExperimentConfiguration, ScientificOutputSelection
from lab_sync_acquisition.storage import PersistentStorageManager
from tests import test_sustained_acquisition as sustained


class ExpectedSizeRecordingTests(unittest.TestCase):
    def test_representative_finalized_camera_recordings(self):
        cases = (([2, 4, 3], "uint8", 1, 1),
                 ([48, 64], "uint16", 32, 8),
                 ([480, 640, 3], "uint8", 4, 1),
                 ([480, 640, 3], "uint8", 60, 8),
                 ([720, 1280, 3], "uint8", 8, 4),
                 ([24, 32], "float32", 256, 16))
        for shape, dtype, count, batch in cases:
            with self.subTest(shape=shape, dtype=dtype, count=count), tempfile.TemporaryDirectory() as root:
                owner = LocalStorageManager(root, "session", "node", max_buffered_rows=batch)
                manifest = owner.create_stream(session_id="session", experiment_id="experiment",
                    acquisition_node_id="node", source_component_id="camera", data_product_id="frames",
                    artifact_type="camera_frames", schema={"frame_shape": shape, "frame_dtype": dtype},
                    storage_format="hdf5")
                frame = np.zeros(shape, dtype=dtype)
                owner.append_rows(manifest.storage_id, ({"frame": frame, "frame_index": i,
                    "experiment_id": "experiment", "session_time_s": i / 30,
                    "experiment_time_s": i / 30, "acquisition_node_local_time_s": 100 + i / 30,
                    "timestamp_status": "mapped", "width": shape[1], "height": shape[0],
                    "channels": shape[2] if len(shape) == 3 else 1, "dtype": dtype,
                    "backend": "synthetic", "requested_fps": 30, "reported_fps": 30,
                    "exposure": -6.0, "gain": 1.0} for i in range(count)))
                finalized = owner.finalize_stream(manifest.storage_id)
                raw = frame.nbytes * count
                files = [Path(p) for p in finalized.local_managed_paths]
                actual = sum(p.stat().st_size for p in files)
                with h5py.File(finalized.local_storage_path) as saved:
                    self.assertEqual(saved["frames"].shape[0], count)
                    np.testing.assert_array_equal(saved["frames"][-1], frame)
                self.assertGreater(actual, raw)
                profile = camera_storage_estimate({"frame_shape": shape, "frame_dtype": dtype})
                estimate = profile["fixed_bytes"] + (count + batch) * profile["bytes_per_observation"]
                print(json.dumps({"shape": shape, "dtype": dtype, "frames": count,
                    "batch": batch, "raw_bytes": raw, "stored_bytes": actual,
                    "estimated_bytes": estimate, "overhead_bytes": actual - raw}), flush=True)
                self.assertGreaterEqual(estimate, actual)
                owner.cleanup()


class ExpectedSizeOwnerTests(unittest.TestCase):
    def node(self, *, metadata=True):
        schema = {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}
        product = ScientificProductDeclaration("frames", "camera_frames", schema, "hdf5",
            storage_requirements={"capacity_estimate": camera_storage_estimate(schema)} if metadata else None)
        declaration = DeviceDeclaration("camera", "opencv", True, True, ("camera_frames",), (product,))
        adapter = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", ("camera_frames",), True)
        owner = AcquisitionNode(device_manager=DeviceManager((adapter,)), node_id="node", role="acquisition",
            synchronization_source_id="sync", device_declarations=(declaration,),
            deployment_device_configurations={"camera": OpenCVCameraConfig(0, 0, 2, fps=10)})
        return owner, adapter, product

    def config(self, duration=2, **kwargs):
        return ExperimentConfiguration(duration, participating_devices={"node": ["camera"]}, **kwargs)

    def test_preparation_is_read_only_and_reflects_effective_settings(self):
        node, adapter, product = self.node()
        output = ScientificOutputSelection("camera", "node", "frames")
        initial = node.status(), node.get_inventory()
        with patch.object(adapter, "initialize", side_effect=AssertionError("must not initialize")):
            report = node.estimate_experiment_storage((output,), self.config())
            self.assertTrue(report["valid"])
            self.assertEqual(report["estimated_bytes"], 131072 + 22 * (48 + 4096))
            larger = self.config(4, device_configurations={"node": {"camera": {"frame_width": 8, "fps": 20}}})
            self.assertEqual(node.estimate_experiment_storage((output,), larger)["estimated_bytes"],
                             131072 + 82 * (96 + 4096))
            self.assertEqual(node.estimate_experiment_storage((), self.config())["estimated_bytes"], 0)
            self.assertEqual(node.estimate_experiment_storage((output,), self.config(recording_budgets={"node": 1})), report)
        self.assertEqual((node.status(), node.get_inventory()), initial)
        self.assertEqual(product.schema["frame_shape"], [2, 4, 3])
        self.assertEqual(adapter.state.value, "declared")

    def test_missing_rate_metadata_and_invalid_output_remain_distinct(self):
        output = ScientificOutputSelection("camera", "node", "frames")
        node, _, _ = self.node(metadata=False)
        missing = node.estimate_experiment_storage((output,), self.config())
        self.assertTrue(missing["valid"])
        self.assertIsNone(missing["estimated_bytes"])
        invalid = node.estimate_experiment_storage((replace(output, source_device_id="unknown"),), self.config())
        self.assertFalse(invalid["valid"])
        node, _, _ = self.node()
        missing = node.estimate_experiment_storage((output,), self.config(
            device_configurations={"node": {"camera": {"fps": None}}}))
        self.assertIsNone(missing["estimated_bytes"])

    def test_preservation_roots_automatic_minima_and_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            science = Path(root) / "science"
            science.mkdir()
            storage = PersistentStorageManager(Path(root) / "evidence", global_artifact_root=science)
            estimates = [{"node_id": "one", "valid": True, "estimated_bytes": 200000},
                         {"node_id": "two", "valid": True, "estimated_bytes": 300000}]
            report = storage.estimate_experiment_storage(estimates, storage_location="default")
            self.assertTrue(report["available"], report)
            self.assertEqual({d["destination"]: d["required_bytes"] for d in report["destinations"]},
                             {str(science): 500000, str(Path(root) / "evidence"): 131072})
            self.assertFalse(storage.check_experiment_capacity(499999, recording_estimates=estimates)["ready"])
            self.assertTrue(storage.check_experiment_capacity(500000, recording_estimates=estimates)["ready"])
            auto = storage.check_experiment_capacity(None, recording_estimates=estimates)
            self.assertTrue(auto["ready"])
            validate_storage_capacity((auto,))
            for free in (None, 499999):
                with patch('lab_sync_acquisition.local_storage.shutil.disk_usage', return_value=SimpleNamespace(free=free)):
                    self.assertFalse(storage.check_experiment_capacity(None, recording_estimates=estimates)['ready'])
            with patch('lab_sync_acquisition.local_storage.shutil.disk_usage', return_value=SimpleNamespace(free=600000)), \
                 patch('lab_sync_acquisition.local_storage._local_filesystem_identity', return_value=['host', 'volume']):
                report = storage.check_experiment_capacity(None, recording_estimates=estimates)
                with self.assertRaisesRegex(RuntimeError, 'shared-filesystem'):
                    validate_storage_capacity((report,))
            missing = [{"valid": True, "estimated_bytes": None}]
            self.assertFalse(storage.check_experiment_capacity(None, recording_estimates=missing)["ready"])
            self.assertTrue(storage.check_experiment_capacity(500000, recording_estimates=missing)["ready"])


class ExpectedSizeBrokerWorkflows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = sustained.SustainedAcquisitionTests()
        schema = {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}
        self.fixture.scientific_product = ScientificProductDeclaration("frames", "camera_frames", schema, "hdf5",
            storage_requirements={"capacity_estimate": camera_storage_estimate(schema)})
        self.fixture.before_launch = self.check_pre_session
        self.fixture.addCleanup = self.addCleanup
        self.fixture.addAsyncCleanup = self.addAsyncCleanup
        await self.fixture.asyncSetUp()

    async def check_pre_session(self, f):
        second, adapter, product = ExpectedSizeOwnerTests().node()
        # Independent owner with a distinct configured node identity.
        second = AcquisitionNode(device_manager=DeviceManager((adapter,)), node_id="second", role="acquisition",
            synchronization_source_id="sync", device_declarations=second.declared_devices,
            deployment_device_configurations={"camera": OpenCVCameraConfig(0, 0, 2, fps=10)})
        boundary = sustained._Boundary("acquisition_node", "second", f.broker)
        boundary._client, boundary._jetstream = f.pc._client, f.pc._jetstream
        boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
        sustained.ServiceMaintenanceInterface(second, sustained.RuntimeParticipant("acquisition_node", "second"),
            ingestor=f.ingestor, storage_manager=f.storage, preservation_window_s=2,
            close_resources=sustained.AsyncMock(return_value=True))
        handler = sustained.NatsAcquisitionNodeCommunication(boundary, second)
        await handler.subscribe_commands()
        configuration = ExperimentConfiguration(2, participating_devices={"node": ["camera"], "second": ["camera"]},
            device_configurations={"node": {"camera": {"fps": 10}}})
        outputs = [ScientificOutputSelection("camera", n, "frames").to_dict() for n in ("node", "second")]
        result = await f.controller.estimate_experiment_storage(configuration.to_dict(), outputs, "default",
            communication=f.communication, participants=(f.target, sustained.RuntimeParticipant("acquisition_node", "second")),
            storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"), result_window_s=2)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["expected_bytes"], (131072 + 21 * 4144) + (131072 + 22 * 4144))
        self.assertTrue(result.details["preservation"]["available"])
        self.assertIsNone(f.node.local_storage_manager)
        self.assertIsNone(second.local_storage_manager)
        self.assertEqual(f.camera.capture.read_count, 0)

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()
        self.fixture.doCleanups()

    async def test_controller_readback_and_automatic_recording_admission(self):
        f = self.fixture
        config = ExperimentConfiguration(60, participating_devices={"node": ["camera"]},
            device_configurations={"node": {"camera": {"fps": 2}}})
        outputs = [ScientificOutputSelection("camera", "node", "frames")]
        report = await f.controller.estimate_experiment_storage(config.to_dict(), [o.to_dict() for o in outputs], "default",
            communication=f.communication, participants=(f.target,),
            storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"),
            result_window_s=2, expected_session_id=f.sid)
        self.assertTrue(report.succeeded, report.error)
        self.assertEqual(report.details["expected_bytes"], 131072 + 121 * 4144)
        self.assertTrue(report.details["preservation"]["available"])
        self.assertEqual(f.camera.capture.read_count, 0)
        self.assertEqual(f.local.manifests, ())
        bad = replace(config, recording_budgets={"node": 1})
        rejected = await f.controller.start_launched_experiment("small", configuration=bad,
            scientific_outputs=outputs,
            storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"))
        self.assertFalse(rejected.succeeded)
        self.assertIn("below the automatic", rejected.error)
        original = f.camera.VideoCapture
        def reopen(*args):
            f.camera.capture.opened = True
            f.camera.capture.released = False
            return original(*args)
        with patch.object(f.camera, "VideoCapture", side_effect=reopen):
            accepted = await f.controller.start_launched_experiment("auto", configuration=config,
                scientific_outputs=outputs,
                storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(accepted.succeeded, accepted.error)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        self.assertTrue((await f.controller.stop_launched_experiment("auto")).succeeded)
        self.assertIsNone(config.recording_budgets)
        self.assertIsNone(config.preservation_budget_bytes)
        self.assertGreaterEqual(len(f.saved("auto")[0]), 2)
        larger = replace(config, recording_budgets={"node": report.details["expected_bytes"] + 1},
                         preservation_budget_bytes=report.details["expected_bytes"] + 1)
        with patch.object(f.camera, "VideoCapture", side_effect=reopen):
            accepted = await f.controller.start_launched_experiment("larger", configuration=larger,
                scientific_outputs=outputs, storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(accepted.succeeded, accepted.error)
        self.assertTrue((await f.controller.stop_launched_experiment("larger")).succeeded)

    async def test_missing_estimate_is_not_a_partial_aggregate(self):
        f = self.fixture
        config = ExperimentConfiguration(2, participating_devices={"node": ["camera"]})
        result = await f.controller.estimate_experiment_storage(config.to_dict(),
            [ScientificOutputSelection("camera", "node", "frames").to_dict()], "default",
            communication=f.communication, participants=(f.target,),
            storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"),
            result_window_s=2, expected_session_id=f.sid)
        self.assertTrue(result.succeeded, result.error)
        self.assertIsNone(result.details["expected_bytes"])
        self.assertFalse(result.details["preservation"]["available"])
        self.assertEqual(f.camera.capture.read_count, 0)

    async def test_invalid_owner_size_or_wrong_session_cannot_supply_complete_estimate(self):
        f = self.fixture
        config = ExperimentConfiguration(2, participating_devices={"node": ["camera"]},
            device_configurations={"node": {"camera": {"fps": 10}}})
        arguments = dict(communication=f.communication, participants=(f.target,),
            storage_participant=sustained.RuntimeParticipant("storage_manager", "storage"), result_window_s=2)
        outputs = [ScientificOutputSelection("camera", "node", "frames").to_dict()]
        wrong = await f.controller.estimate_experiment_storage(config.to_dict(), outputs, "default",
            expected_session_id="different", **arguments)
        self.assertFalse(wrong.succeeded)
        def corrupt(operation, result):
            if operation == "estimate_experiment_storage" and result['source_id'] == 'node':
                result['payload']['estimate']['estimated_bytes'] = -1
            return result
        f.broker.change_result = corrupt
        result = await f.controller.estimate_experiment_storage(config.to_dict(), outputs, "default",
            expected_session_id=f.sid, **arguments)
        self.assertTrue(result.succeeded, result.error)
        self.assertIsNone(result.details['expected_bytes'])
        self.assertFalse(result.details['preservation']['available'])
