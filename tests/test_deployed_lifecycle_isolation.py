"""Independent Controller orchestration never borrows another service owner."""

from dataclasses import replace
from pathlib import Path
import unittest

from lab_sync_acquisition import AcquisitionNode, Controller, ExperimentConfiguration, RuntimeParticipant, ScientificOutputSelection
from tests import test_session_launch as launch
from tests import test_remote_finalization_proof as remote
from tests import test_controller_action_decision as development
from tests import test_normal_stop as normal
from tests.test_distributed_synchronization import configuration
from unittest.mock import patch
from tests.test_producer_publication_completion import interpretation


class DeploymentCompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_collaborators_are_rejected_before_distributed_admission(self):
        fixture = launch.SessionLaunchTests()
        fixture.addCleanup = self.addCleanup
        fixture.addAsyncCleanup = self.addAsyncCleanup
        fixture.setUp()
        await fixture.services()
        node, declaration, _ = await fixture.node()
        for collaborators in ({"acquisition_node": node}, {"ingestor": fixture.ingestor},
                              {"synchronization_manager": fixture.sync},
                              {"storage_manager": object()}):
            with self.subTest(collaborators=tuple(collaborators)):
                fixture.controller = Controller(**collaborators)
                before = list(fixture.broker.commands)
                result = await fixture.launch({"node-a": [declaration]})
                self.assertFalse(result.succeeded, result.details)
                self.assertIn("in-process", result.error)
                self.assertIsNone(fixture.controller.get_status()["session_id"])
                self.assertIsNone(node.reserved_for_session_id)
                self.assertEqual(fixture.broker.commands, before)


class LaunchedEntryPointIsolationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = remote.RemoteFinalizationProofTests.asyncSetUp

    async def test_historical_lifecycle_cannot_mutate_launched_session(self):
        controller = self.controller
        decision = controller.process_health_interpretation(replace(interpretation("misroute"),
            interpretation_label="experiment_failure"))
        before = controller.get_status()
        science = {m.local_storage_path: Path(m.local_storage_path).read_bytes()
                   for m in self.f.node.local_storage_manager.manifests}
        commands = list(self.f.broker.commands)
        for invoke in (controller.initialize_session, controller.start_session,
                       controller.run_one_iteration,
                       lambda: controller.start_experiment("wrong"),
                       lambda: controller.stop_experiment("experiment"), controller.stop_session,
                       controller.preserve_artifact_collection_handoff,
                       controller.collect_session_artifacts,
                       lambda: controller.execute_controller_action_decision(decision)):
            with self.subTest(entry=invoke):
                result = invoke()
                self.assertFalse(result.succeeded, result.details)
                self.assertIn("in-process", result.error)
                after = controller.get_status()
                for key in ("session_state", "active_experiment_id", "experiment_lifecycle_evidence"):
                    self.assertEqual(after[key], before[key])
        self.assertEqual(self.f.broker.commands, commands)
        self.assertTrue(self.f.node.experiment_runtime_active)
        self.assertEqual(science, {p: Path(p).read_bytes() for p in science})
        self.assertTrue(all(m.lifecycle_state == "open" for m in self.f.node.local_storage_manager.manifests))
        result = await controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))

    async def test_legacy_preservation_and_collection_reject_before_side_effects(self):
        controller = self.controller
        before = controller.get_status()
        for invoke in (
                lambda: controller.archive_acquisition_evidence(communication=self.f.ingestor_handler),
                controller.collect_session_artifacts_with_evidence):
            result = await invoke()
            self.assertFalse(result.succeeded)
            self.assertIn("in-process", result.error)
        for result in (
                controller.collect_saved_session_artifacts(self.f.sid, evidence_id="collection"),
                controller.collect_selected_session_artifacts({self.f.sid: "collection"})):
            self.assertFalse(result.succeeded)
            self.assertIn("in-process", result.error)
        self.assertEqual(controller.get_status()["session_state"], before["session_state"])
        self.assertTrue(self.f.node.experiment_runtime_active)

    async def test_stopped_launched_session_requires_nats_closeout(self):
        controller = self.controller
        stopped = await controller.stop_launched_session()
        self.assertTrue(stopped.succeeded, stopped.error)
        before = controller.get_status()
        self.assertEqual(before["session_state"], "stopping")
        after = controller.get_status()
        self.assertEqual(after["session_state"], "stopping")
        self.assertEqual(after["experiment_lifecycle_evidence"], before["experiment_lifecycle_evidence"])
        self.assertIsNone(self.owner.workflow.storage.get_acquisition_stage_preservation_confirmation(self.f.sid))
        result = await self.owner.workflow.stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(controller.get_status()["session_state"], "completed")


class MultipleScientificOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_launched_owner_must_confirm_scientific_finalization(self):
        workflow = normal.NormalStopTests()
        workflow.addCleanup = self.addCleanup
        workflow.addAsyncCleanup = self.addAsyncCleanup
        workflow.setUp()
        f = workflow.fixture
        f.config["synchronization_configuration"] = configuration()
        await f.services()
        selections = {}

        def mapped_node(**settings):
            return AcquisitionNode(**{**settings, "synchronization_manager": None,
                                      "synchronization_source_id": "sync"})

        for identity in ("node-a", "node-b"):
            node, declaration, _ = await f.node(identity, node_class=mapped_node)
            selections[identity] = [declaration]
        launched = await f.controller.launch_session(selections, communication=f.communication,
            participants=f.participants, config_parameters=f.config, result_window_s=1)
        self.assertTrue(launched.succeeded, launched.error)
        for node in f.nodes.values():
            self.addCleanup(node.local_storage_manager.cleanup)
        self.addAsyncCleanup(f.controller.stop_launched_session)
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        result = await f.controller.start_launched_experiment("experiment",
            scientific_outputs=tuple(ScientificOutputSelection(devices[0].device_id, identity, "events")
                                     for identity, devices in selections.items()),
            configuration=ExperimentConfiguration(60, {identity: 1000000 for identity in selections}, 1000000,
                participating_devices={identity: [d.device_id for d in devices] for identity, devices in selections.items()}),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(result.succeeded, result.error)
        for identity in selections:
            result = await f.communication.request_runtime_command(RuntimeParticipant("acquisition_node", identity),
                "run_one_iteration", launched.details["session_id"], {}, 1)
            self.assertTrue(result.success)
        decision = f.controller.process_health_interpretation(replace(interpretation("all-owners"),
            interpretation_label="experiment_failure"))
        with patch.object(f.nodes["node-b"].local_storage_manager, "finalize_stream",
                          side_effect=OSError("second scientific owner unavailable")):
            result = await f.controller.execute_launched_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertFalse((result.details or {}).get("health_processing_confirmed", False))
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in f.nodes["node-a"].local_storage_manager.manifests))
        self.assertTrue(any(m.lifecycle_state == "open" for m in f.nodes["node-b"].local_storage_manager.manifests))
        result = await f.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["health_processing_confirmed"])
        for node in f.nodes.values():
            self.assertTrue(all(m.lifecycle_state == "finalized" for m in node.local_storage_manager.manifests))
            self.assertTrue(all(len(Path(m.local_storage_path).read_text().splitlines()) == 1
                                for m in node.local_storage_manager.manifests))
        finals = [command for command in f.broker.commands
                  if command["command_type"] == "finalize_experiment_scientific_outputs"]
        self.assertEqual({command["target_id"] for command in finals}, set(selections))
        self.assertEqual([event.event_type for event in f.controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])


class InProcessCompatibilityTests(unittest.TestCase):
    def test_development_session_still_acquires_and_stops(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            fixture = development.ControllerActionDecisionTests()
            controller, node, _, _ = fixture._running_controller(Path(directory))
            try:
                self.assertTrue(controller.start_experiment("development",
                    configuration=ExperimentConfiguration(60, {}, 1000000,
                        participating_devices={"node": ["source-001"]})).succeeded)
                self.assertTrue(controller.run_one_iteration().succeeded)
                self.assertTrue(controller.stop_experiment("development").succeeded)
                self.assertTrue(controller.stop_session().succeeded)
                self.assertEqual(controller.get_status()["session_state"], "stopping")
            finally:
                node.local_storage_manager.cleanup()


class InProcessAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_release_retains_running_and_stopped_session_without_writing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = development.ControllerActionDecisionTests()
            controller, node, storage, _ = fixture._running_controller(root)
            try:
                for stopped in (False, True):
                    if stopped:
                        self.assertTrue(controller.stop_session().succeeded)
                    before = controller.get_status()
                    products = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    with patch.object(storage, "write_final_session_record", side_effect=AssertionError("unexpected write")), \
                            patch.object(node, "stop_runtime", side_effect=AssertionError("unexpected cleanup")):
                        for _ in range(2):
                            result = await controller.release_session()
                            self.assertFalse(result.succeeded)
                            self.assertIn("launched NATS binding", result.error)
                    after = controller.get_status()
                    for key in ("session_id", "session_state", "experiment_lifecycle_evidence", "last_released_session"):
                        self.assertEqual(after[key], before[key])
                    self.assertEqual(products, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
            finally:
                node.local_storage_manager.cleanup()

    async def test_local_failed_session_cannot_release_even_with_owner_archival(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            fixture = development.ControllerActionDecisionTests()
            controller, node, storage, _ = fixture._running_controller(Path(directory))
            try:
                self.assertTrue(controller.start_experiment("experiment-001",
                    configuration=ExperimentConfiguration(60, {}, 1000000,
                        participating_devices={"node": ["source-001"]})).succeeded)
                decision = controller.process_health_interpretation(fixture._evidence(1, "session_failure"))
                self.assertTrue(controller.execute_controller_action_decision(decision).succeeded)
                before = controller.get_status()
                self.assertEqual(before["session_state"], "failed")
                self.assertTrue(any(item.startswith("Controller decision preservation:")
                    for item in controller.maintenance_blockers(controller._ingestor, storage)))
                paths = storage.write_evidence_archive(before["session_id"],
                    controller._ingestor.compile_persistent_runtime_evidence())
                storage.write_final_session_record(before["session_id"], **controller._session_record_evidence())
                blockers = controller.maintenance_blockers(controller._ingestor, storage)
                self.assertIn("Unconfirmed final Session persistence", blockers)
                self.assertFalse(any(item.startswith("Controller decision preservation:") for item in blockers))
                paths["runtime_evidence"].write_text("", encoding="utf-8")
                self.assertTrue(any(item.startswith("Controller decision preservation:")
                    for item in controller.maintenance_blockers(controller._ingestor, storage)))
                result = await controller.release_session()
                self.assertFalse(result.succeeded)
                self.assertEqual(controller.get_status()["session_id"], before["session_id"])
                self.assertEqual(controller.get_status()["session_state"], "failed")
                self.assertEqual(controller.get_status()["last_released_session"], before["last_released_session"])
            finally:
                node.local_storage_manager.cleanup()

    async def test_launched_closeout_cannot_claim_an_in_process_session(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            fixture = development.ControllerActionDecisionTests()
            controller, node, _, _ = fixture._running_controller(Path(directory))
            try:
                self.assertTrue(controller.start_experiment("development",
                    configuration=ExperimentConfiguration(60, {}, 1000000,
                        participating_devices={"node": ["source-001"]})).succeeded)
                before = controller.get_status()
                for invoke in (controller.stop_launched_session,
                               lambda: controller.stop_launched_experiment("development"),
                               lambda: controller.normal_stop_session(communication=None,
                                   storage_participant=RuntimeParticipant("storage_manager", "storage"),
                                   result_window_s=1),
                               lambda: controller.kill_session(communication=None,
                                   storage_participant=RuntimeParticipant("storage_manager", "storage"),
                                   result_window_s=1, operator_authorized=True)):
                    result = await invoke()
                    self.assertFalse(result.succeeded)
                    after = controller.get_status()
                    for key in ("session_state", "active_experiment_id", "experiment_lifecycle_evidence"):
                        self.assertEqual(after[key], before[key])
                self.assertTrue(controller.run_one_iteration().succeeded)
                self.assertTrue(controller.stop_session().succeeded)
            finally:
                node.local_storage_manager.cleanup()
