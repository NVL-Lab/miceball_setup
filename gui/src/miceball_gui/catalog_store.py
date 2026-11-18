"""GUI-owned reusable catalogs; never an execution or scientific evidence store."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path


COLLECTIONS = ("experimenters", "projects", "animals", "protocols", "templates", "definitions", "experimentTemplates")
FIELDS = {
    "experimenters": {"id", "name"},
    "projects": {"id", "name", "primary_experimenter"},
    "animals": {"id", "projectId", "animal_id", "animal_name", "species", "strain", "sex", "date_of_birth", "notes"},
    "protocols": {"id", "projectId", "name", "description", "protected", "steps"},
    "templates": {"id", "projectId", "protocol", "owner", "name", "description", "included", "devices"},
    "definitions": {"id", "name", "owner", "operation", "description", "mandatory", "required", "optional", "configuration", "type", "recordedInput", "parameters"},
    "experimentTemplates": {"id", "operation", "owner", "name", "configuration"},
}


class CatalogConflict(ValueError):
    """The caller's revision is stale; its draft has not been stored."""


class CatalogStore:
    """One versioned JSON document, committed transactionally in a local SQLite file."""

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        package = Path(__file__).resolve().parent
        if self.path == package or package in self.path.parents:
            raise ValueError("Catalog must reside outside the installed GUI package")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        # Opening an existing corrupt/unsupported file must never initialize over it.
        with self._connection(create=not existed) as connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not tables:
                if existed:
                    raise ValueError("Existing catalog has no supported document; refusing initialization")
                connection.execute("CREATE TABLE catalog (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL)")
                connection.execute("INSERT INTO catalog VALUES (1, 1, 0, ?)",
                                   (json.dumps({key: [] for key in COLLECTIONS}),))
            elif {row[0] for row in tables} != {"catalog"}:
                raise ValueError("Unsupported GUI catalog database")
        self.read()

    @contextmanager
    def _connection(self, *, create=False):
        connection = sqlite3.connect(self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw"), uri=True, timeout=5)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    def _read(self, connection):
        rows = connection.execute("SELECT version, revision, document FROM catalog").fetchall()
        if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] < 0:
            raise ValueError("Unsupported or incomplete GUI catalog")
        document = json.loads(rows[0][2])
        self._validate(document)
        return {"version": 1, "revision": rows[0][1], "catalog": document}

    def read(self):
        """Return an independent committed snapshot; refuse invalid durable state."""
        with self._connection() as connection:
            return self._read(connection)

    def put(self, collection, record, *, expected_revision, actor):
        """Create/update one reusable record with revision and cooperative-owner checks."""
        if collection not in COLLECTIONS or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid catalog collection or revision")
        if not isinstance(record, dict) or not isinstance(actor, str) or not actor:
            raise ValueError("A record and selected Experimenter identity are required")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = self._read(connection)
            if snapshot["revision"] != expected_revision:
                raise CatalogConflict("Catalog changed in another browser. Reload catalog and review your retained draft before saving again.")
            document = snapshot["catalog"]
            old = next((item for item in document[collection] if item["id"] == record.get("id")), None)
            if collection != "experimenters" and actor not in {item["id"] for item in document["experimenters"]}:
                raise ValueError("Select an existing Experimenter")
            if old is not None:
                if collection == "definitions" and old != record:
                    raise ValueError("Saved Steps are immutable; copy to customize")
                if collection == "protocols" and old.get("protected") and old != record:
                    raise ValueError("Laboratory references are immutable")
                if collection in {"templates", "experimentTemplates"} and old != record:
                    if old.get("owner") is None or old["owner"] != actor or record.get("owner") != old["owner"]:
                        raise ValueError("Only the owner can overwrite a personal template; copy references")
                if "projectId" in old and old["projectId"] != record.get("projectId"):
                    raise ValueError("Copy to create an independent record in another project")
            elif collection in {"definitions", "templates", "experimentTemplates"} and record.get("owner") not in {None, actor}:
                raise ValueError("New personal records must belong to the selected Experimenter")
            candidate = deepcopy(record)
            document[collection] = [candidate if item["id"] == candidate.get("id") else item for item in document[collection]]
            if old is None:
                document[collection].append(candidate)
            self._validate(document)
            encoded = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            connection.execute("UPDATE catalog SET revision=?, document=? WHERE singleton=1", (expected_revision + 1, encoded))
            # Reply only after the transaction's durable commit, including commit failures.
            connection.commit()
            return {"version": 1, "revision": expected_revision + 1, "catalog": document}

    def _validate(self, document):
        if not isinstance(document, dict) or set(document) != set(COLLECTIONS):
            raise ValueError("Invalid catalog document")
        indexes = {}
        for key in COLLECTIONS:
            if not isinstance(document[key], list):
                raise ValueError("Invalid catalog collection")
            indexes[key] = {}
            for record in document[key]:
                if not isinstance(record, dict) or set(record) - FIELDS[key]:
                    raise ValueError("Unsupported catalog fields")
                identity = record.get("id")
                if not isinstance(identity, str) or not identity or identity in indexes[key]:
                    raise ValueError("Unique stable record IDs are required")
                name = record.get("animal_id" if key == "animals" else "name")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("A nonempty catalog name is required")
                indexes[key][identity] = record
        for record in document["projects"]:
            if record.get("primary_experimenter") not in indexes["experimenters"]:
                raise ValueError("Project requires an existing Primary Experimenter")
        for key in ("animals", "protocols", "templates"):
            for record in document[key]:
                if record.get("projectId") not in indexes["projects"]:
                    raise ValueError("Project-owned records require an existing project")
        names = set()
        for step in document["definitions"]:
            normalized = step["name"].lower()
            if normalized in names:
                raise ValueError("Saved Step names must be unique across the catalog")
            names.add(normalized)
            self._validate_step(step)
        for key in ("definitions", "templates", "experimentTemplates"):
            for record in document[key]:
                if "owner" not in record or record["owner"] is not None and record["owner"] not in indexes["experimenters"]:
                    raise ValueError("Reusable records require a valid owner or laboratory reference")
        for protocol in document["protocols"]:
            if type(protocol.get("protected")) is not bool or not isinstance(protocol.get("steps"), list):
                raise ValueError("Invalid protocol")
            ids = set()
            for step in protocol["steps"]:
                self._validate_step(step)
                if not isinstance(step.get("id"), str) or not step["id"] or step["id"] in ids:
                    raise ValueError("Unique protocol occurrence IDs are required")
                ids.add(step["id"])
                if "definitionId" in step:
                    definition = indexes["definitions"].get(step["definitionId"])
                    if definition is None or {k: v for k, v in step.items() if k not in {"id", "definitionId"}} != {k: v for k, v in definition.items() if k != "id"}:
                        raise ValueError("Protocol occurrence contradicts its immutable saved Step")
        for template in document["templates"]:
            protocol = indexes["protocols"].get(template.get("protocol"))
            if protocol is None or protocol["projectId"] != template["projectId"]:
                raise ValueError("Session Template and protocol must belong to the same project")
            if not isinstance(template.get("included"), list) or not set(template["included"]) <= {s["id"] for s in protocol["steps"]}:
                raise ValueError("Template includes unknown protocol occurrences")
            if not isinstance(template.get("devices"), list) or not all(isinstance(item, str) for item in template["devices"]):
                raise ValueError("Invalid template device preferences")
        for template in document["experimentTemplates"]:
            if not isinstance(template.get("operation"), str) or not template["operation"] or not isinstance(template.get("configuration"), dict):
                raise ValueError("Invalid reusable Experiment configuration")
        names = set()
        for template in document["experimentTemplates"]:
            identity = (template["operation"], template["owner"], template["name"].lower())
            if identity in names:
                raise ValueError("Template names must be distinct within their owner and operation")
            names.add(identity)
        json.dumps(document, allow_nan=False)

    def _validate_step(self, step):
        if not isinstance(step, dict) or set(step) - (FIELDS["definitions"] | {"definitionId"}):
            raise ValueError("Invalid reusable Step")
        if not isinstance(step.get("name"), str) or not step["name"].strip() or not isinstance(step.get("operation"), str) or not step["operation"] or type(step.get("mandatory")) is not bool:
            raise ValueError("Step requires name, operation and required/optional status")
        for key in ("required", "optional"):
            if not isinstance(step.get(key), list) or not all(isinstance(value, str) and value for value in step[key]) or len(set(step[key])) != len(step[key]):
                raise ValueError("Invalid Step capabilities")
        if set(step["required"]) & set(step["optional"]):
            raise ValueError("Required and optional capabilities overlap")
        if "parameters" in step and not isinstance(step["parameters"], dict):
            raise ValueError("Step parameters must use the existing working configuration object")
        if "parameters" in step:
            configuration = step["parameters"]
            if not isinstance(configuration.get("participants"), list) or not all(isinstance(value, str) for value in configuration["participants"]) or not isinstance(configuration.get("values"), dict):
                raise ValueError("Step parameters require existing participant and typed-value containers")
