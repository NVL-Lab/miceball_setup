"""A replacement Controller observes real retained nodes without taking ownership."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, InMemoryIngestor, NatsControllerCommunication, NatsIngestorCommunication,
    NatsServiceMaintenanceCommunication, NatsSynchronizationManagerCommunication,
    PersistentStorageManager, RuntimeCommandMessage, RuntimeParticipant,
    ScientificOutputSelection, ServiceMaintenanceInterface, ServiceReadiness, SynchronizationManager,
)
from tests import test_session_launch as launch_fixtures


class ControllerStartupReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original = launch_fixtures.SessionLaunchTests("runTest")
        self.original.setUp()
        self.addCleanup(self.original.temporary.cleanup)
        self.root = self.original.root
        self.broker = self.original.broker
        self.storage = PersistentStorageManager(self.root / "global/records.jsonl")
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework.jsonl")
        intake = NatsIngestorCommunication(
            launch_fixtures._Boundary("ingestor", "framework-intake", self.broker), self.ingestor)
        self.addAsyncCleanup((await intake.subscribe_evidence(None)).unsubscribe)
        self.controller = Controller(ingestor=self.ingestor, storage_manager=self.storage,
                                     component_id="replacement")
        self.interface = ServiceMaintenanceInterface(self.controller,
            RuntimeParticipant("controller", "replacement"), ingestor=self.ingestor,
            storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))

    def startup(self, participants):
        communication = NatsServiceMaintenanceCommunication(
            launch_fixtures._Boundary("controller", "replacement", self.broker), self.interface,
            startup_participants=participants, startup_result_window_s=0.05)
        self.addAsyncCleanup(communication.close)
        return communication

    async def recording_node(self):
        await self.original.services()
        node, declaration, adapter = await self.original.node()
        launched = await self.original.launch({"node-a": (declaration,)})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.original.controller.start_launched_session()).succeeded)
        self.addAsyncCleanup(self.original.controller.stop_launched_session)
        return node, declaration, adapter, launched.details["session_id"]

    async def test_startup_observes_retained_recording_without_restoring_or_stopping_session(self):
        node, _, adapter, session_id = await self.recording_node()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        before = node.status()
        device_before = adapter.get_status()
        old_status = self.original.controller.get_status()
        command_count = len(self.broker.commands)
        status = await self.startup((participant,)).start()
        report = status["reconciliation"]
        observed, = report["findings"]["participant_states"]
        self.assertEqual(observed["observed_state"], "active")
        self.assertEqual(observed["reported_session_ids"], [session_id])
        self.assertEqual(node.status(), before)
        self.assertEqual(adapter.get_status(), device_before)
        self.assertEqual(self.original.controller.get_status(), old_status)
        self.assertIsNone(self.controller.get_status()["session_id"])
        self.assertEqual([c["command_type"] for c in self.broker.commands[command_count:]], ["check_readiness"])
        self.assertTrue(report["acceptance_confirmed"])
        self.assertTrue(report["archival_confirmed"])
        self.assertIn(report["evidence"], self.storage.get_framework_preservation_confirmation()["runtime_evidence"])
        json.dumps(report, allow_nan=False)
        summary = node.run_one_iteration()
        self.assertEqual(summary.iteration_index, 1)
        self.assertTrue(node.status()["is_running"])
        self.assertEqual(node.reserved_for_session_id, session_id)

    async def test_stopped_node_reservation_survives_unconfirmed_cleanup_and_readback(self):
        node, _, adapter, session_id = await self.recording_node()
        with patch.object(adapter, "_shutdown_resources", side_effect=OSError("device release failed")):
            stopped = node.stop_runtime()
        self.assertTrue(any(not result.succeeded for result in stopped["device_shutdown_results"]))
        self.assertFalse(node.release_reservation(session_id))
        before = node.status()
        result = await self.startup((RuntimeParticipant("acquisition_node", "node-a"),)).start()
        entry, = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual(entry["observed_state"], "stopped")
        participation = entry["details"]["service_diagnostics"]["participation"]
        self.assertFalse(participation["cleanup_confirmed"])
        self.assertEqual(participation["reserved_for_session_id"], session_id)
        self.assertEqual(node.status(), before)
        self.assertFalse(node.release_reservation(session_id))
        self.assertTrue(node.abort_session_initialization(session_id))
        self.assertTrue(node.release_reservation(session_id))

    async def test_unreachable_participant_remains_unknown_without_invented_session(self):
        participant = RuntimeParticipant("acquisition_node", "unreachable")
        result = await self.startup((participant,)).start()
        report = result["reconciliation"]
        entry, = report["findings"]["participant_states"]
        self.assertEqual(entry["observed_state"], "unknown")
        self.assertIsNone(entry["details"])
        self.assertEqual(report["findings"]["reported_session_ids"], [])
        self.assertTrue(report["findings"]["unresolved"])
        self.assertTrue(report["archival_confirmed"])
        self.assertIsNone(self.controller.get_status()["session_id"])
        self.assertEqual([c["command_type"] for c in self.broker.commands], ["check_readiness"])

    async def test_multiple_nodes_keep_independent_states_and_local_preservation_obligations(self):
        active, _, _, active_id = await self.recording_node()
        stopped, declaration, _ = await self.original.node("node-b")
        self.assertTrue(stopped.reserve("session-b"))
        self.assertTrue(stopped.initialize_session("session-b", (declaration,)).ready)
        selection = ScientificOutputSelection(declaration.device_id, "node-b", "events")
        self.assertTrue(stopped.prepare_experiment_scientific_outputs("experiment-b", (selection,)).ready)
        self.addCleanup(stopped.abort_session_initialization, "session-b")
        before_active, before_stopped = active.status(), stopped.status()
        participants = tuple(RuntimeParticipant("acquisition_node", node_id)
                             for node_id in ("node-a", "node-b", "node-c"))
        result = await self.startup(participants).start()
        entries = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual([e["observed_state"] for e in entries], ["active", "stopped", "unknown"])
        self.assertEqual(result["reconciliation"]["findings"]["reported_session_ids"], sorted((active_id, "session-b")))
        diagnostics = entries[1]["details"]["service_diagnostics"]
        self.assertEqual(diagnostics["scientific_streams"][0]["local_finalization_outcome"], "unresolved")
        self.assertEqual(diagnostics["manifest_handoffs"][0]["handoff_outcome"], "unresolved")
        self.assertEqual(diagnostics["device_cleanup"][0]["cleanup_outcome"], "unresolved")
        self.assertEqual(active.status(), before_active)
        self.assertEqual(stopped.status(), before_stopped)
        self.assertFalse(stopped.release_reservation("session-b"))
        self.assertEqual(stopped.local_storage_manager.manifests[0].lifecycle_state, "open")

    async def test_failed_node_is_reported_from_owner_failure_not_missing_communication(self):
        await self.original.services()
        intake = InMemoryIngestor()
        def configured_node(**kwargs):
            kwargs["ingestor"] = intake
            return AcquisitionNode(acquisition_configuration={"handoff_failure_policy": "must_preserve",
                "handoff_failure_policies": {"must_preserve": {
                    "preserve_failed_envelope": True, "consecutive_failure_threshold": 1}}}, **kwargs)
        node, declaration, _ = await self.original.node(node_class=configured_node)
        launched = await self.original.launch({"node-a": (declaration,)})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.original.controller.start_launched_session()).succeeded)
        self.addAsyncCleanup(self.original.controller.stop_launched_session)
        with patch.object(intake, "receive_envelope", side_effect=ConnectionError("intake unavailable")):
            node.run_one_iteration()
        self.assertTrue(node.status()["failed"])
        before = node.status()
        result = await self.startup((RuntimeParticipant("acquisition_node", "node-a"),)).start()
        entry, = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual(entry["observed_state"], "failed")
        self.assertTrue(entry["details"]["service_diagnostics"]["participation"]["failed"])
        self.assertEqual(node.status(), before)
        self.assertEqual(node.reserved_for_session_id, launched.details["session_id"])

    async def test_one_publication_failure_does_not_discard_other_confirmed_node(self):
        node, _, _, session_id = await self.recording_node()
        missing = RuntimeParticipant("acquisition_node", "missing")
        active = RuntimeParticipant("acquisition_node", "node-a")
        communication = self.startup((missing, active))
        publish = communication._boundary.publish_command
        async def publication(command, component_type):
            if command.target_id == "missing":
                raise ConnectionError("participant route unavailable")
            await publish(command, component_type)
        with patch.object(communication._boundary, "publish_command", new=publication):
            result = await communication.start()
        entries = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual([entry["observed_state"] for entry in entries], ["unknown", "active"])
        self.assertEqual(entries[1]["reported_session_ids"], [session_id])
        self.assertTrue(node.status()["is_running"])

    async def test_repeat_observation_reuses_unchanged_evidence_and_does_not_replay(self):
        node, _, _, _ = await self.recording_node()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        communication = self.startup((participant,))
        initial = await communication.start()
        readback = NatsControllerCommunication(
            launch_fixtures._Boundary("controller", "replacement", self.broker))
        self.addAsyncCleanup((await readback.subscribe_command_results(None)).unsubscribe)
        before = node.status()
        journal = (self.root / "framework.jsonl").read_bytes()
        query_count = len(self.broker.commands)
        result = await self.controller.reconcile_outcomes(participants=(participant,),
            communication=readback, result_window_s=0.05)
        self.assertTrue(result["unchanged"])
        self.assertEqual(result["evidence"], initial["reconciliation"]["evidence"])
        self.assertEqual((self.root / "framework.jsonl").read_bytes(), journal)
        self.assertEqual(node.status(), before)
        self.assertEqual([c["command_type"] for c in self.broker.commands[query_count:]], ["check_readiness"])
        query_count = len(self.broker.commands)
        await communication.start()
        self.assertEqual(len(self.broker.commands), query_count)

    async def test_cancelled_startup_keeps_running_node_and_reservation(self):
        node, _, _, session_id = await self.recording_node()
        communication = self.startup((RuntimeParticipant("acquisition_node", "node-a"),))
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def delayed_result(message, message_type):
            entered.set()
            await proceed.wait()
        # Delay only the transport result, not the domain readback.
        before = node.status()
        publish = self.broker.publish
        async def delayed_publish(subject, data, stream):
            if stream == "LAB_COMMAND_RESULTS" and json.loads(data)["target_id"] == "replacement":
                await delayed_result(data, subject)
            return await publish(subject, data, stream)
        with patch.object(self.broker, "publish", new=delayed_publish):
            task = asyncio.create_task(communication.start())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                proceed.set()
        self.assertEqual(node.status(), before)
        self.assertEqual(node.reserved_for_session_id, session_id)
        self.assertTrue(node.status()["is_running"])
        self.assertIsNone(self.controller.get_status()["session_id"])

    async def test_startup_uses_configured_known_dependencies_and_requires_explicit_window(self):
        participant = RuntimeParticipant("acquisition_node", "unreachable")
        other = Controller(component_id="configured", ingestor=self.ingestor, storage_manager=self.storage)
        interface = ServiceMaintenanceInterface(other, RuntimeParticipant("controller", "configured"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True), dependency_participants=(participant,))
        boundary = launch_fixtures._Boundary("controller", "configured", self.broker)
        missing_window = NatsServiceMaintenanceCommunication(boundary, interface)
        with self.assertRaisesRegex(ValueError, "explicit"):
            await missing_window.start()
        self.assertEqual(self.broker.commands, [])
        valid = NatsServiceMaintenanceCommunication(boundary, interface, startup_result_window_s=0.01)
        self.addAsyncCleanup(valid.close)
        result = await valid.start()
        self.assertEqual(result["reconciliation"]["findings"]["participant_states"][0]["participant"], participant.to_dict())

    async def test_attached_startup_dependencies_preserve_unbound_controller_observations(self):
        controller = Controller()
        interface = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", "startup-alias"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        communication = NatsServiceMaintenanceCommunication(
            launch_fixtures._Boundary("controller", "startup-alias", self.broker), interface)
        self.addAsyncCleanup(communication.close)
        result = await communication.start()
        report = result["reconciliation"]
        self.assertEqual(report["findings"]["controller_id"], "startup-alias")
        self.assertEqual(report["findings"]["participant_states"], [])
        self.assertEqual(report["evidence"]["source_id"], "startup-alias")
        self.assertTrue(report["acceptance_confirmed"])
        self.assertTrue(report["archival_confirmed"])
        self.assertIsNone(controller.get_status()["session_id"])

    async def test_live_technically_unready_service_is_not_misclassified_as_failed(self):
        service = SynchronizationManager()
        participant = RuntimeParticipant("synchronization_manager", "timing-peer")
        ServiceMaintenanceInterface(service, participant, ingestor=self.ingestor,
            storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        handler = NatsSynchronizationManagerCommunication(
            launch_fixtures._Boundary(participant.component_type, participant.component_id, self.broker), service)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        report = ServiceReadiness(participant.component_id, participant.component_type, True, False, "technical_unreadiness")
        with patch.object(service, "check_ready", return_value=report):
            result = await self.startup((participant,)).start()
        entry, = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual(entry["observed_state"], "active")
        self.assertFalse(entry["details"]["service_readiness"]["ready"])
        self.assertFalse(entry["details"]["operational_retirement_confirmed"])

    async def test_confirmed_service_retirement_is_reported_separately_from_readiness(self):
        service = SynchronizationManager()
        participant = RuntimeParticipant("synchronization_manager", "retired-peer")
        interface = ServiceMaintenanceInterface(service, participant, ingestor=self.ingestor,
            storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        stopped = await interface.execute_command(RuntimeCommandMessage("stop-peer", None, "stop",
            "administrator", participant.component_id, {"stop_attempt_id": "peer-retirement",
                                                       "administrator_id": "operator"}))
        self.assertTrue(stopped.success, stopped.reason)
        self.assertTrue(interface.terminated)
        handler = NatsSynchronizationManagerCommunication(
            launch_fixtures._Boundary(participant.component_type, participant.component_id, self.broker), service)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        result = await self.startup((participant,)).start()
        entry, = result["reconciliation"]["findings"]["participant_states"]
        self.assertEqual(entry["observed_state"], "stopped")
        self.assertTrue(entry["details"]["operational_retirement_confirmed"])
        self.assertFalse(entry["details"]["service_readiness"]["ready"])


if __name__ == "__main__":
    unittest.main()
