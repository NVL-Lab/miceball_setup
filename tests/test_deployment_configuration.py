"""Deployment-local inputs consumed through the common service launcher."""

import io
import json
from contextlib import redirect_stderr
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition.deployment_configuration import load_service_configuration
from lab_sync_acquisition import PersistentStorageManager
from lab_sync_acquisition.service_launcher import ServiceLauncher, launch_storage_services, main
from lab_sync_acquisition.service_startup import load_acquisition_node


class DeploymentConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "service.json"
        self.common = {"servers": ["nats://offline.invalid:4222"], "ingestor_id": "intake",
                       "storage_id": "storage", "preservation_window_s": 1}
        self.hardware = {"node_id": "node", "role": "acquisition", "local_storage_root": "science",
            "error_evidence_location": "errors", "devices": [{"adapter": "seeed_imx219_opencv",
                "declaration": {"device_id": "camera", "device_type": "camera", "enabled": True,
                    "required": True, "declared_capabilities": ["frames"], "scientific_products": []},
                "configuration": {"camera_source": 7, "api_preference": 0, "frames_per_collect": 1}}]}
        (self.root / "hardware.json").write_text(json.dumps(self.hardware), encoding="utf-8")
        self.roles = {
            "controller": {**self.common, "service_id": "control", "synchronization_id": "clock",
                           "known_nodes": ["node"], "result_window_s": 1},
            "synchronization-manager": {**self.common, "service_id": "clock", "result_window_s": 1},
            "acquisition-node": {**self.common, "synchronization_id": "clock", "node_config": "hardware.json",
                                 "result_window_s": 1},
            "ingestor": {**self.common, "storage_root": "records", "global_artifact_root": "artifacts",
                "recovery_journal_root": "journals", "framework_journal": "framework.jsonl",
                "no_operational_dependents": True, "retrieval_endpoints": {}},
        }
        self.roles["storage-manager"] = deepcopy(self.roles["ingestor"])

    def load(self, role, data=None):
        self.path.write_text(json.dumps(self.roles[role] if data is None else data), encoding="utf-8")
        return load_service_configuration(self.path, role)

    def test_each_role_loads_its_explicit_installation_settings(self):
        for role in self.roles:
            with self.subTest(role=role):
                settings = self.load(role)
                self.assertEqual(settings["servers"], ("nats://offline.invalid:4222",))
                self.assertEqual(settings["ingestor_id"], "intake")
        self.assertEqual(self.load("controller")["known_nodes"], ("node",))
        self.assertEqual(self.load("ingestor")["storage_root"], self.root / "records")

    def test_controller_external_client_is_explicit_optional_and_strictly_validated(self):
        self.assertNotIn("external_client_id", self.load("controller"))
        self.assertEqual(self.load("controller", {**self.roles["controller"], "external_client_id": "tester"})["external_client_id"], "tester")
        for value in (None, "", "*", "two.clients"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load("controller", {**self.roles["controller"], "external_client_id": value})
        with self.assertRaises(ValueError):
            self.load("synchronization-manager", {**self.roles["synchronization-manager"], "external_client_id": "tester"})

    def test_node_validation_does_not_construct_an_owner_or_open_hardware(self):
        with patch("lab_sync_acquisition.service_startup.AcquisitionNode") as owner, patch(
                "lab_sync_acquisition.service_startup.SeeedIMX219OpenCVCameraAdapter") as adapter:
            settings = self.load("acquisition-node")
            owner.assert_not_called()
            adapter.assert_not_called()
        self.assertEqual(settings["service_id"], "node")
        node = load_acquisition_node(settings["node_config"], settings["synchronization_id"])
        self.assertFalse(node.status()["is_running"])
        self.assertEqual(node.node_id, "node")

    def test_malformed_missing_duplicate_and_session_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Deployment configuration"):
            load_service_configuration(self.path, "controller")
        for text in ('{bad', '[]', '{"servers":[],"servers":[]}', '{"role":"controller"}'):
            self.path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_service_configuration(self.path, "controller")
        for key, value in (("session_id", "session"), ("device_configurations", {}),
                           ("known_nodes", ["node", "node"]), ("servers", []),
                           ("servers", [False]), ("servers", ["nats://host:70000"]),
                           ("service_id", "bad.id"), ("result_window_s", True),
                           ("preservation_window_s", float("nan"))):
            data = {**self.roles["controller"], key: value}
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                self.load("controller", data)

    def test_invalid_hardware_or_identity_fails_before_startup(self):
        data = {**self.roles["acquisition-node"], "service_id": "different"}
        with self.assertRaisesRegex(ValueError, "persistent node_id"):
            self.load("acquisition-node", data)
        self.hardware["devices"][0]["adapter"] = "unknown"
        (self.root / "hardware.json").write_text(json.dumps(self.hardware), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported installed adapter"):
            self.load("acquisition-node")

    def test_retrieval_configuration_is_local_and_does_not_contact_offline_nodes(self):
        key = self.root / "test-key-reference"
        key.write_text("test fixture, not a private key", encoding="utf-8")
        data = deepcopy(self.roles["storage-manager"])
        data["retrieval_endpoints"] = {"node": {"host": "offline.invalid", "username": "operator",
                                               "key_filename": key.name, "port": 2222}}
        endpoint = self.load("storage-manager", data)["retrieval_endpoints"]["node"]
        self.assertEqual(endpoint.host, "offline.invalid")
        self.assertEqual(endpoint.key_filename, str(key))
        self.assertEqual(endpoint.port, 2222)
        for changes in ({"port": True}, {"port": 0}, {"key_filename": "missing"}, {"host": ""}):
            broken = deepcopy(data)
            broken["retrieval_endpoints"]["node"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load("storage-manager", broken)

    def test_file_mode_never_assumes_operational_dependents_are_absent(self):
        for value in (None, False, [], "true"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "operational_dependents"):
                self.load("ingestor", {**self.roles["ingestor"], "no_operational_dependents": value})

    def test_file_changes_are_loaded_only_on_the_next_explicit_load(self):
        first = self.load("controller")
        updated = {**self.roles["controller"], "known_nodes": ["another-node"]}
        second = self.load("controller", updated)
        self.assertEqual(first["known_nodes"], ("node",))
        self.assertEqual(second["known_nodes"], ("another-node",))

    def test_common_cli_dispatches_all_roles_without_replacing_the_launchers(self):
        async def capture(**settings):
            captured.append(settings)
            return 0

        def run(coro):
            try:
                coro.send(None)
            except StopIteration as result:
                return result.value
            self.fail("The injected launcher unexpectedly suspended")

        for role in self.roles:
            with self.subTest(role=role):
                captured = []
                self.load(role)
                target = ("lab_sync_acquisition.service_launcher.launch_storage_services" if role in
                          {"ingestor", "storage-manager"} else "lab_sync_acquisition.service_startup.launch_independent_service")
                with patch(target, capture), patch("lab_sync_acquisition.service_launcher.asyncio.run", run):
                    self.assertEqual(main([role, "--deployment-config", str(self.path)]), 0)
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]["ingestor_id"], "intake")
                if role in {"ingestor", "storage-manager"}:
                    self.assertEqual(captured[0]["operational_dependents"], {})
                    self.assertEqual(captured[0]["global_artifact_root"], self.root / "artifacts")
                else:
                    self.assertEqual(captured[0]["role"], role)

    def test_invalid_files_and_mixed_inputs_cannot_start_services(self):
        self.path.write_text('{"servers": []}', encoding="utf-8")
        with patch("lab_sync_acquisition.service_launcher.asyncio.run") as run, redirect_stderr(io.StringIO()) as output:
            self.assertNotEqual(main(["controller", "--deployment-config", str(self.path)]), 0)
            run.assert_not_called()
        self.assertIn("Deployment configuration", output.getvalue())
        for flags in (["--server", "nats://other:4222"], ["--config", "other.json"],
                      ["--preservation-window-s", "0"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["controller", "--deployment-config", str(self.path), *flags])


class ConfiguredStorageStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_process_uses_configured_retrieval_without_connecting_to_nodes(self):
        from tests.test_session_launch import _Boundary, _Broker
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / "key-reference").write_text("test reference, not a key", encoding="utf-8")
        path = root / "deployment.json"
        path.write_text(json.dumps({"servers": ["nats://broker.invalid:4222"], "ingestor_id": "intake",
            "storage_id": "storage", "storage_root": "records", "global_artifact_root": "artifacts",
            "recovery_journal_root": "journals", "framework_journal": "framework.jsonl",
            "preservation_window_s": 0, "no_operational_dependents": True,
            "retrieval_endpoints": {"node": {"host": "offline.invalid", "username": "operator",
                                              "key_filename": "key-reference"}}}), encoding="utf-8")
        broker = _Broker()
        boundaries = []

        def boundary(kind, identity, servers):
            value = _Boundary(kind, identity, broker)
            value.connect = AsyncMock()
            value.ensure_streams = AsyncMock()
            value.close = AsyncMock()
            boundaries.append(value)
            return value

        async def run(launcher, *, startup):
            await startup()
            self.assertEqual({m.participant.component_type for m in launcher.maintenance},
                             {"ingestor", "storage_manager"})
            self.assertTrue(all(m.service.check_ready().ready for m in launcher.maintenance))
            self.assertTrue(await launcher.stop_locally("operator"))
            return 0

        with patch("lab_sync_acquisition.service_launcher.NatsCommunicationBoundary", boundary), patch.object(
                ServiceLauncher, "run", run), patch(
                "lab_sync_acquisition.service_launcher.PersistentStorageManager", wraps=PersistentStorageManager) as storage, patch.object(
                PersistentStorageManager, "_pull_sftp_file", side_effect=AssertionError("Unexpected node connectivity check")) as transfer:
            self.assertEqual(await launch_storage_services(**load_service_configuration(path, "ingestor"), report=lambda _: None), 0)
            transfer.assert_not_called()
            self.assertEqual(storage.call_args.kwargs["global_artifact_root"], root / "artifacts")
            self.assertEqual(storage.call_args.kwargs["retrieval_endpoints"]["node"].host, "offline.invalid")
        self.assertEqual(len(boundaries), 2)


if __name__ == "__main__":
    unittest.main()
