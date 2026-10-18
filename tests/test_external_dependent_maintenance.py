"""Shared storage and independent owners coordinate existing maintenance over NATS."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, Controller, InMemoryIngestor, PersistentStorageManager, RuntimeCommandMessage,
    RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager,
)
from lab_sync_acquisition.deployment_configuration import load_service_configuration
from lab_sync_acquisition.nats_communication import (
    NatsAcquisitionNodeCommunication, NatsControllerCommunication, NatsIngestorCommunication, NatsServiceMaintenanceCommunication,
    NatsStorageManagerCommunication, NatsSynchronizationManagerCommunication,
)
from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services, main
from tests.test_session_launch import _Boundary, _Broker
from tests.fakes import ReadyFakeAdapter


class ExternalDependentConfigurationTests(unittest.TestCase):
    def test_shared_file_names_actual_dependents_instead_of_declaring_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "storage.json"
            data = {"servers": ["nats://example:4222"], "ingestor_id": "intake", "storage_id": "storage",
                "storage_root": "records", "global_artifact_root": "science", "recovery_journal_root": "journals",
                "framework_journal": "framework.jsonl", "preservation_window_s": 1,
                "retrieval_endpoints": {}, "external_dependents": [
                    {"component_type": "controller", "component_id": "control"}], "result_window_s": 1}
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_service_configuration(path, "ingestor")
            self.assertEqual(loaded["external_dependents"], (RuntimeParticipant("controller", "control"),))
            self.assertEqual(loaded["operational_dependents"], {})
            for change in ({"no_operational_dependents": True}, {"external_dependents": []},
                           {"external_dependents": data["external_dependents"] * 2}, {"result_window_s": 0}):
                path.write_text(json.dumps({**data, **change}), encoding="utf-8")
                with self.subTest(change=change), self.assertRaises(ValueError):
                    load_service_configuration(path, "ingestor")

    def test_cli_passes_explicit_dependents_to_the_existing_pair(self):
        def finish(operation):
            operation.close()
            return 0
        with patch("lab_sync_acquisition.service_launcher.asyncio.run", side_effect=finish), patch(
                "lab_sync_acquisition.service_launcher.launch_storage_services", new_callable=AsyncMock) as launch:
            self.assertEqual(main(["ingestor", "--server", "nats://example:4222", "--ingestor-id", "intake",
                "--storage-id", "storage", "--storage-root", "records", "--recovery-journal-root", "journals",
                "--framework-journal", "framework.jsonl", "--preservation-window-s", "1",
                "--external-dependent", "controller/control", "--result-window-s", "1"]), 0)
        self.assertEqual(launch.call_args.kwargs["external_dependents"], (RuntimeParticipant("controller", "control"),))


class ExternalDependentMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.broker = _Broker()
        self.dependent = RuntimeParticipant("controller", "control")

    async def backend(self, participants=None):
        self.storage = PersistentStorageManager(self.root / "storage", component_id="storage")
        self.intake = InMemoryIngestor(self.storage, component_id="intake",
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.intake_boundary = _Boundary("ingestor", "intake", self.broker)
        self.storage_boundary = _Boundary("storage_manager", "storage", self.broker)
        self.intake_interface = ServiceMaintenanceInterface(self.intake, RuntimeParticipant("ingestor", "intake"),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0.02,
            close_resources=AsyncMock(return_value=True))
        self.storage_interface = ServiceMaintenanceInterface(self.storage, RuntimeParticipant("storage_manager", "storage"),
            ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0.02,
            close_resources=AsyncMock(return_value=True))
        self.intake_interface.configure_external_dependents(
            (self.dependent,) if participants is None else participants,
            NatsControllerCommunication(self.intake_boundary), 0.02)
        await NatsIngestorCommunication(self.intake_boundary, self.intake).subscribe_evidence(None)
        await NatsIngestorCommunication(self.intake_boundary, self.intake).subscribe_commands()
        await NatsStorageManagerCommunication(self.storage_boundary, self.storage).subscribe_commands()
        self.pair = ServiceLauncher((self.intake_interface, self.storage_interface),
            (self.intake_boundary, self.storage_boundary), report=lambda text: None)

    async def producer(self, kind="controller", identity="control"):
        if kind == "controller":
            owner = Controller(component_id=identity)
        elif kind == "acquisition_node":
            owner = AcquisitionNode(device_manager=DeviceManager((ReadyFakeAdapter("device", "fake", (), True),)),
                node_id=identity, role="acquisition", synchronization_source_id="sync")
        else:
            owner = SynchronizationManager()
        boundary = _Boundary(kind, identity, self.broker)
        boundary.close = AsyncMock()
        interface = ServiceMaintenanceInterface(owner, RuntimeParticipant(kind, identity), ingestor=None,
            storage_manager=None, preservation_window_s=0.02, close_resources=AsyncMock(return_value=True),
            evidence_publisher=boundary.publish_evidence, framework_communication=NatsControllerCommunication(boundary),
            framework_ingestor=RuntimeParticipant("ingestor", "intake"),
            framework_storage=RuntimeParticipant("storage_manager", "storage"))
        launcher = ServiceLauncher((interface,), (boundary,), report=lambda text: None)
        if kind == "controller":
            await NatsServiceMaintenanceCommunication(boundary, interface).subscribe_commands()
        elif kind == "acquisition_node":
            await NatsAcquisitionNodeCommunication(boundary, owner).subscribe_commands()
        else:
            await NatsSynchronizationManagerCommunication(boundary, owner).subscribe_commands()
        await interface.register_ingestor_dependency()
        return owner, interface, launcher, boundary

    async def status(self):
        return await self.intake_interface.execute_command(RuntimeCommandMessage(
            "survey-" + str(len(self.intake_interface.command_results)), None, "check_stop_readiness",
            "operator", "intake", {}))

    async def send_confirmation(self, boundary, confirmation):
        registration = next(c["payload"] for c in reversed(self.broker.commands)
            if c["command_type"] == "register_operational_dependent" and c["source_id"] == boundary.component_id)
        return await NatsControllerCommunication(boundary).request_maintenance_readback(
            RuntimeParticipant("ingestor", "intake"), "confirm_dependent_release",
            {**{k: v for k, v in registration.items() if k != "request_nonce"}, "confirmation": confirmation}, 0.02)

    def published_confirmation(self, identity="control"):
        return deepcopy(next(c["payload"]["confirmation"] for c in reversed(self.broker.commands)
            if c["command_type"] == "confirm_dependent_release" and c["source_id"] == identity))

    async def test_operational_dependent_blocks_stop_and_cancel_does_not_release_it(self):
        await self.backend()
        _, _, producer, _ = await self.producer()
        self.assertFalse(await self.pair.stop_locally("operator"))
        self.assertFalse(self.intake_interface.terminated)
        self.assertFalse(self.storage_interface.terminated)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        with self.assertRaisesRegex(RuntimeError, "new unrelated work"):
            self.storage.close_session_evidence_archive("unrelated")
        self.assertTrue(await producer.stop_locally("operator"))
        self.assertTrue(await self.pair.stop_locally("operator"))

    async def test_retirement_reaches_ingestor_before_exit_and_survives_producer_disappearance(self):
        await self.backend()
        _, interface, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertTrue(interface.terminated)
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        self.assertTrue((await self.status()).payload["ready"])
        self.assertTrue(await self.pair.stop_locally("operator"))

    async def test_duplicate_confirmation_does_not_duplicate_durable_evidence(self):
        await self.backend()
        _, interface, launcher, boundary = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        before = self.intake.compile_framework_runtime_evidence()
        confirmation = self.published_confirmation()
        results = await asyncio.gather(self.send_confirmation(boundary, confirmation),
                                       self.send_confirmation(boundary, confirmation))
        self.assertTrue(all(result.success for result in results))
        self.assertEqual(before, self.intake.compile_framework_runtime_evidence())

    async def test_node_retirement_uses_the_same_confirmed_delivery_boundary(self):
        node = RuntimeParticipant("acquisition_node", "node")
        await self.backend((node,))
        _, interface, launcher, _ = await self.producer("acquisition_node", "node")
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertTrue(interface.terminated)
        self.assertFalse(self.intake_interface.operational_dependents[node]())

    async def test_node_remote_stop_confirms_delivery_before_exit_eligibility(self):
        node = RuntimeParticipant("acquisition_node", "node")
        await self.backend((node,))
        _, interface, launcher, _ = await self.producer("acquisition_node", "node")
        request = NatsControllerCommunication(_Boundary("terminal", "administrator", self.broker))
        subscription = await request.subscribe_command_results(None, new_only=True, participant=node, command_type="stop")
        try:
            result = await request.request_command(node, "stop", None,
                {"stop_attempt_id": "node-stop", "administrator_id": "operator"}, 0.1)
        finally:
            await subscription.unsubscribe()
        self.assertTrue(result.success, result.reason)
        self.assertTrue(interface.terminated)
        self.assertTrue(launcher.exit_ready)
        self.assertFalse(self.intake_interface.operational_dependents[node]())

    async def test_unconfigured_producer_cannot_turn_an_isolated_pair_into_a_deployment(self):
        await self.backend(())
        with self.assertRaises(RuntimeError):
            await self.producer()
        self.assertFalse(self.intake_interface.terminated)

    async def test_receiver_restart_does_not_substitute_unverified_archive_history(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse((await self.status()).payload["ready"])

    async def test_restart_replaces_prior_instance_and_rejects_old_confirmation(self):
        await self.backend()
        _, old, launcher, old_boundary = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        prior = deepcopy(next(c["payload"] for c in reversed(self.broker.commands)
            if c["command_type"] == "confirm_dependent_release"))
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        _, current, _, _ = await self.producer()
        self.assertNotEqual(old.operational_instance_id, current.operational_instance_id)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        result = await NatsControllerCommunication(old_boundary).request_maintenance_readback(
            self.intake_interface.participant, "confirm_dependent_release",
            {k: v for k, v in prior.items() if k != "request_nonce"}, 0.02)
        self.assertFalse(result.success)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_lost_confirmation_reply_retains_process_and_explicit_retry_finishes(self):
        await self.backend()
        _, interface, launcher, _ = await self.producer()
        self.broker.drop_results.add(("intake", "confirm_dependent_release"))
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertTrue(interface.terminated)
        self.assertFalse(launcher.exit_ready)
        before = self.intake.compile_framework_runtime_evidence()
        self.broker.drop_results.clear()
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertEqual(before, self.intake.compile_framework_runtime_evidence())

    async def test_acknowledged_remote_retirement_can_finish_confirmation_on_local_retry(self):
        await self.backend()
        _, interface, launcher, _ = await self.producer()
        self.broker.drop_results.add(("intake", "confirm_dependent_release"))
        request = NatsControllerCommunication(_Boundary("terminal", "administrator", self.broker))
        subscription = await request.subscribe_command_results(None, new_only=True,
            participant=self.dependent, command_type="stop")
        try:
            # The inline broker propagates receiver failure; real JetStream publication
            # and receiver execution are independent. Neither establishes process exit.
            with self.assertRaises(Exception):
                await request.request_command(self.dependent, "stop", None,
                    {"stop_attempt_id": "remote-stop", "administrator_id": "operator"}, 0.1)
        finally:
            await subscription.unsubscribe()
        self.assertTrue(interface.terminated)
        self.assertFalse(launcher.exit_ready)
        original = next(c for c in self.broker.commands if c["command_type"] == "stop" and c["source_id"] == "administrator")
        conflicting = NatsControllerCommunication(_Boundary("terminal", "another-administrator", self.broker))
        subscription = await conflicting.subscribe_command_results(None, new_only=True,
            participant=self.dependent, command_type="stop")
        try:
            rejected = await conflicting.request_command(self.dependent, "stop", None, original["payload"],
                0.1, command_id=original["command_id"])
        finally:
            await subscription.unsubscribe()
        self.assertFalse(rejected.success)
        self.assertFalse(launcher.exit_ready)
        before = self.intake.compile_framework_runtime_evidence()
        self.broker.drop_results.clear()
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertEqual(before, self.intake.compile_framework_runtime_evidence())

    async def test_missing_owner_readback_never_releases_a_dependent(self):
        await self.backend()
        _, interface, _, _ = await self.producer()
        self.broker.drop_results.add(("intake", "read_operational_instance"))
        with self.assertRaises(RuntimeError):
            await interface.register_ingestor_dependency()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_stale_instance_readback_cannot_confirm_retirement(self):
        await self.backend()
        _, interface, launcher, _ = await self.producer()

        def stale(operation, result):
            if operation == "read_operational_instance" and result["source_id"] == "control":
                result["payload"]["operational_instance_id"] = "previous-instance"
            return result

        self.broker.change_result = stale
        self.assertFalse(await launcher.stop_locally("operator"))
        self.assertTrue(interface.terminated)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse(launcher.exit_ready)

    async def test_cancelled_confirmation_keeps_the_result_for_explicit_retry(self):
        await self.backend()
        _, interface, launcher, _ = await self.producer()
        reached, resume = asyncio.Event(), asyncio.Event()
        original = self.intake_boundary.publish_command_result

        async def pause(result, operation):
            if operation == "confirm_dependent_release":
                reached.set()
                await resume.wait()
            await original(result, operation)

        with patch.object(self.intake_boundary, "publish_command_result", pause):
            task = asyncio.create_task(launcher.stop_locally("operator"))
            try:
                await asyncio.wait_for(reached.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                resume.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(interface.terminated)
        self.assertFalse(launcher.exit_ready)
        self.assertTrue(await launcher.stop_locally("operator"))

    async def test_contradictory_confirmation_remains_blocked_after_a_valid_redelivery(self):
        await self.backend()
        _, interface, launcher, boundary = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        good = self.published_confirmation()
        bad = deepcopy(good)
        bad["result"]["payload"]["outcome"] = "blocked"
        self.assertFalse((await self.send_confirmation(boundary, bad)).success)
        self.assertFalse((await self.send_confirmation(boundary, good)).success)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_incorrect_attempt_correlation_cannot_remove_blocker(self):
        await self.backend()
        _, interface, launcher, boundary = await self.producer()
        self.broker.drop_results.add(("intake", "confirm_dependent_release"))
        await launcher.stop_locally("operator")
        self.broker.drop_results.clear()
        bad = self.published_confirmation()
        bad["command"]["payload"]["stop_attempt_id"] = "different"
        self.assertFalse((await self.send_confirmation(boundary, bad)).success)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_authorized_kill_does_not_fabricate_dependent_release(self):
        await self.backend()
        await self.producer()
        payload = {"stop_attempt_id": "blocked", "administrator_id": "operator"}
        blocked = await self.intake_interface.execute_command(RuntimeCommandMessage(
            "stop", None, "stop", "operator", "intake", payload))
        self.assertEqual(blocked.payload["outcome"], "blocked")
        denied = await self.intake_interface.execute_command(RuntimeCommandMessage(
            "deny", None, "kill", "operator", "intake", payload))
        self.assertFalse(denied.success)
        killed = await self.intake_interface.execute_command(RuntimeCommandMessage(
            "kill", None, "kill", "operator", "intake", {**payload, "authorized": True}))
        self.assertTrue(killed.success, killed.reason)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse(self.pair.exit_ready)

    async def test_preparation_alone_cannot_release_controller_dependency(self):
        await self.backend()
        _, interface, _, _ = await self.producer()
        prepared = await interface.execute_command(RuntimeCommandMessage("prepare", None, "prepare_stop",
            "control", "control", {"stop_attempt_id": "prepared", "framework_stop_attempt_id": "framework",
                                  "administrator_id": "operator"}))
        self.assertTrue(prepared.success, prepared.reason)
        self.assertFalse(interface.terminated)
        with self.assertRaises(RuntimeError):
            await interface.release_ingestor_dependency("framework")
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_coordinated_controller_release_precedes_infrastructure_retirement(self):
        sync = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((self.dependent, sync))
        controller, interface, _, boundary = await self.producer()
        await self.producer("synchronization_manager", "sync")
        scope = (self.dependent, sync, self.intake_interface.participant, self.storage_interface.participant)
        released_while_operational = []
        original = interface._deliver_dependency_confirmation

        async def record(confirmation):
            if "controller_release" in confirmation:
                released_while_operational.append(not interface.terminated)
            await original(confirmation)
            if "controller_release" in confirmation:
                with self.assertRaises(RuntimeError):
                    controller.create_session()

        with patch.object(interface, "_deliver_dependency_confirmation", record):
            result = await controller.shutdown_framework(scope, communication=NatsControllerCommunication(boundary),
                stop_attempt_id="framework", administrator_id="operator", result_window_s=0.1)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(released_while_operational, [True])
        self.assertTrue(interface.terminated)
        self.assertTrue(self.intake_interface.terminated)
        self.assertTrue(self.storage_interface.terminated)

    async def test_unconfirmed_controller_release_can_retry_only_its_frozen_boundary(self):
        sync = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((self.dependent, sync))
        controller, interface, _, boundary = await self.producer()
        await self.producer("synchronization_manager", "sync")
        original = self.intake_boundary.publish_command_result

        async def lose_controller_reply(result, operation):
            if (operation == "confirm_dependent_release" and result.target_id == "control"):
                return
            await original(result, operation)

        scope = (self.dependent, sync, self.intake_interface.participant, self.storage_interface.participant)
        with patch.object(self.intake_boundary, "publish_command_result", lose_controller_reply):
            result = await controller.shutdown_framework(scope, communication=NatsControllerCommunication(boundary),
                stop_attempt_id="framework", administrator_id="operator", result_window_s=0.1)
        self.assertFalse(result.succeeded)
        self.assertFalse(interface.terminated)
        self.assertFalse(self.intake_interface.terminated)
        before = self.intake.compile_framework_runtime_evidence()
        await interface.release_ingestor_dependency("framework")
        self.assertEqual(before, self.intake.compile_framework_runtime_evidence())
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        with self.assertRaises(RuntimeError):
            await interface.release_ingestor_dependency("another-framework")

    async def test_shared_launcher_composes_only_the_two_owners_and_remote_callbacks(self):
        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            return value

        async def run(launcher, *, startup):
            await startup()
            self.assertEqual(len(launcher.maintenance), 2)
            intake = next(m for m in launcher.maintenance if m.participant.component_type == "ingestor")
            self.assertEqual(set(intake.operational_dependents), {self.dependent})
            self.assertFalse(await launcher.stop_locally("operator"))
            self.assertFalse(launcher.exit_ready)
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", side_effect=boundary), patch.object(
                ServiceLauncher, "run", run):
            self.assertEqual(await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "storage", recovery_journal_root=self.root / "journal",
                framework_journal=self.root / "framework.jsonl", preservation_window_s=0.02,
                operational_dependents={}, external_dependents=(self.dependent,), result_window_s=0.02,
                report=lambda text: None), 0)
