"""Production Storage presentation with controlled Controller responses."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from gui.tests import test_catalog


class ConnectedStorageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_historical_collection_in_browser(self):
        from miceball_gui.catalog_store import CatalogStore
        store = CatalogStore(self.path)
        store.put('experimenters', {'id': 'scientist', 'name': 'Scientist'}, actor='scientist', expected_revision=store.read()['revision'])
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        images = Path(os.environ.get('MICEBALL_STORAGE_SCREENSHOTS', str(self.path.parent)))
        images.mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
            env={**os.environ, 'MICEBALL_STORAGE_ORIGIN': self.origin, 'MICEBALL_STORAGE_SCREENSHOTS': str(images)},
            capture_output=True, text=True, encoding='utf-8', timeout=150)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
