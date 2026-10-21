"""Scientific owner proof and exact health-input replay across closeout."""

import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import RuntimeEvidenceMessage
from tests import test_local_closeout_ownership as local
from tests import test_health_closeout_accounting as remote
from tests.test_producer_publication_completion import interpretation


class ScientificFinalizationProofTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = local.LocalCloseoutOwnershipTests()
        self.owner.addCleanup = self.addCleanup
        self.owner.addAsyncCleanup = self.addAsyncCleanup
        await self.owner.asyncSetUp()
        self.owner.resume.set()
        self.controller = self.owner.controller
        self.node = self.owner.node
        started = self.owner.start_experiment()
        self.assertTrue(started.succeeded, started.error)
        self.node.run_one_iteration()

    def decisions(self):
        return [self.controller.process_health_interpretation(replace(
            interpretation(identity), interpretation_label="experiment_failure"))
            for identity in ("first", "second")]

    async def test_failed_finalization_cannot_be_confirmed_by_replay_or_second_decision(self):
        first, second = self.decisions()
        manager = self.node.local_storage_manager
        with patch.object(manager, "finalize_stream", side_effect=OSError("disk unavailable")) as finalize:
            for decision in (first, first, second):
                result = self.controller.execute_controller_action_decision(decision)
                self.assertFalse(result.succeeded, result.details)
                self.assertFalse((result.details or {}).get("health_processing_confirmed", False))
                self.assertTrue(any(m.lifecycle_state == "open" for m in manager.manifests))
            self.assertGreaterEqual(finalize.call_count, 3)
        for decision in (second, first):
            result = self.controller.execute_controller_action_decision(decision)
            self.assertTrue(result.succeeded, result.error)
            self.assertTrue(result.details["health_processing_confirmed"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in manager.manifests))
        events = self.controller.get_status()["experiment_lifecycle_evidence"]
        self.assertEqual([e.event_type for e in events], ["experiment_start", "experiment_fail"])
        self.assertEqual(self.controller.get_status()["session_state"], "running")

    async def test_confirmed_finalization_does_not_repeat_disk_finalization(self):
        first, second = self.decisions()
        manager = self.node.local_storage_manager
        self.assertTrue(self.controller.execute_controller_action_decision(first).succeeded)
        with patch.object(manager, "flush", wraps=manager.flush) as flush:
            for decision in (first, second):
                result = self.controller.execute_controller_action_decision(decision)
                self.assertTrue(result.succeeded, result.error)
            flush.assert_not_called()
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in manager.manifests))

    async def test_launched_accounting_cannot_bypass_failed_local_finalization(self):
        first, second = self.decisions()
        with patch.object(self.node.local_storage_manager, "finalize_stream",
                          side_effect=OSError("disk unavailable")):
            self.assertFalse(self.controller.execute_controller_action_decision(first).succeeded)
            result = await self.controller.execute_launched_controller_action_decision(second)
            self.assertFalse(result.succeeded)
            self.assertTrue(any(m.lifecycle_state == "open" for m in self.node.local_storage_manager.manifests))
        result = await self.controller.execute_launched_controller_action_decision(second)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.node.local_storage_manager.manifests))

    async def test_interrupted_scientific_finalization_retains_obligation_for_retry(self):
        first, second = self.decisions()
        with patch.object(self.node.local_storage_manager, "finalize_stream", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                self.controller.execute_controller_action_decision(first)
        self.assertTrue(any(m.lifecycle_state == "open" for m in self.node.local_storage_manager.manifests))
        result = self.controller.execute_controller_action_decision(second)
        self.assertTrue(result.succeeded, result.error)
        result = self.controller.execute_controller_action_decision(first)
        self.assertTrue(result.succeeded, result.error)
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.node.local_storage_manager.manifests))
        self.assertEqual([e.event_type for e in self.controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])

    async def test_normal_stop_cannot_preserve_unfinished_scientific_products(self):
        first, _ = self.decisions()
        with patch.object(self.node.local_storage_manager, "finalize_stream",
                          side_effect=OSError("disk unavailable")):
            self.assertFalse(self.controller.execute_controller_action_decision(first).succeeded)
            result = await self.owner.workflow.stop()
            self.assertFalse(result.succeeded)
            self.assertIsNotNone(self.controller.get_status()["session_id"])
            self.assertTrue(any(m.lifecycle_state == "open" for m in self.node.local_storage_manager.manifests))
            release = await self.controller.release_session(communication=self.owner.f.communication,
                                                            result_window_s=.05)
            self.assertFalse(release.succeeded)
            self.assertIsNotNone(self.controller.get_status()["session_id"])


class HealthInputIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = remote.HealthCloseoutAccountingTests()
        self.owner.addCleanup = self.addCleanup
        self.owner.addAsyncCleanup = self.addAsyncCleanup
        await self.owner.asyncSetUp()
        self.f = self.owner.f

    async def test_new_envelope_cannot_impersonate_processed_input_after_completion(self):
        callback, message = self.owner.delivery("original")
        # Normal Stop owns cleanup, so this fatal input is independently accounted
        # without changing completion semantics or taking over physical cleanup.
        entered = asyncio.Event()
        resume = asyncio.Event()
        request = self.f.communication.request_runtime_command

        async def pause(participant, operation, *args, **kwargs):
            if participant.component_type == "acquisition_node" and operation == "stop_runtime":
                entered.set()
                await resume.wait()
            return await request(participant, operation, *args, **kwargs)

        with patch.object(self.f.communication, "request_runtime_command", new=pause):
            closing = asyncio.create_task(self.owner.workflow.stop())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await callback(message)
            finally:
                resume.set()
                result = await closing
        self.assertTrue(result.succeeded, result.error)
        archive = self.owner.workflow.archive()
        await callback(message)
        for change in ("identity", "details", "time", "source"):
            with self.subTest(change=change):
                _, late = self.owner.delivery("original")
                body = json.loads(late.data)
                if change == "identity":
                    body["evidence_id"] = "new-envelope"
                elif change == "details":
                    body["payload"]["details"] = {"different": "diagnostic"}
                    body["evidence_id"] = "changed-diagnostic"
                elif change == "time":
                    body["payload"]["session_time_s"] = 9.0
                    body["evidence_id"] = "changed-time"
                else:
                    body["source_id"] = "unregistered"
                late.data = json.dumps(body).encode()
                with self.assertRaises((RuntimeError, ValueError)):
                    await callback(late)
                late.ack.assert_not_awaited()
        self.assertEqual(len(self.f.controller.controller_action_decision_evidence), 1)
        self.assertEqual(archive, self.owner.workflow.archive())

    async def test_exact_direct_envelope_is_replayed_after_cutoff_without_new_decision(self):
        callback, message = self.owner.delivery("delayed")
        controller = self.f.controller
        envelope = RuntimeEvidenceMessage.from_dict(json.loads(message.data))
        decision = controller.process_health_interpretation(envelope)
        with patch.object(controller, "_current_session_time_s", side_effect=RuntimeError("clock unavailable")):
            self.assertEqual(controller.process_health_interpretation(envelope), decision)
        stopped = await self.owner.workflow.stop()
        self.assertFalse(stopped.succeeded)
        self.assertIn("require durable accounting", stopped.error)
        await callback(message)
        await callback(message)
        self.assertEqual(message.ack.await_count, 2)
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)
        retained, = controller.controller_action_decision_evidence
        self.assertEqual(retained.payload["details"]["interpretation"], envelope.to_dict())
        self.assertTrue(self.f.ingestor.has_durable_runtime_evidence(retained))

    async def test_payload_only_acceptance_cannot_vouch_for_new_transport_identity(self):
        callback, message = self.owner.delivery("unbound")
        payload = RuntimeEvidenceMessage.from_dict(json.loads(message.data)).payload
        from lab_sync_acquisition import HealthInterpretationEvidence
        self.f.controller.process_health_interpretation(HealthInterpretationEvidence.from_dict(payload))
        stopped = await self.owner.workflow.stop()
        self.assertFalse(stopped.succeeded)
        with self.assertRaises(ValueError):
            await callback(message)
        message.ack.assert_not_awaited()

    async def test_timing_replay_uses_exact_envelope_and_cannot_alias_after_cutoff(self):
        controller = self.f.controller
        evidence = RuntimeEvidenceMessage("timing-original", self.f.sid, "timing_quality_interpretation",
            "node", {"experiment_id": "experiment", "interpretation_label": "warning",
                     "details": {"uncertainty": 1}}, True)
        decision = controller.process_timing_quality_interpretation(evidence)
        self.assertEqual(controller.process_timing_quality_interpretation(evidence), decision)
        self.assertTrue((await self.owner.workflow.stop()).succeeded)
        self.assertEqual(controller.process_timing_quality_interpretation(evidence), decision)
        for changed in (replace(evidence, payload={**evidence.payload, "details": {"uncertainty": 2}}),
                        replace(evidence, evidence_id="new-timing")):
            with self.assertRaises((ValueError, RuntimeError)):
                controller.process_timing_quality_interpretation(changed)

    async def test_remote_finalization_failure_is_retried_before_canonical_termination(self):
        controller = self.f.controller
        decisions = [controller.process_health_interpretation(replace(interpretation(identity),
            interpretation_label="experiment_failure")) for identity in ("first", "second")]
        with patch.object(self.f.node.local_storage_manager, "finalize_stream",
                          side_effect=OSError("remote disk unavailable")):
            for decision in decisions:
                result = await controller.execute_launched_controller_action_decision(decision)
                self.assertFalse(result.succeeded)
                self.assertFalse((result.details or {}).get("health_processing_confirmed", False))
                self.assertEqual([e.event_type for e in controller.get_status()["experiment_lifecycle_evidence"]],
                                 ["experiment_start"])
        for decision in decisions:
            result = await controller.execute_launched_controller_action_decision(decision)
            self.assertTrue(result.succeeded, result.error)
        self.assertEqual([e.event_type for e in controller.get_status()["experiment_lifecycle_evidence"]],
                         ["experiment_start", "experiment_fail"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in self.f.node.local_storage_manager.manifests))
        stopped = await self.owner.workflow.stop()
        self.assertTrue(stopped.succeeded, stopped.error)

    async def test_direct_replay_requires_complete_interpretation(self):
        controller = self.f.controller
        original = interpretation("direct")
        decision = controller.process_health_interpretation(original)
        self.assertEqual(controller.process_health_interpretation(original), decision)
        for changed in (replace(original, details={"changed": True}),
                        replace(original, session_time_s=9),
                        replace(original, observation_type="different")):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    controller.process_health_interpretation(changed)
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)

    async def test_concurrent_exact_inputs_reuse_one_authoritative_decision(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        controller = self.f.controller
        barrier = Barrier(2)

        accept = controller._accept_action_payload

        def simultaneous_accept(*args, **kwargs):
            barrier.wait(timeout=2)
            return accept(*args, **kwargs)

        evidence = interpretation("concurrent")
        with patch.object(controller, "_accept_action_payload", new=simultaneous_accept):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(controller.process_health_interpretation, evidence) for _ in range(2)]
                decisions = [future.result(timeout=3) for future in futures]
        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)
        self.assertEqual(len(controller.controller_action_decisions), 1)

    async def test_same_identity_changed_input_is_rejected_before_cutoff(self):
        controller = self.f.controller
        callback, message = self.owner.delivery("conflicting")
        original = RuntimeEvidenceMessage.from_dict(json.loads(message.data))
        controller.process_health_interpretation(original)
        for changed in (replace(original, payload={**original.payload, "details": {"changed": True}}),
                        replace(original, payload={**original.payload, "originating_observation_id": "different"}),
                        replace(original, payload={**original.payload, "live_source_id": "different"}),
                        replace(original, is_persistent=False),
                        replace(original, evidence_id="other-envelope")):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    controller.process_health_interpretation(changed)
        changed = json.loads(message.data)
        changed["payload"]["session_time_s"] = 8
        message.data = json.dumps(changed).encode()
        with self.assertRaises(ValueError):
            await callback(message)
        message.ack.assert_not_awaited()
        self.assertEqual(len(controller.controller_action_decision_evidence), 1)

    async def test_timing_receiver_rejects_late_new_or_changed_input_without_ack(self):
        callback, message = self.owner.delivery("timing-input")
        original = RuntimeEvidenceMessage("timing-input", self.f.sid, "timing_quality_interpretation",
            "node", {"experiment_id": "experiment", "interpretation_label": "warning"}, True)
        message.subject = message.subject.replace(".health_interpretation", ".timing_quality_interpretation")
        message.data = json.dumps(original.to_dict()).encode()
        await callback(message)
        self.assertTrue((await self.owner.workflow.stop()).succeeded)
        await callback(message)
        self.assertEqual(message.ack.await_count, 2)
        for changed in (replace(original, evidence_id="new-timing-input"),
                        replace(original, payload={**original.payload, "details": {"changed": True}})):
            _, late = self.owner.delivery("unused")
            late.subject = message.subject
            late.data = json.dumps(changed.to_dict()).encode()
            with self.assertRaises((ValueError, RuntimeError)):
                await callback(late)
            late.ack.assert_not_awaited()
