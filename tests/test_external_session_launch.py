"""External launch requests use a live restricted broker and existing service owners."""

import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import AsyncMock, patch

from nats.aio.client import Client as NATS

from lab_sync_acquisition.communication import (
    ExternalSessionLaunchRequest, ExternalSessionLaunchResult, RuntimeParticipant,
    EXTERNAL_CONTROLLER_OPERATIONS,
)
from lab_sync_acquisition.controller import Controller
from lab_sync_acquisition.nats_communication import (
    NatsCommunicationBoundary, NatsExternalSessionLaunchClient, NatsExternalSessionLaunchReceiver,
)
from lab_sync_acquisition.service_maintenance import ServiceMaintenanceInterface
from lab_sync_acquisition.service_launcher import ServiceLauncher
from lab_sync_acquisition.service_startup import launch_independent_service
from tests.test_session_launch import _Boundary
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server
from tests import test_session_launch


SUBJECT = "controller_external.controller.tester.launch_session"
AUTHORIZATION = '''users: [
  {user: service, password: service},
  {user: tester, password: tester, permissions: {
    publish: ["controller_external.controller.tester.launch_session"], subscribe: ["_INBOX.>"]}},
  {user: outsider, password: outsider, permissions: {publish: ["unused.>"], subscribe: ["_INBOX.>"]}}
]'''
AUTHORIZATION = AUTHORIZATION.replace('"controller_external.controller.tester.launch_session"',
    ", ".join(json.dumps(f"controller_external.controller.tester.{operation}")
              for operation in ("launch_session", *EXTERNAL_CONTROLLER_OPERATIONS)))


class ExternalLaunchModelTests(unittest.TestCase):
    def test_invalid_envelopes_are_rejected(self):
        for data in ({}, {"controller_id": "*"}, {"operation": "kill"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                ExternalSessionLaunchRequest.from_dict(data)

    def test_success_requires_a_real_controller_outcome_and_session_identity(self):
        for outcome in (None, {}, {"succeeded": True, "details": {}}):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                ExternalSessionLaunchResult("controller", "tester", "request-1", "succeeded", outcome)


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class ExternalLaunchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = test_session_launch.SessionLaunchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        await self.fixture.services()
        self.node, declaration, _ = await self.fixture.node()
        self.url = await self.enterAsyncContext(temporary_jetstream_server(authorization=AUTHORIZATION))
        self.server = NatsCommunicationBoundary("controller", "controller", (self.auth_url("service"),))
        await self.server.connect()
        self.addAsyncCleanup(self.server.close)
        self.client_boundary = NatsCommunicationBoundary("client", "tester", (self.auth_url("tester"),))
        await self.client_boundary.connect()
        self.addAsyncCleanup(self.client_boundary.close)
        self.client = NatsExternalSessionLaunchClient(self.client_boundary)
        self.maintenance = ServiceMaintenanceInterface(self.fixture.controller,
            RuntimeParticipant("controller", "controller"), ingestor=None, storage_manager=None,
            preservation_window_s=0, close_resources=AsyncMock(return_value=True))
        self.receiver = self.make_receiver()
        await self.receiver.start()
        self.addAsyncCleanup(self.receiver.close)
        self.request = ExternalSessionLaunchRequest("controller", "tester", "request-1",
            {"node-a": [declaration.to_dict()]}, self.fixture.config, [])

    def auth_url(self, user):
        return self.url.replace("nats://", f"nats://{user}:{user}@")

    def make_receiver(self, controller=None):
        return NatsExternalSessionLaunchReceiver(self.server, controller or self.fixture.controller,
            communication=self.fixture.communication, maintenance=self.maintenance,
            client_id="tester", participants=self.fixture.participants, result_window_s=0.1)

    async def terminal(self, request=None):
        for _ in range(100):
            result = await self.client.request_launch(request or self.request, timeout_s=1)
            if result.status != "pending":
                return result
            await asyncio.sleep(0.01)
        self.fail("External launch did not reach a terminal outcome")

    async def raw(self, data):
        message = await self.client_boundary._require_client().request(SUBJECT, json.dumps(data).encode(), timeout=1)
        return ExternalSessionLaunchResult.from_dict(json.loads(message.data))

    async def test_launch_reaches_original_owner_and_completed_duplicates_do_not_reinitialize(self):
        result = await self.terminal()
        self.assertEqual(result.status, "succeeded", result)
        sid = result.outcome["details"]["session_id"]
        self.assertEqual(self.fixture.controller.get_status()["session_id"], sid)
        self.assertEqual(self.node.reserved_for_session_id, sid)
        commands = len(self.fixture.broker.commands)
        self.assertEqual((await self.terminal()).to_dict(), result.to_dict())
        self.assertEqual(len(self.fixture.broker.commands), commands)

    async def test_conflicting_payload_and_wrong_target_are_rejected(self):
        self.request = replace(self.request, config_parameters={**self.fixture.config, "protocol_plan": {"value": True}})
        self.assertEqual((await self.terminal()).status, "succeeded")
        # JSON boolean and numeric parameters must not alias through Python equality.
        changed = replace(self.request, config_parameters={**self.fixture.config, "protocol_plan": {"value": 1}})
        self.assertEqual((await self.terminal(changed)).status, "rejected")
        wrong = {**self.request.to_dict(), "controller_id": "other"}
        self.assertEqual((await self.raw(wrong)).status, "rejected")
        no_receiver = replace(self.request, controller_id="absent")
        self.assertEqual((await self.client.request_launch(no_receiver, timeout_s=0.05)).status, "uncertain")

    async def test_invalid_inputs_cannot_dispatch_and_unknown_nodes_are_rejected(self):
        data = self.request.to_dict()
        data["selections"] = []
        self.assertEqual((await self.raw(data)).status, "rejected")
        unknown = replace(self.request, selections={"unknown": self.request.selections["node-a"]})
        self.assertEqual((await self.terminal(unknown)).status, "rejected")
        self.assertIsNone(self.fixture.controller.get_status()["session_id"])
        self.assertEqual(self.fixture.broker.commands, [])

    async def test_pending_concurrent_duplicates_and_client_disconnect_do_not_cancel_launch(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        original_publish = self.fixture.broker.publish

        async def delayed(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "initialize_session":
                entered.set()
                await resume.wait()
            return await original_publish(subject, data, stream)

        self.fixture.broker.publish = delayed
        try:
            results = await asyncio.gather(*(self.client.request_launch(self.request, timeout_s=1) for _ in range(3)))
            self.assertTrue(all(r.status == "pending" for r in results))
            await asyncio.wait_for(entered.wait(), 1)
            await self.client_boundary.close()
            resume.set()
            await self.client_boundary.connect()
            self.assertEqual((await self.terminal()).status, "succeeded")
            reserves = [c for c in self.fixture.broker.commands if c["command_type"] == "reserve"]
            self.assertEqual(len(reserves), 1)
        finally:
            resume.set()

    async def test_lost_response_returns_uncertain_then_recovers_same_outcome(self):
        transport = self.server._require_client()
        publish = transport.publish
        async def lose(subject, *args, **kwargs):
            if not subject.startswith("_INBOX."):
                await publish(subject, *args, **kwargs)
        with patch.object(transport, "publish", side_effect=lose):
            result = await self.client.request_launch(self.request, timeout_s=0.05)
        self.assertEqual(result.status, "uncertain")
        result = await self.terminal()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len([c for c in self.fixture.broker.commands if c["command_type"] == "reserve"]), 1)

    async def test_client_cancellation_does_not_cancel_admitted_launch(self):
        transport = self.server._require_client()
        published = asyncio.Event()
        publish = transport.publish
        async def lose(subject, *args, **kwargs):
            if subject.startswith("_INBOX."):
                published.set()
            else:
                await publish(subject, *args, **kwargs)
        with patch.object(transport, "publish", side_effect=lose):
            waiting = asyncio.create_task(self.client.request_launch(self.request, timeout_s=1))
            await asyncio.wait_for(published.wait(), 1)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
        self.assertEqual((await self.terminal()).status, "succeeded")
        self.assertEqual(len([c for c in self.fixture.broker.commands if c["command_type"] == "reserve"]), 1)

    async def test_interrupted_subscription_setup_retains_teardown_ownership(self):
        await self.receiver.close()
        receiver = self.make_receiver()
        self.addAsyncCleanup(receiver.close)
        transport = self.server._require_client()
        subscribe = transport.subscribe
        entered, resume = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            subscription = await subscribe(*args, **kwargs)
            entered.set()
            await resume.wait()
            return subscription
        with patch.object(transport, "subscribe", side_effect=delayed):
            starting = asyncio.create_task(receiver.start())
            await asyncio.wait_for(entered.wait(), 1)
            starting.cancel()
            resume.set()
            with self.assertRaises(asyncio.CancelledError):
                await starting
        await receiver.close()
        self.assertEqual((await self.client.request_launch(self.request, timeout_s=0.05)).status, "uncertain")

    async def test_lifecycle_failure_retains_existing_rollback_behavior(self):
        bad = replace(self.request, config_parameters={**self.fixture.config, "unknown_field": True})
        result = await self.terminal(bad)
        self.assertEqual(result.status, "failed")
        self.assertIsNone(self.fixture.controller.get_status()["session_id"])
        self.assertIsNone(self.node.reserved_for_session_id)
        self.assertTrue(any(c["command_type"] == "release_reservation" for c in self.fixture.broker.commands))

    async def test_maintenance_admission_blocks_new_launch(self):
        self.maintenance._closeout_started = True
        self.assertEqual((await self.terminal()).status, "rejected")
        self.assertEqual(self.fixture.broker.commands, [])

    async def test_broker_denies_unauthorized_publisher_even_with_forged_client_identity(self):
        errors = []
        async def error(error):
            errors.append(error)
        outsider = NATS()
        await outsider.connect(servers=[self.auth_url("outsider")], error_cb=error, allow_reconnect=False)
        try:
            await outsider.publish(SUBJECT, json.dumps(self.request.to_dict()).encode())
            await outsider.flush()
            for _ in range(50):
                if errors:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(any("permissions violation" in str(e).lower() for e in errors), errors)
            self.assertIsNone(self.fixture.controller.get_status()["session_id"])
            self.assertEqual(self.fixture.broker.commands, [])
        finally:
            await outsider.close()

    async def test_receiver_shutdown_removes_interest_without_repeating_completed_work(self):
        self.assertEqual((await self.terminal()).status, "succeeded")
        commands = len(self.fixture.broker.commands)
        await self.receiver.close()
        self.assertEqual((await self.client.request_launch(self.request, timeout_s=0.05)).status, "uncertain")
        self.assertEqual(len(self.fixture.broker.commands), commands)

    async def test_shutdown_joins_pending_launch_instead_of_cancelling_it(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.fixture.broker.publish
        async def delayed(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "initialize_session":
                entered.set()
                await resume.wait()
            return await original(subject, data, stream)
        self.fixture.broker.publish = delayed
        await self.client.request_launch(self.request, timeout_s=1)
        await asyncio.wait_for(entered.wait(), 1)
        closing = asyncio.create_task(self.receiver.close())
        try:
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            self.assertTrue(self.fixture.controller.check_ready().ready)
            resume.set()
            await asyncio.wait_for(closing, 2)
            self.assertEqual(self.fixture.controller.get_status()["session_state"], "initialized")
            self.assertIsNotNone(self.node.reserved_for_session_id)
        finally:
            resume.set()
            await closing

    async def test_production_startup_wires_external_requests_to_its_original_controller(self):
        await self.receiver.close()
        owners = []
        def construct(**kwargs):
            owner = Controller(**kwargs)
            owners.append(owner)
            return owner
        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.fixture.broker)
            value._client = self.server._client
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            return value
        async def registered(interface):
            interface._dependency_registration = {}
        async def run(launcher, *, startup):
            await startup()
            result = await self.terminal()
            self.assertEqual(result.status, "succeeded", result)
            self.assertEqual(len(owners), 1)
            self.assertIs(launcher.maintenance[0].service, owners[0])
            self.assertEqual(owners[0].get_status()["session_id"], result.outcome["details"]["session_id"])
            await launcher.maintenance[0].close_resources(False)
            return 0
        with patch("lab_sync_acquisition.service_startup.Controller", side_effect=construct) as constructor, patch(
                "lab_sync_acquisition.service_startup.NatsCommunicationBoundary", side_effect=boundary), patch.object(
                ServiceLauncher, "run", run), patch.object(ServiceMaintenanceInterface, "register_ingestor_dependency", registered), patch(
                "lab_sync_acquisition.service_startup.NatsServiceMaintenanceCommunication.start", AsyncMock(return_value={})):
            result = await launch_independent_service(role="controller", servers=(self.url,), service_id="controller",
                ingestor_id="ingestor", storage_id="storage", preservation_window_s=0.1, result_window_s=0.1,
                synchronization_id="sync", known_nodes=("node-a",), external_client_id="tester", report=lambda _: None)
        self.assertEqual(result, 0)
        constructor.assert_called_once_with(component_id="controller")

    async def test_new_receiver_lifetime_has_no_request_replay(self):
        self.assertEqual((await self.terminal()).status, "succeeded")
        await self.receiver.close()
        # New process/owner semantics: no requests are replayed on startup.
        owner = Controller()
        maintenance = ServiceMaintenanceInterface(owner, RuntimeParticipant("controller", "controller"),
            ingestor=None, storage_manager=None, preservation_window_s=0, close_resources=AsyncMock(return_value=True))
        receiver = NatsExternalSessionLaunchReceiver(self.server, owner, communication=self.fixture.communication,
            maintenance=maintenance, client_id="tester", participants=self.fixture.participants, result_window_s=0.1)
        commands = len(self.fixture.broker.commands)
        await receiver.start()
        await receiver.close()
        self.assertIsNone(owner.get_status()["session_id"])
        self.assertEqual(len(self.fixture.broker.commands), commands)
