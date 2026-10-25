"""Scientific timing and Experiment operations across independent NATS owners."""

import asyncio
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsCommunicationBoundary, NatsControllerCommunication,
    NatsIngestorCommunication, NatsSynchronizationManagerCommunication, RuntimeParticipant,
    ScientificOutputSelection, ScientificProductDeclaration, SynchronizationConfiguration,
    ExperimentRuntimeHealthMapping,
    SynchronizationManager,
    ExperimentConfiguration, PersistentStorageManager, NatsStorageManagerCommunication,
)
from tests.test_session_launch import _Boundary, _Broker, _CollectingAdapter
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


def configuration(**changes):
    return SynchronizationConfiguration(**{
        "exchanges": 3, "initial_scale": 1.0, "clock_rate_error_bound": 0.001,
        "max_uncertainty_s": 0.5, "max_mapping_age_s": 20.0,
        "assessment_interval_s": 5.0, "result_window_s": 2.0,
        "quality_interpretation": "warning", **changes}).to_dict()


def declaration():
    return DeviceDeclaration("device", "fake", True, True, ("events",), (
        ScientificProductDeclaration("events", "event", {"value": "int"}, "jsonl"),))


class DistributedSynchronizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.broker = _Broker()
        self.sync = SynchronizationManager()
        self.sync_handler = NatsSynchronizationManagerCommunication(
            _Boundary("synchronization_manager", "sync", self.broker), self.sync)
        await self.sync_handler.subscribe_commands()
        self.ingestor = InMemoryIngestor(recovery_journal_root=self.root / "journals")
        storage = self.ingestor._storage_manager or PersistentStorageManager(self.root / "storage")
        self.ingestor._storage_manager = storage
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), storage).subscribe_commands()
        self.ingestor_handler = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        await self.ingestor_handler.subscribe_commands()
        adapter = _CollectingAdapter("device", "fake", ("events",), True)
        adapter.initialize({})
        self.node = AcquisitionNode(device_manager=DeviceManager((adapter,)),
            node_id="node", role="acquisition", synchronization_source_id="sync",
            default_local_storage_root=self.root / "local", device_declarations=(declaration(),),
            error_evidence_location=str(self.root / "errors"))
        self.handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", self.broker), self.node)
        await self.handler.subscribe_commands()
        self.controller = Controller()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.participants = (RuntimeParticipant("ingestor", "ingestor"),
            RuntimeParticipant("synchronization_manager", "sync"), RuntimeParticipant("acquisition_node", "node"))
        self.config = {"storage_location": str(self.root / "records"), "protocol_plan": {"name": "test"},
            "error_evidence_location": str(self.root / "errors"),
            "synchronization_configuration": configuration()}
        self.addCleanup(self.cleanup_node)
        self.addAsyncCleanup(self.sync_handler.close)

    def cleanup_node(self):
        if self.node.status()["is_running"]:
            self.node.stop_runtime()
        if self.node.local_storage_manager is not None:
            self.node.local_storage_manager.cleanup()

    async def launch(self):
        result = await self.controller.launch_session({"node": (declaration(),)},
            communication=self.communication, participants=self.participants,
            config_parameters=self.config, result_window_s=2)
        self.assertTrue(result.succeeded, result.error)
        self.sid = result.details["session_id"]
        return result

    async def start(self):
        await self.launch()
        result = await self.controller.start_launched_session()
        self.assertTrue(result.succeeded, result.error)

    async def request(self, target, operation, payload=None, **kwargs):
        return await self.communication.request_runtime_command(target, operation,
            self.sid, payload or {}, 0.02, **kwargs)

    async def experiment(self, name="experiment"):
        result = await self.controller.start_launched_experiment(name,
            scientific_outputs=(ScientificOutputSelection("device", "node", "events"),),
            configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000, participating_devices={"node": ["device"]}),
            storage_participant=RuntimeParticipant("storage_manager", "storage"))
        self.assertTrue(result.succeeded, result.error)

    async def test_measured_mapping_drives_local_science_and_experiment_finalization(self):
        await self.start()
        await self.experiment()
        result = await self.request(self.participants[-1], "run_one_iteration")
        self.assertTrue(result.success, result.reason)
        local = self.node.local_storage_manager
        stopped = await self.controller.stop_launched_experiment("experiment")
        self.assertTrue(stopped.succeeded, stopped.error)
        row = json.loads(Path(local.manifests[0].local_storage_path).read_text())
        activation = self.node.mapping_activation_history[0]
        mapping = activation["mapping"]
        self.assertAlmostEqual(row["session_time_s"], mapping["session_time_anchor_s"] +
            mapping["scale"] * (row["acquisition_node_local_time_s"] - mapping["local_time_anchor_s"]))
        self.assertGreaterEqual(row["acquisition_node_local_time_s"], activation["activated_local_time_s"])
        start = self.controller._session.experiment_lifecycle_evidence[0]
        self.assertAlmostEqual(row["experiment_time_s"], row["session_time_s"] - start.session_time_s)
        self.assertEqual(row["timestamp_status"], "runtime_timestamped")
        self.assertEqual(row["value"], 1)
        self.assertEqual(local.manifests[0].lifecycle_state, "finalized")
        self.assertTrue(self.ingestor.accepted_runtime_evidence)
        self.assertTrue(all("value" not in message.payload for message in self.ingestor.accepted_runtime_evidence))
        self.assertFalse(any(message.evidence_type == "scientific_observation"
                             for message in self.ingestor.accepted_runtime_evidence))
        self.assertEqual(len(self.sync.mapping_update_evidence), 1)
        self.assertTrue(any(m.evidence_type == "mapping_activation" for m in self.node.runtime_evidence))
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)

    async def test_quality_assessment_does_not_replace_mapping_but_resynchronization_does(self):
        await self.start()
        mapping = self.node.status()["active_synchronization_mapping"]
        assessed = await self.request(self.participants[1], "assess_synchronization", {"node_ids": ["node"]})
        self.assertTrue(assessed.success, assessed.reason)
        self.assertEqual(self.node.status()["active_synchronization_mapping"], mapping)
        self.assertEqual(len(self.node.mapping_activation_history), 1)
        await self.experiment()
        await self.request(self.participants[-1], "run_one_iteration")
        await self.advance_local_clock(monotonic())
        refreshed = await self.request(self.participants[1], "resynchronize", {"node_ids": ["node"]})
        self.assertTrue(refreshed.success, refreshed.reason)
        await self.request(self.participants[-1], "run_one_iteration")
        self.assertEqual(len(self.node.mapping_activation_history), 2)
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        rows = [json.loads(line) for line in Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text().splitlines()]
        for row, activation in zip(rows, self.node.mapping_activation_history):
            mapping = activation["mapping"]
            self.assertAlmostEqual(row["session_time_s"], mapping["session_time_anchor_s"] +
                mapping["scale"] * (row["acquisition_node_local_time_s"] - mapping["local_time_anchor_s"]))

    async def test_missing_synchronization_prevents_acquisition(self):
        await self.launch()
        result = await self.request(self.participants[-1], "start_runtime")
        self.assertFalse(result.success)
        self.assertFalse(self.node.status()["is_running"])

    async def test_expired_mapping_preserves_science_with_degraded_status_and_policy(self):
        await self.start()
        await self.experiment()
        quality = deepcopy(self.sync._measured_mapping_quality["node"])
        quality["acceptable"] = False
        quality["assessment_sequence"] += 1
        requester = NatsControllerCommunication(self.sync_handler._boundary)
        result = await requester.request_runtime_command(self.participants[-1], "accept_synchronization_quality",
            self.sid, {"quality": quality}, 1)
        self.assertTrue(result.success)
        result = await self.request(self.participants[-1], "run_one_iteration")
        self.assertTrue(result.success, result.reason)
        self.assertTrue(self.node.status()["is_running"])
        rejected = await self.controller.start_launched_experiment("other")
        self.assertFalse(rejected.succeeded)
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        row = json.loads(Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text())
        self.assertEqual(row["timestamp_status"], "synchronization_degraded")
        interpretation, = [m for m in self.node.runtime_evidence if m.evidence_type == "timing_quality_interpretation"]
        decision = self.controller.process_timing_quality_interpretation(interpretation)
        self.assertEqual(decision["controller_decision"], "record_warning")
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_authority_and_session_mismatches_cannot_change_mapping(self):
        await self.start()
        original = self.node.status()["active_synchronization_mapping"]
        quality = deepcopy(self.sync._measured_mapping_quality["node"])
        result = await self.request(self.participants[-1], "accept_synchronization_quality", {"quality": quality})
        self.assertFalse(result.success)
        with self.assertRaises(ValueError):
            await self.communication.request_runtime_command(self.participants[-1], "read_local_time", "", {}, 1)
        requester = NatsControllerCommunication(self.sync_handler._boundary)
        result = await requester.request_runtime_command(self.participants[-1], "accept_synchronization_quality",
            "unrelated", {"quality": quality}, 1)
        self.assertFalse(result.success)
        self.assertEqual(original, self.node.status()["active_synchronization_mapping"])

    async def test_missing_and_stale_results_do_not_confirm_runtime_work(self):
        await self.start()
        self.broker.change_result = lambda operation, result: {
            **result, "payload": {**result["payload"], "request_nonce": "old-attempt"}}
        result = await self.request(self.participants[1], "read_session_time")
        self.assertIsNone(result)
        self.broker.change_result = None
        self.broker.drop_results.add(("sync", "read_session_time"))
        self.assertIsNone(await self.request(self.participants[1], "read_session_time"))

    async def test_missing_measurement_blocks_experiment_start(self):
        self.config["synchronization_configuration"] = configuration(result_window_s=0.01)
        await self.start()
        self.broker.drop_results.add(("node", "read_local_time"))
        result = await self.controller.start_launched_experiment("experiment")
        self.assertFalse(result.succeeded)
        self.assertFalse(self.controller._session.experiment_lifecycle_evidence)

    async def test_periodic_quality_failure_is_recorded_without_stopping_acquisition(self):
        self.config["synchronization_configuration"] = configuration(assessment_interval_s=0.02, result_window_s=0.01)
        await self.start()
        await self.experiment()
        delivered = asyncio.Event()
        def observe(command):
            if command["command_type"] == "accept_synchronization_quality" and not command["payload"]["quality"]["acceptable"]:
                delivered.set()
        self.broker.on_command = observe
        self.broker.drop_results.add(("node", "read_local_time"))
        await asyncio.wait_for(delivered.wait(), 2)
        self.assertTrue(self.node.status()["is_running"])
        self.assertTrue(any(m.evidence_type == "timing_quality_interpretation" for m in self.node.runtime_evidence))
        self.assertFalse(self.node.check_node_readiness().ready)

    async def test_expiry_keeps_local_timing_when_authority_cannot_be_reached(self):
        await self.start()
        await self.experiment()
        until = self.sync._measured_mapping_quality["node"]["valid_until_local_time_s"]
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=until + 1):
            result = await self.request(self.participants[-1], "run_one_iteration")
            self.assertTrue(result.success)
            self.assertFalse(self.node.check_node_readiness().ready)
        await self.controller.stop_launched_experiment("experiment")
        row = json.loads(Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text())
        self.assertEqual(row["timestamp_status"], "synchronization_degraded")
        self.assertIn("acquisition_node_local_time_s", row)

    async def test_publication_failure_withholds_finalization_confirmation_and_retry_does_not_rewrite(self):
        await self.start()
        await self.experiment()
        await self.request(self.participants[-1], "run_one_iteration")
        publish = self.handler._boundary.publish_evidence
        async def fail_finalized(message):
            if message.evidence_type == "artifact_manifest" and message.payload["lifecycle_state"] == "finalized":
                raise OSError("Injected finalized manifest publication failure")
            await publish(message)
        with patch.object(self.handler._boundary, "publish_evidence", side_effect=fail_finalized):
            result = await self.controller.stop_launched_experiment("experiment")
        self.assertFalse(result.succeeded)
        manifest = self.node.local_storage_manager.manifests[0]
        original = Path(manifest.local_storage_path).read_bytes()
        self.assertEqual(self.controller._active_experiment_id, "experiment")
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        self.assertEqual(Path(manifest.local_storage_path).read_bytes(), original)
        self.assertEqual(len(original.splitlines()), 1)

    async def test_cancelled_context_delivery_records_abort_and_cleans_prepared_outputs(self):
        await self.start()
        reached = asyncio.Event()
        release = asyncio.Event()
        publish = self.handler._boundary.publish_command_result
        async def pause(result, operation):
            if operation == "activate_experiment_runtime":
                reached.set()
                await release.wait()
            return await publish(result, operation)
        with patch.object(self.handler._boundary, "publish_command_result", side_effect=pause):
            task = asyncio.create_task(self.controller.start_launched_experiment("experiment",
                scientific_outputs=(ScientificOutputSelection("device", "node", "events"),),
                configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000, participating_devices={"node": ["device"]}),
                storage_participant=RuntimeParticipant("storage_manager", "storage")))
            await asyncio.wait_for(reached.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(self.node.status()["active_experiment_runtime_context"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.node.local_storage_manager.manifests))
        self.assertEqual([e.event_type for e in self.controller._session.experiment_lifecycle_evidence],
                         ["experiment_start", "experiment_abort"])

    async def test_historical_quality_cannot_replace_new_mapping_or_activation_provenance(self):
        await self.start()
        old = deepcopy(self.sync._measured_mapping_quality["node"])
        await self.advance_local_clock(monotonic())
        await self.request(self.participants[1], "resynchronize", {"node_ids": ["node"]})
        current = self.node.status()["active_synchronization_mapping"]
        old["measured_local_time_s"] -= 1
        result = await NatsControllerCommunication(self.sync_handler._boundary).request_runtime_command(
            self.participants[-1], "accept_synchronization_quality", self.sid, {"quality": old}, 1)
        self.assertFalse(result.success)
        self.assertEqual(self.node.status()["active_synchronization_mapping"], current)
        self.assertEqual(len(self.node.mapping_activation_history), 2)

    async def test_repeated_session_start_never_resets_clock_or_existing_node_runtime(self):
        await self.start()
        initial = self.node.status()["active_synchronization_mapping"]
        result = await self.controller.start_launched_session()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.node.status()["is_running"])
        self.assertEqual(self.node.status()["active_synchronization_mapping"], initial)

    async def test_buffered_observation_uses_its_local_mapping_boundary_and_preserves_native_time(self):
        await self.start()
        await self.experiment()
        original = self.node.status()["active_synchronization_mapping"]
        observed_at = monotonic()
        await self.advance_local_clock(observed_at)
        result = await self.request(self.participants[1], "resynchronize", {"node_ids": ["node"]})
        self.assertTrue(result.success, result.reason)
        def buffered(products, **context):
            return {"scientific_products": {p.data_product_id: [{"value": 1,
                "acquisition_node_local_time_s": observed_at, "device_local_time": 77.5}] for p in products},
                "operational_evidence": ()}
        adapter = self.node._device_manager.adapters[0]
        with patch.object(adapter, "collect_products", side_effect=buffered):
            self.assertTrue((await self.request(self.participants[-1], "run_one_iteration")).success)
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        row = json.loads(Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text())
        self.assertEqual(row["acquisition_node_local_time_s"], observed_at)
        self.assertEqual(row["device_local_time"], 77.5)
        self.assertAlmostEqual(row["session_time_s"], original.session_time_anchor_s +
                               original.scale * (observed_at - original.local_time_anchor_s))

    async def collect_buffered(self, rows):
        def buffered(products, **context):
            return {"scientific_products": {p.data_product_id: rows for p in products},
                    "operational_evidence": ()}
        with patch.object(self.node._device_manager.adapters[0], "collect_products", side_effect=buffered):
            result = await self.request(self.participants[-1], "run_one_iteration")
        self.assertTrue(result.success, result.reason)

    async def advance_local_clock(self, previous):
        async def advanced():
            while monotonic() <= previous:
                await asyncio.sleep(0)
        await asyncio.wait_for(advanced(), 2)

    async def test_buffered_degraded_observation_stays_degraded_after_recovery(self):
        await self.start()
        await self.experiment()
        await self.request(self.participants[-1], "run_one_iteration")
        local = self.node.local_storage_manager
        manifest = local.manifests[0]
        local.flush(manifest.storage_id)
        original_bytes = Path(manifest.local_storage_path).read_bytes()
        mapping = self.node.status()["active_synchronization_mapping"]
        quality = self.sync.mark_synchronization_unavailable(self.sid, "node", "sync", "missed assessment")
        requester = NatsControllerCommunication(self.sync_handler._boundary)
        result = await requester.request_runtime_command(self.participants[-1], "accept_synchronization_quality",
            self.sid, {"quality": quality}, 1)
        self.assertTrue(result.success, result.reason)
        observed_at = monotonic()
        interpretation_ids = {m.evidence_id for m in self.node.runtime_evidence
                              if m.evidence_type == "timing_quality_interpretation"}
        await self.advance_local_clock(observed_at)
        result = await self.request(self.participants[1], "resynchronize", {"node_ids": ["node"]})
        self.assertTrue(result.success, result.reason)
        await self.collect_buffered([{"value": 2, "acquisition_node_local_time_s": observed_at,
                                     "device_timestamp": 123.5}])
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        content = Path(manifest.local_storage_path).read_bytes()
        self.assertTrue(content.startswith(original_bytes))
        first, buffered = [json.loads(line) for line in content.splitlines()]
        self.assertEqual(first["timestamp_status"], "runtime_timestamped")
        self.assertEqual(buffered["timestamp_status"], "synchronization_degraded")
        self.assertEqual(buffered["acquisition_node_local_time_s"], observed_at)
        self.assertEqual(buffered["device_timestamp"], 123.5)
        self.assertAlmostEqual(buffered["session_time_s"], mapping.session_time_anchor_s +
                               mapping.scale * (observed_at - mapping.local_time_anchor_s))
        self.assertEqual(interpretation_ids, {m.evidence_id for m in self.node.runtime_evidence
                                             if m.evidence_type == "timing_quality_interpretation"})

    async def test_buffered_valid_observation_stays_valid_after_degradation(self):
        await self.start()
        await self.experiment()
        observed_at = monotonic()
        quality = self.sync.mark_synchronization_unavailable(self.sid, "node", "sync", "missed assessment")
        requester = NatsControllerCommunication(self.sync_handler._boundary)
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=observed_at + 1):
            result = await requester.request_runtime_command(self.participants[-1], "accept_synchronization_quality",
                self.sid, {"quality": quality}, 1)
            self.assertTrue(result.success, result.reason)
            await self.collect_buffered([{"value": 1, "acquisition_node_local_time_s": observed_at}])
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        row = json.loads(Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text())
        self.assertEqual(row["timestamp_status"], "runtime_timestamped")

    async def test_buffered_observations_preserve_expiry_boundary_after_remapping(self):
        await self.start()
        await self.experiment()
        expiry = self.sync._measured_mapping_quality["node"]["valid_until_local_time_s"]
        mapping = self.node.status()["active_synchronization_mapping"]
        observed_times = (expiry - .001, expiry, expiry + .001)
        # Advance only the node clock; the measured exchange observes its new offset.
        with patch("lab_sync_acquisition.acquisition_node.monotonic", return_value=expiry + 1), \
                patch("lab_sync_acquisition.nats_communication.monotonic", return_value=expiry + 1):
            result = await self.request(self.participants[1], "resynchronize", {"node_ids": ["node"]})
            self.assertTrue(result.success, result.reason)
            await self.collect_buffered([{"value": index, "acquisition_node_local_time_s": observed_at}
                                         for index, observed_at in enumerate(observed_times)])
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        rows = [json.loads(line) for line in Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text().splitlines()]
        self.assertEqual([row["timestamp_status"] for row in rows],
                         ["runtime_timestamped", "runtime_timestamped", "synchronization_degraded"])
        for row, observed_at in zip(rows, observed_times):
            self.assertAlmostEqual(row["session_time_s"], mapping.session_time_anchor_s +
                                   mapping.scale * (observed_at - mapping.local_time_anchor_s))

    async def test_buffered_degraded_observation_stays_degraded_after_reassessment(self):
        await self.start()
        await self.experiment()
        mapping = self.node.status()["active_synchronization_mapping"]
        quality = self.sync.mark_synchronization_unavailable(self.sid, "node", "sync", "missed assessment")
        requester = NatsControllerCommunication(self.sync_handler._boundary)
        self.assertTrue((await requester.request_runtime_command(self.participants[-1],
            "accept_synchronization_quality", self.sid, {"quality": quality}, 1)).success)
        observed_at = monotonic()
        await self.advance_local_clock(observed_at)
        result = await self.request(self.participants[1], "assess_synchronization", {"node_ids": ["node"]})
        self.assertTrue(result.success, result.reason)
        self.assertEqual(self.node.status()["active_synchronization_mapping"], mapping)
        retained = self.node.runtime_evidence
        self.assertTrue((await requester.request_runtime_command(self.participants[-1],
            "accept_synchronization_quality", self.sid, {"quality": result.payload["qualities"][0]}, 1)).success)
        self.assertEqual(self.node.runtime_evidence, retained)
        await self.collect_buffered([{"value": 1, "acquisition_node_local_time_s": observed_at}])
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)
        row = json.loads(Path(self.node.local_storage_manager.manifests[0].local_storage_path).read_text())
        self.assertEqual(row["timestamp_status"], "synchronization_degraded")
        applications = [m for m in self.ingestor.accepted_runtime_evidence if
                        m.source_id == "node" and m.evidence_type == "timing_quality_observation"]
        self.assertTrue(all(self.ingestor.has_durable_runtime_evidence(m) for m in applications))
        self.assertEqual([m.payload["quality"]["acceptable"] for m in applications], [True, True, False, True])

    async def test_periodic_publication_recovers_retained_evidence(self):
        self.config["synchronization_configuration"] = configuration(assessment_interval_s=.02)
        await self.start()
        baseline = {m.evidence_id for m in self.sync.session_timing_evidence(self.sid, "sync")}
        publish = self.sync_handler._boundary.publish_evidence
        failed, retrying, resume, recovered, subsequent = (asyncio.Event() for _ in range(5))
        self.addCleanup(resume.set)
        retained = []

        async def fail_once(message):
            if message.evidence_type == "timing_quality_observation" and message.evidence_id not in baseline:
                if not retained:
                    retained.append(deepcopy(message))
                    failed.set()
                    raise OSError("Injected periodic evidence publication failure")
                if message.evidence_id == retained[0].evidence_id:
                    self.assertEqual(message.to_dict(), retained[0].to_dict())
                    retrying.set()
                    await resume.wait()
                    await publish(message)
                    recovered.set()
                    return
                await publish(message)
                subsequent.set()
                return
            await publish(message)

        task = self.sync_handler._assessment_task
        with patch.object(self.sync_handler._boundary, "publish_evidence", side_effect=fail_once):
            await asyncio.wait_for(failed.wait(), 2)
            self.assertFalse(self.ingestor.has_durable_runtime_evidence(retained[0]))
            await asyncio.wait_for(retrying.wait(), 2)
            self.assertFalse(task.done())
            resume.set()
            await asyncio.wait_for(recovered.wait(), 2)
            await asyncio.wait_for(subsequent.wait(), 2)
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(retained[0]))
        self.assertEqual(sum(m.evidence_id == retained[0].evidence_id
                             for m in self.ingestor.accepted_runtime_evidence), 1)
        result = await self.request(self.participants[1], "start_runtime", {"node_ids": ["node"]})
        self.assertTrue(result.success, result.reason)
        self.assertIs(self.sync_handler._assessment_task, task)
        self.assertTrue(self.node.status()["is_running"])

    async def test_close_cancels_periodic_publication_recovery(self):
        self.config["synchronization_configuration"] = configuration(assessment_interval_s=.02)
        await self.start()
        baseline = {m.evidence_id for m in self.sync.session_timing_evidence(self.sid, "sync")}
        publish = self.sync_handler._boundary.publish_evidence
        failed, retrying, release = (asyncio.Event() for _ in range(3))
        self.addCleanup(release.set)

        async def fail_then_pause(message):
            if message.evidence_type == "timing_quality_observation" and message.evidence_id not in baseline:
                if not failed.is_set():
                    failed.set()
                    raise OSError("Injected periodic evidence publication failure")
                retrying.set()
                await release.wait()
            await publish(message)

        task = self.sync_handler._assessment_task
        with patch.object(self.sync_handler._boundary, "publish_evidence", side_effect=fail_then_pause):
            await asyncio.wait_for(retrying.wait(), 2)
            await asyncio.wait_for(self.sync_handler.close(), 2)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.sync_handler._assessment_task)
        self.assertTrue(self.sync.is_running)
        self.assertTrue(self.node.status()["is_running"])

    async def test_session_stop_publishes_retained_evidence_and_cancels_recovery(self):
        self.config["synchronization_configuration"] = configuration(assessment_interval_s=.02)
        await self.start()
        baseline = {m.evidence_id for m in self.sync.session_timing_evidence(self.sid, "sync")}
        publish = self.sync_handler._boundary.publish_evidence
        retrying, release = asyncio.Event(), asyncio.Event()
        self.addCleanup(release.set)
        task = self.sync_handler._assessment_task
        retained = []

        async def fail_then_pause(message):
            if (asyncio.current_task() is task and message.evidence_type == "timing_quality_observation"
                    and message.evidence_id not in baseline):
                if not retained:
                    retained.append(deepcopy(message))
                    raise OSError("Injected periodic evidence publication failure")
                retrying.set()
                await release.wait()
            await publish(message)

        with patch.object(self.sync_handler._boundary, "publish_evidence", side_effect=fail_then_pause):
            await asyncio.wait_for(retrying.wait(), 2)
            self.assertTrue((await self.controller.stop_launched_session()).succeeded)
            result = await self.request(self.participants[1], "stop_runtime")
            self.assertTrue(result.success, result.reason)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.sync_handler._assessment_task)
        self.assertFalse(self.sync.is_running)
        self.assertTrue(self.ingestor.has_durable_runtime_evidence(retained[0]))

    async def test_rejected_stop_preserves_monitoring_and_later_assessments(self):
        self.config["synchronization_configuration"] = configuration(assessment_interval_s=.02)
        await self.start()
        participant = self.participants[1]
        accepted = await self.request(participant, "read_session_time", command_id="clock-read")
        self.assertTrue(accepted.success, accepted.reason)
        task = self.sync_handler._assessment_task
        publishing, resume, assessed = (asyncio.Event() for _ in range(3))
        self.addCleanup(resume.set)
        publish = self.sync_handler._boundary.publish_evidence

        async def pause(message):
            if asyncio.current_task() is task and not publishing.is_set():
                publishing.set()
                await resume.wait()
            await publish(message)

        with patch.object(self.sync_handler._boundary, "publish_evidence", side_effect=pause):
            await asyncio.wait_for(publishing.wait(), 2)
            rejected = await asyncio.wait_for(self.request(participant, "stop_runtime", command_id="clock-read"), 2)
            self.assertFalse(rejected.success)
            self.assertIn("Conflicting synchronization command identity", rejected.reason)
            self.assertTrue(self.sync.is_running)
            self.assertTrue(self.node.status()["is_running"])
            self.assertIs(self.sync_handler._assessment_task, task)
            self.assertFalse(task.done())
            sequence = self.sync._measured_mapping_quality["node"]["assessment_sequence"]

            def observe(command):
                if (command["command_type"] == "accept_synchronization_quality"
                        and command["payload"]["quality"]["assessment_sequence"] > sequence):
                    assessed.set()

            self.broker.on_command = observe
            resume.set()
            await asyncio.wait_for(assessed.wait(), 2)
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        stopped = await self.request(participant, "stop_runtime")
        self.assertTrue(stopped.success, stopped.reason)
        self.assertFalse(self.sync.is_running)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.sync_handler._assessment_task)

    async def test_wrong_session_stop_preserves_running_monitoring(self):
        await self.start()
        task = self.sync_handler._assessment_task
        original = self.node.status()["active_synchronization_mapping"]
        rejected = await self.communication.request_runtime_command(self.participants[1], "stop_runtime",
            "other-session", {}, 1, command_id="wrong-session-stop")
        self.assertFalse(rejected.success)
        self.assertIn("Session mismatch", rejected.reason)
        self.assertTrue(self.sync.is_running)
        self.assertTrue(self.node.status()["is_running"])
        self.assertEqual(self.node.status()["active_synchronization_mapping"], original)
        self.assertIs(self.sync_handler._assessment_task, task)
        self.assertFalse(task.done())
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.request(self.participants[1], "stop_runtime")).success)
        self.assertTrue(task.cancelled())

    async def test_concurrent_duplicate_stops_preserve_identity_and_closeout(self):
        await self.start()
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        task = self.sync_handler._assessment_task
        publishing, resume, duplicate_sent = (asyncio.Event() for _ in range(3))
        self.addCleanup(resume.set)
        publish = self.sync_handler._boundary.publish_evidence

        async def pause(message):
            if not publishing.is_set():
                publishing.set()
                await resume.wait()
            await publish(message)

        with patch.object(self.sync_handler._boundary, "publish_evidence", side_effect=pause):
            first = asyncio.create_task(self.request(self.participants[1], "stop_runtime", command_id="stop-once"))
            await asyncio.wait_for(publishing.wait(), 2)
            self.broker.on_command = lambda command: duplicate_sent.set() if command["command_id"] == "stop-once" else None
            second = asyncio.create_task(self.request(self.participants[1], "stop_runtime", command_id="stop-once"))
            await asyncio.wait_for(duplicate_sent.wait(), 2)
            resume.set()
            first, second = await asyncio.wait_for(asyncio.gather(first, second), 2)
        self.assertTrue(first.success and second.success)
        self.assertEqual(first.result_id, second.result_id)
        self.assertEqual(first.payload["session_time_s"], second.payload["session_time_s"])
        self.assertEqual(sum(e.update_type == "retired" for e in self.sync.mapping_update_evidence), 1)
        preserved = self.sync.session_timing_evidence(self.sid, "sync")
        rejected = await self.request(self.participants[1], "read_session_time", command_id="stop-once")
        self.assertFalse(rejected.success)
        self.assertIn("Conflicting synchronization command identity", rejected.reason)
        self.assertEqual(self.sync.session_timing_evidence(self.sid, "sync"), preserved)
        self.assertFalse(self.sync.is_running)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.sync_handler._assessment_task)

    async def test_release_requires_quality_evidence_as_well_as_mapping_updates(self):
        await self.start()
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertTrue((await self.request(self.participants[1], "stop_runtime")).success)
        incomplete = InMemoryIngestor(session_id=self.sid, recovery_journal_path=self.root / "incomplete-journal")
        for message in self.ingestor.accepted_runtime_evidence:
            if message.evidence_type == "mapping_update_evidence":
                incomplete.receive_runtime_evidence(message)
        with self.assertRaisesRegex(RuntimeError, "quality evidence"):
            self.sync.release_session(self.sid, ingestor=incomplete)
        self.assertTrue(self.sync.release_session(self.sid, ingestor=self.ingestor))

    async def test_clock_readback_failure_after_node_release_can_be_retried_without_replaying_stop(self):
        await self.start()
        await self.experiment()
        self.broker.drop_results.add(("sync", "read_session_time"))
        self.controller._launch_result_window_s = 0.02
        result = await self.controller.stop_launched_session()
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.node.reserved_for_session_id)
        stops = len([c for c in self.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "node"])
        self.broker.drop_results.clear()
        self.assertTrue((await self.controller.stop_launched_session()).succeeded)
        self.assertEqual(stops, len([c for c in self.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "node"]))
        self.assertEqual(self.controller.get_status()["session_state"], "stopping")

    async def test_overlapping_session_start_does_not_reset_clock_or_abort_first_start(self):
        await self.launch()
        reached, release = asyncio.Event(), asyncio.Event()
        publish = self.sync_handler._boundary.publish_command_result
        async def pause(result, operation):
            if operation == "start_runtime":
                reached.set()
                await release.wait()
            return await publish(result, operation)
        with patch.object(self.sync_handler._boundary, "publish_command_result", side_effect=pause):
            first = asyncio.create_task(self.controller.start_launched_session())
            await asyncio.wait_for(reached.wait(), 2)
            second = await self.controller.start_launched_session()
            self.assertFalse(second.succeeded)
            release.set()
            self.assertTrue((await first).succeeded)
        self.assertTrue(self.node.status()["is_running"])

    async def test_two_nodes_receive_only_their_explicit_experiment_health_context(self):
        other_declaration = DeviceDeclaration("device-two", "fake", True, True, ("events",), declaration().scientific_products)
        adapter = _CollectingAdapter("device-two", "fake", ("events",), True)
        adapter.initialize({})
        other = AcquisitionNode(device_manager=DeviceManager((adapter,)), node_id="node-two", role="acquisition",
            synchronization_source_id="sync", default_local_storage_root=self.root / "other",
            device_declarations=(other_declaration,), error_evidence_location=str(self.root / "errors"))
        handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node-two", self.broker), other)
        await handler.subscribe_commands()
        def cleanup():
            if other.status()["is_running"]:
                other.stop_runtime()
            if other.local_storage_manager:
                other.local_storage_manager.cleanup()
        self.addCleanup(cleanup)
        result = await self.controller.launch_session({"node": (declaration(),), "node-two": (other_declaration,)},
            communication=self.communication, participants=(*self.participants, RuntimeParticipant("acquisition_node", "node-two")),
            config_parameters=self.config, result_window_s=2)
        self.assertTrue(result.succeeded, result.error)
        self.sid = result.details["session_id"]
        self.assertTrue((await self.controller.start_launched_session()).succeeded)
        first = ExperimentRuntimeHealthMapping("device", "device", "policy", True, "events")
        second = ExperimentRuntimeHealthMapping("device-two", "device-two", "policy", True, "events")
        result = await self.controller.start_launched_experiment("experiment",
            runtime_health_mapping={"node": (first,), "node-two": (second,)})
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(self.node.status()["active_experiment_runtime_health_mapping"], (first,))
        self.assertEqual(other.status()["active_experiment_runtime_health_mapping"], (second,))
        self.assertEqual(self.node.status()["active_experiment_runtime_context"], other.status()["active_experiment_runtime_context"])
        self.assertTrue((await self.controller.stop_launched_experiment("experiment")).succeeded)

    async def test_repeated_context_preserves_health_scope_and_conflicting_command_is_rejected(self):
        await self.start()
        await self.experiment()
        context = self.node.status()["active_experiment_runtime_context"].to_dict()
        payload = {"context": context, "health_mapping": []}
        result = await self.request(self.participants[-1], "activate_experiment_runtime", payload, command_id="context")
        repeated = await self.request(self.participants[-1], "activate_experiment_runtime", payload, command_id="context")
        self.assertTrue(result.success and repeated.success)
        bad = deepcopy(payload)
        bad["context"]["experiment_id"] = "wrong"
        self.assertFalse((await self.request(self.participants[-1], "activate_experiment_runtime", bad,
                                            command_id="context")).success)


class MeasuredClockBoundsTests(unittest.TestCase):
    def owner(self, **changes):
        owner = SynchronizationManager()
        owner.prepare_session("session")
        owner.configure_distributed_session("session", configuration(**changes))
        owner.start_distributed_session("session")
        return owner

    def test_offset_bound_accounts_for_asymmetric_delay_and_variability(self):
        owner = self.owner(max_uncertainty_s=2)
        samples = [{"sent_session_time_s": s, "received_local_time_s": 100 + s + delay,
                    "sent_local_time_s": 100 + s + delay + 0.01,
                    "received_session_time_s": s + 0.9, "local_clock_resolution_s": 0.0}
                   for s, delay in ((0, .1), (1, .7), (2, .2))]
        quality = owner.assess_cross_clock_exchanges("session", "node", samples,
            replace_mapping=True, source_id="sync")
        self.assertTrue(quality["acceptable"])
        mapping = quality["mapping"]
        actual = mapping["local_time_anchor_s"] - 100
        self.assertLessEqual(abs(mapping["session_time_anchor_s"] - actual), quality["uncertainty_s"])
        self.assertEqual(quality["exchanges"], samples)

    def test_inconsistent_or_invalid_exchanges_cannot_create_mapping(self):
        owner = self.owner()
        for samples in ([], [{"sent_session_time_s": 2, "received_local_time_s": 1,
                "sent_local_time_s": 0, "received_session_time_s": 1}] * 3):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                owner.assess_cross_clock_exchanges("session", "node", samples,
                    replace_mapping=True, source_id="sync")
        self.assertIsNone(owner.get_active_mapping("session", "node"))

    def test_configuration_requires_explicit_finite_bounds_and_policy(self):
        for change in ({"exchanges": 1}, {"max_uncertainty_s": float("nan")},
                       {"clock_rate_error_bound": -1}, {"quality_interpretation": "automatic_kill"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                configuration(**change)

    def test_timing_readback_snapshots_cannot_change_retained_evidence(self):
        owner = self.owner()
        samples = [{"sent_session_time_s": s, "received_local_time_s": 100 + s,
            "sent_local_time_s": 100 + s, "received_session_time_s": s + .01,
            "local_clock_resolution_s": 0.0} for s in (0, 1, 2)]
        owner.assess_cross_clock_exchanges("session", "node", samples, replace_mapping=True, source_id="sync")
        original = [m.to_dict() for m in owner.session_timing_evidence("session", "sync")]
        readback = owner.session_timing_evidence("session", "sync")
        readback[0].payload["new_mapping"]["scale"] = 50
        self.assertEqual([m.to_dict() for m in owner.session_timing_evidence("session", "sync")], original)


def run_participant(role, url, directory, ready, stop):
    """Separate-process harness: no owner object crosses the process boundary."""
    async def run():
        boundary = NatsCommunicationBoundary(role, "sync" if role == "synchronization_manager" else "node", servers=[url])
        await boundary.connect()
        await boundary.ensure_streams()
        if role == "synchronization_manager":
            handler = NatsSynchronizationManagerCommunication(boundary, SynchronizationManager())
            node = None
        else:
            adapter = _CollectingAdapter("device", "fake", ("events",), True)
            adapter.initialize({})
            node = AcquisitionNode(device_manager=DeviceManager((adapter,)), node_id="node", role="acquisition",
                synchronization_source_id="sync", default_local_storage_root=Path(directory) / "local",
                device_declarations=(declaration(),), error_evidence_location=directory)
            handler = NatsAcquisitionNodeCommunication(boundary, node)
        subscriptions = await handler.subscribe_commands()
        ready.send(True)
        try:
            await asyncio.to_thread(stop.wait)
        finally:
            if role == "synchronization_manager":
                await handler.close()
            else:
                for subscription in subscriptions:
                    await subscription.unsubscribe()
                if node.status()["is_running"]:
                    node.stop_runtime()
                if node.local_storage_manager:
                    node.local_storage_manager.cleanup()
            await boundary.close()
    asyncio.run(run())


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class CrossProcessTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_node_and_clock_preserve_local_scientific_timing(self):
        async with temporary_jetstream_server() as url:
            with tempfile.TemporaryDirectory() as directory:
                context = multiprocessing.get_context("spawn")
                workers = []
                try:
                    for role in ("synchronization_manager", "acquisition_node"):
                        parent, child = context.Pipe()
                        stop = context.Event()
                        process = context.Process(target=run_participant, args=(role, url, directory, child, stop))
                        process.start()
                        workers.append((process, stop, parent, child))
                        self.assertTrue(await asyncio.to_thread(parent.poll, 20), "Participant did not start")
                        self.assertTrue(parent.recv())
                    boundary = NatsCommunicationBoundary("controller", "controller", servers=[url])
                    await boundary.connect()
                    try:
                        communication = NatsControllerCommunication(boundary)
                        async def request(role, target, operation, payload, *, command_id=None):
                            result = await communication.request_runtime_command(RuntimeParticipant(role, target),
                                operation, "session", payload, 5, command_id=command_id)
                            self.assertIsNotNone(result, operation)
                            self.assertTrue(result.success, result.reason)
                            return result
                        await request("synchronization_manager", "sync", "initialize_session",
                                      {"synchronization_configuration": configuration(assessment_interval_s=.05)})
                        await request("acquisition_node", "node", "reserve", {})
                        await request("acquisition_node", "node", "initialize_session", {"selected_devices": [declaration().to_dict()]})
                        await request("synchronization_manager", "sync", "start_runtime", {"node_ids": ["node"]})
                        await request("acquisition_node", "node", "start_runtime", {})
                        await request("synchronization_manager", "sync", "read_session_time", {}, command_id="clock-read")
                        rejected = await communication.request_runtime_command(
                            RuntimeParticipant("synchronization_manager", "sync"), "stop_runtime", "session",
                            {}, 5, command_id="clock-read")
                        self.assertIsNotNone(rejected)
                        self.assertFalse(rejected.success)
                        self.assertIn("Conflicting synchronization command identity", rejected.reason)
                        await request("synchronization_manager", "sync", "read_session_time", {})
                        quality_subject = "messages.session.evidence.synchronization_manager.sync.timing_quality_observation"
                        jetstream = boundary._require_jetstream()
                        published = await jetstream.get_last_msg("LAB_EVIDENCE", quality_subject)
                        sequence = json.loads(published.data)["payload"]["assessment_sequence"]
                        assessed = asyncio.Event()

                        async def observe(message):
                            if json.loads(message.data)["payload"]["assessment_sequence"] > sequence:
                                assessed.set()
                            await message.ack()

                        subscription = await jetstream.subscribe(quality_subject, cb=observe, manual_ack=True)
                        try:
                            await asyncio.wait_for(assessed.wait(), 5)
                        finally:
                            await subscription.unsubscribe()
                        await request("acquisition_node", "node", "prepare_experiment_scientific_outputs",
                            {"experiment_id": "experiment", "scientific_outputs": [ScientificOutputSelection("device", "node", "events").to_dict()]})
                        clock = await request("synchronization_manager", "sync", "read_session_time", {})
                        await request("acquisition_node", "node", "activate_experiment_runtime",
                            {"context": {"experiment_id": "experiment", "experiment_start_session_time_s": clock.payload["session_time_s"]}, "health_mapping": []})
                        await request("acquisition_node", "node", "run_one_iteration", {})
                        result = await request("acquisition_node", "node", "finalize_experiment_scientific_outputs", {"experiment_id": "experiment"})
                        row = json.loads(Path(result.payload["manifests"][0]["local_storage_path"]).read_text())
                        self.assertEqual(row["value"], 1)
                        self.assertEqual(row["timestamp_status"], "runtime_timestamped")
                        self.assertGreaterEqual(row["experiment_time_s"], 0)
                        await request("acquisition_node", "node", "stop_runtime", {})
                        stopped = await request("synchronization_manager", "sync", "stop_runtime", {}, command_id="stop-once")
                        duplicate = await request("synchronization_manager", "sync", "stop_runtime", {}, command_id="stop-once")
                        self.assertEqual(stopped.result_id, duplicate.result_id)
                        self.assertEqual(stopped.payload["session_time_s"], duplicate.payload["session_time_s"])
                    finally:
                        await boundary.close()
                finally:
                    for process, stop, parent, child in workers:
                        stop.set()
                        await asyncio.to_thread(process.join, 15)
                        if process.is_alive():
                            process.terminate()
                            await asyncio.to_thread(process.join, 5)
                        parent.close()
                        child.close()
                        self.assertEqual(process.exitcode, 0)
