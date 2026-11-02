"""Offline timing workflows using disk-backed scientific and preservation owners."""

from copy import deepcopy
from dataclasses import replace
import asyncio
import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import h5py
import numpy as np

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, InMemoryIngestor, PersistentStorageManager,
    ReconstructionManager, RuntimeEvidenceMessage, SynchronizationManager, SshRetrievalEndpoint,
)
from tests.fakes import ReadyFakeAdapter
from tests.test_distributed_synchronization import configuration
from tests import test_artifact_retrieval as retrieval


class TimingReconstructionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root / "archive")
        self.time = 0.
        self.local = 100.
        for target, clock in (("lab_sync_acquisition.synchronization.monotonic", lambda: self.time),
                              ("lab_sync_acquisition.acquisition_node.monotonic", lambda: self.local)):
            context = patch(target, side_effect=clock)
            context.start()
            self.addCleanup(context.stop)
        self.sync = SynchronizationManager()
        self.sync.prepare_session("session")
        self.sync.configure_distributed_session("session", configuration(
            clock_rate_error_bound=.02, max_mapping_age_s=100000, max_uncertainty_s=1.))
        self.sync.start_distributed_session("session")
        self.node = AcquisitionNode(device_manager=DeviceManager([
            ReadyFakeAdapter("camera", "camera", ("frames",), True)]), node_id="node",
            synchronization_source_id="sync", default_local_storage_root=self.root / "originals")
        self.node.reserve("session")
        self.node.initialize_session("session", self.node.declared_devices)
        self.manager = self.node.local_storage_manager
        self.addCleanup(self.manager.finalize_all)
        self.messages = []
        self.manifests = []
        self.rows = []
        self.quality(100, 0)
        self.first = self.sync.get_active_mapping("session", "node").to_dict()
        self.quality(110, 10.02)
        self.second = self.sync.get_active_mapping("session", "node").to_dict()
        self.quality(120, 20.04)
        self.stream("jsonl")
        self.stream("hdf5")

    def quality(self, local, session, *, rate=1.002, apply=True):
        samples = [dict(sent_session_time_s=session + rate * i * .1 - .002,
                        received_local_time_s=local + i * .1, sent_local_time_s=local + i * .1,
                        received_session_time_s=session + rate * i * .1 + .002,
                        local_clock_resolution_s=0.) for i in range(3)]
        self.time = session + 1
        quality = self.sync.assess_cross_clock_exchanges("session", "node", samples,
            replace_mapping=True, source_id="sync")
        self.local = local + .21
        if apply:
            self.node.accept_synchronization_quality("session", "sync", quality)
        return quality

    def test_quantized_exchange_bounds_remain_usable_offline(self):
        exact = [dict(sent_session_time_s=i * .1, received_local_time_s=100 + i * .1,
            sent_local_time_s=100 + i * .1 + .010, received_session_time_s=i * .1 + .009,
            local_clock_resolution_s=.001) for i in range(3)]
        accepted = self.sync.assess_cross_clock_exchanges("session", "quantized", exact,
            replace_mapping=True, source_id="sync")
        self.assertTrue(accepted["measurement_valid"])
        self.assertTrue(accepted["acceptable"])
        for resolution in (.001, .002, .01):
            samples = [dict(sent_session_time_s=30.06 + i * .1,
                received_local_time_s=130 + i * .1, sent_local_time_s=130 + i * .1 + .010,
                received_session_time_s=30.06 + i * .1 + .009,
                local_clock_resolution_s=resolution) for i in range(3)]
            # Distinct chronological batches, with the exact audited duration mismatch.
            shift = resolution * 10000
            for sample in samples:
                for key in ("sent_session_time_s", "received_session_time_s"):
                    sample[key] += shift * 1.002
                for key in ("received_local_time_s", "sent_local_time_s"):
                    sample[key] += shift
            q = self.sync.assess_cross_clock_exchanges("session", "node", samples,
                replace_mapping=True, source_id="sync")
            self.assertTrue(q["measurement_valid"])
            self.assertTrue(q["acceptable"])
        self.archive()
        result = self.reconstruct()
        self.assertEqual(result["quality"]["reconstructed_count"], 4, result["issues"])
        self.assertEqual(result["issues"], [])

    def stream(self, storage_format):
        manifest = self.manager.create_stream(session_id="session", experiment_id="experiment",
            acquisition_node_id="node", source_component_id="camera", data_product_id=storage_format,
            artifact_type="frames" if storage_format == "hdf5" else "events",
            storage_format=storage_format,
            schema={"frame_shape": [2, 3], "frame_dtype": "uint8"} if storage_format == "hdf5" else {})
        rows = []
        for i, (local, mapping) in enumerate(((105., self.first), (115., self.second))):
            session = mapping["session_time_anchor_s"] + mapping["scale"] * (local - mapping["local_time_anchor_s"])
            row = dict(experiment_id="experiment", session_time_s=session, experiment_time_s=session,
                acquisition_node_local_time_s=local, timestamp_status="runtime_timestamped", frame_index=i,
                device_local_time=local - 2)
            if storage_format == "hdf5":
                row["frame"] = np.full((2, 3), i, dtype="uint8")
            rows.append(row)
        self.manager.append_rows(manifest.storage_id, rows)
        self.manifests.append(self.manager.finalize_stream(manifest.storage_id))
        self.rows.append(rows)

    def archive(self, mutate=None, *, release=True, partial=False):
        evidence = list(self.sync.session_timing_evidence("session", "sync")) + list(self.node.runtime_evidence)
        evidence += [RuntimeEvidenceMessage("manifest-" + m.artifact_manifest_id, "session",
                        "artifact_manifest", "node", m.to_dict(), True) for m in self.manifests]
        marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        evidence.append(marker)
        if mutate:
            evidence = mutate(deepcopy(evidence))
        self.intake = InMemoryIngestor(session_id="session",
            recovery_journal_path=self.root / (self.storage.storage_root.name + "-intake.jsonl"))
        for message in evidence:
            self.intake.receive_runtime_evidence(message)
        record = dict(accepted_session_config={"session_id": "session"},
            lifecycle_evidence=[{"to_state": "completed"}], readiness_evidence=[],
            device_readiness_evidence=[], service_readiness_evidence=[],
            final_session_status={"state": "completed"}, cleanup_evidence={})
        if partial:
            self.storage.write_kill_acquisition_stage("session", self.intake.compile_persistent_runtime_evidence(),
                uncertainties=[{"reason": "participant evidence unavailable"}], **record)
        else:
            self.storage.write_acquisition_stage("session", self.intake.compile_persistent_runtime_evidence(),
                receipt={"session_id": "session", "durable_receipt_confirmed": True,
                         "evidence_id": "marker", "marker_stream_sequence": len(evidence)}, **record)
        self.storage.write_artifact_collection_handoff("session", self.intake.compile_artifact_collection_handoff("session"))
        if release:
            self.assertTrue(self.node.abort_session_initialization("session"))
            self.assertTrue(self.node.release_reservation("session"))
            self.assertTrue(self.intake.release_session("session", storage_manager=self.storage))

    def reconstruct(self, version="v1", storage=None):
        return ReconstructionManager(storage or self.storage,
            local_storage_roots={"node": self.root / "originals"}).reconstruct_session("session", version=version)

    def snapshot(self):
        return {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()
                and "reconstructed_timing" not in p.parts}

    def observations(self, result):
        return [r for a in result["artifacts"] for r in a["observations"]]

    def test_jsonl_hdf5_after_release_exact_provenance_and_unchanged_inputs(self):
        self.archive()
        before = self.snapshot()
        restored = PersistentStorageManager(self.root / "archive")
        result = self.reconstruct(storage=restored)
        self.assertTrue(result["quality"]["complete"], result)
        self.assertEqual(result["quality"]["observation_count"], 4)
        self.assertEqual(result, restored.read_timing_reconstruction("session", "v1"))
        self.assertIsNone(self.node.reserved_for_session_id)
        self.assertIsNone(self.node.local_storage_manager)
        self.assertIsNone(self.intake.session_id)
        ids = set(result["input_evidence_ids"])
        for artifact in result["artifacts"]:
            for index, row in enumerate(artifact["observations"]):
                true_time = (row["original_timing"]["acquisition_node_local_time_s"] - 100) * 1.002
                refined = row["reconstructed"]
                self.assertLessEqual(abs(refined["session_time_s"] - true_time), refined["uncertainty_s"])
                self.assertGreater(row["runtime"]["uncertainty_s"], 0)
                self.assertIn(row["provenance"]["mapping_update_evidence_id"], ids)
                self.assertIn(row["provenance"]["mapping_activation_evidence_id"], ids)
                self.assertTrue(set(row["provenance"]["refinement_evidence_ids"]).issubset(ids))
                self.assertEqual(row["provenance"]["runtime_mapping"], self.first if index == 0 else self.second)
                self.assertEqual(row["original_timing"]["device_local_time"], 103 if index == 0 else 113)
        self.assertEqual(before, self.snapshot())

    def test_versions_identical_retry_conflict_and_reconstructed_readback(self):
        self.archive()
        first = self.reconstruct()
        self.assertEqual(first, self.reconstruct())
        second = self.reconstruct("v2")
        self.assertEqual(first["artifacts"], second["artifacts"])
        changed = deepcopy(first)
        changed["issues"].append("different result")
        with self.assertRaises(ValueError):
            self.storage.write_timing_reconstruction(changed)
        self.assertEqual(first, self.storage.read_timing_reconstruction("session", "v1"))
        path = self.root / "archive/session_session/reconstructed_timing/v2.json"
        path.write_text(path.read_text().replace('"complete": true', '"complete": false'))
        with self.assertRaises(ValueError):
            PersistentStorageManager(self.root / "archive").read_timing_reconstruction("session", "v2")

    def test_pending_write_failure_and_retry_without_original_mutation(self):
        self.archive()
        before = self.snapshot()
        original = PersistentStorageManager._write_record_contents
        def partial(path, text, **kwargs):
            path.write_text(text[:30])
            raise OSError("interrupted derived write")
        with patch.object(PersistentStorageManager, "_write_record_contents", side_effect=partial):
            with self.assertRaises(OSError):
                self.reconstruct()
        with self.assertRaises(FileNotFoundError):
            self.storage.read_timing_reconstruction("session", "v1")
        with patch.object(PersistentStorageManager, "_write_record_contents", side_effect=original):
            result = self.reconstruct()
        self.assertTrue(result["quality"]["complete"])
        self.assertEqual(before, self.snapshot())

    def test_failed_confirmation_after_publication_can_retry_after_owner_reconstruction(self):
        self.archive()
        original = self.storage._sync_artifact_handoff_directory
        def fail_derived(path):
            if path.parent.name == "reconstructed_timing":
                raise OSError("fsync")
            return original(path)
        with patch.object(self.storage, "_sync_artifact_handoff_directory", side_effect=fail_derived):
            with self.assertRaises(OSError):
                self.reconstruct()
        restored = PersistentStorageManager(self.root / "archive")
        first = restored.read_timing_reconstruction("session", "v1")
        self.assertEqual(first, self.reconstruct(storage=restored))

    def test_missing_or_corrupt_preservation_never_reports_success(self):
        self.archive()
        path = self.root / "archive/session_session/evidence/runtime_evidence.jsonl"
        path.write_bytes(path.read_bytes()[:-3])
        before = self.snapshot()
        result = self.reconstruct()
        self.assertFalse(result["quality"]["complete"])
        self.assertEqual(result["artifacts"], [])
        self.assertTrue(result["issues"])
        self.assertEqual(before, self.snapshot())

    def test_missing_activation_owner_and_conflicting_quality_are_explicit(self):
        for damage in ("activation", "owner", "conflict", "wrong_session"):
            with self.subTest(damage=damage):
                def mutate(messages):
                    if damage == "activation":
                        return [m for m in messages if m.evidence_type != "mapping_activation"]
                    if damage == "owner":
                        return [m for m in messages if not (m.evidence_type == "timing_quality_observation" and m.source_id == "sync")]
                    item = next(m for m in messages if m.evidence_type == "timing_quality_observation" and m.source_id == "node")
                    item.payload["quality"]["uncertainty_s"] += 1
                    if damage == "wrong_session":
                        item.payload["session_id"] = "other"
                    return messages
                # Separate owners prevent test setup from rewriting a released archive.
                self.storage = PersistentStorageManager(self.root / damage)
                self.archive(mutate, release=False)
                result = self.reconstruct(damage)
                self.assertFalse(result["quality"]["complete"])
                self.assertTrue(all(r["reconstructed"] is None for r in self.observations(result)))

    def test_missing_original_and_malformed_jsonl_are_explicit(self):
        self.archive()
        data = Path(self.manifests[0].local_storage_path)
        original = data.read_bytes()
        data.unlink()
        result = self.reconstruct("missing")
        self.assertTrue(result["artifacts"][0]["issues"])
        data.write_bytes(original[:-2])
        result = self.reconstruct("partial")
        self.assertFalse(result["quality"]["complete"])
        self.assertTrue(result["artifacts"][0]["issues"])
        self.assertTrue(all(r["reconstructed"] is None for r in result["artifacts"][0]["observations"]))

    def test_hdf5_misaligned_or_conflicting_timing_is_not_confirmed(self):
        self.archive()
        path = Path(self.manifests[1].local_storage_path)
        with h5py.File(path, "r+") as source:
            source["session_time_s"][0] += 1
        result = self.reconstruct()
        self.assertFalse(result["quality"]["complete"])
        self.assertTrue(result["artifacts"][1]["issues"])

    def test_degraded_runtime_can_be_refined_without_relabeling_original(self):
        path = Path(self.manifests[0].local_storage_path)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["timestamp_status"] = "synchronization_degraded"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.archive()
        before = path.read_bytes()
        result = self.reconstruct()
        first = result["artifacts"][0]["observations"][0]
        self.assertEqual(first["quality"], "refined_runtime_degraded")
        self.assertIsNotNone(first["reconstructed"])
        self.assertEqual(path.read_bytes(), before)

    def test_source_and_output_aliases_are_refused_without_changing_other_files(self):
        self.archive()
        source = Path(self.manifests[0].local_storage_path)
        other = self.root / "other"
        os.link(source, other)
        result = self.reconstruct("alias")
        self.assertFalse(result["quality"]["complete"])
        output = self.root / "archive/session_session/reconstructed_timing/aliased.json"
        os.link(other, output)
        before = other.read_bytes()
        with self.assertRaises(ValueError):
            self.reconstruct("aliased")
        self.assertEqual(before, other.read_bytes())

    def test_active_replacement_session_and_closed_archive_are_untouched(self):
        self.archive()
        self.storage.close_session_evidence_archive("session")
        self.node.reserve("replacement")
        self.node.initialize_session("replacement", self.node.declared_devices)
        current = self.node.local_storage_manager
        self.addCleanup(current.finalize_all)
        before = self.snapshot()
        self.assertTrue(self.reconstruct()["quality"]["complete"])
        self.assertEqual(self.node.reserved_for_session_id, "replacement")
        self.assertIs(self.node.local_storage_manager, current)
        self.assertEqual(self.snapshot(), before)

    def test_collected_jsonl_and_hdf5_reconstruct_without_access_to_original_nodes(self):
        self.archive()
        storage = PersistentStorageManager(self.root / "archive", global_artifact_root=self.root / "collected",
            retrieval_endpoints={"node": SshRetrievalEndpoint("test", "reader")})
        files = {m.local_storage_path: Path(m.local_storage_path).read_bytes() for m in self.manifests}
        transport, _ = retrieval.ArtifactRetrievalTests().ssh(retrieval.SftpDouble(files))
        with transport:
            collected = storage.collect_saved_artifacts("session", evidence_id="collection", require_eligible=False)
        self.assertTrue(collected["archival_confirmed"], collected)
        before = self.snapshot()
        result = ReconstructionManager(storage).reconstruct_session("session", version="collected")
        self.assertTrue(result["quality"]["complete"], result)
        self.assertTrue(all(Path(a["read_path"]).is_relative_to(self.root / "collected") for a in result["artifacts"]))
        self.assertEqual(before, self.snapshot())

    def test_rejected_future_and_partial_measurements_remain_visible_without_poisoning_offline_fit(self):
        rejected = self.quality(1000, 30, apply=False)
        self.assertFalse(rejected["estimator"]["refinement_accepted"])
        self.sync.mark_synchronization_unavailable("session", "node", "sync", "interrupted measurement",
            exchanges=[rejected["exchanges"][0]])
        self.quality(130, 30.06)
        self.quality(140, 40.08)
        self.archive()
        before = self.snapshot()
        result = self.reconstruct()
        self.assertTrue(any("rejected refinement" in i for i in result["issues"]))
        self.assertTrue(any("unavailable measurement" in i for i in result["issues"]))
        self.assertEqual(result["quality"]["reconstructed_count"], 4)
        self.assertEqual(before, self.snapshot())

    def test_sustained_change_is_separate_and_does_not_bridge_an_unconfirmed_gap(self):
        rejected = self.quality(130, 31.06)
        self.assertFalse(rejected["estimator"]["refinement_accepted"])
        changed = self.quality(140, 41.08)
        self.assertEqual(changed["estimator"]["disposition"], "sustained_change")
        new_mapping = changed["mapping"]
        self.quality(150, 51.10)
        manifest = self.manager.create_stream(session_id="session", experiment_id="experiment",
            acquisition_node_id="node", source_component_id="camera", data_product_id="drift",
            artifact_type="events", schema={})
        for local, mapping in ((135., self.sync.mapping_update_evidence[2].new_mapping.to_dict()), (145., new_mapping)):
            session = mapping["session_time_anchor_s"] + mapping["scale"] * (local - mapping["local_time_anchor_s"])
            self.manager.append_rows(manifest.storage_id, [dict(experiment_id="experiment", session_time_s=session,
                experiment_time_s=session, acquisition_node_local_time_s=local, timestamp_status="runtime_timestamped")])
        self.manifests.append(self.manager.finalize_stream(manifest.storage_id))
        self.archive()
        result = self.reconstruct()
        rows = result["artifacts"][-1]["observations"]
        self.assertIsNone(rows[0]["reconstructed"])
        self.assertIn("No bracketed offline", str(rows[0]["issues"]))
        self.assertIsNotNone(rows[1]["reconstructed"])
        refined = rows[1]["reconstructed"]
        self.assertLessEqual(abs(refined["session_time_s"] - 46.09), refined["uncertainty_s"])
        self.assertEqual(rows[1]["provenance"]["runtime_mapping"], new_mapping)

    def test_duplicate_delivery_does_not_create_duplicate_refinement_support(self):
        def duplicate(messages):
            return messages[:-1] + [messages[0]] + messages[-1:]
        self.archive(duplicate)
        result = self.reconstruct()
        self.assertTrue(result["quality"]["complete"])
        self.assertEqual(len(result["input_evidence_ids"]), len(set(result["input_evidence_ids"])))
        for row in self.observations(result):
            ids = row["provenance"]["refinement_evidence_ids"]
            self.assertEqual(len(ids), len(set(ids)))

    def test_conflicting_duplicate_and_cross_session_deliveries_cannot_enter_preservation(self):
        intake = InMemoryIngestor(session_id="session", recovery_journal_path=self.root / "conflicts.jsonl")
        message = self.sync.session_timing_evidence("session", "sync")[0]
        intake.receive_runtime_evidence(message)
        conflict = replace(message, payload={**message.payload, "reason": "conflict"})
        with self.assertRaises(ValueError):
            intake.receive_runtime_evidence(conflict)
        with self.assertRaises(ValueError):
            intake.receive_runtime_evidence(replace(message, evidence_id="other", session_id="other"))

    def test_cancelled_derived_write_is_not_a_completed_version(self):
        self.archive()
        before = self.snapshot()
        with patch.object(PersistentStorageManager, "_write_record_contents", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                self.reconstruct()
        with self.assertRaises(FileNotFoundError):
            self.storage.read_timing_reconstruction("session", "v1")
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.reconstruct()["quality"]["complete"])

    def test_nonfinite_timing_and_hdf5_misalignment_are_reported_without_invented_results(self):
        self.archive()
        jsonl = Path(self.manifests[0].local_storage_path)
        original = jsonl.read_bytes()
        jsonl.write_bytes(original.replace(b'"acquisition_node_local_time_s": 105.0',
                                           b'"acquisition_node_local_time_s": 1e400'))
        hdf = Path(self.manifests[1].local_storage_path)
        with h5py.File(hdf, "r+") as source:
            source["timestamp_status"].resize(1, axis=0)
        result = self.reconstruct()
        self.assertFalse(result["quality"]["complete"])
        self.assertEqual(result["quality"]["reconstructed_count"], 0)
        self.assertTrue(all(a["issues"] for a in result["artifacts"]))

    def test_external_artifacts_are_reported_without_guessing_observation_index_associations(self):
        manifest = self.manifests[0]
        external = replace(manifest, external_artifact_path=manifest.local_storage_path)
        self.manifests[0] = external
        self.archive()
        result = self.reconstruct()
        artifact = result["artifacts"][0]
        self.assertEqual(artifact["observations"], [])
        self.assertIn("unresolved observation/index", str(artifact["issues"]))

    def test_overlapping_or_contradictory_accepted_measurements_cannot_confirm_refinement(self):
        for case in ("overlap", "uncertainty", "sequence", "applied_sequence"):
            with self.subTest(case=case):
                self.storage = PersistentStorageManager(self.root / case)
                def mutate(messages):
                    owners = [m for m in messages if m.evidence_type == "timing_quality_observation" and m.source_id == "sync"]
                    changed = owners[1].payload
                    sequence = changed["assessment_sequence"]
                    if case == "overlap":
                        for sample in changed["exchanges"]:
                            for key in ("received_local_time_s", "sent_local_time_s"):
                                sample[key] -= 10
                            for key in ("sent_session_time_s", "received_session_time_s"):
                                sample[key] -= 10.02
                        changed["measured_local_time_s"] -= 10
                        # Keep the interval conservative so chronology, not shrinkage,
                        # is what prevents this accepted-batch claim from being used.
                        changed["uncertainty_s"] = 1
                    elif case == "uncertainty":
                        changed["uncertainty_s"] = 0
                    elif case == "sequence":
                        changed["assessment_sequence"] = owners[0].payload["assessment_sequence"]
                    for message in messages:
                        if message.source_id != "node":
                            continue
                        for key in ("measurement", "quality"):
                            value = message.payload.get(key)
                            if value and value["assessment_sequence"] == sequence:
                                message.payload[key] = deepcopy(changed)
                    if case == "applied_sequence":
                        applications = [m for m in messages if m.evidence_type == "timing_quality_observation" and m.source_id == "node"]
                        applications[1].payload["quality"] = deepcopy(owners[0].payload)
                    return messages
                self.archive(mutate, release=False)
                result = self.reconstruct(case)
                self.assertFalse(result["quality"]["complete"])
                self.assertTrue(result["issues"])
                self.assertTrue(all(r["reconstructed"] is None for r in self.observations(result)))

    def test_concurrent_identical_version_publication_and_conflicting_retry(self):
        self.archive()
        result = self.reconstruct()
        result["version"] = "parallel"
        def publish(_):
            owner = PersistentStorageManager(self.root / "archive")
            try:
                return owner.write_timing_reconstruction(result)
            except ValueError as error:
                # Independent owners can observe the atomic promotion's temporary
                # second link. That must remain uncertain, not bypass alias safety.
                self.assertIn("unavailable or aliased", str(error))
                return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            paths = list(workers.map(publish, range(2)))
        self.assertTrue(any(path is not None for path in paths))
        confirmed = self.storage.write_timing_reconstruction(result)
        self.assertTrue(all(path is None or path == confirmed for path in paths))
        self.assertEqual(self.storage.read_timing_reconstruction("session", "parallel"), result)

    def test_incomplete_existing_version_is_not_repaired_or_overwritten(self):
        self.archive()
        directory = self.root / "archive/session_session/reconstructed_timing"
        directory.mkdir()
        target = directory / "v1.json"
        target.write_text('{"result":')
        (directory / "input-check.json").write_text('{"damaged":')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.reconstruct()
        self.assertEqual(target.read_text(), '{"result":')
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.reconstruct("new-version")["quality"]["complete"])

    def test_partial_preservation_does_not_claim_complete_session_reconstruction(self):
        self.archive(partial=True, release=False)
        result = self.reconstruct()
        self.assertFalse(result["quality"]["complete"])
        self.assertTrue(any("preservation is partial" in issue for issue in result["issues"]))
        self.assertEqual(result["quality"]["reconstructed_count"], 4)


if __name__ == "__main__":
    unittest.main()
