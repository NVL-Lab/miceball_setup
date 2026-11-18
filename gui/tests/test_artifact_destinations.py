"""Developer checks for the destination GUI and its existing transport boundary."""
import asyncio
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from miceball_gui.backend import create_gui_app
from aiohttp.test_utils import TestClient, TestServer


class ArtifactDestinationGuiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.settings = dict(servers=["nats://127.0.0.1:1"], controller_id="controller", client_id="gui",
            origin=self.origin, timeout_s=.1, catalog_path=Path(self.directory) / "catalog.sqlite3")
        self.web = TestClient(TestServer(create_gui_app(**self.settings), port=port))
        await self.web.start_server()
        self.addAsyncCleanup(self.web.close)

    async def test_registry_is_owned_by_storage_and_survives_gui_backend_restart(self):
        from lab_sync_acquisition import PersistentStorageManager
        root = Path(self.directory)
        for directory in (root / "default", root / "alternative"):
            directory.mkdir()
        storage = PersistentStorageManager(root / "records", global_artifact_root=root / "default", component_id="storage")
        with self.assertRaises(PermissionError):
            storage.register_artifact_destination("alternative", "Second disk", str(root / "alternative"),
                experimenter_name="Alice", administrator_mode=False)
        storage.register_artifact_destination("alternative", "Second disk", str(root / "alternative"),
            experimenter_name="Alice", administrator_mode=True)
        storage.admit_session_artifact_destination("session", "alternative")
        await self.web.close()
        port = int(self.origin.rsplit(":", 1)[1])
        self.web = TestClient(TestServer(create_gui_app(**self.settings), port=port))
        await self.web.start_server()
        self.addAsyncCleanup(self.web.close)
        fresh = PersistentStorageManager(root / "records", global_artifact_root=root / "default", component_id="storage")
        entries = fresh.list_artifact_destinations()["destinations"]
        self.assertEqual([entry["destination_id"] for entry in entries], ["default", "alternative"])
        self.assertEqual(fresh.read_session_artifact_destination("session")["destination_id"], "alternative")
        with self.assertRaises(RuntimeError):
            fresh.update_artifact_destination("alternative", enabled=False, remove=True,
                experimenter_name="Alice", administrator_mode=True)
        fresh.update_artifact_destination("alternative", enabled=False, experimenter_name="Alice", administrator_mode=True)
        self.assertEqual(fresh.read_session_artifact_destination("session")["destination_id"], "alternative")

    async def test_existing_transport_preserves_management_context_without_local_authorization(self):
        result = SimpleNamespace(status="succeeded", outcome={}, to_dict=lambda: {"status": "succeeded", "outcome": {}})
        send = AsyncMock(return_value=result)
        with patch("miceball_gui.backend.NatsCommunicationBoundary.connect", new_callable=AsyncMock), patch(
                "miceball_gui.backend.NatsExternalSessionLaunchClient.request_operation", send):
            ws = await self.web.ws_connect("/ws", headers={"Origin": self.origin})
            await ws.receive_json()
            for operation, parameters in (
                    ("list_artifact_destinations", {}),
                    ("register_artifact_destination", {"destination_id": "alternative", "name": "Disk", "root": "/data/disk", "experimenter_name": "Alice", "administrator_mode": False}),
                    ("update_artifact_destination", {"destination_id": "alternative", "enabled": False, "remove": True, "experimenter_name": "Alice", "administrator_mode": True})):
                await ws.send_json(dict(id=operation, operation=operation, session_id=None, parameters=parameters))
                reply = await asyncio.wait_for(ws.receive_json(), 3)
                self.assertEqual(reply["result"]["status"], "succeeded")
                self.assertEqual(send.call_args.args[0].parameters, parameters)
                self.assertEqual(send.call_args.args[0].operation, operation)
            await ws.close()

    async def test_destination_workflows_in_browser(self):
        node = shutil.which("node")
        module = os.environ.get("LAB_SYNC_PLAYWRIGHT_MODULE", "playwright")
        if not node or subprocess.run([node, "-e", "require(process.argv[1])", module], capture_output=True).returncode:
            self.skipTest("Node and installed Playwright required")
        environment = {**os.environ, "MICEBALL_DESTINATION_ORIGIN": self.origin,
            "MICEBALL_DESTINATION_EVIDENCE": os.environ.get("LAB_SYNC_GUI_EVIDENCE_DIR", self.directory)}
        result = await asyncio.to_thread(subprocess.run,
            [node, str(Path(__file__).with_suffix(".mjs"))], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=150)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
