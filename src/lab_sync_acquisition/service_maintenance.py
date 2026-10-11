"""Individual-service administrative attempts over existing runtime messages."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from inspect import iscoroutinefunction
from threading import current_thread
from time import time
from uuid import uuid4

from lab_sync_acquisition.communication import RuntimeCommandMessage, RuntimeCommandResultMessage, RuntimeEvidenceMessage, RuntimeParticipant

_service_calls = ContextVar("service_calls", default=())


def service_operation(*, new_work: bool = False):
    """Guard operational calls while allowing existing obligations during blocked maintenance."""
    def decorate(method):
        @contextmanager
        def enter(owner):
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
    """Target-owned cleanup and retirement, not a framework shutdown coordinator.

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
                 retire_resources: Callable[[bool], Awaitable[bool]] | None = None):
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
        service._maintenance = self

    @property
    def _active_operations(self):
        return self.service._active_service_operations

    @property
    def terminated(self) -> bool:
        """Confirmed operational-service retirement, not a claim of OS process death."""
        return self._terminated

    @property
    def command_results(self):
        """Last confirmed local results, including correlation and actual closeout outcome."""
        return tuple(RuntimeCommandResultMessage.from_dict(deepcopy(r.to_dict())) for r in self._results.values())

    @property
    def evidence(self):
        """Producer-owned attempt evidence retained even when preservation fails."""
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict())) for m in self._evidence)

    async def execute_command(self, command: RuntimeCommandMessage) -> RuntimeCommandResultMessage:
        """Execute correlated stop/kill/cancel once, retaining original blockers and authorization."""
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
                if command.command_type not in {"stop", "kill", "cancel"}:
                    raise ValueError("Unsupported maintenance command")
                attempt_id = command.payload.get("stop_attempt_id")
                administrator = command.payload.get("administrator_id")
                if not isinstance(attempt_id, str) or not attempt_id or not isinstance(administrator, str) or not administrator:
                    raise ValueError("Attempt and administrator identities are required")
                if self.terminated:
                    raise RuntimeError("Service has terminated")
                if command.command_type == "stop":
                    if self._attempt is not None or attempt_id in self._attempts:
                        raise RuntimeError("An overlapping or reused maintenance attempt is not allowed")
                    attempt = {"stop_attempt_id": attempt_id, "target": self.participant.to_dict(),
                               "requester_id": command.source_id, "started_at": time(), "commands": [],
                               "blockers": [], "actions": [], "failures": [], "outcome": "blocked"}
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
                elif command.command_type == "stop" and attempt["blockers"]:
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
                        with self._admission_lock:
                            if self._active_operations:
                                raise RuntimeError("Forced termination remains unconfirmed; service operations are active")
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
                        # Do not hold synchronous intake/storage locks across retirement.
                        if self.retire_resources is not None:
                            if await self.retire_resources(False) is not True:
                                raise RuntimeError("Operational retirement is unconfirmed; manual intervention required")
                        with self._orderly_preservation_guard():
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
                    outcome = "blocked" if not cleanup_started and command.command_type == "stop" else "failed"
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
    def _orderly_preservation_guard(self):
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
            yield

    async def _preserve(self, attempt, checkpoint=None):
        payload = deepcopy({**attempt, "recorded_at": time()})
        if checkpoint is not None:
            payload["checkpoint"] = checkpoint
        message = RuntimeEvidenceMessage(uuid4().hex, None, "service_maintenance_evidence",
                                         self.participant.component_id, payload, True)
        self._evidence.append(message)
        if self.evidence_publisher is None:
            audit = self.ingestor.receive_runtime_evidence(message)
            if not audit.accepted:
                raise RuntimeError("Maintenance evidence was rejected by Ingestor")
        else:
            await self.evidence_publisher(message)
        if not await self.ingestor.await_durable_runtime_evidence(message, self.preservation_window_s):
            raise RuntimeError("Maintenance evidence lacks durable Ingestor acceptance")
        self.storage_manager.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())
        with self.ingestor.framework_preservation_guard(self.storage_manager):
            pass

    def _result(self, command, outcome, reason, attempt=None):
        return RuntimeCommandResultMessage(uuid4().hex, command.command_id, None, self.participant.component_id,
                                           command.source_id, "succeeded" if outcome == "completed" else "failed",
                                           outcome == "completed", reason,
                                           {"outcome": outcome, "termination_confirmed": self.terminated,
                                            "manual_intervention_required": command.command_type == "kill" and outcome == "failed" and attempt is not None and self._closeout_started,
                                            "attempt": deepcopy(attempt) if attempt is not None else None})

    def _remember(self, command, result):
        self._commands[command.command_id] = deepcopy(command.to_dict())
        self._results[command.command_id] = result
        return RuntimeCommandResultMessage.from_dict(deepcopy(result.to_dict()))
