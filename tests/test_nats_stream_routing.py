import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nats.js.api import ConsumerConfig, StorageType, StreamConfig
from nats.js.errors import APIError
from lab_sync_acquisition import (
    NatsCommunicationBoundary, RuntimeCommandMessage, RuntimeCommandResultMessage,
    RuntimeEvidenceMessage, RuntimeTelemetryMessage, build_runtime_subject,
)
from tests.nats_server_fixture import NATS_SERVER, temporary_jetstream_server


STREAMS = (("LAB_COMMANDS", "command"), ("LAB_COMMAND_RESULTS", "command_result"),
           ("LAB_EVIDENCE", "evidence"))


@unittest.skipUnless(NATS_SERVER, "optional local nats-server unavailable")
class LiveStreamRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_routing_preserves_both_scopes_and_core_telemetry(self):
        async with temporary_jetstream_server() as url:
            boundary = NatsCommunicationBoundary("controller", "controller", (url,))
            await boundary.connect()
            try:
                await boundary.ensure_streams()
                js = boundary._require_jetstream()
                received = []
                subscriptions = []
                for name, kind in STREAMS:
                    info = await js.stream_info(name)
                    self.assertEqual(info.config.subjects, [f"messages.*.{kind}.*.*.*", f"messages.{kind}.*.*.*"])
                    for session in (None, "A", "evidence", "command", "command_result"):
                        message_type = "check_readiness" if kind == "command" else "event"
                        subject = build_runtime_subject(session, kind, "controller", "controller", message_type)
                        subscription = await js.subscribe(subject, stream=name, manual_ack=True)
                        subscriptions.append(subscription)
                        evidence = RuntimeEvidenceMessage(f"{kind}-{session}", session, "event", "controller", {}, True)
                        if kind == "command":
                            await boundary.publish_command(RuntimeCommandMessage(f"cmd-{session}", session, "check_readiness", "controller", "controller", {}), "controller")
                        elif kind == "command_result":
                            await boundary.publish_command_result(RuntimeCommandResultMessage(f"result-{session}", f"cmd-{session}", session, "controller", "controller", "succeeded", True, None, {}), "event")
                        else:
                            await boundary.publish_evidence(evidence)
                        message = await subscription.next_msg(timeout=2)
                        self.assertEqual(message.subject, subject)
                        await message.ack_sync()
                        received.append((name, session))
                self.assertEqual(len(received), 15)
                delivered = asyncio.Future()

                async def telemetry_callback(message):
                    delivered.set_result(json.loads(message.data))

                subject = build_runtime_subject("A", "telemetry", "controller", "controller", "status")
                telemetry = await boundary._require_client().subscribe(subject, cb=telemetry_callback)
                counts = [(await js.stream_info(name)).state.messages for name, _ in STREAMS]
                await boundary.publish_telemetry(RuntimeTelemetryMessage("A", "status", "controller", {}))
                self.assertEqual((await asyncio.wait_for(delivered, 2))["session_id"], "A")
                self.assertEqual([(await js.stream_info(name)).state.messages for name, _ in STREAMS], counts)
                await telemetry.unsubscribe()
                for subscription in subscriptions:
                    await subscription.unsubscribe()
            finally:
                await boundary.close()

    async def test_existing_migration_preserves_messages_consumers_and_unrelated_settings(self):
        async with temporary_jetstream_server() as url:
            boundary = NatsCommunicationBoundary("controller", "controller", (url,))
            await boundary.connect()
            try:
                js = boundary._require_jetstream()
                originals = {}
                for name, kind in STREAMS:
                    info = await js.add_stream(config=StreamConfig(
                        name=name, subjects=[f"messages.*.{kind}.>", f"custom.{name}.>"],
                        storage=StorageType.FILE, description="preserved", max_msgs=100,
                        max_bytes=1000000, duplicate_window=17, deny_delete=True,
                    ))
                    originals[name] = info
                    await js.publish(f"messages.A.{kind}.controller.controller.event", b"original")
                    sub = await js.pull_subscribe(f"messages.A.{kind}.>", durable="preserved", stream=name,
                                                  config=ConsumerConfig())
                    message = (await sub.fetch(1, timeout=2))[0]
                    await message.ack_sync()
                    await sub.unsubscribe()
                consumers = {name: await js.consumer_info(name, "preserved") for name, _ in STREAMS}
                await boundary.ensure_streams()
                for name, kind in STREAMS:
                    info = await js.stream_info(name)
                    self.assertEqual(info.created, originals[name].created)
                    self.assertEqual(replace(info.config, subjects=originals[name].config.subjects), originals[name].config)
                    self.assertEqual((await js.get_msg(name, seq=1)).data, b"original")
                    self.assertEqual((await js.consumer_info(name, "preserved")).ack_floor, consumers[name].ack_floor)
                    self.assertIn(f"custom.{name}.>", info.config.subjects)
                    self.assertEqual((await js.publish(f"messages.{kind}.controller.controller.event", b"new")).stream, name)
                before = {name: (await js.stream_info(name)).config for name, _ in STREAMS}
                await boundary.ensure_streams()
                self.assertEqual({name: (await js.stream_info(name)).config for name, _ in STREAMS}, before)
            finally:
                await boundary.close()

    async def test_conflicting_custom_filter_is_not_silently_removed_or_recreated(self):
        async with temporary_jetstream_server() as url:
            boundary = NatsCommunicationBoundary("controller", "controller", (url,))
            await boundary.connect()
            try:
                js = boundary._require_jetstream()
                original = await js.add_stream(config=StreamConfig(name="LAB_COMMANDS", subjects=["messages.>"], storage=StorageType.FILE))
                await js.publish("messages.A.command.controller.controller.event", b"retain")
                with self.assertRaises(APIError):
                    await boundary.ensure_streams()
                current = await js.stream_info("LAB_COMMANDS")
                self.assertEqual(current.created, original.created)
                self.assertEqual(current.config, original.config)
                self.assertEqual((await js.get_msg("LAB_COMMANDS", seq=1)).data, b"retain")
            finally:
                await boundary.close()
