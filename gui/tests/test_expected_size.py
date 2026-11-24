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

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from miceball_gui.backend import create_gui_app
from lab_sync_acquisition.session import ExperimentConfiguration, ScientificOutputSelection
from lab_sync_acquisition.storage import PersistentStorageManager
from tests import test_expected_size as owners


class ExpectedSizeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_size_preparation(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        owner, _, _ = owners.ExpectedSizeOwnerTests().node()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'science').mkdir()
            storage = PersistentStorageManager(root / 'evidence', global_artifact_root=root / 'science')
            with socket.socket() as candidate:
                candidate.bind(('127.0.0.1', 0))
                port = candidate.getsockname()[1]
            origin = f'http://127.0.0.1:{port}'
            app = create_gui_app(servers=['nats://127.0.0.1:1'], controller_id='controller', client_id='gui',
                origin=origin, timeout_s=.1, catalog_path=root / 'catalog.sqlite3')

            async def estimate(request):
                data = await request.json()
                try:
                    configuration = ExperimentConfiguration.from_dict(data['configuration'])
                except (ValueError, TypeError) as error:
                    return web.json_response({'error': str(error)}, status=400)
                outputs = [ScientificOutputSelection.from_dict(o) for o in data['scientific_outputs']]
                report = owner.estimate_experiment_storage(outputs, configuration)
                return web.json_response({**data, 'session_id': None, 'recording': [report],
                    'preservation': storage.estimate_experiment_storage([report], storage_location='default'),
                    'expected_bytes': report['estimated_bytes']})

            app.router.add_post('/test/estimate', estimate)
            client = TestClient(TestServer(app, port=port))
            await client.start_server()
            try:
                environment = {**os.environ, 'MICEBALL_EXPECTED_ORIGIN': origin,
                               'MICEBALL_EXPECTED_INVENTORY': json.dumps(owner.get_inventory())}
                result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
                    env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout)
            finally:
                await client.close()
