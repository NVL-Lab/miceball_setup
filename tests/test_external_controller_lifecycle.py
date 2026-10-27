"""Finite external operations delegate to actual scientific and preservation owners."""

import asyncio
from dataclasses import replace
from itertools import repeat
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import h5py
import numpy as np
from nats.aio.client import Client as NATS

from lab_sync_acquisition import (
    AcquisitionNode, Controller, DeviceDeclaration, DeviceManager, ExperimentConfiguration,
    InMemoryIngestor, LocalStorageManager, NatsAcquisitionNodeCommunication, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsExternalSessionLaunchClient, NatsExternalSessionLaunchReceiver,
    NatsIngestorCommunication, NatsStorageManagerCommunication, NatsSynchronizationManagerCommunication,
    OpenCVCameraConfig, PersistentStorageManager, RuntimeParticipant, ScientificOutputSelection,
    ScientificProductDeclaration, SeeedIMX219OpenCVCameraAdapter, ServiceMaintenanceInterface,
    SshRetrievalEndpoint, SynchronizationManager,
)
from lab_sync_acquisition.communication import (
    ExternalControllerRequest, ExternalControllerResult, ExternalSessionLaunchRequest,
    EXTERNAL_CONTROLLER_OPERATIONS,
)
from tests import test_artifact_retrieval as retrieval
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server
from tests.test_distributed_session_closeout import CloseoutBroker, ReleaseSubscription
from tests.test_distributed_synchronization import configuration
from tests.test_external_session_launch import AUTHORIZATION
from tests.test_scientific_camera_collection import FakeCV2, FakeCapture
from tests.test_session_launch import _Boundary


class ExternalOperationModelsTests(unittest.TestCase):
    def test_only_explicit_operations_and_parameters_are_accepted(self):
        for operation, parameters in (("kill_session", {}), ("start_launched_session", {"communication": {}}),
                                      ("start_launched_experiment", {}), ("stop_launched_experiment", {})):
            with self.subTest(operation=operation), self.assertRaises((ValueError, TypeError)):
                ExternalControllerRequest("controller", "tester", "r", operation, "session", parameters)

    def test_plain_data_round_trip_and_outcome_operation_validation(self):
        request = ExternalControllerRequest("controller", "tester", "r", "start_launched_session", "s", {})
        self.assertEqual(ExternalControllerRequest.from_dict(request.to_dict()), request)
        with self.assertRaises(ValueError):
            ExternalControllerResult("controller", "tester", "r", request.operation, "s", "succeeded",
                {"command": "normal_stop_session", "succeeded": True})


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class ExternalLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.broker = CloseoutBroker()
        self.storage = PersistentStorageManager(self.root / "storage", global_artifact_root=self.root / "global",
            retrieval_endpoints={"node": SshRetrievalEndpoint("test-host", "test-reader")})
        self.ingestor = InMemoryIngestor(storage_manager=self.storage, recovery_journal_root=self.root / "journals",
            framework_recovery_journal_path=self.root / "framework.jsonl")
        self.intake = NatsIngestorCommunication(_Boundary("ingestor", "ingestor", self.broker), self.ingestor)
        await self.intake.subscribe_evidence(None)
        await self.intake.subscribe_commands()
        await NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), self.storage).subscribe_commands()
        self.clock = SynchronizationManager()
        self.sync = NatsSynchronizationManagerCommunication(_Boundary("synchronization_manager", "sync", self.broker), self.clock)
        await self.sync.subscribe_commands()
        self.addAsyncCleanup(self.sync.close)
        self.frame = np.arange(24, dtype=np.uint16).reshape(2, 4, 3)
        self.camera = FakeCV2(repeat(self.frame), {0: 12.5})
        def reopen(source, api_preference):
            if self.camera.capture.released:
                self.camera.capture = FakeCapture(repeat(self.frame), {0: 12.5})
            return self.camera.capture
        self.camera.VideoCapture = reopen
        self.adapter = SeeedIMX219OpenCVCameraAdapter("device", "opencv", ("camera_frames",), True, cv2_module=self.camera)
        self.declaration = DeviceDeclaration("device", "opencv", True, True, ("camera_frames",), (
            ScientificProductDeclaration("frames", "camera_frames", {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),))
        self.node = AcquisitionNode(device_manager=DeviceManager((self.adapter,)), node_id="node", role="acquisition",
            synchronization_source_id="sync", default_local_storage_root=self.root / "local",
            error_evidence_location=str(self.root / "errors"), device_declarations=(self.declaration,),
            deployment_device_configurations={"device": OpenCVCameraConfig(0, 0, 1)})
        self.handler = NatsAcquisitionNodeCommunication(_Boundary("acquisition_node", "node", self.broker), self.node)
        await self.handler.subscribe_commands()
        await self.handler.start_acquisition_execution()
        self.addCleanup(self.cleanup_node)
        self.addAsyncCleanup(self.handler.stop_acquisition_execution)
        self.controller = Controller()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.participants = tuple(RuntimeParticipant(kind, identity) for kind, identity in (
            ("ingestor", "ingestor"), ("storage_manager", "storage"), ("synchronization_manager", "sync"), ("acquisition_node", "node")))
        self.maintenance = ServiceMaintenanceInterface(self.controller, RuntimeParticipant("controller", "controller"),
            ingestor=None, storage_manager=None, preservation_window_s=0.1, close_resources=AsyncMock(return_value=True))
        url = await self.enterAsyncContext(temporary_jetstream_server(authorization=AUTHORIZATION))
        self.service_boundary = NatsCommunicationBoundary("controller", "controller", (url.replace("nats://", "nats://service:service@"),))
        self.client_boundary = NatsCommunicationBoundary("client", "tester", (url.replace("nats://", "nats://tester:tester@"),))
        for boundary in (self.service_boundary, self.client_boundary):
            await boundary.connect()
            self.addAsyncCleanup(boundary.close)
        self.client = NatsExternalSessionLaunchClient(self.client_boundary)
        self.receiver = NatsExternalSessionLaunchReceiver(self.service_boundary, self.controller,
            communication=self.communication, maintenance=self.maintenance, client_id="tester",
            participants=self.participants, result_window_s=1)
        await self.receiver.start()
        self.addAsyncCleanup(self.receiver.close)
        self.sequence = 0
        self.sid = None
        self.broker.after_publication = self.deliver_marker_boundary

    def cleanup_node(self):
        if self.node.status()["is_running"]:
            self.node.stop_runtime()
        if self.node.local_storage_manager is not None:
            self.node.local_storage_manager.cleanup()

    async def test_storage_shared_client_context_history_and_deletion(self):
        sid = "historical"
        self.storage.write_initial_session_record(sid,
            accepted_session_config={"session_id": sid, "session_parameters": {"experimenter": "Alice"},
                "expected_runtime_participants": [self.participants[-1].to_dict()]},
            lifecycle_evidence=[], readiness_evidence=[], device_readiness_evidence=[], service_readiness_evidence=[],
            final_session_status=None, cleanup_evidence={})
        local = LocalStorageManager(self.root / "local", sid, "node")
        manifest = local.create_stream(session_id=sid, experiment_id="old-experiment", acquisition_node_id="node",
            source_component_id="device", data_product_id="timing", artifact_type="timing", schema={})
        local.finalize_all()
        metadata = {Path(p): Path(p).read_bytes() for p in manifest.local_managed_paths if Path(p).suffix == ".json"}
        context = {"experimenter_name": "Alice", "administrator_mode": False}
        query = ExternalControllerRequest("controller", "tester", "storage-list", "read_storage_sessions", None, context)
        listed = await self.terminal(query)
        self.assertEqual(listed.status, "succeeded", listed)
        self.assertEqual([s["session_id"] for s in listed.outcome["details"]["sessions"]], [sid])
        denied = await self.terminal(self.request("read_storage_session",
            {"experimenter_name": "Bob", "administrator_mode": False}, session_id=sid))
        self.assertEqual(denied.status, "failed")
        conflict = await self.terminal(ExternalControllerRequest("controller", "tester", "storage-list",
            "read_storage_sessions", None, {"experimenter_name": "Bob", "administrator_mode": False}))
        self.assertEqual(conflict.status, "rejected")
        deletion = self.request("delete_original_artifacts", {**context, "operation_id": "delete-historical",
            "experiment_ids": ["old-experiment"], "confirmed": True, "warning_acknowledged": True}, session_id=sid)
        deleted = await self.terminal(deletion)
        self.assertEqual(deleted.status, "succeeded", deleted)
        self.assertFalse(Path(manifest.local_storage_path).exists())
        self.assertEqual((await self.terminal(deletion)).to_dict(), deleted.to_dict())
        readback = await self.terminal(self.request("read_storage_session", context, session_id=sid))
        self.assertEqual(readback.status, "succeeded", readback)
        operation = readback.outcome["details"]["nodes"]["node"]["deletions"]["operations"][0]
        self.assertEqual(operation["files"][0]["status"], "deleted")
        self.assertEqual(metadata, {p: p.read_bytes() for p in metadata})
        self.assertIsNone(self.controller.get_status()["session_id"])

    async def deliver_marker_boundary(self, subject, payload):
        if payload.get("evidence_type") != "acquisition_evidence_completion":
            return
        topic = f"messages.{payload['session_id']}.evidence.*.*.*"
        for name, consumer in self.broker.consumers.items():
            if consumer.config.filter_subject == topic:
                self.broker.callbacks[name] = next(s.callback for s in self.broker.subscriptions if s.subject == topic)
                for sequence in sorted(self.broker.records):
                    await self.broker.deliver(name, sequence)

    async def terminal(self, request):
        for _ in range(200):
            if isinstance(request, ExternalSessionLaunchRequest):
                result = await self.client.request_launch(request, timeout_s=2)
            else:
                result = await self.client.request_operation(request, timeout_s=2)
            if result.status != "pending":
                return result
            await asyncio.sleep(0.01)
        self.fail("External operation remained pending")

    def request(self, operation, parameters=None, *, session_id=None, request_id=None):
        self.sequence += 1
        if operation == "collect_saved_session_artifacts_remote":
            parameters = {**(parameters or {}), "experimenter_name": None, "administrator_mode": True}
        return ExternalControllerRequest("controller", "tester", request_id or f"operation-{self.sequence}",
            operation, session_id or self.sid, parameters or {})

    async def launch(self):
        self.sequence += 1
        request = ExternalSessionLaunchRequest("controller", "tester", f"launch-{self.sequence}",
            {"node": [self.declaration.to_dict()]}, {"storage_location": str(self.root / "records"),
             "protocol_plan": {}, "error_evidence_location": str(self.root / "errors"),
             "synchronization_configuration": configuration()}, [])
        result = await self.terminal(request)
        self.assertEqual(result.status, "succeeded", result)
        self.sid = result.outcome["details"]["session_id"]
        return request

    async def start(self):
        await self.launch()
        request = self.request("start_launched_session")
        result = await self.terminal(request)
        self.assertEqual(result.status, "succeeded", result)
        return request

    async def experiment(self, identity="experiment", duration=0.2):
        request = self.request("start_launched_experiment", {"experiment_id": identity,
            "configuration": ExperimentConfiguration(duration, {"node": 1000000}, 1000000, participating_devices={"node": ["device"]}).to_dict(),
            "scientific_outputs": [ScientificOutputSelection("device", "node", "frames").to_dict()]})
        result = await self.terminal(request)
        self.assertEqual(result.status, "succeeded", result)
        return request

    async def wait_for_frames(self):
        for _ in range(100):
            if self.node.status()["iteration_count"] > 0:
                return
            await asyncio.sleep(0.01)
        self.fail("Scientific frames were not persisted")

    async def test_collection_before_release_preserves_scientific_data_and_permits_reuse(self):
        await self.start()
        sid = self.sid
        await self.experiment()
        await self.client_boundary.close()
        await asyncio.sleep(0.3)
        await self.client_boundary.connect()
        expired = await self.terminal(self.request("reconcile_launched_experiment_expiry", {"experiment_id": "experiment"}))
        self.assertEqual(expired.status, "succeeded", expired)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])
        manifest, = self.node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        source = Path(manifest.local_storage_path)
        original = source.read_bytes()
        with h5py.File(source) as artifact:
            self.assertGreater(len(artifact["frames"]), 0)
            np.testing.assert_array_equal(artifact["frames"][0], self.frame)
            self.assertEqual(len(artifact["session_time_s"]), len(artifact["frames"]))
        stopped = await self.terminal(self.request("normal_stop_session"))
        self.assertEqual(stopped.status, "succeeded", stopped)
        self.assertTrue(stopped.outcome["details"]["acquisition_preservation_eligible"])
        sftp = retrieval.SftpDouble({str(source): original})
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(sftp)
        with transport:
            collected = await self.terminal(self.request("collect_saved_session_artifacts_remote", {"evidence_id": "collection"}))
        self.assertEqual(collected.status, "succeeded", collected)
        artifact, = collected.outcome["details"]["collection_outcome"]["artifact_collection_result"]["artifact_results"]
        self.assertEqual(artifact["verification_outcome"], "verified")
        self.assertEqual(Path(artifact["global_destination"]).read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        preserved = self.storage.get_persisted_session_preservation_confirmation(sid)
        self.assertIn("collection", preserved["compilation_summary"]["runtime_evidence_origins"]["storage_manager"])
        compiled = self.ingestor.compile_persistent_runtime_evidence()
        self.assertNotIn("collection", [m.evidence_id for m in compiled["runtime_evidence"]])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.ingestor.maintenance_blockers(self.ingestor, self.storage), [])
        released = await self.terminal(self.request("release_session"))
        self.assertEqual(released.status, "succeeded", released)
        self.assertIsNone(self.ingestor.session_id)
        self.assertIsNone(self.controller.get_status()["session_id"])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.storage.get_persisted_session_preservation_confirmation(sid), preserved)
        await self.launch()
        self.assertNotEqual(self.sid, sid)

    async def test_collection_release_rejects_damaged_preservation_products(self):
        await self.start()
        await self.experiment()
        await asyncio.sleep(0.3)
        self.assertEqual((await self.terminal(self.request("reconcile_launched_experiment_expiry",
            {"experiment_id": "experiment"}))).status, "succeeded")
        manifest, = self.node.local_storage_manager.manifests
        source = Path(manifest.local_storage_path)
        original = source.read_bytes()
        self.assertEqual((await self.terminal(self.request("normal_stop_session"))).status, "succeeded")
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(retrieval.SftpDouble({str(source): original}))
        with transport:
            self.assertEqual((await self.terminal(self.request("collect_saved_session_artifacts_remote",
                {"evidence_id": "collection"}))).status, "succeeded")
        directory = self.root / "storage" / f"session_{self.sid}" / "evidence"
        summary_path = directory / "compilation_summary.json"
        evidence_path = directory / "runtime_evidence.jsonl"
        audit_path = directory / "ingest_audit.jsonl"
        summary = json.loads(summary_path.read_bytes())
        evidence = evidence_path.read_bytes()
        corrupt = json.loads(json.dumps(summary))
        corrupt["runtime_evidence_origins"]["storage_manager"].append(
            corrupt["runtime_evidence_origins"]["ingestor"].pop())
        cases = (("provenance", summary_path, json.dumps(corrupt).encode()),
                 ("missing acquisition", evidence_path, b"".join(evidence.splitlines(keepends=True)[1:])),
                 ("duplicate evidence", evidence_path, evidence + evidence.splitlines(keepends=True)[0]),
                 ("corrupt evidence", evidence_path, evidence.replace(b'"is_persistent": true', b'"is_persistent": false', 1)),
                 ("changed audit", audit_path, audit_path.read_bytes() + b'{}\n'),
                 ("incomplete Stage B", evidence_path, evidence[:-5]))
        for name, path, damaged in cases:
            before = path.read_bytes()
            self.assertNotEqual(before, damaged, name)
            with self.subTest(case=name):
                try:
                    path.write_bytes(damaged)
                    self.assertTrue(self.ingestor.maintenance_blockers(self.ingestor, self.storage))
                    with self.assertRaises(RuntimeError):
                        self.ingestor.release_session(self.sid)
                    self.assertEqual(self.ingestor.session_id, self.sid)
                finally:
                    path.write_bytes(before)
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.ingestor.maintenance_blockers(self.ingestor, self.storage), [])
        self.assertTrue(self.ingestor.release_session(self.sid))

    async def test_incomplete_collection_persistence_blocks_release_and_maintenance(self):
        await self.start()
        await self.experiment()
        await asyncio.sleep(0.3)
        await self.terminal(self.request("reconcile_launched_experiment_expiry", {"experiment_id": "experiment"}))
        manifest, = self.node.local_storage_manager.manifests
        source = Path(manifest.local_storage_path)
        original = source.read_bytes()
        self.assertEqual((await self.terminal(self.request("normal_stop_session"))).status, "succeeded")
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(retrieval.SftpDouble({str(source): original}))
        with transport, patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("summary publication interrupted")):
            result = await self.terminal(self.request("collect_saved_session_artifacts_remote", {"evidence_id": "interrupted"}))
        self.assertEqual(result.status, "failed", result)
        self.assertIsNone(self.storage.get_persisted_session_preservation_confirmation(self.sid))
        self.assertTrue(self.ingestor.maintenance_blockers(self.ingestor, self.storage))
        released = await self.terminal(self.request("release_session"))
        self.assertNotEqual(released.status, "succeeded", released)
        self.assertEqual(self.ingestor.session_id, self.sid)
        self.assertEqual(self.controller.get_status()["session_id"], self.sid)
        self.assertEqual(source.read_bytes(), original)

    async def test_complete_cycle_expiry_release_saved_collection_and_new_session(self):
        await self.start()
        sid = self.sid
        await self.experiment()
        await asyncio.sleep(0.3)
        expired = await self.terminal(self.request("reconcile_launched_experiment_expiry", {"experiment_id": "experiment"}))
        self.assertEqual(expired.status, "succeeded", expired)
        manifest, = self.node.local_storage_manager.manifests
        stopped = await self.terminal(self.request("normal_stop_session"))
        self.assertEqual(stopped.status, "succeeded", stopped)
        source = Path(manifest.local_storage_path)
        original = source.read_bytes()
        released = await self.terminal(self.request("release_session"))
        self.assertEqual(released.status, "succeeded", released)
        self.assertIsNone(self.controller.get_status()["session_id"])
        self.assertIsNone(self.node.reserved_for_session_id)
        await self.launch()
        replacement = self.sid
        self.assertNotEqual(replacement, sid)
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(retrieval.SftpDouble({str(source): original}))
        with transport:
            collected = await self.terminal(self.request("collect_saved_session_artifacts_remote", {"evidence_id": "collection"}, session_id=sid))
        self.assertEqual(collected.status, "succeeded", collected)
        artifact, = collected.outcome["details"]["collection_outcome"]["artifact_collection_result"]["artifact_results"]
        self.assertEqual(artifact["verification_outcome"], "verified")
        self.assertEqual(Path(artifact["global_destination"]).read_bytes(), original)
        self.assertEqual(self.controller.get_status()["session_id"], replacement)
        old = await self.terminal(self.request("start_launched_session", session_id=sid))
        self.assertEqual(old.status, "rejected")

    async def test_early_experiment_stop_preserves_frames_without_ending_session(self):
        await self.start()
        await self.experiment(duration=10)
        await self.wait_for_frames()
        result = await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "experiment"}))
        self.assertEqual(result.status, "succeeded", result)
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        self.assertEqual(self.node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
        stopped = await self.terminal(self.request("normal_stop_session"))
        self.assertEqual(stopped.status, "succeeded", stopped)

    async def test_configuration_read_after_client_reconnect_and_detached_result(self):
        await self.launch()
        read = self.request("read_session_configuration")
        first = await self.terminal(read)
        self.assertEqual(first.status, "succeeded", first)
        accepted = first.outcome["details"]["configuration"]
        self.assertEqual(accepted["session_id"], self.sid)
        await self.client_boundary.close()
        await self.client_boundary.connect()
        self.assertEqual((await self.terminal(read)).to_dict(), first.to_dict())
        accepted["protocol_plan"]["edited"] = True
        fresh = await self.terminal(self.request("read_session_configuration"))
        self.assertNotIn("edited", fresh.outcome["details"]["configuration"]["protocol_plan"])
        wrong = await self.terminal(self.request("read_session_configuration", session_id="other"))
        self.assertEqual(wrong.status, "rejected")
        conflict = self.request("start_launched_session", request_id=read.request_id)
        self.assertEqual((await self.terminal(conflict)).status, "rejected")

    async def test_experiment_configuration_does_not_change_accepted_session_values(self):
        await self.start()
        before = await self.terminal(self.request("read_session_configuration"))
        await self.experiment(duration=10)
        await self.wait_for_frames()
        stopped = await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "experiment"}))
        self.assertEqual(stopped.status, "succeeded", stopped)
        after = await self.terminal(self.request("read_session_configuration"))
        self.assertEqual(before.outcome["details"], after.outcome["details"])
        self.assertEqual(self.node.local_storage_manager.manifests[0].lifecycle_state, "finalized")

    async def test_identity_validation_and_cross_operation_duplicates(self):
        launch = await self.launch()
        before = len(self.broker.commands)
        wrong = self.request("start_launched_session", session_id="unrelated")
        self.assertEqual((await self.terminal(wrong)).status, "rejected")
        request = self.request("start_launched_session", request_id=launch.request_id)
        self.assertEqual((await self.terminal(request)).status, "rejected")
        self.assertEqual(len(self.broker.commands), before)
        request = self.request("start_launched_session")
        result = await self.terminal(request)
        self.assertEqual(result.status, "succeeded", result)
        after = len(self.broker.commands)
        self.assertEqual((await self.terminal(request)).to_dict(), result.to_dict())
        changed = replace(request, operation="release_session")
        self.assertEqual((await self.terminal(changed)).status, "rejected")
        self.assertEqual(len(self.broker.commands), after)
        wrong_experiment = await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "unknown"}))
        self.assertEqual(wrong_experiment.status, "failed")
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_pending_timeout_cancel_and_disconnect_preserve_one_start(self):
        await self.launch()
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.broker.publish
        async def paused(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "start_runtime":
                entered.set()
                await resume.wait()
            return await original(subject, data, stream)
        self.broker.publish = paused
        request = self.request("start_launched_session")
        transport = self.service_boundary._require_client()
        publish = transport.publish
        replied = asyncio.Event()
        async def lose(subject, *args, **kwargs):
            if subject.startswith("_INBOX."):
                replied.set()
            else:
                await publish(subject, *args, **kwargs)
        try:
            with patch.object(transport, "publish", side_effect=lose):
                self.assertEqual((await self.client.request_operation(request, timeout_s=0.05)).status, "uncertain")
                await asyncio.wait_for(entered.wait(), 1)
                replied.clear()
                waiting = asyncio.create_task(self.client.request_operation(request, timeout_s=2))
                await asyncio.wait_for(replied.wait(), 1)
                waiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiting
            self.assertEqual((await self.client.request_operation(request, timeout_s=1)).status, "pending")
            await self.client_boundary.close()
            resume.set()
            await self.client_boundary.connect()
            self.assertEqual((await self.terminal(request)).status, "succeeded")
            node_starts = [c for c in self.broker.commands if c["command_type"] == "start_runtime" and c["target_id"] == "node"]
            self.assertEqual(len(node_starts), 1)
        finally:
            resume.set()

    async def test_start_failure_uses_existing_rollback_without_erasing_session(self):
        await self.launch()
        sid = self.sid
        with patch.object(self.node, "start_runtime", side_effect=OSError("device start failed")):
            result = await self.terminal(self.request("start_launched_session"))
        self.assertEqual(result.status, "failed", result)
        self.assertEqual(self.controller.get_status()["session_state"], "failed")
        self.assertEqual(self.controller.get_status()["session_id"], sid)
        self.assertFalse(self.node.status()["is_running"])
        self.assertTrue(any(c["command_type"] == "abort_session_initialization" for c in self.broker.commands))

    async def test_finalization_failure_is_unconfirmed_and_explicit_retry_preserves_frames(self):
        await self.start()
        await self.experiment(duration=10)
        await self.wait_for_frames()
        request = self.request("stop_launched_experiment", {"experiment_id": "experiment"})
        with patch.object(self.node, "finalize_experiment_scientific_outputs", side_effect=OSError("finalization failed")):
            failed = await self.terminal(request)
        self.assertEqual(failed.status, "failed", failed)
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")
        self.assertEqual((await self.terminal(request)).status, "failed")
        recovered = await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "experiment"}))
        self.assertEqual(recovered.status, "succeeded", recovered)
        manifest, = self.node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        with h5py.File(manifest.local_storage_path) as artifact:
            self.assertGreater(len(artifact["frames"]), 0)

    async def test_preservation_failure_blocks_release_then_new_request_resumes_without_cleanup_repeat(self):
        await self.start()
        await self.experiment(duration=10)
        await self.wait_for_frames()
        request = self.request("normal_stop_session")
        with patch.object(self.node, "stop_runtime", wraps=self.node.stop_runtime) as cleanup:
            with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
                failed = await self.terminal(request)
            self.assertEqual(failed.status, "failed", failed)
            self.assertEqual(self.controller.get_status()["session_id"], self.sid)
            self.assertEqual((await self.terminal(self.request("release_session"))).status, "failed")
            count = cleanup.call_count
            self.assertGreater(count, 0)
            self.assertEqual((await self.terminal(request)).status, "failed")
            recovered = await self.terminal(self.request("normal_stop_session"))
            self.assertEqual(recovered.status, "succeeded", recovered)
            self.assertEqual(cleanup.call_count, count)

    async def test_cleanup_operations_remain_available_during_blocked_maintenance(self):
        await self.start()
        await self.experiment(duration=10)
        self.maintenance._closeout_started = True
        new = self.request("start_launched_experiment", {"experiment_id": "other",
            "configuration": ExperimentConfiguration(10, {"node": 1000000}, 1000000, participating_devices={"node": ["device"]}).to_dict(), "scientific_outputs": []})
        self.assertEqual((await self.terminal(new)).status, "rejected")
        self.assertEqual((await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "experiment"}))).status, "succeeded")
        stopped = await self.terminal(self.request("normal_stop_session"))
        self.assertEqual(stopped.status, "succeeded", stopped)
        self.assertEqual((await self.terminal(self.request("release_session"))).status, "succeeded")

    async def test_interrupted_release_retries_only_unfinished_teardown(self):
        await self.start()
        self.assertEqual((await self.terminal(self.request("normal_stop_session"))).status, "succeeded")
        wrapped = tuple(ReleaseSubscription(s) for s in self.controller._launch_subscriptions)
        self.controller._launch_subscriptions = wrapped
        async def interrupt():
            wrapped[1].before_unsubscribe = None
            raise asyncio.CancelledError()
        wrapped[1].before_unsubscribe = interrupt
        first = await self.terminal(self.request("release_session"))
        self.assertEqual(first.status, "failed", first)
        self.assertEqual(self.controller.get_status()["session_id"], self.sid)
        retried = await self.terminal(self.request("release_session"))
        self.assertEqual(retried.status, "succeeded", retried)
        self.assertEqual(wrapped[0].attempts, 1)
        self.assertEqual(wrapped[1].attempts, 2)

    async def test_expiry_readback_does_not_manufacture_completion(self):
        await self.start()
        await self.experiment(duration=10)
        result = await self.terminal(self.request("reconcile_launched_experiment_expiry", {"experiment_id": "experiment"}))
        self.assertEqual(result.status, "failed")
        self.assertIs(result.outcome["details"]["expiry_confirmed"], False)
        self.assertEqual(self.controller.get_status()["active_experiment_id"], "experiment")

    async def test_broker_denies_all_lifecycle_operations_to_unrelated_client(self):
        errors = []
        async def error(error):
            errors.append(error)
        outsider = NATS()
        url = self.client_boundary.servers[0].replace("tester:tester", "outsider:outsider")
        await outsider.connect(servers=[url], error_cb=error, allow_reconnect=False)
        try:
            for operation in EXTERNAL_CONTROLLER_OPERATIONS:
                await outsider.publish(f"controller_external.controller.tester.{operation}", b"{}")
            await outsider.flush()
            for _ in range(100):
                if len(errors) == len(EXTERNAL_CONTROLLER_OPERATIONS):
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(errors), len(EXTERNAL_CONTROLLER_OPERATIONS))
            self.assertTrue(all("permissions violation" in str(e).lower() for e in errors))
            self.assertIsNone(self.controller.get_status()["session_id"])
        finally:
            await outsider.close()

    async def queued_transition(self, operation):
        await self.start()
        self.assertEqual((await self.terminal(self.request("normal_stop_session"))).status, "succeeded")
        old = self.sid
        if operation == "start_launched_experiment":
            parameters = {"experiment_id": "late", "scientific_outputs": [],
                "configuration": ExperimentConfiguration(10, {"node": 1000000}, 1000000, participating_devices={"node": ["device"]}).to_dict()}
        else:
            parameters = {"experiment_id": "late"}
        request = self.request(operation, parameters)
        async with self.controller._experiment_operation_lock:
            self.assertEqual((await self.client.request_operation(request, timeout_s=1)).status, "pending")
            await asyncio.sleep(0.02)
            released = await self.terminal(self.request("release_session"))
            self.assertEqual(released.status, "succeeded", released)
        late = await self.terminal(request)
        self.assertIn(late.status, {"failed", "rejected"})
        await self.launch()
        replacement = self.sid
        self.assertNotEqual(old, replacement)
        commands = len(self.broker.commands)
        self.assertEqual((await self.terminal(request)).to_dict(), late.to_dict())
        self.assertEqual(self.controller.get_status()["session_id"], replacement)
        self.assertEqual(len(self.broker.commands), commands)
        self.assertIsNone(self.controller.get_status()["active_experiment_id"])

    async def test_queued_experiment_start_rechecks_binding_after_lock_wait(self):
        await self.queued_transition("start_launched_experiment")

    async def test_queued_experiment_stop_rechecks_binding_after_lock_wait(self):
        await self.queued_transition("stop_launched_experiment")

    async def test_retrieval_failure_preserves_source_and_durable_failure_outcome(self):
        await self.start()
        await self.experiment(duration=10)
        await self.wait_for_frames()
        self.assertEqual((await self.terminal(self.request("stop_launched_experiment", {"experiment_id": "experiment"}))).status, "succeeded")
        manifest, = self.node.local_storage_manager.manifests
        source = Path(manifest.local_storage_path)
        original = source.read_bytes()
        self.assertEqual((await self.terminal(self.request("normal_stop_session"))).status, "succeeded")
        sftp = retrieval.SftpDouble({str(source): original}, failures=(str(source),))
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(sftp)
        request = self.request("collect_saved_session_artifacts_remote", {"evidence_id": "failed-collection"})
        with transport:
            result = await self.terminal(request)
            count = len(sftp.opened)
            self.assertEqual((await self.terminal(request)).to_dict(), result.to_dict())
            self.assertEqual(len(sftp.opened), count)
        self.assertEqual(result.status, "failed", result)
        outcome = result.outcome["details"]["collection_outcome"]
        self.assertFalse(outcome["artifact_collection_result"]["succeeded"])
        self.assertTrue(outcome["archival_confirmed"])
        self.assertEqual(source.read_bytes(), original)

    async def test_acquisition_failure_retains_partial_hdf5_and_failure_evidence(self):
        await self.start()
        self.camera.capture.frames = iter((self.frame,))
        with self.assertLogs("lab_sync_acquisition.nats_communication", level="ERROR"):
            await self.experiment(duration=10)
            for _ in range(100):
                if not self.node.status()["is_running"]:
                    break
                await asyncio.sleep(0.01)
        self.assertFalse(self.node.status()["is_running"])
        manifest, = self.node.local_storage_manager.manifests
        self.assertEqual(manifest.lifecycle_state, "finalized")
        with h5py.File(manifest.local_storage_path) as artifact:
            self.assertEqual(len(artifact["frames"]), 1)
            np.testing.assert_array_equal(artifact["frames"][0], self.frame)
        self.assertTrue(any(m.payload.get("event_type") == "acquisition_failure" for m in self.node.runtime_evidence))

    async def test_receiver_shutdown_joins_pending_session_start(self):
        await self.launch()
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.broker.publish
        async def paused(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "start_runtime":
                entered.set()
                await resume.wait()
            return await original(subject, data, stream)
        self.broker.publish = paused
        request = self.request("start_launched_session")
        await self.client.request_operation(request, timeout_s=1)
        await asyncio.wait_for(entered.wait(), 1)
        closing = asyncio.create_task(self.receiver.close())
        try:
            await asyncio.sleep(0.01)
            self.assertFalse(closing.done())
            resume.set()
            await asyncio.wait_for(closing, 2)
        finally:
            resume.set()
            await closing
        self.assertEqual(self.controller.get_status()["session_state"], "running")
        self.assertEqual((await self.client.request_operation(request, timeout_s=0.05)).status, "uncertain")

    async def test_mismatched_responses_remain_uncertain_without_repeating_start(self):
        await self.launch()
        request = self.request("start_launched_session")
        transport = self.service_boundary._require_client()
        publish = transport.publish
        for field, value in (("request_id", "stale"), ("session_id", "unrelated"), ("operation", "release_session")):
            async def changed(subject, data, **kwargs):
                envelope = json.loads(data)
                envelope[field] = value
                await publish(subject, json.dumps(envelope).encode(), **kwargs)
            with self.subTest(field=field), patch.object(transport, "publish", side_effect=changed):
                self.assertEqual((await self.client.request_operation(request, timeout_s=1)).status, "uncertain")
        self.assertEqual((await self.terminal(request)).status, "succeeded")
        starts = [c for c in self.broker.commands if c["command_type"] == "start_runtime" and c["target_id"] == "node"]
        self.assertEqual(len(starts), 1)
