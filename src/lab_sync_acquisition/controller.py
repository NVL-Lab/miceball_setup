"""Sequential single-session Controller v1 orchestration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, TYPE_CHECKING
from collections.abc import Mapping
from uuid import uuid4

from lab_sync_acquisition.acquisition_health import HealthInterpretationEvidence
from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.communication import (
    GroupCommandOutcome,
    RuntimeEvidenceMessage,
    RuntimeCommandResultMessage,
    RuntimeParticipant,
    build_runtime_subject,
)
from lab_sync_acquisition.device_adapter import DeviceReadiness
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.experiment_runtime import (
    ActiveExperimentRuntimeContext,
    ExperimentRuntimeHealthMapping,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness, apply_dependency_readiness
from lab_sync_acquisition.session import (
    ExpectedParticipant,
    Session,
    SessionConfig,
    SessionState,
    ScientificOutputSelection,
)
from lab_sync_acquisition.storage import PersistentStorageManager
from lab_sync_acquisition.synchronization import SynchronizationManager

if TYPE_CHECKING:
    from lab_sync_acquisition.nats_communication import NatsControllerCommunication, NatsIngestorCommunication


@dataclass(frozen=True)
class ControllerCommandResult:
    """Result of one sequential Controller command."""

    command: str
    succeeded: bool
    details: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return plain command-result evidence."""

        return {
            "command": self.command,
            "succeeded": self.succeeded,
            "details": self.details,
            "error": self.error,
        }


@dataclass(frozen=True)
class ControllerActionDecision:
    """Evidence-only Controller decision for one health interpretation."""

    originating_observation_id: str
    session_id: str
    experiment_id: str
    live_source_id: str
    acquisition_health_policy: str
    interpretation_label: str
    controller_decision: str
    decision_time_s: float | None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return plain Controller action-decision evidence."""

        return {
            "originating_observation_id": self.originating_observation_id,
            "session_id": self.session_id,
            "experiment_id": self.experiment_id,
            "live_source_id": self.live_source_id,
            "acquisition_health_policy": self.acquisition_health_policy,
            "interpretation_label": self.interpretation_label,
            "controller_decision": self.controller_decision,
            "decision_time_s": self.decision_time_s,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ControllerActionDecision:
        """Reconstruct Controller decision evidence from plain data."""

        return cls(
            originating_observation_id=data["originating_observation_id"],
            session_id=data["session_id"],
            experiment_id=data["experiment_id"],
            live_source_id=data["live_source_id"],
            acquisition_health_policy=data["acquisition_health_policy"],
            interpretation_label=data["interpretation_label"],
            controller_decision=data["controller_decision"],
            decision_time_s=data["decision_time_s"],
            details=(
                dict(data["details"])
                if data.get("details") is not None
                else None
            ),
        )


from lab_sync_acquisition.service_maintenance import service_operation


class Controller:
    """Owns one Session's local or brokered orchestration, not participant startup."""

    def __init__(
        self,
        acquisition_node: AcquisitionNode | None = None,
        ingestor: InMemoryIngestor | None = None,
        storage_manager: PersistentStorageManager | None = None,
        session_record_path: str | Path | None = None,
        synchronization_manager: SynchronizationManager | None = None,
        *,
        component_id: str = "controller",
    ) -> None:
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("Controller component_id must be a nonempty string")
        self._acquisition_node = acquisition_node
        self._service_operation_lock = RLock()
        self._active_service_operations = 0
        self._ingestor = ingestor
        self._storage_manager = storage_manager
        self._session_record_path = (
            Path(session_record_path) if session_record_path is not None else None
        )
        self._synchronization_manager = synchronization_manager
        self._component_id = component_id
        self._session: Session | None = None
        self._active_experiment_id: str | None = None
        self._active_experiment_runtime_health_mapping: tuple[
            ExperimentRuntimeHealthMapping, ...
        ] = ()
        self._last_result: ControllerCommandResult | None = None
        self._command_results: list[ControllerCommandResult] = []
        self._controller_action_decisions: list[ControllerActionDecision] = []
        self._controller_action_decision_evidence: list[RuntimeEvidenceMessage] = []
        self._archived_controller_action_decisions: dict[str, dict[str, Any]] = {}
        self._artifact_collection_in_progress = False
        self._launch_communication: NatsControllerCommunication | None = None
        self._reserved_participants: tuple[RuntimeParticipant, ...] = ()
        self._launch_result_window_s: float | None = None
        self._launch_subscriptions = ()
        self._runtime_cleanup_confirmed = False
        self._finalization_confirmation = None
        self._last_released_session: dict[str, Any] | None = None
        self._framework_shutdown_active = False
        self._framework_shutdown_attempt_id: str | None = None
        self._framework_shutdown_attempts: dict[str, dict[str, Any]] = {}
        self._reconciliation_evidence: list[RuntimeEvidenceMessage] = []
        self._acquisition_publication_active = False
        self._acquisition_marker_session: Session | None = None
        self._acquisition_marker: RuntimeEvidenceMessage | None = None
        self._acquisition_marker_confirmed = False
        self._acquisition_archival_active = False
        self._normal_stop_task: asyncio.Task[Any] | None = None
        self._kill_closeout_session: Session | None = None
        self._kill_closeout: dict[str, Any] | None = None

    @service_operation()
    async def kill_session(
        self, *, communication: NatsControllerCommunication, result_window_s: float,
        operator_authorized: bool, reason: str | None = None,
    ) -> ControllerCommandResult:
        """Explicit forced closeout; preserve available evidence without confirming Normal Stop."""
        from math import isfinite

        session = self._require_session()
        admitted = False
        try:
            with self._service_operation_lock:
                if operator_authorized is not True:
                    raise ValueError("Kill Session requires explicit operator authorization")
                if (communication is not self._launch_communication or self._ingestor is None
                        or self._ingestor.session_id != session.session_id or self._storage_manager is None):
                    raise ValueError("Kill requires the launched communication and original evidence owners")
                if (type(result_window_s) not in {int, float} or not isfinite(result_window_s)
                        or result_window_s <= 0):
                    raise ValueError("Kill requires a finite positive result window")
                if (self._normal_stop_task is not None or self._acquisition_archival_active
                        or self._acquisition_publication_active or self._artifact_collection_in_progress):
                    raise RuntimeError("Session closeout is already in progress")
                if session.current_state not in {SessionState.RUNNING, SessionState.STOPPING, SessionState.ABORTED}:
                    raise RuntimeError("Kill requires a running, stopping, or already aborted Session")
                if self._kill_closeout_session is not session:
                    self._kill_closeout_session = session
                    self._kill_closeout = {"session_id": session.session_id, "reason": reason,
                        "participants": [], "command_ids": {},
                        "uncertainties": [{"reason": "Complete acquisition receipt is unconfirmed"}]}
                self._normal_stop_task = asyncio.current_task()
                admitted = True
                # Retain the Q019 association before any suspension, including cancellation.
                self._acquisition_marker_session = session
                if session.current_state == SessionState.RUNNING:
                    if self._active_experiment_id is not None:
                        session.record_experiment_lifecycle(self._active_experiment_id,
                            "experiment_abort", self._current_session_time_s(), {"reason": reason})
                        self._active_experiment_id = None
                        self._active_experiment_runtime_health_mapping = ()
                    session.stop(reason)
                if session.current_state == SessionState.STOPPING:
                    session.abort(reason)
            confirmed = {item["participant"]["component_id"] for item in self._kill_closeout["participants"]
                         if item["cleanup_confirmed"]}
            participants = tuple(self._reserved_participants) + tuple(
                p for p in session.configuration.expected_runtime_participants
                if p.component_type == "synchronization_manager")
            for participant in participants:
                if participant.component_id in confirmed:
                    continue
                outcome = {"participant": participant.to_dict(), "cleanup_confirmed": False}
                try:
                    result = await communication.request_command(participant, "stop_runtime",
                        session.session_id, {}, result_window_s,
                        command_id=self._kill_closeout["command_ids"].setdefault(
                            (participant.component_type, participant.component_id), uuid4().hex))
                    outcome["cleanup_confirmed"] = (result is not None and result.success is True
                        and result.status == "succeeded")
                    outcome["result"] = result.to_dict() if result is not None else None
                except Exception as error:
                    outcome["error"] = f"{type(error).__name__}: {error}"
                if self._session is not session or self._kill_closeout_session is not session:
                    raise RuntimeError("Controller Session binding changed during Kill")
                self._kill_closeout["participants"].append(outcome)
            self._runtime_cleanup_confirmed = bool(participants) and all(
                any(item["participant"] == p.to_dict() and item["cleanup_confirmed"]
                    for item in self._kill_closeout["participants"]) for p in participants)
            details = self._preserve_kill_closeout(session)
            return self._record_successful_command("kill_session", details)
        except asyncio.CancelledError:
            if admitted and self._session is session:
                self._kill_closeout["uncertainties"].append({"reason": "Kill interrupted; participant cleanup is unconfirmed"})
                try:
                    self._preserve_kill_closeout(session)
                except Exception as error:
                    self._kill_closeout["preservation_warning"] = f"{type(error).__name__}: {error}"
            raise
        except Exception as error:
            if self._session is not session:
                return ControllerCommandResult("kill_session", False,
                    {"session_id": session.session_id}, f"{type(error).__name__}: {error}")
            return self._record_failed_command("kill_session", error,
                {"session_id": session.session_id, "archive_closed": False,
                 "preservation_confirmed": False})
        finally:
            if admitted:
                with self._service_operation_lock:
                    if self._normal_stop_task is asyncio.current_task():
                        self._normal_stop_task = None

    def _preserve_kill_closeout(self, session: Session) -> dict[str, Any]:
        """Preserve exact available intake under existing intake/persistence/admission guards."""
        intake = self._ingestor
        with intake.durable_runtime_evidence_history_guard(
                session.session_id, intake.recovery_journal_path, intake.accepted_runtime_evidence) as confirmed:
            if not confirmed:
                raise RuntimeError("Available Kill evidence journal coverage is unconfirmed")
            with self._storage_manager.session_preservation_guard(session.session_id), self._service_operation_lock:
                if self._session is not session or intake.session_id != session.session_id:
                    raise RuntimeError("Session binding changed during Kill")
                uncertainties = deepcopy(self._kill_closeout["uncertainties"])
                uncertainties.extend(deepcopy(self._kill_closeout["participants"]))
                uncertainties.extend({"participant": p.to_dict(), "reservation_release_confirmed": False,
                    "reason": "Reservation retained; existing node-owned release safety remains required"}
                    for p in self._reserved_participants)
                available = {m.evidence_id for m in intake.accepted_runtime_evidence}
                uncertainties.extend({"evidence_id": identity, "acceptance_confirmed": False,
                    "reason": "Required Controller evidence is retained but not durably accepted"}
                    for identity in self._controller_owned_session_evidence_snapshot(session.session_id)
                    if identity not in available)
                observed = {item["participant"]["component_id"] for item in self._kill_closeout["participants"]}
                uncertainties.extend({"participant": p.to_dict(), "cleanup_confirmed": False,
                    "reason": "No confirmed cleanup result; hardware/resource obligations remain"}
                    for p in session.configuration.expected_runtime_participants
                    if p.component_type in {"acquisition_node", "synchronization_manager"}
                    and p.component_id not in observed)
                current = self._storage_manager.get_persisted_session_preservation_confirmation(session.session_id)
                if current is None:
                    self._storage_manager.write_kill_acquisition_stage(session.session_id,
                        intake.compile_persistent_runtime_evidence(), uncertainties=uncertainties,
                        **self._session_record_evidence())
                    handoff = intake.compile_artifact_collection_handoff(session.session_id)
                    self._storage_manager.write_artifact_collection_handoff(session.session_id, handoff)
                    current = self._storage_manager.get_persisted_session_preservation_confirmation(session.session_id)
                if current is None or current["compilation_summary"].get("kill_preservation") is None:
                    raise RuntimeError("Current partial Kill preservation is unconfirmed")
                compiled = intake.compile_persistent_runtime_evidence()
                if any(current[name] != [item.to_dict() for item in compiled[name]]
                       for name in ("runtime_evidence", "ingest_audit")):
                    raise RuntimeError("Additional Kill intake requires preserved append-only recovery evidence")
                self._archived_controller_action_decisions = self._controller_decision_evidence_snapshot(session.session_id)
                self._finalization_confirmation = (self._session_ingest_state(), str(
                    self._storage_manager._session_directory(session.session_id) / "session_record_final.json"))
                return {"session_id": session.session_id, "session_state": session.current_state.value,
                    "stage_a_complete": False, "archive_closed": False, "preservation_confirmed": True,
                    "participant_cleanup_confirmed": self._runtime_cleanup_confirmed,
                    "participants": deepcopy(self._kill_closeout["participants"]),
                    "uncertainties": uncertainties,
                    "artifact_collection_handoff": current["artifact_collection_handoff"]}

    @service_operation()
    async def normal_stop_session(
        self, *, communication: NatsControllerCommunication,
        receiving: NatsIngestorCommunication, result_window_s: float,
        reason: str | None = None,
    ) -> ControllerCommandResult:
        """Stop a launched Session and confirm Stage A/handoff before completion, not collection."""
        from math import isfinite

        session = self._require_session()
        admitted = False
        try:
            with self._service_operation_lock:
                if (self._normal_stop_task is not None or self._acquisition_publication_active
                        or self._acquisition_archival_active or self._artifact_collection_in_progress):
                    raise RuntimeError("Session closeout is already in progress")
                if (communication is not self._launch_communication or self._ingestor is None
                        or receiving._ingestor is not self._ingestor or self._storage_manager is None):
                    raise ValueError("Normal Stop requires the launched communication and matching evidence owners")
                if (isinstance(result_window_s, bool) or not isinstance(result_window_s, (int, float))
                        or not isfinite(result_window_s) or result_window_s <= 0):
                    raise ValueError("Normal Stop requires a finite positive result window")
                if session.current_state not in {SessionState.RUNNING, SessionState.STOPPING, SessionState.COMPLETED}:
                    raise RuntimeError("Normal Stop requires a running, stopping, or normally completed Session")
                # Retain Q019 obligations even if shutdown fails before producing a marker.
                if self._acquisition_marker_session is not session:
                    self._acquisition_marker_session = session
                    self._acquisition_marker = None
                    self._acquisition_marker_confirmed = False
                self._normal_stop_task = asyncio.current_task()
                admitted = True
            if session.current_state == SessionState.RUNNING:
                stopped = await self.stop_launched_session(reason)
                if not stopped.succeeded:
                    raise RuntimeError(stopped.error)
            if self._session is not session:
                raise RuntimeError("Controller Session binding changed during Normal Stop")
            if session.current_state == SessionState.STOPPING:
                published = await self.publish_acquisition_evidence_completion(
                    communication=communication, result_window_s=result_window_s)
                if not published.succeeded:
                    raise RuntimeError(published.error)
                archived = await self.archive_acquisition_evidence(communication=receiving)
                if not archived.succeeded:
                    raise RuntimeError(archived.error)
                handoff = self.preserve_artifact_collection_handoff()
                if not handoff.succeeded:
                    raise RuntimeError(handoff.error)
            details = self._complete_preserved_acquisition(session)
            return self._record_successful_command("normal_stop_session", details)
        except Exception as error:
            if self._session is not session:
                return ControllerCommandResult("normal_stop_session", False,
                    {"session_id": session.session_id}, f"{type(error).__name__}: {error}")
            return self._record_failed_command("normal_stop_session", error,
                {"session_id": session.session_id})
        finally:
            if admitted:
                with self._service_operation_lock:
                    self._normal_stop_task = None

    def _complete_preserved_acquisition(self, session: Session) -> dict[str, Any]:
        """Commit completion while current journal, Stage A, and handoff coverage are protected."""
        intake = self._ingestor
        if intake is None or self._storage_manager is None:
            raise RuntimeError("Normal completion requires Ingestor and StorageManager")
        with intake.durable_runtime_evidence_history_guard(
                session.session_id, intake.recovery_journal_path, intake.accepted_runtime_evidence) as confirmed:
            if not confirmed:
                raise RuntimeError("Current acquisition journal coverage is unconfirmed")
            with self._storage_manager.session_preservation_guard(session.session_id), self._service_operation_lock:
                if (self._session is not session or intake.session_id != session.session_id
                        or session.current_state not in {SessionState.STOPPING, SessionState.COMPLETED}
                        or not self._runtime_cleanup_confirmed or self._active_experiment_id is not None
                        or self._acquisition_marker_session is not session or not self._acquisition_marker_confirmed
                        or self._acquisition_publication_active or self._acquisition_archival_active
                        or self._artifact_collection_in_progress):
                    raise RuntimeError("Normal acquisition completion prerequisites are unconfirmed")
                archived = self._storage_manager.get_acquisition_stage_preservation_confirmation(session.session_id)
                compiled = intake.compile_persistent_runtime_evidence()
                if archived is None or any(json.dumps(archived[name], sort_keys=True) != json.dumps(
                        [item.to_dict() for item in compiled[name]], sort_keys=True)
                        for name in ("runtime_evidence", "ingest_audit")):
                    raise RuntimeError("Current complete Stage A preservation is unconfirmed")
                record = archived["session_record"]
                if (json.dumps(record.get("accepted_acquisition_envelopes"), sort_keys=True) != json.dumps(
                        [item.to_dict() for item in intake.accepted_envelopes], sort_keys=True)
                        or json.dumps(record.get("ingest_audit_records"), sort_keys=True) != json.dumps(
                            [item.to_dict() for item in intake.ingest_audit], sort_keys=True)):
                    raise RuntimeError("Current acquisition-envelope and audit preservation is unconfirmed")
                actual = {message["evidence_id"]: message for message in archived["runtime_evidence"]}
                required = self._controller_owned_session_evidence_snapshot(session.session_id)
                if any(json.dumps(actual.get(identity), sort_keys=True) != json.dumps(contents, sort_keys=True)
                       for identity, contents in required.items()):
                    raise RuntimeError("Required Controller-owned evidence is missing from Stage A")
                if archived["compilation_summary"].get("acquisition_evidence_completion", {}).get("evidence_id") != self._acquisition_marker.evidence_id:
                    raise RuntimeError("Stage A does not preserve this Session's completion marker")
                handoff = intake.compile_artifact_collection_handoff(session.session_id)
                if json.dumps(self._storage_manager.read_artifact_collection_handoff(session.session_id), sort_keys=True) != json.dumps(handoff, sort_keys=True):
                    raise RuntimeError("Current durable artifact handoff is unconfirmed")
                record_path = self._storage_manager._session_directory(session.session_id) / "session_record_final.json"
                if session.current_state == SessionState.STOPPING:
                    session.complete()
                self._archived_controller_action_decisions = self._controller_decision_evidence_snapshot(session.session_id)
                self._finalization_confirmation = (self._session_ingest_state(), str(record_path))
                return {"session_id": session.session_id, "session_state": session.current_state.value,
                        "stage_a_complete": True, "archive_closed": False,
                        "session_record_path": str(record_path),
                        "artifact_collection_handoff": handoff}

    @service_operation()
    async def archive_acquisition_evidence(
        self, *, communication: NatsIngestorCommunication,
    ) -> ControllerCommandResult:
        """Coordinate verified Stage A persistence without completing or releasing the Session."""
        session = self._require_session()
        admitted = False
        try:
            with self._service_operation_lock:
                if self._normal_stop_task is not None and self._normal_stop_task is not asyncio.current_task():
                    raise RuntimeError("Normal Stop is in progress")
                if self._acquisition_archival_active or self._acquisition_publication_active or self._artifact_collection_in_progress:
                    raise RuntimeError("Acquisition publication or persistence is already in progress")
                if (session.current_state != SessionState.STOPPING or not self._runtime_cleanup_confirmed
                        or self._acquisition_marker_session is not session or not self._acquisition_marker_confirmed):
                    raise RuntimeError("Confirmed cleanup and the closing Session's published marker are required")
                if self._ingestor is None or communication._ingestor is not self._ingestor or self._storage_manager is None:
                    raise RuntimeError("Matching Ingestor receiving and StorageManager references are required")
                marker = self._acquisition_marker
                self._acquisition_archival_active = admitted = True
            receipt = await communication.verify_acquisition_evidence_receipt(marker)
            if receipt.get("durable_receipt_confirmed") is not True:
                raise RuntimeError(f"Acquisition receipt is unconfirmed: {receipt.get('reason')}")
            intake = self._ingestor
            with intake.durable_runtime_evidence_history_guard(
                    session.session_id, intake.recovery_journal_path, intake.accepted_runtime_evidence) as confirmed:
                if not confirmed:
                    raise RuntimeError("Current acquisition journal coverage is unconfirmed")
                # Match existing closeout lock order: intake, storage, then admission.
                with self._storage_manager.session_preservation_guard(session.session_id), self._service_operation_lock:
                    if self._session is not session or intake.session_id != session.session_id:
                        raise RuntimeError("Session binding changed during Stage A verification")
                    compiled = intake.compile_persistent_runtime_evidence()
                    required = self._controller_owned_session_evidence_snapshot(session.session_id)
                    actual = {message.evidence_id: message.to_dict() for message in compiled["runtime_evidence"]}
                    if any(json.dumps(actual.get(identity), sort_keys=True) != json.dumps(contents, sort_keys=True)
                           for identity, contents in required.items()):
                        raise RuntimeError("Required Controller-owned evidence is missing from acquisition compilation")
                    ingest_state = self._session_ingest_state()
                    paths = self._storage_manager.write_acquisition_stage(
                        session.session_id, compiled, receipt=receipt, **self._session_record_evidence())
                    confirmation = self._storage_manager.get_acquisition_stage_preservation_confirmation(session.session_id)
                    if (confirmation is None or ingest_state != self._session_ingest_state()
                            or required != self._controller_owned_session_evidence_snapshot(session.session_id)
                            or any(json.dumps(confirmation[name], sort_keys=True) != json.dumps(
                                [item.to_dict() for item in compiled[name]], sort_keys=True)
                                for name in ("runtime_evidence", "ingest_audit"))):
                        raise RuntimeError("Current complete Stage A preservation is unconfirmed")
                    return self._record_successful_command("archive_acquisition_evidence", {
                        "session_id": session.session_id, "stage_a_complete": True, "archive_closed": False,
                        "receipt": receipt, "paths": {name: str(path) for name, path in paths.items()},
                    })
        except Exception as error:
            if self._session is not session:
                return ControllerCommandResult("archive_acquisition_evidence", False,
                    {"session_id": session.session_id}, f"{type(error).__name__}: {error}")
            return self._record_failed_command("archive_acquisition_evidence", error)
        finally:
            if admitted:
                with self._service_operation_lock:
                    self._acquisition_archival_active = False

    @service_operation()
    def preserve_artifact_collection_handoff(self) -> ControllerCommandResult:
        """Preserve the protected closeout handoff after Stage A, without advancing lifecycle."""
        session = self._require_session()
        try:
            intake = self._ingestor
            if intake is None or self._storage_manager is None:
                raise RuntimeError("Handoff preservation requires Ingestor and StorageManager")
            with intake.durable_runtime_evidence_history_guard(
                    session.session_id, intake.recovery_journal_path, intake.accepted_runtime_evidence) as confirmed:
                if not confirmed:
                    raise RuntimeError("Current artifact evidence journal coverage is unconfirmed")
                with self._storage_manager.session_preservation_guard(session.session_id), self._service_operation_lock:
                    if self._normal_stop_task is not None and self._normal_stop_task is not asyncio.current_task():
                        raise RuntimeError("Normal Stop is in progress")
                    if (self._session is not session or intake.session_id != session.session_id
                            or session.current_state != SessionState.STOPPING or not self._runtime_cleanup_confirmed
                            or self._acquisition_archival_active or self._artifact_collection_in_progress):
                        raise RuntimeError("Handoff requires the closing Session and completed acquisition persistence")
                    archived = self._storage_manager.get_acquisition_stage_preservation_confirmation(session.session_id)
                    compiled = intake.compile_persistent_runtime_evidence()
                    if archived is None or any(json.dumps(archived[name], sort_keys=True) != json.dumps(
                            [item.to_dict() for item in compiled[name]], sort_keys=True)
                            for name in ("runtime_evidence", "ingest_audit")):
                        raise RuntimeError("Current Stage A coverage must be confirmed before handoff preservation")
                    handoff = intake.compile_artifact_collection_handoff(session.session_id)
                    path = self._storage_manager.write_artifact_collection_handoff(session.session_id, handoff)
                    if json.dumps(self._storage_manager.read_artifact_collection_handoff(session.session_id), sort_keys=True) != json.dumps(handoff, sort_keys=True):
                        raise RuntimeError("Current artifact handoff preservation is unconfirmed")
                    return self._record_successful_command("preserve_artifact_collection_handoff", {
                        "session_id": session.session_id, "artifact_collection_handoff_path": str(path),
                        "handoff_preservation_confirmed": True,
                    })
        except Exception as error:
            if self._session is not session:
                return ControllerCommandResult("preserve_artifact_collection_handoff", False,
                    {"session_id": session.session_id}, f"{type(error).__name__}: {error}")
            return self._record_failed_command("preserve_artifact_collection_handoff", error)

    @service_operation()
    async def publish_acquisition_evidence_completion(
        self, *, communication: NatsControllerCommunication, result_window_s: float,
    ) -> ControllerCommandResult:
        """Publish the Session boundary after owner confirmations, without completing the Session."""
        session = self._require_session()
        admitted = False
        try:
            with self._service_operation_lock:
                if self._normal_stop_task is not None and self._normal_stop_task is not asyncio.current_task():
                    raise RuntimeError("Normal Stop is in progress")
                if self._acquisition_publication_active:
                    raise RuntimeError("Acquisition publication completion is already in progress")
                if session.current_state != SessionState.STOPPING or not self._runtime_cleanup_confirmed:
                    raise RuntimeError("Confirmed acquisition cleanup and a stopping Session are required")
                if (communication._boundary.component_id != self._component_id
                        or communication._boundary.component_type != "controller"):
                    raise ValueError("Controller publication identity mismatch")
                if self._acquisition_marker_session is session and self._acquisition_marker_confirmed:
                    return self._record_successful_command("publish_acquisition_evidence_completion",
                        {"marker": self._acquisition_marker.to_dict(), "publication_confirmed": True})
                self._acquisition_publication_active = admitted = True
            participants = session.configuration.expected_runtime_participants
            nodes = tuple(p for p in participants if p.component_type == "acquisition_node")
            if self._acquisition_node is not None and not any(
                    p.component_id == self._acquisition_node.node_id for p in nodes):
                nodes += (RuntimeParticipant("acquisition_node", self._acquisition_node.node_id),)
            for participant in nodes:
                if communication.session_acquisition_completion(participant, session.session_id) is None:
                    raise RuntimeError(f"Acquisition publication unconfirmed: {participant.component_id}")
            synchronization = [p for p in participants if p.component_type == "synchronization_manager"]
            if len(synchronization) != 1:
                raise RuntimeError("One authoritative Session synchronization participant is required")
            result = await communication.request_command(synchronization[0], "stop_runtime",
                session.session_id, {}, result_window_s)
            if result is None or result.status != "succeeded" or result.success is not True:
                raise RuntimeError("Synchronization evidence publication is unconfirmed")
            if not await communication.confirm_session_health_processing(session.session_id, self):
                raise RuntimeError("Controller Session health processing is unconfirmed")
            with self._service_operation_lock:
                if self._session is not session:
                    raise RuntimeError("Controller Session binding changed during publication")
                messages = list(self.controller_action_decision_evidence)
                messages.extend(m for m in communication.unpublished_session_evidence(session.session_id)
                                if self._acquisition_marker is None
                                or m.evidence_id != self._acquisition_marker.evidence_id)
                for recorded in self._command_results:
                    if isinstance(recorded.details, Mapping):
                        rejection = recorded.details.get("rejection_evidence")
                        if isinstance(rejection, dict):
                            messages.append(RuntimeEvidenceMessage.from_dict(rejection))
                unique = {}
                for message in messages:
                    if message.session_id != session.session_id or message.source_id != self._component_id:
                        continue
                    prior = unique.get(message.evidence_id)
                    if prior is not None and json.dumps(prior.to_dict(), sort_keys=True) != json.dumps(message.to_dict(), sort_keys=True):
                        raise RuntimeError("Conflicting Controller publication evidence identity")
                    unique[message.evidence_id] = message
                messages = tuple(unique.values())
                if self._acquisition_marker_session is not session:
                    self._acquisition_marker = None
                    self._acquisition_marker_session = session
                    self._acquisition_marker_confirmed = False
            for message in messages:
                await communication.publish_evidence(message)
            with self._service_operation_lock:
                if self._session is not session:
                    raise RuntimeError("Controller Session binding changed during publication")
                if self._acquisition_marker is None:
                    self._acquisition_marker = RuntimeEvidenceMessage(uuid4().hex,
                        session.session_id, "acquisition_evidence_completion", self._component_id, {}, True)
            await communication.publish_evidence(self._acquisition_marker)
            with self._service_operation_lock:
                if self._session is not session:
                    raise RuntimeError("Controller Session binding changed during publication")
                self._acquisition_marker_confirmed = True
                return self._record_successful_command("publish_acquisition_evidence_completion",
                    {"marker": self._acquisition_marker.to_dict(), "publication_confirmed": True})
        except Exception as error:
            return self._record_failed_command("publish_acquisition_evidence_completion", error)
        finally:
            if admitted:
                with self._service_operation_lock:
                    self._acquisition_publication_active = False

    def check_ready(self) -> ServiceReadiness:
        """Report service readiness independently of Session lifecycle and reservations."""
        terminated = getattr(getattr(self, "_maintenance", None), "terminated", False)
        return apply_dependency_readiness(self, ServiceReadiness(
            self._component_id, "controller", True, not terminated,
            "service_terminated" if terminated else "ready"))

    async def shutdown_framework(
        self, participants: Iterable[RuntimeParticipant], *,
        communication: NatsControllerCommunication, stop_attempt_id: str,
        administrator_id: str, result_window_s: float,
        authorize_kill: Callable[[RuntimeParticipant, RuntimeCommandResultMessage], Awaitable[bool]] | None = None,
    ) -> ControllerCommandResult:
        """Progressively retire an explicit deployment scope, preserving pre-retirement evidence.

        authorize_kill receives each participant's actual blocked result separately.
        Only exactly True authorizes its kill; None means decline. All distributed
        requests and authorization callbacks use the explicit bounded window.
        """
        from math import isfinite
        from time import time

        attempt = None
        subscription = None
        admitted = False
        archival_boundary_crossed = False
        cleanup_sequence_started = False
        maintenance = getattr(self, "_maintenance", None)
        try:
            if any(not isinstance(v, str) or not v for v in (stop_attempt_id, administrator_id)):
                raise ValueError("Framework attempt and administrator identities are required")
            if not isinstance(result_window_s, (int, float)) or not isfinite(result_window_s) or result_window_s <= 0:
                raise ValueError("Framework result window must be finite and positive")
            participants = tuple(participants)
            supported = {"acquisition_node", "synchronization_manager", "ingestor", "storage_manager", "controller"}
            if any(not isinstance(p, RuntimeParticipant) or p.component_type not in supported
                   or not isinstance(p.component_id, str) or not p.component_id for p in participants):
                raise ValueError("Invalid framework shutdown participant")
            for participant in participants:
                build_runtime_subject(None, "command", participant.component_type,
                                      participant.component_id, "check_stop_readiness")
            if len(set(participants)) != len(participants):
                raise ValueError("Framework participant identities must be unique")
            infrastructure = {}
            for kind in ("synchronization_manager", "ingestor", "storage_manager", "controller"):
                matches = [p for p in participants if p.component_type == kind]
                if len(matches) != 1:
                    raise ValueError(f"Framework shutdown requires one explicit {kind}")
                infrastructure[kind] = matches[0]
            if (maintenance is None or maintenance.participant != infrastructure["controller"]
                    or infrastructure["controller"].component_id != self._component_id
                    or maintenance.ingestor is not self._ingestor or maintenance.storage_manager is not self._storage_manager):
                raise ValueError("Controller maintenance and evidence dependencies must match the explicit scope")
            for kind, service in (("ingestor", self._ingestor), ("storage_manager", self._storage_manager)):
                interface = getattr(service, "_maintenance", None)
                if interface is None or interface.participant != infrastructure[kind]:
                    raise ValueError(f"Configured {kind} evidence dependency must match shutdown scope")
            if authorize_kill is not None and not callable(authorize_kill):
                raise ValueError("Kill authorization must be an explicit callable")
            with self._service_operation_lock:
                if self._framework_shutdown_active or maintenance.terminated or maintenance._attempt is not None:
                    raise RuntimeError("Controller shutdown is overlapping or operational admission is closed")
                if stop_attempt_id in self._framework_shutdown_attempts:
                    raise ValueError("Framework stop attempt identity cannot be reused")
                self._framework_shutdown_active = True
                self._framework_shutdown_attempt_id = stop_attempt_id
                admitted = True
            participant_attempt_ids = {p: uuid4().hex for p in participants}
            attempt = {"stop_attempt_id": stop_attempt_id, "administrator_id": administrator_id,
                       "requester_id": self._component_id, "session_id": None, "started_at": time(),
                       "scope": [p.to_dict() for p in participants], "survey": [], "commands": [],
                       "results": [], "authorizations": [], "actions": [], "failures": [],
                       "retired": [], "not_retired": [p.to_dict() for p in participants], "outcome": None,
                       "participant_attempts": [{"participant": p.to_dict(), "stop_attempt_id": identity}
                                                for p, identity in participant_attempt_ids.items()]}
            self._framework_shutdown_attempts[stop_attempt_id] = attempt
            if communication.check_ready().ready is not True:
                raise ConnectionError("Controller NATS communication is not ready")
            subscription = await asyncio.wait_for(communication.subscribe_command_results(None), result_window_s)

            async def request(participant, operation, *, authorized=False):
                command_id = uuid4().hex
                payload = {"stop_attempt_id": participant_attempt_ids[participant],
                           "framework_stop_attempt_id": stop_attempt_id,
                           "administrator_id": administrator_id, "authorized": authorized}
                attempt["commands"].append({"command_id": command_id, "command_type": operation,
                                            "participant": participant.to_dict(), "payload": deepcopy(payload),
                                            "requested_at": time()})
                try:
                    result = await asyncio.wait_for(communication.request_command(
                        participant, operation, None, payload, result_window_s, command_id=command_id), result_window_s)
                except TimeoutError:
                    result = None
                except BaseException as error:
                    attempt["results"].append({"command_id": command_id, "result": None,
                                               "reason": f"{type(error).__name__}: {error}"})
                    raise
                if result is not None:
                    if (result.command_id != command_id or result.session_id is not None
                            or result.source_id != participant.component_id or result.target_id != self._component_id
                            or result.status not in {"succeeded", "failed"}
                            or type(result.success) is not bool or result.success != (result.status == "succeeded")):
                        result = None
                attempt["results"].append({"command_id": command_id,
                                           "result": result.to_dict() if result is not None else None,
                                           "reason": None if result is not None else "Final command result missing or invalid"})
                return result

            async def preserve(checkpoint):
                attempt["remaining_obligations"] = deepcopy(attempt["not_retired"])
                await maintenance._preserve(attempt, checkpoint)

            def correlated(result, participant):
                if result is None or not isinstance(result.payload, dict):
                    return False
                record = result.payload.get("attempt")
                return (isinstance(record, dict) and record.get("target") == participant.to_dict()
                        and record.get("stop_attempt_id") == participant_attempt_ids[participant]
                        and record.get("framework_stop_attempt_id") == stop_attempt_id)

            async def turn(participant, operation):
                result = await request(participant, operation)
                if (operation == "stop" and correlated(result, participant)
                        and result.payload.get("outcome") == "blocked" and not result.success):
                    decision = False
                    if authorize_kill is not None:
                        # A fresh decision is requested for this exact blocked participant attempt.
                        decision = await asyncio.wait_for(authorize_kill(participant,
                            RuntimeCommandResultMessage.from_dict(deepcopy(result.to_dict()))), result_window_s)
                    attempt["authorizations"].append({"participant": participant.to_dict(),
                        "stop_attempt_id": participant_attempt_ids[participant],
                        "blocked_command_id": result.command_id, "administrator_id": administrator_id,
                        "authorized": decision is True, "recorded_at": time(),
                        "blockers": deepcopy(result.payload["attempt"].get("blockers", []))})
                    if not archival_boundary_crossed:
                        await preserve("authorization_recorded")
                    result = await request(participant, "kill" if decision is True else "cancel", authorized=decision is True)
                    if decision is not True:
                        raise RuntimeError(f"Administrator declined forced termination: {participant.component_id}")
                if not correlated(result, participant):
                    raise RuntimeError(f"Maintenance result unconfirmed: {participant.component_id}")
                if operation == "prepare_stop":
                    if (not result.success or result.payload.get("prepared") is not True
                            or result.payload.get("termination_confirmed") is not False
                            or result.payload.get("outcome") is not None):
                        raise RuntimeError(f"Preparation unconfirmed: {participant.component_id}")
                    attempt["actions"].append({"participant": participant.to_dict(), "action": "preparation_confirmed"})
                else:
                    if (not result.success or result.payload.get("outcome") != "completed"
                            or result.payload.get("termination_confirmed") is not True):
                        raise RuntimeError(f"Operational retirement unconfirmed: {participant.component_id}")
                    attempt["retired"].append(participant.to_dict())
                    attempt["not_retired"].remove(participant.to_dict())
                    attempt["actions"].append({"participant": participant.to_dict(), "action": "retirement_confirmed"})
                if not archival_boundary_crossed:
                    await preserve("participant_result_confirmed")

            for participant in participants:
                try:
                    result = await request(participant, "check_stop_readiness")
                except Exception as error:
                    result = None
                    attempt["survey"].append({"participant": participant.to_dict(), "confirmed": False,
                                             "ready": None, "reason": str(error)})
                    continue
                report = result.payload if result is not None and isinstance(result.payload, dict) else {}
                confirmed = (result is not None and result.success and report.get("confirmed") is True
                             and report.get("participant") == participant.to_dict()
                             and type(report.get("ready")) is bool and isinstance(report.get("blockers"), list))
                attempt["survey"].append({"participant": participant.to_dict(), "confirmed": confirmed,
                    "ready": report.get("ready") if confirmed else None,
                    "blockers": deepcopy(report.get("blockers", [])) if confirmed else [],
                    "reason": None if confirmed else "Readiness response missing, invalid, or unconfirmed"})
            await preserve("initial_survey")
            cleanup_sequence_started = True
            for participant in participants:
                if participant.component_type == "acquisition_node":
                    await turn(participant, "stop")
            await turn(infrastructure["synchronization_manager"], "stop")
            await turn(infrastructure["storage_manager"], "prepare_stop")
            await turn(infrastructure["controller"], "prepare_stop")
            await preserve("final_archival_checkpoint")
            with self._ingestor.framework_preservation_guard(self._storage_manager):
                pass
            # Ingestor's own W036 stop preserves its cleanup and last readiness.
            # After dispatch, even a missing result cannot prove its intake is live.
            archival_boundary_crossed = True
            await turn(infrastructure["ingestor"], "stop")
            await turn(infrastructure["storage_manager"], "stop")
            await turn(infrastructure["controller"], "stop")
            attempt["outcome"] = "completed"
            attempt["finished_at"] = time()
            return self._record_successful_command("shutdown_framework", deepcopy(attempt))
        except asyncio.CancelledError:
            if attempt is not None:
                attempt["outcome"] = "failed"
                attempt["failures"].append("Framework coordination cancelled; outstanding confirmations retained")
                attempt["finished_at"] = time()
                if not archival_boundary_crossed:
                    try:
                        await maintenance._preserve(attempt, "coordination_cancelled")
                    except Exception as error:
                        attempt["failures"].append(f"Preservation unconfirmed: {error}")
                self._record_failed_command("shutdown_framework", RuntimeError(attempt["failures"][0]), deepcopy(attempt))
            raise
        except Exception as error:
            if attempt is not None:
                attempt["outcome"] = "failed" if cleanup_sequence_started else "blocked"
                attempt["failures"].append(str(error))
                attempt["finished_at"] = time()
                if not archival_boundary_crossed:
                    try:
                        await maintenance._preserve(attempt, "coordination_failed")
                    except Exception as preservation_error:
                        attempt["failures"].append(f"Preservation unconfirmed: {preservation_error}")
            return self._record_failed_command("shutdown_framework", error, deepcopy(attempt))
        finally:
            try:
                if subscription is not None:
                    try:
                        await asyncio.wait_for(subscription.unsubscribe(), result_window_s)
                    except Exception:
                        pass
            finally:
                if admitted:
                    with self._service_operation_lock:
                        self._framework_shutdown_active = False
                        self._framework_shutdown_attempt_id = None

    @service_operation(new_work=True)
    async def launch_session(
        self,
        selections: Mapping[str, Iterable[DeviceDeclaration]],
        *,
        communication: NatsControllerCommunication,
        participants: Iterable[RuntimeParticipant],
        config_parameters: dict[str, Any],
        result_window_s: float,
        scientific_outputs: Iterable[ScientificOutputSelection] = (),
    ) -> ControllerCommandResult:
        """Resolve/reserve resources and confirm distributed preparation before initialization."""
        session_id = uuid4().hex
        acquired = []
        initializing = []
        subscriptions = []
        rollback = []
        unconfirmed_reservations = []
        initialization_outcomes = []
        try:
            if self._session is not None:
                raise RuntimeError("Controller already owns a Session")
            if result_window_s < 0:
                raise ValueError("result_window_s must be nonnegative")
            if communication.check_ready().ready is not True:
                raise ConnectionError("Controller NATS communication is not ready")
            if config_parameters.get("local_storage_roots") is not None:
                raise ValueError("Distributed launch cannot select node-local storage roots")
            participants = tuple(participants)
            scientific_outputs = tuple(scientific_outputs)
            mandatory = []
            for component_type in ("ingestor", "synchronization_manager"):
                matches = [p for p in participants if p.component_type == component_type]
                if len(matches) != 1:
                    raise ValueError(f"Launch requires one configured {component_type}")
                mandatory.extend(matches)
            nodes = {p.component_id: p for p in participants if p.component_type == "acquisition_node"}
            subscriptions.append(await communication.subscribe_command_results(None))
            subscriptions.append(await communication.subscribe_command_results(session_id))

            async def request(participant, operation, payload=None, session_scoped=True):
                return await communication.request_command(
                    participant, operation, session_id if session_scoped else None,
                    payload or {}, result_window_s,
                )

            def confirmed(result):
                return result is not None and result.success is True and result.status == "succeeded"

            for participant in mandatory:
                result = await request(participant, "check_readiness", session_scoped=False)
                report = result.payload.get("service_readiness") if confirmed(result) else None
                if (
                    not isinstance(report, dict)
                    or report.get("ready") is not True
                    or report.get("required") is not True
                    or report.get("component_id") != participant.component_id
                    or report.get("component_type") != participant.component_type
                ):
                    raise RuntimeError(f"Mandatory {participant.component_type} readiness is unready or unknown")
            resolved = {}
            device_reports = []
            for node_id, requested in selections.items():
                requested = tuple(d for d in requested if d.enabled)
                if not requested:
                    continue
                critical = any(d.required for d in requested)
                participant = nodes.get(node_id)
                if participant is None:
                    if critical:
                        raise RuntimeError(f"Required node is not configured: {node_id}")
                    continue
                inventory_result = await request(participant, "get_inventory", session_scoped=False)
                readiness_result = await request(participant, "check_readiness", session_scoped=False)
                inventory = {}
                report = readiness_result.payload.get("acquisition_node_readiness") if confirmed(readiness_result) else None
                try:
                    if (
                        not confirmed(inventory_result)
                        or not isinstance(report, dict)
                        or report.get("node_id") != node_id
                        or type(report.get("ready")) is not bool
                        or "reserved_for_session_id" not in report
                    ):
                        raise ValueError("Missing or invalid current node report")
                    inventory = {d.device_id: d for d in (DeviceDeclaration.from_dict(data) for data in inventory_result.payload["devices"])}
                    if report["ready"] is not True or report.get("reserved_for_session_id") not in {None, session_id}:
                        raise ValueError("Node is not ready or available")
                    reports = {r["device_id"]: r for r in report["device_readiness"]}
                    services = report["service_readiness"]
                    if not isinstance(services, list) or any(
                        type(s.get("required")) is not bool
                        or type(s.get("ready")) is not bool
                        or (s["required"] and not s["ready"])
                        for s in services
                    ):
                        raise ValueError("Invalid node service readiness")
                    if any(d.enabled and (d.device_id not in reports or type(reports[d.device_id].get("ready")) is not bool) for d in inventory.values()):
                        raise ValueError("Incomplete or invalid device readiness")
                except (KeyError, TypeError, ValueError) as error:
                    if critical:
                        raise RuntimeError(f"Required node readiness is unknown/unavailable: {node_id}") from error
                    continue
                selected = []
                for selection in requested:
                    declaration = inventory.get(selection.device_id)
                    ready = declaration is not None and declaration.enabled and reports.get(selection.device_id, {}).get("ready") is True
                    if not ready:
                        if selection.required:
                            raise RuntimeError(f"Required device is unavailable: {selection.device_id}")
                        continue
                    selected.append(replace(declaration, required=selection.required))
                if not selected:
                    continue
                publication_error = None
                try:
                    reservation = await request(participant, "reserve")
                except Exception as error:
                    reservation = None
                    publication_error = str(error)
                if not confirmed(reservation) or reservation.payload.get("confirmed") is not True:
                    if reservation is None:
                        # No initialization was requested: owner-keyed release is safe,
                        # but an absent release result still leaves ownership unresolved.
                        release_confirmed = False
                        try:
                            release = await request(participant, "release_reservation")
                            release_confirmed = confirmed(release) and release.payload.get("confirmed") is True
                        except Exception:
                            pass
                        unconfirmed_reservations.append({"participant": participant.to_dict(),
                                                        "release_confirmed": release_confirmed,
                                                        "error": publication_error})
                    if any(d.required for d in selected):
                        raise RuntimeError(f"Required node reservation unconfirmed/rejected: {node_id}")
                    continue
                acquired.append(participant)
                resolved[node_id] = tuple(selected)
                device_reports.extend(DeviceReadiness(d.device_id, True, reports[d.device_id].get("reason", "ready"),
                    reports[d.device_id].get("capabilities_available", ())) for d in selected)
            parameters = dict(config_parameters)
            parameters.pop("session_id", None)
            parameters.pop("selected_devices", None)
            parameters.pop("expected_runtime_participants", None)
            config = SessionConfig(**parameters, session_id=session_id,
                selected_devices=[d for devices in resolved.values() for d in devices],
                expected_runtime_participants=tuple((*mandatory, *acquired)))
            self._session = Session(session_id, config)
            preparation_reports = []
            for participant in (*mandatory, *acquired):
                # Record the cleanup obligation before publication: a missing result
                # cannot prove participant preparation never started.
                initializing.append(participant)
                payload = {}
                if participant.component_type == "acquisition_node":
                    payload = {"selected_devices": [d.to_dict() for d in resolved[participant.component_id]],
                               "device_configurations": {d.device_id: (config.device_configurations or {}).get(d.device_id)
                                   for d in resolved[participant.component_id]},
                               "scientific_outputs": [s.to_dict() for s in scientific_outputs
                                   if s.source_node_id == participant.component_id and s.source_device_id in {d.device_id for d in resolved[participant.component_id]}]}
                result = await request(participant, "initialize_session", payload)
                preparation = result.payload.get("preparation") if confirmed(result) else None
                prepared = isinstance(preparation, dict) and preparation.get("ready") is True and preparation.get("component_id") == participant.component_id and preparation.get("component_type") == participant.component_type
                outcome = "succeeded" if prepared else ("failed" if result is not None and result.status == "failed" and result.success is False else "unconfirmed")
                initialization_outcomes.append({"participant": participant.to_dict(), "outcome": outcome,
                                                "reason": result.reason if result is not None else "No confirmed initialization result"})
                if not prepared:
                    raise RuntimeError(f"Participant initialization {outcome}: {participant.component_id}; {initialization_outcomes[-1]['reason']}")
                preparation_reports.append(ServiceReadiness(participant.component_id, participant.component_type, True, True, "session_prepared"))
            self._session.initialize(device_reports, preparation_reports)
            self._launch_communication = communication
            self._reserved_participants = tuple(acquired)
            self._launch_result_window_s = result_window_s
            self._launch_subscriptions = tuple(subscriptions)
            return self._record_successful_command("launch_session", {"session_id": session_id,
                "session_state": self._session.current_state.value, "configuration": config.to_dict(),
                "unconfirmed_reservations": unconfirmed_reservations, "initialization": initialization_outcomes})
        except Exception as error:
            clean = set()
            for participant in initializing:
                try:
                    result = await communication.request_command(participant, "abort_session_initialization", session_id, {}, result_window_s)
                    succeeded = result is not None and result.success is True and result.payload.get("confirmed") is True
                    if succeeded:
                        clean.add(participant)
                    rollback.append({"participant": participant.to_dict(), "operation": "abort_session_initialization", "confirmed": succeeded})
                except Exception as cleanup_error:
                    rollback.append({"participant": participant.to_dict(), "operation": "abort_session_initialization", "confirmed": False, "error": str(cleanup_error)})
            for participant in acquired:
                if participant in initializing and participant not in clean:
                    rollback.append({"participant": participant.to_dict(), "operation": "release_reservation", "confirmed": False, "reason": "cleanup_unconfirmed"})
                    continue
                try:
                    result = await communication.request_command(participant, "release_reservation", session_id, {}, result_window_s)
                    rollback.append({"participant": participant.to_dict(), "operation": "release_reservation", "confirmed": result is not None and result.success is True and result.payload.get("confirmed") is True})
                except Exception as release_error:
                    rollback.append({"participant": participant.to_dict(), "operation": "release_reservation", "confirmed": False, "error": str(release_error)})
            if self._session is not None and self._session.session_id == session_id:
                self._mark_session_failed(str(error))
                self._session = None
            for subscription in subscriptions:
                try:
                    await subscription.unsubscribe()
                except Exception as unsubscribe_error:
                    rollback.append({"operation": "unsubscribe_command_results", "confirmed": False, "error": str(unsubscribe_error)})
            result = ControllerCommandResult("launch_session", False,
                {"session_id": session_id, "rollback": rollback,
                 "unconfirmed_reservations": unconfirmed_reservations,
                 "initialization": initialization_outcomes}, str(error))
            self._command_results.append(result)
            self._last_result = result
            return result

    @service_operation(new_work=True)
    async def start_launched_session(self) -> ControllerCommandResult:
        """Start reserved distributed acquisition through existing runtime commands."""
        session = self._require_session()
        self._runtime_cleanup_confirmed = False
        try:
            for participant in self._reserved_participants:
                result = await self._launch_communication.request_command(participant, "start_runtime", session.session_id, {}, self._launch_result_window_s)
                if result is None or result.success is not True:
                    raise RuntimeError(f"Runtime start unconfirmed/failed: {participant.component_id}")
            session.start()
            if self._storage_manager is not None:
                self._write_initial_session_record()
            return self._record_successful_command("start_session", {"session_state": session.current_state.value})
        except Exception as error:
            rollback = []
            for participant in session.configuration.expected_runtime_participants:
                try:
                    cleanup = await self._launch_communication.request_command(participant, "abort_session_initialization", session.session_id, {}, self._launch_result_window_s)
                    confirmed = cleanup is not None and cleanup.success is True and cleanup.payload.get("confirmed") is True
                    if participant in self._reserved_participants and confirmed:
                        release = await self._launch_communication.request_command(participant, "release_reservation", session.session_id, {}, self._launch_result_window_s)
                        confirmed = release is not None and release.success is True and release.payload.get("confirmed") is True
                    rollback.append({"participant": participant.to_dict(), "confirmed": confirmed})
                except Exception as cleanup_error:
                    rollback.append({"participant": participant.to_dict(), "confirmed": False, "error": str(cleanup_error)})
            self._mark_session_failed(str(error))
            self._runtime_cleanup_confirmed = bool(rollback) and all(item["confirmed"] for item in rollback)
            return self._record_failed_command("start_session", error, {"rollback": rollback})

    @service_operation()
    async def stop_launched_session(self, reason: str | None = None) -> ControllerCommandResult:
        """Stop/finalize every reserved node before releasing it, independently of global collection."""
        session = self._require_session()
        if self._normal_stop_task is not None and self._normal_stop_task is not asyncio.current_task():
            return self._record_failed_command("stop_session", RuntimeError("Normal Stop is in progress"))
        self._runtime_cleanup_confirmed = False
        outcomes = []
        for participant in self._reserved_participants:
            try:
                result = await self._launch_communication.request_command(participant, "stop_runtime", session.session_id, {}, self._launch_result_window_s)
                if result is None or result.success is not True:
                    raise RuntimeError("Node stop/local finalization unconfirmed")
                release = await self._launch_communication.request_command(participant, "release_reservation", session.session_id, {}, self._launch_result_window_s)
                if release is None or release.success is not True or release.payload.get("confirmed") is not True:
                    raise RuntimeError("Reservation release unconfirmed")
                outcomes.append({"participant": participant.to_dict(), "released": True})
            except Exception as error:
                outcomes.append({"participant": participant.to_dict(), "released": False, "error": str(error)})
        if any(not o["released"] for o in outcomes):
            self._mark_session_failed("Distributed runtime cleanup unconfirmed")
            return self._record_failed_command("stop_session", RuntimeError("Distributed runtime cleanup unconfirmed"), {"nodes": outcomes})
        if self._active_experiment_id is not None:
            # Nodes already finalized their files; record the Controller-owned Experiment end only.
            session.record_experiment_lifecycle(self._active_experiment_id, "experiment_stop", self._current_session_time_s())
            self._active_experiment_id = None
            self._active_experiment_runtime_health_mapping = ()
        session.stop(reason)
        self._runtime_cleanup_confirmed = True
        return self._record_successful_command("stop_session", {"session_state": session.current_state.value, "nodes": outcomes})

    @property
    def controller_action_decisions(self) -> tuple[ControllerActionDecision, ...]:
        """Recorded health-derived decisions in presentation order."""

        return tuple(self._controller_action_decisions)

    @property
    def controller_action_decision_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Persistent decision messages available for existing caller-managed publication."""

        return tuple(self._controller_action_decision_evidence)

    @property
    def expected_runtime_participants(self) -> tuple[RuntimeParticipant, ...]:
        """Expected runtime identities from the accepted SessionConfig."""

        return self._require_session().configuration.expected_runtime_participants

    @service_operation()
    def process_health_interpretation(
        self,
        evidence: HealthInterpretationEvidence,
    ) -> ControllerActionDecision:
        """Record one evidence-only decision for presented interpretation evidence."""

        session = self._require_session()
        decision_by_interpretation = {
            "informational": "record_only",
            "uninterpreted": "record_only",
            "warning": "record_warning",
            "recoverable_failure": "record_recoverable_failure",
            "experiment_failure": "experiment_fail",
            "session_failure": "session_fail",
        }
        decision = ControllerActionDecision(
            originating_observation_id=evidence.originating_observation_id,
            session_id=session.session_id,
            experiment_id=evidence.experiment_id,
            live_source_id=evidence.live_source_id,
            acquisition_health_policy=evidence.acquisition_health_policy,
            interpretation_label=evidence.interpretation_label,
            controller_decision=decision_by_interpretation[
                evidence.interpretation_label
            ],
            decision_time_s=self._current_session_time_s(),
            details={
                "expected_participant_id": evidence.expected_participant_id,
                "required": evidence.required,
            },
        )
        self._record_action_decision(decision)
        return decision

    def _record_action_decision(self, decision: ControllerActionDecision) -> None:
        with self._service_operation_lock:
            if any(recorded is decision for recorded in self._controller_action_decisions):
                return
            if self._acquisition_marker_session is self._session and self._session is not None:
                raise RuntimeError("Session acquisition evidence publication boundary is closed")
            message = RuntimeEvidenceMessage(
                evidence_id=uuid4().hex,
                session_id=decision.session_id,
                evidence_type="controller_action_decision",
                source_id=self._component_id,
                payload=deepcopy(decision.to_dict()),
                is_persistent=True,
            )
            # Retain ownership before handoff; do not nest Controller and intake locks.
            self._controller_action_decisions.append(decision)
            self._controller_action_decision_evidence.append(message)
        if self._ingestor is not None:
            audit = self._ingestor.receive_runtime_evidence(message)
            if not audit.accepted:
                raise RuntimeError("Controller decision evidence intake was not accepted")

    def _controller_decision_evidence_snapshot(self, session_id: str) -> dict[str, dict[str, Any]]:
        return {
            message.evidence_id: deepcopy(message.to_dict())
            for message in self._controller_action_decision_evidence
            if message.session_id == session_id
        }

    def _controller_owned_session_evidence_snapshot(self, session_id: str) -> dict[str, dict[str, Any]]:
        """Read owned persistent decisions, rejection evidence, and any produced marker."""
        snapshot = self._controller_decision_evidence_snapshot(session_id)
        for result in self._command_results:
            if isinstance(result.details, Mapping):
                contents = result.details.get("rejection_evidence")
                if isinstance(contents, dict):
                    message = RuntimeEvidenceMessage.from_dict(contents)
                    if message.session_id == session_id and message.source_id == self._component_id and message.is_persistent:
                        snapshot[message.evidence_id] = deepcopy(message.to_dict())
        if self._acquisition_marker is not None and self._acquisition_marker.session_id == session_id:
            snapshot[self._acquisition_marker.evidence_id] = deepcopy(self._acquisition_marker.to_dict())
        return snapshot

    def _require_controller_decision_archival(
        self, session_id: str, confirmation: dict[str, Any] | None,
    ) -> None:
        decisions = self._controller_decision_evidence_snapshot(session_id)
        if confirmation is None or decisions != self._archived_controller_action_decisions:
            raise RuntimeError("Controller decision Evidence Archive preservation is unconfirmed")
        archived = {message["evidence_id"]: message for message in confirmation["runtime_evidence"]}
        if any(archived.get(identity) != contents for identity, contents in decisions.items()):
            raise RuntimeError("Current Evidence Archive does not preserve required Controller decisions")
        owned = self._controller_owned_session_evidence_snapshot(session_id)
        if any(json.dumps(archived.get(identity), sort_keys=True) != json.dumps(contents, sort_keys=True)
               for identity, contents in owned.items()):
            raise RuntimeError("Current Evidence Archive does not preserve required Controller-owned evidence")
        if self._acquisition_marker_session is self._session and self._acquisition_marker is not None:
            expected_handoff = self._ingestor.compile_artifact_collection_handoff(session_id)
            if json.dumps(self._storage_manager.read_artifact_collection_handoff(session_id), sort_keys=True) != json.dumps(expected_handoff, sort_keys=True):
                raise RuntimeError("Current durable artifact handoff does not cover the closing Session")

    @service_operation()
    def execute_controller_action_decision(
        self,
        decision: ControllerActionDecision,
    ) -> ControllerCommandResult:
        """Execute accepted Phase 8b lifecycle decisions."""

        def command() -> dict[str, Any]:
            session = self._require_session()
            if decision.session_id != session.session_id:
                raise RuntimeError(
                    "ControllerActionDecision session_id does not match active Session"
                )
            if decision.controller_decision not in {
                "record_only", "record_warning", "record_recoverable_failure",
                "operator_required", "experiment_fail", "session_fail",
            }:
                raise RuntimeError(
                    f"ControllerActionDecision is not executable in Phase 8b: {decision.controller_decision}"
                )
            self._record_action_decision(decision)
            if decision.controller_decision in {
                "record_only",
                "record_warning",
                "record_recoverable_failure",
                "operator_required",
            }:
                return {
                    "controller_decision": decision.controller_decision,
                    "lifecycle_mutated": False,
                }
            if decision.controller_decision == "experiment_fail":
                if session.current_state != SessionState.RUNNING:
                    raise RuntimeError(
                        "Experiment failure requires a running Session"
                    )
                if self._active_experiment_id is None:
                    raise RuntimeError("No Experiment is active")
                if decision.experiment_id != self._active_experiment_id:
                    raise RuntimeError(
                        f"Active Experiment is '{self._active_experiment_id}', "
                        f"not '{decision.experiment_id}'"
                    )
                evidence = self._end_experiment(
                    experiment_id=decision.experiment_id,
                    event_type="experiment_fail",
                    details={
                        "originating_observation_id": (
                            decision.originating_observation_id
                        ),
                        "acquisition_health_policy": (
                            decision.acquisition_health_policy
                        ),
                        "interpretation_label": decision.interpretation_label,
                        "controller_decision": decision.controller_decision,
                    },
                )
                return evidence
            if decision.controller_decision == "session_fail":
                self._attempt_runtime_stop()
                self._mark_session_failed(
                    "ControllerActionDecision requested Session failure"
                )
                return {"session_state": session.current_state.value}
            raise RuntimeError(
                "ControllerActionDecision is not executable in Phase 8b: "
                f"{decision.controller_decision}"
            )

        return self._run_command("execute_controller_action_decision", command)

    @service_operation(new_work=True)
    def create_session(self, config: SessionConfig) -> ControllerCommandResult:
        """Create one Session from accepted configuration."""

        def command() -> dict[str, Any]:
            if self._session is not None:
                raise RuntimeError("Controller already has a Session")
            if not config.session_id:
                raise ValueError("SessionConfig.session_id is required")
            self._session = Session(
                session_id=config.session_id,
                configuration=config,
            )
            return {"session_id": config.session_id}

        return self._run_command("create_session", command)

    @service_operation(new_work=True)
    def initialize_session(
        self,
        device_readiness_summary: Iterable[DeviceReadiness] | None = None,
        service_readiness: Iterable[ServiceReadiness] | None = None,
    ) -> ControllerCommandResult:
        """Initialize Session with readiness evidence supplied by runtime owners."""

        def command() -> dict[str, Any]:
            session = self._require_session()
            session.initialize(
                device_readiness_summary=device_readiness_summary,
                service_readiness=service_readiness,
                acquisition_nodes=(self._acquisition_node,),
            )
            return {"session_state": session.current_state.value}

        return self._run_command("initialize_session", command)

    @service_operation(new_work=True)
    def start_session(self) -> ControllerCommandResult:
        """Start runtime first, then move Session lifecycle to running."""

        session = self._require_session()
        if self._ingestor is None:
            return self._record_failed_command(
                "start_session", RuntimeError("Local Session start requires an explicit Ingestor reference")
            )
        self._runtime_cleanup_confirmed = False
        try:
            runtime_result = self._acquisition_node.start_runtime()
            if self._runtime_start_failed(runtime_result):
                raise RuntimeError("AcquisitionNode runtime start reported failure")
            session.start()
            self._write_initial_session_record()
        except Exception as error:
            self._attempt_runtime_stop()
            self._mark_session_failed(str(error))
            return self._record_failed_command("start_session", error)
        return self._record_successful_command(
            "start_session",
            {
                "session_state": session.current_state.value,
                "runtime_result": runtime_result,
            },
        )

    @service_operation()
    def run_one_iteration(self) -> ControllerCommandResult:
        """Run one bounded AcquisitionNode runtime iteration."""

        try:
            summary = self._acquisition_node.run_one_iteration()
            if self._acquisition_node.status()["failed"]:
                raise RuntimeError("AcquisitionNode reported failed status")
        except Exception as error:
            self._attempt_runtime_stop()
            self._mark_session_failed(str(error))
            return self._record_failed_command("run_one_iteration", error)
        return self._record_successful_command("run_one_iteration", summary)

    @service_operation(new_work=True)
    def start_experiment(
        self,
        experiment_id: str,
        details: dict[str, Any] | None = None,
        expected_participants: Iterable[ExpectedParticipant] = (),
        runtime_health_mapping: Iterable[ExperimentRuntimeHealthMapping] = (),
        *,
        scientific_outputs: Iterable[ScientificOutputSelection] = (),
        preparation_readiness: Iterable[ServiceReadiness] = (),
        preparation_outcomes: Iterable[GroupCommandOutcome] = (),
    ) -> ControllerCommandResult:
        """Record canonical Experiment start evidence inside a running Session."""

        rejection_details = None

        def command() -> dict[str, Any]:
            nonlocal rejection_details
            session = self._require_session()
            if session.current_state != SessionState.RUNNING:
                raise RuntimeError("Experiment start requires a running Session")
            if self._active_experiment_id is not None:
                raise RuntimeError(
                    f"Experiment '{self._active_experiment_id}' is already active"
                )
            if not experiment_id:
                raise ValueError("experiment_id is required")
            session.check_experiment_can_start(experiment_id)
            if self._synchronization_manager is None:
                raise RuntimeError("Experiment start requires SynchronizationManager Session Time")
            active_runtime_health_mapping = tuple(runtime_health_mapping)
            participants = tuple(expected_participants)
            start_details = dict(details) if details is not None else None
            outputs = tuple(scientific_outputs)
            existing = next((descriptor for descriptor in session.experiment_descriptors
                             if descriptor.experiment_id == experiment_id), None)
            if existing is not None:
                if outputs and outputs != existing.scientific_outputs:
                    raise ValueError("Scientific outputs conflict with existing Experiment descriptor")
                outputs = existing.scientific_outputs
            records = []
            outcomes = []
            try:
                records = list(preparation_readiness)
                outcomes = list(preparation_outcomes)
                if any(not isinstance(record, ServiceReadiness) for record in records):
                    raise TypeError("Preparation readiness must use ServiceReadiness")
                session.record_service_readiness(records)
                if any(record.required and not record.ready for record in records):
                    raise RuntimeError("Required Experiment preparation failed")
                for outcome in outcomes:
                    if (outcome.session_id != session.session_id or
                            outcome.command_type != "prepare_experiment_scientific_outputs"):
                        raise ValueError("Preparation command outcome does not match this Session/command")
                    if outcome.unresolved_outcomes or outcome.outcome == "unresolved":
                        raise RuntimeError("Required Experiment preparation remains unresolved")
                    if outcome.outcome != "succeeded" or not outcome.command_results:
                        raise RuntimeError("Required remote Experiment preparation failed")
                    for result in outcome.command_results:
                        if (result.session_id != session.session_id or result.command_id != outcome.command_id
                                or result.payload.get("experiment_id") != experiment_id):
                            raise ValueError("Preparation command result does not match requested Experiment")
                        if result.status != "succeeded" or not result.success:
                            raise RuntimeError("Required remote Experiment preparation is not confirmed successful")
                        readiness = result.payload.get("preparation")
                        if not isinstance(readiness, dict) or readiness.get("ready") is not True:
                            raise RuntimeError("Required remote scientific preparation did not succeed")
                if any(output.source_node_id != self._acquisition_node.node_id for output in outputs):
                    raise ValueError("Scientific output references an unknown AcquisitionNode")
                preparation = self._acquisition_node.prepare_experiment_scientific_outputs(experiment_id, outputs)
                records.append(preparation)
                session.record_service_readiness((preparation,))
                if preparation.required and not preparation.ready:
                    raise RuntimeError(f"Scientific output preparation failed: {preparation.reason}")
            except Exception as error:
                message = RuntimeEvidenceMessage(
                    evidence_id=uuid4().hex, session_id=session.session_id,
                    evidence_type="experiment_start_rejected", source_id=self._component_id,
                    payload={"experiment_id": experiment_id, "reason": str(error),
                             "session_time_s": self._current_session_time_s(),
                             "preparations": [record.to_dict() for record in records if isinstance(record, ServiceReadiness)],
                             "command_outcomes": [outcome.to_dict() for outcome in outcomes if isinstance(outcome, GroupCommandOutcome)]},
                    is_persistent=True,
                )
                rejection_details = {"rejection_evidence": message.to_dict()}
                self._ingestor.receive_runtime_evidence(message)
                raise
            experiment_start_session_time_s = self._current_session_time_s()
            if experiment_start_session_time_s is None:
                raise RuntimeError(
                    "Experiment start requires SynchronizationManager Session Time"
                )
            session.ensure_experiment_descriptor(
                experiment_id,
                start_details,
                participants,
                scientific_outputs=outputs,
            )
            evidence = session.record_experiment_lifecycle(
                experiment_id=experiment_id,
                event_type="experiment_start",
                session_time_s=experiment_start_session_time_s,
                details=start_details,
            )
            self._active_experiment_id = experiment_id
            self._active_experiment_runtime_health_mapping = (
                active_runtime_health_mapping
            )
            self._acquisition_node.activate_experiment_runtime_context(
                ActiveExperimentRuntimeContext(
                    experiment_id=experiment_id,
                    experiment_start_session_time_s=(
                        experiment_start_session_time_s
                    ),
                )
            )
            self._acquisition_node.activate_experiment_runtime_health_mapping(
                experiment_id,
                active_runtime_health_mapping
            )
            return evidence.to_dict()

        try:
            details = command()
        except Exception as error:
            return self._record_failed_command("start_experiment", error, rejection_details)
        return self._record_successful_command("start_experiment", details)

    @service_operation()
    def stop_experiment(
        self,
        experiment_id: str,
        details: dict[str, Any] | None = None,
    ) -> ControllerCommandResult:
        """Record canonical Experiment stop evidence without stopping Session."""

        def command() -> dict[str, Any]:
            session = self._require_session()
            if session.current_state != SessionState.RUNNING:
                raise RuntimeError("Experiment stop requires a running Session")
            if self._active_experiment_id is None:
                raise RuntimeError("No Experiment is active")
            if experiment_id != self._active_experiment_id:
                raise RuntimeError(
                    f"Active Experiment is '{self._active_experiment_id}', "
                    f"not '{experiment_id}'"
                )
            return self._end_experiment(
                experiment_id=experiment_id,
                event_type="experiment_stop",
                details=details,
            )

        return self._run_command("stop_experiment", command)

    @service_operation()
    def stop_session(self, reason: str | None = None) -> ControllerCommandResult:
        """Stop runtime cleanup first, then move Session to stopping."""

        session = self._require_session()
        if self._normal_stop_task is not None:
            return self._record_failed_command("stop_session", RuntimeError("Normal Stop is in progress"))
        self._runtime_cleanup_confirmed = False
        try:
            runtime_result = self._acquisition_node.stop_runtime()
            self._runtime_cleanup_confirmed = self._acquisition_node.status()["cleanup_confirmed"]
            if self._active_experiment_id is not None:
                self._end_experiment(self._active_experiment_id, "experiment_stop", details={"reason": reason})
        except Exception as error:
            self._mark_session_failed(str(error))
            return self._record_failed_command("stop_session", error)
        session.stop(reason=reason)
        return self._record_successful_command(
            "stop_session",
            {
                "session_state": session.current_state.value,
                "runtime_result": runtime_result,
            },
        )

    @service_operation()
    def finalize_session(self) -> ControllerCommandResult:
        """Persist Phase 13 products, completing only a stopping Session."""

        session = self._require_session()
        if self._artifact_collection_in_progress or self._acquisition_publication_active or self._acquisition_archival_active or self._normal_stop_task is not None:
            return self._record_failed_command(
                "finalize_session", RuntimeError("Artifact collection/publication is in progress"))
        if self._acquisition_marker_session is session:
            try:
                if not self._acquisition_marker_confirmed:
                    raise RuntimeError("Controller-owned evidence is missing durable acquisition publication confirmation")
                return self._record_successful_command("finalize_session", self._complete_preserved_acquisition(session))
            except Exception as error:
                return self._record_failed_command("finalize_session", error)
        if session.current_state not in {
                SessionState.STOPPING, SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED}:
            return self._record_failed_command(
                "finalize_session", RuntimeError("Session must end acquisition before finalization"))
        self._finalization_confirmation = None
        self._archived_controller_action_decisions = {}
        try:
            if self._ingestor is None:
                raise RuntimeError("Session finalization requires an explicit Ingestor reference")
            ingest_state = self._session_ingest_state()
            compiled_runtime_evidence = (
                self._ingestor.compile_persistent_runtime_evidence()
            )
            decision_snapshot = self._controller_decision_evidence_snapshot(session.session_id)
            owned_snapshot = self._controller_owned_session_evidence_snapshot(session.session_id)
            compiled_messages = {
                message.evidence_id: message.to_dict()
                for message in compiled_runtime_evidence["runtime_evidence"]
            }
            if any(compiled_messages.get(identity) != contents
                   for identity, contents in decision_snapshot.items()):
                raise RuntimeError("Required Controller decision evidence is missing from persistent compilation")
            if any(json.dumps(compiled_messages.get(identity), sort_keys=True) != json.dumps(contents, sort_keys=True)
                   for identity, contents in owned_snapshot.items()):
                raise RuntimeError("Required Controller-owned evidence is missing from persistent compilation")
            artifact_collection_handoff = self._ingestor.compile_artifact_collection_handoff(
                session.session_id
            )
            archive_paths = self._storage_manager.write_evidence_archive(
                session.session_id,
                compiled_runtime_evidence,
            )
            if not isinstance(archive_paths, dict) or not all(
                isinstance(archive_paths.get(name), Path)
                for name in ("runtime_evidence", "ingest_audit", "compilation_summary")
            ):
                raise RuntimeError("Evidence Archive write confirmation is unavailable")
            final_record_path = self._write_final_session_record()
            if decision_snapshot != self._controller_decision_evidence_snapshot(session.session_id):
                raise RuntimeError("Controller decision evidence changed during final persistence")
            if owned_snapshot != self._controller_owned_session_evidence_snapshot(session.session_id):
                raise RuntimeError("Controller-owned evidence changed during final persistence")
        except Exception as error:
            self._mark_session_failed(str(error))
            return self._record_failed_command("finalize_session", error)

        if session.current_state == SessionState.STOPPING:
            session.complete()
        self._archived_controller_action_decisions = decision_snapshot
        self._finalization_confirmation = (ingest_state, str(final_record_path))
        return self._record_successful_command(
            "finalize_session",
            {
                "session_state": session.current_state.value,
                "evidence_archive_paths": {
                    name: str(path)
                    for name, path in archive_paths.items()
                },
                "session_record_path": str(final_record_path),
                "artifact_collection_handoff": artifact_collection_handoff,
            },
        )

    @service_operation()
    async def release_session(self) -> ControllerCommandResult:
        """Release a terminal binding after confirmed cleanup and final persistence."""
        session = self._session
        try:
            session = self._require_session()
            if self._normal_stop_task is not None:
                raise RuntimeError("Normal Stop is in progress")
            if session.current_state not in {SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED}:
                raise RuntimeError("Session release requires a terminal Session")
            if not session.cleanup_occurred or not self._runtime_cleanup_confirmed:
                raise RuntimeError("Session runtime cleanup is unconfirmed")
            if self._artifact_collection_in_progress or self._active_experiment_id is not None:
                raise RuntimeError("Session-specific work remains active")
            if self._acquisition_node is not None:
                status = self._acquisition_node.status()
                if status["is_running"] or not status["cleanup_confirmed"]:
                    raise RuntimeError("AcquisitionNode cleanup is unconfirmed")
            if self._synchronization_manager is not None and self._synchronization_manager.is_running:
                raise RuntimeError("Session Time is still running")
            if self._finalization_confirmation is None:
                raise RuntimeError("Required final persistence is unconfirmed")
            ingest_state, record_path = self._finalization_confirmation
            if ingest_state != self._session_ingest_state():
                raise RuntimeError("Accepted intake changed after final persistence")
            with self._storage_manager.session_preservation_guard(session.session_id) as confirmation:
                self._require_controller_decision_archival(session.session_id, confirmation)
                # Refresh the pre-completion record to preserve the actual terminal outcome.
                if self._kill_closeout_session is not session:
                    record_path = str(self._write_final_session_record())
            subscriptions = self._launch_subscriptions
            for subscription in subscriptions:
                await subscription.unsubscribe()
                if self._session is not session:
                    raise RuntimeError("Controller Session binding changed during release")
            # No await inside this guard: archive/record writes cannot overtake commitment.
            with self._storage_manager.session_preservation_guard(session.session_id) as confirmation:
                if ingest_state != self._session_ingest_state():
                    raise RuntimeError("Accepted intake changed during Session release")
                self._require_controller_decision_archival(session.session_id, confirmation)
                record = confirmation["session_record"]
                lifecycle = record.get("session_lifecycle_evidence", [])
                if (record.get("accepted_session_config", {}).get("session_id") != session.session_id
                        or record.get("final_session_status") != session.final_status
                        or not lifecycle or lifecycle[-1].get("to_state") != session.current_state.value):
                    raise RuntimeError("Terminal Session Record preservation is unconfirmed")
                outcome = {"session_id": session.session_id,
                           "session_state": session.current_state.value,
                           "final_session_status": dict(session.final_status),
                           "session_record_path": record_path}
                if self._session is not session:
                    raise RuntimeError("Controller Session binding changed during release")
                self._last_released_session = outcome
                self._session = None
                self._launch_communication = None
                self._reserved_participants = ()
                self._launch_result_window_s = None
                self._launch_subscriptions = ()
                self._runtime_cleanup_confirmed = False
                self._finalization_confirmation = None
                self._archived_controller_action_decisions = {}
                self._controller_action_decisions.clear()
                self._controller_action_decision_evidence.clear()
                self._acquisition_marker_session = None
                self._acquisition_marker = None
                self._acquisition_marker_confirmed = False
                self._kill_closeout_session = None
                self._kill_closeout = None
                self._active_experiment_runtime_health_mapping = ()
                self._command_results.clear()
        except Exception as error:
            if self._session is not session:
                # A stale operation must not record its failure in a newer binding.
                return ControllerCommandResult(
                    "release_session", False, {"session_id": session.session_id},
                    f"{type(error).__name__}: {error}",
                )
            return self._record_failed_command("release_session", error)
        return self._record_successful_command("release_session", outcome)

    @service_operation(new_work=True)
    def collect_session_artifacts(self) -> ControllerCommandResult:
        """Initiate post-session collection without changing lifecycle policy."""
        try:
            session = self._require_session()
            if session.current_state not in {SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED}:
                raise RuntimeError("Artifact collection requires an ended Session")
            handoff = self._ingestor.compile_artifact_collection_handoff(session.session_id)
            result = self._storage_manager.collect_artifacts(handoff)
        except Exception as error:
            return self._record_failed_command("collect_session_artifacts", error)
        details = {"artifact_collection_result": result.to_dict()}
        if not result.succeeded:
            return self._record_failed_command(
                "collect_session_artifacts", RuntimeError("Artifact collection had failures"), details)
        return self._record_successful_command("collect_session_artifacts", details)

    @service_operation(new_work=True)
    async def collect_session_artifacts_with_evidence(self) -> ControllerCommandResult:
        """Await collection evidence publication after acquisition end, before finalization."""
        if self._artifact_collection_in_progress:
            return self._record_failed_command(
                "collect_session_artifacts_with_evidence",
                RuntimeError("Artifact collection/publication is already in progress"))
        self._artifact_collection_in_progress = True
        try:
            session = self._require_session()
            if session.current_state != SessionState.STOPPING:
                raise RuntimeError("Collection evidence requires acquisition end before processing finalization")
            if self._acquisition_node.status()["is_running"]:
                raise RuntimeError("Artifact collection requires stopped acquisition runtime")
            handoff = self._ingestor.compile_artifact_collection_handoff(session.session_id)
            result = await self._storage_manager.collect_artifacts_with_evidence(handoff)
        except Exception as error:
            return self._record_failed_command("collect_session_artifacts_with_evidence", error)
        finally:
            self._artifact_collection_in_progress = False
        details = {"artifact_collection_result": result.to_dict()}
        if not result.succeeded:
            return self._record_failed_command(
                "collect_session_artifacts_with_evidence", RuntimeError("Artifact collection had failures"), details)
        return self._record_successful_command("collect_session_artifacts_with_evidence", details)

    @service_operation(new_work=True)
    def collect_saved_session_artifacts(self, session_id: str, *, evidence_id: str) -> ControllerCommandResult:
        """Coordinate explicit saved-handoff collection without restoring a Session binding."""
        try:
            details = self._storage_manager.collect_saved_artifacts(session_id, evidence_id=evidence_id)
        except Exception as error:
            return self._record_failed_command("collect_saved_session_artifacts", error)
        if not details["archival_confirmed"] or not details["artifact_collection_result"]["succeeded"]:
            return self._record_failed_command("collect_saved_session_artifacts",
                RuntimeError("Collection or collection-evidence preservation is incomplete"), details)
        return self._record_successful_command("collect_saved_session_artifacts", details)

    def get_status(self) -> dict[str, Any]:
        """Return a small Controller view without redefining owned lifecycles."""

        return {
            "session_id": self._session.session_id if self._session else None,
            "session_state": (
                self._session.current_state.value if self._session else None
            ),
            "acquisition_runtime": (
                self._acquisition_node.status() if self._acquisition_node is not None else None
            ),
            "active_experiment_runtime_health_mapping": (
                self._active_experiment_runtime_health_mapping
            ),
            "last_command": self._last_result,
            "last_released_session": self._last_released_session,
        }

    def maintenance_blockers(self, ingestor, storage_manager) -> list[str]:
        """Report Controller-owned obligations without stopping other services."""
        blockers = []
        if self._session is not None:
            if self._session.current_state not in {SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED}:
                blockers.append("Active Session")
            if not self._runtime_cleanup_confirmed:
                blockers.append("Unconfirmed Session cleanup")
            if self._finalization_confirmation is None:
                blockers.append("Unconfirmed final Session persistence")
            if self._controller_action_decision_evidence:
                try:
                    with storage_manager.session_preservation_guard(self._session.session_id) as confirmation:
                        self._require_controller_decision_archival(self._session.session_id, confirmation)
                except Exception as error:
                    blockers.append(f"Controller decision preservation: {error}")
        if self._artifact_collection_in_progress or self._active_experiment_id is not None:
            blockers.append("Unfinished Controller-coordinated work")
        if self._framework_shutdown_active:
            interface = getattr(self, "_maintenance", None)
            active = interface._attempt if interface is not None else None
            if active is None or active.get("framework_stop_attempt_id") != self._framework_shutdown_attempt_id:
                blockers.append("Unfinished framework shutdown coordination")
        if self._reconciliation_evidence:
            confirmation = storage_manager.get_framework_preservation_confirmation()
            if (confirmation is None or any(not ingestor.has_durable_runtime_evidence(message)
                    or message.to_dict() not in confirmation["runtime_evidence"]
                    for message in self._reconciliation_evidence)):
                blockers.append("Unpreserved Controller reconciliation evidence")
        return blockers

    @property
    def reconciliation_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Retained informational findings for existing publication/preservation paths."""
        return tuple(RuntimeEvidenceMessage.from_dict(deepcopy(m.to_dict()))
                     for m in self._reconciliation_evidence)

    @service_operation()
    async def reconcile_outcomes(self, *, session_id: str | None = None,
                                 participants: Iterable[RuntimeParticipant] | None = None,
                                 communication: NatsControllerCommunication | None = None,
                                 result_window_s: float | None = None) -> dict[str, Any]:
        """Read retained scoped outcomes and current preservation without performing recovery."""
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError("Reconciliation requires a real Session identity or framework scope")
        if participants is not None:
            participants = tuple(participants)
            self._validate_participant_reconciliation(participants, result_window_s)
            if session_id is not None or communication is None:
                raise ValueError("Participant observation requires framework scope and current communication")
        elif communication is not None or result_window_s is not None:
            raise ValueError("Participant observation requires an explicit known scope")
        interface = getattr(self, "_maintenance", None)
        storage_manager, evidence_ingestor, source_id = self._storage_manager, self._ingestor, self._component_id
        if participants is not None and interface is not None:
            # Operational startup already has explicit evidence dependencies and participant identity.
            storage_manager, evidence_ingestor = interface.storage_manager, interface.ingestor
            source_id = interface.participant.component_id
        findings = {"session_id": session_id, "controller_id": source_id,
                    "framework_attempts": [], "session_command_outcomes": [],
                    "session_participant_outcomes": [],
                    "received_command_results": [],
                    "unresolved": [], "preservation_confirmed": False}
        if participants is not None:
            findings["participant_states"] = await self._observe_known_participants(
                participants, communication, result_window_s)
            findings["reported_session_ids"] = sorted({identity
                for entry in findings["participant_states"] for identity in entry["reported_session_ids"]})
            findings["unresolved"].extend({"participant": entry["participant"], "reason": entry["reason"]}
                for entry in findings["participant_states"] if entry["observed_state"] == "unknown")
        confirmation = None
        try:
            if storage_manager is not None:
                confirmation = (storage_manager.get_framework_preservation_confirmation()
                    if session_id is None else storage_manager.get_session_preservation_confirmation(session_id))
        except (OSError, ValueError) as error:
            findings["unresolved"].append({"session_id": session_id, "reason": str(error)})
        findings["preservation_confirmed"] = confirmation is not None
        if confirmation is None:
            findings["unresolved"].append({"session_id": session_id,
                "reason": "Current durable Evidence Archive preservation cannot be confirmed"})
        if session_id is None:
            archived = confirmation["runtime_evidence"] if confirmation else []
            with self._service_operation_lock:
                attempts = deepcopy(tuple(self._framework_shutdown_attempts.values()))
            for attempt in attempts:
                report = self._reconcile_framework_attempt(attempt, archived)
                findings["framework_attempts"].append(report)
                findings["unresolved"].extend(report["unresolved"])
        else:
            session = self._session
            if session is None or session.session_id != session_id:
                findings["unresolved"].append({"session_id": session_id,
                    "reason": "No retained Controller binding for this Session; no application restoration attempted"})
            else:
                findings["session_state"] = session.current_state.value
                if self._launch_communication is not None:
                    for result in self._launch_communication.command_results:
                        if result.session_id == session_id:
                            # Preserve replies as replies, not proof of whole-Session completion.
                            findings["received_command_results"].append(result.to_dict())
                for result in tuple(self._command_results):
                    details = result.details
                    associated_session_id = details.get("session_id") if isinstance(details, Mapping) else None
                    if not isinstance(associated_session_id, str) or not associated_session_id:
                        findings["unresolved"].append({"session_id": None, "command": result.command,
                            "succeeded": result.succeeded, "error": result.error,
                            "reason": "Command outcome has no confirmed Session association"})
                        continue
                    if associated_session_id != session_id:
                        continue
                    # These are command outcomes, not proof that every participant completed.
                    snapshot = result.to_dict()
                    snapshot["details"] = deepcopy(dict(details))
                    findings["session_command_outcomes"].append(snapshot)
                if confirmation and confirmation["session_record"].get("accepted_session_config", {}).get("session_id") != session_id:
                    findings["preservation_confirmed"] = False
                    findings["unresolved"].append({"session_id": session_id, "reason": "Session Record identity conflicts"})
                for participant in session.configuration.expected_runtime_participants:
                    reports = [entry for result in findings["session_command_outcomes"]
                               for entry in result["details"].get("initialization", ())
                               if entry.get("participant") == participant.to_dict()]
                    outcomes = {entry.get("outcome") for entry in reports}
                    outcome = ("conflicting" if len(outcomes) > 1 else "completed" if outcomes == {"succeeded"}
                               else "failed" if outcomes == {"failed"} else "unresolved")
                    findings["session_participant_outcomes"].append({"participant": participant.to_dict(),
                        "operation": "initialize_session", "outcome": outcome, "reports": deepcopy(reports)})
                    if outcome != "completed":
                        findings["unresolved"].append({"session_id": session_id,
                            "participant": participant.to_dict(), "reason": "No retained confirmed participant outcome"})
        previous = next((message for message in reversed(self._reconciliation_evidence)
                         if message.payload.get("findings", {}).get("session_id") == session_id), None)
        if previous is not None and previous.payload["findings"] == findings:
            current = storage_manager.get_framework_preservation_confirmation() if storage_manager else None
            preserved = bool(current and previous.to_dict() in current["runtime_evidence"])
            return {"findings": deepcopy(findings), "evidence": previous.to_dict(), "unchanged": True,
                    "acceptance_confirmed": bool(evidence_ingestor and evidence_ingestor.has_durable_runtime_evidence(previous)),
                    "archival_confirmed": preserved, "preservation_warning": None if preserved
                    else "Current reconciliation evidence archival is unconfirmed"}
        message = RuntimeEvidenceMessage(uuid4().hex, None, "controller_reconciliation",
            source_id, {"findings": deepcopy(findings)}, True)
        self._reconciliation_evidence.append(message)
        if interface is None:
            return {"findings": findings, "evidence": message.to_dict(), "unchanged": False,
                    "publication_confirmed": False, "acceptance_confirmed": False,
                    "archival_confirmed": False, "preservation_warning": "Controller framework evidence interface is not configured"}
        # Publishing new findings must not silently repair an unconfirmed archive.
        framework_safe = bool(storage_manager and storage_manager._framework_evidence_write_safe())
        status = await interface._record_framework_evidence(message, archive=framework_safe, require_existing_archive=True)
        return {"findings": findings, **status, "unchanged": False}

    def _validate_participant_reconciliation(self, participants, result_window_s) -> None:
        from math import isfinite
        supported = {"controller", "acquisition_node", "ingestor", "storage_manager", "synchronization_manager"}
        own_identity = getattr(getattr(self, "_maintenance", None), "participant",
                               RuntimeParticipant("controller", self._component_id))
        for participant in participants:
            if (not isinstance(participant, RuntimeParticipant) or participant.component_type not in supported
                    or participant == own_identity):
                raise ValueError("Reconciliation requires explicit remote principal-service identities")
            build_runtime_subject(None, "command", participant.component_type,
                                  participant.component_id, "check_readiness")
        if len(set(participants)) != len(participants):
            raise ValueError("Reconciliation participant identities must be unique")
        if (participants or result_window_s is not None) and (
                not isinstance(result_window_s, (int, float)) or isinstance(result_window_s, bool)
                or not isfinite(result_window_s) or result_window_s < 0
                or participants and result_window_s == 0):
            raise ValueError("Known participants require an explicit finite positive result window")

    async def _observe_known_participants(self, participants, communication, result_window_s) -> list[dict]:
        observations = []
        for participant in participants:
            entry = {"participant": participant.to_dict(), "observed_state": "unknown",
                     "reported_session_ids": [], "details": None,
                     "reason": "Current participant state is unconfirmed"}
            observations.append(entry)
            try:
                result = await asyncio.wait_for(communication.request_command(
                    participant, "check_readiness", None, {}, result_window_s), result_window_s)
            except Exception as error:
                entry["reason"] = str(error) or "Current participant state is unconfirmed"
                continue
            if result is None or not result.success:
                if result is not None and result.reason:
                    entry["reason"] = result.reason
                continue
            payload = result.payload
            if not isinstance(payload, dict):
                continue
            node = participant.component_type == "acquisition_node"
            if node:
                readiness = payload.get("acquisition_node_readiness")
                if not isinstance(readiness, dict) or readiness.get("node_id") != participant.component_id:
                    continue
            else:
                owner = payload.get("participant")
                readiness = payload.get("service_readiness")
                if owner is not None:
                    if owner != participant.to_dict():
                        continue
                elif (not isinstance(readiness, dict)
                        or readiness.get("component_id") != participant.component_id
                        or readiness.get("component_type") != participant.component_type):
                    continue
            entry["details"] = deepcopy(payload)
            diagnostics = payload.get("service_diagnostics")
            diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
            identities = []
            if node:
                owned = diagnostics.get("participation", {})
                if isinstance(owned, dict):
                    identities.extend((owned.get("session_id"), owned.get("reserved_for_session_id")))
                    running, failed = owned.get("is_running"), owned.get("failed")
                    if type(running) is bool and type(failed) is bool:
                        entry["observed_state"] = "failed" if failed else "active" if running else "stopped"
            else:
                retired = payload.get("operational_retirement_confirmed")
                if type(retired) is bool:
                    entry["observed_state"] = "stopped" if retired else "active"
                for key in ("session_binding", "session_intake"):
                    owned = diagnostics.get(key, {})
                    if isinstance(owned, dict):
                        identities.append(owned.get("session_id"))
                identities.append(diagnostics.get("prepared_session_id"))
                for key in ("restricted_timing_scopes", "unfinished_archive_scopes"):
                    scopes = diagnostics.get(key, ())
                    if isinstance(scopes, (list, tuple)):
                        identities.extend(scopes)
                collection = diagnostics.get("collection_evidence", ())
                if isinstance(collection, (list, tuple)):
                    for evidence in collection:
                        if isinstance(evidence, dict) and evidence.get("archival_outcome") == "unresolved":
                            identities.append(evidence.get("session_id"))
            entry["reported_session_ids"] = sorted({identity for identity in identities
                                                    if isinstance(identity, str) and identity})
            if entry["observed_state"] != "unknown":
                entry["reason"] = None
        return observations

    def _reconcile_framework_attempt(self, attempt: dict, archived: list[dict]) -> dict:
        report = {"stop_attempt_id": attempt["stop_attempt_id"],
                  "recorded_outcome": attempt["outcome"], "participant_outcomes": [], "unresolved": []}
        archived_results = [entry["result"] for message in archived
            if message.get("source_id") == self._component_id
            and message.get("evidence_type") == "service_maintenance_evidence"
            and message["payload"].get("stop_attempt_id") == attempt["stop_attempt_id"]
            for entry in message["payload"].get("results", ()) if entry.get("result") is not None]
        for participant in attempt["scope"]:
            commands = [c for c in attempt["commands"] if c["participant"] == participant
                        and c["command_type"] in {"stop", "kill", "cancel"}]
            entry = {"participant": deepcopy(participant), "outcome": "unresolved",
                     "command_id": None, "archival_confirmed": False}
            reason = "No confirmed retirement command result"
            if commands:
                command = commands[-1]
                entry["command_id"] = command["command_id"]
                candidates = [r["result"] for r in attempt["results"]
                    if r["command_id"] == command["command_id"] and r.get("result") is not None]
                if candidates:
                    result = candidates[-1]
                    payload = result.get("payload", {})
                    owned = payload.get("attempt", {}) or {}
                    correlated = (result.get("command_id") == command["command_id"]
                        and result.get("session_id") is None
                        and result.get("source_id") == participant["component_id"]
                        and result.get("target_id") == self._component_id
                        and owned.get("target") == participant
                        and owned.get("stop_attempt_id") == command["payload"]["stop_attempt_id"]
                        and owned.get("framework_stop_attempt_id") == attempt["stop_attempt_id"])
                    conflicts = [r for r in (*candidates, *archived_results)
                                 if r.get("command_id") == command["command_id"] and r != result]
                    if conflicts or not correlated:
                        entry["outcome"] = "conflicting"
                        reason = "Participant evidence conflicts or cannot be correlated"
                    elif (result.get("status") == "succeeded" and result.get("success") is True
                          and payload.get("outcome") == "completed"
                          and payload.get("termination_confirmed") is True):
                        entry["outcome"] = "completed"
                    elif result.get("status") == "failed" and result.get("success") is False:
                        entry["outcome"] = "failed"
                        reason = result.get("reason") or "Participant reported failure"
                    entry["archival_confirmed"] = result in archived_results
                    entry["result"] = deepcopy(result)
            if entry["outcome"] != "completed":
                report["unresolved"].append({"stop_attempt_id": attempt["stop_attempt_id"],
                    "participant": deepcopy(participant), "command_id": entry["command_id"], "reason": reason})
            report["participant_outcomes"].append(entry)
        completed = sum(p["outcome"] == "completed" for p in report["participant_outcomes"])
        report["partial_completion"] = 0 < completed < len(report["participant_outcomes"])
        return report

    def maintenance_diagnostics(self, ingestor, storage_manager) -> dict[str, Any]:
        """Report owned bindings and actual framework-attempt results without executing recovery."""
        interface = getattr(self, "_maintenance", None)
        blockers = self.maintenance_blockers(ingestor, storage_manager)
        return {
            "session_binding": {"session_id": self._session.session_id if self._session else None,
                "state": self._session.current_state.value if self._session else None,
                "cleanup_confirmed": self._runtime_cleanup_confirmed,
                "administrative_outcome": (interface._administrative_outcome({"session_id": self._session.session_id})
                                            if interface and self._session else None)},
            "last_binding_release": dict(self._last_released_session) if self._last_released_session else None,
            "last_reconciliation": (deepcopy(self._reconciliation_evidence[-1].payload["findings"])
                                    if self._reconciliation_evidence else None),
            "framework_attempts": {identity: {"actual_outcome": attempt["outcome"],
                "obligation_outcome": "completed" if attempt["outcome"] == "completed" else
                    (interface._administrative_outcome({"framework_stop_attempt_id": identity}) if interface else None) or "unresolved",
                "participant_scope": deepcopy(attempt["scope"]),
                "recovery_assessment": None if attempt["outcome"] == "completed" else "administrator_intervention"}
                for identity, attempt in self._framework_shutdown_attempts.items()},
            "restricted_coordination": "current Session and unfinished framework attempts" if blockers else None,
            "blocking_conditions": blockers,
        }

    async def _close_maintenance_resources(self, force: bool) -> None:
        for subscription in self._launch_subscriptions:
            await subscription.unsubscribe()
        self._launch_subscriptions = ()

    @service_operation()
    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Controller has no Session")
        return self._session

    def _run_command(self, name: str, command: Any) -> ControllerCommandResult:
        try:
            details = command()
        except Exception as error:
            return self._record_failed_command(name, error)
        else:
            return self._record_successful_command(name, details)

    def _record_failed_command(
        self, name: str, error: Exception, details: Any = None
    ) -> ControllerCommandResult:
        result = ControllerCommandResult(
            command=name,
            succeeded=False,
            error=f"{type(error).__name__}: {error}",
            details=details,
        )
        return self._record_command_result(result)

    def _record_successful_command(
        self, name: str, details: Any
    ) -> ControllerCommandResult:
        result = ControllerCommandResult(
            command=name,
            succeeded=True,
            details=details,
        )
        return self._record_command_result(result)

    def _record_command_result(
        self, result: ControllerCommandResult
    ) -> ControllerCommandResult:
        self._last_result = result
        self._command_results.append(result)
        return result

    def _runtime_start_failed(self, runtime_result: Any) -> bool:
        if getattr(runtime_result, "succeeded", True) is False:
            return True
        if isinstance(runtime_result, dict):
            if runtime_result.get("succeeded") is False:
                return True
            return any(
                getattr(item, "succeeded", True) is False
                for item in runtime_result.get("device_start_results", ())
            )
        return False

    def _attempt_runtime_stop(self) -> None:
        self._runtime_cleanup_confirmed = False
        try:
            self._acquisition_node.stop_runtime()
            self._runtime_cleanup_confirmed = self._acquisition_node.status()["cleanup_confirmed"]
        except Exception as error:
            self._record_failed_command("stop_runtime_cleanup", error)

    def _end_experiment(
        self, experiment_id: str, event_type: str, details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = self._require_session().record_experiment_lifecycle(
            experiment_id, event_type, self._current_session_time_s(), details,
        )
        self._active_experiment_id = None
        self._active_experiment_runtime_health_mapping = ()
        self._acquisition_node.clear_experiment_runtime_context()
        self._acquisition_node.clear_experiment_runtime_health_mapping()
        self._acquisition_node.finalize_experiment_scientific_outputs(experiment_id)
        return evidence.to_dict()

    def _mark_session_failed(self, reason: str) -> None:
        session = self._require_session()
        if session.current_state == SessionState.RUNNING:
            if self._active_experiment_id is not None:
                try:
                    self._end_experiment(self._active_experiment_id, "experiment_fail", {"reason": reason})
                except Exception as error:
                    self._record_failed_command("finalize_experiment_cleanup", error)
            session.stop(reason=reason)
        if session.current_state in {SessionState.INITIALIZED, SessionState.STOPPING}:
            session.fail(reason=reason)

    def _session_record_evidence(self) -> dict[str, Any]:
        session = self._require_session()
        return {
            "accepted_session_config": session.configuration,
            "lifecycle_evidence": session.transition_history,
            "readiness_evidence": session.readiness_checks,
            "device_readiness_evidence": session.device_readiness_summary,
            "service_readiness_evidence": session.service_readiness_checks,
            "accepted_acquisition_envelopes": (
                self._storage_manager.get_envelopes_for_session(session.session_id)
            ),
            "ingest_audit_records": self._ingestor.ingest_audit if self._ingestor is not None else (),
            "final_session_status": session.final_status,
            "cleanup_evidence": {
                "cleanup_occurred": session.cleanup_occurred,
                "cleanup_sequence": session.cleanup_sequence,
            },
            "warnings_or_failures": tuple(
                result for result in self._command_results if not result.succeeded
            ),
            "experiment_lifecycle_evidence": session.experiment_lifecycle_evidence,
            "experiment_descriptors": session.experiment_descriptors,
        }

    def _session_ingest_state(self) -> tuple[Any, ...]:
        return (self._ingestor.accepted_envelopes, self._ingestor.ingest_audit,
                self._ingestor.accepted_runtime_evidence, self._ingestor.runtime_evidence_audit)

    def _write_initial_session_record(self) -> Path:
        session = self._require_session()
        return self._storage_manager.write_initial_session_record(
            session.session_id,
            **self._session_record_evidence(),
        )

    def _write_final_session_record(self) -> Path:
        session = self._require_session()
        return self._storage_manager.write_final_session_record(
            session.session_id,
            **self._session_record_evidence(),
        )

    def _current_session_time_s(self) -> float | None:
        if self._synchronization_manager is None:
            return None
        return self._synchronization_manager.current_session_time_s
