"""Separate-terminal maintenance through real owners and broker-double transport."""

import asyncio
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, InMemoryIngestor, PersistentStorageManager,
    RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager,
    NatsServiceMaintenanceCommunication, NatsIngestorCommunication,
    NatsStorageManagerCommunication,
)
from lab_sync_acquisition.service_launcher import main, ServiceLauncher
from lab_sync_acquisition.service_maintenance_cli import request_service_maintenance
from tests.test_session_launch import _Boundary, _Broker
from tests.fakes import ReadyFakeAdapter


class MaintenanceCommandTests(unittest.TestCase):
    def arguments(self, operation="stop"):
        return [operation, "--server", "nats://example:4222", "--target-type", "ingestor",
                "--target-id", "intake", "--administrator-id", "operator", "--result-window-s", "1"]

    def test_remote_actions_use_common_entry_point(self):
        async def completed(**kwargs):
            self.assertEqual(kwargs["participant"], RuntimeParticipant("ingestor", "intake"))
            self.assertEqual(kwargs["administrator_id"], "operator")
            return 0

        def run(coroutine):
            with self.assertRaises(StopIteration) as done:
                coroutine.send(None)
            return done.exception.value

        with patch("lab_sync_acquisition.service_maintenance_cli.request_service_maintenance", completed), patch("lab_sync_acquisition.service_launcher.asyncio.run", run):
            self.assertEqual(main(self.arguments()), 0)

    def test_authorization_and_existing_attempt_are_explicit(self):
        invalid = [self.arguments("kill"), self.arguments("cancel"),
                   self.arguments("kill") + ["--stop-attempt-id", "blocked"],
                   self.arguments("stop") + ["--stop-attempt-id", "old"],
                   self.arguments("cancel") + ["--stop-attempt-id", "blocked", "--authorize-kill"]]
        for args in invalid:
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)

    def test_remote_settings_are_required_and_validated_before_connecting(self):
        for flag in ("--server", "--target-type", "--target-id", "--administrator-id", "--result-window-s"):
            args = self.arguments()
            index = args.index(flag)
            del args[index:index + 2]
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)
        for flag, value in (("--target-id", "bad.*"), ("--administrator-id", " "),
                            ("--result-window-s", "nan"), ("--result-window-s", "0")):
            args = self.arguments()
            args[args.index(flag) + 1] = value
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)

    def test_cli_preserves_nonzero_remote_outcome(self):
        async def failed(**kwargs):
            return 1

        def run(coroutine):
            try:
                coroutine.send(None)
            except StopIteration as done:
                return done.value

        with patch("lab_sync_acquisition.service_maintenance_cli.request_service_maintenance", failed), patch("lab_sync_acquisition.service_launcher.asyncio.run", run):
            self.assertEqual(main(self.arguments()), 1)

    def test_kill_and_cancel_dispatch_explicit_continuation(self):
        calls = []

        async def record(**kwargs):
            calls.append(kwargs)
            return 1

        def run(coroutine):
            try:
                coroutine.send(None)
            except StopIteration as done:
                return done.value

        with patch("lab_sync_acquisition.service_maintenance_cli.request_service_maintenance", record), patch("lab_sync_acquisition.service_launcher.asyncio.run", run):
            for operation in ("kill", "cancel"):
                flags = ["--authorize-kill"] if operation == "kill" else []
                self.assertEqual(main(self.arguments(operation) + ["--stop-attempt-id", "blocked", *flags]), 1)
        self.assertEqual([c["operation"] for c in calls], ["kill", "cancel"])
        self.assertEqual([c["authorized"] for c in calls], [True, False])
        self.assertTrue(all(c["stop_attempt_id"] == "blocked" for c in calls))


class RemoteMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.storage = PersistentStorageManager(root)
        self.intake = InMemoryIngestor(self.storage, framework_recovery_journal_path=root / "framework.jsonl")
        adapter = ReadyFakeAdapter("device", "fake", (), True)
        self.node = AcquisitionNode(device_manager=DeviceManager((adapter,)), synchronization_manager=SynchronizationManager(),
                                    ingestor=self.intake, node_id="node", role="acquisition")
        self.broker = _Broker()
        self.reports, self.terminals = [], []
        self.close = AsyncMock(return_value=True)
        self.owner = self.maintenance(self.node, "acquisition_node", "node")

    def maintenance(self, service, kind, identity):
        async def publish(message):
            self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)

        return ServiceMaintenanceInterface(service, RuntimeParticipant(kind, identity),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0,
            close_resources=self.close, evidence_publisher=publish)

    def terminal(self, kind, identity, servers):
        boundary = _Boundary(kind, identity, self.broker)
        boundary.connect = AsyncMock()
        boundary.ensure_streams = AsyncMock()
        boundary.close = AsyncMock()
        self.terminals.append(boundary)
        return boundary

    async def request(self, operation="stop", *, attempt=None, authorized=False, target=None, window=0.05):
        with patch("lab_sync_acquisition.service_maintenance_cli.NatsCommunicationBoundary", self.terminal):
            code = await request_service_maintenance(servers=("nats://example:4222",),
                participant=target or self.owner.participant, operation=operation, administrator_id="operator",
                result_window_s=window, stop_attempt_id=attempt, authorized=authorized, report=self.reports.append)
        return code, json.loads(self.reports[-1])

    async def serve(self):
        boundary = _Boundary("acquisition_node", "node", self.broker)
        await NatsServiceMaintenanceCommunication(boundary, self.owner).subscribe_commands()

    async def test_stop_reports_confirmed_owner_retirement_not_process_exit(self):
        await self.serve()
        code, feedback = await self.request()
        self.assertEqual(code, 0)
        self.assertTrue(self.owner.terminated)
        self.assertTrue(feedback["termination_confirmed"])
        self.assertEqual(feedback["outcome"], "completed")
        self.assertIn("OS process exit is not confirmed", feedback["operator_action"])
        request = self.broker.commands[-1]
        self.assertIsNone(request["session_id"])
        self.assertEqual(request["source_id"], feedback["requester_id"])
        self.assertEqual(request["payload"]["administrator_id"], "operator")
        self.terminals[-1].close.assert_awaited_once()

    async def test_blocked_stop_then_authorized_kill_uses_same_attempt(self):
        self.node.reserve("session")
        await self.serve()
        code, blocked = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(blocked["outcome"], "blocked")
        self.assertTrue(blocked["blockers"])
        code, killed = await self.request("kill", attempt=blocked["stop_attempt_id"], authorized=True)
        self.assertEqual(code, 0)
        self.assertEqual(killed["stop_attempt_id"], blocked["stop_attempt_id"])
        self.assertNotEqual(killed["requester_id"], blocked["requester_id"])
        self.assertTrue(self.broker.commands[-1]["payload"]["authorized"])
        self.close.assert_awaited_once_with(True)

    async def test_cancel_ends_blocked_attempt_and_later_stop_is_fresh(self):
        self.node.reserve("session")
        await self.serve()
        _, blocked = await self.request()
        code, cancelled = await self.request("cancel", attempt=blocked["stop_attempt_id"])
        # Existing maintenance records cancellation as a failed attempt, not a new outcome.
        self.assertEqual(code, 1)
        self.assertEqual(cancelled["outcome"], "failed")
        self.assertEqual(cancelled["reason"], "Administrator cancelled")
        self.close.assert_not_awaited()
        self.node.release_reservation("session")
        code, stopped = await self.request()
        self.assertEqual(code, 0)
        self.assertNotEqual(stopped["stop_attempt_id"], blocked["stop_attempt_id"])
        self.assertEqual(len({c["command_id"] for c in self.broker.commands}), 3)

    async def test_missing_result_is_unconfirmed_without_automatic_kill(self):
        code, feedback = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "unconfirmed")
        self.assertEqual([c["command_type"] for c in self.broker.commands], ["stop"])
        self.assertFalse(self.owner.terminated)

    async def test_lost_reply_does_not_claim_retirement_or_escalate(self):
        await self.serve()
        self.broker.drop_results.add(("node", "stop"))
        code, feedback = await self.request()
        self.assertTrue(self.owner.terminated)
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "unconfirmed")
        self.assertFalse(feedback["termination_confirmed"])

    async def test_slow_publication_is_bounded_without_escalation(self):
        published = []
        pending = asyncio.Event()

        async def pause(subject, data, stream):
            published.append(json.loads(data)["command_type"])
            await pending.wait()

        with patch.object(self.broker, "publish", pause):
            code, feedback = await self.request(window=0.01)
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "unconfirmed")
        self.assertEqual(published, ["stop"])
        self.close.assert_not_awaited()

    async def test_stale_attempt_is_reported_as_rejected_by_owner(self):
        await self.serve()
        code, feedback = await self.request("kill", attempt="unknown", authorized=True)
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "failed")
        self.assertIn("No matching blocked", feedback["reason"])
        self.close.assert_not_awaited()

    async def test_conflicting_command_rejection_cannot_confirm_retirement(self):
        from types import SimpleNamespace
        self.node.reserve("session")
        await self.serve()
        _, blocked = await self.request()
        identities = [SimpleNamespace(hex=value) for value in
                      ("new-attempt", "different-terminal", blocked["command_id"])]
        with patch("lab_sync_acquisition.service_maintenance_cli.uuid4", side_effect=identities):
            code, rejected = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(rejected["outcome"], "failed")
        self.assertEqual(rejected["reason"], "Conflicting command identity")
        self.assertFalse(self.owner.terminated)
        self.close.assert_not_awaited()

    async def test_wrong_result_subject_cannot_confirm_retirement(self):
        await self.serve()
        publish = self.broker.publish

        async def wrong_subject(subject, data, stream):
            if stream == "LAB_COMMAND_RESULTS":
                subject = subject.rsplit(".", 1)[0] + ".kill"
            return await publish(subject, data, stream)

        with patch.object(self.broker, "publish", wrong_subject):
            code, feedback = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "unconfirmed")

    async def test_interrupted_terminal_does_not_authorize_kill(self):
        for operation in ("stop", "cancel"):
            with self.subTest(operation=operation):
                with patch.object(self.broker, "publish", AsyncMock(side_effect=asyncio.CancelledError)):
                    code, feedback = await self.request(operation,
                        attempt="blocked" if operation == "cancel" else None)
                self.assertEqual(code, 1)
                self.assertEqual(feedback["outcome"], "unconfirmed")
                self.assertFalse(feedback["termination_confirmed"])
                self.assertIn("interrupted", feedback["reason"])
                self.assertIn("no automatic force escalation", feedback["reason"])
                self.assertIn("does not revoke a submitted request", feedback["reason"])
                self.assertNotIn("Explicitly authorized Kill", feedback["reason"])
        self.close.assert_not_awaited()

    async def test_interrupted_executed_kill_reports_uncertain_retirement(self):
        self.node.reserve("session")
        await self.serve()
        code, blocked = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(blocked["outcome"], "blocked")
        publish = self.broker.publish

        async def interrupt_reply(subject, data, stream):
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".kill"):
                self.assertTrue(self.owner.terminated)
                self.assertTrue(json.loads(data)["success"])
                raise asyncio.CancelledError()
            return await publish(subject, data, stream)

        with patch.object(self.broker, "publish", interrupt_reply):
            code, feedback = await self.request("kill", attempt=blocked["stop_attempt_id"], authorized=True)
        self.close.assert_awaited_once_with(True)
        self.assertTrue(self.owner.terminated)
        self.assertTrue(self.broker.commands[-1]["payload"]["authorized"])
        self.assertEqual(feedback["command"], "kill")
        self.assertEqual(feedback["stop_attempt_id"], blocked["stop_attempt_id"])
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "unconfirmed")
        self.assertFalse(feedback["termination_confirmed"])
        self.assertIn("Explicitly authorized Kill may already have been submitted or executed", feedback["reason"])
        self.assertIn("Interruption does not revoke a submitted request", feedback["reason"])
        self.assertIn("do not assume the target remains active or has retired", feedback["reason"])
        self.assertNotIn("no force requested", feedback["reason"])
        self.terminals[-1].close.assert_awaited_once()

    async def test_failed_terminal_cleanup_retains_received_blockers(self):
        self.node.reserve("session")
        await self.serve()
        terminal = self.terminal

        def fail_close(*args):
            boundary = terminal(*args)
            boundary.close.side_effect = ConnectionError("drain failed")
            return boundary

        with patch.object(self, "terminal", fail_close):
            code, feedback = await self.request()
        self.assertEqual(code, 1)
        self.assertEqual(feedback["outcome"], "blocked")
        self.assertTrue(feedback["blockers"])
        self.assertTrue(any("drain failed" in error for error in feedback["errors"]))

    async def test_mismatched_results_cannot_confirm_success(self):
        await self.serve()
        for field, value in (("command_id", "other"), ("source_id", "other"),
                             ("target_id", "other"), ("session_id", "other"),
                             ("success", "true")):
            with self.subTest(field=field):
                # The first request may retire the owner; subsequent rejected replies
                # are equally unable to confirm success with mismatched correlation.
                self.broker.change_result = lambda operation, data: {**data, field: value}
                code, feedback = await self.request()
                self.assertEqual(code, 1)
                self.assertEqual(feedback["outcome"], "unconfirmed")

    async def test_transport_failure_is_reported_and_connection_is_closed(self):
        with patch.object(self.broker, "publish", AsyncMock(side_effect=ConnectionError("offline"))):
            code, feedback = await self.request()
        self.assertEqual(code, 1)
        self.assertIn("offline", feedback["reason"])
        self.terminals[-1].close.assert_awaited_once()
        self.close.assert_not_awaited()

    async def test_shared_pair_requires_each_owner_result_before_exit(self):
        boundaries = (_Boundary("ingestor", "intake", self.broker),
                      _Boundary("storage_manager", "storage", self.broker))
        interfaces = (self.maintenance(self.intake, "ingestor", "intake"),
                      self.maintenance(self.storage, "storage_manager", "storage"))
        launcher = ServiceLauncher(interfaces, boundaries, report=lambda message: None)
        await NatsIngestorCommunication(boundaries[0], self.intake).subscribe_commands()
        await NatsStorageManagerCommunication(boundaries[1], self.storage).subscribe_commands()
        code, _ = await self.request(target=interfaces[0].participant)
        self.assertEqual(code, 0)
        self.assertTrue(interfaces[0].terminated)
        self.assertFalse(interfaces[1].terminated)
        self.assertFalse(launcher.exit_ready)
        self.assertIs(interfaces[0].storage_manager, interfaces[1].storage_manager)


if __name__ == "__main__":
    unittest.main()
