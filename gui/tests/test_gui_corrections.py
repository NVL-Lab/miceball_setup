"""Focused rendered feedback with controlled Controller replies and real catalogs."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from gui.tests import test_catalog


class GuiCorrectionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_feedback_membership_and_automatic_catalog_refresh(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        environment = {**os.environ, 'MICEBALL_CORRECTIONS_ORIGIN': self.origin}
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
            env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
