"""Adapter-defined Session choices through installed inventory and node preparation."""

import tempfile
from pathlib import Path
import unittest

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, DeviceAdapterState,
    InMemoryIngestor, NatsAcquisitionNodeCommunication, NatsControllerCommunication,
    OpenCVCameraConfig, RuntimeParticipant, SeeedIMX219OpenCVCameraAdapter, SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_seeed_imx219_camera_adapter import FakeCV2
from tests.test_session_launch import _Boundary, _Broker


class AdjustableAdapter(ReadyFakeAdapter):
    def get_session_parameter_definitions(self):
        return {"rate": {"type": "number", "minimum": 1, "maximum": 20},
                "mode": {"type": "string", "allowed_values": ["fast", "slow"]},
                "enabled": {"type": "boolean"}}


class DeviceParameterTests(unittest.TestCase):
    def test_adapter_constraints_reject_invalid_values_without_coercion(self):
        adapter = AdjustableAdapter("events", "event-device", (), True)
        base = {"connection": "installation", "rate": 2, "mode": "slow", "enabled": True}
        self.assertEqual(adapter.resolve_session_configuration(base, {"rate": 10})["rate"], 10)
        for values in ({"rate": True}, {"rate": "10"}, {"rate": 21}, {"rate": float("nan")},
                       {"rate": 0}, {"mode": "unknown"}, {"enabled": 1}, {"connection": "other"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                adapter.resolve_session_configuration(base, values)
        self.assertEqual(base["rate"], 2)
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)

    def test_camera_inventory_does_not_open_hardware_or_expose_installation_settings(self):
        cv2 = FakeCV2([])
        camera = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", (), True, cv2_module=cv2)
        node = AcquisitionNode(device_manager=DeviceManager([camera]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        inventory = node.get_inventory()
        definitions = inventory["session_parameter_definitions"]["camera"]
        self.assertEqual(definitions["frames_per_collect"], {"type": "integer", "minimum": 1})
        self.assertNotIn("camera_source", definitions)
        self.assertNotIn("api_preference", definitions)
        definitions["frames_per_collect"]["minimum"] = -1
        self.assertEqual(node.get_inventory()["session_parameter_definitions"]["camera"]["frames_per_collect"]["minimum"], 1)
        self.assertEqual(cv2.captures, [])

    def test_successive_sessions_use_overrides_then_restore_installation_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            cv2 = FakeCV2([])
            camera = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", (), True, cv2_module=cv2)
            defaults = OpenCVCameraConfig(0, 0, 2, fps=15)
            declaration = DeviceDeclaration("camera", "opencv", True, True, ())
            node = AcquisitionNode(device_manager=DeviceManager([camera]), node_id="node",
                synchronization_manager=SynchronizationManager(), ingestor=InMemoryIngestor(),
                default_local_storage_root=Path(directory), device_declarations=[declaration],
                deployment_device_configurations={"camera": defaults})
            for sid, overrides, count, fps in (("one", {"frames_per_collect": 4, "fps": 30}, 4, 30),
                                                ("two", {"frames_per_collect": 1}, 1, 15),
                                                ("three", None, 2, 15)):
                self.assertTrue(node.reserve(sid))
                node.initialize_session(sid, selected_devices=[declaration],
                    device_configurations={"camera": overrides} if overrides is not None else None)
                self.assertEqual(camera.initialization_config.frames_per_collect, count)
                self.assertEqual(camera.initialization_config.fps, fps)
                self.assertEqual(camera.initialization_config.camera_source, 0)
                node.abort_session_initialization(sid)
                self.assertTrue(node.release_reservation(sid))
                self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
            self.assertEqual(defaults, OpenCVCameraConfig(0, 0, 2, fps=15))

    def test_invalid_session_overrides_are_rejected_before_hardware_access(self):
        for overrides in ({"frames_per_collect": 0}, {"frames_per_collect": True}, {"fps": "30"},
                          {"frame_width": -1}, {"camera_source": 1}, {"api_preference": 1}, {"unknown": 1}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as directory:
                cv2 = FakeCV2([])
                camera = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", (), True, cv2_module=cv2)
                declaration = DeviceDeclaration("camera", "opencv", True, True, ())
                node = AcquisitionNode(device_manager=DeviceManager([camera]), node_id="node",
                    synchronization_manager=SynchronizationManager(),
                    default_local_storage_root=Path(directory), device_declarations=[declaration],
                    deployment_device_configurations={"camera": OpenCVCameraConfig(0, 0, 1)})
                self.assertTrue(node.reserve("session"))
                with self.assertRaises(ValueError):
                    node.initialize_session("session", selected_devices=[declaration],
                        device_configurations={"camera": overrides})
                self.assertEqual(cv2.captures, [])
                node.abort_session_initialization("session")
                self.assertTrue(node.release_reservation("session"))


class DeviceParameterInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_reads_adapter_definitions_over_existing_inventory_command(self):
        broker = _Broker()
        adapter = AdjustableAdapter("events", "event-device", (), True)
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        await NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), node).subscribe_commands()
        controller = Controller(component_id="control")
        communication = NatsControllerCommunication(_Boundary("controller", "control", broker))
        inventory = await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
            communication=communication, result_window_s=0.1)
        self.assertEqual(inventory["session_parameter_definitions"]["events"], adapter.get_session_parameter_definitions())
        self.assertEqual(inventory["devices"][0]["device_id"], "events")
        self.assertIsNone(node.reserved_for_session_id)
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)

    async def test_offline_inventory_is_unconfirmed_and_releases_response_subscription(self):
        broker = _Broker()
        communication = NatsControllerCommunication(_Boundary("controller", "control", broker))
        with self.assertRaises((RuntimeError, TimeoutError)):
            await Controller().get_node_inventory(RuntimeParticipant("acquisition_node", "offline"),
                communication=communication, result_window_s=0.01)
        self.assertTrue(all(not subscription.active for subscription in broker.subscriptions))

    async def test_stale_inventory_reply_cannot_confirm_parameter_definitions(self):
        broker = _Broker()
        adapter = AdjustableAdapter("events", "event-device", (), True)
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        await NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), node).subscribe_commands()
        communication = NatsControllerCommunication(_Boundary("controller", "control", broker))
        # A caller can already have a general command-result subscription.
        existing = await communication.subscribe_command_results(None)
        def stale(operation, result):
            result["payload"]["request_nonce"] = "earlier-attempt"
            return result
        broker.change_result = stale
        try:
            with self.assertRaises((RuntimeError, TimeoutError)):
                await Controller().get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
                    communication=communication, result_window_s=0.01)
        finally:
            await existing.unsubscribe()

    async def test_session_parameter_rejection_over_nats_preserves_hardware_and_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = _Broker()
            cv2 = FakeCV2([])
            camera = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", (), True, cv2_module=cv2)
            declaration = DeviceDeclaration("camera", "opencv", True, True, ())
            node = AcquisitionNode(device_manager=DeviceManager([camera]), node_id="node",
                synchronization_manager=SynchronizationManager(), ingestor=InMemoryIngestor(),
                default_local_storage_root=Path(directory), device_declarations=[declaration],
                deployment_device_configurations={"camera": OpenCVCameraConfig(0, 0, 1)})
            await NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), node).subscribe_commands()
            communication = NatsControllerCommunication(_Boundary("controller", "control", broker))
            subscription = await communication.subscribe_command_results("session")
            participant = RuntimeParticipant("acquisition_node", "node")
            try:
                self.assertTrue((await communication.request_command(participant, "reserve", "session", {}, 0.1)).success)
                result = await communication.request_command(participant, "initialize_session", "session",
                    {"selected_devices": [declaration.to_dict()],
                     "device_configurations": {"camera": {"camera_source": 5}}}, 0.1)
                self.assertFalse(result.success)
                self.assertIn("Unsupported Session parameter", result.reason)
                self.assertEqual(cv2.captures, [])
                self.assertEqual(node.reserved_for_session_id, "session")
                self.assertTrue((await communication.request_command(participant, "abort_session_initialization", "session", {}, 0.1)).success)
                self.assertTrue((await communication.request_command(participant, "release_reservation", "session", {}, 0.1)).success)
            finally:
                await subscription.unsubscribe()
