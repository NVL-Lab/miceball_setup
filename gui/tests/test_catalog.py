"""Public durable catalog workflows; no Controller or live broker required."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from miceball_gui.catalog_store import CatalogStore, CatalogConflict
from miceball_gui.backend import create_gui_app
from aiohttp.test_utils import TestClient, TestServer


class CatalogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "catalog.sqlite3"
        self.store = CatalogStore(self.path)
        self.save("experimenters", {"id": "alice", "name": "Alice"})
        self.save("experimenters", {"id": "bob", "name": "Bob"})
        self.save("projects", {"id": "p", "name": "Study", "primary_experimenter": "alice"})
        self.save("projects", {"id": "q", "name": "Other study", "primary_experimenter": "bob"})

    def save(self, collection, record, actor="alice"):
        return self.store.put(collection, record, actor=actor, expected_revision=self.store.read()["revision"])

    def step(self):
        return dict(id="saved", name="Acquire", owner="alice", operation="acquisition", description="",
                    mandatory=True, required=[], optional=[], configuration="")

    def protocol(self):
        step = self.step()
        step.update(id="occurrence", definitionId="saved")
        return dict(id="protocol", projectId="p", owner="alice", name="Procedure", description="", protected=False, steps=[step])

    def test_restart_backup_and_independent_installation(self):
        self.save("animals", dict(id="animal-stable", projectId="p", animal_id="M1", animal_name="Pip"))
        snapshot = self.store.read()
        self.assertEqual(CatalogStore(self.path).read(), snapshot)
        backup = self.path.with_name("backup.sqlite3")
        shutil.copy2(self.path, backup)  # Store holds no persistent connection; backend is stopped.
        self.save("experimenters", {"id": "alice", "name": "Renamed"})
        restored = self.path.with_name("restored.sqlite3")
        shutil.copy2(backup, restored)
        self.assertEqual(CatalogStore(restored).read(), snapshot)
        independent = CatalogStore(self.path.with_name("independent.sqlite3"))
        self.assertEqual(independent.read()["catalog"]["experimenters"], [])
        self.assertEqual(self.store.read()["catalog"]["animals"][0]["id"], "animal-stable")

    def test_concurrent_browsers_cannot_lose_updates(self):
        revision = self.store.read()["revision"]
        def submit(name):
            try:
                return CatalogStore(self.path).put("experimenters", {"id": name, "name": name},
                    expected_revision=revision, actor="alice")
            except CatalogConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, ["one", "two"]))
        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(self.store.read()["revision"], revision + 1)

    def test_project_relationships_and_stable_references(self):
        before = self.store.read()
        for collection, record in [
            ("projects", dict(id="x", name="Unowned", primary_experimenter="missing")),
            ("animals", dict(id="x", animal_id="M1")),
            ("protocols", dict(id="x", name="No project", protected=False, steps=[])),
        ]:
            with self.assertRaises(ValueError):
                self.save(collection, record)
            self.assertEqual(self.store.read(), before)
        self.save("definitions", self.step())
        self.save("protocols", self.protocol())
        template = dict(id="session-template", projectId="p", protocol="protocol", owner="alice", name="Daily", included=["occurrence"], devices=[])
        self.save("templates", template)
        with self.assertRaises(ValueError):
            self.save("templates", {**template, "id": "wrong-project", "projectId": "q"})
        with self.assertRaises(ValueError):
            self.save("protocols", {**self.protocol(), "projectId": "q"})
        renamed = {**self.protocol(), "name": "Renamed procedure"}
        self.save("protocols", renamed)
        self.assertEqual(self.store.read()["catalog"]["templates"][0]["protocol"], renamed["id"])

    def test_saved_steps_are_immutable_globally_unique_and_copies_independent(self):
        self.save("definitions", self.step())
        self.save("protocols", self.protocol())
        with self.assertRaises(ValueError):
            self.save("definitions", {**self.step(), "description": "Changed"})
        with self.assertRaises(ValueError):
            self.save("definitions", {**self.step(), "id": "other", "name": "ACQUIRE", "owner": "bob"}, "bob")
        copy = {**self.step(), "id": "independent", "name": "Acquire - copy", "owner": "bob"}
        self.save("definitions", copy, "bob")
        contradictory = self.protocol()
        contradictory["steps"][0]["configuration"] = "Different"
        with self.assertRaises(ValueError):
            self.save("protocols", contradictory)
        self.assertEqual(self.store.read()["catalog"]["definitions"][0], self.step())

    def test_lab_and_personal_template_rules_and_lossless_configuration(self):
        configuration = dict(durationSeconds=2, participants=[], values={"text": " \u03a9\r\n\0\ud800\"\\ ", "null": None, "empty": ""})
        lab = dict(id="lab", name="Reference", owner=None, operation="acquisition", configuration=configuration)
        self.save("experimentTemplates", lab)
        with self.assertRaises(ValueError):
            self.save("experimentTemplates", {**lab, "name": "Overwrite"})
        personal = {**lab, "id": "personal", "name": "My copy", "owner": "alice"}
        self.save("experimentTemplates", personal)
        with self.assertRaises(ValueError):
            self.save("experimentTemplates", {**personal, "name": "Other owner's edit"}, "bob")
        self.save("experimentTemplates", {**personal, "name": "My edited copy"})
        recovered = CatalogStore(self.path).read()["catalog"]["experimentTemplates"]
        self.assertEqual(recovered[0], lab)
        self.assertEqual(recovered[1]["configuration"], configuration)
        self.assertNotIn("absent", recovered[1]["configuration"]["values"])

    def test_session_template_owner_edits_do_not_change_lab_references(self):
        self.save("definitions", self.step())
        self.save("protocols", self.protocol())
        reference = dict(id="reference", projectId="p", protocol="protocol", owner=None,
            name="Laboratory", included=["occurrence"], devices=[])
        self.save("templates", reference)
        with self.assertRaises(ValueError):
            self.save("templates", {**reference, "name": "Changed reference"})
        personal = {**reference, "id": "personal", "name": "My template", "owner": "alice"}
        self.save("templates", personal)
        with self.assertRaises(ValueError):
            self.save("templates", {**personal, "included": []}, "bob")
        self.save("templates", {**personal, "included": []})
        self.assertEqual(self.store.read()["catalog"]["templates"][0], reference)
        self.assertEqual(self.store.read()["catalog"]["templates"][1]["included"], [])

    def test_write_failure_and_interruption_retain_committed_document(self):
        before = self.store.read()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TRIGGER refuse_update BEFORE UPDATE ON catalog BEGIN SELECT RAISE(ABORT, 'disk write refused'); END")
        with self.assertRaises(sqlite3.Error):
            self.save("experimenters", {"id": "failed", "name": "Failed"})
        self.assertEqual(self.store.read(), before)
        # A killed writer with an uncommitted transaction must not replace the document.
        script = "import sqlite3,sys,os; c=sqlite3.connect(sys.argv[1]); c.execute('DROP TRIGGER refuse_update'); c.execute('BEGIN IMMEDIATE'); c.execute(\"UPDATE catalog SET document='{}'\"); os._exit(0)"
        subprocess.run([sys.executable, "-B", "-c", script, str(self.path)], check=True)
        self.assertEqual(CatalogStore(self.path).read(), before)

    def test_corruption_and_unsupported_catalog_are_not_reset(self):
        for contents in (b"not sqlite", b""):
            path = self.path.with_name("damaged.sqlite3")
            path.write_bytes(contents)
            with self.assertRaises((ValueError, sqlite3.Error)):
                CatalogStore(path)
            self.assertEqual(path.read_bytes(), contents)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE catalog SET version=99")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            CatalogStore(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_runtime_state_is_not_catalog_data(self):
        with self.assertRaises(ValueError):
            self.save("activeSession", {"id": "session", "name": "Session"})
        with self.assertRaises(ValueError):
            self.save("protocols", {**self.protocol(), "activeSession": {"accepted": True}})

    def test_disappeared_catalog_is_not_recreated_by_readback(self):
        self.path.unlink()
        with self.assertRaises(sqlite3.Error):
            self.store.read()
        self.assertFalse(self.path.exists())


class CatalogHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "catalog.sqlite3"
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        app = create_gui_app(servers=["nats://127.0.0.1:1"], controller_id="controller", client_id="gui",
            origin=self.origin, timeout_s=.1, catalog_path=self.path, max_request_bytes=4096)
        self.web = TestClient(TestServer(app, port=port))
        await self.web.start_server()
        self.addAsyncCleanup(self.web.close)

    async def test_shared_read_stale_save_and_backend_status_without_broker(self):
        first = await (await self.web.get("/api/catalog")).json()
        second = await (await self.web.get("/api/catalog")).json()
        payload = dict(collection="experimenters", record={"id": "alice", "name": "Alice"}, actor="alice", expected_revision=first["revision"])
        result = await self.web.post("/api/catalog", json=payload, headers={"Origin": self.origin})
        self.assertEqual(result.status, 200)
        payload["record"] = {"id": "bob", "name": "Bob"}
        payload["expected_revision"] = second["revision"]
        rejected = await self.web.post("/api/catalog", json=payload, headers={"Origin": self.origin})
        self.assertEqual(rejected.status, 409)
        self.assertEqual(len((await (await self.web.get("/api/catalog")).json())["catalog"]["experimenters"]), 1)
        info = await (await self.web.get("/api/backend")).json()
        self.assertEqual(info["host"], socket.gethostname())
        self.assertEqual(info["catalog_path"], str(self.path.resolve()))
        self.assertTrue(info["catalog_available"])
        self.assertNotIn("servers", info)

    async def test_origin_host_body_and_record_guards(self):
        payload = dict(collection="experimenters", record={"id": "alice", "name": "Alice"}, actor="alice", expected_revision=0)
        for origin in (None, "https://untrusted.invalid"):
            result = await self.web.post("/api/catalog", json=payload, headers={"Origin": origin} if origin else {})
            self.assertEqual(result.status, 403)
        self.assertEqual((await self.web.get("/api/catalog", headers={"Host": "untrusted.invalid"})).status, 403)
        oversized = await self.web.post("/api/catalog", data="x" * 5000, headers={"Origin": self.origin, "Content-Type": "application/json"})
        self.assertEqual(oversized.status, 413)
        payload["record"]["activeSession"] = {}
        self.assertEqual((await self.web.post("/api/catalog", json=payload, headers={"Origin": self.origin})).status, 400)
        self.assertEqual((await (await self.web.get("/api/catalog")).json())["revision"], 0)


if __name__ == "__main__":
    unittest.main()
