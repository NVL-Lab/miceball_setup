"""A remotely activated camera records locally without per-frame PC commands."""

import asyncio
from itertools import repeat
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsControllerCommunication, NatsIngestorCommunication,
    NatsSynchronizationManagerCommunication, OpenCVCameraConfig, PersistentStorageManager,
    RuntimeParticipant, ScientificOutputSelection, ScientificProductDeclaration, ExperimentConfiguration,
    NatsStorageManagerCommunication,
    SeeedIMX219OpenCVCameraAdapter, ServiceMaintenanceInterface, SynchronizationManager,
)
from tests.test_distributed_synchronization import configuration
from tests.test_scientific_camera_collection import FakeCV2
from tests.test_session_launch import _Boundary, _Broker


class SustainedAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.frame = np.arange(24, dtype=np.uint16).reshape(2, 4, 3)
        self.camera = FakeCV2(repeat(self.frame), {0: 12.5})
        self.adapter = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frames",), True, cv2_module=self.camera)
        self.declaration = DeviceDeclaration("camera", "opencv", True, True, ("camera_frames",), (
            ScientificProductDeclaration("frames", "camera_frames",
                {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),))
        self.broker = _Broker()
        self.storage = PersistentStorageManager(self.root / "storage")
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker),
                                              self.storage).subscribe_commands()
        self.ingestor = InMemoryIngestor(storage_manager=self.storage,
            recovery_journal_root=self.root / "journals", framework_recovery_journal_path=self.root / "framework.jsonl")
        self.intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        await self.intake.subscribe_evidence(None)
        await self.intake.subscribe_commands()
        self.clock = SynchronizationManager()
        self.sync = NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), self.clock)
        await self.sync.subscribe_commands()
        self.node = AcquisitionNode(device_manager=DeviceManager((self.adapter,)), node_id="node",
            role="acquisition", synchronization_source_id="sync", default_local_storage_root=self.root / "local",
            device_declarations=(self.declaration,), error_evidence_location=str(self.root / "errors"),
            deployment_device_configurations={"camera": OpenCVCameraConfig(0, 0, 1)})
        self.handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", self.broker), self.node)
        await self.handler.start_acquisition_execution()
        await self.handler.subscribe_commands()
        self.controller = Controller()
        self.pc = _Boundary("controller", "controller", self.broker)
        self.communication = NatsControllerCommunication(self.pc)
        self.target = RuntimeParticipant("acquisition_node", "node")
        result = await self.controller.launch_session({"node": (self.declaration,)},
            communication=self.communication, participants=(RuntimeParticipant("ingestor", "ingestor"),
                RuntimeParticipant("synchronization_manager", "sync"), self.target),
            config_parameters={"storage_location": str(self.root / "record"), "protocol_plan": {},
                "error_evidence_location": str(self.root / "errors"),
                "synchronization_configuration": configuration()}, result_window_s=2)
        self.assertTrue(result.succeeded, result.error)
        self.sid = result.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.local = self.node.local_storage_manager

    async def asyncTearDown(self):
        await self.handler.stop_acquisition_execution()
        if self.node.status()["is_running"]:
            self.node.stop_runtime()
        self.local.cleanup()
        await self.sync.close()

    async def until(self, predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0)
        self.fail("Expected bounded workflow progress did not occur")

    async def experiment(self, identity="experiment"):
        result = await self.controller.start_launched_experiment(identity,
            scientific_outputs=(ScientificOutputSelection("camera", "node", "frames"),),
            configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000, participating_devices={"node": ["camera"]}),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(result.succeeded, result.error)

    async def request(self, operation, payload=None, **kwargs):
        return await self.communication.request_runtime_command(self.target, operation, self.sid,
            payload or {}, 0.02, **kwargs)

    def saved(self, experiment="experiment"):
        manifest, = [m for m in self.local.manifests if m.experiment_id == experiment]
        self.assertEqual(manifest.lifecycle_state, "finalized")
        with h5py.File(manifest.local_storage_path, "r") as artifact:
            frames = artifact["frames"][:]
            metadata = [json.loads(row) for row in artifact["record_metadata_json"][:]]
        return frames, metadata

    async def test_single_activation_records_sequential_frames_without_iteration_commands(self):
        self.assertFalse(self.handler.acquisition_execution_active)
        self.assertEqual(self.camera.capture.read_count, 0)
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 4)
        stopped = await self.controller.stop_launched_experiment("experiment")
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertFalse(self.handler.acquisition_execution_active)
        frames, metadata = self.saved()
        self.assertGreaterEqual(len(frames), 4)
        self.assertEqual([m["frame_index"] for m in metadata], list(range(len(frames))))
        for frame, row in zip(frames, metadata):
            np.testing.assert_array_equal(frame, self.frame)
            self.assertEqual(row["session_id"], self.sid)
            self.assertEqual(row["experiment_id"], "experiment")
            self.assertEqual(row["device_local_time"], 12.5)
            self.assertIn("session_time_s", row)
            self.assertIn("acquisition_node_local_time_s", row)
            self.assertIn("timestamp_status", row)
        self.assertEqual(len(frames), self.camera.capture.read_count)
        self.assertFalse(any(command["command_type"] == "run_one_iteration" for command in self.broker.commands))

    async def test_pc_disconnection_does_not_terminate_recording(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 2)
        count = self.camera.capture.read_count
        self.pc.available = False
        try:
            self.assertFalse(self.pc.connected)
            await self.until(lambda: self.camera.capture.read_count >= count + 4)
            self.assertTrue(self.handler.acquisition_execution_active)
            self.assertTrue(self.node.status()["is_running"])
        finally:
            self.pc.available = True
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertFalse(self.handler.acquisition_execution_active)
        self.assertTrue(self.camera.capture.released)
        self.assertGreaterEqual(len(self.saved()[0]), count + 4)

    async def test_identical_activation_and_repeated_enable_have_one_recording_writer(self):
        writers = set()
        read = self.camera.capture.read

        def track_read():
            writers.add(asyncio.current_task())
            return read()

        with patch.object(self.camera.capture, "read", side_effect=track_read):
            await self.experiment()
            await self.until(lambda: self.camera.capture.read_count >= 2)
            context = self.node.status()["active_experiment_runtime_context"].to_dict()
            for _ in range(3):
                await self.handler.start_acquisition_execution()
                result = await self.request("activate_experiment_runtime",
                    {"context": context, "health_mapping": []}, command_id="repeat-activation")
                self.assertTrue(result.success, result.reason)
            count = self.camera.capture.read_count
            await self.until(lambda: self.camera.capture.read_count >= count + 3)
            self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        self.assertEqual(len(writers), 1)
        self.assertEqual(len(self.saved()[0]), self.camera.capture.read_count)

    async def test_experiment_gap_is_idle_and_next_experiment_resumes(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 2)
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        count = self.camera.capture.read_count
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(self.camera.capture.read_count, count)
        self.assertTrue(self.node.status()["is_running"])
        await self.experiment("second")
        await self.until(lambda: self.camera.capture.read_count >= count + 2)
        self.assertTrue((await self.controller.stop_launched_experiment("second")).succeeded)
        self.assertEqual(len(self.saved()[0]), count)
        self.assertEqual(self.saved("second")[1][0]["frame_index"], count)

    async def test_rejected_runtime_stop_leaves_recording_active(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 2)
        rejected = await self.communication.request_runtime_command(self.target, "stop_runtime", "other", {}, 0.02)
        self.assertFalse(rejected.success)
        count = self.camera.capture.read_count
        await self.until(lambda: self.camera.capture.read_count >= count + 2)
        self.assertTrue(self.handler.acquisition_execution_active)

    async def test_experiment_without_selected_products_keeps_expiry_without_reads(self):
        result = await self.controller.start_launched_experiment("idle",
            configuration=ExperimentConfiguration(60, {"node": 0}, 1000000, participating_devices={"node": ["camera"]}),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(result.succeeded, result.error)
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertTrue(self.handler.acquisition_execution_active)
        self.assertEqual(self.camera.capture.read_count, 0)

    async def test_publication_failure_retains_timing_evidence_without_stopping_frames(self):
        await self.experiment()
        quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "assessment unavailable")
        self.node.accept_synchronization_quality(self.sid, "sync", quality)
        count = self.camera.capture.read_count
        with patch.object(self.handler._boundary, "publish_evidence", side_effect=ConnectionError("broker unavailable")):
            with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
                await self.until(lambda: self.camera.capture.read_count >= count + 3)
            self.assertTrue(self.handler.acquisition_execution_active)
            interpretation, = [m for m in self.node.runtime_evidence if m.evidence_type == "timing_quality_interpretation"]
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        accepted = self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]
        self.assertEqual(sum(m.evidence_id == interpretation.evidence_id for m in accepted), 1)
        self.assertEqual(self.saved()[1][-1]["timestamp_status"], "synchronization_degraded")

    async def test_interrupted_scheduler_shutdown_can_be_retried_without_background_reads(self):
        await self.experiment()
        publishing = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()

        async def paused_publication():
            publishing.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

        with patch.object(self.handler, "publish_new_runtime_evidence", side_effect=paused_publication):
            await publishing.wait()
            stopping = asyncio.create_task(self.handler.stop_acquisition_execution())
            await cleaning.wait()
            stopping.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await stopping
            await self.handler.stop_acquisition_execution()
        self.assertFalse(self.handler.acquisition_execution_active)
        count = self.camera.capture.read_count
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(self.camera.capture.read_count, count)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertEqual(len(self.saved()[0]), count)

    async def test_acquisition_failure_preserves_partial_frames_and_cleans_devices(self):
        self.camera.capture.frames = iter((self.frame, self.frame, None))
        with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
            await self.experiment()
            await self.until(lambda: self.node.status()["failed"] and not self.handler.acquisition_execution_active)
        self.assertFalse(self.node.status()["is_running"])
        self.assertTrue(self.node.status()["cleanup_confirmed"])
        self.assertTrue(self.camera.capture.released)
        self.assertEqual(len(self.saved()[0]), 2)
        self.assertTrue(any(m.payload.get("event_type") == "acquisition_failure" for m in self.node.runtime_evidence))
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_blocked_stop_cancel_and_authorized_kill_preserve_existing_semantics(self):
        async def cleaned(force):
            await self.handler.stop_acquisition_execution()
            return True

        maintenance = ServiceMaintenanceInterface(self.node, self.target, ingestor=self.ingestor,
            storage_manager=self.storage, preservation_window_s=0.1, close_resources=cleaned)
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 2)

        async def maintain(operation, attempt, **extra):
            return await self.communication.request_command(self.target, operation, None,
                {"stop_attempt_id": attempt, "administrator_id": "operator", **extra}, 0.1)

        blocked = await maintain("stop", "first")
        self.assertFalse(blocked.success)
        self.assertEqual(blocked.payload["outcome"], "blocked", blocked.reason)
        count = self.camera.capture.read_count
        await self.until(lambda: self.camera.capture.read_count >= count + 2)
        cancelled = await maintain("cancel", "first")
        self.assertFalse(cancelled.success)
        self.assertFalse(maintenance.terminated)
        self.assertTrue(self.handler.acquisition_execution_active)
        self.assertEqual((await maintain("stop", "second")).payload["outcome"], "blocked")
        unauthorized = await maintain("kill", "second", authorized=False)
        self.assertFalse(unauthorized.success)
        self.assertTrue(self.handler.acquisition_execution_active)
        killed = await maintain("kill", "second", authorized=True)
        self.assertTrue(killed.success, killed.reason)
        self.assertTrue(maintenance.terminated)
        self.assertFalse(self.handler.acquisition_execution_active)
        self.assertFalse(self.node.status()["is_running"])
        self.assertTrue(self.camera.capture.released)
        self.assertGreaterEqual(len(self.saved()[0]), count + 2)


if __name__ == "__main__":
    unittest.main()
