"""Confirmed Session release and conservative evidence-bearing closeout gates."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import (
    Controller, HealthInterpretationEvidence, InMemoryIngestor, PersistentStorageManager,
    AcquisitionRecordEnvelope, RuntimeEvidenceMessage, RuntimeParticipant, Session, SessionConfig,
    SynchronizationManager,
)
from tests import test_session_launch as launch_fixtures


class SessionBindingReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.launch = launch_fixtures.SessionLaunchTests()
        self.launch.setUp()
        self.addCleanup(self.launch.temporary.cleanup)
        self.storage = PersistentStorageManager(self.launch.root / "records.jsonl")
        self.launch.controller = Controller(
            ingestor=self.launch.ingestor, storage_manager=self.storage,
            synchronization_manager=self.launch.sync)
        await self.launch.services()
        self.node, self.declaration, self.adapter = await self.launch.node()

    async def start_session(self):
        result = await self.launch.launch({"node-a": [self.declaration]})
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue((await self.launch.controller.start_launched_session()).succeeded)
        return result.details["session_id"]

    async def stop_session(self):
        result = await self.launch.controller.stop_launched_session()
        self.assertTrue(result.succeeded, result.error)

    def record_decision(self, index=1):
        return self.launch.controller.process_health_interpretation(HealthInterpretationEvidence(
            originating_observation_id=f"observation-{index}",
            experiment_id="experiment-001", live_source_id=self.declaration.device_id,
            expected_participant_id="participant-001", observation_type="first_evidence_missing",
            acquisition_health_policy="policy-001", interpretation_label="informational",
            required=True, session_time_s=1.0, details={"index": index},
        ))

    def archived_decisions(self, session_id):
        path = self.launch.root / f"session_{session_id}" / "evidence/runtime_evidence.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def assert_separate_persistence_products(self, session_id, messages):
        directory = self.launch.root / f"session_{session_id}"
        for name in ("session_record_initial.json", "session_record_final.json"):
            record = self.storage.read_session_record(directory / name)
            self.assertEqual(record["accepted_session_config"]["session_id"], session_id)
            self.assertEqual(record["runtime_evidence"], [])
            self.assertEqual(record["runtime_evidence_audit"], [])
        self.assertEqual(record["ingest_audit_records"], [
            audit.to_dict() for audit in self.launch.ingestor.ingest_audit
        ])
        self.assertEqual(self.archived_decisions(session_id), [message.to_dict() for message in messages])
        audits = [json.loads(line) for line in
                  (directory / "evidence/ingest_audit.jsonl").read_text().splitlines()]
        self.assertEqual(audits, [audit.to_dict() for audit in self.launch.ingestor.runtime_evidence_audit])
        summary = json.loads((directory / "evidence/compilation_summary.json").read_text())
        self.assertEqual(summary["runtime_evidence_ids"], [message.evidence_id for message in messages])
        self.assertEqual(summary["runtime_evidence_count"], len(messages))
        self.assertEqual(summary["ingest_audit_count"], len(audits))

    async def test_successive_sessions_reuse_services_and_node_preserving_records(self):
        controller, ingestor, sync = self.launch.controller, self.launch.ingestor, self.launch.sync
        snapshots = []
        for _ in range(2):
            sid = await self.start_session()
            iteration = await self.launch.communication.request_command(
                RuntimeParticipant("acquisition_node", "node-a"),
                "run_one_iteration", sid, {}, 0.01)
            self.assertTrue(iteration.success, iteration.reason)
            journal = ingestor.recovery_journal_path
            await self.stop_session()
            finalized = controller.finalize_session()
            self.assertTrue(finalized.succeeded, finalized.error)
            paths = [self.launch.root / f"session_{sid}" / name for name in (
                "session_record_initial.json", "session_record_final.json",
                "evidence/runtime_evidence.jsonl", "evidence/ingest_audit.jsonl",
                "evidence/compilation_summary.json")]
            self.assertTrue(ingestor.release_session(sid))
            self.assertTrue(sync.release_session(sid))
            released = await controller.release_session()
            self.assertTrue(released.succeeded, released.error)
            self.assertEqual(released.details["session_state"], "completed")
            self.assertEqual(released.details["final_session_status"]["state"], "completed")
            self.assertIsNone(controller.get_status()["session_id"])
            self.assertEqual(controller.get_status()["last_released_session"]["session_id"], sid)
            self.assertIs(self.launch.controller, controller)
            self.assertIs(self.launch.ingestor, ingestor)
            self.assertIs(self.launch.sync, sync)
            self.assertIs(self.launch.nodes["node-a"], self.node)
            self.assertIs(self.launch.adapters["node-a"][0], self.adapter)
            self.assertIsNone(self.node.reserved_for_session_id)
            self.assertTrue(self.node.status()["cleanup_confirmed"])
            self.assertTrue(self.launch.communication.check_ready().ready)
            terminal_record = self.storage.read_session_record(paths[1])
            self.assertEqual(terminal_record["final_session_status"]["state"], "completed")
            snapshots.extend((path, path.read_bytes()) for path in (*paths, journal))
        for path, content in snapshots:
            self.assertEqual(path.read_bytes(), content)

    async def test_evidence_bearing_services_reuse_after_controller_archival(self):
        controller, ingestor, sync = self.launch.controller, self.launch.ingestor, self.launch.sync
        preserved = []
        for index in range(2):
            sid = await self.start_session()
            self.record_decision(index)
            ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                "temporary-" + sid, sid, "observation", "producer", {}, False))
            sync.create_and_activate_mapping(sid, "node-a", 1.0, 2.0, 1.0, "initial")
            sync.retire_active_mapping(sid, "node-a", "Session ending")
            for position, update in enumerate(sync.mapping_update_evidence):
                ingestor.receive_runtime_evidence(update.to_runtime_evidence_message(
                    f"mapping-{sid}-{position}", "synchronization"))
            await self.stop_session()
            sync.stop()
            self.assertTrue(sync.release_session(sid, ingestor=ingestor))
            self.assertTrue(controller.finalize_session().succeeded)
            with self.assertRaisesRegex(RuntimeError, "completion evidence"):
                ingestor.release_session(sid, storage_manager=self.storage)
            self.assertTrue((await controller.release_session()).succeeded)
            journal = ingestor.recovery_journal_path
            confirmation = self.storage.get_session_preservation_confirmation(sid)
            self.assertEqual(len(confirmation["runtime_evidence"]), 3)
            self.assertEqual(len(confirmation["ingest_audit"]), 4)
            self.assertEqual(confirmation["session_record"]["runtime_evidence"], [])
            self.assertEqual(confirmation["session_record"]["runtime_evidence_audit"], [])
            self.assertTrue(ingestor.release_session(sid, storage_manager=self.storage))
            self.assertEqual(ingestor.accepted_runtime_evidence, ())
            self.assertEqual(sync.mapping_update_evidence, ())
            preserved.append((journal, journal.read_bytes()))
        for path, content in preserved:
            self.assertEqual(path.read_bytes(), content)

    async def test_controller_release_requires_terminal_cleanup_and_final_persistence(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        await self.stop_session()
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_failed_persistence_blocks_release_until_failed_outcome_is_preserved(self):
        sid = await self.start_session()
        await self.stop_session()
        controller = self.launch.controller
        with patch.object(self.storage, "write_evidence_archive", side_effect=OSError("disk full")):
            self.assertFalse(controller.finalize_session().succeeded)
        self.assertEqual(controller.get_status()["session_state"], "failed")
        self.assertFalse((await controller.release_session()).succeeded)
        persisted = controller.finalize_session()
        self.assertTrue(persisted.succeeded, persisted.error)
        self.assertEqual(controller.get_status()["session_state"], "failed")
        record = self.storage.read_session_record(persisted.details["session_record_path"])
        self.assertEqual(record["final_session_status"]["state"], "failed")
        result = await controller.release_session()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(result.details["session_id"], sid)
        self.assertEqual(result.details["session_state"], "failed")

    async def test_final_record_failure_blocks_release_without_changing_failed_outcome(self):
        await self.start_session()
        await self.stop_session()
        controller = self.launch.controller
        with patch.object(self.storage, "write_final_session_record", side_effect=OSError("record unavailable")):
            self.assertFalse(controller.finalize_session().succeeded)
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["session_state"], "failed")
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertTrue((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["last_released_session"]["session_state"], "failed")

    async def test_unconfirmed_node_cleanup_blocks_controller_release(self):
        sid = await self.start_session()
        with patch.object(self.adapter, "shutdown", side_effect=OSError("cleanup unavailable")):
            self.assertFalse((await self.launch.controller.stop_launched_session()).succeeded)
        self.assertTrue(self.launch.controller.finalize_session().succeeded)
        self.assertFalse((await self.launch.controller.release_session()).succeeded)
        self.assertEqual(self.node.reserved_for_session_id, sid)
        self.assertFalse(self.node.status()["cleanup_confirmed"])

    async def test_terminal_record_refresh_failure_retains_completed_binding(self):
        sid = await self.start_session()
        await self.stop_session()
        controller = self.launch.controller
        self.assertTrue(controller.finalize_session().succeeded)
        with patch.object(self.storage, "write_final_session_record", side_effect=OSError("disk unavailable")):
            result = await controller.release_session()
        self.assertFalse(result.succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.get_status()["session_state"], "completed")
        released = await controller.release_session()
        self.assertTrue(released.succeeded, released.error)
        record = self.storage.read_session_record(released.details["session_record_path"])
        self.assertEqual(record["final_session_status"]["state"], "completed")

    async def test_intake_after_final_persistence_blocks_controller_release(self):
        sid = await self.start_session()
        await self.stop_session()
        self.assertTrue(self.launch.controller.finalize_session().succeeded)
        self.launch.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
            "late", sid, "warning", "producer", {"reason": "late evidence"}, True))
        result = await self.launch.controller.release_session()
        self.assertFalse(result.succeeded)
        self.assertIn("intake changed", result.error)
        self.assertEqual(self.launch.controller.get_status()["session_id"], sid)
        self.assertTrue(self.launch.controller.finalize_session().succeeded)
        self.assertTrue((await self.launch.controller.release_session()).succeeded)
        evidence_path = self.launch.root / f"session_{sid}" / "evidence/runtime_evidence.jsonl"
        self.assertEqual(json.loads(evidence_path.read_text())["evidence_id"], "late")

    async def test_all_controller_decisions_are_archived_before_release_and_retained_on_disk(self):
        sid = await self.start_session()
        controller = self.launch.controller
        for index in (1, 2):
            self.record_decision(index)
        messages = controller.controller_action_decision_evidence
        self.assertEqual(self.launch.ingestor.accepted_runtime_evidence, messages)
        self.assertEqual(len(self.launch.ingestor.runtime_evidence_audit), 2)
        await self.stop_session()
        result = controller.finalize_session()
        self.assertTrue(result.succeeded, result.error)
        self.assert_separate_persistence_products(sid, messages)
        self.assertEqual(self.archived_decisions(sid), [message.to_dict() for message in messages])
        paths = [Path(path) for path in result.details["evidence_archive_paths"].values()]
        snapshots = [(path, path.read_bytes()) for path in paths]
        released = await controller.release_session()
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(controller.get_status()["session_id"])
        self.assertEqual(controller.controller_action_decisions, ())
        self.assertEqual(controller.controller_action_decision_evidence, ())
        for path, content in snapshots:
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(len(self.launch.ingestor.accepted_runtime_evidence), 2)
        self.assert_separate_persistence_products(sid, messages)
        record = self.storage.read_session_record(self.launch.root / f"session_{sid}/session_record_final.json")
        self.assertEqual(record["final_session_status"]["state"], "completed")
        self.assertTrue(record["cleanup_evidence"]["cleanup_occurred"])

    async def test_archive_rewrite_after_finalization_blocks_controller_release(self):
        sid = await self.start_session()
        controller = self.launch.controller
        incomplete = self.launch.ingestor.compile_persistent_runtime_evidence()
        self.record_decision()
        messages = controller.controller_action_decision_evidence
        journal = self.launch.ingestor.recovery_journal_path
        journal_contents = journal.read_bytes()
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)

        self.storage.write_evidence_archive(sid, incomplete)
        result = await controller.release_session()

        self.assertFalse(result.succeeded)
        self.assertIn("Current Evidence Archive", result.error)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.get_status()["session_state"], "completed")
        self.assertEqual(controller.controller_action_decision_evidence, messages)
        self.assertEqual(journal.read_bytes(), journal_contents)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_failed_archive_rewrite_after_finalization_retains_controller_binding(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision()
        messages = controller.controller_action_decision_evidence
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)
        compiled = self.launch.ingestor.compile_persistent_runtime_evidence()
        journal = self.launch.ingestor.recovery_journal_path
        journal_contents = journal.read_bytes()
        open_file = Path.open

        for failed_file in ("runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"):
            with self.subTest(failed_file=failed_file):
                def fail_write(path, *args, **kwargs):
                    if path.name == failed_file and args and args[0] == "w":
                        raise OSError("archive rewrite unavailable")
                    return open_file(path, *args, **kwargs)

                with patch.object(Path, "open", fail_write):
                    with self.assertRaises(OSError):
                        self.storage.write_evidence_archive(sid, compiled)
                self.assertIsNone(self.storage.get_session_preservation_confirmation(sid))
                result = await controller.release_session()
                self.assertFalse(result.succeeded)
                self.assertEqual(controller.get_status()["session_id"], sid)
                self.assertEqual(controller.get_status()["session_state"], "completed")
                self.assertEqual(controller.controller_action_decision_evidence, messages)
                self.assertEqual(journal.read_bytes(), journal_contents)
                self.storage.write_evidence_archive(sid, compiled)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_controller_confirmation_blocks_rewrite_until_release_commits(self):
        sid = await self.start_session()
        controller = self.launch.controller
        incomplete = self.launch.ingestor.compile_persistent_runtime_evidence()
        self.record_decision()
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)
        attempted = Event()
        get_confirmation = self.storage.get_session_preservation_confirmation
        open_file = Path.open
        pending, observed_bindings = [], []
        calls = 0

        def rewrite():
            attempted.set()
            return self.storage.write_evidence_archive(sid, incomplete)

        def observe_write(path, *args, **kwargs):
            if path.name == "runtime_evidence.jsonl" and args and args[0] == "w":
                observed_bindings.append(controller.get_status()["session_id"])
            return open_file(path, *args, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as workers:
            def confirm(session_id):
                nonlocal calls
                calls += 1
                confirmation = get_confirmation(session_id)
                if calls == 2:
                    pending.append(workers.submit(rewrite))
                    self.assertTrue(attempted.wait(5))
                    with self.assertRaises(FutureTimeoutError):
                        pending[0].result(timeout=0.1)
                return confirmation

            with patch.object(self.storage, "get_session_preservation_confirmation", side_effect=confirm):
                with patch.object(Path, "open", observe_write):
                    result = await controller.release_session()
                    self.assertTrue(result.succeeded, result.error)
                    pending[0].result(timeout=5)
        self.assertEqual(observed_bindings, [None])
        self.assertEqual(controller.controller_action_decision_evidence, ())

    async def test_archive_rewrite_during_unsubscribe_blocks_controller_release(self):
        sid = await self.start_session()
        controller = self.launch.controller
        incomplete = self.launch.ingestor.compile_persistent_runtime_evidence()
        self.record_decision()
        messages = controller.controller_action_decision_evidence
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)
        unsubscribe = launch_fixtures._Subscription.unsubscribe
        rewritten = False

        async def unsubscribe_then_rewrite(subscription):
            nonlocal rewritten
            await unsubscribe(subscription)
            if not rewritten:
                self.storage.write_evidence_archive(sid, incomplete)
                rewritten = True

        with patch.object(launch_fixtures._Subscription, "unsubscribe", unsubscribe_then_rewrite):
            result = await controller.release_session()
        self.assertTrue(rewritten)
        self.assertFalse(result.succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.controller_action_decision_evidence, messages)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_stale_release_preserves_subsequent_session_binding(self):
        controller, ingestor, sync = self.launch.controller, self.launch.ingestor, self.launch.sync
        unsubscribe = launch_fixtures._Subscription.unsubscribe
        for with_decision, fail_unsubscribe in ((False, False), (True, False), (True, True)):
            with self.subTest(with_decision=with_decision, fail_unsubscribe=fail_unsubscribe):
                sid_a = await self.start_session()
                await self.stop_session()
                self.assertTrue(controller.finalize_session().succeeded)
                paused, resume = asyncio.Event(), asyncio.Event()
                delayed = None

                async def pause_old_release(subscription):
                    if asyncio.current_task() is delayed:
                        paused.set()
                        await resume.wait()
                        if fail_unsubscribe:
                            raise OSError("Old subscription unavailable")
                    await unsubscribe(subscription)

                with patch.object(launch_fixtures._Subscription, "unsubscribe", pause_old_release):
                    delayed = asyncio.create_task(controller.release_session())
                    try:
                        await asyncio.wait_for(paused.wait(), 5)
                        winner = await controller.release_session()
                        self.assertTrue(winner.succeeded, winner.error)
                        self.assertEqual(winner.details["session_id"], sid_a)
                        self.assertTrue(ingestor.release_session(sid_a, storage_manager=self.storage))
                        self.assertTrue(sync.release_session(sid_a))
                        sid_b = await self.start_session()
                        self.assertNotEqual(sid_a, sid_b)
                        if with_decision:
                            self.record_decision()
                        status = controller.get_status()
                        decisions = controller.controller_action_decisions
                        messages = controller.controller_action_decision_evidence
                        intake = ingestor.accepted_runtime_evidence
                        audit = ingestor.runtime_evidence_audit
                        journal = ingestor.recovery_journal_path
                        journal_bytes = journal.read_bytes()
                        subscriptions = tuple(s for s in self.launch.broker.subscriptions
                                              if s.active and ".command_result." in s.subject)
                        self.assertEqual(len(subscriptions), 2)
                        resume.set()
                        stale = await asyncio.wait_for(delayed, 5)
                    finally:
                        resume.set()
                        if not delayed.done():
                            delayed.cancel()
                        await asyncio.gather(delayed, return_exceptions=True)

                self.assertFalse(stale.succeeded)
                self.assertEqual(stale.details["session_id"], sid_a)
                self.assertEqual(controller.get_status(), status)
                self.assertEqual(controller.controller_action_decisions, decisions)
                self.assertEqual(controller.controller_action_decision_evidence, messages)
                self.assertEqual(ingestor.accepted_runtime_evidence, intake)
                self.assertEqual(ingestor.runtime_evidence_audit, audit)
                self.assertEqual(ingestor.session_id, sid_b)
                self.assertEqual(journal.read_bytes(), journal_bytes)
                self.assertTrue(all(s.active for s in subscriptions))
                self.assertEqual(self.node.status()["session_id"], sid_b)
                self.assertEqual(self.node.reserved_for_session_id, sid_b)
                self.assertTrue(self.node.status()["is_running"])
                iteration = await self.launch.communication.request_command(
                    RuntimeParticipant("acquisition_node", "node-a"),
                    "run_one_iteration", sid_b, {}, 0.01)
                self.assertTrue(iteration.success, iteration.reason)
                await self.stop_session()
                self.assertTrue(controller.finalize_session().succeeded)
                self.assertTrue((await controller.release_session()).succeeded)
                self.assertTrue(sync.release_session(sid_b))
                self.assertTrue(ingestor.release_session(sid_b, storage_manager=self.storage))

    async def test_overlapping_releases_retire_same_binding_once(self):
        controller = self.launch.controller
        unsubscribe = launch_fixtures._Subscription.unsubscribe
        for pause_index in (0, 1):
            with self.subTest(pause_index=pause_index):
                sid = await self.start_session()
                self.record_decision()
                messages = controller.controller_action_decision_evidence
                journal = self.launch.ingestor.recovery_journal_path
                journal_bytes = journal.read_bytes()
                await self.stop_session()
                self.assertTrue(controller.finalize_session().succeeded)
                paused, resume = asyncio.Event(), asyncio.Event()
                delayed = None
                calls = 0

                async def pause_old_release(subscription):
                    nonlocal calls
                    if asyncio.current_task() is delayed:
                        index = calls
                        calls += 1
                        if index == pause_index:
                            paused.set()
                            await resume.wait()
                    await unsubscribe(subscription)

                with patch.object(launch_fixtures._Subscription, "unsubscribe", pause_old_release):
                    delayed = asyncio.create_task(controller.release_session())
                    try:
                        await asyncio.wait_for(paused.wait(), 5)
                        winner = await controller.release_session()
                        self.assertTrue(winner.succeeded, winner.error)
                        status = controller.get_status()
                        resume.set()
                        stale = await asyncio.wait_for(delayed, 5)
                    finally:
                        resume.set()
                        if not delayed.done():
                            delayed.cancel()
                        await asyncio.gather(delayed, return_exceptions=True)
                self.assertFalse(stale.succeeded)
                self.assertIn("binding changed", stale.error)
                self.assertEqual(stale.details["session_id"], sid)
                self.assertEqual(controller.get_status(), status)
                self.assertEqual(controller.controller_action_decision_evidence, ())
                self.assertEqual(self.archived_decisions(sid), [m.to_dict() for m in messages])
                self.assertEqual(journal.read_bytes(), journal_bytes)
                self.assertTrue(self.launch.ingestor.release_session(sid, storage_manager=self.storage))
                self.assertTrue(self.launch.sync.release_session(sid))

    async def test_release_cancellation_preserves_binding_and_allows_retry(self):
        controller = self.launch.controller
        unsubscribe = launch_fixtures._Subscription.unsubscribe
        for pause_index in (0, 1):
            with self.subTest(pause_index=pause_index):
                sid = await self.start_session()
                self.record_decision()
                decisions = controller.controller_action_decisions
                messages = controller.controller_action_decision_evidence
                journal = self.launch.ingestor.recovery_journal_path
                journal_bytes = journal.read_bytes()
                await self.stop_session()
                self.assertTrue(controller.finalize_session().succeeded)
                status = controller.get_status()
                paused, resume = asyncio.Event(), asyncio.Event()
                calls = 0

                async def pause_unsubscribe(subscription):
                    nonlocal calls
                    index = calls
                    calls += 1
                    if index == pause_index:
                        paused.set()
                        await resume.wait()
                    await unsubscribe(subscription)

                with patch.object(launch_fixtures._Subscription, "unsubscribe", pause_unsubscribe):
                    pending = asyncio.create_task(controller.release_session())
                    try:
                        await asyncio.wait_for(paused.wait(), 5)
                        pending.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await pending
                    finally:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                self.assertEqual(controller.get_status(), status)
                self.assertEqual(controller.controller_action_decisions, decisions)
                self.assertEqual(controller.controller_action_decision_evidence, messages)
                self.assertEqual(self.launch.ingestor.session_id, sid)
                self.assertEqual(self.launch.ingestor.accepted_runtime_evidence, messages)
                self.assertEqual(journal.read_bytes(), journal_bytes)
                self.assertTrue((await controller.release_session()).succeeded)
                self.assertTrue(self.launch.ingestor.release_session(sid, storage_manager=self.storage))
                self.assertTrue(self.launch.sync.release_session(sid))

    async def test_unsubscribe_exception_preserves_binding_and_allows_retry(self):
        controller = self.launch.controller
        unsubscribe = launch_fixtures._Subscription.unsubscribe
        for failure_index in (0, 1):
            with self.subTest(failure_index=failure_index):
                sid = await self.start_session()
                self.record_decision()
                decisions = controller.controller_action_decisions
                messages = controller.controller_action_decision_evidence
                journal = self.launch.ingestor.recovery_journal_path
                journal_bytes = journal.read_bytes()
                await self.stop_session()
                self.assertTrue(controller.finalize_session().succeeded)
                calls = 0

                async def fail_unsubscribe(subscription):
                    nonlocal calls
                    index = calls
                    calls += 1
                    await unsubscribe(subscription)
                    if index == failure_index:
                        raise OSError("Subscription unavailable")

                with patch.object(launch_fixtures._Subscription, "unsubscribe", fail_unsubscribe):
                    result = await controller.release_session()
                self.assertFalse(result.succeeded)
                self.assertIn("Subscription unavailable", result.error)
                self.assertEqual(controller.get_status()["session_id"], sid)
                self.assertEqual(controller.get_status()["session_state"], "completed")
                self.assertEqual(controller.controller_action_decisions, decisions)
                self.assertEqual(controller.controller_action_decision_evidence, messages)
                self.assertEqual(self.launch.ingestor.accepted_runtime_evidence, messages)
                self.assertEqual(journal.read_bytes(), journal_bytes)
                self.assertTrue((await controller.release_session()).succeeded)
                self.assertTrue(self.launch.ingestor.release_session(sid, storage_manager=self.storage))
                self.assertTrue(self.launch.sync.release_session(sid))

    async def test_successful_publication_does_not_confirm_controller_decision_archival(self):
        sid = await self.start_session()
        await self.stop_session()
        controller = self.launch.controller
        self.assertTrue(controller.finalize_session().succeeded)
        self.record_decision()
        message = controller.controller_action_decision_evidence[0]
        boundary = launch_fixtures._Boundary("controller", "controller", self.launch.broker)
        await boundary.publish_evidence(message)
        self.assertEqual(self.archived_decisions(sid), [])
        result = await controller.release_session()
        self.assertFalse(result.succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.controller_action_decision_evidence, (message,))

    async def test_repeated_observation_presentations_have_independent_archive_identities(self):
        sid = await self.start_session()
        controller = self.launch.controller
        decisions = [self.record_decision(1), self.record_decision(1)]
        for decision in decisions:
            self.assertTrue(controller.execute_controller_action_decision(decision).succeeded)
        messages = controller.controller_action_decision_evidence
        self.assertEqual(len(messages), 2)
        self.assertEqual(len({message.evidence_id for message in messages}), 2)
        self.assertEqual(len(self.launch.ingestor.runtime_evidence_audit), 2)
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(self.archived_decisions(sid), [message.to_dict() for message in messages])
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_partial_controller_decision_compilation_cannot_confirm_release(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision(1)
        self.record_decision(2)
        compiled = self.launch.ingestor.compile_persistent_runtime_evidence()
        partial = {**compiled, "runtime_evidence": compiled["runtime_evidence"][:1]}
        await self.stop_session()
        # A real archive write of a subset is not confirmation of all owned decisions.
        self.storage.write_evidence_archive(sid, partial)
        self.assertEqual(len(self.archived_decisions(sid)), 1)
        with patch.object(self.launch.ingestor, "compile_persistent_runtime_evidence", return_value=partial):
            result = controller.finalize_session()
        self.assertFalse(result.succeeded)
        self.assertIn("missing from persistent compilation", result.error)
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(len(controller.controller_action_decisions), 2)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(len(self.archived_decisions(sid)), 2)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_matching_evidence_identity_with_changed_contents_cannot_confirm_release(self):
        await self.start_session()
        controller = self.launch.controller
        self.record_decision()
        compiled = self.launch.ingestor.compile_persistent_runtime_evidence()
        original = compiled["runtime_evidence"][0]
        changed = RuntimeEvidenceMessage.from_dict({
            **original.to_dict(), "payload": {**original.payload, "controller_decision": "record_warning"},
        })
        await self.stop_session()
        with patch.object(self.launch.ingestor, "compile_persistent_runtime_evidence",
                          return_value={**compiled, "runtime_evidence": (changed,)}):
            result = controller.finalize_session()
        self.assertFalse(result.succeeded)
        self.assertIn("missing from persistent compilation", result.error)
        self.assertFalse((await controller.release_session()).succeeded)

    async def test_decision_after_archive_snapshot_requires_new_finalization(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision(1)
        await self.stop_session()
        self.assertTrue(controller.finalize_session().succeeded)
        self.record_decision(2)
        self.assertEqual(len(self.archived_decisions(sid)), 1)
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["session_state"], "completed")
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(len(self.archived_decisions(sid)), 2)
        messages = controller.controller_action_decision_evidence
        self.assert_separate_persistence_products(sid, messages)
        self.assertTrue((await controller.release_session()).succeeded)
        self.assert_separate_persistence_products(sid, messages)

    async def test_decision_during_archive_write_prevents_stale_completion_confirmation(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision(1)
        await self.stop_session()
        write_archive = self.storage.write_evidence_archive

        def write_then_decide(session_id, compiled):
            paths = write_archive(session_id, compiled)
            self.record_decision(2)
            return paths

        with patch.object(self.storage, "write_evidence_archive", side_effect=write_then_decide):
            result = controller.finalize_session()
        self.assertFalse(result.succeeded)
        self.assertIn("changed during final persistence", result.error)
        self.assertEqual(controller.get_status()["session_state"], "failed")
        self.assertEqual(len(self.archived_decisions(sid)), 1)
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertTrue(controller.finalize_session().succeeded)
        self.assertEqual(len(self.archived_decisions(sid)), 2)
        self.assertTrue((await controller.release_session()).succeeded)

    async def test_failed_or_unconfirmed_archive_write_retains_controller_decisions(self):
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision()
        await self.stop_session()
        for outcome in (OSError("archive unavailable"), None):
            with self.subTest(outcome=outcome):
                options = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(self.storage, "write_evidence_archive", **options):
                    result = controller.finalize_session()
                self.assertFalse(result.succeeded)
                self.assertFalse((await controller.release_session()).succeeded)
                self.assertEqual(controller.get_status()["session_id"], sid)
                self.assertEqual(len(controller.controller_action_decisions), 1)
        self.assertTrue(controller.finalize_session().succeeded)
        messages = controller.controller_action_decision_evidence
        self.assert_separate_persistence_products(sid, messages)
        record = self.storage.read_session_record(self.launch.root / f"session_{sid}/session_record_final.json")
        self.assertEqual(record["final_session_status"]["state"], "failed")
        self.assertTrue(record["warnings_or_failures"])
        self.assertTrue((await controller.release_session()).succeeded)
        self.assert_separate_persistence_products(sid, messages)

    async def test_brokered_controller_without_ingestor_reports_explicit_finalization_failure(self):
        self.launch.controller = Controller(storage_manager=self.storage, synchronization_manager=self.launch.sync)
        sid = await self.start_session()
        controller = self.launch.controller
        self.record_decision()
        messages = controller.controller_action_decision_evidence
        await self.stop_session()

        result = controller.finalize_session()

        self.assertFalse(result.succeeded)
        self.assertIn("RuntimeError: Session finalization requires an explicit Ingestor reference", result.error)
        self.assertEqual(controller.get_status()["session_state"], "failed")
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.controller_action_decision_evidence, messages)
        self.assertEqual(self.launch.ingestor.accepted_runtime_evidence, ())
        self.assertFalse((self.launch.root / f"session_{sid}/evidence/runtime_evidence.jsonl").exists())

    async def test_failed_decision_intake_retains_evidence_and_blocks_archival_release(self):
        sid = await self.start_session()
        controller = self.launch.controller
        with patch.object(self.launch.ingestor, "receive_runtime_evidence", side_effect=OSError("journal unavailable")):
            with self.assertRaisesRegex(OSError, "journal unavailable"):
                self.record_decision()
        message = controller.controller_action_decision_evidence[0]
        self.assertTrue(message.is_persistent)
        self.assertEqual(self.launch.ingestor.accepted_runtime_evidence, ())
        await self.stop_session()
        self.assertFalse(controller.finalize_session().succeeded)
        self.assertFalse((await controller.release_session()).succeeded)
        self.assertEqual(controller.get_status()["session_id"], sid)
        self.assertEqual(controller.controller_action_decision_evidence, (message,))


class EvidenceOwnerReleaseTests(unittest.TestCase):
    def test_empty_ingestor_reuses_binding_without_deleting_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            ingestor = InMemoryIngestor(recovery_journal_root=directory)
            paths = []
            for sid in ("session-a", "session-b"):
                self.assertTrue(ingestor.prepare_session(sid).ready)
                paths.append(ingestor.recovery_journal_path)
                with self.assertRaises(RuntimeError):
                    ingestor.release_session("someone-else")
                self.assertTrue(ingestor.release_session(sid))
                self.assertIsNone(ingestor.session_id)
                with self.assertRaises(RuntimeError):
                    ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                        "late-" + sid, sid, "observation", "producer", {}, True))
            self.assertTrue(all(path.read_bytes() == b"" for path in paths))

    def test_ingestor_preserves_evidence_and_audit_when_confirmation_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            ingestor = InMemoryIngestor(recovery_journal_root=directory)
            ingestor.prepare_session("session-a")
            for persistent in (False, True):
                ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                    str(persistent), "session-a", "observation", "producer", {}, persistent))
            messages = ingestor.accepted_runtime_evidence
            audit = ingestor.runtime_evidence_audit
            path = ingestor.recovery_journal_path
            content = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "confirmation"):
                ingestor.release_session("session-a")
            with self.assertRaises(RuntimeError):
                ingestor.prepare_session("session-b")
            self.assertEqual(ingestor.session_id, "session-a")
            self.assertEqual(ingestor.accepted_runtime_evidence, messages)
            self.assertEqual(ingestor.runtime_evidence_audit, audit)
            self.assertEqual(path.read_bytes(), content)
            recovered = InMemoryIngestor(session_id="session-a", recovery_journal_path=path)
            self.assertEqual(recovered.accepted_runtime_evidence[:2], messages)

    def test_synchronization_reuse_requires_stopped_time(self):
        sync = SynchronizationManager()
        for sid in ("session-a", "session-b"):
            sync.prepare_session(sid)
            self.assertEqual(sync.start(), 0.0)
            with self.assertRaisesRegex(RuntimeError, "must stop"):
                sync.release_session(sid)
            with self.assertRaises(RuntimeError):
                sync.prepare_session("other-session")
            sync.stop()
            self.assertTrue(sync.release_session(sid))
            self.assertFalse(sync.is_running)

    def test_uncertain_journal_blocks_release_without_discarding_recovery_information(self):
        with tempfile.TemporaryDirectory() as directory:
            ingestor = InMemoryIngestor(recovery_journal_root=directory)
            ingestor.prepare_session("session-a")
            path = ingestor.recovery_journal_path
            with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("flush failed")):
                with self.assertRaises(OSError):
                    ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                        "uncertain", "session-a", "warning", "producer", {}, True))
            content = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "integrity"):
                ingestor.release_session("session-a")
            self.assertEqual(ingestor.session_id, "session-a")
            self.assertEqual(ingestor.recovery_journal_path, path)
            self.assertEqual(path.read_bytes(), content)
            self.assertFalse(ingestor.check_ready().ready)

    def test_synchronization_keeps_mapping_history_without_preservation_confirmation(self):
        sync = SynchronizationManager()
        sync.prepare_session("session-a")
        sync.start()
        mapping = sync.create_and_activate_mapping("session-a", "node", 1.0, 2.0, 1.0, "anchor")
        sync.stop()
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            sync.release_session("session-a")
        self.assertIs(sync.get_active_mapping("session-a", "node"), mapping)
        sync.retire_active_mapping("session-a", "node", "Session ended")
        evidence = sync.mapping_update_evidence
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            sync.release_session("session-a")
        self.assertEqual(sync.mapping_update_evidence, evidence)
        with self.assertRaises(RuntimeError):
            sync.prepare_session("session-b")


class EvidenceBearingReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = PersistentStorageManager(self.root / "records.jsonl")
        self.ingestor = InMemoryIngestor(self.storage, recovery_journal_root=self.root / "journals")
        self.ingestor.prepare_session("session-a")
        self.session = self.make_session("session-a")

    @staticmethod
    def make_session(sid):
        session = Session(sid, SessionConfig([], "storage", [], "errors", session_id=sid))
        session.initialize()
        session.start()
        session.stop()
        return session

    def message(self, identity="persistent", persistent=True):
        return RuntimeEvidenceMessage(identity, self.session.session_id, "observation", "producer",
                                      {"value": identity}, persistent)

    def write_terminal_record(self):
        return self.storage.write_final_session_record(
            self.session.session_id,
            accepted_session_config=self.session.configuration,
            lifecycle_evidence=self.session.transition_history,
            readiness_evidence=self.session.readiness_checks,
            device_readiness_evidence=(), service_readiness_evidence=(),
            accepted_acquisition_envelopes=self.storage.get_envelopes_for_session(self.session.session_id),
            ingest_audit_records=self.ingestor.ingest_audit,
            final_session_status=self.session.final_status,
            cleanup_evidence={"cleanup_occurred": self.session.cleanup_occurred},
        )

    def archive(self, compiled=None):
        return self.storage.write_evidence_archive(
            self.session.session_id,
            compiled if compiled is not None else self.ingestor.compile_persistent_runtime_evidence())

    def finish(self):
        self.session.complete()
        self.write_terminal_record()

    def test_exact_archive_and_completion_allow_release_and_later_session(self):
        for sid in ("session-a", "session-b"):
            if sid != self.session.session_id:
                self.ingestor.prepare_session(sid)
                self.session = self.make_session(sid)
            persistent, temporary = self.message(), self.message("temporary", False)
            for message in (persistent, temporary):
                self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
            journal = self.ingestor.recovery_journal_path
            content = journal.read_bytes()
            paths = self.archive()
            self.finish()
            confirmation = self.storage.get_session_preservation_confirmation(sid)
            self.assertEqual(confirmation["runtime_evidence"], [persistent.to_dict()])
            self.assertEqual(confirmation["ingest_audit"], [
                audit.to_dict() for audit in self.ingestor.runtime_evidence_audit])
            self.assertEqual([json.loads(line) for line in paths["runtime_evidence"].read_text().splitlines()],
                             [persistent.to_dict()])
            # Callers cannot mutate StorageManager's retained confirmation.
            confirmation["runtime_evidence"].clear()
            self.assertTrue(self.ingestor.release_session(sid))
            self.assertIsNone(self.ingestor.session_id)
            self.assertEqual(self.ingestor.accepted_runtime_evidence, ())
            self.assertEqual(self.ingestor.runtime_evidence_audit, ())
            self.assertEqual(journal.read_bytes(), content)
            self.assertTrue(self.ingestor.check_ready().ready)

    def test_terminal_lifecycle_evidence_is_required_not_only_archive_success(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.write_terminal_record()
        with self.assertRaisesRegex(RuntimeError, "completion evidence"):
            self.ingestor.release_session("session-a")
        self.finish()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_failed_and_aborted_session_records_allow_confirmed_release(self):
        for state in ("failed", "aborted"):
            with self.subTest(state=state):
                if self.ingestor.session_id is None:
                    self.ingestor.prepare_session(state)
                    self.session = self.make_session(state)
                self.ingestor.receive_runtime_evidence(self.message())
                self.archive()
                getattr(self.session, "fail" if state == "failed" else "abort")()
                self.write_terminal_record()
                self.assertTrue(self.ingestor.release_session(self.session.session_id))

    def test_absent_partial_and_changed_content_archive_block_without_losing_evidence(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.ingestor.receive_runtime_evidence(self.message("second"))
        self.finish()
        journal = self.ingestor.recovery_journal_path
        original = journal.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            self.ingestor.release_session("session-a")
        for missing in ("runtime_evidence", "ingest_audit"):
            with self.subTest(missing=missing):
                compiled = self.ingestor.compile_persistent_runtime_evidence()
                compiled[missing] = compiled[missing][:-1]
                self.archive(compiled)
                with self.assertRaisesRegex(RuntimeError, "current runtime intake"):
                    self.ingestor.release_session("session-a")
        compiled = self.ingestor.compile_persistent_runtime_evidence()
        compiled["runtime_evidence"][0].payload["value"] = "changed"
        self.archive(compiled)
        with self.assertRaisesRegex(RuntimeError, "current runtime intake"):
            self.ingestor.release_session("session-a")
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 2)
        self.assertEqual(journal.read_bytes(), original)
        self.archive()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_failed_archive_rewrite_invalidates_confirmation_and_preserves_journal(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        journal = self.ingestor.recovery_journal_path
        original = journal.read_bytes()
        open_file = Path.open

        def failing_open(path, *args, **kwargs):
            if path.name == "ingest_audit.jsonl" and args and args[0] == "w":
                raise OSError("archive disk unavailable")
            return open_file(path, *args, **kwargs)

        with patch.object(Path, "open", failing_open):
            with self.assertRaises(OSError):
                self.archive()
        self.assertIsNone(self.storage.get_session_preservation_confirmation("session-a"))
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            self.ingestor.release_session("session-a")
        self.assertEqual(journal.read_bytes(), original)
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 1)
        self.archive()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_ingestor_confirmation_blocks_incomplete_rewrite_until_release_commits(self):
        self.ingestor.receive_runtime_evidence(self.message())
        incomplete = self.ingestor.compile_persistent_runtime_evidence()
        self.ingestor.receive_runtime_evidence(self.message("second"))
        self.archive()
        self.finish()
        journal = self.ingestor.recovery_journal_path
        journal_contents = journal.read_bytes()
        get_confirmation = self.storage.get_session_preservation_confirmation
        open_file = Path.open
        attempted = Event()
        pending, observed_bindings = [], []

        def rewrite():
            attempted.set()
            return self.archive(incomplete)

        def observe_write(path, *args, **kwargs):
            if path.name == "runtime_evidence.jsonl" and args and args[0] == "w":
                observed_bindings.append(self.ingestor.session_id)
            return open_file(path, *args, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as workers:
            def confirm(sid):
                confirmation = get_confirmation(sid)
                pending.append(workers.submit(rewrite))
                self.assertTrue(attempted.wait(5))
                with self.assertRaises(FutureTimeoutError):
                    pending[0].result(timeout=0.1)
                return confirmation

            with patch.object(self.storage, "get_session_preservation_confirmation", side_effect=confirm):
                with patch.object(Path, "open", observe_write):
                    self.assertTrue(self.ingestor.release_session("session-a"))
                    pending[0].result(timeout=5)
        self.assertEqual(observed_bindings, [None])
        self.assertEqual(journal.read_bytes(), journal_contents)
        self.assertEqual(self.ingestor.accepted_runtime_evidence, ())

    def test_concurrent_partial_archive_failure_blocks_ingestor_release_and_preserves_intake(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        compiled = self.ingestor.compile_persistent_runtime_evidence()
        messages = self.ingestor.accepted_runtime_evidence
        audits = self.ingestor.runtime_evidence_audit
        journal = self.ingestor.recovery_journal_path
        journal_contents = journal.read_bytes()
        entered, proceed, releasing = Event(), Event(), Event()
        open_file = Path.open

        def fail_audit_write(path, *args, **kwargs):
            if path.name == "ingest_audit.jsonl" and args and args[0] == "w":
                entered.set()
                if not proceed.wait(5):
                    raise TimeoutError("test did not permit partial write failure")
                raise OSError("audit archive unavailable")
            return open_file(path, *args, **kwargs)

        def release():
            releasing.set()
            return self.ingestor.release_session("session-a")

        with ThreadPoolExecutor(max_workers=2) as workers:
            with patch.object(Path, "open", fail_audit_write):
                writing = workers.submit(self.archive, compiled)
                self.assertTrue(entered.wait(5))
                closing = workers.submit(release)
                self.assertTrue(releasing.wait(5))
                proceed.set()
                with self.assertRaises(OSError):
                    writing.result(timeout=5)
                with self.assertRaisesRegex(RuntimeError, "confirmation"):
                    closing.result(timeout=5)
        self.assertEqual(self.ingestor.session_id, "session-a")
        self.assertEqual(self.ingestor.accepted_runtime_evidence, messages)
        self.assertEqual(self.ingestor.runtime_evidence_audit, audits)
        self.assertEqual(journal.read_bytes(), journal_contents)
        self.archive()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_failed_final_record_write_cannot_confirm_release(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        with patch.object(self.storage, "write_session_record", side_effect=OSError("record unavailable")):
            with self.assertRaises(OSError):
                self.write_terminal_record()
        with self.assertRaisesRegex(RuntimeError, "confirmation"):
            self.ingestor.release_session("session-a")
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 1)
        self.write_terminal_record()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_late_nonpersistent_persistent_and_duplicate_intake_require_new_archive(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.finish()
        for message in (self.message("late-temporary", False), self.message("late-persistent"), self.message()):
            with self.subTest(identity=message.evidence_id):
                self.archive()
                self.assertTrue(self.ingestor.receive_runtime_evidence(message).accepted)
                with self.assertRaisesRegex(RuntimeError, "current runtime intake"):
                    self.ingestor.release_session("session-a")
                self.assertEqual(self.ingestor.session_id, "session-a")
        self.archive()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_rejected_intake_audit_also_requires_updated_archive_coverage(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        invalid = RuntimeEvidenceMessage("", "session-a", "observation", "producer", {})
        self.assertFalse(self.ingestor.receive_runtime_evidence(invalid).accepted)
        with self.assertRaisesRegex(RuntimeError, "current runtime intake"):
            self.ingestor.release_session("session-a")
        paths = self.archive()
        audits = [json.loads(line) for line in paths["ingest_audit"].read_text().splitlines()]
        self.assertEqual(len(audits), 2)
        self.assertFalse(audits[-1]["accepted"])
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_acquisition_envelopes_and_audit_stay_on_existing_persistence_path(self):
        envelope = AcquisitionRecordEnvelope("session-a", "device", "stream",
                                            ({"session_time_s": 1.0},), source_node_id="node")
        self.assertTrue(self.ingestor.receive_envelope(envelope).accepted)
        self.archive()
        self.finish()
        stored = self.storage.get_envelopes_for_session("session-a")
        self.assertTrue(self.ingestor.release_session("session-a"))
        self.assertEqual(self.storage.get_envelopes_for_session("session-a"), stored)
        self.assertEqual(self.ingestor.accepted_envelopes, ())
        self.assertEqual(self.ingestor.ingest_audit, ())

    def test_late_acquisition_intake_requires_existing_session_record_refresh(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        envelope = AcquisitionRecordEnvelope("session-a", "device", "stream", ({"session_time_s": 1.0},))
        self.assertTrue(self.ingestor.receive_envelope(envelope).accepted)
        with self.assertRaisesRegex(RuntimeError, "Acquisition-envelope preservation"):
            self.ingestor.release_session("session-a")
        self.write_terminal_record()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_concurrent_accepted_intake_cannot_be_omitted_by_release(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        entered, proceed, releasing = Event(), Event(), Event()
        from lab_sync_acquisition import ingestor as ingestor_module
        fsync = ingestor_module.os.fsync

        def delayed_fsync(descriptor):
            entered.set()
            if not proceed.wait(5):
                raise TimeoutError("test did not permit journal completion")
            fsync(descriptor)

        def release():
            releasing.set()
            return self.ingestor.release_session("session-a")

        with ThreadPoolExecutor(max_workers=2) as workers:
            with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=delayed_fsync):
                intake = workers.submit(self.ingestor.receive_runtime_evidence, self.message("concurrent", False))
                self.assertTrue(entered.wait(5))
                closing = workers.submit(release)
                self.assertTrue(releasing.wait(5))
                proceed.set()
                self.assertTrue(intake.result(timeout=5).accepted)
                with self.assertRaisesRegex(RuntimeError, "current runtime intake"):
                    closing.result(timeout=5)
        self.assertEqual(len(self.ingestor.accepted_runtime_evidence), 2)
        self.archive()
        self.assertTrue(self.ingestor.release_session("session-a"))

    def test_intake_arriving_during_release_is_rejected_after_commit_not_silently_accepted(self):
        self.ingestor.receive_runtime_evidence(self.message())
        self.archive()
        self.finish()
        started = Event()
        confirmation = self.storage.get_session_preservation_confirmation
        pending = []

        def intake():
            started.set()
            return self.ingestor.receive_runtime_evidence(self.message("after-commit"))

        with ThreadPoolExecutor(max_workers=1) as workers:
            def confirm(sid):
                pending.append(workers.submit(intake))
                self.assertTrue(started.wait(5))
                return confirmation(sid)

            with patch.object(self.storage, "get_session_preservation_confirmation", side_effect=confirm):
                self.assertTrue(self.ingestor.release_session("session-a"))
            with self.assertRaisesRegex(RuntimeError, "released"):
                pending[0].result(timeout=5)
        self.assertIsNone(self.ingestor.session_id)

    def mapping_history(self):
        sync = SynchronizationManager()
        sync.prepare_session("session-a")
        sync.start()
        sync.create_and_activate_mapping("session-a", "node", 1.0, 2.0, 1.0, "initial")
        sync.replace_active_mapping("session-a", "node", 3.0, 4.0, 1.0, "replace")
        sync.retire_active_mapping("session-a", "node", "finished")
        return sync

    def test_sync_releases_after_durable_handoff_without_waiting_for_archive(self):
        sync = self.mapping_history()
        messages = [update.to_runtime_evidence_message(str(index), "synchronization")
                    for index, update in enumerate(sync.mapping_update_evidence)]
        for message in messages:
            self.ingestor.receive_runtime_evidence(message)
            self.assertTrue(self.ingestor.has_durable_runtime_evidence(message))
        with self.assertRaisesRegex(RuntimeError, "must stop"):
            sync.release_session("session-a", ingestor=self.ingestor)
        sync.stop()
        journal = self.ingestor.recovery_journal_path.read_bytes()
        self.assertIsNone(self.storage.get_session_preservation_confirmation("session-a"))
        self.assertTrue(sync.release_session("session-a", ingestor=self.ingestor))
        self.assertEqual(sync.mapping_update_evidence, ())
        self.assertEqual(self.ingestor.accepted_runtime_evidence, tuple(messages))
        self.assertEqual(self.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertTrue(sync.prepare_session("session-b").ready)
        sync.start()
        sync.stop()
        self.assertTrue(sync.release_session("session-b"))

    def test_sync_blocks_incomplete_and_memory_only_handoff(self):
        sync = self.mapping_history()
        messages = [update.to_runtime_evidence_message(str(index), "synchronization")
                    for index, update in enumerate(sync.mapping_update_evidence)]
        sync.stop()
        self.ingestor.receive_runtime_evidence(messages[0])
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            sync.release_session("session-a", ingestor=self.ingestor)
        memory_only = InMemoryIngestor()
        for message in messages:
            memory_only.receive_runtime_evidence(message)
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            sync.release_session("session-a", ingestor=memory_only)
        self.assertEqual(len(sync.mapping_update_evidence), 3)
        for message in messages[1:]:
            self.ingestor.receive_runtime_evidence(message)
        self.assertTrue(sync.release_session("session-a", ingestor=self.ingestor))

    def test_sync_keeps_active_mapping_and_uncertain_handoff_blocked(self):
        sync = SynchronizationManager()
        sync.prepare_session("session-a")
        sync.create_and_activate_mapping("session-a", "node", 1.0, 2.0, 1.0, "initial")
        message = sync.mapping_update_evidence[0].to_runtime_evidence_message("mapping", "synchronization")
        self.ingestor.receive_runtime_evidence(message)
        with self.assertRaisesRegex(RuntimeError, "Active mappings"):
            sync.release_session("session-a", ingestor=self.ingestor)
        retired = sync.retire_active_mapping("session-a", "node", "finished")
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("uncertain")):
            with self.assertRaises(OSError):
                self.ingestor.receive_runtime_evidence(retired.to_runtime_evidence_message("retired", "synchronization"))
        self.assertFalse(self.ingestor.has_durable_runtime_evidence(message))
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            sync.release_session("session-a", ingestor=self.ingestor)
        self.assertEqual(len(sync.mapping_update_evidence), 2)
