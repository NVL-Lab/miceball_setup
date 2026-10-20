"""Closeout preserves admission, owner progress and proof across public retries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from threading import Event
from unittest.mock import patch

from lab_sync_acquisition import (
    ControllerActionDecision, DeviceAdapterState, ExperimentConfiguration,
    NatsControllerCommunication, RuntimeEvidenceMessage, RuntimeParticipant,
    ScientificOutputSelection,
)
from tests import test_closeout_attempt_ownership as ownership
from tests import test_distributed_session_closeout as remote
from tests import test_session_binding_release as binding
from tests.test_closeout_confirmation_integrity import _deliver_result
from tests.test_producer_publication_completion import interpretation
from tests.test_session_launch import _Boundary, _Broker


class HistoricalStopIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_valid_replay_requires_its_new_invocation_handover(self):
        broker = _Broker()
        communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
        participant = RuntimeParticipant("acquisition_node", "node")
        observer = await communication.subscribe_command_results("session")
        self.addAsyncCleanup(observer.unsubscribe)
        publish = broker.publish
        entered, resume = asyncio.Event(), asyncio.Event()
        first = None
        replay = False

        async def wire(subject, data, stream):
            nonlocal first
            if stream == "LAB_COMMANDS":
                command = json.loads(data)
                if first is None:
                    first = deepcopy(command)
                if replay:
                    entered.set()
                    await resume.wait()
                ack = await publish(subject, data, stream)
                result = dict(result_id="owner", command_id=command["command_id"], session_id="session",
                    source_id="node", target_id="controller", status="succeeded", success=True,
                    reason=None, payload=command["payload"])
                await publish("messages.session.command_result.acquisition_node.node.stop_runtime",
                              json.dumps(result).encode(), "LAB_COMMAND_RESULTS")
                return ack
            return await publish(subject, data, stream)

        with patch.object(broker, "publish", side_effect=wire):
            self.assertIsNotNone(await communication.request_runtime_command(participant,
                "stop_runtime", "session", {}, .1, command_id="A"))
            self.assertIsNotNone(await communication.request_runtime_command(participant,
                "stop_runtime", "session", {}, .1, command_id="B"))
            replay = True
            pending = asyncio.create_task(communication.request_command(participant,
                "stop_runtime", "session", first["payload"], .1, command_id="A"))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertIsNone(communication.session_acquisition_completion(participant, "session"))
            finally:
                resume.set()
                result = await pending
            self.assertIsNotNone(result)
            self.assertEqual(result.command_id, "A")

    async def test_scoped_only_request_retains_other_known_attempts_integrity(self):
        for mode in ("malformed", "contradictory", "nonfinite"):
            with self.subTest(mode=mode):
                broker = _Broker()
                communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
                participant = RuntimeParticipant("acquisition_node", "node")
                route = "messages.session.command_result.acquisition_node.node.stop_runtime"
                publish = broker.publish
                saved = {}
                count = 0

                async def wire(subject, data, stream):
                    nonlocal count
                    ack = await publish(subject, data, stream)
                    if stream == "LAB_COMMANDS":
                        command = json.loads(data)
                        count += 1
                        reply = dict(result_id="owner", command_id=command["command_id"], session_id="session",
                            source_id="node", target_id="controller", status="succeeded", success=True,
                            reason=None, payload=command["payload"])
                        saved.setdefault("command", deepcopy(command))
                        saved.setdefault("result", deepcopy(reply))
                        if count == 2:
                            old = deepcopy(saved["result"])
                            if mode == "malformed":
                                old.pop("reason")
                            elif mode == "contradictory":
                                old.update(status="failed", success=False, reason="Historical contradiction")
                            else:
                                old["payload"]["bad"] = float("nan")
                            await publish(route, json.dumps(old).encode(), "LAB_COMMAND_RESULTS")
                        await publish(route, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")
                    return ack

                with patch.object(broker, "publish", side_effect=wire):
                    self.assertIsNotNone(await communication.request_runtime_command(participant,
                        "stop_runtime", "session", {}, .1, command_id="A"))
                    self.assertIsNotNone(await communication.request_runtime_command(participant,
                        "stop_runtime", "session", {}, .1, command_id="B"))
                    subscription = await communication.subscribe_command_results("session")
                    self.addAsyncCleanup(subscription.unsubscribe)
                    original = saved["command"]
                    self.assertIsNone(await communication.request_command(participant, "stop_runtime", "session",
                        original["payload"], .1, command_id=original["command_id"]))
                    self.assertIsNotNone(await communication.request_runtime_command(participant,
                        "stop_runtime", "session", {}, .1))

    async def test_known_attempt_integrity_survives_supersession_and_replay(self):
        for scoped in (False, True):
            for historical in (False, True):
                for same_id in (False, True):
                    for mode in ("malformed", "contradictory", "nonfinite"):
                        with self.subTest(scoped=scoped, historical=historical, same_id=same_id, mode=mode):
                            broker = _Broker()
                            communication = NatsControllerCommunication(_Boundary("controller", "controller", broker))
                            participant = RuntimeParticipant("acquisition_node", "node")
                            subscription = await communication.subscribe_command_results("session")
                            self.addAsyncCleanup(subscription.unsubscribe)
                            route = "messages.session.command_result.acquisition_node.node.stop_runtime"
                            publish = broker.publish
                            saved = {}

                            async def wire(subject, data, stream):
                                ack = await publish(subject, data, stream)
                                if stream == "LAB_COMMANDS":
                                    command = json.loads(data)
                                    reply = dict(result_id="cached-result", command_id=command["command_id"],
                                        session_id="session", source_id="node", target_id="controller",
                                        status="succeeded", success=True, reason=None, payload=command["payload"])
                                    saved.setdefault("command", deepcopy(command))
                                    saved.setdefault("result", deepcopy(reply))
                                    await publish(route, json.dumps(reply).encode(), "LAB_COMMAND_RESULTS")
                                return ack

                            with patch.object(broker, "publish", side_effect=wire):
                                request = communication.request_runtime_command if scoped else communication.request_command
                                self.assertIsNotNone(await request(participant, "stop_runtime", "session", {}, .1, command_id="A"))
                                bad = deepcopy(saved["result"])
                                if mode == "malformed":
                                    bad.pop("reason")
                                elif mode == "contradictory":
                                    bad.update(status="failed", success=False, reason="Owner correction")
                                else:
                                    bad["payload"]["diagnostic"] = float("nan")
                                if not historical:
                                    self.assertEqual(await _deliver_result(subscription.callback, route, json.dumps(bad).encode()), ([], 1))
                                fresh = await communication.request_runtime_command(participant, "stop_runtime", "session", {}, .1,
                                    command_id="A" if same_id else "B")
                                self.assertIsNotNone(fresh)
                                if historical:
                                    self.assertEqual(await _deliver_result(subscription.callback, route, json.dumps(bad).encode()), ([], 1))
                                    self.assertEqual(communication.session_acquisition_completion(participant, "session"), fresh)
                                # Identical duplicate delivery remains a valid negative control.
                                self.assertEqual(await _deliver_result(subscription.callback, route,
                                    json.dumps(fresh.to_dict()).encode()), ([], 1))
                                original = saved["command"]
                                for _ in range(2):
                                    self.assertIsNone(await communication.request_command(participant, "stop_runtime", "session",
                                        original["payload"], .1, command_id=original["command_id"]))
                                    self.assertIsNone(communication.session_acquisition_completion(participant, "session"))
                                    self.assertIsNotNone(await communication.request_runtime_command(participant,
                                        "stop_runtime", "session", {}, .1))


class CloseoutLifecycleIntegrityTests(unittest.IsolatedAsyncioTestCase):
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
        return ControllerActionDecision("lifecycle-health", f.sid, "experiment", "source", "policy",
            "session_failure", "session_fail", None)

    async def invalidate(self, f, participant, *, malformed=False):
        sid = f.controller.get_status()["session_id"]
        result = f.communication.session_acquisition_completion(participant, sid)
        self.assertIsNotNone(result)
        body = result.to_dict()
        if malformed:
            body.pop("reason")
        else:
            body.update(status="failed", success=False, reason="Cleanup is unconfirmed")
        await f.broker.publish(f"messages.{sid}.command_result.{participant.component_type}.{participant.component_id}.stop_runtime",
                              json.dumps(body).encode(), "LAB_COMMAND_RESULTS")
        self.assertIsNone(f.communication.session_acquisition_completion(participant, sid))
        return result

    async def test_kill_cannot_overtake_experiment_preparation_at_each_owner_boundary(self):
        for boundary in ("sync.assess_synchronization", "storage.check_experiment_capacity",
                         "node.prepare_experiment_scientific_outputs"):
            with self.subTest(boundary=boundary):
                workflow, f = await self.workflow()
                self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
                entered, resume = asyncio.Event(), asyncio.Event()
                publish = f.broker.publish
                armed = True

                async def wire(subject, data, stream):
                    nonlocal armed
                    ack = await publish(subject, data, stream)
                    if armed and stream == "LAB_COMMAND_RESULTS" and subject.endswith("." + boundary):
                        armed = False
                        entered.set()
                        await resume.wait()
                    return ack

                output = ScientificOutputSelection("device", "node", "events")
                configuration = ExperimentConfiguration(60, {"node": 1000000}, 1000000)
                with patch.object(f.broker, "publish", side_effect=wire), patch.object(
                        f.node, "stop_runtime", wraps=f.node.stop_runtime) as stopped:
                    starting = asyncio.create_task(f.controller.start_launched_experiment("next",
                        scientific_outputs=(output,), configuration=configuration, storage_participant=workflow.storage_participant))
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        rejected = await f.controller.kill_session(communication=f.communication,
                            storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True)
                        self.assertFalse(rejected.succeeded)
                        self.assertEqual(f.controller.get_status()["session_state"], "running")
                        self.assertEqual(stopped.call_count, 0)
                    finally:
                        resume.set()
                    self.assertTrue((await starting).succeeded)
                    killed = await f.controller.kill_session(communication=f.communication,
                        storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True)
                    self.assertTrue(killed.succeeded, killed.error)
                    self.assertTrue(killed.details["participant_cleanup_confirmed"])
                    self.assertEqual(stopped.call_count, 1)
                    states = [a.state for a in f.node._runtime_device_manager.adapters]
                    self.assertEqual(states, [DeviceAdapterState.DECLARED])
                    self.assertFalse(f.node.prepare_experiment_scientific_outputs("late", (output,),
                        configuration=configuration).ready)
                    self.assertEqual([a.state for a in f.node._runtime_device_manager.adapters], states)

    async def test_admitted_kill_rejects_new_experiment_before_remote_preparation(self):
        workflow, f = await self.workflow()
        self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = f.broker.publish

        async def wire(subject, data, stream):
            ack = await publish(subject, data, stream)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".admit_session_kill"):
                entered.set()
                await resume.wait()
            return ack

        with patch.object(f.broker, "publish", side_effect=wire):
            killing = asyncio.create_task(f.controller.kill_session(communication=f.communication,
                storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                before = len(f.broker.commands)
                rejected = await f.controller.start_launched_experiment("rejected",
                    configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000),
                    storage_participant=workflow.storage_participant)
                self.assertFalse(rejected.succeeded)
                self.assertEqual(len(f.broker.commands), before)
            finally:
                resume.set()
            self.assertTrue((await killing).succeeded)

    async def test_owner_cleanup_joins_preparation_before_confirming_resource_closure(self):
        workflow, f = await self.workflow()
        self.assertTrue((await f.controller.stop_launched_experiment("experiment")).succeeded)
        local = f.node.local_storage_manager
        create = local.create_stream
        entered, resume, stopping = Event(), Event(), Event()

        def pause(**parameters):
            entered.set()
            if not resume.wait(2):
                raise TimeoutError("Preparation test was not resumed")
            return create(**parameters)

        def stop():
            stopping.set()
            return f.node.stop_runtime()

        with ThreadPoolExecutor(max_workers=2) as workers, patch.object(local, "create_stream", side_effect=pause):
            preparing = workers.submit(f.node.prepare_experiment_scientific_outputs, "owner-preparation",
                (ScientificOutputSelection("device", "node", "events"),),
                configuration=ExperimentConfiguration(60, {"node": 1000000}, 1000000))
            try:
                self.assertTrue(entered.wait(2))
                closing = workers.submit(stop)
                self.assertTrue(stopping.wait(2))
                with self.assertRaises(FutureTimeout):
                    closing.result(timeout=.05)
            finally:
                resume.set()
            self.assertTrue(preparing.result(timeout=2).ready)
            closing.result(timeout=2)
        self.assertTrue(f.node.status()["cleanup_confirmed"])
        self.assertTrue(all(m.lifecycle_state == "finalized" for m in local.manifests))
        self.assertTrue(all(a.state == DeviceAdapterState.DECLARED for a in f.node._runtime_device_manager.adapters))

    async def test_completed_normal_stop_and_binding_release_require_current_cleanup(self):
        for local in (False, True):
            for malformed in (False, True):
                with self.subTest(local=local, malformed=malformed):
                    workflow, f = await self.workflow(local=local)
                    participant = f.controller._reserved_participants[0]
                    node = f.nodes[participant.component_id] if local else f.node
                    with patch.object(node, "stop_runtime", wraps=node.stop_runtime) as stopped:
                        self.assertTrue((await workflow.stop()).succeeded)
                        before = {p: b for p, b in (workflow.products() if local else workflow.archive()).items()
                                  if str(p).endswith(".jsonl")}
                        original = await self.invalidate(f, participant, malformed=malformed)
                        self.assertFalse((await workflow.stop()).succeeded)
                        options = {} if local else {"communication": f.communication, "result_window_s": .25}
                        self.assertFalse((await f.controller.release_session(**options)).succeeded)
                        self.assertIsNotNone(f.controller.get_status()["session_id"])
                        self.assertEqual(f.controller.get_status()["session_state"], "completed")
                        self.assertIn("Unconfirmed Session cleanup", f.controller.maintenance_blockers(f.ingestor, workflow.storage))
                        self.assertIsNotNone(await f.communication.request_runtime_command(participant, "stop_runtime",
                            original.session_id, {}, .25, command_id=original.command_id))
                        self.assertTrue((await workflow.stop()).succeeded)
                        released = await f.controller.release_session(**options)
                        self.assertTrue(released.succeeded, released.error)
                        self.assertEqual(stopped.call_count, 1)
                        after = workflow.products() if local else workflow.archive()
                        self.assertEqual({p: b for p, b in after.items() if str(p).endswith(".jsonl")}, before)

    async def test_legacy_local_release_keeps_current_node_proof_without_requiring_a_marker(self):
        workflow = binding.SessionBindingReleaseTests()
        workflow.addCleanup = self.addCleanup
        workflow.addAsyncCleanup = self.addAsyncCleanup
        await workflow.asyncSetUp()
        f = workflow.launch
        sid = await workflow.start_session()
        with patch.object(workflow.node, "stop_runtime", wraps=workflow.node.stop_runtime) as stopped:
            await workflow.stop_session()
            self.assertTrue(f.controller.finalize_session().succeeded)
            directory = workflow.storage._session_directory(sid)
            before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
            original = await self.invalidate(f, RuntimeParticipant("acquisition_node", "node-a"))
            self.assertFalse((await f.controller.release_session()).succeeded)
            self.assertEqual(f.controller.get_status()["session_id"], sid)
            self.assertIsNotNone(await f.communication.request_runtime_command(RuntimeParticipant("acquisition_node", "node-a"),
                "stop_runtime", sid, {}, .1, command_id=original.command_id))
            self.assertTrue((await f.controller.release_session()).succeeded)
            self.assertEqual(stopped.call_count, 1)
            # Legacy release persists its terminal lifecycle; archived evidence is unchanged.
            self.assertEqual({p: p.read_bytes() for p in directory.rglob("*.jsonl")},
                             {p: data for p, data in before.items() if p.suffix == ".jsonl"})
            self.assertEqual(workflow.storage.read_session_record(directory / "session_record_final.json")
                             ["final_session_status"]["state"], "completed")

    async def test_release_rechecks_current_proof_and_retains_completed_release_steps(self):
        for boundary in ("local_unsubscribe", "read_session_closeout", "release_session", "final_readback"):
            with self.subTest(boundary=boundary):
                local = boundary == "local_unsubscribe"
                workflow, f = await self.workflow(local=local)
                self.assertTrue((await workflow.stop()).succeeded)
                participant = f.controller._reserved_participants[0]
                sid = f.controller.get_status()["session_id"]
                # An independent observer can still receive proof corrections after
                # launch-subscription teardown. It shares the same issuer lifetime.
                observer = await f.communication.subscribe_command_results(sid)
                self.addAsyncCleanup(observer.unsubscribe)
                options = {} if local else {"communication": f.communication, "result_window_s": .25}
                original = None
                if local:
                    wrappers = tuple(remote.ReleaseSubscription(s) for s in f.controller._launch_subscriptions)
                    f.controller._launch_subscriptions = wrappers

                    async def invalidate_before_unsubscribe():
                        nonlocal original
                        original = await self.invalidate(f, participant)

                    wrappers[0].before_unsubscribe = invalidate_before_unsubscribe
                    failed = await f.controller.release_session(**options)
                    wrappers[0].before_unsubscribe = None
                    self.assertTrue(wrappers[0].released)
                else:
                    publish = f.broker.publish
                    reads = 0

                    async def wire(subject, data, stream):
                        nonlocal original, reads
                        ack = await publish(subject, data, stream)
                        if stream == "LAB_COMMAND_RESULTS":
                            if subject.endswith(".read_session_closeout"):
                                reads += 1
                            trigger = (subject.endswith("." + boundary) if boundary != "final_readback"
                                       else subject.endswith(".read_session_closeout") and reads == 2)
                            if original is None and trigger:
                                original = await self.invalidate(f, participant)
                        return ack

                    with patch.object(f.broker, "publish", side_effect=wire):
                        failed = await f.controller.release_session(**options)
                self.assertIsNotNone(original)
                self.assertFalse(failed.succeeded)
                self.assertIsNotNone(f.controller.get_status()["session_id"])
                self.assertIsNotNone(await f.communication.request_runtime_command(participant, "stop_runtime",
                    sid, {}, .25, command_id=original.command_id))
                retried = await f.controller.release_session(**options)
                self.assertTrue(retried.succeeded, retried.error)
                if local:
                    self.assertEqual([s.attempts for s in wrappers], [1] * len(wrappers))

    async def test_normal_stop_to_kill_keeps_confirmed_reservation_release(self):
        workflow, f = await self.workflow()
        with patch.object(f.node, "stop_runtime", wraps=f.node.stop_runtime) as stopped, patch.object(
                f.node, "release_reservation", wraps=f.node.release_reservation) as released:
            f.broker.drop_results.add(("sync", "stop_runtime"))
            self.assertFalse((await workflow.stop()).succeeded)
            self.assertIsNone(f.node.reserved_for_session_id)
            f.broker.drop_results.clear()
            killed = await f.controller.kill_session(communication=f.communication,
                storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True)
            self.assertTrue(killed.succeeded, killed.error)
            result = await f.controller.release_session(communication=f.communication, result_window_s=.25)
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(stopped.call_count, 1)
            self.assertEqual(released.call_count, 1)
            self.assertIsNone(f.ingestor.session_id)

    async def test_participant_release_retries_distinguish_lost_and_failed_responses(self):
        for lost in (False, True):
            with self.subTest(lost=lost):
                workflow, f = await self.workflow()
                self.assertTrue((await workflow.stop()).succeeded)
                real = f.sync.release_session
                calls = 0

                def release(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    return False if not lost and calls == 1 else real(*args, **kwargs)

                with patch.object(f.sync, "release_session", side_effect=release):
                    if lost:
                        f.broker.drop_results.add(("sync", "release_session"))
                    self.assertFalse((await f.controller.release_session(communication=f.communication,
                        result_window_s=.25)).succeeded)
                    f.broker.drop_results.clear()
                    result = await f.controller.release_session(communication=f.communication, result_window_s=.4)
                    self.assertTrue(result.succeeded, result.error)
                sent = [c for c in f.broker.commands if c["command_type"] == "release_session" and c["target_id"] == "sync"]
                self.assertEqual(len({c["command_id"] for c in sent}), 1 if lost else 2)
                self.assertEqual(calls, 1 if lost else 2)

    async def test_lost_synchronization_stop_reply_reuses_owner_operation(self):
        workflow, f = await self.workflow()
        with patch.object(f.sync, "complete_session_evidence_publication",
                wraps=f.sync.complete_session_evidence_publication) as cleanup:
            f.broker.drop_results.add(("sync", "stop_runtime"))
            self.assertFalse((await workflow.stop()).succeeded)
            f.broker.drop_results.clear()
            result = await workflow.stop()
            self.assertTrue(result.succeeded, result.error)
            sent = [c for c in f.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "sync"]
            self.assertEqual(len({c["command_id"] for c in sent}), 1)
            self.assertEqual(len({c["payload"]["request_nonce"] for c in sent}), len(sent))
            self.assertEqual(cleanup.call_count, 1)

    async def test_health_cleanup_requires_the_remote_synchronization_receipt(self):
        workflow, f = await self.workflow()
        with patch.object(f.node, "stop_runtime", wraps=f.node.stop_runtime) as stopped, patch.object(
                f.sync, "complete_session_evidence_publication",
                wraps=f.sync.complete_session_evidence_publication) as synchronization:
            f.broker.drop_results.add(("sync", "stop_runtime"))
            result = await f.controller.execute_launched_controller_action_decision(self.decision(f))
            self.assertFalse(result.succeeded)
            self.assertFalse(result.details["cleanup_confirmed"])
            self.assertFalse(result.details["preservation_confirmed"])
            self.assertEqual(f.controller.get_status()["session_state"], "failed")
            self.assertIsNotNone(f.controller.get_status()["session_id"])
            f.broker.drop_results.clear()
            retry = await f.controller.execute_launched_controller_action_decision(self.decision(f))
            self.assertTrue(retry.succeeded, retry.error)
            self.assertTrue(retry.details["cleanup_confirmed"])
            self.assertEqual((stopped.call_count, synchronization.call_count), (1, 1))

    async def test_fatal_health_after_interrupted_normal_stop_keeps_failure_and_its_cleanup_owner(self):
        workflow, f = await self.workflow()
        with patch.object(f.node, "stop_runtime", wraps=f.node.stop_runtime) as stopped:
            f.broker.drop_results.add(("sync", "stop_runtime"))
            self.assertFalse((await workflow.stop()).succeeded)
            f.broker.drop_results.clear()
            health = await f.controller.execute_launched_controller_action_decision(self.decision(f))
            self.assertTrue(health.succeeded, health.error)
            self.assertTrue(health.details["health_processing_confirmed"])
            self.assertEqual(health.details["cleanup_owner"], "normal_stop")
            self.assertFalse((await f.controller.kill_session(communication=f.communication,
                storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True)).succeeded)
            result = await workflow.stop()
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(f.controller.get_status()["session_state"], "failed")
            self.assertEqual(stopped.call_count, 1)

    async def test_partial_owner_cleanup_retries_finalization_without_repeating_device_stop(self):
        for mode in ("normal", "health", "kill"):
            with self.subTest(mode=mode):
                workflow, f = await self.workflow()
                local = f.node.local_storage_manager
                finalize = local.finalize_stream
                adapter, = f.node._runtime_device_manager.adapters
                failed = False

                def fail_once(storage_id):
                    nonlocal failed
                    if not failed:
                        failed = True
                        raise OSError("Transient scientific finalization failure")
                    return finalize(storage_id)

                async def close():
                    if mode == "normal":
                        return await workflow.stop()
                    if mode == "health":
                        return await f.controller.execute_launched_controller_action_decision(self.decision(f))
                    return await f.controller.kill_session(communication=f.communication,
                        storage_participant=workflow.storage_participant, result_window_s=.25, operator_authorized=True)

                with patch.object(adapter, "stop", wraps=adapter.stop) as stops:
                    with patch.object(local, "finalize_stream", side_effect=fail_once):
                        first = await close()
                    self.assertFalse(f.node.status()["cleanup_confirmed"])
                    before = workflow.archive()
                    second = await close()
                    self.assertTrue(f.node.status()["cleanup_confirmed"])
                    self.assertEqual(stops.call_count, 1)
                    self.assertTrue(all(m.lifecycle_state == "finalized" for m in local.manifests))
                    if mode == "kill":
                        self.assertTrue(first.succeeded)
                        self.assertFalse(first.details["participant_cleanup_confirmed"])
                        self.assertFalse(second.succeeded)
                        self.assertEqual(workflow.archive(), before)
                        self.assertIsNotNone(f.controller.get_status()["session_id"])
                    else:
                        self.assertFalse(first.succeeded)
                        self.assertTrue(second.succeeded, second.error)

    async def test_cancelled_partial_cleanup_retains_failed_receipt_and_device_progress(self):
        workflow, f = await self.workflow()
        local = f.node.local_storage_manager
        finalize, publish = local.finalize_stream, f.broker.publish
        entered, resume = asyncio.Event(), asyncio.Event()
        adapter, = f.node._runtime_device_manager.adapters
        failed = False

        def fail_once(storage_id):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("Transient finalization failure")
            return finalize(storage_id)

        async def wire(subject, data, stream):
            ack = await publish(subject, data, stream)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                entered.set()
                await resume.wait()
            return ack

        with patch.object(adapter, "stop", wraps=adapter.stop) as stops:
            with patch.object(local, "finalize_stream", side_effect=fail_once), patch.object(f.broker, "publish", side_effect=wire):
                task = asyncio.create_task(workflow.stop())
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    resume.set()
            self.assertTrue((await workflow.stop()).succeeded)
            self.assertEqual(stops.call_count, 1)
            self.assertTrue(all(m.lifecycle_state == "finalized" for m in local.manifests))
            sent = [c for c in f.broker.commands if c["command_type"] == "stop_runtime" and c["target_id"] == "node"]
            self.assertEqual(len({c["command_id"] for c in sent}), 2)

    async def test_device_shutdown_failure_retries_without_repeating_completed_stop(self):
        workflow, f = await self.workflow()
        adapter, = f.node._runtime_device_manager.adapters
        shutdown = adapter._shutdown_resources
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("Shutdown dependency temporarily unavailable")
            return shutdown()

        with patch.object(adapter, "_shutdown_resources", side_effect=fail_once), patch.object(
                adapter, "stop", wraps=adapter.stop) as stopped:
            self.assertFalse((await workflow.stop()).succeeded)
            self.assertFalse(f.node.status()["cleanup_confirmed"])
            self.assertIsNotNone(f.node.reserved_for_session_id)
            result = await workflow.stop()
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual((stopped.call_count, attempts), (1, 2))
            self.assertEqual(adapter.state, DeviceAdapterState.DECLARED)

    async def test_multi_node_partial_cleanup_preserves_other_nodes_release(self):
        workflow, f = await self.workflow(local=True, two=True)
        first, second = tuple(f.nodes.values())
        adapter, = second._runtime_device_manager.adapters
        finalize = second.local_storage_manager.finalize_stream
        failed = False

        def fail_once(storage_id):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("One node's finalization is unavailable")
            return finalize(storage_id)

        with patch.object(first, "stop_runtime", wraps=first.stop_runtime) as stops, patch.object(
                first, "release_reservation", wraps=first.release_reservation) as releases, patch.object(
                adapter, "stop", wraps=adapter.stop) as device_stops:
            with patch.object(second.local_storage_manager, "finalize_stream", side_effect=fail_once):
                self.assertFalse((await workflow.stop()).succeeded)
            result = await workflow.stop()
            self.assertTrue(result.succeeded, result.error)
            self.assertEqual((stops.call_count, releases.call_count, device_stops.call_count), (1, 1, 1))

    async def test_historical_malformed_proof_cannot_authorize_disk_closeout(self):
        for operation in ("preserve_session_acquisition", "preserve_session_terminal_record"):
            for fatal in (False, True):
                with self.subTest(operation=operation, fatal=fatal):
                    workflow, f = await self.workflow()
                    participant = RuntimeParticipant("acquisition_node", "node")
                    publish = f.broker.publish
                    saved = {}
                    injected = False

                    async def wire(subject, data, stream):
                        nonlocal injected
                        body = json.loads(data)
                        if stream == "LAB_COMMANDS" and subject.endswith(".node.stop_runtime"):
                            saved.setdefault("command", deepcopy(body))
                        if fatal and stream == "LAB_COMMANDS" and subject.endswith(".node.release_reservation"):
                            evidence = replace(interpretation("history-fatal"), interpretation_label="session_failure")
                            await f.handler.publish_evidence(RuntimeEvidenceMessage("history-fatal", f.sid,
                                "health_interpretation", "node", evidence.to_dict(), True))
                        ack = await publish(subject, data, stream)
                        if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".node.stop_runtime"):
                            saved.setdefault("result", deepcopy(body))
                        if not injected and stream == "LAB_COMMAND_RESULTS" and subject.endswith("." + operation):
                            injected = True
                            command = saved["command"]
                            fresh = await f.communication.request_runtime_command(participant, "stop_runtime", f.sid,
                                {}, .25, command_id=command["command_id"])
                            self.assertIsNotNone(fresh)
                            bad = deepcopy(saved["result"])
                            bad.pop("reason")
                            await publish(f"messages.{f.sid}.command_result.acquisition_node.node.stop_runtime",
                                          json.dumps(bad).encode(), "LAB_COMMAND_RESULTS")
                            self.assertEqual(f.communication.session_acquisition_completion(participant, f.sid), fresh)
                            self.assertIsNone(await f.communication.request_command(participant, "stop_runtime", f.sid,
                                command["payload"], .25, command_id=command["command_id"]))
                        return ack

                    with patch.object(f.broker, "publish", side_effect=wire), patch.object(
                            f.node, "stop_runtime", wraps=f.node.stop_runtime) as stops:
                        self.assertFalse((await workflow.stop()).succeeded)
                        self.assertTrue(injected)
                        before = {p: b for p, b in workflow.archive().items() if p.endswith(".jsonl")}
                        command = saved["command"]
                        self.assertIsNotNone(await f.communication.request_runtime_command(participant, "stop_runtime",
                            f.sid, {}, .25, command_id=command["command_id"]))
                        retried = await workflow.stop()
                        self.assertTrue(retried.succeeded, retried.error)
                        self.assertEqual(f.controller.get_status()["session_state"], "failed" if fatal else "completed")
                        self.assertEqual({p: b for p, b in workflow.archive().items() if p.endswith(".jsonl")}, before)
                        self.assertEqual(stops.call_count, 1)
