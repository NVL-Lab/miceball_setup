"""Persistent administrative settings through the real node configuration boundary."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
import asyncio
from threading import Thread
from unittest.mock import AsyncMock

from lab_sync_acquisition.service_startup import load_acquisition_node


class DeviceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / "explicit-hardware.json"
        self.document = json.loads(Path("config_templates/manual_installation/acquisition-node.json").read_text())
        self.document.update(node_id="node", local_storage_root="local", error_evidence_location="errors")
        self.document["devices"][0]["declaration"]["device_id"] = "camera"
        self.document["devices"][0]["configuration"]["camera_source"] = 0
        self.path.write_text(json.dumps(self.document), encoding="utf-8")
        self.node = load_acquisition_node(self.path, "sync")

    def test_save_changes_only_persistent_settings_and_restart_loads_them(self):
        before = self.node.get_inventory()["administrative_configuration"]
        self.assertEqual(before["loaded"]["camera"], {"frames_per_collect": 1})
        result = self.node.update_device_configuration("camera", {"frames_per_collect": 4},
            expected_revision=before["revision"], administrator_id="Operator", authorized=True)
        self.assertEqual(result["outcome"], "succeeded")
        saved = self.node.get_inventory()["administrative_configuration"]
        self.assertEqual(saved["saved"]["camera"], {"frames_per_collect": 4})
        self.assertEqual(saved["loaded"]["camera"], {"frames_per_collect": 1})
        expected = json.loads(json.dumps(self.document))
        expected["devices"][0]["configuration"]["frames_per_collect"] = 4
        self.assertEqual(json.loads(self.path.read_text()), expected)
        restarted = load_acquisition_node(self.path, "sync")
        self.assertEqual(restarted.get_inventory()["administrative_configuration"]["loaded"]["camera"],
                         {"frames_per_collect": 4})

    def test_ordinary_overrides_cannot_change_administrative_values(self):
        adapter = self.node._device_manager.adapters[0]
        with self.assertRaisesRegex(ValueError, "administrator"):
            adapter.resolve_session_configuration(self.document["devices"][0]["configuration"], {"frames_per_collect": 2})
        self.assertEqual(adapter.resolve_session_configuration(self.document["devices"][0]["configuration"], {"fps": 30})["fps"], 30)

    def test_saved_settings_only_apply_to_subsequent_session_after_normal_restart(self):
        from tests.test_seeed_imx219_camera_adapter import FakeCV2
        self.save(4)
        for owner, expected in ((self.node, 1), (load_acquisition_node(self.path, 'sync'), 4)):
            adapter = owner._device_manager.adapters[0]
            adapter._cv2 = FakeCV2([])
            owner.reserve('session')
            owner.initialize_session('session', owner.declared_devices)
            snapshot = owner.get_inventory()['configured_parameters']
            self.assertEqual(snapshot['values']['camera']['frames_per_collect'], expected)
            with self.assertRaises(RuntimeError):
                owner.update_device_configuration('camera', {'frames_per_collect': 5},
                    expected_revision=owner.get_inventory()['administrative_configuration']['revision'],
                    administrator_id='Operator', authorized=True)
            self.assertEqual(owner.get_inventory()['configured_parameters'], snapshot)
            owner.abort_session_initialization('session')
            owner.release_reservation('session')

    def save(self, value, **kwargs):
        revision = self.node.get_inventory()['administrative_configuration']['revision']
        return self.node.update_device_configuration('camera', {'frames_per_collect': value},
            **dict(expected_revision=revision, administrator_id='Operator', authorized=True, **kwargs))

    def test_invalid_unauthorized_reserved_and_stale_writes_preserve_file(self):
        before = self.path.read_bytes()
        for value in (True, 0, -1, '2', 1.5, None):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                self.save(value)
        revision = self.node.get_inventory()['administrative_configuration']['revision']
        for identity, allowed in (('', True), ('Operator', False)):
            with self.assertRaises(PermissionError):
                self.node.update_device_configuration('camera', {'frames_per_collect': 2},
                    expected_revision=revision, administrator_id=identity, authorized=allowed)
        self.node.reserve('session')
        with self.assertRaises(RuntimeError): self.save(2)
        self.node.release_reservation('session')
        self.document['role'] = 'externally updated'
        self.path.write_text(json.dumps(self.document))
        with self.assertRaises(ValueError):
            self.node.update_device_configuration('camera', {'frames_per_collect': 2},
                expected_revision=revision, administrator_id='Operator', authorized=True)
        self.assertNotEqual(self.path.read_bytes(), before)
        self.assertEqual(json.loads(self.path.read_bytes()), self.document)

    def test_unavailable_or_malformed_source_does_not_fabricate_saved_values(self):
        from lab_sync_acquisition import AcquisitionNode, DeviceManager
        from tests.fakes import ReadyFakeAdapter
        source_less = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter('device', 'fake', (), False)]),
            node_id='other', synchronization_source_id='sync')
        self.assertFalse(source_less.get_inventory()['administrative_configuration']['available'])
        for contents in (b'{', b'null', b'[]'):
            self.path.write_bytes(contents)
            report = self.node.get_inventory()['administrative_configuration']
            self.assertFalse(report['available']); self.assertIsNone(report['revision']); self.assertEqual(report['saved'], {})
            with self.assertRaises((ValueError, TypeError)):
                self.save(2)
            self.assertEqual(self.path.read_bytes(), contents)
        self.path.unlink()
        self.assertFalse(self.node.get_inventory()['administrative_configuration']['available'])
        self.assertFalse(self.path.exists())

    def test_precommit_failure_and_postcommit_uncertainty_reconcile_without_live_application(self):
        from lab_sync_acquisition import configuration_publication as publication
        before = self.path.read_bytes()
        with patch.object(publication, 'preserve_configuration_access', side_effect=OSError('staging failed')):
            with self.assertRaises(OSError): self.save(2)
        self.assertEqual(self.path.read_bytes(), before)
        original = publication.replace_configuration_file
        def interrupted(path, temporary):
            original(path, temporary)
            raise OSError('confirmation interrupted')
        with patch.object(publication, 'replace_configuration_file', side_effect=interrupted):
            result = self.save(3)
        self.assertEqual(result['outcome'], 'unconfirmed')
        report = self.node.get_inventory()['administrative_configuration']
        self.assertEqual(report['saved']['camera']['frames_per_collect'], 3)
        self.assertEqual(report['loaded']['camera']['frames_per_collect'], 1)
        self.assertEqual(self.save(4)['outcome'], 'succeeded')

    def test_supported_writers_serialize_at_final_publication_boundary(self):
        from lab_sync_acquisition import configuration_publication as publication
        entered, release = Event(), Event()
        other = load_acquisition_node(self.path, 'sync')
        revision = self.node.get_inventory()['administrative_configuration']['revision']
        original = publication.replace_configuration_file
        def held(path, temporary):
            entered.set()
            if not release.wait(5): raise RuntimeError('Test publication gate expired')
            original(path, temporary)
        def save(owner, value):
            return owner.update_device_configuration('camera', {'frames_per_collect': value},
                expected_revision=revision, administrator_id='Operator', authorized=True)
        with ThreadPoolExecutor(2) as pool, patch.object(publication, 'replace_configuration_file', side_effect=held):
            first = pool.submit(save, self.node, 2)
            self.assertTrue(entered.wait(5))
            second = pool.submit(save, other, 3)
            try:
                time.sleep(.05)
                self.assertFalse(second.done())
            finally: release.set()
            self.assertEqual(first.result(5)['outcome'], 'succeeded')
            with self.assertRaises(ValueError): second.result(5)
        self.assertEqual(json.loads(self.path.read_bytes())['devices'][0]['configuration']['frames_per_collect'], 2)

    def test_detectable_out_of_band_change_is_not_overwritten(self):
        from lab_sync_acquisition import configuration_publication as publication
        original = publication.preserve_configuration_access
        changed = {**self.document, 'role': 'external'}
        def edit(path, temporary):
            original(path, temporary)
            self.path.write_text(json.dumps(changed))
        with patch.object(publication, 'preserve_configuration_access', side_effect=edit):
            with self.assertRaises(ValueError): self.save(2)
        self.assertEqual(json.loads(self.path.read_bytes()), changed)

    def test_file_access_controls_survive_replacement(self):
        import os, stat, subprocess
        mode = stat.S_IMODE(self.path.stat().st_mode)
        acl = subprocess.check_output(['icacls', str(self.path)]) if os.name == 'nt' else None
        self.save(3)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), mode)
        if acl is not None:
            self.assertEqual(subprocess.check_output(['icacls', str(self.path)]), acl)

    def test_second_adapter_and_multiple_devices_use_the_same_publication_contract(self):
        from lab_sync_acquisition import deployment_configuration as configuration, service_startup
        from tests.fakes import ReadyFakeAdapter
        class TechnicalAdapter(ReadyFakeAdapter):
            def get_session_parameter_definitions(self):
                return {'service_interval': {'type': 'integer', 'minimum': 1, 'adjustment_scope': 'administrator'},
                        'rate': {'type': 'number', 'minimum': 1}}
        original = configuration.create_installed_adapter
        def create(name, declaration):
            if name == 'technical-test':
                return TechnicalAdapter(declaration.device_id, declaration.device_type, (), False)
            return original(name, declaration)
        item = json.loads(json.dumps(self.document['devices'][0]))
        item['adapter'] = 'technical-test'; item['declaration']['device_id'] = 'other'
        item['configuration'] = {'service_interval': 5, 'rate': 2, 'connection': 'retained'}
        self.document['devices'].append(item)
        self.path.write_text(json.dumps(self.document))
        with patch.object(configuration, 'create_installed_adapter', side_effect=create), \
                patch.object(service_startup, 'create_installed_adapter', side_effect=create):
            owner = load_acquisition_node(self.path, 'sync')
            revision = owner.get_inventory()['administrative_configuration']['revision']
            result = owner.update_device_configuration('other', {'service_interval': 8},
                expected_revision=revision, administrator_id='Operator', authorized=True)
            self.assertEqual(result['outcome'], 'succeeded')
            report = owner.get_inventory()['administrative_configuration']
            self.assertEqual(report['loaded']['other'], {'service_interval': 5})
            self.assertEqual(report['saved']['other'], {'service_interval': 8})
        saved = json.loads(self.path.read_bytes())
        self.assertEqual(saved['devices'][0], self.document['devices'][0])
        self.assertEqual(saved['devices'][1]['configuration']['connection'], 'retained')


class DistributedDeviceConfigurationTests(unittest.IsolatedAsyncioTestCase):
    setUp = DeviceConfigurationTests.setUp

    async def asyncSetUp(self):
        from lab_sync_acquisition import Controller, RuntimeParticipant, ServiceMaintenanceInterface
        from tests.nats_server_fixture import acquire_test_controller_authority
        self.participant = RuntimeParticipant('acquisition_node', 'node')
        self.controller = Controller(component_id='control')
        maintenance = ServiceMaintenanceInterface(self.controller, RuntimeParticipant('controller', 'control'),
            ingestor=None, storage_manager=None, preservation_window_s=2, close_resources=AsyncMock(return_value=True))
        self.authority = await acquire_test_controller_authority(self, maintenance)
        await self.authority.ensure_streams()
        self.ready = Event()
        self.thread_errors = []
        def responder():
            async def serve():
                from lab_sync_acquisition import NatsCommunicationBoundary, NatsAcquisitionNodeCommunication
                boundary = NatsCommunicationBoundary('acquisition_node', 'node', self.authority.servers)
                await boundary.connect()
                boundary.configure_controller_authority(account='LAB', bucket='AUTHORITY', key='controller', timeout_s=2)
                ServiceMaintenanceInterface(self.node, self.participant, ingestor=None, storage_manager=None,
                    preservation_window_s=2, close_resources=AsyncMock(return_value=True))
                self.responder_loop = asyncio.get_running_loop()
                self.done = asyncio.Event()
                await NatsAcquisitionNodeCommunication(boundary, self.node).subscribe_commands()
                self.ready.set()
                try: await self.done.wait()
                finally: await boundary.close()
            try: asyncio.run(serve())
            except BaseException as error:
                self.thread_errors.append(error); self.ready.set()
        self.worker = Thread(target=responder)
        self.worker.start()
        self.addAsyncCleanup(self.stop_responder)
        self.assertTrue(await asyncio.to_thread(self.ready.wait, 10))
        self.assertEqual(self.thread_errors, [])
        from lab_sync_acquisition import NatsControllerCommunication
        self.communication = NatsControllerCommunication(self.authority)

    async def stop_responder(self):
        if hasattr(self, 'done'):
            self.responder_loop.call_soon_threadsafe(self.done.set)
        await asyncio.to_thread(self.worker.join, 10)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.thread_errors, [])

    async def save(self, value, **kwargs):
        revision = self.node.get_inventory()['administrative_configuration']['revision']
        return await self.controller.update_device_configuration(self.participant, 'camera', {'frames_per_collect': value},
            expected_revision=revision, administrator_id='Operator', authorized=True,
            communication=self.communication, result_window_s=3, **kwargs)

    async def test_nats_save_keeps_loaded_values_and_refuses_reserved_or_unauthorized_updates(self):
        result = await self.save(3)
        self.assertTrue(result.succeeded, result)
        report = await self.controller.get_node_inventory(self.participant, communication=self.communication, result_window_s=3)
        self.assertEqual(report['administrative_configuration']['saved']['camera']['frames_per_collect'], 3)
        self.assertEqual(report['administrative_configuration']['loaded']['camera']['frames_per_collect'], 1)
        reserved = await self.communication.request_runtime_command(self.participant, 'reserve', 'session', {}, 3)
        self.assertTrue(reserved.success)
        self.assertFalse((await self.save(4)).succeeded)
        self.assertEqual(json.loads(self.path.read_bytes())['devices'][0]['configuration']['frames_per_collect'], 3)
        released = await self.communication.request_runtime_command(self.participant, 'release_reservation', 'session', {}, 3)
        self.assertTrue(released.success)
        result = await self.communication.request_runtime_command(self.participant, 'update_device_configuration', None,
            dict(device_id='camera', parameters={'frames_per_collect': 5},
                expected_revision=report['administrative_configuration']['revision'], administrator_id='Operator', authorized=False), 3)
        self.assertFalse(result.success)

    async def test_independently_scheduled_reservation_cannot_cross_publication(self):
        from lab_sync_acquisition import configuration_publication as publication
        entered, release = Event(), Event()
        original = publication.replace_configuration_file
        def held(path, temporary):
            entered.set()
            if not release.wait(5): raise RuntimeError('Publication gate expired')
            original(path, temporary)
        with patch.object(publication, 'replace_configuration_file', side_effect=held):
            save = asyncio.create_task(self.save(2))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                reserve = asyncio.create_task(self.communication.request_runtime_command(self.participant, 'reserve', 'later', {}, 3))
                await asyncio.sleep(.1)
                self.assertFalse(reserve.done())
            finally: release.set()
            result = await save
            self.assertTrue(result.succeeded, result)
            self.assertTrue((await reserve).success)
        self.assertEqual(self.node.reserved_for_session_id, 'later')
        self.assertFalse((await self.save(3)).succeeded)
        self.node.release_reservation('later')

    async def test_stop_preparation_cannot_cross_publication_or_admit_later_updates(self):
        from lab_sync_acquisition import configuration_publication as publication
        entered, release = Event(), Event()
        original = publication.replace_configuration_file
        def held(path, temporary):
            entered.set()
            if not release.wait(5): raise RuntimeError('Publication gate expired')
            original(path, temporary)
        with patch.object(publication, 'replace_configuration_file', side_effect=held):
            save = asyncio.create_task(self.save(2))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                stop = asyncio.create_task(self.communication.request_runtime_command(self.participant, 'stop', None,
                    {'administrator_id': 'Operator', 'authorized': True, 'stop_attempt_id': 'stop-after-save'}, 3))
                await asyncio.sleep(.1)
                self.assertFalse(stop.done())
            finally: release.set()
            self.assertTrue((await save).succeeded)
            result = await stop
            self.assertIsNotNone(result)
        self.assertEqual(result.payload.get('attempt', {}).get('stop_attempt_id'), 'stop-after-save', result)
        self.assertFalse((await self.save(3)).succeeded)
        self.assertEqual(json.loads(self.path.read_bytes())['devices'][0]['configuration']['frames_per_collect'], 2)

    async def test_uncertain_save_duplicate_does_not_republish_and_conflicting_identity_is_rejected(self):
        from lab_sync_acquisition import configuration_publication as publication
        revision = self.node.get_inventory()['administrative_configuration']['revision']
        payload = dict(device_id='camera', parameters={'frames_per_collect': 3}, expected_revision=revision,
            administrator_id='Operator', authorized=True)
        original = publication.replace_configuration_file
        def interrupted(path, temporary):
            original(path, temporary)
            raise OSError('Confirmation unavailable')
        with patch.object(publication, 'replace_configuration_file', side_effect=interrupted) as publisher:
            first = await self.communication.request_runtime_command(self.participant, 'update_device_configuration',
                None, payload, 3, command_id='explicit-save')
            self.assertIsNotNone(first)
            self.assertEqual(first.payload['outcome'], 'unconfirmed')
            contents = self.path.read_bytes()
            duplicate = await self.communication.request_runtime_command(self.participant, 'update_device_configuration',
                None, payload, 3, command_id='explicit-save')
            self.assertIsNotNone(duplicate)
            self.assertEqual(duplicate.payload['outcome'], 'unconfirmed')
            conflict = await self.communication.request_runtime_command(self.participant, 'update_device_configuration',
                None, {**payload, 'parameters': {'frames_per_collect': 4}}, 3, command_id='explicit-save')
            self.assertFalse(conflict.success)
            self.assertIn('Conflicting', conflict.reason)
            self.assertEqual(publisher.call_count, 1)
            self.assertEqual(self.path.read_bytes(), contents)
