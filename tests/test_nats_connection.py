"""Real nats-py handshake and cleanup with simulated stream I/O, not real sockets."""

import asyncio
from collections import deque
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import NatsCommunicationBoundary
from lab_sync_acquisition.installation_communication import verify_node_communication
from tests.test_installation_communication import controller_configuration


class HandshakeReader:
    """Supply a failed/cancelled INFO handshake or a minimal successful NATS exchange."""

    def __init__(self, mode):
        self.mode = mode
        self.lines = deque((b'INFO {"server_id":"test","version":"2.10.0","max_payload":1048576}\r\n', b"PONG\r\n"))
        self.incoming = asyncio.Queue()

    async def readline(self):
        if self.mode == "paused":
            return await self.incoming.get()
        if self.mode == "cancelled":
            raise asyncio.CancelledError("Interrupted while awaiting server INFO")
        if self.mode == "invalid":
            return b"invalid server greeting\r\n"
        return self.lines.popleft()

    async def read(self, size):
        return await self.incoming.get()

    def at_eof(self):
        return False


class HandshakeWriter:
    """Record transport closure and provide server PONGs for post-handshake flushes."""

    def __init__(self, reader):
        self.reader = reader
        self.close_count = 0
        self.wait_closed_count = 0
        self.pings = 0
        self.written = []

    def write(self, content):
        self.written.append(content)
        if b"PING\r\n" in content:
            self.pings += 1
            if self.pings > 1:
                self.reader.incoming.put_nowait(b"PONG\r\n")

    def writelines(self, contents):
        for content in contents:
            self.write(content)

    async def drain(self):
        pass

    def close(self):
        self.close_count += 1

    async def wait_closed(self):
        self.wait_closed_count += 1


class NatsConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mode = "invalid"
        self.writers = []
        self.stream_opened = asyncio.Event()
        self.enterContext(patch("asyncio.open_connection", self.open_stream))
        self.enterContext(patch("nats.aio.client._default_error_callback", AsyncMock()))

    async def open_stream(self, **settings):
        reader = HandshakeReader(self.mode)
        writer = HandshakeWriter(reader)
        self.writers.append(writer)
        self.stream_opened.set()
        return reader, writer

    async def test_task_cancellation_during_info_closes_open_transport(self):
        self.mode = "paused"
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://example:4222",))
        task = asyncio.create_task(boundary.connect())
        try:
            await asyncio.wait_for(self.stream_opened.wait(), 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.writers[0].close_count, 1)
        self.assertEqual(self.writers[0].wait_closed_count, 1)
        self.assertFalse(boundary.connected)

    async def test_cancelled_info_handshake_closes_open_transport(self):
        self.mode = "cancelled"
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://example:4222",))
        with self.assertRaises(asyncio.CancelledError):
            await boundary.connect()
        self.assertEqual(self.writers[0].close_count, 1)
        self.assertEqual(self.writers[0].wait_closed_count, 1)
        self.assertFalse(boundary.connected)
        self.assertFalse(boundary.check_ready().ready)
        await boundary.close()
        self.assertEqual(self.writers[0].close_count, 1)

    async def test_invalid_info_handshake_closes_open_transport(self):
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://example:4222",))
        with self.assertRaisesRegex(ConnectionError, "NATS startup connection failed"):
            await boundary.connect()
        self.assertEqual(self.writers[0].close_count, 1)
        self.assertEqual(self.writers[0].wait_closed_count, 1)
        self.assertFalse(boundary.connected)
        await boundary.close()
        self.assertEqual(self.writers[0].close_count, 1)

    async def test_repeated_verification_attempts_close_each_failed_transport(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        config = controller_configuration(root)
        reports = []
        for mode in ("cancelled", "invalid", "cancelled", "invalid"):
            self.mode = mode
            code = await verify_node_communication(config, "node", report=reports.append)
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(reports[-1])["communication_confirmed"])
            self.assertEqual(json.loads(reports[-1])["outcome"], "FAIL")
        self.assertEqual(len(self.writers), 4)
        self.assertTrue(all(w.close_count == 1 and w.wait_closed_count == 1 for w in self.writers))

    async def test_successful_connection_flushes_and_drains_normally(self):
        self.mode = "connected"
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://example:4222",))
        await boundary.connect()
        try:
            self.assertTrue(boundary.connected)
            self.assertTrue(boundary.check_ready().ready)
            await boundary.flush()
        finally:
            await boundary.close()
        self.assertFalse(boundary.connected)
        self.assertEqual(self.writers[0].close_count, 1)
        self.assertEqual(self.writers[0].wait_closed_count, 1)
        self.assertGreaterEqual(self.writers[0].pings, 3)

    async def test_successful_connection_preserves_options_and_graceful_drain(self):
        client = SimpleNamespace(connect=AsyncMock(), flush=AsyncMock(), drain=AsyncMock(),
            close=AsyncMock(), jetstream=lambda: SimpleNamespace(), is_connected=True, is_closed=False)
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://configured:4222",))
        with patch("lab_sync_acquisition.nats_communication.NATS", return_value=client):
            await boundary.connect()
        self.assertTrue(boundary.check_ready().ready)
        await boundary.flush()
        await boundary.close()
        client.connect.assert_awaited_once_with(servers=["nats://configured:4222"], allow_reconnect=False)
        client.flush.assert_awaited_once()
        client.drain.assert_awaited_once()
        client.close.assert_not_awaited()
        self.assertFalse(boundary.connected)

    async def test_same_boundary_can_connect_after_failed_handshake(self):
        boundary = NatsCommunicationBoundary("terminal", "requester", ("nats://example:4222",))
        with self.assertRaises(ConnectionError):
            await boundary.connect()
        self.mode = "connected"
        await boundary.connect()
        try:
            self.assertTrue(boundary.connected)
        finally:
            await boundary.close()
        self.assertEqual(len(self.writers), 2)
        self.assertTrue(all(w.close_count == 1 and w.wait_closed_count == 1 for w in self.writers))


if __name__ == "__main__":
    unittest.main()
