"""Public Session publication boundaries using real owners and controlled transport."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    AcquisitionNode, AcquisitionHealthPolicy, Controller, DurablePublicationError, ExperimentRuntimeHealthMapping,
    HealthInterpretationEvidence, NatsAcquisitionNodeCommunication,
    NatsCommunicationBoundary, NatsControllerCommunication, NatsIngestorCommunication,
    NatsSynchronizationManagerCommunication, RuntimeEvidenceMessage, RuntimeParticipant,
    ScientificOutputSelection, ServiceReadiness, ExperimentConfiguration,
)
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server
from tests import test_session_launch as launch_fixture
from tests.test_session_launch import _Boundary, _Broker


def interpretation(identity="observation"):
    return HealthInterpretationEvidence(identity, "experiment", "source", "participant",
        "frame_gap", "policy", "warning", True, 1.0, {})


class PublicationBroker(_Broker):
    def __init__(self):
        super().__init__()
        self.events = []
        self.before_publication = None
        self.after_publication = None

    async def publish(self, subject, data, stream):
        payload = json.loads(data)
        if self.before_publication is not None:
            await self.before_publication(subject, payload)
        if stream == "LAB_EVIDENCE":
            await EvidenceReceiptBroker.publish(self, subject, data, stream)
        self.events.append((subject, payload))
        acknowledgment = await super().publish(subject, data, stream)
        if self.after_publication is not None:
            await self.after_publication(subject, payload)
        return acknowledgment


class HealthNode(AcquisitionNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, acquisition_health_policies=(AcquisitionHealthPolicy(
            "frames", {"first_evidence": {"record_kind": "frame", "grace_window_s": 0}},
            {"first_evidence_missing": "warning"}),), **kwargs)


class ProducerPublicationCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = launch_fixture.SessionLaunchTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.addAsyncCleanup = self.addAsyncCleanup
        self.fixture.setUp()
        self.fixture.broker = PublicationBroker()
        self.fixture.controller = Controller(ingestor=self.fixture.ingestor,
                                             synchronization_manager=self.fixture.sync)
        self.fixture.communication = NatsControllerCommunication(
            _Boundary("controller", "controller", self.fixture.broker))

    async def running(self, *, optional=False, two=True, artifacts=True):
        f = self.fixture
        await f.services()
        selections = {}
        for name in ("node-a", "node-b") if two else ("node-a",):
            _, declaration, _ = await f.node(name)
            selections[name] = [replace(declaration, required=False) if optional else declaration]
        launched = await f.launch(selections)
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        if artifacts:
            for node_id, declarations in selections.items():
                result = await f.communication.request_command(RuntimeParticipant("acquisition_node", node_id),
                    "prepare_experiment_scientific_outputs", sid,
                    {"experiment_id": "experiment",
                     "configuration": ExperimentConfiguration(60, {node_id: 1000000}, 1000000).to_dict(),
                     "scientific_outputs": [
                        ScientificOutputSelection(declarations[0].device_id, node_id, "events").to_dict()]}, 1)
                self.assertTrue(result.success, result.reason)
        return sid

    async def marker(self):
        return await self.fixture.controller.publish_acquisition_evidence_completion(
            communication=self.fixture.communication, result_window_s=1)

    def published(self, kind):
        return [data for _, data in self.fixture.broker.events if data.get("evidence_type") == kind]

    async def test_multiple_producers_publish_before_responses_and_single_marker(self):
        sid = await self.running(optional=True)
        f = self.fixture
        f.controller.process_health_interpretation(interpretation())
        f.sync.create_and_activate_mapping(sid, "node-a", 0, 0, 1, "initial")
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        outcome = await self.marker()
        self.assertTrue(outcome.succeeded, outcome.error)
        events = f.broker.events
        marker_index = next(i for i, (_, data) in enumerate(events)
                            if data.get("evidence_type") == "acquisition_evidence_completion")
        for node in ("node-a", "node-b"):
            final_index = next(i for i, (_, data) in enumerate(events)
                if data.get("evidence_type") == "artifact_manifest" and data["source_id"] == node
                and data["payload"]["lifecycle_state"] == "finalized")
            response_index = next(i for i, (subject, data) in enumerate(events)
                if subject.endswith(".stop_runtime") and "command_result" in subject
                and data["source_id"] == node)
            self.assertLess(final_index, response_index)
            self.assertLess(response_index, marker_index)
        mapping = self.published("mapping_update_evidence")
        self.assertEqual([m["payload"]["update_type"] for m in mapping], ["created", "retired"])
        self.assertTrue(all(m["session_id"] == sid for m in mapping))
        self.assertEqual(len(self.published("controller_action_decision")), 1)
        self.assertEqual(f.controller._session.current_state.value, "stopping")
        self.assertTrue(f.sync.check_ready().ready)
        again = await self.marker()
        self.assertEqual(outcome.details["marker"], again.details["marker"])
        self.assertEqual(len(self.published("acquisition_evidence_completion")), 1)

    async def test_late_node_publication_prevents_response_and_marker(self):
        await self.running()
        entered, resume = asyncio.Event(), asyncio.Event()
        async def pause(subject, data):
            if data.get("evidence_type") == "artifact_manifest" and data["source_id"] == "node-b" and data["payload"]["lifecycle_state"] == "finalized":
                entered.set()
                await resume.wait()
        self.fixture.broker.before_publication = pause
        task = asyncio.create_task(self.fixture.controller.stop_launched_session())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertFalse((await self.marker()).succeeded)
            self.assertFalse(self.published("acquisition_evidence_completion"))
            self.assertFalse(any(subject.endswith(".stop_runtime") and "command_result" in subject
                and data["source_id"] == "node-b" for subject, data in self.fixture.broker.events))
        finally:
            resume.set()
            await task
        self.assertTrue((await self.marker()).succeeded)

    async def test_overlapping_inventory_cannot_skip_finalized_manifest(self):
        sid = await self.running(two=False, artifacts=False)
        f = self.fixture
        participant = RuntimeParticipant("acquisition_node", "node-a")
        initial_entered, initial_resume = asyncio.Event(), asyncio.Event()
        inventory_executed = asyncio.Event()
        final_entered, final_resume = asyncio.Event(), asyncio.Event()
        original_execute = NatsAcquisitionNodeCommunication.execute_command

        def observe_execute(handler, command):
            result = original_execute(handler, command)
            if command.command_type == "get_inventory":
                inventory_executed.set()
            return result

        async def pause(subject, data):
            if data.get("evidence_type") != "artifact_manifest":
                return
            if data["payload"]["lifecycle_state"] == "open" and not initial_entered.is_set():
                initial_entered.set()
                await initial_resume.wait()
            elif data["payload"]["lifecycle_state"] == "finalized":
                final_entered.set()
                await final_resume.wait()

        f.broker.before_publication = pause
        tasks = []
        try:
            with patch.object(NatsAcquisitionNodeCommunication, "execute_command", new=observe_execute):
                preparation = asyncio.create_task(f.communication.request_command(participant,
                    "prepare_experiment_scientific_outputs", sid,
                    {"experiment_id": "experiment", "scientific_outputs": [
                        ScientificOutputSelection("node-a-device", "node-a", "events").to_dict()]}, 3))
                tasks.append(preparation)
                await asyncio.wait_for(initial_entered.wait(), 2)
                inventory = asyncio.create_task(f.communication.request_command(
                    participant, "get_inventory", None, {}, 3))
                tasks.append(inventory)
                await asyncio.wait_for(inventory_executed.wait(), 2)
                initial_resume.set()
                self.assertTrue((await preparation).success)
                self.assertTrue((await inventory).success)
            stopped = asyncio.create_task(f.controller.stop_launched_session())
            tasks.append(stopped)
            await asyncio.wait_for(final_entered.wait(), 2)
            self.assertFalse((await self.marker()).succeeded)
            self.assertFalse(self.published("acquisition_evidence_completion"))
            self.assertFalse(any("command_result" in subject and subject.endswith(".stop_runtime")
                and data["source_id"] == "node-a" for subject, data in f.broker.events))
            final_resume.set()
            self.assertTrue((await stopped).succeeded)
            produced = [m.to_dict() for m in f.nodes["node-a"].artifact_manifest_evidence]
            self.assertEqual(self.published("artifact_manifest"), produced)
            self.assertTrue((await self.marker()).succeeded)
            events = f.broker.events
            final_index = next(i for i, (_, data) in enumerate(events) if data == produced[-1])
            response_index = next(i for i, (subject, data) in enumerate(events)
                if "command_result" in subject and subject.endswith(".stop_runtime")
                and data["source_id"] == "node-a")
            marker_index = next(i for i, (_, data) in enumerate(events)
                if data.get("evidence_type") == "acquisition_evidence_completion")
            self.assertLess(final_index, response_index)
            self.assertLess(response_index, marker_index)
        finally:
            initial_resume.set()
            final_resume.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_interrupted_manifest_publication_preserves_retry_and_unblocks_inventory(self):
        sid = await self.running(two=False, artifacts=False)
        f = self.fixture
        node = f.nodes["node-a"]
        participant = RuntimeParticipant("acquisition_node", "node-a")
        original_execute = NatsAcquisitionNodeCommunication.execute_command
        for mode in ("failure", "cancellation"):
            with self.subTest(mode=mode):
                entered, resume, inventory_executed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                tasks = []

                def observe_execute(handler, command):
                    result = original_execute(handler, command)
                    if command.command_type == "get_inventory":
                        inventory_executed.set()
                    return result

                async def pause(subject, data):
                    if data.get("evidence_type") == "artifact_manifest" and not entered.is_set():
                        entered.set()
                        await resume.wait()
                        if mode == "failure":
                            raise ConnectionError("initial manifest publication unavailable")

                payload = {"experiment_id": mode + "-experiment", "scientific_outputs": [
                    ScientificOutputSelection("node-a-device", "node-a", "events").to_dict()]}
                f.broker.before_publication = pause
                try:
                    with patch.object(NatsAcquisitionNodeCommunication, "execute_command", new=observe_execute):
                        preparation = asyncio.create_task(f.communication.request_command(participant,
                            "prepare_experiment_scientific_outputs", sid, payload, 3, command_id="prepare-" + mode))
                        tasks.append(preparation)
                        await asyncio.wait_for(entered.wait(), 2)
                        retained = node.artifact_manifest_evidence
                        inventory = asyncio.create_task(f.communication.request_command(
                            participant, "get_inventory", None, {}, 3))
                        tasks.append(inventory)
                        await asyncio.wait_for(inventory_executed.wait(), 2)
                        if mode == "failure":
                            resume.set()
                            with self.assertRaises(DurablePublicationError):
                                await preparation
                        else:
                            preparation.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await preparation
                        self.assertTrue((await asyncio.wait_for(inventory, 2)).success)
                    f.broker.before_publication = None
                    retry = await f.communication.request_command(participant,
                        "prepare_experiment_scientific_outputs", sid, payload, 3, command_id="prepare-" + mode)
                    self.assertTrue(retry.success, retry.reason)
                    self.assertEqual(node.artifact_manifest_evidence, retained)
                    self.assertEqual(self.published("artifact_manifest"), [m.to_dict() for m in retained])
                    self.assertEqual(node.reserved_for_session_id, sid)
                finally:
                    resume.set()
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertEqual(self.published("artifact_manifest"), [m.to_dict() for m in node.artifact_manifest_evidence])
        self.assertTrue((await self.marker()).succeeded)

    async def test_overlapping_health_publications_cannot_skip_later_evidence(self):
        f = self.fixture
        await f.services()
        node, declaration, _ = await f.node(node_class=HealthNode)
        for subscription in tuple(f.broker.subscriptions):
            if ".command.acquisition_node.node-a." in subscription.subject:
                await subscription.unsubscribe()
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", f.broker), node)
        await handler.subscribe_commands()
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        mapping = (ExperimentRuntimeHealthMapping(declaration.device_id, "node-a", "frames", True, "frames"),)
        node.activate_experiment_runtime_health_mapping("first-experiment", mapping)
        entered, resume, overlapping_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_publish = handler.publish_new_runtime_evidence

        async def observe_publish():
            if entered.is_set():
                overlapping_entered.set()
            await original_publish()

        async def pause(subject, data):
            if data.get("evidence_type") == "health_interpretation" and not entered.is_set():
                entered.set()
                await resume.wait()

        f.broker.before_publication = pause
        tasks = []
        try:
            with patch.object(handler, "publish_new_runtime_evidence", new=observe_publish):
                iteration = asyncio.create_task(f.communication.request_command(
                    RuntimeParticipant("acquisition_node", "node-a"), "run_one_iteration", sid, {}, 3))
                tasks.append(iteration)
                await asyncio.wait_for(entered.wait(), 2)
                publication = asyncio.create_task(handler.publish_new_runtime_evidence())
                tasks.append(publication)
                await asyncio.wait_for(overlapping_entered.wait(), 2)
                resume.set()
                self.assertTrue((await iteration).success)
                await publication
            node.clear_experiment_runtime_health_mapping()
            node.activate_experiment_runtime_health_mapping("second-experiment", mapping)
            result = await f.communication.request_command(RuntimeParticipant("acquisition_node", "node-a"),
                "run_one_iteration", sid, {}, 3)
            self.assertTrue(result.success, result.reason)
            self.assertEqual(len(node.health_runtime_evidence), 2)
            self.assertEqual(self.published("health_interpretation"),
                             [m.to_dict() for m in node.health_runtime_evidence])
            self.assertTrue((await f.controller.stop_launched_session()).succeeded)
            self.assertTrue((await self.marker()).succeeded)
        finally:
            resume.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_failed_node_publication_keeps_reservation_and_prevents_confirmation(self):
        await self.running(two=False)
        async def fail(subject, data):
            if data.get("evidence_type") == "artifact_manifest" and data["payload"]["lifecycle_state"] == "finalized":
                raise ConnectionError("publication acknowledgment unavailable")
        self.fixture.broker.before_publication = fail
        stopped = await self.fixture.controller.stop_launched_session()
        self.assertFalse(stopped.succeeded)
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))
        node = self.fixture.nodes["node-a"]
        self.assertIsNotNone(node.reserved_for_session_id)
        self.assertEqual(node.artifact_manifest_evidence[-1].payload["lifecycle_state"], "finalized")

    async def test_missing_response_prevents_marker_even_when_artifact_was_published(self):
        await self.running(two=False)
        self.fixture.broker.drop_results.add(("node-a", "stop_runtime"))
        self.assertFalse((await self.fixture.controller.stop_launched_session()).succeeded)
        self.assertTrue(self.published("artifact_manifest"))
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))

    async def test_missing_synchronization_response_prevents_marker(self):
        await self.running(two=False)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        self.fixture.broker.drop_results.add(("sync", "stop_runtime"))
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))

    async def test_ambiguous_synchronization_response_is_not_confirmation(self):
        await self.running(two=False)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        def ambiguous(operation, data):
            if operation == "stop_runtime" and data["source_id"] == "sync":
                return {**data, "status": "accepted"}
            return data
        self.fixture.broker.change_result = ambiguous
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))

    async def test_unselected_optional_node_creates_no_completion_obligation(self):
        f = self.fixture
        await f.services()
        _, declaration, _ = await f.node(unready=True)
        launched = await f.launch({"node-a": [replace(declaration, required=False)]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertNotIn(RuntimeParticipant("acquisition_node", "node-a"), f.controller.expected_runtime_participants)
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertFalse(self.published("artifact_manifest"))

    async def test_rejected_experiment_start_evidence_is_published_before_marker(self):
        await self.running(two=False)
        f = self.fixture
        rejected = f.controller.start_experiment("rejected", preparation_readiness=(
            ServiceReadiness("node-a", "acquisition_node", True, False, "required preparation failed"),))
        self.assertFalse(rejected.succeeded)
        original = rejected.details["rejection_evidence"]
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(self.published("experiment_start_rejected"), [original])

    async def test_rejection_survives_failed_local_intake_and_is_later_published(self):
        await self.running(two=False)
        f = self.fixture
        with patch.object(f.ingestor, "receive_runtime_evidence", side_effect=OSError("intake unavailable")):
            rejected = f.controller.start_experiment("rejected", preparation_readiness=(
                ServiceReadiness("node-a", "acquisition_node", True, False, "required preparation failed"),))
        self.assertFalse(rejected.succeeded)
        retained = RuntimeEvidenceMessage.from_dict(rejected.details["rejection_evidence"])
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(self.published("experiment_start_rejected"), [retained.to_dict()])
        self.assertTrue(f.ingestor.has_durable_runtime_evidence(retained))

    async def test_unaccepted_produced_marker_cannot_be_discarded_by_finalization_or_release(self):
        sid = await self.running(two=False)
        f = self.fixture
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        async def fail(subject, data):
            if data.get("evidence_type") == "acquisition_evidence_completion":
                raise ConnectionError("marker publication unavailable")
        f.broker.before_publication = fail
        self.assertFalse((await self.marker()).succeeded)
        retained = f.communication.unpublished_session_evidence(sid)
        self.assertEqual(len(retained), 1)
        final = f.controller.finalize_session()
        self.assertFalse(final.succeeded)
        self.assertIn("Controller-owned evidence is missing", final.error)
        self.assertFalse((await f.controller.release_session()).succeeded)
        self.assertEqual(f.controller.get_status()["session_id"], sid)
        self.assertEqual(f.communication.unpublished_session_evidence(sid), retained)

    async def test_caller_managed_controller_publication_is_retained_and_session_scoped(self):
        sid = await self.running(two=False)
        f = self.fixture
        message = RuntimeEvidenceMessage("external-rejection", sid, "experiment_start_rejected",
            "controller", {"experiment_id": "experiment", "reason": "required preparation failed"}, True)
        other = replace(message, evidence_id="other-rejection", session_id="other")
        async def fail(subject, data):
            if data.get("evidence_type") == "experiment_start_rejected":
                raise ConnectionError("publication unavailable")
        f.broker.before_publication = fail
        for pending in (message, other):
            with self.assertRaises(DurablePublicationError):
                await f.communication.publish_evidence(pending)
        self.assertEqual(f.communication.unpublished_session_evidence(sid), (message,))
        f.broker.before_publication = None
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(self.published("experiment_start_rejected"), [message.to_dict()])
        self.assertEqual(f.communication.unpublished_session_evidence("other"), (other,))

    async def test_caller_managed_node_publication_finishes_before_stop_response(self):
        sid = await self.running(two=False)
        f = self.fixture
        for subscription in tuple(f.broker.subscriptions):
            if ".command.acquisition_node.node-a." in subscription.subject:
                await subscription.unsubscribe()
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", f.broker), f.nodes["node-a"])
        await handler.subscribe_commands()
        message = RuntimeEvidenceMessage("external-health", sid, "health_interpretation", "node-a",
                                        interpretation().to_dict(), True)
        async def fail(subject, data):
            if data.get("evidence_id") == message.evidence_id:
                raise ConnectionError("publication unavailable")
        f.broker.before_publication = fail
        with self.assertRaises(DurablePublicationError):
            await handler.publish_evidence(message)
        f.broker.before_publication = None
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertIn(message.to_dict(), self.published("health_interpretation"))
        self.assertTrue((await self.marker()).succeeded)

    async def test_timing_publication_does_not_retire_or_publish_another_session(self):
        sid = await self.running(two=False)
        f = self.fixture
        other = f.sync.create_and_activate_mapping("other", "node-other", 3, 4, 1, "other scope")
        f.sync.create_and_activate_mapping(sid, "node-a", 0, 0, 1, "this scope")
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(f.sync.get_active_mapping("other", "node-other"), other)
        self.assertTrue(all(m["session_id"] == sid for m in self.published("mapping_update_evidence")))

    async def test_failed_timing_publication_retains_messages_for_explicit_retry(self):
        sid = await self.running(two=False)
        f = self.fixture
        f.sync.create_and_activate_mapping(sid, "node-a", 0, 0, 1, "initial")
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        async def fail(subject, data):
            if data.get("evidence_type") == "mapping_update_evidence":
                raise ConnectionError("timing publication failed")
        f.broker.before_publication = fail
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))
        self.assertEqual(len(f.sync.mapping_update_evidence), 2)
        f.broker.before_publication = None
        self.assertTrue((await self.marker()).succeeded)
        with self.assertRaises(RuntimeError):
            f.sync.create_and_activate_mapping(sid, "node-a", 0, 0, 1, "late")
        f.sync.create_and_activate_mapping("unrelated", "node-c", 0, 0, 1, "other scope")

    async def test_controller_failure_retains_decision_and_stable_retry_boundary(self):
        await self.running(two=False)
        f = self.fixture
        f.controller.process_health_interpretation(interpretation())
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        async def fail(subject, data):
            if data.get("evidence_type") == "controller_action_decision":
                raise ConnectionError("decision publication failed")
        f.broker.before_publication = fail
        self.assertFalse((await self.marker()).succeeded)
        retained = f.controller.controller_action_decision_evidence
        self.assertEqual(len(retained), 1)
        self.assertFalse(self.published("acquisition_evidence_completion"))
        f.broker.before_publication = None
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(self.published("controller_action_decision")[0], retained[0].to_dict())
        with self.assertRaises(RuntimeError):
            f.controller.process_health_interpretation(interpretation("late"))

    async def test_marker_acknowledgment_interruption_reuses_identical_message(self):
        await self.running(two=False)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        async def fail_after_store(subject, data):
            if data.get("evidence_type") == "acquisition_evidence_completion":
                raise ConnectionError("lost marker acknowledgment")
        self.fixture.broker.after_publication = fail_after_store
        self.assertFalse((await self.marker()).succeeded)
        first = self.published("acquisition_evidence_completion")[0]
        self.fixture.broker.after_publication = None
        result = await self.marker()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["marker"], first)
        self.assertEqual(self.published("acquisition_evidence_completion"), [first, first])

    async def test_cancellation_and_overlapping_marker_requests_preserve_boundary(self):
        await self.running(two=False)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def pause(subject, data):
            if data.get("evidence_type") == "acquisition_evidence_completion":
                entered.set()
                await resume.wait()
        self.fixture.broker.before_publication = pause
        task = asyncio.create_task(self.marker())
        await asyncio.wait_for(entered.wait(), 2)
        self.assertFalse((await self.marker()).succeeded)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.fixture.broker.before_publication = None
        self.assertTrue((await self.marker()).succeeded)
        self.assertEqual(len(self.published("acquisition_evidence_completion")), 1)

    async def test_local_recovery_evidence_is_not_republished(self):
        sid = await self.running(two=False)
        local = RuntimeEvidenceMessage("local-recovery", sid, "ingestor_recovery_evidence", "ingestor", {}, True)
        self.fixture.ingestor.receive_runtime_evidence(local)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)
        self.assertFalse(self.published("ingestor_recovery_evidence"))
        self.assertIn(local, self.fixture.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"])

    async def test_delayed_controller_health_callback_blocks_marker_until_finished(self):
        sid = await self.running(two=False)
        f = self.fixture
        entered, resume = asyncio.Event(), asyncio.Event()
        async def pause(decision):
            entered.set()
            await resume.wait()
        await f.communication.subscribe_health_interpretation_evidence(sid, f.controller, pause)
        health = RuntimeEvidenceMessage("health", sid, "health_interpretation", "node-a", interpretation().to_dict(), True)
        task = asyncio.create_task(_Boundary("acquisition_node", "node-a", f.broker).publish_evidence(health))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertTrue((await f.controller.stop_launched_session()).succeeded)
            self.assertFalse((await self.marker()).succeeded)
            self.assertFalse(self.published("acquisition_evidence_completion"))
        finally:
            resume.set()
            await task
        self.assertTrue((await self.marker()).succeeded)
        await _Boundary("acquisition_node", "node-a", f.broker).publish_evidence(health)
        self.assertEqual(len(f.controller.controller_action_decisions), 1)

    async def test_controller_unconsumed_published_health_cannot_be_omitted(self):
        sid = await self.running(two=False)
        f = self.fixture
        health = RuntimeEvidenceMessage("health", sid, "health_interpretation", "node-a", interpretation().to_dict(), True)
        await _Boundary("acquisition_node", "node-a", f.broker).publish_evidence(health)
        await f.communication.subscribe_health_interpretation_evidence(sid, f.controller)
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertFalse((await self.marker()).succeeded)
        self.assertFalse(self.published("acquisition_evidence_completion"))

    async def test_produced_health_keeps_session_identity_after_interrupted_publication_and_reuse(self):
        f = self.fixture
        await f.services()
        node, declaration, _ = await f.node(node_class=HealthNode)
        launched = await f.launch({"node-a": [declaration]})
        sid = launched.details["session_id"]
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        node.activate_experiment_runtime_health_mapping("experiment", (
            ExperimentRuntimeHealthMapping(declaration.device_id, "participant", "frames", True, "frames"),))
        async def fail(subject, data):
            if data.get("evidence_type") == "health_interpretation":
                raise ConnectionError("health publication unavailable")
        f.broker.before_publication = fail
        with self.assertRaises(DurablePublicationError):
            await f.communication.request_command(RuntimeParticipant("acquisition_node", "node-a"),
                "run_one_iteration", sid, {}, 1)
        retained = node.health_runtime_evidence
        self.assertTrue(retained)
        node.stop_runtime()
        self.assertTrue(node.release_reservation(sid))
        self.assertTrue(node.reserve("next-session"))
        self.assertTrue(node.initialize_session("next-session", (declaration,), {}).ready)
        f.broker.before_publication = None
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", f.broker), node)
        await handler.publish_new_runtime_evidence()
        self.assertEqual(self.published("health_interpretation"), [m.to_dict() for m in retained])
        self.assertTrue(all(m.session_id == sid for m in retained))
        self.assertTrue(node.abort_session_initialization("next-session"))
        self.assertTrue(node.release_reservation("next-session"))

    async def test_two_nodes_health_publication_has_distinct_retained_identities(self):
        f = self.fixture
        await f.services()
        selections = {}
        for node_id in ("node-a", "node-b"):
            _, declaration, _ = await f.node(node_id, node_class=HealthNode)
            selections[node_id] = [declaration]
        launched = await f.launch(selections)
        sid = launched.details["session_id"]
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        for node_id, declarations in selections.items():
            f.nodes[node_id].activate_experiment_runtime_health_mapping("experiment", (
                ExperimentRuntimeHealthMapping(declarations[0].device_id, node_id, "frames", True, "frames"),))
            result = await f.communication.request_command(RuntimeParticipant("acquisition_node", node_id),
                "run_one_iteration", sid, {}, 1)
            self.assertTrue(result.success, result.reason)
        messages = self.published("health_interpretation")
        self.assertEqual(len(messages), 2)
        self.assertEqual(len({message["evidence_id"] for message in messages}), 2)
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.marker()).succeeded)


@unittest.skipUnless(NATS_SERVER, "local nats-server is optional")
class RealProducerPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_server_publication_order_and_w041_receipt(self):
        f = launch_fixture.SessionLaunchTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        async with temporary_jetstream_server() as url:
            boundaries = []
            async def boundary(kind, identity):
                instance = NatsCommunicationBoundary(kind, identity, (url,))
                await instance.connect()
                boundaries.append(instance)
                return instance
            try:
                controller_boundary = await boundary("controller", "controller")
                await controller_boundary.ensure_streams()
                f.communication = NatsControllerCommunication(controller_boundary)
                f.controller = Controller(ingestor=f.ingestor, synchronization_manager=f.sync)
                sync_boundary = await boundary("synchronization_manager", "sync")
                await NatsSynchronizationManagerCommunication(sync_boundary, f.sync).subscribe_commands()
                intake_boundary = await boundary("ingestor", "ingestor")
                intake = NatsIngestorCommunication(intake_boundary, f.ingestor)
                acknowledged = asyncio.Event()
                original = intake_boundary._require_jetstream().subscribe
                async def subscribe(topic, cb, **options):
                    async def receive(message):
                        await cb(message)
                        if json.loads(message.data).get("evidence_type") == "acquisition_evidence_completion":
                            acknowledged.set()
                    return await original(topic, cb=receive, **options)
                with patch.object(intake_boundary._require_jetstream(), "subscribe", side_effect=subscribe):
                    await intake.subscribe_commands()
                    selections = {}
                    node_boundaries = {}
                    for node_id in ("node-a", "node-b"):
                        node, declaration, _ = await f.node(node_id, node_class=HealthNode)
                        selections[node_id] = [declaration]
                        node_boundary = await boundary("acquisition_node", node_id)
                        node_boundaries[node_id] = node_boundary
                        await NatsAcquisitionNodeCommunication(node_boundary, node).subscribe_commands()
                    launched = await f.controller.launch_session(selections, communication=f.communication,
                        participants=f.participants, config_parameters=f.config, result_window_s=3)
                    self.assertTrue(launched.succeeded, launched.error)
                    sid = launched.details["session_id"]
                    self.assertTrue((await f.controller.start_launched_session()).succeeded)
                    health_processed = asyncio.Event()
                    async def observed(decision):
                        if len(f.controller.controller_action_decisions) == 2:
                            health_processed.set()
                    await f.communication.subscribe_health_interpretation_evidence(sid, f.controller, observed)
                    for node_id, declarations in selections.items():
                        participant = RuntimeParticipant("acquisition_node", node_id)
                        payload = {"experiment_id": "experiment", "scientific_outputs": [
                            ScientificOutputSelection(declarations[0].device_id, node_id, "events").to_dict()]}
                        if node_id == "node-a":
                            entered, resume, inventory_executed = asyncio.Event(), asyncio.Event(), asyncio.Event()
                            original_publish = node_boundaries[node_id].publish_evidence
                            original_execute = NatsAcquisitionNodeCommunication.execute_command

                            async def pause(message):
                                if message.evidence_type == "artifact_manifest" and not entered.is_set():
                                    entered.set()
                                    await resume.wait()
                                await original_publish(message)

                            def observe_execute(handler, command):
                                result = original_execute(handler, command)
                                if command.command_type == "get_inventory":
                                    inventory_executed.set()
                                return result

                            tasks = []
                            try:
                                with patch.object(node_boundaries[node_id], "publish_evidence", new=pause), \
                                        patch.object(NatsAcquisitionNodeCommunication, "execute_command", new=observe_execute):
                                    preparation = asyncio.create_task(f.communication.request_command(
                                        participant, "prepare_experiment_scientific_outputs", sid, payload, 3))
                                    tasks.append(preparation)
                                    await asyncio.wait_for(entered.wait(), 2)
                                    inventory = asyncio.create_task(f.communication.request_command(
                                        participant, "get_inventory", None, {}, 3))
                                    tasks.append(inventory)
                                    await asyncio.wait_for(inventory_executed.wait(), 2)
                                    resume.set()
                                    result = await preparation
                                    self.assertTrue((await inventory).success)
                            finally:
                                resume.set()
                                for task in tasks:
                                    if not task.done():
                                        task.cancel()
                                await asyncio.gather(*tasks, return_exceptions=True)
                        else:
                            result = await f.communication.request_command(participant,
                                "prepare_experiment_scientific_outputs", sid, payload, 3)
                        self.assertTrue(result.success, result.reason)
                        f.nodes[node_id].activate_experiment_runtime_health_mapping("experiment", (
                            ExperimentRuntimeHealthMapping(declarations[0].device_id, node_id, "frames", True, "frames"),))
                        iteration = await f.communication.request_command(RuntimeParticipant("acquisition_node", node_id),
                            "run_one_iteration", sid, {}, 3)
                        self.assertTrue(iteration.success, iteration.reason)
                    await asyncio.wait_for(health_processed.wait(), 5)
                    self.assertTrue((await f.controller.stop_launched_session()).succeeded)
                    outcome = await f.controller.publish_acquisition_evidence_completion(
                        communication=f.communication, result_window_s=3)
                    self.assertTrue(outcome.succeeded, outcome.error)
                    marker = RuntimeEvidenceMessage.from_dict(outcome.details["marker"])
                    await asyncio.wait_for(acknowledged.wait(), 5)
                    proof = await intake.verify_acquisition_evidence_receipt(marker)
                    self.assertTrue(proof["durable_receipt_confirmed"], proof)
                    self.assertEqual(f.controller._session.current_state.value, "stopping")
                    accepted = f.ingestor.accepted_runtime_evidence
                    self.assertEqual(len([m for m in accepted if m.evidence_type == "artifact_manifest"]), 4)
                    for node in f.nodes.values():
                        for manifest_message in node.artifact_manifest_evidence:
                            self.assertIn(manifest_message, accepted)
                    self.assertEqual(len([m for m in accepted if m.evidence_type == "health_interpretation"]), 2)
                    self.assertEqual(len([m for m in accepted if m.evidence_type == "controller_action_decision"]), 2)
            finally:
                for instance in reversed(boundaries):
                    await instance.close()
