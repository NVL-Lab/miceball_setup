"""Manual launch and process lifetime around the existing maintenance owners."""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    Controller, InMemoryIngestor, NatsCommunicationBoundary,
    NatsServiceMaintenanceCommunication, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeParticipant, ServiceMaintenanceInterface,
    SessionConfig, RuntimeEvidenceMessage, NatsIngestorCommunication, NatsStorageManagerCommunication,
)
from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services, main
from tests.test_session_launch import _Boundary, _Broker


class LauncherCommandTests(unittest.TestCase):
    def test_help_describes_all_logical_roles(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        for role in ("controller", "acquisition-node", "ingestor", "storage-manager", "synchronization-manager"):
            self.assertIn(role, output.getvalue())

    def test_independent_roles_require_explicit_startup_settings(self):
        for role in ("controller", "acquisition-node", "synchronization-manager"):
            with self.subTest(role=role), patch("lab_sync_acquisition.service_launcher.asyncio.run") as run:
                output = io.StringIO()
                with redirect_stderr(output), self.assertRaises(SystemExit) as stopped:
                    main([role])
                self.assertNotEqual(stopped.exception.code, 0)
                self.assertIn("requires explicit", output.getvalue())
                run.assert_not_called()

    def test_pair_requires_explicit_constructor_settings(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(["ingestor"])
        self.assertNotEqual(stopped.exception.code, 0)

    def test_pair_rejects_invalid_window_or_empty_identity(self):
        base = ["storage-manager", "--server", "nats://example:4222", "--ingestor-id", "intake",
            "--storage-id", "storage", "--storage-root", "records", "--recovery-journal-root", "journals",
            "--framework-journal", "framework.jsonl", "--no-operational-dependents"]
        for value in ("nan", "inf", "-1"):
            with self.subTest(window=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main([*base, "--preservation-window-s", value])
        base[base.index("storage")] = ""
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([*base, "--preservation-window-s", "1"])

    def test_pair_never_silently_assumes_no_operational_dependents(self):
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            main(["ingestor", "--server", "nats://example:4222", "--ingestor-id", "intake",
                "--storage-id", "storage", "--storage-root", "records", "--recovery-journal-root", "journals",
                "--framework-journal", "framework.jsonl", "--preservation-window-s", "1"])
        self.assertIn("Explicit dependency configuration is required", output.getvalue())


class ServiceLauncherTests(unittest.IsolatedAsyncioTestCase):
    async def finish_task(self, task, launcher):
        if not task.done():
            # Cancellation deliberately retains a live launcher. Terminate only
            # this test task through its injected reporter on assertion failure.
            with patch.object(launcher, "_report", side_effect=RuntimeError("Fixture cleanup")):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        else:
            await task

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root)
        self.intake = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.controller = Controller(ingestor=self.intake, storage_manager=self.storage)
        self.close = AsyncMock(return_value=True)

        async def publish(message):
            self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)

        self.owner = ServiceMaintenanceInterface(self.controller, RuntimeParticipant("controller", "control"),
            ingestor=self.intake, storage_manager=self.storage,
            preservation_window_s=0, close_resources=self.close, evidence_publisher=publish)
        self.boundary = NatsCommunicationBoundary("controller", "control", servers=("nats://example:4222",))
        self.boundary.close = AsyncMock()
        self.reports = []
        self.launcher = ServiceLauncher((self.owner,), (self.boundary,), report=self.reports.append)

    async def test_local_stop_confirms_retirement_before_process_exit(self):
        self.launcher.request_interrupt()
        result = await self.launcher.run()
        self.assertEqual(result, 0)
        self.assertTrue(self.owner.terminated)
        self.assertTrue(self.launcher.exit_ready)
        self.close.assert_awaited_once_with(False)
        self.boundary.close.assert_awaited_once()
        self.assertEqual(json.loads(self.reports[-1])["outcome"], "completed")

    async def test_blocked_stop_cancels_same_attempt_and_keeps_running(self):
        self.assertTrue(self.controller.create_session(SessionConfig([], str(self.root), {},
            str(self.root), session_id="active")).succeeded)
        self.assertFalse(await self.launcher.stop_locally("operator"))
        commands = [r for r in self.owner.command_results]
        self.assertEqual(len(commands), 2)
        stop, cancel = [json.loads(r) for r in self.reports]
        self.assertEqual(stop["outcome"], "blocked")
        self.assertTrue(stop["blockers"])
        self.assertEqual(cancel["command"], "cancel")
        self.assertEqual(stop["stop_attempt_id"], cancel["stop_attempt_id"])
        self.assertFalse(self.owner.terminated)
        self.boundary.close.assert_not_awaited()
        self.close.assert_not_awaited()

    async def test_failed_cleanup_does_not_exit_or_force_kill(self):
        self.close.return_value = False
        self.assertFalse(await self.launcher.stop_locally("operator"))
        self.assertEqual(json.loads(self.reports[-1])["outcome"], "failed")
        self.assertFalse(self.owner.terminated)
        self.boundary.close.assert_not_awaited()
        self.assertEqual(len(self.owner.command_results), 1)

    async def test_unconfirmed_result_retains_process(self):
        with patch.object(self.owner, "execute_command", AsyncMock(side_effect=ConnectionError("unavailable"))):
            self.assertFalse(await self.launcher.stop_locally("operator"))
        self.assertEqual(json.loads(self.reports[-1])["outcome"], "unconfirmed")
        self.boundary.close.assert_not_awaited()

    async def test_repeated_sigint_never_authorizes_kill(self):
        reached, resume = asyncio.Event(), asyncio.Event()

        async def pause(force):
            self.assertFalse(force)
            reached.set()
            await resume.wait()
            return True

        self.close.side_effect = pause
        installed = []
        with patch("lab_sync_acquisition.service_launcher.signal.signal", side_effect=lambda *args: installed.append(args)):
            task = asyncio.create_task(self.launcher.run())
            try:
                await asyncio.sleep(0)
                handler = installed[0][1]
                handler(signal.SIGINT, None)
                await asyncio.wait_for(reached.wait(), 2)
                handler(signal.SIGINT, None)
                handler(signal.SIGINT, None)
                self.assertFalse(task.done())
                resume.set()
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
            finally:
                await self.finish_task(task, self.launcher)
        self.close.assert_awaited_once_with(False)

    async def test_remote_retirement_waits_for_result_publication_and_ack(self):
        broker = _Broker()
        boundary = _Boundary("controller", "control", broker)
        boundary.close = AsyncMock()
        boundary.maintenance_command_handled = None
        # Rebind only the transport; the same authoritative owner handles Stop.
        self.boundary.maintenance_command_handled = None
        launcher = ServiceLauncher((self.owner,), (boundary,), report=self.reports.append)
        handler = NatsServiceMaintenanceCommunication(boundary, self.owner)
        await handler.subscribe_commands()
        command = RuntimeCommandMessage("stop-remote", None, "stop", "terminal", "control",
            {"stop_attempt_id": "remote-attempt", "administrator_id": "operator"})
        subscriptions = [s for s in broker.subscriptions if s.subject.startswith("messages.command.")]
        self.assertEqual(len(subscriptions), 1)
        reached, resume = asyncio.Event(), asyncio.Event()
        publish = boundary.publish_command_result

        async def paused(result, operation):
            reached.set()
            await resume.wait()
            await publish(result, operation)

        boundary.publish_command_result = paused
        acknowledged = []

        async def ack():
            self.assertFalse(launcher.exit_ready)
            acknowledged.append(True)

        from types import SimpleNamespace
        message = SimpleNamespace(data=json.dumps(command.to_dict()).encode(), ack=ack)
        delivery = asyncio.create_task(subscriptions[0].callback(message))
        try:
            await asyncio.wait_for(reached.wait(), 2)
            self.assertTrue(self.owner.terminated)
            self.assertFalse(launcher.exit_ready)
            resume.set()
            await delivery
        finally:
            if not delivery.done():
                delivery.cancel()
                await asyncio.gather(delivery, return_exceptions=True)
        self.assertEqual(acknowledged, [True])
        self.assertTrue(launcher.exit_ready)
        self.assertEqual(await launcher.run(), 0)

    async def test_failed_remote_result_publication_does_not_confirm_exit(self):
        broker = _Broker()
        boundary = _Boundary("controller", "control", broker)
        launcher = ServiceLauncher((self.owner,), (boundary,), report=self.reports.append)
        handler = NatsServiceMaintenanceCommunication(boundary, self.owner)
        await handler.subscribe_commands()
        command = RuntimeCommandMessage("stop", None, "stop", "terminal", "control",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"})
        from types import SimpleNamespace
        ack = AsyncMock()
        message = SimpleNamespace(data=json.dumps(command.to_dict()).encode(), ack=ack)
        callback = broker.subscriptions[-1].callback
        with patch.object(boundary, "publish_command_result", AsyncMock(side_effect=ConnectionError("lost"))):
            with self.assertRaises(ConnectionError):
                await callback(message)
        self.assertTrue(self.owner.terminated)
        self.assertFalse(launcher.exit_ready)
        ack.assert_not_awaited()
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertEqual(json.loads(self.reports[-1])["outcome"], "unconfirmed")
        # Identical delivery reuses maintenance's existing result, then handles it.
        with patch.object(boundary, "publish_command_result", AsyncMock()):
            await callback(message)
        self.assertTrue(launcher.exit_ready)
        self.close.assert_awaited_once_with(False)

    async def test_pair_uses_existing_prepared_retirement_order(self):
        boundaries = (NatsCommunicationBoundary("ingestor", "intake"), NatsCommunicationBoundary("storage_manager", "storage"))
        interfaces = tuple(ServiceMaintenanceInterface(service, RuntimeParticipant(b.component_type, b.component_id),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
            for service, b in zip((self.intake, self.storage), boundaries))
        launcher = ServiceLauncher(interfaces, boundaries, report=self.reports.append)
        self.assertTrue(await launcher.stop_locally("operator"))
        reports = [json.loads(r) for r in self.reports]
        self.assertEqual([(r["target"]["component_type"], r["command"]) for r in reports],
            [("storage_manager", "prepare_stop"), ("ingestor", "stop"), ("storage_manager", "stop")])
        self.assertTrue(all(m.terminated for m in interfaces))
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())

    async def test_remote_ack_failure_retains_exit_obligation_until_redelivery(self):
        broker = _Broker()
        boundary = _Boundary("controller", "control", broker)
        launcher = ServiceLauncher((self.owner,), (boundary,), report=self.reports.append)
        await NatsServiceMaintenanceCommunication(boundary, self.owner).subscribe_commands()
        command = RuntimeCommandMessage("stop-ack", None, "stop", "terminal", "control",
            {"stop_attempt_id": "ack-attempt", "administrator_id": "operator"})
        from types import SimpleNamespace
        message = SimpleNamespace(data=json.dumps(command.to_dict()).encode(),
            ack=AsyncMock(side_effect=ConnectionError("ACK unavailable")))
        callback = broker.subscriptions[-1].callback
        with self.assertRaises(ConnectionError):
            await callback(message)
        self.assertTrue(self.owner.terminated)
        self.assertFalse(launcher.exit_ready)
        message.ack.side_effect = None
        await callback(message)
        self.assertTrue(launcher.exit_ready)
        self.close.assert_awaited_once_with(False)

    async def test_operational_dependent_blocks_pair_retirement_without_a_session(self):
        boundaries = (NatsCommunicationBoundary("ingestor", "intake"), NatsCommunicationBoundary("storage_manager", "storage"))
        dependent = RuntimeParticipant("acquisition_node", "node")
        interfaces = tuple(ServiceMaintenanceInterface(service, RuntimeParticipant(b.component_type, b.component_id),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True),
            operational_dependents={dependent: lambda: True} if service is self.intake else None)
            for service, b in zip((self.intake, self.storage), boundaries))
        launcher = ServiceLauncher(interfaces, boundaries, report=self.reports.append)
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertFalse(launcher.exit_ready)
        self.assertFalse(self.intake._maintenance.terminated)
        self.assertTrue(any("Operational dependency" in r for r in self.reports))

    async def test_rejected_remote_stop_does_not_confirm_exit(self):
        broker = _Broker()
        boundary = _Boundary("controller", "control", broker)
        launcher = ServiceLauncher((self.owner,), (boundary,), report=self.reports.append)
        await NatsServiceMaintenanceCommunication(boundary, self.owner).subscribe_commands()
        command = RuntimeCommandMessage("invalid-stop", None, "stop", "terminal", "control", {})
        from types import SimpleNamespace
        message = SimpleNamespace(data=json.dumps(command.to_dict()).encode(), ack=AsyncMock())
        await broker.subscriptions[-1].callback(message)
        self.assertFalse(launcher.exit_ready)
        self.assertFalse(self.owner.terminated)
        self.close.assert_not_awaited()
        self.assertEqual(json.loads(self.reports[-1])["outcome"], "failed")

    async def test_pair_startup_constructs_only_the_two_local_owners(self):
        broker = _Broker()
        boundaries = []

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            boundaries.append(value)
            return value

        async def run(launcher, *, startup):
            await startup()
            self.assertEqual({m.participant.component_type for m in launcher.maintenance}, {"ingestor", "storage_manager"})
            self.assertTrue(all(m.service.check_ready().ready for m in launcher.maintenance))
            self.assertTrue(await launcher.stop_locally("operator"))
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", side_effect=boundary), patch.object(ServiceLauncher, "run", run):
            result = await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "pair", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "pair-framework.jsonl", preservation_window_s=0,
                operational_dependents={}, report=self.reports.append)
        self.assertEqual(result, 0)
        self.assertEqual(len(boundaries), 2)
        self.assertTrue(all(b.connect.await_count == 1 for b in boundaries))

    async def test_partial_command_startup_retains_owners_for_local_maintenance(self):
        broker = _Broker()

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            return value

        async def retained(launcher, *, startup):
            await startup()
            self.assertFalse(launcher.exit_ready)
            self.assertTrue(any("Command startup unconfirmed" in r for r in self.reports))
            self.assertTrue(await launcher.stop_locally("operator"))
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", side_effect=boundary), patch.object(ServiceLauncher, "run", retained), patch("lab_sync_acquisition.service_launcher.NatsStorageManagerCommunication.subscribe_commands", AsyncMock(side_effect=ConnectionError("subscribe failed"))):
            result = await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "pair", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "pair-framework.jsonl", preservation_window_s=0,
                operational_dependents={}, report=self.reports.append)
        self.assertEqual(result, 0)

    async def test_conflicting_rejection_cannot_replace_unpublished_retirement(self):
        broker = _Broker()
        boundaries = (_Boundary("ingestor", "intake", broker), _Boundary("storage_manager", "storage", broker))

        async def publish(message):
            self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)

        interfaces = tuple(ServiceMaintenanceInterface(service, RuntimeParticipant(b.component_type, b.component_id),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True), evidence_publisher=publish)
            for service, b in zip((self.intake, self.storage), boundaries))
        launcher = ServiceLauncher(interfaces, boundaries, report=self.reports.append)
        await NatsIngestorCommunication(boundaries[0], self.intake).subscribe_commands()
        await NatsStorageManagerCommunication(boundaries[1], self.storage).subscribe_commands()

        def command(identity, operation, target, attempt, source="terminal", administrator="operator"):
            return RuntimeCommandMessage(identity, None, operation, source, target,
                {"stop_attempt_id": attempt, "framework_stop_attempt_id": "scope", "administrator_id": administrator})

        async def deliver(request, kind):
            from types import SimpleNamespace
            subscription = next(s for s in broker.subscriptions
                if s.subject == f"messages.command.{kind}.{request.target_id}.*")
            await subscription.callback(SimpleNamespace(data=json.dumps(request.to_dict()).encode(), ack=AsyncMock()))

        await deliver(command("prepare", "prepare_stop", "storage", "storage-attempt"), "storage_manager")
        original = command("stop-intake", "stop", "intake", "intake-attempt")
        with patch.object(boundaries[0], "publish_command_result", AsyncMock(side_effect=ConnectionError("lost reply"))):
            with self.assertRaises(ConnectionError):
                await deliver(original, "ingestor")
        await deliver(command("stop-storage", "stop", "storage", "storage-attempt"), "storage_manager")
        self.assertTrue(all(m.terminated for m in interfaces))
        self.assertFalse(launcher.exit_ready)
        for source, administrator in (("different-terminal", "operator"), ("terminal", "different-admin")):
            with self.subTest(source=source, administrator=administrator):
                await deliver(command("stop-intake", "stop", "intake", "intake-attempt", source, administrator), "ingestor")
                self.assertFalse(broker.results[-1]["success"])
                self.assertEqual(broker.results[-1]["reason"], "Conflicting command identity")
                self.assertFalse(launcher.exit_ready)
                self.assertEqual(json.loads(self.reports[-1])["outcome"], "failed")
        self.assertFalse(any(r["success"] for r in broker.results if r["command_id"] == original.command_id))
        # Identical redelivery publishes the actual retained success. No requester
        # receipt is fabricated or required by the publication/handling contract.
        await deliver(original, "ingestor")
        self.assertTrue(broker.results[-1]["success"])
        self.assertTrue(launcher.exit_ready)
        self.assertEqual(await launcher.run(), 0)
        self.assertEqual(len(interfaces[0].command_results), 1)

    async def check_startup_interruption(self, *, sigint):
        import lab_sync_acquisition.service_launcher as module
        broker = _Broker()
        boundaries, launchers, intakes = [], [], []
        reached, retained, pending = asyncio.Event(), asyncio.Event(), asyncio.Event()
        installed = []
        real_launcher = ServiceLauncher

        def capture_launcher(*args, **kwargs):
            launcher = real_launcher(*args, **kwargs)
            launchers.append(launcher)
            return launcher

        def intake(*args, **kwargs):
            value = InMemoryIngestor(*args, **kwargs)
            intakes.append(value)
            return value

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, broker)

            async def connect():
                self.assertTrue(installed, "SIGINT protection must precede startup")

            value.connect = connect
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            boundaries.append(value)
            return value

        evidence = RuntimeEvidenceMessage("admitted", "active", "warning", "node", {"message": "operational"}, True)

        async def pause(handler):
            self.assertTrue(intakes[0].prepare_session("active").ready)
            self.assertTrue(intakes[0].receive_runtime_evidence(evidence).accepted)
            reached.set()
            await pending.wait()

        def report(message):
            self.reports.append(message)
            if message.startswith("{"):
                value = json.loads(message)
                if value.get("command") == "cancel" and value["target"]["component_type"] == "ingestor":
                    retained.set()

        with patch.object(module, "NatsCommunicationBoundary", side_effect=boundary), patch.object(module, "InMemoryIngestor", side_effect=intake), patch.object(module, "ServiceLauncher", side_effect=capture_launcher), patch.object(NatsStorageManagerCommunication, "subscribe_commands", pause), patch.object(module.signal, "signal", side_effect=lambda *args: installed.append(args)):
            task = asyncio.create_task(launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "pair", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "pair-framework.jsonl", preservation_window_s=0,
                operational_dependents={}, report=report))
            try:
                await asyncio.wait_for(reached.wait(), 2)
                journal = intakes[0].recovery_journal_path.read_bytes()
                if sigint:
                    installed[0][1](signal.SIGINT, None)
                    installed[0][1](signal.SIGINT, None)
                else:
                    task.cancel()
                await asyncio.wait_for(retained.wait(), 2)
                self.assertFalse(task.done())
                self.assertEqual(len(intakes), 1)
                self.assertEqual(len(launchers), 1)
                self.assertEqual(intakes[0].session_id, "active")
                self.assertTrue(intakes[0].has_durable_runtime_evidence(evidence))
                self.assertEqual(intakes[0].recovery_journal_path.read_bytes(), journal)
                self.assertFalse(launchers[0].exit_ready)
                for b in boundaries:
                    b.close.assert_not_awaited()
                reports = [json.loads(r) for r in self.reports if r.startswith("{") and "command" in json.loads(r)]
                self.assertTrue(any(r["command"] == "stop" and r["outcome"] == "blocked" for r in reports))
                self.assertFalse(any(r["command"] == "kill" for r in reports))
            finally:
                if launchers:
                    await self.finish_task(task, launchers[0])
                else:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_sigint_during_partial_startup_preserves_admitted_session(self):
        await self.check_startup_interruption(sigint=True)

    async def test_cancellation_during_partial_startup_preserves_admitted_session(self):
        await self.check_startup_interruption(sigint=False)

    async def test_connection_failure_before_admission_is_not_orderly_shutdown(self):
        import lab_sync_acquisition.service_launcher as module
        broker = _Broker()
        boundaries = []
        previous = signal.getsignal(signal.SIGINT)

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, broker)
            value.connect = AsyncMock(side_effect=ConnectionError("offline") if kind == "storage_manager" else None)
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            boundaries.append(value)
            return value

        with patch.object(module, "NatsCommunicationBoundary", side_effect=boundary):
            with self.assertRaisesRegex(ConnectionError, "offline"):
                await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                    storage_id="storage", storage_root=self.root / "pair", recovery_journal_root=self.root / "journals",
                    framework_journal=self.root / "pair-framework.jsonl", preservation_window_s=0,
                    operational_dependents={}, report=self.reports.append)
        boundaries[0].close.assert_awaited_once()
        self.assertIs(signal.getsignal(signal.SIGINT), previous)
        self.assertFalse(any('"outcome": "completed"' in r for r in self.reports))


if __name__ == "__main__":
    unittest.main()
