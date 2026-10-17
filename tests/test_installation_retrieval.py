"""Explicit installation verification through StorageManager's existing SFTP path."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import PersistentStorageManager
from lab_sync_acquisition.deployment_configuration import load_retrieval_configuration, load_service_configuration
from lab_sync_acquisition.service_launcher import main
from tests import test_artifact_retrieval as retrieval_tests
from tests.test_artifact_retrieval import SftpDouble


class InstallationRetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / "service.json"
        self.expected = self.root / "expected.txt"
        self.expected.write_bytes(b"installation retrieval check\n")
        (self.root / "key").write_text("fixture reference, not a key", encoding="utf-8")
        (self.root / "hosts").write_text("fixture host reference", encoding="utf-8")
        self.settings = {"servers": ["nats://unused.invalid:4222"], "ingestor_id": "intake",
            "storage_id": "storage", "storage_root": "records", "global_artifact_root": "science",
            "recovery_journal_root": "journals", "framework_journal": "framework.jsonl",
            "preservation_window_s": 1, "no_operational_dependents": None,
            "retrieval_endpoints": {"node": {"host": "node.invalid", "username": "scientist", "port": 2222,
                                              "key_filename": "key", "known_hosts_path": "hosts"}}}
        self.config.write_text(json.dumps(self.settings), encoding="utf-8")
        (self.root / "science").mkdir()
        (self.root / "science" / "existing-artifact.bin").write_bytes(b"scientific artifact: unchanged")
        self.source = "/installation/check.txt"

    def invoke(self, *, node="node", max_bytes=1024):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["verify-retrieval", "--deployment-config", str(self.config), "--node-id", node,
                         "--source-path", self.source, "--expected-file", str(self.expected),
                         "--max-bytes", str(max_bytes)])
        return code, json.loads(output.getvalue())

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def test_exact_dummy_contents_pass_without_changing_scientific_or_session_products(self):
        sftp = SftpDouble({self.source: b"installation retrieval check\n", "/science/data.h5": b"science"})
        original = deepcopy(sftp.files)
        before = self.snapshot()
        transport, client = retrieval_tests.ArtifactRetrievalTests.ssh(self, sftp)
        with transport, patch("lab_sync_acquisition.service_launcher.asyncio.run") as runtime:
            code, result = self.invoke()
            runtime.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["node_id"], "node")
        self.assertTrue(result["retrieval_succeeded"])
        self.assertTrue(result["content_match"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "records").exists())
        self.assertFalse((self.root / "journals").exists())
        self.assertEqual(sftp.files, original)
        self.assertEqual(sftp.opened, [(self.source, "rb")])
        self.assertTrue(all(reader.closed for reader in sftp.readers))
        client.load_system_host_keys.assert_called_once()
        client.load_host_keys.assert_called_once_with(str(self.root / "hosts"))
        client.set_missing_host_key_policy.assert_not_called()
        client.connect.assert_called_once_with(hostname="node.invalid", username="scientist", port=2222,
                                               key_filename=str(self.root / "key"))

    def test_unknown_or_missing_node_identity_cannot_retrieve(self):
        transport, client = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({}))
        with transport:
            code, result = self.invoke(node="unknown")
        self.assertEqual(code, 1)
        self.assertIn("No retrieval endpoint", result["failure_reason"])
        self.assertFalse(result["retrieval_succeeded"])
        client.connect.assert_not_called()
        owner = PersistentStorageManager(**load_retrieval_configuration(self.config))
        result = owner.verify_installation_retrieval(None, self.source, b"expected", max_bytes=1024)
        self.assertEqual(result["outcome"], "FAIL")

    def test_missing_remote_dummy_is_a_failed_verification(self):
        sftp = SftpDouble({})
        transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, sftp)
        with transport, patch.object(sftp, "open", side_effect=FileNotFoundError("missing source")):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(result["retrieval_succeeded"])
        self.assertIsNone(result["content_match"])
        self.assertIn("not found", result["failure_reason"])

    def test_authentication_and_connection_failures_do_not_expose_exception_secrets(self):
        for error in (PermissionError("private key: SECRET"), ConnectionError("password=SECRET")):
            with self.subTest(error=type(error).__name__):
                transport, client = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({}))
                client.connect.side_effect = error
                with transport:
                    code, result = self.invoke()
                self.assertEqual(code, 1)
                self.assertEqual(result["outcome"], "FAIL")
                self.assertFalse(result["retrieval_succeeded"])
                self.assertIn(type(error).__name__, result["failure_reason"])
                self.assertNotIn("SECRET", json.dumps(result))

    def test_mismatched_and_truncated_contents_never_pass(self):
        for content in (b"different file\n", b"installation"):
            with self.subTest(content=content):
                transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({self.source: content}))
                with transport:
                    code, result = self.invoke()
                self.assertEqual(code, 1)
                self.assertTrue(result["retrieval_succeeded"])
                self.assertFalse(result["content_match"])

    def test_failed_transfer_cleans_up_verification_temporary_file(self):
        sftp = SftpDouble({}, failures=(self.source,))
        transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, sftp)
        opened = []
        before = self.snapshot()
        real_temporary = tempfile.TemporaryFile

        def temporary(**kwargs):
            handle = real_temporary(**kwargs)
            opened.append(handle)
            return handle

        with transport, patch("lab_sync_acquisition.storage.TemporaryFile", side_effect=temporary):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(result["retrieval_succeeded"])
        self.assertIsNone(result["content_match"])
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))
        self.assertTrue(all(reader.closed for reader in sftp.readers))
        self.assertEqual(self.snapshot(), before)

    def test_size_limit_bounds_temporary_writes_and_is_not_an_artifact_policy(self):
        self.expected.write_bytes(b"expected")
        transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({self.source: b"x" * 4096}))
        opened = []
        sizes = []
        real_temporary = tempfile.TemporaryFile

        @contextmanager
        def temporary(**kwargs):
            with real_temporary(**kwargs) as handle:
                opened.append(handle)
                try:
                    yield handle
                finally:
                    sizes.append(handle.seek(0, 2))

        before = self.snapshot()
        with transport, patch("lab_sync_acquisition.storage.TemporaryFile", side_effect=temporary):
            code, result = self.invoke(max_bytes=64)
        self.assertEqual(code, 1)
        self.assertIn("exceeds max_bytes", result["failure_reason"])
        self.assertTrue(all(handle.closed for handle in opened))
        self.assertTrue(sizes)
        self.assertTrue(all(size <= 64 for size in sizes))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_local_inputs_fail_without_starting_services_or_connecting(self):
        transport, client = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({}))
        with transport:
            code, result = self.invoke(max_bytes=2)
            self.assertEqual(code, 1)
            self.assertFalse(result["retrieval_succeeded"])
            self.expected.unlink()
            code, result = self.invoke()
            self.assertEqual(code, 1)
        client.connect.assert_not_called()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke(node="")

    def test_installation_readback_reuses_endpoint_validation_without_retiring_dependents(self):
        installation = load_retrieval_configuration(self.config)
        self.settings["no_operational_dependents"] = True
        self.config.write_text(json.dumps(self.settings), encoding="utf-8")
        startup = load_service_configuration(self.config, "storage-manager")
        self.assertEqual(installation["retrieval_endpoints"], startup["retrieval_endpoints"])
        (self.root / "key").unlink()
        with self.assertRaisesRegex(ValueError, "key_filename"):
            load_retrieval_configuration(self.config)

    def test_interruption_closes_temporary_destination_without_claiming_success(self):
        sftp = SftpDouble({})
        transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, sftp)
        opened = []
        real_temporary = tempfile.TemporaryFile

        def temporary(**kwargs):
            handle = real_temporary(**kwargs)
            opened.append(handle)
            return handle

        with transport, patch.object(sftp, "open", side_effect=KeyboardInterrupt("SECRET")), patch(
                "lab_sync_acquisition.storage.TemporaryFile", side_effect=temporary):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(result["outcome"], "FAIL")
        self.assertIn("interrupted", result["failure_reason"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertTrue(opened)
        self.assertTrue(all(handle.closed for handle in opened))

    def test_short_local_write_cannot_turn_a_wrong_source_into_a_match(self):
        class PartialWriter(io.BytesIO):
            def write(self, data):
                return super().write(data[:2])

        self.expected.write_bytes(b"ba")
        transport, _ = retrieval_tests.ArtifactRetrievalTests.ssh(self, SftpDouble({self.source: b"bad-extra"}))
        destination = PartialWriter()
        with transport, patch("lab_sync_acquisition.storage.TemporaryFile", return_value=destination):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(result["retrieval_succeeded"])
        self.assertIsNone(result["content_match"])
        self.assertTrue(destination.closed)


if __name__ == "__main__":
    unittest.main()
