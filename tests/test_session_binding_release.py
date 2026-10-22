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

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage, Session, SessionConfig, SynchronizationManager
from tests import test_normal_stop as normal
from tests import test_closeout_attempt_ownership as ownership


class SessionBindingReleaseTests(unittest.IsolatedAsyncioTestCase):
    """Controller release uses the same launched closeout owners as production."""

    async def asyncSetUp(self):
        factory = ownership.InterruptedNormalStopTests()
        factory.addCleanup = self.addCleanup
        factory.addAsyncCleanup = self.addAsyncCleanup
        factory.enterContext = self.enterContext
        self.workflow = await factory.workflow(local_owners=True)
        self.fixture = self.workflow.fixture

    async def release(self):
        return await self.fixture.controller.release_session(
            communication=self.fixture.communication, result_window_s=1)

    async def test_release_requires_confirmed_closeout_and_preserves_scientific_history(self):
        sid = self.workflow.sid
        self.assertFalse((await self.release()).succeeded)
        manifests = tuple(self.fixture.nodes["node-a"].local_storage_manager.manifests)
        self.assertTrue((await self.workflow.stop()).succeeded)
        paths = self.workflow.products()
        self.assertTrue((await self.release()).succeeded)
        self.assertIsNone(self.fixture.controller.get_status()["session_id"])
        self.assertEqual(self.fixture.controller.get_status()["last_released_session"]["session_id"], sid)
        self.assertEqual(self.workflow.products(), paths)
        handoff = self.workflow.storage.read_artifact_collection_handoff(sid)
        self.assertTrue(all(item["artifact_manifest"]["lifecycle_state"] == "finalized"
                            for item in handoff["artifacts"]))
        self.assertTrue(all(Path(m.local_storage_path).is_file() for m in manifests))

    async def test_failed_preservation_retains_binding_and_explicit_retry_can_release(self):
        with patch.object(self.workflow.storage, "write_acquisition_stage", side_effect=OSError("archive unavailable")):
            failed = await self.workflow.stop()
        self.assertFalse(failed.succeeded)
        self.assertFalse((await self.release()).succeeded)
        self.assertEqual(self.fixture.controller.get_status()["session_id"], self.workflow.sid)
        self.assertTrue((await self.workflow.stop()).succeeded)
        self.assertTrue((await self.release()).succeeded)

    async def test_decision_archival_and_corrupt_terminal_record_block_release(self):
        self.fixture.controller.process_health_interpretation(normal.producers.interpretation())
        messages = self.fixture.controller.controller_action_decision_evidence
        self.assertTrue((await self.workflow.stop()).succeeded)
        record = self.fixture.root / f"session_{self.workflow.sid}/session_record_final.json"
        good = record.read_bytes()
        record.write_text("{}", encoding="utf-8")
        self.assertFalse((await self.release()).succeeded)
        self.assertEqual(self.fixture.controller.controller_action_decision_evidence, messages)
        self.assertEqual(self.fixture.controller.get_status()["session_id"], self.workflow.sid)
        record.write_bytes(good)
        self.assertTrue((await self.release()).succeeded)
        archived = self.workflow.storage.get_acquisition_stage_preservation_confirmation(self.workflow.sid)
        self.assertTrue(all(m.to_dict() in archived["runtime_evidence"] for m in messages))

    async def test_unsubscribe_cancellation_retains_binding_and_resumes_without_cleanup_repetition(self):
        self.assertTrue((await self.workflow.stop()).succeeded)
        subscription = self.fixture.controller._launch_subscriptions[0]
        unsubscribe = subscription.unsubscribe
        interrupted = False

        async def cancel_once():
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise asyncio.CancelledError()
            await unsubscribe()

        node = self.fixture.nodes["node-a"]
        with patch.object(subscription, "unsubscribe", side_effect=cancel_once), \
                patch.object(node, "stop_runtime", wraps=node.stop_runtime) as stop:
            with self.assertRaises(asyncio.CancelledError):
                await self.release()
            self.assertEqual(self.fixture.controller.get_status()["session_id"], self.workflow.sid)
            self.assertTrue((await self.release()).succeeded)
        self.assertEqual(stop.call_count, 0)

    async def test_successive_launched_sessions_keep_closed_history(self):
        self.assertTrue((await self.workflow.stop()).succeeded)
        before = self.workflow.products()
        self.assertTrue((await self.release()).succeeded)
        declaration = self.fixture.nodes["node-a"].declared_devices[0]
        self.assertTrue((await self.fixture.launch({"node-a": [declaration]})).succeeded)
        self.assertTrue((await self.fixture.controller.start_launched_session()).succeeded)
        self.assertEqual(self.workflow.products(), before)
        self.assertTrue((await self.fixture.controller.stop_launched_session()).succeeded)


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
        self.storage = PersistentStorageManager(self.root)
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
