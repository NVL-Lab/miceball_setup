"""Local lifecycle calls respect the existing admitted Session closeout owner."""

import asyncio
from contextlib import ExitStack
from time import monotonic
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, ControllerActionDecision, ExperimentConfiguration, ScientificOutputSelection,
)
from tests import test_normal_stop as normal
from tests import test_experiment_capacity as capacity
from tests.test_distributed_synchronization import configuration


class LocalCloseoutOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workflow = normal.NormalStopTests()
        self.workflow.addCleanup = self.addCleanup
        self.workflow.addAsyncCleanup = self.addAsyncCleanup
        self.workflow.setUp()
        self.f = self.workflow.fixture
        await self.f.services()

        def mapped_node(**settings):
            return AcquisitionNode(**{**settings, "synchronization_manager": None,
                                      "synchronization_source_id": "sync"})

        self.node, self.declaration, self.adapter = await self.f.node(node_class=mapped_node)
        self.f.config["synchronization_configuration"] = configuration()
        self.storage = self.workflow.storage
        self.controller = Controller(self.node, self.f.ingestor, self.storage,
                                     synchronization_manager=self.f.sync)
        self.f.controller = self.controller
        launched = await self.f.launch({"node-a": [self.declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.workflow.sid = self.sid = launched.details["session_id"]
        self.workflow.connect_receipt()
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.local = self.node.local_storage_manager
        self.entered, self.resume = asyncio.Event(), asyncio.Event()
        self.closing = None
        self.pause_after_cleanup = False
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stops = self.stack.enter_context(patch.object(self.node, "stop_runtime", wraps=self.node.stop_runtime))
        self.physical_stops = self.stack.enter_context(patch.object(self.adapter, "stop", wraps=self.adapter.stop))
        publish = self.f.broker.publish

        async def wire(subject, data, stream):
            expected = "LAB_COMMAND_RESULTS" if self.pause_after_cleanup else "LAB_COMMANDS"
            if stream == expected and subject.endswith(".node-a.stop_runtime") and not self.entered.is_set():
                self.entered.set()
                await self.resume.wait()
            return await publish(subject, data, stream)

        self.stack.enter_context(patch.object(self.f.broker, "publish", new=wire))
        self.addAsyncCleanup(self.finish)

    async def finish(self):
        self.resume.set()
        if self.closing is not None:
            await asyncio.gather(self.closing, return_exceptions=True)
        if self.node.status()["is_running"]:
            self.node.stop_runtime()
        self.local.cleanup()

    def start_experiment(self, identity="experiment"):
        return self.controller.start_experiment(identity,
            scientific_outputs=(ScientificOutputSelection(self.declaration.device_id, "node-a", "events"),),
            configuration=ExperimentConfiguration(60, {"node-a": 1000000}, 1000000))

    def fatal(self, identity="fatal", experiment_id=None):
        return ControllerActionDecision(identity, self.sid, experiment_id, "source", "policy",
                                        "session_failure", "session_fail", None)

    async def begin(self):
        self.closing = asyncio.create_task(self.workflow.stop())
        await asyncio.wait_for(self.entered.wait(), 2)

    async def finish_unpreserved(self):
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            self.resume.set()
            result = await self.closing
            self.assertFalse(result.succeeded)
            self.assertIn("archive unavailable", result.error)
            self.assertIsNotNone(self.controller.get_status()["session_id"])
            retry = await self.workflow.stop()
            self.assertFalse(retry.succeeded)
            self.assertIn("archive unavailable", retry.error)
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))
        self.assertFalse(any(c["command_type"] == "kill" for c in self.f.broker.commands))

    async def test_local_fatal_uses_normal_stop_owner_and_durable_failure(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        decision = self.fatal(experiment_id="experiment")
        result = self.controller.execute_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertEqual(result.details["cleanup_owner"], "normal_stop")
        self.assertEqual(self.stops.call_count, 0)
        message, = self.controller.controller_action_decision_evidence
        self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(message))
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        events = self.controller.get_status()["experiment_lifecycle_evidence"]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
        await self.finish_unpreserved()
        self.assertEqual(self.controller.get_status()["session_state"], "failed")

    async def test_repeated_local_start_does_not_take_over_cleanup(self):
        await self.begin()
        with patch.object(self.node, "start_runtime", wraps=self.node.start_runtime) as start:
            result = self.controller.start_session()
        self.assertFalse(result.succeeded)
        start.assert_not_called()
        self.assertEqual(self.stops.call_count, 0)
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        await self.finish_unpreserved()

    async def test_late_iteration_after_owner_cleanup_does_not_stop_again(self):
        self.pause_after_cleanup = True
        await self.begin()
        result = self.controller.run_one_iteration()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        await self.finish_unpreserved()

    async def test_iteration_failure_request_during_cleanup_is_rejected_before_collection(self):
        await self.begin()
        with patch.object(self.node, "run_one_iteration", side_effect=OSError("collection failed")) as collect:
            result = self.controller.run_one_iteration()
        self.assertFalse(result.succeeded)
        collect.assert_not_called()
        self.assertEqual(self.stops.call_count, 0)
        await self.finish_unpreserved()

    async def test_local_experiment_transitions_and_initialization_cannot_escape_closeout(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        with patch.object(self.node, "prepare_experiment_scientific_outputs", wraps=self.node.prepare_experiment_scientific_outputs) as prepare, \
             patch.object(self.node, "finalize_experiment_scientific_outputs", side_effect=OSError("must remain with owner")) as finalize:
            for result in (self.start_experiment("new"), self.controller.stop_experiment("experiment"),
                           self.controller.initialize_session(), self.controller.stop_session()):
                self.assertFalse(result.succeeded)
            prepare.assert_not_called()
            finalize.assert_not_called()
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")
        await self.finish_unpreserved()

    async def test_cancelled_normal_stop_retains_admission_and_fatal_accounting(self):
        await self.begin()
        self.closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.closing
        self.assertFalse(self.start_experiment("after-interruption").succeeded)
        self.assertFalse(self.controller.start_session().succeeded)
        decision = self.fatal()
        self.assertTrue(self.controller.execute_controller_action_decision(decision).succeeded)
        self.assertEqual(self.stops.call_count, 0)
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            retry = await self.workflow.stop()
        self.assertFalse(retry.succeeded)
        self.assertIn("archive unavailable", retry.error)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.stops.call_count, 1)

    async def test_fatal_acceptance_failure_retains_consequence_and_allows_explicit_retry(self):
        await self.begin()
        decision = self.fatal()
        with patch.object(self.f.ingestor, "receive_runtime_evidence", side_effect=OSError("journal unavailable")):
            result = self.controller.execute_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.stops.call_count, 0)
        retried = self.controller.execute_controller_action_decision(decision)
        self.assertTrue(retried.succeeded, retried.error)
        self.assertTrue(retried.details["health_processing_confirmed"])
        self.assertEqual(len(self.controller.controller_action_decision_evidence), 1)
        await self.finish_unpreserved()

    async def test_mismatched_fatal_context_never_takes_cleanup_ownership(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        result = self.controller.execute_controller_action_decision(self.fatal(experiment_id="other"))
        self.assertFalse(result.succeeded)
        self.assertEqual(self.stops.call_count, 0)
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        await self.finish_unpreserved()

    async def test_unconfirmed_durable_acceptance_cannot_confirm_health_processing(self):
        await self.begin()
        decision = self.fatal()
        with patch.object(self.f.ingestor, "has_durable_runtime_evidence", return_value=False):
            result = self.controller.execute_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertIn("durable acceptance is unconfirmed", result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.stops.call_count, 0)
        self.assertTrue(self.controller.execute_controller_action_decision(decision).succeeded)
        await self.finish_unpreserved()

    async def test_experiment_failure_decision_cannot_finalize_for_the_stop_owner(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        decision = ControllerActionDecision("experiment-failure", self.sid, "experiment", "source", "policy",
                                            "experiment_failure", "experiment_fail", None)
        with patch.object(self.node, "finalize_experiment_scientific_outputs", wraps=self.node.finalize_experiment_scientific_outputs) as finalize:
            result = self.controller.execute_controller_action_decision(decision)
            self.assertFalse(result.succeeded)
            finalize.assert_not_called()
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")
        await self.finish_unpreserved()

    async def test_owner_finalization_failure_retains_science_and_retry_progress(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        self.assertFalse(self.controller.stop_experiment("experiment").succeeded)
        with patch.object(self.local, "finalize_stream", side_effect=OSError("scientific finalization unavailable")):
            self.resume.set()
            result = await self.closing
        self.assertFalse(result.succeeded)
        self.assertIsNotNone(self.node.reserved_for_session_id)
        self.assertTrue(any(m.lifecycle_state == "open" for m in self.local.manifests))
        self.assertEqual(self.physical_stops.call_count, 1)
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            retry = await self.workflow.stop()
        self.assertFalse(retry.succeeded)
        self.assertIn("archive unavailable", retry.error)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))

    async def test_expiry_and_fatal_decision_preserve_one_canonical_experiment_end(self):
        started = self.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        await self.begin()
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=monotonic() + 61):
            self.assertTrue(self.node.expire_experiment_if_due())
        proof = self.node.read_experiment_expiry("experiment")
        self.assertFalse(self.controller.accept_experiment_expiry(proof))
        result = self.controller.execute_controller_action_decision(self.fatal(experiment_id="experiment"))
        self.assertTrue(result.succeeded, result.error)
        events = self.controller.get_status()["experiment_lifecycle_evidence"]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        await self.finish_unpreserved()


class LocalLifecycleCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.f = capacity.LocalActivationFailureTests()
        self.f.addCleanup = self.addCleanup
        self.f.setUp()

    def test_repeated_start_preserves_recording_and_a_subsequent_experiment(self):
        self.assertTrue(self.f.start("first").succeeded)
        with patch.object(self.f.node, "start_runtime", wraps=self.f.node.start_runtime) as start, \
             patch.object(self.f.node, "stop_runtime", wraps=self.f.node.stop_runtime) as stop:
            self.assertFalse(self.f.controller.start_session().succeeded)
            start.assert_not_called()
            stop.assert_not_called()
        self.assertTrue(self.f.controller.run_one_iteration().succeeded)
        self.assertTrue(self.f.controller.stop_experiment("first").succeeded)
        self.f.record_next()

    def test_iteration_failure_still_cleans_up_when_no_closeout_is_admitted(self):
        self.assertTrue(self.f.start("failed").succeeded)
        with patch.object(self.f.node, "run_one_iteration", side_effect=OSError("collection failed")), \
             patch.object(self.f.node, "stop_runtime", wraps=self.f.node.stop_runtime) as stop:
            result = self.f.controller.run_one_iteration()
        self.assertFalse(result.succeeded)
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(self.f.controller.get_status()["session_state"], "failed")
        self.assertFalse(self.f.node.status()["is_running"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.local.manifests))
