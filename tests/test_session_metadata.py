"""Accepted Session values are isolated and durably retained before launch."""

from copy import deepcopy
import asyncio
import json
import unittest
from unittest.mock import patch

from lab_sync_acquisition import Controller, NatsControllerCommunication, PersistentStorageManager, Session, SessionConfig
from lab_sync_acquisition.communication import ExternalControllerRequest
from tests.test_distributed_session_closeout import CloseoutBroker
from tests import test_session_launch as launch_fixture


class SessionMetadataTests(unittest.TestCase):
    def test_accepted_values_ignore_input_and_public_snapshot_edits(self):
        metadata = {"animal": {"id": "original"}, "experimenter": "operator"}
        config = SessionConfig([], None, {"steps": ["baseline"]}, "errors", session_parameters=metadata)
        session = Session("session", config)
        metadata["animal"]["id"] = "catalog-edit"
        config.session_parameters["animal"]["id"] = "caller-edit"
        session.configuration.session_parameters["animal"]["id"] = "public-edit"
        snapshot = session.configuration.to_dict()
        snapshot["protocol_plan"]["steps"].append("edited")
        self.assertEqual(session.configuration.session_parameters["animal"]["id"], "original")
        self.assertEqual(session.configuration.protocol_plan, {"steps": ["baseline"]})

    def test_accepted_configuration_cannot_be_replaced(self):
        session = Session("session", SessionConfig([], None, None, "errors"))
        with self.assertRaises(AttributeError):
            session.configuration = SessionConfig([], None, None, "other")
        with self.assertRaises(AttributeError):
            del session.configuration

    def test_external_configuration_read_is_a_bounded_operation(self):
        request = ExternalControllerRequest("controller", "client", "read", "read_session_configuration", "session", {})
        self.assertEqual(ExternalControllerRequest.from_dict(request.to_dict()), request)
        with self.assertRaises(ValueError):
            ExternalControllerRequest("controller", "client", "read", request.operation, "session", {"replace": {}})


class SessionMetadataLaunchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = launch_fixture.SessionLaunchTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.broker = CloseoutBroker()
        self.f.communication = NatsControllerCommunication(launch_fixture._Boundary("controller", "controller", self.f.broker))
        self.storage = self.f.storage
        await self.f.services()
        self.node, self.declaration, _ = await self.f.node()
        self.f.config["session_parameters"] = {"animal": {"id": "original"}, "project": "study"}

    async def launch(self):
        return await self.f.launch({"node-a": [self.declaration]})

    def initial(self, sid):
        return self.f.root / "storage" / f"session_{sid}" / "session_record_initial.json"

    async def test_launch_preserves_complete_configuration_independently_of_controller(self):
        result = await self.launch()
        self.assertTrue(result.succeeded, result.error)
        sid = result.details["session_id"]
        accepted = deepcopy(result.details["configuration"])
        self.f.config["session_parameters"]["animal"]["id"] = "catalog-edit"
        result.details["configuration"]["session_parameters"]["animal"]["id"] = "response-edit"
        self.f.controller = Controller()
        restored = PersistentStorageManager(self.f.root / "storage")
        self.assertEqual(restored.read_session_record(self.initial(sid))["accepted_session_config"], accepted)
        self.assertFalse((self.initial(sid).parent / "session_record_final.json").exists())
        self.assertIsNone(restored.get_persisted_session_preservation_confirmation(sid))

    async def test_failed_initial_write_rolls_back_and_new_launch_uses_a_new_identity(self):
        with patch.object(self.storage, "_write_record_contents", side_effect=OSError("disk failure")):
            failed = await self.launch()
        self.assertFalse(failed.succeeded)
        self.assertIsNone(self.node.reserved_for_session_id)
        self.assertIsNone(self.f.controller.get_status()["session_id"])
        retried = await self.launch()
        self.assertTrue(retried.succeeded, retried.error)
        self.assertNotEqual(failed.details["session_id"], retried.details["session_id"])

    async def test_interrupted_initial_write_requires_existing_authorized_recovery(self):
        with patch.object(self.storage, "_write_record_contents", side_effect=OSError("interrupted write")):
            failed = await self.launch()
        command = next(c for c in self.f.broker.commands if c["command_type"] == "preserve_initial_session_record")
        with self.assertRaisesRegex(RuntimeError, "authorized write recovery"):
            self.storage.preserve_initial_session_record(failed.details["session_id"], command["payload"]["session_record"])

    async def test_existing_record_writers_cannot_change_accepted_metadata(self):
        launched = await self.launch()
        self.assertTrue(launched.succeeded, launched.error)
        sid = launched.details["session_id"]
        command = next(c for c in self.f.broker.commands if c["command_type"] == "preserve_initial_session_record")
        evidence = deepcopy(command["payload"]["session_record"])
        evidence["accepted_session_config"]["session_parameters"] = {"animal": "changed"}
        original = self.initial(sid).read_bytes()
        for writer in (lambda: self.storage.write_initial_session_record(sid, **evidence),
                       lambda: self.storage.write_final_session_record(sid, **evidence),
                       lambda: self.storage.write_session_record(self.initial(sid), **evidence)):
            with self.subTest(writer=writer), self.assertRaises(RuntimeError):
                writer()
            self.assertEqual(self.initial(sid).read_bytes(), original)

    async def test_false_write_acknowledgment_cannot_confirm_launch(self):
        with patch.object(self.storage, "write_initial_session_record", return_value=self.f.root / "missing"):
            result = await self.launch()
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.node.reserved_for_session_id)

    async def test_lost_preservation_result_does_not_report_launch_success(self):
        self.f.broker.drop_results.add(("ingestor", "preserve_initial_session_record"))
        result = await self.launch()
        self.assertFalse(result.succeeded)
        sid = result.details["session_id"]
        self.assertEqual(self.storage.read_session_record(self.initial(sid))["accepted_session_config"]["session_parameters"],
                         self.f.config["session_parameters"])
        self.assertIsNone(self.node.reserved_for_session_id)

    async def test_readback_failure_retains_record_without_success(self):
        with patch.object(self.storage, "read_session_record", side_effect=ValueError("corrupt readback")):
            result = await self.launch()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.initial(result.details["session_id"]).exists())
        self.assertIsNone(self.node.reserved_for_session_id)

    async def test_conflicting_or_corrupt_record_is_not_replaced(self):
        writer = self.storage.write_initial_session_record
        for content in ("not-json", json.dumps({"accepted_session_config": {"session_id": "other"}})):
            with self.subTest(content=content):
                def damaged(sid, **evidence):
                    path = writer(sid, **evidence)
                    path.write_text(content, encoding="utf-8")
                    return path
                with patch.object(self.storage, "write_initial_session_record", side_effect=damaged):
                    result = await self.launch()
                self.assertFalse(result.succeeded)
                self.assertEqual(self.initial(result.details["session_id"]).read_text(encoding="utf-8"), content)

    async def test_failed_fsync_cannot_establish_launch_success(self):
        import lab_sync_acquisition.storage as persistence
        write = self.storage._write_record_contents
        def failed(path, contents):
            with patch.object(persistence.os, "fsync", side_effect=OSError("fsync failure")):
                return write(path, contents)
        with patch.object(self.storage, "_write_record_contents", side_effect=failed):
            result = await self.launch()
        self.assertFalse(result.succeeded)
        self.assertTrue(self.initial(result.details["session_id"]).exists())
        self.assertIsNone(self.node.reserved_for_session_id)

    async def test_failed_preservation_and_uncertain_cleanup_block_reuse_until_cleanup(self):
        with patch.object(self.storage, "_write_record_contents", side_effect=OSError("disk failure")), \
                patch.object(self.node, "abort_session_initialization", side_effect=OSError("cleanup failure")):
            failed = await self.launch()
        original = failed.details["session_id"]
        self.assertEqual(self.node.reserved_for_session_id, original)
        reservations = sum(c["command_type"] == "reserve" for c in self.f.broker.commands)
        with patch.object(self.node, "abort_session_initialization", side_effect=OSError("cleanup failure")):
            blocked = await self.launch()
        self.assertFalse(blocked.succeeded)
        self.assertEqual(sum(c["command_type"] == "reserve" for c in self.f.broker.commands), reservations)
        recovered = await self.launch()
        self.assertTrue(recovered.succeeded, recovered.error)
        self.assertNotEqual(recovered.details["session_id"], original)

    async def test_incomplete_confirmation_and_wrong_configuration_are_rejected(self):
        preserve = self.storage.preserve_initial_session_record
        for change in (lambda proof: proof.pop("initial_record_preserved"),
                       lambda proof: proof["session_record"]["accepted_session_config"].update(session_parameters={"animal": "wrong"})):
            with self.subTest(change=change):
                def altered(*args):
                    proof = preserve(*args)
                    change(proof)
                    return proof
                with patch.object(self.storage, "preserve_initial_session_record", side_effect=altered):
                    result = await self.launch()
                self.assertFalse(result.succeeded)
                self.assertIsNone(self.node.reserved_for_session_id)

    async def test_wrong_operation_type_and_conflicting_preservation_results_cannot_confirm_launch(self):
        publish = self.f.broker.publish
        for fault in ("operation", "type", "conflict"):
            with self.subTest(fault=fault):
                async def altered(subject, data, stream):
                    payload = json.loads(data)
                    if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".preserve_initial_session_record"):
                        if fault == "operation":
                            subject = subject.rsplit(".", 1)[0] + ".check_readiness"
                        elif fault == "type":
                            subject = subject.replace(".command_result.ingestor.", ".command_result.storage_manager.")
                        else:
                            await publish(subject, data, stream)
                            payload.update(success=False, status="failed", reason="conflicting resolution")
                            data = json.dumps(payload).encode()
                    return await publish(subject, data, stream)
                with patch.object(self.f.broker, "publish", side_effect=altered):
                    result = await self.launch()
                self.assertFalse(result.succeeded)
                self.assertIsNone(self.node.reserved_for_session_id)

    async def test_cancellation_during_preservation_keeps_original_cleanup_scope(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = self.f.broker.publish

        async def paused(subject, data, stream):
            if stream == "LAB_COMMANDS" and json.loads(data)["command_type"] == "preserve_initial_session_record":
                entered.set()
                await resume.wait()
            return await publish(subject, data, stream)

        with patch.object(self.f.broker, "publish", side_effect=paused):
            task = asyncio.create_task(self.launch())
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
        self.assertIsNone(self.node.reserved_for_session_id)
        self.assertIsNone(self.f.controller.get_status()["session_id"])

    async def test_cancellation_after_initial_write_preserves_record_and_releases_resources(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = self.f.broker.publish
        saved = []

        async def paused(subject, data, stream):
            payload = json.loads(data)
            if stream == "LAB_COMMAND_RESULTS" and subject.endswith(".preserve_initial_session_record"):
                saved.append(payload["session_id"])
                entered.set()
                await resume.wait()
            return await publish(subject, data, stream)

        with patch.object(self.f.broker, "publish", side_effect=paused):
            task = asyncio.create_task(self.launch())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertTrue(self.initial(saved[0]).exists())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                resume.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertIsNone(self.node.reserved_for_session_id)
        self.assertEqual(self.storage.read_session_record(self.initial(saved[0]))["accepted_session_config"]["session_parameters"],
                         self.f.config["session_parameters"])
