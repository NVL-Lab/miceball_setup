"""Deployment-local inputs for the existing explicit-role launchers."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

from lab_sync_acquisition.communication import build_runtime_subject
from lab_sync_acquisition.storage import SshRetrievalEndpoint


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate configuration field: {key}")
        result[key] = value
    return result


def _local_path(directory, value, field):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} requires a nonempty local path")
    return directory / Path(value)


def _identity(value, kind, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} requires an explicit participant identity")
    try:
        build_runtime_subject(None, "command", kind, value, "stop")
    except ValueError as error:
        raise ValueError(f"Invalid {field}: {error}") from error


def load_service_configuration(path, role):
    """Validate one explicitly selected role's JSON settings without connecting or opening hardware."""
    path = Path(path).absolute()
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        return _validate_service_configuration(data, path.parent, role)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError(f"Deployment configuration {path}: {error}") from error


def _validate_service_configuration(data, directory, role):
    pair = role in {"ingestor", "storage-manager"}
    common = {"servers", "ingestor_id", "storage_id", "preservation_window_s"}
    specific = {
        "controller": {"service_id", "synchronization_id", "known_nodes", "result_window_s"},
        "synchronization-manager": {"service_id", "result_window_s"},
        "acquisition-node": {"synchronization_id", "node_config", "result_window_s"},
        "ingestor": {"storage_root", "global_artifact_root", "retrieval_endpoints",
                     "recovery_journal_root", "framework_journal", "no_operational_dependents"},
    }
    specific["storage-manager"] = specific["ingestor"]
    if role not in specific:
        raise ValueError("Configuration requires an explicitly selected service role")
    required = common | specific[role]
    optional = {"service_id"} if role == "acquisition-node" else set()
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    missing, unknown = required - data.keys(), data.keys() - required - optional
    if missing or unknown:
        raise ValueError(f"Missing fields: {sorted(missing)}; unsupported fields: {sorted(unknown)}")
    data = dict(data)
    servers = data["servers"]
    if not isinstance(servers, list) or not servers:
        raise ValueError("servers requires a nonempty list of NATS URLs")
    for server in servers:
        try:
            url = urlsplit(server)
            valid = (isinstance(server, str) and not any(c.isspace() for c in server)
                     and url.scheme in {"nats", "tls", "ws", "wss"} and url.hostname
                     and (url.port is None or 1 <= url.port <= 65535))
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("servers contains an invalid NATS URL")
    data["servers"] = tuple(servers)
    for field in ("preservation_window_s", *(() if pair else ("result_window_s",))):
        value = data[field]
        if (type(value) not in {int, float} or not isfinite(value)
                or value < 0 or (not pair and value == 0)):
            raise ValueError(f"{field} must be finite and {'nonnegative' if pair else 'positive'}")
    for field, kind in (("ingestor_id", "ingestor"), ("storage_id", "storage_manager"),
                        ("service_id", role.replace("-", "_")),
                        ("synchronization_id", "synchronization_manager")):
        if field in data:
            _identity(data[field], kind, field)
    if role == "controller":
        nodes = data["known_nodes"]
        if not isinstance(nodes, list):
            raise ValueError("known_nodes requires an explicit list, including [] when none are registered")
        for node in nodes:
            _identity(node, "acquisition_node", "known_nodes")
        if len(set(nodes)) != len(nodes):
            raise ValueError("known_nodes contains conflicting duplicate node identities")
        data["known_nodes"] = tuple(nodes)
    if role == "acquisition-node":
        data["node_config"] = _local_path(directory, data["node_config"], "node_config")
        from lab_sync_acquisition.service_startup import read_acquisition_node_configuration
        node = read_acquisition_node_configuration(data["node_config"])
        if "service_id" in data and data["service_id"] != node["node_id"]:
            raise ValueError("service_id conflicts with the persistent node_id in node_config")
        data.setdefault("service_id", node["node_id"])
    if pair:
        if data.pop("no_operational_dependents") is not True:
            raise ValueError("This file launch path requires explicit no_operational_dependents=true; "
                             "actual dependents require the existing configured maintenance callbacks")
        for field in ("storage_root", "global_artifact_root", "recovery_journal_root", "framework_journal"):
            data[field] = _local_path(directory, data[field], field)
            if data[field].exists() and (data[field].is_dir() if field == "framework_journal" else not data[field].is_dir()):
                raise ValueError(f"{field} has the wrong local file/directory type")
        endpoints = data["retrieval_endpoints"]
        if not isinstance(endpoints, dict):
            raise ValueError("retrieval_endpoints requires an explicit node-to-endpoint object")
        parsed = {}
        for node_id, endpoint in endpoints.items():
            _identity(node_id, "acquisition_node", "retrieval_endpoints node")
            if (not isinstance(endpoint, dict) or not {"host", "username", "key_filename"} <= endpoint.keys()
                    or endpoint.keys() - {"host", "username", "port", "key_filename", "known_hosts_path"}):
                raise ValueError("Retrieval endpoints require host, username and key_filename; only port and known_hosts_path are optional")
            if any(not isinstance(endpoint[k], str) or not endpoint[k].strip() for k in ("host", "username")):
                raise ValueError("Retrieval host and username must be nonempty strings")
            port = endpoint.get("port", 22)
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Retrieval port must be an integer in 1..65535")
            endpoint = dict(endpoint)
            for field in ("key_filename", "known_hosts_path"):
                if field in endpoint:
                    reference = _local_path(directory, endpoint[field], f"retrieval {field}")
                    if not reference.is_file():
                        raise ValueError(f"Retrieval {field} must reference an existing local file")
                    endpoint[field] = str(reference)
            parsed[node_id] = SshRetrievalEndpoint(**endpoint)
        data["retrieval_endpoints"] = parsed
        data["operational_dependents"] = {}
    return data
