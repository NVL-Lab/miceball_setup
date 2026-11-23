"""Presentation-only output grouping and selectable activity messages."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from gui.tests import test_catalog


class MinorGuiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def check_browser(self, scenario):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs')), scenario],
            env={**os.environ, 'MICEBALL_MINOR_ORIGIN': self.origin}, capture_output=True,
            text=True, encoding='utf-8', timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)

    async def test_scientific_output_grouping(self):
        await self.check_browser('outputs')

    async def test_activity_text_selection(self):
        await self.check_browser('history')
