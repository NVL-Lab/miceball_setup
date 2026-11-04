"""Rendered Services and inventory feedback with controlled transport outcomes."""

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

from gui.tests.test_backend import create_gui_app
from lab_sync_acquisition import AcquisitionNode, DeviceDeclaration, DeviceManager, ScientificProductDeclaration
from lab_sync_acquisition.device_adapter import DeviceAdapter


class ConnectedFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_services_and_inventory_feedback_in_browser(self):
        node = shutil.which("node")
        module = os.environ.get("LAB_SYNC_PLAYWRIGHT_MODULE", "playwright")
        if not node or subprocess.run([node, "-e", "require(process.argv[1])", module], capture_output=True).returncode:
            self.skipTest("Node and an installed Playwright package are required")
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        connected = TestClient(TestServer(create_gui_app(servers=["nats://127.0.0.1:1"],
            controller_id="feedback", client_id="gui", origin=origin, timeout_s=.1), port=port))
        await connected.start_server()
        self.addAsyncCleanup(connected.close)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        static = Path(__file__).parents[1] / "src/miceball_gui/static"
        baseline = Path(directory) / "baseline"
        baseline.mkdir()
        repository = Path(__file__).resolve().parents[2]
        files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "gui/src/miceball_gui/static"], cwd=repository, text=True).splitlines()
        for filename in files:
            (baseline / Path(filename).name).write_bytes(subprocess.check_output(["git", "show", "HEAD:" + filename], cwd=repository))
        demos = {}
        for name, source in (("current", static), ("baseline", baseline)):
            app = web.Application()
            async def index(request, source=source):
                return web.FileResponse(source / "index.html")
            app.router.add_get("/", index)
            app.router.add_static("/", source)
            demo = TestClient(TestServer(app))
            await demo.start_server()
            self.addAsyncCleanup(demo.close)
            demos[name] = str(demo.make_url("/"))
        identities = ['camera" onpointerover="window.__auditMarkupExecuted = 1" data-tail="',
            'camera "double" and \'single\'', 'camera & <metadata> [0] #', 'ordinary-camera']
        product = ScientificProductDeclaration("frames", "camera_frames", {}, "jsonl")
        inventory_owner = AcquisitionNode(device_manager=DeviceManager(
            DeviceAdapter(identity, "test-camera", (), False) for identity in identities),
            node_id="node", role="acquisition", synchronization_source_id="sync",
            device_declarations=tuple(DeviceDeclaration(identity, "test-camera", True, False, (), (product,))
                for identity in identities))
        environment = {**os.environ, "LAB_SYNC_PLAYWRIGHT_MODULE": module,
            "MICEBALL_BROWSER_ORIGIN": origin, "MICEBALL_DEMO_ORIGIN": demos["baseline"],
            "MICEBALL_DEMO_CURRENT_ORIGIN": demos["current"],
            "MICEBALL_BROWSER_EVIDENCE": os.environ.get("LAB_SYNC_GUI_EVIDENCE_DIR", directory),
            "MICEBALL_DEVICE_IDENTITY_INVENTORY": json.dumps(inventory_owner.get_inventory())}
        result = await asyncio.to_thread(subprocess.run,
            [node, str(Path(__file__).with_suffix(".mjs"))], env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
