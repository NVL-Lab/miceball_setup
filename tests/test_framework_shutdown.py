"""Progressive administrative shutdown through real handlers and a broker double."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsControllerCommunication,
    NatsIngestorCommunication, NatsServiceMaintenanceCommunication,
    NatsSynchronizationManagerCommunication, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeEvidenceMessage, RuntimeParticipant, ServiceMaintenanceInterface, SessionConfig,
    SynchronizationManager,
)
from tests.test_session_launch import _Boundary, _Broker
from tests.fakes import ReadyFakeAdapter
from tests.nats_server_fixture import acquire_test_controller_authority


class FrameworkShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self, *, shared_ids=False):
        asyncio.get_running_loop().slow_callback_duration = 10
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.broker = _Broker()
        self.storage = PersistentStorageManager(self.root)
        self.ingestor = InMemoryIngestor(self.storage,
            framework_recovery_journal_path=self.root / "framework-journal.jsonl")
        self.sync = SynchronizationManager()
        adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True, declared_capabilities=())
        self.node = AcquisitionNode(device_manager=DeviceManager((adapter,)),
            synchronization_manager=self.sync, ingestor=self.ingestor, node_id="node", role="acquisition")
        self.controller = Controller(ingestor=self.ingestor, storage_manager=self.storage,
            synchronization_manager=self.sync)
        self.services = {"acquisition_node": self.node, "synchronization_manager": self.sync,
                         "ingestor": self.ingestor, "storage_manager": self.storage, "controller": self.controller}
        self.scope = tuple(RuntimeParticipant(kind, "node" if kind == "acquisition_node"
                           or shared_ids and kind == "storage_manager" else kind)
                           for kind in self.services)
        self.interfaces = {}
        self.closes = {}
        self.retirements = []
        self.cleanup_order = []
        for participant in self.scope:
            kind = participant.component_type

            async def close(force, kind=kind):
                self.cleanup_order.append(kind)
                if kind in {"storage_manager", "controller"}:
                    self.assertFalse(self.interfaces["ingestor"].terminated)
                return True

            async def retire(force, kind=kind):
                self.retirements.append(kind)
                if kind == "ingestor":
                    await self.evidence_subscription.unsubscribe()
                if kind in {"storage_manager", "controller"}:
                    self.assertTrue(self.interfaces["ingestor"].terminated)
                return True

            self.closes[kind] = AsyncMock(side_effect=close)
            dependencies = None
            if kind == "ingestor":
                dependencies = {p: (lambda kind=p.component_type: not self.interfaces[kind].terminated)
                    for p in self.scope if p.component_type in {"acquisition_node", "synchronization_manager"}}
            self.interfaces[kind] = ServiceMaintenanceInterface(self.services[kind], participant,
                ingestor=self.ingestor, storage_manager=self.storage, preservation_window_s=0.05,
                close_resources=self.closes[kind], retire_resources=retire,
                operational_dependents=dependencies)
        self.authority = await acquire_test_controller_authority(self, self.interfaces["controller"])
        intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        self.evidence_subscription = await intake.subscribe_evidence(None)
        self.handlers = []
        for participant in self.scope:
            kind = participant.component_type
            boundary = _Boundary(kind, participant.component_id, self.broker)
            if kind == "acquisition_node":
                handler = NatsAcquisitionNodeCommunication(boundary, self.node)
            elif kind == "synchronization_manager":
                handler = NatsSynchronizationManagerCommunication(boundary, self.sync)
            elif kind == "ingestor":
                handler = intake
            else:
                handler = NatsServiceMaintenanceCommunication(boundary, self.interfaces[kind])
            await handler.subscribe_commands()
            self.handlers.append(handler)
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))

    async def shutdown(self, **kwargs):
        return await self.controller.shutdown_framework(self.scope, communication=self.communication,
            stop_attempt_id=kwargs.pop("stop_attempt_id", "framework-attempt"),
            administrator_id="operator", result_window_s=5, **kwargs)

    def archive(self):
        confirmation = self.storage.get_framework_preservation_confirmation()
        self.assertIsNotNone(confirmation)
        return confirmation["runtime_evidence"]

    async def test_informational_survey_leaves_admission_and_cleanup_unchanged(self):
        subscription = await self.communication.subscribe_command_results(None)
        self.addAsyncCleanup(subscription.unsubscribe)
        self.node.reserve("prospective-session")
        result = await self.communication.request_command(self.scope[0], "check_stop_readiness", None, {}, 0.1)
        self.assertTrue(result.success)
        self.assertTrue(result.payload["confirmed"])
        self.assertFalse(result.payload["ready"])
        self.assertIn("Outstanding Session reservation", result.payload["blockers"])
        self.assertEqual(self.interfaces["acquisition_node"].evidence, ())
        self.closes["acquisition_node"].assert_not_awaited()
        self.assertTrue(self.node.release_reservation("prospective-session"))
        self.assertTrue(self.node.reserve("another-session"))

    async def test_normal_progression_prepares_and_archives_before_retirement(self):
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["outcome"], "completed")
        self.assertIsNone(self.authority.controller_claim_owner)
        self.assertEqual(self.retirements, list(self.services))
        self.assertEqual(self.cleanup_order, ["acquisition_node", "synchronization_manager",
            "storage_manager", "controller", "ingestor"])
        for close in self.closes.values():
            close.assert_awaited_once_with(False)
        self.assertEqual(result.details["not_retired"], [])
        self.assertIsNone(self.controller.get_status()["session_id"])
        evidence = self.archive()
        self.assertTrue(all(m["session_id"] is None and m["is_persistent"] for m in evidence))
        checkpoints = [m["payload"] for m in evidence]
        final = next(p for p in checkpoints if p.get("checkpoint") == "final_archival_checkpoint")
        self.assertIsNone(final["outcome"])
        self.assertEqual([p["component_type"] for p in final["not_retired"]],
                         ["ingestor", "storage_manager", "controller"])
        self.assertEqual([p["component_type"] for p in final["retired"]],
                         ["acquisition_node", "synchronization_manager"])
        for kind in ("storage_manager", "controller"):
            prepared = next(p for p in checkpoints if p.get("target", {}).get("component_type") == kind
                            and p.get("checkpoint") == "prepared_ready_for_retirement")
            self.assertIn("orderly_resources_closed", prepared["actions"])
            self.assertIn("preparation_confirmed", prepared["actions"])
            self.assertIsNone(prepared["outcome"])
            self.assertEqual(prepared["framework_stop_attempt_id"], "framework-attempt")
        ingestor_checkpoint = next(p for p in checkpoints if p.get("target", {}).get("component_type") == "ingestor"
                                   and p.get("checkpoint") == "ready_for_retirement")
        self.assertIn("orderly_resources_closed", ingestor_checkpoint["actions"])
        self.assertFalse(any(p.get("outcome") == "completed" and p.get("scope") for p in checkpoints))
        self.assertTrue(all(i.terminated for i in self.interfaces.values()))
        self.assertEqual(len({c["command_id"] for c in result.details["commands"]}), len(result.details["commands"]))
        self.assertFalse(result.details["survey"][2]["ready"])

    async def test_controller_preparation_retains_coordination_but_rejects_unrelated_work(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.closes["controller"].side_effect
        async def close(force):
            self.assertFalse(self.interfaces["controller"].terminated)
            self.assertFalse(self.interfaces["ingestor"].terminated)
            with self.assertRaises(RuntimeError):
                self.controller.create_session(SessionConfig([], str(self.root), None, str(self.root), session_id="new-session"))
            entered.set()
            await resume.wait()
            return await original(force)
        self.closes["controller"].side_effect = close
        task = asyncio.create_task(self.shutdown())
        await asyncio.wait_for(entered.wait(), 10)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.assertFalse(self.interfaces["ingestor"].terminated)
        resume.set()
        result = await task
        self.assertTrue(result.succeeded, result.error)

    async def test_two_nodes_can_retire_in_explicit_order_without_global_dependency_gate(self):
        second = AcquisitionNode(device_manager=DeviceManager((ReadyFakeAdapter(device_id="other-device",
            device_type="fake", required=True, declared_capabilities=()),)),
            synchronization_manager=self.sync, ingestor=self.ingestor, node_id="second", role="acquisition")
        participant = RuntimeParticipant("acquisition_node", "second")
        async def retire(force):
            self.retirements.append("second")
            return True
        interface = ServiceMaintenanceInterface(second, participant, ingestor=self.ingestor,
            storage_manager=self.storage, preservation_window_s=0.05,
            close_resources=AsyncMock(return_value=True), retire_resources=retire)
        await NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "second", self.broker), second).subscribe_commands()
        self.interfaces["ingestor"].operational_dependents[participant] = lambda: not interface.terminated
        self.scope = (*self.scope, participant)
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.retirements, ["acquisition_node", "second", "synchronization_manager",
            "ingestor", "storage_manager", "controller"])

    async def test_framework_attempt_identity_cannot_be_reused_after_failure(self):
        self.sync.start()
        self.assertFalse((await self.shutdown()).succeeded)
        before = len(self.broker.commands)
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertEqual(len(self.broker.commands), before)

    async def test_invalid_survey_response_remains_unconfirmed_but_stops_are_evaluated(self):
        def change(operation, result):
            if operation == "check_stop_readiness" and result["source_id"] == "node":
                result["payload"]["participant"] = {"component_type": "acquisition_node", "component_id": "other"}
            return result
        self.broker.change_result = change
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        self.assertFalse(result.details["survey"][0]["confirmed"])
        self.assertIsNone(result.details["survey"][0]["ready"])

    async def test_scope_is_explicit_and_not_derived_from_session_participants(self):
        for scope in (self.scope[:-1], (*self.scope, self.scope[0]),
                      (*self.scope[:-1], RuntimeParticipant("controller", "other")),
                      (*self.scope, RuntimeParticipant("unknown", "unsupported"))):
            with self.subTest(scope=scope):
                result = await self.controller.shutdown_framework(scope, communication=self.communication,
                    stop_attempt_id="invalid", administrator_id="operator", result_window_s=0.1)
                self.assertFalse(result.succeeded)
                self.assertEqual(self.broker.commands, [])
        self.assertTrue((await self.shutdown()).succeeded)

    async def test_component_ids_shared_across_roles_keep_distinct_attempts(self):
        await self.asyncSetUp(shared_ids=True)
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        attempts = result.details["participant_attempts"]
        shared = [a for a in attempts if a["participant"]["component_id"] == "node"]
        self.assertEqual(len(shared), 2)
        self.assertEqual({a["participant"]["component_type"] for a in shared},
                         {"acquisition_node", "storage_manager"})
        self.assertEqual(len({a["stop_attempt_id"] for a in shared}), 2)

    async def test_readiness_can_change_after_survey_and_requires_fresh_authorization(self):
        def change(command):
            if command["target_id"] == "node" and command["command_type"] == "stop":
                self.node.reserve("late-session")
        self.broker.on_command = change
        authorize = AsyncMock(return_value=True)
        result = await self.shutdown(authorize_kill=authorize)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["survey"][0]["ready"])
        authorize.assert_awaited_once()
        blocked = authorize.await_args.args[1]
        self.assertIn("Outstanding Session reservation", blocked.payload["attempt"]["blockers"])
        self.assertIn("forced_resources_closed", next(r["result"]["payload"]["attempt"]["actions"]
            for r in result.details["results"] if r["result"] and r["result"]["payload"].get("manual_intervention_required") is False
            and r["result"]["payload"].get("outcome") == "completed" and r["result"]["source_id"] == "node"))

    async def test_two_blocked_participants_require_separate_authorizations(self):
        self.node.reserve("session-a")
        self.sync.start()
        authorize = AsyncMock(return_value=True)
        result = await self.shutdown(authorize_kill=authorize)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(authorize.await_count, 2)
        self.assertEqual([call.args[0].component_type for call in authorize.await_args_list],
                         ["acquisition_node", "synchronization_manager"])
        authorizations = result.details["authorizations"]
        self.assertEqual(len({a["stop_attempt_id"] for a in authorizations}), 2)
        self.assertTrue(all(a["authorized"] for a in authorizations))

    async def test_decline_after_partial_shutdown_does_not_restart_services(self):
        self.sync.start()
        authorize = AsyncMock(return_value=False)
        result = await self.shutdown(authorize_kill=authorize)
        self.assertFalse(result.succeeded)
        self.assertTrue(self.interfaces["acquisition_node"].terminated)
        self.assertFalse(self.interfaces["synchronization_manager"].terminated)
        self.assertTrue(self.sync.is_running)
        self.assertEqual(result.details["outcome"], "failed")
        self.assertFalse(result.details["authorizations"][0]["authorized"])
        self.assertIn("coordination_failed", [m["payload"].get("checkpoint") for m in self.archive()])

    async def test_failed_force_cannot_count_as_retirement(self):
        self.node.reserve("session-a")
        self.closes["acquisition_node"].side_effect = None
        self.closes["acquisition_node"].return_value = False
        result = await self.shutdown(authorize_kill=AsyncMock(return_value=True))
        self.assertFalse(result.succeeded)
        self.assertEqual(self.retirements, [])
        self.assertEqual(result.details["retired"], [])
        self.assertFalse(self.interfaces["acquisition_node"].terminated)

    async def test_prepare_is_not_retirement_and_duplicate_does_not_repeat_cleanup(self):
        interface = self.interfaces["storage_manager"]
        command = RuntimeCommandMessage("prepare", None, "prepare_stop", "controller", "storage_manager",
            {"stop_attempt_id": "storage-attempt", "framework_stop_attempt_id": "framework-attempt", "administrator_id": "operator"})
        first = await interface.execute_command(command)
        again = await interface.execute_command(command)
        self.assertEqual(first.to_dict(), again.to_dict())
        self.assertTrue(first.success, first.reason)
        self.assertTrue(first.payload["prepared"])
        self.assertIsNone(first.payload["outcome"])
        self.assertFalse(first.payload["termination_confirmed"])
        self.closes["storage_manager"].assert_awaited_once_with(False)
        self.assertTrue(interface.prepared)
        self.assertEqual(self.retirements, [])
        self.assertTrue(any(m["payload"].get("checkpoint") == "prepared_ready_for_retirement" for m in self.archive()))

    async def test_preparation_failure_retains_actual_failure_and_stops_before_ingestor(self):
        self.closes["storage_manager"].side_effect = RuntimeError("ordinary cleanup failed")
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.retirements, ["acquisition_node", "synchronization_manager"])
        self.assertFalse(self.interfaces["storage_manager"].prepared)
        self.closes["ingestor"].assert_not_awaited()
        self.assertTrue(any("ordinary cleanup failed" in str(m["payload"].get("failures")) for m in self.archive()))

    async def test_blocked_required_preparation_cannot_retire_controller_out_of_order(self):
        created = self.controller.create_session(SessionConfig([], str(self.root), None, str(self.root), session_id="session-a"))
        self.assertTrue(created.succeeded, created.error)
        authorize = AsyncMock(return_value=True)
        result = await self.shutdown(authorize_kill=authorize)
        self.assertFalse(result.succeeded)
        self.assertEqual(self.retirements, ["acquisition_node", "synchronization_manager"])
        self.assertFalse(self.interfaces["ingestor"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.assertTrue(self.interfaces["storage_manager"].prepared)
        authorize.assert_not_awaited()
        self.assertEqual(self.controller.get_status()["session_id"], "session-a")
        self.assertTrue(any(m["payload"].get("checkpoint") == "coordination_failed" for m in self.archive()))

    async def test_preservation_failure_prevents_any_cleanup(self):
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=OSError("archive unavailable")):
            result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.cleanup_order, [])
        self.assertTrue(self.interfaces["controller"].evidence)
        self.assertTrue(self.evidence_subscription.active)

    async def test_preparation_preservation_failure_does_not_cross_archival_boundary(self):
        original = self.storage.write_framework_evidence_archive
        def archive(compilation):
            if any(m.payload.get("checkpoint") == "prepared_ready_for_retirement" for m in compilation["runtime_evidence"]):
                raise OSError("prepared evidence write failed")
            return original(compilation)
        with patch.object(self.storage, "write_framework_evidence_archive", side_effect=archive):
            result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertFalse(self.interfaces["ingestor"].terminated)
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertTrue(self.interfaces["storage_manager"].evidence)

    async def test_missing_survey_is_unconfirmed_not_a_global_gate(self):
        self.broker.drop_results.add(("node", "check_stop_readiness"))
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        self.assertFalse(result.details["survey"][0]["confirmed"])
        self.assertIsNone(result.details["survey"][0]["ready"])

    async def test_missing_final_retirement_confirmation_is_not_success(self):
        self.broker.drop_results.add(("storage_manager", "stop"))
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.assertIn(self.scope[3].to_dict(), result.details["not_retired"])
        self.assertIsNone(result.details["results"][-1]["result"])
        self.assertEqual(result.details["results"][-1]["command_id"], result.details["commands"][-1]["command_id"])
        self.assertIn("storage_manager", result.error)
        self.assertFalse(any(m["payload"].get("scope") and m["payload"].get("outcome") == "completed" for m in self.archive()))

    async def test_current_archive_rewrite_blocks_prepared_retirement(self):
        def rewrite(command):
            if command["target_id"] == "storage_manager" and command["command_type"] == "stop":
                compilation = self.ingestor.compile_framework_runtime_evidence()
                compilation["runtime_evidence"] = []
                compilation["ingest_audit"] = []
                self.storage.write_framework_evidence_archive(compilation)
        self.broker.on_command = rewrite
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.interfaces["ingestor"].terminated)
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)

    async def test_archive_rewrite_during_retirement_callback_prevents_commit(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        async def retire(force):
            entered.set()
            await resume.wait()
            return True
        self.interfaces["storage_manager"].retire_resources = retire
        task = asyncio.create_task(self.shutdown())
        await asyncio.wait_for(entered.wait(), 10)
        compilation = self.ingestor.compile_framework_runtime_evidence()
        compilation["runtime_evidence"] = []
        compilation["ingest_audit"] = []
        self.storage.write_framework_evidence_archive(compilation)
        resume.set()
        result = await task
        self.assertFalse(result.succeeded)
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)

    async def test_earlier_compilation_cannot_authorize_prepared_retirement(self):
        earlier = {}
        def rewrite(command):
            if command["target_id"] == "ingestor" and command["command_type"] == "stop":
                earlier.update(self.ingestor.compile_framework_runtime_evidence())
            if command["target_id"] == "storage_manager" and command["command_type"] == "stop":
                self.storage.write_framework_evidence_archive(earlier)
        self.broker.on_command = rewrite
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.interfaces["ingestor"].terminated)
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)
        archived = self.archive()
        for kind in ("storage_manager", "controller"):
            self.assertTrue(all(m.to_dict() in archived for m in self.interfaces[kind].evidence))
        self.assertFalse(any(m["source_id"] == "ingestor" for m in archived))
        self.assertTrue((self.root / "framework-journal.jsonl").exists())

    async def test_earlier_compilation_during_retirement_cannot_lose_ingestor_cleanup(self):
        earlier = {}
        entered, resume = asyncio.Event(), asyncio.Event()
        def capture(command):
            if command["target_id"] == "ingestor" and command["command_type"] == "stop":
                earlier.update(self.ingestor.compile_framework_runtime_evidence())
        async def retire(force):
            entered.set()
            await resume.wait()
            return True
        self.broker.on_command = capture
        self.interfaces["storage_manager"].retire_resources = retire
        task = asyncio.create_task(self.shutdown())
        try:
            await asyncio.wait_for(entered.wait(), 10)
            complete = self.storage.get_framework_preservation_confirmation()
            self.storage.write_framework_evidence_archive(earlier)
            archived = self.archive()
            omitted = [m for m in complete["runtime_evidence"] if m not in archived]
            self.assertEqual([m["payload"].get("checkpoint") for m in omitted],
                             ["initial", "cleanup_confirmed", "ready_for_retirement"])
            self.assertTrue(all(m["source_id"] == "ingestor" for m in omitted))
        finally:
            resume.set()
            result = await task
        self.assertFalse(result.succeeded)
        self.assertEqual(result.details["outcome"], "failed")
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.assertFalse(result.details["results"][-1]["result"]["payload"]["termination_confirmed"])
        self.closes["storage_manager"].assert_awaited_once_with(False)

    async def test_audit_only_rewrite_cannot_authorize_prepared_retirement(self):
        original = {}
        def rewrite(command):
            if command["target_id"] == "storage_manager" and command["command_type"] == "stop":
                original.update(self.storage.get_framework_preservation_confirmation())
                self.storage.write_framework_evidence_archive({
                    "runtime_evidence": original["runtime_evidence"], "ingest_audit": []})
        self.broker.on_command = rewrite
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        confirmation = self.storage.get_framework_preservation_confirmation()
        self.assertEqual(confirmation["runtime_evidence"], original["runtime_evidence"])
        self.assertGreater(len(original["ingest_audit"]), 0)
        self.assertEqual(confirmation["ingest_audit"], [])
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)

    async def test_audit_only_rewrite_during_retirement_cannot_authorize_completion(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        async def retire(force):
            entered.set()
            await resume.wait()
            return True
        self.interfaces["storage_manager"].retire_resources = retire
        task = asyncio.create_task(self.shutdown())
        try:
            await asyncio.wait_for(entered.wait(), 10)
            complete = self.storage.get_framework_preservation_confirmation()
            self.storage.write_framework_evidence_archive({
                "runtime_evidence": complete["runtime_evidence"], "ingest_audit": []})
        finally:
            resume.set()
            result = await task
        self.assertFalse(result.succeeded)
        self.assertEqual(result.details["outcome"], "failed")
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.closes["storage_manager"].assert_awaited_once_with(False)

    async def test_partial_archive_rewrite_during_retirement_prevents_commit(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        async def retire(force):
            entered.set()
            await resume.wait()
            return True
        self.interfaces["storage_manager"].retire_resources = retire
        task = asyncio.create_task(self.shutdown())
        try:
            await asyncio.wait_for(entered.wait(), 10)
            complete = self.storage.get_framework_preservation_confirmation()
            original = Path.open
            def fail_summary(path, *args, **kwargs):
                if path.name == "compilation_summary.json" and args and args[0] == "w":
                    raise OSError("summary write failed")
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", fail_summary), self.assertRaises(OSError):
                self.storage.write_framework_evidence_archive(complete)
            self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        finally:
            resume.set()
            result = await task
        self.assertFalse(result.succeeded)
        self.assertFalse(self.interfaces["storage_manager"].terminated)
        self.assertFalse(self.interfaces["controller"].terminated)

    async def test_shutdown_preserves_duplicate_rejected_and_nonpersistent_intake_audit(self):
        message = RuntimeEvidenceMessage("nonpersistent", None, "service_maintenance_evidence", "node", {})
        self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
        self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
        rejected = RuntimeEvidenceMessage("rejected", None, "", "node", {})
        self.assertFalse(self.ingestor.receive_runtime_evidence(rejected).accepted)
        intake_audit = self.ingestor.compile_framework_runtime_evidence()["ingest_audit"]
        result = await self.shutdown()
        self.assertTrue(result.succeeded, result.error)
        confirmation = self.storage.get_framework_preservation_confirmation()
        self.assertFalse(any(m["evidence_id"] == "nonpersistent" for m in confirmation["runtime_evidence"]))
        self.assertEqual(confirmation["ingest_audit"][:3], [a.to_dict() for a in intake_audit])

    async def test_authorized_ingestor_retirement_retains_complete_intake_coverage(self):
        self.interfaces["ingestor"].operational_dependents[
            RuntimeParticipant("acquisition_node", "shared-node")] = lambda: True
        authorize = AsyncMock(return_value=True)
        result = await self.shutdown(authorize_kill=authorize)
        self.assertTrue(result.succeeded, result.error)
        authorize.assert_awaited_once()
        self.assertEqual(authorize.await_args.args[0].component_type, "ingestor")
        archived = self.archive()
        self.assertTrue(all(m.to_dict() in archived for m in self.interfaces["ingestor"].evidence))
        self.assertTrue(all(i.terminated for i in self.interfaces.values()))

    async def test_prepared_final_stop_requires_same_participant_and_framework_attempt(self):
        interface = self.interfaces["storage_manager"]
        payload = {"stop_attempt_id": "storage-attempt", "framework_stop_attempt_id": "framework-attempt",
                   "administrator_id": "operator"}
        prepare = RuntimeCommandMessage("prepare", None, "prepare_stop", "controller", "storage_manager", payload)
        self.assertTrue((await interface.execute_command(prepare)).success)
        wrong = RuntimeCommandMessage("wrong", None, "stop", "controller", "storage_manager",
                                      {**payload, "framework_stop_attempt_id": "unrelated"})
        result = await interface.execute_command(wrong)
        self.assertFalse(result.success)
        self.assertTrue(interface.prepared)
        self.assertEqual(self.retirements, [])

    async def test_authorization_wait_is_bounded_and_retains_original_blockers(self):
        self.node.reserve("session-a")
        entered = asyncio.Event()
        async def authorize(participant, result):
            entered.set()
            await asyncio.Event().wait()
        result = await self.controller.shutdown_framework(self.scope, communication=self.communication,
            stop_attempt_id="bounded-authorization", administrator_id="operator", result_window_s=0.5,
            authorize_kill=authorize)
        self.assertTrue(entered.is_set())
        self.assertFalse(result.succeeded)
        self.assertFalse(self.interfaces["acquisition_node"].terminated)
        blocked = next(r["result"] for r in result.details["results"]
                       if r["result"] and r["result"]["payload"].get("outcome") == "blocked")
        self.assertIn("Outstanding Session reservation", blocked["payload"]["attempt"]["blockers"])

    async def test_cancellation_preserves_obligations_and_rejects_overlapping_coordination(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def close(force):
            entered.set()
            await finish.wait()
            return True
        self.closes["acquisition_node"].side_effect = close
        task = asyncio.create_task(self.shutdown())
        await asyncio.wait_for(entered.wait(), 10)
        overlapping = await self.shutdown(stop_attempt_id="other-attempt")
        self.assertFalse(overlapping.succeeded)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.interfaces["acquisition_node"].terminated)
        self.assertFalse(self.interfaces["ingestor"].terminated)
        self.assertTrue(any(m["payload"].get("checkpoint") == "coordination_cancelled" for m in self.archive()))
        finish.set()
        later = await self.shutdown(stop_attempt_id="new-explicit-attempt")
        self.assertTrue(later.succeeded, later.error)

    async def test_invalid_result_correlation_never_confirms_retirement(self):
        def change(operation, result):
            if operation == "stop" and result["source_id"] == "node":
                result["payload"]["attempt"]["framework_stop_attempt_id"] = "another-attempt"
            return result
        self.broker.change_result = change
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertEqual(result.details["retired"], [])
        self.assertFalse(self.interfaces["synchronization_manager"].terminated)

    async def test_unconfirmed_retirement_callback_preserves_copy_and_prepared_state(self):
        self.interfaces["storage_manager"].retire_resources = AsyncMock(return_value=False)
        result = await self.shutdown()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.interfaces["storage_manager"].prepared)
        self.assertFalse(self.interfaces["controller"].terminated)
        self.assertIsNotNone(self.storage.get_framework_preservation_confirmation())
        final_result = result.details["results"][-1]["result"]
        self.assertFalse(final_result["payload"]["termination_confirmed"])
        self.assertEqual(final_result["payload"]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
