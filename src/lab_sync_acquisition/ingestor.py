"""Operational runtime evidence intake and known-Session journal recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from threading import RLock
from time import time
from typing import Any
from uuid import uuid4

from lab_sync_acquisition.communication import ARTIFACT_MANIFEST_EVIDENCE_TYPE, RuntimeEvidenceMessage
from lab_sync_acquisition.local_storage import ArtifactManifest
from lab_sync_acquisition.service_readiness import ServiceReadiness, apply_dependency_readiness
from lab_sync_acquisition.service_maintenance import service_operation
from lab_sync_acquisition.storage import (
    PersistentStorageManager,
)


@dataclass(frozen=True)
class RuntimeEvidenceAuditRecord:
    """Audit evidence for one received durable runtime evidence message."""

    ingest_order: int
    ingest_received_at: float
    evidence_id: str
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return plain runtime evidence intake audit data."""

        return {
            "ingest_order": self.ingest_order,
            "ingest_received_at": self.ingest_received_at,
            "evidence_id": self.evidence_id,
            "accepted": self.accepted,
            "reason": self.reason,
        }


class InMemoryIngestor:
    """Receives operational evidence, with explicit known-Session recovery."""

    def __init__(
        self,
        storage_manager: PersistentStorageManager | None = None,
        *,
        session_id: str | None = None,
        recovery_journal_path: str | Path | None = None,
        component_id: str = "ingestor",
        recovery_journal_root: str | Path | None = None,
        framework_recovery_journal_path: str | Path | None = None,
        evidence_scope: str = "session",
    ) -> None:
        if evidence_scope not in {"session", "framework"}:
            raise ValueError("Unknown runtime evidence scope")
        if evidence_scope == "framework" and session_id is not None:
            raise ValueError("Framework intake must not create a Session binding")
        if evidence_scope == "session" and (session_id is None) != (recovery_journal_path is None):
            raise ValueError("Session identity and recovery journal path must be supplied together")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("Ingestor component_id must be a nonempty string")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError("Recovery requires a nonempty known Session identity")
        self._storage_manager = storage_manager
        self._service_operation_lock = RLock()
        self._active_service_operations = 0
        self._evidence_scope = evidence_scope
        self._framework_ingestor = None
        self._intake_lock = RLock()
        self._recovery_journal_root = Path(recovery_journal_root) if recovery_journal_root is not None else None
        self._session_prepared = session_id is not None
        self._requires_prepared_session = session_id is not None or recovery_journal_root is not None
        self._session_id = session_id
        self._kill_handoff_required = False
        self._finalized_intake = None
        self._component_id = component_id
        self._recovery_journal_path = (
            Path(recovery_journal_path) if recovery_journal_path is not None else None
        )
        self._journal_failed = False
        self._accepted_evidence_content: dict[str, str] = {}
        self._durable_evidence_waiters = {}
        self._accepted_runtime_evidence: tuple[RuntimeEvidenceMessage, ...] = ()
        self._runtime_evidence_audit: tuple[RuntimeEvidenceAuditRecord, ...] = ()
        if evidence_scope == "framework" and self._recovery_journal_path is not None:
            self._recovery_journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_recovery_journal()
        if framework_recovery_journal_path is not None:
            self.prepare_framework_evidence(framework_recovery_journal_path)

    @service_operation(new_work=True)
    def prepare_framework_evidence(self, recovery_journal_path: str | Path) -> None:
        """Configure deployment-scoped journal-backed intake without a Session binding."""
        with self._intake_lock:
            if self._evidence_scope != "session" or self._framework_ingestor is not None:
                raise RuntimeError("Framework evidence intake is already configured")
            self._framework_ingestor = InMemoryIngestor(
                self._storage_manager, component_id=self._component_id,
                recovery_journal_path=recovery_journal_path, evidence_scope="framework",
            )

    def compile_framework_runtime_evidence(self) -> dict[str, tuple]:
        """Compile persistent framework messages and all their intake audit records."""
        if self._framework_ingestor is None:
            raise RuntimeError("Framework recovery journal is not configured")
        return self._framework_ingestor.compile_persistent_runtime_evidence()

    def continue_framework_evidence_archive(self):
        """Reconcile recovered journal-backed compilation through paired StorageManager."""
        intake = self._framework_ingestor
        if intake is None or self._storage_manager is None:
            raise RuntimeError("Framework journal and paired StorageManager are required")
        with self._intake_lock, intake._intake_lock:
            if intake._journal_failed or intake._recovery_journal_path is None:
                raise RuntimeError("Framework journal integrity is unconfirmed")
            evidence, audits = {}, []
            with intake._recovery_journal_path.open("rb") as journal:
                before = os.fstat(journal.fileno())
                for line in journal:
                    entry = json.loads(line)
                    audits.append(entry["ingest_audit"])
                    if entry["runtime_evidence"] is not None:
                        message = RuntimeEvidenceMessage.from_dict(entry["runtime_evidence"])
                        content = intake._evidence_content(message)
                        if (not entry["ingest_audit"]["accepted"]
                                or entry["ingest_audit"]["evidence_id"] != message.evidence_id
                                or evidence.get(message.evidence_id, content) != content):
                            raise ValueError("Framework journal has inconsistent evidence or audit")
                        evidence.setdefault(message.evidence_id, content)
                    elif entry["ingest_audit"]["accepted"]:
                        raise ValueError("Framework journal acceptance lacks evidence")
                after = os.fstat(journal.fileno())
                current = intake._recovery_journal_path.stat()
            if (list(evidence.items()) != list(intake._accepted_evidence_content.items())
                    or audits != [item.to_dict() for item in intake._runtime_evidence_audit]
                    or any(getattr(before, name) != getattr(after, name)
                           or getattr(before, name) != getattr(current, name)
                           for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns"))):
                raise RuntimeError("Recovered framework compilation differs from current durable journal")
            compiled = self.compile_framework_runtime_evidence()
            confirmation = self._storage_manager.continue_framework_evidence_archive(compiled)
            if confirmation is not None:
                with self.framework_preservation_guard(self._storage_manager):
                    pass
            return confirmation

    async def await_durable_runtime_evidence(self, evidence: RuntimeEvidenceMessage, timeout_s: float) -> bool:
        """Boundedly observe exact journal-backed acceptance without polling or transport acknowledgments."""
        from math import isfinite
        if not isinstance(timeout_s, (int, float)) or not isfinite(timeout_s) or timeout_s < 0:
            raise ValueError("Acceptance window must be finite and nonnegative")
        if evidence.session_id is None and self._evidence_scope == "session":
            if self._framework_ingestor is None:
                raise RuntimeError("Framework recovery journal is not configured")
            return await self._framework_ingestor.await_durable_runtime_evidence(evidence, timeout_s)
        content = self._evidence_content(evidence)
        future = asyncio.get_running_loop().create_future()
        with self._intake_lock:
            if self.has_durable_runtime_evidence(evidence):
                return True
            if self._journal_failed or self._recovery_journal_path is None:
                return False
            entries = self._durable_evidence_waiters.setdefault(evidence.evidence_id, [])
            entry = (content, future)
            entries.append(entry)
        try:
            await asyncio.wait_for(future, timeout_s)
            return self.has_durable_runtime_evidence(evidence)
        except TimeoutError:
            return False
        finally:
            with self._intake_lock:
                entries.remove(entry)
                if not entries:
                    self._durable_evidence_waiters.pop(evidence.evidence_id, None)

    @staticmethod
    def _confirm_acceptance_future(future):
        if not future.done():
            future.set_result(True)

    @contextmanager
    def framework_preservation_guard(self, storage_manager: PersistentStorageManager):
        """Hold intake and storage steady while checking complete framework archival."""
        intake = self._framework_ingestor
        if intake is None:
            raise RuntimeError("Framework recovery journal is not configured")
        with intake._intake_lock, storage_manager.framework_preservation_guard() as confirmation:
            compiled = intake.compile_persistent_runtime_evidence()
            if (intake._journal_failed or confirmation is None
                    or any(confirmation[name] != [item.to_dict() for item in compiled[name]]
                           for name in ("runtime_evidence", "ingest_audit"))):
                raise RuntimeError("Current framework intake is not durably archived")
            yield confirmation

    @service_operation()
    async def preserve_service_evidence(self, messages, source_id, acceptance_window_s):
        """Confirm a producer boundary using authoritative journals and paired storage."""
        messages = tuple(RuntimeEvidenceMessage.from_dict(m) for m in messages)
        if (not messages or any(m.source_id != source_id or not m.is_persistent for m in messages)
                or len({(m.session_id, m.evidence_id) for m in messages}) != len(messages)):
            raise ValueError("A unique persistent evidence boundary for the requesting producer is required")
        storage = self._storage_manager
        if storage is None or self._framework_ingestor is None:
            raise RuntimeError("Framework journal and paired StorageManager are required")
        for message in messages:
            if message.session_id is None:
                if not await self.await_durable_runtime_evidence(message, acceptance_window_s):
                    raise RuntimeError("Producer framework evidence lacks journal-backed acceptance")
            else:
                # Session products remain immutable; this operation cannot repair or
                # append to their Stage A baseline or collect scientific artifacts.
                self.read_session_closeout(message.session_id)
                saved = storage.get_persisted_session_preservation_confirmation(message.session_id)
                if (saved is None or message.to_dict() not in saved["runtime_evidence"]
                        or message.evidence_id not in saved["compilation_summary"]["runtime_evidence_origins"]["ingestor"]):
                    raise RuntimeError("Producer Session evidence lacks verified Stage A preservation")
        intake = self._framework_ingestor
        with self._intake_lock, intake._intake_lock, storage._preservation_lock:
            if not storage._framework_evidence_write_safe():
                raise RuntimeError("Framework archive requires authorized recovery")
            if any(not self.has_durable_runtime_evidence(m) for m in messages if m.session_id is None):
                raise RuntimeError("Framework journal changed during boundary verification")
            compiled = self.compile_framework_runtime_evidence()
            current = storage.get_framework_preservation_confirmation()
            if current is None or any(current[name] != [m.to_dict() for m in compiled[name]]
                                      for name in ("runtime_evidence", "ingest_audit")):
                storage.write_framework_evidence_archive(compiled)
            with self.framework_preservation_guard(storage) as archive:
                if any(m.to_dict() not in archive["runtime_evidence"] for m in messages if m.session_id is None):
                    raise RuntimeError("Framework preservation does not cover the producer boundary")
                return {"acceptance_confirmed": True, "archival_confirmed": True,
                        "evidence": [m.to_dict() for m in messages],
                        "storage_participant": {"component_type": "storage_manager", "component_id": storage._component_id}}

    def _initialize_recovery_journal(self) -> None:
        if self._recovery_journal_path is not None:
            if self._recovery_journal_path.exists():
                self._restore_runtime_evidence()
                if self._finalized_intake is not None:
                    return
                self.receive_runtime_evidence(
                    RuntimeEvidenceMessage(
                        evidence_id=uuid4().hex,
                        session_id=self._session_id,
                        evidence_type="ingestor_recovery_evidence",
                        source_id=self._component_id,
                        payload={
                            "recovered_entry_count": len(self._accepted_runtime_evidence),
                            "recovery_time": time(),
                        },
                        is_persistent=True,
                    )
                )
            else:
                with self._recovery_journal_path.open("xb") as journal:
                    journal.flush()
                    os.fsync(journal.fileno())
                self._sync_journal_directory()

    @property
    def session_id(self) -> str | None:
        """Known Session identity for journal-backed runtime evidence intake."""

        return self._session_id

    @service_operation(new_work=True)
    def prepare_session(self, session_id: str) -> ServiceReadiness:
        """Prepare known-Session intake using deployment-local journal configuration."""
        with self._intake_lock:
            if self._evidence_scope != "session":
                raise RuntimeError("Framework intake has no Session binding")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Session preparation requires a real Session identity")
            if self._session_id == session_id:
                if self._journal_failed or self._recovery_journal_path is None:
                    raise RuntimeError("Session journal is not ready")
                self._session_prepared = True
                return self.check_ready()
            if self._session_id is not None or self._accepted_runtime_evidence:
                raise RuntimeError("Ingestor already has Session evidence/binding")
            if self._recovery_journal_root is None:
                raise ValueError("Ingestor deployment recovery journal root is not configured")
            self._recovery_journal_root.mkdir(parents=True, exist_ok=True)
            self._session_id = session_id
            self._recovery_journal_path = self._recovery_journal_root / f"session_{session_id}.jsonl"
            self._requires_prepared_session = True
            self._session_prepared = True
            try:
                self._initialize_recovery_journal()
            except Exception:
                self._session_prepared = False
                self._journal_failed = True
                raise
            return self.check_ready()

    @service_operation()
    def abort_session_initialization(self, session_id: str) -> bool:
        """Stop prepared intake without deleting accepted evidence or journal history."""
        with self._intake_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Initialization abort requires session_id")
            if self._session_id not in {None, session_id}:
                raise RuntimeError("Initialization abort does not match Ingestor Session")
            self._session_prepared = False
            if not self._accepted_runtime_evidence and not self._kill_handoff_required:
                self._session_id = None
                self._recovery_journal_path = None
            return True

    def _require_kill_handoff(self, session_id: str) -> None:
        """Retain an admitted Kill's handoff obligation independently of archive success."""
        with self._intake_lock:
            if self._session_id != session_id:
                raise RuntimeError("Kill handoff obligation does not match Ingestor Session")
            self._kill_handoff_required = True

    def admit_kill_closeout(self, session_id: str) -> None:
        """Durably retain Kill preservation obligations before participant shutdown."""
        with self._intake_lock:
            if self._session_id != session_id or self._finalized_intake is not None:
                raise RuntimeError("Kill admission requires the current unfinalized Session")
            if not self._kill_handoff_required:
                if self._recovery_journal_path is None:
                    raise RuntimeError("Kill admission requires a durable journal")
                self._append_runtime_evidence(json.dumps({"ingestor_checkpoint": {
                    "kind": "kill_admission", "session_id": session_id}}, sort_keys=True))
                self._kill_handoff_required = True

    def finalize_acquisition_intake(self, marker: RuntimeEvidenceMessage, receipt: dict) -> dict:
        """Freeze exact acquisition intake after owner-side complete receipt verification."""
        with self._intake_lock:
            if self._finalized_intake is not None:
                if self._finalized_intake["marker"] != marker.to_dict():
                    raise RuntimeError("A different completion marker cannot replace finalized intake")
                return self.finalized_acquisition_intake(marker.session_id)
            if (self._kill_handoff_required or marker.session_id != self._session_id
                    or marker.evidence_type != "acquisition_evidence_completion"
                    or receipt.get("session_id") != self._session_id
                    or receipt.get("evidence_id") != marker.evidence_id
                    or receipt.get("durable_receipt_confirmed") is not True
                    or type(receipt.get("marker_stream_sequence")) is not int
                    or receipt["marker_stream_sequence"] <= 0):
                raise RuntimeError("Finalization requires matching complete durable acquisition receipt")
            with self.durable_runtime_evidence_history_guard(self._session_id,
                    self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
                if not confirmed or not self.has_durable_runtime_evidence(marker):
                    raise RuntimeError("Finalization journal coverage is unconfirmed")
                checkpoint = {"kind": "acquisition_finality", "session_id": self._session_id,
                    "marker": marker.to_dict(), "receipt": deepcopy(receipt),
                    "evidence_ids": list(self._accepted_evidence_content),
                    "ingest_audit": [audit.to_dict() for audit in self._runtime_evidence_audit]}
                self._append_runtime_evidence(json.dumps({"ingestor_checkpoint": checkpoint},
                    sort_keys=True, allow_nan=False))
                self._finalized_intake = checkpoint
                return deepcopy(checkpoint)

    def finalized_acquisition_intake(self, session_id: str) -> dict | None:
        """Read exact journal-confirmed finality, never an in-memory flag alone."""
        with self._intake_lock:
            if session_id != self._session_id or self._finalized_intake is None:
                return None
            with self.durable_runtime_evidence_history_guard(session_id,
                    self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
                if not confirmed:
                    raise RuntimeError("Finalized acquisition journal is unconfirmed")
                return deepcopy(self._finalized_intake)

    def preserve_session_closeout(self, session_id: str, *, mode: str, session_record: dict,
                                  controller_evidence: list[dict], uncertainties: list[dict]) -> dict:
        """Preserve owner-verified complete or explicitly partial intake with the paired storage owner."""
        storage = self._storage_manager
        if storage is None:
            raise RuntimeError("Closeout requires the configured shared-process StorageManager")
        with self._intake_lock, self.durable_runtime_evidence_history_guard(
                session_id, self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
            if not confirmed:
                raise RuntimeError("Closeout journal coverage is unconfirmed")
            if mode not in {"normal", "kill"}:
                raise ValueError("Unknown Session closeout mode")
            if mode == "normal" and self._finalized_intake is None:
                raise RuntimeError("Normal closeout requires finalized acquisition intake")
            if mode == "kill" and (not self._kill_handoff_required or self._finalized_intake is not None):
                raise RuntimeError("Partial Kill requires its admitted preservation obligation")
            if session_record.get("accepted_session_config", {}).get("session_id") != session_id:
                raise ValueError("Closeout Session Record identity mismatch")
            compiled = self.compile_persistent_runtime_evidence()
            actual = {m.evidence_id: m.to_dict() for m in self._accepted_runtime_evidence}
            if mode == "normal" and any(actual.get(m.get("evidence_id")) != m for m in controller_evidence):
                raise RuntimeError("Required Controller evidence is not durably accepted")
            with storage.session_preservation_guard(session_id):
                current = storage.get_persisted_session_preservation_confirmation(session_id)
                if current is None:
                    record = deepcopy(session_record)
                    record.update(runtime_evidence=[m.to_dict() for m in compiled["runtime_evidence"]],
                                  runtime_evidence_audit=[a.to_dict() for a in compiled["ingest_audit"]])
                    if mode == "normal":
                        storage.write_acquisition_stage(session_id, compiled,
                            receipt=self._finalized_intake["receipt"], **record)
                    else:
                        uncertainties = deepcopy(uncertainties) + [{"evidence_id": m.get("evidence_id"),
                            "acceptance_confirmed": False, "reason": "Controller publication is unconfirmed"}
                            for m in controller_evidence if actual.get(m.get("evidence_id")) != m]
                        storage.write_kill_acquisition_stage(session_id, compiled,
                            uncertainties=uncertainties, **record)
                    storage.write_artifact_collection_handoff(session_id,
                        self.compile_artifact_collection_handoff(session_id))
                return self.read_session_closeout(session_id)

    def read_session_closeout(self, session_id: str) -> dict:
        """Reconcile exact current journal, finalized audit, archive and handoff coverage."""
        storage = self._storage_manager
        if storage is None:
            raise RuntimeError("Closeout readback requires the paired StorageManager")
        if self._session_id is None:
            return self._read_saved_closeout(session_id)
        with self._intake_lock, self.durable_runtime_evidence_history_guard(
                session_id, self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
            if not confirmed:
                raise RuntimeError("Current closeout journal coverage is unconfirmed")
            with storage.session_preservation_guard(session_id):
                current = storage.get_persisted_session_preservation_confirmation(session_id)
                compiled = self.compile_persistent_runtime_evidence()
                origins = set((current or {}).get("compilation_summary", {}).get("runtime_evidence_origins", {}).get("ingestor", []))
                if (current is None or [m for m in current["runtime_evidence"] if m["evidence_id"] in origins]
                        != [v.to_dict() for v in compiled["runtime_evidence"]]
                        or current["ingest_audit"] != [v.to_dict() for v in compiled["ingest_audit"]]
                        or current["artifact_collection_handoff"] != self.compile_artifact_collection_handoff(session_id)):
                    raise RuntimeError("Current closeout preservation does not cover intake")
                normal = self._finalized_intake is not None
                summary = current["compilation_summary"]
                if normal:
                    if (summary.get("stage_a_complete") is not True
                            or summary.get("acquisition_evidence_completion", {}).get("evidence_id")
                                != self._finalized_intake["marker"]["evidence_id"]
                            or summary["acquisition_evidence_completion"].get("marker_stream_sequence")
                                != self._finalized_intake["receipt"]["marker_stream_sequence"]):
                        raise RuntimeError("Finalized marker provenance is not preserved")
                elif not summary.get("kill_preservation", {}).get("preservation_confirmed"):
                    raise RuntimeError("Partial Kill preservation is unconfirmed")
                return deepcopy({"session_id": session_id, "storage_id": storage._component_id,
                    "preservation_confirmed": True, "acquisition_preservation_eligible": normal,
                    "finalized_intake": self._finalized_intake,
                    "runtime_evidence": current["runtime_evidence"],
                    "compilation_summary": summary, "session_record": current["session_record"],
                    "artifact_collection_handoff": current["artifact_collection_handoff"]})

    def _read_saved_closeout(self, session_id: str) -> dict:
        """Verify a known saved scope without restoring an active Session or adding recovery intake."""
        if self._recovery_journal_root is None or not isinstance(session_id, str) or not session_id:
            raise RuntimeError("Known-Session journal configuration is required for restart readback")
        if any(c in session_id for c in '/\\\x00:') or session_id in {".", ".."}:
            raise ValueError("Invalid Session journal identity")
        with self._intake_lock, self._storage_manager.session_preservation_guard(session_id):
            current = self._storage_manager.get_persisted_session_preservation_confirmation(session_id)
            if current is None:
                raise RuntimeError("Saved preservation is unconfirmed")
            messages, finality, kill = {}, None, False
            with (self._recovery_journal_root / f"session_{session_id}.jsonl").open("rb") as journal:
                before = os.fstat(journal.fileno())
                for line in journal:
                    data = json.loads(line)
                    if "ingestor_checkpoint" in data:
                        checkpoint = data["ingestor_checkpoint"]
                        if checkpoint.get("session_id") != session_id:
                            raise ValueError("Saved checkpoint Session mismatch")
                        if checkpoint.get("kind") == "kill_admission" and finality is None:
                            kill = True
                        elif checkpoint.get("kind") == "acquisition_finality" and finality is None and not kill:
                            finality = checkpoint
                        else:
                            raise ValueError("Saved closeout checkpoint is conflicting")
                    else:
                        evidence = RuntimeEvidenceMessage.from_dict(data)
                        if finality is not None or evidence.session_id != session_id:
                            raise ValueError("Saved acquisition interval changed")
                        old = messages.setdefault(evidence.evidence_id, evidence.to_dict())
                        if old != evidence.to_dict():
                            raise ValueError("Saved evidence identity conflict")
                after = os.fstat(journal.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError("Saved journal changed during readback")
            origins = set(current["compilation_summary"].get("runtime_evidence_origins", {}).get("ingestor", []))
            if [m for m in current["runtime_evidence"] if m["evidence_id"] in origins] != [m for m in messages.values() if m["is_persistent"]]:
                raise RuntimeError("Saved journal evidence is not completely preserved")
            summary = current["compilation_summary"]
            if finality is not None:
                if (finality.get("evidence_ids") != list(messages)
                        or finality.get("ingest_audit") != current["ingest_audit"]
                        or finality.get("marker") != messages.get(finality.get("receipt", {}).get("evidence_id"))
                        or finality.get("marker", {}).get("session_id") != session_id
                        or finality.get("marker", {}).get("evidence_type") != "acquisition_evidence_completion"
                        or finality.get("receipt", {}).get("session_id") != session_id
                        or finality.get("receipt", {}).get("durable_receipt_confirmed") is not True
                        or type(finality.get("receipt", {}).get("marker_stream_sequence")) is not int
                        or finality["receipt"]["marker_stream_sequence"] <= 0
                        or summary.get("stage_a_complete") is not True
                        or summary.get("acquisition_evidence_completion", {}).get("evidence_id")
                            != finality["receipt"]["evidence_id"]
                        or summary.get("acquisition_evidence_completion", {}).get("marker_stream_sequence")
                            != finality.get("receipt", {}).get("marker_stream_sequence")):
                    raise RuntimeError("Saved finalized intake coverage is unconfirmed")
            elif not kill or not summary.get("kill_preservation", {}).get("preservation_confirmed"):
                raise RuntimeError("Saved partial Kill obligation is unconfirmed")
            return deepcopy({"session_id": session_id, "storage_id": self._storage_manager._component_id,
                "preservation_confirmed": True, "acquisition_preservation_eligible": finality is not None,
                "finalized_intake": finality, "compilation_summary": summary,
                "runtime_evidence": current["runtime_evidence"], "session_record": current["session_record"],
                "artifact_collection_handoff": current["artifact_collection_handoff"]})

    def preserve_terminal_session_record(self, session_id: str, session_record: dict) -> dict:
        """Persist Controller-owned terminal lifecycle without changing acquisition evidence."""
        with self._intake_lock:
            before = self.read_session_closeout(session_id)
            old = before["session_record"]
            lifecycle = session_record.get("lifecycle_evidence", [])
            status = session_record.get("final_session_status") or {}
            if (session_record.get("accepted_session_config") != old["accepted_session_config"]
                    or status.get("state") not in {"completed", "failed", "aborted"}
                    or not lifecycle or lifecycle[-1].get("to_state") != status["state"]
                    or lifecycle[:len(old["session_lifecycle_evidence"])] != old["session_lifecycle_evidence"]):
                raise RuntimeError("Terminal Session Record conflicts with preserved lifecycle")
            if (old.get("final_session_status") or {}).get("state") in {"completed", "failed", "aborted"}:
                if (old["final_session_status"] != status or old["session_lifecycle_evidence"] != lifecycle):
                    raise RuntimeError("Terminal Session history cannot be replaced")
                return before
            if not before["acquisition_preservation_eligible"]:
                raise RuntimeError("Partial Kill terminal history is immutable")
            record = deepcopy(session_record)
            if self._session_id is None:
                archived = self._storage_manager.get_persisted_session_preservation_confirmation(session_id)
                origins = set(archived["compilation_summary"]["runtime_evidence_origins"]["ingestor"])
                record.update(runtime_evidence=[m for m in archived["runtime_evidence"] if m["evidence_id"] in origins],
                              runtime_evidence_audit=archived["ingest_audit"])
            else:
                compiled = self.compile_persistent_runtime_evidence()
                record.update(runtime_evidence=[m.to_dict() for m in compiled["runtime_evidence"]],
                              runtime_evidence_audit=[a.to_dict() for a in compiled["ingest_audit"]])
            self._storage_manager.write_final_session_record(session_id, **record)
            return self.read_session_closeout(session_id)

    @service_operation()
    def release_session(
        self, session_id: str, *, storage_manager: PersistentStorageManager | None = None,
    ) -> bool:
        """Release confirmed terminal evidence, or an empty binding, without deleting its journal."""
        with self._intake_lock, ExitStack() as preservation:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Session release requires session_id")
            if self._session_id != session_id:
                raise RuntimeError("Session release does not match Ingestor Session")
            if self._journal_failed:
                raise RuntimeError("Recovery journal integrity is unresolved")
            storage = storage_manager if storage_manager is not None else self._storage_manager
            confirmation = (preservation.enter_context(storage.session_preservation_guard(session_id))
                            if isinstance(storage, PersistentStorageManager) else None)
            partial_kill = (self._kill_handoff_required or (confirmation is not None
                            and confirmation["compilation_summary"].get("kill_preservation") is not None))
            if self._accepted_runtime_evidence or self._runtime_evidence_audit or partial_kill:
                if not isinstance(storage, PersistentStorageManager):
                    raise RuntimeError("Evidence preservation confirmation is required before release")
                # Lock order is intake -> storage; retain both through state retirement.
                if confirmation is None:
                    raise RuntimeError("Evidence preservation confirmation is unavailable")
                if self._kill_handoff_required and confirmation["compilation_summary"].get("kill_preservation") is None:
                    raise RuntimeError("Kill preservation confirmation is unavailable")
                record = confirmation["session_record"]
                state = (record.get("final_session_status") or {}).get("state")
                lifecycle = record.get("session_lifecycle_evidence", [])
                if (record.get("accepted_session_config", {}).get("session_id") != session_id
                        or state not in {"completed", "failed", "aborted"}
                        or not lifecycle or lifecycle[-1].get("to_state") != state):
                    raise RuntimeError("Terminal Session completion evidence is unconfirmed")
                compiled = self.compile_persistent_runtime_evidence()
                if any(confirmation[name] != [item.to_dict() for item in compiled[name]]
                       for name in ("runtime_evidence", "ingest_audit")):
                    raise RuntimeError("Archive confirmation does not cover current runtime intake")
                if partial_kill or any(message.evidence_type == "acquisition_evidence_completion"
                                       for message in self._accepted_runtime_evidence):
                    if json.dumps(storage.read_artifact_collection_handoff(session_id), sort_keys=True) != json.dumps(
                            self.compile_artifact_collection_handoff(session_id), sort_keys=True):
                        raise RuntimeError("Durable artifact handoff does not cover current Session manifests")
            self._session_prepared = False
            self._session_id = None
            self._kill_handoff_required = False
            self._finalized_intake = None
            self._recovery_journal_path = None
            self._accepted_evidence_content.clear()
            self._accepted_runtime_evidence = ()
            self._runtime_evidence_audit = ()
            return True

    def has_durable_runtime_evidence(self, evidence: RuntimeEvidenceMessage) -> bool:
        """Confirm exact journal-backed acceptance, not publication or final archival."""
        with self._intake_lock:
            if evidence.session_id is None and self._evidence_scope == "session":
                return (self._framework_ingestor is not None
                        and self._framework_ingestor.has_durable_runtime_evidence(evidence))
            if (self._journal_failed or self._recovery_journal_path is None
                    or evidence.session_id != self._session_id):
                return False
            return self._accepted_evidence_content.get(evidence.evidence_id) == self._evidence_content(evidence)

    @contextmanager
    def durable_runtime_evidence_history_guard(
        self, session_id: str, journal_path: str | Path,
        evidence: Iterable[RuntimeEvidenceMessage],
    ) -> Iterator[bool]:
        """Check retained Session journal coverage while preventing intake/binding changes."""
        with self._intake_lock:
            confirmed = False
            try:
                if (self._evidence_scope == "session" and self._session_id == session_id
                        and self._recovery_journal_path == Path(journal_path)
                        and not self._journal_failed and self._session_prepared):
                    required = {}
                    for item in evidence:
                        content = self._evidence_content(item)
                        if item.evidence_id in required and required[item.evidence_id] != content:
                            raise ValueError("Required evidence has conflicting content")
                        required[item.evidence_id] = content
                    remaining = dict(self._accepted_evidence_content)
                    if all(self._accepted_evidence_content.get(identity) == content
                           for identity, content in required.items()):
                        with self._recovery_journal_path.open("rb") as journal:
                            before = os.fstat(journal.fileno())
                            finality_seen = None
                            kill_seen = False
                            for line in journal:
                                data = json.loads(line)
                                if "ingestor_checkpoint" in data:
                                    checkpoint = data["ingestor_checkpoint"]
                                    if checkpoint.get("session_id") != session_id:
                                        raise ValueError("Journal checkpoint Session mismatch")
                                    if checkpoint.get("kind") == "kill_admission" and finality_seen is None:
                                        kill_seen = True
                                    elif checkpoint.get("kind") == "acquisition_finality" and finality_seen is None and not kill_seen:
                                        finality_seen = checkpoint
                                    else:
                                        raise ValueError("Conflicting journal checkpoint")
                                    continue
                                if finality_seen is not None:
                                    raise ValueError("Acquisition evidence follows finalized intake")
                                item = RuntimeEvidenceMessage.from_dict(data)
                                content = self._evidence_content(item)
                                if self._accepted_evidence_content.get(item.evidence_id) != content:
                                    raise ValueError("Journal history differs from accepted evidence")
                                remaining.pop(item.evidence_id, None)
                            after = os.fstat(journal.fileno())
                            current = self._recovery_journal_path.stat()
                            attributes = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
                            confirmed = (not remaining and finality_seen == self._finalized_intake
                                and (not kill_seen or self._kill_handoff_required) and all(
                                getattr(before, name) == getattr(after, name) == getattr(current, name)
                                for name in attributes))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                confirmed = False
            # The caller commits only a readback result here, never an async operation.
            yield confirmed

    @property
    def recovery_journal_path(self) -> Path | None:
        """Explicit caller-supplied recovery journal location, not a permanent archive."""

        return self._recovery_journal_path

    def _sync_journal_directory(self) -> None:
        if os.name == "posix":
            descriptor = os.open(self._recovery_journal_path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _evidence_content(self, evidence: RuntimeEvidenceMessage) -> str:
        identities = (
            evidence.evidence_id, evidence.evidence_type, evidence.source_id
        )
        if not all(isinstance(value, str) and value for value in identities):
            raise ValueError("Runtime evidence requires nonempty string identities")
        if self._session_id is not None and evidence.session_id != self._session_id:
            raise ValueError("Runtime evidence Session does not match recovery journal")
        if self._evidence_scope == "framework" and evidence.session_id is not None:
            raise ValueError("Framework evidence must have session_id=None")
        if self._evidence_scope == "session" and not isinstance(evidence.session_id, str):
            raise ValueError("Session evidence requires session_id")
        return json.dumps(evidence.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _append_runtime_evidence(self, content: str) -> None:
        if self._journal_failed:
            raise RuntimeError("Recovery journal append previously failed; restart Ingestor before further intake")
        if self._recovery_journal_path is None:
            return
        data = (content + "\n").encode("utf-8")
        try:
            with self._recovery_journal_path.open("ab") as journal:
                if journal.write(data) != len(data):
                    raise OSError("Incomplete recovery journal append")
                journal.flush()
                os.fsync(journal.fileno())
        except Exception:
            # A failed write may leave an uncertain tail; only startup reconstruction
            # may establish its integrity before further acceptance.
            self._journal_failed = True
            raise

    def _restore_runtime_evidence(self) -> None:
        restored: dict[str, tuple[str, RuntimeEvidenceMessage]] = {}
        framework_audit = []
        finality = None
        kill_required = False
        with self._recovery_journal_path.open("r+b") as journal:
            while True:
                offset = journal.tell()
                line = journal.readline()
                if not line:
                    break
                terminated = line.endswith(b"\n")
                try:
                    text = line.decode("utf-8")
                    data = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    truncated = False
                    if isinstance(error, UnicodeDecodeError) and error.reason == "unexpected end of data":
                        prefix = line[:error.start].decode("utf-8")
                        try:
                            json.loads(prefix)
                        except json.JSONDecodeError as prefix_error:
                            truncated = self._is_interrupted_json(prefix, prefix_error)
                    if isinstance(error, json.JSONDecodeError):
                        truncated = self._is_interrupted_json(text, error)
                    if terminated or not truncated:
                        raise ValueError("Recovery journal contains corrupt completed evidence") from error
                    # Remove only an interrupted, unaccepted final append so new
                    # evidence cannot be concatenated onto its incomplete bytes.
                    journal.truncate(offset)
                    journal.flush()
                    os.fsync(journal.fileno())
                    break
                if self._evidence_scope == "session" and "ingestor_checkpoint" in data:
                    checkpoint = data["ingestor_checkpoint"]
                    if not isinstance(checkpoint, dict) or checkpoint.get("session_id") != self._session_id:
                        raise ValueError("Invalid Session journal checkpoint")
                    if checkpoint.get("kind") == "kill_admission" and finality is None:
                        kill_required = True
                    elif checkpoint.get("kind") == "acquisition_finality" and finality is None and not kill_required:
                        marker = RuntimeEvidenceMessage.from_dict(checkpoint["marker"])
                        receipt = checkpoint["receipt"]
                        audits = [RuntimeEvidenceAuditRecord(**item) for item in checkpoint["ingest_audit"]]
                        if (checkpoint["evidence_ids"] != list(restored)
                                or marker.evidence_id not in restored
                                or restored[marker.evidence_id][0] != self._evidence_content(marker)
                                or marker.evidence_type != "acquisition_evidence_completion"
                                or receipt.get("session_id") != self._session_id
                                or receipt.get("evidence_id") != marker.evidence_id
                                or receipt.get("durable_receipt_confirmed") is not True
                                or type(receipt.get("marker_stream_sequence")) is not int
                                or receipt["marker_stream_sequence"] <= 0
                                or any(a.ingest_order != i or type(a.accepted) is not bool
                                    or type(a.ingest_received_at) not in {int, float}
                                    or not isinstance(a.reason, str)
                                    or (a.accepted and a.evidence_id not in restored)
                                    for i, a in enumerate(audits, 1))
                                or {a.evidence_id for a in audits if a.accepted} != set(restored)):
                            raise ValueError("Finalized journal coverage or audit is inconsistent")
                        finality = checkpoint
                    else:
                        raise ValueError("Conflicting Session journal checkpoint")
                    if not terminated:
                        journal.write(b"\n")
                        journal.flush()
                        os.fsync(journal.fileno())
                    continue
                if finality is not None:
                    raise ValueError("Journal evidence follows finalized acquisition intake")
                if self._evidence_scope == "framework":
                    audit = RuntimeEvidenceAuditRecord(**data["ingest_audit"])
                    if audit.ingest_order != len(framework_audit) + 1:
                        raise ValueError("Framework journal intake order is inconsistent")
                    framework_audit.append(audit)
                    data = data["runtime_evidence"]
                    if data is None:
                        if audit.accepted:
                            raise ValueError("Accepted framework audit lacks evidence")
                        if not terminated:
                            journal.write(b"\n")
                            journal.flush()
                            os.fsync(journal.fileno())
                        continue
                evidence = RuntimeEvidenceMessage.from_dict(data)
                content = self._evidence_content(evidence)
                if self._evidence_scope == "framework" and (
                        not audit.accepted or audit.evidence_id != evidence.evidence_id):
                    raise ValueError("Framework journal evidence and intake audit disagree")
                previous = restored.get(evidence.evidence_id)
                if previous is not None and previous[0] != content:
                    raise ValueError("Recovery journal contains conflicting evidence_id content")
                restored.setdefault(evidence.evidence_id, (content, evidence))
                if not terminated:
                    journal.write(b"\n")
                    journal.flush()
                    os.fsync(journal.fileno())
            # Do not expose any staged state unless the entire journal is valid.
            journal.flush()
            os.fsync(journal.fileno())
        self._accepted_runtime_evidence = tuple(item[1] for item in restored.values())
        self._accepted_evidence_content = {key: value[0] for key, value in restored.items()}
        self._finalized_intake = finality
        self._kill_handoff_required = kill_required
        self._runtime_evidence_audit = tuple(RuntimeEvidenceAuditRecord(**item) for item in finality["ingest_audit"]) if finality is not None else tuple(framework_audit) if self._evidence_scope == "framework" else tuple(
            RuntimeEvidenceAuditRecord(index, time(), evidence.evidence_id, True, "recovered")
            for index, evidence in enumerate(self._accepted_runtime_evidence, 1)
        )

    @staticmethod
    def _is_interrupted_json(text: str, error: json.JSONDecodeError) -> bool:
        if error.pos >= len(text.rstrip()) or error.msg.startswith("Unterminated string"):
            return True
        tail = text[error.pos:]
        if error.msg == "Expecting value":
            return any(token.startswith(tail) for token in ("true", "false", "null")) or tail == "-"
        if error.msg == "Invalid \\uXXXX escape":
            return re.fullmatch(r"u[0-9a-fA-F]{0,4}", tail) is not None
        if error.msg == "Expecting ',' delimiter":
            # The decoder consumed a numeric prefix only if it immediately
            # follows a value delimiter; suffixes after completed values are corrupt.
            number = re.search(
                r"(?:^|[\[,:]\s*)(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)$",
                text[:error.pos],
            )
            if number is None:
                return False
            return (tail == "." and "." not in number.group(1)) or re.fullmatch(
                r"[eE][+-]?", tail
            ) is not None
        return False


    @property
    def accepted_runtime_evidence(self) -> tuple[RuntimeEvidenceMessage, ...]:
        """Accepted durable runtime evidence in intake order."""

        return self._accepted_runtime_evidence

    @property
    def runtime_evidence_audit(self) -> tuple[RuntimeEvidenceAuditRecord, ...]:
        """Audit records for durable runtime evidence intake."""

        return self._runtime_evidence_audit

    def compile_persistent_runtime_evidence(
        self,
    ) -> dict[str, tuple[RuntimeEvidenceMessage | RuntimeEvidenceAuditRecord, ...]]:
        """Return accepted persistent runtime evidence and intake audit records."""

        with self._intake_lock:
            return {
                "runtime_evidence": tuple(
                    RuntimeEvidenceMessage.from_dict(deepcopy(evidence.to_dict()))
                    for evidence in self._accepted_runtime_evidence
                    if evidence.is_persistent
                ),
                "ingest_audit": self._runtime_evidence_audit,
            }

    def compile_artifact_collection_handoff(self, session_id: str) -> dict[str, Any]:
        """Select complete manifests for one Session without collecting artifact bytes."""
        selected: dict[str, ArtifactManifest] = {}
        for message in self._accepted_runtime_evidence:
            if message.session_id != session_id or message.evidence_type != ARTIFACT_MANIFEST_EVIDENCE_TYPE:
                continue
            manifest = ArtifactManifest.from_dict(message.payload)
            if manifest.session_id != session_id:
                raise ValueError("ArtifactManifest Session does not match runtime evidence")
            previous = selected.get(manifest.artifact_manifest_id)
            if previous is None or manifest.lifecycle_state == "finalized":
                selected[manifest.artifact_manifest_id] = manifest
        return {
            "session_id": session_id,
            "artifacts": [
                {"artifact_manifest": manifest.to_dict(),
                 "missing_finalization_evidence": manifest.lifecycle_state != "finalized"}
                for manifest in selected.values()
            ],
        }

    @service_operation()
    def receive_runtime_evidence(
        self,
        evidence: RuntimeEvidenceMessage,
    ) -> RuntimeEvidenceAuditRecord:
        """Journal new evidence before acceptance when configured; deduplicate intake."""

        with self._intake_lock:
            if evidence.session_id is None and self._evidence_scope == "session":
                if self._framework_ingestor is None:
                    raise RuntimeError("Framework recovery journal is not configured")
                return self._framework_ingestor.receive_runtime_evidence(evidence)
            if self._finalized_intake is not None:
                return RuntimeEvidenceAuditRecord(0, time(), evidence.evidence_id, False, "acquisition_intake_finalized")
            if self._evidence_scope == "session" and self._requires_prepared_session and not self._session_prepared:
                raise RuntimeError("Session evidence intake is not prepared or has been aborted/released")

            accepted = bool(
                evidence.evidence_id and (evidence.session_id or self._evidence_scope == "framework")
                and evidence.evidence_type and evidence.source_id
            )
            duplicate = False
            if accepted:
                content = self._evidence_content(evidence)
                previous = self._accepted_evidence_content.get(evidence.evidence_id)
                if previous is not None and previous != content:
                    raise ValueError("Conflicting runtime evidence content for evidence_id")
                duplicate = previous is not None
                if not duplicate and self._evidence_scope == "session":
                    self._append_runtime_evidence(content)
                    evidence = RuntimeEvidenceMessage.from_dict(json.loads(content))
            audit = RuntimeEvidenceAuditRecord(
                ingest_order=len(self._runtime_evidence_audit) + 1,
                ingest_received_at=time(),
                evidence_id=evidence.evidence_id,
                accepted=accepted,
                reason=("already_accepted" if duplicate else "accepted") if accepted else "missing_required_identity",
            )
            if self._evidence_scope == "framework":
                self._append_runtime_evidence(json.dumps({
                    "runtime_evidence": evidence.to_dict() if accepted else None,
                    "ingest_audit": audit.to_dict(),
                }, sort_keys=True, separators=(",", ":"), allow_nan=False))
                if accepted:
                    evidence = RuntimeEvidenceMessage.from_dict(json.loads(content))
            self._runtime_evidence_audit += (audit,)
            if accepted and not duplicate:
                self._accepted_runtime_evidence += (evidence,)
                self._accepted_evidence_content[evidence.evidence_id] = content
            if accepted and self._recovery_journal_path is not None and not self._journal_failed:
                for expected, future in self._durable_evidence_waiters.get(evidence.evidence_id, ()):
                    if expected == content:
                        future.get_loop().call_soon_threadsafe(self._confirm_acceptance_future, future)
            return audit

    def maintenance_blockers(self, ingestor, storage_manager) -> list[str]:
        """Report unpreserved Session intake; operational dependencies are explicitly configured."""
        with self._intake_lock:
            if self._journal_failed:
                return ["Recovery journal integrity is unresolved"]
            if self._framework_ingestor is not None and self._framework_ingestor._journal_failed:
                return ["Framework recovery journal integrity is unresolved"]
            if not (self._accepted_runtime_evidence or self._runtime_evidence_audit):
                return []
            with storage_manager.session_preservation_guard(self._session_id) as confirmation:
                if confirmation is None:
                    return ["Session evidence archival is unconfirmed"]
                compiled = self.compile_persistent_runtime_evidence()
                if (any(confirmation[name] != [item.to_dict() for item in compiled[name]]
                        for name in ("runtime_evidence", "ingest_audit"))):
                    return ["Session intake is not completely preserved"]
            return []

    def maintenance_diagnostics(self, ingestor, storage_manager) -> dict:
        """Report retained intake/journal obligations without reconstructing or clearing them."""
        with self._intake_lock:
            interface = getattr(self, "_maintenance", None)
            blockers = self.maintenance_blockers(ingestor, storage_manager)
            return {
                "session_intake": {"session_id": self._session_id, "evidence_scope": self._evidence_scope,
                    "accepted_evidence_count": len(self._accepted_runtime_evidence),
                    "runtime_audit_count": len(self._runtime_evidence_audit),
                    "administrative_outcome": (interface._administrative_outcome({"session_id": self._session_id})
                                                if interface and self._session_id else None)},
                "journal_integrity_unconfirmed": self._journal_failed,
                "framework_journal_integrity_unconfirmed": bool(self._framework_ingestor
                                                               and self._framework_ingestor._journal_failed),
                "framework_journal_recovery": {
                    "journal_path": (str(self._framework_ingestor._recovery_journal_path)
                                     if self._framework_ingestor else None),
                    "assessment": "potentially_recoverable" if self._framework_ingestor
                        and self._framework_ingestor._journal_failed else None,
                    "recovered": False if self._framework_ingestor and self._framework_ingestor._journal_failed else None},
                "known_session_recovery": {"session_id": self._session_id,
                    "journal_path": str(self._recovery_journal_path) if self._recovery_journal_path else None,
                    "assessment": ("potentially_recoverable" if self._recovery_journal_path is not None
                                   else "administrator_intervention") if self._journal_failed else None,
                    "recovered": False if self._journal_failed else None},
                "restricted_intake": (("service readiness and Session intake" if self._journal_failed
                    or self._framework_ingestor and self._framework_ingestor._journal_failed else "Session binding release")
                    if blockers else None),
                "blocking_conditions": blockers,
            }

    async def _close_maintenance_resources(self, force: bool) -> None:
        # Journal handles are opened and closed inside individual intake operations.
        pass

    def check_ready(self) -> ServiceReadiness:
        """Report readiness, rejecting new intake after uncertain journal writes."""

        journal_failed = self._journal_failed or (
            self._framework_ingestor is not None and self._framework_ingestor._journal_failed)
        terminated = getattr(getattr(self, "_maintenance", None), "terminated", False)
        return apply_dependency_readiness(self, ServiceReadiness(
            component_id=self._component_id,
            component_type="ingestor",
            required=True,
            ready=not journal_failed and not terminated,
            reason="service_terminated" if terminated else "recovery_journal_failed" if journal_failed else "ready",
        ))


    @service_operation()
    def compile_durable_session_evidence(self, session_id: str) -> dict[str, Any]:
        """Return current journal-verified operational compilation, not archival confirmation."""
        with self._intake_lock:
            if not isinstance(session_id, str) or not session_id or session_id != self._session_id:
                raise ValueError("Compilation requires the current Ingestor Session")
            if self._recovery_journal_path is None:
                raise RuntimeError("Compilation requires a durable recovery journal")
            with self.durable_runtime_evidence_history_guard(
                    session_id, self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
                if not confirmed:
                    raise RuntimeError("Current journal coverage is unconfirmed")
                compiled = self.compile_persistent_runtime_evidence()
                return deepcopy({"session_id": session_id, "journal_coverage_confirmed": True,
                    **{name: [item.to_dict() for item in values] for name, values in compiled.items()},
                    "artifact_collection_handoff": self.compile_artifact_collection_handoff(session_id)})
