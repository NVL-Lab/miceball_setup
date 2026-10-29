"""Controller authority admission and persistent claim public workflows."""

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import nats
from nats.js.api import KeyValueConfig, StorageType
from nats.js.errors import BadRequestError, KeyNotFoundError, KeyWrongLastSequenceError

from lab_sync_acquisition import (Controller, RuntimeParticipant, RuntimeCommandMessage,
    InMemoryIngestor, PersistentStorageManager, ServiceMaintenanceInterface,
    NatsCommunicationBoundary, SessionConfig)
from lab_sync_acquisition.service_launcher import ServiceLauncher
from tests.nats_server_fixture import (NATS_SERVER, restartable_jetstream_server,
                                      CONTROLLER_AUTHORITY_SERVER_CONFIGURATION)


class ControllerAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_construction_cannot_initiate_operational_work(self):
        controller = Controller()
        with self.assertRaisesRegex(RuntimeError, "claim"):
            await controller.get_node_inventory(RuntimeParticipant("acquisition_node", "node"),
                                                communication=None, result_window_s=0.1)
        self.assertFalse(controller.check_ready().ready)


@unittest.skipUnless(NATS_SERVER, "Set LAB_SYNC_NATS_SERVER to an installed nats-server")
class ControllerClaimTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        self.server = await self.stack.enter_async_context(restartable_jetstream_server(
            server_configuration=CONTROLLER_AUTHORITY_SERVER_CONFIGURATION))
        self.url = self.server.url.replace("nats://", "nats://demo:demo@")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = PersistentStorageManager(Path(self.temp.name))
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=Path(self.temp.name) / "journal.jsonl")
        self.boundaries = []
        self.controller, self.owner, self.boundary = await self.new_owner("controller")
        self.client = await nats.connect(self.url)
        self.stack.push_async_callback(self.client.close)
        self.js = self.client.jetstream()
        self.kv = await self.js.create_key_value(
            KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))

    async def new_owner(self, identity):
        controller = Controller(ingestor=self.ingestor, storage_manager=self.storage,
                                component_id=identity)
        owner = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", identity),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0.1,
            close_resources=AsyncMock(return_value=True))
        boundary = NatsCommunicationBoundary("controller", identity, (self.url,))
        await boundary.connect()
        self.stack.push_async_callback(boundary.close)
        self.boundaries.append(boundary)
        return controller, owner, boundary

    async def acquire(self, owner=None, boundary=None, **changes):
        return await (owner or self.owner).acquire_controller_authority(boundary or self.boundary,
            **{"account": "LAB", "bucket": "AUTHORITY", "key": "controller", "timeout_s": 1, **changes})

    def command(self, operation="stop", *, attempt="attempt", authorized=False):
        return RuntimeCommandMessage(operation + attempt, None, operation, "administrator", "controller",
            {"stop_attempt_id": attempt, "administrator_id": "operator", "authorized": authorized})

    async def stop(self):
        command = self.command()
        result = await self.owner.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(self.owner.terminated)
        return command, result

    async def test_concurrent_acquisition_admits_exactly_one_controller(self):
        other, owner, boundary = await self.new_owner("other")
        results = await asyncio.gather(self.acquire(), self.acquire(owner, boundary), return_exceptions=True)
        self.assertEqual(sum(isinstance(v, int) for v in results), 1)
        self.assertEqual(sum(c.check_ready().ready for c in (self.controller, other)), 1)
        self.assertIn((await self.kv.get("controller")).value.decode(),
                      (self.owner.operational_instance_id, owner.operational_instance_id))

    async def test_inprocess_session_creation_requires_explicit_claim(self):
        config = SessionConfig([], self.temp.name, None, self.temp.name, session_id="session")
        with self.assertRaisesRegex(RuntimeError, "claim"):
            self.controller.create_session(config)
        self.assertIsNone(self.controller.get_status()["session_id"])
        await self.acquire()
        created = self.controller.create_session(config)
        self.assertTrue(created.succeeded, created.error)
        self.assertEqual(self.controller.get_status()["session_id"], "session")

    async def test_independent_launcher_refuses_occupied_or_unspecified_authority(self):
        from lab_sync_acquisition.service_startup import launch_independent_service
        settings = dict(role="controller", servers=(self.url,), service_id="candidate",
            ingestor_id="ingestor", storage_id="storage", synchronization_id="sync", known_nodes=(),
            preservation_window_s=0.1, result_window_s=1, report=lambda text: None)
        with self.assertRaisesRegex(ValueError, "authority"):
            await launch_independent_service(**settings)
        await self.acquire()
        with self.assertRaises(KeyWrongLastSequenceError):
            await launch_independent_service(**settings, controller_claim_account="LAB",
                controller_claim_bucket="AUTHORITY", controller_claim_key="controller")
        self.assertEqual((await self.kv.get("controller")).value.decode(), self.owner.operational_instance_id)

    async def test_missing_occupied_and_wrong_account_deny_admission(self):
        for changes in ({"bucket": "MISSING"}, {"account": "WRONG"}):
            controller, owner, boundary = await self.new_owner("candidate" + str(len(self.boundaries)))
            with self.assertRaises(Exception):
                await owner.acquire_controller_authority(boundary, **{
                    "account": "LAB", "bucket": "AUTHORITY", "key": "controller", "timeout_s": 1, **changes})
            self.assertFalse(controller.check_ready().ready)
        await self.acquire()
        controller, owner, boundary = await self.new_owner("occupied")
        with self.assertRaises(KeyWrongLastSequenceError):
            await self.acquire(owner, boundary)
        self.assertFalse(controller.check_ready().ready)

    async def test_memory_or_expiring_bucket_is_not_authority(self):
        for index, config in enumerate((KeyValueConfig(bucket="MEMORY", storage=StorageType.MEMORY),
                                        KeyValueConfig(bucket="EXPIRING", storage=StorageType.FILE, ttl=30))):
            await self.js.create_key_value(config)
            controller, owner, boundary = await self.new_owner("invalid" + str(index))
            with self.assertRaisesRegex(RuntimeError, "persistent"):
                await owner.acquire_controller_authority(boundary, account="LAB", bucket=config.bucket,
                                                        key="controller", timeout_s=1)
            self.assertFalse(controller.check_ready().ready)

    async def test_unknown_acquisition_and_cancellation_retain_claim_without_admission(self):
        original = type(self.kv).create
        for index, cancel in enumerate((False, True)):
            controller, owner, boundary = await self.new_owner("uncertain" + str(index))
            key = "uncertain" + str(index)
            async def uncertain(kv, key, value, **kwargs):
                await original(kv, key, value, **kwargs)
                if cancel:
                    raise asyncio.CancelledError()
                raise TimeoutError("Acquisition acknowledgment unavailable")
            with patch.object(type(self.kv), "create", uncertain):
                with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                    await owner.acquire_controller_authority(boundary, account="LAB", bucket="AUTHORITY",
                                                            key=key, timeout_s=1)
            self.assertFalse(controller.check_ready().ready)
            self.assertEqual((await self.kv.get(key)).value.decode(), owner.operational_instance_id)
            with self.assertRaisesRegex(RuntimeError, "already attempted"):
                await owner.acquire_controller_authority(boundary, account="LAB", bucket="AUTHORITY",
                                                        key=key, timeout_s=1)

    async def test_normal_stop_release_and_post_retirement_mutation_rejection(self):
        await self.acquire()
        command, result = await self.stop()
        self.assertEqual((await self.kv.get("controller")).value.decode(), self.owner.operational_instance_id)
        await self.owner.complete_retirement(command, result)
        await self.owner.complete_retirement(command, result)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")
        with self.assertRaises(RuntimeError):
            await self.controller.close_saved_session_archive_remote("session", communication=None,
                storage_participant=RuntimeParticipant("storage_manager", "storage"), result_window_s=1)

    async def test_blocked_stop_then_authorized_kill_releases_once(self):
        await self.acquire()
        self.controller.maintenance_blockers = lambda *args: ["Demonstration unresolved obligation"]
        blocked = await self.owner.execute_command(self.command())
        self.assertEqual(blocked.payload["outcome"], "blocked")
        self.assertIsNotNone(await self.kv.get("controller"))
        command = self.command("kill", authorized=True)
        result = await self.owner.execute_command(command)
        self.assertTrue(result.success, result.reason)
        await self.owner.complete_retirement(command, result)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")

    async def test_failed_retirement_and_inflight_operation_keep_claim(self):
        await self.acquire()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def request(*args, **kwargs):
            entered.set()
            await finish.wait()
        communication = AsyncMock()
        communication.request_persistence_command.side_effect = request
        task = asyncio.create_task(self.controller.close_saved_session_archive_remote("session",
            communication=communication, storage_participant=RuntimeParticipant("storage_manager", "storage"),
            result_window_s=1))
        await entered.wait()
        result = await self.owner.execute_command(self.command())
        self.assertFalse(result.success)
        self.assertFalse(self.owner.terminated)
        self.assertIsNotNone(await self.kv.get("controller"))
        finish.set()
        await task
        await self.owner.execute_command(self.command("cancel"))
        self.owner.close_resources = AsyncMock(return_value=False)
        failed = await self.owner.execute_command(self.command(attempt="retry"))
        self.assertFalse(failed.success)
        self.assertFalse(self.owner.terminated)
        self.assertIsNotNone(await self.kv.get("controller"))

    async def test_release_failure_retry_and_stale_revision_protection(self):
        await self.acquire()
        command, result = await self.stop()
        with patch.object(type(self.kv), "delete", AsyncMock(side_effect=TimeoutError("unavailable"))):
            with self.assertRaises(TimeoutError):
                await self.owner.complete_retirement(command, result)
        self.assertTrue(self.owner.terminated)
        self.assertFalse(self.controller.check_ready().ready)
        await self.owner.complete_retirement(command, result)
        _, replacement, boundary = await self.new_owner("replacement")
        await self.acquire(replacement, boundary)
        await self.owner.complete_retirement(command, result)
        self.assertEqual((await self.kv.get("controller")).value.decode(), replacement.operational_instance_id)

    async def test_stale_revision_after_uncertain_delete_cannot_remove_replacement(self):
        await self.acquire()
        original_entry = await self.kv.get("controller")
        command, result = await self.stop()
        original = type(self.kv).delete
        async def uncertain(kv, key, **kwargs):
            await original(kv, key, **kwargs)
            raise TimeoutError("Release acknowledgment unavailable")
        with patch.object(type(self.kv), "delete", uncertain):
            with self.assertRaises(TimeoutError):
                await self.owner.complete_retirement(command, result)
        _, replacement, boundary = await self.new_owner("replacement")
        await self.acquire(replacement, boundary)
        with self.assertRaisesRegex(RuntimeError, "owner/revision"):
            await self.owner.complete_retirement(command, result)
        # Even a stale read cannot bypass the server's conditional-delete boundary.
        with patch.object(type(self.kv), "get", AsyncMock(return_value=original_entry)), self.assertRaises(BadRequestError) as rejected:
            await self.owner.complete_retirement(command, result)
        self.assertEqual(rejected.exception.err_code, 10071)
        self.assertEqual((await self.kv.get("controller")).value.decode(), replacement.operational_instance_id)

    async def test_disconnect_and_broker_restart_retain_claim(self):
        await self.acquire()
        await self.client.close()
        await self.boundary.close()  # Abrupt transport loss, without maintenance retirement.
        self.server.stop()
        await self.server.start()
        controller, owner, boundary = await self.new_owner("restarted")
        with self.assertRaises(KeyWrongLastSequenceError):
            await self.acquire(owner, boundary)
        self.assertFalse(controller.check_ready().ready)

    async def test_unavailable_storage_and_unretired_release_fail_closed(self):
        await self.boundary.close()
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.acquire()
        self.assertFalse(self.controller.check_ready().ready)
        controller, owner, boundary = await self.new_owner("available")
        await self.acquire(owner, boundary)
        with self.assertRaisesRegex(RuntimeError, "retirement"):
            await boundary.release_controller_claim(operational_instance_id=owner.operational_instance_id)
        self.assertTrue(controller.check_ready().ready)
        self.assertEqual((await self.kv.get("controller")).value.decode(), owner.operational_instance_id)

    async def test_preparation_retains_claim_without_operational_retirement(self):
        await self.acquire()
        prepare = self.command("prepare_stop")
        prepare.payload["framework_stop_attempt_id"] = "framework"
        result = await self.owner.execute_command(prepare)
        self.assertTrue(result.success, result.reason)
        self.assertTrue(self.owner.prepared)
        self.assertFalse(self.owner.terminated)
        with self.assertRaises(RuntimeError):
            await self.owner.complete_retirement(prepare, result)
        self.assertIsNotNone(await self.kv.get("controller"))

    async def test_launcher_completes_existing_local_stop_and_claim_release(self):
        await self.acquire()
        launcher = ServiceLauncher((self.owner,), (self.boundary,), report=lambda text: None)
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertTrue(launcher.exit_ready)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")

    async def test_remote_stop_preserves_result_handling_and_releases_claim(self):
        from lab_sync_acquisition import NatsServiceMaintenanceCommunication
        from lab_sync_acquisition.service_maintenance_cli import request_service_maintenance
        await self.acquire()
        await self.boundary.ensure_streams()
        async def publish(evidence):
            self.assertTrue(self.ingestor.receive_runtime_evidence(evidence).accepted)
        self.owner.evidence_publisher = publish
        handler = NatsServiceMaintenanceCommunication(self.boundary, self.owner)
        await handler.subscribe_commands()
        launcher = ServiceLauncher((self.owner,), (self.boundary,), report=lambda text: None)
        messages = []
        exit_code = await request_service_maintenance(servers=(self.url,), participant=self.owner.participant,
            operation="stop", administrator_id="operator", result_window_s=2, report=messages.append)
        self.assertEqual(exit_code, 0, messages)
        async with asyncio.timeout(2):
            while not launcher.exit_ready:
                await asyncio.sleep(0.01)
        self.assertTrue(self.owner.terminated)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")

