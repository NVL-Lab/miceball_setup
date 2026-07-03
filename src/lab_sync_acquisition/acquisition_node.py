"""Bounded acquisition-side execution for Phase 1 workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.acquisition_node_readiness import AcquisitionNodeReadiness
from lab_sync_acquisition.device_manager import DeviceManager
from lab_sync_acquisition.ingestor import InMemoryIngestor
from lab_sync_acquisition.service_readiness import ServiceReadiness
from lab_sync_acquisition.synchronization import SynchronizationManager


@dataclass(frozen=True)
class AcquisitionIterationSummary:
    """Inspectable result for one bounded acquisition iteration."""

    iteration_index: int
    collections_seen: int
    envelopes_sent: int
    accepted_count: int
    rejected_count: int


class AcquisitionNode:
    """Owns bounded acquisition execution without owning Session lifecycle."""

    def __init__(
        self,
        session_id: str,
        device_manager: DeviceManager,
        synchronization_manager: SynchronizationManager,
        ingestor: InMemoryIngestor,
        node_id: str | None = None,
        role: str | None = None,
        acquisition_configuration: Mapping[str, Any] | None = None,
        error_evidence_location: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._device_manager = device_manager
        self._synchronization_manager = synchronization_manager
        self._ingestor = ingestor
        self._node_id = node_id
        self._role = role
        self._error_evidence_location = error_evidence_location
        self._handoff_failure_policy = self._read_handoff_failure_policy(
            acquisition_configuration
        )
        (
            self._stream_batch_max_records,
            self._stream_batch_max_age_s,
        ) = self._read_stream_batch_configuration(acquisition_configuration)
        self._pending_stream_batches: dict[
            tuple[str | None, str, str], list[dict[str, Any]]
        ] = {}
        self._pending_stream_batch_started_session_times: dict[
            tuple[str | None, str, str], float
        ] = {}
        self._running = False
        self._iteration_index = 0
        self._last_error: str | None = None

    def check_ready(self) -> dict[str, Any]:
        """Return acquisition-side readiness using existing readiness contracts."""

        device_readiness = self._device_manager.check_readiness()
        service_readiness = (
            self._synchronization_manager.check_ready(),
            self._ingestor.check_ready(),
        )
        ready = device_readiness.all_ready and all(
            readiness.ready for readiness in service_readiness
        )
        return {
            "ready": ready,
            "device_readiness": device_readiness,
            "service_readiness": service_readiness,
        }

    def check_node_readiness(
        self,
        additional_service_readiness: Iterable[ServiceReadiness] = (),
    ) -> AcquisitionNodeReadiness:
        """Return Phase 2 readiness with explicit node and session identity."""

        if not self._node_id or not self._role:
            raise ValueError("Phase 2 node readiness requires node_id and role")
        device_readiness = self._device_manager.check_readiness()
        service_readiness = (
            self._synchronization_manager.check_ready(),
            self._ingestor.check_ready(),
            *additional_service_readiness,
        )
        readiness = AcquisitionNodeReadiness(
            node_id=self._node_id,
            session_id=self._session_id,
            role=self._role,
            device_readiness=device_readiness,
            service_readiness=service_readiness,
        )
        return readiness

    def start_acquisition(self) -> dict[str, Any]:
        """Start Session Time, record session_start evidence, and start devices."""

        session_time_s = self._synchronization_manager.start()
        session_start_audit = self._send_envelope(
            source_device_id="acquisition_node",
            record_kind="event",
            records=[
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_start",
                    "session_time_s": session_time_s,
                }
            ],
        )
        device_start_results = self._device_manager.start_all()
        self._running = True
        return {
            "session_time_s": session_time_s,
            "session_start_audit": session_start_audit,
            "device_start_results": device_start_results,
        }

    def run_one_iteration(self) -> AcquisitionIterationSummary:
        """Collect one bounded batch of records and send envelopes to ingestion."""

        if not self._running:
            raise RuntimeError("AcquisitionNode must be running before iteration")

        record_collections = self._device_manager.collect_records()
        self._iteration_index += 1
        envelopes_sent = 0
        accepted_count = 0
        rejected_count = 0

        for collection in record_collections:
            records = tuple(
                self._with_session_time(row)
                for row in collection.records
            )
            if collection.record_kind == "stream" and self._stream_batching_enabled():
                audits = self._append_stream_records(
                    source_device_id=collection.source_device_id,
                    record_kind=collection.record_kind,
                    records=records,
                )
            else:
                audits = (
                    self._send_envelope(
                        source_device_id=collection.source_device_id,
                        record_kind=collection.record_kind,
                        records=records,
                    ),
                )
            envelopes_sent += len(audits)
            accepted_count += sum(audit.accepted for audit in audits)
            rejected_count += sum(not audit.accepted for audit in audits)

        return AcquisitionIterationSummary(
            iteration_index=self._iteration_index,
            collections_seen=len(record_collections),
            envelopes_sent=envelopes_sent,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
        )

    def stop_acquisition(self) -> dict[str, Any]:
        """Stop Session Time, record session_stop evidence, and stop devices."""

        self._flush_pending_stream_batches()
        final_session_time_s = self._synchronization_manager.stop()
        session_stop_audit = self._send_envelope(
            source_device_id="acquisition_node",
            record_kind="event",
            records=[
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_stop",
                    "session_time_s": final_session_time_s,
                }
            ],
        )
        device_stop_results = self._device_manager.stop_all()
        device_shutdown_results = self._device_manager.shutdown_all()
        self._running = False
        return {
            "final_session_time_s": final_session_time_s,
            "session_stop_audit": session_stop_audit,
            "device_stop_results": device_stop_results,
            "device_shutdown_results": device_shutdown_results,
        }

    def abort_acquisition(self) -> dict[str, Any]:
        """Attempt minimal acquisition shutdown without defining a failure model."""

        result = self.stop_acquisition()
        return {
            **result,
            "aborted": True,
        }

    def status(self) -> dict[str, Any]:
        """Return simple acquisition-side runtime status."""

        return {
            "session_id": self._session_id,
            "is_running": self._running,
            "iteration_count": self._iteration_index,
            "last_error": self._last_error,
        }

    def _send_envelope(
        self,
        source_device_id: str,
        record_kind: str,
        records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> Any:
        envelope = AcquisitionRecordEnvelope(
            session_id=self._session_id,
            source_device_id=source_device_id,
            record_kind=record_kind,
            records=records,
            source_node_id=self._node_id,
        )
        envelope_data = envelope.to_dict()
        reconstructed_envelope = AcquisitionRecordEnvelope.from_dict(envelope_data)
        try:
            return self._ingestor.receive_envelope(reconstructed_envelope)
        except Exception as error:
            return self._record_handoff_failure(reconstructed_envelope, error)

    def _record_handoff_failure(
        self,
        envelope: AcquisitionRecordEnvelope,
        error: Exception,
    ) -> Any:
        if not self._error_evidence_location:
            raise RuntimeError(
                "Sender handoff failed but error_evidence_location is not configured"
            ) from error

        preserve = self._handoff_failure_policy == "must_preserve"
        evidence = {
            "session_id": envelope.session_id,
            "source_node_id": envelope.source_node_id,
            "source_device_id": envelope.source_device_id,
            "record_kind": envelope.record_kind,
            "record_count": len(envelope.records),
            "failure_type": type(error).__name__,
            "error_message": str(error),
            "policy_name": self._handoff_failure_policy,
            "action_taken": (
                "preserved_failed_envelope"
                if preserve
                else "recorded_drop_and_continued"
            ),
            "failure_session_time_s": (
                self._synchronization_manager.current_session_time_s
            ),
            "preserved_envelope": preserve,
        }
        if preserve:
            evidence["envelope"] = envelope.to_dict()

        evidence_directory = Path(self._error_evidence_location)
        evidence_directory.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_directory / "sender_handoff_failures.jsonl"
        with evidence_path.open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(evidence))
            evidence_file.write("\n")

        return _FailedHandoffAudit()

    def _with_session_time(self, row: dict[str, Any]) -> dict[str, Any]:
        if "session_time_s" in row:
            return dict(row)
        return {
            **row,
            "session_time_s": self._synchronization_manager.current_session_time_s,
        }

    def _append_stream_records(
        self,
        source_device_id: str,
        record_kind: str,
        records: tuple[dict[str, Any], ...],
    ) -> tuple[Any, ...]:
        key = (self._node_id, source_device_id, record_kind)
        pending = self._pending_stream_batches.get(key)
        if records:
            if pending is None:
                pending = []
                self._pending_stream_batches[key] = pending
                self._pending_stream_batch_started_session_times[key] = (
                    self._synchronization_manager.current_session_time_s
                )
            pending.extend(records)
        elif pending is None:
            return ()

        audits = []
        while (
            self._stream_batch_max_records is not None
            and len(pending) >= self._stream_batch_max_records
        ):
            batch = pending[: self._stream_batch_max_records]
            audit = self._send_envelope(
                source_device_id=source_device_id,
                record_kind=record_kind,
                records=tuple(batch),
            )
            del pending[: self._stream_batch_max_records]
            audits.append(audit)
            if pending:
                self._pending_stream_batch_started_session_times[key] = (
                    self._synchronization_manager.current_session_time_s
                )

        if pending and self._stream_batch_max_age_s is not None:
            batch_started = self._pending_stream_batch_started_session_times[key]
            batch_age = (
                self._synchronization_manager.current_session_time_s
                - batch_started
            )
            if batch_age >= self._stream_batch_max_age_s:
                audit = self._send_envelope(
                    source_device_id=source_device_id,
                    record_kind=record_kind,
                    records=tuple(pending),
                )
                pending.clear()
                audits.append(audit)

        if not pending:
            self._pending_stream_batches.pop(key, None)
            self._pending_stream_batch_started_session_times.pop(key, None)
        return tuple(audits)

    def _flush_pending_stream_batches(self) -> None:
        for key, records in tuple(self._pending_stream_batches.items()):
            source_node_id, source_device_id, record_kind = key
            if source_node_id != self._node_id:
                continue
            if records:
                self._send_envelope(
                    source_device_id=source_device_id,
                    record_kind=record_kind,
                    records=tuple(records),
                )
            self._pending_stream_batches.pop(key, None)
            self._pending_stream_batch_started_session_times.pop(key, None)

    def _read_stream_batch_configuration(
        self,
        acquisition_configuration: Mapping[str, Any] | None,
    ) -> tuple[int | None, float | None]:
        if not isinstance(acquisition_configuration, Mapping):
            return None, None
        policy_name = acquisition_configuration.get("batch_policy")
        policies = acquisition_configuration.get("batch_policies")
        if policy_name != "type_1" or not isinstance(policies, Mapping):
            return None, None
        policy = policies.get(policy_name)
        if not isinstance(policy, Mapping):
            return None, None
        max_records = policy.get("max_records")
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records <= 1
        ):
            max_records = None
        max_batch_age_s = policy.get("max_batch_age_s")
        if (
            isinstance(max_batch_age_s, bool)
            or not isinstance(max_batch_age_s, (int, float))
            or not isfinite(max_batch_age_s)
            or max_batch_age_s <= 0
        ):
            max_batch_age_s = None
        return max_records, (
            float(max_batch_age_s) if max_batch_age_s is not None else None
        )

    def _read_handoff_failure_policy(
        self,
        acquisition_configuration: Mapping[str, Any] | None,
    ) -> str:
        if not isinstance(acquisition_configuration, Mapping):
            return "must_preserve"
        policy_name = acquisition_configuration.get("handoff_failure_policy")
        policies = acquisition_configuration.get("handoff_failure_policies")
        if policy_name not in {"must_preserve", "best_effort"}:
            return "must_preserve"
        if not isinstance(policies, Mapping):
            return "must_preserve"
        policy = policies.get(policy_name)
        if not isinstance(policy, Mapping):
            return "must_preserve"
        expected_preserve = policy_name == "must_preserve"
        if policy.get("preserve_failed_envelope") is not expected_preserve:
            return "must_preserve"
        return policy_name

    def _stream_batching_enabled(self) -> bool:
        return (
            self._stream_batch_max_records is not None
            or self._stream_batch_max_age_s is not None
        )


@dataclass(frozen=True)
class _FailedHandoffAudit:
    accepted: bool = False
