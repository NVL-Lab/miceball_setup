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
        self.storage = PersistentStorageManager(self.root / "global")
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
            return AcquisitionNode(**kwargs)
        node, declaration, adapter = await self.original.node(node_class=configured_node)
        launched = await self.original.launch({"node-a": (declaration,)})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.original.controller.start_launched_session()).succeeded)
        self.addAsyncCleanup(self.original.controller.stop_launched_session)
        with patch.object(adapter, "collect_products", side_effect=OSError("device acquisition failed")):
            with self.assertRaisesRegex(RuntimeError, "device acquisition failed"):
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

    async def test_initial_startup_creates_confirmed_framework_archive(self):
        directory = self.root / "global/framework/evidence"
        self.assertFalse(directory.exists())
        status = await self.startup(()).start()
        confirmation = self.storage.get_framework_preservation_confirmation()
        self.assertIsNotNone(confirmation)
        for report in (status, status["reconciliation"]):
            self.assertTrue(report["acceptance_confirmed"])
            self.assertTrue(report["archival_confirmed"])
            self.assertIsNone(report["preservation_warning"])
            self.assertIn(report["evidence"], confirmation["runtime_evidence"])

    async def test_return_startup_preserves_healthy_existing_archive(self):
        communication = self.startup(())
        await communication.start()
        original = self.storage.get_framework_preservation_confirmation()
        await communication.close()
        status = await communication.start()
        confirmation = self.storage.get_framework_preservation_confirmation()
        for name in ("runtime_evidence", "ingest_audit"):
            for entry in original[name]:
                self.assertIn(entry, confirmation[name])
        self.assertTrue(status["archival_confirmed"])
        self.assertTrue(status["reconciliation"]["archival_confirmed"])
        self.assertIsNone(status["preservation_warning"])

    async def test_unconfirmed_archive_products_are_not_repaired_by_startup(self):
        initial = self.startup(())
        await initial.start()
        await initial.close()
        directory = self.root / "global/framework/evidence"
        paths = tuple(directory / name for name in (
            "runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"))
        healthy = {path: path.read_bytes() for path in paths}
        cases = [(path, damage) for path in paths for damage in ("corrupt", "missing", "inconsistent")]
        for path, damage in cases:
            with self.subTest(product=path.name, damage=damage):
                for product, contents in healthy.items():
                    product.write_bytes(contents)
                if damage == "missing":
                    path.unlink()
                elif damage == "corrupt":
                    path.write_bytes(b"invalid completed archive product")
                else:
                    path.write_bytes(b"{}" if path.suffix == ".json" else b"")
                before = {product: product.read_bytes() if product.exists() else None for product in paths}
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                communication = self.startup(())
                with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                    status = await communication.start()
                self.assertTrue(status["publication_confirmed"])
                for report in (status, status["reconciliation"]):
                    self.assertTrue(report["acceptance_confirmed"])
                    self.assertFalse(report["archival_confirmed"])
                    self.assertTrue(report["preservation_warning"])
                self.assertFalse(status["reconciliation"]["findings"]["preservation_confirmed"])
                self.assertEqual(before, {
                    product: product.read_bytes() if product.exists() else None for product in paths})
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                await communication.close()

    async def test_startup_evidence_remains_available_for_authorized_archive_recovery(self):
        communication = self.startup(())
        await communication.start()
        await communication.close()
        compiled = self.ingestor.compile_framework_runtime_evidence()
        with patch("lab_sync_acquisition.storage.Path.open", side_effect=OSError("archive interrupted")):
            with self.assertRaises(OSError):
                self.storage.write_framework_evidence_archive(compiled)
        path = self.root / "global/framework/evidence/runtime_evidence.jsonl"
        damaged = b"corrupt runtime evidence"
        path.write_bytes(damaged)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await communication.start()
        evidence = (status["evidence"], status["reconciliation"]["evidence"])
        retained = [message.to_dict() for message in self.interface.evidence]
        compiled = [message.to_dict() for message in self.ingestor.compile_framework_runtime_evidence()["runtime_evidence"]]
        journal = [json.loads(line) for line in (self.root / "framework.jsonl").read_text().splitlines()]
        for message in evidence:
            self.assertIn(message, retained)
            self.assertIn(message, compiled)
            self.assertTrue(any(message == entry.get("runtime_evidence") for entry in journal))
        self.assertEqual(path.read_bytes(), damaged)
        recovery = ServiceMaintenanceInterface(self.storage, RuntimeParticipant("storage_manager", "storage"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        obligation = {"session_id": None}
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            decision = await recovery.record_administrator_decision("administrator", "resume", {
                "operation": "recover_archive_write", "obligation": obligation,
                "command_id": "repair-startup-archive"})
            result = await recovery.execute_command(RuntimeCommandMessage("repair-startup-archive", None,
                "recover_archive_write", "operator", "storage", {
                    "authorization_evidence_id": decision["evidence"]["evidence_id"], "obligation": obligation}))
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
        self.assertTrue(result.payload["preservation"]["archival_confirmed"])
        confirmation = self.storage.get_framework_preservation_confirmation()
        for message in evidence:
            self.assertIn(message, confirmation["runtime_evidence"])

    async def test_fresh_controller_does_not_repair_corrupted_archive_or_stop_recording(self):
        node, _, adapter, session_id = await self.recording_node()
        original = self.startup(())
        await original.start()
        await original.close()
        path = self.root / "global/framework/evidence/ingest_audit.jsonl"
        damaged = b"corrupt intake audit"
        path.write_bytes(damaged)
        controller = Controller(component_id="fresh", ingestor=self.ingestor, storage_manager=self.storage)
        interface = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", "fresh"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        communication = NatsServiceMaintenanceCommunication(
            launch_fixtures._Boundary("controller", "fresh", self.broker), interface,
            startup_participants=(RuntimeParticipant("acquisition_node", "node-a"),), startup_result_window_s=0.05)
        self.addAsyncCleanup(communication.close)
        before, device_before = node.status(), adapter.get_status()
        command_count = len(self.broker.commands)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await communication.start()
        self.assertEqual(path.read_bytes(), damaged)
        for report in (status, status["reconciliation"]):
            self.assertTrue(report["acceptance_confirmed"])
            self.assertFalse(report["archival_confirmed"])
            self.assertTrue(report["preservation_warning"])
        self.assertFalse(status["reconciliation"]["findings"]["preservation_confirmed"])
        observed, = status["reconciliation"]["findings"]["participant_states"]
        self.assertEqual(observed["observed_state"], "active")
        self.assertEqual(observed["reported_session_ids"], [session_id])
        self.assertEqual(node.status(), before)
        self.assertEqual(adapter.get_status(), device_before)
        self.assertIsNone(controller.get_status()["session_id"])
        self.assertEqual([c["command_type"] for c in self.broker.commands[command_count:]], ["check_readiness"])
        self.assertEqual(node.reserved_for_session_id, session_id)
        node.run_one_iteration()
        self.assertTrue(node.status()["is_running"])

    async def test_archive_safety_is_rechecked_after_startup_publication(self):
        communication = self.startup(())
        await communication.start()
        await communication.close()
        path = self.root / "global/framework/evidence/ingest_audit.jsonl"
        entered, proceed = asyncio.Event(), asyncio.Event()
        publish = self.interface.evidence_publisher
        async def delayed(message):
            if message.evidence_type == "service_readiness":
                entered.set()
                await proceed.wait()
            await publish(message)
        with patch.object(self.interface, "evidence_publisher", new=delayed):
            task = asyncio.create_task(communication.start())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                damaged = b"audit corrupted during publication"
                path.write_bytes(damaged)
                with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                    proceed.set()
                    status = await task
            finally:
                proceed.set()
                await task
        self.assertEqual(path.read_bytes(), damaged)
        for report in (status, status["reconciliation"]):
            self.assertTrue(report["acceptance_confirmed"])
            self.assertFalse(report["archival_confirmed"])
            self.assertTrue(report["preservation_warning"])

    async def test_existing_archive_without_current_confirmation_is_not_overwritten(self):
        original = self.startup(())
        await original.start()
        await original.close()
        directory = self.root / "global/framework/evidence"
        before = {path: path.read_bytes() for path in directory.iterdir()}
        storage = PersistentStorageManager(self.root / "global")
        self.assertIsNone(storage.get_framework_preservation_confirmation())
        controller = Controller(component_id="fresh", ingestor=self.ingestor, storage_manager=storage)
        interface = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", "fresh"),
            ingestor=self.ingestor, storage_manager=storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        communication = NatsServiceMaintenanceCommunication(
            launch_fixtures._Boundary("controller", "fresh", self.broker), interface)
        self.addAsyncCleanup(communication.close)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await communication.start()
        for report in (status, status["reconciliation"]):
            self.assertTrue(report["acceptance_confirmed"])
            self.assertFalse(report["archival_confirmed"])
            self.assertTrue(report["preservation_warning"])
        self.assertEqual(before, {path: path.read_bytes() for path in directory.iterdir()})
        self.assertIsNone(storage.get_framework_preservation_confirmation())

    async def test_malformed_optional_collections_do_not_abort_other_observations(self):
        node, _, _, session_id = await self.recording_node()
        participants = (RuntimeParticipant("synchronization_manager", "sync"),
                        RuntimeParticipant("acquisition_node", "node-a"))
        before = node.status()
        for malformed in (None, 1, True, "invented-session", {"session_id": "invented-session"}, [None, 1, "bad"]):
            with self.subTest(collection_evidence=malformed):
                def alter(operation, result):
                    if result["source_id"] == "sync":
                        result["payload"]["service_diagnostics"] = {"collection_evidence": malformed}
                    return result
                self.broker.change_result = alter
                communication = self.startup(participants)
                status = await communication.start()
                entries = status["reconciliation"]["findings"]["participant_states"]
                self.assertEqual(entries[0]["observed_state"], "unknown")
                self.assertEqual(entries[0]["reported_session_ids"], [])
                self.assertEqual(entries[1]["observed_state"], "active")
                self.assertEqual(entries[1]["reported_session_ids"], [session_id])
                self.assertEqual(status["reconciliation"]["findings"]["reported_session_ids"], [session_id])
                self.assertEqual(node.status(), before)
                json.dumps(status, allow_nan=False)
                await communication.close()
        self.broker.change_result = None


if __name__ == "__main__":
    unittest.main()
