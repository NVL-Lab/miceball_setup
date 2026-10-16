"""Session closeout with independent Controller, timing, node and intake owners."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lab_sync_acquisition import InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage, RuntimeParticipant
from tests import test_distributed_synchronization as timing
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker
from tests.test_producer_publication_completion import PublicationBroker


class CloseoutBroker(PublicationBroker):
    """Keep evidence receipts and command resolution history independently."""

    def __init__(self):
        super().__init__()
        self.result_history = EvidenceReceiptBroker()

    async def stream_info(self, name):
        if name == "LAB_COMMAND_RESULTS":
            return await self.result_history.stream_info(name)
        return await super().stream_info(name)

    async def get_msg(self, stream, **options):
        if stream == "LAB_COMMAND_RESULTS":
            return await self.result_history.get_msg(stream, **options)
        return await super().get_msg(stream, **options)

    async def publish(self, subject, data, stream):
        if stream == "LAB_COMMAND_RESULTS":
            await self.result_history.publish(subject, data, stream)
        return await super().publish(subject, data, stream)


class DistributedSessionCloseoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = timing.DistributedSynchronizationTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.addAsyncCleanup = self.addAsyncCleanup

        def intake(**configuration):
            self.storage = PersistentStorageManager(Path(configuration["recovery_journal_root"]).parent)
            return InMemoryIngestor(storage_manager=self.storage, **configuration)

        with patch.object(timing, "_Broker", CloseoutBroker), patch.object(timing, "InMemoryIngestor", intake):
            await self.fixture.asyncSetUp()
        self.storage_participant = RuntimeParticipant("storage_manager", "storage")

    async def running(self):
        f = self.fixture
        await f.start()
        topic = f"messages.{f.sid}.evidence.*.*.*"
        self.durable = next(name for name, consumer in f.broker.consumers.items()
                            if consumer.config.filter_subject == topic)
        f.broker.callbacks[self.durable] = next(s.callback for s in f.broker.subscriptions if s.subject == topic)

        async def acknowledge_marker(subject, payload):
            if payload.get("evidence_type") == "acquisition_evidence_completion":
                await self.acknowledge()

        f.broker.after_publication = acknowledge_marker
        await f.experiment()
        self.assertTrue((await f.request(f.participants[-1], "run_one_iteration")).success)

    async def acknowledge(self):
        for sequence in sorted(self.fixture.broker.records):
            await self.fixture.broker.deliver(self.durable, sequence)

    async def stop(self):
        f = self.fixture
        return await f.controller.normal_stop_session(communication=f.communication,
            storage_participant=self.storage_participant, result_window_s=0.05)

    def archive(self):
        return {str(p): p.read_bytes() for p in (self.fixture.root / f"session_{self.fixture.sid}").rglob("*") if p.is_file()}

    async def test_normal_stop_preserves_science_and_releases_independent_services(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(f.controller.get_status()["session_state"], "completed")
        self.assertTrue(result.details["acquisition_preservation_eligible"])
        self.assertFalse(result.details["compilation_summary"]["archive_closed"])
        manifest, = f.node.local_storage_manager.manifests
        self.assertEqual(len(Path(manifest.local_storage_path).read_text().splitlines()), 1)
        before = self.archive()
        self.assertTrue((await self.stop()).succeeded)
        self.assertEqual(self.archive(), before)
        released = await f.controller.release_session(communication=f.communication, result_window_s=0.05)
        self.assertTrue(released.succeeded, released.error)
        self.assertIsNone(f.ingestor.session_id)

    async def test_finalized_intake_discards_late_and_duplicate_delivery_without_audit_changes(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        journal = f.ingestor.recovery_journal_path.read_bytes()
        audit = f.ingestor.runtime_evidence_audit
        evidence = f.ingestor.accepted_runtime_evidence[0]
        late = deepcopy(evidence.to_dict())
        late["evidence_id"] = "late-observation"
        await f.handler._boundary.publish_evidence(evidence)
        await f.handler._boundary.publish_evidence(RuntimeEvidenceMessage.from_dict(late))
        self.assertEqual(f.ingestor.runtime_evidence_audit, audit)
        self.assertEqual(f.ingestor.recovery_journal_path.read_bytes(), journal)
        self.assertEqual(self.archive(), before)

    async def test_restart_verifies_finalized_preservation_without_restoring_a_session(self):
        await self.running()
        f = self.fixture
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)
        before = self.archive()
        storage = PersistentStorageManager(f.root)
        restored = InMemoryIngestor(storage_manager=storage, recovery_journal_root=f.root / "journals")
        saved = restored.read_session_closeout(f.sid)
        self.assertTrue(saved["acquisition_preservation_eligible"])
        self.assertIsNone(restored.session_id)
        bound = InMemoryIngestor(session_id=f.sid, storage_manager=storage,
            recovery_journal_path=f.ingestor.recovery_journal_path)
        self.assertEqual(bound.compile_persistent_runtime_evidence()["ingest_audit"],
                         f.ingestor.compile_persistent_runtime_evidence()["ingest_audit"])
        self.assertTrue(bound.read_session_closeout(f.sid)["preservation_confirmed"])
        self.assertEqual(self.archive(), before)

    async def test_incomplete_receipt_blocks_completion_until_explicit_retry(self):
        await self.running()
        f = self.fixture
        f.broker.after_publication = None
        result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertEqual(f.controller.get_status()["session_state"], "stopping")
        self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
        await self.acknowledge()
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

    async def test_preservation_failure_retains_finality_and_blocks_release(self):
        await self.running()
        f = self.fixture
        with patch.object(self.storage, "write_acquisition_stage", side_effect=OSError("disk unavailable")):
            result = await self.stop()
        self.assertFalse(result.succeeded)
        self.assertIsNotNone(f.ingestor.finalized_acquisition_intake(f.sid))
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        self.assertEqual(f.ingestor.session_id, f.sid)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

    async def test_kill_preserves_partial_evidence_without_confirming_missing_cleanup(self):
        await self.running()
        f = self.fixture
        f.broker.drop_results.add(("node", "stop_runtime"))
        result = await f.controller.kill_session(communication=f.communication,
            storage_participant=self.storage_participant, result_window_s=0.05, operator_authorized=True)
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(f.controller.get_status()["session_state"], "aborted")
        self.assertFalse(result.details["acquisition_preservation_eligible"])
        self.assertFalse(result.details["participant_cleanup_confirmed"])
        self.assertEqual(f.controller._session.experiment_lifecycle_evidence[-1].event_type, "experiment_abort")
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        self.assertEqual(f.node.reserved_for_session_id, f.sid)

    async def test_cancelled_preservation_keeps_binding_and_allows_explicit_retry(self):
        await self.running()
        f = self.fixture
        reached = asyncio.Event()
        release = asyncio.Event()

        async def pause(subject, payload):
            if payload.get("command_type") == "preserve_session_acquisition":
                reached.set()
                await release.wait()

        f.broker.before_publication = pause
        task = asyncio.create_task(self.stop())
        await asyncio.wait_for(reached.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        f.broker.before_publication = None
        self.assertEqual(f.ingestor.session_id, f.sid)
        self.assertFalse(f.controller.finalize_session().succeeded)
        self.assertFalse((await f.controller.release_session(communication=f.communication, result_window_s=0.05)).succeeded)
        result = await self.stop()
        self.assertTrue(result.succeeded, result.error)

