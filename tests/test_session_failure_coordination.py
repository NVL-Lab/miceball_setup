"""Session failure shares cleanup ownership and positively confirms health accounting."""

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import ControllerCommandResult, RuntimeEvidenceMessage
from tests import test_local_closeout_ownership as ownership_fixtures
from tests.test_producer_publication_completion import interpretation


class SessionFailureCoordinationTests(unittest.IsolatedAsyncioTestCase):
    async def workflow(self, *, remote=False, active=False):
        fixture = ownership_fixtures.ExperimentCloseoutAdmissionTests()
        fixture.addCleanup = self.addCleanup
        fixture.addAsyncCleanup = self.addAsyncCleanup
        return fixture, await fixture.workflow(remote=remote, active=active)

    def health(self, case, identity="fatal", experiment="next"):
        payload = replace(interpretation(identity), experiment_id=experiment,
                          interpretation_label="session_failure")
        return RuntimeEvidenceMessage(identity, case.sid, "health_interpretation",
                                      case.node.node_id, payload.to_dict(), True)

    async def deliver(self, case, message):
        subject = f"messages.{case.sid}.evidence.acquisition_node.{case.node.node_id}.health_interpretation"
        return await case.f.broker.publish(subject, json.dumps(message.to_dict()).encode(), "LAB_EVIDENCE")

    async def handover(self, *, remote, ending=False, before_start=False):
        fixture, case = await self.workflow(remote=remote, active=ending)
        controller = case.controller
        entered, resume = asyncio.Event(), asyncio.Event()
        handover_ready = asyncio.Event()
        request = case.f.communication.request_runtime_command
        operation = "read_session_time" if ending or before_start else "activate_experiment_runtime"
        release = controller._experiment_operation_lock.release

        def release_to_waiters():
            # Make closeout runnable at lock release, before the queued fatal
            # waiter resumes, without changing either admission implementation.
            handover_ready.set()
            release()

        async def paused(participant, command_type, *args, **kwargs):
            result = await request(participant, command_type, *args, **kwargs)
            if command_type == operation:
                entered.set()
                await resume.wait()
            return result

        async def close():
            await (handover_ready if before_start else resume).wait()
            return await case.workflow.stop()

        tasks = []
        with patch.object(case.f.communication, "request_runtime_command", new=paused), \
                patch.object(controller._experiment_operation_lock, "release", new=release_to_waiters):
            try:
                transition = asyncio.create_task(controller.stop_launched_experiment("next")
                    if ending else fixture.start(case))
                tasks.append(transition)
                await asyncio.wait_for(entered.wait(), 2)
                incoming = self.health(case, experiment=None if before_start else "next")
                delivery = asyncio.create_task(self.deliver(case, incoming))
                tasks.append(delivery)
                for _ in range(20):
                    if controller.controller_action_decision_evidence:
                        break
                    await asyncio.sleep(0)
                self.assertTrue(controller.controller_action_decision_evidence)
                self.assertFalse(delivery.done())
                closing = asyncio.create_task(close())
                tasks.append(closing)
                await asyncio.sleep(0)
                resume.set()
                transition_result = await transition
                await delivery
                result = await closing
            finally:
                resume.set()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertTrue(transition_result.succeeded, transition_result.error)
        self.assertFalse(result.succeeded)
        decision, = controller.controller_action_decision_evidence
        self.assertTrue(case.f.ingestor.has_durable_runtime_evidence(decision))
        states = case.f.communication._health_receivers[case.sid]
        self.assertTrue(all(incoming.evidence_id in state["processed"] for state in states))
        await self.deliver(case, incoming)
        self.assertEqual(controller.controller_action_decision_evidence, (decision,))
        self.assertEqual(case.stops.call_count, 1)
        self.assertEqual(case.physical_stops.call_count, 1)
        fixture.assert_finalized_once(case)
        self.assertIsNone(case.storage.get_acquisition_stage_preservation_confirmation(case.sid))
        self.assertIs(controller._acquisition_marker_session, controller._session)
        events = [event.event_type for event in controller.get_status()["experiment_lifecycle_evidence"]
                  if event.experiment_id == "next"]
        self.assertEqual(events, ["experiment_start", "experiment_stop"])

    async def preserve_normal(self, case):
        writer = case.storage.write_artifact_collection_handoff

        def existing(session_id, contents):
            path = case.storage._artifact_collection_handoff_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(contents, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
            return writer(session_id, contents)

        with patch.object(case.storage, "write_acquisition_stage",
                          new=type(case.storage).write_acquisition_stage.__get__(case.storage)), \
                patch.object(case.storage, "write_artifact_collection_handoff", side_effect=existing):
            preserved = await case.workflow.stop()
        self.assertTrue(preserved.succeeded, preserved.error)
        self.assertEqual(case.controller.get_status()["session_state"], "completed")
        self.assertEqual(case.stops.call_count, 1)
        self.assertIsNotNone(case.storage.get_acquisition_stage_preservation_confirmation(case.sid))

    async def test_fatal_at_start_lock_handover_cannot_lose_its_consequence(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.handover(remote=remote)

    async def test_fatal_at_termination_handover_retains_original_context(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.handover(remote=remote, ending=True)

    async def test_fatal_waiting_before_canonical_start_rechecks_new_normal_stop_owner(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                await self.handover(remote=remote, before_start=True)

    async def test_receiver_requires_affirmative_fatal_accounting_proof(self):
        for details in ({}, {"health_processing_confirmed": True},
                        {"health_processing_confirmed": True, "durable_acceptance_confirmed": True,
                         "session_state": "failed"}):
            with self.subTest(details=details):
                _, case = await self.workflow(active=True)
                callback = AsyncMock(return_value=ControllerCommandResult("action", True, details))
                subscription = await case.f.communication.subscribe_health_interpretation_evidence(
                    case.sid, case.controller, callback)
                incoming = self.health(case)
                message = SimpleNamespace(
                    subject=f"messages.{case.sid}.evidence.acquisition_node.{case.node.node_id}.health_interpretation",
                    data=json.dumps(incoming.to_dict()).encode(), ack=AsyncMock())
                with self.assertRaises(RuntimeError):
                    await subscription.callback(message)
                message.ack.assert_not_awaited()
                self.assertEqual(case.controller.get_status()["session_state"], "running")

    async def test_unrelated_local_fatal_context_cannot_stop_the_active_experiment(self):
        _, case = await self.workflow(active=True)
        with self.assertRaises(RuntimeError):
            case.controller.process_health_interpretation(replace(
                interpretation("unrelated-fatal"), experiment_id="unrelated",
                interpretation_label="session_failure"))
        result = case.controller.execute_controller_action_decision(case.decision("unrelated"))
        self.assertFalse(result.succeeded)
        self.assertEqual(case.stops.call_count, 0)
        self.assertEqual(case.physical_stops.call_count, 0)
        self.assertTrue(case.node.status()["is_running"])
        self.assertEqual(case.controller.get_status()["session_state"], "running")
        self.assertEqual(case.controller.get_status()["active_experiment_id"], "next")

    async def test_standalone_fatal_keeps_bindings_and_does_not_archive_or_release(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                fixture, case = await self.workflow(remote=remote, active=True)
                incoming = self.health(case)
                await self.deliver(case, incoming)
                self.assertEqual(case.controller.get_status()["session_state"], "failed")
                self.assertEqual(case.node.reserved_for_session_id, case.sid)
                self.assertEqual(case.f.ingestor.session_id, case.sid)
                self.assertIsNone(case.storage.get_acquisition_stage_preservation_confirmation(case.sid))
                self.assertFalse(any(command["command_type"] == "release_reservation"
                                     for command in case.f.broker.commands))
                self.assertEqual(case.stops.call_count, 1)
                fixture.assert_finalized_once(case)
                await self.deliver(case, incoming)
                self.assertEqual(case.stops.call_count, 1)
                self.assertFalse((await case.workflow.stop()).succeeded)
                self.assertEqual(case.controller.get_status()["session_state"], "failed")

    async def test_missing_acceptance_prevents_ack_and_redelivery_reuses_cleanup(self):
        fixture, case = await self.workflow(remote=True, active=True)
        incoming = self.health(case)
        case.f.broker.drop_results.add(("ingestor", "read_runtime_evidence_acceptance"))
        try:
            with self.assertRaises(RuntimeError):
                await self.deliver(case, incoming)
        finally:
            case.f.broker.drop_results.clear()
        self.assertEqual(case.controller.get_status()["session_state"], "failed")
        self.assertTrue(all(incoming.evidence_id not in state["processed"]
                            for state in case.f.communication._health_receivers[case.sid]))
        await self.deliver(case, incoming)
        self.assertEqual(case.stops.call_count, 1)
        self.assertEqual(case.physical_stops.call_count, 1)
        fixture.assert_finalized_once(case)

    async def test_cancelled_queued_fatal_cannot_be_acknowledged_or_allow_completion(self):
        fixture, case = await self.workflow(remote=True)
        incoming = self.health(case, experiment=None)
        async with fixture.paused(case, "prepare_experiment_scientific_outputs", after=True) as (entered, resume):
            starting = asyncio.create_task(fixture.start(case))
            delivery = None
            try:
                await asyncio.wait_for(entered.wait(), 2)
                delivery = asyncio.create_task(self.deliver(case, incoming))
                await asyncio.sleep(0)
                delivery.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await delivery
            finally:
                resume.set()
                await starting
                if delivery is not None:
                    await asyncio.gather(delivery, return_exceptions=True)
        self.assertTrue(all(incoming.evidence_id not in state["processed"]
                            for state in case.f.communication._health_receivers[case.sid]))
        async with case.holding("acquisition_node", "stop_runtime"):
            await self.deliver(case, incoming)
        self.assertEqual(case.controller.get_status()["session_state"], "stopping")
        self.assertEqual(case.stops.call_count, 1)

    async def test_normal_stop_owner_preserves_fatal_evidence_and_completes_after_retry(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                fixture, case = await self.workflow(remote=remote, active=True)
                async with case.holding("acquisition_node", "stop_runtime"):
                    await self.deliver(case, self.health(case))
                    self.assertEqual(case.stops.call_count, 0)
                    self.assertEqual(case.controller.get_status()["session_state"], "running")
                    await case.cancel_closeout()
                unpreserved = await case.workflow.stop()
                self.assertFalse(unpreserved.succeeded)
                self.assertIn("archive unavailable", unpreserved.error)
                await self.preserve_normal(case)
                self.assertEqual(case.stops.call_count, 1)
                self.assertEqual(case.physical_stops.call_count, 1)
                fixture.assert_finalized_once(case)

    async def test_partial_cleanup_is_distinct_from_confirmed_fatal_processing(self):
        fixture, case = await self.workflow(remote=True, active=True)
        case.f.broker.drop_results.add((case.node.node_id, "stop_runtime"))
        try:
            await self.deliver(case, self.health(case))
        finally:
            case.f.broker.drop_results.clear()
        result = case.controller.get_status()["last_command"]
        self.assertFalse(result.succeeded)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertFalse(result.details["preservation_confirmed"])
        self.assertEqual(case.node.reserved_for_session_id, case.sid)
        decision, = case.controller.controller_action_decisions
        retried = await case.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(retried.succeeded, retried.error)
        self.assertEqual(case.stops.call_count, 1)
        fixture.assert_finalized_once(case)

    async def test_stalled_cleanup_retains_obligations_and_allows_explicit_retry(self):
        fixture, case = await self.workflow(remote=True, active=True)
        request = case.f.communication.request_runtime_command

        async def stalled(participant, operation, *args, **kwargs):
            if participant == case.controller._reserved_participants[0] and operation == "stop_runtime":
                await asyncio.Event().wait()
            return await request(participant, operation, *args, **kwargs)

        with patch.object(case.f.communication, "request_runtime_command", new=stalled):
            await asyncio.wait_for(self.deliver(case, self.health(case)), 3)
        result = case.controller.get_status()["last_command"]
        self.assertFalse(result.succeeded)
        self.assertTrue(result.details["health_processing_confirmed"])
        self.assertFalse(result.details["cleanup_confirmed"])
        self.assertTrue(case.node.status()["is_running"])
        self.assertEqual(case.node.reserved_for_session_id, case.sid)
        self.assertIsNone(case.storage.get_acquisition_stage_preservation_confirmation(case.sid))
        decision, = case.controller.controller_action_decisions
        retried = await case.controller.execute_launched_controller_action_decision(decision)
        self.assertTrue(retried.succeeded, retried.error)
        self.assertEqual(case.physical_stops.call_count, 1)
        fixture.assert_finalized_once(case)

    async def test_pending_duplicate_is_not_acknowledged_before_accounting(self):
        fixture, case = await self.workflow(remote=True, active=True)
        entered, resume = asyncio.Event(), asyncio.Event()
        request = case.f.communication.request_persistence_command

        async def paused(participant, operation, *args, **kwargs):
            if operation == "read_runtime_evidence_acceptance":
                entered.set()
                await resume.wait()
            return await request(participant, operation, *args, **kwargs)

        incoming = self.health(case)
        with patch.object(case.f.communication, "request_persistence_command", new=paused):
            delivery = asyncio.create_task(self.deliver(case, incoming))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with self.assertRaisesRegex(RuntimeError, "in progress"):
                    await self.deliver(case, incoming)
                self.assertTrue(all(incoming.evidence_id not in state["processed"]
                    for state in case.f.communication._health_receivers[case.sid]))
            finally:
                resume.set()
                await delivery
        await self.deliver(case, incoming)
        self.assertEqual(case.stops.call_count, 1)

