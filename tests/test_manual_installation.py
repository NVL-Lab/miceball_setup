"""Operator-edited example files consumed by existing startup interfaces."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition.deployment_configuration import (
    load_retrieval_configuration, load_service_configuration,
)
from lab_sync_acquisition.service_launcher import main
from lab_sync_acquisition.service_startup import load_acquisition_node


class ManualInstallationTests(unittest.TestCase):
    """Validate installation examples without network connections or hardware."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        examples = Path(__file__).resolve().parents[1] / "config_templates" / "manual_installation"
        for path in examples.glob("*.json"):
            shutil.copyfile(path, self.root / path.name)
        # Only local references are required by validation, not credential bytes.
        for name in ("SSH_PRIVATE_KEY_PATH", "SSH_KNOWN_HOSTS_PATH"):
            (self.root / name).write_text("test reference, not a credential", encoding="utf-8")
        self.files = {
            "controller": "controller.json", "synchronization-manager": "synchronization-manager.json",
            "acquisition-node": "acquisition-node-service.json", "ingestor": "storage-services.json",
            "storage-manager": "storage-services.json",
        }

    def test_example_files_load_for_all_roles_without_opening_hardware(self):
        with patch("lab_sync_acquisition.service_startup.SeeedIMX219OpenCVCameraAdapter") as adapter:
            settings = {role: load_service_configuration(self.root / name, role)
                        for role, name in self.files.items()}
            adapter.assert_not_called()
        node = load_acquisition_node(settings["acquisition-node"]["node_config"], "SYNCHRONIZATION_ID")
        self.assertFalse(node.status()["is_running"])
        self.assertEqual(settings["controller"]["known_nodes"], (node.node_id,))
        self.assertIn(node.node_id, settings["ingestor"]["retrieval_endpoints"])
        self.assertEqual(settings["ingestor"]["storage_id"], settings["storage-manager"]["storage_id"])
        self.assertEqual(settings["acquisition-node"]["service_id"], node.node_id)

    def test_documented_file_launch_commands_use_existing_role_composition(self):
        def finish_without_starting(operation):
            operation.close()
            return 0

        with patch("lab_sync_acquisition.service_launcher.asyncio.run", side_effect=finish_without_starting), patch(
                "lab_sync_acquisition.service_launcher.launch_storage_services", new_callable=AsyncMock) as pair, patch(
                "lab_sync_acquisition.service_startup.launch_independent_service", new_callable=AsyncMock) as independent:
            for role, name in self.files.items():
                with self.subTest(role=role):
                    self.assertEqual(main([role, "--deployment-config", str(self.root / name)]), 0)
            self.assertEqual(pair.call_count, 2)
            self.assertEqual([call.kwargs["role"] for call in independent.call_args_list],
                             ["controller", "synchronization-manager", "acquisition-node"])

    def test_retrieval_check_does_not_require_a_false_no_dependents_declaration(self):
        path = self.root / "storage-services.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["no_operational_dependents"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        settings = load_retrieval_configuration(path)
        self.assertIn("ACQUISITION_NODE_ID", settings["retrieval_endpoints"])
        with self.assertRaisesRegex(ValueError, "no_operational_dependents"):
            load_service_configuration(path, "ingestor")

    def test_installation_commands_expose_the_documented_flags(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit:
            main(["--help"])
        self.assertEqual(exit.exception.code, 0)
        for flag in ("verify-node", "verify-retrieval", "--deployment-config", "--node-id",
                     "--source-path", "--expected-file", "--max-bytes"):
            self.assertIn(flag, output.getvalue())
