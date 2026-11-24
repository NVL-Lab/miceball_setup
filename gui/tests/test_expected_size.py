"""Expected size in the production GUI using software-only owner readback."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from miceball_gui.backend import create_gui_app
from lab_sync_acquisition.session import ExperimentConfiguration, ScientificOutputSelection, SessionConfig
from lab_sync_acquisition.storage import PersistentStorageManager
from lab_sync_acquisition import Controller, InMemoryIngestor, AcquisitionNode, DeviceManager
from lab_sync_acquisition.service_maintenance import ServiceMaintenanceInterface
from lab_sync_acquisition.communication import RuntimeParticipant
from tests import test_expected_size as owners
from tests.nats_server_fixture import acquire_test_controller_authority


class ExpectedSizeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_size_preparation(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        owner, _, _ = owners.ExpectedSizeOwnerTests().node()
        _, session_adapter, _ = owners.ExpectedSizeOwnerTests().node()
        session_owner = AcquisitionNode(device_manager=DeviceManager((session_adapter,)), node_id='node',
            role='acquisition', synchronization_source_id='sync', device_declarations=owner.declared_devices,
            deployment_device_configurations={'camera': {'camera_source': 0, 'api_preference': 0,
                'frames_per_collect': 2, 'frame_width': 4, 'frame_height': 2}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'science').mkdir()
            storage = PersistentStorageManager(root / 'evidence', global_artifact_root=root / 'science')
            controller = Controller()
            async def close_resources(force):
                return True
            maintenance = ServiceMaintenanceInterface(controller, RuntimeParticipant('controller', 'controller'),
                ingestor=InMemoryIngestor(), storage_manager=storage, preservation_window_s=1,
                close_resources=close_resources)
            await acquire_test_controller_authority(self, maintenance)

            class OwnerReadback:
                async def request_runtime_command(self, target, operation, session_id, payload, result_window_s):
                    if target.component_type == 'acquisition_node':
                        report = (session_owner if session_id else owner).estimate_experiment_storage(
                            [ScientificOutputSelection.from_dict(o) for o in payload['scientific_outputs']],
                            ExperimentConfiguration.from_dict(payload['configuration']))
                    else:
                        report = storage.estimate_experiment_storage(payload['recording_estimates'],
                            storage_location=payload['storage_location'])
                    return SimpleNamespace(success=True, status='succeeded', source_id=target.component_id,
                        target_id='controller', session_id=session_id, payload={'estimate': report})
            with socket.socket() as candidate:
                candidate.bind(('127.0.0.1', 0))
                port = candidate.getsockname()[1]
            origin = f'http://127.0.0.1:{port}'
            app = create_gui_app(servers=['nats://127.0.0.1:1'], controller_id='controller', client_id='gui',
                origin=origin, timeout_s=.1, catalog_path=root / 'catalog.sqlite3')

            async def estimate(request):
                data = await request.json()
                result = await controller.estimate_experiment_storage(**data,
                    communication=OwnerReadback(), participants=(RuntimeParticipant('acquisition_node', 'node'),),
                    storage_participant=RuntimeParticipant('storage_manager', 'storage'), result_window_s=1)
                if not result.succeeded:
                    return web.json_response({'error': result.error}, status=400)
                return web.json_response(result.details)

            async def accept_session(request):
                configuration = SessionConfig(list(owner.declared_devices), 'default', {}, str(root / 'errors'),
                    session_id='scoped-session', session_parameters={'name': 'Scoped inventory'},
                    expected_runtime_participants=(RuntimeParticipant('acquisition_node', 'node'),))
                result = controller.create_session(configuration)
                self.assertTrue(result.succeeded, result.error)
                return web.json_response(configuration.to_dict())

            app.router.add_post('/test/estimate', estimate)
            app.router.add_post('/test/session', accept_session)
            client = TestClient(TestServer(app, port=port))
            await client.start_server()
            try:
                environment = {**os.environ, 'MICEBALL_EXPECTED_ORIGIN': origin,
                               'MICEBALL_EXPECTED_INVENTORY': json.dumps(owner.get_inventory())}
                if os.environ.get('LAB_SYNC_GUI_EVIDENCE_DIR'):
                    Path(os.environ['LAB_SYNC_GUI_EVIDENCE_DIR']).mkdir(parents=True, exist_ok=True)
                result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
                    env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout)
            finally:
                await client.close()
