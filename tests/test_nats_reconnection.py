"""Running shared owners restore transport without replaying lifecycle work."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nats.errors import ConnectionReconnectingError
from nats.js.errors import NotFoundError

from lab_sync_acquisition import (
    DurablePublicationError, NatsCommunicationBoundary, NatsIngestorCommunication,
    RuntimeEvidenceMessage, RuntimeTelemetryMessage,
)
from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services
from tests.nats_server_fixture import NATS_SERVER, restartable_jetstream_server


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class NatsReconnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = await self.enterAsyncContext(restartable_jetstream_server())
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

        async def capture(launcher, *, startup):
            await startup()
            return launcher

        with patch.object(ServiceLauncher, "run", new=capture):
            self.launcher = await launch_storage_services(
                servers=(self.server.url,), ingestor_id="intake", storage_id="storage",
                storage_root=self.root / "storage", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "framework.jsonl", preservation_window_s=1,
                operational_dependents={}, report=lambda message: None,
            )
        self.intake_boundary, self.storage_boundary = self.launcher.boundaries
        self.intake, self.storage = (interface.service for interface in self.launcher.maintenance)
        for boundary in self.launcher.boundaries:
            self.addAsyncCleanup(boundary.close)
            boundary._client._error_cb = AsyncMock()

    async def until(self, predicate):
        async def settled():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(settled(), 12)

    async def outage(self):
        self.server.stop()
        await self.until(lambda: not any(b.connected for b in self.launcher.boundaries))

    async def restored(self):
        await self.server.start()
        await self.until(lambda: all(b.connected for b in self.launcher.boundaries))

    async def test_broker_restart_restores_existing_core_and_evidence_subscriptions(self):
        received = []
        async def telemetry(message):
            received.append(message.payload["sequence"])
        subscription = await self.intake_boundary.subscribe_telemetry(
            "messages.probe-session.telemetry.storage_manager.storage.progress", telemetry)
        await self.intake_boundary.flush()
        clients = tuple(b._client for b in self.launcher.boundaries)
        contexts = tuple(b._jetstream for b in self.launcher.boundaries)
        counts = tuple(len(c._subs) for c in clients)
        outcomes = tuple(len(m.command_results) for m in self.launcher.maintenance)
        for sequence in (1, 2):
            if sequence == 2:
                await self.outage()
                self.assertFalse(self.intake_boundary.check_ready().ready)
                with self.assertRaises(DurablePublicationError):
                    await self.storage_boundary.publish_evidence(RuntimeEvidenceMessage(
                        "outage", None, "probe", "storage", {}, True))
                await self.restored()
            await self.storage_boundary.publish_telemetry(RuntimeTelemetryMessage(
                "probe-session", "progress", "storage", {"sequence": sequence}))
            evidence = RuntimeEvidenceMessage(f"preserved-{sequence}", None, "probe", "storage", {}, True)
            await self.storage_boundary.publish_evidence(evidence)
            self.assertTrue(await self.intake.await_durable_runtime_evidence(evidence, 2))
            await self.until(lambda: len(received) == sequence)
        self.assertEqual(received, [1, 2])
        self.assertEqual(tuple(b._client for b in self.launcher.boundaries), clients)
        self.assertEqual(tuple(b._jetstream for b in self.launcher.boundaries), contexts)
        self.assertEqual(tuple(len(c._subs) for c in clients), counts)
        self.assertIsNotNone(subscription)
        ids = [m.evidence_id for m in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]]
        self.assertEqual(ids.count("preserved-2"), 1)
        self.assertNotIn("outage", ids)
        self.assertEqual(tuple(len(m.command_results) for m in self.launcher.maintenance), outcomes)
        self.assertFalse(self.launcher.exit_ready)

    async def test_session_durable_consumer_and_receipt_survive_reconnect(self):
        self.intake.prepare_session("receiving-session")
        handler = NatsIngestorCommunication(self.intake_boundary, self.intake)
        subscription = await handler.subscribe_evidence("receiving-session")
        controller = NatsCommunicationBoundary("controller", "control", (self.server.url,))
        await controller.connect()
        controller._client._error_cb = AsyncMock()
        self.addAsyncCleanup(controller.close)
        first = RuntimeEvidenceMessage("first", "receiving-session", "probe", "storage", {}, True)
        await self.storage_boundary.publish_evidence(first)
        self.assertTrue(await self.intake.await_durable_runtime_evidence(first, 2))
        async def acknowledged():
            while True:
                consumer = await subscription.consumer_info()
                if consumer.delivered.consumer_seq >= 1 and consumer.num_ack_pending == 0:
                    return
                await asyncio.sleep(.01)
        await asyncio.wait_for(acknowledged(), 3)
        await self.outage()
        await self.restored()
        await self.until(lambda: controller.connected)
        marker = RuntimeEvidenceMessage("last-call", "receiving-session",
            "acquisition_evidence_completion", "control", {}, True)
        await controller.publish_evidence(marker)
        # An abruptly stopped broker may restore an older consumer ACK floor.
        # Existing JetStream redelivery, not resubscription/repair, resolves that
        # outstanding delivery before this max_ack_pending=1 consumer advances.
        consumer = await subscription.consumer_info()
        self.assertTrue(await self.intake.await_durable_runtime_evidence(marker, consumer.config.ack_wait + 5))
        async def confirmed():
            while True:
                receipt = await handler.verify_acquisition_evidence_receipt(marker)
                if receipt["durable_receipt_confirmed"]:
                    return receipt
                await asyncio.sleep(.01)
        proof = await asyncio.wait_for(confirmed(), 3)
        self.assertEqual(proof["evidence_id"], marker.evidence_id)
        self.assertEqual([m.evidence_id for m in self.intake.accepted_runtime_evidence].count("first"), 1)
        self.assertIsNone(self.intake.finalized_acquisition_intake("receiving-session"))

    async def test_connected_transport_cannot_confirm_missing_jetstream_preservation(self):
        await self.outage()
        await self.restored()
        await self.storage_boundary._jetstream.delete_stream("LAB_EVIDENCE")
        evidence = RuntimeEvidenceMessage("missing-stream", None, "probe", "storage", {}, True)
        with self.assertRaises(DurablePublicationError):
            await self.storage_boundary.publish_evidence(evidence)
        self.assertFalse(self.intake.has_durable_runtime_evidence(evidence))
        self.assertFalse(await self.launcher.stop_locally("administrator"))
        self.assertFalse(self.launcher.exit_ready)
        with self.assertRaises(NotFoundError):
            await self.storage_boundary._jetstream.stream_info("LAB_EVIDENCE")

    async def test_each_shared_owner_reconnects_without_replacing_the_other(self):
        for boundary, other in ((self.intake_boundary, self.storage_boundary),
                                (self.storage_boundary, self.intake_boundary)):
            with self.subTest(owner=boundary.component_type):
                client, other_client = boundary._client, other._client
                count, other_count = client.stats["reconnects"], other_client.stats["reconnects"]
                client._transport.close()
                await self.until(lambda: client.stats["reconnects"] > count and boundary.connected)
                self.assertIs(boundary._client, client)
                self.assertTrue(other.connected)
                self.assertEqual(other_client.stats["reconnects"], other_count)
                evidence = RuntimeEvidenceMessage(f"after-{boundary.component_type}", None,
                    "probe", "storage", {}, True)
                await self.storage_boundary.publish_evidence(evidence)
                self.assertTrue(await self.intake.await_durable_runtime_evidence(evidence, 2))

    async def test_explicit_maintenance_retry_after_outage_preserves_prior_evidence(self):
        await self.outage()
        self.assertFalse(await self.launcher.stop_locally("administrator"))
        self.assertFalse(self.launcher.exit_ready)
        self.assertTrue(all(not m.terminated for m in self.launcher.maintenance))
        journal = self.root / "framework.jsonl"
        before = journal.read_bytes()
        required = tuple(message for interface in self.launcher.maintenance for message in interface.required_evidence())
        self.assertTrue(required)
        await self.restored()
        # Restoring transport alone cannot execute the rejected Stop or Cancel.
        self.assertFalse(self.launcher.exit_ready)
        self.assertTrue(all(not m.terminated for m in self.launcher.maintenance))
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(await self.launcher.stop_locally("administrator"))
        self.assertTrue(journal.read_bytes().startswith(before))
        confirmation = self.storage.get_framework_preservation_confirmation()
        self.assertIsNotNone(confirmation)
        for message in required:
            self.assertIn(message.to_dict(), confirmation["runtime_evidence"])

    async def test_intentional_close_during_reconnect_does_not_return_with_broker(self):
        await self.outage()
        client = self.storage_boundary._client
        count = client.stats["reconnects"]
        await asyncio.wait_for(self.storage_boundary.close(), 5)
        self.assertTrue(client.is_closed)
        await self.server.start()
        await self.until(lambda: self.intake_boundary.connected)
        self.assertFalse(self.storage_boundary.connected)
        self.assertEqual(client.stats["reconnects"], count)

    async def test_intentional_close_handles_drain_admission_handover(self):
        client = self.storage_boundary._client
        original = client.close
        with patch.object(client, "drain", AsyncMock(side_effect=ConnectionReconnectingError)), \
             patch.object(client, "close", wraps=original) as closed:
            await self.storage_boundary.close()
            closed.assert_awaited_once()
        self.assertTrue(client.is_closed)
        self.assertFalse(self.storage_boundary.connected)

    async def test_close_joins_sdk_reconnection_handover_despite_caller_cancellation(self):
        client = self.storage_boundary._client
        reached, resume = asyncio.Event(), asyncio.Event()
        original_connect, original_close = client._process_connect_init, client.close
        closing, finish = asyncio.Event(), asyncio.Event()

        async def paused_handshake():
            reached.set()
            await resume.wait()
            await original_connect()

        async def paused_close():
            closing.set()
            await finish.wait()
            await original_close()

        with patch.object(client, "_process_connect_init", new=paused_handshake), \
             patch.object(client, "close", new=paused_close):
            client._transport.close()
            await asyncio.wait_for(reached.wait(), 5)
            task = asyncio.create_task(self.storage_boundary.close())
            try:
                await asyncio.wait_for(closing.wait(), 5)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                self.assertFalse(task.done())
                finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            finally:
                resume.set()
                finish.set()
                if not task.done():
                    await task
        self.assertTrue(client.is_closed)
        self.assertFalse(self.storage_boundary.connected)

    async def test_uncertain_publication_is_not_retried_on_reconnect(self):
        original = self.storage_boundary._jetstream.publish
        evidence = RuntimeEvidenceMessage("uncertain", None, "probe", "storage", {}, True)
        async def lose_ack(*args, **kwargs):
            await original(*args, **kwargs)
            raise asyncio.TimeoutError("acknowledgement lost after acceptance")
        with patch.object(self.storage_boundary._jetstream, "publish", new=lose_ack):
            with self.assertRaises(DurablePublicationError):
                await self.storage_boundary.publish_evidence(evidence)
        self.assertTrue(await self.intake.await_durable_runtime_evidence(evidence, 2))
        before = (await self.storage_boundary._jetstream.stream_info("LAB_EVIDENCE")).state.messages
        await self.outage()
        await self.restored()
        after = (await self.storage_boundary._jetstream.stream_info("LAB_EVIDENCE")).state.messages
        self.assertEqual(after, before)
        self.assertFalse(self.launcher.exit_ready)
