"""Installation-owned defaults, durable updates and real GUI HTTP/WS admission."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from gui.tests import test_catalog
from miceball_gui.catalog_store import CatalogStore, CatalogConflict, INITIAL_SYNCHRONIZATION_CONFIGURATION
from miceball_gui.backend import create_gui_app
from lab_sync_acquisition import DeviceDeclaration, SessionConfig
from aiohttp.test_utils import TestClient, TestServer


class SynchronizationSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'catalog.sqlite3'
        self.store = CatalogStore(self.path)

    def save(self, configuration, **changes):
        return self.store.put_synchronization(configuration, expected_revision=changes.get('revision', self.store.read()['revision']),
            administrator_id=changes.get('administrator_id', 'Operator'), authorized=changes.get('authorized', True))

    def test_initial_values_and_saved_settings_survive_update_proposals(self):
        expected = dict(exchanges=3, initial_scale=1.0, clock_rate_error_bound=.001, max_uncertainty_s=.5,
            max_mapping_age_s=20., assessment_interval_s=5., result_window_s=2., quality_interpretation='warning')
        self.assertEqual(self.store.read()['synchronization_configuration'], expected)
        saved = self.save({**expected, 'exchanges': 5})
        self.assertEqual(CatalogStore(self.path, initial_synchronization={**expected, 'exchanges': 7}).read(), saved)
        other = CatalogStore(self.path.with_name('override.sqlite3'), initial_synchronization={**expected, 'exchanges': 9})
        self.assertEqual(other.read()['synchronization_configuration']['exchanges'], 9)

    def test_legacy_document_migrates_without_changing_catalog_values(self):
        path = self.path.with_name('legacy.sqlite3')
        document = json.dumps(self.store.read()['catalog'])
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('CREATE TABLE catalog(singleton INTEGER PRIMARY KEY, version INTEGER, revision INTEGER, document TEXT)')
            connection.execute('INSERT INTO catalog VALUES(1,1,7,?)', (document,))
        snapshot = CatalogStore(path).read()
        self.assertEqual(snapshot['revision'], 8)
        self.assertEqual(snapshot['catalog'], json.loads(document))
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute('SELECT document FROM catalog').fetchone()[0], document)
        self.assertEqual(CatalogStore(path).read(), snapshot)

    def test_invalid_configuration_authorization_and_corruption_refuse_changes(self):
        before = self.store.read(); config = before['synchronization_configuration']
        for change in ({'exchanges': True}, {'exchanges': 1}, {'initial_scale': 0}, {'clock_rate_error_bound': 1},
                       {'max_uncertainty_s': float('inf')}, {'max_mapping_age_s': -1}, {'assessment_interval_s': 0},
                       {'result_window_s': None}, {'quality_interpretation': 'invented'}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                self.save({**config, **change})
            self.assertEqual(self.store.read(), before)
        for authorization in ({'authorized': False}, {'administrator_id': ''}):
            with self.assertRaises(ValueError): self.save(config, **authorization)
        for corrupt in ('{', '{}', json.dumps({**config, 'exchanges': 0})):
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.execute('UPDATE catalog SET synchronization_configuration=?', (corrupt,))
            data = self.path.read_bytes()
            with self.assertRaises((ValueError, TypeError)): CatalogStore(self.path)
            self.assertEqual(self.path.read_bytes(), data)

    def test_shared_revision_fences_catalog_and_settings_updates(self):
        snapshot = self.store.read(); config = snapshot['synchronization_configuration']
        self.store.put('experimenters', dict(id='alice', name='Alice'), actor='alice', expected_revision=snapshot['revision'])
        with self.assertRaises(CatalogConflict): self.save(config, revision=snapshot['revision'])
        revision = self.store.read()['revision']
        def save(value):
            try: return self.save({**config, 'exchanges': value}, revision=revision)
            except CatalogConflict: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(save, [4, 5]))
        self.assertEqual(results.count('conflict'), 1)
        with self.assertRaises(CatalogConflict):
            self.store.put('experimenters', dict(id='bob', name='Bob'), actor='alice', expected_revision=revision)


class SynchronizationSettingsHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / 'catalog.sqlite3'
        boundary = SimpleNamespace(connected=True, close=AsyncMock())
        self.forwarded = []
        async def launch(request, **kwargs):
            self.forwarded.append(request.to_dict())
            return SimpleNamespace(to_dict=lambda: {'status': 'succeeded'})
        self.client = SimpleNamespace(request_launch=AsyncMock(side_effect=launch))
        self.enterContext(patch('miceball_gui.backend.NatsCommunicationBoundary', return_value=boundary))
        self.enterContext(patch('miceball_gui.backend.NatsExternalSessionLaunchClient', return_value=self.client))
        self.web, self.origin = await self.backend(self.path)

    async def backend(self, path):
        with socket.socket() as candidate:
            candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        client = TestClient(TestServer(create_gui_app(servers=['nats://unused:4222'], controller_id='controller',
            client_id='gui', origin=origin, timeout_s=.1, catalog_path=path), port=port))
        await client.start_server(); self.addAsyncCleanup(client.close)
        return client, origin

    async def test_settings_authorization_and_authoritative_launch_without_live_reconfiguration(self):
        first = await (await self.web.get('/api/catalog')).json()
        settings = {**first['synchronization_configuration'], 'exchanges': 6}
        payload = dict(synchronization_configuration=settings, administrator_id='Operator', authorized=False,
                       expected_revision=first['revision'])
        headers = {'Origin': self.origin}
        self.assertEqual((await self.web.post('/api/catalog', json=payload, headers=headers)).status, 400)
        payload['authorized'] = True
        self.assertEqual((await self.web.post('/api/catalog', json=payload, headers=headers)).status, 200)
        self.assertEqual(self.forwarded, [])
        self.assertEqual((await self.web.post('/api/catalog', json=payload, headers=headers)).status, 409)
        ws = await self.web.ws_connect('/ws', headers=headers); await ws.receive_json()
        declaration = DeviceDeclaration('camera', 'test', True, False, ()).to_dict()
        parameters = dict(selections={'node': [declaration]}, scientific_outputs=[],
            config_parameters={'storage_location': 'destination', 'error_evidence_location': 'errors',
                               'synchronization_configuration': {'exchanges': 'hostile'}, 'protocol_plan': {'preserve': True}})
        await ws.send_json(dict(id='launch-one', operation='launch_session', parameters=parameters, session_id=None))
        self.assertEqual((await ws.receive_json())['result']['status'], 'succeeded')
        self.assertEqual(self.forwarded[0]['config_parameters']['synchronization_configuration'], settings)
        self.assertEqual(self.forwarded[0]['config_parameters']['protocol_plan'], {'preserve': True})
        accepted = SessionConfig([], 'destination', {}, 'errors', synchronization_configuration=settings)
        before = accepted.to_dict()
        store = CatalogStore(self.path)
        store.put_synchronization({**settings, 'exchanges': 8}, expected_revision=store.read()['revision'], administrator_id='Operator', authorized=True)
        self.assertEqual(accepted.to_dict(), before)
        self.assertEqual(self.forwarded[0]['config_parameters']['synchronization_configuration'], settings)
        await ws.send_json(dict(id='launch-two', operation='launch_session', parameters=parameters, session_id=None))
        self.assertEqual((await ws.receive_json())['result']['status'], 'succeeded')
        self.assertEqual(self.forwarded[1]['config_parameters']['synchronization_configuration']['exchanges'], 8)
        await ws.close()
        legacy, origin = await self.backend(None)
        ws = await legacy.ws_connect('/ws', headers={'Origin': origin}); await ws.receive_json()
        await ws.send_json(dict(id='legacy', operation='launch_session', parameters=parameters, session_id=None))
        self.assertEqual((await ws.receive_json())['status'], 'rejected')
        self.assertEqual(len(self.forwarded), 2)
        await ws.close()
