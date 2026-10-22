"""Failed launch resource cleanup through scoped NATS owner commands."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nats.aio.client import Client
from nats.aio.subscription import Subscription
from nats.js.client import JetStreamContext

from lab_sync_acquisition import AcquisitionNode, RuntimeEvidenceMessage

from tests import test_session_launch as launch


class LaunchCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = launch.SessionLaunchTests()
        self.f.addCleanup = self.addCleanup
        self.f.setUp()

    async def test_invalid_optional_reservation_requires_release_or_retained_cleanup(self):
        for value in ("missing", False, "true"):
            for blocked in (False, True):
                with self.subTest(confirmation=value, cleanup_blocked=blocked):
                    f = launch.SessionLaunchTests()
                    f.addCleanup = self.addCleanup
                    f.setUp()
                    await f.services()
                    node, declaration, _ = await f.node()
                    optional = replace(declaration, required=False)

                    def damage(operation, result):
                        if operation == "reserve":
                            if value == "missing":
                                result["payload"].pop("confirmed", None)
                            else:
                                result["payload"]["confirmed"] = value
                        return result

                    release = node.release_reservation
                    def release_owner(sid):
                        if blocked:
                            raise OSError("resource cleanup unavailable")
                        return release(sid)

                    with patch.object(f.broker, "change_result", new=damage), \
                            patch.object(node, "release_reservation", side_effect=release_owner):
                        result = await f.launch({"node-a": [optional]})
                        if blocked:
                            self.assertFalse(result.succeeded)
                            sid = node.reserved_for_session_id
                            self.assertIsNotNone(sid)
                            before = sum(c["command_type"] == "reserve" for c in f.broker.commands)
                            self.assertFalse((await f.launch({"node-a": [optional]})).succeeded)
                            self.assertEqual(node.reserved_for_session_id, sid)
                            self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), before)
                        else:
                            self.assertTrue(result.succeeded, result.error)
                            self.assertIsNone(node.reserved_for_session_id)
                            self.assertFalse(any(p["component_id"] == "node-a" for p in
                                                 result.details["configuration"]["expected_runtime_participants"]))
                        self.assertTrue(any(c["command_type"] == "release_reservation"
                                            and c["target_id"] == "node-a" for c in f.broker.commands))
                    if blocked:
                        fresh = await f.launch({"node-a": [optional]})
                        self.assertTrue(fresh.succeeded, fresh.error)
                        self.assertNotEqual(fresh.details["session_id"], sid)

    async def sdk_abort_cleanup(self, *, evidence=False, cancellation=False, transport_failure=True):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node(node_class=launch._FailingInitializationNode)
        client = Client()
        client._status = Client.CONNECTED
        client._flush_queue = asyncio.Queue()
        reached = asyncio.Event()

        class Transport:
            broken = transport_failure
            def writelines(self, lines):
                pass
            async def drain(self):
                if self.broken:
                    reached.set()
                    if cancellation:
                        await asyncio.Event().wait()
                    raise ConnectionResetError("Ingestor UNSUB transport interrupted")

        transport = Transport()
        client._transport = transport
        core = Subscription(client, id=505, subject="test.ingestor.evidence")
        core._jsi = SimpleNamespace(_hbtask=None, _fctask=None)
        client._subs[505] = core
        subscription = JetStreamContext.PushSubscription(None, core, "LAB_EVIDENCE", "cleanup-test")
        original = f.broker.publish
        sid = None

        async def install(subject, data, stream):
            nonlocal sid
            result = await original(subject, data, stream)
            command = json.loads(data)
            if (stream == "LAB_COMMANDS" and command["command_type"] == "initialize_session"
                    and command["target_id"] == "ingestor"):
                sid = command["session_id"]
                await f.ingestor_handler._evidence_subscriptions[sid].unsubscribe()
                f.ingestor_handler._evidence_subscriptions[sid] = subscription
                if evidence:
                    f.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage(
                        "preserved-obligation", sid, "observation", "source", {"value": 1}, True))
            return result

        with patch.object(f.broker, "publish", side_effect=install):
            if cancellation:
                task = asyncio.create_task(f.launch({"node-a": [declaration]}))
                await asyncio.wait_for(reached.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                self.assertFalse((await f.launch({"node-a": [declaration]})).succeeded)
        self.assertTrue(subscription._closed)
        self.assertNotIn(505, client._subs)
        if transport_failure:
            self.assertIn(sid, f.ingestor_handler._evidence_subscriptions)
        else:
            self.assertNotIn(sid, f.ingestor_handler._evidence_subscriptions)
        self.assertIsNone(f.controller.get_status()["session_id"])
        journal = f.root / "journals" / ("session_" + sid + ".jsonl")
        before = journal.read_bytes()
        accepted = f.ingestor.accepted_runtime_evidence
        transport.broken = False
        reservations = sum(c["command_type"] == "reserve" for c in f.broker.commands)
        with patch.object(node, "initialize_session", side_effect=lambda *a, **k:
                          AcquisitionNode.initialize_session(node, *a, **k)):
            retry = await f.launch({"node-a": [declaration]})
        self.assertNotIn(sid, f.ingestor_handler._evidence_subscriptions)
        self.assertEqual(journal.read_bytes(), before)
        if evidence:
            self.assertFalse(retry.succeeded)
            self.assertEqual(f.ingestor.session_id, sid)
            self.assertEqual(f.ingestor.accepted_runtime_evidence, accepted)
            self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), reservations)
        else:
            self.assertTrue(retry.succeeded, retry.error)
            self.assertNotEqual(retry.details["session_id"], sid)

    async def test_sdk_ingestor_abort_recovers_after_local_close_and_transport_failure(self):
        await self.sdk_abort_cleanup()

    async def test_sdk_healthy_ingestor_abort_allows_new_session(self):
        await self.sdk_abort_cleanup(transport_failure=False)

    async def test_sdk_ingestor_abort_cancellation_retains_teardown_for_retry(self):
        await self.sdk_abort_cleanup(cancellation=True)

    async def test_sdk_ingestor_abort_preserves_evidence_obligations_after_transport_recovery(self):
        await self.sdk_abort_cleanup(evidence=True)

    async def test_cancelled_reservation_is_cleaned_before_new_session(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        reached = asyncio.Event()
        publish = f.broker.publish

        async def pause(subject, data, stream):
            result = await publish(subject, data, stream)
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "reserve":
                reached.set()
                await asyncio.Event().wait()
            return result

        with patch.object(f.broker, "publish", side_effect=pause):
            task = asyncio.create_task(f.launch({"node-a": [declaration]}))
            await asyncio.wait_for(reached.wait(), 1)
            old = node.reserved_for_session_id
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(node.reserved_for_session_id)
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertNotEqual(launched.details["session_id"], old)

    async def test_unconfirmed_cleanup_blocks_new_reservations_then_recovers(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node(node_class=launch._FailingInitializationNode)
        f.broker.drop_results.add(("node-a", "abort_session_initialization"))
        failed = await f.launch({"node-a": [declaration]})
        self.assertFalse(failed.succeeded)
        reservations = sum(c["command_type"] == "reserve" for c in f.broker.commands)
        blocked = await f.launch({"node-a": [declaration]})
        self.assertFalse(blocked.succeeded)
        self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), reservations)
        f.broker.drop_results.clear()
        # The original failure is not retried as scientific initialization.
        from lab_sync_acquisition import AcquisitionNode
        with patch.object(node, "initialize_session", side_effect=lambda *a, **k:
                          AcquisitionNode.initialize_session(node, *a, **k)):
            launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded, launched.error)
        self.assertNotEqual(launched.details["session_id"], failed.details["session_id"])

    async def test_overlapping_launch_is_rejected_without_reserving(self):
        f = self.f
        await f.services()
        _, declaration, _ = await f.node()
        reached, resume = asyncio.Event(), asyncio.Event()
        publish = f.broker.publish

        async def pause(subject, data, stream):
            if stream == "LAB_COMMANDS" and not reached.is_set():
                reached.set()
                await resume.wait()
            return await publish(subject, data, stream)

        with patch.object(f.broker, "publish", side_effect=pause):
            first = asyncio.create_task(f.launch({"node-a": [declaration]}))
            await asyncio.wait_for(reached.wait(), 1)
            second = await f.launch({"node-a": [declaration]})
            self.assertFalse(second.succeeded)
            self.assertFalse(any(c["command_type"] == "reserve" for c in f.broker.commands))
            resume.set()
            self.assertTrue((await first).succeeded)

    async def test_wrong_operation_cannot_confirm_runtime_start(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        self.assertTrue((await f.launch({"node-a": [declaration]})).succeeded)
        publish = f.broker.publish

        async def redirect(subject, data, stream):
            payload = json.loads(data)
            if stream == "LAB_COMMANDS" and payload["command_type"] == "start_runtime":
                payload["command_type"] = "check_readiness"
                subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                data = json.dumps(payload).encode()
            return await publish(subject, data, stream)

        with patch.object(f.broker, "publish", side_effect=redirect):
            result = await f.controller.start_launched_session()
        self.assertFalse(result.succeeded)
        self.assertFalse(node.status()["is_running"])

    async def test_correlated_wrong_type_stale_and_conflicting_reserve_results(self):
        for fault in ("operation", "participant", "nonce", "conflict"):
            with self.subTest(fault=fault):
                f = launch.SessionLaunchTests()
                f.addCleanup = self.addCleanup
                f.setUp()
                await f.services()
                node, declaration, _ = await f.node()
                publish = f.broker.publish

                async def inject(subject, data, stream):
                    payload = json.loads(data)
                    if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".reserve"):
                        if fault == "operation":
                            subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                        elif fault == "participant":
                            subject = subject.replace(".acquisition_node.", ".ingestor.")
                        elif fault == "nonce":
                            payload["payload"]["request_nonce"] = "stale"
                        else:
                            bad = {**payload, "success": False, "status": "failed", "reason": "contradiction"}
                            await publish(subject, json.dumps(bad).encode(), stream)
                        data = json.dumps(payload).encode()
                    return await publish(subject, data, stream)

                with patch.object(f.broker, "publish", side_effect=inject):
                    result = await f.launch({"node-a": [declaration]})
                self.assertFalse(result.succeeded)
                self.assertFalse(node.status()["is_running"])

    async def test_lost_abort_and_release_replies_are_reconciled(self):
        for operation in ("abort_session_initialization", "release_reservation"):
            with self.subTest(operation=operation):
                f = launch.SessionLaunchTests()
                f.addCleanup = self.addCleanup
                f.setUp()
                await f.services()
                node, declaration, _ = await f.node()
                initialize = node.initialize_session
                f.broker.drop_results.add(("node-a", operation))
                with patch.object(node, "initialize_session", side_effect=OSError("injected preparation failure")):
                    failed = await f.launch({"node-a": [declaration]})
                self.assertFalse(failed.succeeded)
                f.broker.drop_results.clear()
                with patch.object(node, "initialize_session", wraps=initialize) as prepare:
                    fresh = await f.launch({"node-a": [declaration]})
                self.assertTrue(fresh.succeeded, fresh.error)
                self.assertNotEqual(fresh.details["session_id"], failed.details["session_id"])
                self.assertEqual(prepare.call_count, 1)

    async def test_replacement_reservation_is_never_released(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node(node_class=launch._FailingInitializationNode)
        f.broker.drop_results.add(("node-a", "release_reservation"))
        failed = await f.launch({"node-a": [declaration]})
        self.assertFalse(failed.succeeded)
        self.assertIsNone(node.reserved_for_session_id)
        self.assertTrue(node.reserve("unrelated-session"))
        f.broker.drop_results.clear()
        before = sum(c["command_type"] == "reserve" for c in f.broker.commands)
        result = await f.launch({"node-a": [declaration]})
        self.assertFalse(result.succeeded)
        self.assertEqual(node.reserved_for_session_id, "unrelated-session")
        self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), before)

    async def test_cancellation_during_initialization_and_rollback_retains_cleanup(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        initialize_seen, abort_seen = asyncio.Event(), asyncio.Event()
        publish = f.broker.publish

        async def pause(subject, data, stream):
            outcome = await publish(subject, data, stream)
            if stream == "LAB_COMMANDS":
                operation = json.loads(data)["command_type"]
                if operation == "initialize_session" and json.loads(data)["target_id"] == "node-a":
                    initialize_seen.set()
                    await asyncio.Event().wait()
                if operation == "abort_session_initialization":
                    abort_seen.set()
                    await asyncio.Event().wait()
            return outcome

        with patch.object(f.broker, "publish", side_effect=pause):
            task = asyncio.create_task(f.launch({"node-a": [declaration]}))
            await asyncio.wait_for(initialize_seen.wait(), 1)
            old = node.reserved_for_session_id
            task.cancel()
            await asyncio.wait_for(abort_seen.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(f.controller.get_status()["session_id"])
        fresh = await f.launch({"node-a": [declaration]})
        self.assertTrue(fresh.succeeded, fresh.error)
        self.assertNotEqual(fresh.details["session_id"], old)

    async def test_start_cancellation_preserves_launched_failed_session(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded)
        reached = asyncio.Event()
        publish = f.broker.publish

        async def pause(subject, data, stream):
            result = await publish(subject, data, stream)
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "start_runtime":
                reached.set()
                await asyncio.Event().wait()
            return result

        with patch.object(f.broker, "publish", side_effect=pause):
            task = asyncio.create_task(f.controller.start_launched_session())
            await asyncio.wait_for(reached.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        status = f.controller.get_status()
        self.assertEqual(status["session_id"], launched.details["session_id"])
        self.assertEqual(status["session_state"], "failed")
        self.assertFalse(node.status()["is_running"])
        self.assertFalse((await f.launch({"node-a": [declaration]})).succeeded)

    async def test_wrong_operation_rollback_cannot_confirm_cleanup_or_release(self):
        for operation in ("abort_session_initialization", "release_reservation"):
            with self.subTest(operation=operation):
                f = launch.SessionLaunchTests()
                f.addCleanup = self.addCleanup
                f.setUp()
                await f.services()
                node, declaration, _ = await f.node(node_class=launch._FailingInitializationNode)
                publish = f.broker.publish

                async def redirect(subject, data, stream):
                    payload = json.loads(data)
                    if (stream == "LAB_COMMANDS" and payload["target_id"] == "node-a"
                            and payload["command_type"] == operation):
                        payload["command_type"] = "reserve"
                        subject = subject.rsplit(".", 1)[0] + ".reserve"
                        data = json.dumps(payload).encode()
                    return await publish(subject, data, stream)

                with patch.object(f.broker, "publish", side_effect=redirect):
                    failed = await f.launch({"node-a": [declaration]})
                    before = len(f.broker.commands)
                    again = await f.launch({"node-a": [declaration]})
                self.assertFalse(failed.succeeded)
                self.assertFalse(again.succeeded)
                self.assertEqual(node.reserved_for_session_id, failed.details["session_id"])
                if operation == "abort_session_initialization":
                    self.assertFalse(any(c["command_type"] == "release_reservation" and c["target_id"] == "node-a"
                                         for c in f.broker.commands[:before]))
                from lab_sync_acquisition import AcquisitionNode
                with patch.object(node, "initialize_session", side_effect=lambda *a, **k:
                                  AcquisitionNode.initialize_session(node, *a, **k)):
                    # The redirected command consumed the old command ID at its
                    # owner. Its explicit conflict rejection permits a fresh ID
                    # on the following request, not a hidden automatic retry.
                    recovered = await f.launch({"node-a": [declaration]})
                    self.assertFalse(recovered.succeeded)
                    recovered = await f.launch({"node-a": [declaration]})
                self.assertTrue(recovered.succeeded, recovered.error)

    async def test_active_session_rejects_new_launch_without_cleanup(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        launched = await f.launch({"node-a": [declaration]})
        self.assertTrue(launched.succeeded)
        self.assertTrue((await f.controller.start_launched_session()).succeeded)
        commands = len(f.broker.commands)
        rejected = await f.launch({"node-a": [declaration]})
        self.assertFalse(rejected.succeeded)
        self.assertEqual(len(f.broker.commands), commands)
        self.assertTrue(node.status()["is_running"])
        self.assertEqual(f.controller.get_status()["session_id"], launched.details["session_id"])
        self.assertTrue((await f.controller.stop_launched_session()).succeeded)

    async def test_cleanup_in_progress_rejects_competing_new_launch(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()
        f.broker.drop_results.add(("node-a", "abort_session_initialization"))
        with patch.object(node, "initialize_session", side_effect=OSError("preparation failed")):
            self.assertFalse((await f.launch({"node-a": [declaration]})).succeeded)
        f.broker.drop_results.clear()
        reached, resume = asyncio.Event(), asyncio.Event()
        publish = f.broker.publish

        async def pause(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "abort_session_initialization":
                reached.set()
                await resume.wait()
            return await publish(subject, data, stream)

        with patch.object(f.broker, "publish", side_effect=pause):
            recovery = asyncio.create_task(f.launch({"node-a": [declaration]}))
            await asyncio.wait_for(reached.wait(), 1)
            count = sum(c["command_type"] == "reserve" for c in f.broker.commands)
            self.assertFalse((await f.launch({"node-a": [declaration]})).succeeded)
            self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), count)
            resume.set()
            result = await recovery
        self.assertTrue(result.succeeded, result.error)

    async def test_readiness_without_resource_proof_retains_cleanup(self):
        f = self.f
        await f.services()
        node, declaration, _ = await f.node()

        def omit(operation, result):
            if operation == "check_readiness":
                result["payload"].pop("service_diagnostics", None)
            return result

        with patch.object(node, "initialize_session", side_effect=OSError("preparation failed")), \
                patch.object(f.broker, "change_result", new=omit):
            failed = await f.launch({"node-a": [declaration]})
        self.assertFalse(failed.succeeded)
        self.assertIsNone(f.controller.get_status()["session_id"])
        self.assertIn("Unresolved failed-launch resource cleanup", f.controller.maintenance_blockers(None, None))
        before = sum(c["command_type"] == "reserve" for c in f.broker.commands)
        with patch.object(f.broker, "change_result", new=omit):
            rejected = await f.launch({"node-a": [declaration]})
        self.assertFalse(rejected.succeeded)
        self.assertEqual(sum(c["command_type"] == "reserve" for c in f.broker.commands), before)
        self.assertTrue((await f.launch({"node-a": [declaration]})).succeeded)

