"""GUI-owned catalogs and installation defaults; never scientific execution state."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from lab_sync_acquisition import SynchronizationConfiguration


# Approved initialization values, not scientifically validated tolerances.
INITIAL_SYNCHRONIZATION_CONFIGURATION = SynchronizationConfiguration(
    exchanges=3, initial_scale=1.0, clock_rate_error_bound=0.001,
    max_uncertainty_s=0.5, max_mapping_age_s=20.0, assessment_interval_s=5.0,
    result_window_s=2.0, quality_interpretation="warning")


COLLECTIONS = ("experimenters", "projects", "animals", "protocols", "templates", "definitions", "experimentTemplates")
FIELDS = {
    "experimenters": {"id", "name"},
    "projects": {"id", "name", "primary_experimenter"},
    "animals": {"id", "projectId", "animal_id", "animal_name", "species", "strain", "sex", "date_of_birth", "notes"},
    "protocols": {"id", "projectId", "owner", "name", "description", "protected", "steps"},
    "templates": {"id", "projectId", "protocol", "owner", "name", "description", "included", "devices"},
    "definitions": {"id", "name", "owner", "operation", "description", "mandatory", "required", "optional", "configuration", "type", "recordedInput", "parameters"},
    "experimentTemplates": {"id", "operation", "owner", "name", "configuration"},
}


class CatalogConflict(ValueError):
    """The caller's revision is stale; its draft has not been stored."""


class CatalogStore:
    """One versioned JSON document, committed transactionally in a local SQLite file."""

    def __init__(self, path, *, initial_synchronization=None):
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
            # Validate the old document before migrating; never initialize over corruption.
            rows = connection.execute("SELECT version, revision, document FROM catalog").fetchall()
            if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int or rows[0][1] < 0:
                raise ValueError("Unsupported or incomplete GUI catalog")
            self._validate(json.loads(rows[0][2]))
            columns = {row[1] for row in connection.execute("PRAGMA table_info(catalog)")}
            if "synchronization_configuration" not in columns:
                connection.execute("ALTER TABLE catalog ADD COLUMN synchronization_configuration TEXT")
            saved = connection.execute("SELECT synchronization_configuration FROM catalog").fetchone()[0]
            if saved is None:
                configuration = (INITIAL_SYNCHRONIZATION_CONFIGURATION if initial_synchronization is None
                                 else SynchronizationConfiguration.from_dict(initial_synchronization)).to_dict()
                connection.execute("UPDATE catalog SET synchronization_configuration=?, revision=revision+?",
                                   (json.dumps(configuration, allow_nan=False), int(existed)))
            else:
                SynchronizationConfiguration.from_dict(json.loads(saved))
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
        saved = connection.execute("SELECT synchronization_configuration FROM catalog").fetchone()[0]
        configuration = SynchronizationConfiguration.from_dict(json.loads(saved)).to_dict()
        return {"version": 1, "revision": rows[0][1], "catalog": document,
                "synchronization_configuration": configuration}

    def put_synchronization(self, configuration, *, expected_revision, administrator_id, authorized):
        """Commit complete installation defaults under explicit cooperative authorization."""
        if (authorized is not True or not isinstance(administrator_id, str) or not administrator_id.strip()
                or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("Administrator authorization and a valid revision are required")
        validated = SynchronizationConfiguration.from_dict(configuration).to_dict()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = self._read(connection)
            if snapshot["revision"] != expected_revision:
                raise CatalogConflict("Settings changed. Your draft is retained; reload and review before saving.")
            connection.execute("UPDATE catalog SET synchronization_configuration=?, revision=?",
                               (json.dumps(validated, allow_nan=False), expected_revision + 1))
            result = self._read(connection)
            connection.commit()
            return result

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
                if collection in {"protocols", "templates", "experimentTemplates"} and old != record:
                    if old.get("owner") is None or old["owner"] != actor or record.get("owner") != old["owner"]:
                        raise ValueError("Only the owner can overwrite a personal template; copy references")
                if "projectId" in old and old["projectId"] != record.get("projectId"):
                    raise ValueError("Copy to create an independent record in another project")
            elif collection in {"definitions", "templates", "experimentTemplates"} and record.get("owner") not in {None, actor}:
                raise ValueError("New personal records must belong to the selected Experimenter")
            candidate = deepcopy(record)
            self._validate_mutation(document, collection, candidate, old, actor)
            document[collection] = [candidate if item["id"] == candidate.get("id") else item for item in document[collection]]
            if old is None:
                document[collection].append(candidate)
            self._validate(document)
            encoded = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            connection.execute("UPDATE catalog SET revision=?, document=? WHERE singleton=1", (expected_revision + 1, encoded))
            # Reply only after the transaction's durable commit, including commit failures.
            result = self._read(connection)
            connection.commit()
            return result

    def remove(self, collection, identity, *, expected_revision, actor, administrator=False, authorized=False):
        """Remove an exact catalog entry, atomically including project-local dependents."""
        if collection not in COLLECTIONS or not isinstance(identity, str) or not identity or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid catalog target or revision")
        if authorized is not True or not isinstance(actor, str) or not actor or type(administrator) is not bool:
            raise ValueError("Explicit removal authorization and identity are required")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = self._read(connection)
            if snapshot["revision"] != expected_revision:
                raise CatalogConflict("Catalog changed. Review the target and confirm removal again.")
            document = snapshot["catalog"]
            target = next((item for item in document[collection] if item["id"] == identity), None)
            if target is None:
                raise ValueError("Catalog entry is no longer available")
            if not administrator and (collection not in {"protocols", "definitions", "templates", "experimentTemplates"}
                    or actor not in {item["id"] for item in document["experimenters"]}
                    or target.get("owner") != actor or target.get("protected")):
                raise ValueError("Only the owner can remove a personal reusable entry")
            document[collection] = [item for item in document[collection] if item["id"] != identity]
            if collection == "projects":
                for key in ("animals", "protocols", "templates"):
                    document[key] = [item for item in document[key] if item["projectId"] != identity]
            self._validate(document)
            encoded = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
            connection.execute("UPDATE catalog SET revision=?, document=? WHERE singleton=1", (expected_revision + 1, encoded))
            result = self._read(connection)
            connection.commit()
            return result

    def _name_key(self, collection, record):
        name = record.get("animal_id" if collection == "animals" else "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("A nonempty catalog name is required")
        scope = ()
        if collection == "animals":
            scope = (record.get("projectId"),)
        elif collection in {"protocols", "templates"}:
            scope = (record.get("projectId"), record.get("owner", "legacy:" + record.get("id", "")))
        elif collection == "experimentTemplates":
            scope = (record.get("operation"), record.get("owner"))
        return (*scope, name.strip().casefold())

    def _validate_mutation(self, document, collection, record, old, actor):
        key = self._name_key(collection, record)
        if old is None or self._name_key(collection, old) != key:
            if any(item["id"] != record.get("id") and self._name_key(collection, item) == key for item in document[collection]):
                raise ValueError("Catalog name already exists in this scope")
        indexes = {key: {item["id"]: item for item in values} for key, values in document.items()}
        def reference(field, target):
            value = record.get(field)
            if old is None or old.get(field) != value:
                if value not in indexes[target]:
                    raise ValueError("Select an existing catalog reference")
        if collection == "projects":
            reference("primary_experimenter", "experimenters")
        if collection in {"animals", "protocols", "templates"}:
            reference("projectId", "projects")
        if collection in {"protocols", "definitions", "templates", "experimentTemplates"}:
            if collection == "protocols" and old is None and "owner" not in record:
                raise ValueError("New protocols require an explicit owner")
            if record.get("owner") is not None:
                reference("owner", "experimenters")
                if old is None and record["owner"] != actor:
                    raise ValueError("New personal records must belong to the selected Experimenter")
            if collection == "protocols" and "owner" in record and record.get("protected") != (record.get("owner") is None):
                raise ValueError("Laboratory protocols are protected; personal protocols identify their owner")
        if collection == "templates":
            reference("protocol", "protocols")
        if collection == "protocols":
            prior = {step["id"]: step for step in old.get("steps", [])} if old else {}
            for step in record.get("steps", []):
                if "definitionId" in step and step["definitionId"] not in indexes["definitions"] and prior.get(step.get("id")) != step:
                    raise ValueError("Select an existing saved Step or copy to edit")

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
            if not isinstance(record.get("primary_experimenter"), str) or not record["primary_experimenter"]:
                raise ValueError("Project requires a Primary Experimenter identity")
        for key in ("animals", "protocols", "templates"):
            for record in document[key]:
                if record.get("projectId") not in indexes["projects"]:
                    raise ValueError("Project-owned records require an existing project")
        for step in document["definitions"]:
            self._validate_step(step)
        for key in ("definitions", "templates", "experimentTemplates"):
            for record in document[key]:
                if "owner" not in record or record["owner"] is not None and (not isinstance(record["owner"], str) or not record["owner"]):
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
                    if definition is not None and {k: v for k, v in step.items() if k not in {"id", "definitionId"}} != {k: v for k, v in definition.items() if k != "id"}:
                        raise ValueError("Protocol occurrence contradicts its immutable saved Step")
        for template in document["templates"]:
            protocol = indexes["protocols"].get(template.get("protocol"))
            if not isinstance(template.get("protocol"), str) or protocol is not None and protocol["projectId"] != template["projectId"]:
                raise ValueError("Session Template and protocol must belong to the same project")
            if not isinstance(template.get("included"), list) or protocol is not None and not set(template["included"]) <= {s["id"] for s in protocol["steps"]}:
                raise ValueError("Template includes unknown protocol occurrences")
            if not isinstance(template.get("devices"), list) or not all(isinstance(item, str) for item in template["devices"]):
                raise ValueError("Invalid template device preferences")
        for template in document["experimentTemplates"]:
            if not isinstance(template.get("operation"), str) or not template["operation"] or not isinstance(template.get("configuration"), dict):
                raise ValueError("Invalid reusable Experiment configuration")
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
