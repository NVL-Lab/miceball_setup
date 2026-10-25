"""Per-Experiment storage readiness and independently enforced recording deadlines."""

import asyncio
import json
from itertools import repeat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import ExperimentConfiguration, ScientificProductDeclaration, ScientificOutputSelection
from lab_sync_acquisition import RuntimeEvidenceMessage, PersistentStorageManager
from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, InMemoryIngestor,
    OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter, SessionConfig, SynchronizationManager,
)
from lab_sync_acquisition.device_adapter import DeviceReadiness
from lab_sync_acquisition.local_storage import inspect_storage_capacity, validate_storage_capacity
from tests import test_sustained_acquisition as sustained
from tests import test_scientific_acquisition_persistence as scientific
from tests.test_scientific_camera_collection import FakeCV2


class LocalActivationFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.frame = np.arange(24, dtype=np.uint16).reshape(2, 4, 3)
        self.camera = FakeCV2(repeat(self.frame), {})
        self.adapter = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frames",), True, cv2_module=self.camera)
        manager = DeviceManager((self.adapter,))
        self.assertTrue(all(r.succeeded for r in manager.initialize_all(OpenCVCameraConfig(0, 0, 1))))
        products = tuple(ScientificProductDeclaration(name, "camera_frames",
            {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5") for name in ("frames", "second"))
        declarations = (DeviceDeclaration("camera", "opencv", True, True, ("camera_frames",), products),)
        config = SessionConfig(declarations, str(root / "runtime.jsonl"), {},
            str(root / "errors"), session_id="session")
        self.storage = PersistentStorageManager(root / "storage")
        self.ingestor = InMemoryIngestor(self.storage)
        self.sync = SynchronizationManager()
        self.node = AcquisitionNode("session", manager, self.sync, self.ingestor, node_id="node",
            error_evidence_location=config.error_evidence_location, default_local_storage_root=root / "local",
            device_declarations=declarations)
        self.controller = Controller(self.node, self.ingestor, self.storage, root / "session.json",
            synchronization_manager=self.sync)
        self.assertTrue(self.controller.create_session(config).succeeded)
        ready = self.node.check_ready()
        self.assertTrue(self.controller.initialize_session(ready["device_readiness"], ready["service_readiness"]).succeeded)
        self.assertTrue(self.controller.start_session().succeeded)
        self.local = self.node.local_storage_manager
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.node.status()["is_running"]:
            self.node.stop_runtime()
        self.local.cleanup()

    def start(self, identity, *, both=False):
        outputs = tuple(ScientificOutputSelection("camera", "node", name)
                        for name in (("frames", "second") if both else ("frames",)))
        return self.controller.start_experiment(identity, scientific_outputs=outputs,
            configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000, participating_devices={"node": ["camera"]}))

    def assert_resolved(self, result, identity, *, confirmed=True):
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        self.assertFalse(self.node.scientific_acquisition_active)
        self.assertIsNone(self.node.status()["active_experiment_runtime_context"])
        events = [e for e in self.controller.get_status()["experiment_lifecycle_evidence"]
                  if e.experiment_id == identity]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
        self.assertIsNone(events[-1].session_time_s)
        self.assertTrue(events[-1].details["end_time_unconfirmed"])
        self.assertEqual(result.details["cleanup_confirmed"], confirmed)
        self.assertEqual(self.camera.capture.read_count, 0)
        if confirmed:
            self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))

    def record_next(self):
        previous = {Path(m.local_storage_path): Path(m.local_storage_path).read_bytes()
                    for m in self.local.manifests}
        self.assertTrue(self.start("next").succeeded)
        self.assertTrue(self.controller.run_one_iteration().succeeded)
        self.assertTrue(self.controller.stop_experiment("next").succeeded)
        manifest, = [m for m in self.local.manifests if m.experiment_id == "next"]
        self.assertEqual(manifest.lifecycle_state, "finalized")
        events = [e for e in self.controller.get_status()["experiment_lifecycle_evidence"]
                  if e.experiment_id == "next"]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_stop"])
        self.assertIsNotNone(events[-1].session_time_s)
        self.assertTrue(all(path.read_bytes() == data for path, data in previous.items()))
        with h5py.File(manifest.local_storage_path) as saved:
            np.testing.assert_array_equal(saved["frames"][0], self.frame)
            row = json.loads(saved["record_metadata_json"][0])
            self.assertEqual(row["experiment_id"], "next")
            self.assertEqual(row["session_id"], "session")

    def test_local_readiness_loss_resolves_start_and_allows_recording(self):
        ready = self.adapter.check_ready
        calls = 0

        def lose_readiness():
            nonlocal calls
            calls += 1
            if calls == 2:
                return DeviceReadiness("camera", False, "Readiness lost at activation", ("camera_frames",))
            return ready()

        with patch.object(self.adapter, "check_ready", side_effect=lose_readiness):
            result = self.start("activation-failed")
        self.assertIn("ready, running devices", result.error)
        self.assert_resolved(result, "activation-failed")
        self.record_next()

    def test_local_mapping_failure_resolves_without_another_clock_read(self):
        with patch.object(self.sync, "local_deadline_for_session_time", side_effect=RuntimeError("Mapping unavailable")):
            result = self.start("mapping-failed")
        self.assertIn("Mapping unavailable", result.error)
        self.assert_resolved(result, "mapping-failed")
        self.record_next()

    def test_failure_after_context_activation_clears_context_and_deadline(self):
        activate = self.node.activate_experiment_runtime

        def activate_then_fail(*args):
            activate(*args)
            raise OSError("Activation confirmation failed")

        with patch.object(self.node, "activate_experiment_runtime", side_effect=activate_then_fail):
            result = self.start("context-failed")
        self.assertIn("Activation confirmation failed", result.error)
        self.assert_resolved(result, "context-failed")
        self.assertFalse(self.node.expire_experiment_if_due())
        self.record_next()

    def test_activation_cleanup_failure_retains_products_and_reports_unconfirmed(self):
        finalize = self.local.finalize_stream

        def finalize_one(storage_id):
            if storage_id == self.local.manifests[1].storage_id:
                raise OSError("Injected scientific finalization failure")
            return finalize(storage_id)

        with patch.object(self.sync, "local_deadline_for_session_time", side_effect=RuntimeError("Mapping unavailable")), \
             patch.object(self.local, "finalize_stream", side_effect=finalize_one):
            result = self.start("cleanup-failed", both=True)
        self.assertIn("Mapping unavailable", result.error)
        self.assert_resolved(result, "cleanup-failed", confirmed=False)
        self.assertIn("Injected scientific finalization failure", result.details["cleanup_error"])
        self.assertEqual([m.lifecycle_state for m in self.local.manifests], ["finalized", "open"])
        paths = [Path(m.local_storage_path) for m in self.local.manifests]
        self.assertTrue(all(p.exists() for p in paths))
        self.node.finalize_experiment_scientific_outputs("cleanup-failed")
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))
        self.assertEqual(len([e for e in self.controller.get_status()["experiment_lifecycle_evidence"]
                              if e.event_type == "experiment_fail"]), 1)
        self.record_next()


class ExperimentCapacityTests(unittest.TestCase):
    def test_configuration_requires_a_finite_duration_and_explicit_valid_budgets(self):
        for duration in (None, True, 0, -1, float("nan"), float("inf")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                ExperimentConfiguration(duration, participating_devices={"node": ["camera"]})
        for budget in (True, -1, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                ExperimentConfiguration(1, {"node": budget}, participating_devices={"node": ["camera"]})
        config = ExperimentConfiguration(2, {"node": 100}, 200, participating_devices={"node": ["camera"]})
        self.assertEqual(config, ExperimentConfiguration.from_dict(config.to_dict()))

    def test_encoded_estimate_uses_duration_selected_rate_and_inflight_batch(self):
        product = ScientificProductDeclaration("frames", "camera_frames",
            {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5",
            expected_data_size_bytes=999999, storage_requirements={
                "capacity_estimate": {"fixed_bytes": 100, "bytes_per_observation": 80}})
        self.assertEqual(product.estimate_storage_bytes(2, {"fps": 5, "frames_per_collect": 1}), 980)
        self.assertEqual(product.estimate_storage_bytes(4, {"fps": 5, "frames_per_collect": 1}), 1780)
        self.assertEqual(product.estimate_storage_bytes(2, {"fps": 10, "frames_per_collect": 1}), 1780)
        for parameters in ({"fps": None, "frames_per_collect": 1},
                           {"fps": 5, "frames_per_collect": 1, "frame_width": 8}):
            with self.assertRaises(ValueError):
                product.estimate_storage_bytes(2, parameters)
        self.assertEqual(product.expected_data_size_bytes, 999999)

    def test_capacity_preserves_writability_and_unknown_space_failures(self):
        with tempfile.TemporaryDirectory() as root:
            for free, ready in ((1000, True), (99, False), (None, False)):
                with self.subTest(free=free), patch("lab_sync_acquisition.local_storage.shutil.disk_usage",
                        return_value=SimpleNamespace(free=free)):
                    report = inspect_storage_capacity(root, 100)
                    self.assertEqual(report["ready"], ready)
            with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", side_effect=OSError("unavailable")):
                self.assertFalse(inspect_storage_capacity(root, 100)["ready"])
            with patch("lab_sync_acquisition.local_storage._local_filesystem_identity", side_effect=RuntimeError("shared mount")):
                self.assertFalse(inspect_storage_capacity(root, 100)["ready"])
            file = Path(root) / "file"
            file.write_bytes(b"not a writable directory")
            self.assertFalse(inspect_storage_capacity(file, 100)["ready"])

    def test_shared_filesystem_sums_writes_not_free_space(self):
        one = {"ready": True, "filesystem_id": ["host", "volume"],
               "required_bytes": 70, "available_bytes": 100}
        with self.assertRaises(RuntimeError):
            validate_storage_capacity((one, one))
        validate_storage_capacity((one, {**one, "filesystem_id": ["other-host", "volume"]}))
        validate_storage_capacity(({**one, "required_bytes": 40}, {**one, "required_bytes": 60}))

    def test_local_initialization_after_node_construction_supports_recording(self):
        fixture = scientific.ScientificAcquisitionPersistenceTests()
        with fixture.workflow(initialize_after_node=True) as (controller, node, _, capture):
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            self.assertEqual(capture.read_count, 1)
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.lifecycle_state, "finalized")
            self.assertEqual(fixture.saved_metadata(node)[0]["experiment_id"], "experiment")

    def test_preservation_roots_on_one_filesystem_sum_distinct_writes(self):
        with tempfile.TemporaryDirectory() as root:
            owner = PersistentStorageManager(Path(root) / "evidence",
                global_artifact_root=Path(root) / "science")
            with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", return_value=SimpleNamespace(free=150)), \
                 patch("lab_sync_acquisition.local_storage._local_filesystem_identity", return_value=["host", "volume"]):
                report = owner.check_experiment_capacity(100)
                with self.assertRaisesRegex(RuntimeError, "shared-filesystem"):
                    validate_storage_capacity((report,))
            with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", return_value=SimpleNamespace(free=200)), \
                 patch("lab_sync_acquisition.local_storage._local_filesystem_identity", return_value=["host", "volume"]):
                validate_storage_capacity((owner.check_experiment_capacity(100),))


class ExperimentPreflightWorkflows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = sustained.SustainedAcquisitionTests()
        await self.fixture.asyncSetUp()
        self.target = sustained.RuntimeParticipant("storage_manager", "storage")
        self.output = ScientificOutputSelection("camera", "node", "frames")

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()
        self.fixture.doCleanups()

    async def start(self, name="experiment", configuration=None, outputs=None):
        return await self.fixture.controller.start_launched_experiment(name,
            configuration=configuration, scientific_outputs=(self.output,) if outputs is None else outputs,
            storage_participant=self.target)

    async def test_sufficient_budgets_and_each_experiment_is_checked_again(self):
        f = self.fixture
        config = ExperimentConfiguration(60, {"node": 100}, 100, participating_devices={"node": ["camera"]})
        self.assertTrue((await self.start(configuration=config)).succeeded)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
        with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", return_value=SimpleNamespace(free=150)):
            result = await self.start("second", config)
        self.assertFalse(result.succeeded)
        self.assertIn("shared-filesystem", result.error)
        self.assertEqual(f.controller.get_status()["session_state"], "running")

    async def test_missing_configuration_or_budget_never_begins_recording(self):
        f = self.fixture
        for config in (None, ExperimentConfiguration(1, participating_devices={"node": ["camera"]}), ExperimentConfiguration(1, {"node": 100}, participating_devices={"node": ["camera"]})):
            result = await self.start(configuration=config)
            self.assertFalse(result.succeeded, result)
            self.assertFalse(f.node.scientific_acquisition_active)
        self.assertEqual(f.camera.capture.read_count, 0)

    async def test_insufficient_recording_and_preservation_are_reported(self):
        for config in (ExperimentConfiguration(1, {"node": 1000}, 1, participating_devices={"node": ["camera"]}),
                       ExperimentConfiguration(1, {"node": 1}, 1000, participating_devices={"node": ["camera"]})):
            with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", return_value=SimpleNamespace(free=100)):
                result = await self.start(configuration=config)
            self.assertFalse(result.succeeded)
            self.assertIn("capacity", result.error.lower())
            self.assertIn("rejection_evidence", result.details)
        self.assertEqual(self.fixture.camera.capture.read_count, 0)

    async def test_unknown_capacity_and_failed_synchronization_block_start(self):
        config = ExperimentConfiguration(1, {"node": 100}, 100, participating_devices={"node": ["camera"]})
        with patch("lab_sync_acquisition.local_storage.shutil.disk_usage", side_effect=OSError("unavailable")):
            self.assertFalse((await self.start(configuration=config)).succeeded)
        with patch.object(self.fixture.clock, "assess_cross_clock_exchanges", side_effect=RuntimeError("unconfirmed sync")):
            result = await self.start(configuration=config)
            self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.camera.capture.read_count, 0)

    async def test_operating_overrides_are_selected_per_experiment_and_do_not_leak(self):
        f = self.fixture
        config = ExperimentConfiguration(60, {"node": 1000000}, 1000,
            {"node": {"camera": {"fps": 5}}}, participating_devices={"node": ["camera"]})
        original = f.camera.VideoCapture

        def reopen(*args):
            f.camera.capture.opened = True
            f.camera.capture.released = False
            return original(*args)

        with patch.object(f.camera, "VideoCapture", side_effect=reopen):
            result = await self.start(configuration=config)
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(f.adapter.initialization_config.fps, 5)
            await f.until(lambda: f.camera.capture.read_count >= 2)
            self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
            result = await self.start("second", ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))
            self.assertTrue(result.succeeded, result.error)
            self.assertIsNone(f.adapter.initialization_config.fps)

    async def failed_preparation_then_record(self, phase, next_fps, identity):
        """Retry explicitly after a device transition fails, using public Experiment commands."""
        f = self.fixture
        reopen = f.camera.VideoCapture
        initialize = f.adapter.initialize
        start = f.adapter.start
        ready = f.adapter.check_ready

        def open_camera(*args):
            f.camera.capture.opened = True
            f.camera.capture.released = False
            return reopen(*args)

        def initialize_device(parameters):
            if phase == "initialize_before":
                raise OSError("Injected initialization failure")
            initialize(parameters)
            if phase == "initialize_after":
                raise OSError("Injected failure after initialization")

        def check_ready():
            if phase == "readiness":
                return DeviceReadiness("camera", False, "Injected readiness failure", ("camera_frames",))
            return ready()

        def start_device():
            if phase == "start_before":
                raise OSError("Injected start failure")
            if phase != "start_without_running":
                start()
            if phase == "start_after":
                raise OSError("Injected failure after start")

        with patch.object(f.camera, "VideoCapture", side_effect=open_camera):
            count = f.camera.capture.read_count
            with patch.object(f.adapter, "initialize", side_effect=initialize_device), \
                 patch.object(f.adapter, "check_ready", side_effect=check_ready), \
                 patch.object(f.adapter, "start", side_effect=start_device):
                result = await self.start(identity + "-failed", ExperimentConfiguration(60,
                    {"node": 1000000}, 1000, {"node": {"camera": {"fps": 5}}}, participating_devices={"node": ["camera"]}))
            self.assertFalse(result.succeeded)
            self.assertIsNone(f.controller.get_status()["active_experiment_id"])
            self.assertFalse(f.node.scientific_acquisition_active)
            self.assertEqual(f.camera.capture.read_count, count)
            overrides = None if next_fps is None else {"node": {"camera": {"fps": next_fps}}}
            count = f.camera.capture.read_count
            result = await self.start(identity + "-recovered", ExperimentConfiguration(60,
                {"node": 1000000}, 1000, overrides, participating_devices={"node": ["camera"]}))
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(f.adapter.initialization_config.fps, next_fps)
            self.assertEqual(f.adapter.state.value, "running")
            await f.until(lambda: f.camera.capture.read_count >= count + 2)
            self.assertTrue((await f.controller.stop_launched_experiment(identity + "-recovered")).succeeded)
            frames, rows = f.saved(identity + "-recovered")
            self.assertGreaterEqual(len(frames), 2)
            self.assertTrue(all(row["experiment_id"] == identity + "-recovered" for row in rows))

    async def test_failed_first_override_cannot_replace_session_baseline(self):
        self.assertIsNone(self.fixture.adapter.initialization_config.fps)
        await self.failed_preparation_then_record("readiness", None, "baseline")

    async def test_explicit_repreparation_recovers_device_transition_failures(self):
        for phase in ("initialize_before", "initialize_after", "readiness",
                      "start_before", "start_after", "start_without_running"):
            for next_fps in (None, 7):
                with self.subTest(phase=phase, next_fps=next_fps):
                    await self.failed_preparation_then_record(phase, next_fps, f"{phase}-{next_fps}")
        # Successful recovery overrides still must not become Session defaults.
        await self.failed_preparation_then_record("readiness", None, "final-baseline")

    async def test_activation_rechecks_readiness_after_preparation(self):
        f = self.fixture
        ready = f.adapter.check_ready
        activating = False

        def on_command(command):
            nonlocal activating
            if command["command_type"] == "activate_experiment_runtime":
                activating = True

        def check_ready():
            if activating:
                return DeviceReadiness("camera", False, "Readiness lost after preparation", ("camera_frames",))
            return ready()

        f.broker.on_command = on_command
        try:
            with patch.object(f.adapter, "check_ready", side_effect=check_ready):
                result = await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))
        finally:
            f.broker.on_command = None
        self.assertFalse(result.succeeded)
        self.assertFalse(f.node.scientific_acquisition_active)
        self.assertIsNone(f.controller.get_status()["active_experiment_id"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in f.local.manifests))
        self.assertEqual(f.camera.capture.read_count, 0)

    async def test_failed_expiry_finalization_is_not_canonical_completion(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        with patch.object(f.local, "finalize_stream", side_effect=OSError("unconfirmed")), \
             patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12), \
             self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
            await f.until(lambda: not f.handler.acquisition_execution_active)
        proof = f.node.read_experiment_expiry("experiment")
        self.assertFalse(proof.payload["finalization_confirmed"])
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
        self.assertFalse(f.node.status()["is_running"])
        self.assertTrue(f.camera.capture.released)

    async def test_resolution_must_match_stored_representation_even_with_budget(self):
        config = ExperimentConfiguration(60, {"node": 1000000}, 1000,
            {"node": {"camera": {"frame_width": 8}}}, participating_devices={"node": ["camera"]})
        result = await self.start(configuration=config)
        self.assertFalse(result.succeeded)
        self.assertIn("representation", result.error)
        self.assertEqual(self.fixture.camera.capture.read_count, 0)

    async def test_ended_preparation_cannot_reconfigure_a_device(self):
        f = self.fixture
        config = ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]})
        self.assertTrue((await self.start(configuration=config)).succeeded)
        self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
        original = f.adapter.initialization_config
        altered = ExperimentConfiguration(60, {"node": 1000000}, 1000,
            {"node": {"camera": {"fps": 12}}}, participating_devices={"node": ["camera"]})
        result = await f.request("prepare_experiment_scientific_outputs", {
            "experiment_id": "experiment", "scientific_outputs": [self.output.to_dict()],
            "configuration": altered.to_dict()})
        self.assertFalse(result.success)
        self.assertEqual(f.adapter.initialization_config, original)
        self.assertTrue(f.camera.capture.isOpened())

    async def test_expiry_finalizes_locally_and_controller_reconciles_only_experiment(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        context = f.node.status()["active_experiment_runtime_context"]
        mapping = f.node.mapping_activation_history[-1]["mapping"]
        deadline = mapping["local_time_anchor_s"] + (
            context.experiment_start_session_time_s + context.duration_s - mapping["session_time_anchor_s"]) / mapping["scale"]
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=deadline + 1):
            await f.until(lambda: not f.handler.acquisition_execution_active)
        frames, rows = f.saved()
        self.assertGreaterEqual(len(frames), 2)
        proof = f.node.read_experiment_expiry("experiment")
        self.assertIsNotNone(proof)
        self.assertEqual(proof.payload["session_deadline_s"], context.experiment_start_session_time_s + 60)
        self.assertEqual(proof.payload["mapping"], mapping)
        self.assertEqual(f.controller.get_status()["session_state"], "running")
        ends = [e for e in f.controller.get_status()["experiment_lifecycle_evidence"] if e.event_type == "experiment_stop"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0].session_time_s, proof.payload["session_deadline_s"])
        self.assertFalse(f.controller.accept_experiment_expiry(proof))
        self.assertEqual(len([e for e in f.controller.get_status()["experiment_lifecycle_evidence"] if e.event_type == "experiment_stop"]), 1)
        bad = replace(proof, payload={**proof.payload, "duration_s": 1})
        with self.assertRaises(ValueError):
            f.controller.accept_experiment_expiry(bad)
        later = await self.start("later", ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))
        self.assertTrue(later.succeeded, later.error)
        self.assertFalse(f.controller.accept_experiment_expiry(proof))
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "later")

    async def test_bounded_iteration_enforces_the_same_prepared_deadline(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        await f.handler.stop_acquisition_execution()
        count = f.camera.capture.read_count
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12):
            result = await f.request("run_one_iteration")
        self.assertTrue(result.success, result.reason)
        self.assertEqual(result.payload["scientific_observations"], 0)
        self.assertEqual(f.camera.capture.read_count, count)
        self.assertTrue(f.node.status()["is_running"])
        self.assertIsNotNone(f.node.read_experiment_expiry("experiment"))

    async def test_offline_controller_and_degraded_sync_do_not_disable_captured_deadline(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        subscription = next(s for s in f.broker.subscriptions if s.subject.endswith(".experiment_duration_expired"))
        subscription.active = False
        f.pc.available = False
        quality = f.clock.mark_synchronization_unavailable(f.sid, "node", "sync", "offline")
        f.node.accept_synchronization_quality(f.sid, "sync", quality)
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12):
            await f.until(lambda: not f.handler.acquisition_execution_active)
        count = f.camera.capture.read_count
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
        self.assertTrue(f.node.status()["is_running"])
        f.pc.available = True
        self.assertTrue(await f.controller.reconcile_launched_experiment_expiry("experiment"))
        self.assertEqual(f.camera.capture.read_count, count)
        self.assertIsNone(f.controller.get_status()["active_experiment_id"])

    async def test_publication_wait_cannot_extend_recording_deadline(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(0.2, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        entered = asyncio.Event()

        async def unavailable():
            entered.set()
            await asyncio.Event().wait()

        with patch.object(f.handler, "publish_new_runtime_evidence", side_effect=unavailable):
            await entered.wait()
            await asyncio.sleep(0.3)
            self.assertFalse(f.node.scientific_acquisition_active)
            self.assertIsNotNone(f.node.read_experiment_expiry("experiment"))
            await f.handler.stop_acquisition_execution()
        self.assertFalse(f.node.scientific_acquisition_active)
        self.assertIsNotNone(f.node.read_experiment_expiry("experiment"))
        self.assertTrue(await f.controller.reconcile_launched_experiment_expiry("experiment"))

    async def test_malformed_or_contradictory_expiry_cannot_end_recording(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        await f.until(lambda: f.camera.capture.read_count >= 2)
        context = f.node.status()["active_experiment_runtime_context"]
        mapping = f.node.mapping_activation_history[-1]["mapping"]
        end = context.experiment_start_session_time_s + context.duration_s
        local_end = mapping["local_time_anchor_s"] + (end - mapping["session_time_anchor_s"]) / mapping["scale"]
        payload = {"experiment_id": "experiment", "duration_s": 60,
            "experiment_start_session_time_s": context.experiment_start_session_time_s,
            "session_deadline_s": end, "local_deadline_s": local_end,
            "finalized_local_time_s": local_end + 1, "mapping": mapping,
            "finalization_confirmed": True,
            "artifact_manifest_ids": [f.local.manifests[0].artifact_manifest_id]}
        for changes in ({"mapping": {}, "local_deadline_s": 0, "finalized_local_time_s": 1},
                        {"local_deadline_s": local_end - 1},
                        {"mapping": {**mapping, "scale": mapping["scale"] * 2}},
                        {"mapping": {**mapping, "acquisition_node_id": "other"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                f.controller.accept_experiment_expiry(RuntimeEvidenceMessage(
                    "malformed", f.sid, "experiment_duration_expired", "node", {**payload, **changes}, True))
            self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
            self.assertTrue(f.node.scientific_acquisition_active)
            self.assertEqual(f.local.manifests[0].lifecycle_state, "open")
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=local_end + 1):
            await f.until(lambda: not f.handler.acquisition_execution_active)
        self.assertIsNone(f.controller.get_status()["active_experiment_id"])
        self.assertFalse(f.controller.accept_experiment_expiry(f.node.read_experiment_expiry("experiment")))

    async def test_early_transport_timeout_followed_by_pending_publication_still_expires(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(0.2, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        pending = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def publication():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise asyncio.TimeoutError("transport timed out before expiry")
            pending.set()
            await release.wait()

        with patch.object(f.handler, "publish_new_runtime_evidence", side_effect=publication):
            await asyncio.wait_for(pending.wait(), 1)
            await asyncio.sleep(0.3)
            try:
                self.assertFalse(f.node.scientific_acquisition_active)
                self.assertIsNotNone(f.node.read_experiment_expiry("experiment"))
                self.assertEqual(f.local.manifests[0].lifecycle_state, "finalized")
            finally:
                release.set()
                await f.handler.stop_acquisition_execution()
        self.assertTrue(await f.controller.reconcile_launched_experiment_expiry("experiment"))
        self.assertGreaterEqual(len(f.saved()[0]), 1)

    async def test_delayed_expiry_uses_activation_mapping_after_resynchronization(self):
        f = self.fixture
        self.assertTrue((await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))).succeeded)
        mapping = f.node.mapping_activation_history[-1]["mapping"]
        context = f.node.status()["active_experiment_runtime_context"]
        deadline = mapping["local_time_anchor_s"] + (
            context.experiment_start_session_time_s + context.duration_s - mapping["session_time_anchor_s"]) / mapping["scale"]
        subscription = next(s for s in f.broker.subscriptions if s.subject.endswith(".experiment_duration_expired"))
        subscription.active = False
        result = await f.communication.request_runtime_command(
            sustained.RuntimeParticipant("synchronization_manager", "sync"), "resynchronize", f.sid,
            {"node_ids": ["node"]}, 2)
        self.assertTrue(result.success, result.reason)
        self.assertNotEqual(f.node.mapping_activation_history[-1]["mapping"], mapping)
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=deadline + 1):
            await f.until(lambda: not f.handler.acquisition_execution_active)
        self.assertEqual(f.node.read_experiment_expiry("experiment").payload["mapping"], mapping)
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
        self.assertTrue(await f.controller.reconcile_launched_experiment_expiry("experiment"))
        self.assertIsNone(f.controller.get_status()["active_experiment_id"])

    async def test_activation_deadline_must_use_authorized_synchronization_mapping(self):
        f = self.fixture

        def replace_mapping(operation, result):
            if operation == "activate_experiment_runtime":
                deadline = result["payload"]["deadline"]
                mapping = {**deadline["mapping"], "scale": deadline["mapping"]["scale"] * 2}
                result["payload"]["deadline"] = {**deadline, "mapping": mapping,
                    "local_deadline_s": mapping["local_time_anchor_s"] + (
                        deadline["session_deadline_s"] - mapping["session_time_anchor_s"]) / mapping["scale"]}
            return result

        f.broker.change_result = replace_mapping
        result = await self.start(configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000, participating_devices={"node": ["camera"]}))
        self.assertFalse(result.succeeded)
        self.assertIn("authorized synchronization mapping", result.error)
        self.assertFalse(f.node.scientific_acquisition_active)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in f.local.manifests))

    async def test_actual_scientific_preservation_destination_is_required(self):
        f = self.fixture
        destination = f.root / "scientific-preservation"
        owner = PersistentStorageManager(f.root / "storage", global_artifact_root=destination)
        # The existing adapter keeps its StorageManager owner; replace only its
        # public capacity inspection to exercise this configured destination.
        for free in (0, None, 10000):
            visited = []

            def capacity(path):
                path = Path(path)
                visited.append(path)
                return SimpleNamespace(free=free if path == destination else 10000)

            def filesystem(path):
                return ["host", "preservation" if Path(path) == destination else "recording"]

            with patch.object(f.storage, "check_experiment_capacity", side_effect=owner.check_experiment_capacity), \
                 patch("lab_sync_acquisition.local_storage.shutil.disk_usage", side_effect=capacity), \
                 patch("lab_sync_acquisition.local_storage._local_filesystem_identity", side_effect=filesystem):
                result = await self.start(configuration=ExperimentConfiguration(60, {"node": 100}, 100, participating_devices={"node": ["camera"]}))
            self.assertIn(destination, visited)
            self.assertEqual(result.succeeded, free == 10000, result.error)
            if result.succeeded:
                self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
            else:
                self.assertFalse(f.node.scientific_acquisition_active)

    async def test_idle_experiment_expires_without_camera_reads(self):
        f = self.fixture
        result = await self.start(configuration=ExperimentConfiguration(0.02, {"node": 0}, 1000, participating_devices={"node": ["camera"]}), outputs=())
        self.assertTrue(result.succeeded, result.error)
        await asyncio.wait_for(asyncio.shield(f.handler._acquisition_task), 2)
        self.assertEqual(f.camera.capture.read_count, 0)
        self.assertIsNotNone(f.node.read_experiment_expiry("experiment"))
