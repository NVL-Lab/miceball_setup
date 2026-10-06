import json
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    ActiveExperimentRuntimeContext, ControllerActionDecision, ScientificOutputSelection,
    ScientificProductDeclaration, Session, SessionConfig, SessionLifecycleError,
    DeviceAdapterState,
)
from tests import test_scientific_acquisition_persistence as persistence_tests
from tests.test_scientific_acquisition_persistence import ScientificEventAdapter


class RestartableEventAdapter(ScientificEventAdapter):
    """Concrete test adapter supporting restart without changing the base contract."""
    def start(self):
        if self.state == DeviceAdapterState.STOPPED:
            self._set_state(DeviceAdapterState.RUNNING)
        else:
            super().start()


class ExperimentScientificFinalizationTests(unittest.TestCase):
    workflow = persistence_tests.ScientificAcquisitionPersistenceTests.workflow

    def failure_decision(self, kind="experiment_fail"):
        return ControllerActionDecision(
            "observation", "session", "experiment", "camera", "camera-policy",
            "experiment_failure" if kind == "experiment_fail" else "session_failure",
            kind, 0.0,
        )

    def test_normal_stop_flushes_buffered_frames_and_finalizes_manifest(self):
        with self.workflow(max_buffered_rows=20) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            manifest, = node.local_storage_manager.manifests
            with h5py.File(manifest.local_storage_path, "r") as artifact:
                self.assertEqual(len(artifact["frames"]), 0)
            result = controller.stop_experiment("experiment")
            self.assertTrue(result.succeeded, result.error)
            finalized, = node.local_storage_manager.manifests
            self.assertEqual(finalized.lifecycle_state, "finalized")
            self.assertEqual(finalized.details["row_count"], 1)
            with h5py.File(finalized.local_storage_path, "r") as artifact:
                np.testing.assert_array_equal(artifact["frames"][0], np.arange(24, dtype=np.uint16).reshape(2, 4, 3))
            saved = json.loads(Path(finalized.local_managed_paths[2]).read_text())
            self.assertEqual(saved["lifecycle_state"], "finalized")
            self.assertEqual(controller.get_status()["session_state"], "running")
            self.assertTrue(node.status()["is_running"])
            self.assertIsNone(node.status()["active_experiment_runtime_context"])
            with self.assertRaisesRegex(RuntimeError, "finalized"):
                node.local_storage_manager.append_rows(finalized.storage_id, ({},))

    def test_zero_frame_stream_finalizes_and_repeated_finalization_is_idempotent(self):
        with self.workflow() as (controller, node, _, _):
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.details["row_count"], 0)
            self.assertEqual(node.finalize_experiment_scientific_outputs("experiment"), (manifest,))
            self.assertFalse(controller.stop_experiment("experiment").succeeded)

    def test_experiment_failure_preserves_buffered_artifact_and_leaves_session_running(self):
        with self.workflow(max_buffered_rows=20) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            result = controller.execute_controller_action_decision(self.failure_decision())
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(result.details["event_type"], "experiment_fail")
            manifest, = node.local_storage_manager.manifests
            self.assertEqual(manifest.lifecycle_state, "finalized")
            self.assertEqual(manifest.details["row_count"], 1)
            self.assertEqual(controller.get_status()["session_state"], "running")
            self.assertTrue(node.status()["is_running"])
            self.assertFalse(controller.start_experiment("experiment").succeeded)

    def test_session_failure_finalizes_active_experiment_artifact(self):
        with self.workflow(max_buffered_rows=20) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            result = controller.execute_controller_action_decision(self.failure_decision("session_fail"))
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
            self.assertIsNone(node.status()["active_experiment_runtime_context"])

    def test_session_stop_finalizes_and_records_active_experiment_normal_stop(self):
        with self.workflow() as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertTrue(controller.stop_session().succeeded)
            self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
            final = controller.finalize_session()
            self.assertTrue(final.succeeded, final.error)
            record = json.loads(Path(final.details["session_record_path"]).read_text())
            self.assertEqual([e["event_type"] for e in record["experiment_lifecycle_evidence"]],
                             ["experiment_start", "experiment_stop"])

    def test_finalization_failure_reports_failure_and_still_attempts_other_streams(self):
        products = (
            ScientificProductDeclaration("frames", "camera_frames", {"frame_shape": [2, 4, 3], "frame_dtype": "uint16"}, "hdf5"),
            ScientificProductDeclaration("events", "events", {}, "jsonl"),
        )
        with self.workflow(products=products, select_all=True) as (controller, node, _, _):
            local = node.local_storage_manager
            first, second = local.manifests
            flush = local.flush
            def fail_first(storage_id):
                if storage_id == first.storage_id:
                    raise OSError("flush unavailable")
                return flush(storage_id)
            with patch.object(local, "flush", side_effect=fail_first):
                result = controller.stop_experiment("experiment")
            self.assertFalse(result.succeeded)
            self.assertIn("flush unavailable", result.error)
            manifests = local.manifests
            self.assertNotEqual(manifests[0].lifecycle_state, "finalized")
            self.assertEqual(manifests[1].lifecycle_state, "finalized")
            self.assertTrue(any(e.evidence_type == "finalization_failure" for e in local.evidence))
            self.assertTrue(Path(first.local_storage_path).exists())
            self.assertFalse(controller.start_experiment("experiment").succeeded)
            self.assertEqual(controller.get_status()["session_state"], "running")
            with self.assertRaisesRegex(RuntimeError, "finalization failed"):
                node.stop_runtime()

    def test_new_execution_uses_independent_artifact_and_preserves_previous_pixels(self):
        frames = [np.full((2, 4, 3), value, dtype=np.uint16) for value in (10, 20)]
        with self.workflow(frames=frames) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            first, = node.local_storage_manager.manifests
            self.assertFalse(controller.start_experiment("experiment").succeeded)
            self.assertTrue(controller.start_experiment("repeat", scientific_outputs=(
                ScientificOutputSelection("camera", "node", "frames"),)).succeeded)
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertEqual(node.local_storage_manager.manifests[0], first)
            self.assertEqual(node.local_storage_manager.manifests[1].lifecycle_state, "open")
            self.assertTrue(controller.stop_experiment("repeat").succeeded)
            second = node.local_storage_manager.manifests[1]
            self.assertNotEqual(first.storage_id, second.storage_id)
            self.assertNotEqual(first.artifact_manifest_id, second.artifact_manifest_id)
            for manifest, frame in zip((first, second), frames):
                with h5py.File(manifest.local_storage_path, "r") as artifact:
                    np.testing.assert_array_equal(artifact["frames"][:], frame[None, ...])

    def test_terminal_metadata_only_identity_is_not_reusable(self):
        with self.workflow(selected=False) as (controller, node, _, _):
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            self.assertFalse(controller.start_experiment("experiment").succeeded)
            self.assertTrue(controller.start_experiment("new-metadata").succeeded)
            self.assertEqual(node.local_storage_manager.manifests, ())
            self.assertTrue(controller.stop_experiment("new-metadata").succeeded)

    def test_session_timeline_cannot_bypass_terminal_identity_check(self):
        for terminal in ("experiment_stop", "experiment_fail"):
            with self.subTest(terminal=terminal):
                session = Session("session", SessionConfig([], "placeholder", {}, "placeholder"))
                session.initialize()
                session.start()
                session.record_experiment_lifecycle("experiment", "experiment_start", 0.0)
                session.record_experiment_lifecycle("experiment", terminal, 1.0)
                with self.assertRaisesRegex(SessionLifecycleError, "terminal"):
                    session.record_experiment_lifecycle("experiment", "experiment_start", 2.0)
                self.assertEqual(len(session.experiment_lifecycle_evidence), 2)

    def test_node_cannot_reactivate_ended_runtime_identity(self):
        with self.workflow(selected=False) as (controller, node, _, _):
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            with self.assertRaisesRegex(ValueError, "ended"):
                node.activate_experiment_runtime_context(ActiveExperimentRuntimeContext("experiment", 0.0))
            self.assertFalse(node.prepare_experiment_scientific_outputs("experiment", ()).ready)

    def test_device_restart_within_active_experiment_remains_allowed(self):
        adapter = RestartableEventAdapter()
        product = ScientificProductDeclaration("events", "events", {}, "jsonl")
        with self.workflow(adapter=adapter, products=(product,)) as (controller, node, _, _):
            self.assertTrue(controller.run_one_iteration().succeeded)
            adapter.stop()
            adapter.start()
            self.assertTrue(controller.run_one_iteration().succeeded)
            self.assertEqual(node.status()["active_experiment_runtime_context"].experiment_id, "experiment")
            self.assertTrue(controller.stop_experiment("experiment").succeeded)
            self.assertEqual(node.local_storage_manager.manifests[0].details["row_count"], 2)

    def test_handled_collection_failure_preserves_prepared_artifact(self):
        with self.workflow() as (controller, node, _, _):
            with patch("lab_sync_acquisition.device_manager.DeviceManager.collect_scientific_records",
                       side_effect=OSError("camera unavailable")):
                result = controller.run_one_iteration()
            self.assertFalse(result.succeeded)
            self.assertIn("camera unavailable", result.error)
            self.assertEqual(controller.get_status()["session_state"], "failed")
            self.assertFalse(node.status()["is_running"])
            self.assertEqual(node.local_storage_manager.manifests[0].lifecycle_state, "finalized")
            self.assertEqual(node.local_storage_manager.manifests[0].details["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
