"""Interactive setup workflows with real configuration validation and isolated I/O."""

import contextlib
import asyncio
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from scripts import install_framework as installer
from lab_sync_acquisition.deployment_configuration import load_service_configuration
from tests.nats_server_fixture import NATS_SERVER, restartable_jetstream_server


class FrameworkInstallerTests(unittest.TestCase):
    def test_new_device_uses_adapter_initial_value_without_changing_unrelated_fields(self):
        self.answers['Local roles'] = 'acquisition-node'
        path = self.hardware()
        document = json.loads(path.read_bytes())
        del document['devices'][0]['configuration']['frames_per_collect']
        path.write_text(json.dumps(document))
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        expected = json.loads(json.dumps(document))
        expected['devices'][0]['configuration']['frames_per_collect'] = 1
        self.assertEqual(json.loads(path.read_bytes()), expected)
        self.assertIn('takes effect on normal node restart', output)

    def test_device_advanced_settings_preserve_independent_values_and_existing_role_bytes(self):
        self.answers['Local roles'] = 'acquisition-node'
        path = self.hardware()
        document = json.loads(path.read_bytes())
        other = json.loads(json.dumps(document['devices'][0]))
        other['declaration']['device_id'] = 'other'
        other['configuration']['frames_per_collect'] = 7
        document['devices'].append(other)
        path.write_text(json.dumps(document))
        self.assertEqual(self.run_setup()[0], 0)
        service = self.config / 'acquisition-node-service.json'
        original = service.read_bytes()
        self.answers['Advanced administrative device settings'] = 'yes'
        self.answers['camera / frames_per_collect'] = '3'
        self.answers['other / frames_per_collect'] = '9'
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(service.read_bytes(), original)
        self.assertEqual([item['configuration']['frames_per_collect'] for item in json.loads(path.read_bytes())['devices']], [3, 9])
        retained = path.read_bytes()
        self.answers['Advanced administrative device settings'] = 'no'
        self.assertEqual(self.run_setup()[0], 0)
        self.assertEqual(path.read_bytes(), retained)

    def test_invalid_or_cancelled_device_advanced_settings_preserve_hardware(self):
        self.answers['Local roles'] = 'acquisition-node'
        path = self.hardware()
        original = path.read_bytes()
        self.answers['Advanced administrative device settings'] = 'yes'
        self.answers['camera / frames_per_collect'] = 'true'
        self.assertEqual(self.run_setup()[0], 1)
        self.assertEqual(path.read_bytes(), original)
        self.answers['camera / frames_per_collect'] = '3'
        self.answers['Install the displayed'] = 'no'
        self.assertEqual(self.run_setup()[0], 2)
        self.assertEqual(path.read_bytes(), original)

    def test_duplicate_hardware_fields_are_not_silently_repaired(self):
        self.answers['Local roles'] = 'acquisition-node'
        path = self.hardware()
        original = path.read_text().replace('"frames_per_collect": 1', '"frames_per_collect": 1, "frames_per_collect": 2')
        path.write_text(original)
        code, _, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(path.read_text(), original)
        self.assertFalse(any('pip' in call for call in self.calls))

    def gui_package(self):
        package = self.checkout / 'gui'
        package.mkdir(exist_ok=True)
        (package / 'pyproject.toml').write_text('[project]\nname="miceball-gui"\nversion="0.1.0"\n')
        source = Path(__file__).resolve().parents[1] / 'gui' / 'src' / 'miceball_gui'
        target = package / 'src' / 'miceball_gui'
        target.mkdir(parents=True, exist_ok=True)
        for module in source.glob('*.py'):
            shutil.copyfile(module, target / module.name)
        (target / 'static').mkdir(exist_ok=True)
        self.answers['Install or reuse optional GUI'] = 'yes'
        self.answers['Approve these exact local Controller'] = 'yes'
        return package

    def test_optional_gui_installs_separately_and_configures_new_controller_without_startup(self):
        package = self.gui_package()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertTrue(any('pip' in a and a[-1] == str(package) for a in self.calls))
        controller = load_service_configuration(self.config / 'controller.json', 'controller')
        self.assertEqual(controller['external_client_id'], 'gui-control')
        self.assertTrue(controller['browser_control_required'])
        self.assertEqual(json.loads((self.config / 'gui-connection.json').read_text()), {'servers': ['nats://broker:4222']})
        self.assertIn('GUI LAUNCH:', output)
        self.assertIn('GUI browser address: http://127.0.0.1:8043', output)
        self.assertIn('GUI process NOT STARTED; browser control NOT ACQUIRED', output)
        self.assertFalse(any('miceball_gui.backend' in a for a in self.calls))

    def test_gui_declined_never_installs_or_creates_gui_configuration(self):
        package = self.gui_package()
        self.answers['Install or reuse optional GUI'] = 'no'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertFalse(any('pip' in a and a[-1] == str(package) for a in self.calls))
        self.assertFalse((self.config / 'gui-connection.json').exists())
        self.assertNotIn('GUI LAUNCH:', output)

    def test_gui_synchronization_initialization_overrides_and_update_preservation(self):
        self.gui_package()
        self.answers.update({'Advanced synchronization settings': 'yes', 'exchanges': '5'})
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        from miceball_gui.catalog_store import CatalogStore
        path = self.config / 'gui-catalog.sqlite3'
        store = CatalogStore(path)
        self.assertEqual(store.read()['synchronization_configuration']['exchanges'], 5)
        snapshot = store.read()
        store.put_synchronization({**snapshot['synchronization_configuration'], 'exchanges': 7},
            expected_revision=snapshot['revision'], administrator_id='Operator', authorized=True)
        before = store.read()
        self.answers.update({'exchanges': '9', 'Use this existing connection file': 'yes'})
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(CatalogStore(path).read(), before)

    def test_invalid_gui_synchronization_override_refuses_initialization(self):
        self.gui_package()
        self.answers.update({'Advanced synchronization settings': 'yes', 'exchanges': '1'})
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn('at least two', errors)
        self.assertFalse((self.config / 'gui-catalog.sqlite3').exists())
        self.assertFalse((self.config / 'controller.json').exists())

    def test_requested_unavailable_gui_keeps_core_installation_and_reports_pending(self):
        self.answers['Install or reuse optional GUI'] = 'yes'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn('GUI package unavailable', output)
        self.assertTrue((self.config / 'controller.json').exists())
        self.assertFalse((self.config / 'gui-connection.json').exists())

    def test_incomplete_gui_checkout_cannot_claim_package_availability(self):
        package = self.gui_package()
        (package / 'src' / 'miceball_gui' / 'backend.py').unlink()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn('GUI package unavailable', output)
        self.assertFalse(any('pip' in a and a[-1] == str(package) for a in self.calls))
        self.assertFalse((self.config / 'gui-connection.json').exists())

    def test_compatible_installed_gui_can_be_explicitly_reused_without_reinstallation(self):
        self.create_environment()
        self.gui_version = '0.1.0'
        self.answers.update({'Install or reuse optional GUI': 'yes', 'Reuse the installed GUI': 'yes',
                             'Approve these exact local Controller': 'yes'})
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertFalse(any('pip' in a and a[-1] == str(self.checkout / 'gui') for a in self.calls))
        self.assertTrue((self.config / 'gui-connection.json').exists())

    def test_failed_gui_install_does_not_publish_configuration(self):
        self.gui_package()
        self.failure = 'gui-pip'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertFalse((self.config / 'controller.json').exists())
        self.assertFalse((self.config / 'gui-connection.json').exists())
        self.assertNotIn('GUI LAUNCH:', output)

    def test_gui_dependency_validation_failure_preserves_existing_controller(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        before = path.read_bytes()
        self.gui_package()
        self.failure = 'gui-dependencies'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.config / 'gui-connection.json').exists())
        self.assertIn('GUI dependencies or import unavailable', errors)
        self.assertNotIn('GUI LAUNCH:', output)

    def test_matching_existing_controller_and_gui_connection_files_are_not_rewritten(self):
        self.assertEqual(self.run_setup()[0], 0)
        controller = self.config / 'controller.json'
        data = json.loads(controller.read_text())
        data.update(external_client_id='existing-gui', browser_control_required=True,
                    nats_username='service-user', nats_password='service-secret')
        controller.write_text(json.dumps(data))
        connection = self.config / 'gui-connection.json'
        connection.write_text(json.dumps({'servers': ['nats://broker:4222'], 'nats_username': 'gui-user',
                                          'nats_password': 'gui-secret @%40\u03bb '}))
        before = {p: p.read_bytes() for p in (controller, connection)}
        metadata = {p: (p.stat().st_ino, p.stat().st_mtime_ns) for p in before}
        self.gui_package()
        self.answers['Use this existing connection file'] = 'yes'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
            self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), metadata[path])
        self.assertIn('already configured', output)
        visible = output + errors + str(self.calls) + str(self.prompts)
        for value in ('service-user', 'service-secret', 'gui-user', 'gui-secret'):
            self.assertNotIn(value, visible)
        self.assertTrue(any(p.get('nats_password') == 'gui-secret @%40\u03bb ' for p in self.connections))

    def test_existing_controller_update_requires_approval_and_preserves_unrelated_values(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        old = json.loads(path.read_text())
        old.update(external_client_id='old-gui', nats_username='private-user', nats_password='private-secret')
        path.write_text(json.dumps(old))
        self.gui_package()
        self.answers['GUI connection name'] = 'new-gui'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        new = json.loads(path.read_text())
        self.assertEqual(new, dict(old, external_client_id='new-gui', browser_control_required=True))
        self.assertIn('"old": "old-gui", "new": "new-gui"', output)
        self.assertIn('Restart Controller manually', output)
        self.assertNotIn('private-secret', output + errors + str(self.calls))
        self.assertNotIn('nats_password', json.loads((self.config / 'gui-connection.json').read_text()))

    def test_declined_controller_update_preserves_file_and_reports_pending(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        before = path.read_bytes()
        self.gui_package()
        self.answers['Approve these exact local Controller'] = 'no'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('Controller GUI access PENDING', output)
        self.assertTrue((self.config / 'gui-connection.json').exists())

    def test_changed_controller_cannot_receive_a_stale_approved_gui_update(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        changed = dict(json.loads(path.read_text()), result_window_s=7)
        changed_bytes = json.dumps(changed).encode()
        self.gui_package()
        original = installer._publish_controller_gui_update
        def changed_before_publish(target, expected, contents):
            path.write_bytes(changed_bytes)
            return original(target, expected, contents)
        with patch.object(installer, '_publish_controller_gui_update', side_effect=changed_before_publish):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(path.read_bytes(), changed_bytes)
        self.assertIn('approved GUI update was not applied', errors)

    def test_failed_or_interrupted_controller_publication_preserves_original(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        before = path.read_bytes()
        self.gui_package()
        for failure, expected in ((OSError('replace failed'), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(failure=type(failure).__name__), patch.dict(
                    installer._PUBLICATION['publish_configuration'].__globals__,
                    {'replace_configuration_file': unittest.mock.Mock(side_effect=failure)}):
                code, output, errors = self.run_setup()
            self.assertEqual(code, expected)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(self.config.glob('.gui-controller-*')), [])
            (self.config / 'gui-connection.json').unlink(missing_ok=True)

    def test_remote_controller_import_is_read_only_and_requires_owner_side_action(self):
        self.gui_package()
        self.answers['Local roles'] = 'ingestor-storage'
        source = self.shared_source()
        data = json.loads(source.read_text())
        data.pop('storage_root')
        data.pop('node_config')
        data.update(external_client_id='existing-remote-gui', browser_control_required=True)
        source.write_text(json.dumps(data))
        self.answers['Existing laboratory Controller configuration for GUI'] = str(source)
        before = source.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse((self.config / 'controller.json').exists())
        self.assertIn('Controller GUI access PENDING on its owning computer', output)
        self.assertIn('declares matching GUI access', output)
        self.assertNotIn('not-to-import-secret', output + errors + str(self.calls))

    def test_gui_credentials_and_offline_connection_remain_private_and_nonblocking(self):
        self.gui_package()
        self.answers.update({'Use explicit NATS username/password for GUI': 'yes',
                             'GUI nats_username': 'independent-gui-user', 'GUI nats_password': ' exact \r\n\t%40\u03bb '})
        self.failure = 'nats'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        settings = json.loads((self.config / 'gui-connection.json').read_text())
        self.assertEqual(settings['nats_password'], ' exact \r\n\t%40\u03bb ')
        self.assertIn('GUI NATS connectivity PENDING / NOT VERIFIED', output)
        self.assertIn('GUI LAUNCH:', output)
        self.assertNotIn('independent-gui-user', output + errors + str(self.calls) + str(self.prompts))
        self.assertNotIn(' exact \r\n\t%40\u03bb ', output + errors + str(self.calls))

    def test_gui_origin_and_identity_are_validated_before_installation_changes(self):
        self.gui_package()
        for field, value in (('GUI browser address', 'http://host/path'), ('GUI connection name', 'bad.*'),
                             ('GUI browser address', 'http://user:private-secret@host'), ('GUI bind port', '0'),
                             ('GUI bind host', 'http://invalid-host'),
                             ('GUI connection configuration file', str(self.config / 'controller.json'))):
            with self.subTest(field=field, value=value):
                self.answers[field] = value
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertFalse(self.environment.exists())
                self.assertFalse((self.config / 'gui-connection.json').exists())
                self.assertNotIn('private-secret', output + errors)
                del self.answers[field]

    def test_invalid_existing_gui_authentication_is_refused_without_rewriting_it(self):
        self.gui_package()
        self.config.mkdir()
        path = self.config / 'gui-connection.json'
        for fields in ({'nats_username': 'private-user'}, {'nats_username': 'private-user', 'nats_password': ''},
                       {'nats_username': 'private-user', 'nats_password': None},
                       {'servers': ['nats://embedded:private-secret@broker:4222'],
                        'nats_username': 'private-user', 'nats_password': 'other-secret'}):
            with self.subTest(fields=list(fields)):
                path.write_text(json.dumps({'servers': ['nats://broker:4222'], **fields}))
                before = path.read_bytes()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(self.environment.exists())
                for value in ('private-user', 'private-secret', 'other-secret'):
                    self.assertNotIn(value, output + errors + str(self.calls))

    def test_gui_launch_commands_use_native_shell_and_confirmed_browser_origin(self):
        for platform in ('win32', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                self.platform = platform
                self.checkout = Path(directory) / 'checkout with spaces'
                self.checkout.mkdir()
                (self.checkout / 'pyproject.toml').write_text('[project]\nname="lab-sync-acquisition"\n')
                self.environment = self.checkout / '.venv'
                self.config = Path(directory) / 'configuration'
                self.gui_package()
                self.answers['GUI browser address'] = 'http://gui-lab:8043'
                self.answers['GUI bind host'] = '0.0.0.0'
                self.answers['GUI connection name'] = 'first-gui'
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                command = next(l for l in output.splitlines() if l.startswith('GUI LAUNCH:'))
                self.assertIn('miceball_gui.backend', command)
                self.assertIn('gui-connection.json', command)
                self.assertEqual(command.startswith('GUI LAUNCH: & '), platform == 'win32')
                self.assertIn('GUI browser address: http://gui-lab:8043', output)
                self.answers['Use this existing connection file'] = 'yes'
                self.answers['GUI connection name'] = 'second-gui'
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                self.assertEqual(load_service_configuration(self.config / 'controller.json', 'controller')['external_client_id'], 'second-gui')

    def test_gui_launch_preserves_valid_client_identity_beginning_with_a_hyphen(self):
        self.gui_package()
        self.platform = 'linux'
        self.answers['GUI connection name'] = '-gui-client'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        command = next(line.removeprefix('GUI LAUNCH: ') for line in output.splitlines() if line.startswith('GUI LAUNCH:'))
        arguments = installer.shlex.split(command)[3:]
        with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'gui' / 'src'), *sys.path]):
            from miceball_gui import backend
        with patch.object(sys, 'argv', ['miceball-gui', *arguments]), patch.object(backend.web, 'run_app'), \
                patch.object(backend, 'create_gui_app') as create:
            backend.main()
        self.assertEqual(create.call_args.kwargs['client_id'], '-gui-client')

    def test_gui_validation_child_uses_production_gui_without_starting_it(self):
        self.gui_package()
        shutil.copytree(Path(__file__).resolve().parents[1] / 'src', self.checkout / 'src',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.real_validation = True
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertTrue(any(installer.VALIDATE_GUI in a for a in self.calls))

    def test_scientific_storage_selects_a_volume_without_largest_disk_or_early_writes(self):
        small, large = self.root / 'selected volume', self.root / 'larger volume'
        small.mkdir()
        large.mkdir()
        self.storage_volumes = [(small, 'mounted local filesystem'), (large, 'mounted local filesystem')]
        self.answers['Local roles'] = 'ingestor-storage'
        self.answers['Choose primary scientific-data location'] = '1'
        original_mkdir = Path.mkdir
        def mkdir(path, *args, **kwargs):
            if path.is_relative_to(small):
                self.assertTrue(any(p.startswith('Install the displayed') for p in self.prompts))
            return original_mkdir(path, *args, **kwargs)
        with patch.object(installer.shutil, 'disk_usage', side_effect=lambda p: SimpleNamespace(free=100 if Path(p) == small else 100000)), \
                patch.object(Path, 'mkdir', mkdir):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        data = load_service_configuration(self.config / 'storage-services.json', 'ingestor')
        base = small / 'lab-sync-data'
        for key, suffix in (('storage_root', 'records'), ('global_artifact_root', 'artifacts'),
                            ('recovery_journal_root', 'journals'), ('framework_journal', 'framework.jsonl')):
            self.assertEqual(data[key], base / suffix)
        self.assertEqual(list(large.iterdir()), [])
        self.assertIn('free bytes: 100', output)
        self.assertIn('No largest-disk selection', output)
        self.assertIn('Framework configuration directory', output)
        self.assertIn('future experiments', output)

    def test_no_dedicated_storage_offers_explicit_configuration_filesystem_fallback(self):
        self.answers['Local roles'] = 'ingestor-storage'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        data = load_service_configuration(self.config / 'storage-services.json', 'ingestor')
        self.assertEqual(data['storage_root'], self.config / 'data' / 'records')
        self.assertIn('not a dedicated data disk', output)
        self.assertTrue(any(p.startswith('Use discovered primary scientific-data location') for p in self.prompts))

    def test_unavailable_volume_metadata_keeps_the_explicit_fallback_available(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.storage_discovery = True
        for failure in (OSError('metadata unavailable'), UnicodeError('metadata encoding unavailable')):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / 'configuration'
                with patch.object(installer, '_local_storage_destinations', side_effect=failure):
                    code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                self.assertIn('Local volume discovery unavailable', output)
                self.assertIn('not a dedicated data disk', output)

    def test_missing_manual_storage_does_not_inherit_parent_capacity_verification(self):
        base = self.root / 'not mounted or created' / 'science'
        self.answers.update({'Local roles': 'ingestor-storage', 'Use discovered primary scientific-data location': 'no',
                             'Storage data directory': str(base)})
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertIn('Destination capacity unverified', output)
        self.assertIn('does not verify a missing destination', output)
        self.assertEqual(load_service_configuration(self.config / 'storage-services.json', 'ingestor')['storage_root'], base / 'records')

    def test_unreliable_storage_capacity_is_reported_without_fabricated_readiness(self):
        self.answers['Local roles'] = 'ingestor-storage'
        for failure in (OSError('capacity unavailable'), SimpleNamespace(free=-1)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / 'configuration'
                settings = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(installer.shutil, 'disk_usage', **settings):
                    code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                self.assertIn('capacity unverified', output)
                self.assertIn('future experiments', output)

    def test_unsuitable_and_inaccessible_storage_stop_without_modifying_data(self):
        target = self.root / 'existing scientific file'
        target.write_bytes(b'original')
        self.answers.update({'Local roles': 'ingestor-storage', 'Use discovered primary scientific-data location': 'no',
                             'Storage data directory': str(target)})
        self.assertEqual(self.run_setup()[0], 1)
        self.assertEqual(target.read_bytes(), b'original')
        self.assertFalse(self.environment.exists())
        self.answers['Storage data directory'] = str(self.root / 'inaccessible')
        with patch.object(installer.os, 'access', return_value=False):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn('not writable', errors)
        self.assertFalse(self.environment.exists())

    def test_disappearing_storage_volume_is_not_recreated_on_the_parent_filesystem(self):
        volume = self.root / 'disappearing volume'
        volume.mkdir()
        self.storage_volumes = [(volume, 'mounted local filesystem')]
        self.answers.update({'Local roles': 'ingestor-storage', 'Choose primary scientific-data location': '1'})
        original = installer._require_storage_destination
        calls = []
        def revalidate(facts):
            calls.append(facts)
            if len(calls) == 3:
                volume.rmdir()
            return original(facts)
        with patch.object(installer, '_require_storage_destination', side_effect=revalidate):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertFalse(volume.exists())
        self.assertFalse((self.config / 'storage-services.json').exists())
        self.assertIn('no package rollback is claimed', errors)
        self.assertIn('select it again explicitly', errors)

    def test_volume_disappearing_during_selection_blocks_before_package_changes(self):
        volume = self.root / 'listed volume'
        volume.mkdir()
        self.storage_volumes = [(volume, 'mounted local filesystem')]
        self.answers.update({'Local roles': 'ingestor-storage', 'Choose primary scientific-data location': '1'})
        original = installer._choose_discovered
        def choose(label, candidates):
            result = original(label, candidates)
            if label == 'primary scientific-data location':
                volume.rmdir()
            return result
        with patch.object(installer, '_choose_discovered', side_effect=choose):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertFalse(volume.exists())
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())
        self.assertIn('select it again explicitly', errors)

    def test_declined_installation_makes_no_writes_to_the_selected_volume(self):
        volume = self.root / 'read only discovery'
        volume.mkdir()
        self.storage_volumes = [(volume, 'mounted local filesystem')]
        self.answers.update({'Local roles': 'ingestor-storage', 'Choose primary scientific-data location': '1',
                             'Install the displayed': 'no'})
        original_open, original_mkdir = Path.open, Path.mkdir
        def open_path(path, mode='r', *args, **kwargs):
            if path.is_relative_to(volume):
                self.assertFalse(any(flag in mode for flag in 'wax+'))
            return original_open(path, mode, *args, **kwargs)
        def mkdir(path, *args, **kwargs):
            self.assertFalse(path.is_relative_to(volume))
            return original_mkdir(path, *args, **kwargs)
        with patch.object(Path, 'open', open_path), patch.object(Path, 'mkdir', mkdir):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertEqual(list(volume.iterdir()), [])
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())

    def test_storage_selection_cancellation_leaves_no_destination_or_probe_files(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.interrupt_at = 'Use discovered primary scientific-data location'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.environment.exists())
        self.assertEqual(list(self.root.rglob('.capacity-*')), [])

    def test_reinstall_preserves_all_configured_storage_paths_and_scientific_bytes(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'storage-services.json'
        data = json.loads(path.read_text())
        for key in ('storage_root', 'global_artifact_root', 'recovery_journal_root'):
            directory = self.root / ('custom ' + key)
            directory.mkdir()
            (directory / 'original.bin').write_bytes(b'preserved')
            data[key] = str(directory)
        journal = self.root / 'custom framework.jsonl'
        journal.write_bytes(b'preserved journal')
        data['framework_journal'] = str(journal)
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(journal.read_bytes(), b'preserved journal')
        for key in ('storage_root', 'global_artifact_root', 'recovery_journal_root'):
            self.assertEqual((Path(data[key]) / 'original.bin').read_bytes(), b'preserved')
        self.assertFalse(any('primary scientific-data location' in p for p in self.prompts))

    def test_ubuntu_mount_discovery_decodes_spaces_and_excludes_network_filesystems(self):
        volume, remote = self.root / 'local volume', self.root / 'network volume'
        volume.mkdir()
        remote.mkdir()
        mount = str(volume).replace(' ', '\\040')
        network = str(remote).replace(' ', '\\040')
        contents = f'1 0 8:1 / {mount} rw - ext4 /dev/test rw\n2 0 0:2 / {network} rw - nfs host:/data rw\n'
        self.storage_discovery = True
        self.platform = 'linux'
        self.answers.update({'Local roles': 'ingestor-storage', 'Choose primary scientific-data location': '1'})
        original = Path.read_text
        def read(path, *args, **kwargs):
            return contents if path == Path('/proc/self/mountinfo') else original(path, *args, **kwargs)
        original_mount = Path.is_mount
        with patch.object(Path, 'read_text', read), patch.object(
                Path, 'is_mount', lambda path: path == volume or original_mount(path)):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(load_service_configuration(self.config / 'storage-services.json', 'ingestor')['storage_root'], volume / 'lab-sync-data' / 'records')
        self.assertNotIn(str(remote), output)

    def test_windows_native_discovery_excludes_network_and_optical_drives(self):
        import ctypes
        visited = []
        def drive_type(drive):
            visited.append(drive)
            return {'D': 3, 'E': 4, 'F': 5}[drive[0]]
        kernel = SimpleNamespace(GetLogicalDrives=lambda: sum(1 << i for i in (3, 4, 5)), GetDriveTypeW=drive_type)
        self.storage_discovery = True
        self.platform = 'win32'
        self.answers.update({'Local roles': 'ingestor-storage', 'Choose primary scientific-data location': '',
                             'Storage data directory': str(self.root / 'manual science')})
        original = installer._inspect_storage_destination
        def inspect(path):
            return original(self.root) if str(path).replace('\\', '/') == 'D:/' else original(path)
        with patch.object(ctypes, 'windll', SimpleNamespace(kernel32=kernel), create=True), \
                patch.object(installer, '_inspect_storage_destination', side_effect=inspect):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(visited), 3)
        self.assertIn('local Windows drive D:', output)
        self.assertNotIn('local Windows drive E:', output)
        self.assertNotIn('local Windows drive F:', output)

    def test_zero_pair_preservation_window_prompts_for_each_new_independent_role(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.answers['Preservation window'] = '0'
        self.assertEqual(self.run_setup()[0], 0)
        storage = self.config / 'storage-services.json'
        before = storage.read_bytes()
        original = load_service_configuration(storage, 'ingestor')
        scientific = Path(original['storage_root']) / 'original.bin'
        scientific.write_bytes(b'preserved scientific data')
        self.hardware()
        for index, role in enumerate(('controller', 'synchronization-manager', 'acquisition-node')):
            with self.subTest(role=role):
                self.answers['Local roles'] = 'ingestor-storage ' + role
                label = 'Preservation window, seconds for new ' + role
                self.answers[label] = str(3.5 + index)
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                path = self.config / installer.FILES[role]
                data = load_service_configuration(path, role)
                self.assertEqual(data['preservation_window_s'], 3.5 + index)
                self.assertEqual(data['result_window_s'], original['result_window_s'])
                self.assertEqual(data['controller_claim_key'], original['controller_claim_key'])
                self.assertTrue(any(p.startswith(label) for p in self.prompts))
                self.assertIn('requires a positive', output)
                self.assertEqual(storage.read_bytes(), before)
                self.assertEqual(scientific.read_bytes(), b'preserved scientific data')
                path.unlink()

    def test_positive_pair_timing_is_reused_without_prompting_or_changing_existing_config(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.assertEqual(self.run_setup()[0], 0)
        storage = self.config / 'storage-services.json'
        before = storage.read_bytes()
        original = load_service_configuration(storage, 'ingestor')
        self.answers['Local roles'] = 'ingestor-storage controller synchronization-manager'
        self.answers['Preservation window'] = 'must not be requested'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        for role in ('controller', 'synchronization-manager'):
            data = load_service_configuration(self.config / installer.FILES[role], role)
            self.assertEqual(data['preservation_window_s'], original['preservation_window_s'])
            self.assertEqual(data['result_window_s'], original['result_window_s'])
        self.assertFalse(any(p.startswith(('Preservation window', 'Request/check window')) for p in self.prompts))
        self.assertEqual(storage.read_bytes(), before)

    def test_invalid_replacement_window_blocks_before_update_and_preserves_zero_pair(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.answers['Preservation window'] = '0'
        self.assertEqual(self.run_setup()[0], 0)
        storage = self.config / 'storage-services.json'
        before = storage.read_bytes()
        self.answers['Local roles'] = 'ingestor-storage controller'
        for value in ('0', '-1', 'nan', 'inf', 'not a number'):
            with self.subTest(value=value):
                self.answers['Preservation window, seconds for new controller'] = value
                self.calls.clear()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertEqual(storage.read_bytes(), before)
                self.assertFalse((self.config / 'controller.json').exists())
                self.assertFalse(any('pip' in c for c in self.calls))

    def test_cancellation_at_inapplicable_window_prompt_preserves_existing_config(self):
        self.answers['Local roles'] = 'ingestor-storage'
        self.answers['Preservation window'] = '0'
        self.assertEqual(self.run_setup()[0], 0)
        storage = self.config / 'storage-services.json'
        before = storage.read_bytes()
        self.answers['Local roles'] = 'ingestor-storage controller'
        self.interrupt_at = 'Preservation window, seconds for new controller'
        self.calls.clear()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertEqual(storage.read_bytes(), before)
        self.assertFalse((self.config / 'controller.json').exists())
        self.assertFalse(any('pip' in c for c in self.calls))

    def test_local_authentication_and_equivalent_endpoints_are_not_server_conflicts(self):
        self.answers['Local roles'] = 'controller ingestor'
        self.assertEqual(self.run_setup()[0], 0)
        paths = [self.config / 'controller.json', self.config / 'storage-services.json']
        variants = [
            {'servers': ['nats://control-user:control-secret@BROKER:4222']},
            {'servers': ['NATS://broker/'], 'nats_username': 'storage-user',
             'nats_password': 'storage-secret @%40\u03bb '},
        ]
        for path, fields in zip(paths, variants):
            data = json.loads(path.read_text())
            path.write_text(json.dumps({**data, **fields}), encoding='utf-8')
        before = {path: path.read_bytes() for path in paths}
        self.answers['Local roles'] = 'controller ingestor synchronization-manager'
        self.answers['Use explicit NATS username/password for synchronization-manager'] = 'yes'
        self.answers['synchronization-manager nats_username'] = 'new-timing-user'
        self.answers['synchronization-manager nats_password'] = 'new-timing-secret @%40\u03bb '
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        timing = load_service_configuration(self.config / 'synchronization-manager.json', 'synchronization-manager')
        self.assertEqual(timing['servers'], ('nats://broker:4222',))
        self.assertEqual(timing['nats_username'], 'new-timing-user')
        self.assertEqual(timing['nats_password'], 'new-timing-secret @%40\u03bb ')
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
        visible = output + errors + str(self.prompts)
        for secret in ('control-user', 'control-secret', 'storage-user', 'storage-secret', 'new-timing-secret'):
            self.assertNotIn(secret, visible)
        self.assertTrue(any(c['servers'] == variants[0]['servers'] for c in self.connections))
        self.assertTrue(any(c.get('nats_password') == variants[1]['nats_password'] for c in self.connections))

    def test_distinct_local_server_lists_require_selection_and_preserve_files(self):
        self.answers['Local roles'] = 'controller ingestor'
        self.assertEqual(self.run_setup()[0], 0)
        control = self.config / 'controller.json'
        storage = self.config / 'storage-services.json'
        initial = json.loads(storage.read_text())
        for servers in (['nats://other:4222'], ['nats://second:4222', 'nats://broker:4222'],
                        ['nats://broker:4222', 'nats://second:4222']):
            with self.subTest(servers=servers):
                storage.write_text(json.dumps({**initial, 'servers': servers}), encoding='utf-8')
                before = {p: p.read_bytes() for p in (control, storage)}
                self.answers['Local roles'] = 'controller ingestor synchronization-manager'
                self.answers['Choose local NATS'] = '2'
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                path = self.config / 'synchronization-manager.json'
                self.assertEqual(load_service_configuration(path, 'synchronization-manager')['servers'], tuple(servers))
                for p, contents in before.items():
                    self.assertEqual(p.read_bytes(), contents)
                path.unlink()

    def test_declining_or_invalid_local_endpoint_selection_does_not_modify_files(self):
        self.answers['Local roles'] = 'controller ingestor'
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'storage-services.json'
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, 'servers': ['nats://other:4222']}), encoding='utf-8')
        before = {p: p.read_bytes() for p in self.config.glob('*.json')}
        self.answers['Local roles'] = 'controller ingestor synchronization-manager'
        for choice in ('', '3', '1,2'):
            with self.subTest(choice=choice):
                self.answers['Choose local NATS'] = choice
                self.calls.clear()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertEqual({p: p.read_bytes() for p in self.config.glob('*.json')}, before)
                self.assertFalse(any('pip' in c for c in self.calls))

    def test_paired_role_is_visible_and_included_in_default_selection(self):
        self.answers['Local roles'] = ''
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        prompt = next(p for p in self.prompts if p.startswith('Local roles'))
        self.assertIn('ingestor-storage', prompt)
        self.assertNotIn(' storage-manager', prompt)
        self.assertIn('default: ingestor-storage', prompt)
        self.assertIn('both logical services', output)
        load_service_configuration(self.config / 'storage-services.json', 'ingestor')
        self.assertEqual(output.count('LAUNCH:'), 1)
        launch = next(line for line in output.splitlines() if line.startswith('LAUNCH:'))
        self.assertIn('service_launcher ingestor ', launch.replace("'", ''))
        self.assertIn('storage-services.json', launch)

    def test_local_url_list_order_requires_a_choice_without_reordering_existing_files(self):
        self.answers['Local roles'] = 'controller ingestor'
        self.assertEqual(self.run_setup()[0], 0)
        paths = [self.config / 'controller.json', self.config / 'storage-services.json']
        lists = [['nats://first:4222', 'nats://second:4222'],
                 ['nats://second:4222', 'nats://first:4222']]
        for path, servers in zip(paths, lists):
            path.write_text(json.dumps({**json.loads(path.read_text()), 'servers': servers}), encoding='utf-8')
        before = {path: path.read_bytes() for path in paths}
        self.answers['Local roles'] = 'controller ingestor synchronization-manager'
        self.answers['Choose local NATS'] = '2'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        timing = load_service_configuration(self.config / 'synchronization-manager.json', 'synchronization-manager')
        self.assertEqual(timing['servers'], tuple(lists[1]))
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_invalid_existing_authentication_blocks_before_any_update_without_disclosure(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        original = json.loads(path.read_text())
        for fields in ({'nats_username': 'private-user'},
                       {'nats_username': 'private-user', 'nats_password': ''},
                       {'nats_username': 'private-user', 'nats_password': None},
                       {'nats_username': 'private-user', 'nats_password': 7},
                       {'nats_username': 'private-user', 'nats_password': 'private-secret',
                        'servers': ['nats://embedded:another-secret@broker:4222']}):
            with self.subTest(fields=list(fields)):
                path.write_text(json.dumps({**original, **fields}), encoding='utf-8')
                before = path.read_bytes()
                self.calls.clear()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(any('pip' in c for c in self.calls))
                for secret in ('private-user', 'private-secret', 'another-secret'):
                    self.assertNotIn(secret, output + errors + str(self.prompts))

    def test_embedded_credentials_remain_service_specific_on_rerun(self):
        self.answers['Local roles'] = 'controller synchronization-manager ingestor'
        self.assertEqual(self.run_setup()[0], 0)
        before = {}
        for index, path in enumerate(sorted(self.config.glob('*.json'))):
            data = json.loads(path.read_text())
            data['servers'] = [f'nats://service-{index}:secret-{index}@broker:4222']
            path.write_text(json.dumps(data), encoding='utf-8')
            before[path] = path.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        for index in range(3):
            self.assertNotIn(f'secret-{index}', output + errors + str(self.prompts))

    def shared_source(self, *, servers=None):
        path = self.root / "existing laboratory.json"
        path.write_text(json.dumps({"servers": servers or ["nats://lab-broker:4222"],
            "ingestor_id": "lab-intake", "storage_id": "lab-storage", "service_id": "lab-control",
            "synchronization_id": "lab-clock", "known_nodes": ["lab-node"],
            "controller_claim_account": "actual-lab", "controller_claim_bucket": "lab-authority",
            "controller_claim_key": "shared-control", "preservation_window_s": 4, "result_window_s": 2,
            "nats_username": "not-to-import", "nats_password": "not-to-import-secret",
            "storage_root": "Z:/foreign/scientific", "node_config": "Z:/foreign/hardware.json"}), encoding="utf-8")
        self.answers["Existing laboratory service configuration"] = str(path)
        return path

    def test_join_imports_shared_settings_without_foreign_credentials_or_paths(self):
        source = self.shared_source()
        before = source.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        data = load_service_configuration(self.config / "controller.json", "controller")
        self.assertEqual(data["servers"], ("nats://lab-broker:4222",))
        self.assertEqual(data["controller_claim_key"], "shared-control")
        self.assertEqual(data["service_id"], "lab-control")
        self.assertEqual(data["known_nodes"], ("lab-node",))
        self.assertEqual(data["result_window_s"], 2)
        for value in ("not-to-import", "not-to-import-secret", "Z:/foreign"):
            self.assertNotIn(value, json.dumps(data) + output + errors + '\n'.join(self.prompts))
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(any(p.startswith("Controller authority key") for p in self.prompts))

    def test_multiple_candidates_require_selection_and_preserve_selected_order(self):
        self.shared_source(servers=["nats://first:4222", "nats://second:4222"])
        self.answers["Choose NATS server"] = "2,1"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(load_service_configuration(self.config / "controller.json", "controller")["servers"],
                         ("nats://second:4222", "nats://first:4222"))
        self.assertIn("does not establish laboratory membership", output)
        self.assertTrue(all(c['servers'] == ['nats://second:4222', 'nats://first:4222'] for c in self.connections))

    def test_new_system_uses_observed_account_and_confirmed_authority_proposals(self):
        self.answers["Laboratory setup"] = "new"
        self.discovered_account = "observed-account"
        for key in ("Controller authority account", "Controller authority bucket", "Controller authority key"):
            self.answers[key] = ""
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        settings = load_service_configuration(self.config / "controller.json", "controller")
        self.assertEqual(settings["controller_claim_account"], "observed-account")
        self.assertEqual(settings["controller_claim_bucket"], "controller_authority")
        self.assertEqual(settings["controller_claim_key"], "controller")
        self.assertTrue(any(c.get("discover_account") for c in self.connections))
        self.assertIn("does not create a bucket or claim", output)

    def test_denied_account_discovery_keeps_manual_account_and_reports_unverified(self):
        self.answers["Laboratory setup"] = "new"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(load_service_configuration(self.config / "controller.json", "controller")["controller_claim_account"],
                         "lab-account")
        self.assertIn("Account discovery PENDING / NOT VERIFIED", output)

    def test_import_conflict_or_damage_blocks_without_changing_existing_installation(self):
        self.assertEqual(self.run_setup()[0], 0)
        target = self.config / "controller.json"
        before = target.read_bytes()
        source = self.shared_source()
        self.answers["Local roles"] = "controller synchronization-manager"
        self.calls.clear()
        self.assertEqual(self.run_setup()[0], 1)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(any("pip" in c for c in self.calls))
        source.write_text('[]', encoding="utf-8")
        self.assertEqual(self.run_setup()[0], 1)
        self.assertEqual(target.read_bytes(), before)

    def test_imported_url_credentials_are_excluded_and_source_is_unchanged(self):
        from uuid import uuid4
        secret = uuid4().hex
        source = self.shared_source(servers=['nats://source-user:' + secret + '@lab-broker:4222'])
        data = json.loads(source.read_text())
        data.pop('nats_username')
        data.pop('nats_password')
        source.write_text(json.dumps(data), encoding='utf-8')
        before = source.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        target = (self.config / 'controller.json').read_text()
        self.assertNotIn(secret, output + errors + target + str(self.prompts))
        self.assertNotIn('source-user', output + errors + target)
        self.assertEqual(json.loads(target)['servers'], ['nats://lab-broker:4222'])
        self.assertEqual(source.read_bytes(), before)

    def test_malformed_imports_fail_before_presenting_values_or_modifying_environment(self):
        from uuid import uuid4
        secret = uuid4().hex
        source = self.shared_source()
        original = json.loads(source.read_text())
        for mutation in ({'controller_id': {'nats_password': secret}, 'service_id': {'nats_password': secret}},
                         {'known_nodes': [None]}, {'external_dependents': [{'private': secret}]},
                         {'result_window_s': float('nan')}, {'controller_claim_key': ''}):
            with self.subTest(fields=list(mutation)):
                source.write_text(json.dumps({**original, **mutation}), encoding='utf-8')
                self.calls.clear()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 1)
                self.assertNotIn(secret, output + errors + str(self.prompts))
                self.assertFalse(any('pip' in c or 'venv' in c for c in self.calls))
        source.write_text('{"servers": [], "servers": []}', encoding='utf-8')
        self.assertEqual(self.run_setup()[0], 1)

    def test_offline_new_system_accepts_supplied_account_without_claiming_readiness(self):
        self.answers['Laboratory setup'] = 'new'
        self.failure = 'nats'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn('Account discovery PENDING / NOT VERIFIED', output)
        self.assertIn('NATS connectivity PENDING / NOT VERIFIED', output)
        self.assertNotIn('NATS connection and cleanup confirmed', output)
        data = load_service_configuration(self.config / 'controller.json', 'controller')
        self.assertEqual(data['controller_claim_account'], 'lab-account')

    def test_declined_candidate_uses_manual_address_without_probing_candidate(self):
        self.shared_source()
        self.answers['Use discovered'] = 'no'
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads((self.config / 'controller.json').read_text())['servers'], ['nats://broker:4222'])
        self.assertTrue(all(c['servers'] == ['nats://broker:4222'] for c in self.connections))

    def test_ambiguous_candidate_selection_cannot_silently_choose_or_probe(self):
        self.shared_source(servers=['nats://first:4222', 'nats://second:4222'])
        self.answers['Choose NATS server'] = '2,2'
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertFalse(self.connections)
        self.assertFalse(self.environment.exists())

    def test_rerun_reuses_local_settings_without_reasking_internal_details(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        before = path.read_bytes()
        self.assertEqual(self.run_setup()[0], 0)
        for prefix in ('Controller authority', 'Deployment Ingestor', 'Deployment StorageManager',
                       'Preservation window', 'Request/check window', 'Use explicit NATS',
                       'Known AcquisitionNode', 'Existing laboratory service configuration'):
            self.assertFalse(any(p.startswith(prefix) for p in self.prompts), prefix)
        self.assertTrue(any(p.startswith('All services') for p in self.prompts))
        self.assertEqual(path.read_bytes(), before)

    def test_numeric_role_dependency_choices_and_local_hardware_ssh_candidates(self):
        self.answers['Local roles'] = '4 2 3 1'
        hardware = self.hardware()
        self.config.mkdir()
        local_hardware = self.config / 'acquisition-node.json'
        local_hardware.write_bytes(hardware.read_bytes())
        key = self.root / 'operator-home' / '.ssh' / 'id_ed25519'
        key.parent.mkdir(parents=True)
        key.write_text('disposable key-path fixture', encoding='utf-8')
        hosts = key.parent / 'known_hosts'
        hosts.write_text('disposable existing host-file fixture', encoding='utf-8')
        self.answers.update({'Retrieval node IDs': 'node', 'node SSH host': 'node.example',
                             'node SSH username': 'operator', 'node SSH port': '22',
                             'Actual external dependents': '1,2,3'})
        before = local_hardware.read_bytes(), key.read_bytes(), hosts.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        node = load_service_configuration(self.config / 'acquisition-node-service.json', 'acquisition-node')
        self.assertEqual(node['node_config'], local_hardware)
        storage = load_service_configuration(self.config / 'storage-services.json', 'ingestor')
        self.assertEqual(storage['retrieval_endpoints']['node'].key_filename, str(key))
        self.assertEqual(storage['retrieval_endpoints']['node'].known_hosts_path, str(hosts))
        self.assertEqual(len(storage['external_dependents']), 3)
        self.assertEqual((local_hardware.read_bytes(), key.read_bytes(), hosts.read_bytes()), before)
        self.assertFalse(any(p.startswith('Existing node hardware JSON path') for p in self.prompts))

    def test_cancel_during_discovery_does_not_publish_or_prepare_environment(self):
        source = self.shared_source()
        before = source.read_bytes()
        self.interrupt_at = 'Use discovered NATS server'
        code, _, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn('No installation changes', errors)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.environment.exists())
        self.assertEqual(source.read_bytes(), before)

    def test_import_cannot_hide_a_conflicting_websocket_route(self):
        self.assertEqual(self.run_setup()[0], 0)
        target = self.config / 'controller.json'
        data = json.loads(target.read_text())
        data['servers'] = ['wss://broker:4222/first-route']
        target.write_text(json.dumps(data), encoding='utf-8')
        before = target.read_bytes()
        source = self.shared_source()
        source.write_text(json.dumps({**data, 'servers': ['wss://broker:4222/second-route']}), encoding='utf-8')
        self.answers['Local roles'] = 'controller synchronization-manager'
        self.calls.clear()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn('different NATS addresses or ordering', errors)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(any('pip' in c for c in self.calls))

    def test_new_system_choice_cannot_replace_existing_local_scope(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / 'controller.json'
        before = path.read_bytes()
        self.answers['Laboratory setup'] = 'new'
        self.calls.clear()
        self.assertEqual(self.run_setup()[0], 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(any('pip' in c for c in self.calls))

    def test_join_reuses_declared_service_and_node_names_from_a_storage_configuration(self):
        source = self.shared_source()
        data = json.loads(source.read_text())
        for field in ('known_nodes', 'synchronization_id', 'service_id', 'node_config'):
            data.pop(field)
        data['external_dependents'] = [
            {'component_type': 'controller', 'component_id': 'declared-control'},
            {'component_type': 'synchronization_manager', 'component_id': 'declared-clock'},
            {'component_type': 'acquisition_node', 'component_id': 'declared-node'}]
        source.write_text(json.dumps(data), encoding='utf-8')
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        result = load_service_configuration(self.config / 'controller.json', 'controller')
        self.assertEqual(result['service_id'], 'declared-control')
        self.assertEqual(result['synchronization_id'], 'declared-clock')
        self.assertEqual(result['known_nodes'], ('declared-node',))
        self.assertFalse(any(p.startswith('Controller ID') or p.startswith('Deployment SynchronizationManager ID')
                             for p in self.prompts))

    def test_hidden_explicit_credentials_reach_verification_and_config_but_not_output(self):
        from uuid import uuid4
        auth = {"nats_username": uuid4().hex, "nats_password": uuid4().hex + " @:/?#%40\r\n\t\u03bb "}
        self.answers["Use explicit NATS"] = "yes"
        for key, value in auth.items():
            self.answers["controller " + key] = value
        client = SimpleNamespace(is_connected=True, connect=AsyncMock(), drain=AsyncMock(), close=AsyncMock())
        self.connection_client = client
        self.execute_connection_check = True
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        data = load_service_configuration(self.config / "controller.json", "controller")
        for key, value in auth.items():
            self.assertEqual(data[key], value)
            self.assertEqual(self.connections[0][key], value)
            self.assertNotIn(value, output + errors + '\n'.join(self.prompts) + repr(self.calls))
        self.assertEqual(client.connect.call_args.kwargs["user"], auth["nats_username"])
        self.assertEqual(client.connect.call_args.kwargs["password"], auth["nats_password"])
        before = (self.config / "controller.json").read_bytes()
        self.calls.clear()
        self.answers["Use explicit NATS"] = "no"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual((self.config / "controller.json").read_bytes(), before)

    def test_hidden_input_refuses_echo_fallback_without_exposing_input(self):
        import warnings
        def insecure(prompt):
            warnings.warn("No terminal", installer.getpass.GetPassWarning)
            self.fail("Must refuse before echo fallback")
        with patch.object(installer.getpass, "getpass", side_effect=insecure):
            with self.assertRaisesRegex(ValueError, "Non-echoing"):
                installer._hidden_input("NATS credential")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "checkout with spaces"
        self.checkout.mkdir()
        self.checkout.joinpath("pyproject.toml").write_text(
            '[project]\nname="lab-sync-acquisition"\nrequires-python=">=3.12,<3.13"\n', encoding="utf-8")
        self.config = self.root / "private configuration"
        self.environment = self.checkout / ".venv"
        self.calls = []
        self.prompts = []
        self.connections = []
        self.answers = {
            "Laboratory setup": "existing",
            "Use discovered": "yes",
            "Local roles": "controller",
            "NATS URLs": "nats://broker:4222",
            "Deployment Ingestor ID": "intake",
            "Deployment StorageManager ID": "storage",
            "Controller authority account": "lab-account",
            "Controller authority bucket": "lab-authority",
            "Controller authority key": "controller",
            "Preservation window": "3",
            "Request/check window": "1",
            "Deployment SynchronizationManager ID": "clock",
            "Controller ID": "control",
            "Known AcquisitionNode IDs": "node",
            "Existing node hardware JSON path": "",
            "Actual external dependents": "controller/control,acquisition_node/node,synchronization_manager/clock",
            "All services": "yes",
            "Install the displayed": "yes",
            "NATS connectivity timeout": "1",
            "Retrieval node IDs": "none",
        }
        self.discovered_account = None
        self.platform = sys.platform
        self.failure = None
        self.version = [3, 12]
        self.preflight_dependencies_missing = False
        self.real_validation = False
        self.execute_connection_check = False
        self.connection_client = None
        self.interrupt_at = None
        self.storage_volumes = []
        self.storage_discovery = False
        self.gui_version = None

    def hardware(self):
        path = self.root / "node hardware.json"
        path.write_text(json.dumps({"node_id": "node", "role": "acquisition",
            "local_storage_root": "scientific", "error_evidence_location": "errors", "devices": [{
                "adapter": "seeed_imx219_opencv", "declaration": {"device_id": "camera",
                    "device_type": "camera", "enabled": True, "required": True,
                    "declared_capabilities": ["camera_frames"], "scientific_products": []},
                "configuration": {"camera_source": 0, "api_preference": 0, "frames_per_collect": 1}}]}),
            encoding="utf-8")
        self.answers["Existing node hardware JSON path"] = str(path)
        return path

    def environment_python(self):
        return self.environment / ("Scripts/python.exe" if self.platform == "win32" else "bin/python")

    def create_environment(self):
        python = self.environment_python()
        python.parent.mkdir(parents=True)
        python.write_text("test interpreter placeholder", encoding="utf-8")

    def run_setup(self):
        output, errors = io.StringIO(), io.StringIO()
        self.prompts.clear()

        def answer(prompt):
            self.prompts.append(prompt)
            if self.failure == "prompt-interrupt" or (self.interrupt_at and prompt.startswith(self.interrupt_at)):
                raise KeyboardInterrupt()
            return next((value for prefix, value in sorted(self.answers.items(), key=lambda item: -len(item[0]))
                         if prompt.startswith(prefix)), "")

        def run(arguments, *, timeout=60, input=None):
            args = [str(a) for a in arguments]
            self.calls.append(args)
            if args[0] == "git":
                if "--show-toplevel" in args:
                    return str(self.checkout)
                return "" if "status" in args else "a" * 40
            if "import nats" in args:
                self.assertEqual(self.prompts, [])
                if self.failure == "nats-import":
                    raise RuntimeError("Injected missing nats-py")
                if self.real_validation:
                    return installer_run([sys.executable, *args[1:]], timeout=timeout)
            elif "venv" in args:
                self.create_environment()
            elif installer.ENVIRONMENT_REPORT in args:
                return json.dumps({"version": self.version, "prefix": str(self.environment),
                                   "base_prefix": str(self.root / "base-python"), 'gui_version': self.gui_version})
            elif "pip" in args:
                self.assertEqual(Path(args[0]), self.environment_python())
                if "install" in args and self.failure == "pip":
                    raise RuntimeError("Injected pip failure")
                if "install" in args and self.failure == "interrupt":
                    raise KeyboardInterrupt()
                if 'install' in args and args[-1] == str(self.checkout / 'gui') and self.failure == 'gui-pip':
                    raise RuntimeError('Injected GUI package failure')
            elif installer.VALIDATE in args:
                if self.real_validation:
                    return installer_run([sys.executable, *args[1:]], timeout=timeout)
                if self.failure == "validation-dependencies":
                    return "DEPENDENCIES_UNAVAILABLE\n"
                if self.preflight_dependencies_missing and not any("pip" in c for c in self.calls):
                    return "DEPENDENCIES_UNAVAILABLE\n"
                # Run the unchanged production loader, not a fabricated validation result.
                load_service_configuration(args[-2], args[-1])
            elif installer.VALIDATE_GUI in args:
                if self.failure == 'gui-dependencies':
                    return 'DEPENDENCIES_UNAVAILABLE\n'
                settings = json.loads(input)
                gui_source = Path(__file__).resolve().parents[1] / 'gui' / 'src'
                if self.real_validation:
                    return installer_run([sys.executable, '-I', '-B', '-c', installer.VALIDATE_GUI,
                                          Path(__file__).resolve().parents[1] / 'src', gui_source], timeout=timeout, input=input)
                with patch.object(sys, 'path', [str(gui_source), *sys.path]):
                    from miceball_gui.backend import create_gui_app
                    from lab_sync_acquisition.communication import build_runtime_subject
                    for field, kind in (('controller_id', 'controller'), ('client_id', 'client')):
                        build_runtime_subject(None, 'command', kind, settings[field], 'stop')
                    create_gui_app(**settings)
            elif installer.GUI_SYNCHRONIZATION in args:
                gui_source = Path(__file__).resolve().parents[1] / 'gui' / 'src'
                with patch.object(sys, 'path', [str(gui_source), *sys.path]):
                    from miceball_gui.catalog_store import CatalogStore, INITIAL_SYNCHRONIZATION_CONFIGURATION
                    from lab_sync_acquisition import SynchronizationConfiguration
                    request = json.loads(input)
                    if 'path' in request:
                        result = CatalogStore(request['path'], initial_synchronization=request.get('configuration')).read()['synchronization_configuration']
                    elif 'configuration' in request:
                        result = SynchronizationConfiguration.from_dict(request['configuration']).to_dict()
                    else:
                        result = INITIAL_SYNCHRONIZATION_CONFIGURATION.to_dict()
                    return json.dumps(result)
            elif installer.NODE_PARAMETERS in args:
                source = Path(__file__).resolve().parents[1] / 'src'
                return installer_run([sys.executable, '-I', '-B', '-c', installer.NODE_PARAMETERS, source],
                    timeout=timeout, input=input)
            elif installer.CONNECT in args:
                self.connections.append(json.loads(input) if input is not None else json.loads(args[-2]))
                if self.execute_connection_check:
                    with patch("nats.aio.client.Client", return_value=self.connection_client), \
                            patch.object(sys, "stdin", io.StringIO(input)):
                        exec(installer.CONNECT, {"__name__": "installer_connection_check"})
                if self.failure == "nats":
                    raise subprocess.TimeoutExpired(args, timeout)
                if self.failure in {"authentication", "connection-cleanup"}:
                    raise RuntimeError("Injected connection failure; secret must not be echoed")
                if self.failure == "connection-interrupt":
                    raise KeyboardInterrupt()
                if json.loads(input).get("discover_account"):
                    return json.dumps({"account": self.discovered_account})
            else:
                raise AssertionError(f"Unexpected external operation: {args}")
            return ""

        installer_run = installer._run
        discovery = contextlib.nullcontext() if self.storage_discovery else patch.object(
            installer, '_local_storage_destinations', return_value=self.storage_volumes)
        with discovery, patch.object(installer, "_run", side_effect=run), patch("builtins.input", side_effect=answer), \
                patch.object(installer.getpass, "getpass", side_effect=answer), \
                patch.object(installer.Path, "home", return_value=self.root / 'operator-home'), \
                patch.object(installer.sys, "platform", self.platform), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = installer.main(["--checkout", str(self.checkout), "--config-dir", str(self.config)])
        return code, output.getvalue(), errors.getvalue()

    def test_missing_nats_py_blocks_before_configuration_prompts_or_changes(self):
        self.failure = "nats-import"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("nats-py", errors)
        self.assertEqual(self.prompts, [])
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
        self.assertNotIn("LAUNCH:", output)

    def test_available_nats_py_is_checked_in_the_selected_interpreter_first(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.calls.clear()
                    self.prompts.clear()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                check = next(c for c in self.calls if "import nats" in c)
                self.assertEqual(Path(check[0]), self.environment_python() if existing else Path(sys.executable))
                self.assertIn("NATS", output)

    def test_missing_nats_in_existing_environment_never_falls_back_or_changes_it(self):
        self.create_environment()
        before = self.environment_python().read_bytes()
        self.failure = "nats-import"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn(str(self.environment_python()), errors)
        self.assertEqual(self.environment_python().read_bytes(), before)
        checks = [c for c in self.calls if "import nats" in c]
        self.assertEqual(len(checks), 1)
        self.assertEqual(Path(checks[0][0]), self.environment_python())
        self.assertEqual(self.prompts, [])
        self.assertFalse(self.config.exists())

    def test_blank_identifiers_use_visible_editable_defaults(self):
        self.answers["Local roles"] = "controller synchronization-manager ingestor"
        for label in ("Deployment Ingestor ID", "Deployment StorageManager ID",
                      "Deployment SynchronizationManager ID", "Controller ID"):
            self.answers[label] = ""
        self.answers["Actual external dependents"] = "controller/controller-1,synchronization_manager/synchronization-manager-1"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        settings = load_service_configuration(self.config / "storage-services.json", "ingestor")
        self.assertEqual(settings["ingestor_id"], "ingestor-1")
        self.assertEqual(settings["storage_id"], "storage-manager-1")
        self.assertEqual(load_service_configuration(self.config / "controller.json", "controller")["service_id"], "controller-1")
        self.assertTrue(any("press Enter for default: ingestor-1" in p for p in self.prompts))

    def test_connection_failure_leaves_operational_prerequisite_pending_but_installs(self):
        for failure in ("nats", "authentication", "connection-cleanup"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "config"
                self.answers["Local roles"] = "ingestor storage-manager"
                self.calls.clear()
                self.prompts.clear()
                self.failure = failure
                code, output, errors = self.run_setup()
                self.assertEqual(code, 2, errors)
                self.assertIn("PENDING / NOT VERIFIED", output)
                self.assertIn("COMPLETED: isolated package installation", output)
                self.assertNotIn("NATS connection and cleanup confirmed", output)
                self.assertTrue(self.environment_python().is_file())
                settings = load_service_configuration(self.config / "storage-services.json", "ingestor")
                self.assertEqual(settings["ingestor_id"], "intake")
                self.assertTrue(any("install" in c for c in self.calls))
                self.assertEqual(output.count("LAUNCH:"), 1)
                self.assertIn("not operational readiness", output)

    def test_preinstall_cancellation_is_normal_and_leaves_no_installation_changes(self):
        for failure in ("prompt-interrupt", "connection-interrupt"):
            with self.subTest(failure=failure):
                self.calls.clear()
                self.prompts.clear()
                self.failure = failure
                code, output, errors = self.run_setup()
                self.assertEqual(code, 130)
                self.assertIn("CANCELLED", errors)
                self.assertIn("No installation changes", errors)
                self.assertNotIn("KeyboardInterrupt", errors)
                self.assertFalse(self.environment.exists())
                self.assertFalse(self.config.exists())
                self.assertNotIn("LAUNCH:", output)

    def test_cancellation_at_install_confirmation_preserves_existing_installation(self):
        self.assertEqual(self.run_setup()[0], 0)
        files = [p for p in self.root.rglob("*") if p.is_file()]
        before = {p: p.read_bytes() for p in files}
        self.interrupt_at = "Install the displayed"
        self.calls.clear()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn("NATS connection and cleanup confirmed", output)
        self.assertIn("No installation changes", errors)
        self.assertEqual({p: p.read_bytes() for p in files}, before)
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))

    def test_minimal_connection_check_uses_url_authentication_and_closes_before_confirmation(self):
        client = SimpleNamespace(is_connected=False)

        async def connect(**settings):
            self.assertFalse(self.config.exists())
            self.assertFalse(self.environment.exists())
            self.assertEqual(settings["servers"], ["nats://operator:secret@broker:4222"])
            self.assertFalse(settings["allow_reconnect"])
            self.assertTrue(callable(settings["error_cb"]))
            client.is_connected = True

        async def drain():
            client.is_connected = False

        client.connect = AsyncMock(side_effect=connect)
        client.drain = AsyncMock(side_effect=drain)
        client.close = AsyncMock()
        self.connection_client = client
        self.execute_connection_check = True
        self.answers["NATS URLs"] = "nats://operator:secret@broker:4222"
        self.answers["Install the displayed"] = "no"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        client.connect.assert_awaited_once()
        client.drain.assert_awaited_once()
        client.close.assert_awaited_once()
        self.assertIn("NATS connection and cleanup confirmed", output)
        self.assertNotIn("secret", output + errors + str(self.calls))
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())

    def test_minimal_connection_check_failure_always_closes_and_reports_pending(self):
        for stage in ("connect", "drain", "close"):
            with self.subTest(stage=stage):
                client = SimpleNamespace(is_connected=False)

                async def connect(**settings):
                    client.is_connected = True
                    if stage == "connect":
                        raise ConnectionError("Authentication unconfirmed")

                client.connect = AsyncMock(side_effect=connect)
                client.drain = AsyncMock(side_effect=RuntimeError("Drain unconfirmed") if stage == "drain" else None)
                client.close = AsyncMock(side_effect=RuntimeError("Close unconfirmed") if stage == "close" else None)
                self.connection_client = client
                self.execute_connection_check = True
                code, output, errors = self.run_setup()
                self.assertEqual(code, 2, errors)
                client.close.assert_awaited_once()
                self.assertIn("PENDING / NOT VERIFIED", output)
                self.assertNotIn("NATS connection and cleanup confirmed", output)
                load_service_configuration(self.config / "controller.json", "controller")
                self.assertTrue(self.environment_python().is_file())

    def test_fresh_setup_produces_valid_config_and_existing_launcher_command(self):
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        settings = load_service_configuration(self.config / "controller.json", "controller")
        self.assertEqual(settings["service_id"], "control")
        self.assertEqual(settings["ingestor_id"], "intake")
        self.assertEqual(settings["storage_id"], "storage")
        self.assertEqual(settings["known_nodes"], ("node",))
        self.assertEqual(settings["controller_claim_account"], "lab-account")
        self.assertEqual(settings["controller_claim_bucket"], "lab-authority")
        self.assertEqual(settings["controller_claim_key"], "controller")
        self.assertIn("COMPLETED: isolated package installation", output)
        self.assertIn("NATS connection and cleanup confirmed", output)
        self.assertNotIn("PENDING / NOT VERIFIED", output)
        self.assertIn("lab_sync_acquisition.service_launcher", output)
        self.assertIn("--deployment-config", output)
        self.assertEqual(sum("venv" in command for command in self.calls), 1)

    def test_storage_pair_always_has_authority_and_result_window(self):
        for dependents in ("none", "controller/control,acquisition_node/node"):
            with self.subTest(dependents=dependents), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "config"
                self.answers["Local roles"] = "ingestor storage-manager"
                self.answers["Actual external dependents"] = dependents
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                settings = load_service_configuration(self.config / "storage-services.json", "ingestor")
                self.assertEqual(settings["result_window_s"], 1)
                self.assertEqual(settings["controller_claim_account"], "lab-account")
                self.assertEqual(settings["controller_claim_bucket"], "lab-authority")
                self.assertEqual(settings["controller_claim_key"], "controller")
                self.assertEqual(output.count("LAUNCH:"), 1)

    def test_new_roles_reuse_existing_authority_without_changing_storage_settings(self):
        self.answers["Local roles"] = "storage-manager"
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "storage-services.json"
        data = json.loads(path.read_text())
        data.update(controller_claim_account="actual-account", controller_claim_bucket="actual-bucket",
                    controller_claim_key="actual-key", result_window_s=9)
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        self.answers["Local roles"] = "controller storage-manager"
        for label in ("Controller authority account", "Controller authority bucket", "Controller authority key"):
            self.answers[label] = ""
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        settings = load_service_configuration(self.config / "controller.json", "controller")
        for key in ("controller_claim_account", "controller_claim_bucket", "controller_claim_key", "result_window_s"):
            self.assertEqual(settings[key], data[key])
        self.assertEqual(path.read_bytes(), before)

    def test_existing_authority_disagreement_blocks_update_without_mutation(self):
        self.answers["Local roles"] = "controller synchronization-manager"
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "synchronization-manager.json"
        data = json.loads(path.read_text())
        data["controller_claim_key"] = "another-key"
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        self.calls.clear()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("disagree on controller_claim_key", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_existing_configuration_blocks_before_package_update(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "controller.json"
        valid = path.read_bytes()
        for mutation in (lambda d: d.pop("controller_claim_account"),
                         lambda d: d.update(result_window_s=0),
                         lambda d: d.update(unsupported=True)):
            with self.subTest(mutation=mutation):
                data = json.loads(valid)
                mutation(data)
                path.write_text(json.dumps(data), encoding="utf-8")
                before = path.read_bytes()
                self.calls.clear()
                code, _, _ = self.run_setup()
                self.assertEqual(code, 1)
                self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
                self.assertEqual(path.read_bytes(), before)

    def test_unavailable_preflight_dependencies_require_validation_after_install(self):
        self.preflight_dependencies_missing = True
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertIn("Pre-install configuration validation deferred", output)
        load_service_configuration(self.config / "controller.json", "controller")
        validations = [i for i, c in enumerate(self.calls) if installer.VALIDATE in c]
        install = next(i for i, c in enumerate(self.calls) if "install" in c)
        self.assertLess(validations[0], install)
        self.assertGreater(validations[-1], install)
        self.assertEqual(Path(self.calls[validations[0]][-3]), self.checkout / "src")

    def test_deferred_preflight_does_not_allow_invalid_configuration_publication(self):
        self.preflight_dependencies_missing = True
        self.answers["Request/check window"] = "0"
        code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_missing_loader_dependencies_after_install_block_publication(self):
        self.failure = "validation-dependencies"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("dependencies unavailable after installation", errors)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_child_process_validates_selected_checkout_before_and_after_install(self):
        source = Path(installer.__file__).resolve().parents[1] / "src"
        shutil.copytree(source, self.checkout / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.real_validation = True
        self.answers["Local roles"] = "storage-manager"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.calls.clear()
        self.answers["Local roles"] = "controller storage-manager"
        self.answers["Known AcquisitionNode IDs"] = "bad.*"
        self.answers["Use discovered declared node inventory"] = "no"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("Configuration validation failed", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertFalse((self.config / "controller.json").exists())

    def test_missing_selected_checkout_loader_cannot_use_an_older_installed_loader(self):
        self.real_validation = True
        code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("Configuration validation failed", errors)
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
        self.assertNotIn("LAUNCH:", output)

    def test_storage_update_preserves_custom_paths_endpoints_and_scientific_bytes(self):
        self.answers["Local roles"] = "storage-manager"
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "storage-services.json"
        data = json.loads(path.read_text())
        key = self.config / "ssh-key"
        hosts = self.config / "known-hosts"
        key.write_bytes(b"existing key")
        hosts.write_bytes(b"existing host verification")
        data.update(storage_root="custom/records", global_artifact_root="custom/artifacts",
                    recovery_journal_root="custom/journals", framework_journal="custom/framework.jsonl",
                    preservation_window_s=0, result_window_s=8,
                    retrieval_endpoints={"node": {"host": "actual-host", "username": "actual-user",
                        "key_filename": "ssh-key", "known_hosts_path": "known-hosts", "port": 2222}})
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        scientific = self.config / "custom/artifacts/frames.h5"
        scientific.parent.mkdir(parents=True)
        scientific.write_bytes(b"unchanged scientific product")
        before = {p: p.read_bytes() for p in (path, key, hosts, scientific)}
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        settings = load_service_configuration(path, "ingestor")
        self.assertEqual(settings["preservation_window_s"], 0)
        self.assertEqual(settings["result_window_s"], 8)
        self.assertEqual(output.count("LAUNCH:"), 1)

    def test_all_local_role_selections_use_existing_schemas_and_one_storage_pair(self):
        self.answers["Local roles"] = "controller acquisition-node synchronization-manager ingestor storage-manager"
        hardware = self.hardware()
        before = hardware.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        for role, filename in installer.FILES.items():
            load_service_configuration(self.config / filename, role)
        self.assertEqual(output.count("LAUNCH:"), 4)
        self.assertEqual(hardware.read_bytes(), before)
        self.assertTrue((self.root / "scientific").is_dir())
        self.assertTrue((self.config / "data/journals").is_dir())
        pip = next(c for c in self.calls if "install" in c)
        self.assertEqual(pip[-1], str(self.checkout) + "[artifact-retrieval]")
        self.assertEqual(len(self.connections), 4)

    def test_each_individual_role_including_storage_alias_can_be_prepared(self):
        for role in (*installer.FILES, "storage-manager", "ingestor-storage"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "config"
                self.answers["Local roles"] = role
                self.hardware()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                self.assertEqual(output.count("LAUNCH:"), 1)

    def test_compatible_environment_and_customized_configuration_are_preserved(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "controller.json"
        data = json.loads(path.read_text())
        data["result_window_s"] = 7
        path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        before = path.read_bytes()
        evidence = self.config / "recording.h5"
        evidence.write_bytes(b"existing scientific data")
        self.calls.clear()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertNotIn("venv", [arg for c in self.calls for arg in c])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(evidence.read_bytes(), b"existing scientific data")
        self.assertIn("preserve 1 existing files", output)

    def test_incompatible_environment_is_not_recreated_or_installed_into(self):
        self.create_environment()
        self.version = [3, 11]
        before = self.environment_python().read_bytes()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("isolated Python 3.12", errors)
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
        self.assertEqual(self.environment_python().read_bytes(), before)

    def test_update_requires_explicit_confirmation_of_retirement(self):
        self.create_environment()
        self.answers["All services"] = "no"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("Resolve service retirement", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertFalse(self.config.exists())

    def test_declined_plan_makes_no_changes(self):
        self.answers["Install the displayed"] = "no"
        code, output, _ = self.run_setup()
        self.assertEqual(code, 2)
        self.assertIn("no changes made", output)
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())

    def test_missing_hardware_is_deferred_without_fabricated_node_configuration(self):
        self.answers["Local roles"] = "acquisition-node"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn("AcquisitionNode incomplete", output)
        self.assertNotIn("LAUNCH:", output)
        self.assertFalse((self.config / "acquisition-node-service.json").exists())

    def test_existing_inconsistent_peer_identity_blocks_before_install(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "synchronization-manager.json"
        controller = json.loads((self.config / "controller.json").read_text())
        path.write_text(json.dumps({k: v for k, v in controller.items()
            if k not in {"synchronization_id", "known_nodes"}} | {"service_id": "different-clock"}), encoding="utf-8")
        before = path.read_bytes()
        self.calls.clear()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("disagree on synchronization_id", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertEqual(path.read_bytes(), before)

    def test_false_isolated_storage_declaration_cannot_omit_local_dependents(self):
        self.answers["Local roles"] = "controller ingestor"
        self.answers["Actual external dependents"] = "none"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("omits local owners", errors)
        self.assertFalse(self.environment.exists())

    def test_pip_failure_or_interruption_retains_existing_data_without_claiming_rollback(self):
        for failure, expected in (("pip", 1), ("interrupt", 130)):
            with self.subTest(failure=failure):
                self.failure = None
                self.assertEqual(self.run_setup()[0], 0)
                path = self.config / "controller.json"
                before = path.read_bytes()
                self.failure = failure
                code, output, errors = self.run_setup()
                self.assertEqual(code, expected)
                self.assertEqual(path.read_bytes(), before)
                self.assertIn("partially changed", errors)
                self.assertNotIn("LAUNCH:", output)

    def test_invalid_generated_config_is_never_published(self):
        for label, value in (("NATS URLs", "not-a-url"), ("Request/check window", "0"),
                             ("Request/check window", "nan"), ("Preservation window", "-1")):
            with self.subTest(label=label, value=value):
                original = self.answers[label]
                self.answers[label] = value
                self.calls.clear()
                code, output, _ = self.run_setup()
                self.assertEqual(code, 1)
                self.assertNotIn("LAUNCH:", output)
                self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
                self.assertEqual(list(self.config.glob("*.json")), [])
                self.answers[label] = original

    def test_directory_failure_blocks_without_configuration_publication(self):
        self.config.write_text("not a directory", encoding="utf-8")
        before = self.config.read_bytes()
        code, _, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(self.config.read_bytes(), before)

    def test_failed_configuration_write_removes_partial_file(self):
        with patch.object(installer.os, "fsync", side_effect=OSError("Injected publication failure")):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("publication failure", errors)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_unavailable_nats_on_rerun_preserves_configuration_and_data(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "controller.json"
        scientific = self.config / "frames.h5"
        scientific.write_bytes(b"existing scientific data")
        before = {p: p.read_bytes() for p in (path, scientific)}
        self.calls.clear()
        self.failure = "nats"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn("PENDING / NOT VERIFIED", output)
        self.assertNotIn("NATS connection and cleanup confirmed", output)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertTrue(any("install" in c for c in self.calls))
        self.assertEqual(output.count("LAUNCH:"), 1)

    def test_offline_connectivity_does_not_bypass_required_configuration_validation(self):
        self.failure = "nats"
        self.preflight_dependencies_missing = True
        self.answers["Known AcquisitionNode IDs"] = "bad.*"
        code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("PENDING / NOT VERIFIED", output)
        self.assertIn("Installing selected checkout", output)
        self.assertNotIn("LAUNCH:", output)
        self.assertFalse((self.config / "controller.json").exists())

    def test_offline_connectivity_does_not_change_pre_or_post_install_cancellation(self):
        self.failure = "nats"
        self.interrupt_at = "Install the displayed"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn("PENDING / NOT VERIFIED", output)
        self.assertIn("No installation changes", errors)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.environment.exists())
        self.interrupt_at = None
        with patch.object(installer.os, "fsync", side_effect=KeyboardInterrupt):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn("CANCELLED", errors)
        self.assertIn("partially changed", errors)
        self.assertFalse((self.config / "controller.json").exists())
        self.assertNotIn("LAUNCH:", output)

    def test_interrupted_configuration_write_leaves_no_partial_json(self):
        with patch.object(installer.os, "fsync", side_effect=KeyboardInterrupt):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn("CANCELLED", errors)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_configuration_created_by_another_operator_is_never_overwritten(self):
        publish = installer._publish
        contents = b'{"operator": "new configuration must not be overwritten"}'

        def appear(path, generated):
            path.write_bytes(contents)
            return publish(path, generated)

        with patch.object(installer, "_publish", side_effect=appear):
            code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual((self.config / "controller.json").read_bytes(), contents)
        self.assertEqual(len(list(self.config.glob("*.json"))), 1)

    def test_invalid_hardware_is_rejected_by_actual_loader_without_opening_camera(self):
        self.answers["Local roles"] = "acquisition-node"
        hardware = self.hardware()
        hardware.write_text('{"node_id":"node"}', encoding="utf-8")
        before = hardware.read_bytes()
        with patch("lab_sync_acquisition.service_startup.SeeedIMX219OpenCVCameraAdapter",
                   side_effect=AssertionError("Hardware must not be opened")):
            code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(hardware.read_bytes(), before)
        self.assertNotIn("LAUNCH:", output)
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_later_publication_failure_keeps_only_complete_valid_earlier_configs(self):
        self.answers["Local roles"] = "controller synchronization-manager"
        publish = installer._publish

        def fail_second(path, contents):
            if path.name == "synchronization-manager.json":
                raise OSError("Second config cannot be published")
            return publish(path, contents)

        with patch.object(installer, "_publish", side_effect=fail_second):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        load_service_configuration(self.config / "controller.json", "controller")
        self.assertFalse((self.config / "synchronization-manager.json").exists())
        self.assertEqual(len(list(self.config.glob("*.json"))), 1)
        self.assertIn("complete new configs may remain", errors)
        self.assertNotIn("LAUNCH:", output)

    def test_windows_and_linux_commands_quote_paths_with_spaces_for_native_shell(self):
        for operating_system in ("win32", "linux"):
            with self.subTest(operating_system=operating_system), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "private config"
                self.environment = Path(directory) / ".venv"
                # The installer environment is always relative to its chosen checkout.
                self.checkout = Path(directory) / "checkout with spaces"
                self.checkout.mkdir()
                self.environment = self.checkout / ".venv"
                (self.checkout / "pyproject.toml").write_text('[project]\nname="lab-sync-acquisition"\n', encoding="utf-8")
                self.platform = operating_system
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                command = next(line for line in output.splitlines() if line.startswith("LAUNCH:"))
                self.assertIn("--deployment-config", command)
                self.assertIn("'", command)
                self.assertEqual(command.startswith("LAUNCH: & "), operating_system == "win32")


@unittest.skipUnless(NATS_SERVER, 'isolated nats-server unavailable')
class InstallerAccountDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_account_readback_or_denial_never_creates_broker_resources(self):
        from uuid import uuid4
        import nats
        for account_available in (True, False):
            with self.subTest(account_available=account_available):
                user, password = uuid4().hex, uuid4().hex + '@:/?#%40 \u03bb'
                declaration = {'user': user, 'password': password}
                if not account_available:
                    declaration['permissions'] = {'publish': {'allow': ['>'], 'deny': ['$SYS.REQ.USER.INFO']}}
                users = json.dumps([declaration], ensure_ascii=False)
                options = ({'server_configuration': 'system_account: SYS\naccounts {\nSYS {}\nLAB {\njetstream: enabled\nusers: ' + users + '\n}\n}\n'}
                           if account_available else {'authorization': 'users: ' + users})
                async with restartable_jetstream_server(**options) as server:
                    payload = json.dumps({'servers': [server.url], 'nats_username': user,
                        'nats_password': password, 'timeout_s': 1, 'discover_account': True}).encode()
                    arguments = [sys.executable, '-I', '-B', '-c', installer.CONNECT]
                    child = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(child.communicate(payload), 10)
                    self.assertEqual(child.returncode, 0, 'Isolated account discovery child failed')
                    self.assertEqual(json.loads(stdout)['account'], 'LAB' if account_available else None)
                    for value in (user, password):
                        self.assertNotIn(value, stdout.decode() + stderr.decode() + str(arguments))
                    client = await nats.connect(server.url, user=user, password=password, allow_reconnect=False)
                    try:
                        self.assertEqual(await client.jetstream().streams_info(), [])
                    finally:
                        await client.close()


if __name__ == "__main__":
    unittest.main()
