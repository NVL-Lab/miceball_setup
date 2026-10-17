"""Manual process lifetime around existing service maintenance, not supervision."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
from math import isfinite
from pathlib import Path
import signal
import sys
from uuid import uuid4

from lab_sync_acquisition.communication import RuntimeCommandMessage, RuntimeParticipant
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.nats_communication import (
    NatsCommunicationBoundary, NatsIngestorCommunication,
    NatsServiceMaintenanceCommunication, NatsStorageManagerCommunication,
)
from lab_sync_acquisition.service_maintenance import ServiceMaintenanceInterface
from lab_sync_acquisition.storage import PersistentStorageManager


class ServiceLauncher:
    """Keep explicitly composed service owners alive until confirmed retirement.

    The supported composition is one owner, or the existing Ingestor/StorageManager
    pair. This class supplies no configuration, evidence authority or service owner.
    """

    def __init__(self, maintenance, boundaries, *, report=print):
        self.maintenance = tuple(maintenance)
        self.boundaries = tuple(boundaries)
        participants = [m.participant for m in self.maintenance]
        if not participants or len(participants) != len(self.boundaries) or len(set(participants)) != len(participants):
            raise ValueError("Explicit unique maintenance owners and matching boundaries are required")
        kinds = {p.component_type for p in participants}
        if len(participants) > 1 and (len(participants) != 2 or kinds != {"ingestor", "storage_manager"}):
            raise ValueError("Only the shared Ingestor/StorageManager pair shares a launcher")
        if kinds & {"ingestor", "storage_manager"} and kinds != {"ingestor", "storage_manager"}:
            raise ValueError("Ingestor and StorageManager must launch and exit together")
        if len(participants) == 2:
            owners = {m.participant.component_type: m.service for m in self.maintenance}
            if any(m.ingestor is not owners["ingestor"] or m.storage_manager is not owners["storage_manager"]
                   for m in self.maintenance):
                raise ValueError("Shared-process maintenance must reference the same two authoritative owners")
        for maintenance, boundary in zip(self.maintenance, self.boundaries):
            if (boundary.component_type, boundary.component_id) != (
                    maintenance.participant.component_type, maintenance.participant.component_id):
                raise ValueError("Communication identity must match its maintenance owner")
            if boundary.maintenance_command_handled is not None:
                raise ValueError("Communication already has a process-lifetime observer")
        self._report = report
        self._requester = uuid4().hex
        self._wake = asyncio.Event()
        self._interrupt = False
        self._handled_retirements = set()
        for maintenance, boundary in zip(self.maintenance, self.boundaries):
            boundary.maintenance_command_handled = lambda command, result, owner=maintenance: self._remote_handled(owner, command, result)

    def _feedback(self, owner, command, result=None, error=None):
        payload = result.payload if result is not None else {}
        attempt = payload.get("attempt") or {}
        self._report(json.dumps({
            "target": owner.participant.to_dict(), "command": command.command_type,
            "command_id": command.command_id, "stop_attempt_id": command.payload.get("stop_attempt_id"),
            "outcome": payload.get("outcome", "unconfirmed"),
            "reason": str(error) if error is not None else (result.reason if result is not None else "No confirmed result"),
            "blockers": attempt.get("blockers", []), "errors": attempt.get("failures", []),
            "remaining_obligations": attempt.get("remaining_obligations", []),
            "termination_confirmed": payload.get("termination_confirmed") is True,
            "operator_action": ("none" if result is not None and result.success
                and payload.get("termination_confirmed") is True else
                "Process retained; inspect blockers and unresolved obligations. Kill is never implicit."),
        }, sort_keys=True))

    def _remote_handled(self, owner, command, result):
        # The handler returns this exact owner's response to this full request;
        # a different resolution cached under the same command ID is not proof.
        if result is not None and (
                command.target_id != owner.participant.component_id or command.session_id is not None
                or result.command_id != command.command_id or result.session_id != command.session_id
                or result.source_id != owner.participant.component_id or result.target_id != command.source_id):
            self._feedback(owner, command, error="Handled maintenance result identity mismatch")
            return
        self._feedback(owner, command, result)
        if (result is not None and result.success and result.payload.get("outcome") == "completed"
                and result.payload.get("termination_confirmed") is True and owner.terminated):
            self._handled_retirements.add(owner.participant)
        self._wake.set()

    @property
    def exit_ready(self):
        """Every hosted owner retired and its final maintenance result was handled."""
        return all(m.terminated and m.participant in self._handled_retirements for m in self.maintenance)

    def request_interrupt(self):
        """Queue local Stop, including repeated Ctrl+C, without cancelling maintenance."""
        self._interrupt = True
        self._wake.set()

    async def stop_locally(self, administrator_id):
        """Use existing maintenance Stop/Cancel and paired prepared-retirement order."""
        if not isinstance(administrator_id, str) or not administrator_id.strip():
            raise ValueError("Local administrator identity is required")
        attempt = uuid4().hex
        pending = []

        async def execute(owner, operation, payload):
            command = RuntimeCommandMessage(uuid4().hex, None, operation, self._requester,
                owner.participant.component_id, {**payload, "administrator_id": administrator_id})
            try:
                result = await owner.execute_command(command)
                self._feedback(owner, command, result)
                if (result.success and result.payload.get("outcome") == "completed"
                        and result.payload.get("termination_confirmed") is True and owner.terminated):
                    self._handled_retirements.add(owner.participant)
                return result
            except Exception as error:
                self._feedback(owner, command, error=error)
                return None

        owners = {m.participant.component_type: m for m in self.maintenance}
        if len(owners) == 2:
            storage, intake = owners["storage_manager"], owners["ingestor"]
            # Reuse the established prepare -> Ingestor stop -> prepared retirement
            # sequence so no final StorageManager evidence needs retired intake.
            plan = [(storage, "prepare_stop"), (intake, "stop"), (storage, "stop")]
        else:
            plan = [(self.maintenance[0], "stop")]
        for owner, operation in plan:
            if owner.terminated:
                if owner.participant not in self._handled_retirements:
                    self._report(json.dumps({"target": owner.participant.to_dict(), "outcome": "unconfirmed",
                        "remaining_obligations": ["Final maintenance command-result publication/handling"],
                        "retained_results": [r.to_dict() for r in owner.command_results],
                        "operator_action": "Process retained; retry the original remote maintenance command."}, sort_keys=True))
                continue
            payload = {"stop_attempt_id": f"{attempt}-{owner.participant.component_type}"}
            if len(owners) == 2:
                payload["framework_stop_attempt_id"] = attempt
            result = await execute(owner, operation, payload)
            if result is not None and result.success:
                if result.payload.get("prepared") is True:
                    pending.append((owner, payload))
                continue
            if result is not None and result.payload.get("outcome") == "blocked":
                await execute(owner, "cancel", payload)
            for prepared_owner, prepared_payload in pending:
                if not prepared_owner.terminated and prepared_owner is not owner:
                    await execute(prepared_owner, "cancel", prepared_payload)
            break
        self._wake.set()
        return self.exit_ready

    async def run(self, *, startup=None):
        """Run optional async startup under SIGINT protection, then await confirmed retirement."""
        loop = asyncio.get_running_loop()
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(self.request_interrupt))
        startup_task = None

        async def initialize():
            try:
                await startup()
            finally:
                self._wake.set()

        try:
            if startup is not None:
                startup_task = asyncio.create_task(initialize())
            while True:
                try:
                    await self._wake.wait()
                    self._wake.clear()
                    if startup_task is not None:
                        if self._interrupt and not startup_task.done():
                            startup_task.cancel()
                        if not startup_task.done() and not self._interrupt:
                            continue
                        try:
                            await startup_task
                        except asyncio.CancelledError:
                            self._report("Startup interrupted; owners retained for local maintenance.")
                            self._interrupt = True
                        startup_task = None
                    if self._interrupt:
                        self._interrupt = False
                        try:
                            administrator = getpass.getuser()
                        except Exception as error:
                            self._report(f"Local administrator identity unconfirmed: {error}; process retained.")
                            continue
                        await self.stop_locally(administrator)
                    if self.exit_ready:
                        try:
                            for boundary in self.boundaries:
                                await boundary.close()
                        except Exception as error:
                            self._report(f"Final communication cleanup unconfirmed: {error}; process retained; retry Ctrl+C.")
                            continue
                        return 0
                except asyncio.CancelledError:
                    self._report("Launcher cancellation is not confirmed retirement; process retained.")
                    if startup_task is not None:
                        self.request_interrupt()
        finally:
            try:
                if startup_task is not None and not startup_task.done():
                    startup_task.cancel()
                    try:
                        await startup_task
                    except asyncio.CancelledError:
                        pass
            finally:
                signal.signal(signal.SIGINT, previous)


async def launch_storage_services(*, servers, ingestor_id, storage_id, storage_root,
                                  recovery_journal_root, framework_journal,
                                  preservation_window_s, operational_dependents, report=print,
                                  global_artifact_root=None, retrieval_endpoints=None):
    """Launch the existing paired owners with explicit constructor settings."""
    servers = tuple(servers)
    if not servers or any(not isinstance(server, str) or not server.strip() for server in servers):
        raise ValueError("Explicit nonempty NATS servers are required")
    storage = PersistentStorageManager(storage_root, component_id=storage_id,
        global_artifact_root=global_artifact_root, retrieval_endpoints=retrieval_endpoints)
    intake = InMemoryIngestor(storage, component_id=ingestor_id,
        recovery_journal_root=recovery_journal_root,
        framework_recovery_journal_path=framework_journal)
    boundaries = tuple(NatsCommunicationBoundary(kind, identity, tuple(servers)) for kind, identity in (
        ("ingestor", ingestor_id), ("storage_manager", storage_id)))

    async def cleaned(force):
        # These owners open/close disk handles within each authoritative operation.
        return True

    async def publish(owner_boundary, message):
        audit = intake.receive_runtime_evidence(message)
        if not audit.accepted:
            raise RuntimeError("Local framework evidence intake rejected maintenance evidence")
        await owner_boundary.publish_evidence(message)

    interfaces = tuple(ServiceMaintenanceInterface(owner,
        RuntimeParticipant(boundary.component_type, boundary.component_id), ingestor=intake,
        storage_manager=storage, preservation_window_s=preservation_window_s, close_resources=cleaned,
        operational_dependents=operational_dependents if owner is intake else None,
        evidence_publisher=lambda message, b=boundary: publish(b, message))
        for owner, boundary in zip((intake, storage), boundaries))
    launcher = ServiceLauncher(interfaces, boundaries, report=report)
    connected = []

    async def startup():
        admission_started = False
        try:
            for boundary in boundaries:
                await boundary.connect()
                connected.append(boundary)
                await boundary.ensure_streams()
            intake_handler = NatsIngestorCommunication(boundaries[0], intake)
            # Even a failed subscription may have begun admitting evidence.
            admission_started = True
            await intake_handler.subscribe_evidence(None)
            for boundary, interface in zip(boundaries, interfaces):
                status = await NatsServiceMaintenanceCommunication(boundary, interface).start()
                report(json.dumps({"target": interface.participant.to_dict(), "startup": status}, sort_keys=True))
            await intake_handler.subscribe_commands()
            await NatsStorageManagerCommunication(boundaries[1], storage).subscribe_commands()
        except asyncio.CancelledError:
            # The protected launcher cancels and awaits initialization before Stop.
            # Never close participants whose admitted obligations are still unknown.
            raise
        except Exception as error:
            if admission_started:
                report(f"Command startup unconfirmed: {error}; process retained; Ctrl+C requests local maintenance.")
                return
            for boundary in reversed(connected):
                await boundary.close()
            raise

    return await launcher.run(startup=startup)


def main(argv=None):
    """Common installed CLI; unavailable role composition fails before startup."""
    parser = argparse.ArgumentParser(description="Launch existing services; Ctrl+C requests maintenance Stop.")
    parser.add_argument("role", choices=("controller", "acquisition-node", "ingestor", "storage-manager", "synchronization-manager", "stop", "kill", "cancel", "verify-retrieval"))
    parser.add_argument("--node-id")
    parser.add_argument("--source-path")
    parser.add_argument("--expected-file", type=Path)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--target-type", choices=("controller", "acquisition_node", "ingestor", "storage_manager", "synchronization_manager"))
    parser.add_argument("--target-id")
    parser.add_argument("--administrator-id")
    parser.add_argument("--result-window-s", type=float)
    parser.add_argument("--stop-attempt-id")
    parser.add_argument("--authorize-kill", action="store_true")
    parser.add_argument("--service-id")
    parser.add_argument("--synchronization-id")
    parser.add_argument("--known-node", action="append")
    parser.add_argument("--no-known-nodes", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--deployment-config", type=Path,
        help="Explicit deployment-local JSON service settings; not combined with launch-setting flags")
    parser.add_argument("--server", action="append", help="Explicit NATS server URL; repeat for multiple servers")
    parser.add_argument("--ingestor-id")
    parser.add_argument("--storage-id")
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--recovery-journal-root", type=Path)
    parser.add_argument("--framework-journal", type=Path)
    parser.add_argument("--preservation-window-s", type=float)
    parser.add_argument("--no-operational-dependents", action="store_true",
        help="Explicitly declare no external operational dependents; other dependency composition is unavailable here")
    args = parser.parse_args(argv)
    if args.role == "verify-retrieval":
        forbidden = ("server", "service_id", "ingestor_id", "storage_id", "synchronization_id",
                     "known_node", "no_known_nodes", "config", "storage_root", "recovery_journal_root",
                     "framework_journal", "preservation_window_s", "result_window_s", "no_operational_dependents",
                     "target_type", "target_id", "administrator_id", "stop_attempt_id", "authorize_kill")
        if (args.deployment_config is None or not args.node_id or not args.source_path
                or args.expected_file is None or args.max_bytes is None or args.max_bytes <= 0
                or any(getattr(args, field) is not None and getattr(args, field) is not False for field in forbidden)):
            parser.error("verify-retrieval requires only --deployment-config, --node-id, --source-path, --expected-file and positive --max-bytes")
        result = {"node_id": args.node_id, "outcome": "FAIL", "retrieval_succeeded": False,
                  "content_match": None, "failure_reason": None}
        try:
            from lab_sync_acquisition.deployment_configuration import load_retrieval_configuration
            settings = load_retrieval_configuration(args.deployment_config)
            with args.expected_file.open("rb") as reference:
                expected = reference.read(args.max_bytes + 1)
            if len(expected) > args.max_bytes:
                raise ValueError("Expected dummy file exceeds max_bytes")
            storage = PersistentStorageManager(**settings)
            result = storage.verify_installation_retrieval(args.node_id, args.source_path, expected,
                                                         max_bytes=args.max_bytes)
        except KeyboardInterrupt:
            result["failure_reason"] = "Installation verification interrupted; success is not confirmed"
        except Exception as error:
            result["failure_reason"] = f"Local verification inputs failed ({type(error).__name__}); check configuration, expected file and max_bytes"
        print(json.dumps(result, sort_keys=True))
        return 0 if result["outcome"] == "PASS" else 1
    if any(value is not None for value in (args.node_id, args.source_path, args.expected_file, args.max_bytes)):
        parser.error("Dummy-file verification arguments require the verify-retrieval action")
    if args.deployment_config is not None:
        if args.role in {"stop", "kill", "cancel"}:
            parser.error("--deployment-config is for service startup, not administrative commands")
        fields = ("server", "service_id", "ingestor_id", "storage_id", "synchronization_id",
                  "known_node", "no_known_nodes", "config", "storage_root", "recovery_journal_root",
                  "framework_journal", "preservation_window_s", "result_window_s", "no_operational_dependents",
                  "target_type", "target_id", "administrator_id", "stop_attempt_id", "authorize_kill")
        if any(getattr(args, field) is not None and getattr(args, field) is not False for field in fields):
            parser.error("--deployment-config cannot be combined with explicit launch or maintenance settings; no override precedence is applied")
        try:
            from lab_sync_acquisition.deployment_configuration import load_service_configuration
            settings = load_service_configuration(args.deployment_config, args.role)
            if args.role in {"ingestor", "storage-manager"}:
                operation = launch_storage_services(**settings)
            else:
                from lab_sync_acquisition.service_startup import launch_independent_service
                settings.setdefault("service_id", None)
                operation = launch_independent_service(role=args.role, **settings)
            return asyncio.run(operation)
        except Exception as error:
            print(f"Startup unconfirmed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    if args.role in {"stop", "kill", "cancel"}:
        from lab_sync_acquisition.communication import build_runtime_subject
        from lab_sync_acquisition.service_maintenance_cli import request_service_maintenance
        if (not args.server or any(not s.strip() for s in args.server)
                or not args.target_type or not args.target_id or not args.target_id.strip()
                or not args.administrator_id or not args.administrator_id.strip()
                or args.result_window_s is None or not isfinite(args.result_window_s) or args.result_window_s <= 0):
            parser.error("Remote maintenance requires --server, --target-type, --target-id, --administrator-id and a positive finite --result-window-s")
        try:
            build_runtime_subject(None, "command", args.target_type, args.target_id, args.role)
        except ValueError as error:
            parser.error(str(error))
        if args.role == "stop" and (args.stop_attempt_id is not None or args.authorize_kill):
            parser.error("Stop creates a new attempt; do not supply continuation or Kill authorization")
        if args.role in {"kill", "cancel"} and (not args.stop_attempt_id or not args.stop_attempt_id.strip()):
            parser.error("Kill/Cancel require --stop-attempt-id from the existing blocked Stop")
        if args.authorize_kill != (args.role == "kill"):
            parser.error("--authorize-kill is required only for Kill")
        try:
            return asyncio.run(request_service_maintenance(servers=args.server,
                participant=RuntimeParticipant(args.target_type, args.target_id), operation=args.role,
                administrator_id=args.administrator_id, result_window_s=args.result_window_s,
                stop_attempt_id=args.stop_attempt_id, authorized=args.authorize_kill))
        except KeyboardInterrupt:
            print("Remote outcome unconfirmed after interruption; no Kill was authorized implicitly.", file=sys.stderr)
            return 1
        except Exception as error:
            print(f"Remote maintenance unconfirmed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    if args.role not in {"ingestor", "storage-manager"}:
        from lab_sync_acquisition.service_startup import launch_independent_service
        required = ("server", "ingestor_id", "storage_id", "preservation_window_s", "result_window_s")
        for field in required:
            if getattr(args, field) is None:
                parser.error("Independent service startup requires explicit --" + field.replace("_", "-"))
        if args.role != "acquisition-node" and not args.service_id:
            parser.error("Independent service startup requires --service-id")
        if args.role in {"controller", "acquisition-node"} and not args.synchronization_id:
            parser.error("Configured --synchronization-id is required")
        if args.role == "controller" and (bool(args.known_node) == args.no_known_nodes):
            parser.error("Controller requires --known-node entries or explicit --no-known-nodes")
        try:
            return asyncio.run(launch_independent_service(role=args.role, servers=args.server,
                service_id=args.service_id, ingestor_id=args.ingestor_id, storage_id=args.storage_id,
                preservation_window_s=args.preservation_window_s, result_window_s=args.result_window_s,
                synchronization_id=args.synchronization_id, known_nodes=tuple(args.known_node or ()),
                node_config=args.config or Path.home() / ".config" / "lab-sync-acquisition" / "acquisition-node.json"))
        except Exception as error:
            print(f"Startup unconfirmed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
    required = ("server", "ingestor_id", "storage_id", "storage_root", "recovery_journal_root", "framework_journal", "preservation_window_s")
    for field in required:
        if getattr(args, field) is None:
            parser.error("Required for the shared process: --" + field.replace("_", "-"))
    if (not isfinite(args.preservation_window_s) or args.preservation_window_s < 0
            or any(not value.strip() for value in (*args.server, args.ingestor_id, args.storage_id))):
        parser.error("Explicit nonempty connection/owner identities and a finite nonnegative preservation window are required")
    if not args.no_operational_dependents:
        parser.error("Explicit dependency configuration is required: this bounded CLI supports only "
                     "--no-operational-dependents. Deployments with dependents require existing configured maintenance interfaces.")
    try:
        return asyncio.run(launch_storage_services(servers=args.server, ingestor_id=args.ingestor_id,
            storage_id=args.storage_id, storage_root=args.storage_root, recovery_journal_root=args.recovery_journal_root,
            framework_journal=args.framework_journal, preservation_window_s=args.preservation_window_s,
            operational_dependents={}))
    except Exception as error:
        print(f"Startup unconfirmed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
