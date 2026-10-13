import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nats.js.api import AckPolicy, SequenceInfo
from lab_sync_acquisition import InMemoryIngestor, NatsCommunicationBoundary, NatsIngestorCommunication, RuntimeEvidenceMessage
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


def evidence(identity="marker", session="A", kind="acquisition_evidence_completion", source="controller"):
    return RuntimeEvidenceMessage(identity, session, kind, source, {}, True)


def subject(message):
    component = "controller" if message.evidence_type == "acquisition_evidence_completion" else "acquisition_node"
    return f"messages.{message.session_id}.evidence.{component}.{message.source_id}.{message.evidence_type}"


class EvidenceReceiptProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "journal.jsonl"
        self.broker = EvidenceReceiptBroker()
        self.ingestor = InMemoryIngestor(session_id="A", recovery_journal_path=self.path)
        self.boundary = SimpleNamespace(_require_jetstream=lambda: self.broker)
        self.receiver = NatsIngestorCommunication(self.boundary, self.ingestor)
        await self.receiver.subscribe_evidence("A")
        self.durable = next(iter(self.broker.consumers))

    async def publish(self, message):
        return (await self.broker.publish(subject(message), json.dumps(message.to_dict()).encode())).seq

    async def complete(self):
        marker = evidence()
        await self.broker.deliver(self.durable, await self.publish(marker))
        return marker

    async def proof(self, marker):
        return await self.receiver.verify_acquisition_evidence_receipt(marker)

    async def test_initial_all_history_multiple_producers_and_interleaved_sessions(self):
        first = await self.publish(evidence("first", kind="mapping_update", source="node1"))
        await self.publish(evidence("other", session="B", kind="mapping_update", source="node3"))
        second = await self.publish(evidence("second", kind="mapping_update", source="node2"))
        for sequence in (first, second):
            await self.broker.deliver(self.durable, sequence)
        marker = await self.complete()
        proof = await self.proof(marker)
        self.assertTrue(proof["durable_receipt_confirmed"])
        self.assertEqual(proof["marker_stream_sequence"], 4)
        self.assertEqual(proof["acknowledged_consumer_sequence"], 3)
        self.assertEqual({item.session_id for item in self.ingestor.accepted_runtime_evidence}, {"A"})

    async def test_marker_receipt_does_not_cover_an_earlier_unacked_delivery(self):
        earlier = await self.publish(evidence("early", kind="mapping_update"))
        with self.assertRaises(ConnectionError):
            await self.broker.deliver(self.durable, earlier, acknowledge=False)
        # Fault-injected out-of-order marker delivery tests the proof, independently
        # of the real consumer's max_ack_pending backpressure.
        marker = await self.complete()
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_journal_append_interruption_prevents_broker_ack(self):
        marker = evidence()
        sequence = await self.publish(marker)
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("interrupted append")):
            with self.assertRaises(OSError):
                await self.broker.deliver(self.durable, sequence)
        self.assertEqual(self.broker.consumers[self.durable].ack_floor.consumer_seq, 0)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_restart_and_identical_redelivery_preserve_durable_receiving_position(self):
        marker = evidence()
        sequence = await self.publish(marker)
        with self.assertRaises(ConnectionError):
            await self.broker.deliver(self.durable, sequence, acknowledge=False)
        restored = InMemoryIngestor(session_id="A", recovery_journal_path=self.path)
        self.receiver = NatsIngestorCommunication(self.boundary, restored)
        await self.receiver.subscribe_evidence("A")
        before = self.path.read_bytes()
        await self.broker.deliver(self.durable, sequence)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sum(item.evidence_id == marker.evidence_id for item in restored.accepted_runtime_evidence), 1)
        self.assertTrue((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_deleted_history_cannot_hide_behind_contiguous_filtered_sequences(self):
        first = await self.publish(evidence("first", kind="mapping_update"))
        missing = await self.publish(evidence("missing", kind="mapping_update"))
        del self.broker.records[missing]
        await self.broker.deliver(self.durable, first)
        marker = await self.complete()
        self.assertEqual(self.broker.consumers[self.durable].ack_floor.consumer_seq, 2)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_truncated_prefix_prevents_confirmation(self):
        earlier = await self.publish(evidence("earlier", kind="mapping_update"))
        del self.broker.records[earlier]
        self.assertFalse((await self.proof(await self.complete()))["durable_receipt_confirmed"])

    async def test_missing_durable_state_is_not_silently_reconstructed(self):
        marker = await self.complete()
        del self.broker.consumers[self.durable]
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])
        restored = InMemoryIngestor(session_id="A", recovery_journal_path=self.path)
        self.receiver = NatsIngestorCommunication(self.boundary, restored)
        await self.receiver.subscribe_evidence("A")
        await self.broker.deliver(self.durable, 1)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_invalid_consumer_and_unverifiable_progress_fail_closed(self):
        marker = await self.complete()
        consumer = self.broker.consumers[self.durable]
        consumer.config.ack_policy = AckPolicy.ALL
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])
        with self.assertRaises(ValueError):
            await self.receiver.subscribe_evidence("A")
        consumer.config.ack_policy = AckPolicy.EXPLICIT
        consumer.ack_floor = SequenceInfo(100, 100)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])
        self.broker.unavailable = True
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_unpublished_or_unrelated_marker_is_not_confirmed(self):
        marker = evidence()
        self.ingestor.receive_runtime_evidence(marker)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])
        self.assertFalse((await self.proof(evidence(session="B")))["durable_receipt_confirmed"])

    async def test_stream_replacement_invalidates_original_receiving_state(self):
        marker = await self.complete()
        self.broker.created += timedelta(seconds=1)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_history_loss_during_asynchronous_readback_prevents_confirmation(self):
        marker = await self.complete()
        original = self.broker.get_last_msg

        async def lose_history(*args):
            record = await original(*args)
            del self.broker.records[record.seq]
            return record

        with patch.object(self.broker, "get_last_msg", side_effect=lose_history):
            self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_consumer_reset_during_readback_prevents_stale_confirmation(self):
        marker = await self.complete()
        original = self.broker.get_last_msg

        async def reset(*args):
            record = await original(*args)
            self.broker.consumers[self.durable] = replace(
                self.broker.consumers[self.durable], ack_floor=SequenceInfo(0, 0),
                created=self.broker.created + timedelta(seconds=1))
            return record

        with patch.object(self.broker, "get_last_msg", side_effect=reset):
            self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_inconsistent_ack_floor_cannot_claim_contiguous_receipt(self):
        marker = await self.complete()
        self.broker.consumers[self.durable].ack_floor = SequenceInfo(0, 1)
        self.assertFalse((await self.proof(marker))["durable_receipt_confirmed"])

    async def test_binding_change_during_subscription_preserves_subsequent_session(self):
        ingestor = InMemoryIngestor(recovery_journal_root=self.path.parent / "reusable")
        self.assertTrue(ingestor.prepare_session("A").ready)
        receiver = NatsIngestorCommunication(self.boundary, ingestor)
        entered, continue_subscription = asyncio.Event(), asyncio.Event()
        original_subscribe = self.broker.subscribe
        unsubscribed = []

        async def delayed_subscribe(*args, **kwargs):
            subscription = await original_subscribe(*args, **kwargs)
            entered.set()
            await continue_subscription.wait()
            return SimpleNamespace(unsubscribe=self.record_unsubscribe(unsubscribed))

        with patch.object(self.broker, "subscribe", side_effect=delayed_subscribe):
            task = asyncio.create_task(receiver.subscribe_evidence("A"))
            await entered.wait()
            self.assertTrue(ingestor.abort_session_initialization("A"))
            self.assertTrue(ingestor.prepare_session("B").ready)
            continue_subscription.set()
            with self.assertRaisesRegex(RuntimeError, "binding changed"):
                await task
        self.assertEqual(unsubscribed, [True])
        self.assertEqual(ingestor.session_id, "B")
        self.assertTrue(ingestor.check_ready().ready)
        self.assertEqual(ingestor.accepted_runtime_evidence, ())

    @staticmethod
    def record_unsubscribe(records):
        async def unsubscribe():
            records.append(True)
        return unsubscribe


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class LiveEvidenceReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_receipt_restart_missing_history_and_redelivery(self):
        with tempfile.TemporaryDirectory() as directory:
            async with temporary_jetstream_server() as url:
                boundary = NatsCommunicationBoundary("ingestor", "ingestor", (url,))
                await boundary.connect()
                try:
                    await boundary.ensure_streams()
                    js = boundary._require_jetstream()
                    path = Path(directory) / "session.jsonl"
                    ingestor = InMemoryIngestor(session_id="A", recovery_journal_path=path,
                        framework_recovery_journal_path=Path(directory) / "framework.jsonl")
                    acknowledged = asyncio.Event()
                    original_subscribe = js.subscribe

                    async def subscribe(topic, cb, **options):
                        async def receive(message):
                            await cb(message)
                            if json.loads(message.data)["evidence_type"] == "acquisition_evidence_completion":
                                acknowledged.set()
                        return await original_subscribe(topic, cb=receive, **options)

                    receiver = NatsIngestorCommunication(boundary, ingestor)
                    with patch.object(js, "subscribe", side_effect=subscribe):
                        subscription = await receiver.subscribe_evidence("A")
                        framework_subscription = await receiver.subscribe_evidence(None)
                    marker = evidence()
                    first_sequence = None
                    for item in (evidence("first", kind="mapping_update", source="node1"),
                                 evidence("other", session="B", kind="mapping_update", source="node3"),
                                 evidence("second", kind="mapping_update", source="node2"),
                                 marker):
                        published = await js.publish(subject(item), json.dumps(item.to_dict()).encode())
                        if first_sequence is None:
                            first_sequence = published.seq
                    await asyncio.wait_for(acknowledged.wait(), 5)
                    proof = await receiver.verify_acquisition_evidence_receipt(marker)
                    self.assertTrue(proof["durable_receipt_confirmed"], proof)
                    self.assertEqual(proof["marker_stream_sequence"], 4)
                    self.assertEqual(proof["acknowledged_consumer_sequence"], 3)
                    self.assertEqual(len(ingestor.accepted_runtime_evidence), 3)
                    framework = evidence("framework", session=None, kind="service_readiness")
                    await js.publish("messages.evidence.controller.controller.service_readiness", json.dumps(framework.to_dict()).encode())
                    self.assertTrue(await ingestor.await_durable_runtime_evidence(framework, 2))
                    self.assertEqual(len(ingestor.compile_framework_runtime_evidence()["runtime_evidence"]), 1)
                    await framework_subscription.unsubscribe()
                    await subscription.unsubscribe()
                    await boundary.close()
                    await boundary.connect()
                    restored = InMemoryIngestor(session_id="A", recovery_journal_path=path)
                    receiver = NatsIngestorCommunication(boundary, restored)
                    subscription = await receiver.subscribe_evidence("A")
                    proof = await receiver.verify_acquisition_evidence_receipt(marker)
                    self.assertTrue(proof["durable_receipt_confirmed"], proof)
                    await boundary._require_jetstream().delete_msg("LAB_EVIDENCE", first_sequence)
                    self.assertFalse((await receiver.verify_acquisition_evidence_receipt(marker))["durable_receipt_confirmed"])
                    await subscription.unsubscribe()
                finally:
                    await boundary.close()

    async def test_real_unconfirmed_ack_blocks_marker_then_restart_redelivery_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            async with temporary_jetstream_server() as url:
                boundary = NatsCommunicationBoundary("ingestor", "ingestor", (url,))
                await boundary.connect()
                try:
                    await boundary.ensure_streams()
                    js = boundary._require_jetstream()
                    path = Path(directory) / "journal.jsonl"
                    ingestor = InMemoryIngestor(session_id="A", recovery_journal_path=path)
                    receiver = NatsIngestorCommunication(boundary, ingestor)
                    failed, completed = asyncio.Event(), asyncio.Event()
                    interrupted = []
                    original_subscribe = js.subscribe

                    async def subscribe(topic, cb, **options):
                        async def receive(message):
                            if json.loads(message.data)["evidence_id"] == "early" and not interrupted:
                                async def unconfirmed_ack():
                                    raise ConnectionError("crash after journal before ACK")
                                try:
                                    await cb(SimpleNamespace(data=message.data, ack_sync=unconfirmed_ack))
                                except ConnectionError:
                                    interrupted.append(message)
                                    failed.set()
                            else:
                                await cb(message)
                                if json.loads(message.data)["evidence_id"] == "marker":
                                    completed.set()
                        return await original_subscribe(topic, cb=receive, **options)

                    with patch.object(js, "subscribe", side_effect=subscribe):
                        subscription = await receiver.subscribe_evidence("A")
                    early, marker = evidence("early", kind="mapping_update"), evidence()
                    for item in (early, marker):
                        await js.publish(subject(item), json.dumps(item.to_dict()).encode())
                    await asyncio.wait_for(failed.wait(), 5)
                    self.assertTrue(ingestor.has_durable_runtime_evidence(early))
                    self.assertFalse(ingestor.has_durable_runtime_evidence(marker))
                    consumer = (await js.consumers_info("LAB_EVIDENCE"))[0]
                    self.assertEqual(consumer.ack_floor.consumer_seq, 0)
                    self.assertFalse((await receiver.verify_acquisition_evidence_receipt(marker))["durable_receipt_confirmed"])
                    await subscription.unsubscribe()
                    await boundary.flush()
                    restored = InMemoryIngestor(session_id="A", recovery_journal_path=path)
                    receiver = NatsIngestorCommunication(boundary, restored)
                    with patch.object(js, "subscribe", side_effect=subscribe):
                        subscription = await receiver.subscribe_evidence("A")
                    # Explicitly trigger broker redelivery in this deterministic test;
                    # production relies on JetStream, not framework retry machinery.
                    await interrupted[0].nak()
                    await asyncio.wait_for(completed.wait(), 5)
                    self.assertEqual(sum(item.evidence_id == "early" for item in restored.accepted_runtime_evidence), 1)
                    self.assertEqual(sum(json.loads(line)["evidence_id"] == "early" for line in path.read_text().splitlines()), 1)
                    proof = await receiver.verify_acquisition_evidence_receipt(marker)
                    self.assertTrue(proof["durable_receipt_confirmed"], proof)
                    await subscription.unsubscribe()
                finally:
                    await boundary.close()
