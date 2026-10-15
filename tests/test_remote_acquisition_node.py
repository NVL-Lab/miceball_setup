import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    DeviceManager,
    InMemoryIngestor,
    ServiceReadiness,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class RemoteRecordFakeAdapter(ReadyFakeAdapter):
    def collect_products(self, products, **context):
        return {"scientific_products": {}, "operational_evidence": ()}


class RemoteAcquisitionNodeTests(unittest.TestCase):
    def test_caller_does_not_start_when_required_service_is_not_ready(
        self,
    ) -> None:
        adapter = RemoteRecordFakeAdapter(
            "remote-device-001",
            "remote_fake_device",
            ["remote_fake_stream"],
            True,
        )
        manager = DeviceManager(adapters=(adapter,))
        manager.initialize_all(config={})
        node = AcquisitionNode(
            session_id="remote-session-001",
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(),
            node_id="jetson-like-001",
            role="acquisition_node",
            error_evidence_location=tempfile.gettempdir(),
        )
        storage_not_ready = ServiceReadiness(
            component_id="node_storage",
            component_type="local_storage",
            required=True,
            ready=False,
            reason="path_unavailable",
        )

        readiness = node.check_node_readiness(
            additional_service_readiness=(storage_not_ready,)
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.node_id, "jetson-like-001")
        self.assertIsNone(readiness.reserved_for_session_id)
        self.assertEqual(readiness.role, "acquisition_node")
        self.assertEqual(readiness.device_readiness.results[0].device_id, "remote-device-001")
        self.assertIn(storage_not_ready, readiness.service_readiness)

        started = False
        if readiness.ready:
            node.start_acquisition()
            started = True

        self.assertFalse(started)
        self.assertFalse(node.status()["is_running"])

        manager.start_all()
        manager.stop_all()
        manager.shutdown_all()


if __name__ == "__main__":
    unittest.main()
