"""Explicit Experiment subsets through deployed NATS owners and real artifacts."""

import asyncio
from itertools import repeat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, DeviceReadiness,
    ExperimentConfiguration, InMemoryIngestor, NatsAcquisitionNodeCommunication,
    NatsControllerCommunication, NatsIngestorCommunication, NatsStorageManagerCommunication,
    NatsSynchronizationManagerCommunication, OpenCVCameraConfig, PersistentStorageManager,
    RuntimeParticipant, ScientificOutputSelection, ScientificProductDeclaration,
    SeeedIMX219OpenCVCameraAdapter, Session, SessionConfig, SynchronizationManager,
)
from tests.test_distributed_synchronization import configuration
from tests.test_scientific_camera_collection import FakeCV2
from tests.test_session_launch import _Boundary, _Broker


class ExperimentParticipationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.broker = _Broker()
        self.storage = PersistentStorageManager(self.root / "storage")
        self.ingestor = InMemoryIngestor(storage_manager=self.storage,
            recovery_journal_root=self.root / "journals",
            framework_recovery_journal_path=self.root / "framework.jsonl")
        intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        await intake.subscribe_evidence(None)
        await intake.subscribe_commands()
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker),
                                              self.storage).subscribe_commands()
        self.sync = NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), SynchronizationManager())
        await self.sync.subscribe_commands()
        self.addAsyncCleanup(self.sync.close)
        self.nodes, self.adapters, self.cameras, self.handlers = {}, {}, {}, {}
        selections = {}
        for node_id, devices in (("node", ("camera", "other")), ("second", ("remote",))):
            declarations, adapters = [], []
            for device_id in devices:
                camera = FakeCV2(repeat(np.zeros((2, 4, 3), dtype=np.uint16)), {0: 12.5})
                adapter = SeeedIMX219OpenCVCameraAdapter(
                    device_id, "opencv", ("camera_frames",), True, cv2_module=camera)
                declarations.append(DeviceDeclaration(device_id, "opencv", True, True,
                    ("camera_frames",), (() if device_id == "other" else (
                        ScientificProductDeclaration("frames", "camera_frames",
                            {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),))))
                self.adapters[device_id], self.cameras[device_id] = adapter, camera
                adapters.append(adapter)
            node = AcquisitionNode(device_manager=DeviceManager(adapters), node_id=node_id,
                role="acquisition", synchronization_source_id="sync",
                default_local_storage_root=self.root / node_id,
                device_declarations=declarations, error_evidence_location=str(self.root / "errors"),
                deployment_device_configurations={d: OpenCVCameraConfig(0, 0, 1) for d in devices})
            handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", node_id, self.broker), node)
            await handler.start_acquisition_execution()
            await handler.subscribe_commands()
            self.nodes[node_id], self.handlers[node_id] = node, handler
            self.addAsyncCleanup(handler.stop_acquisition_execution)
            selections[node_id] = tuple(declarations)
        self.controller = Controller()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        result = await self.controller.launch_session(selections, communication=self.communication,
            participants=(RuntimeParticipant("ingestor", "ingestor"),
                RuntimeParticipant("synchronization_manager", "sync"),
                *(RuntimeParticipant("acquisition_node", n) for n in selections)),
            config_parameters={"storage_location": str(self.root / "records"), "protocol_plan": "test",
                "error_evidence_location": str(self.root / "errors"),
                "synchronization_configuration": configuration()}, result_window_s=1)
        self.assertTrue(result.succeeded, result.error)
        self.sid = result.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.accepted = self.controller.read_session_configuration().details["configuration"]

    async def asyncTearDown(self):
        for handler in self.handlers.values():
            await handler.stop_acquisition_execution()
        for node in self.nodes.values():
            if node.status()["is_running"]:
                node.stop_runtime()
            if node.local_storage_manager is not None:
                node.local_storage_manager.cleanup()

    def config(self, devices=None, duration=60):
        return ExperimentConfiguration(duration, {"node": 1000000}, 1000000,
            participating_devices={"node": ["camera"]} if devices is None else devices)

    async def start(self, identity="experiment", *, devices=None, duration=60, outputs=None):
        return await self.controller.start_launched_experiment(identity,
            configuration=self.config(devices, duration),
            scientific_outputs=(ScientificOutputSelection("camera", "node", "frames"),)
                if outputs is None else outputs,
            storage_participant=RuntimeParticipant("storage_manager", "storage"))

    def unavailable(self, device):
        return patch.object(self.adapters[device], "check_ready",
            return_value=DeviceReadiness(device, False, "disconnected", ()))

    async def test_unrelated_same_node_and_remote_devices_do_not_block_or_acquire(self):
        with self.unavailable("other"), self.unavailable("remote"):
            result = await self.start()
            self.assertTrue(result.succeeded, result.error)
            await asyncio.sleep(0.02)
            self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        self.assertEqual(self.cameras["other"].capture.read_count, 0)
        self.assertEqual(self.cameras["remote"].capture.read_count, 0)
        manifest, = self.nodes["node"].local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        self.assertEqual(self.controller.read_session_configuration().details["configuration"], self.accepted)
        for node in self.nodes.values():
            self.assertEqual(node.check_node_readiness().reserved_for_session_id, self.sid)

    async def test_required_unavailable_device_blocks_without_canonical_start(self):
        with self.unavailable("camera"):
            result = await self.start()
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        self.assertFalse(self.nodes["node"].experiment_runtime_active)

    async def test_nonrecording_participant_is_prepared_and_checked(self):
        devices = {"node": ["camera", "other"]}
        with self.unavailable("other"):
            self.assertFalse((await self.start(devices=devices)).succeeded)
        self.assertTrue((await self.start("ready", devices=devices)).succeeded)
        await asyncio.sleep(0.02)
        self.assertTrue((await self.controller.stop_launched_experiment("ready")).succeeded)
        self.assertEqual(self.cameras["other"].capture.read_count, 0)

    async def test_control_only_participation_does_not_replace_data_acquisition_device(self):
        result = await self.start(devices={"node": ["other"]}, outputs=())
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])

    async def test_empty_and_missing_participation_rejected_before_lifecycle_mutation(self):
        for devices in ({}, {"node": []}):
            with self.subTest(devices=devices):
                try:
                    result = await self.start(devices=devices, outputs=())
                except ValueError:
                    pass
                else:
                    self.assertFalse(result.succeeded)
        missing = await self.controller.start_launched_experiment("missing",
            configuration=ExperimentConfiguration(1, {"node": 0}, 100),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertFalse(missing.succeeded)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        self.assertEqual(self.controller.get_status()["experiment_lifecycle_evidence"], ())
        self.assertFalse(any(n.local_storage_manager.manifests for n in self.nodes.values()))

    async def test_unknown_or_wrong_node_devices_and_nonparticipating_outputs_rejected(self):
        for devices in ({"node": ["unknown"]}, {"second": ["camera"]}, {"node": ["other"]}):
            with self.subTest(devices=devices):
                result = await self.start(devices=devices)
                self.assertFalse(result.succeeded)
                self.assertIsNone(self.controller.get_status()["active_experiment_id"])
                self.assertEqual(self.controller.get_status()["experiment_lifecycle_evidence"], ())

    async def test_outputless_participant_is_checked_and_expires(self):
        with self.unavailable("camera"):
            rejected = await self.start(outputs=())
            self.assertFalse(rejected.succeeded)
        result = await self.start("outputless", duration=0.02, outputs=())
        self.assertTrue(result.succeeded, result.error)
        await asyncio.sleep(0.05)
        self.assertIsNotNone(self.nodes["node"].read_experiment_expiry("outputless"))
        self.assertTrue(await self.controller.reconcile_launched_experiment_expiry("outputless"))
        self.assertEqual(self.cameras["camera"].capture.read_count, 0)
        self.assertFalse(self.nodes["second"].experiment_runtime_active)

    async def test_two_participating_nodes_reconcile_only_their_deadlines(self):
        result = await self.start("both", devices={"node": ["camera"], "second": ["remote"]},
                                  duration=0.2, outputs=())
        self.assertTrue(result.succeeded, result.error)
        await asyncio.sleep(0.3)
        self.assertTrue(await self.controller.reconcile_launched_experiment_expiry("both"))
        for node in self.nodes.values():
            self.assertIsNotNone(node.read_experiment_expiry("both"))
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_successive_subsets_leave_session_membership_unchanged(self):
        self.assertTrue((await self.start(outputs=())).succeeded)
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        with self.unavailable("camera"):
            result = await self.start("next", devices={"second": ["remote"]}, outputs=())
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue((await self.controller.stop_launched_experiment("next")).succeeded)
        self.assertEqual(self.controller.read_session_configuration().details["configuration"], self.accepted)

    async def test_readiness_loss_at_activation_finalizes_prepared_artifact(self):
        original = self.adapters["camera"].check_ready
        def change(command):
            if command["command_type"] == "activate_experiment_runtime":
                self.adapters["camera"].check_ready = lambda: DeviceReadiness("camera", False, "lost", ())
        self.broker.on_command = change
        try:
            result = await self.start()
        finally:
            self.adapters["camera"].check_ready = original
            self.broker.on_command = None
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        manifest, = self.nodes["node"].local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")

    async def test_cancellation_after_preparation_finalizes_then_allows_another_experiment(self):
        def interrupt(operation, result):
            if operation == "prepare_experiment_scientific_outputs":
                raise asyncio.CancelledError()
            return result
        self.broker.change_result = interrupt
        with self.assertRaises(asyncio.CancelledError):
            await self.start()
        self.broker.change_result = None
        manifest, = self.nodes["node"].local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        self.assertFalse(self.nodes["node"].experiment_runtime_active)
        self.assertTrue((await self.start("retry", outputs=())).succeeded)
        self.assertTrue((await self.controller.stop_launched_experiment("retry")).succeeded)


class ExperimentParticipationConfigurationTests(unittest.TestCase):
    def test_participation_round_trip_and_accepted_descriptor_are_detached(self):
        devices = {"node": ["camera"]}
        config = ExperimentConfiguration(1, {"node": 10}, 10, participating_devices=devices)
        devices["node"].append("input-edit")
        session = Session("session", SessionConfig([], None, "protocol", "errors"))
        descriptor = session.ensure_experiment_descriptor("experiment", configuration=config)
        config.participating_devices["node"].append("config-edit")
        descriptor.configuration.participating_devices.clear()
        snapshot = session.experiment_descriptors[0]
        plain = snapshot.to_dict()
        snapshot.configuration.participating_devices.clear()
        self.assertEqual(plain["configuration"]["participating_devices"], {"node": ["camera"]})
        restored = ExperimentConfiguration.from_dict(session.experiment_descriptors[0].configuration.to_dict())
        self.assertEqual(restored.participating_devices, {"node": ["camera"]})
