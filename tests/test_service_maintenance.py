"""Individual-service maintenance and real broker-double command workflows."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, InMemoryIngestor, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeEvidenceMessage, RuntimeParticipant, ServiceMaintenanceInterface,
    SynchronizationManager, SessionConfig, NatsServiceMaintenanceCommunication,
    NatsControllerCommunication, NatsIngestorCommunication, NatsSynchronizationManagerCommunication,
    NatsAcquisitionNodeCommunication,
)
from tests.test_session_launch import _Broker, _Boundary
from tests.fakes import ReadyFakeAdapter


class ServiceMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = PersistentStorageManager(self.root / "records.jsonl")
        self.ingestor = InMemoryIngestor(self.storage, framework_recovery_journal_path=self.root / "journal" / "framework.jsonl")
        self.sync = SynchronizationManager()
        self.adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True, declared_capabilities=())
        self.node = AcquisitionNode(device_manager=DeviceManager((self.adapter,)), synchronization_manager=self.sync,
                                    ingestor=self.ingestor, node_id="node", role="acquisition")
        self.controller = Controller(ingestor=self.ingestor, storage_manager=self.storage, synchronization_manager=self.sync)

    def target(self, kind="controller", close=None, dependencies=None):
        service = {"controller": self.controller, "acquisition_node": self.node, "ingestor": self.ingestor,
                   "storage_manager": self.storage, "synchronization_manager": self.sync}[kind]
        close = close if close is not None else AsyncMock(return_value=True)
        interface = ServiceMaintenanceInterface(service, RuntimeParticipant(kind, kind), ingestor=self.ingestor,
                     storage_manager=self.storage, preservation_window_s=0.1, close_resources=close, operational_dependents=dependencies)
        return interface, close

    def command(self, interface, operation="stop", attempt="attempt-1", identity="command-1", authorized=False):
        return RuntimeCommandMessage(identity, None, operation, "administrator", interface.participant.component_id,
                                     {"stop_attempt_id": attempt, "administrator_id": "operator", "authorized": authorized})

    async def test_orderly_idle_stop_of_each_principal_service(self):
        for kind in ("controller", "acquisition_node", "synchronization_manager", "ingestor", "storage_manager"):
            with self.subTest(kind=kind):
                self.setUp()
                interface, close = self.target(kind)
                result = await interface.execute_command(self.command(interface))
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.payload["outcome"], "completed")
                self.assertTrue(result.payload["termination_confirmed"])
                close.assert_awaited_once_with(False)
                confirmation = self.storage.get_framework_preservation_confirmation()
                self.assertIsNotNone(confirmation)
                self.assertEqual(confirmation["runtime_evidence"][-1]["payload"]["outcome"], "completed")
                self.assertIsNone(self.controller.get_status()["session_id"])

    async def test_node_reservation_blocks_shutdown_and_unrelated_new_work(self):
        self.node.reserve("session-a")
        interface, close = self.target("acquisition_node")
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.assertIn("Outstanding Session reservation", result.payload["attempt"]["blockers"])
        close.assert_not_awaited()
        with self.assertRaises(RuntimeError):
            self.node.reserve("session-b")
        self.assertTrue(self.node.release_reservation("session-a"))

    async def test_running_synchronization_blocks_without_stopping_time(self):
        self.sync.start()
        interface, close = self.target("synchronization_manager")
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.assertTrue(self.sync.is_running)
        close.assert_not_awaited()
        self.sync.stop()

    async def test_active_mapping_and_unpreserved_evidence_block_synchronization(self):
        self.sync.prepare_session("session-a")
        self.sync.create_and_activate_mapping("session-a", "node", 0.0, 0.0, 1.0, "initial")
        interface, close = self.target("synchronization_manager")
        result = await interface.execute_command(self.command(interface))
        self.assertIn("Active synchronization mappings", result.payload["attempt"]["blockers"])
        self.assertIn("Unpreserved mapping evidence", result.payload["attempt"]["blockers"])
        close.assert_not_awaited()

    async def test_ingestor_explicit_operational_dependency_blocks_without_session(self):
        dependency = RuntimeParticipant("acquisition_node", "node")
        interface, close = self.target("ingestor", dependencies={dependency: lambda: True})
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.assertIsNone(self.node.status()["session_id"])
        close.assert_not_awaited()
        # Existing evidence obligations continue while a new binding is rejected.
        self.assertTrue(self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("continued", None, "warning", "node", {}, True)).accepted)
        with self.assertRaises(RuntimeError):
            self.ingestor.prepare_session("session-b")

    async def test_ingestor_unpreserved_session_intake_blocks(self):
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("session-evidence", "session-a", "warning", "node", {}, True))
        interface, close = self.target("ingestor")
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        close.assert_not_awaited()

    async def test_cancel_preserves_original_blockers_and_allows_new_attempt(self):
        self.node.reserve("session-a")
        interface, close = self.target("acquisition_node")
        first = await interface.execute_command(self.command(interface))
        cancelled = await interface.execute_command(self.command(interface, "cancel", identity="command-2"))
        self.assertEqual(cancelled.payload["outcome"], "failed")
        self.assertEqual(cancelled.payload["attempt"]["blockers"], first.payload["attempt"]["blockers"])
        close.assert_not_awaited()
        self.node.release_reservation("session-a")
        next_result = await interface.execute_command(self.command(interface, attempt="attempt-2", identity="command-3"))
        self.assertTrue(next_result.success)

    async def test_authorized_kill_continues_original_blocked_attempt_once(self):
        self.node.reserve("session-a")
        interface, close = self.target("acquisition_node")
        first = await interface.execute_command(self.command(interface))
        for attempt, authorized in (("attempt-1", False), ("stale", True)):
            result = await interface.execute_command(self.command(interface, "kill", attempt, f"invalid-{attempt}-{authorized}", authorized))
            self.assertFalse(result.success)
        close.assert_not_awaited()
        kill = self.command(interface, "kill", identity="command-2", authorized=True)
        result = await interface.execute_command(kill)
        self.assertTrue(result.success)
        self.assertEqual(result.payload["attempt"]["blockers"], first.payload["attempt"]["blockers"])
        close.assert_awaited_once_with(True)
        again = await interface.execute_command(kill)
        self.assertEqual(again, result)
        close.assert_awaited_once()
        self.assertEqual(self.node.reserved_for_session_id, "session-a")
        with self.assertRaises(RuntimeError):
            self.node.reserve("session-b")

    async def test_resource_close_failure_reports_failed_and_retains_evidence(self):
        for failure in (False, OSError("release failed")):
            with self.subTest(failure=failure):
                self.setUp()
                close = AsyncMock(side_effect=failure) if isinstance(failure, Exception) else AsyncMock(return_value=False)
                interface, _ = self.target(close=close)
                result = await interface.execute_command(self.command(interface))
                self.assertEqual(result.payload["outcome"], "failed")
                self.assertFalse(result.payload["termination_confirmed"])
                self.assertTrue(interface.evidence)

    async def test_archive_failure_before_cleanup_blocks_orderly_termination(self):
        interface, close = self.target()
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=OSError("disk full")):
            result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        close.assert_not_awaited()
        self.assertFalse(interface.terminated)
        self.assertTrue(interface.evidence)

    async def test_journal_failure_before_cleanup_blocks_orderly_termination(self):
        interface, close = self.target()
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("journal failed")):
            result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        close.assert_not_awaited()

    async def test_final_preservation_failure_does_not_claim_termination(self):
        interface, close = self.target()
        write = self.storage.write_framework_evidence_archive
        calls = []
        def fail_after_preparation(compiled):
            calls.append(1)
            if len(calls) > 1:
                raise OSError("final evidence write failed")
            return write(compiled)
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=fail_after_preparation):
            result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "failed")
        self.assertFalse(result.payload["termination_confirmed"])
        close.assert_awaited_once()

    async def test_overlapping_duplicate_stop_executes_closeout_once(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def close(force):
            entered.set()
            await proceed.wait()
            return True
        interface, _ = self.target(close=close)
        command = self.command(interface)
        first = asyncio.create_task(interface.execute_command(command))
        await entered.wait()
        duplicate = asyncio.create_task(interface.execute_command(command))
        other = asyncio.create_task(interface.execute_command(self.command(interface, attempt="attempt-2", identity="command-2")))
        proceed.set()
        a, b, c = await asyncio.gather(first, duplicate, other)
        self.assertTrue(a.success)
        self.assertEqual(a, b)
        self.assertFalse(c.success)

    async def test_cancellation_retains_failed_attempt_and_duplicate_cannot_repeat_closeout(self):
        entered = asyncio.Event()
        async def close(force):
            entered.set()
            await asyncio.Event().wait()
        interface, _ = self.target(close=close)
        command = self.command(interface)
        task = asyncio.create_task(interface.execute_command(command))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(interface.terminated)
        self.assertEqual((await interface.execute_command(command)).payload["outcome"], "failed")

    async def test_maintenance_commands_use_existing_broker_and_result_correlation(self):
        for kind in ("controller", "storage_manager", "ingestor", "synchronization_manager", "acquisition_node"):
            with self.subTest(kind=kind):
                self.setUp()
                interface, close = self.target(kind)
                broker = _Broker()
                boundary = _Boundary(kind, kind, broker)
                await NatsIngestorCommunication(_Boundary("ingestor", "archive-intake", broker), self.ingestor).subscribe_evidence(None)
                handler = {"ingestor": lambda: NatsIngestorCommunication(boundary, self.ingestor),
                           "synchronization_manager": lambda: NatsSynchronizationManagerCommunication(boundary, self.sync),
                           "acquisition_node": lambda: NatsAcquisitionNodeCommunication(boundary, self.node)}.get(
                               kind, lambda: NatsServiceMaintenanceCommunication(boundary, interface))()
                await handler.subscribe_commands()
                admin = NatsControllerCommunication(_Boundary("administrator", "administrator", broker))
                await admin.subscribe_command_results(None)
                result = await admin.request_command(interface.participant, "stop", None,
                         {"stop_attempt_id": "broker-attempt", "administrator_id": "operator"}, 1.0)
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.command_id, broker.commands[0]["command_id"])
                self.assertEqual(admin.maintenance_requests[0]["payload"]["stop_attempt_id"], "broker-attempt")
                close.assert_awaited_once()

    async def test_framework_evidence_uses_existing_nats_ingestor_subscription(self):
        broker = _Broker()
        handler = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", broker), self.ingestor)
        await handler.subscribe_evidence(None)
        boundary = _Boundary("controller", "producer", broker)
        message = RuntimeEvidenceMessage("broker-evidence", None, "warning", "producer", {}, True)
        await boundary.publish_evidence(message)
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(message))
        self.assertIsNone(self.ingestor.session_id)

    async def test_storage_active_collection_blocks_stop_but_existing_publication_can_finish(self):
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def publish(message):
            entered.set()
            await proceed.wait()
        storage = PersistentStorageManager(self.root / "other-records.jsonl", evidence_publisher=publish)
        interface = ServiceMaintenanceInterface(storage, RuntimeParticipant("storage_manager", "storage"),
                    ingestor=self.ingestor, storage_manager=storage, preservation_window_s=0.1, close_resources=AsyncMock(return_value=True))
        collection = asyncio.create_task(storage.collect_artifacts_with_evidence({"session_id": "session-a", "artifacts": []}))
        await entered.wait()
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.assertIn("Unfinished service operations", result.payload["attempt"]["blockers"])
        with self.assertRaises(RuntimeError):
            await storage.collect_artifacts_with_evidence({"session_id": "session-b", "artifacts": []})
        proceed.set()
        await collection

    async def test_late_session_intake_during_ingestor_closeout_prevents_termination(self):
        async def close(force):
            self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("late-session", "session-a", "warning", "node", {}, True))
            return True
        interface, _ = self.target("ingestor", close=close)
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "failed")
        self.assertFalse(interface.terminated)
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 1)

    async def test_real_device_cleanup_is_executed_for_authorized_node_kill(self):
        self.node.reserve("session-a")
        self.adapter.initialize({})
        self.adapter.check_ready()
        interface, close = self.target("acquisition_node")
        self.assertEqual((await interface.execute_command(self.command(interface))).payload["outcome"], "blocked")
        result = await interface.execute_command(self.command(interface, "kill", identity="kill-1", authorized=True))
        self.assertTrue(result.success, result.reason)
        from lab_sync_acquisition import DeviceAdapterState
        self.assertEqual(self.adapter.state, DeviceAdapterState.DECLARED)
        self.assertFalse(self.node.check_node_readiness().ready)

    async def test_publication_without_confirmed_journal_acceptance_blocks_stop(self):
        interface, close = self.target()
        with patch.object(self.ingestor, "await_durable_runtime_evidence", new=AsyncMock(return_value=False)):
            result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        close.assert_not_awaited()

    async def test_transport_ack_precedes_intake_but_bounded_acceptance_wait_allows_stop(self):
        acknowledged, deliver = asyncio.Event(), asyncio.Event()
        deliveries = []
        async def publisher(message):
            async def intake():
                await deliver.wait()
                self.ingestor.receive_runtime_evidence(message)
            deliveries.append(asyncio.create_task(intake()))
            acknowledged.set()
        interface, close = self.target()
        interface.evidence_publisher = publisher
        task = asyncio.create_task(interface.execute_command(self.command(interface)))
        await acknowledged.wait()
        close.assert_not_awaited()
        deliver.set()
        result = await task
        await asyncio.gather(*deliveries)
        self.assertTrue(result.success, result.reason)
        close.assert_awaited_once()

    async def test_conflicting_duplicate_command_cannot_change_original_attempt(self):
        self.node.reserve("session-a")
        interface, close = self.target("acquisition_node")
        first = await interface.execute_command(self.command(interface))
        conflict = self.command(interface, "kill", identity="command-1", authorized=True)
        result = await interface.execute_command(conflict)
        self.assertFalse(result.success)
        self.assertEqual((await interface.execute_command(self.command(interface))), first)
        close.assert_not_awaited()

    async def test_broker_publication_ack_without_intake_does_not_authorize_stop(self):
        interface, close = self.target()
        broker = _Broker()
        await NatsServiceMaintenanceCommunication(_Boundary("controller", "controller", broker), interface).subscribe_commands()
        admin = NatsControllerCommunication(_Boundary("administrator", "administrator", broker))
        await admin.subscribe_command_results(None)
        result = await admin.request_command(interface.participant, "stop", None,
                     {"stop_attempt_id": "unaccepted", "administrator_id": "operator"}, 1.0)
        self.assertEqual(result.payload["outcome"], "blocked")
        close.assert_not_awaited()

    async def test_controller_bound_session_blocks_without_mutating_lifecycle(self):
        config = SessionConfig([], str(self.root), None, str(self.root / "errors"), session_id="session-a")
        self.assertTrue(self.controller.create_session(config).succeeded)
        before = self.controller.get_status()
        interface, close = self.target()
        result = await interface.execute_command(self.command(interface))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.assertEqual(self.controller.get_status(), before)
        close.assert_not_awaited()
        with self.assertRaises(RuntimeError):
            self.controller.create_session(config)

