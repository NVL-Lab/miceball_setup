"""Sequential single-session Controller v1 orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING
from collections.abc import Mapping
from uuid import uuid4

from lab_sync_acquisition.acquisition_health import HealthInterpretationEvidence
from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.communication import (
    GroupCommandOutcome,
    RuntimeEvidenceMessage,
    RuntimeParticipant,
)
from lab_sync_acquisition.device_adapter import DeviceReadiness
from lab_sync_acquisition.device import DeviceDeclaration
from lab_sync_acquisition.experiment_runtime import (
    ActiveExperimentRuntimeContext,
    ExperimentRuntimeHealthMapping,
)
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness
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
    from lab_sync_acquisition.nats_communication import NatsControllerCommunication


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
        self._artifact_collection_in_progress = False
        self._launch_communication: NatsControllerCommunication | None = None
        self._reserved_participants: tuple[RuntimeParticipant, ...] = ()
        self._launch_result_window_s: float | None = None
        self._launch_subscriptions = ()

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

    async def start_launched_session(self) -> ControllerCommandResult:
        """Start reserved distributed acquisition through existing runtime commands."""
        session = self._require_session()
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
            return self._record_failed_command("start_session", error, {"rollback": rollback})

    async def stop_launched_session(self, reason: str | None = None) -> ControllerCommandResult:
        """Stop/finalize every reserved node before releasing it, independently of global collection."""
        session = self._require_session()
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
        session.stop(reason)
        return self._record_successful_command("stop_session", {"session_state": session.current_state.value, "nodes": outcomes})

    @property
    def controller_action_decisions(self) -> tuple[ControllerActionDecision, ...]:
        """Recorded health-derived decisions in presentation order."""

        return tuple(self._controller_action_decisions)

    @property
    def expected_runtime_participants(self) -> tuple[RuntimeParticipant, ...]:
        """Expected runtime identities from the accepted SessionConfig."""

        return self._require_session().configuration.expected_runtime_participants

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
        self._controller_action_decisions.append(decision)
        return decision

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

    def start_session(self) -> ControllerCommandResult:
        """Start runtime first, then move Session lifecycle to running."""

        session = self._require_session()
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
                self._ingestor.receive_runtime_evidence(message)
                rejection_details = {"rejection_evidence": message.to_dict()}
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

    def stop_session(self, reason: str | None = None) -> ControllerCommandResult:
        """Stop runtime cleanup first, then move Session to stopping."""

        session = self._require_session()
        try:
            runtime_result = self._acquisition_node.stop_runtime()
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

    def finalize_session(self) -> ControllerCommandResult:
        """Persist Phase 13 evidence products, then complete the Session."""

        session = self._require_session()
        if self._artifact_collection_in_progress:
            return self._record_failed_command(
                "finalize_session", RuntimeError("Artifact collection/publication is in progress"))
        try:
            compiled_runtime_evidence = (
                self._ingestor.compile_persistent_runtime_evidence()
            )
            artifact_collection_handoff = self._ingestor.compile_artifact_collection_handoff(
                session.session_id
            )
            archive_paths = self._storage_manager.write_evidence_archive(
                session.session_id,
                compiled_runtime_evidence,
            )
            final_record_path = self._write_final_session_record()
        except Exception as error:
            self._mark_session_failed(str(error))
            return self._record_failed_command("finalize_session", error)

        session.complete()
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
        }

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
        try:
            self._acquisition_node.stop_runtime()
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
                self._storage_manager.read_envelopes()
            ),
            "ingest_audit_records": self._ingestor.ingest_audit if self._ingestor is not None else (),
            "runtime_evidence": self._ingestor.accepted_runtime_evidence if self._ingestor is not None else (),
            "runtime_evidence_audit": self._ingestor.runtime_evidence_audit if self._ingestor is not None else (),
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
