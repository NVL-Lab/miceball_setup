import io
import os
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    ArtifactManifest, LocalStorageManager, PersistentStorageManager,
    SshRetrievalEndpoint,
)
from tests import test_artifact_collection_handoff as handoff_tests


class SftpDouble:
    def __init__(self, files, failures=()):
        self.files = files
        self.failures = set(failures)
        self.opened = []
        self.readers = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def open(self, source, mode):
        self.opened.append((source, mode))
        if source in self.failures:
            class InterruptedReader(io.BytesIO):
                def read(self, size=-1):
                    if self.tell():
                        raise OSError("SFTP transfer interrupted")
                    return super().read(size)
            reader = InterruptedReader(b"partial")
        else:
            reader = io.BytesIO(self.files[source])
        self.readers.append(reader)
        return reader


class ArtifactRetrievalTests(unittest.TestCase):
    def manifest(self, identity="artifact", source="/node/frames.h5", **changes):
        return ArtifactManifest(
            identity, "session", "experiment", "node", "camera", "frames",
            changes.get("lifecycle_state", "finalized"), "storage-" + identity,
            source, changes.get("external_artifact_path"),
            ("/node/metadata.json", source, "/node/artifact_manifest.json"), {},
        )

    def handoff(self, *manifests):
        return {"session_id": "session", "artifacts": [
            {"artifact_manifest": manifest.to_dict(),
             "missing_finalization_evidence": manifest.lifecycle_state != "finalized"}
            for manifest in manifests]}

    def storage(self, root, endpoints=None):
        return PersistentStorageManager(
            root / "records.jsonl", global_artifact_root=root / "global",
            retrieval_endpoints=endpoints if endpoints is not None else {
                "node": SshRetrievalEndpoint("lab-host", "scientist", port=2222,
                                             key_filename="key", known_hosts_path="hosts")},
        )

    def ssh(self, sftp):
        client = MagicMock()
        client.__enter__.return_value = client
        client.open_sftp.return_value = sftp
        module = SimpleNamespace(SSHClient=MagicMock(return_value=client))
        return patch.dict(sys.modules, {"paramiko": module}), client

    def test_framework_file_uses_temporary_destination_and_exact_hierarchy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sftp = SftpDouble({"/node/frames.h5": b"scientific frames"})
            mock_ssh, client = self.ssh(sftp)
            destination = root / "global/session/experiment/node/artifact/frames.h5"
            real_link = os.link

            def promote(temporary, final):
                self.assertEqual(final, destination)
                self.assertEqual(temporary.parent, destination.parent)
                self.assertTrue(temporary.name.startswith(".incomplete-"))
                self.assertFalse(destination.exists())
                self.assertEqual(temporary.read_bytes(), b"scientific frames")
                self.assertTrue(sftp.readers[0].closed)
                real_link(temporary, final)

            with mock_ssh, patch("lab_sync_acquisition.storage.os.link", side_effect=promote):
                result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertEqual(result.to_dict(), {"succeeded": False, "artifact_results": [{
                "artifact_manifest_id": "artifact", "outcome": "success",
                "global_destination": str(destination), "verification_outcome": "copied_unverified",
                "verification_information": "No applicable light-verification contract"}]})
            self.assertEqual(destination.read_bytes(), b"scientific frames")
            self.assertEqual(list(destination.parent.iterdir()), [destination])
            self.assertEqual(sftp.opened, [("/node/frames.h5", "rb")])
            client.connect.assert_called_once_with(
                hostname="lab-host", username="scientist", port=2222, key_filename="key")
            client.load_host_keys.assert_called_once_with("hosts")

    def test_external_file_and_separate_timing_artifact_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = self.manifest(external_artifact_path="/external/video.mp4")
            timing = self.manifest("timing", "/node/timing.jsonl")
            sftp = SftpDouble({"/external/video.mp4": b"video", "/node/timing.jsonl": b"timing"})
            mock_ssh, _ = self.ssh(sftp)
            with mock_ssh:
                result = self.storage(root).collect_artifacts(self.handoff(external, timing))
            self.assertFalse(result.succeeded)
            self.assertTrue(all(r.outcome == "success" for r in result.artifact_results))
            self.assertEqual(sftp.opened, [("/external/video.mp4", "rb"), ("/node/timing.jsonl", "rb")])
            self.assertEqual(len(result.artifact_results), 2)

    def test_missing_finalization_is_still_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            handoff = self.handoff(self.manifest(lifecycle_state="open"))
            sftp = SftpDouble({"/node/frames.h5": b"unfinished"})
            mock_ssh, _ = self.ssh(sftp)
            with mock_ssh:
                result = self.storage(Path(directory)).collect_artifacts(handoff)
            self.assertFalse(result.succeeded)
            self.assertEqual(result.artifact_results[0].outcome, "success")
            self.assertTrue(handoff["artifacts"][0]["missing_finalization_evidence"])
            self.assertEqual(handoff["artifacts"][0]["artifact_manifest"]["lifecycle_state"], "open")

    def test_interrupted_transfer_preserves_source_and_attempts_later_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {"/node/bad.h5": b"original", "/node/good.h5": b"good"}
            sftp = SftpDouble(files, failures=("/node/bad.h5",))
            mock_ssh, _ = self.ssh(sftp)
            with mock_ssh:
                result = self.storage(root).collect_artifacts(self.handoff(
                    self.manifest("bad", "/node/bad.h5"), self.manifest("good", "/node/good.h5")))
            self.assertFalse(result.succeeded)
            self.assertEqual(result.artifact_results[0].to_dict(), {
                "artifact_manifest_id": "bad", "outcome": "failure",
                "failure_information": "OSError: SFTP transfer interrupted"})
            self.assertEqual(result.artifact_results[1].outcome, "success")
            self.assertFalse((root / "global/session/experiment/node/bad/bad.h5").exists())
            self.assertFalse(list((root / "global").rglob(".incomplete-*")))
            self.assertEqual(files, {"/node/bad.h5": b"original", "/node/good.h5": b"good"})

    def test_existing_destination_is_not_overwritten_or_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "global/session/experiment/node/artifact/frames.h5"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"existing")
            sftp = SftpDouble({"/node/frames.h5": b"new"})
            mock_ssh, client = self.ssh(sftp)
            with mock_ssh:
                result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertEqual(destination.read_bytes(), b"existing")
            client.connect.assert_not_called()

    def test_collision_during_promotion_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_link = os.link

            def collision(temporary, final):
                final.write_bytes(b"concurrent copy")
                real_link(temporary, final)

            mock_ssh, _ = self.ssh(SftpDouble({"/node/frames.h5": b"new"}))
            with mock_ssh, patch("lab_sync_acquisition.storage.os.link", side_effect=collision):
                result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertEqual((root / "global/session/experiment/node/artifact/frames.h5").read_bytes(), b"concurrent copy")

    def test_unconfigured_endpoint_fails_only_that_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            sftp = SftpDouble({"/node/frames.h5": b"frames"})
            mock_ssh, _ = self.ssh(sftp)
            with mock_ssh:
                result = self.storage(Path(directory)).collect_artifacts(self.handoff(
                    replace(self.manifest("missing"), acquisition_node_id="unconfigured"), self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertIn("not configured", result.artifact_results[0].failure_information)
            self.assertEqual(result.artifact_results[1].outcome, "success")

    def test_connection_failure_becomes_artifact_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            mock_ssh, client = self.ssh(SftpDouble({}))
            client.connect.side_effect = ConnectionError("SSH unavailable")
            with mock_ssh:
                result = self.storage(Path(directory)).collect_artifacts(self.handoff(self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertIn("SSH unavailable", result.artifact_results[0].failure_information)
            self.assertFalse(list((Path(directory) / "global").rglob(".incomplete-*")))

    def test_promotion_and_destination_write_failures_do_not_leave_final_files(self):
        for operation in ("os.link", "shutil.copyfileobj"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                mock_ssh, _ = self.ssh(SftpDouble({"/node/frames.h5": b"frames"}))
                with mock_ssh, patch("lab_sync_acquisition.storage." + operation,
                                     side_effect=OSError("destination failed")):
                    result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
                self.assertFalse(result.succeeded)
                self.assertFalse((root / "global/session/experiment/node/artifact/frames.h5").exists())
                self.assertFalse(list((root / "global").rglob(".incomplete-*")))

    def test_malformed_entry_and_session_mismatch_do_not_stop_valid_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            handoff = self.handoff(replace(self.manifest("other"), session_id="other"), self.manifest())
            handoff["artifacts"].insert(0, {"artifact_manifest": {"artifact_manifest_id": "incomplete"}})
            mock_ssh, _ = self.ssh(SftpDouble({"/node/frames.h5": b"frames"}))
            with mock_ssh:
                result = self.storage(Path(directory)).collect_artifacts(handoff)
            self.assertEqual([r.outcome for r in result.artifact_results], ["failure", "failure", "success"])
            self.assertEqual(result.artifact_results[0].artifact_manifest_id, "incomplete")

    def test_invalid_source_and_destination_identity_are_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = (replace(self.manifest(), external_artifact_path=""),
                       replace(self.manifest(), local_storage_path="/node/"),
                       replace(self.manifest(), experiment_id="../escape"))
            result = self.storage(Path(directory)).collect_artifacts(self.handoff(*invalid))
            self.assertFalse(result.succeeded)
            self.assertTrue(all(r.outcome == "failure" for r in result.artifact_results))

    def test_empty_and_malformed_handoffs_have_explicit_aggregate_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = self.storage(Path(directory))
            self.assertEqual(storage.collect_artifacts(self.handoff()).to_dict(),
                             {"succeeded": True, "artifact_results": []})
            self.assertFalse(storage.collect_artifacts({}).succeeded)

    def test_framework_stream_creation_keeps_single_file_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            local = LocalStorageManager(directory, "session", "node")
            manifest = local.create_stream(
                session_id="session", experiment_id="experiment", acquisition_node_id="node",
                source_component_id="camera", data_product_id="timing", artifact_type="timing",
                schema={"frame_index": "integer"},
            )
            try:
                self.assertIsNone(manifest.external_artifact_path)
                self.assertEqual(ArtifactManifest.from_dict(manifest.to_dict()), manifest)
                self.assertEqual(Path(manifest.local_storage_path).name, "rows.jsonl")
            finally:
                local.cleanup()

    def test_multiple_nodes_and_experiments_keep_distinct_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.manifest()
            second = replace(self.manifest("second"), acquisition_node_id="node-two", experiment_id="experiment-two")
            mock_ssh, client = self.ssh(SftpDouble({"/node/frames.h5": b"frames"}))
            endpoints = {"node": SshRetrievalEndpoint("first-host", "scientist"),
                         "node-two": SshRetrievalEndpoint("second-host", "scientist")}
            with mock_ssh:
                result = self.storage(root, endpoints).collect_artifacts(self.handoff(first, second))
            self.assertFalse(result.succeeded)
            self.assertTrue(all(r.outcome == "success" for r in result.artifact_results))
            self.assertEqual([call.kwargs["hostname"] for call in client.connect.call_args_list],
                             ["first-host", "second-host"])
            self.assertEqual(Path(result.artifact_results[1].global_destination),
                             root / "global/session/experiment-two/node-two/second/frames.h5")

    def test_destination_close_failure_prevents_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            from tempfile import NamedTemporaryFile

            def failing_close(**kwargs):
                temporary = NamedTemporaryFile(**kwargs)

                class FailingClose:
                    def __enter__(self):
                        return temporary

                    def __exit__(self, *args):
                        temporary.close()
                        raise OSError("destination close failed")

                return FailingClose()

            mock_ssh, _ = self.ssh(SftpDouble({"/node/frames.h5": b"frames"}))
            with mock_ssh, patch("lab_sync_acquisition.storage.NamedTemporaryFile", side_effect=failing_close):
                result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
            self.assertFalse(result.succeeded)
            self.assertIn("destination close failed", result.artifact_results[0].failure_information)
            self.assertFalse((root / "global/session/experiment/node/artifact/frames.h5").exists())
            self.assertFalse(list((root / "global").rglob(".incomplete-*")))

    def test_temporary_cleanup_failure_does_not_mask_transfer_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock_ssh, client = self.ssh(SftpDouble({}))
            client.connect.side_effect = ConnectionError("primary SSH failure")
            with mock_ssh, patch("lab_sync_acquisition.storage.Path.unlink", side_effect=OSError("cleanup failed")):
                result = self.storage(root).collect_artifacts(self.handoff(self.manifest()))
            self.assertIn("primary SSH failure", result.artifact_results[0].failure_information)
            self.assertFalse((root / "global/session/experiment/node/artifact/frames.h5").exists())

    def test_controller_initiates_collection_after_finalization_without_lifecycle_change(self):
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = handoff_tests.ArtifactCollectionHandoffTests()

                def configured_storage(records_path):
                    return PersistentStorageManager(
                        records_path, global_artifact_root=root / "global",
                        retrieval_endpoints={"node-001": SshRetrievalEndpoint("jetson", "scientist")})

                with patch("tests.test_scientific_output_preparation.PersistentStorageManager",
                           side_effect=configured_storage):
                    preparation, controller, node = fixture.workflow(root)
                self.assertTrue(controller.start_experiment(
                    "experiment", scientific_outputs=(preparation.output("events"),)).succeeded)
                self.assertTrue(controller.stop_experiment("experiment").succeeded)
                self.assertTrue(controller.stop_session().succeeded)
                finalization = controller.finalize_session()
                self.assertTrue(finalization.succeeded)
                manifest = node.local_storage_manager.manifests[0]
                source_bytes = Path(manifest.local_storage_path).read_bytes()
                sftp = SftpDouble({manifest.local_storage_path: source_bytes})
                mock_ssh, client = self.ssh(sftp)
                if failure:
                    client.connect.side_effect = ConnectionError("SSH unavailable")
                record_path = Path(finalization.details["session_record_path"])
                record_before = record_path.read_bytes()
                archive = Path(finalization.details["evidence_archive_paths"]["runtime_evidence"])
                archive_before = archive.read_bytes()
                with mock_ssh:
                    result = controller.collect_session_artifacts()
                self.assertFalse(result.succeeded)
                self.assertEqual(controller.get_status()["session_state"], "completed")
                collection = result.details["artifact_collection_result"]
                self.assertFalse(collection["succeeded"])
                self.assertEqual(collection["artifact_results"][0]["outcome"],
                                 "failure" if failure else "success")
                self.assertEqual(collection["artifact_results"][0]["artifact_manifest_id"], manifest.artifact_manifest_id)
                self.assertEqual(record_path.read_bytes(), record_before)
                self.assertEqual(archive.read_bytes(), archive_before)
                self.assertEqual(Path(manifest.local_storage_path).read_bytes(), source_bytes)
