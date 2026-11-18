"""Developer browser workflows against real disposable catalog HTTP persistence."""

import asyncio
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

from gui.tests.test_catalog import create_gui_app
from aiohttp.test_utils import TestClient, TestServer


class CatalogBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_workflows_in_browser(self):
        node = shutil.which("node")
        module = os.environ.get("LAB_SYNC_PLAYWRIGHT_MODULE", "playwright")
        if not node or subprocess.run([node, "-e", "require(process.argv[1])", module], capture_output=True).returncode:
            self.skipTest("Node and Playwright required")
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            settings = dict(servers=["nats://127.0.0.1:1"], controller_id="controller", client_id="gui",
                origin=origin, timeout_s=.1, catalog_path=Path(directory) / "catalog.sqlite3")
            web = TestClient(TestServer(create_gui_app(**settings), port=port))
            await web.start_server()
            try:
                environment = {**os.environ, "MICEBALL_CATALOG_ORIGIN": origin,
                    "MICEBALL_CATALOG_EVIDENCE": os.environ.get("LAB_SYNC_GUI_EVIDENCE_DIR", directory)}
                result = await asyncio.to_thread(subprocess.run, [node, str(Path(__file__).with_suffix(".mjs"))],
                    env=environment, capture_output=True, text=True, encoding="utf-8", timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout)
            finally:
                await web.close()
            # A new backend application must read the same accepted catalog.
            restarted = TestClient(TestServer(create_gui_app(**settings), port=port))
            await restarted.start_server()
            try:
                snapshot = await (await restarted.get("/api/catalog")).json()
                self.assertEqual(len(snapshot["catalog"]["experimenters"]), 2)
                self.assertEqual(len(snapshot["catalog"]["protocols"]), 1)
                self.assertEqual(snapshot["catalog"]["definitions"][0]["name"], "Saved acquisition")
            finally:
                await restarted.close()
