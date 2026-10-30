"""Service-owned terminal loss and monthly recovery using existing durable owners."""

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (InMemoryIngestor, PersistentStorageManager, RuntimeEvidenceMessage,
    RuntimeCommandMessage, RuntimeParticipant, ServiceMaintenanceInterface)


class ServiceDispositionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.journal = self.root / "framework.jsonl"
        self.month = patch("lab_sync_acquisition.storage.time", return_value=self.stamp(2026, 1))
        self.clock = self.month.start()
        self.addCleanup(self.month.stop)
        self.construct()

    @staticmethod
    def stamp(year, month):
        return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()

    def construct(self):
        self.storage = PersistentStorageManager(self.root / "archive")
        self.intake = InMemoryIngestor(self.storage, recovery_journal_root=self.root / "sessions",
                                      framework_recovery_journal_path=self.journal)
        settings = dict(ingestor=self.intake, storage_manager=self.storage, preservation_window_s=0,
                        close_resources=AsyncMock(return_value=True))
        self.storage_admin = ServiceMaintenanceInterface(self.storage, RuntimeParticipant("storage_manager", "storage"), **settings)
        self.intake_admin = ServiceMaintenanceInterface(self.intake, RuntimeParticipant("ingestor", "ingestor"), **settings)

    async def authorize(self, owner, operation, scope, *, loss=True, identity="command"):
        accepted = await owner.record_administrator_decision("operator", "resume", {
            "operation": operation, "obligation": scope, "command_id": identity,
            "permanent_loss_acknowledged": loss})
        return RuntimeCommandMessage(identity, None, operation, "operator", owner.participant.component_id,
            {"authorization_evidence_id": accepted["evidence"]["evidence_id"], "obligation": scope,
             "administrator_id": "operator"})

    def accept(self, identity):
        self.assertTrue(self.intake.receive_runtime_evidence(
            RuntimeEvidenceMessage(identity, None, "warning", "source", {}, True)).accepted)

    def archive(self):
        return self.storage.write_framework_evidence_archive(self.intake.compile_framework_runtime_evidence())

    def corrupt_journal(self):
        directory = self.root / "sessions"
        directory.mkdir(exist_ok=True)
        path = directory / "session_lost.jsonl"
        path.write_bytes(b'{"unrecoverable":true}\n')
        return path, {"session_id": "lost", "journal_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    async def test_disposal_requires_loss_acknowledgment_and_preserves_actual_loss(self):
        path, scope = self.corrupt_journal()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope, loss=False)
        rejected = await self.intake_admin.execute_command(command)
        self.assertFalse(rejected.success)
        self.assertTrue(path.exists())
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope, identity="dispose")
        result = await self.intake_admin.execute_command(command)
        self.assertTrue(result.success, result.reason)
        self.assertFalse(path.exists())
        self.assertEqual(result.payload["confirmation"]["disposition"], "disposed")
        self.assertFalse(result.payload["confirmation"]["preservation_succeeded"])
        self.assertTrue(result.payload["preservation"]["archival_confirmed"])
        self.assertEqual((await self.intake_admin.execute_command(command)).to_dict(), result.to_dict())
        saved = self.storage.get_framework_preservation_confirmation()
        self.assertTrue(any(r["payload"].get("actual_outcome") == "succeeded"
                            and r["payload"].get("operation") == "dispose_temporary_evidence" for r in saved["runtime_evidence"]))
        self.construct()
        with self.assertRaisesRegex(RuntimeError, "dispos"):
            self.intake.prepare_session("lost")

    async def test_unavailable_audit_and_changed_identity_never_destroy(self):
        path, scope = self.corrupt_journal()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope)
        original = path.read_bytes()
        with patch.object(self.intake, "has_durable_runtime_evidence", return_value=False):
            result = await self.intake_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(path.read_bytes(), original)
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope, identity="changed")
        path.write_bytes(original + b'{}\n')
        changed = path.read_bytes()
        result = await self.intake_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(path.read_bytes(), changed)

    async def test_drop_and_recoverable_tail_do_not_authorize_disposal(self):
        path, scope = self.corrupt_journal()
        await self.intake_admin.record_administrator_decision("operator", "drop", {"obligation": scope})
        self.assertTrue(path.exists())
        path.write_bytes(b'{"interrupted":')
        scope["journal_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope)
        result = await self.intake_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual(path.read_bytes(), b'{"interrupted":')

    def interrupt(self):
        self.accept("pending")
        original = self.storage._write_record_contents
        def partial(path, text, **kwargs):
            if path.name == "compilation_summary.json":
                path.write_bytes(b'{')
                raise OSError("Interrupted monthly summary")
            return original(path, text, **kwargs)
        with patch.object(self.storage, "_write_record_contents", partial), self.assertRaises(OSError):
            self.archive()
        records = self.intake.read_framework_write_records()
        return next(r for r in reversed(records) if r["kind"] == "intent")

    async def test_typed_intent_is_outside_compilation_and_completion_is_exact(self):
        self.accept("accepted")
        before = self.intake.compile_framework_runtime_evidence()
        self.archive()
        self.assertEqual(self.intake.compile_framework_runtime_evidence(), before)
        records = self.intake.read_framework_write_records()
        self.assertEqual([r["kind"] for r in records], ["intent", "completion"])
        self.assertEqual(records[0]["products"], records[1]["products"])
        self.assertEqual(records[0]["write_attempt_id"], records[1]["write_attempt_id"])

    async def test_intent_failure_prevents_any_target_mutation(self):
        self.accept("accepted")
        with patch.object(self.intake, "accept_framework_write_record", side_effect=OSError("Journal unavailable")), self.assertRaises(OSError):
            self.archive()
        self.assertFalse((self.root / "archive/framework/evidence").exists())

    async def test_same_month_and_fresh_owner_rollover_recovery(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                # Independent target months preserve all previously finalized bytes.
                self.clock.return_value = self.stamp(2026, 1 if not restart else 3)
                intent = self.interrupt()
                target = self.root / "archive/framework/evidence" / intent["target_month"]
                other = {str(p): p.read_bytes() for p in target.parent.rglob("*") if p.is_file() and p.parent != target}
                if restart:
                    self.construct()
                    self.clock.return_value = self.stamp(2026, 4)
                command = await self.authorize(self.storage_admin, "recover_archive_write",
                    {"session_id": None, "write_attempt_id": intent["write_attempt_id"]}, identity="repair-" + str(restart))
                result = await self.storage_admin.execute_command(command)
                self.assertTrue(result.success, result.reason)
                self.assertTrue(result.payload["confirmation"]["actual_write_confirmed"])
                self.assertEqual({p: Path(p).read_bytes() for p in other}, other)
                records = self.intake.read_framework_write_records()
                self.assertTrue(any(r["kind"] == "completion" and r["write_attempt_id"] == intent["write_attempt_id"] for r in records))

    async def test_conflicting_target_is_untouched_and_completed_partition_not_reopened(self):
        intent = self.interrupt()
        target = self.root / "archive/framework/evidence" / intent["target_month"]
        (target / "runtime_evidence.jsonl").write_bytes(b'unrelated corruption')
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
        result = await self.storage_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)

    @unittest.skipUnless(os.name == "nt", "Windows junctions require Windows")
    async def test_monthly_recovery_refuses_junction_targets_and_ancestors(self):
        for level in ("2026-01", "evidence", "framework"):
            for restart in (False, True):
                with self.subTest(level=level, restart=restart), tempfile.TemporaryDirectory() as temp:
                    self.root = Path(temp)
                    self.journal = self.root / "framework.jsonl"
                    self.construct()
                    intent = self.interrupt()
                    month = self.root / "archive/framework/evidence/2026-01"
                    target = next(p for p in (month, *month.parents) if p.name == level)
                    unrelated = self.root / "unrelated"
                    target.rename(unrelated)
                    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(unrelated)],
                                             capture_output=True, text=True)
                    self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
                    before = {p: p.read_bytes() for p in unrelated.rglob("*") if p.is_file()}
                    if restart:
                        self.construct()
                    command = await self.authorize(self.storage_admin, "recover_archive_write",
                        {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
                    result = await self.storage_admin.execute_command(command)
                    self.assertFalse(result.success, result.to_dict())
                    self.assertEqual({p: p.read_bytes() for p in before}, before)
                    self.assertFalse(any(r["kind"] == "completion" and
                        r["write_attempt_id"] == intent["write_attempt_id"]
                        for r in self.intake.read_framework_write_records()))

    @unittest.skipUnless(os.name == "nt", "Windows junctions require Windows")
    async def test_recovery_refuses_junction_created_before_original_target_exists(self):
        self.accept("pending")
        mkdir = Path.mkdir
        def interrupted(path, *args, **kwargs):
            if path.name == "2026-01":
                raise OSError("Interrupted before monthly target creation")
            return mkdir(path, *args, **kwargs)
        with patch.object(Path, "mkdir", interrupted), self.assertRaises(OSError):
            self.archive()
        intent = self.intake.read_framework_write_records()[0]
        target = self.root / "archive/framework/evidence/2026-01"
        target.parent.mkdir(parents=True, exist_ok=True)
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(unrelated)],
                                 capture_output=True, text=True)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.construct()
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
        result = await self.storage_admin.execute_command(command)
        self.assertFalse(result.success, result.to_dict())
        self.assertEqual(list(unrelated.iterdir()), [])

    async def test_monthly_recovery_refuses_hard_links_before_changing_any_product(self):
        for filename in ("runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"):
            for restart in (False, True):
                with self.subTest(filename=filename, restart=restart), tempfile.TemporaryDirectory() as temp:
                    self.root = Path(temp)
                    self.journal = self.root / "framework.jsonl"
                    self.construct()
                    intent = self.interrupt()
                    directory = self.root / "archive/framework/evidence/2026-01"
                    target = directory / filename
                    unrelated = self.root / "unrelated.jsonl"
                    unrelated.write_bytes(target.read_bytes())
                    target.unlink()
                    target.hardlink_to(unrelated)
                    before = {p: p.read_bytes() for p in directory.iterdir()}
                    original = unrelated.read_bytes()
                    if restart:
                        self.construct()
                    command = await self.authorize(self.storage_admin, "recover_archive_write",
                        {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
                    result = await self.storage_admin.execute_command(command)
                    self.assertFalse(result.success, result.to_dict())
                    self.assertEqual(unrelated.read_bytes(), original)
                    self.assertEqual({p: p.read_bytes() for p in before}, before)
                    self.assertFalse(any(r["kind"] == "completion" and
                        r["write_attempt_id"] == intent["write_attempt_id"]
                        for r in self.intake.read_framework_write_records()))

    async def test_aliased_monthly_products_cannot_confirm_or_authorize_an_append(self):
        for filename in ("runtime_evidence.jsonl", "ingest_audit.jsonl", "compilation_summary.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                self.journal = self.root / "framework.jsonl"
                self.construct()
                self.accept("preserved")
                self.archive()
                directory = self.root / "archive/framework/evidence/2026-01"
                target = directory / filename
                unrelated = self.root / "unrelated.jsonl"
                unrelated.hardlink_to(target)
                before = {p: p.read_bytes() for p in directory.iterdir()}
                self.assertIsNone(self.storage.get_framework_preservation_confirmation())
                self.accept("new")
                with self.assertRaises((RuntimeError, ValueError)):
                    self.archive()
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                self.assertEqual(unrelated.read_bytes(), before[target])

    async def test_monthly_recovery_refuses_symbolic_links(self):
        for directory_alias in (True, False):
            with self.subTest(directory_alias=directory_alias), tempfile.TemporaryDirectory() as temp:
                self.root = Path(temp)
                self.journal = self.root / "framework.jsonl"
                self.construct()
                intent = self.interrupt()
                directory = self.root / "archive/framework/evidence/2026-01"
                target = directory if directory_alias else directory / "compilation_summary.json"
                unrelated = self.root / "unrelated"
                target.rename(unrelated)
                try:
                    target.symlink_to(unrelated, target_is_directory=directory_alias)
                except OSError as error:
                    if os.name == "nt" and error.winerror == 1314:
                        self.skipTest("Windows symbolic-link creation privilege unavailable")
                    raise
                before = ({p: p.read_bytes() for p in unrelated.iterdir()} if directory_alias
                          else {unrelated: unrelated.read_bytes()})
                self.construct()
                command = await self.authorize(self.storage_admin, "recover_archive_write",
                    {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
                result = await self.storage_admin.execute_command(command)
                self.assertFalse(result.success, result.to_dict())
                self.assertEqual({p: p.read_bytes() for p in before}, before)

    async def test_completed_history_is_not_repaired(self):
        self.accept("complete")
        self.archive()
        intent = self.intake.read_framework_write_records()[0]
        target = self.root / "archive/framework/evidence/2026-01"
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        self.clock.return_value = self.stamp(2026, 2)
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
        result = await self.storage_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)

    async def test_working_copy_commitment_keeps_exact_readback_and_detects_damage(self):
        self.accept("preserved")
        paths = self.archive()
        before = {name: path.read_bytes() for name, path in paths.items()}
        saved = self.storage.get_framework_preservation_confirmation()
        self.assertEqual(saved["runtime_evidence"][0]["evidence_id"], "preserved")
        self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)
        paths["runtime_evidence"].write_bytes(b'{}\n')
        self.assertIsNone(self.storage.get_framework_preservation_confirmation())
        self.assertTrue(self.intake.has_durable_runtime_evidence(
            RuntimeEvidenceMessage("preserved", None, "warning", "source", {}, True)))

    async def test_disposal_outcome_audit_failure_retains_actual_disposition_and_retry_evidence(self):
        path, scope = self.corrupt_journal()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope)
        original = self.intake.receive_runtime_evidence
        def fail_outcome(message):
            if message.evidence_type == "service_recovery_evidence" and message.payload.get("actual_outcome") == "succeeded":
                raise OSError("Outcome journal unavailable")
            return original(message)
        with patch.object(self.intake, "receive_runtime_evidence", side_effect=fail_outcome), self.assertLogs(level="WARNING"):
            result = await self.intake_admin.execute_command(command)
        self.assertFalse(path.exists())
        self.assertEqual(result.payload["actual_outcome"], "succeeded")
        self.assertFalse(result.payload["preservation"]["acceptance_confirmed"])
        self.assertTrue(any(m.payload.get("actual_outcome") == "succeeded" for m in self.intake_admin.required_evidence()))
        self.construct()
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.intake.prepare_session("lost")

    async def test_missing_intent_and_wrong_authorization_refuse_without_mutation(self):
        self.accept("complete")
        paths = self.archive()
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": "not-recorded"})
        result = await self.storage_admin.execute_command(command)
        self.assertFalse(result.success)
        # Recording the refusal may append current evidence, but cannot repair the identified products.
        self.assertTrue(all(path.exists() for path in paths.values()))
        path, scope = self.corrupt_journal()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope, identity="authorized")
        changed = RuntimeCommandMessage("different", None, command.command_type, command.source_id,
            command.target_id, command.payload)
        result = await self.intake_admin.execute_command(changed)
        self.assertFalse(result.success)
        self.assertTrue(path.exists())

    async def test_completion_failure_reconciles_exact_products_after_restart(self):
        self.accept("complete-but-unconfirmed")
        original = self.intake.accept_framework_write_record
        def fail_completion(record):
            if record["kind"] == "completion":
                raise OSError("Completion acknowledgment unavailable")
            return original(record)
        with patch.object(self.intake, "accept_framework_write_record", side_effect=fail_completion), self.assertRaises(OSError):
            self.archive()
        target = self.root / "archive/framework/evidence/2026-01"
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        self.construct()
        self.clock.return_value = self.stamp(2026, 2)
        self.intake.continue_framework_evidence_archive()
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)
        records = self.intake.read_framework_write_records()
        self.assertTrue(any(r["kind"] == "completion" and r["write_attempt_id"] == records[0]["write_attempt_id"] for r in records))

    async def test_intent_without_created_target_can_be_recovered_explicitly(self):
        self.accept("before-creation")
        original = Path.mkdir
        def fail_month(path, *args, **kwargs):
            if path.name == "2026-01":
                raise OSError("Interrupted before target creation")
            return original(path, *args, **kwargs)
        with patch.object(Path, "mkdir", fail_month), self.assertRaises(OSError):
            self.archive()
        intent = self.intake.read_framework_write_records()[0]
        self.construct()
        self.clock.return_value = self.stamp(2026, 2)
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
        result = await self.storage_admin.execute_command(command)
        self.assertTrue(result.success, result.reason)

    async def test_working_copy_cleanup_preserves_duplicate_and_pending_publication(self):
        self.accept("retained")
        self.archive()
        message = RuntimeEvidenceMessage("retained", None, "warning", "source", {}, True)
        self.assertEqual(self.intake.receive_runtime_evidence(message).reason, "already_accepted")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.intake.receive_runtime_evidence(
                RuntimeEvidenceMessage("retained", None, "warning", "source", {"conflicting": True}, True))
        async def unavailable(_):
            raise OSError("Transport unavailable")
        self.storage_admin.evidence_publisher = unavailable
        with self.assertLogs(level="WARNING"):
            await self.storage_admin.announce_readiness(startup=True)
        self.archive()
        self.assertTrue(self.storage_admin.required_evidence())

    async def test_disposal_uses_existing_administrator_command_transport(self):
        from lab_sync_acquisition import NatsControllerCommunication, NatsServiceMaintenanceCommunication, NatsIngestorCommunication
        from tests.test_session_launch import _Boundary, _Broker
        path, scope = self.corrupt_journal()
        command = await self.authorize(self.intake_admin, "dispose_temporary_evidence", scope)
        broker = _Broker()
        evidence = NatsIngestorCommunication(_Boundary("ingestor", "intake", broker), self.intake)
        self.addAsyncCleanup((await evidence.subscribe_evidence(None)).unsubscribe)
        receiver = NatsServiceMaintenanceCommunication(_Boundary("ingestor", "ingestor", broker), self.intake_admin)
        for subscription in await receiver.subscribe_commands():
            self.addAsyncCleanup(subscription.unsubscribe)
        issuer = NatsControllerCommunication(_Boundary("terminal", "operator", broker))
        self.addAsyncCleanup((await issuer.subscribe_command_results(None)).unsubscribe)
        result = await issuer.request_command(self.intake_admin.participant, command.command_type, None,
            command.payload, 1, command_id=command.command_id)
        self.assertTrue(result.success, result.reason)
        self.assertFalse(path.exists())

    async def test_malformed_or_conflicting_write_proof_cannot_authorize_target_changes(self):
        intent = self.interrupt()
        target = self.root / "archive/framework/evidence/2026-01"
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        for changes in ({"products": {}}, {"before": {}}, {"evidence_end": None}, {"audit_fingerprint": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.intake.accept_framework_write_record({**intent, **changes, "write_attempt_id": "malformed"})
        # Conflicting durable proof is retained for diagnosis, never silently repaired.
        conflict = deepcopy(intent)
        conflict.update(write_attempt_id="conflicting-attempt", storage_id="another-storage")
        self.intake.accept_framework_write_record(conflict)
        command = await self.authorize(self.storage_admin, "recover_archive_write",
            {"session_id": None, "write_attempt_id": intent["write_attempt_id"]})
        result = await self.storage_admin.execute_command(command)
        self.assertFalse(result.success)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)
