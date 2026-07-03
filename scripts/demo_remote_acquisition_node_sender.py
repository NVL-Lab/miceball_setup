"""Run one simulated remote AcquisitionNode session over a provisional socket."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    AcquisitionRecordEnvelope,
    DeviceAdapter,
    DeviceAdapterState,
    DeviceManager,
    ServiceReadiness,
    SynchronizationManager,
)


class RemoteFakeAdapter(DeviceAdapter):
    """Demo-local adapter that exposes one small untimestamped record batch."""

    def check_ready(self):
        return self._mark_ready()

    def collect_records(self):
        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("Remote fake adapter must be running")
        return {
            "record_kind": "remote_fake_stream",
            "records": (
                {"sample_index": 0, "value": 10},
                {"sample_index": 1, "value": 11},
            ),
        }


@dataclass(frozen=True)
class SocketSendResult:
    accepted: bool
    reason: str


class SocketEnvelopeBoundary:
    """Demo-local Ingestor-like boundary for one connected socket writer."""

    def __init__(self, writer: Any) -> None:
        self._writer = writer
        self.envelopes_sent = 0

    def check_ready(self) -> ServiceReadiness:
        return ServiceReadiness(
            component_id="computer_ingestor",
            component_type="ingestor_connection",
            required=True,
            ready=True,
            reason="socket_connected",
        )

    def receive_envelope(
        self,
        envelope: AcquisitionRecordEnvelope,
    ) -> SocketSendResult:
        self._writer.write(json.dumps(envelope.to_dict()))
        self._writer.write("\n")
        self._writer.flush()
        self.envelopes_sent += 1
        return SocketSendResult(accepted=True, reason="sent")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one simulated remote AcquisitionNode socket session."
    )
    parser.add_argument("host", help="Computer Ingestor host or IP address.")
    parser.add_argument("port", type=int, help="Computer Ingestor TCP port.")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--failure-evidence-path", required=True)
    args = parser.parse_args()

    failure_path = Path(args.failure_evidence_path)
    local_storage_readiness = _failure_path_readiness(failure_path)
    adapter = None
    manager = None
    synchronization = None
    acquisition_node = None
    envelopes_sent = 0
    cleanup_evidence: dict[str, Any] = {
        "attempted": False,
        "completed": True,
        "reason": "acquisition_not_started",
    }

    try:
        if not local_storage_readiness.ready:
            raise RuntimeError(local_storage_readiness.reason)

        with socket.create_connection((args.host, args.port), timeout=5) as connection:
            writer = connection.makefile("w", encoding="utf-8", newline="\n")
            socket_boundary = SocketEnvelopeBoundary(writer)
            adapter = RemoteFakeAdapter(
                device_id="remote-fake-device-001",
                device_type="remote_fake_device",
                declared_capabilities=("remote_fake_stream",),
                required=True,
            )
            manager = DeviceManager(adapters=(adapter,))
            synchronization = SynchronizationManager()
            acquisition_node = AcquisitionNode(
                session_id=args.session_id,
                device_manager=manager,
                synchronization_manager=synchronization,
                ingestor=socket_boundary,
                node_id=args.node_id,
                role=args.role,
                error_evidence_location=str(failure_path.parent),
            )

            try:
                initialization = manager.initialize_all(config={"mode": "remote_demo"})
                if not all(item.succeeded for item in initialization):
                    raise RuntimeError(f"device_initialization_failed: {initialization}")

                cleanup_readiness = ServiceReadiness(
                    component_id="acquisition_cleanup",
                    component_type="cleanup_finalization",
                    required=True,
                    ready=True,
                    reason="device_manager_lifecycle_available",
                )
                node_readiness = acquisition_node.check_node_readiness(
                    additional_service_readiness=(
                        local_storage_readiness,
                        cleanup_readiness,
                    )
                )
                if not node_readiness.ready:
                    raise RuntimeError(f"node_not_ready: {node_readiness.to_dict()}")

                acquisition_node.start_acquisition()
                acquisition_node.run_one_iteration()
                acquisition_node.stop_acquisition()
                envelopes_sent = socket_boundary.envelopes_sent
            finally:
                cleanup_evidence = _cleanup_runtime(
                    acquisition_node=acquisition_node,
                    synchronization=synchronization,
                    manager=manager,
                    adapter=adapter,
                )
                writer.close()
    except Exception as error:
        evidence = {
            "evidence_kind": "remote_acquisition_failure",
            "recorded_at": time(),
            "node_id": args.node_id,
            "session_id": args.session_id,
            "role": args.role,
            "target": f"{args.host}:{args.port}",
            "error_type": type(error).__name__,
            "reason": str(error),
            "cleanup": cleanup_evidence,
        }
        _write_failure_evidence(failure_path, evidence)
        print(json.dumps(evidence), file=sys.stderr)
        return 1

    print(f"node_id={args.node_id}")
    print(f"session_id={args.session_id}")
    print(f"target={args.host}:{args.port}")
    print(f"envelopes_sent={envelopes_sent}")
    print(f"cleanup_completed={cleanup_evidence['completed']}")
    return 0


def _failure_path_readiness(path: Path) -> ServiceReadiness:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            raise IsADirectoryError(str(path))
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as error:
        return ServiceReadiness(
            component_id="node_local_failure_evidence",
            component_type="local_storage",
            required=True,
            ready=False,
            reason=f"failure_evidence_path_unavailable: {error}",
        )
    return ServiceReadiness(
        component_id="node_local_failure_evidence",
        component_type="local_storage",
        required=True,
        ready=True,
        reason="path_ready",
    )


def _cleanup_runtime(
    acquisition_node: AcquisitionNode | None,
    synchronization: SynchronizationManager | None,
    manager: DeviceManager | None,
    adapter: DeviceAdapter | None,
) -> dict[str, Any]:
    errors = []
    attempted = adapter is not None
    if acquisition_node is not None and acquisition_node.status()["is_running"]:
        try:
            acquisition_node.stop_acquisition()
        except Exception as error:
            errors.append(str(error))
    if synchronization is not None and synchronization.is_running:
        synchronization.stop()
    if manager is not None and adapter is not None:
        if adapter.state is DeviceAdapterState.READY:
            manager.start_all()
        if adapter.state is DeviceAdapterState.RUNNING:
            manager.stop_all()
        if adapter.state is DeviceAdapterState.STOPPED:
            manager.shutdown_all()
    final_state = adapter.state.value if adapter is not None else "not_created"
    completed = final_state in {"not_created", "shutdown"}
    return {
        "attempted": attempted,
        "completed": completed,
        "final_adapter_state": final_state,
        "errors": errors,
    }


def _write_failure_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as evidence_file:
        evidence_file.write(json.dumps(evidence))
        evidence_file.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
