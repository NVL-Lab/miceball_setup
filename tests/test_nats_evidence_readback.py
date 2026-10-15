"""Operational evidence compilation, receipt and preservation use owner-confirmed NATS readback."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    InMemoryIngestor, NatsControllerCommunication,
    NatsIngestorCommunication, NatsStorageManagerCommunication,
    PersistentStorageManager, RuntimeEvidenceMessage, RuntimeParticipant,
)
from tests.test_session_launch import _Boundary, _Broker
from tests import test_storage as record_fixtures
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker


class EvidenceReadbackBroker(_Broker):
    async def subscribe(self, subject, cb, **options):
        subscription = await super().subscribe(subject, cb, **options)
        if options.get("durable"):
            self.callbacks[options["durable"]] = cb
        if ".command_result." in subject and options.get("config") is None:
            for result in self.results:
                await cb(SimpleNamespace(data=json.dumps(result).encode(), ack=AsyncMock()))
        return subscription

    async def publish(self, subject, data, stream):
        if stream == "LAB_EVIDENCE":
            return await EvidenceReceiptBroker.publish(self, subject, data, stream)
        return await super().publish(subject, data, stream)


class NatsEvidenceReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.broker = EvidenceReadbackBroker()
        self.storage = PersistentStorageManager(self.root, component_id="storage")
        self.ingestor = InMemoryIngestor(session_id="session",
            recovery_journal_path=self.root / "journal.jsonl", component_id="intake")
        self.store_peer = RuntimeParticipant("storage_manager", "storage")
        self.intake_peer = RuntimeParticipant("ingestor", "intake")
        self.writer = NatsStorageManagerCommunication(
            _Boundary("storage_manager", "storage", self.broker), self.storage)
        self.intake_boundary = _Boundary("ingestor", "intake", self.broker)
        self.intake = NatsIngestorCommunication(self.intake_boundary, self.ingestor)
        for subscription in await self.writer.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        for subscription in await self.intake.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)


    async def request(self, peer, operation, payload=None, *, session="session", identity="read"):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        return await requests.request_persistence_command(peer, operation, session, payload or {},
            0.01, command_id=identity)


    async def test_existing_readiness_command_reports_the_storage_owner(self):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        subscription = await requests.subscribe_command_results(None)
        try:
            result = await requests.request_command(self.store_peer, "check_readiness", None, {},
                0.01, command_id="ready")
        finally:
            await subscription.unsubscribe()
        self.assertTrue(result.success)
        self.assertEqual(result.payload["service_readiness"]["component_id"], "storage")

    async def test_exact_acceptance_requires_journal_intake_not_publication(self):
        message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
        await self.intake.subscribe_evidence("session")
        producer = _Boundary("acquisition_node", "node", self.broker)
        await producer.publish_evidence(message)
        pending = await self.request(self.intake_peer, "read_runtime_evidence_acceptance", {"evidence": message.to_dict()})
        self.assertFalse(pending.success)
        consumer = next(iter(self.broker.consumers))
        await self.broker.deliver(consumer, self.broker.last_sequence)
        before = self.ingestor.recovery_journal_path.read_bytes()
        await self.broker.deliver(consumer, self.broker.last_sequence)
        confirmed = await self.request(self.intake_peer, "read_runtime_evidence_acceptance", {"evidence": message.to_dict()})
        self.assertTrue(confirmed.success, confirmed.reason)
        self.assertTrue(confirmed.payload["durable_acceptance_confirmed"])
        self.assertNotIn("archival_confirmed", confirmed.payload)
        self.assertEqual(self.ingestor.recovery_journal_path.read_bytes(), before)
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 1)
        conflict = replace(message, payload={"changed": True})
        rejected = await self.request(self.intake_peer, "read_runtime_evidence_acceptance", {"evidence": conflict.to_dict()})
        self.assertFalse(rejected.success)
        self.ingestor.recovery_journal_path.write_text("damaged", encoding="utf-8")
        damaged = await self.request(self.intake_peer, "read_runtime_evidence_acceptance", {"evidence": message.to_dict()})
        self.assertFalse(damaged.success)

    async def test_misrouted_evidence_is_not_accepted_or_acknowledged(self):
        await self.intake.subscribe_evidence("session")
        consumer = next(iter(self.broker.consumers))
        for change in ({"session_id": "other"}, {"source_id": "other"}, {"evidence_type": "other"}):
            with self.subTest(change=change):
                message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
                forged = replace(message, **change)
                await self.broker.publish("messages.session.evidence.acquisition_node.node.acquisition_health",
                    json.dumps(forged.to_dict()).encode(), "LAB_EVIDENCE")
                with self.assertRaisesRegex(ValueError, "NATS subject"):
                    await self.broker.deliver(consumer, self.broker.last_sequence)
        self.assertEqual(self.ingestor.accepted_runtime_evidence, ())
        self.assertEqual(self.broker.consumers[consumer].ack_floor.consumer_seq, 0)

    async def test_failed_journal_delivery_recovers_after_restart_without_duplicate(self):
        await self.intake.subscribe_evidence("session")
        consumer = next(iter(self.broker.consumers))
        message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
        await _Boundary("acquisition_node", "node", self.broker).publish_evidence(message)
        sequence = self.broker.last_sequence
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("injected journal failure")):
            with self.assertRaises(OSError):
                await self.broker.deliver(consumer, sequence)
        self.assertEqual(self.broker.consumers[consumer].ack_floor.consumer_seq, 0)
        restored = InMemoryIngestor(session_id="session", recovery_journal_path=self.ingestor.recovery_journal_path,
                                    component_id="intake")
        receiver = NatsIngestorCommunication(self.intake_boundary, restored)
        await receiver.subscribe_evidence("session")
        await self.broker.deliver(consumer, sequence)
        await self.broker.deliver(consumer, sequence)
        self.assertTrue(restored.has_durable_runtime_evidence(message))
        self.assertEqual(sum(item.evidence_id == message.evidence_id
                             for item in restored.accepted_runtime_evidence), 1)

    async def test_acceptance_readback_rejects_wrong_session_and_stale_replies(self):
        message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
        self.ingestor.receive_runtime_evidence(message)
        payload = {"evidence": message.to_dict()}
        self.assertFalse((await self.request(self.intake_peer, "read_runtime_evidence_acceptance", payload, session="other")).success)
        good = await self.request(self.intake_peer, "read_runtime_evidence_acceptance", payload)
        self.assertTrue(good.success)
        old = self.broker.results[-1]
        self.broker.change_result = lambda operation, current: old
        self.assertIsNone(await self.request(self.intake_peer, "read_runtime_evidence_acceptance", payload))
        self.broker.change_result = None
        self.broker.drop_results.add(("intake", "read_runtime_evidence_acceptance"))
        self.assertIsNone(await self.request(self.intake_peer, "read_runtime_evidence_acceptance", payload))

    async def test_cancelled_intake_callback_redelivers_without_duplicate_acceptance(self):
        message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
        entered, resume = asyncio.Event(), asyncio.Event()
        calls = []

        async def callback(evidence):
            calls.append(evidence.evidence_id)
            entered.set()
            await resume.wait()

        await self.intake.subscribe_evidence("session", callback)
        consumer = next(iter(self.broker.consumers))
        await _Boundary("acquisition_node", "node", self.broker).publish_evidence(message)
        task = asyncio.create_task(self.broker.deliver(consumer, self.broker.last_sequence))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertTrue(self.ingestor.has_durable_runtime_evidence(message))
            self.assertEqual(self.broker.consumers[consumer].ack_floor.consumer_seq, 0)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await self.broker.deliver(consumer, self.broker.last_sequence)
        self.assertEqual(calls, [message.evidence_id])
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 1)

    async def test_recovery_command_cannot_bypass_existing_administrator_interface(self):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        subscription = await requests.subscribe_command_results(None)
        try:
            result = await requests.request_command(self.store_peer, "recover_archive_write", None,
                {"authorization_evidence_id": "missing", "obligation": {"session_id": "session"}},
                0.01, command_id="unauthorized")
        finally:
            await subscription.unsubscribe()
        self.assertFalse(result.success)


    async def test_compilation_is_journal_verified_and_not_an_archival_claim(self):
        persistent = RuntimeEvidenceMessage("persistent", "session", "note", "node", {}, True)
        transient = RuntimeEvidenceMessage("transient", "session", "note", "node", {})
        for message in (persistent, transient):
            self.ingestor.receive_runtime_evidence(message)
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("", "session", "note", "node", {}))
        result = await self.request(self.intake_peer, "compile_session_evidence")
        self.assertTrue(result.success)
        self.assertTrue(result.payload["journal_coverage_confirmed"])
        self.assertEqual(result.payload["runtime_evidence"], [persistent.to_dict()])
        self.assertEqual(len(result.payload["ingest_audit"]), 3)
        self.assertNotIn("archival_confirmed", result.payload)
        self.ingestor.recovery_journal_path.write_text("corrupted", encoding="utf-8")
        refused = await self.request(self.intake_peer, "compile_session_evidence", identity="again")
        self.assertFalse(refused.success)

    async def test_compilation_rejects_unrelated_session_without_changing_intake(self):
        before = self.ingestor.accepted_runtime_evidence
        result = await self.request(self.intake_peer, "compile_session_evidence", session="other")
        self.assertFalse(result.success)
        self.assertEqual(self.ingestor.accepted_runtime_evidence, before)

    async def test_missing_and_stale_readback_replies_cannot_confirm_preservation(self):
        self.preserve_session()
        directory = self.root / "session_session"
        before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        self.broker.drop_results.add(("storage", "read_session_preservation"))
        self.assertIsNone(await self.request(self.store_peer, "read_session_preservation"))
        old_reply = self.broker.results[-1]
        self.broker.drop_results.clear()
        self.broker.change_result = lambda operation, current: old_reply
        self.assertIsNone(await self.request(self.store_peer, "read_session_preservation"))
        self.broker.change_result = None
        result = await self.request(self.store_peer, "read_session_preservation")
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["archival_confirmed"])
        self.assertEqual({p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}, before)

    async def test_mismatched_owner_reply_cannot_confirm_compilation(self):
        self.broker.change_result = lambda operation, current: {**current, "source_id": "other-intake"}
        self.assertIsNone(await self.request(self.intake_peer, "compile_session_evidence"))
        self.broker.change_result = None
        result = await self.request(self.intake_peer, "compile_session_evidence")
        self.assertTrue(result.success, result.reason)


    async def test_receipt_verification_uses_owner_consumer_and_rejects_missing_ack_progress(self):
        subscription = await self.intake.subscribe_evidence("session")
        self.addAsyncCleanup(subscription.unsubscribe)
        consumer = next(iter(self.broker.consumers))
        producer = _Boundary("controller", "controller", self.broker)
        marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        await producer.publish_evidence(marker)
        await self.broker.deliver(consumer, self.broker.last_sequence)
        result = await self.request(self.intake_peer, "verify_acquisition_receipt", {"marker": marker.to_dict()})
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["durable_receipt_confirmed"])
        self.broker.consumers[consumer].ack_floor.stream_seq = 0
        failed = await self.request(self.intake_peer, "verify_acquisition_receipt",
            {"marker": marker.to_dict()}, identity="recheck")
        self.assertFalse(failed.success)
        self.assertFalse(failed.payload["durable_receipt_confirmed"])

    def preserve_session(self):
        marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        self.ingestor.receive_runtime_evidence(marker)
        record = record_fixtures.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        self.storage.write_acquisition_stage("session", self.ingestor.compile_persistent_runtime_evidence(),
            receipt={"session_id": "session", "durable_receipt_confirmed": True,
                     "evidence_id": "marker", "marker_stream_sequence": 1},
            **record)
        self.storage.write_artifact_collection_handoff("session", self.ingestor.compile_artifact_collection_handoff("session"))

    async def test_preservation_readback_is_current_after_restart_and_detects_corruption(self):
        self.preserve_session()
        for subscription in self.broker.subscriptions:
            if ".command.storage_manager.storage." in subscription.subject:
                await subscription.unsubscribe()
        restored = PersistentStorageManager(self.storage.storage_root, component_id="storage")
        handler = NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), restored)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        result = await self.request(self.store_peer, "read_session_preservation")
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["archival_confirmed"])
        self.assertFalse(result.payload["confirmation"]["compilation_summary"]["archive_closed"])
        audit = self.root / "session_session/evidence/ingest_audit.jsonl"
        audit.write_text("", encoding="utf-8")
        before = audit.read_bytes()
        failed = await self.request(self.store_peer, "read_session_preservation", identity="corrupt")
        self.assertFalse(failed.success)
        self.assertFalse(failed.payload["archival_confirmed"])
        self.assertEqual(audit.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
