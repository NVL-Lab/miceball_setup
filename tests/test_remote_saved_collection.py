"""Controller requests saved scientific-artifact collection from a NATS owner."""

import asyncio
import multiprocessing
from pathlib import Path
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (Controller, InMemoryIngestor, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsStorageManagerCommunication, PersistentStorageManager,
    RuntimeParticipant, SshRetrievalEndpoint)
from tests import test_saved_session_selection as selection_fixtures
from tests.test_session_launch import _Boundary, _Broker
from tests import test_artifact_retrieval as retrieval_fixtures
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


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
        self.broker = _Broker()
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

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_separate_storage_process_collects_and_retries_after_restart(self):
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
                result, duplicate = await asyncio.gather(collect_remote(), collect_remote())
                self.assertTrue(result.succeeded, result.error)
                self.assertTrue(duplicate.succeeded, duplicate.error)
                saved = self.fixture.products()
                stop.set()
                await asyncio.to_thread(worker.join, 10)
                self.assertEqual(worker.exitcode, 0)
                await start_owner()
                self.assertTrue((await collect_remote()).succeeded)
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
