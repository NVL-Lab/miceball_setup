"""Explicit archive closure uses current owner products, not historical broker results."""
import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from tests import test_remote_saved_collection as remote
from tests.nats_server_fixture import NATS_SERVER


@unittest.skipUnless(NATS_SERVER, "isolated nats-server unavailable")
class RemoteArchiveClosureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.remote = remote.RemoteSavedCollectionTests()
        self.remote.addCleanup = self.addCleanup
        self.remote.addAsyncCleanup = self.addAsyncCleanup
        await self.remote.asyncSetUp()
        self.stage = self.remote.fixture
        self.summary = self.stage.root / "session_session/evidence/compilation_summary.json"

    async def close(self, session="session", window=2):
        return await self.remote.controller.close_saved_session_archive_remote(session,
            communication=self.remote.communication, storage_participant=self.remote.peer,
            result_window_s=window)

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

    async def test_missing_or_corrupt_preservation_prevents_closure_without_repair(self):
        self.assertFalse((await self.close("missing")).succeeded)
        self.summary.write_bytes(b"corrupt")
        result = await self.close()
        self.assertFalse(result.succeeded)
        self.assertEqual(self.summary.read_bytes(), b"corrupt")

    async def test_replacement_reads_durable_closure_without_broker_result_history(self):
        self.assertTrue((await self.close()).succeeded)
        before = self.summary.read_bytes()
        await self.remote.subscribe(self.stage.new_storage())
        with patch.object(self.remote.js, "get_msg", side_effect=AssertionError("historical broker result")), \
                patch("lab_sync_acquisition.storage.os.replace", side_effect=AssertionError("closure rewritten")):
            results = await asyncio.gather(self.close(), self.close())
        self.assertTrue(all(result.succeeded for result in results), results)
        self.assertEqual(self.summary.read_bytes(), before)

    async def test_mismatched_reply_is_unconfirmed_but_does_not_undo_owner_completion(self):
        boundary = self.remote.storage_boundary
        original = boundary.publish_command_result
        async def mismatched(result, operation):
            if operation == "close_session_evidence_archive":
                result = replace(result, payload={**result.payload, "request_nonce": "different-request"})
            return await original(result, operation)
        with patch.object(boundary, "publish_command_result", mismatched):
            result = await self.close(window=.2)
        self.assertFalse(result.succeeded)
        self.assertTrue(json.loads(self.summary.read_bytes())["archive_closed"])
        before = self.summary.read_bytes()
        self.assertTrue((await self.close()).succeeded)
        self.assertEqual(self.summary.read_bytes(), before)

    async def test_closed_owner_outcome_cannot_hide_current_physical_corruption(self):
        self.assertTrue((await self.close()).succeeded)
        self.summary.write_bytes(b"corrupt after closure")
        await self.remote.subscribe(self.stage.new_storage())
        self.assertFalse((await self.close()).succeeded)
        self.assertEqual(self.summary.read_bytes(), b"corrupt after closure")
