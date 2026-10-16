"""Independent role startup and service-specific remote preservation workflows."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from nats.js.api import DeliverPolicy

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, InMemoryIngestor, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeEvidenceMessage, RuntimeParticipant, ServiceMaintenanceInterface,
    SynchronizationManager, NatsControllerCommunication, NatsIngestorCommunication,
    NatsStorageManagerCommunication, NatsSynchronizationManagerCommunication,
    NatsAcquisitionNodeCommunication, NatsServiceMaintenanceCommunication,
    build_runtime_subject,
)
from lab_sync_acquisition.service_launcher import ServiceLauncher, main
from lab_sync_acquisition.service_startup import load_acquisition_node, launch_independent_service
from tests.fakes import ReadyFakeAdapter
from tests.test_session_launch import _Boundary
from tests.test_remote_saved_collection import CollectionBroker


class RetainedCommandsBroker(CollectionBroker):
    """Replay command history unless the real adapter explicitly requests fresh delivery."""
    def __init__(self):
        super().__init__()
        self.history = []

    async def publish(self, subject, data, stream):
        if stream == "LAB_COMMANDS":
            self.history.append((subject, data))
        return await super().publish(subject, data, stream)

    async def subscribe(self, subject, cb, **kwargs):
        subscription = await super().subscribe(subject, cb, **kwargs)
        if getattr(kwargs.get("config"), "deliver_policy", None) != DeliverPolicy.NEW:
            for original, data in tuple(self.history):
                if self.matches(subject, original):
                    await cb(SimpleNamespace(subject=original, data=data, ack=AsyncMock()))
        return subscription


class NodeInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "node.json"
        self.configuration = {"node_id": "node", "role": "acquisition", "local_storage_root": "science",
            "error_evidence_location": "errors", "devices": [{"adapter": "seeed_imx219_opencv",
                "declaration": {"device_id": "camera", "device_type": "camera", "enabled": True,
                    "required": True, "declared_capabilities": ["frames"], "scientific_products": []},
                "configuration": {"camera_source": 0, "api_preference": 0, "frames_per_collect": 1}}]}

    def test_installation_loads_explicit_adapter_without_opening_hardware(self):
        self.path.write_text(json.dumps(self.configuration), encoding="utf-8")
        node = load_acquisition_node(self.path, "sync")
        self.assertEqual(node.node_id, "node")
        self.assertEqual(node.synchronization_source_id, "sync")
        self.assertEqual(node.declared_devices[0].device_id, "camera")
        self.assertEqual(node.status()["is_running"], False)

    def test_missing_or_invalid_installation_prevents_startup(self):
        with self.assertRaises(FileNotFoundError):
            load_acquisition_node(self.path, "sync")
        for mutation in (lambda c: c.update(node_id=""),
                         lambda c: c["devices"][0].update(adapter="unknown"),
                         lambda c: c["devices"][0]["configuration"].update(frames_per_collect=0)):
            data = json.loads(json.dumps(self.configuration))
            mutation(data)
            self.path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_acquisition_node(self.path, "sync")

    def test_installation_settings_are_reused_for_successive_sessions(self):
        from tests.test_seeed_imx219_camera_adapter import FakeCV2
        self.configuration["devices"][0]["configuration"]["camera_source"] = 7
        self.path.write_text(json.dumps(self.configuration), encoding="utf-8")
        node = load_acquisition_node(self.path, "sync")
        camera = FakeCV2([])
        with patch("lab_sync_acquisition.opencv_camera.SeeedIMX219OpenCVCameraAdapter._import_cv2", return_value=camera):
            for session_id in ("first", "second"):
                node.reserve(session_id)
                try:
                    self.assertTrue(node.initialize_session(session_id, node.declared_devices).ready)
                    self.assertEqual(camera.captures[-1].source, 7)
                finally:
                    self.assertTrue(node.abort_session_initialization(session_id))
                    self.assertTrue(node.release_reservation(session_id))
        self.assertEqual(len(camera.captures), 2)


class IndependentRoleCommandTests(unittest.TestCase):
    def test_all_independent_roles_dispatch_explicit_startup_settings(self):
        seen = []

        async def launch(**settings):
            seen.append(settings)
            return 0

        def run(coroutine):
            try:
                coroutine.send(None)
            except StopIteration as done:
                return done.value

        base = ["--server", "nats://example:4222", "--ingestor-id", "intake", "--storage-id", "storage",
                "--preservation-window-s", "1", "--result-window-s", "1"]
        with patch("lab_sync_acquisition.service_startup.launch_independent_service", launch), patch("lab_sync_acquisition.service_launcher.asyncio.run", run):
            for role, extra in (("controller", ["--service-id", "control", "--synchronization-id", "sync", "--known-node", "node"]),
                                ("synchronization-manager", ["--service-id", "sync"]),
                                ("acquisition-node", ["--config", "node.json", "--synchronization-id", "sync"])):
                self.assertEqual(main([role, *base, *extra]), 0)
        self.assertEqual([s["role"] for s in seen], ["controller", "synchronization-manager", "acquisition-node"])
        self.assertEqual(seen[0]["known_nodes"], ("node",))
        self.assertEqual(seen[2]["node_config"], Path("node.json"))

    def test_controller_does_not_assume_empty_node_registration(self):
        args = ["controller", "--server", "nats://example:4222", "--ingestor-id", "intake",
                "--storage-id", "storage", "--service-id", "control", "--synchronization-id", "sync",
                "--preservation-window-s", "1", "--result-window-s", "1"]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(args)


class IndependentServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root, component_id="storage")
        self.intake = InMemoryIngestor(self.storage, component_id="intake",
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.broker = CollectionBroker()
        self.reports = []

    async def backend(self):
        self.intake_boundary = _Boundary("ingestor", "intake", self.broker)
        handler = NatsIngestorCommunication(self.intake_boundary, self.intake)
        await handler.subscribe_evidence(None)
        await handler.subscribe_commands()
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), self.storage).subscribe_commands()

    def service(self, kind, *, storage_id="storage"):
        identity = {"controller": "control", "synchronization_manager": "sync", "acquisition_node": "node"}[kind]
        if kind == "controller":
            owner = Controller(component_id=identity)
        elif kind == "synchronization_manager":
            owner = SynchronizationManager()
        else:
            owner = AcquisitionNode(device_manager=DeviceManager((ReadyFakeAdapter("device", "fake", (), True),)),
                                    node_id=identity, role="acquisition", synchronization_source_id="sync")
        boundary = _Boundary(kind, identity, self.broker)
        boundary.close = AsyncMock()
        cleanup = AsyncMock(return_value=True)
        interface = ServiceMaintenanceInterface(owner, RuntimeParticipant(kind, identity),
            ingestor=None, storage_manager=None, preservation_window_s=0.1, close_resources=cleanup,
            framework_communication=NatsControllerCommunication(boundary),
            framework_ingestor=RuntimeParticipant("ingestor", "intake"),
            framework_storage=RuntimeParticipant("storage_manager", storage_id), evidence_publisher=boundary.publish_evidence)
        return owner, interface, ServiceLauncher((interface,), (boundary,), report=self.reports.append), cleanup, boundary

    async def test_each_independent_owner_stops_with_remote_preservation(self):
        await self.backend()
        for kind in ("controller", "synchronization_manager", "acquisition_node"):
            with self.subTest(kind=kind):
                owner, interface, launcher, cleanup, _ = self.service(kind)
                self.assertTrue(await launcher.stop_locally("operator"), self.reports)
                self.assertTrue(interface.terminated)
                cleanup.assert_awaited_once_with(False)
                archive = self.storage.get_framework_preservation_confirmation()
                self.assertTrue(all(m.to_dict() in archive["runtime_evidence"] for m in interface.evidence))
                self.assertIsNone(interface.ingestor)
                self.assertIsNone(interface.storage_manager)

    async def test_unrelated_intake_does_not_invalidate_retiring_producer(self):
        await self.backend()
        _, interface, launcher, _, _ = self.service("controller")

        def another_producer(operation, result):
            if operation == "preserve_service_evidence" and result["success"]:
                self.intake.receive_runtime_evidence(RuntimeEvidenceMessage(
                    "unrelated-" + result["result_id"], None, "warning", "another-service", {}, True))
            return result

        self.broker.change_result = another_producer
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertTrue(interface.terminated)
        self.assertTrue(self.intake.check_ready().ready)
        self.assertTrue(any(m.source_id == "another-service" for m in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]))

    async def test_corrupted_archive_blocks_orderly_stop_without_repair(self):
        await self.backend()
        _, interface, launcher, cleanup, _ = self.service("controller")
        await interface.announce_readiness(startup=True)
        summary = next(self.root.rglob("compilation_summary.json"))
        summary.write_text("{broken", encoding="utf-8")
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertFalse(interface.terminated)
        cleanup.assert_not_awaited()
        self.assertEqual(summary.read_text(encoding="utf-8"), "{broken")
        self.assertTrue(interface.evidence)

    async def test_conflicting_preservation_command_cannot_change_history(self):
        await self.backend()
        _, interface, _, _, boundary = self.service("controller")
        await interface.announce_readiness(startup=True)
        requests = NatsControllerCommunication(boundary)
        payload = {"evidence": [m.to_dict() for m in interface.required_evidence()], "acceptance_window_s": 0.1}
        first = await requests.request_persistence_command(RuntimeParticipant("ingestor", "intake"),
            "preserve_service_evidence", None, payload, 0.1, command_id="stable")
        self.assertTrue(first.success)
        original = self.storage.get_framework_preservation_confirmation()
        changed = await requests.request_persistence_command(RuntimeParticipant("ingestor", "intake"),
            "preserve_service_evidence", None, {**payload, "acceptance_window_s": 0.2}, 0.1, command_id="stable")
        self.assertFalse(changed.success)
        self.assertIn("Conflicting", changed.reason)
        self.assertEqual(self.storage.get_framework_preservation_confirmation(), original)

    async def test_incomplete_confirmation_cannot_retire_owner(self):
        await self.backend()
        _, interface, launcher, cleanup, _ = self.service("controller")
        self.broker.change_result = lambda operation, result: ({**result,
            "payload": {**result["payload"], "evidence": []}}
            if operation == "preserve_service_evidence" else result)
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertFalse(interface.terminated)
        cleanup.assert_not_awaited()

    async def test_identical_boundary_retry_reuses_durable_products(self):
        await self.backend()
        _, interface, _, _, boundary = self.service("controller")
        await interface.announce_readiness(startup=True)
        requests = NatsControllerCommunication(boundary)
        payload = {"evidence": [m.to_dict() for m in interface.required_evidence()], "acceptance_window_s": 0.1}
        first = await requests.request_persistence_command(RuntimeParticipant("ingestor", "intake"),
            "preserve_service_evidence", None, payload, 0.1, command_id="stable")
        self.assertTrue(first.success)
        paths = tuple((self.root / "framework").rglob("*.json*"))
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        again = await requests.request_persistence_command(RuntimeParticipant("ingestor", "intake"),
            "preserve_service_evidence", None, payload, 0.1, command_id="stable")
        self.assertTrue(again.success)
        self.assertEqual(again.payload["evidence"], first.payload["evidence"])
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)

    async def test_different_storage_owner_cannot_confirm_retirement(self):
        await self.backend()
        _, interface, launcher, cleanup, _ = self.service("controller", storage_id="another-storage")
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertFalse(interface.terminated)
        cleanup.assert_not_awaited()

    async def test_restarted_runtime_does_not_execute_old_stop_requests(self):
        self.broker = RetainedCommandsBroker()
        await self.backend()
        handlers = {"controller": NatsServiceMaintenanceCommunication,
                    "acquisition_node": NatsAcquisitionNodeCommunication,
                    "synchronization_manager": NatsSynchronizationManagerCommunication}
        for kind, handler_type in handlers.items():
            owner, interface, launcher, _, boundary = self.service(kind)
            old = RuntimeCommandMessage("old-" + kind, None, "stop", "old-terminal", interface.participant.component_id,
                {"stop_attempt_id": "old-attempt", "administrator_id": "operator"})
            await self.broker.publish(build_runtime_subject(None, "command", kind, interface.participant.component_id, "stop"),
                                     json.dumps(old.to_dict()).encode(), "LAB_COMMANDS")
            await handler_type(boundary, interface if kind == "controller" else owner).subscribe_commands()
            self.assertFalse(interface.terminated)
            self.assertFalse(launcher.exit_ready)
            self.assertTrue(await launcher.stop_locally("operator"))

    async def test_missing_confirmation_blocks_retirement_and_retains_evidence(self):
        await self.backend()
        _, interface, launcher, cleanup, _ = self.service("controller")
        self.broker.drop_results.add(("intake", "preserve_service_evidence"))
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertFalse(interface.terminated)
        cleanup.assert_not_awaited()
        self.assertTrue(interface.evidence)

    async def test_new_evidence_during_confirmation_cannot_use_older_boundary(self):
        await self.backend()
        _, interface, launcher, cleanup, _ = self.service("controller")
        reached, resume = asyncio.Event(), asyncio.Event()
        original = self.intake_boundary.publish_command_result
        first = True

        async def pause(result, operation):
            nonlocal first
            if operation == "preserve_service_evidence" and first:
                first = False
                reached.set()
                await resume.wait()
            await original(result, operation)

        with patch.object(self.intake_boundary, "publish_command_result", pause):
            stopping = asyncio.create_task(launcher.stop_locally("operator"))
            try:
                await asyncio.wait_for(reached.wait(), 2)
                await interface.record_administrator_decision("operator", "resume", {"reason": "inspect"})
                resume.set()
                self.assertFalse(await asyncio.wait_for(stopping, 2))
            finally:
                resume.set()
                if not stopping.done():
                    stopping.cancel()
                    await asyncio.gather(stopping, return_exceptions=True)
        self.assertFalse(interface.terminated)
        cleanup.assert_not_awaited()
        self.assertTrue(any(m.evidence_type == "administrator_decision" for m in interface.evidence))

    async def test_remote_stop_is_handled_before_exit_for_each_runtime_adapter(self):
        await self.backend()
        handlers = {"controller": NatsServiceMaintenanceCommunication,
                    "acquisition_node": NatsAcquisitionNodeCommunication,
                    "synchronization_manager": NatsSynchronizationManagerCommunication}
        for kind, handler_type in handlers.items():
            owner, interface, launcher, _, boundary = self.service(kind)
            await handler_type(boundary, interface if kind == "controller" else owner).subscribe_commands()
            requester = NatsControllerCommunication(_Boundary("terminal", "admin-" + kind, self.broker))
            subscription = await requester.subscribe_command_results(None, new_only=True,
                participant=interface.participant, command_type="stop")
            try:
                result = await requester.request_command(interface.participant, "stop", None,
                    {"stop_attempt_id": "attempt-" + kind, "administrator_id": "operator"}, 0.1)
            finally:
                await subscription.unsubscribe()
            self.assertTrue(result.success, result.reason)
            self.assertTrue(launcher.exit_ready)

    async def test_launch_composes_only_one_owner_with_explicit_remote_dependencies(self):
        await self.backend()
        sync = SynchronizationManager()
        await NatsSynchronizationManagerCommunication(_Boundary("synchronization_manager", "clock", self.broker), sync).subscribe_commands()
        real = ServiceLauncher

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            return value

        seen = []

        async def run(launcher, *, startup):
            self.assertIsInstance(launcher, real)
            await startup()
            self.assertEqual(len(launcher.maintenance), 1)
            interface = launcher.maintenance[0]
            seen.append(interface.participant.component_type)
            self.assertIsNone(interface.ingestor)
            self.assertIsNone(interface.storage_manager)
            self.assertIn(RuntimeParticipant("ingestor", "intake"), interface.dependency_readiness)
            self.assertTrue(all(value is not None for value in interface.dependency_readiness.values()))
            self.assertTrue(await launcher.stop_locally("operator"), self.reports)
            return 0

        node = AcquisitionNode(device_manager=DeviceManager((ReadyFakeAdapter("device", "fake", (), True),)),
                               node_id="node", role="acquisition", synchronization_source_id="clock")
        with patch("lab_sync_acquisition.service_startup.NatsCommunicationBoundary", boundary), patch.object(ServiceLauncher, "run", run), patch("lab_sync_acquisition.service_startup.load_acquisition_node", return_value=node):
            for role, identity in (("controller", "control"), ("synchronization-manager", "sync"), ("acquisition-node", "node")):
                result = await launch_independent_service(role=role, servers=("nats://example:4222",),
                    service_id=identity, ingestor_id="intake", storage_id="storage", preservation_window_s=0.1,
                    result_window_s=0.1, synchronization_id="clock", known_nodes=(), node_config="node.json",
                    report=self.reports.append)
                self.assertEqual(result, 0)
        self.assertEqual(seen, ["controller", "synchronization_manager", "acquisition_node"])

    async def test_partial_startup_interrupt_preserves_running_clock_until_explicit_stop(self):
        await self.backend()
        reached, blocked = asyncio.Event(), asyncio.Event()
        captured = []
        real_launcher = ServiceLauncher

        def capture(*args, **kwargs):
            launcher = real_launcher(*args, **kwargs)
            captured.append(launcher)
            return launcher

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            return value

        async def paused_subscription(handler):
            captured[0].maintenance[0].service.start()
            reached.set()
            await asyncio.Event().wait()

        def report(message):
            self.reports.append(message)
            if message.startswith("{") and json.loads(message).get("command") == "cancel":
                blocked.set()

        with patch("lab_sync_acquisition.service_startup.NatsCommunicationBoundary", boundary), patch("lab_sync_acquisition.service_startup.ServiceLauncher", capture), patch.object(NatsSynchronizationManagerCommunication, "subscribe_commands", paused_subscription):
            task = asyncio.create_task(launch_independent_service(role="synchronization-manager",
                servers=("nats://example:4222",), service_id="sync", ingestor_id="intake", storage_id="storage",
                preservation_window_s=0.1, result_window_s=0.1, report=report))
            try:
                await asyncio.wait_for(reached.wait(), 2)
                launcher = captured[0]
                launcher.request_interrupt()
                await asyncio.wait_for(blocked.wait(), 2)
                self.assertFalse(task.done())
                self.assertTrue(launcher.maintenance[0].service.is_running)
                self.assertFalse(launcher.exit_ready)
                launcher.boundaries[0].close.assert_not_awaited()
                launcher.maintenance[0].service.stop()
                launcher.request_interrupt()
                self.assertEqual(await asyncio.wait_for(task, 2), 0)
                self.assertFalse(any('"command": "kill"' in message for message in self.reports))
            finally:
                if not task.done():
                    if captured:
                        with patch.object(captured[0], "_report", side_effect=RuntimeError("Fixture cleanup")):
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                    else:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
