"""Prepare an existing checkout for the common service CLI; never start owners."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile


FILES = {
    "controller": "controller.json",
    "acquisition-node": "acquisition-node-service.json",
    "synchronization-manager": "synchronization-manager.json",
    "ingestor": "storage-services.json",
}
AUTHORITY_FIELDS = ("controller_claim_account", "controller_claim_bucket", "controller_claim_key")
ENVIRONMENT_REPORT = (
    "import importlib.metadata as m,json,sys; "
    "v=next((d.version for d in m.distributions() if d.metadata.get('Name')=='lab-sync-acquisition'),None); "
    "print(json.dumps({'version':list(sys.version_info[:2]),"
    "'prefix':sys.prefix,'base_prefix':sys.base_prefix,'package_version':v}))"
)
VALIDATE = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
source = Path(sys.argv[1]) / 'lab_sync_acquisition' / 'deployment_configuration.py'
if not source.is_file():
    raise RuntimeError('Selected checkout configuration loader is missing')
try:
    from lab_sync_acquisition import deployment_configuration
except ModuleNotFoundError as error:
    if error.name == 'lab_sync_acquisition' or error.name.startswith('lab_sync_acquisition.'):
        raise
    print('DEPENDENCIES_UNAVAILABLE')
else:
    if Path(deployment_configuration.__file__).resolve() != source.resolve():
        raise RuntimeError('Configuration loader does not belong to the selected checkout')
    deployment_configuration.load_service_configuration(sys.argv[2], sys.argv[3])
"""
CONNECT = """
import asyncio,json,sys
from nats.aio.client import Client
async def check():
    settings = json.load(sys.stdin)
    servers, window = settings['servers'], settings['timeout_s']
    if not isinstance(servers, list) or not servers or any(not isinstance(s, str) or not s.strip() for s in servers):
        raise ValueError('Explicit nonempty NATS server URLs are required')
    client = Client()
    try:
        await asyncio.wait_for(client.connect(servers=servers, allow_reconnect=False), window)
    finally:
        try:
            if client.is_connected:
                await asyncio.wait_for(client.drain(), window)
        finally:
            await asyncio.wait_for(client.close(), window)
asyncio.run(check())
"""


def _run(arguments, *, timeout=60, input=None):
    """Run an accountable child without a shell or leaking private connection inputs."""
    result = subprocess.run([str(a) for a in arguments], capture_output=True,
                            text=True, timeout=timeout, check=False, input=input)
    if result.returncode:
        raise RuntimeError(f"Setup child failed (exit {result.returncode}); no rollback is claimed")
    return result.stdout


def _ask(label, default=None, *, allow_empty=False):
    value = input(f"{label}" + (f" (press Enter for default: {default})" if default is not None else "") + ": ").strip()
    value = value or (str(default) if default is not None else "")
    if not value and not allow_empty:
        raise ValueError(f"{label} is required")
    return value


def _confirm(label):
    return input(label + " [yes/no]: ").strip().lower() == "yes"


def _comma(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def _inspect_environment(python, environment):
    report = json.loads(_run([python, "-I", "-B", "-c", ENVIRONMENT_REPORT]))
    if (report["version"] != [3, 12] or Path(report["prefix"]).resolve() != environment.resolve()
            or report["prefix"] == report["base_prefix"]):
        raise RuntimeError("Target .venv is not an isolated Python 3.12 environment; resolve manually")
    return report


def _configuration_plan(roles, directory, existing):
    """Collect only installation values; existing configurations are never edited."""
    values = {}
    for role, (_, data) in existing.items():
        fields = dict(data)
        if role == "controller":
            fields["controller_id"] = data.get("service_id")
        if role == "synchronization-manager":
            fields["synchronization_id"] = data.get("service_id")
        for key in ("servers", "ingestor_id", "storage_id", "synchronization_id", "controller_id", *AUTHORITY_FIELDS):
            if key in fields:
                if key in values and values[key] != fields[key]:
                    raise ValueError(f"Existing configurations disagree on {key}; resolve explicitly")
                values[key] = fields[key]
    pending = [role for role in roles if role not in existing]
    print("External NATS is required for service operation, not software installation. "
          "Supply the deployment URL and runtime-compatible URL authentication; connectivity is verified separately.")
    for key, label, default in (("servers", "NATS URLs, comma-separated (external broker)", None),
                               ("ingestor_id", "Deployment Ingestor ID", "ingestor-1"),
                               ("storage_id", "Deployment StorageManager ID", "storage-manager-1")):
        if key not in values:
            answer = _ask(label, default)
            values[key] = _comma(answer) if key == "servers" else answer
    if any(key not in values for key in AUTHORITY_FIELDS):
        print("Ask the NATS administrator for the actual account ID reported by $SYS.REQ.USER.INFO, "
              "the existing persistent non-expiring KV bucket name (not its KV_ stream prefix), "
              "and the shared installation claim key. These are not credentials or per-computer values. "
              "The installer will not create or change them; the minimal connection check does not verify them.")
    for key, label in (("controller_claim_account", "Controller authority account (actual NATS account ID)"),
                       ("controller_claim_bucket", "Controller authority bucket (existing persistent KV bucket)"),
                       ("controller_claim_key", "Controller authority key (shared installation claim)")):
        if key not in values:
            values[key] = _ask(label)
    windows = {}
    if pending:
        for key, label in (("preservation_window_s", "Preservation window, seconds"),
                           ("result_window_s", "Request/check window, seconds")):
            previous = {data[key] for _, data in existing.values() if key in data}
            windows[key] = (previous.pop() if len(previous) == 1 else float(_ask(label)))
    generated, deferred = {}, []
    for role in pending:
        data = {key: values[key] for key in ("servers", "ingestor_id", "storage_id", *AUTHORITY_FIELDS)}
        data["preservation_window_s"] = windows["preservation_window_s"]
        data["result_window_s"] = windows["result_window_s"]
        if role in {"controller", "acquisition-node", "synchronization-manager"}:
            if "synchronization_id" not in values:
                values["synchronization_id"] = _ask("Deployment SynchronizationManager ID", "synchronization-manager-1")
            if role != "synchronization-manager":
                data["synchronization_id"] = values["synchronization_id"]
        if role == "controller":
            data["service_id"] = values.get("controller_id") or _ask("Controller ID", "controller-1")
            data["known_nodes"] = _comma(_ask("Known AcquisitionNode IDs, comma-separated; empty for none",
                                              allow_empty=True))
        elif role == "synchronization-manager":
            data["service_id"] = values["synchronization_id"]
        elif role == "acquisition-node":
            hardware = _ask("Existing node hardware JSON path; empty to defer node setup", allow_empty=True)
            if not hardware or not Path(hardware).expanduser().is_file():
                deferred.append("AcquisitionNode incomplete: provide an existing valid hardware JSON; no declarations invented")
                continue
            data["node_config"] = str(Path(hardware).expanduser().resolve())
        else:
            base = Path(_ask("Storage data directory", directory / "data")).expanduser().resolve()
            data.update(storage_root=str(base / "records"), global_artifact_root=str(base / "artifacts"),
                        recovery_journal_root=str(base / "journals"), framework_journal=str(base / "framework.jsonl"))
            dependents = _ask("Actual external dependents TYPE/ID, comma-separated; type none only if isolated")
            if dependents == "none":
                data["no_operational_dependents"] = True
            else:
                data["external_dependents"] = [dict(zip(("component_type", "component_id"), item.split("/", 1), strict=True))
                                                for item in _comma(dependents)]
            endpoints = {}
            for identity in _comma(_ask("Retrieval node IDs, comma-separated; empty for none", allow_empty=True)):
                if identity in endpoints:
                    raise ValueError("Duplicate retrieval node")
                endpoints[identity] = {
                    "host": _ask(f"{identity} SSH host"), "username": _ask(f"{identity} SSH username"),
                    "key_filename": str(Path(_ask(f"{identity} existing SSH private-key path")).expanduser().resolve()),
                    "port": int(_ask(f"{identity} SSH port", 22)),
                }
                hosts = _ask(f"{identity} existing known-hosts path; empty for system host keys", allow_empty=True)
                if hosts:
                    endpoints[identity]["known_hosts_path"] = str(Path(hosts).expanduser().resolve())
            data["retrieval_endpoints"] = endpoints
        generated[role] = data
    combined = {role: data for role, (_, data) in existing.items()} | generated
    storage = combined.get("ingestor")
    if storage:
        required = set()
        for role, data in combined.items():
            if role == "ingestor":
                continue
            if role == "acquisition-node":
                hardware = Path(data["node_config"])
                if not hardware.is_absolute():
                    hardware = directory / hardware
                identity = json.loads(hardware.read_text(encoding="utf-8"))["node_id"]
            else:
                identity = data["service_id"]
            required.add((role.replace("-", "_"), identity))
        declared = {(p["component_type"], p["component_id"]) for p in storage.get("external_dependents", [])}
        if not required <= declared:
            raise ValueError("Storage dependency declaration omits local owners; resolve actual identities before setup")
    return generated, deferred


def _validate(python, checkout, path, role, *, allow_unavailable=False):
    """Use the selected checkout's loader; defer only missing import dependencies in preflight."""
    try:
        result = _run([python, "-I", "-B", "-c", VALIDATE, checkout / "src", path, role])
    except RuntimeError as error:
        raise ValueError(f"Configuration validation failed for {role}: {path}; resolve using the existing loader") from error
    if result.strip() == "DEPENDENCIES_UNAVAILABLE":
        if allow_unavailable:
            return False
        raise RuntimeError("Configuration loader dependencies unavailable after installation; setup is blocked")
    return True


def _publish(path, contents):
    """Exclusively create one validated config; remove our incomplete write on error."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    complete = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        complete = True
    finally:
        if not complete:
            path.unlink()


def main(argv=None):
    """Interactively prepare one checkout/environment and print existing launch commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config-dir", type=Path, help="Deployment-local directory outside the checkout")
    args = parser.parse_args(argv)
    installation_started = False
    try:
        if sys.version_info[:2] != (3, 12) or sys.platform not in {"win32", "linux"}:
            raise RuntimeError("Use Python 3.12 on Windows or Linux; no OS/Python provisioning is performed")
        import tomllib
        checkout = args.checkout.expanduser().resolve()
        metadata = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))
        if metadata["project"]["name"] != "lab-sync-acquisition":
            raise ValueError("Selected checkout is not lab-sync-acquisition")
        if Path(_run(["git", "-C", checkout, "rev-parse", "--show-toplevel"]).strip()).resolve() != checkout:
            raise ValueError("Select the repository root checkout")
        revision = _run(["git", "-C", checkout, "rev-parse", "HEAD"]).strip()
        dirty = bool(_run(["git", "-C", checkout, "status", "--porcelain"]).strip())
        environment = checkout / ".venv"
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if environment.exists():
            if environment.is_symlink() or not python.is_file():
                raise RuntimeError("Existing .venv is incomplete or linked; resolve manually, it will not be replaced")
            installed = _inspect_environment(python, environment)
            print("Existing package version: " + str(installed.get("package_version") or "not installed"))
        preflight_python = python if environment.exists() else Path(sys.executable)
        try:
            _run([preflight_python, "-I", "-B", "-c", "import nats"])
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"nats-py is required in the pre-install verification interpreter: {preflight_python}. "
                               "Provide nats-py>=2.15,<3 there explicitly, then rerun. "
                               "The installer will not install this prerequisite or create a verification environment.") from error
        print(f"COMPLETED: nats import in {preflight_python}; broker connectivity is not yet verified")
        directory = (args.config_dir or Path(_ask("Configuration directory outside Git",
                     Path.home() / ".config" / "lab-sync-acquisition"))).expanduser().resolve()
        if directory.is_relative_to(checkout):
            raise ValueError("Configuration must stay outside the repository")
        existing = {}
        for role, filename in FILES.items():
            path = directory / filename
            if path.exists():
                contents = path.read_bytes()
                data = json.loads(contents)
                if not isinstance(data, dict):
                    raise ValueError(f"Existing {filename} is not a configuration object")
                existing[role] = (contents, data)
        choices = _ask("Local roles: controller acquisition-node synchronization-manager ingestor storage-manager",
                       " ".join(existing) or None).replace(",", " ").split()
        if not choices or set(choices) - (set(FILES) | {"storage-manager"}):
            raise ValueError("Select existing framework role names")
        roles = tuple(dict.fromkeys("ingestor" if r == "storage-manager" else r for r in choices))
        generated, deferred = _configuration_plan(roles, directory, existing)
        configured = {role: (existing[role][1] if role in existing else generated[role])
                      for role in roles if role in existing or role in generated}
        if not configured:
            for message in deferred:
                print("DEFERRED: " + message)
            print("DEFERRED: no complete selected role configuration; no installation changes made")
            return 2
        staged = []
        with tempfile.TemporaryDirectory(prefix="lab-sync-setup-") as staging:
            for role, data in generated.items():
                contents = json.dumps(data, indent=2) + "\n"
                # Generated references are absolute; existing files retain their original base directory.
                path = Path(staging) / FILES[role]
                path.write_text(contents, encoding="utf-8")
                staged.append((role, path, contents))
            for role, path in ([(role, path) for role, path, _ in staged]
                               + [(role, directory / FILES[role]) for role in existing]):
                validated = _validate(preflight_python, checkout, path, role, allow_unavailable=True)
                if not validated and str(preflight_python) != sys.executable:
                    validated = _validate(sys.executable, checkout, path, role, allow_unavailable=True)
                if not validated:
                    print("DEFERRED: Pre-install configuration validation deferred: loader dependencies unavailable; "
                          "full validation is required after dependency installation")
            # The configuration plan already requires identical server lists across local roles.
            settings = next(iter(configured.values()))
            window = settings["result_window_s"]
            if type(window) not in (int, float) or not math.isfinite(window) or window <= 0:
                raise ValueError("NATS connectivity timeout must be positive and finite")
            try:
                _run([preflight_python, "-I", "-B", "-c", CONNECT], timeout=3 * window + 5,
                     input=json.dumps({"servers": settings["servers"], "timeout_s": window}))
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                message = ("NATS connectivity PENDING / NOT VERIFIED: connection/cleanup unconfirmed. "
                           "Installation may proceed; verify the external broker, URLs, firewall, authentication "
                           "and TLS before service operation.")
                deferred.append(message)
                print(message)
            else:
                print("COMPLETED: NATS connection and cleanup confirmed; not JetStream/authority/permission/service/scientific readiness")
            print(f"Plan: {sys.platform}/{platform.machine()}, checkout {checkout}, revision {revision}")
            print(f"Environment: {'reuse/update' if environment.exists() else 'create'} {environment}")
            print(f"Configuration: {directory}; preserve {len(existing)} existing files; create {list(generated)}")
            print("Local roles: " + ", ".join(roles) + "; Ingestor/StorageManager share one process")
            if dirty:
                print("WARNING: checkout has local changes; installation includes those changes, without resetting Git")
            print("No services, Controller, cameras or broker will be started. NATS remains external.")
            if existing or environment.exists():
                if not _confirm("All services using this installation are confirmed retired with obligations resolved (not merely unreachable)"):
                    raise RuntimeError("Resolve service retirement before updating this installation")
            if not _confirm("Install the displayed local checkout and dependencies, preserving existing configuration/data"):
                print("DEFERRED: setup declined; no changes made")
                return 2
            installation_started = True
            directory.mkdir(parents=True, exist_ok=True)
            if not environment.exists():
                _run([sys.executable, "-I", "-m", "venv", environment], timeout=120)
            # A newly created environment must pass the same isolation check before pip.
            _inspect_environment(python, environment)
            package = str(checkout) + ("[artifact-retrieval]" if "ingestor" in roles or "ingestor" in existing else "")
            print("Installing selected checkout in .venv, then checking declared dependencies...")
            _run([python, "-I", "-m", "pip", "install", package], timeout=900)
            _run([python, "-I", "-m", "pip", "check"])
            for role, path, _ in staged:
                _validate(python, checkout, path, role)
            for role, (contents, _) in existing.items():
                path = directory / FILES[role]
                if path.read_bytes() != contents:
                    raise RuntimeError("Existing configuration changed during setup; rerun explicitly")
                _validate(python, checkout, path, role)
            for role, data in generated.items():
                if role == "ingestor":
                    for key in ("storage_root", "global_artifact_root", "recovery_journal_root"):
                        Path(data[key]).mkdir(parents=True, exist_ok=True)
                    Path(data["framework_journal"]).parent.mkdir(parents=True, exist_ok=True)
                if role == "acquisition-node":
                    hardware = Path(data["node_config"])
                    settings = json.loads(hardware.read_text(encoding="utf-8"))
                    for key in ("local_storage_root", "error_evidence_location"):
                        (hardware.parent / settings[key]).mkdir(parents=True, exist_ok=True)
            for role, _, contents in staged:
                _publish(directory / FILES[role], contents)
        print("COMPLETED: isolated package installation, dependency check and configuration validation")
        print("Software installation is not operational readiness; resolve pending connectivity and "
              "existing service-readiness/Controller-authority requirements before operation.")
        for message in deferred:
            print("DEFERRED: " + message)
        for role in configured:
            command = [str(python), "-m", "lab_sync_acquisition.service_launcher", role,
                       "--deployment-config", str(directory / FILES[role])]
            rendered = ("& " + " ".join("'" + part.replace("'", "''") + "'" for part in command)
                        if sys.platform == "win32" else shlex.join(command))
            print("LAUNCH: " + rendered)
        print("Setup exits without launching services; run the printed commands only after resolving reported prerequisites")
        return 2 if deferred else 0
    except (Exception, KeyboardInterrupt) as error:
        cancelled = isinstance(error, KeyboardInterrupt)
        print("CANCELLED: setup interrupted by operator" if cancelled else f"BLOCKED: {type(error).__name__}: {error}", file=sys.stderr)
        if installation_started:
            print("WARNING: environment/directories may be partially changed and complete new configs may remain; no package rollback is claimed. Existing data is not deleted.", file=sys.stderr)
        else:
            print("No installation changes made to the framework environment, configuration or scientific-data directories.", file=sys.stderr)
        return 130 if cancelled else 1


if __name__ == "__main__":
    raise SystemExit(main())
