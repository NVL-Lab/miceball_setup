"""Envelope intake and optionally journal-backed runtime evidence acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
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
from lab_sync_acquisition.service_readiness import ServiceReadiness
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
    ) -> None:
        if (session_id is None) != (recovery_journal_path is None):
            raise ValueError("Session identity and recovery journal path must be supplied together")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("Ingestor component_id must be a nonempty string")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError("Recovery requires a nonempty known Session identity")
        self._storage_manager = storage_manager
        self._intake_lock = RLock()
        self._recovery_journal_root = Path(recovery_journal_root) if recovery_journal_root is not None else None
        self._session_prepared = session_id is not None
        self._requires_prepared_session = session_id is not None or recovery_journal_root is not None
        self._session_id = session_id
        self._component_id = component_id
        self._recovery_journal_path = (
            Path(recovery_journal_path) if recovery_journal_path is not None else None
        )
        self._journal_failed = False
        self._accepted_evidence_content: dict[str, str] = {}
        self._accepted_envelopes: tuple[AcquisitionRecordEnvelope, ...] = ()
        self._ingest_audit: tuple[IngestAuditRecord, ...] = ()
        self._accepted_runtime_evidence: tuple[RuntimeEvidenceMessage, ...] = ()
        self._runtime_evidence_audit: tuple[RuntimeEvidenceAuditRecord, ...] = ()
        self._initialize_recovery_journal()

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

    def prepare_session(self, session_id: str) -> ServiceReadiness:
        """Prepare known-Session intake using deployment-local journal configuration."""
        with self._intake_lock:
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

    def abort_session_initialization(self, session_id: str) -> bool:
        """Stop prepared intake without deleting accepted evidence or journal history."""
        with self._intake_lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("Initialization abort requires session_id")
            if self._session_id not in {None, session_id}:
                raise RuntimeError("Initialization abort does not match Ingestor Session")
            self._session_prepared = False
            if not self._accepted_runtime_evidence:
                self._session_id = None
                self._recovery_journal_path = None
            return True

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
            if (self._accepted_runtime_evidence or self._runtime_evidence_audit
                    or self._accepted_envelopes or self._ingest_audit):
                storage = storage_manager if storage_manager is not None else self._storage_manager
                if not isinstance(storage, PersistentStorageManager):
                    raise RuntimeError("Evidence preservation confirmation is required before release")
                # Lock order is intake -> storage; retain both through state retirement.
                confirmation = preservation.enter_context(storage.session_preservation_guard(session_id))
                if confirmation is None:
                    raise RuntimeError("Evidence preservation confirmation is unavailable")
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
                # Acquisition envelopes and their audit stay on the existing Session Record path.
                if (record.get("accepted_acquisition_envelopes") != [
                        envelope.to_dict() for envelope in self._accepted_envelopes]
                        or record.get("ingest_audit_records") != [
                            audit.to_dict() for audit in self._ingest_audit]):
                    raise RuntimeError("Acquisition-envelope preservation is unconfirmed")
            self._session_prepared = False
            self._session_id = None
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
            if (self._journal_failed or self._recovery_journal_path is None
                    or evidence.session_id != self._session_id):
                return False
            return self._accepted_evidence_content.get(evidence.evidence_id) == self._evidence_content(evidence)

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
            evidence.evidence_id, evidence.session_id, evidence.evidence_type, evidence.source_id
        )
        if not all(isinstance(value, str) and value for value in identities):
            raise ValueError("Runtime evidence requires nonempty string identities")
        if self._session_id is not None and evidence.session_id != self._session_id:
            raise ValueError("Runtime evidence Session does not match recovery journal")
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
                evidence = RuntimeEvidenceMessage.from_dict(data)
                content = self._evidence_content(evidence)
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
        self._runtime_evidence_audit = tuple(
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

    def receive_runtime_evidence(
        self,
        evidence: RuntimeEvidenceMessage,
    ) -> RuntimeEvidenceAuditRecord:
        """Journal new evidence before acceptance when configured; deduplicate intake."""

        with self._intake_lock:
            if self._requires_prepared_session and not self._session_prepared:
                raise RuntimeError("Session evidence intake is not prepared or has been aborted/released")

            accepted = bool(
                evidence.evidence_id and evidence.session_id and evidence.evidence_type and evidence.source_id
            )
            duplicate = False
            if accepted:
                content = self._evidence_content(evidence)
                previous = self._accepted_evidence_content.get(evidence.evidence_id)
                if previous is not None and previous != content:
                    raise ValueError("Conflicting runtime evidence content for evidence_id")
                duplicate = previous is not None
                if not duplicate:
                    self._append_runtime_evidence(content)
                    evidence = RuntimeEvidenceMessage.from_dict(json.loads(content))
            audit = RuntimeEvidenceAuditRecord(
                ingest_order=len(self._runtime_evidence_audit) + 1,
                ingest_received_at=time(),
                evidence_id=evidence.evidence_id,
                accepted=accepted,
                reason=("already_accepted" if duplicate else "accepted") if accepted else "missing_required_identity",
            )
            self._runtime_evidence_audit += (audit,)
            if accepted and not duplicate:
                self._accepted_runtime_evidence += (evidence,)
                self._accepted_evidence_content[evidence.evidence_id] = content
            return audit

    def check_ready(self) -> ServiceReadiness:
        """Report readiness, rejecting new intake after uncertain journal writes."""

        return ServiceReadiness(
            component_id=self._component_id,
            component_type="ingestor",
            required=True,
            ready=not self._journal_failed,
            reason="recovery_journal_failed" if self._journal_failed else "ready",
        )

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
                if self._storage_manager is not None:
                    self._storage_manager.store_envelopes((envelope,))
            return audit

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
