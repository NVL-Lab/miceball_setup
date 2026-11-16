"""Exact NATS credential validation shared by bootstrap and runtime clients."""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit


UNSET = object()
AUTH_FIELDS = ("nats_username", "nats_password")


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration field")
        result[key] = value
    return result


def nats_connect_options(servers, *, nats_username=UNSET, nats_password=UNSET):
    """Validate every endpoint and return SDK options without transforming credentials."""
    if not isinstance(servers, (list, tuple)) or not servers:
        raise ValueError("NATS servers require a nonempty URL list")
    explicit = nats_username is not UNSET or nats_password is not UNSET
    if explicit and any(not isinstance(v, str) or not v for v in (nats_username, nats_password)):
        raise ValueError("NATS authentication requires both nonempty string fields")
    invalid = False
    mixed = False
    for server in servers:
        try:
            url = urlsplit(server)
            if (not isinstance(server, str) or any(c.isspace() for c in server)
                    or url.scheme not in {"nats", "tls", "ws", "wss"} or not url.hostname
                    or (url.port is not None and not 1 <= url.port <= 65535)):
                invalid = True
            if explicit and (url.username is not None or url.password is not None):
                mixed = True
        except (ValueError, TypeError, AttributeError):
            invalid = True
    if invalid:
        raise ValueError("Invalid NATS server URL")
    if mixed:
        raise ValueError("Explicit NATS credentials cannot be combined with URL userinfo")
    options = {"servers": list(servers)}
    if explicit:
        options.update(user=nats_username, password=nats_password)
    return options


def load_nats_configuration(path):
    """Read connection fields from an existing deployment JSON without exposing values."""
    failed = False
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
        if not isinstance(data, dict):
            raise ValueError()
        settings = {key: data[key] for key in ("servers", *AUTH_FIELDS) if key in data}
        nats_connect_options(settings.get("servers"), **{k: settings[k] for k in AUTH_FIELDS if k in settings})
    except (OSError, ValueError, TypeError):
        failed = True
    if failed:
        raise ValueError("Invalid NATS connection configuration")
    return settings


async def report_nats_error(error):
    """Keep SDK asynchronous errors observable without logging secrets or tracebacks."""
    logging.getLogger("lab_sync_acquisition.deployment").warning(
        "NATS transport error (%s)", type(error).__name__)
