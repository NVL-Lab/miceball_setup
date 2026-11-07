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
from tests.nats_server_fixture import NATS_SERVER, restartable_jetstream_server, acquire_test_controller_authority


class ExternalDependentConfigurationTests(unittest.TestCase):
    def test_repeated_framework_envelopes_preserve_complete_audit_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = PersistentStorageManager(root / "storage")
            intake = InMemoryIngestor(storage, framework_recovery_journal_path=root / "framework.jsonl")
            evidence = RuntimeEvidenceMessage("same", None, "warning", "source",
                {"values": [True, 1, 1.0, {"text": "line\nnext"}]}, True)
            for _ in range(30):
                self.assertTrue(intake.receive_runtime_evidence(evidence).accepted)
            with intake.framework_journal_guard():
                self.assertEqual(intake.read_framework_write_records(), [])
                storage.write_framework_evidence_archive(intake.compile_framework_runtime_evidence())
            with intake.framework_preservation_guard(storage) as archive:
                self.assertEqual(archive["runtime_evidence"], [evidence.to_dict()])
                self.assertEqual(len(archive["ingest_audit"]), 30)

    def test_changed_or_malformed_duplicate_cannot_authorize_preservation(self):
        for value in (True, 1.0, None, [1], {"nested": float("nan")}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                storage = PersistentStorageManager(root / "storage")
                path = root / "framework.jsonl"
                intake = InMemoryIngestor(storage, framework_recovery_journal_path=path)
                message = RuntimeEvidenceMessage("same", None, "warning", "source", {"value": 1}, True)
                intake.receive_runtime_evidence(message)
                intake.receive_runtime_evidence(message)
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                rows[-1]["runtime_evidence"]["payload"] = {"value": value}
                path.write_text("".join(json.dumps(row) + "\n" for row in rows))
                before = path.read_bytes()
                with self.assertRaises((RuntimeError, ValueError)):
                    storage.write_framework_evidence_archive(intake.compile_framework_runtime_evidence())
                self.assertEqual(path.read_bytes(), before)
                self.assertIsNone(storage.get_framework_preservation_confirmation())

    def test_nested_framework_operations_revalidate_appends_and_external_damage(self):
        import os
        import re
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "framework.jsonl"
            storage = PersistentStorageManager(root / "storage")
            intake = InMemoryIngestor(storage, framework_recovery_journal_path=path)
            first = RuntimeEvidenceMessage("first", None, "warning", "source", {"value": 1}, True)
            intake.receive_runtime_evidence(first)
            with intake.framework_journal_guard():
                intake.read_framework_write_records()
                intake.receive_runtime_evidence(RuntimeEvidenceMessage("later", None, "warning", "source", {}, True))
                storage.write_framework_evidence_archive(intake.compile_framework_runtime_evidence())
            with intake.framework_preservation_guard(storage) as archive:
                self.assertEqual([m["evidence_id"] for m in archive["runtime_evidence"]], ["first", "later"])
            with self.assertRaises((RuntimeError, ValueError)):
                with intake.framework_journal_guard():
                    intake.read_framework_write_records()
                    stamp = path.stat()
                    original = path.read_bytes()
                    damaged = re.sub(rb'("value"\s*:\s*)1', rb'\g<1>2', original, count=1)
                    self.assertNotEqual(original, damaged)
                    path.write_bytes(damaged)
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    intake.read_framework_write_records()

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


@unittest.skipUnless(NATS_SERVER, "optional isolated nats-server unavailable")
class ExternalDependentRegistrationTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_public_pair_preserves_empty_history_during_startup_publication(self):
        from lab_sync_acquisition import NatsCommunicationBoundary
        server = await self.enterAsyncContext(restartable_jetstream_server())
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        observed, reports = [], []
        original = NatsCommunicationBoundary.publish_evidence

        async def publish(boundary, evidence):
            if boundary.component_type == "ingestor" and not observed:
                owner = boundary._maintenance_owner
                # The paired publisher has accepted this readiness record locally,
                # but its first archival write has not happened yet.
                result = await owner.execute_command(RuntimeCommandMessage("startup-survey", None,
                    "check_stop_readiness", "observer", "intake", {}))
                observed.append(result.payload)
            return await original(boundary, evidence)

        async def capture(launcher, *, startup):
            for boundary in launcher.boundaries:
                self.addAsyncCleanup(boundary.close)
            await startup()
            return launcher

        with patch.object(ServiceLauncher, "run", capture), patch.object(NatsCommunicationBoundary, "publish_evidence", publish):
            launcher = await launch_storage_services(servers=(server.url,), ingestor_id="intake", storage_id="storage",
                storage_root=root / "storage", recovery_journal_root=root / "journals",
                framework_journal=root / "framework.jsonl", preservation_window_s=2, operational_dependents={},
                external_dependents=(RuntimeParticipant("acquisition_node", "unused"),), result_window_s=1,
                controller_claim_account="$G", controller_claim_bucket="AUTHORITY", controller_claim_key="controller",
                report=reports.append)
        self.assertTrue(observed)
        self.assertNotIn("Operational dependency: acquisition_node/unused", observed[0]["blockers"])
        self.assertTrue(all(json.loads(row)["startup"]["archival_confirmed"] for row in reports if row.startswith("{")))
        self.assertTrue(await launcher.stop_locally("operator"))

    async def test_queued_framework_evidence_after_retirement_has_truthful_cleanup(self):
        import nats
        from lab_sync_acquisition import NatsCommunicationBoundary
        from lab_sync_acquisition.communication import build_runtime_subject

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for case in ("duplicate", "unknown", "conflict", "damaged", "cancelled", "close-cancelled"):
            with self.subTest(case=case):
                server = await self.enterAsyncContext(restartable_jetstream_server())
                entered, resume = asyncio.Event(), asyncio.Event()
                errors, subscriptions = [], []
                original = NatsIngestorCommunication.subscribe_evidence

                async def error_cb(error):
                    errors.append(str(error))

                async def observer(evidence):
                    if evidence.evidence_id == "queued":
                        entered.set()
                        await resume.wait()
                        if case == "cancelled":
                            raise asyncio.CancelledError()

                async def subscribe(receiver, session_id, callback=None):
                    receiver._boundary._require_client()._error_cb = error_cb
                    subscription = await original(receiver, session_id, observer if session_id is None else callback)
                    subscriptions.append(subscription)
                    return subscription

                async def capture(launcher, *, startup):
                    await startup()
                    return launcher

                with patch.object(ServiceLauncher, "run", capture), patch.object(NatsIngestorCommunication, "subscribe_evidence", subscribe):
                    launcher = await launch_storage_services(servers=(server.url,), ingestor_id="intake", storage_id="storage",
                        storage_root=root / case / "storage", recovery_journal_root=root / case / "journals",
                        framework_journal=root / case / "framework.jsonl", preservation_window_s=2,
                        operational_dependents={}, external_dependents=(RuntimeParticipant("acquisition_node", "unused"),),
                        result_window_s=1, controller_claim_account="$G", controller_claim_bucket="AUTHORITY",
                        controller_claim_key="controller", report=lambda text: None)
                client = await nats.connect(server.url)
                evidence = RuntimeEvidenceMessage("queued", None, "warning", "probe", {"value": "original"}, True)

                async def publish(message):
                    subject = build_runtime_subject(None, "evidence", "synchronization_manager", message.source_id, message.evidence_type)
                    await client.jetstream().publish(subject, json.dumps(message.to_dict()).encode())

                try:
                    await publish(evidence)
                    await asyncio.wait_for(entered.wait(), 2)
                    queued = (RuntimeEvidenceMessage("unknown", None, "warning", "probe", {}, True) if case == "unknown" else
                              RuntimeEvidenceMessage("queued", None, "warning", "probe", {"value": "conflict"}, True)
                              if case == "conflict" else evidence)
                    await publish(queued)
                    self.assertTrue(await launcher.stop_locally("operator"))
                    journal = root / case / "framework.jsonl"
                    before = journal.read_bytes()
                    if case == "damaged":
                        journal.write_bytes(before + b"corrupt\n")
                        before = journal.read_bytes()
                    if case == "close-cancelled":
                        closing = asyncio.create_task(launcher.boundaries[0].close())
                        await asyncio.sleep(0)
                        closing.cancel()
                        resume.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(closing, 3)
                        self.assertIsNone(launcher.boundaries[0]._client)
                        await launcher.boundaries[1].close()
                        self.assertEqual(errors, [])
                        self.assertEqual(journal.read_bytes(), before)
                    elif case == "duplicate":
                        resume.set()
                        for boundary in launcher.boundaries:
                            await asyncio.wait_for(boundary.close(), 3)
                        self.assertEqual(errors, [])
                        self.assertEqual(journal.read_bytes(), before)
                    else:
                        resume.set()
                        # Use the existing SDK drain bound, not a production timing setting.
                        launcher.boundaries[0]._require_client().options["drain_timeout"] = .2
                        with self.assertRaises((RuntimeError, TimeoutError)):
                            await launcher.boundaries[0].close()
                        self.assertIsNotNone(launcher.boundaries[0]._client)
                        self.assertFalse(launcher.boundaries[0]._require_client().is_closed)
                        info = await subscriptions[0].consumer_info()
                        self.assertGreater(info.num_ack_pending, 0)
                        if case in {"unknown", "conflict"}:
                            self.assertEqual(info.num_ack_pending, 1)
                        self.assertEqual(journal.read_bytes(), before)
                finally:
                    resume.set()
                    await client.close()
                    for boundary in launcher.boundaries:
                        # Test teardown only: unresolved owner obligations must not
                        # be mistaken for successful production communication close.
                        if boundary._client is not None:
                            await boundary._client.close()
                    server.stop()

    async def test_retained_controller_startup_recovers_maintenance_before_exact_claim_release(self):
        import nats
        from nats.js.api import KeyValueConfig, StorageType
        from nats.js.client import JetStreamContext
        from nats.js.errors import KeyNotFoundError
        from lab_sync_acquisition import NatsCommunicationBoundary
        from lab_sync_acquisition.service_startup import launch_independent_service

        server = await self.enterAsyncContext(restartable_jetstream_server())
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        client = await nats.connect(server.url)
        self.addAsyncCleanup(client.close)
        kv = await client.jetstream().create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))

        async def capture(launcher, *, startup):
            for boundary in launcher.boundaries:
                self.addAsyncCleanup(boundary.close)
            try:
                await startup()
            except asyncio.CancelledError:
                pass  # Model the protected launcher's joined startup cancellation.
            return launcher

        for phase in ("streams", "subscription", "registration", "sync-subscription"):
            with self.subTest(phase=phase):
                kind, identity = (("synchronization_manager", "sync") if phase == "sync-subscription"
                                  else ("controller", "control"))
                pair_kwargs = dict(servers=(server.url,), ingestor_id="intake", storage_id="storage",
                    storage_root=root / phase / "storage", recovery_journal_root=root / phase / "journals",
                    framework_journal=root / phase / "framework.jsonl", preservation_window_s=2,
                    operational_dependents={}, external_dependents=(RuntimeParticipant(kind, identity),
                        RuntimeParticipant("acquisition_node", "unused")), result_window_s=1,
                    controller_claim_account="$G", controller_claim_bucket="AUTHORITY", controller_claim_key="controller",
                    report=lambda text: None)
                with patch.object(ServiceLauncher, "run", capture):
                    pair = await launch_storage_services(**pair_kwargs)
                ensure, subscribe, register = (NatsCommunicationBoundary.ensure_streams,
                    JetStreamContext.subscribe, ServiceMaintenanceInterface.register_ingestor_dependency)
                failed = False

                async def fail_streams(boundary):
                    nonlocal failed
                    if phase == "streams" and boundary.component_type == "controller" and not failed:
                        failed = True
                        raise ConnectionError("startup stream interruption")
                    return await ensure(boundary)

                async def fail_subscription(js, subject, **kwargs):
                    nonlocal failed
                    if phase in {"subscription", "sync-subscription"} and subject == f"messages.command.{kind}.{identity}.*" and not failed:
                        failed = True
                        await subscribe(js, subject, **kwargs)
                        if phase == "sync-subscription":
                            raise ConnectionError("partial SynchronizationManager subscription")
                        raise asyncio.CancelledError()
                    return await subscribe(js, subject, **kwargs)

                async def fail_registration(owner):
                    nonlocal failed
                    if phase == "registration" and owner.participant.component_type == "controller" and not failed:
                        failed = True
                        raise asyncio.CancelledError()
                    return await register(owner)

                with patch.object(ServiceLauncher, "run", capture), patch.object(
                        NatsCommunicationBoundary, "ensure_streams", fail_streams), patch.object(
                        JetStreamContext, "subscribe", fail_subscription), patch.object(
                        ServiceMaintenanceInterface, "register_ingestor_dependency", fail_registration):
                    launcher = await launch_independent_service(role=kind.replace("_", "-"), servers=(server.url,),
                        service_id=identity, ingestor_id="intake", storage_id="storage", synchronization_id="sync",
                        known_nodes=(), preservation_window_s=2, result_window_s=1,
                        controller_claim_account="$G", controller_claim_bucket="AUTHORITY", controller_claim_key="controller",
                        report=lambda text: None)
                self.assertTrue(failed)
                if kind == "controller":
                    self.assertEqual((await kv.get("controller")).value.decode(), launcher.maintenance[0].operational_instance_id)
                self.assertFalse(launcher.exit_ready)
                self.assertTrue(await launcher.stop_locally("operator"))
                self.assertTrue(launcher.exit_ready)
                with self.assertRaises(KeyNotFoundError):
                    await kv.get("controller")
                self.assertTrue(await pair.stop_locally("operator"))
                for boundary in (*launcher.boundaries, *pair.boundaries):
                    await boundary.close()

    async def test_remote_retirement_allows_ingestor_owner_readback_before_exit(self):
        await self.remote_retirement_workflow()

    async def test_remote_retirement_lost_ack_retains_process_until_explicit_completion(self):
        await self.remote_retirement_workflow(lose_reply=True)

    async def test_remote_retirement_preservation_failure_prevents_cleanup(self):
        await self.remote_retirement_workflow(fail_preservation=True)

    async def test_remote_retirement_transport_close_retains_unconfirmed_delivery(self):
        await self.remote_retirement_workflow(interrupt=True)

    async def remote_retirement_workflow(self, *, lose_reply=False, fail_preservation=False, interrupt=False):
        import nats
        from nats.js.api import KeyValueConfig, StorageType
        from lab_sync_acquisition import NatsCommunicationBoundary

        server = await self.enterAsyncContext(restartable_jetstream_server())
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        participant = RuntimeParticipant("synchronization_manager", "sync")

        async def capture(launcher, *, startup):
            await startup()
            for boundary in launcher.boundaries:
                self.addAsyncCleanup(boundary.close)
            return launcher

        with patch.object(ServiceLauncher, "run", capture):
            pair = await launch_storage_services(servers=(server.url,), ingestor_id="intake",
                storage_id="storage", storage_root=root / "storage", recovery_journal_root=root / "journals",
                framework_journal=root / "framework.jsonl", preservation_window_s=2,
                operational_dependents={}, external_dependents=(participant,), result_window_s=.5,
                controller_claim_account="$G", controller_claim_bucket="AUTHORITY", controller_claim_key="controller",
                report=lambda text: None)
        client = await nats.connect(server.url)
        self.addAsyncCleanup(client.close)
        await client.jetstream().create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))
        boundary = NatsCommunicationBoundary("synchronization_manager", "sync", (server.url,))
        await boundary.connect()
        self.addAsyncCleanup(boundary.close)
        owner = SynchronizationManager()
        maintenance = ServiceMaintenanceInterface(owner, participant, ingestor=None, storage_manager=None,
            preservation_window_s=2, close_resources=AsyncMock(return_value=True),
            evidence_publisher=boundary.publish_evidence, framework_communication=NatsControllerCommunication(boundary),
            framework_ingestor=RuntimeParticipant("ingestor", "intake"),
            framework_storage=RuntimeParticipant("storage_manager", "storage"))
        boundary.configure_controller_authority(account="$G", bucket="AUTHORITY", key="controller", timeout_s=2)
        handler = NatsSynchronizationManagerCommunication(boundary, owner)
        await handler.subscribe_commands()
        async def close_handler():
            if boundary.connected:
                await handler.close()
        self.addAsyncCleanup(close_handler)
        launcher = ServiceLauncher((maintenance,), (boundary,), report=lambda text: None)
        await maintenance.register_ingestor_dependency()
        control = Controller(component_id="control")
        control_boundary = NatsCommunicationBoundary("controller", "control", (server.url,))
        await control_boundary.connect()
        self.addAsyncCleanup(control_boundary.close)
        authority = ServiceMaintenanceInterface(control, RuntimeParticipant("controller", "control"),
            ingestor=None, storage_manager=None, preservation_window_s=2, close_resources=AsyncMock(return_value=True))
        await authority.acquire_controller_authority(control_boundary, account="$G", bucket="AUTHORITY",
            key="controller", timeout_s=2)
        requests = NatsControllerCommunication(control_boundary)
        if fail_preservation:
            storage = pair.maintenance[0].storage_manager
            with patch.object(storage, "_write_framework_evidence_archive", side_effect=OSError("disk unavailable")):
                blocked = await requests.request_runtime_command(participant, "stop", None,
                    {"stop_attempt_id": "blocked-stop", "administrator_id": "operator"}, 4)
            self.assertFalse(blocked.success)
            self.assertEqual(blocked.payload["outcome"], "blocked")
            self.assertFalse(maintenance.terminated)
            self.assertEqual(maintenance.close_resources.await_count, 0)
            self.assertFalse(launcher.exit_ready)
            await requests.request_runtime_command(participant, "cancel", None,
                {"stop_attempt_id": "blocked-stop", "administrator_id": "operator"}, 4)
        confirmation_started, allow_reply = asyncio.Event(), asyncio.Event()
        native = pair.boundaries[0].publish_command_result
        original_commands = []

        async def observe(message):
            original_commands.append(message.data)

        observer = await client.subscribe("messages.command.synchronization_manager.sync.stop", cb=observe)
        self.addAsyncCleanup(observer.unsubscribe)

        async def delayed_reply(result, operation):
            if operation == "confirm_dependent_release":
                confirmation_started.set()
                await allow_reply.wait()
                if lose_reply:
                    return
            await native(result, operation)

        with patch.object(pair.boundaries[0], "publish_command_result", delayed_reply):
            try:
                result = await requests.request_runtime_command(participant, "stop", None,
                    {"stop_attempt_id": "remote-stop", "administrator_id": "operator"}, 4, command_id="exact-stop")
                self.assertTrue(result.success, result)
                await asyncio.wait_for(confirmation_started.wait(), 3)
                self.assertFalse(launcher.exit_ready)
                status = await requests.request_runtime_command(participant, "check_readiness", None, {}, 2)
                self.assertTrue(status.payload["operational_retirement_confirmed"])
                self.assertFalse(status.payload["retirement_delivery"]["dependency_release_confirmed"])
                # Redeliver the exact wire command, not a new Stop or new nonce.
                await client.jetstream().publish("messages.command.synchronization_manager.sync.stop", original_commands[0])
                status = await requests.request_runtime_command(participant, "check_readiness", None, {}, 2)
                self.assertTrue(status.success)
                self.assertEqual(maintenance.close_resources.await_count, 1)
                if interrupt:
                    await boundary.close()
                    self.assertTrue(maintenance.terminated)
                    self.assertFalse(launcher.exit_ready)
                    return
            finally:
                allow_reply.set()
            if lose_reply:
                await asyncio.sleep(2.1)  # Let the explicitly configured acknowledgment window expire.
                self.assertFalse(launcher.exit_ready)
                self.assertTrue(maintenance.terminated)
                self.assertEqual(maintenance.close_resources.await_count, 1)

        async def exit_confirmed():
            while not launcher.exit_ready:
                await asyncio.sleep(.01)
        if lose_reply:
            before = pair.maintenance[0].ingestor.compile_framework_runtime_evidence()
            self.assertTrue(await launcher.stop_locally("operator"))
            self.assertEqual(before, pair.maintenance[0].ingestor.compile_framework_runtime_evidence())
        else:
            await asyncio.wait_for(exit_confirmed(), 3)
        self.assertTrue(maintenance.terminated)
        self.assertFalse(pair.maintenance[0].operational_dependents[participant]())
        status = await requests.request_runtime_command(participant, "check_readiness", None, {}, 2)
        self.assertTrue(status.payload["operational_retirement_confirmed"])
        self.assertIsNone(status.payload["maintenance_attempt"])
        self.assertTrue(status.payload["retirement_delivery"]["dependency_release_confirmed"])

    async def test_replayed_framework_history_preserves_registration_across_owner_restart(self):
        import nats
        from nats.js.api import KeyValueConfig, StorageType
        from lab_sync_acquisition import NatsCommunicationBoundary

        server = await self.enterAsyncContext(restartable_jetstream_server())
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        participants = tuple(RuntimeParticipant(kind, identity) for kind, identity in (
            ("synchronization_manager", "sync"), ("acquisition_node", "node"), ("controller", "control")))
        reports = []

        async def capture(launcher, *, startup):
            await startup()
            for boundary in launcher.boundaries:
                self.addAsyncCleanup(boundary.close)
            return launcher

        async def pair():
            with patch.object(ServiceLauncher, "run", capture):
                return await launch_storage_services(servers=(server.url,), ingestor_id="intake",
                    storage_id="storage", storage_root=root / "storage", recovery_journal_root=root / "journals",
                    framework_journal=root / "framework.jsonl", preservation_window_s=3,
                    operational_dependents={}, external_dependents=participants, result_window_s=3,
                    controller_claim_account="$G", controller_claim_bucket="AUTHORITY", controller_claim_key="controller",
                    report=reports.append)

        async def producer(participant):
            owner = (SynchronizationManager() if participant.component_type == "synchronization_manager" else
                Controller(component_id=participant.component_id) if participant.component_type == "controller" else
                AcquisitionNode(device_manager=DeviceManager((ReadyFakeAdapter("device", "fake", (), True),)),
                    node_id=participant.component_id, role="acquisition", synchronization_source_id="sync"))
            boundary = NatsCommunicationBoundary(participant.component_type, participant.component_id, (server.url,))
            await boundary.connect()
            self.addAsyncCleanup(boundary.close)
            interface = ServiceMaintenanceInterface(owner, participant, ingestor=None, storage_manager=None,
                preservation_window_s=3, close_resources=AsyncMock(return_value=True),
                evidence_publisher=boundary.publish_evidence, framework_communication=NatsControllerCommunication(boundary),
                framework_ingestor=RuntimeParticipant("ingestor", "intake"),
                framework_storage=RuntimeParticipant("storage_manager", "storage"))
            if participant.component_type == "controller":
                await interface.acquire_controller_authority(boundary, account="$G", bucket="AUTHORITY",
                    key="controller", timeout_s=3)
                await NatsServiceMaintenanceCommunication(boundary, interface).subscribe_commands()
            elif participant.component_type == "acquisition_node":
                await NatsAcquisitionNodeCommunication(boundary, owner).subscribe_commands()
            else:
                await NatsSynchronizationManagerCommunication(boundary, owner).subscribe_commands()
            await interface.register_ingestor_dependency()
            return interface, boundary

        first = await pair()
        previous, boundary = await producer(participants[0])
        await boundary.close()
        for boundary in first.boundaries:
            await boundary.close()
        second = await pair()
        intake = second.maintenance[0].ingestor
        storage = second.maintenance[0].storage_manager
        evidence = intake.compile_framework_runtime_evidence()["runtime_evidence"][0]
        before = len(intake.compile_framework_runtime_evidence()["ingest_audit"])
        await second.boundaries[0].publish_evidence(evidence)

        async def received():
            while len(intake.compile_framework_runtime_evidence()["ingest_audit"]) <= before:
                await asyncio.sleep(.01)
        await asyncio.wait_for(received(), 3)
        self.assertTrue(any(json.loads(line).get("startup", {}).get("archival_confirmed")
            for line in reports if line.startswith("{")))

        client = await nats.connect(server.url)
        self.addAsyncCleanup(client.close)
        await client.jetstream().create_key_value(KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE))
        for participant in participants:
            interface, _ = await producer(participant)
            await interface.register_ingestor_dependency()
            self.assertFalse(interface.terminated)
            self.assertTrue(second.maintenance[0].operational_dependents[participant]())
        self.assertNotEqual(previous.operational_instance_id,
            second.maintenance[0]._dependent_instances[participants[0]])
        with intake.framework_preservation_guard(storage, verify_journal=True) as archived:
            compiled = intake.compile_framework_runtime_evidence()
            self.assertEqual(archived["runtime_evidence"], [m.to_dict() for m in compiled["runtime_evidence"]])
            self.assertEqual(archived["ingest_audit"], [m.to_dict() for m in compiled["ingest_audit"]])
            self.assertTrue(any(a["reason"] == "already_accepted" for a in archived["ingest_audit"]))


class ExternalDependentMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_framework_verification_is_fresh_after_yield_and_cancellation(self):
        import os
        import re
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "framework.jsonl"
            intake = InMemoryIngestor(PersistentStorageManager(root / "storage"),
                framework_recovery_journal_path=path)
            intake.receive_runtime_evidence(RuntimeEvidenceMessage("first", None, "warning", "source",
                {"value": 1}, True))
            entered = asyncio.Event()

            async def wait_inside_guard():
                with intake.framework_journal_guard():
                    intake.read_framework_write_records()
                    entered.set()
                    await asyncio.Event().wait()

            task = asyncio.create_task(wait_inside_guard())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(intake.read_framework_write_records(), [])
            reused_after_yield = False
            with self.assertRaises((RuntimeError, ValueError)):
                with intake.framework_journal_guard():
                    intake.read_framework_write_records()
                    await asyncio.sleep(0)
                    stamp = path.stat()
                    original = path.read_bytes()
                    damaged = re.sub(rb'("value"\s*:\s*)1', rb'\g<1>2', original, count=1)
                    self.assertNotEqual(original, damaged)
                    path.write_bytes(damaged)
                    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    intake.read_framework_write_records()
                    reused_after_yield = True
            self.assertFalse(reused_after_yield)

    async def test_verified_empty_history_survives_unarchived_unrelated_evidence(self):
        nodes = (RuntimeParticipant("acquisition_node", "unused"),)
        await self.backend(participants=nodes)
        self.assertTrue((await self.status()).payload["ready"])
        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage("unrelated", None, "warning", "other", {}, True))
        self.assertTrue((await self.status()).payload["ready"])
        _, _, launcher, _ = await self.producer("acquisition_node", "unused")
        self.assertFalse((await self.status()).payload["ready"])
        self.assertTrue(await launcher.stop_locally("operator"))
        self.assertTrue((await self.status()).payload["ready"])
        self.assertTrue(await self.pair.stop_locally("operator"))

    async def test_unarchived_restart_does_not_inherit_verified_empty_authority(self):
        nodes = (RuntimeParticipant("acquisition_node", "unused"),)
        await self.backend(participants=nodes)
        self.assertTrue((await self.status()).payload["ready"])
        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage("unarchived", None, "warning", "other", {}, True))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend(participants=nodes)
        result = await self.status()
        self.assertFalse(result.payload["ready"])
        self.assertIn("Operational dependency: acquisition_node/unused", result.payload["blockers"])

    async def test_initial_history_damage_cannot_be_reclassified_as_fresh(self):
        nodes = (RuntimeParticipant("acquisition_node", "unused"),)
        await self.backend(participants=nodes)
        self.assertTrue((await self.status()).payload["ready"])
        journal = self.root / "framework.jsonl"
        before = journal.read_bytes()
        journal.unlink()
        self.assertFalse((await self.status()).payload["ready"])
        # Recreating an empty file is not an authorized recovery result.
        journal.write_bytes(before)
        self.assertFalse((await self.status()).payload["ready"])

    async def test_unused_nodes_survive_ordinary_restart_without_becoming_blockers(self):
        nodes = (RuntimeParticipant("acquisition_node", "unused"),)
        await self.backend(participants=nodes)
        message = RuntimeEvidenceMessage("normal-startup", None, "warning", "intake", {}, True)
        self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)
        self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend(participants=nodes)
        self.assertTrue((await self.status()).payload["ready"])
        self.assertTrue(await self.pair.stop_locally("operator"))

    async def test_detected_missing_history_cannot_become_unused_node_authority(self):
        nodes = (RuntimeParticipant("acquisition_node", "used"), RuntimeParticipant("acquisition_node", "unused"))
        await self.backend(participants=nodes)
        await self.producer("acquisition_node", "used")
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        (self.root / "framework.jsonl").unlink()
        archived = {p: p.read_bytes() for p in (self.root / "storage/framework").rglob("*") if p.is_file()}
        await self.backend(participants=nodes)
        result = await self.status()
        self.assertFalse(result.payload["ready"])
        self.assertIn("Operational dependency: acquisition_node/unused", result.payload["blockers"])
        self.assertEqual(archived, {p: p.read_bytes() for p in archived})

    async def test_registration_and_stop_are_serialized(self):
        nodes = (RuntimeParticipant("acquisition_node", "used"), RuntimeParticipant("acquisition_node", "unused"))
        await self.backend(participants=nodes, result_window_s=2)
        entered, resume = asyncio.Event(), asyncio.Event()
        communication = self.intake_interface._dependent_communication
        original = communication.request_maintenance_readback

        async def paused(*args, **kwargs):
            entered.set()
            await resume.wait()
            return await original(*args, **kwargs)

        with patch.object(communication, "request_maintenance_readback", paused):
            registration = asyncio.create_task(self.producer("acquisition_node", "used", preservation_window_s=2))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                survey = asyncio.create_task(self.intake_interface.execute_command(RuntimeCommandMessage(
                    "racing-stop", None, "stop", "operator", "intake",
                    {"stop_attempt_id": "racing-stop", "administrator_id": "operator"})))
                await asyncio.sleep(0)
                self.assertFalse(survey.done())
                resume.set()
                await registration
                result = await survey
                self.assertEqual(result.payload["outcome"], "blocked")
                self.assertIn("Operational dependency: acquisition_node/used", result.payload["attempt"]["blockers"])
                self.assertNotIn("Operational dependency: acquisition_node/unused", result.payload["attempt"]["blockers"])
            finally:
                resume.set()
                await asyncio.gather(registration, return_exceptions=True)

    async def test_pending_new_node_registration_cannot_restore_an_older_release(self):
        nodes = (RuntimeParticipant("acquisition_node", "used"), RuntimeParticipant("acquisition_node", "unused"))
        await self.backend(participants=nodes)
        _, _, old_launcher, _ = await self.producer("acquisition_node", "used")
        self.assertTrue(await old_launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            if ".command.acquisition_node.used." in subscription.subject:
                await subscription.unsubscribe()
        with patch.object(self.intake_interface._dependent_communication, "request_maintenance_readback",
                          AsyncMock(return_value=None)):
            with self.assertRaisesRegex(RuntimeError, "registration is unconfirmed"):
                await self.producer("acquisition_node", "used")
        result = await self.status()
        self.assertIn("Operational dependency: acquisition_node/used", result.payload["blockers"])
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend(participants=nodes)
        result = await self.status()
        self.assertFalse(result.payload["ready"])
        self.assertIn("Operational dependency: acquisition_node/used", result.payload["blockers"])

    async def test_invalid_archives_and_journals_do_not_authorize_unused_nodes(self):
        nodes = (RuntimeParticipant("acquisition_node", "unused"),)
        original_root = self.root
        for damage in ("missing_archive", "corrupt_archive", "corrupt_journal"):
            with self.subTest(damage=damage):
                self.root = original_root / damage
                self.root.mkdir()
                self.broker = _Broker()
                await self.backend(participants=nodes)
                message = RuntimeEvidenceMessage("startup", None, "warning", "intake", {}, True)
                self.assertTrue(self.intake.receive_runtime_evidence(message).accepted)
                self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())
                for subscription in self.broker.subscriptions:
                    await subscription.unsubscribe()
                archive = next((self.root / "storage/framework/evidence").glob("????-??")) / "runtime_evidence.jsonl"
                if damage == "missing_archive":
                    archive.unlink()
                else:
                    path = self.root / "framework.jsonl" if damage == "corrupt_journal" else archive
                    path.write_text("corrupt completed record\n", encoding="utf-8")
                files = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                if damage == "corrupt_journal":
                    with self.assertRaises(ValueError):
                        await self.backend(participants=nodes)
                else:
                    await self.backend(participants=nodes)
                    result = await self.status()
                    self.assertFalse(result.payload["ready"])
                    self.assertIn("Operational dependency: acquisition_node/unused", result.payload["blockers"])
                    self.assertEqual(files[archive] if archive in files else None,
                                     archive.read_bytes() if archive.exists() else None)

    async def test_configured_unused_nodes_allow_paired_retirement(self):
        nodes = tuple(RuntimeParticipant("acquisition_node", name) for name in ("unused-a", "unused-b"))
        await self.backend(participants=nodes)
        result = await self.status()
        self.assertTrue(result.payload["ready"], result.payload)
        self.assertTrue(await self.pair.stop_locally("operator"))
        self.assertTrue(self.pair.exit_ready)

    async def test_only_registered_node_blocks_until_confirmed_release_and_restart(self):
        nodes = tuple(RuntimeParticipant("acquisition_node", name) for name in ("used", "unused"))
        await self.backend(participants=nodes)
        _, _, launcher, _ = await self.producer("acquisition_node", "used")
        result = await self.status()
        self.assertFalse(result.payload["ready"])
        self.assertIn("Operational dependency: acquisition_node/used", result.payload["blockers"])
        self.assertNotIn("Operational dependency: acquisition_node/unused", result.payload["blockers"])
        self.assertTrue(await launcher.stop_locally("operator"))
        for subscription in self.broker.subscriptions:
            await subscription.unsubscribe()
        await self.backend(participants=nodes)
        result = await self.status()
        self.assertTrue(result.payload["ready"], result.payload)
        self.assertTrue(await self.pair.stop_locally("operator"))

    def setUp(self):
        terminal = patch("lab_sync_acquisition.service_launcher._read_terminal_choice", AsyncMock(return_value=None))
        terminal.start()
        self.addCleanup(terminal.stop)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.broker = _Broker()
        self.dependent = RuntimeParticipant("controller", "control")

    async def backend(self, participants=None, *, result_window_s=0.02):
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
            NatsControllerCommunication(self.intake_boundary), result_window_s)
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
            await acquire_test_controller_authority(self, interface)
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
        release["evidence"].append(RuntimeEvidenceMessage("unrelated-failed-maintenance", None,
            "service_maintenance_evidence", "control", {"checkpoint": "cleanup_confirmed",
                "stop_attempt_id": "previous-attempt", "framework_stop_attempt_id": "previous-framework",
                "target": self.dependent.to_dict(), "requester_id": "previous-operator", "commands": [],
                "outcome": "failed", "failures": ["Previously unconfirmed cleanup"], "actions": []}, True).to_dict())
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
        await self._assert_contradictory_checkpoint_retains_dependency(maintenance=False)

    async def test_contradictory_controller_cleanup_cannot_authorize_release(self):
        await self._assert_contradictory_checkpoint_retains_dependency(maintenance=True)

    async def _assert_contradictory_checkpoint_retains_dependency(self, *, maintenance):
        state, _, sync = await self.controller_release_boundary(prior_sync_stop=True)
        release = state["confirmation"]["confirmation"]["controller_release"]
        for number, message in enumerate(release["evidence"]):
            message["evidence_id"] = f"false-retirement-{number}"
        if maintenance:
            checkpoint = next(m["payload"] for m in release["evidence"]
                if m["payload"].get("checkpoint") == "cleanup_confirmed")
            checkpoint["outcome"] = "completed"
            checkpoint["actions"].append("operational_retirement_confirmed")
        else:
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
                 "checkpoint_future_action", "checkpoint_final_retired", "checkpoint_survey", "checkpoint_attempt",
                 "maintenance_outcome", "maintenance_actions", "maintenance_prepared", "maintenance_termination",
                 "maintenance_blockers", "maintenance_failures", "maintenance_obligations", "maintenance_instance",
                 "maintenance_framework", "maintenance_attempt", "maintenance_duplicate", "maintenance_reordered",
                 "maintenance_missing", "maintenance_unknown_stage", "maintenance_target", "maintenance_requester",
                 "maintenance_command", "maintenance_final_order", "maintenance_evidence_type")
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
                if fault.startswith("maintenance_"):
                    cleanup = next(m for m in release["evidence"] if m["payload"].get("checkpoint") == "cleanup_confirmed")
                    record = cleanup["payload"]
                    changes = {"maintenance_outcome": ("outcome", "completed"),
                        "maintenance_actions": ("actions", ["orderly_resources_closed", "operational_retirement_confirmed"]),
                        "maintenance_prepared": ("prepared", True), "maintenance_termination": ("termination_confirmed", True),
                        "maintenance_blockers": ("blockers", ["Unresolved cleanup"]),
                        "maintenance_failures": ("failures", ["Cleanup failed"]),
                        "maintenance_obligations": ("remaining_obligations", ["Unfinished work"]),
                        "maintenance_instance": ("operational_instance_id", "another-controller-instance"),
                        "maintenance_framework": ("framework_stop_attempt_id", "another-framework"),
                        "maintenance_attempt": ("stop_attempt_id", "another-attempt"),
                        "maintenance_unknown_stage": ("checkpoint", "unconfirmed_cleanup"),
                        "maintenance_target": ("target", sync.to_dict()),
                        "maintenance_requester": ("requester_id", "another-controller")}
                    if fault in changes:
                        key, value = changes[fault]
                        record[key] = value
                    elif fault == "maintenance_duplicate":
                        duplicate = deepcopy(cleanup)
                        duplicate["evidence_id"] = "alternative-cleanup"
                        release["evidence"].insert(release["evidence"].index(cleanup) + 1, duplicate)
                    elif fault == "maintenance_reordered":
                        release["evidence"].remove(cleanup)
                        release["evidence"].append(cleanup)
                    elif fault == "maintenance_missing":
                        release["evidence"].remove(cleanup)
                    elif fault == "maintenance_command":
                        record["commands"][0]["command_id"] = "unrelated-command"
                    elif fault == "maintenance_final_order":
                        final_message = next(m for m in release["evidence"] if m["payload"] is final)
                        release["evidence"].remove(final_message)
                        release["evidence"].insert(release["evidence"].index(cleanup), final_message)
                    elif fault == "maintenance_evidence_type":
                        cleanup["evidence_type"] = "warning"
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
        async with asyncio.timeout(2):
            while not launcher.exit_ready:
                await asyncio.sleep(0.01)
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

    async def test_registration_preserves_framework_intake_after_startup_confirmation(self):
        participant = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((participant,))
        _, interface, _, _ = await self.producer(participant.component_type, participant.component_id)
        original = self.intake.compile_framework_runtime_evidence()["runtime_evidence"][0]
        archived = self.storage.get_framework_preservation_confirmation()
        audit = self.intake.receive_runtime_evidence(original)
        self.assertEqual(audit.reason, "already_accepted")
        with self.assertRaisesRegex(RuntimeError, "Current framework intake"):
            with self.intake.framework_preservation_guard(self.storage):
                pass
        await interface.register_ingestor_dependency()
        with self.intake.framework_preservation_guard(self.storage) as current:
            self.assertEqual(current["runtime_evidence"], archived["runtime_evidence"])
            self.assertEqual(current["ingest_audit"][:-1], archived["ingest_audit"])
            self.assertEqual(current["ingest_audit"][-1], audit.to_dict())
        self.assertTrue(self.intake_interface.operational_dependents[participant]())
        self.assertFalse(interface.terminated)

    async def test_registration_after_late_intake_refuses_failed_preservation_until_explicit_retry(self):
        participant = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((participant,))
        _, interface, _, _ = await self.producer(participant.component_type, participant.component_id)
        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage(
            "late-framework-warning", None, "warning", "sync", {"reason": "retained"}, True))
        with patch.object(self.storage, "_write_framework_evidence_archive", side_effect=OSError("disk failed")):
            with self.assertRaisesRegex(RuntimeError, "registration is unconfirmed"):
                await interface.register_ingestor_dependency()
        self.assertTrue(self.intake_interface.operational_dependents[participant]())
        await interface.register_ingestor_dependency()
        with self.intake.framework_preservation_guard(self.storage) as current:
            self.assertIn("late-framework-warning", [m["evidence_id"] for m in current["runtime_evidence"]])

    async def test_registration_cannot_continue_corrupt_history_after_late_intake(self):
        participant = RuntimeParticipant("synchronization_manager", "sync")
        await self.backend((participant,))
        _, interface, _, _ = await self.producer(participant.component_type, participant.component_id)
        self.intake.receive_runtime_evidence(RuntimeEvidenceMessage(
            "late-framework-warning", None, "warning", "sync", {}, True))
        product = next((self.root / "storage/framework/evidence").glob("????-??")) / "runtime_evidence.jsonl"
        product.write_bytes(b"corrupt\n")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(RuntimeError, "registration is unconfirmed"):
            await interface.register_ingestor_dependency()
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(self.intake_interface.operational_dependents[participant]())

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
