import tempfile
import unittest
from pathlib import Path

from lab_sync_acquisition import (
    AcquisitionNode,
    Controller,
    ControllerActionDecision,
    DeviceDeclaration,
    DeviceManager,
    HealthInterpretationEvidence,
    InMemoryIngestor,
    PersistentStorageManager,
    SessionConfig,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


class ControllerActionDecisionTests(unittest.TestCase):
    def test_each_interpretation_produces_exactly_one_evidence_only_decision(self):
        expected_decisions = {
            "informational": "record_only",
            "uninterpreted": "record_only",
            "warning": "record_warning",
            "recoverable_failure": "record_recoverable_failure",
            "experiment_failure": "experiment_fail",
            "session_failure": "session_fail",
        }

        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            before = controller.get_status()

            for index, (interpretation, expected_decision) in enumerate(
                expected_decisions.items(),
                start=1,
            ):
                evidence = self._evidence(index, interpretation)
                decision = controller.process_health_interpretation(evidence)

                self.assertIsInstance(decision, ControllerActionDecision)
                self.assertEqual(decision.controller_decision, expected_decision)
                self.assertEqual(decision.interpretation_label, interpretation)
                self.assertEqual(
                    decision.originating_observation_id,
                    evidence.originating_observation_id,
                )
                self.assertEqual(len(controller.controller_action_decisions), index)

            after = controller.get_status()
            self.assertEqual(after["session_state"], before["session_state"])
            self.assertEqual(after["acquisition_runtime"], before["acquisition_runtime"])
            self.assertEqual(after["last_command"], before["last_command"])

    def test_action_decision_round_trips_with_interpretation_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self._controller(Path(directory))
            evidence = self._evidence(1, "warning")

            decision = controller.process_health_interpretation(evidence)
            reconstructed = ControllerActionDecision.from_dict(decision.to_dict())

            self.assertEqual(reconstructed, decision)
            self.assertEqual(decision.session_id, "controller-action-session")
            self.assertEqual(decision.experiment_id, evidence.experiment_id)
            self.assertEqual(decision.live_source_id, evidence.live_source_id)
            self.assertEqual(
                decision.acquisition_health_policy,
                evidence.acquisition_health_policy,
            )

    def test_no_mutation_decisions_execute_successfully(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, node, _, _ = self._running_controller(Path(directory))
            before = controller.get_status()
            decisions = [
                controller.process_health_interpretation(
                    self._evidence(index, interpretation)
                )
                for index, interpretation in enumerate(
                    ("informational", "uninterpreted", "warning", "recoverable_failure"),
                    start=1,
                )
            ]
            decisions.append(
                ControllerActionDecision(
                    originating_observation_id="health-observation-operator",
                    session_id="controller-action-session",
                    experiment_id="experiment-001",
                    live_source_id="camera-source-001",
                    acquisition_health_policy="camera-policy",
                    interpretation_label="warning",
                    controller_decision="operator_required",
                    decision_time_s=1.25,
                )
            )

            for decision in decisions:
                result = controller.execute_controller_action_decision(decision)
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(
                    result.details,
                    {
                        "controller_decision": decision.controller_decision,
                        "lifecycle_mutated": False,
                    },
                )

            after = controller.get_status()
            self.assertEqual(after["session_state"], before["session_state"])
            self.assertEqual(
                after["active_experiment_runtime_health_mapping"],
                before["active_experiment_runtime_health_mapping"],
            )
            self.assertTrue(node.status()["is_running"])
            controller.stop_session()

    def test_experiment_failure_ends_only_active_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, node, storage, manager = self._running_controller(root)
            started = controller.start_experiment("experiment-001")
            self.assertTrue(started.succeeded)
            decision = controller.process_health_interpretation(
                self._evidence(1, "experiment_failure")
            )

            result = controller.execute_controller_action_decision(decision)

            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(result.details["event_type"], "experiment_fail")
            self.assertEqual(result.details["experiment_id"], "experiment-001")
            status = controller.get_status()
            self.assertEqual(status["session_state"], "running")
            self.assertTrue(status["acquisition_runtime"]["is_running"])
            self.assertEqual(
                status["active_experiment_runtime_health_mapping"],
                (),
            )
            self.assertEqual(
                node.status()["active_experiment_runtime_health_mapping"],
                (),
            )

            controller.stop_session()
            controller.finalize_session()
            record = storage.read_session_record(
                root
                / "session_controller-action-session"
                / "session_record_final.json"
            )
            self.assertEqual(
                [
                    item["event_type"]
                    for item in record["experiment_lifecycle_evidence"]
                ],
                ["experiment_start", "experiment_fail"],
            )
            self.assertNotIn(
                "experiment_abort",
                {
                    item["event_type"]
                    for item in record["experiment_lifecycle_evidence"]
                },
            )

    def test_session_failure_uses_existing_failed_session_cleanup_path(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, node, _, manager = self._running_controller(Path(directory))
            decision = controller.process_health_interpretation(
                self._evidence(1, "session_failure")
            )

            result = controller.execute_controller_action_decision(decision)

            self.assertTrue(result.succeeded)
            self.assertEqual(result.details["session_state"], "failed")
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assertFalse(node.status()["is_running"])
            self.assertTrue(all(status.shutdown for status in manager.collect_statuses()))

    def test_normal_experiment_stop_remains_normal_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            controller, _, _, _ = self._running_controller(Path(directory))
            controller.start_experiment("experiment-001")

            result = controller.stop_experiment("experiment-001")

            self.assertTrue(result.succeeded)
            self.assertEqual(result.details["event_type"], "experiment_stop")
            self.assertEqual(controller.get_status()["session_state"], "running")
            controller.stop_session()

    def _controller(self, root):
        manager = DeviceManager(
            (ReadyFakeAdapter("source-001", "fake", ("stream",), True),)
        )
        storage = PersistentStorageManager(root / "accepted.jsonl")
        ingestor = InMemoryIngestor(storage_manager=storage)
        node = AcquisitionNode(
            session_id="controller-action-session",
            device_manager=manager,
            synchronization_manager=SynchronizationManager(),
            ingestor=ingestor,
        )
        controller = Controller(
            node,
            ingestor,
            storage,
            root / "session-record.json",
        )
        result = controller.create_session(
            SessionConfig(
                session_id="controller-action-session",
                selected_devices=[
                    DeviceDeclaration(
                        device_id="source-001",
                        device_type="fake",
                        enabled=True,
                        required=True,
                        declared_capabilities=("stream",),
                    )
                ],
                storage_location=str(root / "accepted.jsonl"),
                protocol_plan={"name": "phase-8b"},
                error_evidence_location=str(root / "errors"),
            )
        )
        self.assertTrue(result.succeeded)
        return controller

    def _running_controller(self, root):
        manager = DeviceManager(
            (ReadyFakeAdapter("source-001", "fake", ("stream",), True),)
        )
        storage = PersistentStorageManager(root / "accepted.jsonl")
        ingestor = InMemoryIngestor(storage_manager=storage)
        synchronization = SynchronizationManager()
        node = AcquisitionNode(
            session_id="controller-action-session",
            device_manager=manager,
            synchronization_manager=synchronization,
            ingestor=ingestor,
            error_evidence_location=str(root / "errors"),
        )
        controller = Controller(
            node,
            ingestor,
            storage,
            root / "session-record.json",
            synchronization_manager=synchronization,
        )
        manager.initialize_all(config={"mode": "phase-8b"})
        readiness = node.check_ready()
        created = controller.create_session(
            SessionConfig(
                session_id="controller-action-session",
                selected_devices=[
                    DeviceDeclaration(
                        device_id="source-001",
                        device_type="fake",
                        enabled=True,
                        required=True,
                        declared_capabilities=("stream",),
                    )
                ],
                storage_location=str(root / "accepted.jsonl"),
                protocol_plan={"name": "phase-8b"},
                error_evidence_location=str(root / "errors"),
            )
        )
        initialized = controller.initialize_session(
            readiness["device_readiness"],
            readiness["service_readiness"],
        )
        started = controller.start_session()
        self.assertTrue(created.succeeded, created.error)
        self.assertTrue(initialized.succeeded, initialized.error)
        self.assertTrue(started.succeeded, started.error)
        return controller, node, storage, manager

    def _evidence(self, index, interpretation):
        return HealthInterpretationEvidence(
            originating_observation_id=f"health-observation-{index}",
            experiment_id="experiment-001",
            live_source_id="camera-source-001",
            expected_participant_id="camera-001",
            observation_type="expected_acquisition_evidence_missing",
            acquisition_health_policy="camera-policy",
            interpretation_label=interpretation,
            required=True,
            session_time_s=1.25,
            details={"observed_record_count": 0},
        )


if __name__ == "__main__":
    unittest.main()
