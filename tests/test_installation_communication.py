"""Explicit installation readiness checks through real node handlers and simulated NATS."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from nats.js.api import DeliverPolicy

from lab_sync_acquisition import AcquisitionNode, DeviceManager, DeviceReadiness, NatsAcquisitionNodeCommunication
from lab_sync_acquisition.installation_communication import verify_node_communication
from lab_sync_acquisition.service_launcher import main
from tests.fakes import ReadyFakeAdapter
from tests.test_session_launch import _Boundary, _Broker


def controller_configuration(directory, **changes):
    path = Path(directory) / "controller.json"
    path.write_text(json.dumps({"servers": ["nats://example:4222"], "service_id": "controller",
        "ingestor_id": "intake", "storage_id": "storage", "synchronization_id": "clock",
        "preservation_window_s": 1, "result_window_s": 0.03, "known_nodes": ["node", "offline"],
        **changes}), encoding="utf-8")
    return path


class NodeVerificationCommandTests(unittest.TestCase):
    def test_event_loop_startup_failure_does_not_claim_communication(self):
        output = io.StringIO()
        with patch("lab_sync_acquisition.service_launcher.asyncio.run", side_effect=OSError("private detail")), redirect_stdout(output):
            code = main(["verify-node", "--deployment-config", "controller.json", "--node-id", "node"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result["communication_confirmed"])
        self.assertIn("unconfirmed", result["failure_reason"])
        self.assertNotIn("private detail", result["failure_reason"])

    def test_common_cli_dispatches_only_configured_verification(self):
        async def verify(path, node):
            self.assertEqual(path, Path("controller.json"))
            self.assertEqual(node, "node")
            return 1

        def run(coroutine):
            try:
                coroutine.send(None)
            except StopIteration as done:
                return done.value

        with patch("lab_sync_acquisition.installation_communication.verify_node_communication", verify), patch(
                "lab_sync_acquisition.service_launcher.asyncio.run", run):
            self.assertEqual(main(["verify-node", "--deployment-config", "controller.json", "--node-id", "node"]), 1)

    def test_configuration_and_node_are_required_without_setting_overrides(self):
        args = ["verify-node", "--deployment-config", "controller.json", "--node-id", "node"]
        invalid = [["verify-node"], args[:3], ["verify-node", "--node-id", "node"]]
        for flag, value in (("--server", "nats://other:4222"), ("--result-window-s", "2"),
                            ("--source-path", "remote"), ("--known-node", "other")):
            invalid.append([*args, flag, value])
        for arguments in invalid:
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)


class NodeCommunicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.config = controller_configuration(self.directory)
        self.broker = _Broker()
        self.reports, self.terminals = [], []
        self.adapter = ReadyFakeAdapter("device", "fake", (), True)
        self.adapter.initialize({})
        self.node = AcquisitionNode(device_manager=DeviceManager((self.adapter,)),
                                    synchronization_source_id="clock", node_id="node", role="acquisition")

    def terminal(self, kind, identity, servers):
        self.assertEqual(servers, ("nats://example:4222",))
        boundary = _Boundary(kind, identity, self.broker)
        boundary.connect = AsyncMock()
        boundary.close = AsyncMock()
        self.terminals.append(boundary)
        return boundary

    async def serve(self):
        await NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", self.broker), self.node).subscribe_commands()

    async def verify(self, node="node", factory=None):
        with patch("lab_sync_acquisition.installation_communication.NatsCommunicationBoundary", factory or self.terminal):
            code = await verify_node_communication(self.config, node, report=self.reports.append)
        return code, json.loads(self.reports[-1])

    def assert_cleaned(self):
        self.terminals[-1].close.assert_awaited_once()
        self.assertTrue(all(not s.active for s in self.broker.subscriptions if ".command_result." in s.subject))

    async def test_current_registered_response_confirms_communication_only(self):
        await self.serve()
        # Technical/synchronization unreadiness is not a failed communication check.
        with patch.object(self.adapter, "check_ready", return_value=DeviceReadiness("device", True, "ready", ())):
            code, result = await self.verify()
        self.assertEqual(code, 0)
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["communication_confirmed"])
        self.assertEqual(result["node_readiness"]["node_id"], "node")
        self.assertFalse(result["node_readiness"]["ready"])
        self.assertEqual(len(self.broker.commands), 1)
        self.assertEqual(self.broker.commands[0]["command_type"], "check_readiness")
        self.assertIsNone(self.broker.commands[0]["session_id"])
        self.assertNotEqual(self.broker.commands[0]["source_id"], "controller")
        self.assert_cleaned()

    async def test_unready_hardware_response_does_not_require_initialization(self):
        await self.serve()
        before = self.node.status()
        with patch.object(self.adapter, "check_ready", return_value=DeviceReadiness("device", False, "disconnected", ())), patch.object(
                self.adapter, "initialize") as initialize, patch.object(self.adapter, "start") as start:
            code, result = await self.verify()
        self.assertEqual(code, 0)
        self.assertFalse(result["node_readiness"]["device_readiness"][0]["ready"])
        initialize.assert_not_called()
        start.assert_not_called()
        self.assertEqual(self.node.status(), before)
        self.assertIsNone(self.node.local_storage_manager)
        self.assertEqual(self.node.runtime_evidence, ())
        self.assert_cleaned()

    async def test_unknown_invalid_and_ambiguous_registration_do_not_connect(self):
        for node in ("unknown", "bad.*", " "):
            with self.subTest(node=node):
                code, result = await self.verify(node)
                self.assertEqual(code, 1)
                self.assertFalse(result["communication_confirmed"])
        for changes in ({"known_nodes": ["node", "node"]}, {"result_window_s": 0}):
            self.config = controller_configuration(self.directory, **changes)
            self.assertEqual((await self.verify())[0], 1)
        self.assertEqual(self.terminals, [])
        self.assertEqual(self.broker.commands, [])

    async def test_offline_node_is_unknown_with_bounded_wait_and_cleanup(self):
        code, result = await asyncio.wait_for(self.verify(), 1)
        self.assertEqual(code, 1)
        self.assertIn("availability is unknown", result["failure_reason"])
        self.assertIsNone(result["node_readiness"])
        self.assert_cleaned()

    async def test_stale_mismatched_and_invalid_replies_do_not_confirm(self):
        await self.serve()
        changes = ({"command_id": "old"}, {"source_id": "other"}, {"target_id": "other"},
                   {"session_id": "session"}, {"success": "yes"}, {"payload": {"request_nonce": "old"}},
                   {"status": "invalid"}, {"payload": {"acquisition_node_readiness": {}}})
        for change in changes:
            with self.subTest(change=change):
                self.broker.change_result = lambda operation, result: {**result, **change}
                code, result = await self.verify()
                self.assertEqual(code, 1)
                self.assertFalse(result["communication_confirmed"])
                self.assertIsNotNone(result["failure_reason"])
                self.assert_cleaned()

    async def test_malformed_reply_is_reported_without_leaking_callback_failure(self):
        await self.serve()
        self.broker.change_result = lambda operation, result: {"invalid": True}
        code, result = await self.verify()
        self.assertEqual(code, 1)
        self.assertIn("Malformed", result["failure_reason"])
        self.assert_cleaned()

    async def test_invalid_node_report_with_current_correlation_cannot_confirm(self):
        await self.serve()
        for change in ({"node_id": "other"}, {"ready": "yes"}, {"device_readiness": None},
                       {"service_readiness": [{}]}, {"reserved_for_session_id": 7}):
            def mutate(operation, response):
                payload = response["payload"]
                return {**response, "payload": {**payload, "acquisition_node_readiness": {
                    **payload["acquisition_node_readiness"], **change}}}
            self.broker.change_result = mutate
            with self.subTest(change=change):
                code, result = await self.verify()
                self.assertEqual(code, 1)
                self.assertIn("Invalid AcquisitionNode", result["failure_reason"])
                self.assert_cleaned()

    async def test_node_rejection_and_publication_failure_do_not_confirm(self):
        await self.serve()
        self.broker.change_result = lambda operation, response: {
            **response, "success": False, "status": "failed", "reason": "unavailable"}
        code, result = await self.verify()
        self.assertEqual(code, 1)
        self.assertIn("rejected", result["failure_reason"])
        self.assert_cleaned()
        with patch.object(self.broker, "publish", side_effect=OSError("publication failed")):
            code, result = await self.verify()
        self.assertEqual(code, 1)
        self.assertFalse(result["communication_confirmed"])
        self.assert_cleaned()

    async def test_readiness_check_preserves_an_existing_reservation(self):
        self.assertTrue(self.node.reserve("session-in-use"))
        await self.serve()
        before = self.node.status()
        code, result = await self.verify()
        self.assertEqual(code, 0)
        self.assertEqual(result["node_readiness"]["reserved_for_session_id"], "session-in-use")
        self.assertEqual(self.node.status(), before)
        self.assertEqual(self.node.runtime_evidence, ())
        self.assertIsNone(self.node.local_storage_manager)

    async def test_historical_and_wrong_operation_responses_are_not_current_proof(self):
        original = self.broker.subscribe

        async def subscribe(subject, cb, **kwargs):
            subscription = await original(subject, cb, **kwargs)
            if ".command_result." in subject:
                self.assertEqual(kwargs["config"].deliver_policy, DeliverPolicy.NEW)
            return subscription

        async def unrelated(subject, data, stream):
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                payload = {"result_id": "historical", "command_id": command["command_id"], "session_id": None,
                    "source_id": "node", "target_id": command["source_id"], "success": True,
                    "status": "succeeded", "reason": None, "payload": command["payload"]}
                await publish("messages.command_result.acquisition_node.node.get_inventory", json.dumps(payload).encode(), "LAB_COMMAND_RESULTS")
                await publish("messages.evidence.acquisition_node.node.service_readiness", b"{}", "LAB_EVIDENCE")
            return await publish(subject, data, stream)

        publish = self.broker.publish
        with patch.object(self.broker, "subscribe", subscribe), patch.object(self.broker, "publish", unrelated):
            code, result = await self.verify()
        self.assertEqual(code, 1)
        self.assertFalse(result["communication_confirmed"])
        self.assert_cleaned()

    async def test_transport_failure_and_cleanup_failure_cannot_report_pass(self):
        await self.serve()
        def factory(kind, identity, servers):
            boundary = self.terminal(kind, identity, servers)
            boundary.connect.side_effect = ConnectionError("private connection detail")
            return boundary

        code, result = await self.verify(factory=factory)
        self.assertEqual(code, 1)
        self.assertNotIn("private connection detail", result["failure_reason"])
        self.assert_cleaned()

        def cleanup_failure(kind, identity, servers):
            boundary = self.terminal(kind, identity, servers)
            boundary.close.side_effect = OSError("cleanup")
            return boundary

        code, result = await self.verify(factory=cleanup_failure)
        self.assertEqual(code, 1)
        self.assertTrue(result["communication_confirmed"])
        self.assertIn("cleanup unconfirmed", result["failure_reason"])

    async def test_cancellation_releases_verification_resources_without_maintenance(self):
        entered = asyncio.Event()
        async def pause(subject, data, stream):
            entered.set()
            await asyncio.Event().wait()

        with patch.object(self.broker, "publish", pause):
            task = asyncio.create_task(self.verify())
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            code, result = await task
        self.assertEqual(code, 1)
        self.assertIn("interrupted", result["failure_reason"])
        self.assertFalse(result["communication_confirmed"])
        self.assert_cleaned()

    async def test_subscription_cleanup_failure_still_closes_connection(self):
        await self.serve()
        subscribe = self.broker.subscribe
        async def failing_cleanup(subject, cb, **kwargs):
            subscription = await subscribe(subject, cb, **kwargs)
            if ".command_result." in subject:
                subscription.unsubscribe = AsyncMock(side_effect=OSError("unsubscribe"))
            return subscription

        with patch.object(self.broker, "subscribe", failing_cleanup):
            code, result = await self.verify()
        self.assertEqual(code, 1)
        self.assertTrue(result["communication_confirmed"])
        self.assertIn("subscription cleanup unconfirmed", result["failure_reason"])
        self.terminals[-1].close.assert_awaited_once()

    async def test_invalid_response_does_not_prevent_later_valid_current_response(self):
        await self.serve()
        original = self.broker.publish
        async def publish(subject, data, stream):
            if stream == "LAB_COMMAND_RESULTS":
                response = json.loads(data)
                stale = {**response, "payload": {"request_nonce": "old"}}
                await original(subject, json.dumps(stale).encode(), stream)
            return await original(subject, data, stream)

        with patch.object(self.broker, "publish", publish):
            code, result = await self.verify()
        self.assertEqual(code, 0)
        self.assertTrue(result["communication_confirmed"])
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main()
