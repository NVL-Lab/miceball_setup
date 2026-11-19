"""Current catalog choices coexist with detached accepted scientific identities."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from gui.tests import test_catalog


class CatalogIdentityBrowserTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_choices_and_history_through_catalog_changes_and_release(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
            env={**os.environ, 'MICEBALL_CATALOG_ORIGIN': self.origin}, capture_output=True,
            text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
