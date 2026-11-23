"""Ordinary rendered preparation through the real backend, Controller and isolated NATS."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from gui.tests import test_backend as fixtures


class SessionPreparationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.GUIIntegrationTests.asyncSetUp
    backend = fixtures.GUIIntegrationTests.backend
    cleanup_node = fixtures.GUIIntegrationTests.cleanup_node
    deliver_marker_boundary = fixtures.GUIIntegrationTests.deliver_marker_boundary

    async def test_free_mode_launch_requires_no_framework_json(self):
        await self.check_preparation()

    async def test_free_mode_stop_releases_binding_through_real_owners(self):
        await self.check_preparation(closeout=True)

    async def test_protocol_mode_preserves_selected_name_without_framework_json(self):
        from miceball_gui.catalog_store import CatalogStore
        store = CatalogStore(self.root / 'gui-catalog.sqlite3')
        for collection, record in (
            ('experimenters', {'id': 'scientist', 'name': 'Scientist'}),
            ('projects', {'id': 'project', 'name': 'Study', 'primary_experimenter': 'scientist'}),
            ('protocols', {'id': 'procedure', 'projectId': 'project', 'owner': 'scientist', 'name': 'Procedure',
                'description': '', 'protected': False, 'steps': [{'id': 'one', 'name': 'Acquire',
                    'operation': 'acquisition', 'description': '', 'mandatory': True,
                    'required': [], 'optional': [], 'configuration': ''}]})):
            store.put(collection, record, actor='scientist', expected_revision=store.read()['revision'])
        await self.check_preparation(protocol=True)

    async def check_preparation(self, protocol=False, closeout=False):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        result = await asyncio.to_thread(subprocess.run,
            [node, str(Path(__file__).with_suffix('.mjs'))],
            env={**os.environ, 'MICEBALL_PREPARATION_ORIGIN': self.origin,
                 'MICEBALL_PREPARATION_PROTOCOL': '1' if protocol else '',
                 'MICEBALL_PREPARATION_CLOSEOUT': '1' if closeout else '',
                 'MICEBALL_PREPARATION_ERRORS': str(self.root / 'errors')},
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if closeout:
            self.assertIsNone(self.controller.get_status()['session_id'])
            return
        self.assertEqual(self.controller.get_status()['session_state'], 'running')
        configuration = self.controller.read_session_configuration().details['configuration']
        self.assertEqual(configuration['protocol_reference'], 'Procedure' if protocol else None)
        self.assertEqual(configuration['protocol_plan'], {})
        self.assertIsNone(self.controller.get_status()['active_experiment_id'])

