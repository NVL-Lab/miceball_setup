"""Catalog availability changes preserve copied configuration and durable references."""
from copy import deepcopy
from contextlib import closing
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import unittest
from gui.tests import test_catalog
from miceball_gui.catalog_store import CatalogStore, CatalogConflict


class CatalogRemovalTests(unittest.TestCase):
    setUp = test_catalog.CatalogTests.setUp
    save = test_catalog.CatalogTests.save
    step = test_catalog.CatalogTests.step
    protocol = test_catalog.CatalogTests.protocol
    def remove(self, collection, identity, actor="Administrator", administrator=True, **overrides):
        return self.store.remove(collection, identity, expected_revision=self.store.read()["revision"],
            actor=actor, administrator=administrator, authorized=overrides.get("authorized", True))

    def populated(self):
        self.save("definitions", self.step())
        self.save("protocols", self.protocol())
        self.save("templates", dict(id="daily", name="Daily", projectId="p", protocol="protocol",
            owner="alice", included=["occurrence"], devices=[]))
        self.save("experimentTemplates", dict(id="experiment", name="Daily", owner="alice",
            operation="acquisition", configuration={"text": " Ω\r\n\0 ", "empty": "", "null": None}))

    def test_normalized_uniqueness_and_self_update(self):
        for name in ["Alice", "ALICE", " alice "]:
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.save("experimenters", dict(id="duplicate", name=name))
        self.save("experimenters", dict(id="alice", name=" ALICE "))
        self.assertEqual(self.store.read()["catalog"]["experimenters"][0]["name"], " ALICE ")
        self.save("animals", dict(id="one", projectId="p", animal_id="M1"))
        self.save("animals", dict(id="two", projectId="q", animal_id=" m1 "))
        with self.assertRaises(ValueError):
            self.save("animals", dict(id="three", projectId="p", animal_id=" m1 "))

    def test_ownership_namespaces_and_permissions(self):
        base = {**self.protocol(), "steps": []}
        self.save("protocols", base)
        self.save("protocols", {**base, "id": "bob-protocol", "owner": "bob"}, "bob")
        self.save("protocols", {**base, "id": "lab", "owner": None, "protected": True})
        with self.assertRaises(ValueError):
            self.save("protocols", {**base, "name": "Changed"}, "bob")
        for identity in ("protocol", "lab"):
            with self.assertRaises(ValueError):
                self.remove("protocols", identity, "bob", False)
        self.remove("protocols", "protocol", "alice", False)
        self.save("protocols", {**base, "id": "replacement"})

    def test_project_removal_is_atomic_and_preserves_nonproject_scopes(self):
        self.populated()
        self.save("animals", dict(id="animal", projectId="p", animal_id="M1"))
        before = self.store.read()["catalog"]
        accepted = deepcopy(before["protocols"][0])
        scientific = self.path.with_name("scientific.bin")
        scientific.write_bytes(b"existing scientific evidence")
        self.remove("projects", "p")
        after = CatalogStore(self.path).read()["catalog"]
        for key in ("animals", "protocols", "templates"):
            self.assertEqual(after[key], [])
        for key in ("definitions", "experimentTemplates", "experimenters"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(accepted, before["protocols"][0])
        self.assertEqual(scientific.read_bytes(), b"existing scientific evidence")

    def test_individual_removal_preserves_values_and_references(self):
        self.populated()
        before = self.store.read()["catalog"]
        self.remove("experimenters", "alice")
        self.remove("definitions", "saved")
        self.remove("protocols", "protocol")
        after = CatalogStore(self.path).read()["catalog"]
        for key in ("projects", "templates", "experimentTemplates"):
            self.assertEqual(after[key], before[key])
        self.save("projects", before["projects"][0], "bob")
        with self.assertRaises(ValueError):
            self.save("projects", {**before["projects"][0], "id": "new-project"}, "bob")

    def test_removed_definition_retains_protocol_occurrence(self):
        self.populated()
        before = self.store.read()["catalog"]["protocols"][0]
        self.remove("definitions", "saved", "alice", False)
        self.assertEqual(self.store.read()["catalog"]["protocols"][0], before)
        self.save("protocols", {**before, "name": "Renamed"})
        with self.assertRaises(ValueError):
            self.save("protocols", {**before, "id": "new"})

    def test_authorization_revision_and_failed_commit(self):
        self.populated()
        before = self.store.read()
        with self.assertRaises(ValueError):
            self.remove("projects", "p", authorized=False)
        with self.assertRaises(CatalogConflict):
            self.store.remove("projects", "p", actor="Admin", administrator=True,
                authorized=True, expected_revision=0)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TRIGGER refuse_remove BEFORE UPDATE ON catalog BEGIN SELECT RAISE(ABORT, 'refused'); END")
        with self.assertRaises(sqlite3.Error):
            self.remove("projects", "p")
        self.assertEqual(self.store.read(), before)

    def test_legacy_duplicates_and_ownerless_protocol_remain_readable(self):
        snapshot = self.store.read()
        legacy = snapshot["catalog"]
        legacy["experimenters"].append(dict(id="duplicate", name=" ALICE "))
        legacy["protocols"].append(dict(id="legacy", projectId="p", name="Old", description="", protected=False, steps=[]))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE catalog SET document=?", (json.dumps(legacy),))
        self.assertEqual(CatalogStore(self.path).read()["catalog"], legacy)
        self.save("experimenters", legacy["experimenters"][0])
        with self.assertRaises(ValueError):
            self.save("protocols", {**legacy["protocols"][0], "owner": "alice"})
        self.save("experimenters", dict(id="duplicate", name="Different"))

    def test_concurrent_normalized_create_then_retry(self):
        revision = self.store.read()["revision"]
        def create(pair):
            identity, name = pair
            try:
                self.store.put("experimenters", dict(id=identity, name=name), actor="alice", expected_revision=revision)
                return identity
            except CatalogConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, [("first", "Nuria"), ("second", " NURIA ")]))
        self.assertEqual(results.count(None), 1)
        with self.assertRaises(ValueError):
            self.save("experimenters", dict(id="third", name="nuria"))

    def test_remaining_name_scopes_and_template_reuse(self):
        self.populated()
        snapshot = self.store.read()["catalog"]
        cases = [("projects", snapshot["projects"][0]), ("definitions", snapshot["definitions"][0]),
                 ("templates", snapshot["templates"][0]), ("experimentTemplates", snapshot["experimentTemplates"][0])]
        for collection, original in cases:
            with self.subTest(collection=collection):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    self.save(collection, {**original, "id": "duplicate", "name": " " + original["name"].upper() + " "})
        template = snapshot["templates"][0]
        self.save("templates", {**template, "id": "bob-template", "owner": "bob"}, "bob")
        self.save("templates", {**template, "id": "lab-template", "owner": None})
        experiment = snapshot["experimentTemplates"][0]
        self.save("experimentTemplates", {**experiment, "id": "other-operation", "operation": "analysis"})
        self.save("experimentTemplates", {**experiment, "id": "bob-experiment", "owner": "bob"}, "bob")
        self.remove("experimentTemplates", "experiment", "alice", False)
        self.save("experimentTemplates", {**experiment, "id": "reused"})
        self.assertEqual(self.store.read()["catalog"]["experimentTemplates"][-1]["configuration"], experiment["configuration"])


class CatalogRemovalHttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_catalog.CatalogHttpTests.asyncSetUp

    async def test_removal_transport_authorization_and_revision(self):
        origin = {"Origin": self.origin}
        create = dict(collection="experimenters", record=dict(id="alice", name="Alice"), actor="alice", expected_revision=0)
        self.assertEqual((await self.web.post("/api/catalog", json=create, headers=origin)).status, 200)
        mutation = dict(collection="experimenters", identity="alice", expected_revision=1,
                        actor="Admin", administrator=True, authorized=False)
        self.assertEqual((await self.web.post("/api/catalog", json=mutation, headers=origin)).status, 400)
        mutation["authorized"] = True
        response = await self.web.post("/api/catalog", json=mutation, headers=origin)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["catalog"]["experimenters"], [])
        self.assertEqual((await self.web.post("/api/catalog", json=mutation, headers=origin)).status, 409)
