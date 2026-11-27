"""Saved collection uses owner outcomes and lifetime-scoped attempt protection."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import nats
from nats.js.api import ConsumerConfig, DeliverPolicy, KeyValueConfig, StorageType

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsServiceMaintenanceCommunication,
    NatsStorageManagerCommunication, RuntimeCommandResultMessage,
    RuntimeParticipant, ServiceMaintenanceInterface, PersistentStorageManager, SshRetrievalEndpoint,
)
from lab_sync_acquisition.communication import build_runtime_subject
from tests import test_saved_session_selection as selection_fixtures
from tests import test_artifact_retrieval as retrieval_fixtures
from tests.test_session_launch import _Broker
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker
from tests.nats_server_fixture import (
    CONTROLLER_AUTHORITY_SERVER_CONFIGURATION, NATS_SERVER, restartable_jetstream_server,
)


class CollectionBroker(_Broker):
    """Historical transport fixture retained for not-yet-converted closeout tests."""
    def __init__(self):
        super().__init__()
        self.result_history = EvidenceReceiptBroker()

    async def stream_info(self, name):
        if name == "LAB_COMMAND_RESULTS":
            return await self.result_history.stream_info(name)
        return await super().stream_info(name)

    async def get_msg(self, stream, **options):
        if stream == "LAB_COMMAND_RESULTS":
            return await self.result_history.get_msg(stream, **options)
        return await super().get_msg(stream, **options)

    async def publish(self, subject, data, stream):
        if stream == "LAB_COMMAND_RESULTS":
            await self.result_history.publish(subject, data, stream)
        return await super().publish(subject, data, stream)


def run_storage_owner(url, root, files, ready, stop):
    """Run an isolated storage owner for existing separate-process closure tests."""
    async def run():
        boundary = NatsCommunicationBoundary("storage_manager", "storage", servers=[url])
        await boundary.connect()
        try:
            await boundary.ensure_streams()
            storage = PersistentStorageManager(root, global_artifact_root=Path(root) / "global",
                retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "reader")})
            InMemoryIngestor(storage_manager=storage)
            subscriptions = await NatsStorageManagerCommunication(boundary, storage).subscribe_commands()
            transport, _ = retrieval_fixtures.ArtifactRetrievalTests().ssh(retrieval_fixtures.SftpDouble(files))
            with transport:
                ready.send(True)
                await asyncio.to_thread(stop.wait)
            for subscription in subscriptions:
                await subscription.unsubscribe()
        finally:
            await boundary.close()
            ready.close()
    asyncio.run(run())


@unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
class RemoteSavedCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.selection = selection_fixtures.SavedSessionSelectionTests()
        self.selection.addCleanup = self.addCleanup
        self.selection.setUp()
        self.fixture = self.selection.fixture
        self.storage = self.selection.storage
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        server = await self.stack.enter_async_context(restartable_jetstream_server(
            server_configuration=CONTROLLER_AUTHORITY_SERVER_CONFIGURATION))
        self.url = server.url.replace("nats://", "nats://demo:demo@")
        client = await nats.connect(self.url)
        self.stack.push_async_callback(client.close)
        self.js = client.jetstream()
        await self.js.create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE, history=8))
        self.scope = dict(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
        self.intake = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.fixture.root / "framework.jsonl")
        self.controller = Controller(component_id="controller")
        owner = ServiceMaintenanceInterface(self.controller, RuntimeParticipant("controller", "controller"),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=1,
            close_resources=AsyncMock(return_value=True))
        self.boundary = await self.new_boundary("controller", "controller")
        await owner.acquire_controller_authority(self.boundary, **self.scope)
        self.communication = NatsControllerCommunication(self.boundary)
        self.peer = RuntimeParticipant("storage_manager", "storage")
        self.wire_commands = []
        publish = self.boundary._publish_command_wire
        async def record(command, kind):
            if command.command_type == "collect_saved_artifacts":
                self.wire_commands.append(command)
            return await publish(command, kind)
        self.boundary._publish_command_wire = record
        self.subscriptions = ()
        await self.subscribe(self.storage)

    async def new_boundary(self, kind, identity):
        boundary = NatsCommunicationBoundary(kind, identity, (self.url,))
        await boundary.connect()
        self.stack.push_async_callback(boundary.close)
        await boundary.ensure_streams()
        return boundary

    async def subscribe(self, storage):
        for subscription in self.subscriptions:
            await subscription.unsubscribe()
        self.storage_boundary = await self.new_boundary("storage_manager", "storage")
        self.storage_owner = ServiceMaintenanceInterface(storage, self.peer,
            ingestor=self.intake, storage_manager=storage, preservation_window_s=1,
            close_resources=AsyncMock(return_value=True))
        self.storage_boundary.configure_controller_authority(**self.scope)
        NatsServiceMaintenanceCommunication(self.storage_boundary, self.storage_owner)
        self.subscriptions = await NatsStorageManagerCommunication(self.storage_boundary, storage).subscribe_commands()
        for subscription in self.subscriptions:
            async def unsubscribe(s=subscription):
                if not s._closed:
                    await s.unsubscribe()
            self.stack.push_async_callback(unsubscribe)

    async def collect(self, identity="collection"):
        return await self.controller.collect_saved_session_artifacts_remote("session", evidence_id=identity,
            communication=self.communication, storage_participant=self.peer, result_window_s=2,
            experimenter_name=None, administrator_mode=True)

    async def redeliver(self, command):
        """Deliver the actual old envelope, without publisher re-admission."""
        future = asyncio.get_running_loop().create_future()
        async def receive(message):
            result = RuntimeCommandResultMessage.from_dict(json.loads(message.data))
            if result.command_id == command.command_id and not future.done():
                future.set_result(result)
            await message.ack()
        subject = build_runtime_subject(command.session_id, "command_result", "storage_manager",
                                        "storage", command.command_type, recipient_id=command.source_id)
        subscription = await self.js.subscribe(subject, cb=receive, manual_ack=True,
            config=ConsumerConfig(deliver_policy=DeliverPolicy.NEW))
        try:
            await self.js.publish(build_runtime_subject(command.session_id, "command", "storage_manager",
                "storage", command.command_type), json.dumps(command.to_dict()).encode())
            return await asyncio.wait_for(future, 3)
        finally:
            await subscription.unsubscribe()

    async def test_rejected_attempt_is_lifetime_scoped_and_fresh_retry_can_collect(self):
        self.selection.terminal("session", "stopping")
        rejected = await self.collect("denied")
        self.assertFalse(rejected.succeeded)
        old = self.wire_commands[-1]
        self.assertEqual(old.receiver_instance_id, self.storage_owner.operational_instance_id)
        self.selection.terminal("session", "completed")
        repeated = await self.redeliver(old)
        self.assertFalse(repeated.success)
        self.assertEqual(rejected.error, "RuntimeError: " + repeated.reason)
        self.assertEqual(self.fixture.sftp.opened, [])
        await self.subscribe(self.fixture.new_storage())
        stale = await self.redeliver(old)
        self.assertFalse(stale.success)
        self.assertIn("instance", stale.reason.lower())
        with self.assertRaisesRegex(RuntimeError, "previous operational instance"):
            await self.communication.publish_command(old, "storage_manager")
        self.assertEqual(self.fixture.sftp.opened, [])
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            self.assertTrue((await self.collect("denied")).succeeded)
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_changed_same_lifetime_attempt_cannot_execute(self):
        self.selection.terminal("session", "stopping")
        self.assertFalse((await self.collect("denied")).succeeded)
        old = self.wire_commands[-1]
        self.selection.terminal("session", "completed")
        changed = replace(old, command_id='["session","different"]',
            payload={**old.payload, "evidence_id": "different"})
        result = await self.redeliver(changed)
        self.assertFalse(result.success)
        self.assertIn("Conflicting", result.reason)
        self.assertEqual(self.fixture.sftp.opened, [])

    async def test_unavailable_broker_history_is_not_a_collection_dependency(self):
        get_msg = type(self.js).get_msg
        async def unavailable(js, stream, **options):
            if stream == "LAB_COMMAND_RESULTS":
                raise AssertionError("Historical broker results must not be read")
            return await get_msg(js, stream, **options)
        with patch.object(type(self.js), "get_msg", new=unavailable):
            transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
            with transport:
                result = await self.collect()
        self.assertTrue(result.succeeded, result.error)

    async def test_reply_loss_and_owner_replacement_do_not_repeat_transfer(self):
        # Keep native redelivery deterministic within this test's request window.
        for info in await self.js.consumers_info("LAB_COMMANDS"):
            if info.config.filter_subject == "messages.*.command.storage_manager.storage.*":
                await self.js.add_consumer("LAB_COMMANDS", config=replace(info.config, ack_wait=.1))
        publish = self.storage_boundary.publish_command_result
        async def lose_reply(result, operation):
            if operation == "collect_saved_artifacts":
                raise ConnectionError("Injected uncertain reply publication")
            return await publish(result, operation)
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport, patch.object(self.storage_boundary, "publish_command_result", side_effect=lose_reply):
            lost = await self.collect()
        self.assertFalse(lost.succeeded)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        await self.subscribe(self.fixture.new_storage())
        with transport:
            recovered = await self.collect()
        self.assertTrue(recovered.succeeded, recovered.error)
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_duplicate_success_uses_durable_owner_outcome(self):
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            first = await self.collect()
            self.assertTrue(first.succeeded, first.error)
            await self.subscribe(self.fixture.new_storage())
            recovered = await self.collect()
        self.assertTrue(recovered.succeeded, recovered.error)
        self.assertEqual(first.details["collection_outcome"], recovered.details["collection_outcome"])
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_failed_transfer_retains_durable_outcome(self):
        self.fixture.sftp.files.clear()
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            failed = await self.collect()
            await self.subscribe(self.fixture.new_storage())
            repeated = await self.collect()
        self.assertFalse(failed.succeeded)
        self.assertFalse(repeated.succeeded)
        self.assertTrue(failed.details["collection_outcome"]["archival_confirmed"])
        self.assertEqual(failed.details["collection_outcome"], repeated.details["collection_outcome"])

    async def test_closed_or_ineligible_session_does_not_transfer(self):
        self.selection.terminal("session", "stopping")
        before = self.fixture.products()
        self.assertFalse((await self.collect()).succeeded)
        self.assertEqual(self.fixture.products(), before)
        self.selection.terminal("session", "completed")
        self.storage.close_session_evidence_archive("session")
        before = self.fixture.products()
        self.assertFalse((await self.collect()).succeeded)
        self.assertEqual(self.fixture.products(), before)
        self.assertEqual(self.fixture.sftp.opened, [])
