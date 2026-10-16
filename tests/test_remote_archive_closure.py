"""Explicit saved-Session archive closure through Controller and NATS owners."""

import asyncio
from copy import deepcopy
import json
import multiprocessing
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (NatsCommunicationBoundary, NatsControllerCommunication,
    RuntimeCommandMessage, RuntimeCommandResultMessage)
from tests import test_remote_saved_collection as remote
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


class RemoteArchiveClosureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.remote = remote.RemoteSavedCollectionTests()
        self.remote.addCleanup = self.addCleanup
        self.remote.addAsyncCleanup = self.addAsyncCleanup
        await self.remote.asyncSetUp()
        self.stage = self.remote.fixture
        self.summary = self.stage.root / "session_session/evidence/compilation_summary.json"

    async def close(self, session="session"):
        return await self.remote.controller.close_saved_session_archive_remote(session,
            communication=self.remote.communication, storage_participant=self.remote.peer,
            result_window_s=.02)

    async def test_explicit_closure_preserves_products_and_does_not_release_services(self):
        transport, _ = self.stage.retrieval.ssh(self.stage.sftp)
        with transport:
            self.assertTrue((await self.remote.collect()).succeeded)
        before = self.stage.products()
        self.assertFalse(json.loads(self.summary.read_bytes())["archive_closed"])
        result = await self.close()
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(result.details["compilation_summary"]["archive_closed"])
        self.assertEqual(before, self.stage.products())
        self.assertEqual(len(self.stage.sftp.opened), 1)
        self.assertTrue(self.remote.storage.check_ready().ready)
        self.assertIsNone(self.remote.controller.get_status()["session_state"])
        self.assertFalse((await self.remote.collect("after-closure")).succeeded)

    async def test_failed_collection_does_not_prevent_verified_closure(self):
        self.stage.sftp.failures.add(self.stage.manifest.local_storage_path)
        transport, _ = self.stage.retrieval.ssh(self.stage.sftp)
        with transport:
            self.assertFalse((await self.remote.collect()).succeeded)
        self.assertTrue((await self.close()).succeeded)

    async def test_missing_and_unresolved_preservation_prevent_closure(self):
        self.assertFalse((await self.close("missing")).succeeded)
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=OSError("interrupted")):
            outcome = self.stage.collect()
        self.assertFalse(outcome["archival_confirmed"])
        before = self.summary.read_bytes()
        self.assertFalse((await self.close()).succeeded)
        self.assertEqual(self.summary.read_bytes(), before)
        restored = self.stage.new_storage()
        recovered, _ = await self.stage.recover(restored)
        self.assertTrue(recovered.success, recovered.reason)
        await self.remote.subscribe(restored)
        self.assertTrue((await self.close()).succeeded)
        self.assertEqual(len(self.stage.sftp.opened), 1)

    async def test_rejected_attempt_remains_rejected_after_prerequisites_recover(self):
        before = self.summary.read_bytes()
        self.summary.unlink()
        self.assertFalse((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        self.summary.write_bytes(before)
        await self.remote.subscribe(self.stage.new_storage())
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), before)
        self.assertTrue((await self.close()).succeeded)

    async def test_lost_reply_restart_and_overlapping_retries_do_not_rewrite_closure(self):
        self.remote.broker.drop_results.add(("storage", "close_session_evidence_archive"))
        self.assertFalse((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        closed = self.summary.read_bytes()
        self.remote.broker.drop_results.clear()
        await self.remote.subscribe(self.stage.new_storage())
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("closure rewritten")):
            await self.remote.communication.publish_command(command, "storage_manager")
            self.assertTrue(self.remote.broker.results[-1]["success"])
            results = await asyncio.gather(self.close(), self.close())
        self.assertTrue(all(result.succeeded for result in results))
        self.assertEqual(self.summary.read_bytes(), closed)
        self.assertEqual(self.stage.sftp.opened, [])

    async def test_closed_history_cannot_substitute_for_current_durable_archive(self):
        self.assertTrue((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        self.summary.write_bytes(b"corrupt")
        await self.remote.subscribe(self.stage.new_storage())
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), b"corrupt")

    async def test_cancelled_result_publication_retains_closure_but_requires_current_readback(self):
        entered = asyncio.Event()

        async def pause(*args):
            entered.set()
            await asyncio.Future()

        with patch("tests.test_session_launch._Boundary.publish_command_result", side_effect=pause):
            task = asyncio.create_task(self.close())
            try:
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        self.assertTrue(json.loads(self.summary.read_bytes())["archive_closed"])
        self.summary.write_bytes(b"corrupt after cancelled publication")
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), b"corrupt after cancelled publication")

    async def test_failed_result_publication_can_retry_without_rewriting_closed_archive(self):
        with patch("tests.test_session_launch._Boundary.publish_command_result", side_effect=ConnectionError("lost")):
            self.assertFalse((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        closed = self.summary.read_bytes()
        with patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("rewritten")):
            await self.remote.communication.publish_command(command, "storage_manager")
        self.assertTrue(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), closed)

    async def test_stale_success_response_cannot_confirm_another_request(self):
        self.assertTrue((await self.close()).succeeded)
        old = deepcopy(self.remote.broker.results[-1])
        self.remote.broker.change_result = lambda operation, current: old
        self.assertFalse((await self.close()).succeeded)

    async def test_success_history_requires_matching_closed_summary(self):
        self.assertTrue((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        record = self.remote.broker.result_history.records[self.remote.broker.result_history.last_sequence]
        data = json.loads(record.data)
        data["payload"]["compilation_summary"]["archive_closed"] = False
        record.data = json.dumps(data).encode()
        corrupt = record.data
        before = self.summary.read_bytes()
        await self.remote.subscribe(self.stage.new_storage())
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), before)
        self.assertEqual(record.data, corrupt)

    async def test_corrupt_attempt_history_blocks_closure_without_repair(self):
        original_summary = self.summary.read_bytes()
        for mutation in (lambda data: data.update(target_id="another-controller"),
                         lambda data: data.update(command_id='["session","other-operation"]'),
                         lambda data: data["payload"].pop("request_nonce"),
                         lambda data: data.update(source_id="another-storage")):
            with self.subTest(mutation=mutation):
                self.remote.broker = remote.CollectionBroker()
                self.remote.communication = NatsControllerCommunication(
                    remote._Boundary("controller", "controller", self.remote.broker))
                await self.remote.subscribe(self.stage.new_storage())
                self.summary.unlink()
                self.assertFalse((await self.close()).succeeded)
                command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
                record = self.remote.broker.result_history.records[self.remote.broker.result_history.last_sequence]
                data = json.loads(record.data)
                mutation(data)
                record.data = json.dumps(data).encode()
                corrupted = record.data
                self.summary.write_bytes(original_summary)
                await self.remote.subscribe(self.stage.new_storage())
                await self.remote.communication.publish_command(command, "storage_manager")
                self.assertFalse(self.remote.broker.results[-1]["success"])
                self.assertEqual(record.data, corrupted)
                self.assertEqual(self.summary.read_bytes(), original_summary)
                self.assertEqual(self.stage.sftp.opened, [])

    async def test_conflicting_tail_blocks_reuse_of_matching_resolution(self):
        self.assertTrue((await self.close()).succeeded)
        command = RuntimeCommandMessage.from_dict(self.remote.broker.commands[-1])
        altered = deepcopy(self.remote.broker.results[-1])
        altered["target_id"] = "other-controller"
        await remote._Boundary("storage_manager", "storage", self.remote.broker).publish_command_result(
            RuntimeCommandResultMessage.from_dict(altered), "close_session_evidence_archive")
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertIn("conflicting", self.remote.broker.results[-1]["reason"])

    async def test_missing_service_and_invalid_closure_request_remain_unconfirmed(self):
        for subscription in self.remote.subscriptions:
            await subscription.unsubscribe()
        self.assertFalse((await self.close()).succeeded)
        await self.remote.subscribe(self.stage.new_storage())
        command = RuntimeCommandMessage("invalid", "session", "close_session_evidence_archive",
            "controller", "storage", {"request_nonce": "bad"})
        before = self.summary.read_bytes()
        await self.remote.communication.publish_command(command, "storage_manager")
        self.assertFalse(self.remote.broker.results[-1]["success"])
        self.assertEqual(self.summary.read_bytes(), before)

    @unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
    async def test_separate_owner_restart_requires_explicit_closure_and_reuses_closed_archive(self):
        async with temporary_jetstream_server() as url:
            boundary = NatsCommunicationBoundary("controller", "controller", servers=[url])
            await boundary.connect()
            context = multiprocessing.get_context("spawn")
            workers = []
            try:
                await boundary.ensure_streams()
                communication = NatsControllerCommunication(boundary)
                async def start():
                    parent, child = context.Pipe()
                    stop = context.Event()
                    worker = context.Process(target=remote.run_storage_owner,
                        args=(url, self.stage.root, self.stage.files, child, stop))
                    worker.start()
                    child.close()
                    workers.append((worker, stop))
                    try:
                        self.assertTrue(await asyncio.to_thread(parent.poll, 15))
                        self.assertTrue(parent.recv())
                    finally:
                        parent.close()
                    return worker, stop
                async def close():
                    return await self.remote.controller.close_saved_session_archive_remote("session",
                        communication=communication, storage_participant=self.remote.peer, result_window_s=3)
                worker, stop = await start()
                saved = self.summary.read_bytes()
                self.summary.unlink()
                rejected = await close()
                self.assertFalse(rejected.succeeded)
                stop.set()
                await asyncio.to_thread(worker.join, 10)
                self.assertEqual(worker.exitcode, 0)
                self.summary.write_bytes(saved)
                worker, stop = await start()
                status = await communication.request_persistence_command(self.remote.peer,
                    "read_session_preservation", "session", {}, 3, command_id="restart-barrier")
                self.assertTrue(status.success, status.reason)
                self.assertEqual(self.summary.read_bytes(), saved)
                old = RuntimeCommandMessage(json.dumps(["session", "close_session_evidence_archive"],
                    separators=(",", ":")), "session", "close_session_evidence_archive", "controller", "storage",
                    {"request_nonce": rejected.details["request_nonce"]})
                await communication.publish_command(old, "storage_manager")
                await communication.request_persistence_command(self.remote.peer,
                    "read_session_preservation", "session", {}, 3, command_id="redelivery-barrier")
                self.assertEqual(self.summary.read_bytes(), saved)
                results = await asyncio.gather(close(), close())
                self.assertTrue(all(result.succeeded for result in results))
                closed = self.summary.read_bytes()
                stop.set()
                await asyncio.to_thread(worker.join, 10)
                self.assertEqual(worker.exitcode, 0)
                await start()
                self.assertTrue((await close()).succeeded)
                self.assertEqual(self.summary.read_bytes(), closed)
                self.assertFalse((self.stage.root / "global").exists())
            finally:
                for worker, stop in workers:
                    stop.set()
                    await asyncio.to_thread(worker.join, 10)
                    if worker.is_alive():
                        worker.terminate()
                        await asyncio.to_thread(worker.join, 5)
                    worker.close()
                await boundary.close()
