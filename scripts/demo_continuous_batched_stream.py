"""Demonstrate count- and Session-Time-age-triggered stream batching."""

from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceAdapter,
    DeviceAdapterState,
    DeviceManager,
    InMemoryIngestor,
    PersistentStorageManager,
    ServiceReadiness,
    SessionConfig,
)


class ContinuousFakeStreamAdapter(DeviceAdapter):
    """Demo-local adapter that produces a finite continuous fake stream."""

    def __init__(
        self,
        *,
        total_records: int,
        records_per_iteration: int,
    ) -> None:
        super().__init__(
            device_id="continuous-fake-stream-001",
            device_type="continuous_fake_stream",
            declared_capabilities=("stream",),
            required=True,
        )
        self._total_records = total_records
        self._records_per_iteration = records_per_iteration
        self._next_sample_index = 0

    def check_ready(self):
        return self._mark_ready()

    def collect_records(self):
        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("Continuous fake stream adapter must be running")
        remaining = self._total_records - self._next_sample_index
        row_count = min(self._records_per_iteration, max(0, remaining))
        records = []
        for _ in range(row_count):
            sample_index = self._next_sample_index
            records.append(
                {
                    "sample_index": sample_index,
                    "device_local_time": sample_index / 1000.0,
                    "value": float(sample_index % 17),
                }
            )
            self._next_sample_index += 1
        return {"record_kind": "stream", "records": tuple(records)}


class ControlledSynchronizationManager:
    """Demo-local deterministic Session Time owner."""

    def __init__(self) -> None:
        self._session_time_s = 0.0
        self._running = False

    @property
    def current_session_time_s(self) -> float:
        return self._session_time_s

    @property
    def is_running(self) -> bool:
        return self._running

    def check_ready(self) -> ServiceReadiness:
        return ServiceReadiness(
            component_id="synchronization",
            component_type="synchronization_manager",
            required=True,
            ready=True,
            reason="ready",
        )

    def start(self) -> float:
        self._session_time_s = 0.0
        self._running = True
        return 0.0

    def stop(self) -> float:
        self._running = False
        return self._session_time_s

    def advance(self, seconds: float) -> None:
        self._session_time_s += seconds


def run_scenario(
    *,
    scenario_name: str,
    output_path: Path,
    total_records: int,
    records_per_iteration: int,
    max_records: int,
    max_batch_age_s: float,
    session_time_step_s: float,
    expected_stream_envelope_sizes: list[int],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    acquisition_configuration = {
        "batch_policy": "type_1",
        "batch_policies": {
            "type_1": {
                "max_records": max_records,
                "max_batch_age_s": max_batch_age_s,
            }
        },
    }
    configuration = SessionConfig(
        selected_devices=[],
        storage_location=str(output_path),
        protocol_plan={"name": scenario_name},
        error_evidence_location="placeholder://errors",
        acquisition_configuration=acquisition_configuration,
    )
    adapter = ContinuousFakeStreamAdapter(
        total_records=total_records,
        records_per_iteration=records_per_iteration,
    )
    manager = DeviceManager(adapters=(adapter,))
    synchronization = ControlledSynchronizationManager()
    storage = PersistentStorageManager(records_path=output_path)
    ingestor = InMemoryIngestor(storage_manager=storage)
    node = AcquisitionNode(
        session_id=f"batch-demo-{scenario_name}",
        device_manager=manager,
        synchronization_manager=synchronization,
        ingestor=ingestor,
        node_id="batch-demo-node",
        acquisition_configuration=configuration.acquisition_configuration,
    )

    manager.initialize_all(config={"mode": scenario_name})
    readiness = node.check_ready()
    if not readiness["ready"]:
        raise RuntimeError(f"Scenario is not ready: {scenario_name}")

    node.start_acquisition()
    try:
        iterations = math.ceil(total_records / records_per_iteration)
        for _ in range(iterations):
            node.run_one_iteration()
            synchronization.advance(session_time_step_s)
    finally:
        if node.status()["is_running"]:
            node.stop_acquisition()

    stored_envelopes = storage.read_envelopes()
    stream_envelopes = tuple(
        envelope
        for envelope in stored_envelopes
        if envelope.record_kind == "stream"
    )
    stream_envelope_sizes = [len(envelope.records) for envelope in stream_envelopes]
    stored_stream_records = sum(stream_envelope_sizes)
    expected_sizes_matched = (
        stream_envelope_sizes == expected_stream_envelope_sizes
    )

    print(f"scenario={scenario_name}")
    print(f"total_stream_records_generated={stored_stream_records}")
    print(f"stream_envelope_count={len(stream_envelopes)}")
    print(f"stream_envelope_sizes={stream_envelope_sizes}")
    print(f"expected_sizes_matched={expected_sizes_matched}")
    print(f"accepted_envelope_count={len(ingestor.accepted_envelopes)}")
    print(f"stored_envelope_count={len(stored_envelopes)}")
    print(f"jsonl_path={output_path.resolve()}")
    print()

    assert stored_stream_records == total_records
    assert expected_sizes_matched, (
        f"{scenario_name}: expected {expected_stream_envelope_sizes}, "
        f"got {stream_envelope_sizes}"
    )


def main() -> int:
    output_directory = ROOT / "tmp_continuous_batched_stream_demo"
    run_scenario(
        scenario_name="fast_count_triggered",
        output_path=output_directory / "fast_count_records.jsonl",
        total_records=1200,
        records_per_iteration=100,
        max_records=500,
        max_batch_age_s=100.0,
        session_time_step_s=0.01,
        expected_stream_envelope_sizes=[500, 500, 200],
    )
    run_scenario(
        scenario_name="slow_age_triggered",
        output_path=output_directory / "slow_age_records.jsonl",
        total_records=5,
        records_per_iteration=1,
        max_records=500,
        max_batch_age_s=1.0,
        session_time_step_s=1.0,
        expected_stream_envelope_sizes=[2, 2, 1],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


