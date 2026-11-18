"""Approved scientific destinations through owner and Controller/NATS workflows."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (PersistentStorageManager, RuntimeParticipant, SshRetrievalEndpoint,
    NatsCommunicationBoundary, NatsControllerCommunication, ServiceMaintenanceInterface,
    InMemoryIngestor, NatsStorageManagerCommunication)
from tests.nats_server_fixture import acquire_test_controller_authority
from tests import test_artifact_retrieval as retrieval
from tests import test_session_launch as launch


ADMIN = {"experimenter_name": "Lab administrator", "administrator_mode": True}


class SessionArtifactDestinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.default = self.root / "default"
        self.other = self.root / "other"
        self.default.mkdir()
        self.other.mkdir()
        self.storage = self.restart()

    def restart(self):
        return PersistentStorageManager(self.root / "records", global_artifact_root=self.default,
            retrieval_endpoints={"node": SshRetrievalEndpoint("host", "scientist")})

    def register(self):
        return self.storage.register_artifact_destination("second", "Second disk", str(self.other), **ADMIN)

    def test_default_listing_does_not_probe_scientific_directory(self):
        with patch("lab_sync_acquisition.storage.inspect_storage_capacity", side_effect=AssertionError("probe")):
            result = self.storage.list_artifact_destinations()
        self.assertEqual(result["default_destination_id"], "default")
        self.assertEqual(result["destinations"][0]["validation"]["status"], "unverified")
        self.assertEqual(list(self.default.iterdir()), [])

    def test_registration_persistence_idempotence_and_conflicts(self):
        self.assertEqual(self.register()["validation"]["status"], "verified")
        self.register()
        self.assertEqual(len(self.restart().list_artifact_destinations()["destinations"]), 2)
        with self.assertRaises(ValueError):
            self.storage.register_artifact_destination("second", "Changed", str(self.default), **ADMIN)

    def test_administrator_and_directory_validation(self):
        for admin in (False, None, 1):
            with self.subTest(admin=admin), self.assertRaises(PermissionError):
                self.storage.register_artifact_destination("second", "Disk", str(self.other),
                    experimenter_name="Operator", administrator_mode=admin)
        with self.assertRaises(ValueError):
            self.storage.register_artifact_destination("missing", "Missing", str(self.root / "missing"), **ADMIN)
        self.assertFalse((self.root / "missing").exists())

    def test_binding_restart_immutability_and_disabled_obligations(self):
        self.register()
        first = self.storage.admit_session_artifact_destination("session", "second")
        self.assertEqual(first["binding"], self.storage.admit_session_artifact_destination("session", "second")["binding"])
        with self.assertRaises(ValueError):
            self.storage.admit_session_artifact_destination("session", "default")
        self.storage.update_artifact_destination("second", enabled=False, **ADMIN)
        self.assertEqual(self.restart().resolve_session_artifact_root("session"), self.other)
        with self.assertRaises(ValueError):
            self.storage.admit_session_artifact_destination("later", "second")
        with self.assertRaises(RuntimeError):
            self.storage.update_artifact_destination("second", enabled=False, remove=True, **ADMIN)

    def test_unused_destination_removal(self):
        self.register()
        self.storage.update_artifact_destination("second", enabled=False, remove=True, **ADMIN)
        self.assertEqual(len(self.restart().list_artifact_destinations()["destinations"]), 1)

    def test_interrupted_registry_replace_preserves_complete_configuration_and_allows_retry(self):
        self.storage.list_artifact_destinations()
        path = self.root / "records/artifact_destinations/registry.json"
        before = path.read_bytes()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.register()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.storage.list_artifact_destinations()["destinations"]), 1)
        self.assertEqual(self.register()["destination"]["destination_id"], "second")

    def test_corrupt_or_missing_retained_registry_refuses_restart(self):
        self.register()
        path = self.root / "records/artifact_destinations/registry.json"
        original = path.read_bytes()
        for content in (b"{}", b'{"version":1,"version":1,"destinations":[]}', b"broken"):
            path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises((ValueError, RuntimeError)):
                self.restart()
        path.write_bytes(original)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.restart()

    def test_unavailable_bound_directory_never_falls_back(self):
        self.register()
        self.storage.admit_session_artifact_destination("session", "second")
        self.other.rmdir()
        with self.assertRaises(RuntimeError):
            self.restart().resolve_session_artifact_root("session")
        self.assertEqual(list(self.default.iterdir()), [])

    def test_transfer_all_experiments_and_sessions_resolve_their_binding(self):
        self.register()
        self.storage.admit_session_artifact_destination("session", "second")
        self.storage.admit_session_artifact_destination("other-session", "default")
        helper = retrieval.ArtifactRetrievalTests()
        source = {"/node/frames.h5": b"original"}
        mock_ssh, _ = helper.ssh(retrieval.SftpDouble(source))
        with mock_ssh:
            for sid, experiment, root in (("session", "first", self.other),
                    ("session", "second", self.other), ("other-session", "first", self.default)):
                manifest = replace(helper.manifest(), session_id=sid, experiment_id=experiment)
                handoff = {"session_id": sid, "artifacts": [{"artifact_manifest": manifest.to_dict(),
                    "missing_finalization_evidence": False}]}
                result = self.storage.collect_artifacts(handoff)
                self.assertEqual(result.artifact_results[0].outcome, "success")
                path = root / sid / experiment / "node/artifact/frames.h5"
                self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(source["/node/frames.h5"], b"original")
        self.assertFalse((self.root / "records/session/first").exists())

    def test_legacy_free_text_is_not_reinterpreted_as_a_destination(self):
        self.register()
        self.assertEqual(self.storage.resolve_session_artifact_root("old-session"), self.default)
        self.assertTrue(self.storage.read_session_artifact_destination("old-session")["legacy"])

    def test_capacity_uses_bound_root_and_preserves_shared_filesystem_accounting(self):
        self.register()
        self.storage.admit_session_artifact_destination("session", "second")
        report = self.storage.check_experiment_capacity(1024, session_id="session")
        self.assertTrue(report["ready"], report)
        self.assertEqual({r["destination"] for r in report["destinations"]},
                         {str(self.root / "records"), str(self.other)})
        from lab_sync_acquisition.local_storage import validate_storage_capacity
        validate_storage_capacity([report])

    def test_interrupted_binding_publication_is_not_confirmed(self):
        self.storage.list_artifact_destinations()
        with patch("lab_sync_acquisition.storage.os.link", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.storage.admit_session_artifact_destination("session", "default")
        with self.assertRaises(RuntimeError):
            self.storage.read_session_artifact_destination("session")
        self.assertFalse(list(self.root.rglob(".destination-*")))
        self.assertTrue(self.storage.admit_session_artifact_destination("session", "default")["admitted"])

    def test_separate_owners_serialize_registry_updates_and_binding_conflicts(self):
        self.register()
        another = self.restart()
        third = self.root / "third"
        third.mkdir()
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(owner.admit_session_artifact_destination, "session", identity)
                for owner, identity in ((self.storage, "default"), (another, "second"))]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except ValueError:
                    results.append(None)
        self.assertEqual(sum(r is not None for r in results), 1)
        binding = self.restart().read_session_artifact_destination("session")
        self.assertIn(binding["destination_id"], {"default", "second"})
        another.register_artifact_destination("third", "Third", str(third), **ADMIN)
        self.assertEqual(len(self.storage.list_artifact_destinations()["destinations"]), 3)

    def test_lost_or_contradictory_binding_does_not_reinterpret_new_session_as_legacy(self):
        from tests.test_storage import PersistentStorageManagerTests
        self.storage.admit_session_artifact_destination("session", "default")
        evidence = PersistentStorageManagerTests._minimal_session_record_evidence("session")
        evidence["accepted_session_config"]["storage_location"] = "default"
        evidence["accepted_session_config"]["storage_configuration"] = {"artifact_destination_binding_required": True}
        self.storage.preserve_initial_session_record("session", evidence)
        path = self.root / "records/session_session/artifact_destination.json"
        data = json.loads(path.read_text())
        data["destination"]["root"] = str(self.other)
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.restart().read_session_artifact_destination("session")
        path.unlink()
        with self.assertRaises(RuntimeError):
            self.restart().resolve_session_artifact_root("session")

    def test_bound_saved_collection_restart_verification_and_deletion_proof(self):
        from tests import test_stage_b_collection as stage_b
        fixture = stage_b.StageBCollectionTests()
        fixture.addCleanup = self.addCleanup
        def storage():
            manager = PersistentStorageManager(fixture.root, global_artifact_root=fixture.root / "global",
                retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "reader")})
            if not (fixture.root / "artifact_destinations").exists():
                manager.register_artifact_destination("second", "Second disk", str(self.other), **ADMIN)
                manager.admit_session_artifact_destination("session", "second")
            return manager
        fixture.new_storage = storage
        fixture.setUp()
        before = {Path(p): Path(p).read_bytes() for p in fixture.files}
        binding = fixture.root / "session_session/artifact_destination.json"
        bound_bytes = binding.read_bytes()
        fixture.sftp.failures.update(fixture.files)
        failed = fixture.collect()
        self.assertFalse(failed["artifact_collection_result"]["succeeded"])
        fixture.sftp.failures.clear()
        result = fixture.collect(identity="explicit-retry")
        self.assertTrue(result["archival_confirmed"], result)
        self.assertTrue(result["artifact_collection_result"]["succeeded"], result)
        restarted = storage()
        restarted.update_artifact_destination("second", enabled=False, **ADMIN)
        proof = restarted.confirm_collected_originals("session", [m.to_dict() for m in fixture.manifests])
        self.assertTrue(proof["verification_confirmed"])
        self.assertEqual(binding.read_bytes(), bound_bytes)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(all(Path(r["global_destination"]).is_relative_to(self.other)
            for r in result["artifact_collection_result"]["artifact_results"]))

    def test_bound_jsonl_hdf5_reconstruction_uses_preserved_destination(self):
        from tests import test_timing_reconstruction as timing
        from lab_sync_acquisition import ReconstructionManager
        fixture = timing.TimingReconstructionTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        storage = PersistentStorageManager(fixture.root / "archive", global_artifact_root=self.default,
            retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "reader")})
        storage.register_artifact_destination("second", "Second disk", str(self.other), **ADMIN)
        storage.admit_session_artifact_destination("session", "second")
        fixture.storage = storage
        fixture.archive()
        files = {m.local_storage_path: Path(m.local_storage_path).read_bytes() for m in fixture.manifests}
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(retrieval.SftpDouble(files))
        with transport:
            outcome = storage.collect_saved_artifacts("session", evidence_id="bound-collection", require_eligible=False)
        self.assertTrue(outcome["archival_confirmed"], outcome)
        storage.update_artifact_destination("second", enabled=False, **ADMIN)
        restarted = PersistentStorageManager(fixture.root / "archive", global_artifact_root=self.default)
        before = fixture.snapshot()
        result = ReconstructionManager(restarted).reconstruct_session("session", version="bound")
        self.assertTrue(result["quality"]["complete"], result)
        self.assertTrue(all(Path(a["read_path"]).is_relative_to(self.other) for a in result["artifacts"]))
        self.assertEqual(fixture.snapshot(), before)
        self.assertEqual(files, {p: Path(p).read_bytes() for p in files})


class DestinationLaunchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = launch.SessionLaunchTests()
        self.f.addCleanup = self.addCleanup
        self.f.setUp()
        f = self.f
        (f.root / "artifacts").mkdir()
        f.storage = PersistentStorageManager(f.root / "storage", global_artifact_root=f.root / "artifacts")
        f.ingestor = InMemoryIngestor(storage_manager=f.storage, recovery_journal_root=f.root / "journals")
        f.participants.append(RuntimeParticipant("storage_manager", "storage"))
        f.config["storage_location"] = "default"

    async def asyncSetUp(self):
        f = self.f
        maintenance = ServiceMaintenanceInterface(f.controller, RuntimeParticipant("controller", "controller"),
            ingestor=f.ingestor, storage_manager=f.storage, preservation_window_s=2,
            close_resources=AsyncMock(return_value=True))
        authority = await acquire_test_controller_authority(self, maintenance)
        await authority.ensure_streams()
        boundaries = {("controller", "controller"): authority}
        for kind, identity in (("ingestor", "ingestor"), ("storage_manager", "storage"),
                               ("synchronization_manager", "sync"), ("acquisition_node", "node-a")):
            boundary = NatsCommunicationBoundary(kind, identity, authority.servers)
            await boundary.connect()
            await boundary.ensure_streams()
            boundary.configure_controller_authority(account="LAB", bucket="AUTHORITY", key="controller", timeout_s=2)
            self.addAsyncCleanup(boundary.close)
            boundaries[kind, identity] = boundary
        for owner, kind, identity in ((f.ingestor, "ingestor", "ingestor"),
                (f.storage, "storage_manager", "storage"), (f.sync, "synchronization_manager", "sync")):
            ServiceMaintenanceInterface(owner, RuntimeParticipant(kind, identity),
                ingestor=f.ingestor, storage_manager=f.storage, preservation_window_s=2,
                close_resources=AsyncMock(return_value=True))
        self.boundaries = boundaries
        patched = patch.object(launch, "_Boundary", side_effect=lambda kind, identity, broker: boundaries[kind, identity])
        patched.start()
        self.addCleanup(patched.stop)
        f.communication = NatsControllerCommunication(authority)
        original_services = f.services
        async def services(**kwargs):
            await original_services(**kwargs)
            handler = NatsStorageManagerCommunication(boundaries["storage_manager", "storage"], f.storage)
            await handler.subscribe_commands()
            f.storage_handler = handler
        f.services = services
        original_node = f.node
        async def node(*args, **kwargs):
            result = await original_node(*args, **kwargs)
            ServiceMaintenanceInterface(result[0], RuntimeParticipant("acquisition_node", result[0].node_id),
                ingestor=f.ingestor, storage_manager=f.storage, preservation_window_s=2,
                close_resources=AsyncMock(return_value=True))
            return result
        f.node = node
        async def launch_session(selections, **kwargs):
            return await f.controller.launch_session(selections, communication=f.communication,
                participants=f.participants, config_parameters=f.config, result_window_s=2, **kwargs)
        f.launch = launch_session

    async def test_controller_launch_admission_and_exact_initial_record(self):
        f = self.f
        await f.services()
        _, device, _ = await f.node()
        result = await f.launch({"node-a": [device]})
        self.assertTrue(result.succeeded, result.error)
        sid = result.details["session_id"]
        binding = f.storage.read_session_artifact_destination(sid)
        self.assertFalse(binding["legacy"])
        self.assertEqual(binding["destination_id"], "default")
        config = f.storage.read_session_record(f.root / "storage" / f"session_{sid}" / "session_record_initial.json")["accepted_session_config"]
        self.assertEqual(config, result.details["configuration"])

    async def test_missing_or_conflicting_admission_confirmation_refuses_launch(self):
        f = self.f
        await f.services()
        _, device, _ = await f.node()
        boundary = self.boundaries["storage_manager", "storage"]
        publish = boundary.publish_command_result
        async def damage(result, *args, **kwargs):
            if "binding" in result.payload:
                payload = json.loads(json.dumps(result.payload))
                payload["binding"]["destination_id"] = "wrong"
                result = replace(result, payload=payload)
            return await publish(result, *args, **kwargs)
        with patch.object(boundary, "publish_command_result", side_effect=damage):
            result = await f.launch({"node-a": [device]})
        self.assertFalse(result.succeeded)
        self.assertIn("destination admission is unconfirmed", result.error)
        bindings = list((f.root / "storage").glob("session_*/artifact_destination.json"))
        self.assertEqual(len(bindings), 1)
        saved = json.loads(bindings[0].read_text())
        self.assertEqual(saved["destination"]["destination_id"], "default")

    async def test_controller_administrator_management_through_nats(self):
        f = self.f
        await f.services()
        other = f.root / "other"
        other.mkdir()
        arguments = {"communication": f.communication,
            "storage_participant": RuntimeParticipant("storage_manager", "storage"), "result_window_s": 2}
        refused = await f.controller.register_artifact_destination("other", "Other disk", str(other),
            experimenter_name="Operator", administrator_mode=False, **arguments)
        self.assertFalse(refused.succeeded)
        accepted = await f.controller.register_artifact_destination("other", "Other disk", str(other), **ADMIN, **arguments)
        self.assertTrue(accepted.succeeded, accepted.error)
        listed = await f.controller.list_artifact_destinations(**arguments)
        self.assertTrue(listed.succeeded, listed.error)
        self.assertEqual(len(listed.details["destinations"]), 2)

    async def test_failure_after_admission_retains_binding(self):
        f = self.f
        await f.services()
        _, device, _ = await f.node(node_class=launch._FailingInitializationNode)
        result = await f.launch({"node-a": [device]})
        self.assertFalse(result.succeeded)
        bindings = list((f.root / "storage").glob("session_*/artifact_destination.json"))
        self.assertEqual(len(bindings), 1)
        restarted = PersistentStorageManager(f.root / "storage", global_artifact_root=f.root / "artifacts")
        saved = json.loads(bindings[0].read_text())
        self.assertEqual(restarted.resolve_session_artifact_root(saved["session_id"]), f.root / "artifacts")
