# Framework Milestones

This document records major technical milestones in the evolution of the Lab Sync Acquisition framework.

Unlike the Architecture Decisions, which capture *why* the system is designed a certain way, milestones capture *what has been successfully demonstrated*. A milestone represents a significant increase in confidence in the framework through implementation and validation.

---

# M001 — Framework Foundation

**Status:** Completed

## Goal

Establish the core acquisition architecture and ownership boundaries.

## Demonstrated

- Session lifecycle
- SessionConfig ownership
- Device lifecycle
- DeviceManager coordination
- SynchronizationManager ownership of Session Time
- AcquisitionNode execution
- AcquisitionRecordEnvelope boundary
- Ingestor boundary
- Persistent JSONL storage
- Persistent Session Record
- Public workflow tests

## Confidence gained

The core framework architecture supports bounded acquisition, ingestion, persistence, auditability, and clean ownership boundaries.

---

# M002 — Cross-Process Acquisition

**Status:** Completed

## Goal

Demonstrate that acquisition and ingestion can execute in independent processes without sharing live Python objects.

## Demonstrated

```text
Acquisition Process
        │
        ▼
AcquisitionRecordEnvelope (plain JSON)
        │
localhost socket
        │
        ▼
Ingestor Process
```

## Validated

- Cross-process communication
- Plain-data envelope boundary
- Independent producer and consumer processes
- Ingestor persistence through StorageManager
- No shared Python objects

## Confidence gained

The `AcquisitionRecordEnvelope` is a sufficient boundary between acquisition and ingestion. The framework does not require shared memory or shared runtime objects.

---

# M003 — First Real Hardware Integration

**Status:** Completed

## Goal

Replace the fake camera implementation with a real OpenCV camera without changing the framework architecture.

## Hardware

- Laptop integrated webcam
- OpenCV `cv2.VideoCapture`
- Windows Media Foundation (MSMF)

## Demonstrated

```text
Real webcam
        ↓
cv2.VideoCapture
        ↓
OpenCVCameraAdapter
        ↓
DeviceManager
        ↓
AcquisitionNode
        ↓
live localhost socket
        ↓
Ingestor
        ↓
PersistentStorageManager
```

## Validated

- Real SDK integration
- Device lifecycle
- Readiness
- Metadata acquisition
- Session Time assignment
- Cross-process transport
- Persistent storage
- Metadata-only acquisition records
- No image payload transmitted

## Confidence gained

A real hardware SDK can replace the fake implementation without requiring architectural changes.

The acquisition framework supports real devices while preserving the established ownership boundaries.

---

# M004 — Controller v1 Sequential Orchestration

**Status:** Completed

## Goal

Replace manual single-Session sequencing with a minimal synchronous Controller while preserving existing component ownership.

## Demonstrated

- Acquisition Runtime terminology through `start_runtime()` and `stop_runtime()`
- sequential create, initialize, start, iteration, stop, and finalization commands
- Controller command-result evidence
- pre-running, iteration, runtime-stop, and first-write finalization failure outcomes
- two-step Session Record persistence ending with durable completed evidence

## Confidence gained

One bounded Session can be orchestrated and finalized through public framework APIs without introducing GUI behavior, asynchronous execution, retry, or new ownership boundaries.

---

# M005 — Experiment Lifecycle and Scoped Acquisition Health

**Status:** Completed

## Goal

Add bounded scientific Experiment activity inside a running Session while preserving the distinction between persistent intent, runtime mapping, and runtime execution.

## Demonstrated

- Controller-owned canonical Experiment start/stop lifecycle
- at most one active Experiment per Session
- Session-owned Experiment descriptors and lifecycle evidence
- persistent ordered Expected Participant declarations
- runtime-only live-source Experiment health mappings that own Experiment-specific policy assignment
- Controller activation and clearing of AcquisitionNode mappings
- no participant binding or identifier inference
- AcquisitionNode health evaluation only for mapped live source IDs
- no participant-scoped health evaluation without an active mapping
- Session-ready but unmapped resources excluded from Experiment health scope

## Confidence gained

A completed Session can contain auditable Experiment activity and explicit expected participation while runtime health scope remains narrow, inspectable, and independent of resource ownership or persistence.

---

# M006 - Acquisition-Health Observations and Policy Definitions

**Status:** Completed

## Goal

Separate Experiment-scoped health detection evidence from configured operational meaning without introducing consequence execution.

## Demonstrated

- evidence-only `ExperimentScopedHealthObservation` records
- observation type kept distinct from consequence label
- Experiment-scoped policy assignment through `ExperimentRuntimeHealthMapping`
- removal of acquisition-health policy ownership from `DeviceDeclaration`
- immutable plain-data `AcquisitionHealthPolicy` definitions
- explicit evaluation parameters and observation interpretation mappings
- validation against supported observation names and accepted consequence-label vocabulary
- no warning, failure, Controller, notification, retry, recovery, or policy-execution behavior

## Confidence gained

The framework can describe what acquisition health observed and how an Experiment configures its interpretation while leaving operational consequence execution as explicit future work.

---

# M007 - Immediate Acquisition-Health Interpretation Evidence

**Status:** Completed

## Goal

Connect Session-scoped policy definitions and Experiment-scoped assignments to immediate, provenance-linked runtime interpretation evidence without executing framework consequences.

## Demonstrated

- persistent `SessionConfig` ownership of `AcquisitionHealthPolicy` definitions
- rule-specific `evaluation_rules` with no legacy raw policy dictionary path
- Experiment-scoped policy assignment through `ExperimentRuntimeHealthMapping`
- AcquisitionNode lookup and execution of the assigned policy interpretation
- runtime-unique `observation_id` on each emitted Health Observation
- immediate one-to-one `HealthInterpretationEvidence` linked by `originating_observation_id`
- configured interpretation labels and explicit `uninterpreted` outcomes
- observation and interpretation evidence through the existing envelope, ingest, and storage path
- no runtime stop, node failure, Controller action, lifecycle consequence, notification, retry, recovery, or orchestration

## Confidence gained

The framework now preserves an auditable runtime chain from configured policy and detected health condition to policy interpretation while keeping framework actions as explicit future Controller work.

---

# M008 - Slice 20 Scientific Camera Persistence and Jetson Validation

**Status:** Completed

## Goal

Complete Slice 20 by demonstrating real camera-frame collection, Experiment-scoped
local HDF5 persistence, finalization, reopening, and visual inspection on Jetson.

## Demonstrated

- Controller -> AcquisitionNode -> DeviceManager -> OpenCVCameraAdapter -> LocalStorageManager integration
- explicit scientific-product selection and prepared scientific streams
- real NVIDIA Jetson camera acquisition for 10 seconds
- 256 `uint8` frames, shape `(480, 640, 3)`, indices 0-255
- HDF5 persistence and reopening with finalized artifact and manifest
- `validation=PASS` from the existing manual camera smoke script
- recorded frames successfully displayed and visually inspected on Jetson

## Validation

W029 in `validated_workflows.md` records the hardware results and acquisition/
visualization commands, including `--show-frames` and `--view-hdf5`.
Four independent manual software validations passed. The automated suite passed
284 tests with optional Matplotlib dependencies; the Python 3.12 suite passed
277 tests with seven optional rendering tests skipped. Simulated automated
tests are distinct from the user-performed Jetson hardware validation.

## Confidence gained

The scientific camera vertical slice preserves frames through the accepted
framework ownership chain into finalized, readable local artifacts and supports
subsequent read-only visual inspection. Slice 20 is complete; subsequent
Slice 21 completion is recorded separately in M009.

---

# M009 - Slice 21 Pre-start Experiment Preparation Failure

**Status:** Completed

## Goal

Establish successful required preparation before canonical Experiment start,
preserving rejected attempts as persistent runtime evidence without introducing
new lifecycle states or changing component ownership.

## Demonstrated

- required scientific preparation failure rejects start without an active Experiment
- optional service failure permits start when all required preparation succeeds
- supplied missing required remote responses remain unresolved and block start
- rejected starts produce persistent experiment_start_rejected evidence, not experiment_start or experiment_fail
- one matching rejection is preserved in the existing Evidence Archive
- Session remains running after rejected preparation and can finalize successfully
- Session Record retains useful failure diagnostics
- distributed preparation retains caller-managed orchestration

## Validation

W030 records three successful independent manual IPython validations using
existing public framework workflows and test fixtures. The focused independent
audit passed 62 automated tests; the full suite was not rerun during that audit.
These validations do not constitute a live NATS broker end-to-end test.

The revised independent audit concluded CONDITIONAL PASS with documentation
synchronization as its only remaining closure requirement. Synchronization is
complete. Redundant raw rejection representation and a composed distributed
preparation test remain nonblocking improvement opportunities, not closure
requirements. Additional live NATS validation is not required.

## Confidence gained

Preparation failures and missing required outcomes cannot be mistaken for a
successfully started or failed active Experiment in the validated workflows.
Existing lifecycle and persistence boundaries preserve useful diagnostics.
Slice 21 is complete; no subsequent implementation slice is begun here.

---

# M010 - Phase 14 / Slice 22 Artifact Collection Handoff

**Status:** Completed

## Goal

Implement Decisions 240-244: publish complete LocalStorageManager-owned initial
and finalized manifests through AcquisitionNode's existing runtime evidence
pathway, and compile a Session-scoped artifact collection handoff in Ingestor.

## Implemented scope

- reuse existing runtime evidence intake and in-memory retention
- associate messages by artifact_manifest_id while preserving Session, Experiment, and AcquisitionNode identities
- select finalized manifests, otherwise initial manifests with missing finalization reported
- make one complete manifest entry per artifact available to Controller
- retain Controller initiation and handoff coordination, and StorageManager global retrieval ownership

## Validation

W031 records completed manual IPython validation of normal lifecycle, missing
finalization, Controller integration and persistent outputs, explicit NATS
publication with a broker double, and subscribed-command publication with a
broker double. All five scenarios passed. The implementation full suite reported
290 passed and seven optional rendering tests skipped; independent audit ran
72 focused tests, all passing. The audit verdict was PASS, Decisions 240-244
were satisfied, and no blocking defects were found. These are recorded results,
not tests executed during documentation closure.

## Boundaries and completion

Slice 22 is complete. No live NATS or hardware acquisition validation is claimed
for this slice, and no artifact-byte retrieval or global collection is implemented.
Artifact-byte transfer, remote filesystem
access, copying, checksums, diagnostics compilation, restart recovery, new
persistence infrastructure, and Session lifecycle changes are excluded.
Restart reconstruction roadmap placement and later Artifact Plane retrieval
remain future architecture work. Existing Evidence Archive behavior is unchanged.

---

# M011 - Phase 14 / Slice 23 StorageManager Artifact Retrieval

**Status:** Open - pending real Jetson/SSH-SFTP deployment validation

## Goal

Implement accepted Decisions 245-260 using the completed Slice 22 handoff:
Controller-initiated, StorageManager-owned SSH/SFTP pull retrieval with deployment-local
endpoint resolution, one file per manifest, deterministic global destinations,
independent attempts, temporary-file promotion, and per-artifact/aggregate outcomes.

## Implementation progress

SSH/SFTP pull retrieval, deployment-local endpoint configuration, and explicit
Controller collection are implemented with mock-backed automated tests. W032
records software retrieval/handoff regression coverage and independent manual
IPython validation of the Slice 24 collection/verification path. M011 remains
open pending deployment validation against the real Jetson/SSH-SFTP environment;
software validation does not establish real SSH/SFTP deployment behavior.

## Boundaries

Authoritative local files remain unchanged. Artifact bytes do not pass through
NATS or Ingestor. No retry/replay, resumable transfer, checksum verification,
cleanup/retention policy, restart recovery, or export is included. Aggregate failure
consequences for Session completion remain open. No real SSH/SFTP deployment
validation is claimed.

---

# M012 - Phase 14 / Slice 24 Light Verification of Globally Copied Artifacts

**Status:** Completed

## Goal

Implement Decisions 261-270: StorageManager-owned, bounded, non-destructive
structural verification after successful publication of a global artifact copy,
with separate retrieval and verification outcomes and aggregate reporting.

## Accepted scope

- first format/layout-specific contract for the current LocalStorageManager HDF5 layout, not camera-specific or universal HDF5 verification
- accessible nonzero-size HDF5, matching embedded identity, required datasets, aligned lengths, and existing persisted counts
- valid zero-record artifacts and no invented finalized count when finalization evidence is missing
- verified, copied_unverified, structurally_invalid, and verification_failed outcomes
- concise per-artifact information and aggregate visibility without Controller interpreting checks
- preservation of global copies regardless of verification outcome

## Validation status

Slice 24 implementation and automated validation are complete: 26 focused
verification tests and 21 Slice 23 retrieval/handoff regression tests passed.
Full unittest discovery ran 340 tests: 333 passed, 7 optional rendering tests
were skipped, and there were no failures. Six independent manual IPython
scenarios passed; W032 records their outcomes separately from automated results.

The initial independent audit failed on Decision 263's diagnostic-text classifier.
The implementation correction replaced the whitelist with failure-provenance
classification. The corrupt-header regression passed independently, and the
targeted independent re-audit returned PASS: Decision 263 satisfied, no remaining
blocking or nonblocking implementation findings, and no further code changes
required for closure. Final test/reproduction processes exited normally with
code 0. These are previously executed/reported results, not new validation during
documentation closure. Decisions 261-270 are implemented and M012 is complete.
M011 remains separately open for real Jetson/SSH-SFTP deployment validation.

## Boundaries

No new manifest/product schema fields, JSONL verifier, universal HDF5 layout,
full-file checksums, deep scientific-data scans, repair/deletion, reconstruction,
NWB transformation/validation, retry/replay, resume, separate verification service,
or verifier plugin framework. Session lifecycle consequences remain future
high-level architecture (Q017); broader ScientificProduct structural contracts
and extended verification remain open in Q020.

---

# M013 - Phase 14 / Slice 25 Post-session Global Artifact Collection Evidence

**Status:** Completed

## Goal

Implement Decisions 271-275: StorageManager-owned, persistent operational evidence
for one completed post-session collection pass through the existing durable
runtime-evidence path and same-Session Evidence Archive.

## Accepted scope

- one compiled collection-level record with actual attempted-artifact results, not one evidence message per artifact or a duplicate manifest
- existing independent collection and verification vocabularies, without aggregate evidence status or invented unattempted outcomes
- operational wall-clock pass timestamps, never extended scientific Session Time
- smallest existing publication-capability wiring; Controller orchestrates but does not translate StorageManager evidence
- distinction between Session acquisition end and processing finalization, with minimum ordering allowing post-session evidence before final archive closure

## Implementation status and dependency

StorageManager publishes one persistent record through an injected existing
async publication callable. Controller exposes an explicit stopping-Session
collection path before existing archive finalization. Focused Slice 25 tests:
18 passed; Slice 23 regression: 21 passed; Slice 24 regression: 26 passed;
communication/archive regression: 47 passed. Full discovery: 351 passed and
7 optional rendering tests skipped (358 total). W033 records independent manual
Scenarios 1-5 and 6B PASS, Scenario 6's inconclusive injection, initial audit FAIL,
the P1/P2 corrections, and final independent re-audit PASS with Decisions 271-275
satisfied and both blockers fixed. Controller rejects finalization during active
collection/publication and clears its guard after success, failure, or cancellation.
Unavailable temporary-file position yields null copied size without changing
outcomes or stopping later attempts. These are previously executed/reported results;
no validation was run during documentation closure. The broader guarantee that all
durable evidence has been consumed/accepted before final archive closure remains
OPEN in Q019; no consumer-drain protocol is implemented.

## Boundaries

No StorageManager-specific consumer-ACK waiting, polling, sleeps, arbitrary delays,
count assumptions, new broker protocol/transport/archive, scientific timing or
Experiment lifecycle change, checksum, export, retry/resume, or background transfer.
Collection outcome must not retroactively change acquisition success or local
finalization; further consequences remain Q017. M011 stays open pending real
Jetson/SSH-SFTP deployment validation; M012 stays complete for Slice 24.

---

# M014 - Phase 14 / Slice 27 Ingestor Crash Recovery and Handoff Reconstruction

**Status:** Completed

## Goal

Implement Decisions 276-280: preserve all accepted runtime evidence through an
Ingestor-owned local append-only JSONL recovery journal, durably before ACK,
and reconstruct the normal evidence/handoff working view for the same known Session.
Slice 26 was redundant with completed Slice 25 and is not a separate implementation
slice; Slice 27 numbering is preserved.

## Accepted scope

- Journal all accepted messages, regardless of is_persistent, without changing permanent selection.
- Use evidence_id for identical-redelivery deduplication and conflicting-content rejection.
- Rebuild normal accepted state and deduplication before intake; reuse the Slice 22 compiler.
- Preserve successful reconstruction as persistent ingestor_recovery_evidence through normal acceptance.
- Tolerate a clearly truncated final append, but fail clearly on earlier completed-entry corruption.

## Completed validation and audit history

Decisions 276-280 are implemented and all SATISFIED in the final independent
re-audit. W034 records the completed software workflow and the actual sequence:

1. Initial implementation and independent manual Scenarios 1-5 PASS.
2. Original Scenario 6 exposed uncertain-fsync architectural ambiguity, not an
   implementation failure: complete valid bytes survived a reported durability
   failure despite correct live rejection/no ACK. Decision 276 was clarified
   in place, without a new decision or commit protocol; regression coverage was added.
3. Independent manual Scenario 6R PASS under the clarified live/restart semantics.
4. Initial independent audit FAIL for one separate blocking P2: corrupt final
   numeric-looking suffixes could be silently treated as interrupted JSON.
5. Minimal numeric-prefix/context correction without public API, journal-format,
   ownership, protocol, or architecture changes; Scenario 7's nine manual checks PASS.
6. Targeted independent re-audit PASS: original P2 FIXED, no blocking findings,
   102 corruption probes, 80 genuine numeric-truncation probes, and one valid
   complete-record/no-newline probe passed.

Final automated results, reported after correction and independently confirmed:

- Slice 27 recovery: **25 passed, 0 failed**.
- Storage/communication/NATS regressions: **39 passed, 0 failed**.
- Artifact handoff/retrieval/verification/global evidence/Controller/start-rejection
  regressions: **82 passed, 0 failed**.
- Full discovery: **383 total, 376 passed, 0 failed, 7 optional rendering skips**.

These are prior implementation/re-audit results, distinct from independent manual
IPython validation. No tests, new manual validation, or new audit were run during
documentation closure. Original Scenario 6 remains an ambiguity discovery, not
a final PASS or implementation FAIL.

## Boundaries and dependencies

Implementation, automated tests, and independent manual software validation cover
durable ordering, journal failure without ACK, restart/deduplication, interrupted
final writes, corruption rejection,
recovery evidence, and unchanged handoff/persistent compilation. W034 records
the final corrected independent re-audit PASS and software closure. No new
component/database/snapshot/identity/handoff, producer
retry machinery, application restart orchestration, or Session cleanup policy is
accepted. Journal lifecycle and application-wide discovery/resumption remain Q024.
Q019 remains OPEN: durable Ingestor recovery does not prove Session-wide consumption
to Controller before archive closure. M013 and M012 stay complete; M011 stays open.
Closure does not validate live JetStream server crash/recovery, hardware deployment,
real Jetson/SSH-SFTP, application-wide restart/discovery, or scientific artifact
reconstruction beyond the existing handoff semantics.

---

# Future Milestones

Planned future milestones include:

- First Jetson CSI camera
- First lick sensor integration
- First synchronized multi-device acquisition
- First Parquet backend
- First microscope integration
- First NWB export
- First distributed acquisition across multiple nodes

These milestones will be added as they are successfully demonstrated.
