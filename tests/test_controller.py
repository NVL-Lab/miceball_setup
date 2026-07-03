import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    Controller,
    DeviceDeclaration,
    DeviceManager,
    InMemoryIngestor,
    PersistentStorageManager,
    SessionConfig,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class ControllerFakeAdapter(ReadyFakeAdapter):
    def __init__(self):
        super().__init__("live-source-001", "fake_stream", ("stream",), True)
        self._records = ({"sample_index": 1, "value": 42},)

    def collect_records(self):
        records, self._records = self._records, ()
        return {"record_kind": "stream", "records": records}


class DeviceHandoffFailingIngestor(InMemoryIngestor):
    def receive_envelope(self, envelope):
        if envelope.source_device_id != "acquisition_node":
            raise ConnectionError("device handoff unavailable")
        return super().receive_envelope(envelope)


class FirstSessionRecordWriteFailingStorage(PersistentStorageManager):
    def write_session_record(self, *args, **kwargs):
        raise OSError("session record unavailable")


class StopFailingSynchronizationManager(SynchronizationManager):
    def stop(self):
        raise RuntimeError("clock stop failed")


class ControllerWorkflowTests(unittest.TestCase):
    def test_controller_completes_one_bounded_session_and_session_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records_path = root / "accepted_records.jsonl"
            session_record_path = root / "session_record.json"
            config = SessionConfig(
                session_id="controller-session-001",
                selected_devices=[
                    DeviceDeclaration(
                        device_id="declared-source-001",
                        device_type="fake_stream",
                        enabled=True,
                        required=True,
                        declared_capabilities=("stream",),
                    )
                ],
                storage_location=str(records_path),
                protocol_plan={"name": "controller-v1"},
                error_evidence_location=str(root / "errors"),
            )
            adapter = ControllerFakeAdapter()
            manager = DeviceManager((adapter,))
            storage = PersistentStorageManager(records_path=records_path)
            ingestor = InMemoryIngestor(storage_manager=storage)
            node = AcquisitionNode(
                session_id=config.session_id,
                device_manager=manager,
                synchronization_manager=SynchronizationManager(),
                ingestor=ingestor,
                error_evidence_location=config.error_evidence_location,
            )
            controller = Controller(
                acquisition_node=node,
                ingestor=ingestor,
                storage_manager=storage,
                session_record_path=session_record_path,
            )

            manager.initialize_all(config={"mode": "controller-test"})
            readiness = node.check_ready()
            results = [
                controller.create_session(config),
                controller.initialize_session(
                    device_readiness_summary=readiness["device_readiness"],
                    service_readiness=(
                        *readiness["service_readiness"],
                        storage.check_ready(),
                    ),
                ),
                controller.start_session(),
                controller.run_one_iteration(),
                controller.stop_session(reason="bounded workflow complete"),
                controller.finalize_session(),
            ]

            status = controller.get_status()
            session_record = storage.read_session_record(session_record_path)
            self.assertTrue(all(result.succeeded for result in results))
            self.assertEqual(status["session_id"], "controller-session-001")
            self.assertEqual(status["session_state"], "completed")
            self.assertFalse(status["acquisition_runtime"]["is_running"])
            self.assertEqual(status["acquisition_runtime"]["iteration_count"], 1)
            self.assertEqual(status["last_command"].command, "finalize_session")
            self.assertEqual(
                [
                    transition["to_state"]
                    for transition in session_record["session_lifecycle_evidence"]
                ],
                ["initialized", "running", "stopping", "completed"],
            )
            self.assertEqual(
                len(session_record["accepted_acquisition_envelopes"]),
                3,
            )
            self.assertTrue(session_record["cleanup_evidence"]["cleanup_occurred"])

    def test_start_runtime_failure_marks_initialized_session_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, manager, node, config = self._controller_fixture(root)
            manager.initialize_all(config={"mode": "start-failure"})
            readiness = node.check_ready()
            self.assertTrue(controller.create_session(config).succeeded)
            self.assertTrue(
                controller.initialize_session(
                    readiness["device_readiness"],
                    readiness["service_readiness"],
                ).succeeded
            )
            evidence_path = Path(config.error_evidence_location)
            evidence_path.rmdir()
            evidence_path.write_text("unavailable", encoding="utf-8")

            result = controller.start_session()

            self.assertFalse(result.succeeded)
            self.assertIn("failure evidence location is not writable", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assertFalse(controller.get_status()["acquisition_runtime"]["is_running"])

    def test_failed_acquisition_node_marks_session_failed_and_stops_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(
                root,
                acquisition_configuration={
                    "handoff_failure_policy": "must_preserve",
                    "handoff_failure_policies": {
                        "must_preserve": {
                            "preserve_failed_envelope": True,
                            "consecutive_failure_threshold": 1,
                        }
                    },
                },
            )
            adapter = ControllerFakeAdapter()
            manager = DeviceManager((adapter,))
            storage = PersistentStorageManager(root / "accepted_records.jsonl")
            ingestor = DeviceHandoffFailingIngestor(storage_manager=storage)
            node = AcquisitionNode(
                session_id=config.session_id,
                device_manager=manager,
                synchronization_manager=SynchronizationManager(),
                ingestor=ingestor,
                acquisition_configuration=config.acquisition_configuration,
                error_evidence_location=config.error_evidence_location,
            )
            controller = Controller(
                node, ingestor, storage, root / "session_record.json"
            )
            manager.initialize_all(config={"mode": "iteration-failure"})
            readiness = node.check_ready()
            controller.create_session(config)
            controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]
            )
            controller.start_session()

            result = controller.run_one_iteration()

            self.assertFalse(result.succeeded)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assertFalse(controller.get_status()["acquisition_runtime"]["is_running"])
            self.assertTrue(all(status.shutdown for status in manager.collect_statuses()))

    def test_stop_runtime_failure_marks_running_session_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, manager, node, config = self._controller_fixture(
                root,
                synchronization_manager=StopFailingSynchronizationManager(),
            )
            manager.initialize_all(config={"mode": "stop-failure"})
            readiness = node.check_ready()
            controller.create_session(config)
            controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]
            )
            controller.start_session()

            result = controller.stop_session()

            self.assertFalse(result.succeeded)
            self.assertIn("clock stop failed", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")

    def test_first_session_record_write_failure_leaves_session_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root)
            adapter = ControllerFakeAdapter()
            manager = DeviceManager((adapter,))
            storage = FirstSessionRecordWriteFailingStorage(
                root / "accepted_records.jsonl"
            )
            ingestor = InMemoryIngestor(storage_manager=storage)
            node = AcquisitionNode(
                session_id=config.session_id,
                device_manager=manager,
                synchronization_manager=SynchronizationManager(),
                ingestor=ingestor,
                error_evidence_location=config.error_evidence_location,
            )
            controller = Controller(
                node, ingestor, storage, root / "session_record.json"
            )
            manager.initialize_all(config={"mode": "finalization-failure"})
            readiness = node.check_ready()
            controller.create_session(config)
            controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]
            )
            controller.start_session()
            controller.stop_session()

            result = controller.finalize_session()

            self.assertFalse(result.succeeded)
            self.assertIn("session record unavailable", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")

    def _controller_fixture(self, root, synchronization_manager=None):
        config = self._config(root)
        adapter = ControllerFakeAdapter()
        manager = DeviceManager((adapter,))
        storage = PersistentStorageManager(root / "accepted_records.jsonl")
        ingestor = InMemoryIngestor(storage_manager=storage)
        node = AcquisitionNode(
            session_id=config.session_id,
            device_manager=manager,
            synchronization_manager=(
                synchronization_manager or SynchronizationManager()
            ),
            ingestor=ingestor,
            error_evidence_location=config.error_evidence_location,
        )
        controller = Controller(
            node, ingestor, storage, root / "session_record.json"
        )
        return controller, manager, node, config

    def _config(self, root, acquisition_configuration=None):
        return SessionConfig(
            session_id="controller-failure-session-001",
            selected_devices=[],
            storage_location=str(root / "accepted_records.jsonl"),
            protocol_plan={"name": "controller-failure-v1"},
            error_evidence_location=str(root / "errors"),
            acquisition_configuration=acquisition_configuration,
        )


if __name__ == "__main__":
    unittest.main()
