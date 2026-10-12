"""Historical timing reconciliation without old-map activation or clock restoration."""

import unittest
from unittest.mock import AsyncMock

from lab_sync_acquisition import ServiceMaintenanceInterface, RuntimeParticipant, SynchronizationManager
from tests import test_authorized_recovery as recovery_fixtures


class TimingReconciliationTests(unittest.IsolatedAsyncioTestCase):
    setUp = recovery_fixtures.AuthorizedRecoveryTests.setUp

    def journal_history(self):
        original = SynchronizationManager()
        original.prepare_session("session-a")
        original.start()
        mapping = original.create_and_activate_mapping("session-a", "node", 10, 20, 1, "initial")
        update, = original.mapping_update_evidence
        message = update.to_runtime_evidence_message(evidence_id="historical", source_id="sync")
        self.ingestor.receive_runtime_evidence(message)
        return original, mapping

    def interface_for(self, service):
        return ServiceMaintenanceInterface(service, RuntimeParticipant("synchronization_manager", "sync"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))

    async def test_lost_active_time_reports_history_without_restoring_clock_or_mapping(self):
        original, mapping = self.journal_history()
        before = (self.root / "session.jsonl").read_bytes()
        returned = SynchronizationManager()
        interface = self.interface_for(returned)
        await interface.announce_readiness(startup=True)
        result = await returned.reconcile_timing("session-a", active_session=True, ingestor=self.ingestor)
        self.assertTrue(result["findings"]["continuity_gap"])
        self.assertFalse(result["findings"]["active_synchronization_available"])
        self.assertFalse(result["findings"]["recovery_performed"])
        self.assertTrue(result["findings"]["uncertainty"])
        history, = result["findings"]["historical_mapping_updates"]
        self.assertEqual(history["mapping_update"]["new_mapping"], mapping.to_dict())
        self.assertIsNone(returned.get_active_mapping("session-a", "node"))
        self.assertFalse(returned.is_running)
        self.assertTrue(result["archival_confirmed"])
        self.assertEqual((self.root / "session.jsonl").read_bytes(), before)
        self.assertIs(original.get_active_mapping("session-a", "node"), mapping)
        returned.prepare_session("session-a")
        with self.assertRaisesRegex(RuntimeError, "trustworthy current Session Time"):
            _ = returned.current_session_time_s
        with self.assertRaises(RuntimeError):
            returned.stop()
        with self.assertRaisesRegex(RuntimeError, "restart Session Time"):
            returned.start()
        with self.assertRaises(RuntimeError):
            returned.create_and_activate_mapping("session-a", "node", 10, 20, 1, "old mapping")

    async def test_healthy_mapping_updates_need_no_new_administrator_authorization(self):
        healthy, original = self.journal_history()
        interface = self.interface_for(healthy)
        await interface.announce_readiness(startup=True)
        result = await healthy.reconcile_timing("session-a", active_session=True, ingestor=self.ingestor)
        self.assertFalse(result["findings"]["continuity_gap"])
        self.assertTrue(result["findings"]["time_reference_confirmed"])
        replacement = healthy.replace_active_mapping("session-a", "node", 30, 40, 1, "healthy update")
        self.assertIsNot(original, replacement)
        self.assertEqual(original.local_time_anchor_s, 10)

    async def test_normal_new_session_start_does_not_restore_interrupted_session(self):
        self.journal_history()
        returned = SynchronizationManager()
        self.interface_for(returned)
        await returned.reconcile_timing("session-a", active_session=True, ingestor=self.ingestor)
        returned.prepare_session("session-b")
        self.assertEqual(returned.start(), 0)
        self.assertTrue(returned.is_running)
        self.assertIsNone(returned.get_active_mapping("session-a", "node"))

    async def test_repeated_report_does_not_create_redundant_evidence(self):
        self.journal_history()
        returned = SynchronizationManager()
        interface = self.interface_for(returned)
        await interface.announce_readiness(startup=True)
        first = await returned.reconcile_timing("session-a", active_session=True, ingestor=self.ingestor)
        journal = (self.root / "framework.jsonl").read_bytes()
        second = await returned.reconcile_timing("session-a", active_session=True, ingestor=self.ingestor)
        self.assertTrue(second["unchanged"])
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual((self.root / "framework.jsonl").read_bytes(), journal)

    async def test_unrelated_session_history_is_not_invented_or_activated(self):
        self.journal_history()
        returned = SynchronizationManager()
        self.interface_for(returned)
        result = await returned.reconcile_timing("session-b", active_session=True, ingestor=self.ingestor)
        self.assertFalse(result["findings"]["evidence_context_confirmed"])
        self.assertEqual(result["findings"]["historical_mapping_updates"], [])
        self.assertTrue(result["findings"]["warnings"])
        self.assertIsNone(returned.get_active_mapping("session-b", "node"))
