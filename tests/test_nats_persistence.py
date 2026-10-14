"""Accepted intake reaches its storage owner through public NATS command/result adapters."""

import asyncio
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope, InMemoryIngestor, NatsControllerCommunication,
    NatsIngestorCommunication, NatsStorageManagerCommunication,
    PersistentStorageManager, RuntimeCommandResultMessage, RuntimeEvidenceMessage, RuntimeParticipant,
)
from tests.test_session_launch import _Boundary, _Broker
from tests import test_storage as record_fixtures
from tests.evidence_receipt_fixtures import EvidenceReceiptBroker


class PersistenceBroker(_Broker):
    async def subscribe(self, subject, cb, **options):
        subscription = await super().subscribe(subject, cb, **options)
        if options.get("durable"):
            self.callbacks[options["durable"]] = cb
        if ".command_result." in subject and options.get("config") is None:
            for result in self.results:
                await cb(SimpleNamespace(data=json.dumps(result).encode(), ack=AsyncMock()))
        return subscription

    async def publish(self, subject, data, stream):
        if stream == "LAB_EVIDENCE":
            return await EvidenceReceiptBroker.publish(self, subject, data, stream)
        return await super().publish(subject, data, stream)


class NatsPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.broker = PersistenceBroker()
        self.storage = PersistentStorageManager(self.root / "records.jsonl", component_id="storage")
        self.ingestor = InMemoryIngestor(session_id="session",
            recovery_journal_path=self.root / "journal.jsonl", component_id="intake")
        self.store_peer = RuntimeParticipant("storage_manager", "storage")
        self.intake_peer = RuntimeParticipant("ingestor", "intake")
        self.writer = NatsStorageManagerCommunication(
            _Boundary("storage_manager", "storage", self.broker), self.storage)
        self.intake_boundary = _Boundary("ingestor", "intake", self.broker)
        self.intake = NatsIngestorCommunication(self.intake_boundary, self.ingestor)
        for subscription in await self.writer.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        for subscription in await self.intake.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        self.envelope = AcquisitionRecordEnvelope("session", "device", "event",
            [{"session_time_s": 1.0, "value": 7}], "node")
        self.assertTrue(self.ingestor.receive_envelope(self.envelope).accepted)

    async def persist(self, identity="write", envelope=None):
        return await self.intake.persist_accepted_envelope(envelope or self.envelope,
            storage_participant=self.store_peer, command_id=identity, result_window_s=0.01)

    async def request(self, peer, operation, payload=None, *, session="session", identity="read"):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        return await requests.request_persistence_command(peer, operation, session, payload or {},
            0.01, command_id=identity)

    async def test_accepted_envelope_is_persisted_and_read_back_over_nats(self):
        with patch("lab_sync_acquisition.ingestor.InMemoryIngestor", side_effect=AssertionError("extra owner")), \
                patch("lab_sync_acquisition.storage.PersistentStorageManager", side_effect=AssertionError("extra owner")):
            result = await self.persist()
        self.assertTrue(result["durable_persistence_confirmed"], result)
        self.assertEqual(result["command_id"], "write")
        self.assertEqual(result["requester_id"], "intake")
        self.assertEqual(result["storage_manager_id"], "storage")
        self.assertEqual(result["envelope"], self.envelope.to_dict())
        readback = await self.request(self.store_peer, "read_envelopes")
        self.assertTrue(readback.success)
        self.assertEqual(readback.payload["envelopes"], [self.envelope.to_dict()])
        self.assertEqual(len(self.ingestor.ingest_audit), 1)
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))

    async def test_nonfinite_scientific_values_keep_existing_storage_behavior(self):
        envelope = AcquisitionRecordEnvelope("session", "device", "event",
            [{"session_time_s": 2.0, "value": float("nan")}], "node")
        self.storage.store_envelopes((envelope,))
        self.assertTrue(math.isnan(self.storage.read_envelopes()[0].records[0]["value"]))
        self.ingestor.receive_envelope(envelope)
        result = await self.persist("nonfinite", envelope)
        self.assertTrue(result["durable_persistence_confirmed"])
        self.assertTrue(math.isnan(result["envelope"]["records"][0]["value"]))
        repeat = await self.persist("nonfinite", envelope)
        self.assertTrue(repeat["already_persisted"])
        self.assertEqual(len(self.storage.read_envelopes()), 2)

    async def test_durability_failure_is_not_confirmed_and_identical_retry_does_not_append(self):
        with patch("lab_sync_acquisition.storage.os.fsync", side_effect=OSError("durability unavailable")):
            failed = await self.persist()
        self.assertFalse(failed["durable_persistence_confirmed"])
        self.assertIn("durability unavailable", failed["reason"])
        retry = await self.persist()
        self.assertTrue(retry["durable_persistence_confirmed"])
        self.assertTrue(retry["already_persisted"])
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))

    async def test_owner_readback_must_confirm_before_success_is_returned(self):
        with patch.object(self.storage, "get_envelope_persistence_confirmation", return_value=None):
            failed = await self.persist()
        self.assertFalse(failed["durable_persistence_confirmed"])
        self.assertIn("unconfirmed", failed["reason"])
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_lost_result_remains_unconfirmed_and_retry_reconfirms_current_owner(self):
        self.broker.drop_results.add(("storage", "persist_envelope"))
        result = await self.persist()
        self.assertFalse(result["durable_persistence_confirmed"])
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.broker.drop_results.clear()
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_historical_success_cannot_hide_a_missing_retry_result(self):
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        self.broker.drop_results.add(("storage", "persist_envelope"))
        failed = await self.persist()
        self.assertFalse(failed["durable_persistence_confirmed"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_late_previous_attempt_reply_is_ignored_during_retry(self):
        await self.persist()
        previous = RuntimeCommandResultMessage.from_dict(self.broker.results[-1])
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = self.writer._boundary.publish_command_result
        current = True

        async def pause(result, operation):
            nonlocal current
            if current:
                current = False
                entered.set()
                await resume.wait()
            await publish(result, operation)

        with patch.object(self.writer._boundary, "publish_command_result", side_effect=pause):
            pending = asyncio.create_task(self.persist())
            await entered.wait()
            await self.writer._boundary.publish_command_result(previous, "persist_envelope")
            self.assertFalse(pending.done())
            resume.set()
            result = await pending
        self.assertTrue(result["durable_persistence_confirmed"])
        self.assertNotEqual(result["request_nonce"], previous.payload["request_nonce"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_publication_failure_retains_accepted_intake_for_retry(self):
        self.intake_boundary.available = False
        with self.assertRaises(ConnectionError):
            await self.persist()
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.assertEqual(self.storage.read_envelopes(), ())
        self.intake_boundary.available = True
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])

    async def test_retry_after_storage_restart_keeps_one_command_owned_record(self):
        await self.persist()
        original = self.storage.records_path.read_bytes()
        for subscription in self.broker.subscriptions:
            if ".command.storage_manager.storage." in subscription.subject:
                await subscription.unsubscribe()
        restored = PersistentStorageManager(self.storage.records_path, component_id="storage")
        writer = NatsStorageManagerCommunication(
            _Boundary("storage_manager", "storage", self.broker), restored)
        for subscription in await writer.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        result = await self.persist()
        self.assertTrue(result["durable_persistence_confirmed"])
        self.assertTrue(result["already_persisted"])
        self.assertEqual(restored.records_path.read_bytes(), original)

    async def test_same_command_conflicts_but_distinct_commands_preserve_identical_observations(self):
        await self.persist()
        changed = AcquisitionRecordEnvelope("session", "device", "event",
            [{"session_time_s": 2.0, "value": 8}], "node")
        self.ingestor.receive_envelope(changed)
        failed = await self.persist(envelope=changed)
        self.assertFalse(failed["durable_persistence_confirmed"])
        self.assertIn("Conflicting", failed["reason"])
        self.assertTrue((await self.persist("second"))["durable_persistence_confirmed"])
        self.assertEqual(self.storage.read_envelopes(), (self.envelope, self.envelope))

    async def test_overlapping_identical_requests_append_once(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        publish = self.writer._boundary.publish_command_result
        first_result = True

        async def pause(result, operation):
            nonlocal first_result
            if first_result:
                first_result = False
                entered.set()
                await resume.wait()
            await publish(result, operation)

        with patch.object(self.writer._boundary, "publish_command_result", side_effect=pause):
            pending = asyncio.create_task(self.persist())
            await entered.wait()
            second = await self.persist()
            resume.set()
            first = await pending
        self.assertTrue(first["durable_persistence_confirmed"])
        self.assertTrue(second["durable_persistence_confirmed"])
        self.assertTrue(second["already_persisted"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_unaccepted_or_wrong_session_envelope_is_not_published(self):
        for envelope in (AcquisitionRecordEnvelope("session", "device", "event", [], "node"),
                         AcquisitionRecordEnvelope("other", "device", "event", [], "node")):
            with self.assertRaises((ValueError, RuntimeError)):
                await self.persist(envelope=envelope)
        self.assertEqual(self.broker.commands, [])
        self.assertEqual(self.storage.read_envelopes(), ())

    async def test_existing_readiness_command_reports_the_storage_owner(self):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        subscription = await requests.subscribe_command_results(None)
        try:
            result = await requests.request_command(self.store_peer, "check_readiness", None, {},
                0.01, command_id="ready")
        finally:
            await subscription.unsubscribe()
        self.assertTrue(result.success)
        self.assertEqual(result.payload["service_readiness"]["component_id"], "storage")
        self.assertEqual(self.storage.read_envelopes(), ())

    async def test_recovery_command_cannot_bypass_existing_administrator_interface(self):
        requests = NatsControllerCommunication(_Boundary("controller", "operator", self.broker))
        subscription = await requests.subscribe_command_results(None)
        try:
            result = await requests.request_command(self.store_peer, "recover_archive_write", None,
                {"authorization_evidence_id": "missing", "obligation": {"session_id": "session"}},
                0.01, command_id="unauthorized")
        finally:
            await subscription.unsubscribe()
        self.assertFalse(result.success)
        self.assertEqual(self.storage.read_envelopes(), ())

    async def test_malformed_and_cross_session_requests_are_rejected_without_writes(self):
        malformed = self.envelope.to_dict()
        malformed["records"] = "not-records"
        cross_session = self.envelope.to_dict()
        cross_session["session_id"] = "other"
        for index, payload in enumerate(({"envelope": malformed}, {"envelope": cross_session},
                                         {"envelope": self.envelope.to_dict(), "unexpected": True})):
            result = await self.request(self.store_peer, "persist_envelope", payload, identity=f"invalid-{index}")
            self.assertFalse(result.success)
        self.assertEqual(self.storage.read_envelopes(), ())

    async def test_cancelled_request_keeps_evidence_and_retry_reconfirms_without_duplicate(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        boundary = self.writer._boundary
        publish = boundary.publish_command_result

        async def pause(result, operation):
            entered.set()
            await resume.wait()
            await publish(result, operation)

        with patch.object(boundary, "publish_command_result", side_effect=pause):
            task = asyncio.create_task(self.persist())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_binding_change_during_result_delivery_is_not_confirmed_for_new_session(self):
        def change(operation, result):
            if operation == "persist_envelope":
                self.ingestor.abort_session_initialization("session")
                self.ingestor.prepare_session("other")
            return result
        self.ingestor = InMemoryIngestor(recovery_journal_root=self.root / "journals", component_id="intake")
        self.ingestor.prepare_session("session")
        self.ingestor.receive_envelope(self.envelope)
        self.intake = NatsIngestorCommunication(self.intake_boundary, self.ingestor)
        self.broker.change_result = change
        with self.assertRaisesRegex(RuntimeError, "binding changed"):
            await self.persist()
        self.assertEqual(self.ingestor.session_id, "other")
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope,))
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))

    async def test_corrupt_record_history_blocks_retry_without_rewriting(self):
        await self.persist()
        with self.storage.records_path.open("ab") as output:
            output.write(b'{"interrupted":')
        before = self.storage.records_path.read_bytes()
        failed = await self.persist()
        self.assertFalse(failed["durable_persistence_confirmed"])
        self.assertEqual(self.storage.records_path.read_bytes(), before)

    async def test_invalid_correlation_blocks_retry_without_rewriting(self):
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        original = json.loads(self.storage.records_path.read_text(encoding="utf-8"))
        valid = original["persistence_command"]
        invalid = [None, [], "write", {},
                   {key: value for key, value in valid.items() if key != "command_id"}]
        for field in valid:
            invalid.extend({**valid, field: value} for value in (None, 7, "", " "))
        invalid.append({**valid, "unexpected": True})
        for correlation in invalid:
            with self.subTest(correlation=correlation):
                damaged = {**original, "persistence_command": correlation}
                self.storage.records_path.write_text(json.dumps(damaged) + "\n", encoding="utf-8")
                before = self.storage.records_path.read_bytes()
                failed = await self.persist()
                self.assertFalse(failed["durable_persistence_confirmed"], failed)
                self.assertIn("persistence_command correlation", failed["reason"])
                self.assertEqual(self.storage.records_path.read_bytes(), before)
                self.assertEqual(len(before.splitlines()), 1)

    async def test_invalid_correlation_blocks_retry_after_storage_restart(self):
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])
        original = json.loads(self.storage.records_path.read_text(encoding="utf-8"))
        for correlation in (None, {key: value for key, value in
                                  original["persistence_command"].items() if key != "command_id"}):
            with self.subTest(correlation=correlation):
                damaged = {**original, "persistence_command": correlation}
                self.storage.records_path.write_text(json.dumps(damaged) + "\n", encoding="utf-8")
                before = self.storage.records_path.read_bytes()
                for subscription in tuple(self.broker.subscriptions):
                    if ".command.storage_manager.storage." in subscription.subject:
                        await subscription.unsubscribe()
                restored = PersistentStorageManager(self.storage.records_path, component_id="storage")
                writer = NatsStorageManagerCommunication(
                    _Boundary("storage_manager", "storage", self.broker), restored)
                for subscription in await writer.subscribe_commands():
                    self.addAsyncCleanup(subscription.unsubscribe)
                failed = await self.persist()
                self.assertFalse(failed["durable_persistence_confirmed"], failed)
                self.assertIn("persistence_command correlation", failed["reason"])
                self.assertEqual(restored.records_path.read_bytes(), before)
                self.assertEqual(len(before.splitlines()), 1)

    async def test_legacy_envelopes_remain_readable_with_correlated_retries(self):
        self.storage.store_envelopes((self.envelope,))
        legacy = self.storage.records_path.read_bytes()
        self.assertNotIn("persistence_command", json.loads(legacy))
        readback = await self.request(self.store_peer, "read_envelopes")
        self.assertTrue(readback.success)
        self.assertEqual(readback.payload["envelopes"], [self.envelope.to_dict()])
        first = await self.persist()
        self.assertTrue(first["durable_persistence_confirmed"])
        self.assertFalse(first["already_persisted"])
        before = self.storage.records_path.read_bytes()
        self.assertTrue(before.startswith(legacy))
        retry = await self.persist()
        self.assertTrue(retry["durable_persistence_confirmed"])
        self.assertTrue(retry["already_persisted"])
        self.assertEqual(self.storage.records_path.read_bytes(), before)
        self.assertEqual(self.storage.read_envelopes(), (self.envelope, self.envelope))

    async def test_stale_or_mismatched_success_reply_cannot_confirm_persistence(self):
        for field, value in (("session_id", "other"), ("requester_id", "other"),
                             ("storage_manager_id", "other"), ("command_id", "old"),
                             ("envelope", {"session_id": "other"})):
            def change(operation, result):
                if operation == "persist_envelope":
                    result["payload"][field] = value
                return result
            self.broker.change_result = change
            with self.assertRaises(ValueError):
                await self.persist()
        self.assertEqual(len(self.storage.read_envelopes()), 1)

    async def test_compilation_is_journal_verified_and_not_an_archival_claim(self):
        persistent = RuntimeEvidenceMessage("persistent", "session", "note", "node", {}, True)
        transient = RuntimeEvidenceMessage("transient", "session", "note", "node", {})
        for message in (persistent, transient):
            self.ingestor.receive_runtime_evidence(message)
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("", "session", "note", "node", {}))
        result = await self.request(self.intake_peer, "compile_session_evidence")
        self.assertTrue(result.success)
        self.assertTrue(result.payload["journal_coverage_confirmed"])
        self.assertEqual(result.payload["runtime_evidence"], [persistent.to_dict()])
        self.assertEqual(len(result.payload["ingest_audit"]), 3)
        self.assertEqual(result.payload["accepted_acquisition_envelopes"], [self.envelope.to_dict()])
        self.assertNotIn("archival_confirmed", result.payload)
        self.ingestor.recovery_journal_path.write_text("corrupted", encoding="utf-8")
        refused = await self.request(self.intake_peer, "compile_session_evidence", identity="again")
        self.assertFalse(refused.success)

    async def test_compilation_rejects_unrelated_session_without_changing_intake(self):
        before = self.ingestor.accepted_envelopes
        result = await self.request(self.intake_peer, "compile_session_evidence", session="other")
        self.assertFalse(result.success)
        self.assertEqual(self.ingestor.accepted_envelopes, before)

    async def test_conflicting_intake_cannot_be_compiled_as_current_session_evidence(self):
        other = AcquisitionRecordEnvelope("other", "device", "event", [], "node")
        self.ingestor.receive_envelope(other)
        result = await self.request(self.intake_peer, "compile_session_evidence")
        self.assertFalse(result.success)
        self.assertIn("conflicting Session", result.reason)
        self.assertEqual(self.ingestor.accepted_envelopes, (self.envelope, other))

    async def test_receipt_verification_uses_owner_consumer_and_rejects_missing_ack_progress(self):
        subscription = await self.intake.subscribe_evidence("session")
        self.addAsyncCleanup(subscription.unsubscribe)
        consumer = next(iter(self.broker.consumers))
        producer = _Boundary("controller", "controller", self.broker)
        marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        await producer.publish_evidence(marker)
        await self.broker.deliver(consumer, self.broker.last_sequence)
        result = await self.request(self.intake_peer, "verify_acquisition_receipt", {"marker": marker.to_dict()})
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["durable_receipt_confirmed"])
        self.broker.consumers[consumer].ack_floor.stream_seq = 0
        failed = await self.request(self.intake_peer, "verify_acquisition_receipt",
            {"marker": marker.to_dict()}, identity="recheck")
        self.assertFalse(failed.success)
        self.assertFalse(failed.payload["durable_receipt_confirmed"])

    def preserve_session(self):
        marker = RuntimeEvidenceMessage("marker", "session", "acquisition_evidence_completion", "controller", {}, True)
        self.ingestor.receive_runtime_evidence(marker)
        record = record_fixtures.PersistentStorageManagerTests._minimal_session_record_evidence("session")
        record.update(accepted_acquisition_envelopes=self.ingestor.accepted_envelopes,
                      ingest_audit_records=self.ingestor.ingest_audit)
        self.storage.write_acquisition_stage("session", self.ingestor.compile_persistent_runtime_evidence(),
            receipt={"session_id": "session", "durable_receipt_confirmed": True,
                     "evidence_id": "marker", "marker_stream_sequence": 1},
            **record)
        self.storage.write_artifact_collection_handoff("session", self.ingestor.compile_artifact_collection_handoff("session"))

    async def test_preservation_readback_is_current_after_restart_and_detects_corruption(self):
        self.preserve_session()
        for subscription in self.broker.subscriptions:
            if ".command.storage_manager.storage." in subscription.subject:
                await subscription.unsubscribe()
        restored = PersistentStorageManager(self.storage.records_path, component_id="storage")
        handler = NatsStorageManagerCommunication(_Boundary("storage_manager", "storage", self.broker), restored)
        for subscription in await handler.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        result = await self.request(self.store_peer, "read_session_preservation")
        self.assertTrue(result.success, result.reason)
        self.assertTrue(result.payload["archival_confirmed"])
        self.assertFalse(result.payload["confirmation"]["compilation_summary"]["archive_closed"])
        audit = self.root / "session_session/evidence/ingest_audit.jsonl"
        audit.write_text("", encoding="utf-8")
        before = audit.read_bytes()
        failed = await self.request(self.store_peer, "read_session_preservation", identity="corrupt")
        self.assertFalse(failed.success)
        self.assertFalse(failed.payload["archival_confirmed"])
        self.assertEqual(audit.read_bytes(), before)

    async def test_closed_archive_rejects_new_persistence_without_mutating_preserved_products(self):
        await self.persist()
        self.preserve_session()
        closed = self.storage.close_session_evidence_archive("session")
        self.assertTrue(closed["archive_closed"])
        directory = self.root / "session_session"
        before = {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        rejected = await self.persist("late")
        self.assertFalse(rejected["durable_persistence_confirmed"])
        self.assertEqual(self.storage.read_envelopes(), (self.envelope,))
        self.assertEqual({str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()}, before)
        self.assertTrue((await self.persist())["durable_persistence_confirmed"])


if __name__ == "__main__":
    unittest.main()
