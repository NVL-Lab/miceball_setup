"""Envelope intake and optionally journal-backed runtime evidence acceptance."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Iterator
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

from lab_sync_acquisition.acquisition_record import AcquisitionRecordEnvelope
from lab_sync_acquisition.communication import ARTIFACT_MANIFEST_EVIDENCE_TYPE, RuntimeEvidenceMessage
from lab_sync_acquisition.local_storage import ArtifactManifest
from lab_sync_acquisition.service_readiness import ServiceReadiness, apply_dependency_readiness
from lab_sync_acquisition.service_maintenance import service_operation
from lab_sync_acquisition.storage import (
    InMemoryStorageManager,
    PersistentStorageManager,
)


@dataclass(frozen=True)
class IngestAuditRecord:
    """Audit evidence for one received acquisition envelope."""

    ingest_order: int
    ingest_received_at: float
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "ingest_order": self.ingest_order,
            "ingest_received_at": self.ingest_received_at,
            "accepted": self.accepted,
            "reason": self.reason,
        }


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
    """Receives envelopes and evidence, with explicit known-Session recovery."""

    def __init__(
        self,
        storage_manager: InMemoryStorageManager
        | PersistentStorageManager
        | None = None,
        *,
        session_id: str | None = None,
        recovery_journal_path: str | Path | None = None,
        component_id: str = "ingestor",
        recovery_journal_root: str | Path | None = None,
        framework_recovery_journal_path: str | Path | None = None,
        evidence_scope: str = "session",
        correlated_persistence: bool = False,
    ) -> None:
        if not isinstance(correlated_persistence, bool):
            raise ValueError("correlated_persistence must be a boolean")
        if correlated_persistence and not isinstance(storage_manager, PersistentStorageManager):
            raise ValueError("Correlated local persistence requires a PersistentStorageManager owner")
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
        self._correlated_persistence = correlated_persistence
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
        self._component_id = component_id
        self._recovery_journal_path = (
            Path(recovery_journal_path) if recovery_journal_path is not None else None
        )
        self._journal_failed = False
        self._accepted_evidence_content: dict[str, str] = {}
        self._durable_evidence_waiters = {}
        self._accepted_envelopes: tuple[AcquisitionRecordEnvelope, ...] = ()
        self._ingest_audit: tuple[IngestAuditRecord, ...] = ()
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

    def _initialize_recovery_journal(self) -> None:
        if self._recovery_journal_path is not None:
            if self._recovery_journal_path.exists():
                self._restore_runtime_evidence()
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
            if (self._accepted_runtime_evidence or self._runtime_evidence_audit
                    or self._accepted_envelopes or self._ingest_audit or partial_kill):
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
                # Acquisition envelopes and their audit stay on the existing Session Record path.
                if (record.get("accepted_acquisition_envelopes") != [
                        envelope.to_dict() for envelope in self._accepted_envelopes]
                        or record.get("ingest_audit_records") != [
                            audit.to_dict() for audit in self._ingest_audit]):
                    raise RuntimeError("Acquisition-envelope preservation is unconfirmed")
            self._session_prepared = False
            self._session_id = None
            self._kill_handoff_required = False
            self._recovery_journal_path = None
            self._accepted_evidence_content.clear()
            self._accepted_runtime_evidence = ()
            self._runtime_evidence_audit = ()
            self._accepted_envelopes = ()
            self._ingest_audit = ()
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
                            for line in journal:
                                item = RuntimeEvidenceMessage.from_dict(json.loads(line))
                                content = self._evidence_content(item)
                                if self._accepted_evidence_content.get(item.evidence_id) != content:
                                    raise ValueError("Journal history differs from accepted evidence")
                                remaining.pop(item.evidence_id, None)
                            after = os.fstat(journal.fileno())
                            current = self._recovery_journal_path.stat()
                            attributes = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
                            confirmed = not remaining and all(
                                getattr(before, name) == getattr(after, name) == getattr(current, name)
                                for name in attributes)
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
        self._accepted_runtime_evidence = tuple(item[1] for item in restored.values())
        self._accepted_evidence_content = {key: value[0] for key, value in restored.items()}
        self._runtime_evidence_audit = tuple(framework_audit) if self._evidence_scope == "framework" else tuple(
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
    def accepted_envelopes(self) -> tuple[AcquisitionRecordEnvelope, ...]:
        """Accepted acquisition envelopes for inspection."""

        return self._accepted_envelopes

    @property
    def ingest_audit(self) -> tuple[IngestAuditRecord, ...]:
        """Audit records for received acquisition envelopes."""

        return self._ingest_audit

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
            if not (self._accepted_runtime_evidence or self._runtime_evidence_audit
                    or self._accepted_envelopes or self._ingest_audit):
                return []
            with storage_manager.session_preservation_guard(self._session_id) as confirmation:
                if confirmation is None:
                    return ["Session evidence archival is unconfirmed"]
                compiled = self.compile_persistent_runtime_evidence()
                record = confirmation["session_record"]
                if (any(confirmation[name] != [item.to_dict() for item in compiled[name]]
                        for name in ("runtime_evidence", "ingest_audit"))
                        or record.get("accepted_acquisition_envelopes") != [item.to_dict() for item in self._accepted_envelopes]
                        or record.get("ingest_audit_records") != [item.to_dict() for item in self._ingest_audit]):
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
    def receive_envelope(
        self,
        envelope: AcquisitionRecordEnvelope,
    ) -> IngestAuditRecord:
        """Receive one acquisition envelope and forward it if accepted."""

        with self._intake_lock:
            if self._requires_prepared_session and not self._session_prepared:
                raise RuntimeError("Session envelope intake is not prepared or has been aborted/released")

            accepted, reason = self._validate_envelope(envelope)
            audit = IngestAuditRecord(
                ingest_order=len(self._ingest_audit) + 1,
                ingest_received_at=time(), accepted=accepted, reason=reason,
            )
            self._ingest_audit += (audit,)
            if accepted:
                self._accepted_envelopes += (envelope,)
                if self._storage_manager is not None and not self._correlated_persistence:
                    self._storage_manager.store_envelopes((envelope,))
            return audit

    @service_operation()
    async def persist_accepted_envelope(
        self, envelope: AcquisitionRecordEnvelope, *,
        persist: Callable[[AcquisitionRecordEnvelope], Awaitable[dict[str, Any] | None]] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        """Send retained accepted intake to its storage owner without reaccepting or holding intake locks."""
        with self._intake_lock:
            if self._storage_manager is not None and not self._correlated_persistence:
                raise RuntimeError("Independent persistence must not also use a local StorageManager")
            if self._correlated_persistence:
                if persist is not None or not isinstance(command_id, str) or not command_id.strip():
                    raise ValueError("Local correlated persistence requires command_id and no transport callback")
            elif persist is None or command_id is not None:
                raise ValueError("Transport persistence requires a callback and callback-owned command identity")
            if (not isinstance(envelope, AcquisitionRecordEnvelope) or not self._session_prepared
                    or envelope.session_id != self._session_id or self._journal_failed):
                raise RuntimeError("Persistence requires the current prepared Ingestor Session")
            content = json.dumps(envelope.to_dict(), sort_keys=True)
            if not any(json.dumps(item.to_dict(), sort_keys=True) == content
                       for item in self._accepted_envelopes):
                raise ValueError("Envelope has not been accepted by this Ingestor")
            session_id, journal = self._session_id, self._recovery_journal_path
            snapshot = AcquisitionRecordEnvelope.from_dict(json.loads(content))
            if self._correlated_persistence:
                # Local writes cannot suspend: retain the binding lock through owner readback.
                return self._storage_manager.persist_envelope(
                    snapshot, command_id=command_id, requester_id=self._component_id)
        confirmation = await persist(snapshot)
        with self._intake_lock:
            if (self._session_id != session_id or self._recovery_journal_path != journal
                    or not self._session_prepared or self._journal_failed):
                raise RuntimeError("Ingestor binding changed during envelope persistence")
            if confirmation is None:
                return {"session_id": session_id, "durable_persistence_confirmed": False,
                        "reason": "StorageManager persistence response is missing or timed out"}
            if (confirmation.get("durable_persistence_confirmed") is True
                    and json.dumps(confirmation.get("envelope"), sort_keys=True) != content):
                raise ValueError("Persistence confirmation does not match accepted envelope contents")
            return deepcopy(confirmation)

    @service_operation()
    def compile_durable_session_evidence(self, session_id: str) -> dict[str, Any]:
        """Return current journal-verified compilation and acquisition intake, not archival confirmation."""
        with self._intake_lock:
            if not isinstance(session_id, str) or not session_id or session_id != self._session_id:
                raise ValueError("Compilation requires the current Ingestor Session")
            if self._recovery_journal_path is None:
                raise RuntimeError("Compilation requires a durable recovery journal")
            if any(envelope.session_id != session_id for envelope in self._accepted_envelopes):
                raise RuntimeError("Acquisition intake has conflicting Session association")
            with self.durable_runtime_evidence_history_guard(
                    session_id, self._recovery_journal_path, self._accepted_runtime_evidence) as confirmed:
                if not confirmed:
                    raise RuntimeError("Current journal coverage is unconfirmed")
                compiled = self.compile_persistent_runtime_evidence()
                return deepcopy({"session_id": session_id, "journal_coverage_confirmed": True,
                    **{name: [item.to_dict() for item in values] for name, values in compiled.items()},
                    "accepted_acquisition_envelopes": [item.to_dict() for item in self._accepted_envelopes],
                    "ingest_audit_records": [item.to_dict() for item in self._ingest_audit],
                    "artifact_collection_handoff": self.compile_artifact_collection_handoff(session_id)})

    def _validate_envelope(self, envelope: AcquisitionRecordEnvelope) -> tuple[bool, str]:
        if not envelope.session_id:
            return False, "missing_session_id"
        if not envelope.source_device_id:
            return False, "missing_source_device_id"
        if not envelope.record_kind:
            return False, "missing_record_kind"
        if envelope.records is None:
            return False, "missing_records"
        for row in envelope.records:
            if not self._row_has_session_time(row):
                return False, "missing_session_time"
        return True, "accepted"

    def _row_has_session_time(self, row: Any) -> bool:
        try:
            return "session_time_s" in row or "session_time" in row
        except TypeError:
            return False
