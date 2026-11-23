"""Framework intake remains durable and sequential while sharing the event loop."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server

from lab_sync_acquisition import InMemoryIngestor, NatsIngestorCommunication, RuntimeEvidenceMessage


class FrameworkIntakeSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'framework.jsonl'
        self.ingestor = InMemoryIngestor(framework_recovery_journal_path=self.path)
        self.boundary = SimpleNamespace(_framework_evidence_subscriptions=[])

        async def subscribe(subject, callback, **options):
            self.assertEqual(subject, 'messages.evidence.*.*.*')
            self.receive = callback
            return SimpleNamespace()

        self.boundary._subscribe_jetstream = subscribe
        self.boundary._require_jetstream = lambda: None
        await NatsIngestorCommunication(self.boundary, self.ingestor).subscribe_evidence(None)

    def delivery(self, identity='one', payload=None, ack=None):
        evidence = RuntimeEvidenceMessage(identity, None, 'test_evidence', 'source', payload or {'value': 1}, True)
        return SimpleNamespace(subject='messages.evidence.acquisition_node.source.test_evidence',
                               data=json.dumps(evidence.to_dict()).encode(), ack=ack or AsyncMock())

    async def test_backlog_yields_after_durable_ack_without_reordering_or_losing_duplicate_audit(self):
        events, peer_observations = [], []
        original = os.fsync

        def sync(descriptor):
            original(descriptor)
            events.append('durable')

        async def ack():
            self.assertEqual(events[-1], 'durable')
            events.append('ack')
            asyncio.get_running_loop().call_soon(lambda: peer_observations.append(len(events)))

        deliveries = [self.delivery(identity, ack=AsyncMock(side_effect=ack)) for identity in ('one', 'one', 'two')]
        with patch('lab_sync_acquisition.ingestor.os.fsync', side_effect=sync):
            for index, message in enumerate(deliveries):
                await self.receive(message)
                self.assertEqual(peer_observations, list(range(2, 2 * (index + 1) + 1, 2)),
                                 'Ready peer work must run between completed deliveries')
        self.assertEqual(events, ['durable', 'ack'] * 3)
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([row['ingest_audit']['reason'] for row in rows], ['accepted', 'already_accepted', 'accepted'])
        self.assertEqual([row['ingest_audit']['ingest_order'] for row in rows], [1, 2, 3])
        self.assertEqual([m.evidence_id for m in self.ingestor.compile_framework_runtime_evidence()['runtime_evidence']], ['one', 'two'])

    async def test_conflict_and_durability_failure_remain_unacknowledged_and_pending(self):
        await self.receive(self.delivery())
        conflict = self.delivery(payload={'value': 2})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            await self.receive(conflict)
        conflict.ack.assert_not_awaited()
        self.assertEqual(self.path.read_bytes(), before)
        failed = self.delivery('failed')
        with patch('lab_sync_acquisition.ingestor.os.fsync', side_effect=OSError('durability unavailable')):
            with self.assertRaisesRegex(OSError, 'durability unavailable'):
                await self.receive(failed)
        failed.ack.assert_not_awaited()
        later = self.delivery('later')
        with self.assertRaisesRegex(RuntimeError, 'restart'):
            await self.receive(later)
        later.ack.assert_not_awaited()
        pending = self.boundary._framework_evidence_subscriptions[0]['pending']
        self.assertEqual(set(pending), {id(conflict), id(failed), id(later)})

    async def test_cancellation_during_ack_retains_durable_delivery_for_cleanup(self):
        entered = asyncio.Event()

        async def ack():
            entered.set()
            await asyncio.Event().wait()

        message = self.delivery(ack=AsyncMock(side_effect=ack))
        task = asyncio.create_task(self.receive(message))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIn(id(message), self.boundary._framework_evidence_subscriptions[0]['pending'])
        restored = InMemoryIngestor(framework_recovery_journal_path=self.path)
        self.assertEqual(restored.compile_framework_runtime_evidence()['runtime_evidence'][0].evidence_id, 'one')

    async def test_cancellation_after_ack_does_not_retain_completed_delivery(self):
        async def ack():
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)

        message = self.delivery(ack=AsyncMock(side_effect=ack))
        task = asyncio.create_task(self.receive(message))
        with self.assertRaises(asyncio.CancelledError):
            await task
        message.ack.assert_awaited_once()
        self.assertEqual(self.boundary._framework_evidence_subscriptions[0]['pending'], {})
        self.assertEqual(self.ingestor.compile_framework_runtime_evidence()['runtime_evidence'][0].evidence_id, 'one')

    @unittest.skipUnless(NATS_SERVER, 'optional isolated nats-server unavailable')
    async def test_paired_startup_puback_is_processed_before_historical_replay_finishes(self):
        import contextvars
        import importlib.metadata
        import time
        from nats.aio.client import Client
        from nats.aio.msg import Msg
        from nats.aio.transport import TcpTransport
        from lab_sync_acquisition import NatsCommunicationBoundary
        from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services

        count = 120
        gate, entered = asyncio.Event(), asyncio.Event()
        delivery_context = contextvars.ContextVar('delivery', default=None)
        deliveries, synced, acknowledged, pubacks, reports = [], [], [], [], []
        original_subscribe = NatsCommunicationBoundary._subscribe_jetstream
        original_write, original_reply = TcpTransport.writelines, Client._request_sub_callback
        original_sync, original_ack = os.fsync, Msg.ack

        async def subscribe(boundary, subject, callback, **options):
            if subject != 'messages.evidence.*.*.*':
                return await original_subscribe(boundary, subject, callback, **options)

            async def receive(message):
                entered.set()
                await gate.wait()
                index = len(deliveries)
                deliveries.append(json.loads(message.data)['evidence_id'])
                token = delivery_context.set(index)
                try:
                    await callback(message)
                finally:
                    delivery_context.reset(token)

            subscription = await original_subscribe(boundary, subject, receive, **options)
            async with asyncio.timeout(5):
                await entered.wait()
                while subscription.pending_msgs < count - 1:
                    await asyncio.sleep(.001)
            return subscription

        def write(transport, data):
            result = original_write(transport, data)
            if any(b'messages.evidence.ingestor.fair-intake.service_readiness' in part for part in data):
                gate.set()
            return result

        def sync(descriptor):
            index = delivery_context.get()
            if index is not None:
                # Keep real durability, with the observed class of synchronous delay.
                time.sleep(.482 if not synced else .049)
            original_sync(descriptor)
            if index is not None:
                synced.append(index)

        async def ack(message):
            index = delivery_context.get()
            if index is not None:
                self.assertIn(index, synced, 'Consumer ACK must follow this delivery durability')
                acknowledged.append(index)
            return await original_ack(message)

        async def reply(client, message):
            data = json.loads(message.data)
            if data.get('stream') == 'LAB_EVIDENCE' and data.get('seq') == count + 1:
                pubacks.append(len(deliveries))
            return await original_reply(client, message)

        async with temporary_jetstream_server() as url:
            producer = NatsCommunicationBoundary('synchronization_manager', 'history', (url,))
            await producer.connect()
            try:
                await producer.ensure_streams()
                messages = [RuntimeEvidenceMessage(f'history-{i}', None, 'test_evidence', 'history', {'index': i}, True)
                            for i in range(count // 2)]
                for i in range(count):
                    await producer.publish_evidence(messages[i // 2])
            finally:
                await producer.close()

            async def run(launcher, *, startup):
                intake = launcher.maintenance[0].ingestor
                for message in messages:
                    intake.receive_runtime_evidence(message)
                try:
                    await startup()
                    statuses = [json.loads(line)['startup'] for line in reports if line.startswith('{')]
                    self.assertEqual(len(statuses), 2)
                    for status in statuses:
                        self.assertTrue(status['publication_confirmed'], status)
                        self.assertTrue(status['acceptance_confirmed'], status)
                        self.assertTrue(status['archival_confirmed'], status)
                    self.assertEqual(launcher.boundaries[0]._require_jetstream()._timeout, 5)
                finally:
                    gate.set()
                    for boundary in launcher.boundaries:
                        await boundary.close()  # Real framework subscription drain/cleanup.
                return 0

            with patch.object(NatsCommunicationBoundary, '_subscribe_jetstream', subscribe), \
                 patch.object(TcpTransport, 'writelines', write), patch.object(Client, '_request_sub_callback', reply), \
                 patch.object(Msg, 'ack', ack), patch('lab_sync_acquisition.ingestor.os.fsync', side_effect=sync), \
                 patch.object(ServiceLauncher, 'run', run):
                await launch_storage_services(servers=(url,), ingestor_id='fair-intake', storage_id='fair-storage',
                    storage_root=self.path.parent / 'storage', recovery_journal_root=self.path.parent / 'sessions',
                    framework_journal=self.path.parent / 'paired.jsonl', preservation_window_s=1.,
                    operational_dependents=(), result_window_s=1., controller_claim_account='LAB',
                    controller_claim_bucket='UNUSED', controller_claim_key='UNUSED', report=reports.append)
        self.assertEqual(deliveries[:count], [messages[i // 2].evidence_id for i in range(count)])
        self.assertEqual(acknowledged, list(range(count + 2)))
        self.assertEqual(synced, acknowledged)
        self.assertEqual(len(pubacks), 1)
        self.assertLess(pubacks[0], count, 'Readiness PubAck must be processed while replay remains queued')
        print(f'Actual nats-py {importlib.metadata.version("nats-py")}: PubAck processed after {pubacks[0]}/{count} historical deliveries')
