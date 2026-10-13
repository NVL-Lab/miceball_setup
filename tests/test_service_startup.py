"""Independent service startup and return through existing NATS/evidence contracts."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nats.js.api import AckPolicy, DeliverPolicy

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, DurablePublicationError, InMemoryIngestor,
    NatsControllerCommunication, NatsIngestorCommunication, NatsServiceMaintenanceCommunication,
    NatsSynchronizationManagerCommunication, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeEvidenceMessage, RuntimeParticipant,
    ServiceMaintenanceInterface, ServiceReadiness, SessionConfig, SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_session_launch import _Boundary, _Broker
from tests import test_framework_shutdown as shutdown_fixtures


class AnnouncementBroker(_Broker):
    """Transport double honoring new-only subscriptions while retaining evidence history."""

    def __init__(self):
        super().__init__()
        self.history = []
        self.policies = []
        self.ack_policies = []

    async def subscribe(self, subject, cb, **kwargs):
        subscription = await super().subscribe(subject, cb, **kwargs)
        self.policies.append((subject, kwargs.get("deliver_policy")))
        self.ack_policies.append((subject, getattr(kwargs.get("config"), "ack_policy", None)))
        if kwargs.get("deliver_policy") != DeliverPolicy.NEW:
            for topic, data in tuple(self.history):
                if self.matches(subject, topic):
                    await cb(SimpleNamespace(data=data, ack=AsyncMock()))
        return subscription

    async def publish(self, subject, data, stream):
        if stream == "LAB_EVIDENCE":
            self.history.append((subject, data))
        return await super().publish(subject, data, stream)


class ServiceStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.broker = AnnouncementBroker()
        self.storage = PersistentStorageManager(self.root / "records.jsonl")
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        self.intake_subscription = await self.intake.subscribe_evidence(None)
        self.addAsyncCleanup(self.intake_subscription.unsubscribe)
        self.source = RuntimeParticipant("synchronization_manager", "sync")
        self.observer = RuntimeParticipant("controller", "observer")

    def interface(self, service, participant, dependencies=(), *, ingestor=True, storage=True):
        return ServiceMaintenanceInterface(service, participant,
            ingestor=self.ingestor if ingestor else None,
            storage_manager=self.storage if storage else None,
            preservation_window_s=0, close_resources=AsyncMock(return_value=True),
            dependency_participants=dependencies)

    def communication(self, interface):
        communication = NatsServiceMaintenanceCommunication(
            _Boundary(interface.participant.component_type, interface.participant.component_id, self.broker), interface,
            startup_result_window_s=0.01 if interface.participant.component_type == "controller" else None)
        self.addAsyncCleanup(communication.close)
        return communication

    def observer_pair(self):
        controller = Controller(component_id="observer", ingestor=self.ingestor, storage_manager=self.storage)
        interface = self.interface(controller, self.observer, (self.source,))
        return controller, interface, self.communication(interface)

    def evidence(self):
        return [json.loads(data) for _, data in self.broker.history]

    async def test_each_principal_service_announces_identity_and_current_readiness(self):
        sync = SynchronizationManager()
        adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True, declared_capabilities=())
        node = AcquisitionNode(device_manager=DeviceManager((adapter,)), synchronization_manager=sync,
            ingestor=self.ingestor, node_id="node", role="acquisition",
            error_evidence_location=str(self.root / "errors"))
        services = {"synchronization_manager": sync, "acquisition_node": node,
                    "controller": Controller(), "ingestor": self.ingestor, "storage_manager": self.storage}
        for kind, service in services.items():
            participant = RuntimeParticipant(kind, "node" if kind == "acquisition_node" else kind)
            interface = self.interface(service, participant)
            status = await self.communication(interface).start()
            self.assertTrue(status["publication_confirmed"])
            self.assertTrue(status["acceptance_confirmed"])
            self.assertTrue(status["archival_confirmed"], status["preservation_warning"])
            message = RuntimeEvidenceMessage.from_dict(status["evidence"])
            self.assertIsNone(message.session_id)
            self.assertTrue(message.is_persistent)
            self.assertEqual(message.payload["participant"], participant.to_dict())
            self.assertEqual(message.payload["service_readiness"]["component_id"], participant.component_id)
            self.assertTrue(message.payload["service_readiness"]["ready"])
        archive = self.storage.get_framework_preservation_confirmation()
        announcements = [message for message in archive["runtime_evidence"]
                         if message["evidence_type"] == "service_readiness"]
        self.assertEqual(len(announcements), 5)
        self.assertEqual(len(archive["runtime_evidence"]), 6)
        self.assertEqual(len(archive["ingest_audit"]), 6)

    async def test_direct_announcements_update_readiness_without_redundant_queries_or_relay(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        startup_queries = list(self.broker.commands)
        self.assertEqual([c["command_type"] for c in startup_queries], ["check_readiness"])
        self.assertIsNone(observer.dependency_readiness[self.source])
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            controller.check_ready()
        source = self.interface(SynchronizationManager(), self.source)
        await self.communication(source).start()
        self.assertTrue(observer.dependency_readiness[self.source].ready)
        self.assertTrue(controller.check_ready().ready)
        self.assertEqual(self.broker.commands, startup_queries)
        source_messages = [m for m in self.evidence() if m["source_id"] == "sync"]
        self.assertEqual(len(source_messages), 1)
        self.assertEqual(len([m for m in self.evidence() if m["source_id"] == "observer"]), 3)

    async def test_historical_announcements_cannot_establish_current_readiness(self):
        source = self.interface(SynchronizationManager(), self.source)
        await self.communication(source).start()
        controller, observer, communication = self.observer_pair()
        await communication.start()
        self.assertIsNone(observer.dependency_readiness[self.source])
        self.assertIsNone(observer.last_known_dependency_readiness[self.source])
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            controller.check_ready()
        self.assertIn(("messages.evidence.synchronization_manager.sync.service_readiness", DeliverPolicy.NEW),
                      self.broker.policies)
        self.assertIn(("messages.evidence.synchronization_manager.sync.service_readiness", AckPolicy.NONE),
                      self.broker.ack_policies)

    async def test_ingestor_still_consumes_historical_startup_evidence(self):
        await self.intake_subscription.unsubscribe()
        source = self.interface(SynchronizationManager(), self.source)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await self.communication(source).start()
        self.assertTrue(status["publication_confirmed"])
        self.assertFalse(status["acceptance_confirmed"])
        recovered = InMemoryIngestor(framework_recovery_journal_path=self.root / "late-intake.jsonl")
        subscription = await NatsIngestorCommunication(
            _Boundary("ingestor", "late", self.broker), recovered).subscribe_evidence(None)
        self.addAsyncCleanup(subscription.unsubscribe)
        compiled = recovered.compile_framework_runtime_evidence()
        self.assertEqual(compiled["runtime_evidence"][0].to_dict(), status["evidence"])
        self.assertTrue(recovered.has_durable_runtime_evidence(compiled["runtime_evidence"][0]))

    async def test_loss_invalidates_current_readiness_and_return_updates_existing_observer(self):
        controller, observer, communication = self.observer_pair()
        self.assertTrue(controller.create_session(SessionConfig([], None, None,
            str(self.root / "errors"), session_id="session-a")).succeeded)
        await communication.start()
        original = SynchronizationManager()
        source = self.interface(original, self.source)
        await self.communication(source).start()
        handler = NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), original)
        subscriptions = await handler.subscribe_commands()
        for subscription in subscriptions:
            await subscription.unsubscribe()
        before = controller.get_status()
        self.assertIsNone(await communication.check_dependency_readiness(self.source, 0))
        self.assertIsNone(observer.dependency_readiness[self.source])
        self.assertTrue(observer.last_known_dependency_readiness[self.source].ready)
        self.assertEqual(controller.get_status()["session_state"], before["session_state"])
        self.assertFalse(observer.terminated)
        replacement = self.interface(SynchronizationManager(), self.source)
        await self.communication(replacement).start()
        self.assertTrue(controller.check_ready().ready)
        self.assertTrue(observer.dependency_readiness[self.source].ready)
        self.assertEqual(len(self.broker.commands), 2)

    async def test_failed_communication_invalidates_availability_without_fabricating_unreadiness(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        await self.communication(self.interface(SynchronizationManager(), self.source)).start()
        communication._boundary.available = False
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            with self.assertRaises(RuntimeError):
                await communication.check_dependency_readiness(self.source, 0)
        self.assertIsNone(observer.dependency_readiness[self.source])
        self.assertTrue(observer.last_known_dependency_readiness[self.source].ready)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            controller.check_ready()

    async def test_actual_unreadiness_report_is_distinct_from_unknown(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        original = SynchronizationManager()
        source = self.interface(original, self.source)
        await self.communication(source).start()
        unready = ServiceReadiness("sync", "synchronization_manager", True, False, "timing_unavailable")
        with patch.object(original, "check_ready", return_value=unready):
            await source.announce_readiness()
        self.assertFalse(observer.dependency_readiness[self.source].ready)
        self.assertFalse(controller.check_ready().ready)
        self.assertIn("timing_unavailable", controller.check_ready().reason)

    async def test_missed_announcement_can_be_checked_explicitly(self):
        original = SynchronizationManager()
        source = self.interface(original, self.source)
        await self.communication(source).start()
        controller, observer, communication = self.observer_pair()
        await communication.start()
        subscriptions = await NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), original).subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        report = await communication.check_dependency_readiness(self.source, 0)
        self.assertTrue(report.ready)
        self.assertTrue(controller.check_ready().ready)
        self.assertEqual(len(self.broker.commands), 2)

    async def test_unchanged_readiness_does_not_create_redundant_evidence(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        first = await communication.start()
        second = await communication.publish_readiness()
        self.assertEqual(first["evidence"]["evidence_id"], second["evidence"]["evidence_id"])
        self.assertEqual(len(interface.evidence), 1)
        self.assertEqual(len(self.evidence()), 1)

    async def test_transport_return_uses_same_format_without_retiring_service(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        first = await communication.start()
        await communication.close()
        second = await communication.start()
        initial, returned = deepcopy(first["evidence"]), deepcopy(second["evidence"])
        self.assertNotEqual(initial.pop("evidence_id"), returned.pop("evidence_id"))
        initial["payload"].pop("recorded_at")
        returned["payload"].pop("recorded_at")
        self.assertEqual(initial, returned)
        self.assertFalse(interface.terminated)

    async def test_unavailable_storage_warns_without_blocking_startup_or_losing_evidence(self):
        interface = self.interface(SynchronizationManager(), self.source, storage=False)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await self.communication(interface).start()
        self.assertTrue(status["publication_confirmed"])
        self.assertTrue(status["acceptance_confirmed"])
        self.assertFalse(status["archival_confirmed"])
        self.assertIn("StorageManager", status["preservation_warning"])
        self.assertEqual(interface.evidence[0].to_dict(), status["evidence"])
        self.assertTrue(interface.service.check_ready().ready)

    async def test_unavailable_ingestor_warns_and_publication_is_not_acceptance(self):
        await self.intake_subscription.unsubscribe()
        interface = self.interface(SynchronizationManager(), self.source, ingestor=False)
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            status = await self.communication(interface).start()
        self.assertTrue(status["publication_confirmed"])
        self.assertFalse(status["acceptance_confirmed"])
        self.assertFalse(status["archival_confirmed"])
        self.assertTrue(status["preservation_warning"])
        self.assertEqual(len(interface.evidence), 1)

    async def test_archive_failure_preserves_accepted_producer_obligation(self):
        interface = self.interface(SynchronizationManager(), self.source)
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=OSError("disk full")):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                status = await self.communication(interface).start()
        self.assertTrue(status["acceptance_confirmed"])
        self.assertFalse(status["archival_confirmed"])
        self.assertIn("disk full", status["preservation_warning"])
        command = RuntimeCommandMessage("stop", None, "stop", "administrator", "sync",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"})
        # Restored archival can preserve the original obligation, without replaying it.
        result = await interface.execute_command(command)
        self.assertTrue(result.success, result.reason)
        archived = self.storage.get_framework_preservation_confirmation()["runtime_evidence"]
        self.assertIn(status["evidence"], archived)

    async def test_administrator_resume_drop_records_choice_without_executing_or_clearing_work(self):
        sync = SynchronizationManager()
        adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True, declared_capabilities=())
        node = AcquisitionNode(device_manager=DeviceManager((adapter,)), synchronization_manager=sync,
            ingestor=self.ingestor, node_id="node", role="acquisition",
            error_evidence_location=str(self.root / "errors"))
        self.assertTrue(node.reserve("unfinished-session"))
        participant = RuntimeParticipant("acquisition_node", "node")
        interface = self.interface(node, participant)
        status = await self.communication(interface).start()
        payload = status["evidence"]["payload"]
        self.assertIn("Outstanding Session reservation", payload["remaining_obligations"])
        self.assertTrue(payload["service_readiness"]["ready"])
        self.assertEqual(payload["acquisition_node_readiness"]["reserved_for_session_id"], "unfinished-session")
        for choice in ("resume", "drop"):
            result = await interface.record_administrator_decision("operator", choice,
                {"session_id": "unfinished-session", "reason": "manual choice"})
            self.assertTrue(result["archival_confirmed"])
            decision = result["evidence"]["payload"]
            self.assertEqual(decision["decision"], choice)
            self.assertEqual(decision["actions"], [])
            self.assertIsNone(decision["outcome"])
            self.assertEqual(node.reserved_for_session_id, "unfinished-session")
        self.assertFalse(node.reserve("unrelated-session"))
        # Reservation protection does not stop unrelated evidence intake/storage work.
        unrelated = RuntimeEvidenceMessage("unrelated", None, "warning", "other", {}, True)
        self.assertTrue(self.ingestor.receive_runtime_evidence(unrelated).accepted)
        self.assertTrue(node.release_reservation("unfinished-session"))
        self.assertTrue(node.reserve("next-session"))

    async def test_required_nats_failure_does_not_claim_successful_startup(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        communication._boundary.available = False
        with self.assertRaisesRegex(ConnectionError, "NATS"):
            await communication.start()
        self.assertEqual(interface.evidence, ())

    async def test_retired_service_cannot_bypass_reuse_protections_by_announcing(self):
        interface = self.interface(SynchronizationManager(), self.source)
        command = RuntimeCommandMessage("stop", None, "stop", "administrator", "sync",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"})
        self.assertTrue((await interface.execute_command(command)).success)
        with self.assertRaisesRegex(RuntimeError, "reuse protections"):
            await self.communication(interface).start()

    async def test_overlapping_start_calls_publish_once(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        first, second = await asyncio.gather(communication.start(), communication.start())
        self.assertEqual(first, second)
        self.assertEqual(len(self.evidence()), 1)

    async def test_active_startup_publication_blocks_retirement_and_preserves_original_evidence(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        started, finish = asyncio.Event(), asyncio.Event()

        async def publish(message):
            if message.evidence_type == "service_readiness":
                started.set()
                await finish.wait()
            await communication._boundary.publish_evidence(message)

        interface.evidence_publisher = publish
        task = asyncio.create_task(communication.start())
        try:
            await started.wait()
            command = RuntimeCommandMessage("stop", None, "stop", "administrator", "sync",
                {"stop_attempt_id": "attempt", "administrator_id": "operator"})
            result = await interface.execute_command(command)
            self.assertEqual(result.payload["outcome"], "blocked")
            self.assertIn("Unfinished service operations", result.payload["attempt"]["blockers"])
            self.assertFalse(interface.terminated)
        finally:
            finish.set()
            status = await task
        self.assertTrue(status["archival_confirmed"])
        self.assertIn(status["evidence"], self.storage.get_framework_preservation_confirmation()["runtime_evidence"])

    async def test_cancellation_retains_producer_obligation_and_service_binding(self):
        interface = self.interface(SynchronizationManager(), self.source)
        communication = self.communication(interface)
        started = asyncio.Event()

        async def publish(message):
            started.set()
            await asyncio.Event().wait()

        interface.evidence_publisher = publish
        task = asyncio.create_task(communication.start())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(interface.evidence), 1)
        self.assertFalse(interface.terminated)
        self.assertTrue(interface.service.check_ready().ready)
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(interface.evidence[0]))

    async def test_old_request_cannot_replace_readiness_after_communication_returns(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        original = SynchronizationManager()
        source = self.interface(original, self.source)
        await self.communication(source).start()
        boundary = _Boundary("synchronization_manager", "sync", self.broker)
        subscriptions = await NatsSynchronizationManagerCommunication(boundary, original).subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        started, finish = asyncio.Event(), asyncio.Event()
        publish_result = boundary.publish_command_result

        async def delayed_result(message, message_type):
            started.set()
            await finish.wait()
            await publish_result(message, message_type)

        with patch.object(boundary, "publish_command_result", new=delayed_result):
            task = asyncio.create_task(communication.check_dependency_readiness(self.source, 1))
            try:
                await started.wait()
                await communication.close()
                await communication.start()
                unready = ServiceReadiness("sync", "synchronization_manager", True, False, "current_unready")
                with patch.object(original, "check_ready", return_value=unready):
                    await source.announce_readiness(startup=True)
            finally:
                finish.set()
            with self.assertRaisesRegex(RuntimeError, "earlier communication binding"):
                await task
        self.assertFalse(observer.dependency_readiness[self.source].ready)
        self.assertEqual(observer.last_known_dependency_readiness[self.source].reason, "current_unready")

    async def test_storage_and_controller_readiness_commands_use_existing_result_path(self):
        participant = RuntimeParticipant("storage_manager", "storage-peer")
        peer = self.interface(self.storage, participant)
        peer_communication = self.communication(peer)
        await peer_communication.start()
        subscriptions = await peer_communication.subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        observer = self.interface(Controller(), self.observer, (participant,))
        communication = self.communication(observer)
        await communication.start()
        report = await communication.check_dependency_readiness(participant, 0)
        self.assertTrue(report.ready)
        self.assertEqual(self.broker.commands[-1]["command_type"], "check_readiness")

    async def test_delayed_readiness_result_cannot_overwrite_newer_same_binding_announcement(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        dependency = RuntimeParticipant("storage_manager", "disk")
        original = SynchronizationManager()
        source = self.interface(original, self.source, (dependency,))
        source.receive_dependency_readiness(dependency,
            ServiceReadiness("disk", "storage_manager", True, True, "ready"))
        await self.communication(source).start()
        boundary = _Boundary("synchronization_manager", "sync", self.broker)
        subscriptions = await NatsSynchronizationManagerCommunication(boundary, original).subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        started, finish = asyncio.Event(), asyncio.Event()
        publish_result = boundary.publish_command_result

        async def delayed_result(message, message_type):
            self.assertTrue(message.payload["service_readiness"]["ready"])
            started.set()
            await finish.wait()
            await publish_result(message, message_type)

        with patch.object(boundary, "publish_command_result", new=delayed_result):
            task = asyncio.create_task(communication.check_dependency_readiness(self.source, 1))
            try:
                await asyncio.wait_for(started.wait(), 5)
                source.receive_dependency_readiness(dependency,
                    ServiceReadiness("disk", "storage_manager", True, False, "disk_failure"))
                await source.announce_readiness()
                newer = observer.dependency_readiness[self.source]
                self.assertFalse(newer.ready)
                evidence_count = len(observer.evidence)
            finally:
                finish.set()
                result = await task
        self.assertEqual(result, newer)
        self.assertEqual(observer.dependency_readiness[self.source], newer)
        self.assertEqual(observer.last_known_dependency_readiness[self.source], newer)
        self.assertFalse(controller.check_ready().ready)
        self.assertEqual(len(observer.evidence), evidence_count)

    async def test_unresolved_group_results_invalidate_only_missing_dependencies(self):
        missing = RuntimeParticipant("synchronization_manager", "missing")
        outside_group = RuntimeParticipant("synchronization_manager", "outside")
        unconfigured = RuntimeParticipant("synchronization_manager", "unconfigured")
        observer = self.interface(Controller(), self.observer, (self.source, missing, outside_group))
        communication = self.communication(observer)
        await communication.start()
        responding_service = SynchronizationManager()
        for participant, service in ((self.source, responding_service),
                                     (missing, SynchronizationManager()),
                                     (outside_group, SynchronizationManager())):
            await self.communication(self.interface(service, participant)).start()
        subscriptions = await NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), responding_service).subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        issuer = NatsControllerCommunication(communication._boundary)
        self.addAsyncCleanup((await issuer.subscribe_command_results("group-session")).unsubscribe)
        participants = (self.source, missing, unconfigured)
        before = observer.last_known_dependency_readiness
        await issuer.publish_group_command("group-loss", "group-session", "check_readiness",
            "synchronization_manager", participants, {})
        outcome = await issuer.await_group_command_outcome("group-loss", "group-session", "check_readiness",
            "synchronization_manager", participants, 0)
        self.assertEqual(outcome.outcome, "unresolved")
        self.assertEqual([item.expected_target_id for item in outcome.unresolved_outcomes],
                         ["missing", "unconfigured"])
        self.assertIsNone(observer.dependency_readiness[missing])
        self.assertTrue(observer.dependency_readiness[self.source].ready)
        self.assertTrue(observer.dependency_readiness[outside_group].ready)
        self.assertEqual(observer.last_known_dependency_readiness, before)
        self.assertNotIn(unconfigured, observer.dependency_readiness)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            observer.service.check_ready()

    async def test_overlapping_readiness_checks_preserve_later_check_in_either_delivery_order(self):
        for newer_first in (False, True):
            with self.subTest(newer_first=newer_first):
                suffix = str(newer_first).lower()
                participant = RuntimeParticipant("synchronization_manager", "sync-" + suffix)
                target = RuntimeParticipant("controller", "observer-" + suffix)
                observer = self.interface(Controller(), target, (participant,))
                communication = self.communication(observer)
                await communication.start()
                dependency = RuntimeParticipant("storage_manager", "disk")
                service = SynchronizationManager()
                source = self.interface(service, participant, (dependency,))
                source.receive_dependency_readiness(dependency,
                    ServiceReadiness("disk", "storage_manager", True, True, "ready"))
                await self.communication(source).start()
                boundary = _Boundary(participant.component_type, participant.component_id, self.broker)
                subscriptions = await NatsSynchronizationManagerCommunication(boundary, service).subscribe_commands()
                for subscription in subscriptions:
                    self.addAsyncCleanup(subscription.unsubscribe)
                started = (asyncio.Event(), asyncio.Event())
                finish = (asyncio.Event(), asyncio.Event())
                publish_result = boundary.publish_command_result
                calls = []

                async def delayed_result(message, message_type):
                    index = len(calls)
                    calls.append(message)
                    started[index].set()
                    await finish[index].wait()
                    await publish_result(message, message_type)

                with patch.object(boundary, "publish_command_result", new=delayed_result):
                    first = asyncio.create_task(communication.check_dependency_readiness(participant, 1))
                    second = None
                    try:
                        await asyncio.wait_for(started[0].wait(), 5)
                        source.receive_dependency_readiness(dependency,
                            ServiceReadiness("disk", "storage_manager", True, False, "disk_failure"))
                        second = asyncio.create_task(communication.check_dependency_readiness(participant, 1))
                        await asyncio.wait_for(started[1].wait(), 5)
                        self.assertTrue(calls[0].payload["service_readiness"]["ready"])
                        self.assertFalse(calls[1].payload["service_readiness"]["ready"])
                        order = (1, 0) if newer_first else (0, 1)
                        tasks = (first, second)
                        for index in order:
                            finish[index].set()
                            await tasks[index]
                    finally:
                        for event in finish:
                            event.set()
                        await asyncio.gather(*(task for task in (first, second) if task is not None))
                self.assertFalse(observer.dependency_readiness[participant].ready)
                self.assertFalse(observer.last_known_dependency_readiness[participant].ready)
                self.assertFalse(observer.service.check_ready().ready)

    async def test_group_publication_failure_invalidates_only_attempted_failed_dependency(self):
        failing = RuntimeParticipant("synchronization_manager", "failing")
        unattempted = RuntimeParticipant("synchronization_manager", "unattempted")
        participants = (self.source, failing, unattempted)
        observer = self.interface(Controller(), self.observer, participants)
        communication = self.communication(observer)
        await communication.start()
        for participant in participants:
            await self.communication(self.interface(SynchronizationManager(), participant)).start()
        before = observer.last_known_dependency_readiness
        attempted = []
        publish = self.broker.publish

        async def fail_second_publication(subject, data, stream):
            if stream == "LAB_COMMANDS":
                target = json.loads(data)["target_id"]
                attempted.append(target)
                if target == "failing":
                    raise OSError("JetStream publication unavailable")
            return await publish(subject, data, stream)

        issuer = NatsControllerCommunication(communication._boundary)
        with patch.object(self.broker, "publish", new=fail_second_publication):
            with self.assertRaisesRegex(DurablePublicationError, "publication unavailable"):
                await issuer.publish_group_command("group-publication", "group-session", "check_readiness",
                    "synchronization_manager", participants, {})
        self.assertEqual(attempted, ["sync", "failing"])
        self.assertIsNone(observer.dependency_readiness[failing])
        self.assertTrue(observer.dependency_readiness[self.source].ready)
        self.assertTrue(observer.dependency_readiness[unattempted].ready)
        self.assertEqual(observer.last_known_dependency_readiness, before)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            observer.service.check_ready()

    async def test_started_services_preserve_evidence_through_existing_coordinated_shutdown(self):
        framework = shutdown_fixtures.FrameworkShutdownTests()
        await framework.asyncSetUp()
        self.addCleanup(framework.temporary.cleanup)
        announcements = []
        for participant in framework.scope:
            communication = NatsServiceMaintenanceCommunication(
                _Boundary(participant.component_type, participant.component_id, framework.broker),
                framework.interfaces[participant.component_type],
                startup_result_window_s=0.01 if participant.component_type == "controller" else None)
            self.addAsyncCleanup(communication.close)
            status = await communication.start()
            self.assertTrue(status["archival_confirmed"])
            announcements.append(status["evidence"])
        result = await framework.shutdown()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["outcome"], "completed")
        archive = framework.storage.get_framework_preservation_confirmation()
        for message in announcements:
            self.assertIn(message, archive["runtime_evidence"])
        self.assertTrue(all(interface.terminated for interface in framework.interfaces.values()))

    async def test_failed_subscription_cleanup_blocks_return_until_confirmed(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        source = self.interface(SynchronizationManager(), self.source)
        await self.communication(source).start()
        subscription = next(s for s in self.broker.subscriptions
                            if s.subject == "messages.command_result.*.*.*")
        with patch.object(subscription, "unsubscribe", new=AsyncMock(side_effect=OSError("disconnect failure"))):
            with self.assertRaises(OSError):
                await communication.close()
            with self.assertRaisesRegex(RuntimeError, "cleanup remains unconfirmed"):
                await communication.start()
            with self.assertRaisesRegex(RuntimeError, "subscriptions are not active"):
                await communication.check_dependency_readiness(self.source, 0)
        self.assertIsNone(observer.dependency_readiness[self.source])
        self.assertTrue(observer.last_known_dependency_readiness[self.source].ready)
        self.assertFalse(observer.terminated)
        await communication.close()
        await communication.start()
        await source.announce_readiness(startup=True)
        self.assertTrue(controller.check_ready().ready)

    async def test_active_dependency_request_blocks_retirement_until_operation_finishes(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        original = SynchronizationManager()
        source = self.interface(original, self.source)
        await self.communication(source).start()
        boundary = _Boundary("synchronization_manager", "sync", self.broker)
        subscriptions = await NatsSynchronizationManagerCommunication(boundary, original).subscribe_commands()
        for subscription in subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)
        started, finish = asyncio.Event(), asyncio.Event()
        publish_result = boundary.publish_command_result

        async def delayed_result(message, message_type):
            started.set()
            await finish.wait()
            await publish_result(message, message_type)

        with patch.object(boundary, "publish_command_result", new=delayed_result):
            task = asyncio.create_task(communication.check_dependency_readiness(self.source, 1))
            try:
                await started.wait()
                command = RuntimeCommandMessage("stop", None, "stop", "administrator", "observer",
                    {"stop_attempt_id": "attempt", "administrator_id": "operator"})
                result = await observer.execute_command(command)
                self.assertEqual(result.payload["outcome"], "blocked")
                self.assertIn("Unfinished service operations", result.payload["attempt"]["blockers"])
                self.assertFalse(observer.terminated)
            finally:
                finish.set()
            self.assertTrue((await task).ready)

    async def test_existing_command_issuer_invalidates_the_same_service_owned_readiness(self):
        controller, observer, communication = self.observer_pair()
        await communication.start()
        source = self.interface(SynchronizationManager(), self.source)
        await self.communication(source).start()
        role_communication = NatsControllerCommunication(communication._boundary)
        subscription = await role_communication.subscribe_command_results(None)
        self.addAsyncCleanup(subscription.unsubscribe)
        result = await role_communication.request_command(self.source, "check_readiness", None, {}, 0)
        self.assertIsNone(result)
        self.assertIsNone(observer.dependency_readiness[self.source])
        self.assertTrue(observer.last_known_dependency_readiness[self.source].ready)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            controller.check_ready()
