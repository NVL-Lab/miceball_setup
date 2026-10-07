import asyncio
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import h5py

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    DurablePublicationError, InMemoryIngestor, NatsCommunicationBoundary,
    NatsIngestorCommunication, PersistentStorageManager, SshRetrievalEndpoint,
    SynchronizationManager,
)
from tests import test_artifact_retrieval as retrieval_tests
from tests import test_local_storage_hdf5 as hdf5_tests
from tests import test_scientific_output_preparation as preparation_tests


class EvidenceBrokerDouble:
    def __init__(self):
        self.messages = []
        self.callback = None
        self.failure = None
        self.deliver_immediately = True

    async def subscribe(self, subject, cb, **kwargs):
        self.callback = cb
        return subject

    async def publish(self, subject, data, stream):
        self.messages.append((subject, json.loads(data), stream))
        if self.failure is not None:
            raise self.failure
        if self.callback is not None and self.deliver_immediately:
            await self.callback(SimpleNamespace(data=data, ack=AsyncMock()))
        return SimpleNamespace(stream=stream)


class GlobalArtifactCollectionEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.retrieval = retrieval_tests.ArtifactRetrievalTests()
        self.writer = hdf5_tests.HDF5ScientificPersistenceTests()
        self.broker = EvidenceBrokerDouble()
        client = SimpleNamespace(is_connected=True, jetstream=lambda: self.broker)
        self.boundary = NatsCommunicationBoundary("storage_manager", "storage-001")
        with patch("lab_sync_acquisition.nats_communication.nats.connect", AsyncMock(return_value=client)):
            await self.boundary.connect()
        self.ingestor = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "session-recovery.jsonl")
        await NatsIngestorCommunication(self.boundary, self.ingestor).subscribe_evidence("session")

    def storage(self, records_path=None, node="node"):
        return PersistentStorageManager(
            records_path or self.root / "records.jsonl",
            global_artifact_root=self.root / "global",
            retrieval_endpoints={node: SshRetrievalEndpoint("lab-host", "scientist")},
            evidence_publisher=self.boundary.publish_evidence,
            component_id="storage-001",
        )

    def artifact(self, name="local", count=2):
        local = self.writer.manager(self.root / name)
        initial = self.writer.stream(local)
        local.append_rows(initial.storage_id, (self.writer.row(i) for i in range(count)))
        return local.finalize_all().manifests[0]

    async def collect(self, *manifests, failure_sources=()):
        files = {m.external_artifact_path or m.local_storage_path:
                 Path(m.local_storage_path).read_bytes() for m in manifests}
        sftp = retrieval_tests.SftpDouble(files, failures=failure_sources)
        mock_ssh, _ = self.retrieval.ssh(sftp)
        with mock_ssh:
            result = await self.storage().collect_artifacts_with_evidence(self.retrieval.handoff(*manifests))
        return result, sftp

    def evidence(self):
        self.assertEqual(len(self.broker.messages), 1)
        subject, message, stream = self.broker.messages[0]
        self.assertEqual(stream, "LAB_EVIDENCE")
        self.assertEqual(subject, "messages.session.evidence.storage_manager.storage-001.global_artifact_collection_evidence")
        self.assertTrue(message["is_persistent"])
        self.assertEqual(message["source_id"], "storage-001")
        self.assertEqual(message["session_id"], "session")
        self.assertEqual(set(message["payload"]), {"started_at", "finished_at", "artifact_results"})
        return message["payload"]

    async def test_multiple_attempts_publish_one_persistent_pass_with_manifest_identities(self):
        first, second = self.artifact("one"), self.artifact("two")
        second = replace(second, experiment_id="another-experiment", artifact_type="declared-type")
        result, sftp = await self.collect(first, second)
        self.assertTrue(result.succeeded)
        payload = self.evidence()
        self.assertEqual(len(sftp.opened), 2)
        for manifest, item in zip((first, second), payload["artifact_results"]):
            self.assertEqual(item["artifact_manifest_id"], manifest.artifact_manifest_id)
            self.assertEqual(item["experiment_id"], manifest.experiment_id)
            self.assertEqual(item["acquisition_node_id"], manifest.acquisition_node_id)
            self.assertEqual(item["artifact_type"], manifest.artifact_type)
            self.assertEqual(item["collection_status"], "success")
            self.assertEqual(item["verification_status"], "verified")
            self.assertEqual(Path(item["global_artifact_locator"]).stat().st_size, item["file_size_copied"])
            self.assertIsNone(item["failure_information"])
        self.assertEqual(len(self.ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]), 1)

    async def test_structural_invalidity_preserves_successful_copy_evidence(self):
        manifest = self.artifact()
        with h5py.File(manifest.local_storage_path, "r+") as artifact:
            del artifact["frame_index"]
        result, _ = await self.collect(manifest)
        item = self.evidence()["artifact_results"][0]
        self.assertFalse(result.succeeded)
        self.assertEqual((item["collection_status"], item["verification_status"]),
                         ("success", "structurally_invalid"))
        self.assertIn("frame_index", item["failure_information"])
        self.assertTrue(Path(item["global_artifact_locator"]).exists())

    async def test_external_artifact_remains_copied_unverified(self):
        manifest = self.artifact()
        external = replace(manifest, external_artifact_path="/external/recording.h5")
        _, sftp = await self.collect(external)
        self.assertEqual(sftp.opened, [(external.external_artifact_path, "rb")])
        item = self.evidence()["artifact_results"][0]
        self.assertEqual((item["collection_status"], item["verification_status"]),
                         ("success", "copied_unverified"))

    async def test_operational_verification_failure_remains_separate(self):
        manifest = self.artifact()
        original_open = Path.open

        def open_file(path, *args, **kwargs):
            if self.root / "global" in path.parents and args and args[0] == "rb":
                raise PermissionError("verification read unavailable")
            return original_open(path, *args, **kwargs)

        with patch("lab_sync_acquisition.storage.Path.open", new=open_file):
            await self.collect(manifest)
        item = self.evidence()["artifact_results"][0]
        self.assertEqual((item["collection_status"], item["verification_status"]),
                         ("success", "verification_failed"))
        self.assertIn("PermissionError", item["failure_information"])

    async def test_failed_retrieval_does_not_prevent_subsequent_attempt_or_invent_copy(self):
        first, second = self.artifact("one"), self.artifact("two")
        result, sftp = await self.collect(first, second, failure_sources=(first.local_storage_path,))
        self.assertFalse(result.succeeded)
        self.assertEqual([source for source, _ in sftp.opened], [first.local_storage_path, second.local_storage_path])
        failed, successful = self.evidence()["artifact_results"]
        self.assertEqual(failed["collection_status"], "failure")
        for field in ("verification_status", "global_artifact_locator", "file_size_copied"):
            self.assertIsNone(failed[field])
        self.assertIn("interrupted", failed["failure_information"])
        self.assertEqual(successful["verification_status"], "verified")

    async def test_wall_clock_bounds_cover_transfer_and_verification(self):
        manifest = self.artifact()
        with patch("lab_sync_acquisition.storage.time", side_effect=(1700000000.0, 1700000009.0)) as clock:
            await self.collect(manifest)
            self.assertEqual(clock.call_count, 2)
        payload = self.evidence()
        self.assertEqual((payload["started_at"], payload["finished_at"]), (1700000000.0, 1700000009.0))

    async def test_completed_copies_do_not_require_a_second_size_stat(self):
        first, second = self.artifact("one"), self.artifact("two")
        original_stat = Path.stat
        blocked_lookups = []

        def unavailable_size(path, *args, **kwargs):
            if self.root / "global" in path.parents and first.artifact_manifest_id in path.parts:
                blocked_lookups.append(path)
                raise PermissionError("copied-size lookup unavailable")
            return original_stat(path, *args, **kwargs)

        with patch("lab_sync_acquisition.storage.Path.stat", new=unavailable_size):
            result, sftp = await self.collect(first, second)
        self.assertTrue(result.succeeded)
        self.assertEqual(len(sftp.opened), 2)
        self.assertEqual(blocked_lookups, [])
        for item in self.evidence()["artifact_results"]:
            self.assertEqual(item["file_size_copied"], Path(item["global_artifact_locator"]).stat().st_size)

    async def test_unavailable_copy_position_preserves_outcomes_and_later_attempts(self):
        first, second = self.artifact("one"), self.artifact("two")
        original_temporary_file = tempfile.NamedTemporaryFile
        created = []

        def unavailable_position(**kwargs):
            temporary = original_temporary_file(**kwargs)
            created.append(temporary.name)
            if len(created) != 1:
                return temporary

            class PositionUnavailable:
                def __enter__(self):
                    temporary.__enter__()
                    return self

                def __exit__(self, *args):
                    return temporary.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(temporary, name)

                def tell(self):
                    raise OSError("copy position unavailable")

            return PositionUnavailable()

        with patch("lab_sync_acquisition.storage.NamedTemporaryFile", side_effect=unavailable_position):
            result, sftp = await self.collect(first, second)
        self.assertTrue(result.succeeded)
        self.assertEqual([source for source, _ in sftp.opened], [first.local_storage_path, second.local_storage_path])
        items = self.evidence()["artifact_results"]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual((item["collection_status"], item["verification_status"]), ("success", "verified"))
            self.assertIsNone(item["failure_information"])
            self.assertTrue(Path(item["global_artifact_locator"]).exists())
        self.assertIsNone(items[0]["file_size_copied"])
        self.assertEqual(items[1]["file_size_copied"], Path(second.local_storage_path).stat().st_size)

    async def test_publication_failure_propagates_existing_error_without_retry(self):
        manifest = self.artifact()
        self.broker.failure = ConnectionError("JetStream unavailable")
        with self.assertRaises(DurablePublicationError) as caught:
            await self.collect(manifest)
        self.assertEqual(len(self.broker.messages), 1)
        self.assertEqual(caught.exception.intended_stream, "LAB_EVIDENCE")
        self.assertEqual(caught.exception.message_class, "evidence")
        self.assertEqual(self.ingestor.accepted_runtime_evidence, ())

    async def test_rejected_handoff_is_not_a_completed_collection_pass(self):
        with self.assertRaises(ValueError):
            await self.storage().collect_artifacts_with_evidence({"session_id": "session"})
        self.assertEqual(self.broker.messages, [])

    async def test_configured_publication_cannot_be_silently_bypassed(self):
        with self.assertRaisesRegex(RuntimeError, "await collect_artifacts_with_evidence"):
            self.storage().collect_artifacts({"session_id": "session", "artifacts": []})
        self.assertEqual(self.broker.messages, [])

    async def test_empty_completed_pass_still_publishes_one_record(self):
        result = await self.storage().collect_artifacts_with_evidence({"session_id": "session", "artifacts": []})
        self.assertTrue(result.succeeded)
        self.assertEqual(self.evidence()["artifact_results"], [])

    async def test_interrupted_pass_does_not_publish_unattempted_artifacts(self):
        first, second = self.artifact("one"), self.artifact("two")
        mock_ssh, _ = self.retrieval.ssh(retrieval_tests.SftpDouble({}))
        with mock_ssh, patch("lab_sync_acquisition.storage.Path.mkdir", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                await self.storage().collect_artifacts_with_evidence(self.retrieval.handoff(first, second))
        self.assertEqual(self.broker.messages, [])

    async def test_controller_collects_before_archive_finalization_without_changing_scientific_time(self):
        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        sync = SynchronizationManager()
        ingestors = []

        def ingestor(**kwargs):
            instance = InMemoryIngestor(**kwargs, session_id="session-001",
                                       recovery_journal_path=self.root / "controller-recovery.jsonl")
            ingestors.append(instance)
            return instance

        with patch("tests.test_scientific_output_preparation.PersistentStorageManager",
                   side_effect=lambda path: self.storage(path, node="node-001")), \
                patch("tests.test_scientific_output_preparation.InMemoryIngestor", side_effect=ingestor), \
                patch("tests.test_scientific_output_preparation.SynchronizationManager", return_value=sync):
            controller, node, _ = fixture.fixture(self.root)
        await NatsIngestorCommunication(self.boundary, ingestors[0]).subscribe_evidence("session-001")
        fixture.start_session(controller, node)
        self.assertTrue(controller.start_experiment("experiment", scientific_outputs=(fixture.output(),)).succeeded)
        self.assertTrue(controller.stop_experiment("experiment").succeeded)
        self.assertEqual(self.broker.messages, [])
        rejected = await controller.collect_session_artifacts_with_evidence()
        self.assertFalse(rejected.succeeded)
        self.assertEqual(controller.get_status()["session_state"], "running")
        self.assertTrue(controller.stop_session().succeeded)
        frozen_time = sync.current_session_time_s
        manifest = node.local_storage_manager.manifests[0]
        sftp = retrieval_tests.SftpDouble({manifest.local_storage_path: Path(manifest.local_storage_path).read_bytes()})
        mock_ssh, _ = self.retrieval.ssh(sftp)
        with mock_ssh:
            collection = await controller.collect_session_artifacts_with_evidence()
        self.assertTrue(collection.succeeded, collection.error)
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertEqual(sync.current_session_time_s, frozen_time)
        self.assertFalse((self.root / "session_session-001/evidence/runtime_evidence.jsonl").exists())
        final = controller.finalize_session()
        self.assertTrue(final.succeeded, final.error)
        archived = [json.loads(line) for line in Path(final.details["evidence_archive_paths"]["runtime_evidence"]).read_text().splitlines()]
        self.assertEqual(archived[-1], self.broker.messages[0][1])
        self.assertEqual(controller.get_status()["session_state"], "completed")

    async def test_controller_reports_publication_failure_without_lifecycle_policy(self):
        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        with patch("tests.test_scientific_output_preparation.PersistentStorageManager",
                   side_effect=lambda path: self.storage(path, node="node-001")):
            controller, node, _ = fixture.fixture(self.root)
        fixture.start_session(controller, node)
        self.assertTrue(controller.stop_session().succeeded)
        self.broker.failure = ConnectionError("JetStream unavailable")
        result = await controller.collect_session_artifacts_with_evidence()
        self.assertFalse(result.succeeded)
        self.assertIn("DurablePublicationError", result.error)
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertEqual(len(self.broker.messages), 1)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(controller.get_status()["session_state"], "completed")

    async def test_finalization_rejects_pending_publication_and_succeeds_after_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()
        published = []

        async def publisher(message):
            entered.set()
            await release.wait()
            published.append(message)

        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        with patch("tests.test_scientific_output_preparation.PersistentStorageManager",
                   side_effect=lambda path: PersistentStorageManager(path, evidence_publisher=publisher)):
            controller, node, _ = fixture.fixture(self.root)
        fixture.start_session(controller, node)
        self.assertTrue(controller.stop_session().succeeded)
        task = asyncio.create_task(controller.collect_session_artifacts_with_evidence())
        await entered.wait()
        try:
            rejected = controller.finalize_session()
            self.assertFalse(rejected.succeeded)
            self.assertIn("in progress", rejected.error)
            self.assertEqual(controller.get_status()["session_state"], "stopping")
            self.assertEqual(published, [])
            self.assertFalse((self.root / "session_session-001/evidence/runtime_evidence.jsonl").exists())
            duplicate = await controller.collect_session_artifacts_with_evidence()
            self.assertFalse(duplicate.succeeded)
            self.assertFalse(controller.finalize_session().succeeded)
        finally:
            release.set()
            collection = await task
        self.assertTrue(collection.succeeded)
        self.assertEqual(len(published), 1)
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(controller.get_status()["session_state"], "completed")

    async def test_cancelled_collection_releases_finalization_guard(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def publisher(message):
            entered.set()
            await release.wait()

        fixture = preparation_tests.ScientificOutputPreparationTests()
        fixture.nodes = []
        with patch("tests.test_scientific_output_preparation.PersistentStorageManager",
                   side_effect=lambda path: PersistentStorageManager(path, evidence_publisher=publisher)):
            controller, node, _ = fixture.fixture(self.root)
        fixture.start_session(controller, node)
        self.assertTrue(controller.stop_session().succeeded)
        task = asyncio.create_task(controller.collect_session_artifacts_with_evidence())
        await entered.wait()
        self.assertFalse(controller.finalize_session().succeeded)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(controller.get_status()["session_state"], "stopping")
        self.assertTrue(controller.finalize_session().succeeded)

    async def test_durable_acceptance_does_not_claim_ingestor_consumption(self):
        self.broker.deliver_immediately = False
        await self.collect(self.artifact())
        self.assertEqual(len(self.broker.messages), 1)
        self.assertEqual(self.ingestor.accepted_runtime_evidence, ())


if __name__ == "__main__":
    unittest.main()
