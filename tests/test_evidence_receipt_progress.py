"""Native receiving obligations and durable intake without broker history audits."""
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, NatsCommunicationBoundary, NatsIngestorCommunication, RuntimeEvidenceMessage
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


@unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
class EvidenceReceiptProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.url = await self.stack.enter_async_context(temporary_jetstream_server())
        self.boundary = await self.connect("ingestor", "intake")
        self.producer = await self.connect("controller", "controller")
        self.path = self.root / "session.jsonl"
        self.intake = InMemoryIngestor(session_id="A", recovery_journal_path=self.path)
        self.receiver = NatsIngestorCommunication(self.boundary, self.intake)
        self.subscription = await self.receiver.subscribe_evidence("A")
        self.js = self.boundary._require_jetstream()

    async def connect(self, kind, identity):
        boundary = NatsCommunicationBoundary(kind, identity, (self.url,))
        await boundary.connect()
        self.stack.push_async_callback(boundary.close)
        await boundary.ensure_streams()
        return boundary

    def evidence(self, identity, *, marker=False, payload=None):
        return RuntimeEvidenceMessage(identity, "A", "acquisition_evidence_completion" if marker else "event",
            "controller", payload or {}, not marker)

    async def publish(self, message):
        await self.producer.publish_evidence(message)
        self.assertTrue(await self.intake.await_durable_runtime_evidence(message, 2))
        async with asyncio.timeout(2):
            while True:
                info = await self.subscription.consumer_info()
                if not info.num_pending and not info.num_ack_pending:
                    return
                await asyncio.sleep(0)

    async def test_acknowledged_history_can_disappear_without_losing_durable_receipt(self):
        first, marker = self.evidence("first"), self.evidence("marker", marker=True)
        await self.publish(first)
        await self.publish(marker)
        self.assertEqual((await self.js.stream_info("LAB_EVIDENCE")).state.messages, 0)
        with patch.object(self.js, "get_msg", side_effect=AssertionError("historical broker read")):
            proof = await self.receiver.verify_acquisition_evidence_receipt(marker)
        self.assertTrue(proof["durable_receipt_confirmed"], proof)
        self.assertEqual(self.intake.accepted_runtime_evidence, (first, marker))
        self.assertEqual(self.intake.runtime_evidence_audit, ())

    async def test_restart_uses_journal_not_acknowledged_broker_records(self):
        marker = self.evidence("marker", marker=True)
        await self.publish(self.evidence("first"))
        await self.publish(marker)
        await self.boundary.close()
        self.boundary = await self.connect("ingestor", "intake")
        self.intake = InMemoryIngestor(session_id="A", recovery_journal_path=self.path)
        self.receiver = NatsIngestorCommunication(self.boundary, self.intake)
        self.subscription = await self.receiver.subscribe_evidence("A")
        self.assertTrue((await self.receiver.verify_acquisition_evidence_receipt(marker))["durable_receipt_confirmed"])

    async def test_marker_does_not_override_pending_delivery(self):
        from nats.aio.msg import Msg
        entered, resume = asyncio.Event(), asyncio.Event()
        original = Msg.ack_sync
        async def held(message, *args, **kwargs):
            if json.loads(message.data)["evidence_id"] == "first":
                entered.set()
                await resume.wait()
            return await original(message, *args, **kwargs)
        marker = self.evidence("marker", marker=True)
        with patch.object(Msg, "ack_sync", held):
            await self.producer.publish_evidence(self.evidence("first"))
            await asyncio.wait_for(entered.wait(), 2)
            self.intake.receive_runtime_evidence(marker)
            proof = await self.receiver.verify_acquisition_evidence_receipt(marker)
            self.assertFalse(proof["durable_receipt_confirmed"], proof)
            resume.set()
            await self.publish(marker)
        self.assertTrue((await self.receiver.verify_acquisition_evidence_receipt(marker))["durable_receipt_confirmed"])

    async def test_physical_journal_damage_cannot_use_cached_acceptance(self):
        marker = self.evidence("marker", marker=True)
        await self.publish(self.evidence("first"))
        await self.publish(marker)
        self.path.write_bytes(b"corrupt\n")
        self.assertFalse((await self.receiver.verify_acquisition_evidence_receipt(marker))["durable_receipt_confirmed"])

    async def test_identical_duplicates_do_not_append_but_changed_content_conflicts(self):
        first = self.evidence("first", payload={"value": True})
        await self.publish(first)
        before = self.path.read_bytes()
        await self.publish(first)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.intake.receive_runtime_evidence(self.evidence("first", payload={"value": 1}))
        self.assertEqual(self.path.read_bytes(), before)

    async def test_durability_failure_leaves_native_delivery_outstanding(self):
        failed = asyncio.Event()
        original = self.intake.receive_runtime_evidence
        def receive(message):
            try:
                with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("unconfirmed durability")):
                    return original(message)
            finally:
                failed.set()
        with patch.object(self.intake, "receive_runtime_evidence", receive):
            await self.producer.publish_evidence(self.evidence("first"))
            await asyncio.wait_for(failed.wait(), 2)
        self.assertEqual((await self.subscription.consumer_info()).num_ack_pending, 1)
        self.assertFalse((await self.receiver.verify_acquisition_evidence_receipt(
            self.evidence("marker", marker=True)))["durable_receipt_confirmed"])
