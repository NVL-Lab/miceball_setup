"""Concurrent Stop receipts and interrupted closeout through public workflows."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import NatsControllerCommunication, RuntimeEvidenceMessage, RuntimeParticipant
from tests.test_closeout_confirmation_integrity import _deliver_result
from tests.test_session_launch import _Boundary, _Broker
from tests.test_producer_publication_completion import interpretation
from tests import test_distributed_session_closeout as remote
from tests import test_normal_stop as local


class ConcurrentStopReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def overlap(self, gate, outcome, same_id, interruption=None):
        broker = _Broker()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
        participant = RuntimeParticipant("acquisition_node", "node")
        subject = "messages.session.command_result.acquisition_node.node.stop_runtime"
        broad = await communication.subscribe_command_results("session")
        publish, subscribe = broker.publish, broker.subscribe
        entered, resume = asyncio.Event(), asyncio.Event()
        commands = []
        scoped = 0
        notified = False

        async def observe(operation, result):
            nonlocal notified
            if gate == "notification" and not notified:
                notified = True
                entered.set()
                await resume.wait()

        communication._boundary._dependency_result_observer = lambda participant, operation: observe

        async def emit(command, mode="success"):
            body = dict(result_id="reply", command_id=command["command_id"], session_id="session",
                source_id="node", target_id="controller", status="succeeded", success=True, reason=None,
                payload={"request_nonce": command["payload"]["request_nonce"]})
            if mode == "rejection":
                body.update(status="failed", success=False, reason="Unconfirmed cleanup")
            await publish(subject, json.dumps(body).encode(), "LAB_COMMAND_RESULTS")
            if mode in {"contradiction", "malformed"}:
                bad = deepcopy(body)
                if mode == "malformed":
                    bad.pop("reason")
                else:
                    bad.update(status="failed", success=False, reason="Contradiction")
                await publish(subject, json.dumps(bad).encode(), "LAB_COMMAND_RESULTS")
            return body

        async def interest(*args, **kwargs):
            nonlocal scoped
            subscription = await subscribe(*args, **kwargs)
            if args[0] == subject:
                scoped += 1
                if scoped == 1:
                    if gate == "subscription":
                        entered.set()
                        await resume.wait()
                    if gate == "unsubscribe":
                        unsubscribe = subscription.unsubscribe

                        async def teardown():
                            await unsubscribe()
                            entered.set()
                            await resume.wait()

                        subscription.unsubscribe = teardown
            return subscription

        async def wire(route, data, stream):
            ack = await publish(route, data, stream)
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                commands.append(command)
                older = command["command_id"] == "old" and len(commands) == 1 and gate != "subscription"
                if older and gate == "publication":
                    entered.set()
                    await resume.wait()
                if older and gate == "waiting":
                    entered.set()
                elif older:
                    await emit(command)
                elif outcome == "cancel":
                    raise asyncio.CancelledError()
                elif outcome != "timeout":
                    await emit(command, outcome)
            return ack

        async def request(identity, window=1):
            return await communication.request_runtime_command(participant, "stop_runtime", "session", {},
                window, command_id=identity)

        with patch.object(broker, "publish", side_effect=wire), patch.object(broker, "subscribe", side_effect=interest):
            older = asyncio.create_task(request("old"))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                if outcome == "cancel":
                    with self.assertRaises(asyncio.CancelledError):
                        await request("old" if same_id else "new", .02)
                    newer = None
                else:
                    newer = await request("old" if same_id else "new", .02)
                if outcome == "success":
                    self.assertIsNotNone(newer)
                    self.assertEqual(newer.command_id, "old" if same_id else "new")
                elif outcome == "rejection":
                    self.assertFalse(newer.success)
                else:
                    self.assertIsNone(newer)
                current = communication.session_acquisition_completion(participant, "session")
                self.assertEqual(current, newer if outcome == "success" else None)
                waiter = older
                if interruption == "timeout":
                    waiter = asyncio.create_task(asyncio.wait_for(older, .01))
                    while not older.cancelling():
                        await asyncio.sleep(0)
                elif interruption == "cancel":
                    older.cancel()
                resume.set()
                if gate == "waiting":
                    await emit(commands[0])
                if interruption is None:
                    self.assertIsNone(await asyncio.wait_for(older, 1))
                else:
                    with self.assertRaises(TimeoutError if interruption == "timeout" else asyncio.CancelledError):
                        await waiter
                self.assertEqual(communication.session_acquisition_completion(participant, "session"), current)
                if len(commands) > 1:
                    self.assertNotEqual(commands[0]["payload"]["request_nonce"], commands[1]["payload"]["request_nonce"])
            finally:
                resume.set()
                if not older.done():
                    older.cancel()
                await asyncio.gather(older, return_exceptions=True)
                await broad.unsubscribe()
        self.assertTrue(all(not sub.active for sub in broker.subscriptions))

    async def test_overlapping_requests_at_each_handover_boundary(self):
        for gate in ("subscription", "publication", "waiting", "notification", "unsubscribe"):
            for outcome in ("success", "contradiction", "malformed", "rejection", "timeout", "cancel"):
                for same_id in (False, True):
                    with self.subTest(gate=gate, outcome=outcome, same_id=same_id):
                        await self.overlap(gate, outcome, same_id)

    async def test_superseded_cancellation_and_timeout_cannot_erase_current_receipt(self):
        for gate in ("subscription", "publication", "waiting", "notification", "unsubscribe"):
            for interruption in ("cancel", "timeout"):
                for same_id in (False, True):
                    with self.subTest(gate=gate, interruption=interruption, same_id=same_id):
                        await self.overlap(gate, "success", same_id, interruption)

    async def test_direct_request_cannot_destroy_newer_receipt_or_return_its_identity(self):
        broker = _Broker()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
        participant = RuntimeParticipant("acquisition_node", "node")
        subscription = await communication.subscribe_command_results("session")
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = broker.publish

        async def wire(subject, data, stream):
            ack = await publish(subject, data, stream)
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                if command["command_id"] == "old":
                    entered.set()
                    await resume.wait()
                body = dict(result_id="reply", command_id=command["command_id"], session_id="session",
                    source_id="node", target_id="controller", status="succeeded", success=True, reason=None,
                    payload=command["payload"])
                await publish("messages.session.command_result.acquisition_node.node.stop_runtime",
                    json.dumps(body).encode(), "LAB_COMMAND_RESULTS")
            return ack

        async def request(identity):
            return await communication.request_command(participant, "stop_runtime", "session",
                {"request_nonce": identity}, .05, command_id=identity)

        with patch.object(broker, "publish", side_effect=wire):
            older = asyncio.create_task(request("old"))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                with self.assertRaises(ValueError):
                    await request("old")
                newer = await request("new")
                resume.set()
                self.assertIsNone(await older)
                self.assertEqual(communication.session_acquisition_completion(participant, "session"), newer)
                self.assertEqual(newer.command_id, "new")
            finally:
                resume.set()
                await asyncio.gather(older, return_exceptions=True)
                await subscription.unsubscribe()

    async def test_pending_parent_veto_survives_asymmetric_delivery_and_duplicate_success(self):
        for mode in ("contradiction", "payload", "malformed", "nan", "infinity"):
            with self.subTest(mode=mode):
                broker = _Broker()
                communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
                participant = RuntimeParticipant("acquisition_node", "node")
                broad = await communication.subscribe_command_results("session")
                publish = broker.publish

                async def wire(subject, data, stream):
                    ack = await publish(subject, data, stream)
                    if stream == "LAB_COMMANDS":
                        command = json.loads(data)
                        good = dict(result_id="reply", command_id=command["command_id"], session_id="session",
                            source_id="node", target_id="controller", status="succeeded", success=True, reason=None,
                            payload=command["payload"])
                        route = "messages.session.command_result.acquisition_node.node.stop_runtime"
                        await publish(route, json.dumps(good).encode(), "LAB_COMMAND_RESULTS")
                        bad = deepcopy(good)
                        if mode == "contradiction":
                            bad.update(status="failed", success=False, reason="Conflicting resolution")
                        elif mode == "payload":
                            bad["payload"]["changed"] = True
                        elif mode == "malformed":
                            bad.pop("reason")
                        else:
                            bad["payload"]["diagnostic"] = float("nan" if mode == "nan" else "inf")
                        errors, acks = await _deliver_result(broad.callback, route, json.dumps(bad).encode())
                        self.assertEqual((errors, acks), ([], 1))
                        await publish(route, json.dumps(good).encode(), "LAB_COMMAND_RESULTS")
                    return ack

                with patch.object(broker, "publish", side_effect=wire):
                    self.assertIsNone(await communication.request_runtime_command(participant, "stop_runtime",
                        "session", {}, .05))
                self.assertIsNone(communication.session_acquisition_completion(participant, "session"))
                await broad.unsubscribe()

    async def test_interrupted_subscription_setup_is_joined_and_removed(self):
        broker = _Broker()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
        entered, resume = asyncio.Event(), asyncio.Event()
        subscribe = broker.subscribe

        async def setup(*args, **kwargs):
            subscription = await subscribe(*args, **kwargs)
            entered.set()
            await resume.wait()
            return subscription

        with patch.object(broker, "subscribe", side_effect=setup):
            task = asyncio.create_task(communication.request_runtime_command(
                RuntimeParticipant("acquisition_node", "node"), "stop_runtime", "session", {}, .05))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            resume.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(broker.commands, [])
        self.assertTrue(all(not subscription.active for subscription in broker.subscriptions))


class InterruptedNormalStopTests(unittest.IsolatedAsyncioTestCase):
    async def workflow(self, *, local_owners=False, two=False):
        workflow = local.NormalStopTests() if local_owners else remote.DistributedSessionCloseoutTests()
        workflow.addCleanup = self.addCleanup
        workflow.addAsyncCleanup = self.addAsyncCleanup
        if local_owners:
            workflow.setUp()
            await workflow.running(two=two)
        else:
            await workflow.asyncSetUp()
            await workflow.running()
        # Validate the public writer's existing-identical-product path. Initial
        # hard-link promotion is independently tested, not simulated as a pass.
        handoff = workflow.storage.write_artifact_collection_handoff

        def existing(session_id, contents):
            path = workflow.storage._artifact_collection_handoff_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(contents, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8")
            return handoff(session_id, contents)

        self.enterContext(patch.object(workflow.storage, "write_artifact_collection_handoff", side_effect=existing))
        return workflow

    async def interrupt(self, operation, *, fatal=False, local_owners=False, two=False, kill=False):
        workflow = await self.workflow(local_owners=local_owners, two=two)
        f = workflow.fixture
        nodes = tuple(f.nodes.values()) if local_owners else (f.node,)
        counts = [self.enterContext(patch.object(n, "stop_runtime", wraps=n.stop_runtime)) for n in nodes]
        subscribe, publish = f.broker.subscribe, f.broker.publish
        entered, resume = asyncio.Event(), asyncio.Event()
        armed = True
        saved = {}

        async def interest(*args, **kwargs):
            nonlocal armed
            subscription = await subscribe(*args, **kwargs)
            if armed and args[0].endswith("." + operation):
                armed = False
                unsubscribe = subscription.unsubscribe

                async def teardown():
                    await unsubscribe()
                    entered.set()
                    await resume.wait()

                subscription.unsubscribe = teardown
            return subscription

        async def wire(subject, data, stream):
            body = json.loads(data)
            fatal_boundary = ".sync.read_session_time" if operation == "read_session_time" else ".node.release_reservation"
            if fatal and stream == "LAB_COMMANDS" and subject.endswith(fatal_boundary):
                health = replace(interpretation("fatal-progress"), interpretation_label="session_failure")
                await f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-progress", f.sid,
                    "health_interpretation", "node", health.to_dict(), True))
            if body.get("evidence_type") == "acquisition_evidence_completion":
                saved.setdefault("marker", body)
                self.assertEqual(saved["marker"], body)
            return await publish(subject, data, stream)

        async def close():
            if kill:
                return await f.controller.kill_session(communication=f.communication,
                    storage_participant=workflow.storage_participant, result_window_s=.05, operator_authorized=True)
            return await workflow.stop()

        with patch.object(f.broker, "subscribe", side_effect=interest), patch.object(f.broker, "publish", side_effect=wire):
            stopped = asyncio.create_task(close())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                stopped.cancel()
                await asyncio.sleep(0)
                stopped.cancel()
                resume.set()
                with self.assertRaises(asyncio.CancelledError):
                    await stopped
                self.assertIsNotNone(f.controller.get_status()["session_id"])
                result = await close()
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(f.controller.get_status()["session_state"],
                    "aborted" if kill else "completed")
                confirmation = workflow.storage.get_session_preservation_confirmation(workflow.sid if local_owners else f.sid)
                self.assertIsNotNone(confirmation)
                if not kill:
                    self.assertTrue(confirmation["compilation_summary"]["stage_a_complete"])
                before = workflow.products() if local_owners else workflow.archive()
                self.assertTrue((await close()).succeeded)
                self.assertEqual(workflow.products() if local_owners else workflow.archive(), before)
            finally:
                resume.set()
                if not stopped.done():
                    stopped.cancel()
                await asyncio.gather(stopped, return_exceptions=True)
        for count in counts:
            self.assertEqual(count.call_count, 1)
        for node in nodes:
            if not kill:
                self.assertIsNone(node.reserved_for_session_id)
            for op in (("stop_runtime",) if kill else ("stop_runtime", "release_reservation")):
                commands = [c for c in f.broker.commands if c["command_type"] == op and c["target_id"] == node.node_id]
                self.assertEqual(len({c["command_id"] for c in commands}), 1)
                self.assertEqual(len({c["payload"]["request_nonce"] for c in commands}), len(commands))
        self.assertFalse(any(c["command_type"] == "kill" for c in f.broker.commands))

    async def test_cancelled_normal_stop_retries_each_completed_cleanup_boundary(self):
        for operation in ("stop_runtime", "release_reservation", "read_session_time"):
            for fatal in (False, True):
                with self.subTest(operation=operation, fatal=fatal):
                    await self.interrupt(operation, fatal=fatal)

    async def test_local_two_node_closeout_retains_partial_release_progress(self):
        await self.interrupt("release_reservation", local_owners=True, two=True)

    async def test_kill_cancellation_preserves_stable_identity_and_partial_preservation(self):
        await self.interrupt("stop_runtime", kill=True)

    async def test_lost_node_stop_or_release_reply_retries_stable_owner_command(self):
        for operation in ("stop_runtime", "release_reservation"):
            with self.subTest(operation=operation):
                workflow = await self.workflow(local_owners=True, two=True)
                f = workflow.fixture
                counts = {name: self.enterContext(patch.object(node, "stop_runtime", wraps=node.stop_runtime))
                    for name, node in f.nodes.items()}
                f.broker.drop_results.add(("node-b", operation))
                first = await workflow.stop()
                self.assertFalse(first.succeeded)
                self.assertIsNone(f.nodes["node-a"].reserved_for_session_id)
                self.assertEqual(f.controller.get_status()["session_state"], "failed")
                self.assertIsNone(f.ingestor.finalized_acquisition_intake(workflow.sid))
                f.broker.drop_results.clear()
                result = await workflow.stop()
                self.assertTrue(result.succeeded, result.error)
                self.assertEqual(f.controller.get_status()["session_state"], "failed")
                for name, count in counts.items():
                    self.assertEqual(count.call_count, 1)
                    for op in ("stop_runtime", "release_reservation"):
                        sent = [c for c in f.broker.commands if c["target_id"] == name and c["command_type"] == op]
                        self.assertEqual(len({c["command_id"] for c in sent}), 1)
                        self.assertEqual(len({c["payload"]["request_nonce"] for c in sent}), len(sent))

    async def test_pending_conflict_blocks_disk_closeout_and_kill_cleanup_confirmation(self):
        for kill, fatal in ((False, False), (False, True), (True, False)):
            for mode in ("contradiction", "payload", "malformed", "nonfinite"):
                with self.subTest(kill=kill, fatal=fatal, mode=mode):
                    workflow = await self.workflow()
                    f = workflow.fixture
                    publish = f.broker.publish
                    injected = False
                    saved = {}
                    stop = self.enterContext(patch.object(f.node, "stop_runtime", wraps=f.node.stop_runtime))

                    async def wire(subject, data, stream):
                        nonlocal injected
                        if fatal and stream == "LAB_COMMANDS" and subject.endswith(".node.release_reservation"):
                            health = replace(interpretation("fatal-pending"), interpretation_label="session_failure")
                            await f.handler.publish_evidence(RuntimeEvidenceMessage("fatal-pending", f.sid,
                                "health_interpretation", "node", health.to_dict(), True))
                        ack = await publish(subject, data, stream)
                        if not injected and stream == "LAB_COMMAND_RESULTS" and subject.endswith(".sync.stop_runtime"):
                            injected = True
                            good = json.loads(data)
                            saved.update(body=good, subject=subject)
                            bad = deepcopy(good)
                            if mode == "contradiction":
                                bad.update(status="failed", success=False, reason="Conflicting pending proof")
                            elif mode == "payload":
                                bad["payload"]["extra"] = True
                            elif mode == "malformed":
                                bad.pop("reason")
                            else:
                                bad["payload"]["extra"] = float("nan")
                            broad = next(s for s in f.broker.subscriptions if s.active
                                and s.subject == f"messages.{f.sid}.command_result.*.*.*")
                            errors, acks = await _deliver_result(broad.callback, subject, json.dumps(bad).encode())
                            self.assertEqual((errors, acks), ([], 1))
                        return ack

                    async def close():
                        if kill:
                            return await f.controller.kill_session(communication=f.communication,
                                storage_participant=workflow.storage_participant, result_window_s=.05,
                                operator_authorized=True)
                        return await workflow.stop()

                    with patch.object(f.broker, "publish", side_effect=wire):
                        result = await close()
                        if kill:
                            self.assertTrue(result.succeeded, result.error)
                            self.assertTrue(result.details["preservation_confirmed"])
                            self.assertFalse(result.details["participant_cleanup_confirmed"])
                        else:
                            self.assertFalse(result.succeeded)
                            self.assertFalse(result.details.get("preservation_confirmed", False))
                        self.assertEqual(f.controller.get_status()["session_state"],
                            "aborted" if kill else "stopping")
                        self.assertIsNotNone(f.controller.get_status()["session_id"])
                        self.assertIsNone(f.communication.session_acquisition_completion(
                            RuntimeParticipant("synchronization_manager", "sync"), f.sid))
                        if not kill:
                            self.assertIsNone(f.ingestor.finalized_acquisition_intake(f.sid))
                        self.assertTrue((await close()).succeeded)
                    self.assertEqual(stop.call_count, 1)

