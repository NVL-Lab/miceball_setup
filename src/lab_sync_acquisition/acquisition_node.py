"""Bounded acquisition-side execution for Phase 1 workflows."""

from __future__ import annotations

from dataclasses import dataclass
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
    ) -> None:
        self._session_id = session_id
        self._device_manager = device_manager
        self._synchronization_manager = synchronization_manager
        self._ingestor = ingestor
        self._node_id = node_id
        self._role = role
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
            audit = self._send_envelope(
                source_device_id=collection.source_device_id,
                record_kind=collection.record_kind,
                records=records,
            )
            envelopes_sent += 1
            if audit.accepted:
                accepted_count += 1
            else:
                rejected_count += 1

        return AcquisitionIterationSummary(
            iteration_index=self._iteration_index,
            collections_seen=len(record_collections),
            envelopes_sent=envelopes_sent,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
        )

    def stop_acquisition(self) -> dict[str, Any]:
        """Stop Session Time, record session_stop evidence, and stop devices."""

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
        return self._ingestor.receive_envelope(reconstructed_envelope)

    def _with_session_time(self, row: dict[str, Any]) -> dict[str, Any]:
        if "session_time_s" in row:
            return dict(row)
        return {
            **row,
            "session_time_s": self._synchronization_manager.current_session_time_s,
        }
