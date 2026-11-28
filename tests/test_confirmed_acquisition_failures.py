"""Decision 458 workflows through real NATS and the existing runtime owners."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import unittest
import h5py
import numpy as np
from unittest.mock import patch
from unittest.mock import AsyncMock

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, DeviceDeclaration, ExperimentConfiguration,
    ScientificProductDeclaration, ScientificOutputSelection, RuntimeParticipant,
    NatsCommunicationBoundary, NatsAcquisitionNodeCommunication, ServiceMaintenanceInterface,
    ExperimentRuntimeHealthMapping, AcquisitionHealthPolicy,
)
from lab_sync_acquisition.device_adapter import _PartialScientificCollectionError
from tests.fakes import ReadyFakeAdapter
from tests import test_distributed_synchronization as timing


class FaultingScientificAdapter(ReadyFakeAdapter):
    """Real adapter lifecycle with deterministic device-local collection faults."""
    def __init__(self, identity, required):
        super().__init__(identity, "fake", ("events",), required)
        self.failure = None
        self.partial = False
        self.collections = 0

    def collect_products(self, products, **context):
        self.collections += 1
        result = {"scientific_products": {p.data_product_id: (({"frame": np.ones((2, 4, 3), dtype=np.uint16),
            "frame_index": self.collections - 1} if p.product_type == "camera_frames" else {"value": self.collections}),)
                                           for p in products}, "operational_evidence": ()}
        if self.failure:
            if self.partial:
                raise _PartialScientificCollectionError(self.failure, result)
            raise self.failure
        return result


class ConfirmedAcquisitionFailureTests(unittest.IsolatedAsyncioTestCase):
    async def workflow(self, required=(True, False, True), participants=None, *, delayed_health=None,
                       other_node=False, health_policies=(), hdf5_fault=False):
        f = timing.DistributedSynchronizationTests()
        f.addCleanup, f.addAsyncCleanup = self.addCleanup, self.addAsyncCleanup
        await f.asyncSetUp()
        adapters = tuple(FaultingScientificAdapter(name, mandatory)
                         for name, mandatory in zip(("before", "fault", "after"), required))
        declarations = tuple(DeviceDeclaration(a.device_id, "fake", True, a.required, ("events",),
            ((ScientificProductDeclaration("events", "camera_frames", {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5")
              if hdf5_fault and a.device_id == "fault" else
              ScientificProductDeclaration("events", "event", {"value": "int"}, "jsonl")),)) for a in adapters)
        for adapter in adapters:
            adapter.initialize({})
        f.node = AcquisitionNode(device_manager=DeviceManager(adapters), node_id="node", role="acquisition",
            synchronization_source_id="sync", default_local_storage_root=f.root / "local",
            device_declarations=declarations, error_evidence_location=str(f.root / "errors"),
            acquisition_health_policies=health_policies)
        boundaries = await f._use_authorized_transport()
        selections = {"node": declarations}
        if other_node:
            extra_adapter = FaultingScientificAdapter("remote", True)
            extra_adapter.initialize({})
            extra_declaration = DeviceDeclaration("remote", "fake", True, True, ("events",),
                (ScientificProductDeclaration("events", "event", {"value": "int"}, "jsonl"),))
            extra = AcquisitionNode(device_manager=DeviceManager((extra_adapter,)), node_id="other", role="acquisition",
                synchronization_source_id="sync", default_local_storage_root=f.root / "other-local",
                device_declarations=(extra_declaration,), error_evidence_location=str(f.root / "errors"))
            boundary = NatsCommunicationBoundary("acquisition_node", "other",
                (boundaries["controller"]._client.connected_url.geturl(),))
            await boundary.connect()
            self.addAsyncCleanup(boundary.close)
            boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
            ServiceMaintenanceInterface(extra, RuntimeParticipant("acquisition_node", "other"),
                ingestor=f.ingestor, storage_manager=f.ingestor._storage_manager, preservation_window_s=.1,
                close_resources=AsyncMock(return_value=True))
            await NatsAcquisitionNodeCommunication(boundary, extra).subscribe_commands()
            f.participants = f.participants[:-1] + (RuntimeParticipant("acquisition_node", "other"), f.participants[-1])
            selections["other"] = (extra_declaration,)
            f.extra_node = extra

            def cleanup():
                if extra.status()["is_running"]:
                    extra.stop_runtime()
                if extra.local_storage_manager is not None:
                    extra.local_storage_manager.cleanup()
            self.addCleanup(cleanup)
        if delayed_health is not None:
            entered, resume = delayed_health
            subscribe = boundaries["controller"]._subscribe_jetstream

            async def delayed(subject, callback, **options):
                if (options.get("config").metadata or {}).get("purpose") == "health":
                    original = callback
                    async def receive(message):
                        body = json.loads(message.data)
                        if body.get("evidence_type") == "health_interpretation":
                            entered.set()
                            await resume.wait()
                        return await original(message)
                    callback = receive
                return await subscribe(subject, callback, **options)
            self.enterContext(patch.object(boundaries["controller"], "_subscribe_jetstream", side_effect=delayed))
        launch = f.controller.launch_session

        async def selected(*args, **kwargs):
            return await launch(selections, **kwargs)

        with patch.object(f.controller, "launch_session", side_effect=selected):
            await f.start()
        ids = list(participants or (a.device_id for a in adapters))
        participation = {"node": ids, **({"other": ["remote"]} if other_node else {})}
        config = ExperimentConfiguration(60, {node: 1000000 for node in participation}, 1000000,
                                       participating_devices=participation)
        outputs = tuple(ScientificOutputSelection(identity, "node", "events") for identity in ids)
        if other_node:
            outputs += (ScientificOutputSelection("remote", "other", "events"),)
        result = await f.controller.start_launched_experiment("experiment", configuration=config,
            scientific_outputs=outputs, storage_participant=f.participants[2])
        self.assertTrue(result.succeeded, result.error)
        return f, adapters, boundaries, config, outputs

    async def until(self, predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0)

    async def iteration(self, f):
        result = await f.communication.request_runtime_command(
            f.participants[-1], "run_one_iteration", f.sid, {}, 5)
        self.assertIsNotNone(result, "Iteration result delivery is unconfirmed")
        return result

    async def confirm_health(self, f):
        async with asyncio.timeout(5):
            while not await f.communication.confirm_session_health_processing(f.sid, f.controller):
                await asyncio.sleep(0)

    def rows(self, node, device):
        manager = node.local_storage_manager
        manifest = next(m for m in manager.manifests if m.source_component_id == device)
        manager.flush(manifest.storage_id)
        return [json.loads(line) for line in Path(manifest.local_storage_path).read_text().splitlines()]

    async def test_colliding_warning_policies_keep_sustained_scientific_collection(self):
        for label in ("warning", "informational"):
            with self.subTest(label=label):
                policy = AcquisitionHealthPolicy("decision_458",
                    {"first_evidence": {"record_kind": "event", "grace_window_s": 0}},
                    {"expected_acquisition_evidence_missing": label})
                f, adapters, _, _, _ = await self.workflow(health_policies=(policy,))
                f.node.activate_experiment_runtime_health_mapping("experiment", (
                    ExperimentRuntimeHealthMapping("fault", "fault", "decision_458", False, "event"),))
                adapter = adapters[1]
                collect = adapter.collect_products
                def initially_empty(products, **context):
                    if adapter.collections == 0:
                        adapter.collections += 1
                        return {"scientific_products": {p.data_product_id: () for p in products},
                                "operational_evidence": ()}
                    return collect(products, **context)
                transport = f.transport_handler
                self.addAsyncCleanup(transport._finish_evidence_publication)
                self.addAsyncCleanup(transport.stop_acquisition_execution)
                with patch.object(adapter, "collect_products", side_effect=initially_empty):
                    await transport.start_acquisition_execution()
                    try:
                        await self.until(lambda: adapters[0].collections >= 5)
                    finally:
                        await transport.stop_acquisition_execution()
                self.assertGreaterEqual(adapter.collections, 2)
                recorded = self.rows(f.node, "fault")
                self.assertTrue(recorded)
                self.assertEqual(recorded[0]["value"], 2)
                self.assertTrue(all(row["experiment_id"] == "experiment" for row in recorded))
                self.assertFalse(adapter.get_status().shutdown)
                await transport.publish_new_runtime_evidence()
                await self.confirm_health(f)
                interpretation, = f.node.health_runtime_evidence
                self.assertEqual(interpretation.payload["observation_type"], "expected_acquisition_evidence_missing")
                self.assertEqual(interpretation.payload["interpretation_label"], label)
                self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")

    async def test_colliding_configured_fatal_policy_keeps_existing_finalization_order(self):
        policy = AcquisitionHealthPolicy("decision_458",
            {"first_evidence": {"record_kind": "event", "grace_window_s": 0}},
            {"expected_acquisition_evidence_missing": "experiment_failure"})
        f, adapters, _, _, _ = await self.workflow(health_policies=(policy,))
        f.node.activate_experiment_runtime_health_mapping("experiment", (
            ExperimentRuntimeHealthMapping("fault", "fault", "decision_458", False, "event"),))
        with patch.object(adapters[1], "collect_products", return_value={
                "scientific_products": {"events": ()}, "operational_evidence": ()}):
            f.node.run_one_iteration()
        message, = f.node.health_runtime_evidence
        decision = f.controller.process_health_interpretation(message)
        self.assertEqual(decision.controller_decision, "experiment_fail")
        manager = f.node.local_storage_manager
        target = next(m.storage_id for m in manager.manifests if m.source_component_id == "fault")
        finalize = manager.finalize_stream
        def unavailable(identity):
            if identity == target:
                raise OSError("configured health finalization remains unconfirmed")
            return finalize(identity)
        with patch.object(manager, "finalize_stream", side_effect=unavailable):
            outcome = await f.controller.execute_launched_controller_action_decision(decision)
            self.assertFalse(outcome.succeeded)
            status = f.controller.get_status()
            self.assertEqual(status["active_experiment_id"], "experiment")
            self.assertFalse(any(e.event_type == "experiment_fail"
                                 for e in status["experiment_lifecycle_evidence"]))

    async def test_optional_failure_preserves_healthy_devices_in_both_orders(self):
        f, adapters, _, _, _ = await self.workflow()
        adapters[1].failure = OSError("optional read failed")
        result = await self.iteration(f)
        self.assertTrue(result.success, result.reason)
        result = await self.iteration(f)
        self.assertTrue(result.success, result.reason)
        self.assertEqual([a.collections for a in adapters], [2, 1, 2])
        self.assertTrue(adapters[1].get_status().shutdown)
        self.assertEqual(len(self.rows(f.node, "before")), 2)
        self.assertEqual(len(self.rows(f.node, "after")), 2)
        self.assertFalse(f.node.status()["failed"])
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")

    async def test_mandatory_failure_ends_experiment_not_session_and_deduplicates(self):
        f, adapters, boundaries, _, _ = await self.workflow(required=(True, True, True))
        adapters[1].failure = OSError("mandatory read failed")
        self.assertTrue((await self.iteration(f)).success)
        await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
        status = f.controller.get_status()
        self.assertEqual(status["session_state"], "running")
        self.assertEqual(sum(e.event_type == "experiment_fail" for e in status["experiment_lifecycle_evidence"]), 1)
        message = next(m for m in f.node.runtime_evidence if m.evidence_type == "health_interpretation")
        await boundaries["node"].publish_evidence(message)
        await self.confirm_health(f)
        self.assertEqual(len(f.controller.controller_action_decisions), 1)

    async def test_partial_optional_collection_is_preserved_before_cleanup(self):
        f, adapters, _, _, _ = await self.workflow()
        adapters[1].failure, adapters[1].partial = OSError("read after partial data"), True
        self.assertTrue((await self.iteration(f)).success)
        self.assertEqual(len(self.rows(f.node, "fault")), 1)
        self.assertEqual(len(self.rows(f.node, "after")), 1)

    async def test_partial_hdf5_scientific_data_survives_optional_device_cleanup(self):
        f, adapters, _, _, _ = await self.workflow(hdf5_fault=True)
        adapters[1].failure, adapters[1].partial = OSError("camera failed after one frame"), True
        self.assertTrue((await self.iteration(f)).success)
        manifest = next(m for m in f.node.local_storage_manager.manifests if m.source_component_id == "fault")
        self.assertEqual(manifest.lifecycle_state, "finalized")
        with h5py.File(manifest.local_storage_path, "r") as recorded:
            np.testing.assert_array_equal(recorded["frames"][:], np.ones((1, 2, 4, 3), dtype=np.uint16))
            row = json.loads(recorded["record_metadata_json"][0])
            self.assertEqual(recorded.attrs["artifact_manifest_id"], manifest.artifact_manifest_id)
            self.assertEqual(manifest.source_component_id, "fault")
            self.assertEqual(row["experiment_id"], "experiment")
            self.assertIn("session_time_s", row)
        self.assertEqual(len(self.rows(f.node, "after")), 1)

    async def test_recording_failure_preserves_completed_rows_and_other_devices(self):
        f, _, _, _, _ = await self.workflow()
        manager = f.node.local_storage_manager
        failed = next(m.storage_id for m in manager.manifests if m.source_component_id == "fault")
        append = manager.append_rows

        def write(identity, rows):
            append(identity, rows)
            if identity == failed:
                raise OSError("recording confirmation failed after row")

        with patch.object(manager, "append_rows", side_effect=write):
            self.assertTrue((await self.iteration(f)).success)
        self.assertEqual(len(self.rows(f.node, "fault")), 1)
        self.assertEqual(len(self.rows(f.node, "after")), 1)
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")

    async def test_unconfirmed_finalization_does_not_suppress_mandatory_experiment_failure(self):
        f, adapters, _, _, _ = await self.workflow(required=(True, True, True))
        adapters[1].failure = OSError("mandatory acquisition lost")
        manager = f.node.local_storage_manager
        failed = next(m.storage_id for m in manager.manifests if m.source_component_id == "fault")
        finalize = manager.finalize_stream
        def incomplete(identity):
            if identity == failed:
                raise OSError("scientific finalization remains unconfirmed")
            return finalize(identity)
        with patch.object(manager, "finalize_stream", side_effect=incomplete):
            self.assertTrue((await self.iteration(f)).success)
            await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
            self.assertEqual(f.controller.get_status()["session_state"], "running")
            self.assertTrue(any(e.event_type == "experiment_fail"
                                for e in f.controller.get_status()["experiment_lifecycle_evidence"]))
            # Canonical failure is not a claim of cleanup, safe ACK or preservation.
            self.assertFalse(await f.communication.confirm_session_health_processing(f.sid, f.controller))
            outcome = await f.controller.normal_stop_session(communication=f.communication,
                storage_participant=f.participants[2], result_window_s=1)
            self.assertFalse(outcome.succeeded)
            self.assertFalse(outcome.details.get("preservation_confirmed"))

    async def test_expiry_finalization_failure_is_accounted_without_false_expiry_success(self):
        f, _, _, _, _ = await self.workflow(required=(True, True, True))
        self.assertTrue((await self.iteration(f)).success)
        context = f.node.status()["active_experiment_runtime_context"]
        deadline = f.node.activate_experiment_runtime(context, ())
        manager = f.node.local_storage_manager
        failed = next(m.storage_id for m in manager.manifests if m.source_component_id == "fault")
        finalize = manager.finalize_stream
        def incomplete(identity):
            if identity == failed:
                raise OSError("expiry write finalization failed")
            return finalize(identity)
        with patch.object(manager, "finalize_stream", side_effect=incomplete), patch(
                "lab_sync_acquisition.acquisition_node.monotonic", return_value=deadline["local_deadline_s"] + 1):
            with self.assertRaises(RuntimeError):
                f.node.expire_experiment_if_due()
        self.assertFalse(f.node.read_experiment_expiry("experiment").payload["finalization_confirmed"])
        self.assertTrue((await self.iteration(f)).success)
        await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
        await self.confirm_health(f)
        self.assertTrue(any(e.event_type == "experiment_fail"
                            for e in f.controller.get_status()["experiment_lifecycle_evidence"]))
        self.assertEqual(f.controller.get_status()["session_state"], "running")
        # A valid negative owner report is not successful expiry proof and must
        # not become an impossible-to-acknowledge delivery obligation.
        async with asyncio.timeout(3):
            for subscription in f.controller._launch_subscriptions:
                if hasattr(subscription, "_session_responsibility"):
                    while (info := await subscription.consumer_info()).num_pending or info.num_ack_pending:
                        await asyncio.sleep(0)

    async def test_shared_recording_failure_uses_actually_affected_participants(self):
        for required in ((False, False, False), (True, False, False)):
            with self.subTest(required=required):
                f, adapters, _, _, _ = await self.workflow(required=required)
                with patch.object(f.node.local_storage_manager, "append_rows", side_effect=OSError("shared volume failed")):
                    self.assertTrue((await self.iteration(f)).success)
                if any(required):
                    await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
                else:
                    self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
                self.assertEqual(f.controller.get_status()["session_state"], "running")
                self.assertTrue(all(a.get_status().shutdown for a in adapters))
                await self.confirm_health(f)

    async def test_nonparticipant_failure_is_not_collected_or_interpreted(self):
        f, adapters, _, _, _ = await self.workflow(participants=("before", "after"))
        adapters[1].failure = OSError("unused device failed")
        self.assertTrue((await self.iteration(f)).success)
        self.assertEqual(adapters[1].collections, 0)
        self.assertFalse(any(m.evidence_type == "health_interpretation" for m in f.node.runtime_evidence))

    async def test_failure_evidence_does_not_require_current_synchronization_mapping(self):
        f, adapters, _, _, _ = await self.workflow(required=(True, True, True))
        adapters[1].failure = OSError("mandatory read failed without mapping")
        mapping = f.node.status()["active_synchronization_mapping"]
        try:
            f.node.receive_active_synchronization_mapping(None)
            self.assertTrue((await self.iteration(f)).success)
            await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
            failure = next(m for m in f.node.runtime_evidence if m.evidence_type == "health_interpretation")
            self.assertIsNone(failure.payload["session_time_s"])
            self.assertEqual(failure.payload["live_source_id"], "fault")
            await self.confirm_health(f)
        finally:
            f.node.receive_active_synchronization_mapping(mapping)

    async def test_delayed_failure_cannot_terminate_subsequent_experiment(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        f, adapters, _, config, outputs = await self.workflow(required=(True, True, True), delayed_health=(entered, resume))
        try:
            adapters[1].failure = OSError("delayed mandatory read failure")
            self.assertTrue((await self.iteration(f)).success)
            await asyncio.wait_for(entered.wait(), 2)
            self.assertFalse(f.controller.controller_action_decision_evidence)
            ended = await f.controller.stop_launched_experiment("experiment")
            self.assertTrue(ended.succeeded, ended.error)
            started = await f.controller.start_launched_experiment("next", configuration=replace(config,
                participating_devices={"node": ["before", "after"]}),
                scientific_outputs=tuple(o for o in outputs if o.source_device_id != "fault"),
                storage_participant=f.participants[2])
            self.assertTrue(started.succeeded, started.error)
            resume.set()
            await self.confirm_health(f)
            self.assertTrue(f.controller.controller_action_decision_evidence[0].payload["details"]["historical_scientific_failure"])
            self.assertEqual(f.controller.get_status()["active_experiment_id"], "next")
        finally:
            resume.set()

    async def test_conflicting_health_policy_cannot_downgrade_mandatory_failure(self):
        policy = AcquisitionHealthPolicy("ignore",
            {"first_evidence": {"record_kind": "event", "grace_window_s": 0}},
            {"expected_acquisition_evidence_missing": "informational"})
        f, adapters, _, _, _ = await self.workflow(required=(True, True, True), health_policies=(policy,))
        f.node.activate_experiment_runtime_health_mapping("experiment", (
            ExperimentRuntimeHealthMapping("fault", "fault", "ignore", False, "event"),))
        adapters[1].failure = OSError("mandatory despite policy")
        self.assertTrue((await self.iteration(f)).success)
        await self.until(lambda: f.controller.get_status()["active_experiment_id"] is None)
        await self.confirm_health(f)
        self.assertEqual(f.controller.get_status()["session_state"], "running")

    async def test_shared_optional_node_failure_does_not_stop_another_node(self):
        f, _, _, _, _ = await self.workflow(required=(False, False, False), other_node=True)
        with patch.object(f.node.local_storage_manager, "append_rows", side_effect=OSError("primary volume unavailable")):
            self.assertTrue((await self.iteration(f)).success)
        for _ in range(2):
            result = await f.communication.request_runtime_command(RuntimeParticipant("acquisition_node", "other"),
                "run_one_iteration", f.sid, {}, 5)
            self.assertTrue(result.success, result.reason)
        await self.confirm_health(f)
        self.assertEqual(len(self.rows(f.extra_node, "remote")), 2)
        self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")

    async def test_blocked_failure_publication_does_not_block_healthy_collection(self):
        f, adapters, boundaries, _, _ = await self.workflow()
        adapters[1].failure = OSError("optional read failed offline")
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = boundaries["node"].publish_evidence
        async def blocked(message):
            if message.evidence_type == "health_interpretation":
                entered.set()
                await resume.wait()
            return await publish(message)
        with patch.object(boundaries["node"], "publish_evidence", side_effect=blocked):
            requested = asyncio.create_task(self.iteration(f))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                f.node.run_one_iteration()
                self.assertEqual(len(self.rows(f.node, "after")), 2)
                self.assertEqual(f.controller.get_status()["active_experiment_id"], "experiment")
            finally:
                resume.set()
                self.assertTrue((await requested).success)
        await self.confirm_health(f)


if __name__ == "__main__":
    unittest.main()
