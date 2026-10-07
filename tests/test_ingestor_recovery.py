import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_sync_acquisition import InMemoryIngestor, NatsIngestorCommunication, RuntimeEvidenceMessage
from tests import test_local_storage_hdf5 as hdf5_tests


class IngestorRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "recovery.jsonl"

    def ingestor(self, path=None):
        return InMemoryIngestor(session_id="session", recovery_journal_path=path or self.path,
                               component_id="ingestor-test")

    def message(self, identity="evidence", persistent=False, payload=None):
        return RuntimeEvidenceMessage(identity, "session", "test_evidence", "node",
                                      payload or {"value": 1}, persistent)

    async def receiver(self, ingestor, callback=None):
        callbacks = []

        async def subscribe(subject, cb, **options):
            self.assertEqual(subject, "messages.session.evidence.>")
            self.assertTrue(options["manual_ack"])
            callbacks.append(cb)
            return subject

        boundary = SimpleNamespace(_require_jetstream=lambda: SimpleNamespace(subscribe=subscribe))
        await NatsIngestorCommunication(boundary, ingestor).subscribe_evidence("session", callback)
        return callbacks[0]

    def delivery(self, message, ack=None):
        return SimpleNamespace(data=json.dumps(message.to_dict()).encode(), ack=ack or AsyncMock())

    def entries(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    async def test_all_evidence_is_durable_before_working_state_and_broker_ack(self):
        ingestor = self.ingestor()
        receive = await self.receiver(ingestor)
        events = []
        real_fsync = os.fsync
        for index, persistent in enumerate((False, True)):
            message = self.message(str(index), persistent)

            def sync(descriptor):
                self.assertEqual(len(ingestor.accepted_runtime_evidence), index)
                self.assertEqual(events, [])
                real_fsync(descriptor)
                events.append("durable")

            async def ack():
                self.assertEqual(events, ["durable"])
                self.assertEqual(self.entries()[-1], message.to_dict())
                self.assertEqual(ingestor.accepted_runtime_evidence[-1], message)
                events.append("ack")

            with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=sync):
                await receive(self.delivery(message, AsyncMock(side_effect=ack)))
            self.assertEqual(events, ["durable", "ack"])
            events.clear()
        self.assertEqual(len(self.entries()), 2)
        self.assertEqual(len(ingestor.compile_persistent_runtime_evidence()["runtime_evidence"]), 1)

    async def test_fsync_failure_prevents_acceptance_and_ack(self):
        ingestor = self.ingestor()
        receive = await self.receiver(ingestor)
        delivered = self.delivery(self.message())
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("durability unavailable")):
            with self.assertRaisesRegex(OSError, "durability unavailable"):
                await receive(delivered)
        delivered.ack.assert_not_awaited()
        self.assertEqual(ingestor.accepted_runtime_evidence, ())
        self.assertFalse(ingestor.check_ready().ready)
        with self.assertRaisesRegex(RuntimeError, "restart"):
            ingestor.receive_runtime_evidence(self.message("later"))

    async def test_complete_record_survives_reported_fsync_failure_and_restart_deduplicates(self):
        first = self.ingestor()
        callback = AsyncMock()
        receive = await self.receiver(first, callback)
        evidence = self.message("uncertain-durability")
        delivered = self.delivery(evidence)
        real_fsync = os.fsync

        def report_failure_after_sync(descriptor):
            real_fsync(descriptor)
            raise OSError("reported durability failure after real fsync")

        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=report_failure_after_sync):
            with self.assertRaisesRegex(OSError, "reported durability failure after real fsync"):
                await receive(delivered)

        delivered.ack.assert_not_awaited()
        callback.assert_not_awaited()
        self.assertEqual(first.accepted_runtime_evidence, ())
        self.assertEqual(first.runtime_evidence_audit, ())
        self.assertFalse(first.check_ready().ready)
        journal_before_restart = self.path.read_bytes()
        self.assertTrue(journal_before_restart.endswith(b"\n"))
        self.assertEqual(self.entries(), [evidence.to_dict()])

        subsequent = self.delivery(self.message("later"))
        with self.assertRaisesRegex(RuntimeError, "restart"):
            await receive(subsequent)
        subsequent.ack.assert_not_awaited()
        callback.assert_not_awaited()
        self.assertEqual(first.accepted_runtime_evidence, ())
        self.assertEqual(first.runtime_evidence_audit, ())
        self.assertEqual(self.path.read_bytes(), journal_before_restart)

        restored = self.ingestor()
        self.assertTrue(restored.check_ready().ready)
        self.assertEqual(restored.accepted_runtime_evidence[0], evidence)
        recovery = restored.accepted_runtime_evidence[1]
        self.assertEqual(recovery.evidence_type, "ingestor_recovery_evidence")
        self.assertTrue(recovery.is_persistent)
        self.assertEqual(recovery.payload["recovered_entry_count"], 1)
        self.assertEqual(self.entries(), [evidence.to_dict(), recovery.to_dict()])
        self.assertEqual(
            restored.compile_persistent_runtime_evidence()["runtime_evidence"], (recovery,)
        )

        receive = await self.receiver(restored, callback)
        journal_before_redelivery = self.path.read_bytes()
        accepted_before_redelivery = restored.accepted_runtime_evidence
        redelivered = self.delivery(evidence)
        await receive(redelivered)
        redelivered.ack.assert_awaited_once()
        callback.assert_not_awaited()
        self.assertEqual(restored.runtime_evidence_audit[-1].reason, "already_accepted")
        self.assertEqual(restored.accepted_runtime_evidence, accepted_before_redelivery)
        self.assertEqual(self.path.read_bytes(), journal_before_redelivery)
        self.assertEqual(
            sum(item.evidence_id == evidence.evidence_id for item in restored.accepted_runtime_evidence), 1
        )

    async def test_append_open_failure_prevents_acceptance_and_ack(self):
        ingestor = self.ingestor()
        receive = await self.receiver(ingestor)
        delivered = self.delivery(self.message())
        with patch("lab_sync_acquisition.ingestor.Path.open", side_effect=PermissionError("journal unavailable")):
            with self.assertRaises(PermissionError):
                await receive(delivered)
        delivered.ack.assert_not_awaited()
        self.assertEqual(ingestor.accepted_runtime_evidence, ())
        self.assertEqual(self.entries(), [])

    async def test_restart_restores_persistent_and_nonpersistent_evidence(self):
        first = self.ingestor()
        messages = (self.message("transient"), self.message("persistent", True))
        for message in messages:
            first.receive_runtime_evidence(message)
        restored = self.ingestor()
        self.assertEqual(restored.accepted_runtime_evidence[:2], messages)
        persistent = restored.compile_persistent_runtime_evidence()["runtime_evidence"]
        self.assertEqual(persistent[0], messages[1])
        self.assertEqual(persistent[1].evidence_type, "ingestor_recovery_evidence")
        self.assertNotIn(messages[0], persistent)

    async def test_restored_view_reuses_unchanged_artifact_handoff_compiler(self):
        writer = hdf5_tests.HDF5ScientificPersistenceTests()
        local = writer.manager(self.root / "local")
        initial = writer.stream(local)
        finalized = local.finalize_all().manifests[0]
        first = self.ingestor()
        for index, manifest in enumerate((initial, finalized)):
            first.receive_runtime_evidence(RuntimeEvidenceMessage(str(index), "session", "artifact_manifest",
                                                                  "node", manifest.to_dict(), True))
        before = first.compile_artifact_collection_handoff("session")
        restored = self.ingestor()
        self.assertEqual(restored.compile_artifact_collection_handoff("session"), before)
        self.assertEqual(len(before["artifacts"]), 1)
        self.assertEqual(before["artifacts"][0]["artifact_manifest"], finalized.to_dict())

    async def test_identical_redelivery_is_acked_without_duplicate_journal_or_state(self):
        ingestor = self.ingestor()
        callback = AsyncMock()
        receive = await self.receiver(ingestor, callback)
        message = self.message()
        await receive(self.delivery(message))
        original = self.path.read_bytes()
        delivered = self.delivery(message)
        await receive(delivered)
        delivered.ack.assert_awaited_once()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(ingestor.accepted_runtime_evidence, (message,))
        callback.assert_awaited_once_with(message)

    async def test_conflicting_redelivery_is_not_acked_or_accepted(self):
        ingestor = self.ingestor()
        ingestor.receive_runtime_evidence(self.message())
        original = self.path.read_bytes()
        receive = await self.receiver(ingestor)
        delivered = self.delivery(self.message(payload={"value": 2}))
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            await receive(delivered)
        delivered.ack.assert_not_awaited()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(ingestor.accepted_runtime_evidence, (self.message(),))

    async def test_crash_after_journal_before_ack_reconstructs_and_deduplicates(self):
        first = self.ingestor()
        receive = await self.receiver(first)
        message = self.message()
        with self.assertRaisesRegex(OSError, "crash before ACK"):
            await receive(self.delivery(message, AsyncMock(side_effect=OSError("crash before ACK"))))
        restored = self.ingestor()
        receive = await self.receiver(restored)
        before = self.path.read_bytes()
        delivered = self.delivery(message)
        await receive(delivered)
        delivered.ack.assert_awaited_once()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sum(item.evidence_id == message.evidence_id for item in restored.accepted_runtime_evidence), 1)

    async def test_truncated_final_append_is_omitted_and_redelivery_repair_is_recoverable(self):
        first = self.ingestor()
        first.receive_runtime_evidence(self.message("complete"))
        with self.path.open("ab") as journal:
            journal.write(b'{"evidence_id":"unfinished')
        restored = self.ingestor()
        self.assertEqual(restored.accepted_runtime_evidence[0], self.message("complete"))
        receive = await self.receiver(restored)
        await receive(self.delivery(self.message("unfinished")))
        again = self.ingestor()
        self.assertEqual(sum(item.evidence_id == "unfinished" for item in again.accepted_runtime_evidence), 1)

    async def test_corrupt_earlier_entry_fails_startup_without_journal_rewrite(self):
        valid = json.dumps(self.message().to_dict()).encode() + b"\n"
        self.path.write_bytes(valid + b"not-json\n" + valid)
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "corrupt completed"):
            self.ingestor()
        self.assertEqual(self.path.read_bytes(), original)

    async def test_malformed_completed_final_entry_is_not_treated_as_interrupted(self):
        self.path.write_bytes(b'{"unfinished":\n')
        with self.assertRaises(ValueError):
            self.ingestor()

    async def test_conflicting_journal_identity_fails_reconstruction(self):
        self.path.write_text(json.dumps(self.message().to_dict()) + "\n" +
                             json.dumps(self.message(payload={"value": 2}).to_dict()) + "\n")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.ingestor()

    async def test_recovery_evidence_uses_normal_journal_and_persistent_compilation(self):
        self.ingestor().receive_runtime_evidence(self.message())
        restored = self.ingestor()
        evidence = restored.accepted_runtime_evidence[-1]
        self.assertEqual(evidence.evidence_type, "ingestor_recovery_evidence")
        self.assertEqual(evidence.source_id, "ingestor-test")
        self.assertEqual(evidence.session_id, "session")
        self.assertEqual(set(evidence.payload), {"recovered_entry_count", "recovery_time"})
        self.assertEqual(evidence.payload["recovered_entry_count"], 1)
        self.assertTrue(evidence.is_persistent)
        self.assertEqual(self.entries()[-1], evidence.to_dict())
        self.assertIn(evidence, restored.compile_persistent_runtime_evidence()["runtime_evidence"])

    async def test_wrong_session_cannot_enter_journal_or_be_acked(self):
        ingestor = self.ingestor()
        receive = await self.receiver(ingestor)
        message = RuntimeEvidenceMessage("id", "wrong-session", "kind", "node", {})
        delivered = self.delivery(message)
        with self.assertRaisesRegex(ValueError, "Session"):
            await receive(delivered)
        delivered.ack.assert_not_awaited()
        self.assertEqual(self.entries(), [])

    async def test_broker_subscription_requires_matching_recovery_configuration(self):
        for ingestor, session in ((InMemoryIngestor(), "session"), (self.ingestor(), "wrong-session")):
            boundary = SimpleNamespace(_require_jetstream=lambda: None)
            with self.assertRaisesRegex(ValueError, "recovery journal"):
                await NatsIngestorCommunication(boundary, ingestor).subscribe_evidence(session)

    async def test_complete_final_entry_without_newline_remains_recoverable(self):
        self.path.write_text(json.dumps(self.message().to_dict()))
        self.assertEqual(self.ingestor().accepted_runtime_evidence[0], self.message())
        self.assertEqual(len(self.entries()), 2)

    async def test_truncated_utf8_final_string_is_not_a_completed_entry(self):
        self.path.write_bytes(b'{"evidence_id":"partial\xe2\x82')
        restored = self.ingestor()
        self.assertEqual(len(restored.accepted_runtime_evidence), 1)
        self.assertEqual(restored.accepted_runtime_evidence[0].payload["recovered_entry_count"], 0)

    async def test_invalid_final_syntax_is_not_silently_skipped(self):
        self.path.write_bytes(b'{"value":bad}')
        with self.assertRaises(ValueError):
            self.ingestor()

    async def test_numeric_suffix_after_completed_string_fails_recovery(self):
        base = json.dumps(self.message("complete").to_dict()).encode() + b"\n"
        complete = json.dumps(self.message("corrupt").to_dict(), sort_keys=True,
                              separators=(",", ":")).encode()
        for suffix in (b".", b".5", b"e", b"e+", b"e-", b"e2", b"e+2", b"e-2"):
            with self.subTest(suffix=suffix):
                journal = base + complete[:-1] + suffix
                self.path.write_bytes(journal)
                with self.assertRaisesRegex(ValueError, "corrupt completed"):
                    self.ingestor()
                # Failed startup must neither repair corruption nor append recovery evidence.
                self.assertEqual(self.path.read_bytes(), journal)

    async def test_numeric_suffix_after_other_completed_values_fails_recovery(self):
        base = json.dumps(self.message("complete").to_dict()).encode() + b"\n"
        for value, suffixes in (
            ("true", (".", "e+")),
            ("false", (".5", "E-")),
            ("null", (".", "e2")),
            ("{}", (".", "e+")),
            ("[]", (".", "e-")),
            ("1.25", (".", ".2")),
            ("1e2", (".", "e+", "E-")),
            ("1 ", (".", "e+")),
        ):
            for suffix in suffixes:
                with self.subTest(value=value, suffix=suffix):
                    journal = base + ('{"payload":{"value":' + value + suffix).encode()
                    self.path.write_bytes(journal)
                    with self.assertRaisesRegex(ValueError, "corrupt completed"):
                        self.ingestor()
                    self.assertEqual(self.path.read_bytes(), journal)

    async def test_truncated_final_numeric_tokens_recover_prior_entry(self):
        base = json.dumps(self.message("complete").to_dict()).encode() + b"\n"
        complete = json.dumps(self.message("partial", payload={"value": 1.25}).to_dict(),
                              sort_keys=True, separators=(",", ":"))
        prefix = complete[:complete.index('"value":') + len('"value":')]
        for number in ("-", "0.", "1.", "-1.", "1e", "1e+", "1e-", "0E+",
                       "-1.25e", "-1.25e+", "-1.25e-", "1.25", "1e2"):
            for container in ("", "["):
                with self.subTest(number=number, container=container):
                    self.path.write_bytes(base + (prefix + container + number).encode())
                    restored = self.ingestor()
                    self.assertEqual(restored.accepted_runtime_evidence[0], self.message("complete"))
                    recovery = restored.accepted_runtime_evidence[1]
                    self.assertEqual(recovery.evidence_type, "ingestor_recovery_evidence")
                    self.assertEqual(recovery.payload["recovered_entry_count"], 1)
                    self.assertEqual(self.entries(), [self.message("complete").to_dict(),
                                                     recovery.to_dict()])

    async def test_numeric_tail_corruption_with_newline_fails_recovery(self):
        base = json.dumps(self.message("complete").to_dict()).encode() + b"\n"
        for value in ('"node".', '"node"e+', "1.", "1e+"):
            with self.subTest(value=value):
                journal = base + ('{"payload":{"value":' + value + "\n").encode()
                self.path.write_bytes(journal)
                with self.assertRaisesRegex(ValueError, "corrupt completed"):
                    self.ingestor()
                self.assertEqual(self.path.read_bytes(), journal)

    async def test_interrupted_final_message_at_every_byte_boundary_recovers_prior_entry(self):
        base = json.dumps(self.message("complete").to_dict()).encode() + b"\n"
        partial = json.dumps(self.message("partial", payload={
            "flag": False, "empty": None, "number": -1.25e-20, "text": "\u2603"
        }).to_dict()).encode()
        for offset in range(1, len(partial)):
            with self.subTest(offset=offset):
                self.path.write_bytes(base + partial[:offset])
                restored = self.ingestor()
                self.assertEqual(restored.accepted_runtime_evidence[0], self.message("complete"))
                self.assertEqual(restored.accepted_runtime_evidence[-1].payload["recovered_entry_count"], 1)

    async def test_recovery_evidence_append_failure_prevents_successful_startup(self):
        self.ingestor().receive_runtime_evidence(self.message())
        with patch("lab_sync_acquisition.ingestor.os.fsync", side_effect=OSError("recovery evidence write failed")):
            with self.assertRaisesRegex(OSError, "recovery evidence write failed"):
                self.ingestor()


if __name__ == "__main__":
    unittest.main()
