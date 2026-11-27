"""Native delivery responsibilities and transient owner readback on isolated NATS."""

import asyncio
from contextlib import AsyncExitStack
import unittest
from unittest.mock import AsyncMock

from nats.js.api import RetentionPolicy

from lab_sync_acquisition import (
    NatsCommunicationBoundary, NatsControllerCommunication,
    NatsServiceMaintenanceCommunication, NatsSynchronizationManagerCommunication,
    RuntimeCommandResultMessage, RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager,
)
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


@unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
class DeliveryResponsibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        self.url = await self.stack.enter_async_context(temporary_jetstream_server())
        self.producer = await self.connect("synchronization_manager", "sync")
        self.js = self.producer._require_jetstream()

    async def connect(self, kind, identity):
        boundary = NatsCommunicationBoundary(kind, identity, (self.url,))
        await boundary.connect()
        self.stack.push_async_callback(boundary.close)
        await boundary.ensure_streams()
        return boundary

    def result(self, recipient, identity="reply"):
        return RuntimeCommandResultMessage(identity, "request", None, "sync", recipient,
            "succeeded", True, None, {"request_nonce": "attempt"})

    async def test_streams_use_native_interests(self):
        for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
            self.assertEqual((await self.js.stream_info(stream)).config.retention, RetentionPolicy.INTEREST)

    async def test_recipient_interests_are_independent_and_reused(self):
        a = await self.connect("controller", "a")
        b = await self.connect("controller", "b")
        first, second = NatsControllerCommunication(a), NatsControllerCommunication(a)
        other = NatsControllerCommunication(b)
        received = asyncio.get_running_loop().create_future()
        async def observe(result):
            if not received.done():
                received.set_result(result)
        handles = [await first.subscribe_command_results(None, observe),
                   await second.subscribe_command_results(None),
                   await other.subscribe_command_results(None)]
        try:
            consumers = await self.js.consumers_info("LAB_COMMAND_RESULTS")
            self.assertEqual(len(consumers), 2)
            await self.producer.publish_command_result(self.result("a"), "register_operational_dependent")
            self.assertEqual((await asyncio.wait_for(received, 2)).target_id, "a")
            await a.flush()
            self.assertEqual(len(first.command_results), 1)
            self.assertEqual(len(second.command_results), 1)
            self.assertEqual(other.command_results, ())
            self.assertEqual((await self.js.stream_info("LAB_COMMAND_RESULTS")).state.messages, 0)
        finally:
            for handle in handles:
                await handle.unsubscribe()

    async def test_disconnect_retains_required_result_until_recipient_returns(self):
        receiver = await self.connect("ingestor", "intake")
        await NatsControllerCommunication(receiver).subscribe_command_results(None)
        await receiver.close()
        await self.producer.publish_command_result(self.result("intake"), "confirm_dependent_release")
        self.assertEqual((await self.js.stream_info("LAB_COMMAND_RESULTS")).state.messages, 1)
        replacement = await self.connect("ingestor", "intake")
        received = asyncio.get_running_loop().create_future()
        async def observe(result):
            if not received.done():
                received.set_result(result)
        handle = await NatsControllerCommunication(replacement).subscribe_command_results(None, observe)
        try:
            self.assertEqual((await asyncio.wait_for(received, 2)).result_id, "reply")
            await replacement.flush()
            self.assertEqual((await self.js.stream_info("LAB_COMMAND_RESULTS")).state.messages, 0)
        finally:
            await handle.unsubscribe()

    async def test_gui_result_interest_is_not_durable(self):
        gui = await self.connect("gui", "browser")
        handle = await NatsControllerCommunication(gui).subscribe_command_results(None)
        try:
            consumers = await self.js.consumers_info("LAB_COMMAND_RESULTS")
            self.assertEqual(len(consumers), 1)
            self.assertIsNone(consumers[0].config.durable_name)
        finally:
            await handle.unsubscribe()

    async def test_repeated_readiness_reads_do_not_enter_durable_streams(self):
        service = SynchronizationManager()
        maintenance = ServiceMaintenanceInterface(service, RuntimeParticipant("synchronization_manager", "sync"),
            ingestor=None, storage_manager=None, preservation_window_s=1,
            close_resources=AsyncMock(return_value=True))
        NatsServiceMaintenanceCommunication(self.producer, maintenance)
        subscriptions = await NatsSynchronizationManagerCommunication(self.producer, service).subscribe_commands()
        observer = await self.connect("gui", "observer")
        requests = NatsControllerCommunication(observer)
        try:
            for _ in range(4):
                result = await requests.request_runtime_command(maintenance.participant, "check_readiness", None, {}, 2)
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.payload["service_readiness"]["component_id"], "sync")
            for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
                self.assertEqual((await self.js.stream_info(stream)).state.messages, 0)
        finally:
            for subscription in subscriptions:
                await subscription.unsubscribe()

    async def test_unknown_read_is_unconfirmed_not_success(self):
        observer = await self.connect("gui", "observer")
        result = await NatsControllerCommunication(observer).request_runtime_command(
            RuntimeParticipant("acquisition_node", "absent"), "get_inventory", None, {}, .1)
        self.assertIsNone(result)
