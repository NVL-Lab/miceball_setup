"""Native delivery responsibilities and transient owner readback on isolated NATS."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from nats.js.api import DiscardPolicy, RetentionPolicy, KeyValueConfig, StorageType

from lab_sync_acquisition import (
    Controller, NatsCommunicationBoundary, NatsControllerCommunication,
    NatsServiceMaintenanceCommunication, NatsSynchronizationManagerCommunication,
    RuntimeCommandResultMessage, RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager,
)
from lab_sync_acquisition.nats_communication import DurablePublicationError
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


@unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
class DeliveryResponsibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch("lab_sync_acquisition.service_launcher._read_terminal_choice", AsyncMock(return_value=None)))
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

    async def test_existing_stream_limits_preserve_outstanding_delivery(self):
        cases = (
            (True, {}),
            (True, dict(discard=DiscardPolicy.NEW)),
            (False, dict(max_msgs=1)),
            (False, dict(max_bytes=4096)),
            (False, dict(max_msgs_per_subject=1)),
            (False, dict(discard=DiscardPolicy.NEW, max_msgs_per_subject=1)),
            (False, dict(max_age=600)),
            (False, dict(discard=DiscardPolicy.NEW, max_age=600)),
            (True, dict(discard=DiscardPolicy.NEW, max_msgs=1)),
            (True, dict(discard=DiscardPolicy.NEW, max_bytes=4096)),
            (True, dict(discard=DiscardPolicy.NEW, max_msgs_per_subject=1,
                        discard_new_per_subject=True)),
            (True, dict(max_msg_size=1024)),
            (False, dict(discard=DiscardPolicy.NEW, max_msgs=10, max_msgs_per_subject=1)),
        )
        for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
            baseline = (await self.js.stream_info(stream)).config
            try:
                for accepted, changes in cases:
                    with self.subTest(stream=stream, changes=changes):
                        await self.js.update_stream(config=replace(baseline, **changes))
                        before = (await self.js.stream_info(stream)).config.as_dict()
                        if accepted:
                            await self.producer.ensure_streams()
                        else:
                            with self.assertRaisesRegex(RuntimeError, "unacknowledged"):
                                await self.producer.ensure_streams()
                        self.assertEqual((await self.js.stream_info(stream)).config.as_dict(), before)
            finally:
                await self.js.update_stream(config=baseline)

    async def test_bounded_result_capacity_refuses_publication_without_losing_old_result(self):
        for changes in (dict(max_msgs=1), dict(max_bytes=700),
                        dict(max_msgs_per_subject=1, discard_new_per_subject=True)):
            with self.subTest(changes=changes):
                baseline = (await self.js.stream_info("LAB_COMMAND_RESULTS")).config
                receiver = await self.connect("ingestor", "intake")
                await NatsControllerCommunication(receiver).subscribe_command_results(None)
                await receiver.close()
                await self.js.update_stream(config=replace(baseline, discard=DiscardPolicy.NEW, **changes))
                try:
                    await self.producer.ensure_streams()
                    first = self.result("intake", "first")
                    if "max_bytes" in changes:
                        first = replace(first, payload={**first.payload, "padding": "x" * 200})
                    await self.producer.publish_command_result(first, "confirm_dependent_release")
                    before = (await self.js.stream_info("LAB_COMMAND_RESULTS")).state
                    with self.assertRaises(DurablePublicationError):
                        await self.producer.publish_command_result(
                            replace(first, result_id="second"), "confirm_dependent_release")
                    after = (await self.js.stream_info("LAB_COMMAND_RESULTS")).state
                    self.assertEqual((after.messages, after.first_seq, after.last_seq),
                                     (before.messages, before.first_seq, before.last_seq))
                    replacement = await self.connect("ingestor", "intake")
                    received = asyncio.get_running_loop().create_future()
                    async def observe(result):
                        if not received.done():
                            received.set_result(result)
                    handle = await NatsControllerCommunication(replacement).subscribe_command_results(None, observe)
                    try:
                        self.assertEqual((await asyncio.wait_for(received, 2)).to_dict(), first.to_dict())
                        async with asyncio.timeout(2):
                            while (await self.js.stream_info("LAB_COMMAND_RESULTS")).state.messages:
                                await asyncio.sleep(0)
                    finally:
                        await handle.unsubscribe()
                        await replacement.close()
                finally:
                    await self.js.update_stream(config=baseline)

    async def test_per_message_expiry_is_not_compatible(self):
        for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
            baseline = (await self.js.stream_info(stream)).config
            if not hasattr(baseline, "allow_msg_ttl"):
                self.skipTest("SDK does not support per-message TTL")
            # TTL enablement is creation-only on supported servers. These fixture
            # streams are empty and have no consumers; no deployment is involved.
            await self.js.delete_stream(stream)
            await self.js.add_stream(config=replace(baseline, allow_msg_ttl=True))
            before = (await self.js.stream_info(stream)).config.as_dict()
            if not before.get("allow_msg_ttl"):
                self.skipTest("Server does not support per-message TTL")
            with self.subTest(stream=stream):
                with self.assertRaisesRegex(RuntimeError, "unacknowledged"):
                    await self.producer.ensure_streams()
                self.assertEqual((await self.js.stream_info(stream)).config.as_dict(), before)
            await self.js.delete_stream(stream)
            await self.js.add_stream(config=baseline)

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

    async def test_registered_dependency_release_retires_consumers_not_disconnect(self):
        from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        reports = []
        async def capture(launcher, *, startup):
            for boundary in launcher.boundaries:
                self.stack.push_async_callback(boundary.close)
            try:
                await asyncio.wait_for(startup(), 5)
            except TimeoutError as error:
                raise AssertionError(reports) from error
            return launcher
        with patch.object(ServiceLauncher, "run", capture):
            pair = await launch_storage_services(servers=(self.url,), ingestor_id="intake", storage_id="store",
                storage_root=root / "storage", recovery_journal_root=root / "sessions",
                framework_journal=root / "framework.jsonl", preservation_window_s=2,
                operational_dependents={}, external_dependents=(RuntimeParticipant("synchronization_manager", "sync"),),
                result_window_s=2, controller_claim_account="$G", controller_claim_bucket="UNUSED",
                controller_claim_key="controller", report=reports.append)
        service = SynchronizationManager()
        owner = ServiceMaintenanceInterface(service, RuntimeParticipant("synchronization_manager", "sync"),
            ingestor=None, storage_manager=None, preservation_window_s=2, registration_window_s=3,
            close_resources=AsyncMock(return_value=True), evidence_publisher=self.producer.publish_evidence,
            framework_communication=NatsControllerCommunication(self.producer),
            framework_ingestor=RuntimeParticipant("ingestor", "intake"),
            framework_storage=RuntimeParticipant("storage_manager", "store"))
        NatsServiceMaintenanceCommunication(self.producer, owner)
        await NatsSynchronizationManagerCommunication(self.producer, service).subscribe_commands()
        await owner.register_ingestor_dependency()
        self.assertTrue(pair.maintenance[0].operational_dependents[owner.participant]())
        launcher = ServiceLauncher((owner,), (self.producer,), report=reports.append)
        self.assertTrue(await asyncio.wait_for(launcher.stop_locally("operator"), 5), reports)
        self.assertFalse(pair.maintenance[0].operational_dependents[owner.participant]())
        remaining = await self.js.consumers_info("LAB_COMMANDS")
        self.assertFalse(any("synchronization_manager.sync" in (c.config.filter_subject or "") for c in remaining))
        self.assertTrue(await asyncio.wait_for(pair.stop_locally("operator"), 5), reports)
        for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
            self.assertEqual(await self.js.consumers_info(stream), [])

    async def test_coordinated_controller_release_uses_current_owner_proof(self):
        from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services
        await self.js.create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        scope = dict(account="$G", bucket="AUTHORITY", key="controller", timeout_s=3)
        controller_participant = RuntimeParticipant("controller", "control")
        sync_participant = RuntimeParticipant("synchronization_manager", "sync")
        reports = []
        async def capture(launcher, *, startup):
            for boundary in launcher.boundaries:
                self.stack.push_async_callback(boundary.close)
            await asyncio.wait_for(startup(), 5)
            return launcher
        with patch.object(ServiceLauncher, "run", capture):
            pair = await launch_storage_services(servers=(self.url,), ingestor_id="intake", storage_id="store",
                storage_root=root / "storage", recovery_journal_root=root / "sessions",
                framework_journal=root / "framework.jsonl", preservation_window_s=3,
                operational_dependents={}, external_dependents=(controller_participant, sync_participant),
                result_window_s=3, controller_claim_account="$G", controller_claim_bucket="AUTHORITY",
                controller_claim_key="controller", report=reports.append)
        control = Controller(component_id="control")
        control_boundary = await self.connect("controller", "control")
        interfaces = []
        for service, participant, boundary in (
                (SynchronizationManager(), sync_participant, self.producer),
                (control, controller_participant, control_boundary)):
            owner = ServiceMaintenanceInterface(service, participant, ingestor=None, storage_manager=None,
                preservation_window_s=3, registration_window_s=5, close_resources=AsyncMock(return_value=True),
                evidence_publisher=boundary.publish_evidence, framework_communication=NatsControllerCommunication(boundary),
                framework_ingestor=RuntimeParticipant("ingestor", "intake"),
                framework_storage=RuntimeParticipant("storage_manager", "store"))
            boundary.configure_controller_authority(**scope)
            communication = NatsServiceMaintenanceCommunication(boundary, owner)
            if participant.component_type == "controller":
                await owner.acquire_controller_authority(boundary, **scope)
                await communication.subscribe_commands()
            else:
                await NatsSynchronizationManagerCommunication(boundary, service).subscribe_commands()
            await owner.register_ingestor_dependency()
            if participant.component_type == "controller":
                decision = await owner.record_administrator_decision("operator", "resume", {})
                self.assertTrue(decision["evidence"]["is_persistent"])
            interfaces.append(owner)
        participants = (controller_participant, sync_participant, *(owner.participant for owner in pair.maintenance))
        result = await asyncio.wait_for(control.shutdown_framework(participants,
            communication=NatsControllerCommunication(control_boundary), stop_attempt_id="coordinated",
            administrator_id="operator", result_window_s=3), 20)
        self.assertTrue(result.succeeded, (result.error, result.details))
        self.assertTrue(all(owner.terminated for owner in (*interfaces, *pair.maintenance)))
        tasks = [task for boundary in (self.producer, control_boundary, *pair.boundaries)
                 for task in boundary._maintenance_delivery_tasks.values()]
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), 5)
        for stream in ("LAB_COMMANDS", "LAB_COMMAND_RESULTS", "LAB_EVIDENCE"):
            self.assertEqual(await self.js.consumers_info(stream), [])
