"""Adapter-defined Session choices through installed inventory and node preparation."""

import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, DeviceAdapterState,
    InMemoryIngestor, NatsAcquisitionNodeCommunication, NatsControllerCommunication,
    OpenCVCameraConfig, RuntimeParticipant, SeeedIMX219OpenCVCameraAdapter, SynchronizationManager,
    SessionConfig,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_seeed_imx219_camera_adapter import FakeCV2
from tests.test_session_launch import _Boundary, _Broker
from tests.nats_server_fixture import acquire_test_controller_authority
from lab_sync_acquisition import ServiceMaintenanceInterface


class AdjustableAdapter(ReadyFakeAdapter):
    def get_session_parameter_definitions(self):
        return {"rate": {"type": "number", "minimum": 1, "maximum": 20},
                "mode": {"type": "string", "allowed_values": ["fast", "slow"]},
                "enabled": {"type": "boolean"}}


class DeviceParameterTests(unittest.TestCase):
    def test_inventory_values_are_scoped_filtered_and_detached(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = AdjustableAdapter("events", "event-device", (), True)
            declaration = DeviceDeclaration("events", "event-device", True, True, ())
            node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
                synchronization_manager=SynchronizationManager(), ingestor=InMemoryIngestor(),
                default_local_storage_root=Path(directory), device_declarations=[declaration],
                deployment_device_configurations={"events": {"connection": "private", "rate": 2,
                    "mode": "slow", "enabled": False}})
            values = node.get_inventory()["configured_parameters"]
            self.assertEqual(values, {"scope": "installation", "session_id": None,
                "values": {"events": {"rate": 2, "mode": "slow", "enabled": False}}})
            values["values"]["events"]["rate"] = 19
            self.assertEqual(node.get_inventory()["configured_parameters"]["values"]["events"]["rate"], 2)
            self.assertTrue(node.reserve("session"))
            node.initialize_session("session", [declaration], {"events": {"rate": 8}})
            values = node.get_inventory()["configured_parameters"]
            self.assertEqual((values["scope"], values["session_id"]), ("session", "session"))
            self.assertEqual(values["values"]["events"]["rate"], 8)
            node.abort_session_initialization("session")
            node.release_reservation("session")
            self.assertEqual(node.get_inventory()["configured_parameters"]["scope"], "installation")

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
        self.assertEqual(definitions["frames_per_collect"], {"type": "integer", "minimum": 1,
            "adjustment_scope": "administrator", "initial_value": 1})
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
            for sid, overrides, count, fps in (("one", {"fps": 30}, 2, 30),
                                                ("two", {"fps": 20}, 2, 20),
                                                ("three", None, 2, 15)):
                self.assertTrue(node.reserve(sid))
                node.initialize_session(sid, selected_devices=[declaration],
                    device_configurations={"camera": overrides} if overrides is not None else None)
                self.assertEqual(camera.initialization_config.frames_per_collect, count)
                self.assertEqual(camera.initialization_config.fps, fps)
                self.assertEqual(camera.initialization_config.camera_source, 0)
                configured = node.get_inventory()["configured_parameters"]
                self.assertEqual((configured["scope"], configured["session_id"]), ("session", sid))
                self.assertEqual(configured["values"]["camera"]["fps"], fps)
                self.assertIsNone(configured["values"]["camera"]["frame_width"])
                self.assertEqual(configured["values"]["camera"]["frames_per_collect"], 2)
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
    async def test_administrative_confirmation_rejects_contradictory_loaded_or_unrelated_saved_values(self):
        import json
        from lab_sync_acquisition.service_startup import load_acquisition_node
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory) / 'hardware.json'
        document = json.loads(Path('config_templates/manual_installation/acquisition-node.json').read_bytes())
        document.update(node_id='node', local_storage_root='local', error_evidence_location='errors')
        document['devices'][0]['declaration']['device_id'] = 'camera'
        document['devices'][0]['configuration']['camera_source'] = 0
        path.write_text(json.dumps(document))
        owner = load_acquisition_node(path, 'sync')
        broker = _Broker()
        controller, communication = await self.authorized_transport(owner, broker)
        for kind in ('loaded', 'saved', 'revision'):
            def corrupt(operation, result):
                if operation == 'update_device_configuration':
                    report = result['payload']['administrative_configuration']
                    if kind == 'revision': report['revision'] = None
                    else: report[kind]['camera']['frames_per_collect'] = 100
                return result
            broker.change_result = corrupt
            revision = owner.get_inventory()['administrative_configuration']['revision']
            result = await controller.update_device_configuration(RuntimeParticipant('acquisition_node', 'node'),
                'camera', {'frames_per_collect': 3}, expected_revision=revision, administrator_id='Operator',
                authorized=True, communication=communication, result_window_s=.2)
            self.assertFalse(result.succeeded)
            self.assertEqual(result.details['outcome'], 'unconfirmed')
        broker.change_result = None

    async def authorized_transport(self, node, broker, *, real=False):
        controller = Controller(component_id="control")
        maintenance = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", "control"),
            ingestor=None, storage_manager=None, preservation_window_s=2, close_resources=AsyncMock(return_value=True))
        authority = await acquire_test_controller_authority(self, maintenance)
        if real:
            from lab_sync_acquisition import NatsCommunicationBoundary
            boundary = NatsCommunicationBoundary("acquisition_node", "node", authority.servers)
            await boundary.connect()
            await authority.ensure_streams()
            self.addAsyncCleanup(boundary.close)
        else:
            authority._require_jetstream = lambda: broker
            boundary = _Boundary("acquisition_node", "node", broker)
        boundary._client, boundary._jetstream = authority._client, authority._jetstream
        boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
        ServiceMaintenanceInterface(node, RuntimeParticipant("acquisition_node", "node"),
            ingestor=None, storage_manager=None, preservation_window_s=2, close_resources=AsyncMock(return_value=True))
        await NatsAcquisitionNodeCommunication(boundary, node).subscribe_commands()
        return controller, NatsControllerCommunication(authority)

    async def test_configured_values_through_isolated_real_nats(self):
        adapter = AdjustableAdapter("events", "event-device", (), True)
        declaration = DeviceDeclaration("events", "event-device", True, True, ())
        directory = self.enterContext(tempfile.TemporaryDirectory())
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
            synchronization_manager=SynchronizationManager(), ingestor=InMemoryIngestor(),
            default_local_storage_root=Path(directory), device_declarations=[declaration],
            deployment_device_configurations={"events": {"rate": 4, "connection": "private"}})
        controller, communication = await self.authorized_transport(node, None, real=True)
        result = await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
            communication=communication, result_window_s=2)
        self.assertEqual(result["configured_parameters"], {"scope": "installation", "session_id": None,
            "values": {"events": {"rate": 4}}})
        self.assertTrue(controller.create_session(SessionConfig([declaration], None, {}, None, session_id="session")).succeeded)
        self.assertTrue(node.reserve("session"))
        node.initialize_session("session", [declaration], {"events": {"rate": 8}})
        result = await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
            communication=communication, result_window_s=2)
        self.assertEqual(result["configured_parameters"], {"scope": "session", "session_id": "session",
            "values": {"events": {"rate": 8}}})
        node.abort_session_initialization("session")
        node.release_reservation("session")

    async def test_inventory_readback_rejects_invalid_values_and_scope_and_accepts_legacy(self):
        from copy import deepcopy
        broker = _Broker()
        adapter = AdjustableAdapter("events", "event-device", (), True)
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
            synchronization_manager=SynchronizationManager(),
            deployment_device_configurations={"events": {"rate": 2}})
        controller, communication = await self.authorized_transport(node, broker)
        participant = RuntimeParticipant("acquisition_node", "node")
        valid = node.get_inventory()["configured_parameters"]
        for invalid in (None, [], {**valid, "scope": "session", "session_id": "unrelated"},
                        {**valid, "session_id": "unexpected"}, {**valid, "values": {"unknown": {}}},
                        {**valid, "values": {"events": {"connection": "private"}}},
                        {**valid, "values": {"events": {"rate": True}}},
                        {**valid, "values": {"events": {"rate": 30}}},
                        {**valid, "values": {"events": {"rate": float("inf")}}}):
            def corrupt(operation, result):
                result["payload"]["configured_parameters"] = deepcopy(invalid)
                return result
            broker.change_result = corrupt
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError, RuntimeError)):
                await controller.get_node_inventory(participant, communication=communication, result_window_s=.1)
        def legacy(operation, result):
            result["payload"].pop("configured_parameters")
            return result
        broker.change_result = legacy
        inventory = await controller.get_node_inventory(participant, communication=communication, result_window_s=.1)
        self.assertNotIn("configured_parameters", inventory)
        broker.change_result = None
        inventory = await controller.get_node_inventory(participant, communication=communication, result_window_s=.1)
        self.assertEqual(inventory["configured_parameters"], valid)

    async def test_controller_reads_adapter_definitions_over_existing_inventory_command(self):
        broker = _Broker()
        adapter = AdjustableAdapter("events", "event-device", (), True)
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        controller, communication = await self.authorized_transport(node, broker)
        inventory = await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
            communication=communication, result_window_s=0.1)
        self.assertEqual(inventory["session_parameter_definitions"]["events"], adapter.get_session_parameter_definitions())
        self.assertEqual(inventory["devices"][0]["device_id"], "events")
        self.assertIsNone(node.reserved_for_session_id)
        self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)

    async def test_offline_inventory_is_unconfirmed_and_releases_response_subscription(self):
        broker = _Broker()
        node = AcquisitionNode(device_manager=DeviceManager([AdjustableAdapter("events", "event-device", (), True)]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        controller, communication = await self.authorized_transport(node, broker)
        with self.assertRaises((RuntimeError, TimeoutError)):
            await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "offline"),
                communication=communication, result_window_s=0.01)
        self.assertFalse(any(subscription.active and '.offline.' in subscription.subject for subscription in broker.subscriptions))

    async def test_stale_inventory_reply_cannot_confirm_parameter_definitions(self):
        broker = _Broker()
        adapter = AdjustableAdapter("events", "event-device", (), True)
        node = AcquisitionNode(device_manager=DeviceManager([adapter]), node_id="node",
                               synchronization_manager=SynchronizationManager())
        controller, communication = await self.authorized_transport(node, broker)
        # A caller can already have a general command-result subscription.
        existing = await communication.subscribe_command_results(None)
        def stale(operation, result):
            result["payload"]["request_nonce"] = "earlier-attempt"
            return result
        broker.change_result = stale
        try:
            with self.assertRaises((RuntimeError, TimeoutError)):
                await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
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
            _, communication = await self.authorized_transport(node, broker)
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
