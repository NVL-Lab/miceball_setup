"""Manual Phase 10b validation against a real local NATS JetStream server."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
import tempfile
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from lab_sync_acquisition import (  # noqa: E402
    AcquisitionNode,
    DeviceAdapter,
    DeviceAdapterState,
    DeviceManager,
    InMemoryIngestor,
    NatsAcquisitionNodeCommunication,
    NatsCommunicationBoundary,
    NatsControllerCommunication,
    NatsIngestorCommunication,
    RuntimeCommandMessage,
    RuntimeEvidenceMessage,
    RuntimeTelemetryMessage,
    SynchronizationManager,
)


class DemoRecordAdapter(DeviceAdapter):
    """Demo-local adapter that emits one bounded fake stream batch."""

    def __init__(self) -> None:
        super().__init__(
            device_id="source-001",
            device_type="fake_stream",
            declared_capabilities=("stream",),
            required=True,
        )
        self._collected = False

    def check_ready(self):
        return self._mark_ready()

    def collect_records(self):
        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("Demo record collection requires a running adapter")
        if self._collected:
            return {"record_kind": "stream", "records": ()}
        self._collected = True
        return {
            "record_kind": "stream",
            "records": (
                {
                    "sample_index": 0,
                    "device_local_time": 100.0,
                    "value": 1.0,
                },
                {
                    "sample_index": 1,
                    "device_local_time": 100.1,
                    "value": 2.0,
                },
            ),
        }


async def run_demo(server_url: str) -> None:
    session_id = f"phase-10b-demo-{uuid4().hex}"
    controller_boundary = NatsCommunicationBoundary(
        "controller", "controller-001", (server_url,)
    )
    node_boundary = NatsCommunicationBoundary(
        "acquisition_node", "node-001", (server_url,)
    )
    ingestor_boundary = NatsCommunicationBoundary(
        "ingestor", "ingestor-001", (server_url,)
    )
    monitor_boundary = NatsCommunicationBoundary(
        "monitor", "monitor-001", (server_url,)
    )
    boundaries = (
        controller_boundary,
        node_boundary,
        ingestor_boundary,
        monitor_boundary,
    )

    with tempfile.TemporaryDirectory() as directory:
        manager = DeviceManager((DemoRecordAdapter(),))
        manager.initialize_all({"mode": "phase-10b-demo"})
        readiness = manager.check_readiness()
        assert readiness.all_ready
        local_ingestor = InMemoryIngestor()
        node = AcquisitionNode(
            session_id=session_id,
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=local_ingestor,
            node_id="node-001",
            role="acquisition_node",
            error_evidence_location=str(Path(directory) / "errors"),
        )
        controller = NatsControllerCommunication(controller_boundary)
        node_runtime = NatsAcquisitionNodeCommunication(node_boundary, node)
        evidence_ingestor = InMemoryIngestor()
        ingestor = NatsIngestorCommunication(
            ingestor_boundary,
            evidence_ingestor,
        )

        try:
            for boundary in boundaries:
                await boundary.connect()
            await controller_boundary.ensure_streams()

            result_events: dict[str, asyncio.Event] = {}
            evidence_event = asyncio.Event()
            telemetry_event = asyncio.Event()
            telemetry_received: list[RuntimeTelemetryMessage] = []

            async def result_received(result):
                result_events.setdefault(result.command_id, asyncio.Event()).set()

            async def evidence_received(_evidence):
                evidence_event.set()

            async def telemetry_received_callback(telemetry):
                telemetry_received.append(telemetry)
                telemetry_event.set()

            result_subscription = await controller.subscribe_command_results(
                session_id,
                result_received,
            )
            command_subscription = await node_runtime.subscribe_commands()
            evidence_subscription = await ingestor.subscribe_evidence(
                session_id,
                evidence_received,
            )
            await monitor_boundary.subscribe_telemetry(
                f"messages.{session_id}.telemetry.>",
                telemetry_received_callback,
            )

            await result_subscription.consumer_info()
            await command_subscription.consumer_info()
            await evidence_subscription.consumer_info()
            for boundary in boundaries:
                await boundary.flush()
            print("subscriptions_ready=true")

            for index, command_type in enumerate(
                ("start_runtime", "run_one_iteration", "stop_runtime"),
                start=1,
            ):
                command_id = f"command-{index:03d}"
                result_events[command_id] = asyncio.Event()
                await controller.publish_command(
                    RuntimeCommandMessage(
                        command_id=command_id,
                        session_id=session_id,
                        command_type=command_type,
                        source_id="controller-001",
                        target_id="node-001",
                        payload={},
                    )
                )
                await asyncio.wait_for(result_events[command_id].wait(), timeout=5)

            await node_runtime.publish_evidence(
                RuntimeEvidenceMessage(
                    evidence_id="evidence-001",
                    session_id=session_id,
                    evidence_type="runtime_demo",
                    source_id="node-001",
                    payload={"validated": True},
                )
            )
            await asyncio.wait_for(evidence_event.wait(), timeout=5)

            await node_boundary.publish_telemetry(
                RuntimeTelemetryMessage(
                    session_id=session_id,
                    telemetry_type="runtime_demo_status",
                    source_id="node-001",
                    payload={"online": True},
                )
            )
            await asyncio.wait_for(telemetry_event.wait(), timeout=5)

            assert len(controller.command_results) == 3
            for result in controller.command_results:
                print("COMMAND_RESULT:", result.to_dict())
            assert all(result.success for result in controller.command_results)
            assert len(evidence_ingestor.accepted_runtime_evidence) == 1
            assert len(evidence_ingestor.runtime_evidence_audit) == 1
            assert len(telemetry_received) == 1

            print(f"server={server_url}")
            print(f"session_id={session_id}")
            print(f"command_results={len(controller.command_results)}")
            print(
                "runtime_evidence_received="
                f"{len(evidence_ingestor.accepted_runtime_evidence)}"
            )
            print(f"telemetry_received={len(telemetry_received)}")
            print("validation=passed")
        finally:
            for boundary in reversed(boundaries):
                await boundary.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server",
        default="nats://127.0.0.1:4222",
        help="NATS server URL with JetStream enabled",
    )
    arguments = parser.parse_args()
    asyncio.run(run_demo(arguments.server))


if __name__ == "__main__":
    main()
