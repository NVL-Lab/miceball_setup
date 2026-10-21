"""Local lifecycle calls respect the existing admitted Session closeout owner."""

import asyncio
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from time import monotonic
import unittest
from unittest.mock import PropertyMock, patch

import h5py
import numpy as np

from lab_sync_acquisition import (
    AcquisitionNode, Controller, ControllerActionDecision, ExperimentConfiguration, RuntimeParticipant,
    ScientificOutputSelection,
)
from tests import test_normal_stop as normal
from tests import test_experiment_capacity as capacity
from tests import test_closeout_attempt_ownership as attempts
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

    async def test_launched_stop_failure_accounts_for_failure_without_local_time(self):
        self.assertTrue(self.start_experiment().succeeded)
        self.node.run_one_iteration()
        self.resume.set()
        self.f.broker.drop_results.add(("node-a", "release_reservation"))
        read_time = type(self.f.sync).current_session_time_s.fget

        def read_after_cleanup():
            if self.stops.call_count:
                raise OSError("Session Time unavailable after cleanup")
            return read_time(self.f.sync)

        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=read_after_cleanup), \
             patch.object(self.local, "finalize_stream", wraps=self.local.finalize_stream) as finalize:
            result = await self.controller.stop_launched_session()
        self.assertFalse(result.succeeded)
        self.assertIn("Distributed runtime cleanup unconfirmed", result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        events = self.controller.get_status()["experiment_lifecycle_evidence"]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
        self.assertIsNone(events[-1].session_time_s)
        self.assertTrue(events[-1].details["timing_unconfirmed"])
        self.assertEqual(events[-1].details["reason"], "Distributed runtime cleanup unconfirmed")
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertEqual(finalize.call_count, 1)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.assertEqual(self.controller.get_status()["session_id"], self.sid)
        self.assertFalse((await self.controller.release_session()).succeeded)
        self.assertFalse(self.controller.stop_session().succeeded)
        with patch.object(self.storage, "write_evidence_archive", side_effect=OSError("archive unavailable")):
            self.assertFalse(self.controller.finalize_session().succeeded)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.stops.call_count, 1)
        self.assertFalse(any(c["command_type"] == "kill" for c in self.f.broker.commands))

    async def test_interrupted_normal_stop_preserves_fatal_details_without_time(self):
        self.assertTrue(self.start_experiment().succeeded)
        await self.begin()
        self.closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.closing
        decision = self.fatal(experiment_id="experiment")
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Session Time unavailable")):
            result = self.controller.execute_controller_action_decision(decision)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertEqual(self.stops.call_count, 0)
        event = self.controller.get_status()["experiment_lifecycle_evidence"][-1]
        self.assertEqual(event.event_type, "experiment_fail")
        self.assertIsNone(event.session_time_s)
        self.assertTrue(event.details["timing_unconfirmed"])
        self.assertEqual(event.details["cleanup_owner"], "normal_stop")
        for key, value in decision.to_dict().items():
            self.assertEqual(event.details[key], value)
        self.closing = asyncio.create_task(self.workflow.stop())
        await self.finish_unpreserved()
        self.assertEqual(self.controller.get_status()["session_state"], "failed")


class NormalStopAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def running(self, *, remote=False, active=True, preserve=False):
        self.remote = remote
        if remote:
            fixture = attempts.InterruptedNormalStopTests()
            fixture.addCleanup = self.addCleanup
            fixture.addAsyncCleanup = self.addAsyncCleanup
            self.workflow = await fixture.workflow()
            self.f = self.workflow.fixture
            self.node = self.f.node
        else:
            fixture = LocalCloseoutOwnershipTests()
            fixture.addCleanup = self.addCleanup
            fixture.addAsyncCleanup = self.addAsyncCleanup
            await fixture.asyncSetUp()
            fixture.resume.set()
            self.assertTrue(fixture.start_experiment().succeeded)
            fixture.node.run_one_iteration()
            self.workflow, self.f, self.node = fixture.workflow, fixture.f, fixture.node
        self.controller = self.f.controller
        self.storage = self.workflow.storage
        self.sid = self.controller.get_status()["session_id"]
        self.local = self.node.local_storage_manager
        if not active:
            ended = (await self.controller.stop_launched_experiment("experiment") if remote
                     else self.controller.stop_experiment("experiment"))
            self.assertTrue(ended.succeeded, ended.error)
        self.stops = self.enterContext(patch.object(self.node, "stop_runtime", wraps=self.node.stop_runtime))
        adapter, = self.node._runtime_device_manager.adapters
        self.physical_stops = self.enterContext(patch.object(adapter, "stop", wraps=adapter.stop))
        self.finalize = self.enterContext(patch.object(self.local, "finalize_stream", wraps=self.local.finalize_stream))
        if not preserve:
            self.enterContext(patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")))

    @asynccontextmanager
    async def holding(self, component_type, operation, *, interruptions=0):
        entered, proceed = asyncio.Event(), asyncio.Event()
        request = self.f.communication.request_runtime_command

        async def paused(participant, command_type, *args, **kwargs):
            if participant.component_type == component_type and command_type == operation:
                entered.set()
                await proceed.wait()
            return await request(participant, command_type, *args, **kwargs)

        with patch.object(self.f.communication, "request_runtime_command", new=paused):
            try:
                for attempt in range(interruptions + 1):
                    entered.clear()
                    self.closing = asyncio.create_task(self.workflow.stop())
                    await asyncio.wait_for(entered.wait(), 2)
                    if attempt < interruptions:
                        await self.cancel_closeout()
                yield
            finally:
                proceed.set()
                self.closeout_result, = await asyncio.gather(self.closing, return_exceptions=True)

    async def cancel_closeout(self):
        self.closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.closing

    def decision(self, experiment_id="experiment", action="session_fail"):
        return ControllerActionDecision("fatal-" + str(experiment_id), self.sid, experiment_id, "source", "policy",
            "session_failure" if action == "session_fail" else "experiment_failure", action, None)

    async def execute(self, decision):
        if self.remote:
            return await self.controller.execute_launched_controller_action_decision(decision)
        return self.controller.execute_controller_action_decision(decision)

    def assert_failed_closeout(self):
        self.assertFalse(self.closeout_result.succeeded)
        self.assertIn("archive unavailable", self.closeout_result.error)
        status = self.controller.get_status()
        self.assertEqual(status["session_state"], "failed")
        self.assertEqual(status["session_id"], self.sid)
        self.assertIsNone(status["active_experiment_id"])
        events = status["experiment_lifecycle_evidence"]
        self.assertEqual(len([e for e in events if e.event_type != "experiment_start"]), 1)
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertEqual(self.finalize.call_count, 1)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.local.manifests))
        self.assertIsNone(self.storage.get_acquisition_stage_preservation_confirmation(self.sid))
        self.assertFalse(any(c["command_type"] == "kill" for c in self.f.broker.commands))

    async def test_local_retry_retains_original_experiment_for_fatal_accounting(self):
        await self.running()
        async with self.holding("synchronization_manager", "stop_runtime", interruptions=1):
            self.assertEqual(self.controller.get_status()["session_state"], "stopping")
            self.assertIsNone(self.controller.get_status()["active_experiment_id"])
            self.assertFalse((await self.execute(self.decision("unrelated"))).succeeded)
            result = await self.execute(self.decision())
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["durable_acceptance_confirmed"])
            evidence = self.controller.controller_action_decision_evidence[-1]
            self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(evidence))
        self.assert_failed_closeout()
        self.closeout_result = await self.workflow.stop()
        self.assert_failed_closeout()

    async def test_remote_repeated_retry_retains_original_experiment_for_fatal_accounting(self):
        await self.running(remote=True)
        async with self.holding("synchronization_manager", "stop_runtime", interruptions=2):
            result = await self.execute(self.decision())
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["durable_acceptance_confirmed"])
        self.assert_failed_closeout()
        self.closeout_result = await self.workflow.stop()
        self.assert_failed_closeout()

    async def test_rejected_remote_owner_retry_cannot_replace_original_context(self):
        await self.running(remote=True)
        async with self.holding("synchronization_manager", "stop_runtime"):
            await self.cancel_closeout()
            rejected = await self.controller.normal_stop_session(communication=self.f.communication,
                storage_participant=RuntimeParticipant("storage_manager", "different-owner"), result_window_s=.05)
            self.assertFalse(rejected.succeeded)
            self.assertIn("owner identity", rejected.error)
            result = await self.execute(self.decision())
            self.assertTrue(result.succeeded, result.error)
        self.closeout_result = await self.workflow.stop()
        self.assert_failed_closeout()

    async def test_interrupted_closeout_fences_launched_start_without_active_experiment(self):
        await self.running(remote=True, active=False)
        async with self.holding("acquisition_node", "stop_runtime"):
            await self.cancel_closeout()
            with patch.object(self.node, "prepare_experiment_scientific_outputs",
                              wraps=self.node.prepare_experiment_scientific_outputs) as prepare, \
                 patch.object(self.node, "activate_experiment_runtime", wraps=self.node.activate_experiment_runtime) as activate:
                result = await self.controller.start_launched_experiment("competing",
                    scientific_outputs=(ScientificOutputSelection("device", "node", "events"),),
                    configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000),
                    storage_participant=self.workflow.storage_participant)
            self.assertFalse(result.succeeded)
            prepare.assert_not_called()
            activate.assert_not_called()
            self.assertIsNone(self.controller.get_status()["active_experiment_id"])
            self.assertFalse(self.node.scientific_acquisition_active)
            self.assertEqual(self.stops.call_count, 0)

    async def test_interrupted_closeout_fences_manual_launched_termination(self):
        await self.running(remote=True)
        async with self.holding("acquisition_node", "stop_runtime"):
            await self.cancel_closeout()
            with patch.object(self.node, "finalize_experiment_scientific_outputs",
                              wraps=self.node.finalize_experiment_scientific_outputs) as finalize:
                result = await self.controller.stop_launched_experiment("experiment")
            self.assertFalse(result.succeeded)
            finalize.assert_not_called()
            self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")

    async def test_interrupted_closeout_fences_remote_experiment_failure(self):
        await self.running(remote=True)
        async with self.holding("acquisition_node", "stop_runtime"):
            await self.cancel_closeout()
            with patch.object(self.node, "finalize_experiment_scientific_outputs",
                              wraps=self.node.finalize_experiment_scientific_outputs) as finalize:
                result = await self.execute(self.decision(action="experiment_fail"))
            self.assertFalse(result.succeeded)
            finalize.assert_not_called()
            self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")

    async def test_cancellation_between_cleanup_and_canonical_end_retains_context(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.running(remote=remote)
                async with self.holding("synchronization_manager", "read_session_time", interruptions=1):
                    self.assertEqual(self.stops.call_count, 1)
                    self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")
                    result = await self.execute(self.decision())
                    self.assertTrue(result.succeeded, result.error)
                self.assert_failed_closeout()
                endings = [e.event_type for e in self.controller.get_status()["experiment_lifecycle_evidence"]
                           if e.event_type != "experiment_start"]
                self.assertEqual(endings, ["experiment_fail"])

    async def test_fatal_before_cancellation_keeps_its_failure_and_cleanup_owner(self):
        await self.running(remote=True)
        async with self.holding("acquisition_node", "stop_runtime"):
            decision = self.decision()
            self.assertTrue((await self.execute(decision)).succeeded)
            self.assertEqual(self.controller.get_status()["session_state"], "failed")
            await self.cancel_closeout()
            self.assertEqual(self.stops.call_count, 0)
        self.closeout_result = await self.workflow.stop()
        self.assert_failed_closeout()
        self.assertEqual(len(self.controller.controller_action_decision_evidence), 1)

    async def test_fatal_after_cancellation_before_retry_keeps_original_context(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.running(remote=remote)
                async with self.holding("synchronization_manager", "stop_runtime"):
                    await self.cancel_closeout()
                    result = await self.execute(self.decision())
                    self.assertTrue(result.succeeded, result.error)
                    self.assertTrue(result.details["durable_acceptance_confirmed"])
                self.closeout_result = await self.workflow.stop()
                self.assert_failed_closeout()

    async def test_original_none_context_survives_retries_without_authorizing_old_experiments(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.running(remote=remote, active=False)
                async with self.holding("synchronization_manager", "stop_runtime", interruptions=2):
                    self.assertFalse((await self.execute(self.decision())).succeeded)
                    self.assertEqual(self.controller.get_status()["session_state"], "stopping")
                    result = await self.execute(self.decision(None))
                    self.assertTrue(result.succeeded, result.error)
                self.assert_failed_closeout()

    async def test_retry_requires_durable_acceptance_separately_from_canonical_failure(self):
        await self.running(remote=True)
        async with self.holding("synchronization_manager", "stop_runtime", interruptions=1):
            decision = self.decision()
            self.f.broker.drop_results.add(("ingestor", "read_runtime_evidence_acceptance"))
            try:
                result = await self.execute(decision)
            finally:
                self.f.broker.drop_results.clear()
            self.assertFalse(result.succeeded)
            self.assertFalse(result.details["health_processing_confirmed"])
            self.assertEqual(self.controller.get_status()["session_state"], "failed")
            evidence, = self.controller.controller_action_decision_evidence
            self.assertEqual(evidence.payload, decision.to_dict())
            self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(evidence))
            result = await self.execute(decision)
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["durable_acceptance_confirmed"])
            self.assertEqual(self.controller.controller_action_decision_evidence, (evidence,))
        self.assert_failed_closeout()

    async def test_verified_retirement_allows_a_new_session_with_fresh_context(self):
        await self.running(remote=True, preserve=True)
        async with self.holding("synchronization_manager", "stop_runtime", interruptions=1):
            self.assertTrue((await self.execute(self.decision())).succeeded)
        self.assertTrue(self.closeout_result.succeeded, self.closeout_result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        before = self.workflow.archive()
        preserved = self.storage.get_session_preservation_confirmation(self.sid)
        self.assertEqual(preserved["session_record"]["final_session_status"]["state"], "failed")
        self.assertTrue((await self.workflow.stop()).succeeded)
        self.assertEqual(self.workflow.archive(), before)
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertEqual(self.finalize.call_count, 1)
        released = await self.controller.release_session(communication=self.f.communication, result_window_s=.05)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(self.controller.get_status()["session_id"])
        self.assertIsNone(self.f.ingestor.session_id)
        previous_sid = self.sid
        experiment = self.f.experiment

        async def next_experiment(name="experiment"):
            return await experiment("next")

        with patch.object(self.f, "experiment", new=next_experiment):
            await self.workflow.running()
        self.sid = self.f.sid
        self.assertNotEqual(self.sid, previous_sid)
        self.local = self.node.local_storage_manager

        async def acknowledge_current_session():
            durable = self.workflow.durable
            subject = self.f.broker.consumers[durable].config.filter_subject
            for sequence, message in sorted(self.f.broker.records.items()):
                if self.f.broker.matches(subject, message.subject):
                    await self.f.broker.deliver(durable, sequence)

        self.enterContext(patch.object(self.workflow, "acknowledge", new=acknowledge_current_session))
        async with self.holding("synchronization_manager", "stop_runtime", interruptions=1):
            self.assertFalse((await self.execute(self.decision("experiment"))).succeeded)
            self.assertTrue((await self.execute(self.decision("next"))).succeeded)
        self.assertTrue(self.closeout_result.succeeded, self.closeout_result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.stops.call_count, 2)
        self.assertEqual(self.physical_stops.call_count, 2)
        self.assertEqual({path: Path(path).read_bytes() for path in before}, before)
        record = self.storage.get_session_preservation_confirmation(self.sid)["session_record"]
        self.assertEqual([e["experiment_id"] for e in record["experiment_lifecycle_evidence"]], ["next", "next"])

    async def test_permitted_kill_conversion_does_not_reopen_normal_closeout(self):
        await self.running(remote=True, preserve=True)
        async with self.holding("synchronization_manager", "stop_runtime"):
            await self.cancel_closeout()
        result = await self.controller.kill_session(communication=self.f.communication,
            storage_participant=self.workflow.storage_participant, result_window_s=.05, operator_authorized=True)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.controller.get_status()["session_state"], "aborted")
        before = self.workflow.archive()
        self.assertFalse((await self.workflow.stop()).succeeded)
        self.assertEqual(self.workflow.archive(), before)
        self.assertEqual(self.stops.call_count, 1)
        self.assertEqual(self.physical_stops.call_count, 1)
        self.assertEqual(self.finalize.call_count, 1)
        endings = [e.event_type for e in self.controller.get_status()["experiment_lifecycle_evidence"]
                   if e.event_type != "experiment_start"]
        self.assertEqual(endings, ["experiment_stop"])

    async def test_kill_association_does_not_admit_a_local_normal_stop(self):
        await self.running()
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Kill end timing unavailable")):
            killed = await self.controller.kill_session(communication=self.f.communication,
                result_window_s=.05, operator_authorized=True)
        self.assertFalse(killed.succeeded)
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        result = await self.workflow.stop()
        self.assertFalse(result.succeeded)
        self.assertIn("Kill closeout", result.error)
        self.assertEqual(self.stops.call_count, 0)
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")

    async def test_auxiliary_marker_publication_preserves_existing_closeout_contracts(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.running(remote=remote, preserve=remote)
                self.assertTrue((await self.controller.stop_launched_session()).succeeded)
                published = await self.controller.publish_acquisition_evidence_completion(
                    communication=self.f.communication, result_window_s=.05)
                self.assertTrue(published.succeeded, published.error)
                marker = published.details["marker"]
                result = await self.workflow.stop()
                self.assertEqual(result.succeeded, remote, result.error)
                self.assertEqual(self.controller.get_status()["session_state"], "completed" if remote else "stopping")
                if remote:
                    confirmation = self.storage.get_session_preservation_confirmation(self.sid)
                    self.assertEqual(confirmation["compilation_summary"]["acquisition_evidence_completion"]["evidence_id"],
                                     marker["evidence_id"])
                else:
                    self.assertIn("archive unavailable", result.error)
                self.assertEqual(self.stops.call_count, 1)
                self.assertEqual(self.finalize.call_count, 1)


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


class LocalFailureTimingTests(unittest.TestCase):
    def setUp(self):
        self.f = capacity.LocalActivationFailureTests()
        self.f.addCleanup = self.addCleanup
        ingestor = capacity.InMemoryIngestor

        def prepared_ingestor(storage):
            owner = ingestor(storage, recovery_journal_root=Path(self.f.temporary.name) / "journals")
            self.assertTrue(owner.prepare_session("session").ready)
            return owner

        with patch.object(capacity, "InMemoryIngestor", side_effect=prepared_ingestor):
            self.f.setUp()

    def fail_after_cleanup(self, operation, *, action_confirmed=False, timing_available=False):
        f = self.f
        self.assertTrue(f.start("failure").succeeded)
        self.assertTrue(f.controller.run_one_iteration().succeeded)
        stop = f.node.stop_runtime
        read_time = type(f.sync).current_session_time_s.fget
        stopped = False

        def read_after_cleanup():
            if stopped and not timing_available:
                raise OSError("Session Time unavailable after cleanup")
            return read_time(f.sync)

        def stop_then_lose_time():
            nonlocal stopped
            result = stop()
            stopped = True
            return result

        with patch.object(type(f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=read_after_cleanup), \
             patch.object(f.node, "stop_runtime", side_effect=stop_then_lose_time) as stops, \
             patch.object(f.adapter, "stop", wraps=f.adapter.stop) as physical_stops, \
             patch.object(f.local, "finalize_stream", wraps=f.local.finalize_stream) as finalize:
            result = operation()
            self.assertEqual(result.succeeded, action_confirmed, result.error)
            status = f.controller.get_status()
            self.assertEqual(status["session_state"], "failed")
            self.assertEqual(status["session_id"], "session")
            self.assertIsNone(status["active_experiment_id"])
            self.assertEqual(status["active_experiment_runtime_health_mapping"], ())
            events = status["experiment_lifecycle_evidence"]
            self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
            self.assertEqual(events[-1].experiment_id, "failure")
            if timing_available:
                self.assertIsNotNone(events[-1].session_time_s)
                self.assertNotIn("timing_unconfirmed", events[-1].details)
            else:
                self.assertIsNone(events[-1].session_time_s)
                self.assertTrue(events[-1].details["timing_unconfirmed"])
            self.assertFalse(f.node.status()["is_running"])
            self.assertTrue(f.node.status()["cleanup_confirmed"])
            self.assertIsNone(f.storage.get_acquisition_stage_preservation_confirmation("session"))
            self.assertFalse(f.controller.stop_session().succeeded)
            with patch.object(f.storage, "write_evidence_archive", side_effect=OSError("archive unavailable")):
                self.assertFalse(f.controller.finalize_session().succeeded)
            self.assertEqual(f.controller.get_status()["session_state"], "failed")
            preserved = f.controller.finalize_session()
            self.assertTrue(preserved.succeeded, preserved.error)
            self.assertEqual(f.controller.get_status()["session_state"], "failed")
            self.assertEqual(stops.call_count, 1)
            self.assertEqual(physical_stops.call_count, 1)
            self.assertEqual(finalize.call_count, 1)

        manifest, = f.local.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        with h5py.File(manifest.local_storage_path) as saved:
            np.testing.assert_array_equal(saved["frames"][0], f.frame)
        record = f.storage.read_session_record(preserved.details["session_record_path"])
        self.assertEqual(record["final_session_status"]["state"], "failed")
        self.assertEqual([e["event_type"] for e in record["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])
        return result, events[-1]

    def test_acquisition_failure_is_canonical_when_time_is_lost_after_cleanup(self):
        def fail_iteration():
            with patch.object(self.f.camera.capture, "read", return_value=(False, None)):
                return self.f.controller.run_one_iteration()

        result, event = self.fail_after_cleanup(fail_iteration)
        self.assertIn(result.error.split(": ", 1)[-1], event.details["reason"])

    def test_local_fatal_is_canonical_when_time_is_lost_after_cleanup(self):
        decision = ControllerActionDecision("fatal", "session", "failure", "source", "policy",
                                            "session_failure", "session_fail", None)
        _, event = self.fail_after_cleanup(
            lambda: self.f.controller.execute_controller_action_decision(decision), action_confirmed=True)
        self.assertEqual(event.details["reason"], "ControllerActionDecision requested Session failure")
        message, = self.f.controller.controller_action_decision_evidence
        self.assertEqual(message.payload, decision.to_dict())
        self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(message))

    def test_local_stop_failure_is_canonical_when_time_is_lost_after_cleanup(self):
        result, event = self.fail_after_cleanup(self.f.controller.stop_session)
        self.assertIn("Session Time unavailable after cleanup", result.error)
        self.assertEqual(event.details["reason"], "Session Time unavailable after cleanup")

    def test_failure_retains_available_session_time(self):
        def fail_iteration():
            with patch.object(self.f.node, "run_one_iteration", side_effect=OSError("collection failed")):
                return self.f.controller.run_one_iteration()

        result, event = self.fail_after_cleanup(fail_iteration, timing_available=True)
        self.assertIn("collection failed", result.error)
        self.assertEqual(event.details["reason"], "collection failed")

    def test_failure_without_active_experiment_does_not_require_session_time(self):
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Session Time unavailable")), \
             patch.object(self.f.node, "run_one_iteration", side_effect=OSError("collection failed")):
            result = self.f.controller.run_one_iteration()
        self.assertFalse(result.succeeded)
        self.assertIn("collection failed", result.error)
        status = self.f.controller.get_status()
        self.assertEqual(status["session_state"], "failed")
        self.assertIsNone(status["active_experiment_id"])
        self.assertEqual(status["experiment_lifecycle_evidence"], ())
        self.assertFalse(self.f.node.status()["is_running"])
        self.assertFalse(self.f.controller.stop_session().succeeded)

    def test_unconfirmed_cleanup_remains_separate_from_canonical_failure(self):
        self.assertTrue(self.f.start("failure").succeeded)
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Session Time unavailable")), \
             patch.object(self.f.node, "run_one_iteration", side_effect=OSError("collection failed")), \
             patch.object(self.f.local, "finalize_stream", side_effect=OSError("finalization unavailable")) as finalize:
            result = self.f.controller.run_one_iteration()
        self.assertFalse(result.succeeded)
        self.assertIn("collection failed", result.error)
        status = self.f.controller.get_status()
        self.assertEqual(status["session_state"], "failed")
        self.assertIsNone(status["active_experiment_id"])
        self.assertEqual(status["experiment_lifecycle_evidence"][-1].event_type, "experiment_fail")
        self.assertTrue(status["experiment_lifecycle_evidence"][-1].details["timing_unconfirmed"])
        self.assertFalse(self.f.node.status()["cleanup_confirmed"])
        self.assertEqual(finalize.call_count, 1)
        self.assertEqual(self.f.local.manifests[0].lifecycle_state, "open")
        self.assertTrue(Path(self.f.local.manifests[0].local_storage_path).exists())
        self.assertIsNone(self.f.storage.get_acquisition_stage_preservation_confirmation("session"))

    def test_canonical_evidence_failure_is_not_suppressed_as_a_timing_failure(self):
        self.assertTrue(self.f.start("failure").succeeded)
        decision = ControllerActionDecision("fatal", "session", "failure", "source", "policy",
                                            "session_failure", "session_fail", None)
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Session Time unavailable")), \
             patch("lab_sync_acquisition.session.Session.record_experiment_lifecycle",
                   side_effect=RuntimeError("canonical evidence unavailable")):
            result = self.f.controller.execute_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertIn("canonical evidence unavailable", result.error)
        self.assertEqual(self.f.controller.get_status()["active_experiment_id"], "failure")
        self.assertEqual([e.event_type for e in self.f.controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start"])

    def test_canonical_transition_failure_is_not_suppressed_as_a_timing_failure(self):
        self.assertTrue(self.f.start("failure").succeeded)
        decision = ControllerActionDecision("fatal", "session", "failure", "source", "policy",
                                            "session_failure", "session_fail", None)
        with patch.object(type(self.f.sync), "current_session_time_s", new_callable=PropertyMock,
                          side_effect=OSError("Session Time unavailable")), \
             patch("lab_sync_acquisition.session.Session.fail", side_effect=RuntimeError("transition unavailable")):
            result = self.f.controller.execute_controller_action_decision(decision)
        self.assertFalse(result.succeeded)
        self.assertIn("transition unavailable", result.error)
        self.assertEqual(self.f.controller.get_status()["session_state"], "stopping")
        self.assertIsNone(self.f.controller.get_status()["active_experiment_id"])
        self.assertEqual([e.event_type for e in self.f.controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])
