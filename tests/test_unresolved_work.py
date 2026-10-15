"""Service-owned reporting, explicit abandonment, and guarded producer-copy release."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsControllerCommunication, NatsIngestorCommunication,
    NatsServiceMaintenanceCommunication, NatsSynchronizationManagerCommunication,
    PersistentStorageManager, RuntimeCommandMessage, RuntimeEvidenceMessage,
    RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_session_launch import _Boundary, _Broker
from tests import test_storage as storage_fixtures


class UnresolvedWorkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = PersistentStorageManager(self.root)
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.sync = SynchronizationManager()
        self.adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True,
            declared_capabilities=())
        self.node = AcquisitionNode(device_manager=DeviceManager((self.adapter,)),
            synchronization_manager=self.sync, ingestor=self.ingestor, node_id="node", role="acquisition",
            error_evidence_location=str(self.root / "errors"))
        self.controller = Controller(ingestor=self.ingestor, storage_manager=self.storage,
            synchronization_manager=self.sync)

    def interface(self, service=None, kind="controller"):
        return ServiceMaintenanceInterface(service if service is not None else self.controller,
            RuntimeParticipant(kind, kind), ingestor=self.ingestor, storage_manager=self.storage,
            preservation_window_s=0, close_resources=AsyncMock(return_value=True))

    def command(self, interface, operation="stop", identity="stop"):
        return RuntimeCommandMessage(identity, None, operation, "operator", interface.participant.component_id,
            {"stop_attempt_id": "attempt", "administrator_id": "operator"})

    async def test_each_service_reports_owned_information_through_existing_readiness_command(self):
        self.node.reserve("session-a")
        services = (("controller", self.controller), ("acquisition_node", self.node),
                    ("ingestor", self.ingestor), ("storage_manager", self.storage),
                    ("synchronization_manager", self.sync))
        broker = _Broker()
        for kind, service in services:
            interface = self.interface(service, kind)
            boundary = _Boundary(kind, kind, broker)
            if kind == "acquisition_node":
                handler = NatsAcquisitionNodeCommunication(boundary, service)
            elif kind == "ingestor":
                handler = NatsIngestorCommunication(boundary, service)
            elif kind == "synchronization_manager":
                handler = NatsSynchronizationManagerCommunication(boundary, service)
            else:
                handler = NatsServiceMaintenanceCommunication(boundary, interface)
            for subscription in await handler.subscribe_commands():
                self.addAsyncCleanup(subscription.unsubscribe)
            issuer = NatsControllerCommunication(_Boundary("controller", "client-" + kind, broker))
            self.addAsyncCleanup((await issuer.subscribe_command_results(None)).unsubscribe)
            result = await issuer.request_command(interface.participant, "check_readiness", None, {}, 0)
            self.assertTrue(result.success, result.reason)
            self.assertIn("service_diagnostics", result.payload)
            self.assertIn("blocking_conditions", result.payload["service_diagnostics"])
            if kind == "acquisition_node":
                self.assertEqual(result.payload["service_diagnostics"]["participation"]["reserved_for_session_id"], "session-a")

    async def test_abandonment_does_not_complete_cancelled_attempt_or_release_reserved_resources(self):
        interface = self.interface(self.node, "acquisition_node")
        self.assertTrue(self.node.reserve("session-a"))
        stopped = await interface.execute_command(self.command(interface))
        self.assertEqual(stopped.payload["outcome"], "blocked")
        result = await interface.record_administrator_decision("administrator", "drop",
            {"stop_attempt_id": "attempt", "reason": "do not continue"})
        self.assertEqual(result["evidence"]["payload"]["obligation_outcome"], "abandoned")
        self.assertIsNone(result["evidence"]["payload"]["outcome"])
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertEqual(self.node.reserved_for_session_id, "session-a")
        with self.assertRaisesRegex(RuntimeError, "maintenance"):
            self.node.reserve("session-b")
        cancelled = await interface.execute_command(self.command(interface, "cancel", "cancel"))
        self.assertEqual(cancelled.payload["outcome"], "failed")
        self.assertEqual((await interface.execute_command(self.command(interface))).to_dict(), stopped.to_dict())
        announcement = await interface.announce_readiness()
        attempt = announcement["evidence"]["payload"]["maintenance_attempts"]["attempt"]
        self.assertEqual(attempt["actual_outcome"], "failed")
        self.assertEqual(attempt["obligation_outcome"], "abandoned")
        self.assertEqual(attempt["recovery_assessment"], "administrator_intervention")

    async def test_safe_abandonment_releases_duplicate_history_but_preserves_archive_and_idempotency(self):
        interface = self.interface(self.node, "acquisition_node")
        self.node.reserve("session-a")
        stopped = await interface.execute_command(self.command(interface))
        cancelled = await interface.execute_command(self.command(interface, "cancel", "cancel"))
        original = interface.evidence
        journal_prefix = (self.root / "framework.jsonl").read_bytes()
        record = self.storage.write_initial_session_record("scientific-session",
            **storage_fixtures.PersistentStorageManagerTests._minimal_session_record_evidence("scientific-session"))
        record_bytes = record.read_bytes()
        self.assertTrue(self.node.release_reservation("session-a"))
        result = await interface.record_administrator_decision("administrator", "drop",
            {"stop_attempt_id": "attempt", "reason": "closed without executing stop"})
        release = result["temporary_memory_release"]
        self.assertTrue(release["confirmed"], release)
        self.assertEqual(release["released_evidence_count"], len(original))
        retained = {m.evidence_id for m in interface.evidence}
        self.assertFalse(retained.intersection(m.evidence_id for m in original))
        self.assertTrue(release["preservation"]["archival_confirmed"])
        archive = self.storage.get_framework_preservation_confirmation()
        for message in original:
            self.assertIn(message.to_dict(), archive["runtime_evidence"])
            self.assertTrue(self.ingestor.has_durable_runtime_evidence(message))
        self.assertTrue((self.root / "framework.jsonl").read_bytes().startswith(journal_prefix))
        self.assertEqual(record.read_bytes(), record_bytes)
        self.assertEqual((await interface.execute_command(self.command(interface))).to_dict(), stopped.to_dict())
        self.assertEqual((await interface.execute_command(self.command(interface, "cancel", "cancel"))).to_dict(), cancelled.to_dict())
        self.assertFalse(interface.terminated)

    async def test_archival_failure_retains_abandoned_producer_evidence(self):
        interface = self.interface()
        first = await interface.announce_readiness(startup=True)
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=OSError("disk full")):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await interface.record_administrator_decision("operator", "drop",
                    {"evidence_id": first["evidence"]["evidence_id"], "reason": "retire duplicate copy"})
        self.assertFalse(result["archival_confirmed"])
        # A failed write must not authorize release through an earlier successful archive.
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertIn(first["evidence"], [m.to_dict() for m in interface.evidence])

    async def test_memory_only_unpublished_original_cannot_be_discarded_after_drop(self):
        interface = self.interface()
        interface.evidence_publisher = AsyncMock(side_effect=ConnectionError("publication failed"))
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            first = await interface.announce_readiness(startup=True)
        interface.evidence_publisher = None
        result = await interface.record_administrator_decision("operator", "drop",
            {"evidence_id": first["evidence"]["evidence_id"]})
        self.assertTrue(result["archival_confirmed"])
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertIn(first["evidence"], [m.to_dict() for m in interface.evidence])
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(RuntimeEvidenceMessage.from_dict(first["evidence"])))

    async def test_drop_retains_active_mapping_and_time_obligations(self):
        interface = self.interface(self.sync, "synchronization_manager")
        self.sync.prepare_session("session-a")
        self.sync.start()
        mapping = self.sync.create_and_activate_mapping("session-a", "node", 1.0, 0.0, 1.0, "initial")
        result = await interface.record_administrator_decision("operator", "drop", {"session_id": "session-a"})
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertTrue(self.sync.is_running)
        self.assertEqual(self.sync.get_active_mapping("session-a", "node"), mapping)
        report = self.sync.maintenance_diagnostics(self.ingestor, self.storage)
        self.assertEqual(report["administrative_outcome"], "abandoned")
        self.assertEqual(report["clock_stop_outcome"], "unresolved")
        self.assertEqual(report["mapping_handoffs"][0]["handoff_outcome"], "unresolved")
        with self.assertRaises(RuntimeError):
            self.sync.release_session("session-a", ingestor=self.ingestor)

    async def test_unknown_scope_does_not_authorize_session_memory_release(self):
        interface = self.interface()
        result = await interface.record_administrator_decision("operator", "drop", {"session_id": "unknown"})
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertIn("No accepted", result["temporary_memory_release"]["remaining_obligations"][0])
        self.assertIsNone(self.controller.get_status()["session_id"])

    async def test_unrelated_framework_intake_continues_while_node_remains_reserved(self):
        interface = self.interface(self.node, "acquisition_node")
        self.node.reserve("session-a")
        result = await interface.record_administrator_decision("operator", "drop", {"session_id": "session-a"})
        report = self.node.maintenance_diagnostics(self.ingestor, self.storage)
        self.assertEqual(report["participation"]["administrative_outcome"], "abandoned")
        self.assertIn("Outstanding Session reservation", report["blocking_conditions"])
        message = RuntimeEvidenceMessage("other-scope", None, "warning", "other-service", {}, True)
        self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertFalse(self.node.reserve("session-b"))

    async def test_device_cleanup_completion_requires_actual_confirmed_shutdown(self):
        before = self.node.maintenance_diagnostics(self.ingestor, self.storage)["device_cleanup"][0]
        self.assertIsNone(before["cleanup_outcome"])
        self.adapter.initialize({})
        self.adapter.shutdown()
        after = self.node.maintenance_diagnostics(self.ingestor, self.storage)["device_cleanup"][0]
        self.assertEqual(after["cleanup_outcome"], "completed")

    async def test_unbound_running_clock_keeps_broader_restriction_without_invented_session(self):
        self.sync.start()
        report = self.sync.maintenance_diagnostics(self.ingestor, self.storage)
        self.assertIsNone(report["prepared_session_id"])
        self.assertEqual(report["restricted_timing_scopes"], [])
        self.assertTrue(report["broader_timing_restriction"])
        self.sync.create_and_activate_mapping("session-a", "node", 0.0, 0.0, 1.0, "initial")
        report = self.sync.maintenance_diagnostics(self.ingestor, self.storage)
        self.assertEqual(report["restricted_timing_scopes"], ["session-a"])
        self.assertTrue(report["broader_timing_restriction"])

    async def test_actual_retirement_is_reported_completed_without_fabricated_recovery(self):
        interface = self.interface()
        result = await interface.execute_command(self.command(interface))
        self.assertTrue(result.success)
        self.assertTrue(result.payload["termination_confirmed"])
        broker = _Broker()
        handler = NatsServiceMaintenanceCommunication(_Boundary("controller", "controller", broker), interface)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        issuer = NatsControllerCommunication(_Boundary("controller", "reader", broker))
        self.addAsyncCleanup((await issuer.subscribe_command_results(None)).unsubscribe)
        report = await issuer.request_command(interface.participant, "check_readiness", None, {}, 0)
        self.assertFalse(report.payload["service_readiness"]["ready"])
        attempt = report.payload["maintenance_attempts"]["attempt"]
        self.assertEqual(attempt["actual_outcome"], "completed")
        self.assertEqual(attempt["obligation_outcome"], "completed")
        self.assertIsNone(attempt["recovery_assessment"])

    async def test_journal_failure_is_potentially_recoverable_not_recovered(self):
        journals = self.root / "sessions"
        journals.mkdir()
        intake = InMemoryIngestor(session_id="session-a", recovery_journal_path=journals / "session-a.jsonl")
        message = RuntimeEvidenceMessage("write", "session-a", "warning", "source", {}, True)
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("uncertain append")):
            with self.assertRaises(OSError):
                intake.receive_runtime_evidence(message)
        before = intake.recovery_journal_path.read_bytes()
        report = intake.maintenance_diagnostics(intake, self.storage)
        self.assertTrue(report["journal_integrity_unconfirmed"])
        self.assertEqual(report["known_session_recovery"]["assessment"], "potentially_recoverable")
        self.assertIs(report["known_session_recovery"]["recovered"], False)
        self.assertFalse(intake.check_ready().ready)
        self.assertEqual(intake.recovery_journal_path.read_bytes(), before)
        with self.assertRaises(RuntimeError):
            intake.release_session("session-a", storage_manager=self.storage)

    async def test_storage_reports_failed_write_scope_without_claiming_completion(self):
        original = Path.open
        def fail_summary(path, *args, **kwargs):
            if path.name == "compilation_summary.json" and args and args[0] == "w":
                raise OSError("summary unavailable")
            return original(path, *args, **kwargs)
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("unresolved", None, "warning", "source", {}, True))
        with patch.object(Path, "open", fail_summary), self.assertRaises(OSError):
            self.storage.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())
        report = self.storage.maintenance_diagnostics(self.ingestor, self.storage)
        self.assertEqual(report["unfinished_archive_scopes"], [None])
        self.assertIn("Unfinished persistence", report["blocking_conditions"])
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())

    async def test_storage_diagnostics_do_not_hold_archive_lock_during_intake_confirmation(self):
        storage = PersistentStorageManager(self.root,
            evidence_publisher=AsyncMock(return_value=None))
        await storage.collect_artifacts_with_evidence({"session_id": "session-a", "artifacts": []})
        calls = []
        with ThreadPoolExecutor(max_workers=1) as worker:
            def confirm(message):
                calls.append(message)
                worker.submit(storage.get_framework_preservation_confirmation).result(timeout=5)
                return False
            with patch.object(self.ingestor, "has_durable_runtime_evidence", side_effect=confirm):
                report = storage.maintenance_diagnostics(self.ingestor, storage)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["collection_evidence"][0]["archival_outcome"], "unresolved")
        self.assertEqual(report["collection_evidence"][0]["recovery_assessment"], "administrator_intervention")

    async def test_administrative_abandonment_marker_is_retained_for_resource_protection(self):
        interface = self.interface(self.node, "acquisition_node")
        self.node.reserve("session-a")
        abandoned = await interface.record_administrator_decision("operator", "drop", {"session_id": "session-a"})
        self.node.release_reservation("session-a")
        result = await interface.record_administrator_decision("operator", "drop",
            {"evidence_id": abandoned["evidence"]["evidence_id"]})
        self.assertFalse(result["temporary_memory_release"]["confirmed"])
        self.assertIn(abandoned["evidence"], [m.to_dict() for m in interface.evidence])
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(RuntimeEvidenceMessage.from_dict(abandoned["evidence"])))

    async def test_changed_diagnostics_are_preserved_without_redundant_unchanged_evidence(self):
        interface = self.interface(self.node, "acquisition_node")
        initial = await interface.announce_readiness(startup=True)
        self.node.reserve("session-a")
        changed = await interface.announce_readiness()
        unchanged = await interface.announce_readiness()
        self.assertNotEqual(initial["evidence"]["evidence_id"], changed["evidence"]["evidence_id"])
        self.assertEqual(changed, unchanged)
        self.assertIn("Outstanding Session reservation", changed["evidence"]["payload"]["service_diagnostics"]["blocking_conditions"])
        self.assertTrue(changed["archival_confirmed"])

    async def test_failed_outcome_archival_retains_actual_memory_release_evidence(self):
        interface = self.interface()
        initial = await interface.announce_readiness(startup=True)
        write = self.storage.write_framework_evidence_archive
        calls = []
        def fail_second(compiled):
            calls.append(compiled)
            if len(calls) == 2:
                raise OSError("outcome archival failed")
            return write(compiled)
        with patch.object(self.storage, "write_framework_evidence_archive", new=fail_second):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                result = await interface.record_administrator_decision("operator", "drop",
                    {"evidence_id": initial["evidence"]["evidence_id"]})
        release = result["temporary_memory_release"]
        self.assertTrue(release["confirmed"])
        self.assertFalse(release["preservation"]["archival_confirmed"])
        outcome = release["preservation"]["evidence"]
        self.assertIn(outcome, [m.to_dict() for m in interface.evidence])
        self.assertEqual(outcome["payload"]["actions"], ["temporary_producer_evidence_released"])
        self.assertEqual(outcome["payload"]["obligation_outcome"], "abandoned")
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(RuntimeEvidenceMessage.from_dict(initial["evidence"])))

    async def test_concurrent_service_work_prevents_memory_retirement(self):
        interface = self.interface()
        started, resume = asyncio.Event(), asyncio.Event()
        first = await interface.announce_readiness(startup=True)
        async def publish(message):
            started.set()
            await resume.wait()
            self.ingestor.receive_runtime_evidence(message)
        interface.evidence_publisher = publish
        task = asyncio.create_task(interface.record_administrator_decision("operator", "resume", {"reason": "manual choice"}))
        try:
            await asyncio.wait_for(started.wait(), 5)
            interface.evidence_publisher = None
            result = await interface.record_administrator_decision("operator", "drop",
                {"evidence_id": first["evidence"]["evidence_id"]})
            self.assertFalse(result["temporary_memory_release"]["confirmed"])
            self.assertIn(first["evidence"], [m.to_dict() for m in interface.evidence])
        finally:
            resume.set()
            await task
