"""Sequential single-session Controller v1 orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lab_sync_acquisition.acquisition_node import AcquisitionNode
from lab_sync_acquisition.device_adapter import DeviceReadiness
from lab_sync_acquisition.experiment_runtime import ExperimentRuntimeHealthMapping
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.session import (
    ExpectedParticipant,
    Session,
    SessionConfig,
    SessionState,
)
from lab_sync_acquisition.storage import PersistentStorageManager
from lab_sync_acquisition.synchronization import SynchronizationManager


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


class Controller:
    """Coordinates one Session through already-created runtime collaborators."""

    def __init__(
        self,
        acquisition_node: AcquisitionNode,
        ingestor: InMemoryIngestor,
        storage_manager: PersistentStorageManager,
        session_record_path: str | Path,
        synchronization_manager: SynchronizationManager | None = None,
    ) -> None:
        self._acquisition_node = acquisition_node
        self._ingestor = ingestor
        self._storage_manager = storage_manager
        self._session_record_path = Path(session_record_path)
        self._synchronization_manager = synchronization_manager
        self._session: Session | None = None
        self._active_experiment_id: str | None = None
        self._active_experiment_runtime_health_mapping: tuple[
            ExperimentRuntimeHealthMapping, ...
        ] = ()
        self._last_result: ControllerCommandResult | None = None
        self._command_results: list[ControllerCommandResult] = []

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
    ) -> ControllerCommandResult:
        """Record canonical Experiment start evidence inside a running Session."""

        def command() -> dict[str, Any]:
            session = self._require_session()
            if session.current_state != SessionState.RUNNING:
                raise RuntimeError("Experiment start requires a running Session")
            if self._active_experiment_id is not None:
                raise RuntimeError(
                    f"Experiment '{self._active_experiment_id}' is already active"
                )
            if not experiment_id:
                raise ValueError("experiment_id is required")
            active_runtime_health_mapping = tuple(runtime_health_mapping)
            session.ensure_experiment_descriptor(
                experiment_id,
                details,
                expected_participants,
            )
            evidence = session.record_experiment_lifecycle(
                experiment_id=experiment_id,
                event_type="experiment_start",
                session_time_s=self._current_session_time_s(),
                details=details,
            )
            self._active_experiment_id = experiment_id
            self._active_experiment_runtime_health_mapping = (
                active_runtime_health_mapping
            )
            self._acquisition_node.activate_experiment_runtime_health_mapping(
                active_runtime_health_mapping
            )
            return evidence.to_dict()

        return self._run_command("start_experiment", command)

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
            evidence = session.record_experiment_lifecycle(
                experiment_id=experiment_id,
                event_type="experiment_stop",
                session_time_s=self._current_session_time_s(),
                details=details,
            )
            self._active_experiment_id = None
            self._active_experiment_runtime_health_mapping = ()
            self._acquisition_node.clear_experiment_runtime_health_mapping()
            return evidence.to_dict()

        return self._run_command("stop_experiment", command)

    def stop_session(self, reason: str | None = None) -> ControllerCommandResult:
        """Stop runtime cleanup first, then move Session to stopping."""

        session = self._require_session()
        try:
            runtime_result = self._acquisition_node.stop_runtime()
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
        """Complete Session and write its existing v1 persistent evidence."""

        session = self._require_session()
        try:
            self._write_session_record()
        except Exception as error:
            self._mark_session_failed(str(error))
            return self._record_failed_command("finalize_session", error)

        session.complete()
        try:
            self._write_session_record()
        except Exception as error:
            return self._record_failed_command("finalize_session", error)
        return self._record_successful_command(
            "finalize_session",
            {
                "session_state": session.current_state.value,
                "session_record_path": str(self._session_record_path),
            },
        )

    def get_status(self) -> dict[str, Any]:
        """Return a small Controller view without redefining owned lifecycles."""

        return {
            "session_id": self._session.session_id if self._session else None,
            "session_state": (
                self._session.current_state.value if self._session else None
            ),
            "acquisition_runtime": self._acquisition_node.status(),
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
        self, name: str, error: Exception
    ) -> ControllerCommandResult:
        result = ControllerCommandResult(
            command=name,
            succeeded=False,
            error=f"{type(error).__name__}: {error}",
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
        except Exception:
            pass

    def _mark_session_failed(self, reason: str) -> None:
        session = self._require_session()
        if session.current_state == SessionState.RUNNING:
            session.stop(reason=reason)
        if session.current_state in {SessionState.INITIALIZED, SessionState.STOPPING}:
            session.fail(reason=reason)

    def _write_session_record(self) -> None:
        session = self._require_session()
        self._storage_manager.write_session_record(
            self._session_record_path,
            accepted_session_config=session.configuration,
            lifecycle_evidence=session.transition_history,
            readiness_evidence=session.readiness_checks,
            device_readiness_evidence=session.device_readiness_summary,
            service_readiness_evidence=session.service_readiness_checks,
            accepted_acquisition_envelopes=self._storage_manager.read_envelopes(),
            ingest_audit_records=self._ingestor.ingest_audit,
            final_session_status=session.final_status,
            cleanup_evidence={
                "cleanup_occurred": session.cleanup_occurred,
                "cleanup_sequence": session.cleanup_sequence,
            },
            warnings_or_failures=tuple(
                result for result in self._command_results if not result.succeeded
            ),
            experiment_lifecycle_evidence=session.experiment_lifecycle_evidence,
            experiment_descriptors=session.experiment_descriptors,
        )

    def _current_session_time_s(self) -> float | None:
        if self._synchronization_manager is None:
            return None
        return self._synchronization_manager.current_session_time_s
