"""Operational evidence crosses process boundaries without scientific intake."""

import asyncio
import multiprocessing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab_sync_acquisition import (
    AcquisitionNode, DeviceManager, InMemoryIngestor,
    NatsAcquisitionNodeCommunication, NatsCommunicationBoundary,
    NatsControllerCommunication, NatsIngestorCommunication,
    RuntimeEvidenceMessage, RuntimeParticipant,
)
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server
from tests.test_session_launch import _CollectingAdapter


def run_evidence_receiver(url, journal, ready, stop):
    """Own the journal in a separate process; exchange only NATS messages."""
    async def run():
        boundary = NatsCommunicationBoundary("ingestor", "intake", servers=[url])
        await boundary.connect()
        try:
            await boundary.ensure_streams()
            owner = InMemoryIngestor(session_id="session", recovery_journal_path=journal,
                                     component_id="intake")
            receiver = NatsIngestorCommunication(boundary, owner)
            commands = await receiver.subscribe_commands()
            subscription = await receiver.subscribe_evidence("session")
            ready.send(True)
            try:
                await asyncio.to_thread(stop.wait)
            finally:
                await subscription.unsubscribe()
                for command in commands:
                    await command.unsubscribe()
        finally:
            await boundary.close()
            ready.close()
    asyncio.run(run())


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class OperationalEvidenceTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_publication_retry_and_receiver_restart_preserve_exact_intake(self):
        async with temporary_jetstream_server() as url:
            with tempfile.TemporaryDirectory() as directory:
                journal = Path(directory) / "journal.jsonl"
                boundary = NatsCommunicationBoundary("acquisition_node", "node", servers=[url])
                await boundary.connect()
                workers = []
                context = multiprocessing.get_context("spawn")
                try:
                    await boundary.ensure_streams()
                    adapter = _CollectingAdapter("device", "fake", ("events",), True)
                    node = AcquisitionNode(session_id="session", device_manager=DeviceManager((adapter,)),
                        synchronization_source_id="sync", node_id="node", role="acquisition")
                    producer = NatsAcquisitionNodeCommunication(boundary, node)
                    requester = NatsControllerCommunication(boundary)
                    message = RuntimeEvidenceMessage("health", "session", "acquisition_health", "node", {}, True)
                    publish = boundary.publish_evidence

                    async def lost_reply(evidence):
                        await publish(evidence)
                        raise ConnectionError("injected lost publication confirmation")

                    with patch.object(boundary, "publish_evidence", side_effect=lost_reply):
                        with self.assertRaises(ConnectionError):
                            await producer.publish_evidence(message)
                    await producer.publish_evidence(message)
                    # Publication while intake is offline is not intake confirmation.
                    peer = RuntimeParticipant("ingestor", "intake")
                    self.assertIsNone(await requester.request_persistence_command(peer,
                        "read_runtime_evidence_acceptance", "session", {"evidence": message.to_dict()},
                        .05, command_id="offline"))

                    async def start_receiver():
                        parent, child = context.Pipe()
                        stop = context.Event()
                        worker = context.Process(target=run_evidence_receiver,
                            args=(url, journal, child, stop))
                        worker.start()
                        child.close()
                        workers.append((worker, stop))
                        try:
                            self.assertTrue(await asyncio.to_thread(parent.poll, 15))
                            self.assertTrue(parent.recv())
                        finally:
                            parent.close()
                        return worker, stop

                    async def confirmed():
                        async with asyncio.timeout(5):
                            while True:
                                result = await requester.request_persistence_command(peer,
                                    "read_runtime_evidence_acceptance", "session",
                                    {"evidence": message.to_dict()}, 1, command_id="read-health")
                                if result is not None and result.success:
                                    self.assertTrue(result.payload["durable_acceptance_confirmed"])
                                    return
                                await asyncio.sleep(.01)

                    worker, stop = await start_receiver()
                    await confirmed()
                    stop.set()
                    await asyncio.to_thread(worker.join, 10)
                    self.assertEqual(worker.exitcode, 0)
                    before = journal.read_bytes()
                    await start_receiver()
                    await producer.publish_evidence(message)
                    await confirmed()
                    # Reconstruction may add operational recovery evidence, not science.
                    records = [json.loads(line) for line in journal.read_bytes().splitlines()]
                    self.assertEqual(sum(e["evidence_id"] == "health" for e in records), 1)
                    self.assertTrue(journal.read_bytes().startswith(before))
                    self.assertTrue(all(e["evidence_type"] != "scientific_observation" for e in records))
                finally:
                    for worker, stop in workers:
                        stop.set()
                        await asyncio.to_thread(worker.join, 10)
                        if worker.is_alive():
                            worker.terminate()
                            await asyncio.to_thread(worker.join, 5)
                        worker.close()
                    await boundary.close()
