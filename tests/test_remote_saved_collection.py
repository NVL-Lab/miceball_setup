"""Controller requests saved scientific-artifact collection from a NATS owner."""

import asyncio
import json
import multiprocessing
from pathlib import Path
import unittest
from unittest.mock import patch
from copy import deepcopy

from lab_sync_acquisition import (Controller, InMemoryIngestor, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsStorageManagerCommunication, PersistentStorageManager,
    RuntimeCommandMessage, RuntimeCommandResultMessage, RuntimeParticipant, SshRetrievalEndpoint)
from tests import test_saved_session_selection as selection_fixtures
from tests.test_session_launch import _Boundary, _Broker
from tests import test_artifact_retrieval as retrieval_fixtures
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker


class CollectionBroker(_Broker):
    """Retain authoritative result publications independently of dropped replies."""
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


def run_storage_owner(url, root, files, ready, stop):
    """Run one storage owner with fake SFTP and real NATS in a separate process."""
    async def run():
        boundary = NatsCommunicationBoundary("storage_manager", "storage", servers=[url])
        await boundary.connect()
        try:
            await boundary.ensure_streams()
            storage = PersistentStorageManager(root, global_artifact_root=Path(root) / "global",
                retrieval_endpoints={"node": SshRetrievalEndpoint("fake", "reader")})
            # Preserve the accepted shared-process topology without restoring a Session.
            intake = InMemoryIngestor(storage_manager=storage)
            handler = NatsStorageManagerCommunication(boundary, storage)
            subscriptions = await handler.subscribe_commands()
            transport, _ = retrieval_fixtures.ArtifactRetrievalTests().ssh(retrieval_fixtures.SftpDouble(files))
            with transport:
                ready.send(True)
                await asyncio.to_thread(stop.wait)
            for subscription in subscriptions:
                await subscription.unsubscribe()
        finally:
            await boundary.close()
            ready.close()
    asyncio.run(run())


class RemoteSavedCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.selection = selection_fixtures.SavedSessionSelectionTests()
        self.selection.addCleanup = self.addCleanup
        self.selection.setUp()
        self.fixture = self.selection.fixture
        self.storage = self.selection.storage
        self.broker = CollectionBroker()
        self.controller = Controller()
        self.peer = RuntimeParticipant("storage_manager", "storage")
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.subscriptions = ()
        await self.subscribe(self.storage)

    async def subscribe(self, storage):
        for subscription in self.subscriptions:
            await subscription.unsubscribe()
        self.subscriptions = await NatsStorageManagerCommunication(
            _Boundary("storage_manager", "storage", self.broker), storage).subscribe_commands()
        for subscription in self.subscriptions:
            self.addAsyncCleanup(subscription.unsubscribe)

    async def collect(self, identity="collection", session="session"):
        return await self.controller.collect_saved_session_artifacts_remote(session,
            evidence_id=identity, communication=self.communication,
            storage_participant=self.peer, result_window_s=.02)

    async def test_lost_reply_retry_and_owner_restart_do_not_refetch(self):
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            self.broker.drop_results.add(("storage", "collect_saved_artifacts"))
            lost = await self.collect()
            self.assertFalse(lost.succeeded)
            self.broker.drop_results.clear()
            await self.subscribe(self.fixture.new_storage())
            recovered = await self.collect()
            duplicate = await self.collect()
        self.assertTrue(recovered.succeeded, recovered.error)
        self.assertTrue(duplicate.succeeded, duplicate.error)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        self.assertEqual(recovered.details["collection_outcome"], duplicate.details["collection_outcome"])
        self.assertFalse(recovered.details["collection_outcome"]["archive_closed"])
        self.assertIsNone(self.controller._storage_manager)

    async def test_ineligible_corrupt_and_closed_sessions_do_not_transfer(self):
        before = self.fixture.products()
        self.selection.terminal("session", "stopping")
        self.assertFalse((await self.collect()).succeeded)
        self.selection.terminal("session")
        audit = self.fixture.root / "session_session/evidence/ingest_audit.jsonl"
        original = audit.read_bytes()
        audit.write_bytes(b"invalid")
        self.assertFalse((await self.collect()).succeeded)
        audit.write_bytes(original)
        self.assertEqual(self.fixture.sftp.opened, [])
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            self.assertTrue((await self.collect()).succeeded)
        self.storage.close_session_evidence_archive("session")
        closed = self.fixture.products()
        self.assertFalse((await self.collect()).succeeded)
        self.assertEqual(self.fixture.products(), closed)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        self.assertEqual(before["artifact_collection_handoff.json"], closed["artifact_collection_handoff.json"])

    async def test_collection_failure_reports_durable_outcome_without_false_success(self):
        self.fixture.sftp.files.clear()
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = await self.collect()
        self.assertFalse(result.succeeded)
        outcome = result.details["collection_outcome"]
        self.assertTrue(outcome["archival_confirmed"])
        self.assertFalse(outcome["artifact_collection_result"]["succeeded"])
        self.assertFalse(outcome["archive_closed"])

    async def test_wrong_identity_stale_reply_and_missing_service_remain_unconfirmed(self):
        payload = {"evidence_id": "one"}
        result = await self.communication.request_persistence_command(self.peer, "collect_saved_artifacts",
            "session", payload, .02, command_id="unrelated-command")
        self.assertFalse(result.success)
        self.assertEqual(self.fixture.sftp.opened, [])
        status = await self.communication.request_persistence_command(self.peer,
            "get_saved_session_collection_status", "session", {}, .02, command_id="status")
        self.assertTrue(status.success)
        old = self.broker.results[-1]
        self.selection.terminal("session", "stopping")
        self.broker.change_result = lambda operation, current: old
        self.assertFalse((await self.collect()).succeeded)
        self.broker.change_result = None
        for subscription in self.subscriptions:
            await subscription.unsubscribe()
        self.assertFalse((await self.collect()).succeeded)

    async def test_repeated_overlapping_requests_preserve_one_collection_identity(self):
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            first, second = await asyncio.gather(self.collect(), self.collect())
        self.assertTrue(first.succeeded, first.error)
        self.assertTrue(second.succeeded, second.error)
        self.assertEqual(len(self.fixture.sftp.opened), 1)
        self.assertEqual(first.details["collection_outcome"], second.details["collection_outcome"])

    async def test_owner_revalidates_after_status_before_transfer(self):
        read = self.storage.get_saved_session_collection_status

        def changed(session_id):
            status = read(session_id)
            self.selection.terminal(session_id, "stopping")
            return status

        with patch.object(self.storage, "get_saved_session_collection_status", side_effect=changed):
            result = await self.collect()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.sftp.opened, [])

    async def test_rejected_attempt_stays_rejected_but_explicit_retry_can_collect(self):
        self.selection.terminal("session", "stopping")
        rejected = await self.collect("denied")
        self.assertFalse(rejected.succeeded)
        old = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        self.selection.terminal("session", "completed")
        await self.subscribe(self.fixture.new_storage())
        await self.communication.publish_command(old, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertEqual(self.fixture.sftp.opened, [])
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            self.assertTrue((await self.collect("denied")).succeeded)
            await self.communication.publish_command(old, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_unconfirmed_result_history_blocks_new_collection(self):
        self.broker.result_history.unavailable = True
        result = await self.collect()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.fixture.sftp.opened, [])
        self.broker.result_history.unavailable = False
        self.broker.result_history.records.clear()
        self.assertFalse((await self.collect()).succeeded)
        self.assertEqual(self.fixture.sftp.opened, [])

    async def test_rejected_attempt_survives_failed_reply_publication(self):
        self.selection.terminal("session", "stopping")
        # Fail publication before the result reaches the result stream.
        with patch("tests.test_session_launch._Boundary.publish_command_result",
                   side_effect=ConnectionError("injected reply publication failure")):
            self.assertFalse((await self.collect("unpublished-rejection")).succeeded)
        old = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        self.selection.terminal("session", "completed")
        await self.communication.publish_command(old, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertEqual(self.fixture.sftp.opened, [])

    async def _reject_corrupted_result(self, change):
        self.broker = CollectionBroker()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        await self.subscribe(self.storage)
        self.selection.terminal("session", "stopping")
        self.assertFalse((await self.collect("correlation")).succeeded)
        original = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        record = self.broker.result_history.records[self.broker.result_history.last_sequence]
        data = json.loads(record.data)
        change(data)
        record.data = json.dumps(data).encode()
        corrupted = record.data
        self.selection.terminal("session", "completed")
        before = self.fixture.products()
        await self.subscribe(self.fixture.new_storage())
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            await self.communication.publish_command(original, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertIn("history", self.broker.results[-1]["reason"].lower())
        self.assertEqual(self.fixture.sftp.opened, [])
        self.assertEqual(self.fixture.products(), before)
        self.assertEqual(record.data, corrupted)

    async def test_missing_persisted_nonce_cannot_reactivate_rejected_collection(self):
        await self._reject_corrupted_result(lambda data: data["payload"].pop("request_nonce"))

    async def test_persisted_source_mismatch_cannot_reactivate_rejected_collection(self):
        await self._reject_corrupted_result(lambda data: data.update(source_id="different-owner"))

    async def test_same_nonce_destination_conflict_blocks_rejected_replay(self):
        await self._reject_corrupted_result(lambda data: data.update(target_id="different-controller"))

    async def test_same_nonce_command_conflict_blocks_rejected_replay(self):
        await self._reject_corrupted_result(lambda data: data.update(
            command_id=json.dumps(["session", "different-evidence"], separators=(",", ":"))))

    async def test_same_nonce_conflicts_after_matching_history_block_collection(self):
        self.selection.terminal("session", "stopping")
        self.assertFalse((await self.collect()).succeeded)
        original = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        boundary = _Boundary("storage_manager", "storage", self.broker)
        for evidence_id in ("unrelated-first", "unrelated-second"):
            result = RuntimeCommandResultMessage("unrelated-result", json.dumps(
                ["session", evidence_id], separators=(",", ":")), "session", "storage",
                "controller", "failed", False, "rejected", {"request_nonce": "unrelated-attempt"})
            await boundary.publish_command_result(result, "collect_saved_artifacts")
        history = {seq: record.data for seq, record in self.broker.result_history.records.items()}
        self.selection.terminal("session", "completed")
        before = self.fixture.products()
        await self.subscribe(self.fixture.new_storage())
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            await self.communication.publish_command(original, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertIn("conflicting", self.broker.results[-1]["reason"])
        self.assertEqual(self.fixture.sftp.opened, [])
        self.assertEqual(self.fixture.products(), before)
        for seq, content in history.items():
            self.assertEqual(self.broker.result_history.records[seq].data, content)

    async def test_invalid_result_correlation_blocks_collection(self):
        changes = [
            lambda data: data["payload"].update(request_nonce=None),
            lambda data: data["payload"].update(request_nonce=42),
            lambda data: data["payload"].update(request_nonce=""),
            lambda data: data.pop("target_id"),
            lambda data: data.pop("session_id"),
            lambda data: data.update(target_id=7),
            lambda data: data.update(source_id=None),
            lambda data: data.update(result_id=""),
            lambda data: data.update(command_id=7),
            lambda data: data.update(command_id='["other","correlation"]'),
            lambda data: data.update(session_id="other"),
            lambda data: data.update(success=0),
            lambda data: data.update(status="succeeded"),
            lambda data: data.update(payload=[]),
            lambda data: data.update(reason=42),
            lambda data: data["payload"]["collection_status"].update(session_id="other"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                await self._reject_corrupted_result(change)

    async def test_valid_unrelated_attempts_and_other_sessions_remain_isolated(self):
        boundary = _Boundary("storage_manager", "storage", self.broker)
        for session, requester, evidence_id in (("session", "another-controller", "unrelated"),
                                                ("other", "controller", "collection")):
            result = RuntimeCommandResultMessage("other-result", json.dumps([session, evidence_id], separators=(",", ":")),
                session, "storage", requester, "failed", False, "rejected", {"request_nonce": "other-attempt"})
            await boundary.publish_command_result(result, "collect_saved_artifacts")
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            result = await self.collect()
        self.assertTrue(result.succeeded, result.error)
        self.assertEqual(len(self.fixture.sftp.opened), 1)

    async def test_conflicting_attempt_resolutions_block_collection(self):
        self.selection.terminal("session", "stopping")
        self.assertFalse((await self.collect()).succeeded)
        previous = deepcopy(self.broker.results[-1])
        previous["reason"] = "conflicting resolution"
        await _Boundary("storage_manager", "storage", self.broker).publish_command_result(
            RuntimeCommandResultMessage.from_dict(previous), "collect_saved_artifacts")
        self.selection.terminal("session", "completed")
        await self.communication.publish_command(RuntimeCommandMessage.from_dict(self.broker.commands[-1]), "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertIn("conflicting", self.broker.results[-1]["reason"])
        self.assertEqual(self.fixture.sftp.opened, [])

    async def test_success_result_requires_matching_collection_evidence(self):
        transport, _ = self.fixture.retrieval.ssh(self.fixture.sftp)
        with transport:
            self.assertTrue((await self.collect("confirmed")).succeeded)
        original = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        successful = deepcopy(self.broker.results[-1])
        before = self.fixture.products()
        for field, value in (("evidence_id", "different"), ("session_id", "other"),
                             ("source_id", "other-storage")):
            with self.subTest(field=field):
                self.broker = CollectionBroker()
                self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
                await self.subscribe(self.fixture.new_storage())
                corrupted = deepcopy(successful)
                corrupted["payload"]["collection_outcome"]["collection_evidence"][field] = value
                await _Boundary("storage_manager", "storage", self.broker).publish_command_result(
                    RuntimeCommandResultMessage.from_dict(corrupted), "collect_saved_artifacts")
                await self.communication.publish_command(original, "storage_manager")
                self.assertFalse(self.broker.results[-1]["success"])
                self.assertEqual(len(self.fixture.sftp.opened), 1)
                self.assertEqual(self.fixture.products(), before)

    async def test_cancelled_result_publication_retains_rejection(self):
        self.selection.terminal("session", "stopping")
        entered = asyncio.Event()

        async def pause(*args):
            entered.set()
            await asyncio.Future()

        with patch("tests.test_session_launch._Boundary.publish_command_result", side_effect=pause):
            task = asyncio.create_task(self.collect("cancelled"))
            try:
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        original = RuntimeCommandMessage.from_dict(self.broker.commands[-1])
        self.selection.terminal("session", "completed")
        await self.communication.publish_command(original, "storage_manager")
        self.assertFalse(self.broker.results[-1]["success"])
        self.assertEqual(self.fixture.sftp.opened, [])

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_separate_storage_process_collects_and_retries_after_restart(self):
        await self._separate_process_collection(reject_first=False)

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_rejected_collection_is_not_replayed_after_process_restart(self):
        await self._separate_process_collection(reject_first=True)

    async def _separate_process_collection(self, *, reject_first):
        async with temporary_jetstream_server() as url:
            boundary = NatsCommunicationBoundary("controller", "controller", servers=[url])
            await boundary.connect()
            context = multiprocessing.get_context("spawn")
            workers = []
            try:
                await boundary.ensure_streams()
                self.communication = NatsControllerCommunication(boundary)
                async def start_owner():
                    parent, child = context.Pipe()
                    stop = context.Event()
                    worker = context.Process(target=run_storage_owner,
                        args=(url, self.fixture.root, self.fixture.files, child, stop))
                    worker.start()
                    child.close()
                    workers.append((worker, stop))
                    try:
                        self.assertTrue(await asyncio.to_thread(parent.poll, 15))
                        self.assertTrue(parent.recv())
                    finally:
                        parent.close()
                    return worker, stop
                async def collect_remote():
                    return await self.controller.collect_saved_session_artifacts_remote("session",
                        evidence_id="remote", communication=self.communication,
                        storage_participant=self.peer, result_window_s=3)
                worker, stop = await start_owner()
                if reject_first:
                    self.selection.terminal("session", "stopping")
                    rejected = await collect_remote()
                    self.assertFalse(rejected.succeeded)
                    self.assertFalse((self.fixture.root / "global").exists())
                else:
                    result, duplicate = await asyncio.gather(collect_remote(), collect_remote())
                    self.assertTrue(result.succeeded, result.error)
                    self.assertTrue(duplicate.succeeded, duplicate.error)
                saved = self.fixture.products()
                stop.set()
                await asyncio.to_thread(worker.join, 10)
                self.assertEqual(worker.exitcode, 0)
                if reject_first:
                    self.selection.terminal("session", "completed")
                    saved = self.fixture.products()
                await start_owner()
                if reject_first:
                    # A fresh readback is an ordered processing barrier, not a
                    # new collection request or a timing-dependent sleep.
                    status = await self.communication.request_persistence_command(self.peer,
                        "get_saved_session_collection_status", "session", {}, 3, command_id="status-after-restart")
                    self.assertTrue(status.success, status.reason)
                    self.assertEqual(self.fixture.products(), saved)
                    self.assertFalse((self.fixture.root / "global").exists())
                    old = RuntimeCommandMessage(json.dumps(["session", "remote"], separators=(",", ":")),
                        "session", "collect_saved_artifacts", "controller", "storage",
                        {"evidence_id": "remote", "request_nonce": rejected.details["request_nonce"]})
                    await self.communication.publish_command(old, "storage_manager")
                    barrier = await self.communication.request_persistence_command(self.peer,
                        "get_saved_session_collection_status", "session", {}, 3, command_id="after-redelivery")
                    self.assertTrue(barrier.success, barrier.reason)
                    self.assertEqual(self.fixture.products(), saved)
                    self.assertFalse((self.fixture.root / "global").exists())
                self.assertTrue((await collect_remote()).succeeded)
                if not reject_first:
                    self.assertEqual(self.fixture.products(), saved)
            finally:
                for worker, stop in workers:
                    stop.set()
                    await asyncio.to_thread(worker.join, 10)
                    if worker.is_alive():
                        worker.terminate()
                        await asyncio.to_thread(worker.join, 5)
                    worker.close()
                await boundary.close()
