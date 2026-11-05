"""Real rendered shared GUI against disposable Controller/NATS owners."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gui.tests import test_backend as backend_fixtures
from tests import test_external_controller_lifecycle as lifecycle
from tests.nats_server_fixture import NATS_SERVER


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class ConnectedPresentationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = backend_fixtures.GUIIntegrationTests.asyncSetUp
    backend = backend_fixtures.GUIIntegrationTests.backend
    cleanup_node = lifecycle.ExternalLifecycleTests.cleanup_node
    deliver_marker_boundary = lifecycle.ExternalLifecycleTests.deliver_marker_boundary

    async def test_shared_presentation_and_controller_actions_in_browser(self):
        node = shutil.which("node")
        module = os.environ.get("LAB_SYNC_PLAYWRIGHT_MODULE", "playwright")
        if not node:
            self.skipTest("Node and Playwright are required for rendered GUI checks")
        probe = subprocess.run([node, "-e", "require(process.argv[1])", module], capture_output=True)
        if probe.returncode:
            self.skipTest("Set LAB_SYNC_PLAYWRIGHT_MODULE to an installed Playwright package")
        static = Path(__file__).parents[1] / "src/miceball_gui/static"
        directory = self.enterContext(tempfile.TemporaryDirectory())
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
        environment = {**os.environ, "LAB_SYNC_PLAYWRIGHT_MODULE": module,
            "MICEBALL_BROWSER_ORIGIN": self.origin, "MICEBALL_DEMO_ORIGIN": demos["baseline"],
            "MICEBALL_DEMO_CURRENT_ORIGIN": demos["current"],
            "MICEBALL_BROWSER_CONFIGURATION": json.dumps({"storage": str(self.root / "records"),
                "errors": str(self.root / "errors"), "fields": {"protocol_plan": {},
                # This workflow includes a long screenshot pass before a second Experiment.
                "synchronization_configuration": lifecycle.configuration(max_mapping_age_s=300.)}}),
            "MICEBALL_BROWSER_EVIDENCE": os.environ.get("LAB_SYNC_GUI_EVIDENCE_DIR", directory)}
        result = await asyncio.to_thread(subprocess.run,
            [node, str(Path(__file__).with_suffix(".mjs"))], env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
