"""Controller replacement through public authority and addressed service interfaces."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import nats
from nats.js.api import ConsumerConfig, DeliverPolicy, KeyValueConfig, StorageType
from nats.js.errors import KeyNotFoundError

from lab_sync_acquisition import (Controller, RuntimeParticipant, RuntimeCommandMessage,
    InMemoryIngestor, PersistentStorageManager, ServiceMaintenanceInterface,
    NatsCommunicationBoundary, NatsControllerCommunication, SynchronizationManager,
    AcquisitionNode, DeviceManager, RuntimeEvidenceMessage)
from lab_sync_acquisition.nats_communication import (NatsServiceMaintenanceCommunication,
    NatsIngestorCommunication, NatsStorageManagerCommunication, NatsSynchronizationManagerCommunication,
    NatsAcquisitionNodeCommunication)
from lab_sync_acquisition.service_maintenance_cli import recover_controller_claim
from tests.nats_server_fixture import (NATS_SERVER, restartable_jetstream_server,
                                      CONTROLLER_AUTHORITY_SERVER_CONFIGURATION)


@unittest.skipUnless(NATS_SERVER, "Set LAB_SYNC_NATS_SERVER to an installed nats-server")
class ControllerReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        server = await self.stack.enter_async_context(restartable_jetstream_server(
            server_configuration=CONTROLLER_AUTHORITY_SERVER_CONFIGURATION))
        self.url = server.url.replace("nats://", "nats://demo:demo@")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = PersistentStorageManager(Path(self.temp.name), component_id="storage")
        self.ingestor = InMemoryIngestor(self.storage, component_id="ingestor",
            recovery_journal_root=Path(self.temp.name) / "journals",
            framework_recovery_journal_path=Path(self.temp.name) / "framework.jsonl")
        client = await nats.connect(self.url)
        self.stack.push_async_callback(client.close)
        self.js = client.jetstream()
        self.kv = await self.js.create_key_value(
            KeyValueConfig(bucket="AUTHORITY", storage=StorageType.FILE, history=8))
        self.scope = dict(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
        self.controller, self.owner, self.boundary = await self.new_controller("controller")
        self.revision = await self.owner.acquire_controller_authority(self.boundary, **self.scope)
        self.requests = NatsControllerCommunication(self.boundary)
        self.operator = await self.new_boundary("terminal", "operator")
        self.sync = SynchronizationManager()
        self.peer, self.peer_owner = await self.start_service(self.sync, "synchronization_manager", "sync")

    async def new_boundary(self, kind, identity):
        boundary = NatsCommunicationBoundary(kind, identity, (self.url,))
        await boundary.connect()
        self.stack.push_async_callback(boundary.close)
        await boundary.ensure_streams()
        return boundary

    async def new_controller(self, identity):
        controller = Controller(ingestor=self.ingestor, storage_manager=self.storage, component_id=identity)
        owner = ServiceMaintenanceInterface(controller, RuntimeParticipant("controller", identity),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=1,
            close_resources=AsyncMock(return_value=True))
        boundary = await self.new_boundary("controller", identity)
        async def preserve(message):
            acceptance = self.ingestor.receive_runtime_evidence(message)
            if not acceptance.accepted:
                raise RuntimeError(acceptance.reason)
            await boundary.publish_evidence(message)
        owner.evidence_publisher = preserve
        return controller, owner, boundary

    async def start_service(self, service, kind, identity):
        owner = ServiceMaintenanceInterface(service, RuntimeParticipant(kind, identity),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=1,
            close_resources=AsyncMock(return_value=True))
        boundary = await self.new_boundary(kind, identity)
        async def preserve(message):
            acceptance = self.ingestor.receive_runtime_evidence(message)
            if not acceptance.accepted:
                raise RuntimeError(acceptance.reason)
            await boundary.publish_evidence(message)
        owner.evidence_publisher = preserve
        boundary.configure_controller_authority(**self.scope)
        NatsServiceMaintenanceCommunication(boundary, owner)
        handlers = {"synchronization_manager": NatsSynchronizationManagerCommunication,
                    "ingestor": NatsIngestorCommunication, "storage_manager": NatsStorageManagerCommunication,
                    "acquisition_node": NatsAcquisitionNodeCommunication}
        handler = handlers[kind](boundary, service)
        subscriptions = await handler.subscribe_commands()
        for subscription in subscriptions:
            async def unsubscribe(s=subscription, b=boundary):
                if b.connected:
                    await s.unsubscribe()
            self.stack.push_async_callback(unsubscribe)
        return boundary, owner

    async def wire_request(self, boundary, command, kind):
        """Publish a fully specified envelope, including delayed/replayed issuer context."""
        from lab_sync_acquisition.communication import build_runtime_subject, RuntimeCommandResultMessage
        import json
        event = asyncio.get_running_loop().create_future()
        async def receive(message):
            result = RuntimeCommandResultMessage.from_dict(json.loads(message.data))
            if (result.command_id == command.command_id and result.target_id == command.source_id
                    and not event.done()):
                event.set_result(result)
            await message.ack()
        subscription = await self.js.subscribe(build_runtime_subject(command.session_id, "command_result",
            kind, command.target_id, command.command_type), cb=receive, manual_ack=True,
            config=ConsumerConfig(deliver_policy=DeliverPolicy.NEW))
        try:
            # Public JetStream APIs model an envelope delayed before replacement.
            await self.js.publish(build_runtime_subject(command.session_id, "command", kind,
                command.target_id, command.command_type), json.dumps(command.to_dict()).encode())
            return await asyncio.wait_for(event, 3)
        finally:
            await subscription.unsubscribe()

    async def replacement(self):
        snapshot = await self.operator.inspect_controller_claim(**self.scope)
        await self.operator.clear_controller_claim(snapshot, administrator_id="operator", authorized=True,
            termination_verified=True, termination_evidence="Independent host/process verification fixture", timeout_s=2)
        controller, owner, boundary = await self.new_controller("replacement")
        await owner.acquire_controller_authority(boundary, **self.scope)
        return owner, boundary

    async def test_manual_recovery_requires_authorization_and_exact_snapshot(self):
        snapshot = await self.operator.inspect_controller_claim(**self.scope)
        for changes in ({"authorized": False}, {"termination_verified": False}, {"termination_evidence": ""}):
            with self.assertRaises(ValueError):
                await self.operator.clear_controller_claim(snapshot, **{
                    "administrator_id": "operator", "authorized": True, "termination_verified": True,
                    "termination_evidence": "Independent process inspection", "timeout_s": 2, **changes})
            self.assertEqual((await self.kv.get("controller")).revision, snapshot.revision)
        replacement, _ = await self.replacement()
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await self.operator.clear_controller_claim(snapshot, administrator_id="operator", authorized=True,
                termination_verified=True, termination_evidence="Independent process inspection", timeout_s=2)
        self.assertEqual((await self.kv.get("controller")).value.decode(), replacement.operational_instance_id)

    async def test_operator_inspection_and_conditional_clear_workflow(self):
        reports = []
        settings = dict(servers=(self.url,), **self.scope, report=reports.append)
        self.assertEqual(await recover_controller_claim(**settings), 0)
        import json
        snapshot = json.loads(reports[-1])["claim"]
        self.assertEqual(await recover_controller_claim(**settings, clear=True,
            expected_owner=snapshot["operational_instance_id"], expected_revision=snapshot["revision"],
            administrator_id="operator", authorized=True, termination_verified=True,
            termination_evidence="Independently inspected host confirms process absent"), 0)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")

    async def test_registration_acknowledgment_and_controller_operation(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        acknowledged = await self.boundary.register_controller(peer, result_window_s=2)
        self.assertEqual(acknowledged, {"controller_instance_id": self.owner.operational_instance_id,
            "controller_claim_revision": self.revision, "receiver_instance_id": self.peer_owner.operational_instance_id})
        subscription = await self.requests.subscribe_command_results("session")
        try:
            result = await self.requests.request_command(peer, "initialize_session", "session", {}, 2)
            self.assertTrue(result.success, result.reason)
        finally:
            await subscription.unsubscribe()

    async def test_replacement_rejects_original_registration_and_old_command(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        old = await self.boundary.register_controller(peer, result_window_s=2)
        registration = RuntimeCommandMessage("original-registration", None, "register_controller", "controller", "sync",
            {"request_nonce": "old-registration"}, issuer_type="controller", **old)
        self.assertTrue((await self.wire_request(self.operator, registration, peer.component_type)).success)
        replacement, boundary = await self.replacement()
        await boundary.register_controller(peer, result_window_s=2)
        replay = await self.wire_request(self.operator, registration, peer.component_type)
        self.assertFalse(replay.success)
        delayed = RuntimeCommandMessage("delayed", "session", "initialize_session", "controller", "sync", {},
            issuer_type="controller", **old)
        rejected = await self.wire_request(self.operator, delayed, peer.component_type)
        self.assertFalse(rejected.success)
        self.assertIn("registration", rejected.reason)
        accepted = await self.wire_request(self.operator, replace(delayed, command_id="replacement-command",
            source_id="replacement", **await boundary.register_controller(peer, result_window_s=2)), peer.component_type)
        self.assertTrue(accepted.success, accepted.reason)

    async def test_restart_rejects_old_acknowledgment_then_reconfirms(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        old = await self.boundary.register_controller(peer, result_window_s=2)
        await self.peer.close()
        fresh, fresh_owner = await self.start_service(SynchronizationManager(), peer.component_type, peer.component_id)
        delayed = RuntimeCommandMessage("before-restart", "session", "initialize_session", "controller", "sync", {},
            issuer_type="controller", **old)
        self.assertFalse((await self.wire_request(self.operator, delayed, peer.component_type)).success)
        current = await self.boundary.register_controller(peer, result_window_s=2)
        self.assertNotEqual(current["receiver_instance_id"], old["receiver_instance_id"])
        accepted = await self.wire_request(self.operator, replace(delayed, command_id="after-restart", **current), peer.component_type)
        self.assertTrue(accepted.success, accepted.reason)

    async def test_missing_metadata_does_not_bypass_admission(self):
        command = RuntimeCommandMessage("unregistered", "session", "initialize_session", "controller", "sync", {})
        rejected = await self.wire_request(self.operator, command, "synchronization_manager")
        self.assertFalse(rejected.success)
        self.assertIn("authority", rejected.reason)

    async def test_already_admitted_work_survives_replacement(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        registration = await self.boundary.register_controller(peer, result_window_s=2)
        entered, resume = asyncio.Event(), asyncio.Event()
        async def close_resources(force):
            entered.set()
            await resume.wait()
            return True
        self.peer_owner.close_resources = close_resources
        command = RuntimeCommandMessage("admitted-stop", None, "stop", "controller", "sync",
            {"stop_attempt_id": "admitted-stop", "administrator_id": "operator"},
            issuer_type="controller", **registration)
        task = asyncio.create_task(self.peer_owner.execute_command(command))
        try:
            # Direct public maintenance execution permits deterministic overlap
            # independently of NATS's sequential callbacks on one subscription.
            done, _ = await asyncio.wait((task, asyncio.create_task(entered.wait())), timeout=3,
                                         return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                self.fail(f"Stop was not admitted: {(await task).reason}")
            self.assertTrue(entered.is_set())
            _, boundary = await self.replacement()
            await boundary.register_controller(peer, result_window_s=2)
            resume.set()
            result = await task
            self.assertTrue(result.success, result.reason)
            self.assertEqual(result.target_id, "controller")
            self.assertTrue(self.peer_owner.terminated)
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_administrator_and_service_owned_paths_remain_available(self):
        command = RuntimeCommandMessage("admin", None, "stop", "operator", "sync",
            {"stop_attempt_id": "stop-attempt", "administrator_id": "operator"}, issuer_type="terminal")
        result = await self.wire_request(self.operator, command, "synchronization_manager")
        self.assertTrue(result.success, result.reason)
        self.assertTrue(self.peer_owner.terminated)
        # Preserving service evidence uses the existing Ingestor-specific validator,
        # not Controller authority. Invalid evidence fails for its own reason.
        intake, _ = await self.start_service(self.ingestor, "ingestor", "ingestor")
        command = RuntimeCommandMessage("service", None, "preserve_service_evidence", "sync", "ingestor",
            {"request_nonce": "service-proof"}, issuer_type="synchronization_manager")
        result = await self.wire_request(self.operator, command, "ingestor")
        self.assertFalse(result.success)
        self.assertNotIn("Controller", result.reason)

    async def test_all_receiving_roles_require_authority_and_accept_registered_work(self):
        from tests.fakes import ReadyFakeAdapter
        node = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("device", "fake", (), True)]), synchronization_manager=SynchronizationManager(),
            node_id="node", default_local_storage_root=Path(self.temp.name) / "science")
        services = ((self.ingestor, "ingestor", "ingestor"), (self.storage, "storage_manager", "storage"),
                    (node, "acquisition_node", "node"))
        for service, kind, identity in services:
            with self.subTest(kind=kind):
                boundary, owner = await self.start_service(service, kind, identity)
                participant = owner.participant
                operation = ("reserve" if kind == "acquisition_node" else
                             "check_experiment_capacity" if kind == "storage_manager" else "initialize_session")
                command = RuntimeCommandMessage("missing-" + kind, "session", operation, "controller", identity,
                    {"request_nonce": "operation-" + kind, **({"required_bytes": 1} if kind == "storage_manager" else {})})
                self.assertFalse((await self.wire_request(self.operator, command, kind)).success)
                registration = await self.boundary.register_controller(participant, result_window_s=2)
                command = replace(command, command_id="accepted-" + kind, issuer_type="controller", **registration)
                result = await self.wire_request(self.operator, command, kind)
                self.assertTrue(result.success, result.reason)
                # Logical duplicates retain the original result; recipient context
                # cannot manufacture a new operation or erase original ownership.
                repeated = await self.wire_request(self.operator, command, kind)
                if kind == "storage_manager":
                    # Capacity is current readback, not a cached mutation result.
                    self.assertTrue(repeated.success, repeated.reason)
                    self.assertEqual(repeated.controller_instance_id, result.controller_instance_id)
                else:
                    self.assertEqual(repeated.to_dict(), result.to_dict())

    async def test_wrong_recipient_identity_and_wrong_claim_revision_are_refused(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        current = await self.boundary.register_controller(peer, result_window_s=2)
        command = RuntimeCommandMessage("registration", None, "register_controller", "controller", "sync",
            {"request_nonce": "identity"}, issuer_type="controller", **current)
        for changes in ({"receiver_instance_id": "old-service"}, {"controller_claim_revision": self.revision + 1},
                        {"controller_instance_id": "different-owner"}, {"controller_claim_revision": True},
                        {"source_id": "different-controller"}):
            with self.subTest(changes=changes):
                result = await self.wire_request(self.operator, replace(command, **changes), peer.component_type)
                self.assertFalse(result.success)
        valid = RuntimeCommandMessage("still-current", "session", "initialize_session", "controller", "sync", {},
            issuer_type="controller", **current)
        self.assertTrue((await self.wire_request(self.operator, valid, peer.component_type)).success)

    async def test_registration_storage_failure_retains_current_recognition_and_retry_works(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        current = await self.boundary.register_controller(peer, result_window_s=2)
        with patch.object(self.peer, "inspect_controller_claim", side_effect=TimeoutError("Authority storage unavailable")):
            with self.assertRaises(RuntimeError):
                await self.boundary.register_controller(peer, result_window_s=2)
        self.assertEqual(await self.boundary.register_controller(peer, result_window_s=2), current)

    async def test_interrupted_registration_cannot_restore_old_authority(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        current = await self.boundary.register_controller(peer, result_window_s=2)
        _, replacement = await self.replacement()
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.peer.inspect_controller_claim
        async def paused(**scope):
            entered.set()
            await resume.wait()
            return await original(**scope)
        with patch.object(self.peer, "inspect_controller_claim", paused):
            task = asyncio.create_task(replacement.register_controller(peer, result_window_s=2))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            resume.set()
        fresh = await replacement.register_controller(peer, result_window_s=2)
        self.assertNotEqual(fresh["controller_instance_id"], current["controller_instance_id"])
        old = RuntimeCommandMessage("old-after-cancel", "session", "initialize_session", "controller", "sync", {},
            issuer_type="controller", **current)
        self.assertFalse((await self.wire_request(self.operator, old, peer.component_type)).success)

    async def test_lost_manual_clear_ack_is_unconfirmed_and_cannot_remove_replacement(self):
        from nats.js.client import JetStreamContext
        snapshot = await self.operator.inspect_controller_claim(**self.scope)
        original = JetStreamContext.publish
        async def lost_ack(js, subject, *args, **kwargs):
            ack = await original(js, subject, *args, **kwargs)
            if kwargs.get("headers", {}).get("KV-Operation") == "DEL":
                raise TimeoutError("Committed clear, missing acknowledgment")
            return ack
        with patch.object(JetStreamContext, "publish", lost_ack), self.assertRaises(TimeoutError):
            await self.operator.clear_controller_claim(snapshot, administrator_id="operator", authorized=True,
                termination_verified=True, termination_evidence="Independent process verification", timeout_s=2)
        _, owner, boundary = await self.new_controller("replacement")
        await owner.acquire_controller_authority(boundary, **self.scope)
        with self.assertRaisesRegex(RuntimeError, "changed"):
            await self.operator.clear_controller_claim(snapshot, administrator_id="operator", authorized=True,
                termination_verified=True, termination_evidence="Independent process verification", timeout_s=2)
        self.assertEqual((await self.kv.get("controller")).value.decode(), owner.operational_instance_id)

    async def test_service_evidence_preservation_succeeds_without_controller_registration(self):
        await self.start_service(self.ingestor, "ingestor", "ingestor")
        message = RuntimeEvidenceMessage("service-evidence", None, "service_warning", "sync",
                                         {"message": "Retained service-owned evidence"}, is_persistent=True)
        self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
        result = await self.wire_request(self.operator,
            RuntimeCommandMessage("preserve", None, "preserve_service_evidence", "sync", "ingestor",
                {"evidence": [message.to_dict()], "acceptance_window_s": 1, "request_nonce": "preserve"},
                issuer_type="synchronization_manager"), "ingestor")
        self.assertTrue(result.success, result.reason)

    async def test_unavailable_unrelated_participant_is_not_a_registration_barrier(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        with self.assertRaises(TimeoutError):
            await self.boundary.register_controller(RuntimeParticipant("acquisition_node", "offline"), result_window_s=0.05)
        self.assertEqual((await self.boundary.register_controller(peer, result_window_s=2))["receiver_instance_id"],
                         self.peer_owner.operational_instance_id)

    async def test_coordinated_shutdown_can_retire_its_own_controller(self):
        await self.start_service(self.ingestor, "ingestor", "ingestor")
        await self.start_service(self.storage, "storage_manager", "storage")
        interface = NatsServiceMaintenanceCommunication(self.boundary, self.owner)
        for subscription in await interface.subscribe_commands():
            self.stack.push_async_callback(subscription.unsubscribe)
        result = await self.controller.shutdown_framework(
            (self.owner.participant, self.peer_owner.participant,
             RuntimeParticipant("ingestor", "ingestor"), RuntimeParticipant("storage_manager", "storage")),
            communication=self.requests, stop_attempt_id="framework", administrator_id="operator", result_window_s=3)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(self.owner.terminated)
        # Result delivery precedes the existing retirement-completion callback.
        async with asyncio.timeout(3):
            while self.boundary.controller_claim_owner is not None:
                await asyncio.sleep(0)
        with self.assertRaises(KeyNotFoundError):
            await self.kv.get("controller")

    async def test_registration_id_cannot_be_reused_with_different_current_owner(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        old = await self.boundary.register_controller(peer, result_window_s=2)
        original = RuntimeCommandMessage("shared-id", None, "register_controller", "controller", "sync",
            {"request_nonce": "original"}, issuer_type="controller", **old)
        self.assertTrue((await self.wire_request(self.operator, original, peer.component_type)).success)
        _, replacement = await self.replacement()
        fresh = await replacement.register_controller(peer, result_window_s=2)
        changed = replace(original, source_id="replacement", **fresh)
        result = await self.wire_request(self.operator, changed, peer.component_type)
        self.assertFalse(result.success)
        self.assertIn("Conflicting", result.reason)

    async def test_replacement_with_same_component_id_cannot_accept_old_results(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        subscription = await self.requests.subscribe_command_results("session")
        try:
            first = await self.requests.request_command(peer, "initialize_session", "session", {}, 2,
                                                        command_id="same-command")
            self.assertTrue(first.success, first.reason)
            self.assertEqual(first.controller_instance_id, self.owner.operational_instance_id)
        finally:
            await subscription.unsubscribe()
        snapshot = await self.operator.inspect_controller_claim(**self.scope)
        await self.operator.clear_controller_claim(snapshot, administrator_id="operator", authorized=True,
            termination_verified=True, termination_evidence="Independent host/process verification", timeout_s=2)
        _, replacement, boundary = await self.new_controller("controller")
        await replacement.acquire_controller_authority(boundary, **self.scope)
        requests = NatsControllerCommunication(boundary)
        subscription = await requests.subscribe_command_results("session")
        try:
            result = await requests.request_command(peer, "initialize_session", "session", {}, 2,
                                                    command_id="same-command")
            self.assertFalse(result.success)
            self.assertIn("Conflicting", result.reason)
            self.assertEqual(result.controller_instance_id, replacement.operational_instance_id)
            self.assertTrue(all(r.controller_instance_id == replacement.operational_instance_id
                                for r in requests.command_results))
        finally:
            await subscription.unsubscribe()

    async def test_inconsistent_acknowledgments_do_not_authorize_dispatch(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        original = self.peer.publish_command_result
        for change in (lambda r: replace(r, status="failed", success=True),
                       lambda r: replace(r, payload={**r.payload, "receiver_instance_id": "wrong-service"})):
            async def inconsistent(result, operation):
                if operation == "register_controller":
                    result = change(result)
                await original(result, operation)
            with patch.object(self.peer, "publish_command_result", inconsistent), self.assertRaises(RuntimeError):
                await self.boundary.register_controller(peer, result_window_s=2)
        self.assertEqual((await self.boundary.register_controller(peer, result_window_s=2))["receiver_instance_id"],
                         self.peer_owner.operational_instance_id)

    async def test_stop_quiesces_an_inflight_registration_before_release(self):
        peer = RuntimeParticipant("synchronization_manager", "sync")
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.peer.inspect_controller_claim
        async def paused(**scope):
            entered.set()
            await resume.wait()
            return await original(**scope)
        with patch.object(self.peer, "inspect_controller_claim", paused):
            task = asyncio.create_task(self.boundary.register_controller(peer, result_window_s=3))
            await asyncio.wait_for(entered.wait(), 2)
            stop = RuntimeCommandMessage("stop", None, "stop", "operator", "controller",
                {"stop_attempt_id": "stop", "administrator_id": "operator"})
            result = await self.owner.execute_command(stop)
            self.assertTrue(result.success, result.reason)
            await self.owner.complete_retirement(stop, result)
            self.assertTrue(task.cancelled())
            resume.set()
        _, replacement, boundary = await self.new_controller("replacement")
        await replacement.acquire_controller_authority(boundary, **self.scope)
        self.assertEqual((await boundary.register_controller(peer, result_window_s=2))["controller_instance_id"],
                         replacement.operational_instance_id)
