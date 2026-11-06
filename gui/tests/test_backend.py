"""Public browser -> web backend -> restricted NATS -> real framework workflows."""
import asyncio
from dataclasses import replace
from pathlib import Path
import socket
import sys
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from miceball_gui.backend import create_gui_app
from lab_sync_acquisition import (ExternalControllerRequest, NatsCommunicationBoundary, NatsControllerCommunication,
    NatsIngestorCommunication, NatsStorageManagerCommunication, NatsAcquisitionNodeCommunication,
    NatsSynchronizationManagerCommunication, ServiceMaintenanceInterface, RuntimeParticipant)
from tests import test_external_controller_lifecycle as lifecycle
from tests.nats_server_fixture import acquire_test_controller_authority, NATS_SERVER


class BackendOfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_and_bounded_uncertainty_without_operational_broker(self):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            broker_port = candidate.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        web = TestClient(TestServer(create_gui_app(servers=[f"nats://127.0.0.1:{broker_port}"],
            controller_id="offline", client_id="gui", origin=origin, timeout_s=.1), port=port))
        await web.start_server()
        self.addAsyncCleanup(web.close)
        response = await web.get("/")
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn('src="connected.js"', page)
        self.assertIn('src="session-view.js"', page)
        ws = await web.ws_connect("/ws", headers={"Origin": origin})
        await ws.receive_json()
        await ws.send_json({"id": "read", "operation": "read_controller_state", "session_id": None, "parameters": {}})
        reply = await asyncio.wait_for(ws.receive_json(), 3)
        self.assertEqual(reply["id"], "read")
        self.assertEqual(reply["status"], "uncertain")
        await ws.close()


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class GUIIntegrationTests(unittest.IsolatedAsyncioTestCase):
    cleanup_node = lifecycle.ExternalLifecycleTests.cleanup_node
    deliver_marker_boundary = lifecycle.ExternalLifecycleTests.deliver_marker_boundary

    async def asyncSetUp(self):
        await lifecycle.ExternalLifecycleTests.asyncSetUp(self)
        authority = await acquire_test_controller_authority(self, self.maintenance)
        await authority.ensure_streams()
        await self.handler.stop_acquisition_execution()
        await self.sync.close()
        self.communication = NatsControllerCommunication(authority)
        self.receiver._communication = self.communication
        for role, identity, owner, handler_type in (
                ("ingestor", "ingestor", self.ingestor, NatsIngestorCommunication),
                ("storage_manager", "storage", self.storage, NatsStorageManagerCommunication),
                ("synchronization_manager", "sync", self.clock, NatsSynchronizationManagerCommunication),
                ("acquisition_node", "node", self.node, NatsAcquisitionNodeCommunication)):
            ServiceMaintenanceInterface(owner, RuntimeParticipant(role, identity), ingestor=self.ingestor,
                storage_manager=self.storage, preservation_window_s=1, close_resources=AsyncMock(return_value=True))
            boundary = NatsCommunicationBoundary(role, identity, authority.servers)
            await boundary.connect()
            self.addAsyncCleanup(boundary.close)
            boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
            handler = handler_type(boundary, owner)
            await handler.subscribe_commands()
            if role == "ingestor":
                await handler.subscribe_evidence(None)
                self.intake = handler
            elif role == "synchronization_manager":
                self.sync = handler
                self.addAsyncCleanup(handler.close)
            elif role == "acquisition_node":
                self.handler = handler
                await handler.start_acquisition_execution()
                self.addAsyncCleanup(handler.stop_acquisition_execution)
        self.receiver._browser_control_required = True
        self.receiver._window = 10
        self.web, self.origin = await self.backend()

    async def backend(self):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        client = TestClient(TestServer(create_gui_app(servers=self.client_boundary.servers,
            controller_id="controller", client_id="tester", origin=origin, timeout_s=2), port=port))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client, origin

    async def browser(self, client=None, origin=None):
        ws = await (client or self.web).ws_connect("/ws", headers={"Origin": origin or self.origin})
        hello = await ws.receive_json()
        self.assertEqual(hello["type"], "connected")
        self.addAsyncCleanup(ws.close)
        await self.message(ws, "read_controller_state")
        return ws, hello["browser_id"]

    async def message(self, ws, operation, parameters=None, sid=None, identifier=None):
        identifier = identifier or uuid4().hex
        await ws.send_json({"id": identifier, "operation": operation, "session_id": sid,
                            "parameters": parameters or {}})
        reply = await asyncio.wait_for(ws.receive_json(), 6)
        self.assertEqual(reply["id"], identifier)
        return reply

    async def completed(self, ws, operation, parameters=None, sid=None, identifier=None):
        reply = await self.message(ws, operation, parameters, sid, identifier)
        if reply.get("result", {}).get("status") != "pending":
            return reply.get("result", reply)
        target = reply["result"]["request_id"]
        for _ in range(100):
            lookup = await self.message(ws, "read_operation_outcome",
                {"target_request_id": target, "instance_id": reply["instance_id"]})
            details = lookup["result"].get("outcome", {}).get("details", {})
            if details.get("result"):
                return details["result"]
            await asyncio.sleep(.01)
        self.fail("Admitted browser operation remained pending")

    async def take(self, ws):
        result = await self.completed(ws, "take_browser_control")
        self.assertEqual(result["status"], "succeeded", result)
        await self.message(ws, "read_controller_state")

    def launch_parameters(self):
        return {"selections": {"node": [self.declaration.to_dict()]},
            "config_parameters": {"storage_location": str(self.root / "records"), "protocol_plan": {},
                "error_evidence_location": str(self.root / "errors"), "synchronization_configuration": lifecycle.configuration()},
            "scientific_outputs": []}

    async def test_browser_session_workflow_and_takeover(self):
        one, first = await self.browser()
        two, second = await self.browser()
        self.assertNotEqual(first, second)
        denied = await self.completed(two, "launch_session", self.launch_parameters())
        self.assertEqual(denied["status"], "rejected")
        await self.take(one)
        launched = await self.completed(one, "launch_session", self.launch_parameters())
        self.assertEqual(launched["status"], "succeeded", launched)
        sid = launched["outcome"]["details"]["session_id"]
        state = (await self.message(two, "read_controller_state"))["result"]["outcome"]["details"]
        self.assertEqual(state["status"]["session_id"], sid)
        state["configuration"]["storage_location"] = "changed"
        await self.take(two)
        denied = await self.completed(one, "start_launched_session", sid=sid)
        self.assertEqual(denied["status"], "rejected")
        started = await self.completed(two, "start_launched_session", sid=sid)
        self.assertEqual(started["status"], "succeeded", started)
        await one.close()
        state = (await self.message(two, "read_controller_state"))["result"]["outcome"]["details"]
        self.assertNotEqual(state["configuration"]["storage_location"], "changed")
        self.assertEqual(state["status"]["session_state"], "running")
        self.assertEqual((await self.completed(two, "normal_stop_session", sid=sid))["status"], "succeeded")
        self.assertEqual((await self.completed(two, "release_session", sid=sid))["status"], "succeeded")
        self.assertEqual((await self.completed(two, "launch_session", self.launch_parameters()))["status"], "succeeded")

    async def test_services_readback_membership_and_maintenance_fencing(self):
        observer, _ = await self.browser()
        target = {"component_type": "acquisition_node", "component_id": "node"}
        state = (await self.completed(observer, "read_controller_state"))["outcome"]["details"]
        self.assertIn(target, state["configured_services"])
        report = await self.completed(observer, "read_service_status", {"participant": target})
        self.assertEqual(report["status"], "succeeded", report)
        self.assertTrue(report["outcome"]["details"]["current"])
        self.assertEqual(report["outcome"]["details"]["report"]["component_id"], "node")
        admin = {"participant": target, "administrator_id": "operator", "authorized": True}
        self.assertEqual((await self.completed(observer, "stop_service", admin))["status"], "rejected")
        await self.take(observer)
        bad = {**admin, "participant": {**target, "component_id": "unconfigured"}}
        self.assertEqual((await self.completed(observer, "stop_service", bad))["status"], "rejected")
        self.assertEqual((await self.completed(observer, "stop_service", {**admin, "authorized": False}))["status"], "rejected")
        unknown = await self.completed(observer, "kill_service", {**admin, "stop_attempt_id": "unknown"})
        self.assertNotEqual(unknown["status"], "succeeded")
        first = await self.completed(observer, "stop_service", admin, identifier="stop-node")
        self.assertEqual(first["status"], "succeeded", first)
        duplicate = await self.completed(observer, "stop_service", admin, identifier="stop-node")
        self.assertEqual(first, duplicate)
        self.assertTrue(first["outcome"]["details"]["termination_confirmed"])

    async def test_service_failed_check_is_unknown_and_retains_configured_membership(self):
        ws, _ = await self.browser()
        target = {"component_type": "acquisition_node", "component_id": "node"}
        good = await self.completed(ws, "read_service_status", {"participant": target})
        self.assertTrue(good["outcome"]["details"]["current"])
        with patch.object(self.receiver._communication, "request_runtime_command", return_value=None):
            unknown = await self.completed(ws, "read_service_status", {"participant": target})
        self.assertFalse(unknown["outcome"]["details"]["current"])
        self.assertIsNone(unknown["outcome"]["details"]["report"])
        snapshot = (await self.completed(ws, "read_controller_state"))["outcome"]["details"]
        self.assertIn(target, snapshot["configured_services"])
        self.assertIn("node", snapshot["configured_nodes"])

    async def test_session_kill_uses_accepted_owner_contract_and_current_binding(self):
        ws, _ = await self.browser()
        await self.take(ws)
        launch = await self.completed(ws, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        self.assertEqual((await self.completed(ws, "start_launched_session", sid=sid))["status"], "succeeded")
        self.assertEqual((await self.completed(ws, "kill_session", {"operator_authorized": False}, sid))["status"], "rejected")
        self.assertEqual((await self.completed(ws, "kill_session", {"operator_authorized": True}, "wrong-session"))["status"], "rejected")
        killed = await self.completed(ws, "kill_session", {"operator_authorized": True}, sid)
        self.assertEqual(killed["status"], "succeeded", killed)
        self.assertEqual(self.controller.get_status()["session_state"], "aborted")
        snapshot = (await self.completed(ws, "read_controller_state"))["outcome"]["details"]
        self.assertTrue(snapshot["closeout"]["cleanup_confirmed"])
        self.assertEqual(snapshot["configuration"]["session_id"], sid)

    async def test_blocked_service_attempt_readback_cancel_and_unknown_reply(self):
        ws, _ = await self.browser()
        await self.take(ws)
        launch = await self.completed(ws, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        admin = {"participant": {"component_type": "acquisition_node", "component_id": "node"},
                 "administrator_id": "operator", "authorized": True}
        blocked = await self.completed(ws, "stop_service", admin)
        self.assertEqual(blocked["status"], "failed", blocked)
        self.assertEqual(blocked["outcome"]["details"]["outcome"], "blocked")
        attempt = blocked["outcome"]["details"]["attempt"]
        report = await self.completed(ws, "read_service_status", {"participant": admin["participant"]})
        self.assertEqual(report["outcome"]["details"]["details"]["maintenance_attempt"]["stop_attempt_id"], attempt["stop_attempt_id"])
        cancelled = await self.completed(ws, "cancel_service", {**admin, "stop_attempt_id": attempt["stop_attempt_id"]})
        self.assertEqual(cancelled["status"], "failed", cancelled)
        self.assertEqual(cancelled["outcome"]["details"]["attempt"]["outcome"], "failed")
        self.assertEqual(self.controller.get_status()["session_id"], sid)
        with patch.object(self.receiver._communication, "request_runtime_command", return_value=None):
            uncertain = await self.completed(ws, "stop_service", admin)
        self.assertEqual(uncertain["status"], "uncertain", uncertain)
        self.assertIsNone(uncertain["outcome"])

    async def test_live_timing_readback_is_session_scoped_and_does_not_assess(self):
        ws, _ = await self.browser()
        await self.take(ws)
        launch = await self.completed(ws, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        before = await self.completed(ws, "read_synchronization_status", sid=sid)
        self.assertFalse(before["outcome"]["details"]["current"])
        self.assertEqual((await self.completed(ws, "start_launched_session", sid=sid))["status"], "succeeded")
        evidence = self.clock.session_timing_evidence(sid, "sync")
        report = await self.completed(ws, "read_synchronization_status", sid=sid)
        self.assertTrue(report["outcome"]["details"]["current"], report)
        self.assertEqual(report["outcome"]["details"]["timing"]["session_id"], sid)
        self.assertEqual(report["outcome"]["details"]["timing"]["timing_evidence"], [m.to_dict() for m in evidence])
        bad = await self.completed(ws, "read_synchronization_status", sid="another-session")
        self.assertEqual(bad["status"], "rejected")

    async def test_framework_shutdown_delegates_exact_configured_scope_without_force(self):
        from lab_sync_acquisition.controller import ControllerCommandResult
        ws, _ = await self.browser()
        await self.take(ws)
        with patch.object(self.controller, "shutdown_framework", new=AsyncMock(
                return_value=ControllerCommandResult("shutdown_framework", False, {"outcome": "failed"}, "blocked"))) as shutdown:
            result = await self.completed(ws, "shutdown_framework", {"administrator_id": "operator", "authorized": True})
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(set(shutdown.call_args.args[0]), {*self.participants, RuntimeParticipant("controller", "controller")})
        self.assertNotIn("authorize_kill", shutdown.call_args.kwargs)
        self.assertEqual(shutdown.call_args.kwargs["administrator_id"], "operator")

    async def test_controller_stop_can_close_its_issuing_receiver_without_self_join(self):
        from lab_sync_acquisition import NatsServiceMaintenanceCommunication
        self.maintenance.ingestor = self.ingestor
        self.maintenance.storage_manager = self.storage
        transport = NatsServiceMaintenanceCommunication(self.communication._boundary, self.maintenance)
        await transport.subscribe_commands()
        async def cleaned(force):
            commands = self.maintenance._attempt["commands"]
            await self.receiver.close(retiring_command_id=commands[-1]["command_id"])
            return True
        self.maintenance.close_resources = cleaned
        ws, _ = await self.browser()
        await self.take(ws)
        reply = await self.message(ws, "stop_service", {"participant": {
            "component_type": "controller", "component_id": "controller"},
            "administrator_id": "operator", "authorized": True})
        self.assertIn(reply["result"]["status"], {"pending", "succeeded"})
        async def retired():
            while not self.maintenance.terminated:
                await asyncio.sleep(.01)
        try:
            await asyncio.wait_for(retired(), 5)
        except TimeoutError:
            self.fail(str([r.to_dict() for r in self.maintenance.command_results]))
        self.assertTrue(any(r.payload.get("termination_confirmed") is True for r in self.maintenance.command_results))

    async def test_receiver_close_still_joins_unrelated_admitted_session_work(self):
        ws, _ = await self.browser()
        await self.take(ws)
        launch = await self.completed(ws, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.controller.start_launched_session
        async def paused(**kwargs):
            entered.set()
            await resume.wait()
            return await original(**kwargs)
        with patch.object(self.controller, "start_launched_session", side_effect=paused):
            reply = await self.message(ws, "start_launched_session", sid=sid)
            self.assertEqual(reply["result"]["status"], "pending")
            await asyncio.wait_for(entered.wait(), 2)
            closing = asyncio.create_task(self.receiver.close(retiring_command_id=reply["result"]["request_id"]))
            try:
                await asyncio.sleep(.05)
                self.assertFalse(closing.done())
                resume.set()
                await asyncio.wait_for(closing, 5)
            finally:
                resume.set()
                await closing
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_framework_shutdown_runs_existing_owners_over_nats(self):
        from lab_sync_acquisition import NatsServiceMaintenanceCommunication
        self.maintenance.ingestor = self.ingestor
        self.maintenance.storage_manager = self.storage
        self.controller._ingestor = self.ingestor
        self.controller._storage_manager = self.storage
        transport = NatsServiceMaintenanceCommunication(self.communication._boundary, self.maintenance)
        await transport.subscribe_commands()
        async def cleaned(force):
            commands = self.maintenance._attempt["commands"]
            await self.receiver.close(retiring_command_id=commands[-1]["command_id"])
            return True
        self.maintenance.close_resources = cleaned
        ws, _ = await self.browser()
        await self.take(ws)
        await self.message(ws, "shutdown_framework", {"administrator_id": "operator", "authorized": True})
        async def completed_shutdown():
            while True:
                result = self.controller.get_status()["last_command"]
                if result is not None and result.command == "shutdown_framework":
                    return result
                await asyncio.sleep(.01)
        result = await asyncio.wait_for(completed_shutdown(), 15)
        self.assertTrue(result.succeeded, result.to_dict())
        for owner in (self.controller, self.node, self.clock, self.ingestor, self.storage):
            self.assertTrue(owner._maintenance.terminated)

    async def test_blocked_service_kill_requires_current_control_and_exact_attempt(self):
        first, _ = await self.browser()
        second, _ = await self.browser()
        await self.take(first)
        launch = await self.completed(first, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        admin = {"participant": {"component_type": "acquisition_node", "component_id": "node"},
                 "administrator_id": "operator", "authorized": True}
        stopped = await self.completed(first, "stop_service", admin)
        self.assertEqual(stopped["outcome"]["details"]["outcome"], "blocked", stopped)
        attempt_id = stopped["outcome"]["details"]["attempt"]["stop_attempt_id"]
        await self.take(second)
        revoked = await self.completed(first, "kill_service", {**admin, "stop_attempt_id": attempt_id})
        self.assertEqual(revoked["status"], "rejected")
        killed = await self.completed(second, "kill_service", {**admin, "stop_attempt_id": attempt_id})
        self.assertEqual(killed["status"], "succeeded", killed)
        self.assertTrue(killed["outcome"]["details"]["termination_confirmed"])
        self.assertEqual(self.controller.get_status()["session_id"], sid)

    async def test_existing_durable_recovery_authorization_is_required_and_scope_is_preserved(self):
        owner = self.storage._maintenance
        sid = "recovery-session"
        evidence = {"accepted_session_config": {"session_id": sid}, "lifecycle_evidence": [],
            "readiness_evidence": [], "device_readiness_evidence": [], "service_readiness_evidence": [],
            "final_session_status": None, "cleanup_evidence": {}}
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("interrupted write")):
            with self.assertRaises(OSError):
                self.storage.write_initial_session_record(sid, **evidence)
        obligation = {"session_id": sid, "record_kind": "initial"}
        authorization = await owner.record_administrator_decision("operator", "resume", {
            "operation": "recover_session_record_write", "obligation": obligation, "command_id": "exact-recovery"})
        parameters = {"participant": {"component_type": "storage_manager", "component_id": "storage"},
            "administrator_id": "operator", "authorized": True, "recovery_command_id": "exact-recovery",
            "authorization_evidence_id": authorization["evidence"]["evidence_id"], "obligation": obligation}
        ws, _ = await self.browser()
        denied = await self.completed(ws, "recover_session_record_write", parameters)
        self.assertEqual(denied["status"], "rejected")
        await self.take(ws)
        readback = await self.completed(ws, "read_service_status", {"participant": parameters["participant"]})
        self.assertIn(authorization["evidence"], readback["outcome"]["details"]["details"]["recovery_authorizations"])
        recovered = await self.completed(ws, "recover_session_record_write", parameters, identifier="recover-once")
        self.assertEqual(recovered["status"], "succeeded", recovered)
        self.assertEqual(recovered["outcome"]["details"]["obligation"], obligation)
        path = Path(recovered["outcome"]["details"]["confirmation"]["path"])
        self.assertEqual(self.storage.read_session_record(path)["accepted_session_config"], evidence["accepted_session_config"])
        before = path.read_bytes(), path.stat().st_mtime_ns
        duplicate = await self.completed(ws, "recover_session_record_write", parameters, identifier="recover-once")
        self.assertEqual(duplicate, recovered)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        await owner.record_administrator_decision("operator", "drop", {"obligation": obligation})
        fresh = await self.completed(ws, "read_service_status", {"participant": parameters["participant"]})
        self.assertNotIn(authorization["evidence"], fresh["outcome"]["details"]["details"]["recovery_authorizations"])
        rejected = await self.completed(ws, "recover_session_record_write", {**parameters,
            "recovery_command_id": "different", "obligation": {"session_id": "wrong", "record_kind": "initial"}})
        self.assertEqual(rejected["status"], "failed", rejected)
        self.assertEqual(rejected["outcome"]["details"]["actual_outcome"], "refused")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    async def test_identity_namespace_origin_and_nonexecuting_lookup(self):
        one, _ = await self.browser()
        two, _ = await self.browser()
        await self.take(one)
        a = await self.message(one, "read_controller_state", identifier="same")
        b = await self.message(two, "read_controller_state", identifier="same")
        self.assertNotEqual(a["result"]["request_id"], b["result"]["request_id"])
        await two.send_json({"id": "forged", "operation": "take_browser_control", "session_id": None,
                            "parameters": {}, "browser_context": {"browser_id": "victim"}})
        self.assertEqual((await two.receive_json())["status"], "rejected")
        unknown = await self.completed(two, "read_operation_outcome",
            {"target_request_id": "absent", "instance_id": self.maintenance.operational_instance_id})
        self.assertEqual(unknown["outcome"]["details"]["status"], "unknown")
        self.assertIsNone(self.controller.get_status()["session_id"])
        raw = ExternalControllerRequest("controller", "tester", "unscoped", "read_controller_state", None, {})
        self.assertEqual((await self.client.request_operation(raw, timeout_s=2)).status, "rejected")
        response = await self.web.get("/", headers={"Host": "untrusted.invalid"})
        self.assertEqual(response.status, 403)
        page = await (await self.web.get("/")).text()
        self.assertIn('src="connected.js"', page)
        self.assertIn('src="protocol-setup.js"', page)
        for module in ("session-view.js", "scientific-views.js", "parameters-view.js", "services-view.js", "storage-view.js", "setup-usability.js"):
            self.assertIn(f'src="{module}"', page)
        inventory = await self.completed(one, "get_node_inventory", {"node_id": "node"})
        self.assertEqual(inventory["status"], "succeeded", inventory)
        self.assertEqual(inventory["outcome"]["details"]["devices"][0]["device_id"], "device")
        unavailable = await self.completed(one, "get_node_inventory", {"node_id": "not-installed"})
        self.assertEqual(unavailable["status"], "rejected")
        for operation in ("delete_original_artifacts", "collect_saved_session_artifacts_remote", "kill"):
            blocked = await self.message(one, operation)
            self.assertEqual(blocked["status"], "rejected")

    async def test_concurrent_takeovers_fence_new_work_and_explicit_view_only_relinquishes(self):
        one, _ = await self.browser()
        two, _ = await self.browser()
        results = await asyncio.gather(self.completed(one, "take_browser_control"), self.completed(two, "take_browser_control"))
        self.assertTrue(all(r["status"] == "succeeded" for r in results))
        snapshots = await asyncio.gather(self.message(one, "read_controller_state"), self.message(two, "read_controller_state"))
        holders = [m["result"]["outcome"]["details"]["control"]["controlling"] for m in snapshots]
        self.assertEqual(sum(holders), 1)
        active, observer = (one, two) if holders[0] else (two, one)
        self.assertEqual((await self.completed(observer, "launch_session", self.launch_parameters()))["status"], "rejected")
        await self.completed(active, "view_only")
        self.assertEqual((await self.completed(active, "launch_session", self.launch_parameters()))["status"], "rejected")
        await self.take(active)
        invalid = self.launch_parameters()
        invalid["config_parameters"] = {}
        failed = await self.completed(active, "launch_session", invalid)
        self.assertEqual(failed["status"], "failed", failed)
        self.assertIsNone(self.controller.get_status()["session_id"])

    async def test_backend_restart_does_not_restore_control_or_replay(self):
        one, _ = await self.browser()
        await self.take(one)
        launched = await self.completed(one, "launch_session", self.launch_parameters())
        sid = launched["outcome"]["details"]["session_id"]
        await self.web.close()
        web, origin = await self.backend()
        two, _ = await self.browser(web, origin)
        state = (await self.message(two, "read_controller_state"))["result"]["outcome"]["details"]
        self.assertEqual(state["status"]["session_id"], sid)
        self.assertFalse(state["control"]["controlling"])
        self.assertEqual((await self.completed(two, "start_launched_session", sid=sid))["status"], "rejected")
        await self.take(two)
        started = await self.completed(two, "start_launched_session", sid=sid)
        self.assertEqual(started["status"], "succeeded", started)

    async def test_admitted_experiment_survives_takeover_while_waiting_for_lifecycle_lock(self):
        one, _ = await self.browser()
        two, _ = await self.browser()
        await self.take(one)
        launched = await self.completed(one, "launch_session", self.launch_parameters())
        sid = launched["outcome"]["details"]["session_id"]
        started = await self.completed(one, "start_launched_session", sid=sid)
        self.assertEqual(started["status"], "succeeded", started)
        parameters = {"experiment_id": "browser-experiment", "configuration": {
            "duration_s": 2., "recording_budgets": {"node": 1000000}, "preservation_budget_bytes": 1000000,
            "participating_devices": {"node": ["device"]}},
            "scientific_outputs": [dict(source_device_id="device", source_node_id="node", data_product_id="frames")]}
        async with self.controller._experiment_operation_lock:
            pending = await self.message(one, "start_launched_experiment", parameters, sid)
            self.assertEqual(pending["result"]["status"], "pending")
            await self.take(two)
            await one.close()
        for _ in range(100):
            result = await self.completed(two, "read_operation_outcome", {
                "target_request_id": pending["result"]["request_id"], "instance_id": pending["instance_id"]})
            if result["outcome"]["details"]["result"]:
                break
            await asyncio.sleep(.05)
        self.assertEqual(result["outcome"]["details"]["status"], "succeeded", result)
        stopped = await self.completed(two, "stop_launched_experiment", {"experiment_id": "browser-experiment"}, sid)
        self.assertEqual(stopped["status"], "succeeded", stopped)
        self.assertTrue(all(Path(m.local_storage_path).exists() for m in self.node.local_storage_manager.manifests))
        duplicate = await self.completed(two, "stop_launched_experiment", {"experiment_id": "browser-experiment"}, sid, "duplicate")
        repeated = await self.completed(two, "stop_launched_experiment", {"experiment_id": "browser-experiment"}, sid, "duplicate")
        self.assertEqual(duplicate, repeated)
        conflict = await self.completed(two, "stop_launched_experiment", {"experiment_id": "different"}, sid, "duplicate")
        self.assertEqual(conflict["status"], "rejected")

    async def test_lost_reply_is_uncertain_and_lookup_does_not_repeat_launch(self):
        one, _ = await self.browser()
        await self.take(one)
        native = self.service_boundary._require_client().publish
        dropped = False
        async def publish(subject, *args, **kwargs):
            nonlocal dropped
            if not dropped and subject.startswith("_INBOX."):
                dropped = True
                return
            return await native(subject, *args, **kwargs)
        with patch.object(self.service_boundary._require_client(), "publish", side_effect=publish), \
                patch.object(self.controller, "launch_session", wraps=self.controller.launch_session) as launch:
            result = await self.message(one, "launch_session", self.launch_parameters())
            self.assertEqual(result["result"]["status"], "uncertain", result)
            self.assertTrue(dropped)
            for _ in range(100):
                lookup = await self.completed(one, "read_operation_outcome", {
                    "target_request_id": result["result"]["request_id"], "instance_id": result["instance_id"]})
                if lookup["outcome"]["details"]["status"] != "pending":
                    break
                await asyncio.sleep(.05)
            self.assertEqual(lookup["outcome"]["details"]["status"], "succeeded", lookup)
            self.assertEqual(launch.await_count, 1)

    async def test_preservation_failure_blocks_release_and_explicit_retry_reuses_cleanup(self):
        ws, _ = await self.browser()
        await self.take(ws)
        launched = await self.completed(ws, "launch_session", self.launch_parameters())
        sid = launched["outcome"]["details"]["session_id"]
        self.assertEqual((await self.completed(ws, "start_launched_session", sid=sid))["status"], "succeeded")
        started = await self.completed(ws, "start_launched_experiment", {"experiment_id": "preservation",
            "configuration": {"duration_s": 10., "recording_budgets": {"node": 1000000},
                "preservation_budget_bytes": 1000000, "participating_devices": {"node": ["device"]}},
            "scientific_outputs": [dict(source_device_id="device", source_node_id="node", data_product_id="frames")]}, sid)
        self.assertEqual(started["status"], "succeeded", started)
        for _ in range(100):
            if self.node.status()["iteration_count"]:
                break
            await asyncio.sleep(.01)
        self.assertGreater(self.node.status()["iteration_count"], 0)
        with patch.object(self.node, "stop_runtime", wraps=self.node.stop_runtime) as cleanup:
            with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
                failed = await self.completed(ws, "normal_stop_session", sid=sid)
            self.assertEqual(failed["status"], "failed", failed)
            self.assertEqual((await self.completed(ws, "release_session", sid=sid))["status"], "failed")
            completed_cleanup = cleanup.call_count
            self.assertGreater(completed_cleanup, 0)
            recovered = await self.completed(ws, "normal_stop_session", sid=sid)
            self.assertEqual(recovered["status"], "succeeded", recovered)
            self.assertEqual(cleanup.call_count, completed_cleanup)
        self.assertEqual((await self.completed(ws, "release_session", sid=sid))["status"], "succeeded")

    async def test_controller_reconstruction_reports_new_lifetime_without_session_recovery(self):
        from lab_sync_acquisition import Controller, NatsExternalSessionLaunchReceiver
        one, _ = await self.browser()
        await self.take(one)
        launch = await self.completed(one, "launch_session", self.launch_parameters())
        sid = launch["outcome"]["details"]["session_id"]
        await self.receiver.close()
        owner = Controller()
        maintenance = ServiceMaintenanceInterface(owner, RuntimeParticipant("controller", "controller"),
            ingestor=None, storage_manager=None, preservation_window_s=1, close_resources=AsyncMock(return_value=True))
        authority = await acquire_test_controller_authority(self, maintenance)
        receiver = NatsExternalSessionLaunchReceiver(self.service_boundary, owner,
            communication=NatsControllerCommunication(authority), maintenance=maintenance,
            client_id="tester", participants=self.participants, result_window_s=10, browser_control_required=True)
        await receiver.start()
        self.addAsyncCleanup(receiver.close)
        state = (await self.message(one, "read_controller_state"))["result"]["outcome"]["details"]
        self.assertNotEqual(state["instance_id"], self.maintenance.operational_instance_id)
        self.assertIsNone(state["status"]["session_id"])
        self.assertFalse(state["control"]["controlling"])
        lookup = await self.completed(one, "read_operation_outcome", {
            "target_request_id": launch["request_id"], "instance_id": self.maintenance.operational_instance_id})
        self.assertEqual(lookup["outcome"]["details"]["status"], "unknown")
        path = self.storage.storage_root / f"session_{sid}" / "session_record_initial.json"
        self.assertEqual(self.storage.read_session_record(path)["accepted_session_config"]["session_id"], sid)
