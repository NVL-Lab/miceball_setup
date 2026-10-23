"""Interactive setup workflows with real configuration validation and isolated I/O."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_framework as installer
from lab_sync_acquisition.deployment_configuration import load_service_configuration


class FrameworkInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / "checkout with spaces"
        self.checkout.mkdir()
        self.checkout.joinpath("pyproject.toml").write_text(
            '[project]\nname="lab-sync-acquisition"\nrequires-python=">=3.12,<3.13"\n', encoding="utf-8")
        self.config = self.root / "private configuration"
        self.environment = self.checkout / ".venv"
        self.calls = []
        self.answers = {
            "Local roles": "controller",
            "NATS URLs": "nats://broker:4222",
            "Deployment Ingestor ID": "intake",
            "Deployment StorageManager ID": "storage",
            "Preservation window": "3",
            "Request/check window": "1",
            "Deployment SynchronizationManager ID": "clock",
            "Controller ID": "control",
            "Known AcquisitionNode IDs": "node",
            "Existing node hardware JSON path": "",
            "Actual external dependents": "controller/control,acquisition_node/node,synchronization_manager/clock",
            "All services": "yes",
            "Install the displayed": "yes",
            "NATS connectivity timeout": "1",
        }
        self.platform = sys.platform
        self.failure = None
        self.version = [3, 12]

    def hardware(self):
        path = self.root / "node hardware.json"
        path.write_text(json.dumps({"node_id": "node", "role": "acquisition",
            "local_storage_root": "scientific", "error_evidence_location": "errors", "devices": [{
                "adapter": "seeed_imx219_opencv", "declaration": {"device_id": "camera",
                    "device_type": "camera", "enabled": True, "required": True,
                    "declared_capabilities": ["camera_frames"], "scientific_products": []},
                "configuration": {"camera_source": 0, "api_preference": 0, "frames_per_collect": 1}}]}),
            encoding="utf-8")
        self.answers["Existing node hardware JSON path"] = str(path)
        return path

    def environment_python(self):
        return self.environment / ("Scripts/python.exe" if self.platform == "win32" else "bin/python")

    def create_environment(self):
        python = self.environment_python()
        python.parent.mkdir(parents=True)
        python.write_text("test interpreter placeholder", encoding="utf-8")

    def run_setup(self):
        output, errors = io.StringIO(), io.StringIO()

        def answer(prompt):
            return next((value for prefix, value in self.answers.items() if prompt.startswith(prefix)), "")

        def run(arguments, *, timeout=60):
            args = [str(a) for a in arguments]
            self.calls.append(args)
            if args[0] == "git":
                if "--show-toplevel" in args:
                    return str(self.checkout)
                return "" if "status" in args else "a" * 40
            if "venv" in args:
                self.create_environment()
            elif installer.ENVIRONMENT_REPORT in args:
                return json.dumps({"version": self.version, "prefix": str(self.environment),
                                   "base_prefix": str(self.root / "base-python")})
            elif "pip" in args:
                self.assertEqual(Path(args[0]), self.environment_python())
                if "install" in args and self.failure == "pip":
                    raise RuntimeError("Injected pip failure")
                if "install" in args and self.failure == "interrupt":
                    raise KeyboardInterrupt()
            elif installer.VALIDATE in args:
                # Run the unchanged production loader, not a fabricated validation result.
                load_service_configuration(args[-2], args[-1])
            elif installer.CONNECT in args:
                if self.failure == "nats":
                    raise subprocess.TimeoutExpired(args, timeout)
            else:
                raise AssertionError(f"Unexpected external operation: {args}")
            return ""

        with patch.object(installer, "_run", side_effect=run), patch("builtins.input", side_effect=answer), \
                patch.object(installer.sys, "platform", self.platform), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = installer.main(["--checkout", str(self.checkout), "--config-dir", str(self.config)])
        return code, output.getvalue(), errors.getvalue()

    def test_fresh_setup_produces_valid_config_and_existing_launcher_command(self):
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        settings = load_service_configuration(self.config / "controller.json", "controller")
        self.assertEqual(settings["service_id"], "control")
        self.assertEqual(settings["known_nodes"], ("node",))
        self.assertIn("COMPLETED: isolated package installation", output)
        self.assertIn("lab_sync_acquisition.service_launcher", output)
        self.assertIn("--deployment-config", output)
        self.assertEqual(sum("venv" in command for command in self.calls), 1)

    def test_all_local_role_selections_use_existing_schemas_and_one_storage_pair(self):
        self.answers["Local roles"] = "controller acquisition-node synchronization-manager ingestor storage-manager"
        hardware = self.hardware()
        before = hardware.read_bytes()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        for role, filename in installer.FILES.items():
            load_service_configuration(self.config / filename, role)
        self.assertEqual(output.count("LAUNCH:"), 4)
        self.assertEqual(hardware.read_bytes(), before)
        self.assertTrue((self.root / "scientific").is_dir())
        self.assertTrue((self.config / "data/journals").is_dir())
        pip = next(c for c in self.calls if "install" in c)
        self.assertEqual(pip[-1], str(self.checkout) + "[artifact-retrieval]")

    def test_each_individual_role_including_storage_alias_can_be_prepared(self):
        for role in (*installer.FILES, "storage-manager"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "config"
                self.answers["Local roles"] = role
                self.hardware()
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                self.assertEqual(output.count("LAUNCH:"), 1)

    def test_compatible_environment_and_customized_configuration_are_preserved(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "controller.json"
        data = json.loads(path.read_text())
        data["result_window_s"] = 7
        path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        before = path.read_bytes()
        evidence = self.config / "recording.h5"
        evidence.write_bytes(b"existing scientific data")
        self.calls.clear()
        code, output, errors = self.run_setup()
        self.assertEqual(code, 0, errors)
        self.assertNotIn("venv", [arg for c in self.calls for arg in c])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(evidence.read_bytes(), b"existing scientific data")
        self.assertIn("preserve 1 existing files", output)

    def test_incompatible_environment_is_not_recreated_or_installed_into(self):
        self.create_environment()
        self.version = [3, 11]
        before = self.environment_python().read_bytes()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("isolated Python 3.12", errors)
        self.assertFalse(any("pip" in c or "venv" in c for c in self.calls))
        self.assertEqual(self.environment_python().read_bytes(), before)

    def test_update_requires_explicit_confirmation_of_retirement(self):
        self.create_environment()
        self.answers["All services"] = "no"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("Resolve service retirement", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertFalse(self.config.exists())

    def test_declined_plan_makes_no_changes(self):
        self.answers["Install the displayed"] = "no"
        code, output, _ = self.run_setup()
        self.assertEqual(code, 2)
        self.assertIn("no changes made", output)
        self.assertFalse(self.environment.exists())
        self.assertFalse(self.config.exists())

    def test_missing_hardware_is_deferred_without_fabricated_node_configuration(self):
        self.answers["Local roles"] = "acquisition-node"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn("AcquisitionNode incomplete", output)
        self.assertNotIn("LAUNCH:", output)
        self.assertFalse((self.config / "acquisition-node-service.json").exists())

    def test_existing_inconsistent_peer_identity_blocks_before_install(self):
        self.assertEqual(self.run_setup()[0], 0)
        path = self.config / "synchronization-manager.json"
        controller = json.loads((self.config / "controller.json").read_text())
        path.write_text(json.dumps({k: v for k, v in controller.items()
            if k not in {"synchronization_id", "known_nodes"}} | {"service_id": "different-clock"}), encoding="utf-8")
        before = path.read_bytes()
        self.calls.clear()
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("disagree on synchronization_id", errors)
        self.assertFalse(any("pip" in c for c in self.calls))
        self.assertEqual(path.read_bytes(), before)

    def test_false_isolated_storage_declaration_cannot_omit_local_dependents(self):
        self.answers["Local roles"] = "controller ingestor"
        self.answers["Actual external dependents"] = "none"
        code, _, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("omits local owners", errors)
        self.assertFalse(self.environment.exists())

    def test_pip_failure_or_interruption_retains_existing_data_without_claiming_rollback(self):
        for failure, expected in (("pip", 1), ("interrupt", 130)):
            with self.subTest(failure=failure):
                self.failure = None
                self.assertEqual(self.run_setup()[0], 0)
                path = self.config / "controller.json"
                before = path.read_bytes()
                self.failure = failure
                code, output, errors = self.run_setup()
                self.assertEqual(code, expected)
                self.assertEqual(path.read_bytes(), before)
                self.assertIn("partially changed", errors)
                self.assertNotIn("LAUNCH:", output)

    def test_invalid_generated_config_is_never_published(self):
        self.answers["NATS URLs"] = "not-a-url"
        code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_directory_failure_blocks_without_configuration_publication(self):
        self.config.write_text("not a directory", encoding="utf-8")
        before = self.config.read_bytes()
        code, _, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(self.config.read_bytes(), before)

    def test_failed_configuration_write_removes_partial_file(self):
        with patch.object(installer.os, "fsync", side_effect=OSError("Injected publication failure")):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        self.assertIn("publication failure", errors)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_unavailable_nats_leaves_config_but_never_claims_connectivity(self):
        self.failure = "nats"
        code, output, errors = self.run_setup()
        self.assertEqual(code, 2, errors)
        self.assertIn("NATS connectivity/cleanup unconfirmed", output)
        self.assertNotIn("NATS connection and cleanup confirmed", output)
        load_service_configuration(self.config / "controller.json", "controller")

    def test_interrupted_configuration_write_leaves_no_partial_json(self):
        with patch.object(installer.os, "fsync", side_effect=KeyboardInterrupt):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 130)
        self.assertIn("KeyboardInterrupt", errors)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_configuration_created_by_another_operator_is_never_overwritten(self):
        publish = installer._publish
        contents = b'{"operator": "new configuration must not be overwritten"}'

        def appear(path, generated):
            path.write_bytes(contents)
            return publish(path, generated)

        with patch.object(installer, "_publish", side_effect=appear):
            code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual((self.config / "controller.json").read_bytes(), contents)
        self.assertEqual(len(list(self.config.glob("*.json"))), 1)

    def test_invalid_hardware_is_rejected_by_actual_loader_without_opening_camera(self):
        self.answers["Local roles"] = "acquisition-node"
        hardware = self.hardware()
        hardware.write_text('{"node_id":"node"}', encoding="utf-8")
        before = hardware.read_bytes()
        with patch("lab_sync_acquisition.service_startup.SeeedIMX219OpenCVCameraAdapter",
                   side_effect=AssertionError("Hardware must not be opened")):
            code, output, _ = self.run_setup()
        self.assertEqual(code, 1)
        self.assertEqual(hardware.read_bytes(), before)
        self.assertNotIn("LAUNCH:", output)
        self.assertEqual(list(self.config.glob("*.json")), [])

    def test_later_publication_failure_keeps_only_complete_valid_earlier_configs(self):
        self.answers["Local roles"] = "controller synchronization-manager"
        publish = installer._publish

        def fail_second(path, contents):
            if path.name == "synchronization-manager.json":
                raise OSError("Second config cannot be published")
            return publish(path, contents)

        with patch.object(installer, "_publish", side_effect=fail_second):
            code, output, errors = self.run_setup()
        self.assertEqual(code, 1)
        load_service_configuration(self.config / "controller.json", "controller")
        self.assertFalse((self.config / "synchronization-manager.json").exists())
        self.assertEqual(len(list(self.config.glob("*.json"))), 1)
        self.assertIn("complete new configs may remain", errors)
        self.assertNotIn("LAUNCH:", output)

    def test_windows_and_linux_commands_quote_paths_with_spaces_for_native_shell(self):
        for operating_system in ("win32", "linux"):
            with self.subTest(operating_system=operating_system), tempfile.TemporaryDirectory() as directory:
                self.config = Path(directory) / "private config"
                self.environment = Path(directory) / ".venv"
                # The installer environment is always relative to its chosen checkout.
                self.checkout = Path(directory) / "checkout with spaces"
                self.checkout.mkdir()
                self.environment = self.checkout / ".venv"
                (self.checkout / "pyproject.toml").write_text('[project]\nname="lab-sync-acquisition"\n', encoding="utf-8")
                self.platform = operating_system
                code, output, errors = self.run_setup()
                self.assertEqual(code, 0, errors)
                command = next(line for line in output.splitlines() if line.startswith("LAUNCH:"))
                self.assertIn("--deployment-config", command)
                self.assertIn("'", command)
                self.assertEqual(command.startswith("LAUNCH: & "), operating_system == "win32")


if __name__ == "__main__":
    unittest.main()
