"""Public Session launch workflows using real handlers and a controlled broker."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Barrier
from types import SimpleNamespace
import unittest
import h5py
import numpy as np
from unittest.mock import AsyncMock, patch
from nats.js.errors import NotFoundError

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, DeviceReadiness,
    InMemoryIngestor, NatsAcquisitionNodeCommunication, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsIngestorCommunication,
    NatsSynchronizationManagerCommunication, RuntimeCommandMessage,
    RuntimeCommandResultMessage, RuntimeEvidenceMessage, RuntimeParticipant,
    ScientificOutputSelection, ScientificProductDeclaration, ServiceReadiness,
    OpenCVCameraConfig, SeeedIMX219OpenCVCameraAdapter, DeviceAdapterState,
    SynchronizationManager, ActiveExperimentRuntimeContext, build_runtime_subject, parse_runtime_subject,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_scientific_camera_collection import FakeCV2 as CameraBoundary
from tests.test_seeed_imx219_camera_adapter import (
    FakeCV2 as ReopeningCameraBoundary, FakeVideoCapture,
)


class _Subscription:
    def __init__(self, subject, callback):
        self.subject = subject
        self.callback = callback
        self.active = True

    async def unsubscribe(self):
        self.active = False


class _Broker:
    """Only transport is substituted; all domain and command handlers are real."""

    def __init__(self):
        self.subscriptions = []
        self.commands = []
        self.results = []
        self.drop_results = set()
        self.change_result = None
        self.on_command = None

    async def subscribe(self, subject, cb, **kwargs):
        subscription = _Subscription(subject, cb)
        self.subscriptions.append(subscription)
        return subscription

    @staticmethod
    def matches(pattern, subject):
        tokens = subject.split(".")
        for index, expected in enumerate(pattern.split(".")):
            if expected == ">":
                return index < len(tokens)
            if index >= len(tokens) or expected not in {"*", tokens[index]}:
                return False
        return len(tokens) == len(pattern.split("."))

    async def publish(self, subject, data, stream):
        payload = json.loads(data)
        if stream == "LAB_COMMANDS":
            self.commands.append(payload)
            if self.on_command is not None:
                self.on_command(payload)
        elif stream == "LAB_COMMAND_RESULTS":
            self.results.append(payload)
            operation = subject.split(".")[-1]
            if (payload["source_id"], operation) in self.drop_results:
                return SimpleNamespace(stream=stream)
            if self.change_result is not None:
                payload = self.change_result(operation, payload)
                data = json.dumps(payload).encode()
        for subscription in tuple(self.subscriptions):
            if subscription.active and self.matches(subscription.subject, subject):
                await subscription.callback(SimpleNamespace(data=data, ack=AsyncMock()))
        return SimpleNamespace(stream=stream)


class _Boundary(NatsCommunicationBoundary):
    def __init__(self, component_type, component_id, broker):
        super().__init__(component_type, component_id)
        self.broker = broker
        self.available = True

    @property
    def connected(self):
        return self.available

    def _require_jetstream(self):
        if not self.available:
            raise ConnectionError("NATS unavailable")
        return self.broker


class _CollectingAdapter(ReadyFakeAdapter):
    def collect_records(self):
        return {"record_kind": "event", "records": [{"value": 1}]}


class _UnreadyAdapter(ReadyFakeAdapter):
    def check_ready(self):
        return DeviceReadiness(self.device_id, False, "disconnected", ())


class _FailingInitializationNode(AcquisitionNode):
    def initialize_session(self, *args, **kwargs):
        super().initialize_session(*args, **kwargs)
        raise OSError("Local preparation failed")


class _FailingCleanupNode(AcquisitionNode):
    def abort_session_initialization(self, session_id):
        raise OSError("Local cleanup failed")


class _UnreadySynchronization(SynchronizationManager):
    def check_ready(self):
        return ServiceReadiness("synchronization", "synchronization_manager", True, False, "unavailable")


class SessionLaunchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.broker = _Broker()
        self.ingestor = InMemoryIngestor(recovery_journal_root=self.root / "journals")
        self.sync = SynchronizationManager()
        self.controller = Controller()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.participants = [RuntimeParticipant("ingestor", "ingestor"),
                             RuntimeParticipant("synchronization_manager", "sync")]
        self.nodes = {}
        self.adapters = {}
        self.config = {"storage_location": str(self.root / "session-records"),
                       "protocol_plan": {"name": "no-op"},
                       "error_evidence_location": str(self.root / "errors")}

    async def services(self, *, ingestor=True, synchronization=True):
        if ingestor:
            self.ingestor_handler = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
            await self.ingestor_handler.subscribe_commands()
        if synchronization:
            self.sync_handler = NatsSynchronizationManagerCommunication(_Boundary("synchronization_manager", "sync", self.broker), self.sync)
            await self.sync_handler.subscribe_commands()

    async def node(self, node_id="node-a", *, missing=False, unready=False, extra_device=False, node_class=AcquisitionNode):
        product = ScientificProductDeclaration("events", "event", {"value": "int"}, "jsonl")
        declaration = DeviceDeclaration(node_id + "-device", "fake", True, True, ("events",), (product,))
        adapter_class = _UnreadyAdapter if unready else _CollectingAdapter
        adapter = adapter_class(declaration.device_id, "fake", ("events",), True)
        adapter.initialize({})
        inventory = [declaration]
        adapters = [adapter]
        if extra_device:
            inventory.append(DeviceDeclaration(node_id + "-other", "fake", True, False, ()))
            other = _CollectingAdapter(node_id + "-other", "fake", (), False)
            other.initialize({"deployment": "unchanged"})
            adapters.append(other)
        if missing:
            inventory.append(DeviceDeclaration(node_id + "-missing", "fake", True, False, ()))
        node = node_class(device_manager=DeviceManager(adapters), synchronization_manager=SynchronizationManager(),
                          ingestor=InMemoryIngestor(), node_id=node_id, role="acquisition",
                          error_evidence_location=str(self.root / "errors"),
                          default_local_storage_root=self.root / node_id, device_declarations=inventory)
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", node_id, self.broker), node)
        await handler.subscribe_commands()
        self.participants.append(RuntimeParticipant("acquisition_node", node_id))
        self.nodes[node_id] = node
        self.adapters[node_id] = adapters
        return node, declaration, adapter

    async def launch(self, selections, **kwargs):
        return await self.controller.launch_session(selections, communication=self.communication,
            participants=self.participants, config_parameters=self.config, result_window_s=0.01, **kwargs)

    async def test_participant_messages_round_trip_without_session_and_route(self):
        command = RuntimeCommandMessage("c", None, "check_readiness", "controller", "node-a", {})
        self.assertEqual(RuntimeCommandMessage.from_dict(command.to_dict()), command)
        result = RuntimeCommandResultMessage("r", "c", None, "node-a", "controller", "succeeded", True, None, {})
        self.assertEqual(RuntimeCommandResultMessage.from_dict(result.to_dict()), result)
        subject = build_runtime_subject(None, "command", "acquisition_node", "node-a", "check_readiness")
        self.assertEqual(parse_runtime_subject(subject)["session_id"], None)
        await self.services()
        await self.node()
        await self.communication.subscribe_command_results(None)
        report = await self.communication.request_command(self.participants[-1], "get_inventory", None, {}, 0.01)
        self.assertTrue(report.success)
        self.assertEqual(report.payload["devices"][0]["device_id"], "node-a-device")

    async def test_session_operations_reject_missing_invalid_session_ids(self):
        for operation in ("reserve", "initialize_session", "abort_session_initialization", "start_runtime", "run_one_iteration"):
            for identity in (None, "", False):
                with self.subTest(operation=operation, identity=identity), self.assertRaises(ValueError):
                    RuntimeCommandMessage("c", identity, operation, "controller", "node-a", {})

    async def test_inventory_reports_disconnected_and_missing_devices_without_device_criticality(self):
        node, declaration, _ = await self.node(missing=True, unready=True)
        self.assertIsNone(node.status()["session_id"])
        report = node.check_node_readiness()
        self.assertTrue(report.ready)
        self.assertEqual(len(report.device_readiness.results), 2)
        self.assertTrue(all(r.ready is False for r in report.device_readiness.results))
        self.assertIn("no_adapter", report.device_readiness.results[1].reason)
        self.assertEqual(node.declared_devices[0], declaration)
        self.assertNotIn("required", report.device_readiness.results[0].to_dict())

    async def test_atomic_owner_reservation_and_release(self):
        node, _, _ = await self.node()
        gate = Barrier(2)
        def reserve(identity):
            gate.wait()
            return identity, node.reserve(identity)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, ("session-a", "session-b")))
        winner = next(identity for identity, success in outcomes if success)
        self.assertEqual(sum(success for _, success in outcomes), 1)
        self.assertTrue(node.reserve(winner))
        self.assertFalse(node.release_reservation("unrelated"))
        self.assertEqual(node.check_node_readiness().reserved_for_session_id, winner)
        self.assertTrue(node.release_reservation(winner))

    async def test_launch_confirms_all_participants_without_storage_manager(self):
        await self.services()
        node, declaration, _ = await self.node()
        output = ScientificOutputSelection(declaration.device_id, "node-a", "events")
        result = await self.launch({"node-a": [declaration]}, scientific_outputs=[output])
        self.assertTrue(result.succeeded, result.error)
        sid = result.details["session_id"]
        self.assertEqual(result.details["session_state"], "initialized")
        self.assertEqual(node.status()["session_id"], sid)
        self.assertEqual(node.reserved_for_session_id, sid)
        self.assertEqual(node.local_storage_manager.root_path, self.root / "node-a")
        self.assertEqual(self.ingestor.session_id, sid)
        self.assertTrue(self.ingestor.recovery_journal_path.is_file())
        initialization = [c for c in self.broker.commands if c["command_type"] == "initialize_session"]
        self.assertEqual([c["target_id"] for c in initialization], ["ingestor", "sync", "node-a"])
        self.assertEqual(initialization[-1]["payload"]["scientific_outputs"], [output.to_dict()])
        self.assertNotIn("local_storage_roots", initialization[-1]["payload"])
        self.assertTrue(all(c["session_id"] is None for c in self.broker.commands if c["command_type"] in {"get_inventory", "check_readiness"}))

    async def test_controller_does_not_select_remote_filesystem_root(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.config["local_storage_roots"] = {"node-a": str(self.root / "remote")}
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("node-local storage roots", result.error)
        self.assertIsNone(node.reserved_for_session_id)

    async def test_initialization_rejects_undeclared_scientific_selection(self):
        await self.services()
        node, declaration, _ = await self.node()
        result = await self.launch({"node-a": [declaration]},
            scientific_outputs=[ScientificOutputSelection(declaration.device_id, "node-a", "undeclared")])
        self.assertFalse(result.succeeded)
        self.assertIn("Unknown scientific product", result.error)
        self.assertIsNone(node.reserved_for_session_id)

    async def test_required_unavailable_device_blocks_launch(self):
        await self.services()
        node, declaration, _ = await self.node(unready=True)
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("Required device", result.error)
        self.assertIsNone(node.reserved_for_session_id)

    async def test_optional_unavailable_device_is_omitted_from_final_configuration(self):
        await self.services()
        node, declaration, _ = await self.node(missing=True)
        missing = node.declared_devices[1]
        result = await self.launch({"node-a": [declaration, missing]})
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual([d["device_id"] for d in result.details["configuration"]["selected_devices"]], [declaration.device_id])

    async def test_optional_only_reservation_race_omits_resources(self):
        await self.services()
        node, declaration, _ = await self.node()
        optional = replace(declaration, required=False)
        def race(command):
            if command["command_type"] == "reserve":
                node.reserve("other-session")
        self.broker.on_command = race
        result = await self.launch({"node-a": [optional]})
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["configuration"]["selected_devices"], [])
        self.assertEqual(node.reserved_for_session_id, "other-session")

    async def test_mixed_node_reservation_race_blocks_launch(self):
        await self.services()
        node, declaration, _ = await self.node(missing=True)
        self.broker.on_command = lambda c: node.reserve("other-session") if c["command_type"] == "reserve" else None
        result = await self.launch({"node-a": [declaration, node.declared_devices[1]]})
        self.assertFalse(result.succeeded)
        self.assertEqual(node.reserved_for_session_id, "other-session")

    async def test_unknown_mandatory_readiness_blocks_launch(self):
        await self.services()
        for missing_type in ("ingestor", "synchronization_manager"):
            with self.subTest(missing_type=missing_type):
                self.broker.drop_results.add(("ingestor" if missing_type == "ingestor" else "sync", "check_readiness"))
                result = await self.launch({})
                self.assertFalse(result.succeeded)
                self.assertIn("readiness", result.error)
                self.broker.drop_results.clear()

    async def test_unready_synchronization_blocks_launch(self):
        self.sync = _UnreadySynchronization()
        await self.services()
        result = await self.launch({})
        self.assertFalse(result.succeeded)
        self.assertIn("synchronization_manager readiness", result.error)

    async def test_invalid_node_readiness_remains_unknown(self):
        await self.services()
        await self.node()
        declaration = self.nodes["node-a"].declared_devices[0]
        def invalid(operation, result):
            if operation == "check_readiness" and result["source_id"] == "node-a":
                result["payload"]["acquisition_node_readiness"]["device_readiness"] = []
            return result
        self.broker.change_result = invalid
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("unknown", result.error)

    async def test_failed_launch_ids_are_unique_and_allocated_before_requests(self):
        await self.services(ingestor=False)
        first = await self.launch({})
        second = await self.launch({})
        self.assertNotEqual(first.details["session_id"], second.details["session_id"])
        self.assertFalse(first.succeeded)
        self.assertFalse(second.succeeded)

    async def test_initialization_requires_matching_reservation(self):
        node, declaration, _ = await self.node()
        node.reserve("owner")
        with self.assertRaisesRegex(RuntimeError, "matching reservation"):
            node.initialize_session("unrelated", [declaration])
        self.assertIsNone(node.status()["session_id"])

    async def test_failed_preparation_cleans_all_started_participants_before_release(self):
        await self.services()
        good, good_declaration, _ = await self.node()
        bad, bad_declaration, _ = await self.node("node-b", node_class=_FailingInitializationNode)
        result = await self.launch({"node-a": [good_declaration], "node-b": [bad_declaration]})
        self.assertFalse(result.succeeded)
        self.assertIsNone(good.reserved_for_session_id)
        self.assertIsNone(bad.reserved_for_session_id)
        operations = [(c["target_id"], c["command_type"]) for c in self.broker.commands]
        for node_id in ("node-a", "node-b"):
            self.assertLess(operations.index((node_id, "abort_session_initialization")), operations.index((node_id, "release_reservation")))
        self.assertIn(("ingestor", "abort_session_initialization"), operations)
        self.assertIn(("sync", "abort_session_initialization"), operations)
        self.assertTrue((self.root / "journals" / ("session_" + result.details["session_id"] + ".jsonl")).exists())

    async def test_missing_initialization_result_is_unconfirmed_and_cleanup_releases(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.broker.drop_results.add(("node-a", "initialize_session"))
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("unconfirmed", result.error)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertTrue(any(r["operation"] == "abort_session_initialization" and r["confirmed"] for r in result.details["rollback"]))

    async def test_unconfirmed_cleanup_protects_reservation_even_when_initialization_result_missing(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.broker.drop_results.update({("node-a", "initialize_session"), ("node-a", "abort_session_initialization")})
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertEqual(node.reserved_for_session_id, result.details["session_id"])
        self.assertFalse(node.reserve("another-session"))
        self.assertTrue(any(r.get("reason") == "cleanup_unconfirmed" for r in result.details["rollback"]))
        self.assertFalse(any(c["target_id"] == "node-a" and c["command_type"] == "release_reservation" for c in self.broker.commands))

    async def test_cleanup_failure_does_not_abandon_remaining_participants(self):
        await self.services()
        node_a, a, _ = await self.node("node-a", node_class=_FailingCleanupNode)
        node_b, b, _ = await self.node("node-b", node_class=_FailingInitializationNode)
        result = await self.launch({"node-a": [a], "node-b": [b]})
        self.assertFalse(result.succeeded)
        self.assertIsNotNone(node_a.reserved_for_session_id)
        self.assertIsNone(node_b.reserved_for_session_id)
        self.assertTrue(any(c["target_id"] == "node-b" and c["command_type"] == "abort_session_initialization" for c in self.broker.commands))
        self.assertTrue(any(c["target_id"] == "node-b" and c["command_type"] == "release_reservation" for c in self.broker.commands))

    async def test_abort_preserves_accepted_journal_evidence_and_sync_evidence(self):
        await self.services()
        self.ingestor.prepare_session("session-a")
        evidence = RuntimeEvidenceMessage("evidence-a", "session-a", "warning", "node-a", {}, True)
        self.ingestor.receive_runtime_evidence(evidence)
        path = self.ingestor.recovery_journal_path
        before = path.read_bytes()
        self.assertTrue(self.ingestor.abort_session_initialization("session-a"))
        self.assertTrue(self.ingestor.abort_session_initialization("session-a"))
        self.assertEqual(path.read_bytes(), before)
        restored = InMemoryIngestor(session_id="session-a", recovery_journal_path=path)
        self.assertEqual(restored.accepted_runtime_evidence[0], evidence)
        self.sync.prepare_session("session-a")
        mapping = self.sync.create_and_activate_mapping("session-a", "node-a", 1.0, 2.0, 1.0, "initial")
        original = self.sync.mapping_update_evidence
        self.assertTrue(self.sync.abort_session_initialization("session-a"))
        self.assertEqual(self.sync.mapping_update_evidence, original)
        self.assertIs(self.sync.get_active_mapping("session-a", "node-a"), mapping)

    async def test_runtime_requires_bound_session_and_handler_survives_release(self):
        await self.services()
        node, declaration, _ = await self.node()
        launch = await self.launch({"node-a": [declaration]})
        self.assertTrue(launch.succeeded, launch.error)
        await self.communication.subscribe_command_results("wrong-session")
        wrong = await self.communication.request_command(self.participants[-1], "start_runtime", "wrong-session", {}, 0.01)
        self.assertFalse(wrong.success)
        self.assertFalse(node.status()["is_running"])
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        stopped = await self.controller.stop_launched_session()
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertIsNone(node.status()["session_id"])
        report = await self.communication.request_command(self.participants[-1], "get_inventory", None, {}, 0.01)
        self.assertTrue(report.success)
        self.assertEqual(report.payload["devices"][0]["device_id"], declaration.device_id)

    async def test_reservation_covers_local_finalization_but_not_global_collection(self):
        await self.services()
        node, declaration, _ = await self.node()
        launched = await self.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        manager = node.local_storage_manager
        preparation = await self.communication.request_command(self.participants[-1], "prepare_experiment_scientific_outputs", sid,
            {"experiment_id": "experiment-a", "scientific_outputs": [ScientificOutputSelection(declaration.device_id, "node-a", "events").to_dict()]}, 0.01)
        self.assertTrue(preparation.success)
        manifest = manager.manifests[0]
        self.assertFalse(node.release_reservation(sid))
        self.assertEqual(node.reserved_for_session_id, sid)
        finalize = manager.finalize_stream
        def finalize_while_reserved(*args, **kwargs):
            self.assertEqual(node.reserved_for_session_id, sid)
            return finalize(*args, **kwargs)
        with patch.object(manager, "finalize_stream", side_effect=finalize_while_reserved) as finalized:
            stopped = await self.controller.stop_launched_session()
        self.assertEqual(finalized.call_count, 1)
        self.assertTrue(stopped.succeeded, stopped.error)
        self.assertIsNone(node.reserved_for_session_id)
        final = manager.manifests[0]
        self.assertEqual(final.lifecycle_state, "finalized")
        self.assertTrue(Path(final.local_storage_path).is_file())
        self.assertEqual(stopped.details["session_state"], "stopping")
        handoff = self.ingestor.compile_artifact_collection_handoff(sid)
        self.assertEqual(handoff["artifacts"][0]["artifact_manifest"]["artifact_manifest_id"], manifest.artifact_manifest_id)
        self.assertFalse(handoff["artifacts"][0]["missing_finalization_evidence"])

    async def test_only_selected_devices_start_and_collect_through_broker(self):
        await self.services()
        node, declaration, adapter = await self.node(extra_device=True)
        self.config["device_configurations"] = {declaration.device_id: {}, "node-a-other": {"session": "not-selected"}}
        launch = await self.launch({"node-a": [declaration]})
        self.assertTrue(launch.succeeded, launch.error)
        sid = launch.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.assertTrue(adapter.get_status().running)
        self.assertFalse(self.adapters["node-a"][1].get_status().running)
        self.assertEqual(self.adapters["node-a"][1].initialization_config, {"deployment": "unchanged"})
        iteration = await self.communication.request_command(self.participants[-1], "run_one_iteration", sid, {}, 0.01)
        self.assertTrue(iteration.success, iteration.reason)
        self.assertEqual(iteration.payload["collections_seen"], 1)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)

    async def test_missing_service_preparation_confirmation_blocks_launch(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.broker.drop_results.add(("sync", "initialize_session"))
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("sync", result.error)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertTrue(any(c["target_id"] == "sync" and c["command_type"] == "abort_session_initialization" for c in self.broker.commands))

    async def test_invalid_preparation_confirmation_blocks_launch_and_cleans(self):
        await self.services()
        node, declaration, _ = await self.node()
        def invalid(operation, result):
            if operation == "initialize_session" and result["source_id"] == "node-a":
                result["payload"] = {"publication_accepted": True}
            return result
        self.broker.change_result = invalid
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIsNone(node.reserved_for_session_id)

    async def test_node_readiness_requires_its_nats_connection(self):
        node, _, _ = await self.node()
        boundary = _Boundary("acquisition_node", "node-a", self.broker)
        boundary.available = False
        handler = NatsAcquisitionNodeCommunication(boundary, node)
        result = handler.execute_command(RuntimeCommandMessage("c", None, "check_readiness", "controller", "node-a", {}))
        self.assertTrue(result.success)
        self.assertFalse(result.payload["acquisition_node_readiness"]["ready"])

    async def test_repeated_node_readiness_preserves_running_acquisition(self):
        await self.services()
        node, declaration, adapter = await self.node()
        self.assertTrue((await self.launch({"node-a": [declaration]})).succeeded)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.assertTrue(node.check_node_readiness().ready)
        self.assertTrue(node.check_node_readiness().ready)
        self.assertTrue(adapter.get_status().running)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)

    async def test_unconfirmed_stop_preserves_reservation_but_other_nodes_finish(self):
        await self.services()
        node_a, a, _ = await self.node()
        node_b, b, _ = await self.node("node-b")
        launched = await self.launch({"node-a": [a], "node-b": [b]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.broker.drop_results.add(("node-a", "stop_runtime"))
        stopped = await self.controller.stop_launched_session()
        self.assertFalse(stopped.succeeded)
        self.assertEqual(node_a.reserved_for_session_id, launched.details["session_id"])
        self.assertIsNone(node_b.reserved_for_session_id)
        self.assertEqual([n["released"] for n in stopped.details["nodes"]], [False, True])

    async def test_failed_runtime_start_protects_unconfirmed_cleanup(self):
        await self.services()
        node, declaration, adapter = await self.node()
        self.assertTrue((await self.launch({"node-a": [declaration]})).succeeded)
        with patch.object(adapter, "start", side_effect=OSError("hardware start failed")):
            result = await self.controller.start_launched_session()
        self.assertFalse(result.succeeded)
        self.assertFalse(node.status()["is_running"])
        self.assertIsNotNone(node.reserved_for_session_id)
        self.assertTrue(any(r["participant"]["component_id"] == "node-a" and not r["confirmed"] for r in result.details["rollback"]))

    async def test_running_abort_storage_failure_protects_reservation_until_cleanup_completes(self):
        await self.services()
        node_a, a, _ = await self.node()
        _, b, adapter_b = await self.node("node-b")
        node_c, c, _ = await self.node("node-c")
        launched = await self.launch({"node-a": [a], "node-b": [b], "node-c": [c]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        participant = RuntimeParticipant("acquisition_node", "node-a")
        prepared = await self.communication.request_command(participant, "prepare_experiment_scientific_outputs", sid,
            {"experiment_id": "experiment-a", "scientific_outputs": [ScientificOutputSelection(a.device_id, "node-a", "events").to_dict()]}, 0.01)
        self.assertTrue(prepared.success, prepared.reason)
        manager = node_a.local_storage_manager
        manifest = manager.manifests[0]
        journal_path = self.ingestor.recovery_journal_path
        journal_before = journal_path.read_bytes()
        cleanup = manager.cleanup
        with patch.object(manager, "cleanup", side_effect=OSError("storage cleanup failed")) as failed_cleanup:
            with patch.object(adapter_b, "start", side_effect=OSError("hardware start failed")):
                started = await self.controller.start_launched_session()
            self.assertFalse(started.succeeded)
            self.assertTrue(any(r["participant"]["component_id"] == "node-a" and not r["confirmed"]
                                for r in started.details["rollback"]))
            self.assertEqual(failed_cleanup.call_count, 1)
            self.assertEqual(node_a.reserved_for_session_id, sid)
            repeated = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertFalse(repeated.success)
            self.assertIn("cleanup failed", repeated.reason)
            self.assertEqual(failed_cleanup.call_count, 2)
            release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
            self.assertFalse(release.success)
            self.assertEqual(node_a.reserved_for_session_id, sid)
            self.assertFalse(node_a.reserve("competing-session"))
            self.assertFalse(node_a.check_node_readiness().device_readiness.all_ready)
        self.assertIsNone(node_c.reserved_for_session_id)
        self.assertTrue(any(r["participant"]["component_id"] == "node-c" and r["confirmed"]
                            for r in started.details["rollback"]))
        self.assertEqual(journal_path.read_bytes(), journal_before)
        finalized = manager.manifests[0]
        self.assertEqual(finalized.artifact_manifest_id, manifest.artifact_manifest_id)
        self.assertEqual(finalized.lifecycle_state, "finalized")
        artifact_before = Path(finalized.local_storage_path).read_bytes()
        with patch.object(manager, "cleanup", wraps=cleanup) as completed_cleanup:
            recovered = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertTrue(recovered.success, recovered.reason)
            repeated = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertTrue(repeated.success, repeated.reason)
            self.assertEqual(completed_cleanup.call_count, 1)
        release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertTrue(release.success, release.reason)
        self.assertIsNone(node_a.status()["session_id"])
        self.assertEqual(Path(finalized.local_storage_path).read_bytes(), artifact_before)

    async def test_camera_release_failure_protects_reservation_until_confirmed_cleanup(self):
        await self.services()
        cv2 = CameraBoundary([])
        camera = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frames", "camera_frame_metadata"), True,
            cv2_module=cv2,
        )
        camera.initialize(OpenCVCameraConfig(0, 0, 1))
        product = ScientificProductDeclaration(
            "frames", "camera_frames", {"frame_shape": [3, 4, 3], "frame_dtype": "uint8"}, "hdf5",
        )
        declaration = DeviceDeclaration(
            "camera", "opencv", True, True, camera.declared_capabilities, (product,),
        )
        node = AcquisitionNode(
            device_manager=DeviceManager([camera]), synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(), node_id="node-a", role="acquisition",
            error_evidence_location=str(self.root / "errors"),
            default_local_storage_root=self.root / "node-a", device_declarations=[declaration],
        )
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", self.broker), node)
        await handler.subscribe_commands()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        self.participants.append(participant)
        other, b, _ = await self.node("node-b")
        _, c, adapter_c = await self.node("node-c")
        launched = await self.launch({"node-a": [declaration], "node-b": [b], "node-c": [c]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        self.assertEqual(node.reserved_for_session_id, sid)
        self.assertEqual(node.status()["session_id"], sid)
        prepared = await self.communication.request_command(participant, "prepare_experiment_scientific_outputs", sid,
            {"experiment_id": "experiment-a", "scientific_outputs": [ScientificOutputSelection("camera", "node-a", "frames").to_dict()]}, 0.01)
        self.assertTrue(prepared.success, prepared.reason)
        manager = node.local_storage_manager
        manifest = manager.manifests[0]
        warning = RuntimeEvidenceMessage("camera-warning", sid, "warning", "node-a", {"reason": "audit fixture"}, True)
        await handler.publish_evidence(warning)
        accepted_before = self.ingestor.accepted_runtime_evidence
        journal = self.ingestor.recovery_journal_path
        journal_before = journal.read_bytes()
        with patch.object(cv2.capture, "release", side_effect=OSError("camera release failed")) as release:
            with patch.object(adapter_c, "start", side_effect=OSError("other node start failed")):
                started = await self.controller.start_launched_session()
            self.assertFalse(started.succeeded)
            self.assertTrue(any(r["participant"]["component_id"] == "node-a" and not r["confirmed"]
                                for r in started.details["rollback"]))
            self.assertEqual(release.call_count, 1)
            self.assertEqual(camera.state, DeviceAdapterState.FAILED)
            rejected = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
            self.assertFalse(rejected.success)
            self.assertEqual(node.reserved_for_session_id, sid)
            self.assertFalse(node.reserve("competing-session"))
            repeated = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertFalse(repeated.success)
            self.assertEqual(release.call_count, 2)
            self.assertTrue(cv2.capture.isOpened())
            self.assertFalse(camera.get_status().shutdown)
            rejected = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
            self.assertFalse(rejected.success)
            self.assertEqual(node.reserved_for_session_id, sid)
        self.assertIsNone(other.reserved_for_session_id)
        self.assertTrue(any(r["participant"]["component_id"] == "node-b" and r["confirmed"]
                            for r in started.details["rollback"]))
        finalized = manager.manifests[0]
        self.assertEqual(finalized.lifecycle_state, "finalized")
        self.assertEqual(finalized.artifact_manifest_id, manifest.artifact_manifest_id)
        artifact_path = Path(finalized.local_storage_path)
        artifact_before = artifact_path.read_bytes()
        with patch.object(cv2.capture, "release", wraps=cv2.capture.release) as release:
            completed = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertTrue(completed.success, completed.reason)
            self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
            self.assertTrue(cv2.capture.released)
            self.assertFalse(cv2.capture.isOpened())
            repeated = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertTrue(repeated.success, repeated.reason)
            self.assertEqual(release.call_count, 1)
        released = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertTrue(released.success, released.reason)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertIsNone(node.status()["session_id"])
        self.assertEqual(artifact_path.read_bytes(), artifact_before)
        self.assertEqual(manager.manifests[0], finalized)
        self.assertTrue(journal.read_bytes().startswith(journal_before))
        for evidence in accepted_before:
            self.assertIn(evidence, self.ingestor.accepted_runtime_evidence)
        self.assertIn(warning, self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"])

    async def test_retained_camera_node_launches_and_acquires_in_two_sequential_sessions(self):
        await self.services()
        await self.communication.subscribe_command_results(None)
        frames = [np.full((3, 4, 3), value, dtype=np.uint8) for value in (7, 9)]
        cv2 = ReopeningCameraBoundary(frames)
        camera = SeeedIMX219OpenCVCameraAdapter(
            "camera", "opencv", ("camera_frames", "camera_frame_metadata"), True, cv2_module=cv2)
        camera.initialize(OpenCVCameraConfig(0, 0, 1))
        product = ScientificProductDeclaration("frames", "camera_frames",
            {"frame_shape": [3, 4, 3], "frame_dtype": "uint8"}, "hdf5")
        declaration = DeviceDeclaration("camera", "opencv", True, True, camera.declared_capabilities, (product,))
        manager = DeviceManager([camera])
        local_ingestor = InMemoryIngestor()
        node = AcquisitionNode(device_manager=manager, synchronization_manager=SynchronizationManager(),
            ingestor=local_ingestor, node_id="node-a", role="acquisition",
            error_evidence_location=str(self.root / "errors"), default_local_storage_root=self.root / "node-a",
            device_declarations=[declaration])
        participant = RuntimeParticipant("acquisition_node", "node-a")
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", self.broker), node)
        await handler.subscribe_commands()
        self.participants.append(participant)
        snapshots = []
        session_ids = []
        for index, source in enumerate((1, 2)):
            readiness = await self.communication.request_command(participant, "check_readiness", None, {}, 0.01)
            self.assertTrue(readiness.payload["acquisition_node_readiness"]["device_readiness"][0]["ready"])
            self.config["device_configurations"] = {"camera": {
                "camera_source": source, "api_preference": 0, "frames_per_collect": index + 1}}
            launched = await self.launch({"node-a": [declaration]})
            self.assertTrue(launched.succeeded, launched.error)
            sid = launched.details["session_id"]
            session_ids.append(sid)
            self.assertEqual(camera.initialization_config.camera_source, source)
            self.assertEqual(camera.initialization_config.frames_per_collect, index + 1)
            self.assertTrue((await self.controller.start_launched_session()).succeeded)
            eid = "experiment-" + str(index)
            prepared = await self.communication.request_command(participant, "prepare_experiment_scientific_outputs", sid,
                {"experiment_id": eid, "scientific_outputs": [ScientificOutputSelection("camera", "node-a", "frames").to_dict()]}, 0.01)
            self.assertTrue(prepared.success, prepared.reason)
            node.activate_experiment_runtime_context(ActiveExperimentRuntimeContext(eid, 0.0))
            collected = await self.communication.request_command(participant, "run_one_iteration", sid, {}, 0.01)
            self.assertTrue(collected.success, collected.reason)
            storage = node.local_storage_manager
            journal = self.ingestor.recovery_journal_path
            stopped = await self.controller.stop_launched_session()
            self.assertTrue(stopped.succeeded, stopped.error)
            self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
            self.assertTrue(cv2.captures[-1].released)
            self.assertIsNone(node.reserved_for_session_id)
            self.assertIsNone(node.status()["session_id"])
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            self.assertEqual(node.scientific_output_storage_ids.keys(), {(eid, "camera", "frames")})
            manifest = storage.manifests[0]
            self.assertEqual((manifest.session_id, manifest.experiment_id, manifest.lifecycle_state), (sid, eid, "finalized"))
            path = Path(manifest.local_storage_path)
            with h5py.File(path, "r") as artifact:
                self.assertEqual(artifact["frames"].shape[0], index + 1)
                np.testing.assert_array_equal(artifact["frames"][0], frames[0])
                self.assertEqual(artifact["frames"].dtype, np.dtype("uint8"))
                for timing in ("session_time_s", "experiment_time_s", "acquisition_node_local_time_s", "timestamp_status"):
                    self.assertEqual(len(artifact[timing]), index + 1)
            snapshots.append((path, path.read_bytes(), journal, journal.read_bytes(), manifest))
            self.assertIs(manager.adapters[0], camera)
            if index == 0:
                # Normal service binding lifetimes are deferred. Retain Session A's
                # evidence owner and give B fresh services, keeping the same node.
                self.ingestor = InMemoryIngestor(recovery_journal_root=self.root / "journals-b")
                ingestor_b = NatsIngestorCommunication(_Boundary("ingestor", "ingestor-b", self.broker), self.ingestor)
                sync_b = NatsSynchronizationManagerCommunication(
                    _Boundary("synchronization_manager", "sync-b", self.broker), SynchronizationManager())
                await ingestor_b.subscribe_commands()
                await sync_b.subscribe_commands()
                self.participants[:2] = [RuntimeParticipant("ingestor", "ingestor-b"),
                                        RuntimeParticipant("synchronization_manager", "sync-b")]
                self.controller = Controller()
        for path, data, journal, entries, manifest in snapshots:
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(journal.read_bytes(), entries)
            evidence = [message for message in node.artifact_manifest_evidence
                        if message.payload["artifact_manifest_id"] == manifest.artifact_manifest_id]
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all(message.session_id == manifest.session_id for message in evidence))
        self.assertEqual({envelope.session_id for envelope in local_ingestor.accepted_envelopes}, set(session_ids))
        self.assertEqual([capture.source for capture in cv2.captures], [0, 1, 2])
        inventory = await self.communication.request_command(participant, "get_inventory", None, {}, 0.01)
        self.assertTrue(inventory.success)
        self.assertTrue(node.check_node_readiness().device_readiness.all_ready)

    async def test_confirmed_abort_reuses_deployment_configuration_not_previous_session_settings(self):
        node, declaration, adapter = await self.node()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        for sid, configuration in (("session-a", {"node-a-device": {"session_setting": "A"}}), ("session-b", {})):
            await self.communication.subscribe_command_results(sid)
            self.assertTrue((await self.communication.request_command(participant, "reserve", sid, {}, 0.01)).success)
            prepared = await self.communication.request_command(participant, "initialize_session", sid,
                {"selected_devices": [declaration.to_dict()], "device_configurations": configuration}, 0.01)
            self.assertTrue(prepared.success, prepared.reason)
            self.assertEqual(adapter.initialization_config, {"session_setting": "A"} if sid == "session-a" else {})
            aborted = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
            self.assertTrue(aborted.success, aborted.reason)
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)
            self.assertTrue((await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)).success)
            self.assertTrue(node.check_node_readiness().device_readiness.all_ready)

    async def test_camera_initialization_abort_reuses_only_after_capture_cleanup_is_confirmed(self):
        cv2 = ReopeningCameraBoundary([np.full((3, 4, 3), 7, dtype=np.uint8)])
        camera = SeeedIMX219OpenCVCameraAdapter("camera", "opencv", ("camera_frame_metadata",), True, cv2_module=cv2)
        declaration = DeviceDeclaration("camera", "opencv", True, True, camera.declared_capabilities)
        node = AcquisitionNode(device_manager=DeviceManager([camera]), synchronization_manager=SynchronizationManager(),
            ingestor=InMemoryIngestor(), node_id="node-a", role="acquisition",
            error_evidence_location=str(self.root / "errors"), default_local_storage_root=self.root / "node-a",
            device_declarations=[declaration])
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-a", self.broker), node)
        await handler.subscribe_commands()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        async def command(operation, sid, payload=None):
            return await self.communication.request_command(participant, operation, sid, payload or {}, 0.01)
        await self.communication.subscribe_command_results("session-a")
        await self.communication.subscribe_command_results("session-b")
        self.assertTrue((await command("reserve", "session-a")).success)
        with patch.object(node, "prepare_local_storage", side_effect=OSError("storage preparation failed")):
            prepared = await command("initialize_session", "session-a", {
                "selected_devices": [declaration.to_dict()], "device_configurations": {"camera": {
                    "camera_source": 1, "api_preference": 0, "frames_per_collect": 1}}})
        self.assertFalse(prepared.success)
        capture = cv2.captures[0]
        with patch.object(capture, "release", side_effect=OSError("release failed")) as release:
            for _ in range(2):
                self.assertFalse((await command("abort_session_initialization", "session-a")).success)
                self.assertFalse((await command("release_reservation", "session-a")).success)
                self.assertFalse((await command("reserve", "session-b")).success)
                rejected = await command("initialize_session", "session-b", {"selected_devices": [declaration.to_dict()]})
                self.assertFalse(rejected.success)
                self.assertEqual(camera.state, DeviceAdapterState.FAILED)
                self.assertTrue(capture.isOpened())
                self.assertFalse(node.check_node_readiness().device_readiness.all_ready)
            self.assertEqual(release.call_count, 2)
            self.assertEqual(len(cv2.captures), 1)
        self.assertTrue((await command("abort_session_initialization", "session-a")).success)
        self.assertTrue(capture.released)
        self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
        self.assertTrue((await command("release_reservation", "session-a")).success)
        self.assertTrue(node.check_node_readiness().device_readiness.all_ready)
        self.assertTrue((await command("reserve", "session-b")).success)
        self.assertTrue((await command("initialize_session", "session-b", {
            "selected_devices": [declaration.to_dict()], "device_configurations": {"camera": {
                "camera_source": 2, "api_preference": 0, "frames_per_collect": 1}}})).success)
        self.assertEqual(cv2.captures[-1].source, 2)
        self.assertTrue((await command("start_runtime", "session-b")).success)
        self.assertTrue((await command("run_one_iteration", "session-b")).success)
        self.assertTrue((await command("stop_runtime", "session-b")).success)
        self.assertTrue((await command("release_reservation", "session-b")).success)

    async def test_camera_setup_failure_requires_confirmed_cleanup_before_session_reuse(self):
        for operation in ("set", "isOpened"):
            for release_fails in (False, True):
                with self.subTest(operation=operation, release_fails=release_fails):
                    node_id = f"node-{operation}-{release_fails}"
                    session_a = f"session-a-{node_id}"
                    session_b = f"session-b-{node_id}"
                    cv2 = ReopeningCameraBoundary([np.full((3, 4, 3), 7, dtype=np.uint8)])
                    camera = SeeedIMX219OpenCVCameraAdapter(
                        "camera", "opencv", ("camera_frame_metadata",), True, cv2_module=cv2)
                    declaration = DeviceDeclaration("camera", "opencv", True, True, camera.declared_capabilities)
                    node = AcquisitionNode(
                        device_manager=DeviceManager([camera]), synchronization_manager=SynchronizationManager(),
                        ingestor=InMemoryIngestor(), node_id=node_id, role="acquisition",
                        error_evidence_location=str(self.root / "errors"),
                        default_local_storage_root=self.root / node_id, device_declarations=[declaration])
                    handler = NatsAcquisitionNodeCommunication(
                        _Boundary("acquisition_node", node_id, self.broker), node)
                    await handler.subscribe_commands()
                    participant = RuntimeParticipant("acquisition_node", node_id)
                    await self.communication.subscribe_command_results(session_a)
                    await self.communication.subscribe_command_results(session_b)

                    async def command(operation, sid, payload=None):
                        return await self.communication.request_command(
                            participant, operation, sid, payload or {}, 0.01)

                    self.assertTrue((await command("reserve", session_a)).success)
                    with patch.object(FakeVideoCapture, "release", autospec=True,
                                      side_effect=OSError("camera release failed") if release_fails
                                      else FakeVideoCapture.release) as release:
                        with patch.object(FakeVideoCapture, operation,
                                          side_effect=OSError("camera setup failed")):
                            initialized = await command("initialize_session", session_a, {
                                "selected_devices": [declaration.to_dict()],
                                "device_configurations": {"camera": {
                                    "camera_source": 0, "api_preference": 0,
                                    "frames_per_collect": 1, "frame_width": 640}}})
                        self.assertFalse(initialized.success)
                        self.assertEqual(camera.state, DeviceAdapterState.FAILED)
                        self.assertFalse(camera.get_status().shutdown)
                        capture = cv2.captures[0]
                        self.assertEqual(capture.released, not release_fails)
                        self.assertFalse(node.check_node_readiness().device_readiness.all_ready)
                        self.assertFalse((await command("release_reservation", session_a)).success)
                        self.assertFalse((await command("reserve", session_b)).success)
                        self.assertFalse((await command("start_runtime", session_a)).success)
                        if release_fails:
                            for _ in range(2):
                                aborted = await command("abort_session_initialization", session_a)
                                self.assertFalse(aborted.success)
                                self.assertEqual(node.status()["session_id"], session_a)
                                self.assertEqual(node.reserved_for_session_id, session_a)
                                self.assertEqual(camera.state, DeviceAdapterState.FAILED)
                                self.assertFalse(camera.get_status().shutdown)
                                self.assertFalse(node.check_node_readiness().device_readiness.all_ready)
                                self.assertTrue(capture.isOpened())
                                self.assertFalse((await command("release_reservation", session_a)).success)
                                self.assertFalse((await command("reserve", session_b)).success)
                                rejected = await command("initialize_session", session_b,
                                    {"selected_devices": [declaration.to_dict()]})
                                self.assertFalse(rejected.success)
                            self.assertEqual(release.call_count, 3)
                            self.assertEqual(len(cv2.captures), 1)
                        else:
                            self.assertTrue((await command("abort_session_initialization", session_a)).success)
                            self.assertEqual(release.call_count, 1)
                    self.assertTrue((await command("abort_session_initialization", session_a)).success)
                    self.assertTrue(capture.released)
                    self.assertFalse(capture.isOpened())
                    self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
                    self.assertTrue(camera.get_status().shutdown)
                    self.assertTrue((await command("release_reservation", session_a)).success)
                    self.assertIsNone(node.status()["session_id"])
                    self.assertIsNone(node.reserved_for_session_id)
                    self.assertTrue(node.check_node_readiness().device_readiness.all_ready)
                    self.assertTrue((await command("reserve", session_b)).success)
                    initialized = await command("initialize_session", session_b, {
                        "selected_devices": [declaration.to_dict()],
                        "device_configurations": {"camera": {
                            "camera_source": 1, "api_preference": 0, "frames_per_collect": 1}}})
                    self.assertTrue(initialized.success, initialized.reason)
                    self.assertEqual(camera.initialization_config.camera_source, 1)
                    self.assertTrue((await command("start_runtime", session_b)).success)
                    self.assertTrue((await command("run_one_iteration", session_b)).success)
                    self.assertTrue((await command("stop_runtime", session_b)).success)
                    self.assertTrue(cv2.captures[1].released)
                    self.assertEqual(camera.state, DeviceAdapterState.DECLARED)
                    self.assertTrue((await command("release_reservation", session_b)).success)

    async def test_failed_storage_preparation_blocks_runtime_through_broker(self):
        await self.services()
        node, declaration, adapter = await self.node()
        participant = RuntimeParticipant("acquisition_node", "node-a")
        sid = "failed-preparation"
        await self.communication.subscribe_command_results(sid)
        reserved = await self.communication.request_command(participant, "reserve", sid, {}, 0.01)
        self.assertTrue(reserved.success)
        with patch.object(node, "prepare_local_storage", side_effect=PermissionError("storage unavailable")):
            initialized = await self.communication.request_command(participant, "initialize_session", sid,
                {"selected_devices": [declaration.to_dict()], "device_configurations": {}}, 0.01)
        self.assertFalse(initialized.success)
        self.assertIn("storage unavailable", initialized.reason)
        self.assertEqual(node.status()["session_id"], sid)
        self.assertIsNone(node.local_storage_manager)
        with patch.object(adapter, "start", wraps=adapter.start) as start, patch.object(adapter, "collect_records", wraps=adapter.collect_records) as collect:
            for operation in ("start_runtime", "run_one_iteration"):
                result = await self.communication.request_command(participant, operation, sid, {}, 0.01)
                self.assertFalse(result.success)
                self.assertIn("successful Session preparation", result.reason)
            start.assert_not_called()
            collect.assert_not_called()
        self.assertFalse(node.status()["is_running"])
        self.assertEqual(node.status()["iteration_count"], 0)
        self.assertEqual(node.artifact_manifest_evidence, ())
        self.assertFalse((self.root / "node-a").exists())
        release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertFalse(release.success)
        aborted = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
        self.assertTrue(aborted.success, aborted.reason)
        release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertTrue(release.success, release.reason)
        _, good, good_adapter = await self.node("node-b")
        launched = await self.launch({"node-b": [good]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        self.assertTrue(good_adapter.get_status().running)
        iteration = await self.communication.request_command(RuntimeParticipant("acquisition_node", "node-b"),
            "run_one_iteration", launched.details["session_id"], {}, 0.01)
        self.assertTrue(iteration.success, iteration.reason)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)

    async def test_aborted_preparation_blocks_runtime_before_reservation_release(self):
        await self.services()
        node, declaration, adapter = await self.node()
        launched = await self.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        participant = RuntimeParticipant("acquisition_node", "node-a")
        aborted = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
        self.assertTrue(aborted.success, aborted.reason)
        self.assertEqual(node.status()["session_id"], sid)
        for operation in ("start_runtime", "run_one_iteration"):
            result = await self.communication.request_command(participant, operation, sid, {}, 0.01)
            self.assertFalse(result.success)
            self.assertIn("successful Session preparation", result.reason)
        self.assertTrue(adapter.get_status().shutdown)
        self.assertTrue(node.release_reservation(sid))

    async def test_completed_runtime_cleanup_blocks_acquisition_before_release(self):
        await self.services()
        node, declaration, adapter = await self.node()
        launched = await self.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        sid = launched.details["session_id"]
        participant = RuntimeParticipant("acquisition_node", "node-a")
        stopped = await self.communication.request_command(participant, "stop_runtime", sid, {}, 0.01)
        self.assertTrue(stopped.success, stopped.reason)
        self.assertEqual(node.status()["session_id"], sid)
        for operation in ("start_runtime", "run_one_iteration"):
            result = await self.communication.request_command(participant, operation, sid, {}, 0.01)
            self.assertFalse(result.success)
            self.assertIn("successful Session preparation", result.reason)
        self.assertTrue(adapter.get_status().shutdown)
        self.assertTrue(node.release_reservation(sid))

    async def test_failed_runtime_stop_requires_confirmed_abort_before_release(self):
        await self.services()
        node, declaration, adapter = await self.node()
        launched = await self.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        sid = launched.details["session_id"]
        participant = RuntimeParticipant("acquisition_node", "node-a")
        prepared = await self.communication.request_command(participant, "prepare_experiment_scientific_outputs", sid,
            {"experiment_id": "experiment-a", "scientific_outputs": [ScientificOutputSelection(declaration.device_id, "node-a", "events").to_dict()]}, 0.01)
        self.assertTrue(prepared.success, prepared.reason)
        with patch.object(node.local_storage_manager, "finalize_stream", side_effect=OSError("stream finalization failed")):
            stopped = await self.communication.request_command(participant, "stop_runtime", sid, {}, 0.01)
        self.assertFalse(stopped.success)
        self.assertIn("stream finalization failed", stopped.reason)
        self.assertTrue(adapter.get_status().shutdown)
        release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertFalse(release.success)
        self.assertEqual(node.reserved_for_session_id, sid)
        aborted = await self.communication.request_command(participant, "abort_session_initialization", sid, {}, 0.01)
        self.assertTrue(aborted.success, aborted.reason)
        release = await self.communication.request_command(participant, "release_reservation", sid, {}, 0.01)
        self.assertTrue(release.success, release.reason)

    async def test_controller_status_without_local_node_before_and_after_launch(self):
        status = self.controller.get_status()
        self.assertIsNone(status["session_id"])
        self.assertIsNone(status["session_state"])
        self.assertIsNone(status["acquisition_runtime"])
        self.assertIsNone(status["last_command"])
        await self.services()
        _, declaration, _ = await self.node()
        launched = await self.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        status = self.controller.get_status()
        self.assertEqual(status["session_id"], launched.details["session_id"])
        self.assertEqual(status["session_state"], "initialized")
        self.assertIsNone(status["acquisition_runtime"])
        self.assertEqual(status["last_command"], launched)

    async def test_controller_pre_session_status_preserves_local_node_report(self):
        node, _, _ = await self.node()
        controller = Controller(acquisition_node=node)
        status = controller.get_status()
        self.assertIsNone(status["session_id"])
        self.assertIsNone(status["session_state"])
        self.assertEqual(status["acquisition_runtime"], node.status())
        self.assertTrue(node.reserve("status-session"))
        self.assertEqual(controller.get_status()["acquisition_runtime"]["reserved_for_session_id"], "status-session")
        self.assertTrue(node.release_reservation("status-session"))

    async def test_unready_ingestor_blocks_launch(self):
        await self.services()
        with patch.object(self.ingestor, "check_ready", return_value=ServiceReadiness("ingestor", "ingestor", True, False, "not_ready")):
            result = await self.launch({})
        self.assertFalse(result.succeeded)
        self.assertIn("ingestor readiness", result.error)

    async def test_unknown_node_report_blocks_required_launch(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.broker.drop_results.add(("node-a", "check_readiness"))
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIsNone(node.reserved_for_session_id)

    async def test_deployment_preparation_reconstructs_existing_session_journal(self):
        path = self.root / "journals" / "session_prior-session.jsonl"
        path.parent.mkdir()
        original = InMemoryIngestor(session_id="prior-session", recovery_journal_path=path)
        evidence = RuntimeEvidenceMessage("e", "prior-session", "warning", "node-a", {}, True)
        original.receive_runtime_evidence(evidence)
        prepared = self.ingestor.prepare_session("prior-session")
        self.assertTrue(prepared.ready)
        self.assertEqual(self.ingestor.accepted_runtime_evidence[0], evidence)
        self.assertEqual(self.ingestor.accepted_runtime_evidence[1].evidence_type, "ingestor_recovery_evidence")

    async def test_missing_reservation_result_is_not_success_and_owner_release_is_attempted(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.broker.drop_results.add(("node-a", "reserve"))
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertTrue(result.details["unconfirmed_reservations"][0]["release_confirmed"])
        self.assertFalse(any(c["command_type"] == "initialize_session" for c in self.broker.commands))

    async def test_session_configuration_failure_rolls_back_reservations(self):
        await self.services()
        node, declaration, _ = await self.node()
        self.config["invalid_configuration_key"] = True
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertIsNone(node.status()["session_id"])

    async def test_ingestor_journal_preparation_failure_is_explicit(self):
        self.ingestor = InMemoryIngestor()
        await self.services()
        node, declaration, _ = await self.node()
        result = await self.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertIn("journal root is not configured", result.error)
        self.assertEqual(result.details["initialization"][0]["outcome"], "failed")
        self.assertIsNone(node.reserved_for_session_id)

    async def test_disconnected_controller_blocks_launch(self):
        communication = NatsControllerCommunication(NatsCommunicationBoundary("controller", "controller"))
        result = await self.controller.launch_session({}, communication=communication,
            participants=self.participants, config_parameters=self.config, result_window_s=0.01)
        self.assertFalse(result.succeeded)
        self.assertIn("NATS communication is not ready", result.error)

    async def test_jetstream_setup_includes_participant_and_session_commands(self):
        self.broker.stream_info = AsyncMock(side_effect=NotFoundError())
        self.broker.add_stream = AsyncMock()
        boundary = _Boundary("controller", "controller", self.broker)
        await boundary.ensure_streams()
        streams = {call.kwargs["config"].name: call.kwargs["config"].subjects for call in self.broker.add_stream.await_args_list}
        self.assertEqual(streams["LAB_COMMANDS"], ["messages.*.command.>", "messages.command.>"])
        self.assertEqual(streams["LAB_COMMAND_RESULTS"], ["messages.*.command_result.>", "messages.command_result.>"])
        self.assertEqual(streams["LAB_EVIDENCE"], ["messages.*.evidence.>"])

    async def test_node_abort_is_idempotent_and_preserves_finalized_artifacts(self):
        node, declaration, _ = await self.node()
        self.assertTrue(node.reserve("session-a"))
        self.assertTrue(node.initialize_session("session-a", [declaration]).ready)
        manager = node.local_storage_manager
        manifest = manager.create_stream(session_id="session-a", experiment_id="e", acquisition_node_id="node-a",
            source_component_id=declaration.device_id, data_product_id="events", artifact_type="event", schema={})
        manager.finalize_stream(manifest.storage_id)
        before = Path(manifest.local_storage_path).read_bytes()
        self.assertFalse(node.release_reservation("session-a"))
        self.assertTrue(node.abort_session_initialization("session-a"))
        self.assertTrue(node.abort_session_initialization("session-a"))
        self.assertTrue(node.release_reservation("session-a"))
        self.assertEqual(Path(manifest.local_storage_path).read_bytes(), before)

    async def test_nats_startup_failure_is_explicit_and_not_ready(self):
        boundary = NatsCommunicationBoundary("controller", "controller")
        with patch("lab_sync_acquisition.nats_communication.nats.connect", new=AsyncMock(side_effect=OSError("broker unavailable"))) as connect:
            with self.assertRaisesRegex(ConnectionError, "NATS startup connection failed"):
                await boundary.connect()
        self.assertFalse(boundary.check_ready().ready)
        self.assertEqual(connect.await_count, 1)


if __name__ == "__main__":
    unittest.main()
