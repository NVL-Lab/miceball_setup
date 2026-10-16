"""Service-owned readiness, framework evidence, and administrative closeout."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from inspect import iscoroutinefunction
import logging
from threading import current_thread
from time import time
from uuid import uuid4

from lab_sync_acquisition.communication import RuntimeCommandMessage, RuntimeCommandResultMessage, RuntimeEvidenceMessage, RuntimeParticipant, SERVICE_RECOVERY_COMMAND_TYPES
from lab_sync_acquisition.service_readiness import ServiceReadiness

logger = logging.getLogger(__name__)

_service_calls = ContextVar("service_calls", default=())


def service_operation(*, new_work: bool = False):
    """Guard operational calls while allowing existing obligations during blocked maintenance."""
    def decorate(method):
        @contextmanager
        def enter(owner):
            if isinstance(owner, ServiceMaintenanceInterface):
                owner = owner.service
            elif (isinstance(getattr(owner, "_maintenance", None), ServiceMaintenanceInterface)
                    and not hasattr(owner, "_service_operation_lock")):
                owner = owner._maintenance.service
            interface = getattr(owner, "_maintenance", None)
            try:
                execution = asyncio.current_task()
            except RuntimeError:
                execution = None
            call = (id(owner), execution if execution is not None else current_thread())
            with owner._service_operation_lock:
                if interface is not None and interface.terminated:
                    raise RuntimeError("Service has terminated")
                if (interface is not None and new_work and call not in _service_calls.get()
                        and (interface._attempt is not None or interface._closeout_started)):
                    raise RuntimeError("Service maintenance rejects new unrelated work")
                if new_work and getattr(owner, "_framework_shutdown_active", False) and call not in _service_calls.get():
                    raise RuntimeError("Framework shutdown rejects new unrelated Controller work")
                owner._active_service_operations += 1
            token = _service_calls.set((*_service_calls.get(), call))
            try:
                yield
            finally:
                _service_calls.reset(token)
                with owner._service_operation_lock:
                    owner._active_service_operations -= 1
        if iscoroutinefunction(method):
            @wraps(method)
            async def asynchronous(owner, *args, **kwargs):
                with enter(owner):
                    return await method(owner, *args, **kwargs)
            return asynchronous
        @wraps(method)
        def synchronous(owner, *args, **kwargs):
            with enter(owner):
                return method(owner, *args, **kwargs)
        return synchronous
    return decorate


class ServiceMaintenanceInterface:
    """Service-owned readiness/evidence, cleanup, and retirement, not a shutdown coordinator.

    close_resources(force) confirms ordinary cleanup and must retain required
    evidence intake, journaling, archival, and result capabilities. Optional
    retire_resources(force) closes remaining capabilities only after the durable
    readiness checkpoint. Both callbacks must return exactly True to confirm.
    Without retire_resources, final retirement only closes operational admission.
    """

    def __init__(self, service, participant: RuntimeParticipant, *, ingestor, storage_manager,
                 preservation_window_s: float,
                 close_resources: Callable[[bool], Awaitable[bool]],
                 operational_dependents: Mapping[RuntimeParticipant, Callable[[], bool]] | None = None,
                 evidence_publisher: Callable[[RuntimeEvidenceMessage], Awaitable[None]] | None = None,
                 retire_resources: Callable[[bool], Awaitable[bool]] | None = None,
                 dependency_participants: Iterable[RuntimeParticipant] = (),
                 framework_communication=None, framework_ingestor: RuntimeParticipant | None = None,
                 framework_storage: RuntimeParticipant | None = None):
        if getattr(service, "_maintenance", None) is not None:
            raise ValueError("Service already has an administrative interface")
        if participant.component_type not in {"controller", "acquisition_node", "ingestor", "storage_manager", "synchronization_manager"}:
            raise ValueError("Unsupported maintenance participant")
        from lab_sync_acquisition import Controller, AcquisitionNode, InMemoryIngestor, PersistentStorageManager, SynchronizationManager
        expected = {"controller": Controller, "acquisition_node": AcquisitionNode, "ingestor": InMemoryIngestor,
                    "storage_manager": PersistentStorageManager, "synchronization_manager": SynchronizationManager}
        if not isinstance(service, expected[participant.component_type]):
            raise ValueError("Maintenance scope does not match service ownership")
        if not callable(close_resources):
            raise ValueError("Confirmed service-owned resource closeout is required")
        if retire_resources is not None and not callable(retire_resources):
            raise ValueError("Final resource retirement must be callable")
        from math import isfinite
        if not isinstance(preservation_window_s, (int, float)) or not isfinite(preservation_window_s) or preservation_window_s < 0:
            raise ValueError("Preservation window must be finite and nonnegative")
        self.service = service
        self.participant = participant
        self.ingestor = ingestor
        self.storage_manager = storage_manager
        self.close_resources = close_resources
        self.retire_resources = retire_resources
        self.preservation_window_s = preservation_window_s
        self.evidence_publisher = evidence_publisher
        if framework_communication is not None:
            if (ingestor is not None or storage_manager is not None
                    or participant.component_type in {"ingestor", "storage_manager"}
                    or not isinstance(framework_ingestor, RuntimeParticipant)
                    or framework_ingestor.component_type != "ingestor"
                    or not isinstance(framework_storage, RuntimeParticipant)
                    or framework_storage.component_type != "storage_manager" or evidence_publisher is None):
                raise ValueError("Distributed maintenance requires an explicit remote Ingestor, publisher and no local persistence owners")
        elif framework_ingestor is not None or framework_storage is not None:
            raise ValueError("Remote Ingestor requires communication")
        self._framework_communication = framework_communication
        self._framework_ingestor = framework_ingestor
        self._framework_storage = framework_storage
        self._remote_preserved_evidence = {}
        self.operational_dependents = dict(operational_dependents or {})
        if self.operational_dependents and participant.component_type != "ingestor":
            raise ValueError("Operational Ingestor dependencies belong to Ingestor")
        self._lock = asyncio.Lock()
        self._admission_lock = service._service_operation_lock
        self._attempt = None
        self._attempts = {}
        self._commands = {}
        self._results = {}
        self._evidence = []
        self._terminated = False
        self._closeout_started = False
        self._prepared = False
        dependencies = tuple(dependency_participants)
        if any(not isinstance(item, RuntimeParticipant) or item == participant for item in dependencies):
            raise ValueError("Dependencies must be other explicit RuntimeParticipants")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("Duplicate dependency participant")
        self._dependency_readiness = dict.fromkeys(dependencies)
        self._last_known_dependency_readiness = dict.fromkeys(dependencies)
        self._dependency_readiness_versions = dict.fromkeys(dependencies, 0)
        self._readiness_signature = None
        self._last_readiness_status = None
        service._maintenance = self

    @property
    def _active_operations(self):
        return self.service._active_service_operations

    @property
    def terminated(self) -> bool:
        """Confirmed operational-service retirement, not a claim of OS process death."""
        return self._terminated

    @property
    def prepared(self) -> bool:
        """Confirmed ordinary cleanup, with operational retirement still outstanding."""
        return self._prepared and not self.terminated

    @property
    def command_results(self):
        """Last confirmed local results, including correlation and actual closeout outcome."""
        return tuple(RuntimeCommandResultMessage.from_dict(deepcopy(r.to_dict())) for r in self._results.values())

    @property
    def evidence(self):
        """Producer-owned framework evidence retained even when preservation fails."""
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict())) for m in self._evidence)

    @property
    def dependency_readiness(self) -> dict[RuntimeParticipant, ServiceReadiness | None]:
        """Current confirmed reports; None means unknown, not technical unreadiness."""
        with self._admission_lock:
            return dict(self._dependency_readiness)

    def evidence_preserved(self, message) -> bool:
        """Verify exact owner-confirmed coverage for a retained producer message."""
        if self._framework_communication is None:
            return self.ingestor is not None and self.ingestor.has_durable_runtime_evidence(message)
        return self._remote_preserved_evidence.get((message.session_id, message.evidence_id)) == message.to_dict()

    def required_evidence(self):
        """Snapshot this service's persistent evidence without admitting new obligations."""
        messages = (*self._evidence, *(self.service.maintenance_evidence()
                                      if self._framework_communication is not None else ()))
        unique = {}
        for message in messages:
            if not message.is_persistent:
                continue
            key = (message.session_id, message.evidence_id)
            if key in unique and unique[key].to_dict() != message.to_dict():
                raise RuntimeError("Conflicting producer evidence identity")
            unique[key] = message
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict())) for m in unique.values())

    @property
    def last_known_dependency_readiness(self) -> dict[RuntimeParticipant, ServiceReadiness | None]:
        """Historical reports, never substituted for missing current readiness."""
        with self._admission_lock:
            return dict(self._last_known_dependency_readiness)

    def receive_dependency_readiness(self, participant: RuntimeParticipant,
                                     readiness: ServiceReadiness | None) -> bool:
        """Update only a configured dependency, or invalidate current availability."""
        with self._admission_lock:
            if participant not in self._dependency_readiness:
                raise ValueError("Dependency is not configured for this service")
            if self.terminated or self._closeout_started:
                return False
            if readiness is not None:
                if (not isinstance(readiness, ServiceReadiness)
                        or readiness.component_id != participant.component_id
                        or readiness.component_type != participant.component_type
                        or type(readiness.ready) is not bool or type(readiness.required) is not bool
                        or not isinstance(readiness.reason, str)):
                    raise ValueError("Invalid dependency readiness report")
                self._last_known_dependency_readiness[participant] = readiness
            changed = self._dependency_readiness[participant] != readiness
            self._dependency_readiness[participant] = readiness
            self._dependency_readiness_versions[participant] += 1
            return changed

    def dependency_reports(self) -> tuple[ServiceReadiness, ...]:
        """Return current reports, refusing to fabricate a report for an unknown dependency."""
        with self._admission_lock:
            unknown = [p for p, report in self._dependency_readiness.items() if report is None]
            if unknown:
                raise RuntimeError("Dependency readiness is unknown: " + ", ".join(
                    f"{p.component_type}/{p.component_id}" for p in unknown))
            return tuple(self._dependency_readiness.values())

    def _administrative_outcome(self, reference: dict) -> str | None:
        with self._admission_lock:
            for message in reversed(self._evidence):
                if (message.evidence_type == "administrator_decision"
                        and message.payload.get("decision") == "drop"
                        and reference and all(message.payload.get("details", {}).get(key) == value
                                              for key, value in reference.items())):
                    return "abandoned"
        return None

    def _readiness_payload(self):
        payload = {"participant": self.participant.to_dict(), "service_readiness": None,
                   "operational_retirement_confirmed": self.terminated}
        try:
            if self.participant.component_type == "acquisition_node":
                node = self.service.check_node_readiness()
                payload["acquisition_node_readiness"] = node.to_dict()
                report = ServiceReadiness(self.participant.component_id, self.participant.component_type,
                    True, node.ready, "ready" if node.ready else "node_prerequisites_unready")
            else:
                local = self.service.check_ready()
                report = ServiceReadiness(self.participant.component_id, self.participant.component_type,
                    local.required, local.ready, local.reason)
            payload["service_readiness"] = report.to_dict()
        except Exception as error:
            payload["readiness_error"] = str(error)
        try:
            payload["remaining_obligations"] = self.service.maintenance_blockers(self.ingestor, self.storage_manager)
        except Exception as error:
            payload["obligations_unconfirmed"] = str(error)
        payload.update(self._diagnostic_payload())
        payload["dependency_readiness"] = [
            {"participant": p.to_dict(), "service_readiness": r.to_dict() if r is not None else None}
            for p, r in self.dependency_readiness.items()
        ]
        return payload

    def _diagnostic_payload(self):
        payload = {}
        try:
            payload["service_diagnostics"] = self.service.maintenance_diagnostics(self.ingestor, self.storage_manager)
        except Exception as error:
            payload["diagnostics_unconfirmed"] = str(error)
        payload["maintenance_attempts"] = {
            identity: {"actual_outcome": attempt["outcome"],
                       "obligation_outcome": ("completed" if "operational_retirement_confirmed" in attempt["actions"]
                           else self._administrative_outcome({"stop_attempt_id": identity}) or "unresolved"),
                       "recovery_assessment": (None if "operational_retirement_confirmed" in attempt["actions"]
                                               else "administrator_intervention"),
                       "blockers": list(attempt["blockers"]), "failures": list(attempt["failures"])}
            for identity, attempt in self._attempts.items()
        }
        return payload

    @service_operation(new_work=True)
    async def announce_readiness(self, *, startup: bool = False) -> dict:
        """Record startup/return or a changed snapshot without retrying unchanged evidence."""
        payload = self._readiness_payload()
        with self._admission_lock:
            if not startup and payload == self._readiness_signature:
                return deepcopy(self._last_readiness_status)
            self._readiness_signature = deepcopy(payload)
            message = RuntimeEvidenceMessage(uuid4().hex, None, "service_readiness",
                self.participant.component_id, {**payload, "recorded_at": time()}, True)
            status = self._evidence_status(message)
            self._last_readiness_status = status
        return await self._record_framework_evidence(message, status, require_existing_archive=True)

    @service_operation()
    async def record_administrator_decision(self, administrator_id: str, decision: str,
                                            details: dict) -> dict:
        """Preserve an explicit resume/drop choice, without executing or clearing work."""
        if (decision not in {"resume", "drop"} or not isinstance(administrator_id, str)
                or not administrator_id or not isinstance(details, dict)):
            raise ValueError("An explicit administrator identity and resume/drop decision are required")
        if self._closeout_started:
            raise RuntimeError("Resource closeout has already begun")
        message = RuntimeEvidenceMessage(uuid4().hex, None, "administrator_decision",
            self.participant.component_id, {"target": self.participant.to_dict(),
                "administrator_id": administrator_id, "decision": decision,
                "details": deepcopy(details), "actions": [], "outcome": None,
                "obligation_outcome": "abandoned" if decision == "drop" else "unresolved",
                "recorded_at": time()}, True)
        recovery_choice = details.get("operation") in SERVICE_RECOVERY_COMMAND_TYPES
        archive = not recovery_choice or self.storage_manager._framework_evidence_write_safe()
        status = await self._record_framework_evidence(message, archive=archive,
            require_existing_archive=recovery_choice)
        if decision == "drop":
            release, outcome_evidence = self._release_abandoned_evidence(message)
            status["temporary_memory_release"] = release
            if outcome_evidence is not None:
                release["preservation"] = await self._record_framework_evidence(outcome_evidence)
        return status

    def _release_abandoned_evidence(self, decision):
        release = {"released_evidence_count": 0, "confirmed": False, "remaining_obligations": []}
        details = decision.payload["details"]
        if not (isinstance(details.get("evidence_id"), str) or isinstance(details.get("stop_attempt_id"), str)):
            release["remaining_obligations"] = [
                "No accepted temporary-evidence release contract for the referenced service resources"]
            return release, None
        try:
            # Existing intake -> storage -> admission order; no await during retirement of copies.
            with self.ingestor._intake_lock, self.ingestor.framework_preservation_guard(self.storage_manager) as archive, self._admission_lock:
                if (self._attempt is not None or self._closeout_started or self._active_operations > 1):
                    raise RuntimeError("Administrative closeout or concurrent operations remain outstanding")
                blockers = self.service.maintenance_blockers(self.ingestor, self.storage_manager)
                blockers.extend(self._dependency_blockers())
                if blockers:
                    raise RuntimeError("Resource safety/closeout is unconfirmed: " + "; ".join(blockers))
                candidates = [m for m in self._evidence if m.evidence_type != "administrator_decision" and (
                    m.evidence_id == details.get("evidence_id") or (
                        details.get("stop_attempt_id") is not None
                        and (m.payload.get("stop_attempt_id") == details["stop_attempt_id"]
                             or m.payload.get("details", {}).get("stop_attempt_id") == details["stop_attempt_id"])))]
                if not candidates:
                    raise RuntimeError("No matching retained producer evidence")
                archived = {m["evidence_id"]: m for m in archive["runtime_evidence"]}
                for message in [decision, *candidates]:
                    if (not self.ingestor.has_durable_runtime_evidence(message)
                            or message.is_persistent and archived.get(message.evidence_id) != message.to_dict()):
                        raise RuntimeError("Required producer evidence is not currently preserved")
                ids = {m.evidence_id for m in candidates}
                outcome = RuntimeEvidenceMessage(uuid4().hex, None, "administrator_decision",
                    self.participant.component_id, {**deepcopy(decision.payload),
                        "checkpoint": "temporary_evidence_release_confirmed",
                        "actions": ["temporary_producer_evidence_released"],
                        "released_evidence_ids": sorted(ids), "recorded_at": time()}, True)
                self._evidence = [m for m in self._evidence if m.evidence_id not in ids]
                self._evidence.append(outcome)
                release.update(released_evidence_count=len(ids), confirmed=True)
                return release, outcome
        except Exception as error:
            release["remaining_obligations"] = [str(error)]
            return release, None

    @staticmethod
    def _evidence_status(message):
        return {"evidence": message.to_dict(), "publication_confirmed": False,
                "acceptance_confirmed": False, "archival_confirmed": False, "preservation_warning": None}

    async def _record_framework_evidence(self, message, status=None, *, archive=True, require_existing_archive=False):
        status = self._evidence_status(message) if status is None else status
        try:
            await self._preserve_message(message, status, archive=archive, require_existing_archive=require_existing_archive)
        except Exception as error:
            status["preservation_warning"] = f"Framework Evidence Archive preservation unconfirmed: {error}"
            logger.warning("%s/%s: %s", self.participant.component_type,
                           self.participant.component_id, status["preservation_warning"])
        return deepcopy(status)

    async def execute_command(self, command: RuntimeCommandMessage) -> RuntimeCommandResultMessage:
        """Survey or execute correlated maintenance, including coordinated preparation."""
        async with self._lock:
            previous = self._commands.get(command.command_id)
            if previous is not None:
                if previous != command.to_dict():
                    return self._result(command, "failed", "Conflicting command identity")
                return RuntimeCommandResultMessage.from_dict(deepcopy(self._results[command.command_id].to_dict()))
            attempt = None
            cleanup_started = False
            try:
                if command.target_id != self.participant.component_id or command.session_id is not None:
                    raise ValueError("Maintenance requires the matching participant and session_id=None")
                if any(not isinstance(value, str) or not value for value in (command.command_id, command.source_id)):
                    raise ValueError("Command and requester identities are required")
                if command.command_type in SERVICE_RECOVERY_COMMAND_TYPES:
                    return self._remember(command, await self._execute_authorized_recovery(command))
                if command.command_type == "check_stop_readiness":
                    blockers = self._closeout_blockers()
                    if self._attempt is not None:
                        blockers.append("Existing maintenance attempt")
                    result = RuntimeCommandResultMessage(uuid4().hex, command.command_id, None,
                        self.participant.component_id, command.source_id, "succeeded", True, None,
                        {"participant": self.participant.to_dict(), "confirmed": not self.terminated,
                         "ready": not blockers and not self.terminated, "blockers": blockers})
                    return self._remember(command, result)
                if command.command_type not in {"stop", "kill", "cancel", "prepare_stop"}:
                    raise ValueError("Unsupported maintenance command")
                attempt_id = command.payload.get("stop_attempt_id")
                administrator = command.payload.get("administrator_id")
                if not isinstance(attempt_id, str) or not attempt_id or not isinstance(administrator, str) or not administrator:
                    raise ValueError("Attempt and administrator identities are required")
                if self.terminated:
                    raise RuntimeError("Service has terminated")
                if self._prepared:
                    return self._remember(command, await self._retire_prepared(command))
                if command.command_type == "prepare_stop":
                    if self.participant.component_type not in {"storage_manager", "controller"}:
                        raise ValueError("Coordinated preparation is limited to StorageManager and Controller")
                    framework_id = command.payload.get("framework_stop_attempt_id")
                    if not isinstance(framework_id, str) or not framework_id:
                        raise ValueError("Preparation requires an overall framework attempt identity")
                if command.command_type in {"stop", "prepare_stop"}:
                    if self._attempt is not None or attempt_id in self._attempts:
                        raise RuntimeError("An overlapping or reused maintenance attempt is not allowed")
                    attempt = {"stop_attempt_id": attempt_id, "target": self.participant.to_dict(),
                               "requester_id": command.source_id, "started_at": time(), "commands": [],
                               "blockers": [], "actions": [], "failures": [], "outcome": "blocked"}
                    if command.payload.get("framework_stop_attempt_id") is not None:
                        attempt["framework_stop_attempt_id"] = command.payload["framework_stop_attempt_id"]
                    with self._admission_lock:
                        self._attempt = attempt
                        if self._active_operations:
                            attempt["blockers"].append("Unfinished service operations")
                    self._attempts[attempt_id] = attempt
                    attempt["blockers"].extend(self.service.maintenance_blockers(self.ingestor, self.storage_manager))
                    attempt["blockers"].extend(self._dependency_blockers())
                else:
                    if self._attempt is None or self._attempt["stop_attempt_id"] != attempt_id:
                        raise RuntimeError("No matching blocked maintenance attempt")
                    if self._attempt["outcome"] != "blocked":
                        raise RuntimeError("Attempt is not blocked")
                    if command.command_type == "kill" and command.payload.get("authorized") is not True:
                        raise PermissionError("Kill requires explicit administrator authorization")
                    attempt = self._attempt
                attempt["commands"].append({"command_id": command.command_id, "command_type": command.command_type,
                                             "administrator_id": administrator,
                                             "authorized": command.payload.get("authorized") is True, "requested_at": time()})
                if command.command_type == "cancel":
                    attempt["outcome"] = "failed"
                    attempt["failures"].append("Administrator cancelled forced continuation")
                    await self._preserve(attempt)
                    self._attempt = None
                    result = self._result(command, "failed", "Administrator cancelled", attempt)
                elif command.command_type in {"stop", "prepare_stop"} and attempt["blockers"]:
                    await self._preserve(attempt)
                    result = self._result(command, "blocked", "Closeout blockers", attempt)
                else:
                    force = command.command_type == "kill"
                    attempt["outcome"] = None
                    # Confirm submission/preservation before initiating orderly cleanup.
                    if not force:
                        await self._preserve(attempt, "initial")
                        with self._orderly_preservation_guard():
                            pass
                    self._closeout_started = True
                    cleanup_started = True
                    await self.service._close_maintenance_resources(force)
                    confirmed = await self.close_resources(force)
                    if confirmed is not True:
                        raise RuntimeError("Resource cleanup is unconfirmed; manual intervention required")
                    attempt["actions"].append("forced_resources_closed" if force else "orderly_resources_closed")
                    if force:
                        # Preserve actual cleanup, not a claim of confirmed retirement.
                        try:
                            await self._preserve(attempt, "cleanup_confirmed")
                        except Exception as error:
                            attempt["failures"].append(f"Evidence preservation unconfirmed: {error}")
                        if self.retire_resources is not None:
                            if await self.retire_resources(True) is not True:
                                raise RuntimeError("Operational retirement is unconfirmed; manual intervention required")
                        with self._retirement_guard(force=True):
                            self._terminated = True
                            self._attempt = None
                            attempt["actions"].append("operational_retirement_confirmed")
                            attempt["outcome"] = "completed"
                    else:
                        attempt["remaining_obligations"] = self._closeout_blockers()
                        await self._preserve(attempt, "cleanup_confirmed")
                        with self._orderly_preservation_guard():
                            pass
                        await self._preserve(attempt, "ready_for_retirement")
                        with self._orderly_preservation_guard():
                            pass
                        if command.command_type == "prepare_stop":
                            attempt["actions"].append("preparation_confirmed")
                            await self._preserve(attempt, "prepared_ready_for_retirement")
                            with self._orderly_preservation_guard():
                                self._prepared = True
                            result = self._result(command, None, None, attempt, prepared=True)
                            return self._remember(command, result)
                        # Do not hold synchronous intake/storage locks across retirement.
                        if self.retire_resources is not None:
                            if await self.retire_resources(False) is not True:
                                raise RuntimeError("Operational retirement is unconfirmed; manual intervention required")
                        with self._retirement_guard():
                            self._terminated = True
                            self._attempt = None
                        attempt["actions"].append("operational_retirement_confirmed")
                        attempt["outcome"] = "completed"
                        # The initiator retains the actual result; evidence paths may be closed.
                    result = self._result(command, "completed", None, attempt)
            except asyncio.CancelledError:
                if attempt is not None:
                    attempt["outcome"] = "failed"
                    attempt["failures"].append("Maintenance cancelled during resource closeout")
                    self._attempt = None
                    try:
                        await self._preserve(attempt)
                    except Exception:
                        pass
                    self._remember(command, self._result(command, "failed", "Maintenance was cancelled", attempt))
                raise
            except Exception as error:
                if attempt is not None:
                    attempt["failures"].append(str(error))
                    if cleanup_started:
                        try:
                            attempt["remaining_obligations"] = self._closeout_blockers()
                        except Exception as observation_error:
                            attempt["failures"].append(f"Closeout obligations unconfirmed: {observation_error}")
                    # Preservation failure before cleanup is still a pre-stop blocker.
                    outcome = "blocked" if not cleanup_started and command.command_type in {"stop", "prepare_stop"} else "failed"
                    attempt["outcome"] = outcome
                    if outcome == "blocked":
                        attempt["blockers"].append(f"Required closeout precondition: {error}")
                    if outcome == "failed":
                        self._attempt = None
                    try:
                        await self._preserve(attempt)
                    except Exception:
                        pass
                    result = self._result(command, outcome, str(error), attempt)
                else:
                    result = self._result(command, "failed", str(error))
            return self._remember(command, result)

    def _require_recovery_authorization(self, command):
        identity = command.payload.get("authorization_evidence_id")
        authorization = next((m for m in self._evidence if m.evidence_id == identity
                              and m.evidence_type == "administrator_decision"), None)
        obligation = command.payload.get("obligation")
        if (authorization is None or authorization.payload.get("decision") != "resume"
                or authorization.payload.get("target") != self.participant.to_dict()
                or not isinstance(obligation, dict) or not obligation
                or authorization.payload["details"].get("operation") != command.command_type
                or authorization.payload["details"].get("obligation") != obligation
                or authorization.payload["details"].get("command_id") != command.command_id):
            raise ValueError("Specific administrator authorization does not match command/obligation/scope")
        if not self.ingestor.has_durable_runtime_evidence(authorization):
            raise RuntimeError("Administrator authorization lacks durable Ingestor acceptance")
        following = self._evidence[self._evidence.index(authorization) + 1:]
        if any(m.evidence_type == "administrator_decision" and m.payload.get("decision") == "drop"
               and m.payload.get("details", {}).get("obligation") == obligation for m in following):
            raise ValueError("A later administrator drop superseded this authorization")
        return authorization

    @service_operation()
    async def _execute_authorized_recovery(self, command):
        attempt = {"operation": command.command_type, "command_id": command.command_id,
            "authorization_evidence_id": command.payload.get("authorization_evidence_id"),
            "obligation": deepcopy(command.payload.get("obligation")),
            "target": self.participant.to_dict(), "actual_outcome": None, "actions": [],
            "confirmation": None, "remaining_obligations": [], "recorded_at": time()}
        outcome, reason, acted = "refused", None, False
        try:
            authorization = self._require_recovery_authorization(command)
            attempt["administrator_id"] = authorization.payload["administrator_id"]
            message = RuntimeEvidenceMessage(uuid4().hex, None, "service_recovery_evidence",
                self.participant.component_id, {**deepcopy(attempt), "checkpoint": "attempt_recorded"}, True)
            unavailable_target = (self.participant.component_type == "storage_manager"
                and command.command_type == "recover_archive_write"
                and command.payload["obligation"].get("session_id") is None)
            await self._record_framework_evidence(message,
                archive=not unavailable_target and self.storage_manager._framework_evidence_write_safe(),
                require_existing_archive=True)
            intake = self.ingestor._framework_ingestor
            if intake is None:
                raise RuntimeError("Framework recovery journal is not configured")
            # Existing intake -> persistence -> admission ordering, without awaiting inside.
            with self.ingestor._intake_lock, intake._intake_lock, self.storage_manager._preservation_lock, self._admission_lock:
                self._require_recovery_authorization(command)
                if not self.ingestor.has_durable_runtime_evidence(message):
                    raise RuntimeError("Recovery attempt lacks durable Ingestor acceptance")
                if self.terminated or self._closeout_started or self._attempt is not None or self._active_operations != 1:
                    raise RuntimeError("Service admission or concurrent work prevents recovery")
                if self._dependency_blockers():
                    raise RuntimeError("Required dependency availability is unconfirmed")
                if self.participant.component_type == "storage_manager":
                    if command.command_type == "recover_archive_write":
                        action = self.service._recover_archive_write
                    elif command.command_type == "recover_session_record_write":
                        action = self.service._recover_session_record_write
                    elif command.command_type == "recover_artifact_transfer":
                        action = self.service._recover_artifact_transfer
                    else:
                        raise ValueError("Recovery action does not belong to StorageManager")
                elif self.participant.component_type == "acquisition_node":
                    if command.command_type == "preserve_scientific_artifact":
                        action = self.service._preserve_scientific_artifact
                    elif command.command_type == "cleanup_device_resources":
                        action = self.service._cleanup_device_resources
                    else:
                        raise ValueError("Recovery action does not belong to AcquisitionNode")
                else:
                    raise ValueError("No new operational recovery action is supported for this service")
                # The owner performs final scope/prerequisite checks before its first action.
                attempt["confirmation"] = action(command, authorization, attempt)
                acted = bool(attempt["actions"])
                outcome = "succeeded"
        except asyncio.CancelledError:
            attempt["actual_outcome"] = "failed"
            attempt["remaining_obligations"] = ["Recovery cancelled; no unconfirmed action is reported completed"]
            cancelled = RuntimeEvidenceMessage(uuid4().hex, None, "service_recovery_evidence",
                self.participant.component_id, deepcopy(attempt), True)
            preservation = self._evidence_status(cancelled)
            try:
                await self._record_framework_evidence(cancelled, preservation, archive=False)
            finally:
                self._remember(command, RuntimeCommandResultMessage(uuid4().hex, command.command_id, None,
                    self.participant.component_id, command.source_id, "failed", False,
                    "Recovery cancelled", {**deepcopy(attempt), "preservation": deepcopy(preservation)}))
            raise
        except Exception as error:
            acted = bool(attempt["actions"])
            outcome = "failed" if acted else "refused"
            reason = f"{type(error).__name__}: {error}"
            attempt["remaining_obligations"] = [reason]
        attempt["actual_outcome"] = outcome
        attempt["recorded_at"] = time()
        message = RuntimeEvidenceMessage(uuid4().hex, None, "service_recovery_evidence",
            self.participant.component_id, deepcopy(attempt), True)
        preservation = self._evidence_status(message)
        with self._admission_lock:
            self._evidence.append(message)
        # Cancellation during submission cannot turn this command into another attempt.
        self._remember(command, RuntimeCommandResultMessage(uuid4().hex, command.command_id, None,
            self.participant.component_id, command.source_id,
            "succeeded" if outcome == "succeeded" else "failed", outcome == "succeeded", reason,
            {**deepcopy(attempt), "preservation": {**deepcopy(preservation),
                "preservation_warning": "Recovery outcome submission has not completed"}}))
        if command.command_type == "recover_artifact_transfer" and attempt.get("collection_evidence_id"):
            collection_message = next(m for m in self.service._collection_evidence
                           if m.evidence_id == attempt["collection_evidence_id"])
            submission = {"publication_confirmed": False, "acceptance_confirmed": False, "preservation_warning": None}
            try:
                publisher = self.service._evidence_publisher or self.evidence_publisher
                if publisher is not None:
                    await publisher(collection_message)
                    submission["publication_confirmed"] = True
                else:
                    self.ingestor.receive_runtime_evidence(collection_message)
                submission["acceptance_confirmed"] = await self.ingestor.await_durable_runtime_evidence(collection_message, self.preservation_window_s)
                if not submission["acceptance_confirmed"]:
                    raise RuntimeError("Collection evidence durable acceptance is unconfirmed")
            except Exception as error:
                submission["preservation_warning"] = str(error)
            attempt["collection_evidence_submission"] = submission
        preservation = await self._record_framework_evidence(message, preservation,
            archive=self.storage_manager._framework_evidence_write_safe(), require_existing_archive=True)
        return RuntimeCommandResultMessage(uuid4().hex, command.command_id, None,
            self.participant.component_id, command.source_id,
            "succeeded" if outcome == "succeeded" else "failed", outcome == "succeeded", reason,
            {**attempt, "preservation": preservation})

    @contextmanager
    def _prepared_preservation_guard(self, *, force=False):
        if self._framework_communication is not None:
            with self._admission_lock:
                if not force and any(not self.evidence_preserved(m) for m in self.required_evidence()):
                    raise RuntimeError("Prepared producer evidence boundary is unconfirmed")
                yield {"runtime_evidence": [m.to_dict() for m in self.required_evidence()]}
            return
        # Preparation already confirmed journal acceptance. Recheck current durable
        # contents through retirement commit without requiring retired Ingestor intake.
        preservation = (nullcontext(None) if force else
                        self.storage_manager.framework_preservation_guard(require_closeout=True))
        with preservation as confirmation, self._admission_lock:
            if force:
                yield
                return
            if confirmation is None:
                raise RuntimeError("Prepared closeout archive preservation is unconfirmed")
            archived = {m["evidence_id"]: m for m in confirmation["runtime_evidence"]}
            if any(m.is_persistent and archived.get(m.evidence_id) != m.to_dict() for m in self._evidence):
                raise RuntimeError("Prepared closeout evidence is no longer preserved")
            yield

    async def _retire_prepared(self, command):
        attempt = self._attempt
        if (attempt is None or command.payload.get("stop_attempt_id") != attempt["stop_attempt_id"]
                or command.payload.get("framework_stop_attempt_id") != attempt["framework_stop_attempt_id"]
                or command.source_id != attempt["requester_id"]):
            return self._result(command, "failed", "No matching prepared framework attempt")
        if command.command_type not in {"stop", "kill", "cancel"}:
            return self._result(command, "failed", "Preparation already confirmed")
        if attempt["outcome"] not in {None, "blocked"}:
            return self._result(command, "failed", "Prepared attempt already failed; obligations remain outstanding", attempt)
        if command.command_type == "kill" and (attempt["outcome"] != "blocked" or command.payload.get("authorized") is not True):
            return self._result(command, "failed", "Kill requires a matching blocked attempt and explicit authorization")
        attempt["commands"].append({"command_id": command.command_id, "command_type": command.command_type,
            "administrator_id": command.payload["administrator_id"],
            "authorized": command.payload.get("authorized") is True, "requested_at": time()})
        try:
            if command.command_type == "cancel":
                raise RuntimeError("Administrator cancelled forced continuation")
            force = command.command_type == "kill"
            with self._prepared_preservation_guard(force=force):
                blockers = self._closeout_blockers()
                if blockers and not force:
                    attempt["blockers"].extend(blockers)
                    attempt["outcome"] = "blocked"
                    return self._result(command, "blocked", "Closeout blockers", attempt)
            if self.retire_resources is not None and await self.retire_resources(force) is not True:
                raise RuntimeError("Operational retirement is unconfirmed; manual intervention required")
            with self._prepared_preservation_guard(force=force):
                if self._active_operations:
                    raise RuntimeError("Service operations remain active")
                if not force and self._closeout_blockers():
                    raise RuntimeError("Closeout obligations changed before retirement")
                self._terminated = True
                self._attempt = None
                attempt["actions"].append("operational_retirement_confirmed")
                attempt["outcome"] = "completed"
            return self._result(command, "completed", None, attempt)
        except asyncio.CancelledError:
            attempt["outcome"] = "failed"
            attempt["failures"].append("Prepared retirement cancelled; confirmation unavailable")
            self._remember(command, self._result(command, "failed", attempt["failures"][-1], attempt))
            raise
        except Exception as error:
            attempt["outcome"] = "failed"
            attempt["failures"].append(str(error))
            try:
                attempt["remaining_obligations"] = self._closeout_blockers()
            except Exception as observation_error:
                attempt["failures"].append(f"Closeout obligations unconfirmed: {observation_error}")
            # Later confirmations are retained results, not post-Ingestor archive writes.
            return self._result(command, "failed", str(error), attempt)

    def _dependency_blockers(self):
        return [f"Operational dependency: {participant.component_type}/{participant.component_id}"
                for participant, operational in self.operational_dependents.items() if operational() is not False]

    def _closeout_blockers(self):
        blockers = self.service.maintenance_blockers(self.ingestor, self.storage_manager)
        blockers.extend(self._dependency_blockers())
        with self._admission_lock:
            if self._active_operations:
                blockers.append("Unfinished service operations")
        return blockers

    @contextmanager
    def _retirement_guard(self, *, force=False):
        if not force:
            with self._orderly_preservation_guard() as confirmation:
                if self.participant.component_type == "ingestor":
                    self.storage_manager._retain_framework_closeout_compilation(confirmation)
                yield
            return
        intake = (self.ingestor._framework_ingestor
                  if self.participant.component_type == "ingestor" else None)
        # Forced retirement may lack archival confirmation, but must retain the
        # actual required intake coverage rather than blessing an older archive.
        with (
            self.ingestor._intake_lock if intake is not None else nullcontext(),
            intake._intake_lock if intake is not None else nullcontext(),
            self.storage_manager.framework_preservation_guard() if intake is not None else nullcontext(),
            self._admission_lock,
        ):
            if self._active_operations:
                raise RuntimeError("Forced termination remains unconfirmed; service operations are active")
            if intake is not None:
                self.storage_manager._retain_framework_closeout_compilation(
                    self.ingestor.compile_framework_runtime_evidence())
            yield

    @contextmanager
    def _orderly_preservation_guard(self):
        if self._framework_communication is not None:
            with self._admission_lock:
                if any(not self.evidence_preserved(m) for m in self.required_evidence()):
                    raise RuntimeError("Producer evidence boundary changed or preservation is unconfirmed")
                blockers = self._closeout_blockers()
                if blockers:
                    raise RuntimeError("Closeout obligations changed: " + "; ".join(blockers))
                yield {"runtime_evidence": [m.to_dict() for m in self.required_evidence()]}
            return
        # Same intake -> storage -> admission order as the existing synchronous commit.
        with self.ingestor._intake_lock, self.ingestor.framework_preservation_guard(self.storage_manager) as confirmation, self._admission_lock:
            archived = {message["evidence_id"]: message for message in confirmation["runtime_evidence"]}
            for message in self._evidence:
                if message.is_persistent and (not self.ingestor.has_durable_runtime_evidence(message)
                        or archived.get(message.evidence_id) != message.to_dict()):
                    raise RuntimeError(f"Outstanding maintenance evidence: {message.evidence_id}")
            blockers = self._closeout_blockers()
            if blockers:
                raise RuntimeError("Closeout obligations changed: " + "; ".join(blockers))
            yield confirmation

    async def _preserve(self, attempt, checkpoint=None):
        payload = deepcopy({**attempt, "recorded_at": time()})
        if checkpoint is not None:
            payload["checkpoint"] = checkpoint
        message = RuntimeEvidenceMessage(uuid4().hex, None, "service_maintenance_evidence",
                                         self.participant.component_id, payload, True)
        await self._preserve_message(message)

    async def _preserve_message(self, message, status=None, *, archive=True, require_existing_archive=False):
        with self._admission_lock:
            if not any(retained is message for retained in self._evidence):
                self._evidence.append(message)
        if self._framework_communication is not None:
            boundary = self.required_evidence()
            for required in boundary:
                if not self.evidence_preserved(required):
                    await self.evidence_publisher(required)
            if status is not None:
                status["publication_confirmed"] = True
            if not archive:
                raise RuntimeError("Archival is unconfirmed; remote recovery is not automatic")
            result = await self._framework_communication.request_persistence_command(
                self._framework_ingestor, "preserve_service_evidence", None,
                {"evidence": [m.to_dict() for m in boundary], "acceptance_window_s": self.preservation_window_s},
                self.preservation_window_s, command_id=uuid4().hex)
            if (result is None or not result.success or result.payload.get("acceptance_confirmed") is not True
                    or result.payload.get("archival_confirmed") is not True
                    or result.payload.get("storage_participant") != self._framework_storage.to_dict()
                    or result.payload.get("evidence") != [m.to_dict() for m in boundary]):
                raise RuntimeError("Authoritative producer evidence preservation is unconfirmed")
            with self._admission_lock:
                self._remote_preserved_evidence = {(m.session_id, m.evidence_id): m.to_dict() for m in boundary}
            if status is not None:
                status.update(acceptance_confirmed=True, archival_confirmed=True)
            return
        if self.evidence_publisher is None:
            if self.ingestor is None:
                raise RuntimeError("Framework Ingestor is unavailable")
            audit = self.ingestor.receive_runtime_evidence(message)
            if not audit.accepted:
                raise RuntimeError("Maintenance evidence was rejected by Ingestor")
        else:
            await self.evidence_publisher(message)
            if status is not None:
                status["publication_confirmed"] = True
        if self.ingestor is None:
            raise RuntimeError("Framework Ingestor acceptance is unconfirmed")
        if not await self.ingestor.await_durable_runtime_evidence(message, self.preservation_window_s):
            raise RuntimeError("Framework evidence lacks durable Ingestor acceptance")
        if status is not None:
            status["acceptance_confirmed"] = True
        if not archive:
            raise RuntimeError("Archival not attempted while current preservation is unconfirmed")
        if self.storage_manager is None:
            raise RuntimeError("Framework StorageManager is unavailable")
        intake = self.ingestor._framework_ingestor
        if intake is None:
            raise RuntimeError("Framework recovery journal is not configured")
        with self.ingestor._intake_lock, intake._intake_lock, self.storage_manager._preservation_lock:
            if require_existing_archive and not self.storage_manager._framework_evidence_write_safe():
                raise RuntimeError("Current archival is unconfirmed; this evidence cannot repair it")
            self.storage_manager.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())
            with self.ingestor.framework_preservation_guard(self.storage_manager):
                pass
        if status is not None:
            status["archival_confirmed"] = True

    def _result(self, command, outcome, reason, attempt=None, *, prepared=False):
        return RuntimeCommandResultMessage(uuid4().hex, command.command_id, None, self.participant.component_id,
                                           command.source_id, "succeeded" if outcome == "completed" or prepared else "failed",
                                           outcome == "completed" or prepared, reason,
                                           {"outcome": outcome, "termination_confirmed": self.terminated,
                                            "manual_intervention_required": command.command_type == "kill" and outcome == "failed" and attempt is not None and self._closeout_started,
                                            "prepared": prepared,
                                            "attempt": deepcopy(attempt) if attempt is not None else None})

    def _remember(self, command, result):
        self._commands[command.command_id] = deepcopy(command.to_dict())
        self._results[command.command_id] = result
        return RuntimeCommandResultMessage.from_dict(deepcopy(result.to_dict()))
