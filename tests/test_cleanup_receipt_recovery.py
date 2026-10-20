"""Explicit cleanup recovery preserves owner receipts, identities and obligations."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nats.aio.client import Client
from nats.js.manager import JetStreamManager

from lab_sync_acquisition import ControllerActionDecision, NatsControllerCommunication, RuntimeEvidenceMessage, RuntimeParticipant
from tests import test_closeout_attempt_ownership as ownership
from tests.test_closeout_confirmation_integrity import _deliver_result
from tests.test_producer_publication_completion import interpretation
from tests.test_session_launch import _Boundary, _Broker


class StopInvalidationHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_attempts_cannot_revive_after_repeated_supersession(self):
        for scoped in (False, True):
            for same_id in (False, True):
                for pending in (False, True):
                    for mode in ("malformed", "contradiction", "nonfinite"):
                        with self.subTest(scoped=scoped, same_id=same_id, pending=pending, mode=mode):
                            broker = _Broker()
                            communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
                            participant = RuntimeParticipant("acquisition_node", "node")
                            subscription = await communication.subscribe_command_results("session")
                            publish = broker.publish
                            route = "messages.session.command_result.acquisition_node.node.stop_runtime"
                            commands = []
                            good = {}

                            async def invalidate():
                                bad = deepcopy(good)
                                if mode == "malformed":
                                    bad.pop("reason")
                                elif mode == "contradiction":
                                    bad.update(success=False, status="failed", reason="Owner correction")
                                else:
                                    bad["payload"]["diagnostic"] = float("nan")
                                errors, acks = await _deliver_result(subscription.callback, route, json.dumps(bad).encode())
                                self.assertEqual((errors, acks), ([], 1))

                            async def wire(subject, data, stream):
                                ack = await publish(subject, data, stream)
                                if stream == "LAB_COMMANDS":
                                    command = json.loads(data)
                                    commands.append(command)
                                    reply = dict(result_id="reply", command_id=command["command_id"], session_id="session",
                                        source_id="node", target_id="controller", status="succeeded", success=True,
                                        reason=None, payload=command["payload"])
                                    if len(commands) == 1:
                                        good.update(deepcopy(reply))
                                        if pending:
                                            await invalidate()
                                    await publish(route, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")
                                return ack

                            with patch.object(broker, "publish", side_effect=wire):
                                if scoped:
                                    first = await communication.request_runtime_command(participant, "stop_runtime",
                                        "session", {}, .03, command_id="original")
                                else:
                                    first = await communication.request_command(participant, "stop_runtime",
                                        "session", {"request_nonce": "original-nonce"}, .03, command_id="original")
                                self.assertEqual(first is None, pending)
                                if not pending:
                                    await invalidate()
                                original = commands[0]
                                for index in range(3):
                                    fresh = await communication.request_runtime_command(participant, "stop_runtime",
                                        "session", {}, .03, command_id="original" if same_id else f"fresh-{index}")
                                    self.assertIsNotNone(fresh)
                                    replay = await communication.request_command(participant, "stop_runtime", "session",
                                        original["payload"], .03, command_id=original["command_id"])
                                    self.assertIsNone(replay)
                                    self.assertIsNone(communication.session_acquisition_completion(participant, "session"))
                                self.assertIsNotNone(await communication.request_runtime_command(participant,
                                    "stop_runtime", "session", {}, .03))
                            await subscription.unsubscribe()


class CleanupRecoveryWorkflows(unittest.IsolatedAsyncioTestCase):
    async def workflow(self, *, local=False, two=False):
        fixtures = ownership.InterruptedNormalStopTests()
        fixtures.addCleanup = self.addCleanup
        fixtures.addAsyncCleanup = self.addAsyncCleanup
        fixtures.enterContext = self.enterContext
        workflow = await fixtures.workflow(local_owners=local, two=two)
        workflow.fixture.controller._launch_result_window_s = .25
        return workflow, workflow.fixture

    @staticmethod
    def decision(f):
        return ControllerActionDecision("retry-health", f.sid, "experiment", "source", "policy",
            "session_failure", "session_fail", None)

    async def test_disk_closeout_rejects_invalidated_replay_at_preservation_boundaries(self):
        for fatal in (False, True):
            for operation in ("preserve_session_acquisition", "preserve_session_terminal_record"):
                with self.subTest(fatal=fatal, operation=operation):
                    workflow, f = await self.workflow()
                    publish = f.broker.publish
                    saved = {}
                    injected = False
                    participant = RuntimeParticipant("acquisition_node", "node")

                    async def wire(subject, data, stream):
                        nonlocal injected
                        body = json.loads(data)
                        if stream == "LAB_COMMANDS" and subject.endswith(".node.stop_runtime"):
                            saved.setdefault("command", deepcopy(body))
                        if fatal and stream == "LAB_COMMANDS" and subject.endswith(".node.release_reservation"):
                            health = replace(interpretation("fatal-history"), interpretation_label="session_failure")
                            await f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-history", f.sid,
                                "health_interpretation", "node", health.to_dict(), True))
                        ack = await publish(subject, data, stream)
                        if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                            saved.setdefault("result", deepcopy(body))
                            saved.setdefault("subject", subject)
                        if not injected and stream == "LAB_COMMAND_RESULTS" and subject.endswith("." + operation):
                            injected = True
                            bad = deepcopy(saved["result"])
                            bad.pop("reason")
                            parent = next(s for s in f.broker.subscriptions if s.active
                                and s.subject == f"messages.{f.sid}.command_result.*.*.*")
                            self.assertEqual(await _deliver_result(parent.callback, saved["subject"],
                                json.dumps(bad).encode()), ([], 1))
                            fresh = await f.communication.request_runtime_command(participant, "stop_runtime",
                                f.sid, {}, .04, command_id=saved["command"]["command_id"])
                            self.assertIsNotNone(fresh)
                            self.assertIsNone(await f.communication.request_command(participant, "stop_runtime",
                                f.sid, saved["command"]["payload"], .04, command_id=saved["command"]["command_id"]))
                        return ack

                    with patch.object(f.broker, "publish", side_effect=wire), patch.object(
                            f.node, "stop_runtime", wraps=f.node.stop_runtime) as stops:
                        first = await workflow.stop()
                        self.assertTrue(injected)
                        self.assertFalse(first.succeeded)
                        self.assertFalse(first.details["preservation_confirmed"])
                        self.assertEqual(f.controller.get_status()["session_state"], "failed" if fatal else
                            "completed" if operation == "preserve_session_terminal_record" else "stopping")
                        self.assertIsNotNone(f.controller.get_status()["session_id"])
                        journal = f.ingestor.recovery_journal_path.read_bytes()
                        products = {p: data for p, data in workflow.archive().items() if p.endswith(".jsonl")}
                        marker = deepcopy(f.controller._acquisition_marker.to_dict())
                        self.assertIsNotNone(await f.communication.request_runtime_command(participant, "stop_runtime",
                            f.sid, {}, .04, command_id=saved["command"]["command_id"]))
                        final = await workflow.stop()
                        self.assertTrue(final.succeeded, final.error)
                        self.assertEqual(f.controller._acquisition_marker.to_dict(), marker)
                        self.assertEqual(f.ingestor.recovery_journal_path.read_bytes(), journal)
                        self.assertEqual({p: data for p, data in workflow.archive().items() if p.endswith(".jsonl")}, products)
                        self.assertEqual(stops.call_count, 1)

    async def test_health_cleanup_revalidates_receipts_after_another_owner_await(self):
        for mode in ("contradiction", "malformed", "payload"):
            with self.subTest(mode=mode):
                workflow, f = await self.workflow()
                publish = f.broker.publish
                saved = {}

                async def wire(subject, data, stream):
                    body = json.loads(data)
                    if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                        saved.update(subject=subject, body=deepcopy(body))
                    if stream == "LAB_COMMANDS" and subject.endswith(".sync.stop_runtime"):
                        bad = deepcopy(saved["body"])
                        if mode == "malformed":
                            bad.pop("reason")
                        elif mode == "payload":
                            bad["payload"]["changed"] = True
                        else:
                            bad.update(success=False, status="failed", reason="Owner correction")
                        parent = next(s for s in f.broker.subscriptions if s.active
                            and s.subject == f"messages.{f.sid}.command_result.*.*.*")
                        self.assertEqual(await _deliver_result(parent.callback, saved["subject"],
                            json.dumps(bad).encode()), ([], 1))
                    return await publish(subject, data, stream)

                with patch.object(f.broker, "publish", side_effect=wire):
                    result = await f.controller.execute_launched_controller_action_decision(self.decision(f))
                self.assertFalse(result.succeeded)
                self.assertFalse(result.details["cleanup_confirmed"])
                self.assertFalse(result.details["preservation_confirmed"])
                self.assertTrue(result.details["binding_retained"])
                self.assertEqual(f.controller.get_status()["session_state"], "failed")
                self.assertFalse(any(c["command_type"] == "kill" for c in f.broker.commands))

    async def test_health_retry_reuses_lost_or_cancelled_stop_without_physical_reexecution(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                workflow, f = await self.workflow()
                decision = self.decision(f)
                publish = f.broker.publish
                interrupted = False
                entered, resume = asyncio.Event(), asyncio.Event()

                async def wire(subject, data, stream):
                    nonlocal interrupted
                    ack = await publish(subject, data, stream)
                    if cancel and not interrupted and stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                        interrupted = True
                        entered.set()
                        await resume.wait()
                    return ack

                if not cancel:
                    f.broker.drop_results.add(("node", "stop_runtime"))
                with patch.object(f.broker, "publish", side_effect=wire), patch.object(
                        f.node, "stop_runtime", wraps=f.node.stop_runtime) as physical:
                    if cancel:
                        task = asyncio.create_task(f.controller.execute_launched_controller_action_decision(decision))
                        try:
                            await asyncio.wait_for(entered.wait(), 1)
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        finally:
                            resume.set()
                            if not task.done():
                                task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                    else:
                        self.assertFalse((await f.controller.execute_launched_controller_action_decision(decision)).succeeded)
                    f.broker.drop_results.clear()
                    result = await f.controller.execute_launched_controller_action_decision(decision)
                    self.assertTrue(result.succeeded, (result.error, result.details))
                    self.assertTrue(result.details["cleanup_confirmed"])
                    self.assertEqual(physical.call_count, 1)
                    sent = [c for c in f.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "node"]
                    self.assertEqual(len({c["command_id"] for c in sent}), 1)
                    self.assertEqual(len({c["payload"]["request_nonce"] for c in sent}), len(sent))
                    self.assertEqual(f.controller.get_status()["session_state"], "failed")
                    self.assertIsNotNone(f.node.reserved_for_session_id)

    async def test_definitive_stop_failure_allows_new_explicit_normal_health_and_kill_attempts(self):
        for mode in ("normal", "health", "kill"):
            with self.subTest(mode=mode):
                workflow, f = await self.workflow()
                real = f.node.stop_runtime
                attempts = 0

                def fail_once():
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise OSError("Transient cleanup dependency unavailable")
                    return real()

                async def close():
                    if mode == "health":
                        return await f.controller.execute_launched_controller_action_decision(self.decision(f))
                    if mode == "kill":
                        return await f.controller.kill_session(communication=f.communication,
                            storage_participant=workflow.storage_participant, result_window_s=.04, operator_authorized=True)
                    return await workflow.stop()

                with patch.object(f.node, "stop_runtime", side_effect=fail_once):
                    first = await close()
                    self.assertFalse(first.details.get("participant_cleanup_confirmed", False) if mode == "kill" else first.succeeded)
                    self.assertTrue(f.node.status()["is_running"])
                    before = workflow.archive()
                    second = await close()
                    if mode == "kill":
                        # New accepted terminal evidence is not permission to
                        # rewrite a previously preserved partial Kill archive.
                        self.assertFalse(second.succeeded)
                        self.assertFalse(second.details["preservation_confirmed"])
                        self.assertEqual(workflow.archive(), before)
                        self.assertIsNotNone(f.communication.session_acquisition_completion(
                            RuntimeParticipant("acquisition_node", "node"), f.sid))
                    else:
                        self.assertTrue(second.succeeded, second.error)
                    self.assertFalse(f.node.status()["is_running"])
                    self.assertEqual(attempts, 2)
                    sent = [c for c in f.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "node"]
                    self.assertEqual(len({c["command_id"] for c in sent}), 2)
                    self.assertEqual(f.controller.get_status()["session_state"], "aborted" if mode == "kill" else "failed")

    async def test_multi_node_definitive_failure_retains_other_nodes_completed_progress(self):
        workflow, f = await self.workflow(local=True, two=True)
        real = f.nodes["node-b"].stop_runtime
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("Temporary dependent unavailable")
            return real()

        with patch.object(f.nodes["node-b"], "stop_runtime", side_effect=fail_once), patch.object(
                f.nodes["node-a"], "stop_runtime", wraps=f.nodes["node-a"].stop_runtime) as stopped:
            self.assertFalse((await workflow.stop()).succeeded)
            self.assertIsNone(f.nodes["node-a"].reserved_for_session_id)
            second = await workflow.stop()
            self.assertTrue(second.succeeded, second.error)
            self.assertEqual(stopped.call_count, 1)
            self.assertEqual(attempts, 2)
            self.assertEqual(f.controller.get_status()["session_state"], "failed")
            self.assertTrue(workflow.storage.get_acquisition_stage_preservation_confirmation(workflow.sid))

    async def test_definitive_reservation_release_failure_does_not_repeat_stop(self):
        workflow, f = await self.workflow()
        real = f.node.release_reservation
        attempts = 0

        def fail_once(session_id):
            nonlocal attempts
            attempts += 1
            return False if attempts == 1 else real(session_id)

        with patch.object(f.node, "release_reservation", side_effect=fail_once), patch.object(
                f.node, "stop_runtime", wraps=f.node.stop_runtime) as stopped:
            self.assertFalse((await workflow.stop()).succeeded)
            second = await workflow.stop()
            self.assertTrue(second.succeeded, second.error)
            self.assertEqual(stopped.call_count, 1)
            sent = [c for c in f.broker.commands if c["command_type"] == "release_reservation"]
            self.assertEqual(len({c["command_id"] for c in sent}), 2)


class PartialResultSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_sdk_subscription_setup_does_not_accumulate_callbacks(self):
        client = Client()
        client._status = Client.CONNECTED
        client._flush_queue = asyncio.Queue()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", client.jetstream()))
        subscriptions = []
        send = client._send_subscribe

        async def capture(subscription):
            subscriptions.append(subscription)
            await send(subscription)

        async def find(manager, subject):
            return "LAB_COMMAND_RESULTS"

        async def add(manager, stream, config):
            return SimpleNamespace(name="ephemeral", config=config)

        try:
            with patch.object(JetStreamManager, "find_stream_name_by_subject", new=find), patch.object(
                    JetStreamManager, "add_consumer", new=add), patch.object(client, "_send_subscribe", side_effect=capture), \
                    patch.object(client, "_flush_pending", AsyncMock(side_effect=OSError("Simulated flush failure"))) as flush:
                for _ in range(3):
                    with self.assertRaises(OSError):
                        await communication.request_runtime_command(RuntimeParticipant("acquisition_node", "node"),
                            "stop_runtime", "session", {}, .02)
                    self.assertEqual(client._subs, {})
                    self.assertTrue(all(s._wait_for_msgs_task.done() for s in subscriptions))
                    self.assertTrue(client.is_connected)
                    self.assertIsNone(communication.session_acquisition_completion(
                        RuntimeParticipant("acquisition_node", "node"), "session"))
                flush.side_effect = None

                async def respond(command, component_type):
                    body = dict(result_id="recovered", command_id=command.command_id, session_id="session",
                        source_id="node", target_id="controller", status="succeeded", success=True, reason=None,
                        payload={"request_nonce": command.payload["request_nonce"]})
                    for subscription in tuple(client._subs.values()):
                        await subscription._cb(SimpleNamespace(
                            subject="messages.session.command_result.acquisition_node.node.stop_runtime",
                            data=json.dumps(body).encode(), ack=AsyncMock()))

                with patch.object(communication._boundary, "publish_command", side_effect=respond):
                    result = await communication.request_runtime_command(RuntimeParticipant("acquisition_node", "node"),
                        "stop_runtime", "session", {}, .02)
                    self.assertTrue(result.success)
                    self.assertEqual(client._subs, {})
                    self.assertTrue(client.is_connected)
        finally:
            with patch.object(client, "_flush_pending", AsyncMock()):
                await client.close()

    async def test_concurrent_setup_failures_join_cleanup_through_repeated_cancellation(self):
        client = Client()
        client._status = Client.CONNECTED
        client._flush_queue = asyncio.Queue()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", client.jetstream()))
        registered, cleaning, resume = asyncio.Event(), asyncio.Event(), asyncio.Event()
        count = 0
        subscriptions = []
        send = client._send_subscribe
        unsubscribe = client._send_unsubscribe

        async def capture(subscription):
            subscriptions.append(subscription)
            await send(subscription)

        async def flush(*args, **kwargs):
            nonlocal count
            if client._pending[-1].startswith(b"SUB "):
                count += 1
                if count == 2:
                    registered.set()
                await registered.wait()
                raise OSError("Both subscriptions failed after registration")

        async def teardown(*args, **kwargs):
            await unsubscribe(*args, **kwargs)
            cleaning.set()
            await resume.wait()

        async def find(manager, subject):
            return "LAB_COMMAND_RESULTS"

        async def add(manager, stream, config):
            return SimpleNamespace(name="ephemeral", config=config)

        tasks = []
        try:
            with patch.object(JetStreamManager, "find_stream_name_by_subject", new=find), patch.object(
                    JetStreamManager, "add_consumer", new=add), patch.object(client, "_send_subscribe", side_effect=capture), \
                    patch.object(client, "_send_unsubscribe", side_effect=teardown), patch.object(client, "_flush_pending", side_effect=flush):
                for _ in range(2):
                    tasks.append(asyncio.create_task(communication.request_runtime_command(
                        RuntimeParticipant("acquisition_node", "node"), "stop_runtime", "session", {}, .02)))
                await asyncio.wait_for(cleaning.wait(), 1)
                for task in tasks:
                    task.cancel()
                await asyncio.sleep(0)
                for task in tasks:
                    task.cancel()
                resume.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results))
                self.assertEqual(client._subs, {})
                self.assertEqual(len(subscriptions), 2)
                self.assertTrue(all(s._wait_for_msgs_task.done() for s in subscriptions))
                self.assertTrue(client.is_connected)
        finally:
            registered.set()
            resume.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            with patch.object(client, "_flush_pending", AsyncMock()):
                await client.close()

