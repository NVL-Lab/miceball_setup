import sys
import tempfile
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    ARTIFACT_MANIFEST_EVIDENCE_TYPE,
    AcquisitionHealthPolicy,
    AcquisitionNode,
    Controller,
    DeviceDeclaration,
    DeviceManager,
    ExpectedParticipant,
    ExperimentRuntimeHealthMapping,
    InMemoryIngestor,
    PersistentStorageManager,
    RuntimeEvidenceMessage,
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


class EvidenceArchiveWriteFailingStorage(PersistentStorageManager):
    def write_evidence_archive(self, *args, **kwargs):
        raise OSError("evidence archive unavailable")


class FinalSessionRecordWriteFailingStorage(PersistentStorageManager):
    def write_final_session_record(self, *args, **kwargs):
        raise OSError("final session record unavailable")


class StopFailingSynchronizationManager(SynchronizationManager):
    def stop(self):
        raise RuntimeError("clock stop failed")


class ControllerWorkflowTests(unittest.TestCase):
    def test_health_observation_does_not_fail_controller_session_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, manager, node, config = self._controller_fixture(
                root,
                acquisition_health_policies=(
                    AcquisitionHealthPolicy(
                        policy_id="event-required",
                        evaluation_rules={
                            "first_evidence": {
                            "record_kind": "event",
                            "grace_window_s": 0.0,
                            }
                        },
                        interpretation={},
                    ),
                ),
            )
            manager.initialize_all(config={"mode": "health-observation"})
            readiness = node.check_ready()
            controller.create_session(config)
            controller.initialize_session(
                readiness["device_readiness"],
                readiness["service_readiness"],
            )
            controller.start_session()
            controller.start_experiment(
                "experiment-observation-001",
                runtime_health_mapping=(
                    ExperimentRuntimeHealthMapping(
                        live_source_id="live-source-001",
                        expected_participant_id="event-source-001",
                        acquisition_health_policy="event-required",
                        required=True,
                        expected_contribution="event_records",
                    ),
                ),
            )

            result = controller.run_one_iteration()

            self.assertTrue(result.succeeded)
            self.assertEqual(controller.get_status()["session_state"], "running")
            self.assertTrue(
                controller.get_status()["acquisition_runtime"]["is_running"]
            )
            self.assertFalse(node.status()["failed"])
            self.assertEqual(
                node.experiment_scoped_health_observations[0].experiment_id,
                "experiment-observation-001",
            )
            controller.stop_experiment("experiment-observation-001")
            controller.stop_session()

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
            artifact_manifest = RuntimeEvidenceMessage(
                evidence_id="artifact-manifest-001",
                session_id=config.session_id,
                evidence_type=ARTIFACT_MANIFEST_EVIDENCE_TYPE,
                source_id="node-001",
                payload={
                    "artifact_id": "camera-video-001",
                    "local_reference": "camera/video-001",
                },
                is_persistent=True,
            )
            runtime_audit = ingestor.receive_runtime_evidence(artifact_manifest)

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
            session_directory = root / "session_controller-session-001"
            initial_record_path = (
                session_directory / "session_record_initial.json"
            )
            final_record_path = session_directory / "session_record_final.json"
            runtime_evidence_path = (
                session_directory / "evidence" / "runtime_evidence.jsonl"
            )
            ingest_audit_path = (
                session_directory / "evidence" / "ingest_audit.jsonl"
            )
            compilation_summary_path = (
                session_directory / "evidence" / "compilation_summary.json"
            )
            initial_record = storage.read_session_record(initial_record_path)
            session_record = storage.read_session_record(final_record_path)
            archived_runtime_evidence = self._read_jsonl(runtime_evidence_path)
            archived_ingest_audit = self._read_jsonl(ingest_audit_path)
            compilation_summary = json.loads(
                compilation_summary_path.read_text(encoding="utf-8")
            )
            self.assertTrue(all(result.succeeded for result in results))
            self.assertEqual(status["session_id"], "controller-session-001")
            self.assertEqual(status["session_state"], "completed")
            self.assertFalse(status["acquisition_runtime"]["is_running"])
            self.assertEqual(status["acquisition_runtime"]["iteration_count"], 1)
            self.assertEqual(status["last_command"].command, "finalize_session")
            self.assertTrue(initial_record_path.exists())
            self.assertEqual(
                [
                    transition["to_state"]
                    for transition in initial_record["session_lifecycle_evidence"]
                ],
                ["initialized", "running"],
            )
            self.assertEqual(
                [
                    transition["to_state"]
                    for transition in session_record["session_lifecycle_evidence"]
                ],
                ["initialized", "running", "stopping"],
            )
            self.assertEqual(
                len(session_record["accepted_acquisition_envelopes"]),
                3,
            )
            self.assertEqual(
                session_record["runtime_evidence"],
                [artifact_manifest.to_dict()],
            )
            self.assertEqual(
                session_record["runtime_evidence_audit"],
                [runtime_audit.to_dict()],
            )
            self.assertNotIn(
                "artifact_bytes",
                session_record["runtime_evidence"][0]["payload"],
            )
            self.assertEqual(archived_runtime_evidence, [artifact_manifest.to_dict()])
            self.assertEqual(archived_ingest_audit, [runtime_audit.to_dict()])
            self.assertEqual(
                compilation_summary,
                {
                    "session_id": "controller-session-001",
                    "runtime_evidence_count": 1,
                    "ingest_audit_count": 1,
                    "runtime_evidence_ids": ["artifact-manifest-001"],
                    "ingest_audit_evidence_ids": ["artifact-manifest-001"],
                },
            )
            self.assertTrue(
                all(
                    envelope["record_kind"] != ARTIFACT_MANIFEST_EVIDENCE_TYPE
                    for envelope in session_record[
                        "accepted_acquisition_envelopes"
                    ]
                )
            )
            self.assertFalse(session_record["cleanup_evidence"]["cleanup_occurred"])
            self.assertIsNone(session_record["final_session_status"])

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

    def test_controller_records_experiment_lifecycle_inside_running_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, manager, node, config = self._controller_fixture(root)
            manager.initialize_all(config={"mode": "experiment-lifecycle"})
            readiness = node.check_ready()
            controller.create_session(config)

            runtime_mapping = (
                ExperimentRuntimeHealthMapping(
                    live_source_id="live-source-001",
                    expected_participant_id="camera-001",
                    acquisition_health_policy="camera_frames_required",
                    required=True,
                    expected_contribution="camera_frame_metadata",
                ),
            )
            replacement_mapping = (
                ExperimentRuntimeHealthMapping(
                    live_source_id="other-source",
                    expected_participant_id="decoder-001",
                    acquisition_health_policy="decoder_required",
                    required=True,
                    expected_contribution="decoder_predictions",
                ),
            )

            before_running = controller.start_experiment(
                "experiment-001",
                runtime_health_mapping=runtime_mapping,
            )
            self.assertFalse(before_running.succeeded)
            self.assertEqual(
                controller.get_status()[
                    "active_experiment_runtime_health_mapping"
                ],
                (),
            )
            self.assertEqual(
                node.status()["active_experiment_runtime_health_mapping"],
                (),
            )

            controller.initialize_session(
                readiness["device_readiness"], readiness["service_readiness"]
            )
            controller.start_session()

            without_active = controller.stop_experiment("experiment-001")
            self.assertFalse(without_active.succeeded)

            started = controller.start_experiment(
                "experiment-001",
                details={"protocol": "baseline"},
                expected_participants=(
                    ExpectedParticipant(
                        participant_id="camera-001",
                        participant_type="device",
                        expected_contribution="camera_frame_metadata",
                        required=True,
                    ),
                    ExpectedParticipant(
                        participant_id="decoder-001",
                        participant_type="decoder",
                        expected_contribution="decoder_predictions",
                        required=False,
                    ),
                ),
                runtime_health_mapping=runtime_mapping,
            )
            active_status = controller.get_status()
            overlapping = controller.start_experiment(
                "experiment-002",
                runtime_health_mapping=replacement_mapping,
            )
            status_after_overlap = controller.get_status()
            mismatched_stop = controller.stop_experiment("experiment-002")
            node_status_after_mismatched_stop = node.status()
            stopped = controller.stop_experiment("experiment-001")
            status_after_stop = controller.get_status()
            second_started = controller.start_experiment("experiment-002")
            second_stopped = controller.stop_experiment("experiment-002")
            restarted = controller.start_experiment(
                "experiment-001",
                details={"protocol": "replacement"},
            )
            restopped = controller.stop_experiment("experiment-001")

            running_status = controller.get_status()
            self.assertTrue(started.succeeded)
            self.assertEqual(
                active_status["active_experiment_runtime_health_mapping"],
                runtime_mapping,
            )
            self.assertEqual(
                active_status["acquisition_runtime"][
                    "active_experiment_runtime_health_mapping"
                ],
                runtime_mapping,
            )
            self.assertFalse(overlapping.succeeded)
            self.assertIn("already active", overlapping.error)
            self.assertEqual(
                status_after_overlap["active_experiment_runtime_health_mapping"],
                runtime_mapping,
            )
            self.assertEqual(
                status_after_overlap["acquisition_runtime"][
                    "active_experiment_runtime_health_mapping"
                ],
                runtime_mapping,
            )
            self.assertFalse(mismatched_stop.succeeded)
            self.assertIn("not 'experiment-002'", mismatched_stop.error)
            self.assertEqual(
                node_status_after_mismatched_stop[
                    "active_experiment_runtime_health_mapping"
                ],
                runtime_mapping,
            )
            self.assertTrue(stopped.succeeded)
            self.assertEqual(
                status_after_stop["active_experiment_runtime_health_mapping"],
                (),
            )
            self.assertEqual(
                status_after_stop["acquisition_runtime"][
                    "active_experiment_runtime_health_mapping"
                ],
                (),
            )
            self.assertTrue(second_started.succeeded)
            self.assertTrue(second_stopped.succeeded)
            self.assertTrue(restarted.succeeded)
            self.assertTrue(restopped.succeeded)
            self.assertEqual(started.details["event_type"], "experiment_start")
            self.assertEqual(stopped.details["event_type"], "experiment_stop")
            self.assertIsNotNone(started.details["session_time_s"])
            self.assertIsNotNone(stopped.details["session_time_s"])
            self.assertEqual(running_status["session_state"], "running")
            self.assertTrue(running_status["acquisition_runtime"]["is_running"])

            controller.stop_session(reason="experiment lifecycle complete")
            controller.finalize_session()
            session_record = PersistentStorageManager(
                root / "accepted_records.jsonl"
            ).read_session_record(
                root
                / "session_controller-failure-session-001"
                / "session_record_final.json"
            )
            self.assertNotIn("runtime_health_mapping", session_record)
            self.assertNotIn(
                "active_experiment_runtime_health_mapping",
                session_record,
            )
            self.assertEqual(
                [
                    evidence["event_type"]
                    for evidence in session_record["experiment_lifecycle_evidence"]
                ],
                [
                    "experiment_start",
                    "experiment_stop",
                    "experiment_start",
                    "experiment_stop",
                    "experiment_start",
                    "experiment_stop",
                ],
            )
            self.assertEqual(
                [
                    evidence["experiment_id"]
                    for evidence in session_record["experiment_lifecycle_evidence"]
                ],
                [
                    "experiment-001",
                    "experiment-001",
                    "experiment-002",
                    "experiment-002",
                    "experiment-001",
                    "experiment-001",
                ],
            )
            self.assertEqual(
                session_record["experiment_lifecycle_evidence"][0]["experiment_id"],
                "experiment-001",
            )
            self.assertEqual(
                session_record["experiment_lifecycle_evidence"][0]["details"],
                {"protocol": "baseline"},
            )
            self.assertEqual(
                session_record["experiment_descriptors"],
                [
                    {
                        "experiment_id": "experiment-001",
                        "details": {"protocol": "baseline"},
                        "expected_participants": [
                            {
                                "participant_id": "camera-001",
                                "participant_type": "device",
                                "expected_contribution": "camera_frame_metadata",
                                "required": True,
                            },
                            {
                                "participant_id": "decoder-001",
                                "participant_type": "decoder",
                                "expected_contribution": "decoder_predictions",
                                "required": False,
                            },
                        ],
                    },
                    {
                        "experiment_id": "experiment-002",
                        "details": None,
                        "expected_participants": [],
                    },
                ],
            )

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

    def test_evidence_archive_write_failure_leaves_session_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root)
            adapter = ControllerFakeAdapter()
            manager = DeviceManager((adapter,))
            storage = EvidenceArchiveWriteFailingStorage(
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
            self.assertIn("evidence archive unavailable", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")

    def test_final_session_record_write_failure_leaves_session_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._config(root)
            adapter = ControllerFakeAdapter()
            manager = DeviceManager((adapter,))
            storage = FinalSessionRecordWriteFailingStorage(
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
            self.assertIn("final session record unavailable", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")

    def _controller_fixture(
        self,
        root,
        synchronization_manager=None,
        acquisition_configuration=None,
        acquisition_health_policies=(),
    ):
        config = self._config(
            root,
            acquisition_configuration,
            acquisition_health_policies,
        )
        adapter = ControllerFakeAdapter()
        manager = DeviceManager((adapter,))
        storage = PersistentStorageManager(root / "accepted_records.jsonl")
        ingestor = InMemoryIngestor(storage_manager=storage)
        synchronization = synchronization_manager or SynchronizationManager()
        node = AcquisitionNode(
            session_id=config.session_id,
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=ingestor,
            acquisition_configuration=config.acquisition_configuration,
            acquisition_health_policies=config.acquisition_health_policies,
            error_evidence_location=config.error_evidence_location,
        )
        controller = Controller(
            node,
            ingestor,
            storage,
            root / "session_record.json",
            synchronization_manager=synchronization,
        )
        return controller, manager, node, config

    def _config(
        self,
        root,
        acquisition_configuration=None,
        acquisition_health_policies=(),
    ):
        return SessionConfig(
            session_id="controller-failure-session-001",
            selected_devices=[],
            storage_location=str(root / "accepted_records.jsonl"),
            protocol_plan={"name": "controller-failure-v1"},
            error_evidence_location=str(root / "errors"),
            acquisition_configuration=acquisition_configuration,
            acquisition_health_policies=acquisition_health_policies,
        )

    @staticmethod
    def _read_jsonl(path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
