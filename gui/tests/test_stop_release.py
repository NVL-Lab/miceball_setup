"""Connected Stop/release orchestration through production browser presenters."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from gui.tests import test_catalog


class StopReleaseTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_stop_and_release_in_browser(self):
        node = shutil.which('node')
        module = os.environ.get('LAB_SYNC_PLAYWRIGHT_MODULE', 'playwright')
        if not node or subprocess.run([node, '-e', 'require(process.argv[1])', module], capture_output=True).returncode:
            self.skipTest('Node and Playwright required')
        result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix('.mjs'))],
            env={**os.environ, 'MICEBALL_STOP_ORIGIN': self.origin}, capture_output=True,
            text=True, encoding='utf-8', timeout=150)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
