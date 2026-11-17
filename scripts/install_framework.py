"""Prepare an existing checkout for the common service CLI; never start owners."""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile
import runpy
import warnings
from urllib.parse import urlsplit, urlunsplit


_NATS_HELPER_PATH = Path(__file__).resolve().parents[1] / "src" / "lab_sync_acquisition" / "nats_configuration.py"
_NATS_HELPERS = runpy.run_path(str(_NATS_HELPER_PATH))


FILES = {
    "controller": "controller.json",
    "acquisition-node": "acquisition-node-service.json",
    "synchronization-manager": "synchronization-manager.json",
    "ingestor": "storage-services.json",
}
AUTHORITY_FIELDS = ("controller_claim_account", "controller_claim_bucket", "controller_claim_key")
SHARED_FIELDS = ("ingestor_id", "storage_id", "synchronization_id", "controller_id", *AUTHORITY_FIELDS,
                 "preservation_window_s", "result_window_s", "registration_window_s", "known_nodes", "external_dependents")
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
CONNECT = "import runpy\nhelpers = runpy.run_path(" + repr(str(_NATS_HELPER_PATH)) + ")\n" + """
import asyncio,json,sys
from nats.aio.client import Client
async def check():
    settings = json.load(sys.stdin)
    window = settings['timeout_s']
    options = helpers['nats_connect_options'](settings['servers'], **{
        k: settings[k] for k in helpers['AUTH_FIELDS'] if k in settings})
    client = Client()
    failure = None
    account = None
    try:
        await asyncio.wait_for(client.connect(**options, allow_reconnect=False,
            error_cb=helpers['report_nats_error']), window)
        if settings.get('discover_account'):
            try:
                reply = await client.request('$SYS.REQ.USER.INFO', b'', timeout=window)
                identity = json.loads(reply.data)
                observed = identity.get('data', {}).get('account')
                if not identity.get('error') and isinstance(observed, str) and observed.strip():
                    account = observed
            except Exception:
                pass
    except Exception:
        failure = RuntimeError('NATS connection unconfirmed')
    finally:
        try:
            if client.is_connected:
                await asyncio.wait_for(client.drain(), window)
        except Exception:
            failure = RuntimeError('NATS drain unconfirmed')
        finally:
            try:
                await asyncio.wait_for(client.close(), window)
            except Exception:
                failure = RuntimeError('NATS cleanup unconfirmed')
    if failure is not None:
        raise failure
    print(json.dumps({'account': account}))
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


def _hidden_input(label):
    """Read connection inputs without echo or value transformation; never fall back to echo."""
    failed = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(label + ": ")
    except getpass.GetPassWarning:
        failed = True
    if failed:
        raise ValueError("Non-echoing NATS input is unavailable")
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


def _endpoint(server, *, include_route=False):
    """Identify credential-free endpoints; hide routing details in visible labels."""
    url = urlsplit(server)
    host = url.hostname
    if ':' in host:
        host = '[' + host + ']'
    port = url.port or {'nats': 4222, 'tls': 4222, 'ws': 80, 'wss': 443}[url.scheme]
    return urlunsplit((url.scheme, f'{host}:{port}',
                      url.path if include_route and url.path != '/' else '', url.query if include_route else '',
                      url.fragment if include_route else ''))


def _read_shared_configuration(path, *, contents=None):
    """Extract shared declarations from an explicitly selected file, excluding foreign credentials and paths."""
    failed = False
    try:
        data = json.loads(path.read_bytes() if contents is None else contents,
                          object_pairs_hook=_NATS_HELPERS['_unique_fields'])
        if not isinstance(data, dict):
            raise ValueError()
        _NATS_HELPERS['nats_connect_options'](data['servers'], **{
            k: data[k] for k in _NATS_HELPERS['AUTH_FIELDS'] if k in data})
        shared = {k: data[k] for k in SHARED_FIELDS if k in data}
        for field in ('ingestor_id', 'storage_id', *AUTHORITY_FIELDS):
            if not isinstance(shared.get(field), str) or not shared[field].strip():
                raise ValueError()
        if 'known_nodes' in data and 'service_id' in data:
            if 'controller_id' in shared and shared['controller_id'] != data['service_id']:
                raise ValueError()
            shared['controller_id'] = data['service_id']
        elif 'service_id' in data and not any(k in data for k in ('storage_root', 'node_config')):
            if 'synchronization_id' in shared and shared['synchronization_id'] != data['service_id']:
                raise ValueError()
            shared['synchronization_id'] = data['service_id']
        for field in ('controller_id', 'synchronization_id'):
            if field in shared and (not isinstance(shared[field], str) or not shared[field].strip()):
                raise ValueError()
        if 'known_nodes' in shared and (not isinstance(shared['known_nodes'], list) or
                any(not isinstance(n, str) or not n.strip() for n in shared['known_nodes'])):
            raise ValueError()
        for field in ('preservation_window_s', 'result_window_s', 'registration_window_s'):
            if field in shared and (type(shared[field]) not in (int, float) or not math.isfinite(shared[field])
                                    or shared[field] < 0 or field != 'preservation_window_s' and shared[field] == 0):
                raise ValueError()
        if 'external_dependents' in shared:
            if not isinstance(shared['external_dependents'], list):
                raise ValueError()
            for participant in shared['external_dependents']:
                if (not isinstance(participant, dict) or set(participant) != {'component_type', 'component_id'}
                        or participant['component_type'] not in {'controller', 'acquisition_node', 'synchronization_manager'}
                        or not isinstance(participant['component_id'], str) or not participant['component_id'].strip()):
                    raise ValueError()
        shared['servers'] = [_endpoint(s, include_route=True) for s in data['servers']]
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        failed = True
    if failed:
        raise ValueError('Selected deployment configuration is unreadable or lacks valid shared settings')
    return shared


def _choose_discovered(label, candidates):
    """Confirm one bounded candidate or explicitly select among several; empty declines discovery."""
    if not candidates:
        return None
    for i, (description, _) in enumerate(candidates, 1):
        print(f'  {i}. {json.dumps(description)}')
    if len(candidates) == 1:
        return candidates[0][1] if _confirm('Use discovered ' + label) else None
    choice = _ask('Choose ' + label + ' number; empty to enter another value', allow_empty=True)
    if not choice:
        return None
    if not choice.isdigit() or not 1 <= int(choice) <= len(candidates):
        raise ValueError('Choose one of the displayed candidates')
    return candidates[int(choice) - 1][1]


def _configuration_plan(roles, directory, existing, preflight_python):
    """Collect only installation values; existing configurations are never edited."""
    values = {}
    local_servers = []
    for role, (_, data) in existing.items():
        servers = [_endpoint(s, include_route=True) for s in data['servers']]
        if not any(servers == candidate for _, candidate in local_servers):
            local_servers.append((FILES[role] + ': ' + ', '.join(_endpoint(s) for s in servers), servers))
        fields = dict(data)
        if role == "controller":
            fields["controller_id"] = data.get("service_id")
        if role == "synchronization-manager":
            fields["synchronization_id"] = data.get("service_id")
        for key in ("ingestor_id", "storage_id", "synchronization_id", "controller_id", *AUTHORITY_FIELDS):
            if key in fields:
                if key in values and values[key] != fields[key]:
                    raise ValueError(f"Existing configurations disagree on {key}; resolve explicitly")
                values[key] = fields[key]
        for key in ('known_nodes', 'external_dependents'):
            if key in fields:
                values[key] = fields[key]
    pending = [role for role in roles if role not in existing]
    print('Laboratory setup: new = set up a new laboratory system; existing = add/update a computer in an existing system.')
    setup = _ask('Laboratory setup (new/existing)', 'existing' if existing else None)
    if setup not in {'new', 'existing'} or (setup == 'new' and existing):
        raise ValueError('Choose existing for an installation with retained configuration, or new for a new system')
    imported = {}
    if setup == 'existing' and pending:
        source = _ask('Existing laboratory service configuration; empty to enter shared settings manually', allow_empty=True)
        if source:
            imported = _read_shared_configuration(Path(source).expanduser())
            print('Shared settings discovered in ' + str(Path(source).expanduser()) + '; credentials and foreign computer paths are not imported.')
            for key in ('ingestor_id', 'storage_id', 'synchronization_id', 'controller_id', *AUTHORITY_FIELDS):
                if key in values and key in imported and values[key] != imported[key]:
                    raise ValueError(f'Existing configurations disagree on {key}; imported values cannot override them')
            if local_servers and not any(imported['servers'] == servers for _, servers in local_servers):
                raise ValueError('The selected file has different NATS addresses or ordering from the local files; '
                                 'confirm the laboratory configuration before retrying. Existing files were not changed')
            for key, value in imported.items():
                if key != 'servers' or not local_servers:
                    values.setdefault(key, value)
    for key in ('ingestor_id', 'storage_id', 'synchronization_id', 'controller_id', *AUTHORITY_FIELDS):
        if key in values:
            print('Discovered ' + key + ': ' + json.dumps(values[key]))
    if existing:
        print('Discovered local configuration: ' + ', '.join(FILES[role] for role in existing) + '; existing files remain unchanged.')
    if 'known_nodes' not in values:
        nodes = list(dict.fromkeys(p['component_id'] for p in values.get('external_dependents', [])
                                   if p['component_type'] == 'acquisition_node'))
        if nodes:
            values['known_nodes'] = nodes
    print('NATS connects the laboratory computers. Reachability does not establish laboratory membership; no network search is performed.')
    if local_servers:
        print('Existing service addresses and credentials remain unchanged. Discovered addresses for new roles '
              'do not include another service\'s credentials.')
        if len(local_servers) > 1:
            print('Local files declare different NATS address lists or ordering. Select the list for new roles; '
                  'this does not merge lists or replace any existing setting.')
        values['servers'] = _choose_discovered('local NATS settings for new roles without changing existing files', local_servers)
        if values['servers'] is None:
            raise ValueError('Choose a discovered address list explicitly or resolve the local files before retrying; no override was applied')
    elif 'servers' in values:
        if len(values['servers']) == 1:
            if not _choose_discovered('NATS server', [(_endpoint(values['servers'][0]), values['servers'])]):
                values.pop('servers')
        else:
            candidates = values.pop('servers')
            for i, server in enumerate(candidates, 1):
                print(f'  {i}. {json.dumps(_endpoint(server))}')
            choice = _ask('Choose NATS server numbers, comma-separated in chosen order; empty to enter addresses', allow_empty=True)
            if choice:
                selected = _comma(choice)
                if (len(set(selected)) != len(selected) or
                        any(not n.isdigit() or not 1 <= int(n) <= len(candidates) for n in selected)):
                    raise ValueError('Choose distinct displayed NATS server numbers')
                values['servers'] = [candidates[int(n)-1] for n in selected]
    if 'servers' not in values:
        print('No laboratory server has been selected. Ask the laboratory administrator for its NATS address; entering an address does not verify it.')
    print('Service names identify the shared data intake, storage and timing owners; proposed names are editable, not discovered services.')
    for key, label, default in (("servers", "NATS URLs, comma-separated (external broker)", None),
                               ("ingestor_id", "Deployment Ingestor ID", "ingestor-1"),
                               ("storage_id", "Deployment StorageManager ID", "storage-manager-1")):
        if key not in values:
            answer = _hidden_input(label) if key == "servers" else _ask(label, default)
            values[key] = _comma(answer) if key == "servers" else answer
    window_fields = (("preservation_window_s", "Preservation window, seconds"),
                     ("result_window_s", "Request/check window, seconds"))
    windows = {}
    if pending:
        print('Confirmation windows are maximum waits, not recording duration. Reuse laboratory settings or obtain suitable values from its administrator.')
        for key, label in window_fields:
            previous = {data[key] for _, data in existing.values() if key in data}
            if len(previous) > 1:
                print(label + ': local roles use ' + json.dumps(sorted(previous)) + '; choose the value for new roles, without changing existing files.')
            default = values.get(key)
            windows[key] = (previous.pop() if len(previous) == 1 else float(default) if default is not None else float(_ask(label)))
    generated, deferred = {}, []
    for role in pending:
        data = {key: values[key] for key in ("servers", "ingestor_id", "storage_id")}
        if _confirm(f"Use explicit NATS username/password for {role}"):
            for field in _NATS_HELPERS['AUTH_FIELDS']:
                data[field] = _hidden_input(f"{role} {field} (hidden)")
        _NATS_HELPERS['nats_connect_options'](data['servers'], **{
            k: data[k] for k in _NATS_HELPERS['AUTH_FIELDS'] if k in data})
        for key, label in window_fields:
            value = windows[key]
            if value == 0 and (key == 'result_window_s' or role != 'ingestor'):
                print(f'Proposed {label.lower()} is zero; new {role} requires a positive value. '
                      'Choose a value for this new role only; existing configuration stays unchanged.')
                value = float(_ask(f'{label} for new {role}'))
            data[key] = value
        if role in {"controller", "acquisition-node", "synchronization-manager"}:
            data["registration_window_s"] = values.get('registration_window_s', 180.0)
            if "synchronization_id" not in values:
                names = list(dict.fromkeys(p['component_id'] for p in values.get('external_dependents', [])
                                          if p['component_type'] == 'synchronization_manager'))
                values["synchronization_id"] = _choose_discovered('declared timing-service name', [(n, n) for n in names]) or _ask(
                    "Deployment SynchronizationManager ID", "synchronization-manager-1")
            if role != "synchronization-manager":
                data["synchronization_id"] = values["synchronization_id"]
        if role == "controller":
            names = list(dict.fromkeys(p['component_id'] for p in values.get('external_dependents', [])
                                      if p['component_type'] == 'controller'))
            data["service_id"] = values.get("controller_id") or _choose_discovered(
                'declared Controller name', [(n, n) for n in names]) or _ask("Controller ID", "controller-1")
            nodes = (_choose_discovered('declared node inventory', [(json.dumps(values['known_nodes']), values['known_nodes'])])
                     if 'known_nodes' in values else None)
            data["known_nodes"] = nodes if nodes is not None else _comma(_ask(
                "Known AcquisitionNode IDs, comma-separated; empty for none", allow_empty=True))
        elif role == "synchronization-manager":
            data["service_id"] = values["synchronization_id"]
        elif role == "acquisition-node":
            hardware_candidates = [(str(p), str(p)) for p in (directory / 'acquisition-node.json',) if p.is_file()]
            hardware = _choose_discovered('local hardware configuration', hardware_candidates) or _ask(
                "Existing node hardware JSON path; empty to defer node setup", allow_empty=True)
            if not hardware or not Path(hardware).expanduser().is_file():
                deferred.append("AcquisitionNode incomplete: provide an existing valid hardware JSON; no declarations invented")
                continue
            data["node_config"] = str(Path(hardware).expanduser().resolve())
        else:
            base = Path(_ask("Storage data directory", directory / "data")).expanduser().resolve()
            data.update(storage_root=str(base / "records"), global_artifact_root=str(base / "artifacts"),
                        recovery_journal_root=str(base / "journals"), framework_journal=str(base / "framework.jsonl"))
            endpoints = {}
            print('Scientific retrieval uses SSH access prepared by the administrator; no keys, trust or remote devices are created.')
            retrieval = _ask("Retrieval node IDs, comma-separated; empty or none to skip",
                             ','.join(values.get('known_nodes', [])) or None, allow_empty=True)
            for identity in ([] if retrieval == 'none' else _comma(retrieval)):
                if identity in endpoints:
                    raise ValueError("Duplicate retrieval node")
                endpoints[identity] = {
                    "host": _ask(f"{identity} SSH host"), "username": _ask(f"{identity} SSH username"),
                    "port": int(_ask(f"{identity} SSH port", 22)),
                }
                keys = [(str(p), str(p)) for p in (Path.home() / '.ssh' / 'id_ed25519', Path.home() / '.ssh' / 'id_rsa') if p.is_file()]
                key = _choose_discovered(f'{identity} local SSH key path', keys) or _ask(f"{identity} existing SSH private-key path")
                endpoints[identity]['key_filename'] = str(Path(key).expanduser().resolve())
                host_files = [(str(p), str(p)) for p in (Path.home() / '.ssh' / 'known_hosts',) if p.is_file()]
                hosts = _choose_discovered(f'{identity} local host-key file', host_files) or _ask(
                    f"{identity} existing known-hosts path; empty for system host keys", allow_empty=True)
                if hosts:
                    endpoints[identity]["known_hosts_path"] = str(Path(hosts).expanduser().resolve())
            data["retrieval_endpoints"] = endpoints
        generated[role] = data
    if generated:
        if setup == 'new' and 'controller_claim_account' not in values:
            settings = next(iter(generated.values()))
            try:
                result = _run([preflight_python, '-I', '-B', '-c', CONNECT], timeout=3 * settings['result_window_s'] + 5,
                    input=json.dumps({'servers': settings['servers'], 'timeout_s': settings['result_window_s'],
                        'discover_account': True, **{k: settings[k] for k in _NATS_HELPERS['AUTH_FIELDS'] if k in settings}}))
                observed = json.loads(result)
                account = observed.get('account') if isinstance(observed, dict) else None
            except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                account = None
            if isinstance(account, str) and account.strip():
                values['controller_claim_account'] = _ask('Controller authority account (authenticated observation; confirm exact value)', account)
            else:
                print('Account discovery PENDING / NOT VERIFIED. The server may be offline or deny account readback; ask its administrator for the actual account. Software installation can proceed with supplied valid settings.')
        print('Controller exclusivity uses one shared account/bucket/key for the laboratory. This installer does not create a bucket or claim; the administrator must provision the persistent bucket.')
        for key, label, proposal in (
                ('controller_claim_account', 'Controller authority account (actual NATS account ID)', None),
                ('controller_claim_bucket', 'Controller authority bucket (shared persistent bucket)', 'controller_authority'),
                ('controller_claim_key', 'Controller authority key (shared installation claim)', 'controller')):
            if key not in values:
                values[key] = _ask(label, proposal if setup == 'new' else None)
        for data in generated.values():
            data.update({k: values[k] for k in AUTHORITY_FIELDS})
    combined = {role: data for role, (_, data) in existing.items()} | generated
    storage = combined.get("ingestor")
    if 'ingestor' in generated:
        local = []
        for role, data in combined.items():
            if role in {'controller', 'synchronization-manager'}:
                local.append(role.replace('-', '_') + '/' + data['service_id'])
            elif role == 'acquisition-node':
                hardware = Path(data['node_config'])
                if not hardware.is_absolute():
                    hardware = directory / hardware
                local.append('acquisition_node/' + json.loads(hardware.read_text(encoding='utf-8'))['node_id'])
        declared = [p['component_type'] + '/' + p['component_id'] for p in values.get('external_dependents', [])]
        configured = [kind + '/' + values[field] for field, kind in (
            ('controller_id', 'controller'), ('synchronization_id', 'synchronization_manager')) if field in values]
        configured.extend('acquisition_node/' + node for node in values.get('known_nodes', []))
        proposed = list(dict.fromkeys([*declared, *local, *configured]))
        print('These declared services may have retirement obligations, including while offline. Confirm the actual list; use none only for a genuinely isolated pair.')
        for i, participant in enumerate(proposed, 1):
            kind, identity = participant.split('/', 1)
            print(f'  {i}. {kind.replace("_", " ")} named {json.dumps(identity)}')
        dependents = _ask('Actual external dependents TYPE/ID, comma-separated; type none only if isolated', ','.join(proposed) or None)
        if dependents == 'none':
            storage['no_operational_dependents'] = True
        else:
            selected = _comma(dependents)
            if selected and all(n.isdigit() for n in selected):
                if any(not 1 <= int(n) <= len(proposed) for n in selected):
                    raise ValueError('Choose displayed service numbers or explicit TYPE/ID identities')
                selected = [proposed[int(n)-1] for n in selected]
            storage['external_dependents'] = [dict(zip(('component_type', 'component_id'), item.split('/', 1), strict=True))
                                               for item in selected]
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
                _read_shared_configuration(path, contents=contents)
                validated = _validate(preflight_python, checkout, path, role, allow_unavailable=True)
                print(('Discovered validated local configuration: ' if validated else
                       'Discovered local candidate; full validation pending dependencies: ') + str(path))
        print('Choose this computer\'s jobs: 1 controller (coordinate experiments), 2 acquisition-node (attached equipment), '
              '3 synchronization-manager (laboratory time), 4 ingestor-storage (both logical services together in the existing shared process). Multiple jobs are allowed.')
        defaults = list(dict.fromkeys((*existing, 'ingestor')))
        choices = _ask("Local roles: controller acquisition-node synchronization-manager ingestor-storage",
                       " ".join('ingestor-storage' if role == 'ingestor' else role for role in defaults)).replace(",", " ").split()
        names = {'1': 'controller', '2': 'acquisition-node', '3': 'synchronization-manager', '4': 'ingestor',
                 'ingestor-storage': 'ingestor', 'storage-manager': 'ingestor'}
        choices = [names.get(role, role) for role in choices]
        if not choices or set(choices) - set(FILES):
            raise ValueError("Select existing framework role names")
        roles = tuple(dict.fromkeys(choices))
        generated, deferred = _configuration_plan(roles, directory, existing, preflight_python)
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
            # Each selected role retains its own connection and authentication settings.
            settings = next(iter(configured.values()))
            window = settings["result_window_s"]
            if type(window) not in (int, float) or not math.isfinite(window) or window <= 0:
                raise ValueError("NATS connectivity timeout must be positive and finite")
            try:
                for settings in configured.values():
                    _NATS_HELPERS['nats_connect_options'](settings['servers'], **{
                        k: settings[k] for k in _NATS_HELPERS['AUTH_FIELDS'] if k in settings})
                    window = settings['result_window_s']
                    _run([preflight_python, "-I", "-B", "-c", CONNECT], timeout=3 * window + 5,
                         input=json.dumps({"servers": settings["servers"], "timeout_s": window,
                             **{k: settings[k] for k in _NATS_HELPERS['AUTH_FIELDS'] if k in settings}}))
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
            for role, settings in configured.items():
                summary = {k: settings[k] for k in (*SHARED_FIELDS, 'service_id', 'storage_root', 'global_artifact_root',
                           'recovery_journal_root', 'framework_journal', 'node_config') if k in settings}
                summary['servers'] = [_endpoint(s) for s in settings['servers']]
                summary['authentication'] = ('explicit credentials retained/entered; values hidden' if any(
                    k in settings for k in _NATS_HELPERS['AUTH_FIELDS']) else 'URL-only settings; credentials hidden')
                print('Configuration findings for ' + role + ': ' + json.dumps(summary, sort_keys=True))
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
