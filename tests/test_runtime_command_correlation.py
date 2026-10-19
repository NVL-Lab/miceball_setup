"""Public request workflows with controlled, independently delivered owner replies."""

import asyncio
from dataclasses import replace
import json
import unittest

from lab_sync_acquisition import (
    NatsControllerCommunication, RuntimeCommandResultMessage, RuntimeParticipant,
    build_runtime_subject,
)
from tests.test_session_launch import _Boundary, _Broker


class RuntimeCommandCorrelationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.broker = _Broker()
        self.communication = NatsControllerCommunication(_Boundary("controller", "controller", self.broker))
        self.participant = RuntimeParticipant("acquisition_node", "node")
        self.original_publish = self.broker.publish
        self.respond = None

        async def publish(subject, data, stream):
            acknowledgment = await self.original_publish(subject, data, stream)
            if stream == "LAB_COMMANDS" and self.respond is not None:
                await self.respond(json.loads(data))
            return acknowledgment

        self.broker.publish = publish

    async def emit(self, command, *, operation=None, kind="acquisition_node", owner="node", **changes):
        reply = RuntimeCommandResultMessage("result", command["command_id"], command["session_id"],
            "node", "controller", "succeeded", True, None,
            {"request_nonce": command["payload"].get("request_nonce"), "confirmed": True})
        reply = replace(reply, **changes)
        subject = build_runtime_subject(command["session_id"], "command_result", kind, owner,
                                        operation or command["command_type"])
        await self.original_publish(subject, json.dumps(reply.to_dict()).encode(), "LAB_COMMAND_RESULTS")

    async def request(self, *, command_id=None):
        return await self.communication.request_runtime_command(self.participant, "stop_runtime",
            "session", {}, 0.02, command_id=command_id)

    async def test_valid_final_reply_succeeds_and_subscription_is_released(self):
        self.respond = self.emit
        self.assertTrue((await self.request()).success)
        self.assertTrue(all(not subscription.active for subscription in self.broker.subscriptions))

    async def test_scoped_stop_completion_cannot_reuse_a_rejected_attempt(self):
        subscription = await self.communication.subscribe_command_results("session")
        try:
            self.respond = self.emit
            first = await self.request()
            self.assertEqual(self.communication.session_acquisition_completion(self.participant, "session"), first)

            async def wrong_operation(command):
                await self.emit(command, operation="check_readiness")

            self.respond = wrong_operation
            self.assertIsNone(await self.request())
            self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))
            self.respond = self.emit
            retried = await self.request()
            self.assertIsNotNone(retried)
            self.assertEqual(self.communication.session_acquisition_completion(self.participant, "session"), retried)
        finally:
            await subscription.unsubscribe()

    async def test_missing_reply_remains_unconfirmed_and_releases_subscription(self):
        self.assertIsNone(await self.request())
        self.assertTrue(all(not subscription.active for subscription in self.broker.subscriptions))

    async def test_owner_stop_rejection_remains_reportable_without_completion(self):
        async def reject(command):
            await self.emit(command, status="failed", success=False, reason="Device cleanup blocked")

        self.respond = reject
        result = await self.request()
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "Device cleanup blocked")
        self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))

    async def test_pending_retry_cannot_be_confirmed_by_previous_nonce(self):
        subscription = await self.communication.subscribe_command_results("session")
        entered, resume = asyncio.Event(), asyncio.Event()
        pending = None
        commands = []

        async def respond(command):
            commands.append(command)
            if len(commands) == 2:
                entered.set()
                await resume.wait()
            await self.emit(command)

        self.respond = respond
        try:
            self.assertIsNotNone(await self.request(command_id="same-stop"))
            pending = asyncio.create_task(self.request(command_id="same-stop"))
            await asyncio.wait_for(entered.wait(), 1)
            self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))
            await self.emit(commands[0])
            self.assertIsNone(self.communication.session_acquisition_completion(self.participant, "session"))
            resume.set()
            current = await pending
            self.assertIsNotNone(current)
            await self.emit(commands[0], status="failed", success=False, reason="Stale failure")
            self.assertEqual(self.communication.session_acquisition_completion(self.participant, "session"), current)
        finally:
            resume.set()
            if pending is not None:
                await asyncio.gather(pending, return_exceptions=True)
            await subscription.unsubscribe()

    async def test_progress_does_not_hide_a_delayed_final_reply(self):
        async def respond(command):
            await self.emit(command, status="accepted", success=False)

            async def final_reply():
                await asyncio.sleep(0)
                await self.emit(command)

            task = asyncio.create_task(final_reply())

            async def finish():
                await task

            self.addAsyncCleanup(finish)

        self.respond = respond
        self.assertTrue((await self.request()).success)

    async def test_wrong_operation_never_confirms_stop(self):
        async def respond(command):
            await self.emit(command, operation="check_readiness")
        self.respond = respond
        self.assertIsNone(await self.request())

    async def test_wrong_participant_type_never_confirms_stop(self):
        async def respond(command):
            await self.emit(command, kind="storage_manager")
        self.respond = respond
        self.assertIsNone(await self.request())

    async def test_wrong_owner_subject_never_confirms_stop(self):
        async def respond(command):
            await self.emit(command, owner="other-node")
        self.respond = respond
        self.assertIsNone(await self.request())

    async def test_unrelated_replies_do_not_hide_a_later_valid_reply(self):
        async def respond(command):
            await self.emit(command, session_id="other-session")
            await self.emit(command, source_id="other-node")
            await self.emit(command, target_id="other-controller")
            await self.emit(command, command_id="other-command")
            await self.emit(command, payload={"request_nonce": "stale", "confirmed": True})
            await self.emit(command, operation="check_readiness")
            await self.emit(command, kind="storage_manager")
            await self.emit(command)
        self.respond = respond
        self.assertTrue((await self.request()).success)

    async def test_only_stale_or_mismatched_body_replies_remain_unconfirmed(self):
        for mismatch in ({"session_id": "other-session"}, {"source_id": "other-node"},
                         {"target_id": "other-controller"}, {"command_id": "other-command"},
                         {"payload": {"request_nonce": "stale"}}):
            with self.subTest(mismatch=mismatch):
                async def respond(command):
                    await self.emit(command, **mismatch)
                self.respond = respond
                self.assertIsNone(await self.request())

    async def test_contradictory_final_resolutions_are_unconfirmed_in_both_orders(self):
        for failure_first in (False, True):
            with self.subTest(failure_first=failure_first):
                async def respond(command):
                    failure = {"status": "failed", "success": False, "reason": "Owner failure"}
                    for changes in (failure, {}) if failure_first else ({}, failure):
                        await self.emit(command, **changes)
                self.respond = respond
                self.assertIsNone(await self.request())

    async def test_conflicting_success_payloads_are_unconfirmed(self):
        async def respond(command):
            await self.emit(command)
            await self.emit(command, result_id="second", payload={
                "request_nonce": command["payload"]["request_nonce"], "confirmed": False})
        self.respond = respond
        self.assertIsNone(await self.request())

    async def test_identical_duplicates_with_different_delivery_ids_are_valid(self):
        async def respond(command):
            await self.emit(command)
            await self.emit(command, result_id="redelivery")
        self.respond = respond
        self.assertTrue((await self.request()).success)

    async def test_explicit_retry_keeps_command_identity_and_isolates_nonce(self):
        previous = []
        async def respond(command):
            if not previous:
                previous.append(command)
                await self.emit(command)
                await self.emit(command, status="failed", success=False, reason="Conflicting resolution")
            else:
                await self.emit(previous[0])
                await self.emit(command)
        self.respond = respond
        self.assertIsNone(await self.request(command_id="stable-command"))
        self.assertTrue((await self.request(command_id="stable-command")).success)

    async def test_direct_request_rejects_conflicting_resolutions(self):
        subscription = await self.communication.subscribe_command_results("session")
        async def respond(command):
            await self.emit(command)
            await self.emit(command, status="failed", success=False, reason="Owner failure")
        self.respond = respond
        try:
            self.assertIsNone(await self.communication.request_command(self.participant,
                "stop_runtime", "session", {"request_nonce": "attempt"}, 0.02))
        finally:
            await subscription.unsubscribe()
