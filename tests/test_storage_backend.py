"""Controller-mediated Storage workflows with real owners and simulated NATS transport."""

import asyncio
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, InMemoryIngestor, LocalStorageManager,
    NatsAcquisitionNodeCommunication, NatsControllerCommunication, NatsIngestorCommunication,
    NatsStorageManagerCommunication, NatsCommunicationBoundary, PersistentStorageManager, RuntimeParticipant, ServiceMaintenanceInterface, SessionConfig,
)
from lab_sync_acquisition.communication import ExternalControllerRequest, ExternalControllerResult
from tests.test_session_launch import _Boundary, _Broker
from tests.fakes import ReadyFakeAdapter
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


class StorageBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.originals = self.root / "originals"
        self.storage = PersistentStorageManager(self.root / "storage")
        self.ingestor = InMemoryIngestor(storage_manager=self.storage,
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.broker = _Broker()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.controller = Controller()
        self.adapter = ReadyFakeAdapter("camera", "camera", ("frames",), True)
        self.node = AcquisitionNode(device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.originals)
        self.handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", self.broker), self.node)
        await self.handler.subscribe_commands()
        self.intake_handler = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        await self.intake_handler.subscribe_evidence(None)
        await self.intake_handler.subscribe_commands()
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), self.storage).subscribe_commands()
        self.peers = (RuntimeParticipant("acquisition_node", "node"), RuntimeParticipant("ingestor", "ingestor"))
        self.arguments = {"communication": self.communication, "storage_participant": RuntimeParticipant("storage_manager", "storage"),
                          "result_window_s": .1, "experimenter_name": "Alice", "administrator_mode": False}
        self.record("old", "Alice")
        self.manifests = [self.artifact("old", "one", "frames"), self.artifact("old", "one", "timing"),
                          self.artifact("old", "two", "index")]

    def record(self, session_id, owner):
        self.storage.write_initial_session_record(session_id,
            accepted_session_config={"session_id": session_id, "session_parameters": {"experimenter": owner},
                                     "expected_runtime_participants": [p.to_dict() for p in self.peers if p.component_type == "acquisition_node"]},
            lifecycle_evidence=[], readiness_evidence=[], device_readiness_evidence=[], service_readiness_evidence=[],
            final_session_status=None, cleanup_evidence={})

    def artifact(self, sid, eid, product, *, root=None, node_id="node"):
        manager = LocalStorageManager(self.originals if root is None else root, sid, node_id)
        manifest = manager.create_stream(session_id=sid, experiment_id=eid, acquisition_node_id=node_id,
            source_component_id="camera", data_product_id=product, artifact_type=product, schema={})
        manager.append_rows(manifest.storage_id, [{"session_time_s": 1., "experiment_time_s": 0.,
            "acquisition_node_local_time_s": 1., "timestamp_status": "runtime_timestamped", "experiment_id": eid,
            "payload": {"value": 7}}])
        manager.finalize_all()
        return manager.manifests[0]

    async def connect_storage_transport(self, *additional_nodes):
        url = await self.enterAsyncContext(temporary_jetstream_server())
        self.arguments["result_window_s"] = 2.
        for kind, identity, owner, handler in (
            ("controller", "controller", None, None),
            ("ingestor", "ingestor", self.ingestor, NatsIngestorCommunication),
            ("storage_manager", "storage", self.storage, NatsStorageManagerCommunication),
            *(("acquisition_node", node.node_id, node, NatsAcquisitionNodeCommunication)
              for node in (self.node, *additional_nodes)),
        ):
            boundary = NatsCommunicationBoundary(kind, identity, (url,))
            await boundary.connect()
            self.addAsyncCleanup(boundary.close)
            await boundary.ensure_streams()
            if handler is None:
                self.communication = NatsControllerCommunication(boundary)
                self.arguments["communication"] = self.communication
            else:
                receiver = handler(boundary, owner)
                if kind == "ingestor":
                    await receiver.subscribe_evidence(None)
                await receiver.subscribe_commands()

    async def delete(self, operation="delete-one", experiments=None, **changes):
        args = {**self.arguments, "participants": self.peers, "operation_id": operation,
                "experiment_ids": experiments, "confirmed": True, "warning_acknowledged": True, **changes}
        return await self.controller.delete_original_artifacts("old", **args)

    def originals_present(self):
        return [Path(m.local_storage_path).exists() for m in self.manifests]

    async def test_experiment_deletion_before_collection_preserves_metadata_and_other_experiments(self):
        metadata = {p: p.read_bytes() for p in self.originals.rglob("*.json")}
        record = (self.root / "storage/session_old/session_record_initial.json").read_bytes()
        result = await self.delete(experiments=["one"])
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.originals_present(), [False, False, True])
        self.assertEqual(metadata, {p: p.read_bytes() for p in metadata})
        self.assertEqual(record, (self.root / "storage/session_old/session_record_initial.json").read_bytes())
        proof = result.details["nodes"]["node"]["payload"]
        self.assertTrue(proof["local_outcomes_durable"])
        self.assertTrue(proof["acceptance_confirmed"])
        self.assertTrue(proof["archival_confirmed"])
        with self.ingestor.framework_preservation_guard(self.storage) as archived:
            self.assertEqual(archived["runtime_evidence"][0]["evidence_type"], "scientific_original_deletion")
            self.assertIsNone(archived["runtime_evidence"][0]["session_id"])
            self.assertEqual(archived["runtime_evidence"][0]["payload"]["request"]["session_id"], "old")

    async def test_entire_session_and_duplicate_after_owner_restart_do_not_repeat_unlink(self):
        first = await self.delete()
        self.assertTrue(first.succeeded, first.error)
        self.assertEqual(self.originals_present(), [False] * 3)
        with patch.object(Path, "unlink", side_effect=AssertionError("duplicate physical execution")):
            duplicate = await self.delete()
        self.assertTrue(duplicate.succeeded, duplicate.error)
        restarted = AcquisitionNode(device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.originals)
        history = restarted.read_storage_history(session_id="old")
        self.assertEqual(len(history["deletions"]["operations"]), 1)
        self.assertTrue(history["deletions"]["operations"][0]["finished"])
        self.assertEqual(restarted.deletion_evidence(), self.node.deletion_evidence())

    async def test_shared_client_context_and_unknown_ownership(self):
        self.record("bob", "Bob")
        self.record("unknown", None)
        listed = await self.controller.read_storage_sessions(**self.arguments)
        self.assertTrue(listed.succeeded, listed.error)
        self.assertEqual([s["session_id"] for s in listed.details["sessions"]], ["old"])
        admin = await self.controller.read_storage_sessions(**{**self.arguments, "administrator_mode": True})
        self.assertEqual({s["session_id"] for s in admin.details["sessions"]}, {"old", "bob", "unknown"})
        denied = await self.delete(experimenter_name="Bob")
        self.assertFalse(denied.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)
        unknown = await self.controller.read_storage_session("unknown", participants=self.peers, **self.arguments)
        self.assertFalse(unknown.succeeded)

    async def test_historical_readback_isolated_from_active_session(self):
        self.assertTrue(self.node.reserve("new"))
        self.node.initialize_session("new", self.node.declared_devices)
        current = self.node.local_storage_manager
        status = self.node.status()
        result = await self.controller.read_storage_session("old", participants=self.peers, **self.arguments)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(len(result.details["nodes"]["node"]["inventory"]["artifacts"]), 3)
        self.assertTrue((await self.delete()).succeeded)
        self.assertEqual(self.node.status(), status)
        self.assertIs(self.node.local_storage_manager, current)
        self.node.abort_session_initialization("new")
        self.node.release_reservation("new")

    async def test_confirmation_warning_active_scope_and_missing_owner_cannot_authorize(self):
        for changes in ({"confirmed": False}, {"warning_acknowledged": False}, {"administrator_mode": 1},
                        {"experiment_ids": []}, {"experiment_ids": ["absent"]}, {"operation_id": "../escape"}):
            with self.subTest(changes=changes):
                self.assertFalse((await self.delete(**changes)).succeeded)
                self.assertEqual(self.originals_present(), [True] * 3)
        self.assertTrue(self.node.reserve("old"))
        self.assertFalse((await self.delete()).succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)
        self.assertTrue(self.node.release_reservation("old"))

    async def test_lost_result_and_preservation_failure_do_not_repeat_physical_deletion(self):
        self.broker.drop_results.add(("ingestor", "preserve_service_evidence"))
        first = await self.delete()
        self.assertFalse(first.succeeded)
        self.assertEqual(self.originals_present(), [False] * 3)
        self.assertFalse(first.details["nodes"]["node"]["payload"]["archival_confirmed"])
        self.broker.drop_results.clear()
        with patch.object(Path, "unlink", side_effect=AssertionError("must not repeat deletion")):
            second = await self.delete()
        self.assertTrue(second.succeeded, second.error)

    async def test_partial_deletion_requires_linked_retry_and_preserves_earlier_outcomes(self):
        unlink = Path.unlink
        failing = self.manifests[1].local_storage_path
        def interrupted(path, *args, **kwargs):
            if str(path) == failing:
                raise PermissionError("injected permission failure")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupted):
            first = await self.delete()
        self.assertFalse(first.succeeded)
        self.assertEqual(self.originals_present(), [False, True, False])
        unlinked = await self.delete(operation="unlinked")
        self.assertFalse(unlinked.succeeded)
        recovered = await self.delete(operation="retry", retry_of="delete-one")
        self.assertTrue(recovered.succeeded, recovered.error)
        self.assertEqual(self.originals_present(), [False] * 3)
        history = self.node.read_storage_history(session_id="old")["deletions"]["operations"]
        self.assertEqual(len(history), 2)
        self.assertIn("failed", [f["status"] for f in history[0]["files"]])

    async def test_missing_original_and_conflicting_operation_are_not_success(self):
        Path(self.manifests[0].local_storage_path).unlink()
        result = await self.delete()
        self.assertFalse(result.succeeded)
        self.assertIn("missing_deletion_unconfirmed", [f["status"] for f in
            result.details["nodes"]["node"]["payload"]["operation"]["files"]])
        changed = await self.delete(experiments=["one"])
        self.assertFalse(changed.succeeded)

    async def test_ambiguous_originals_are_never_deleted(self):
        other = self.artifact("other", "one", "frames")
        Path(other.local_storage_path).unlink()
        os.link(self.manifests[0].local_storage_path, other.local_storage_path)
        Path(other.local_managed_paths[0]).write_text("broken")
        before = self.originals_present()
        result = await self.delete()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.originals_present(), before)

    async def test_manual_deletion_does_not_require_collection_but_conditional_deletion_does(self):
        denied = await self.delete(policy="after_collection")
        self.assertFalse(denied.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)
        self.assertTrue((await self.delete()).succeeded)

    async def test_historical_owner_ambiguity_is_not_repaired(self):
        path = self.root / "storage/session_old/session_record_final.json"
        initial = json.loads(path.with_name("session_record_initial.json").read_text())
        initial["accepted_session_config"]["session_parameters"]["experimenter"] = "Bob"
        path.write_text(json.dumps(initial))
        denied = await self.delete()
        self.assertFalse(denied.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)

    async def test_interrupted_unlink_is_reconciled_without_automatic_execution(self):
        unlink = Path.unlink
        calls = []
        def interrupted(path, *args, **kwargs):
            calls.append(str(path))
            if len(calls) == 2:
                unlink(path, *args, **kwargs)
                raise asyncio.CancelledError()
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupted):
            with self.assertRaises(asyncio.CancelledError):
                await self.delete()
        history = self.node.read_storage_history(session_id="old")["deletions"]
        self.assertFalse(history["operations"][0]["finished"])
        self.assertIn("missing_deletion_unconfirmed", [r["status"] for r in history["reconciliation"]])
        before = self.originals_present()
        duplicate = await self.delete()
        self.assertFalse(duplicate.succeeded)
        self.assertEqual(self.originals_present(), before)
        self.assertFalse((await self.delete(operation="retry", retry_of="delete-one")).succeeded)

    async def test_intent_write_failure_prevents_all_destructive_work(self):
        with patch("lab_sync_acquisition.local_storage.os.fsync", side_effect=OSError("disk failure")):
            result = await self.delete()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)

    async def test_missing_owner_reply_cannot_authorize_deletion(self):
        self.broker.drop_results.add(("storage", "read_storage_session"))
        result = await self.delete()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)
        self.assertFalse(any(c["command_type"] == "delete_original_artifacts" for c in self.broker.commands))

    async def test_concurrent_duplicate_operations_have_one_physical_execution(self):
        one, two = await asyncio.gather(self.delete(), self.delete())
        self.assertTrue(one.succeeded, one.error)
        self.assertTrue(two.succeeded, two.error)
        self.assertEqual(len(self.node.read_storage_history(session_id="old")["deletions"]["operations"]), 1)

    async def test_unavailable_original_owner_blocks_before_deletion(self):
        self.broker.drop_results.add(("node", "read_storage_history"))
        result = await self.delete()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)

    async def test_unrelated_operation_type_and_stale_nonce_replies_cannot_confirm(self):
        publish = self.broker.publish
        for mutation in ("operation", "type", "nonce"):
            async def changed(subject, data, stream):
                if stream == "LAB_COMMAND_RESULTS" and subject.endswith("read_storage_history"):
                    if mutation == "operation":
                        subject = subject.removesuffix("read_storage_history") + "check_readiness"
                    elif mutation == "type":
                        subject = subject.replace(".acquisition_node.", ".storage_manager.")
                    else:
                        result = json.loads(data)
                        result["payload"]["request_nonce"] = "old-attempt"
                        data = json.dumps(result).encode()
                return await publish(subject, data, stream)
            with self.subTest(mutation=mutation), patch.object(self.broker, "publish", changed):
                self.assertFalse((await self.delete()).succeeded)
                self.assertEqual(self.originals_present(), [True] * 3)

    async def test_retry_cannot_expand_original_targets(self):
        original = Path.unlink
        failing = self.manifests[0].local_storage_path
        def failed(path, *args, **kwargs):
            if str(path) == failing:
                raise PermissionError("injected")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", failed):
            self.assertFalse((await self.delete()).succeeded)
        new = self.artifact("old", "one", "new-original")
        result = await self.delete(operation="retry", retry_of="delete-one")
        self.assertFalse(result.succeeded)
        self.assertTrue(Path(new.local_storage_path).exists())
        self.assertTrue(Path(failing).exists())

    async def test_archived_deletion_history_remains_readable_after_storage_restart(self):
        result = await self.delete()
        self.assertTrue(result.succeeded, result.error)
        restored = PersistentStorageManager(self.root / "storage")
        report = restored.read_storage_session("old")
        self.assertTrue(report["deletion_history_confirmed"])
        self.assertEqual(len(report["deletion_history"]), 1)
        self.assertEqual(report["deletion_history"][0]["payload"]["operation_id"], "delete-one")

    async def test_deployed_maintenance_retains_unconfirmed_deletion_evidence_then_recovers(self):
        intake_boundary = _Boundary("ingestor", "ingestor", self.broker)
        intake_maintenance = ServiceMaintenanceInterface(self.ingestor, RuntimeParticipant("ingestor", "ingestor"),
            ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=.1,
            close_resources=AsyncMock(return_value=True))
        intake_maintenance.configure_external_dependents((self.peers[0],), NatsControllerCommunication(intake_boundary), .1)
        boundary = self.handler._boundary
        maintenance = ServiceMaintenanceInterface(self.node, self.peers[0], ingestor=None, storage_manager=None,
            preservation_window_s=.1, close_resources=AsyncMock(return_value=True),
            evidence_publisher=boundary.publish_evidence, framework_communication=NatsControllerCommunication(boundary),
            framework_ingestor=self.peers[1], framework_storage=self.arguments["storage_participant"])
        await maintenance.register_ingestor_dependency()
        self.broker.drop_results.add(("ingestor", "preserve_service_evidence"))
        result = await self.delete()
        self.assertFalse(result.succeeded)
        evidence = self.node.deletion_evidence()[0]
        self.assertFalse(maintenance.evidence_preserved(evidence))
        self.assertIn("Unpreserved deletion evidence", self.node.maintenance_blockers(None, None))
        self.broker.drop_results.clear()
        self.assertTrue((await self.delete()).succeeded)
        self.assertTrue(maintenance.evidence_preserved(evidence))
        self.assertNotIn("Unpreserved deletion evidence", self.node.maintenance_blockers(None, None))

    async def test_controller_binding_protects_unfinished_closeout_even_without_node_reservation(self):
        created = self.controller.create_session(SessionConfig([], None, None, "unused", session_id="old"))
        self.assertTrue(created.succeeded, created.error)
        before = self.controller.get_status()
        read = await self.controller.read_storage_session("old", participants=self.peers, **self.arguments)
        self.assertTrue(read.succeeded, read.error)
        self.assertEqual(read.details["controller_session"]["state"], "created")
        self.assertFalse((await self.delete()).succeeded)
        self.assertEqual(self.controller.get_status(), before)
        self.assertEqual(self.originals_present(), [True] * 3)

    async def test_damaged_operation_record_never_confirms_or_repeats_deletion(self):
        self.assertTrue((await self.delete()).succeeded)
        path = self.originals / "deletion_operations/delete-one.json"
        record = json.loads(path.read_bytes())
        record["admission"]["local_safety_confirmed"] = False
        path.write_text(json.dumps(record))
        duplicate = await self.delete()
        self.assertFalse(duplicate.succeeded)
        self.assertTrue(self.node.read_storage_history(session_id="old")["deletions"]["issues"])

    async def test_retry_cannot_delete_a_replacement_at_the_original_path(self):
        unlink = Path.unlink
        target = Path(self.manifests[0].local_storage_path)
        def fail_original(path, *args, **kwargs):
            if path == target:
                raise PermissionError("injected")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_original):
            self.assertFalse((await self.delete()).succeeded)
        content = target.read_bytes()
        target.rename(target.with_name("replaced-original.backup"))
        target.write_bytes(content)
        self.assertFalse((await self.delete(operation="retry", retry_of="delete-one")).succeeded)
        self.assertEqual(target.read_bytes(), content)

    async def test_duplicate_requires_current_local_durability_without_rewriting_or_unlinking(self):
        self.assertTrue((await self.delete()).succeeded)
        operation = self.originals / "deletion_operations/delete-one.json"
        before = operation.read_bytes()
        with patch("lab_sync_acquisition.local_storage.os.fsync", side_effect=OSError("durability unavailable")):
            duplicate = await self.delete()
        self.assertFalse(duplicate.succeeded)
        self.assertEqual(operation.read_bytes(), before)
        with patch.object(Path, "unlink", side_effect=AssertionError("must not repeat deletion")):
            self.assertTrue((await self.delete()).succeeded)

    async def test_invalid_optional_deletion_is_rejected_before_collection_dispatch(self):
        result = await self.controller.collect_saved_session_artifacts_remote("old", evidence_id="unused",
            deletion={"policy": "manual"}, participants=self.peers, **self.arguments)
        self.assertFalse(result.succeeded)
        self.assertEqual(self.broker.commands, [])
        self.assertEqual(self.originals_present(), [True] * 3)
        with self.assertRaises(ValueError):
            ExternalControllerRequest("controller", "shared", "invalid", "collect_saved_session_artifacts_remote", "old",
                {"evidence_id": "unused", "experimenter_name": "Alice", "administrator_mode": False,
                 "deletion": {"policy": "manual"}})

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_damaged_duplicate_cannot_omit_failed_timing_outcome_or_archive_success(self):
        await self.connect_storage_transport()
        original = Path.unlink
        remaining = Path(self.manifests[1].local_storage_path)
        def locked(path, *args, **kwargs):
            if path == remaining:
                raise PermissionError("timing original is locked")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", locked):
            self.assertFalse((await self.delete()).succeeded)
        preserved = self.storage.read_storage_session("old")["deletion_history"]
        path = self.originals / "deletion_operations/delete-one.json"
        record = json.loads(path.read_bytes())
        record["files"] = [f for f in record["files"] if f["status"] == "deleted"]
        path.write_text(json.dumps(record))
        with patch.object(Path, "unlink", side_effect=AssertionError("damaged duplicate must not unlink")):
            result = await self.delete()
        self.assertFalse(result.succeeded, result.to_dict())
        self.assertTrue(remaining.exists())
        self.assertTrue(self.node.read_storage_history(session_id="old")["deletions"]["issues"])
        self.assertEqual(self.storage.read_storage_session("old")["deletion_history"], preserved)

    async def test_empty_duplicate_outcomes_are_not_confirmed_after_restart(self):
        with patch.object(Path, "unlink", side_effect=PermissionError("all originals locked")):
            self.assertFalse((await self.delete()).succeeded)
        path = self.originals / "deletion_operations/delete-one.json"
        record = json.loads(path.read_bytes())
        record["files"] = []
        path.write_text(json.dumps(record))
        restarted = AcquisitionNode(device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.originals)
        self.assertTrue(restarted.read_storage_history(session_id="old")["deletions"]["issues"])
        with self.assertRaises((ValueError, RuntimeError)):
            restarted.delete_original_artifacts(operation_id="delete-one", request=record["request"])
        self.assertEqual(self.originals_present(), [True] * 3)

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_disjoint_and_shared_experiments_delete_exact_node_subsets(self):
        other_root = self.root / "other-node"
        other = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("other", "camera", ("frames",), True)]),
            node_id="other-node", synchronization_source_id="sync", default_local_storage_root=other_root)
        self.peers += (RuntimeParticipant("acquisition_node", "other-node"),)
        await self.connect_storage_transport(other)
        for sid, shared in (("disjoint", False), ("overlap", True)):
            with self.subTest(sid=sid):
                self.record(sid, "Alice")
                targets = [self.artifact(sid, "one", "frames"),
                    self.artifact(sid, "two", "index", root=other_root, node_id="other-node")]
                if shared:
                    targets.append(self.artifact(sid, "one", "timing", root=other_root, node_id="other-node"))
                untouched = self.artifact(sid, "three", "frames")
                result = await self.controller.delete_original_artifacts(sid, operation_id=sid, experiment_ids=["one", "two"],
                    confirmed=True, warning_acknowledged=True, participants=self.peers, **self.arguments)
                self.assertTrue(result.succeeded, result.to_dict())
                self.assertFalse(any(Path(m.local_storage_path).exists() for m in targets))
                self.assertTrue(Path(untouched.local_storage_path).exists())
                for node in (self.node, other):
                    saved = node.read_storage_history(session_id=sid)["deletions"]["operations"][0]
                    self.assertEqual(saved["operation_id"], sid)
                    self.assertEqual(saved["request"]["experiment_ids"], ["one", "two"])
                self.assertEqual(len(self.storage.read_storage_session(sid)["deletion_history"]), 2)
                with patch.object(Path, "unlink", side_effect=AssertionError("duplicate must not unlink")):
                    duplicate = await self.controller.delete_original_artifacts(sid, operation_id=sid,
                        experiment_ids=["one", "two"], confirmed=True, warning_acknowledged=True,
                        participants=self.peers, **self.arguments)
                self.assertTrue(duplicate.succeeded, duplicate.to_dict())

    async def test_pending_replacement_remains_uncertain_and_cannot_be_retried(self):
        original = Path.unlink
        target = Path(self.manifests[0].local_storage_path)
        def interrupted(path, *args, **kwargs):
            original(path, *args, **kwargs)
            raise asyncio.CancelledError()
        with patch.object(Path, "unlink", interrupted), self.assertRaises(asyncio.CancelledError):
            await self.delete()
        target.write_bytes(b"replacement, not the deleted original")
        restarted = AcquisitionNode(device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.originals)
        report = restarted.read_storage_history(session_id="old")["deletions"]
        reconciliation = next(r for r in report["reconciliation"] if r["artifact_manifest_id"] == self.manifests[0].artifact_manifest_id)
        self.assertEqual(reconciliation["status"], "unconfirmed")
        self.assertFalse((await self.delete(operation="retry", retry_of="delete-one")).succeeded)
        self.assertEqual(target.read_bytes(), b"replacement, not the deleted original")

    async def test_pending_original_identity_allows_linked_retry_without_repeating_completed_work(self):
        with patch.object(Path, "unlink", side_effect=asyncio.CancelledError()), self.assertRaises(asyncio.CancelledError):
            await self.delete()
        report = self.node.read_storage_history(session_id="old")["deletions"]
        self.assertEqual({r["status"] for r in report["reconciliation"]}, {"not_deleted"})
        self.assertTrue((await self.delete(operation="retry", retry_of="delete-one")).succeeded)
        self.assertEqual(self.originals_present(), [False] * 3)
        records = self.node.read_storage_history(session_id="old")["deletions"]["operations"]
        self.assertFalse(records[0]["finished"])
        self.assertEqual(len(records[1]["files"]), 3)

    async def test_controller_rejects_incomplete_or_contradictory_owner_success(self):
        send = self.broker.publish
        for mutation in ("missing", "duplicate", "operation", "session", "node", "unfinished", "failed", "durability"):
            async def changed(subject, data, stream):
                if stream == "LAB_COMMAND_RESULTS" and subject.endswith("delete_original_artifacts"):
                    envelope = json.loads(data)
                    record = envelope["payload"]["operation"]
                    if mutation == "missing": record["files"].pop()
                    elif mutation == "duplicate": record["files"].append(record["files"][0])
                    elif mutation == "operation": record["operation_id"] = "another-operation"
                    elif mutation == "session": record["request"]["session_id"] = "another-session"
                    elif mutation == "node": record["acquisition_node_id"] = "another-node"
                    elif mutation == "unfinished": record["finished"] = False
                    elif mutation == "failed": record["files"][0].update(status="failed", error="contradictory outcome")
                    else: envelope["payload"]["local_outcomes_durable"] = False
                    data = json.dumps(envelope).encode()
                return await send(subject, data, stream)
            with self.subTest(mutation=mutation), patch.object(self.broker, "publish", changed):
                self.assertFalse((await self.delete()).succeeded)
        self.assertTrue((await self.delete()).succeeded)
        self.assertEqual(self.originals_present(), [False] * 3)

    async def test_incomplete_evidence_is_rejected_before_intake_and_archival(self):
        self.assertTrue((await self.delete()).succeeded)
        message = self.node.deletion_evidence()[0]
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for mutation in ("missing", "empty", "duplicate", "identity", "scope", "admission", "hash"):
            payload = deepcopy(message.payload)
            if mutation == "missing": payload["files"].pop()
            elif mutation == "empty": payload["files"] = []
            elif mutation == "duplicate": payload["files"].append(payload["files"][0])
            elif mutation == "identity": payload["files"][0]["file_identity"] = None
            elif mutation == "scope": payload["request"].pop("artifact_manifests")
            elif mutation == "admission": payload["admission"]["local_safety_confirmed"] = 1
            else: payload["recorded_at"] += 1
            identity = message.evidence_id if mutation == "hash" else "deletion-" + sha256(
                json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
            damaged = replace(message, payload=payload, evidence_id=identity)
            with self.subTest(mutation=mutation):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.ingestor.receive_runtime_evidence(damaged)
                with self.assertRaises((ValueError, RuntimeError)):
                    await self.ingestor.preserve_service_evidence([damaged.to_dict()], "node", .1)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.storage.write_framework_evidence_archive({"runtime_evidence": [damaged], "ingest_audit": []})
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    async def test_damaged_archived_deletion_outcomes_cannot_confirm_history(self):
        self.assertTrue((await self.delete()).succeeded)
        archive = next((self.root / "storage/framework/evidence").glob("*/runtime_evidence.jsonl"))
        rows = [json.loads(line) for line in archive.read_text().splitlines()]
        rows[0]["payload"]["files"].pop()
        archive.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        restored = PersistentStorageManager(self.root / "storage")
        report = restored.read_storage_session("old")
        self.assertFalse(report["deletion_history_confirmed"])
        self.assertTrue(report["issues"])

    async def test_changed_inventory_or_injected_local_scope_cannot_expand_deletion(self):
        send = self.broker.publish
        for mutation in ("missing", "foreign", "expanded"):
            async def changed(subject, data, stream):
                if stream == "LAB_COMMANDS" and subject.endswith("delete_original_artifacts"):
                    command = json.loads(data)
                    if mutation == "missing": command["payload"]["request"]["artifact_manifests"].pop()
                    elif mutation == "foreign":
                        command["payload"]["request"]["artifact_manifests"][0]["acquisition_node_id"] = "foreign"
                    else: self.artifact("old", "one", "unexpected")
                    data = json.dumps(command).encode()
                return await send(subject, data, stream)
            with self.subTest(mutation=mutation), patch.object(self.broker, "publish", changed):
                self.assertFalse((await self.delete()).succeeded)
                self.assertEqual(self.originals_present(), [True] * 3)
        self.assertFalse((await self.delete(experiments=["one", "absent"])).succeeded)
        self.assertEqual(self.originals_present(), [True] * 3)

    async def test_damaged_scientific_content_can_be_manually_deleted_without_touching_metadata(self):
        metadata = {p: p.read_bytes() for p in self.originals.rglob("*.json")}
        Path(self.manifests[0].local_storage_path).write_bytes(b"damaged scientific content")
        self.assertTrue((await self.delete(experiments=["one"])).succeeded)
        self.assertEqual(self.originals_present(), [False, False, True])
        self.assertEqual(metadata, {p: p.read_bytes() for p in metadata})

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_multi_node_partial_deletion_retries_only_originals_that_remain(self):
        other_root = self.root / "other-node"
        other = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("other", "camera", ("frames",), True)]),
            node_id="other-node", synchronization_source_id="sync", default_local_storage_root=other_root)
        self.peers += (RuntimeParticipant("acquisition_node", "other-node"),)
        self.record("partial", "Alice")
        one = self.artifact("partial", "one", "frames")
        two = self.artifact("partial", "two", "timing", root=other_root, node_id="other-node")
        await self.connect_storage_transport(other)
        original = Path.unlink
        calls = []
        def locked(path, *args, **kwargs):
            if str(path) == two.local_storage_path:
                raise PermissionError("second node original locked")
            return original(path, *args, **kwargs)
        arguments = {**self.arguments, "participants": self.peers, "experiment_ids": ["one", "two"],
                     "confirmed": True, "warning_acknowledged": True}
        with patch.object(Path, "unlink", locked):
            first = await self.controller.delete_original_artifacts("partial", operation_id="partial", **arguments)
        self.assertFalse(first.succeeded)
        self.assertFalse(Path(one.local_storage_path).exists())
        self.assertTrue(Path(two.local_storage_path).exists())
        prior = {p: p.read_bytes() for root in (self.originals, other_root)
                 for p in root.glob("deletion_operations/partial.json")}
        def counted(path, *args, **kwargs):
            calls.append(str(path))
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", counted):
            result = await self.controller.delete_original_artifacts("partial", operation_id="partial-retry", retry_of="partial", **arguments)
        self.assertTrue(result.succeeded, result.to_dict())
        self.assertEqual(calls, [two.local_storage_path])
        self.assertEqual(prior, {p: p.read_bytes() for p in prior})
        for node in (self.node, other):
            records = node.read_storage_history(session_id="partial")["deletions"]["operations"]
            self.assertEqual(len(records), 2)
            self.assertEqual(len(records[1]["files"]), 1)

    async def test_interrupted_outcome_write_retains_uncertainty_after_owner_restart(self):
        replace_file = os.replace
        def failed(source, destination):
            if Path(destination).parent == self.originals / "deletion_operations":
                raise OSError("outcome replacement unavailable after unlink")
            return replace_file(source, destination)
        with patch("lab_sync_acquisition.local_storage.os.replace", failed):
            self.assertFalse((await self.delete()).succeeded)
        self.assertEqual(self.originals_present().count(True), 2)
        restarted = AcquisitionNode(device_manager=DeviceManager([self.adapter]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.originals)
        report = restarted.read_storage_history(session_id="old")["deletions"]
        self.assertFalse(report["operations"][0]["finished"])
        self.assertIn("missing_deletion_unconfirmed", [r["status"] for r in report["reconciliation"]])
        before = self.originals_present()
        with patch.object(Path, "unlink", side_effect=AssertionError("duplicate must not retry unlink")):
            self.assertFalse((await self.delete()).succeeded)
        self.assertEqual(self.originals_present(), before)

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_experiment_selection_is_independent_of_remote_path_conventions(self):
        other_root = self.root / "other-node"
        other = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("other", "camera", ("frames",), True)]),
            node_id="other-node", synchronization_source_id="sync", default_local_storage_root=other_root)
        self.peers += (RuntimeParticipant("acquisition_node", "other-node"),)
        await self.connect_storage_transport(other)
        for remote_paths, controller_paths in ((PureWindowsPath, PurePosixPath), (PurePosixPath, PureWindowsPath)):
            for label, selection in (("multiple", ["one", "two"]), ("single", ["one"]), ("whole", None)):
                sid = f"{remote_paths.__name__}-{label}"
                with self.subTest(remote=remote_paths.__name__, selection=selection):
                    self.record(sid, "Alice")
                    manifests = [self.artifact(sid, "one", "frames"), self.artifact(sid, "one", "timing"),
                        self.artifact(sid, "two", "index", root=other_root, node_id="other-node"),
                        self.artifact(sid, "leave", "frames")]
                    with ExitStack() as contexts:
                        contexts.enter_context(patch("lab_sync_acquisition.controller.Path", controller_paths))
                        for node in (self.node, other):
                            read_history = node.read_storage_history
                            def reported_history(*, session_id, read=read_history):
                                report = read(session_id=session_id)
                                for entry in report["inventory"]["artifacts"]:
                                    manifest = entry["manifest"]
                                    base = "Z:/node-originals" if remote_paths is PureWindowsPath else "/node-originals"
                                    entry["manifest_path"] = str(remote_paths(base).joinpath(session_id,
                                        manifest["experiment_id"], manifest["storage_id"], "artifact_manifest.json"))
                                return report
                            contexts.enter_context(patch.object(node, "read_storage_history", reported_history))
                        result = await self.controller.delete_original_artifacts(sid, operation_id=sid,
                            experiment_ids=selection, participants=self.peers, confirmed=True,
                            warning_acknowledged=True, **self.arguments)
                    self.assertTrue(result.succeeded, result.to_dict())
                    for manifest in manifests:
                        selected = selection is None or manifest.experiment_id in selection
                        self.assertEqual(Path(manifest.local_storage_path).exists(), not selected)
                    expected_nodes = {m.acquisition_node_id for m in manifests
                                      if selection is None or m.experiment_id in selection}
                    self.assertEqual(set(result.details["nodes"]), expected_nodes)
                    for node_id, response in result.details["nodes"].items():
                        record = response["payload"]["operation"]
                        self.assertEqual(record["request"]["experiment_ids"], selection)
                        expected = {m.artifact_manifest_id for m in manifests if m.acquisition_node_id == node_id
                                    and (selection is None or m.experiment_id in selection)}
                        self.assertEqual({m["artifact_manifest_id"] for m in record["request"]["artifact_manifests"]}, expected)
                    archived = self.storage.read_storage_session(sid)
                    self.assertTrue(archived["deletion_history_confirmed"])
                    self.assertEqual(len(archived["deletion_history"]), len(expected_nodes))

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_unknown_or_inconsistent_experiment_scope_blocks_every_node(self):
        other_root = self.root / "other-node"
        other = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("other", "camera", ("frames",), True)]),
            node_id="other-node", synchronization_source_id="sync", default_local_storage_root=other_root)
        self.peers += (RuntimeParticipant("acquisition_node", "other-node"),)
        await self.connect_storage_transport(other)
        for index, identity in enumerate((None, "", [], "another-experiment", "missing", "corrupt-json")):
            sid = f"invalid-scope-{index}"
            with self.subTest(identity=identity):
                self.record(sid, "Alice")
                manifests = [self.artifact(sid, "one", "frames"),
                    self.artifact(sid, "one", "timing", root=other_root, node_id="other-node")]
                path = Path(manifests[1].local_managed_paths[-1])
                data = json.loads(path.read_bytes())
                if identity == "missing": data.pop("experiment_id")
                else: data["experiment_id"] = identity
                path.write_text("not JSON" if identity == "corrupt-json" else json.dumps(data))
                before = {p: p.read_bytes() for root in (self.originals, other_root)
                          for p in root.rglob("*") if p.is_file()}
                result = await self.controller.delete_original_artifacts(sid, operation_id=sid,
                    experiment_ids=["one"], participants=self.peers, confirmed=True,
                    warning_acknowledged=True, **self.arguments)
                self.assertFalse(result.succeeded, result.to_dict())
                self.assertTrue(all(Path(m.local_storage_path).exists() for m in manifests))
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                self.assertFalse(any((root / f"deletion_operations/{sid}.json").exists()
                                     for root in (self.originals, other_root)))


class CollectedOriginalDeletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from tests.test_saved_session_selection import SavedSessionSelectionTests
        self.saved = SavedSessionSelectionTests()
        self.saved.addCleanup = self.addCleanup
        self.saved.setUp()
        self.fixture = self.saved.fixture
        self.storage = self.saved.storage
        self.root = self.fixture.root
        self.node = AcquisitionNode(device_manager=DeviceManager([ReadyFakeAdapter("camera", "camera", ("frames",), True)]),
            node_id="node", synchronization_source_id="sync",
            default_local_storage_root=Path(self.fixture.manifest.local_storage_path).parents[3])

    def request(self, policy="after_collection"):
        proof = self.storage.confirm_collected_originals("session", [self.fixture.manifest.to_dict()])
        return {"session_id": "session", "experiment_ids": None, "experimenter_name": None,
                "administrator_mode": True, "confirmed": True, "warning_acknowledged": True,
                "policy": policy, "retry_of": None, "collection_proof": proof}

    async def test_verified_collection_allows_exact_deletion_and_leaves_global_copy_unchanged(self):
        outcome = self.fixture.collect()
        destination = Path(outcome["artifact_collection_result"]["artifact_results"][0]["global_destination"])
        before = destination.read_bytes()
        products = self.fixture.products()
        record = self.node.delete_original_artifacts(operation_id="post-collection", request=self.request())
        self.assertEqual([f["status"] for f in record["files"]], ["deleted"])
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(self.fixture.products(), products)

    async def test_corrupt_global_file_or_unpreserved_evidence_cannot_authorize(self):
        outcome = self.fixture.collect()
        destination = Path(outcome["artifact_collection_result"]["artifact_results"][0]["global_destination"])
        original = Path(self.fixture.manifest.local_storage_path)
        destination.write_bytes(b"corrupt")
        with self.assertRaises(RuntimeError):
            self.request()
        self.assertTrue(original.exists())

    async def test_manual_deletion_evidence_after_archive_closure_does_not_reopen_session(self):
        self.fixture.collect()
        self.storage.close_session_evidence_archive("session")
        directory = self.root / "session_session"
        before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        request = {"session_id": "session", "experiment_ids": None, "experimenter_name": None,
                   "administrator_mode": True, "confirmed": True, "warning_acknowledged": True,
                   "policy": "manual", "retry_of": None}
        record = self.node.delete_original_artifacts(operation_id="manual-after-closure", request=request)
        self.assertEqual(record["files"][0]["status"], "deleted")
        intake = InMemoryIngestor(storage_manager=self.storage,
            framework_recovery_journal_path=self.root / "closed-deletion-evidence.jsonl")
        message = self.node.deletion_evidence()[0]
        self.assertTrue(intake.receive_runtime_evidence(message).accepted)
        proof = await intake.preserve_service_evidence([message.to_dict()], "node", .1)
        self.assertTrue(proof["archival_confirmed"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    async def test_whole_session_collection_optional_deletion_through_controller(self):
        broker = _Broker()
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", broker), self.node)
        await handler.subscribe_commands()
        intake = InMemoryIngestor(storage_manager=self.storage,
            framework_recovery_journal_path=self.root / "deletion-framework.jsonl")
        receiver = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", broker), intake)
        await receiver.subscribe_evidence(None)
        await receiver.subscribe_commands()
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", broker), self.storage).subscribe_commands()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = await Controller().collect_saved_session_artifacts_remote("session", evidence_id="selected-collection",
                communication=communication, storage_participant=RuntimeParticipant("storage_manager", "storage"),
                result_window_s=.2, experimenter_name=None, administrator_mode=True,
                participants=(RuntimeParticipant("acquisition_node", "node"), RuntimeParticipant("ingestor", "ingestor")),
                deletion={"operation_id": "selected-deletion", "experiment_ids": None,
                          "confirmed": True, "warning_acknowledged": True})
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["collection_outcome"]["archival_confirmed"])
        self.assertTrue(result.details["deletion"]["succeeded"])
        self.assertFalse(Path(self.fixture.manifest.local_storage_path).exists())


class StorageExternalModelsTests(unittest.TestCase):
    def test_routing_client_is_not_operator_and_context_is_part_of_request_identity(self):
        params = {"experimenter_name": "Alice", "administrator_mode": False}
        request = ExternalControllerRequest("controller", "shared", "read", "read_storage_sessions", None, params)
        self.assertEqual(ExternalControllerRequest.from_dict(request.to_dict()), request)
        with self.assertRaises(ValueError):
            ExternalControllerRequest("controller", "Alice", "bad", "read_storage_session", "old", {})
        with self.assertRaises(ValueError):
            ExternalControllerRequest("controller", "shared", "bad", "read_storage_sessions", "old", params)
        outcome = {"command": "read_storage_sessions", "succeeded": True, "details": {"sessions": []}}
        response = ExternalControllerResult("controller", "shared", "read", "read_storage_sessions", None,
                                            "succeeded", outcome)
        self.assertEqual(ExternalControllerResult.from_dict(response.to_dict()), response)


if __name__ == "__main__":
    unittest.main()
