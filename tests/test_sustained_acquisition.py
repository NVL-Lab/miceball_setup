"""A remotely activated camera records locally without per-frame PC commands."""

import asyncio
from itertools import repeat
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import h5py
import numpy as np

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsControllerCommunication, NatsIngestorCommunication,
    NatsSynchronizationManagerCommunication, OpenCVCameraConfig, PersistentStorageManager,
    RuntimeParticipant, ScientificOutputSelection, ScientificProductDeclaration, ExperimentConfiguration,
    NatsStorageManagerCommunication,
    NatsCommunicationBoundary,
    SeeedIMX219OpenCVCameraAdapter, ServiceMaintenanceInterface, SynchronizationManager,
)
from tests.test_distributed_synchronization import configuration
from tests.test_scientific_camera_collection import FakeCV2
from tests.test_session_launch import _Boundary
from tests.test_distributed_session_closeout import CloseoutBroker
from tests.nats_server_fixture import acquire_test_controller_authority, restartable_jetstream_server


class SustainedAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "artifacts").mkdir()
        self.frame = np.arange(24, dtype=np.uint16).reshape(2, 4, 3)
        self.camera = FakeCV2(repeat(self.frame), {0: 12.5})
        self.adapter = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frames",), True, cv2_module=self.camera)
        self.declaration = DeviceDeclaration("camera", "opencv", True, True, ("camera_frames",), (
            getattr(self, "scientific_product", None) or ScientificProductDeclaration("frames", "camera_frames",
                {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),))
        self.broker = CloseoutBroker()
        self.storage = PersistentStorageManager(self.root / "storage", global_artifact_root=self.root / "artifacts")
        self.storage_handler = NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), self.storage)
        await self.storage_handler.subscribe_commands()
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
        maintenance = ServiceMaintenanceInterface(self.controller, RuntimeParticipant("controller", "controller"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=2,
            close_resources=AsyncMock(return_value=True))
        self.pc = await acquire_test_controller_authority(self, maintenance)
        self.pc._require_jetstream = lambda: self.broker
        for handler, owner in ((self.storage_handler, self.storage), (self.intake, self.ingestor),
                (self.sync, self.clock), (self.handler, self.node)):
            boundary = handler._boundary
            boundary._client, boundary._jetstream = self.pc._client, self.pc._jetstream
            boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
            ServiceMaintenanceInterface(owner, RuntimeParticipant(boundary.component_type, boundary.component_id),
                ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=2,
                close_resources=AsyncMock(return_value=True))
        self.communication = NatsControllerCommunication(self.pc)
        self.target = RuntimeParticipant("acquisition_node", "node")
        if getattr(self, "before_launch", None) is not None:
            await self.before_launch(self)
        result = await self.controller.launch_session({"node": (self.declaration,)},
            communication=self.communication, participants=(RuntimeParticipant("ingestor", "ingestor"),
                RuntimeParticipant("storage_manager", "storage"),
                RuntimeParticipant("synchronization_manager", "sync"), self.target),
            config_parameters={"storage_location": "default", "protocol_plan": {},
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
        # Dispose the test process even when its scenario deliberately leaves
        # unconfirmed evidence; this is not successful framework retirement.
        if self.handler._publication_task is not None:
            self.handler._publication_task.cancel()
            await asyncio.gather(self.handler._publication_task, return_exceptions=True)
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
        with patch.object(self.pc, "_require_jetstream", side_effect=ConnectionError("Controller disconnected")):
            await self.until(lambda: self.camera.capture.read_count >= count + 4)
            self.assertTrue(self.handler.acquisition_execution_active)
            self.assertTrue(self.node.status()["is_running"])
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

    async def test_pending_ack_does_not_pause_scientific_recording(self):
        await self.experiment()
        entered, release = asyncio.Event(), asyncio.Event()
        publish = self.handler._boundary.publish_evidence

        async def delayed(message):
            entered.set()
            await release.wait()
            await publish(message)

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=delayed):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                count = self.camera.capture.read_count
                await self.until(lambda: self.camera.capture.read_count >= count + 8)
                manifest, = self.local.manifests
                with h5py.File(manifest.local_storage_path, "r") as artifact:
                    self.assertGreaterEqual(len(artifact["frames"]), count + 8)
                    times = artifact["acquisition_node_local_time_s"][:]
                    self.assertTrue(np.all(np.diff(times) >= 0))
                    print(f"Blocked ACK: {len(times) - count} additional persisted frames; "
                          f"max local interval {np.max(np.diff(times)):.6f}s")
                self.assertFalse(release.is_set())
            finally:
                release.set()
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)

    async def test_expiry_finalizes_before_pending_ack_and_later_publishes(self):
        await self.experiment()
        entered, release = asyncio.Event(), asyncio.Event()
        publish = self.handler._boundary.publish_evidence

        async def delayed(message):
            entered.set()
            await release.wait()
            await publish(message)

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=delayed):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12):
                    await self.until(lambda: not self.handler.acquisition_execution_active)
                self.assertIsNotNone(self.node.read_experiment_expiry("experiment"))
                self.assertEqual(self.local.manifests[0].lifecycle_state, "finalized")
                self.assertIsNone(self.communication.session_acquisition_completion(self.target, self.sid))
                self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")
            finally:
                release.set()
        await self.until(lambda: any(m.evidence_type == "experiment_duration_expired"
            for m in self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]))
        self.assertTrue(await self.controller.reconcile_launched_experiment_expiry("experiment"))

    async def test_ack_timeouts_after_expiry_retry_without_another_command(self):
        await self.experiment()
        entered, release = asyncio.Event(), asyncio.Event()
        publish = self.handler._boundary.publish_evidence
        attempts = []

        async def delayed(message):
            entered.set()
            await release.wait()
            attempts.append(message.to_dict())
            retries = [m for m in attempts if m["evidence_id"] == attempts[0]["evidence_id"]]
            if message.evidence_id == attempts[0]["evidence_id"] and len(retries) <= 3:
                raise asyncio.TimeoutError("Connected transport did not confirm publication")
            await publish(message)

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=delayed):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12):
                    await self.until(lambda: not self.handler.acquisition_execution_active)
                with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
                    release.set()
                    await self.until(lambda: sum(m["evidence_id"] == attempts[0]["evidence_id"]
                                                for m in attempts) >= 4)
                self.assertTrue(all(m == attempts[0] for m in attempts
                                    if m["evidence_id"] == attempts[0]["evidence_id"]))
            finally:
                release.set()
        await self.until(lambda: any(m.evidence_type == "experiment_duration_expired"
            for m in self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]))

    async def test_cancelled_flush_retains_publication_without_background_reads(self):
        await self.experiment()
        publishing = asyncio.Event()
        release = asyncio.Event()

        async def paused_publication():
            publishing.set()
            await release.wait()

        with patch.object(self.handler, "publish_new_runtime_evidence", side_effect=paused_publication):
            await publishing.wait()
            await self.handler.stop_acquisition_execution()
            flush = asyncio.create_task(self.handler._finish_evidence_publication())
            await asyncio.sleep(0)
            self.assertFalse(flush.done())
            flush.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await flush
            self.assertFalse(self.handler._publication_task.done())
            release.set()
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

        maintenance = self.node._maintenance
        maintenance.close_resources = cleaned
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

    async def test_manual_stop_finalizes_while_ack_is_pending_without_completion_proof(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 3)
        entered, release = asyncio.Event(), asyncio.Event()
        publish = self.handler._boundary.publish_evidence

        async def delayed(message):
            entered.set()
            await release.wait()
            await publish(message)

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=delayed):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            await asyncio.wait_for(entered.wait(), 2)
            stopping = asyncio.create_task(self.controller.stop_launched_session())
            try:
                await self.until(lambda: not self.node.status()["is_running"])
                self.assertEqual(self.local.manifests[0].lifecycle_state, "finalized")
                self.assertIsNone(self.communication.session_acquisition_completion(self.target, self.sid))
                self.assertFalse(stopping.done())
                count = self.camera.capture.read_count
                for _ in range(5):
                    await asyncio.sleep(0)
                self.assertEqual(self.camera.capture.read_count, count)
            finally:
                release.set()
            self.assertTrue((await stopping).succeeded)

    async def test_camera_failure_finalizes_partial_products_before_pending_ack(self):
        await self.experiment()
        entered, release = asyncio.Event(), asyncio.Event()
        publish = self.handler._boundary.publish_evidence

        async def delayed(message):
            entered.set()
            await release.wait()
            await publish(message)

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=delayed):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            await asyncio.wait_for(entered.wait(), 2)
            try:
                self.camera.capture.frames = iter((self.frame, self.frame, None))
                count = self.camera.capture.read_count
                with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
                    await self.until(lambda: not self.handler.acquisition_execution_active)
                self.assertTrue(self.node.status()["failed"])
                self.assertTrue(self.node.status()["cleanup_confirmed"])
                self.assertEqual(len(self.saved()[0]), count + 2)
                failure, = [m for m in self.node.runtime_evidence
                            if m.payload.get("event_type") == "acquisition_failure"]
            finally:
                release.set()
        await self.until(lambda: self.ingestor.has_durable_runtime_evidence(failure))

    async def test_uncertain_ack_retries_identical_content_and_deduplicates_intake(self):
        await self.experiment()
        publish = self.handler._boundary.publish_evidence
        attempted = []

        async def uncertain(message):
            attempted.append(message.to_dict())
            await publish(message)
            if len(attempted) == 1:
                raise asyncio.TimeoutError("ACK was lost after durable intake")

        with patch.object(self.handler._boundary, "publish_evidence", side_effect=uncertain):
            quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "offline")
            self.node.accept_synchronization_quality(self.sid, "sync", quality)
            with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
                await self.until(lambda: len(attempted) >= 2)
            self.assertEqual(attempted[0], attempted[1])
        messages = self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]
        self.assertEqual(sum(m.evidence_id == attempted[0]["evidence_id"] for m in messages), 1)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)

    async def test_unbound_preserved_evidence_retires_without_republishing_or_losing_conflict_protection(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 3)
        retained = self.node.runtime_evidence
        self.assertTrue(retained)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertIsNone(self.node.status()["session_id"])
        # Intake is independently durable before producer copies can retire.
        self.assertTrue(all(self.ingestor.has_durable_runtime_evidence(m) for m in retained))
        with patch.object(self.handler._boundary, "publish_evidence", wraps=self.handler._boundary.publish_evidence) as publish:
            await self.handler.publish_new_runtime_evidence()
            await self.handler.publish_new_artifact_manifest_evidence()
            publish.assert_not_called()
        self.assertFalse(self.node.runtime_evidence)
        duplicate = retained[0]
        self.assertEqual(self.ingestor.receive_runtime_evidence(duplicate).reason, "already_accepted")
        from dataclasses import replace
        with self.assertRaises(ValueError):
            self.ingestor.receive_runtime_evidence(replace(duplicate, payload={"changed": True}))

    async def _record_through_broker_restart(self, *, expire):
        await self.experiment()
        await self.handler._publish_acquisition_evidence()
        original = self.handler._boundary
        async with restartable_jetstream_server() as server:
            boundary = NatsCommunicationBoundary("acquisition_node", "node", (server.url,))
            await boundary.connect()
            try:
                await boundary.ensure_streams()
                disconnected, reconnected, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def on_disconnect():
                    disconnected.set()

                async def on_reconnect():
                    await boundary._resume_acquisition_publication()
                    reconnected.set()

                async def receive(message):
                    payload = json.loads(message.data)
                    if payload["evidence_id"] == expected:
                        delivered.set()
                    await message.ack()

                boundary._client._disconnected_cb = on_disconnect
                boundary._client._reconnected_cb = on_reconnect
                boundary._acquisition_publication_notification = self.handler._publication_requested
                self.handler._boundary = boundary
                subscription = await boundary._require_jetstream().subscribe(
                    f"messages.{self.sid}.evidence.acquisition_node.node.>", cb=receive, manual_ack=True)
                await boundary._client.flush()
                server.stop()
                await asyncio.wait_for(disconnected.wait(), 5)
                quality = self.clock.mark_synchronization_unavailable(self.sid, "node", "sync", "broker offline")
                self.node.accept_synchronization_quality(self.sid, "sync", quality)
                count = self.camera.capture.read_count
                await self.until(lambda: self.camera.capture.read_count >= count + 8)
                if expire:
                    with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=10**12):
                        await self.until(lambda: not self.handler.acquisition_execution_active)
                    expected = self.node.read_experiment_expiry("experiment").evidence_id
                    self.assertEqual(len(self.saved()[0]), self.camera.capture.read_count)
                else:
                    expected = next(m.evidence_id for m in self.node.runtime_evidence
                                    if m.evidence_type == "timing_quality_interpretation")
                count = self.camera.capture.read_count
                await server.start()
                await asyncio.wait_for(reconnected.wait(), 8)
                await asyncio.wait_for(delivered.wait(), 8)
                stored = await boundary._require_jetstream().get_last_msg(
                    "LAB_EVIDENCE", f"messages.{self.sid}.evidence.acquisition_node.node."
                    + ("experiment_duration_expired" if expire else "timing_quality_interpretation"))
                self.assertEqual(json.loads(stored.data)["evidence_id"], expected)
                if expire:
                    self.assertEqual(self.camera.capture.read_count, count)
                else:
                    self.assertGreater(self.camera.capture.read_count, count)
                await subscription.unsubscribe()
            finally:
                # Join any real publication before restoring the fixture transport.
                await self.handler.stop_acquisition_execution()
                await self.handler._publish_acquisition_evidence()
                self.handler._boundary = original
                await boundary.close()

    async def test_broker_restart_resumes_publication_while_scientific_recording_continues(self):
        await self._record_through_broker_restart(expire=False)

    async def test_broker_restart_resumes_publication_after_local_expiry(self):
        await self._record_through_broker_restart(expire=True)

    async def test_publication_ack_alone_does_not_retire_unpreserved_evidence(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 3)
        with patch.object(self.node._maintenance, "evidence_preserved", return_value=False):
            self.assertTrue((await self.controller.stop_launched_session()).succeeded)
            retained = self.node.runtime_evidence
            self.assertTrue(retained)
            with patch.object(self.handler._boundary, "publish_evidence", wraps=self.handler._boundary.publish_evidence) as publish:
                await self.handler.publish_new_runtime_evidence()
                self.assertEqual(self.node.runtime_evidence, retained)
                publish.assert_not_called()
        await self.handler.publish_new_runtime_evidence()
        self.assertFalse(self.node.runtime_evidence)

    async def test_successive_sessions_publish_after_retirement_without_changing_first_archive(self):
        await self.experiment()
        await self.until(lambda: self.camera.capture.read_count >= 3)
        topic = f"messages.{self.sid}.evidence.*.*.*"
        durable = next(name for name, consumer in self.broker.consumers.items()
                       if consumer.config.filter_subject == topic)
        self.broker.callbacks[durable] = next(s.callback for s in self.broker.subscriptions if s.subject == topic)
        publish = self.broker.publish

        async def receive_marker(subject, data, stream):
            result = await publish(subject, data, stream)
            if stream == "LAB_EVIDENCE" and json.loads(data)["evidence_type"] == "acquisition_evidence_completion":
                for sequence, record in sorted(self.broker.records.items()):
                    if self.broker.matches(topic, record.subject):
                        await self.broker.deliver(durable, sequence)
            return result

        with patch.object(self.broker, "publish", side_effect=receive_marker):
            stopped = await self.controller.normal_stop_session(communication=self.communication,
                storage_participant=RuntimeParticipant("storage_manager", "storage"), result_window_s=2)
        self.assertTrue(stopped.succeeded, stopped.error)
        first_session = self.sid
        first_products = {p: p.read_bytes() for p in self.storage.storage_root.rglob("*")
                          if p.is_file() and first_session in str(p)}
        self.assertTrue(first_products)
        released = await self.controller.release_session(communication=self.communication, result_window_s=2)
        self.assertTrue(released.succeeded, released.error)
        self.camera.capture = FakeCV2(repeat(self.frame), {0: 12.5}).capture
        launched = await self.controller.launch_session({"node": (self.declaration,)},
            communication=self.communication, participants=(RuntimeParticipant("ingestor", "ingestor"),
                RuntimeParticipant("storage_manager", "storage"),
                RuntimeParticipant("synchronization_manager", "sync"), self.target),
            config_parameters={"storage_location": "default", "protocol_plan": {},
                "error_evidence_location": str(self.root / "errors"),
                "synchronization_configuration": configuration()}, result_window_s=2)
        self.assertTrue(launched.succeeded, launched.error)
        self.sid = launched.details["session_id"]
        self.assertNotEqual(self.sid, first_session)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.local = self.node.local_storage_manager
        count = self.camera.capture.read_count
        await self.experiment("second")
        await self.until(lambda: self.camera.capture.read_count >= count + 3)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertEqual(first_products, {p: p.read_bytes() for p in first_products})
        self.assertGreaterEqual(len(self.saved("second")[0]), 3)


if __name__ == "__main__":
    unittest.main()
