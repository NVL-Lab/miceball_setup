"""Shared storage and independent owners coordinate existing maintenance over NATS."""

import asyncio
from datetime import datetime, timezone
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, Controller, InMemoryIngestor, PersistentStorageManager, RuntimeCommandMessage,
    RuntimeCommandResultMessage,
    RuntimeParticipant, RuntimeEvidenceMessage, ServiceMaintenanceInterface, SynchronizationManager,
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
    def test_initial_framework_archive_creation_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = PersistentStorageManager(Path(directory) / "storage")
            intake = InMemoryIngestor(storage, framework_recovery_journal_path=Path(directory) / "framework.jsonl")
            self.assertIsNone(intake.continue_framework_evidence_archive())
            intake.receive_runtime_evidence(RuntimeEvidenceMessage("initial", None, "warning", "source", {}, True))
            storage.write_framework_evidence_archive(intake.compile_framework_runtime_evidence())
            with intake.framework_preservation_guard(storage) as archive:
                self.assertEqual(archive["runtime_evidence"][0]["evidence_id"], "initial")

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
        try:
            self.intake.continue_framework_evidence_archive()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            pass  # Production startup retains blockers when continuation is unconfirmed.
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

    async def producer(self, kind="controller", identity="control", *, preservation_window_s=0.02):
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
            storage_manager=None, preservation_window_s=preservation_window_s, close_resources=AsyncMock(return_value=True),
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

    async def superseded_stop_history(self):
        await self.backend()
        _, _, launcher, old_boundary = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        old_confirmation = self.published_confirmation()
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        _, current, launcher, boundary = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        return old_confirmation, old_boundary, current, boundary

    async def test_history_retirement_preserves_current_state_history_and_restart(self):
        old, old_boundary, _, boundary = await self.superseded_stop_history()
        interface = self.intake_interface
        durable = self.intake.compile_framework_runtime_evidence()
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        results = interface.command_results
        before = interface.evidence
        release = await interface.retire_dependent_maintenance_history()
        self.assertTrue(release["confirmed"], release)
        self.assertEqual(release["released_evidence_count"], 1)
        self.assertEqual(len(interface.evidence), len(before) - 1)
        self.assertEqual(interface.command_results, results)
        self.assertFalse(interface.operational_dependents[self.dependent]())
        self.assertFalse(interface.terminated)
        self.assertEqual(self.intake.compile_framework_runtime_evidence(), durable)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        self.assertEqual((await interface.retire_dependent_maintenance_history())["released_evidence_count"], 0)
        duplicate = await self.send_confirmation(boundary, self.published_confirmation())
        self.assertTrue(duplicate.success)
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        # A request scoped to the former Ingestor lifetime is still rejected.
        stale = await self.send_confirmation(old_boundary, old)
        self.assertFalse(stale.success)

    async def test_history_retirement_retains_on_unconfirmed_journal_or_archive(self):
        await self.superseded_stop_history()
        interface = self.intake_interface
        before = interface.evidence
        journal = self.root / "framework.jsonl"
        content = journal.read_bytes()
        for damage in (b"", content[:-1] + b"x", b"{}\n"):
            with self.subTest(damage=damage[:12]):
                journal.write_bytes(damage)
                release = await interface.retire_dependent_maintenance_history()
                self.assertFalse(release["confirmed"], release)
                self.assertEqual(interface.evidence, before)
                self.assertEqual(journal.read_bytes(), damage)
                journal.write_bytes(content)
        journal.unlink()
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        journal.write_bytes(content)
        for archive in (None, {"runtime_evidence": [], "ingest_audit": []}):
            with patch.object(self.storage, "get_framework_preservation_confirmation", return_value=archive):
                self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
                self.assertEqual(interface.evidence, before)

        archive = deepcopy(self.storage.get_framework_preservation_confirmation())
        archive["runtime_evidence"][0]["payload"]["contradictory"] = True
        with patch.object(self.storage, "get_framework_preservation_confirmation", return_value=archive):
            self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
            self.assertEqual(interface.evidence, before)

    async def test_history_retirement_retains_pending_work_and_resource_obligations(self):
        await self.superseded_stop_history()
        interface = self.intake_interface
        before = interface.evidence
        for attribute, value in (("_dependent_state_messages", {"pending": object()}),
                                 ("_dependent_conflicts", {self.dependent}),
                                 ("_closeout_started", True)):
            with patch.object(interface, attribute, value):
                self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
                self.assertEqual(interface.evidence, before)
        with patch.object(self.intake_boundary, "_pending_dependent_deliveries", {"pending": object()}):
            self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        with patch.object(self.intake, "maintenance_blockers", return_value=["resource unresolved"]):
            self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)

        entered, proceed = asyncio.Event(), asyncio.Event()

        async def preserving(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return {}

        with patch.object(interface, "_record_framework_evidence", side_effect=preserving):
            operation = asyncio.create_task(interface.record_administrator_decision("operator", "resume", {}))
            await entered.wait()
            release = await interface.retire_dependent_maintenance_history()
            self.assertFalse(release["confirmed"], release)
            self.assertTrue(all(m in interface.evidence for m in before))
            proceed.set()
            await operation

    async def test_history_retirement_preserves_duplicate_conflicting_and_current_confirmation_rules(self):
        _, _, _, boundary = await self.superseded_stop_history()
        interface = self.intake_interface
        command = RuntimeCommandMessage.from_dict(next(c for c in reversed(self.broker.commands)
            if c["command_type"] == "confirm_dependent_release"))
        original = await interface.execute_command(command)
        survey = RuntimeCommandMessage("retirement-survey", None, "check_stop_readiness", "operator", "intake", {})
        surveyed = await interface.execute_command(survey)
        self.assertTrue((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual((await interface.execute_command(command)).payload, original.payload)
        self.assertEqual((await interface.execute_command(survey)).to_dict(), surveyed.to_dict())
        changed = survey.to_dict()
        changed["payload"]["unexpected"] = True
        conflict = await interface.execute_command(RuntimeCommandMessage.from_dict(changed))
        self.assertFalse(conflict.success)
        self.assertEqual((await interface.execute_command(survey)).to_dict(), surveyed.to_dict())
        confirmation = self.published_confirmation()
        confirmation["result"]["payload"]["operational_instance_id"] = "contradictory-instance"
        result = await self.send_confirmation(boundary, confirmation)
        self.assertFalse(result.success)
        before = interface.evidence
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)

    async def test_history_retirement_keeps_unsuperseded_orderly_stop(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        before = self.intake_interface.evidence
        release = await self.intake_interface.retire_dependent_maintenance_history()
        self.assertTrue(release["confirmed"], release)
        self.assertEqual(release["released_evidence_count"], 0)
        self.assertEqual(self.intake_interface.evidence, before)

    async def test_history_retirement_serializes_with_new_dependent_admission(self):
        await self.superseded_stop_history()
        interface = self.intake_interface
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        before = interface.evidence
        entered, proceed = asyncio.Event(), asyncio.Event()
        communication = interface._dependent_communication
        original = communication.request_maintenance_readback

        async def readback(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return await original(*args, **kwargs)

        with patch.object(communication, "request_maintenance_readback", side_effect=readback):
            admission = asyncio.create_task(self.producer(preservation_window_s=2))
            await entered.wait()
            retirement = asyncio.create_task(interface.retire_dependent_maintenance_history())
            await asyncio.sleep(0)
            self.assertFalse(retirement.done())
            proceed.set()
            await admission
            release = await retirement
        self.assertFalse(release["confirmed"], release)
        self.assertTrue(all(m in interface.evidence for m in before))
        self.assertTrue(interface.operational_dependents[self.dependent]())

    async def test_malformed_preserved_stop_never_restores_release_or_retires_copies(self):
        base = self.root
        cases = ("missing_ingestor", "null_instance", "blocked", "failed", "incomplete",
                 "missing_outcome", "failures", "obligations", "missing_actions", "wrong_participant",
                 "missing_command", "wrong_administrator", "outer_failed")
        for index, fault in enumerate(cases):
            with self.subTest(fault=fault):
                self.root = base / str(index)
                self.root.mkdir()
                self.broker = _Broker()
                await self.superseded_stop_history()
                interface = self.intake_interface
                data = next(m.to_dict() for m in reversed(interface.evidence)
                    if m.payload.get("dependent_maintenance", {}).get("confirmation"))
                data["evidence_id"] = "malformed-" + fault
                state = data["payload"]["dependent_maintenance"]
                confirmation = state["confirmation"]
                result = confirmation["confirmation"]["result"]
                attempt = result["payload"]["attempt"]
                if fault == "missing_ingestor":
                    del state["registration"]["ingestor_instance_id"]
                    del confirmation["ingestor_instance_id"]
                elif fault == "null_instance":
                    state["registration"]["operational_instance_id"] = None
                    confirmation["operational_instance_id"] = None
                    result["payload"]["operational_instance_id"] = None
                elif fault in {"blocked", "failed", "incomplete"}:
                    attempt["outcome"] = fault if fault != "incomplete" else None
                elif fault == "missing_outcome":
                    del attempt["outcome"]
                elif fault == "failures":
                    attempt["failures"] = ["Unconfirmed cleanup"]
                elif fault == "obligations":
                    attempt["remaining_obligations"] = ["Unreleased resource"]
                elif fault == "missing_actions":
                    attempt["actions"] = []
                elif fault == "missing_command":
                    attempt["commands"] = []
                elif fault == "wrong_administrator":
                    attempt["commands"][-1]["administrator_id"] = "another-administrator"
                elif fault == "outer_failed":
                    result["status"], result["success"] = "failed", False
                else:
                    confirmation["participant"]["component_id"] = "another-owner"
                self.assertTrue(self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(data)).accepted)
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                before = interface.evidence
                files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                self.assertFalse((await self.status()).payload["ready"])
                self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
                self.assertEqual(interface.evidence, before)
                self.assertEqual(files, {p: p.read_bytes() for p in files})
                for subscription in self.broker.subscriptions:
                    await subscription.unsubscribe()
                await self.backend()
                self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_cancelled_registration_remains_unresolved_through_survey_restart_and_retry(self):
        await self.superseded_stop_history()
        interface = self.intake_interface
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        entered, proceed = asyncio.Event(), asyncio.Event()
        communication = interface._dependent_communication
        original = communication.request_maintenance_readback

        async def readback(*args, **kwargs):
            entered.set()
            await proceed.wait()
            return await original(*args, **kwargs)

        with patch.object(communication, "request_maintenance_readback", side_effect=readback):
            registration = asyncio.create_task(self.producer(preservation_window_s=2))
            await asyncio.wait_for(entered.wait(), 2)
            registration.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await registration
        before = interface.evidence
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)
        blocked = await interface.execute_command(RuntimeCommandMessage("cancelled-registration-stop", None,
            "stop", "operator", "intake", {"stop_attempt_id": "cancelled-registration", "administrator_id": "operator"}))
        self.assertEqual(blocked.payload["outcome"], "blocked")
        interface.close_resources.assert_not_awaited()
        await interface.execute_command(RuntimeCommandMessage("cancelled-registration-cancel", None,
            "cancel", "operator", "intake", {"stop_attempt_id": "cancelled-registration", "administrator_id": "operator"}))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse((await self.status()).payload["ready"])
        # Explicitly register and stop a fresh owner using the existing retry path.
        _, _, launcher, _ = await self.producer(preservation_window_s=2)
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        self.assertTrue((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])

    async def test_interrupted_registration_publication_blocks_history_restore_and_can_retry(self):
        await self.superseded_stop_history()
        interface = self.intake_interface
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        entered, proceed = asyncio.Event(), asyncio.Event()

        async def publication(message):
            entered.set()
            await proceed.wait()
            self.intake.receive_runtime_evidence(message)

        with patch.object(interface, "evidence_publisher", publication):
            registration = asyncio.create_task(self.producer(preservation_window_s=2))
            await asyncio.wait_for(entered.wait(), 2)
            registration.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await registration
        before = interface.evidence
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)
        command = RuntimeCommandMessage.from_dict(next(c for c in reversed(self.broker.commands)
            if c["command_type"] == "register_operational_dependent"))
        retry = await interface.execute_command(command)
        self.assertTrue(retry.success, retry.reason)
        self.assertFalse((await self.status()).payload["ready"])
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        _, _, launcher, _ = await self.producer(preservation_window_s=2)
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertFalse(interface.operational_dependents[self.dependent]())

    async def test_repeated_registration_reconfirms_the_same_retired_owner(self):
        _, _, owner, _ = await self.superseded_stop_history()
        await owner.register_ingestor_dependency()
        self.assertTrue((await self.status()).payload["ready"])
        release = await self.intake_interface.retire_dependent_maintenance_history()
        self.assertTrue(release["confirmed"], release)

    async def test_superseded_registration_and_stop_replays_cannot_replace_current_owner(self):
        _, _, old, _ = await self.superseded_stop_history()
        registration = RuntimeCommandMessage.from_dict(next(c for c in reversed(self.broker.commands)
            if c["command_type"] == "register_operational_dependent"))
        confirmation = RuntimeCommandMessage.from_dict(next(c for c in reversed(self.broker.commands)
            if c["command_type"] == "confirm_dependent_release"))
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        _, current, launcher, _ = await self.producer(preservation_window_s=2)
        interface = self.intake_interface
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        before = interface.evidence
        # A still-readable former owner returns genuine readback for its original requests.
        async def old_readback(participant, operation, payload, result_window_s):
            return await old.execute_command(RuntimeCommandMessage("old-readback", None, operation,
                "intake", participant.component_id, payload))
        with patch.object(interface._dependent_communication, "request_maintenance_readback", old_readback):
            self.assertFalse((await interface.execute_command(registration)).success)
            self.assertFalse((await interface.execute_command(confirmation)).success)
        self.assertFalse(current.terminated)
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        # The current owner's retry still works, and only its actual Stop releases the blocker.
        await current.register_ingestor_dependency()
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertFalse(interface.operational_dependents[self.dependent]())

    async def test_unconfirmed_new_registration_retains_known_current_instance(self):
        await self.backend()
        _, current, _, boundary = await self.producer(preservation_window_s=2)
        payload = {"participant": self.dependent.to_dict(), "operational_instance_id": "unconfirmed-new-owner",
                   "ingestor_instance_id": self.intake_interface.operational_instance_id}
        with patch.object(self.intake_interface._dependent_communication,
                "request_maintenance_readback", AsyncMock(return_value=None)):
            result = await self.intake_interface.execute_command(RuntimeCommandMessage(
                "unconfirmed-registration", None, "register_operational_dependent", "control", "intake", payload))
        self.assertFalse(result.success)
        history = [m.payload["dependent_maintenance"] for m in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]
                   if "dependent_maintenance" in m.payload]
        self.assertEqual(history[-1]["registration"]["operational_instance_id"], current.operational_instance_id)
        self.assertFalse((await self.status()).payload["ready"])
        await current.register_ingestor_dependency()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_superseded_owner_cannot_reregister_after_receiver_restart(self):
        _, _, old, _ = await self.superseded_stop_history()
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        _, current, launcher, _ = await self.producer(preservation_window_s=2)
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        interface = self.intake_interface
        before = interface.evidence
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

        async def readback(owner, participant, operation, payload, result_window_s):
            return await owner.execute_command(RuntimeCommandMessage("restart-readback", None, operation,
                "intake", participant.component_id, payload))

        with patch.object(interface._dependent_communication, "request_maintenance_readback",
                lambda *args: readback(old, *args)):
            # This obtains the fresh Ingestor identity; rejection is not just a stale receiver nonce.
            with self.assertRaises(RuntimeError):
                await old.register_ingestor_dependency()
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(interface.evidence, before)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        with patch.object(interface._dependent_communication, "request_maintenance_readback",
                lambda *args: readback(current, *args)):
            await current.register_ingestor_dependency()
            self.assertTrue(await launcher.stop_locally("operator"))
        self.assertFalse(interface.operational_dependents[self.dependent]())

    async def test_preserved_instance_rollback_blocks_restart_reconstruction(self):
        await self.superseded_stop_history()
        old = next(m.to_dict() for m in self.intake_interface.evidence
            if m.payload.get("dependent_maintenance", {}).get("confirmation"))
        old["evidence_id"] = "preserved-rollback"
        self.assertTrue(self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(old)).accepted)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        before = self.intake_interface.evidence
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(self.intake_interface.evidence, before)
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse((await self.status()).payload["ready"])

    async def test_unconfirmed_authority_history_cannot_replace_current_instance(self):
        await self.backend()
        _, current, _, _ = await self.producer(preservation_window_s=2)
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(self.storage, "get_framework_preservation_confirmation", return_value=None):
            result = await self.intake_interface.execute_command(RuntimeCommandMessage("no-authority", None,
                "register_operational_dependent", "control", "intake", {"participant": self.dependent.to_dict(),
                "operational_instance_id": "another-instance", "ingestor_instance_id": self.intake_interface.operational_instance_id}))
        self.assertFalse(result.success)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        await current.register_ingestor_dependency()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

    async def test_incomplete_controller_release_cannot_clear_blocker_or_authorize_retirement(self):
        sync = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((self.dependent, sync))
        _, controller, _, _ = await self.producer()
        registration = deepcopy(next(c["payload"] for c in self.broker.commands
            if c["command_type"] == "register_operational_dependent" and c["source_id"] == "control"))
        registration.pop("request_nonce", None)
        for _ in range(2):
            _, _, launcher, _ = await self.producer("synchronization_manager", "sync")
            self.assertTrue(await launcher.stop_locally("operator"))
            for subscription in self.broker.subscriptions:
                if ".command.synchronization_manager.sync." in subscription.subject:
                    await subscription.unsubscribe()
        warning = RuntimeEvidenceMessage("unrelated-warning", None, "warning", "control", {"message": "unrelated"}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(warning).accepted)
        state = {"registration": registration, "conflicting": False,
            "confirmation": {**registration, "confirmation": {"controller_release": {
                "outcome": "dependency_released", "evidence": [warning.to_dict()]}}}}
        malformed = RuntimeEvidenceMessage("incomplete-release", None, "service_maintenance_evidence", "intake",
            {"dependent_maintenance": state}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(malformed).accepted)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        before = self.intake_interface.evidence
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertFalse(controller.prepared)
        self.assertFalse(controller.terminated)
        self.assertFalse((await self.status()).payload["ready"])
        self.assertFalse((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(self.intake_interface.evidence, before)
        self.assertEqual(files, {p: p.read_bytes() for p in files})

    async def controller_release_boundary(self, *, prior_sync_stop=False, mixed_observations=False):
        sync = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((self.dependent, sync))
        controller, owner, _, boundary = await self.producer(preservation_window_s=2)
        if prior_sync_stop:
            _, _, launcher, _ = await self.producer("synchronization_manager", "sync", preservation_window_s=2)
            self.assertTrue(await launcher.stop_locally("operator"))
            for subscription in self.broker.subscriptions:
                if ".command.synchronization_manager.sync." in subscription.subject:
                    await subscription.unsubscribe()
        sync_service, _, _, _ = await self.producer("synchronization_manager", "sync", preservation_window_s=2)
        original = self.intake_boundary.publish_command_result

        async def hold_release_reply(result, operation):
            if operation != "confirm_dependent_release" or result.target_id != "control":
                await original(result, operation)

        scope = (self.dependent, sync, self.intake_interface.participant, self.storage_interface.participant)
        communication = NatsControllerCommunication(boundary)
        request = communication.request_command

        async def observations(participant, operation, *args, **kwargs):
            if mixed_observations and operation == "check_stop_readiness" and participant == sync:
                return None
            response = await request(participant, operation, *args, **kwargs)
            if mixed_observations and operation == "check_stop_readiness" and participant == self.dependent:
                data = response.to_dict()
                data.update(status="failed", success=False, reason="Readiness observation unavailable")
                return RuntimeCommandResultMessage.from_dict(data)
            return response

        async def authorize(participant, blocked):
            self.assertEqual(participant, sync)
            self.assertEqual(blocked.payload["outcome"], "blocked")
            return True

        with patch.object(self.intake_boundary, "publish_command_result", hold_release_reply), \
                patch.object(communication, "request_command", observations), \
                patch.object(sync_service, "maintenance_blockers", side_effect=(
                    lambda *args: ["Held synchronization obligation"] if mixed_observations else [])):
            result = await controller.shutdown_framework(scope, communication=communication,
                stop_attempt_id="controller-proof", administrator_id="operator", result_window_s=0.5,
                authorize_kill=authorize if mixed_observations else None)
        self.assertFalse(result.succeeded)  # Lost release reply; infrastructure remains available.
        self.assertTrue(owner.prepared)
        self.assertFalse(owner.terminated)
        self.assertFalse(self.intake_interface.terminated)
        state = next(deepcopy(m.payload["dependent_maintenance"]) for m in reversed(self.intake_interface.evidence)
            if m.payload.get("dependent_maintenance", {}).get("confirmation", {}).get("confirmation", {}).get("controller_release"))
        return state, self.intake.compile_framework_runtime_evidence(), sync

    async def test_controller_release_accepts_unknown_failed_surveys_and_authorized_kill(self):
        state, _, sync = await self.controller_release_boundary(mixed_observations=True)
        final = next(m["payload"] for m in state["confirmation"]["confirmation"]["controller_release"]["evidence"]
            if m["payload"].get("checkpoint") == "final_archival_checkpoint")
        self.assertTrue(any(r["result"] is None for r in final["results"]))
        self.assertTrue(any(r["result"] and not r["result"]["success"] for r in final["results"]))
        survey_id = next(c["command_id"] for c in final["commands"]
            if c["command_type"] == "check_stop_readiness" and c["participant"] == self.dependent.to_dict())
        self.assertFalse(next(r["result"] for r in final["results"] if r["command_id"] == survey_id)["success"])
        self.assertEqual([c["command_type"] for c in final["commands"]
            if c["participant"] == sync.to_dict()], ["check_stop_readiness", "stop", "kill"])
        self.assertTrue((await self.status()).payload["ready"])
        # A further informational operation must remain representable; it neither
        # replaces a successful action nor turns an observation into release proof.
        payload = {"stop_attempt_id": next(p["stop_attempt_id"] for p in final["participant_attempts"]
            if p["participant"] == self.intake_interface.participant.to_dict()),
            "framework_stop_attempt_id": final["stop_attempt_id"], "administrator_id": "operator", "authorized": False}
        command = RuntimeCommandMessage("additional-survey", None, "check_stop_readiness", "control", "intake", payload)
        response = await self.intake_interface.execute_command(command)
        final["commands"].append({"command_id": command.command_id, "command_type": command.command_type,
            "participant": self.intake_interface.participant.to_dict(), "payload": payload})
        final["results"].append({"command_id": command.command_id, "result": response.to_dict()})
        release = state["confirmation"]["confirmation"]["controller_release"]
        for number, message in enumerate(release["evidence"]):
            message["evidence_id"] = f"additional-operation-{number}"
            self.assertTrue(self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message)).accepted)
        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage("additional-operation-release", None,
            "service_maintenance_evidence", "intake", {"dependent_maintenance": state}, True))
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        self.assertTrue((await self.status()).payload["ready"])
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend((self.dependent, sync))
        self.assertTrue((await self.status()).payload["ready"])
        self.assertTrue((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])

    async def test_preparation_blockers_prevent_release_despite_matching_cleanup_snapshot(self):
        state, _, _ = await self.controller_release_boundary(prior_sync_stop=True)
        release = state["confirmation"]["confirmation"]["controller_release"]
        for number, message in enumerate(release["evidence"]):
            message["evidence_id"] = f"blocked-preparation-{number}"
        final = next(m["payload"] for m in release["evidence"]
            if m["payload"].get("checkpoint") == "final_archival_checkpoint")
        prepare_id = next(c["command_id"] for c in final["commands"]
            if c["command_type"] == "prepare_stop" and c["participant"] == self.dependent.to_dict())
        prepared = next(r["result"] for r in final["results"] if r["command_id"] == prepare_id)
        prepared["payload"]["attempt"]["blockers"] = ["Unresolved Controller closeout obligation"]
        for message in release["evidence"]:
            if message["payload"].get("checkpoint") == "prepared_ready_for_retirement":
                message["payload"]["blockers"] = ["Unresolved Controller closeout obligation"]
            self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message))
        malformed = RuntimeEvidenceMessage("blocked-controller-release", None, "service_maintenance_evidence", "intake",
            {"dependent_maintenance": state}, True)
        self.intake.receive_runtime_evidence(malformed)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        before = self.intake_interface.evidence
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        survey = (await self.status()).payload
        retirement = await self.intake_interface.retire_dependent_maintenance_history()
        self.assertFalse(survey["ready"], {"readiness": survey, "retirement": retirement})
        self.assertFalse(retirement["confirmed"])
        self.assertEqual(retirement["released_evidence_count"], 0)
        self.assertEqual(self.intake_interface.evidence, before)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        self.assertTrue(self.intake.has_durable_runtime_evidence(malformed))

    async def test_controller_release_rejects_inconsistent_kill_authorization_history(self):
        original_state, compiled, sync = await self.controller_release_boundary(mixed_observations=True)
        base = self.root
        for index, fault in enumerate(("missing", "declined", "duplicate", "orphan", "unblocked", "attempt_history")):
            with self.subTest(fault=fault):
                self.root = base / ("kill-" + str(index))
                self.root.mkdir()
                self.broker = _Broker()
                await self.backend((self.dependent, sync))
                for message in compiled["runtime_evidence"]:
                    self.intake.receive_runtime_evidence(message)
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                self.assertTrue((await self.status()).payload["ready"])
                state = deepcopy(original_state)
                release = state["confirmation"]["confirmation"]["controller_release"]
                for number, message in enumerate(release["evidence"]):
                    message["evidence_id"] = f"kill-{fault}-{number}"
                final = next(m["payload"] for m in release["evidence"]
                    if m["payload"].get("checkpoint") == "final_archival_checkpoint")
                if fault == "missing":
                    final["authorizations"] = []
                elif fault == "declined":
                    final["authorizations"][0]["authorized"] = False
                elif fault == "duplicate":
                    final["authorizations"].append(deepcopy(final["authorizations"][0]))
                elif fault == "orphan":
                    final["authorizations"][0]["blocked_command_id"] = "unrelated-stop"
                else:
                    operation = "stop" if fault == "unblocked" else "kill"
                    identity = next(c["command_id"] for c in final["commands"]
                        if c["participant"] == sync.to_dict() and c["command_type"] == operation)
                    record = next(r["result"] for r in final["results"] if r["command_id"] == identity)
                    if fault == "unblocked":
                        record["payload"]["outcome"] = "failed"
                    else:
                        record["payload"]["attempt"]["commands"][0]["administrator_id"] = "different-admin"
                for message in release["evidence"]:
                    self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message))
                self.intake.receive_runtime_evidence(RuntimeEvidenceMessage("bad-kill-" + fault, None,
                    "service_maintenance_evidence", "intake", {"dependent_maintenance": state}, True))
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                self.assertFalse((await self.status()).payload["ready"])
                self.assertFalse((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])

    async def test_historical_controller_release_proof_and_restart(self):
        await self.controller_release_boundary()
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend((self.dependent, RuntimeParticipant("synchronization_manager", "sync")))
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertTrue((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertEqual(files, {p: p.read_bytes() for p in files})

    async def test_orphan_controller_result_is_preserved_but_cannot_release_or_retire(self):
        state, _, sync = await self.controller_release_boundary(prior_sync_stop=True)
        self.assertTrue((await self.status()).payload["ready"])
        release = state["confirmation"]["confirmation"]["controller_release"]
        for number, message in enumerate(release["evidence"]):
            message["evidence_id"] = f"orphan-proof-{number}"
        final = next(m["payload"] for m in release["evidence"]
            if m["payload"].get("checkpoint") == "final_archival_checkpoint")
        sync_id = next(c["command_id"] for c in final["commands"]
            if c["participant"] == sync.to_dict() and c["command_type"] == "stop")
        embedded = next(r["result"] for r in final["results"] if r["command_id"] == sync_id)
        final["results"].append({"command_id": "ghost", "result": deepcopy(embedded)})
        for message in release["evidence"]:
            self.assertTrue(self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message)).accepted)
        malformed = RuntimeEvidenceMessage("orphan-release", None, "service_maintenance_evidence", "intake",
            {"dependent_maintenance": state}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(malformed).accepted)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        before = self.intake_interface.evidence
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        survey = (await self.status()).payload
        retirement = await self.intake_interface.retire_dependent_maintenance_history()
        self.assertFalse(survey["ready"], {"survey": survey, "retirement": retirement})
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse(retirement["confirmed"])
        self.assertEqual(retirement["released_evidence_count"], 0)
        self.assertEqual(before, self.intake_interface.evidence)
        self.assertEqual(files, {p: p.read_bytes() for p in files})
        self.assertTrue(self.intake.has_durable_runtime_evidence(malformed))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend((self.dependent, sync))
        self.assertFalse((await self.status()).payload["ready"])
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertFalse((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])
        self.assertTrue(self.intake.has_durable_runtime_evidence(malformed))

    async def test_false_checkpoint_retirement_cannot_release_controller_or_retire_history(self):
        state, _, sync = await self.controller_release_boundary(prior_sync_stop=True)
        release = state["confirmation"]["confirmation"]["controller_release"]
        for number, message in enumerate(release["evidence"]):
            message["evidence_id"] = f"false-retirement-{number}"
        checkpoint = next(m["payload"] for m in release["evidence"]
            if m["payload"].get("checkpoint") == "participant_result_confirmed")
        checkpoint["retired"].append(self.dependent.to_dict())
        checkpoint["not_retired"].remove(self.dependent.to_dict())
        checkpoint["remaining_obligations"] = deepcopy(checkpoint["not_retired"])
        for message in release["evidence"]:
            self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message))
        malformed = RuntimeEvidenceMessage("false-retirement-release", None, "service_maintenance_evidence", "intake",
            {"dependent_maintenance": state}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(malformed).accepted)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        before = self.intake_interface.evidence
        files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        survey = (await self.status()).payload
        blocker = self.intake_interface.operational_dependents[self.dependent]()
        retirement = await self.intake_interface.retire_dependent_maintenance_history()
        unchanged = files == {p: p.read_bytes() for p in files}
        retained = before == self.intake_interface.evidence
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend((self.dependent, sync))
        restarted = (await self.status()).payload
        observations = {"ready": survey["ready"], "blocker": blocker, "retirement": retirement,
            "durable_files_unchanged": unchanged, "producer_copies_retained": retained,
            "restart_ready": restarted["ready"]}
        self.assertFalse(survey["ready"], observations)
        self.assertTrue(blocker)
        self.assertFalse(retirement["confirmed"])
        self.assertEqual(retirement["released_evidence_count"], 0)
        self.assertTrue(unchanged)
        self.assertTrue(retained)
        self.assertFalse(restarted["ready"])
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertTrue(self.intake.has_durable_runtime_evidence(malformed))

    async def test_historical_controller_release_rejects_incomplete_or_mismatched_proof(self):
        original_state, compiled, sync = await self.controller_release_boundary()
        base = self.root
        cases = ("missing_attempt", "wrong_framework_attempt", "wrong_preparation_attempt", "missing_preparation",
                 "missing_cleanup_evidence", "missing_checkpoint", "wrong_checkpoint", "wrong_controller_instance",
                 "wrong_ingestor_instance", "wrong_prepared_instance", "unprepared_result", "unpreserved_evidence",
                 "unrelated_evidence", "anticipated_retirement", "matching_blockers", "result_blockers",
                 "snapshot_blockers", "matching_failures", "matching_obligations", "missing_blockers",
                 "missing_preparation_outcome", "missing_result_outcome", "missing_final_outcome",
                 "forced_cleanup", "already_retired", "manual_intervention", "termination_confirmed",
                 "ghost", "orphan", "duplicate_command", "duplicate_result", "duplicate_result_id",
                 "wrong_survey_source", "wrong_survey_target", "wrong_survey_attempt", "wrong_survey_admin",
                 "wrong_survey_status", "wrong_survey_success", "missing_survey_result", "unsupported_action",
                 "reordered_commands", "contradictory_snapshot", "contradictory_prefix", "wrong_attempt_target",
                 "checkpoint_retired", "checkpoint_not_retired", "checkpoint_obligations", "checkpoint_scope",
                 "checkpoint_outcome", "checkpoint_failure", "checkpoint_session", "checkpoint_type",
                 "checkpoint_duplicate", "checkpoint_reordered", "checkpoint_missing", "checkpoint_joint",
                 "checkpoint_future_action", "checkpoint_final_retired", "checkpoint_survey", "checkpoint_attempt")
        for index, fault in enumerate(cases):
            with self.subTest(fault=fault):
                self.root = base / str(index)
                self.root.mkdir()
                self.broker = _Broker()
                await self.backend((self.dependent, sync))
                for message in compiled["runtime_evidence"]:
                    self.intake.receive_runtime_evidence(message)
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                self.assertTrue((await self.status()).payload["ready"])
                state = deepcopy(original_state)
                release = state["confirmation"]["confirmation"]["controller_release"]
                for number, message in enumerate(release["evidence"]):
                    message["evidence_id"] = f"{fault}-{number}"
                final = next(m["payload"] for m in release["evidence"]
                    if m["payload"].get("checkpoint") == "final_archival_checkpoint")
                prepare_id = next(c["command_id"] for c in final["commands"]
                    if c["command_type"] == "prepare_stop" and c["participant"] == self.dependent.to_dict())
                prepared = next(r["result"] for r in final["results"] if r["command_id"] == prepare_id)
                snapshot = next(m["payload"] for m in release["evidence"]
                    if m["payload"].get("checkpoint") == "prepared_ready_for_retirement")
                attempt = prepared["payload"]["attempt"]
                if fault.startswith("checkpoint_"):
                    middle = next(m for m in release["evidence"]
                        if m["payload"].get("checkpoint") == "participant_result_confirmed")
                    claim = middle["payload"]
                    if fault in {"checkpoint_retired", "checkpoint_joint"}:
                        claim["retired"].append(self.dependent.to_dict())
                    if fault in {"checkpoint_not_retired", "checkpoint_joint"}:
                        claim["not_retired"].remove(self.dependent.to_dict())
                    if fault == "checkpoint_joint":
                        claim["remaining_obligations"] = deepcopy(claim["not_retired"])
                    elif fault == "checkpoint_obligations":
                        claim["remaining_obligations"] = []
                    elif fault == "checkpoint_scope":
                        claim["scope"] = list(reversed(claim["scope"]))
                    elif fault == "checkpoint_outcome":
                        claim["outcome"] = "completed"
                    elif fault == "checkpoint_failure":
                        claim["failures"] = ["Unresolved coordination failure"]
                    elif fault == "checkpoint_session":
                        claim["session_id"] = "unrelated-session"
                    elif fault == "checkpoint_type":
                        claim["checkpoint"] = "coordination_failed"
                    elif fault == "checkpoint_duplicate":
                        duplicate = deepcopy(middle)
                        duplicate["evidence_id"] = "duplicate-coordination-checkpoint"
                        release["evidence"].insert(release["evidence"].index(middle) + 1, duplicate)
                    elif fault == "checkpoint_reordered":
                        release["evidence"].remove(middle)
                        release["evidence"].append(middle)
                    elif fault == "checkpoint_missing":
                        release["evidence"].remove(middle)
                    elif fault == "checkpoint_future_action":
                        claim["actions"] = deepcopy(final["actions"])
                    elif fault == "checkpoint_final_retired":
                        final["retired"].append(self.dependent.to_dict())
                    elif fault == "checkpoint_survey":
                        claim["survey"] = []
                    elif fault == "checkpoint_attempt":
                        claim["participant_attempts"][0]["stop_attempt_id"] = "another-attempt"
                first_result = next(r for r in final["results"] if r["result"] is not None)
                first_command = next(c for c in final["commands"] if c["command_id"] == first_result["command_id"])
                if fault in {"ghost", "orphan"}:
                    extra = deepcopy(first_result)
                    extra["command_id"] = "ghost"
                    if fault == "orphan":
                        extra["result"]["command_id"] = "ghost"
                    final["results"].append(extra)
                elif fault == "duplicate_command":
                    final["commands"].append(deepcopy(first_command))
                elif fault == "duplicate_result":
                    final["results"].append(deepcopy(first_result))
                elif fault == "duplicate_result_id":
                    prepared["result_id"] = first_result["result"]["result_id"]
                elif fault in {"wrong_survey_source", "wrong_survey_target", "wrong_survey_status", "wrong_survey_success"}:
                    key, value = {"wrong_survey_source": ("source_id", "another-owner"),
                        "wrong_survey_target": ("target_id", "another-controller"),
                        "wrong_survey_status": ("status", "failed"),
                        "wrong_survey_success": ("success", 1)}[fault]
                    first_result["result"][key] = value
                elif fault in {"wrong_survey_attempt", "wrong_survey_admin"}:
                    key = "framework_stop_attempt_id" if fault == "wrong_survey_attempt" else "administrator_id"
                    first_command["payload"][key] = "another-identity"
                elif fault == "missing_survey_result":
                    final["results"].remove(first_result)
                elif fault == "unsupported_action":
                    final["actions"].append({"participant": self.dependent.to_dict(), "action": "retirement_confirmed"})
                elif fault == "reordered_commands":
                    final["commands"].reverse()
                    final["results"].reverse()
                elif fault == "contradictory_snapshot":
                    extra = deepcopy(next(m for m in release["evidence"]
                        if m["payload"].get("checkpoint") == "prepared_ready_for_retirement"))
                    extra["evidence_id"] = "contradictory-preparation"
                    extra["payload"]["blockers"] = ["Unresolved obligation"]
                    release["evidence"].append(extra)
                elif fault == "contradictory_prefix":
                    earlier = next(m["payload"] for m in release["evidence"]
                        if m["payload"].get("checkpoint") == "initial_survey")
                    earlier["commands"][0]["payload"]["administrator_id"] = "another-admin"
                elif fault == "wrong_attempt_target":
                    attempt["target"] = sync.to_dict()
                if fault in {"matching_blockers", "result_blockers", "snapshot_blockers"}:
                    if fault != "snapshot_blockers":
                        attempt["blockers"] = ["Unresolved Controller closeout obligation"]
                    if fault != "result_blockers":
                        snapshot["blockers"] = ["Unresolved Controller closeout obligation"]
                elif fault in {"matching_failures", "matching_obligations"}:
                    key = "failures" if fault == "matching_failures" else "remaining_obligations"
                    attempt[key] = snapshot[key] = ["Unresolved cleanup"]
                elif fault in {"missing_blockers", "missing_preparation_outcome"}:
                    key = "blockers" if fault == "missing_blockers" else "outcome"
                    del attempt[key]
                    del snapshot[key]
                elif fault == "missing_result_outcome":
                    del prepared["payload"]["outcome"]
                elif fault == "missing_final_outcome":
                    del final["outcome"]
                elif fault in {"forced_cleanup", "already_retired"}:
                    action = "forced_resources_closed" if fault == "forced_cleanup" else "operational_retirement_confirmed"
                    attempt["actions"].append(action)
                    snapshot["actions"].append(action)
                elif fault == "manual_intervention":
                    prepared["payload"]["manual_intervention_required"] = True
                elif fault == "termination_confirmed":
                    prepared["payload"]["termination_confirmed"] = True
                if fault == "missing_attempt":
                    del release["framework_stop_attempt_id"]
                elif fault == "wrong_framework_attempt":
                    release["framework_stop_attempt_id"] = "another-shutdown"
                elif fault == "wrong_preparation_attempt":
                    release["stop_attempt_id"] = "another-preparation"
                elif fault == "missing_preparation":
                    final["results"] = [r for r in final["results"] if r["command_id"] != prepare_id]
                elif fault == "missing_cleanup_evidence":
                    release["evidence"] = [m for m in release["evidence"]
                        if m["payload"].get("checkpoint") != "prepared_ready_for_retirement"]
                elif fault == "missing_checkpoint":
                    release["evidence"] = [m for m in release["evidence"]
                        if m["payload"].get("checkpoint") != "final_archival_checkpoint"]
                elif fault == "wrong_checkpoint":
                    final["checkpoint"] = "participant_result_confirmed"
                elif fault in {"wrong_controller_instance", "wrong_ingestor_instance"}:
                    key = "operational_instance_id" if fault == "wrong_controller_instance" else "ingestor_instance_id"
                    state["registration"][key] = "another-operational-instance"
                    state["confirmation"][key] = "another-operational-instance"
                elif fault == "unprepared_result":
                    prepared["payload"]["prepared"] = False
                elif fault == "wrong_prepared_instance":
                    prepared["payload"]["operational_instance_id"] = "another-controller-instance"
                elif fault == "anticipated_retirement":
                    final["retired"].append(self.dependent.to_dict())
                elif fault == "unrelated_evidence":
                    release["evidence"] = [RuntimeEvidenceMessage("only-warning", None, "warning", "control", {}, True).to_dict()]
                for message in release["evidence"]:
                    if fault != "unpreserved_evidence":
                        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage.from_dict(message))
                malformed = RuntimeEvidenceMessage("bad-" + fault, None, "service_maintenance_evidence", "intake",
                    {"dependent_maintenance": state}, True)
                self.intake.receive_runtime_evidence(malformed)
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                before = self.intake_interface.evidence
                files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                self.assertFalse((await self.status()).payload["ready"])
                self.assertFalse((await self.intake_interface.retire_dependent_maintenance_history())["confirmed"])
                self.assertEqual(self.intake_interface.evidence, before)
                self.assertEqual(files, {p: p.read_bytes() for p in files})
                for subscription in self.broker.subscriptions:
                    await subscription.unsubscribe()
                await self.backend((self.dependent, sync))
                self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

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

    async def test_blocked_stop_and_cancel_span_months_without_rewriting_or_losing_dependency(self):
        december = datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()
        january = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        with patch("lab_sync_acquisition.storage.time", return_value=december) as clock:
            await self.backend()
            await self.producer()
            payload = {"stop_attempt_id": "cross-month-attempt", "administrator_id": "operator"}
            blocked = await self.intake_interface.execute_command(RuntimeCommandMessage(
                "stop-cross-month", None, "stop", "operator", "intake", payload))
            self.assertFalse(blocked.success)
            directory = self.root / "storage/framework/evidence/2025-12"
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            clock.return_value = january
            cancelled = await self.intake_interface.execute_command(RuntimeCommandMessage(
                "cancel-cross-month", None, "cancel", "operator", "intake", payload))
            self.assertFalse(cancelled.success)
            self.assertEqual(cancelled.payload["attempt"]["stop_attempt_id"], "cross-month-attempt")
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
            for subscription in self.broker.subscriptions:
                await subscription.unsubscribe()
            await self.backend()
            self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
            self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())
            self.assertTrue(any(m.payload.get("stop_attempt_id") == "cross-month-attempt"
                                for m in self.intake.compile_framework_runtime_evidence()["runtime_evidence"]))
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

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

    async def test_receiver_restart_continues_archive_before_restoring_release(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
        self.assertTrue((await self.status()).payload["ready"])
        with self.intake.framework_preservation_guard(self.storage) as archive:
            self.assertTrue(any(m["evidence_type"] == "ingestor_recovery_evidence"
                                for m in archive["runtime_evidence"]))
        self.assertTrue(await self.pair.stop_locally("operator"))
        self.assertTrue(self.pair.exit_ready)

    async def test_repeated_receiver_restart_preserves_each_recovery_and_release(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        previous = self.storage.get_framework_preservation_confirmation()
        for _ in range(2):
            for subscription in self.broker.subscriptions:
                await subscription.unsubscribe()
            await self.backend()
            current = self.storage.get_framework_preservation_confirmation()
            self.assertEqual(current["runtime_evidence"][:-1], previous["runtime_evidence"])
            self.assertEqual(current["runtime_evidence"][-1]["evidence_type"], "ingestor_recovery_evidence")
            self.assertFalse(self.intake_interface.operational_dependents[self.dependent]())
            previous = current

    async def test_restart_rejects_inexact_evidence_audit_and_summary_without_rewriting(self):
        for product in ("runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"):
            with self.subTest(product=product):
                # Separate deployment paths avoid treating a prior corruption as a baseline.
                self.root = self.root / product
                self.root.mkdir()
                self.broker = _Broker()
                await self.backend()
                _, _, launcher, _ = await self.producer()
                self.assertTrue(await launcher.stop_locally("operator"))
                path = next((self.root / "storage/framework/evidence").glob("????-??")) / product
                rows = path.read_text().splitlines()
                if product == "compilation_summary.json":
                    data = json.loads(path.read_text())
                    data["runtime_evidence_count"] += 1
                    path.write_text(json.dumps(data))
                else:
                    data = json.loads(rows[0])
                    data["source_id" if product == "runtime_evidence.jsonl" else "reason"] = "conflict"
                    rows[0] = json.dumps(data)
                    path.write_text("\n".join(rows) + "\n")
                before = {p: p.read_bytes() for p in path.parent.iterdir()}
                for subscription in self.broker.subscriptions:
                    await subscription.unsubscribe()
                await self.backend()
                self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                self.assertEqual(before, {p: p.read_bytes() for p in path.parent.iterdir()})

    async def test_corrupt_or_missing_history_cannot_be_continued(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        directory = next((self.root / "storage/framework/evidence").glob("????-??"))
        path = directory / "runtime_evidence.jsonl"
        path.write_text("not-json\n")
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertEqual(path.read_text(), "not-json\n")
        path.unlink()
        with self.assertRaises(OSError):
            self.intake.continue_framework_evidence_archive()
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())

    async def test_failed_continuation_retains_blocker_and_unconfirmed_archive(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        before = self.storage.get_framework_preservation_confirmation()
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        with patch.object(PersistentStorageManager, "_write_framework_evidence_archive", side_effect=OSError("disk failed")):
            await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertGreater(len(self.intake.compile_framework_runtime_evidence()["runtime_evidence"]),
                           len(before["runtime_evidence"]))

    async def test_current_verified_archive_continuation_does_not_rewrite(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        before = self.storage.get_framework_preservation_confirmation()
        with patch.object(self.storage, "write_framework_evidence_archive", wraps=self.storage.write_framework_evidence_archive) as write:
            self.assertEqual(self.intake.continue_framework_evidence_archive(), before)
            write.assert_not_called()

    async def test_mismatched_prefix_boundaries_cannot_authorize_continuation(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        directory = next((self.root / "storage/framework/evidence").glob("????-??"))
        evidence_path = directory / "runtime_evidence.jsonl"
        evidence = [json.loads(line) for line in evidence_path.read_text().splitlines()][:-1]
        evidence_path.write_text("".join(json.dumps(m) + "\n" for m in evidence))
        summary_path = directory / "compilation_summary.json"
        summary = json.loads(summary_path.read_text())
        summary["runtime_evidence_count"] = len(evidence)
        summary["runtime_evidence_ids"] = [m["evidence_id"] for m in evidence]
        summary_path.write_text(json.dumps(summary))
        before = {p: p.read_bytes() for p in directory.iterdir()}
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertEqual(before, {p: p.read_bytes() for p in directory.iterdir()})

    async def test_unconfirmed_final_readback_cannot_restore_release(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        with patch.object(PersistentStorageManager, "get_framework_preservation_confirmation", return_value=None):
            await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())

    async def test_absent_archive_cannot_replace_recovered_history(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        directory = next((self.root / "storage/framework/evidence").glob("????-??"))
        for path in directory.iterdir():
            path.unlink()
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertEqual(list(directory.iterdir()), [])

    async def test_superseded_registration_remains_a_blocker_after_receiver_restart(self):
        await self.backend()
        _, _, launcher, _ = await self.producer()
        self.assertTrue(await launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            if ".command.controller.control." in subscription.subject:
                await subscription.unsubscribe()
        await self.producer()
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())

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
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend()
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())
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

    async def test_shared_launcher_reconciles_before_restoring_dependent_release(self):
        await self.backend()
        _, _, producer, _ = await self.producer()
        self.assertTrue(await producer.stop_locally("operator"))
        historical = self.storage.get_framework_preservation_confirmation()

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            return value

        async def run(launcher, *, startup):
            intake = launcher.maintenance[0]
            self.assertFalse(intake.operational_dependents[self.dependent]())
            with intake.ingestor.framework_preservation_guard(intake.storage_manager) as archive:
                self.assertEqual(archive["runtime_evidence"][:-1], historical["runtime_evidence"])
                self.assertEqual(archive["runtime_evidence"][-1]["evidence_type"], "ingestor_recovery_evidence")
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", side_effect=boundary), patch.object(
                ServiceLauncher, "run", run):
            self.assertEqual(await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "storage", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "framework.jsonl", preservation_window_s=0.02,
                operational_dependents={}, external_dependents=(self.dependent,), result_window_s=0.02,
                report=lambda text: None), 0)

    async def rejected_restart(self, damage="corrupt"):
        await self.backend()
        _, _, producer, _ = await self.producer()
        self.assertTrue(await producer.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        directory = next((self.root / "storage/framework/evidence").glob("????-??"))
        if damage == "missing":
            for path in directory.iterdir():
                path.unlink()
        elif damage == "partial":
            (directory / "ingest_audit.jsonl").unlink()
        else:
            (directory / "runtime_evidence.jsonl").write_bytes(b"CORRUPTED-HISTORY\n")
        before = {path.name: path.read_bytes() for path in directory.iterdir()}
        await self.backend()
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        return directory, before

    async def test_local_stop_cannot_repair_rejected_history(self):
        directory, before = await self.rejected_restart()
        self.assertFalse(await self.pair.stop_locally("operator"))
        self.assertFalse(self.pair.exit_ready)
        self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    async def test_prepare_stop_cannot_replace_missing_or_partial_history(self):
        for damage in ("missing", "partial", "corrupt"):
            with self.subTest(damage=damage):
                self.root = self.root / damage
                self.root.mkdir()
                self.broker = _Broker()
                directory, before = await self.rejected_restart(damage)
                result = await self.storage_interface.execute_command(RuntimeCommandMessage(
                    "prepare", None, "prepare_stop", "operator", "storage",
                    {"stop_attempt_id": "prepare", "framework_stop_attempt_id": "framework", "administrator_id": "operator"}))
                self.assertFalse(result.success)
                self.assertFalse(self.storage_interface.prepared)
                self.assertFalse(self.pair.exit_ready)
                self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    async def test_maintenance_cannot_repair_rejected_archive(self):
        for operation in ("cancel", "kill", "readiness", "administrator"):
            with self.subTest(operation=operation):
                self.root = self.root / operation
                self.root.mkdir()
                self.broker = _Broker()
                directory, before = await self.rejected_restart()
                payload = {"stop_attempt_id": "blocked", "administrator_id": "operator"}
                if operation in {"cancel", "kill"}:
                    blocked = await self.intake_interface.execute_command(RuntimeCommandMessage(
                        "stop", None, "stop", "operator", "intake", payload))
                    self.assertFalse(blocked.success)
                    await self.intake_interface.execute_command(RuntimeCommandMessage(
                        operation, None, operation, "operator", "intake", {**payload, "authorized": True}))
                elif operation == "readiness":
                    with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                        status = await self.intake_interface.announce_readiness(startup=True)
                    self.assertFalse(status["archival_confirmed"])
                else:
                    with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                        status = await self.intake_interface.record_administrator_decision("operator", "resume", {})
                    self.assertFalse(status["archival_confirmed"])
                self.assertTrue(self.intake_interface.operational_dependents[self.dependent]())
                self.assertFalse(self.pair.exit_ready)
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    async def test_production_restart_and_stop_leave_rejected_archive_unchanged(self):
        directory, before = await self.rejected_restart()
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, self.broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            return value

        async def run(launcher, *, startup):
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                await startup()
            self.assertFalse(await launcher.stop_locally("operator"))
            self.assertFalse(launcher.exit_ready)
            intake = launcher.maintenance[0]
            self.assertTrue(intake.operational_dependents[self.dependent]())
            self.assertIsNone(intake.storage_manager.get_framework_preservation_confirmation())
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", side_effect=boundary), patch.object(
                ServiceLauncher, "run", run):
            self.assertEqual(await launch_storage_services(servers=("nats://example:4222",), ingestor_id="intake",
                storage_id="storage", storage_root=self.root / "storage", recovery_journal_root=self.root / "journals",
                framework_journal=self.root / "framework.jsonl", preservation_window_s=0.02,
                operational_dependents={}, external_dependents=(self.dependent,), result_window_s=0.02,
                report=lambda text: None), 0)
