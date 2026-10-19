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
- historical Controller v1 two-step Session Record persistence ending with durable completed evidence

## Confidence gained

One bounded Session can be orchestrated and finalized through public framework APIs without introducing GUI behavior, asynchronous execution, retry, or new ownership boundaries.

This records the Phase 4 validation, not the current persisted terminal-record
shape. Phase 13 subsequently separates archive/record persistence and writes
both before `Session.complete()`; terminal snapshot representation remains for
separate review. M004's historical validation and completion status are unchanged.

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
cleanup/retention policy, restart recovery, or export is included. Decision 303
prevents later global processing failure from retroactively changing a completed
Session. Required pre-completion persistence remains unchanged; Q019's final
archive consumption coordination remains open. No real SSH/SFTP deployment
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
or verifier plugin framework. Decision 303 resolves the former Q017: later global
processing failure does not retroactively change a completed Session's lifecycle.
Broader ScientificProduct structural contracts
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
finalization. Decision 303 also preserves a Session's completed lifecycle despite
later global processing failure; Q019 is CLOSED following overall software integration validation (W050). M011 stays open pending real
Jetson/SSH-SFTP deployment validation; M012 stays complete for Slice 24.

---

## Subsequent accepted Q019 qualification of M013

Decisions 356-360 qualify the historical collection-evidence route and finalization
order above: Stage A acquisition preservation permits successful Session completion
before later operator-requested collection; Stage B directly persists StorageManager
collection evidence and permanently closes the same archive. M013/W033 remain
complete for their original validated scope. The new Q019 contracts are accepted,
not fully implemented or independently validated. Decision 361's receiving
foundation and routing prerequisite are separately complete with automated testing,
independent manual validation, and final independent re-audit PASS in W041;
the producer/marker prerequisite is separately complete after correction in W042.
Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048); the explicit Stage A slice under Decision
362 is complete with automated testing, independent manual validation, and
independent audit PASS (W043). Bounded Stage B collection/direct persistence is
complete with independent manual validation and final targeted independent re-audit
PASS after correction (W045); W046 explicit closure is complete with independent
validation and targeted re-audit PASS after correction. Decision 365's bounded
Normal Stop integration is complete with independent validation and targeted
re-audit PASS after correction (W047); Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048).
The bounded Decision 364 durable handoff
is complete with automated testing, independent manual validation, and independent
audit PASS (W044).
Original implementation results and audit records above are unchanged.

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
At this slice's closure, Q019 remained open: durable Ingestor recovery alone does
not prove Session-wide consumption to Controller before archive closure. Q019 is
now CLOSED through W041-W050. M013 and M012 stay complete; M011 stays open.
Closure does not validate live JetStream server crash/recovery, hardware deployment,
real Jetson/SSH-SFTP, application-wide restart/discovery, or scientific artifact
reconstruction beyond the existing handoff semantics.

---

# M015 - Phase 15 / Slice 28 Controller-owned Session Launch and Runtime Assembly

**Status:** Open - sequential DeviceAdapter reuse implemented; independent validation and audit pending

## Goal

Implement accepted Decisions 281-302 without adding another startup authority
or changing domain ownership: Controller resolves prospective selections and
current participant/device readiness, atomically reserves AcquisitionNodes,
constructs final SessionConfig, and creates/initializes Session.

## Implemented scope (independent validation pending)

- Session-independent RuntimeParticipant identities and node-owned declared inventory using existing declarations/products.
- Pre-Session node reports with reserved_for_session_id, complete enabled-device readiness, and service-only aggregate ready.
- Controller-interpreted unknown for missing/invalid current reports, without a readiness enum.
- DeviceDeclaration.required governs selected-device criticality; DeviceReadiness no longer carries required.
- Mandatory Ingestor and SynchronizationManager launch readiness, without global StorageManager as a prerequisite.
- Atomic node-owned reservation with same-Session idempotency and owner-keyed release after acquisition/local finalization, not global collection.
- Nonreusable intended Session IDs, resolved optional omissions, required initialization/preparation before success, and Controller rollback of failed launches.
- Operational launch results without durable pre-Session journaling or another lifecycle state.
- Participant-scoped pre-Session NATS communication without fabricated Session IDs, while Session-specific commands validate real identities.
- Node-owned Session binding and local initialization; Session authorizes local storage creation and nodes physically create managers using deployment-local roots.
- Confirmed mandatory-participant preparation, independently of service readiness; missing/invalid/unresolved responses do not prove success or absence of remote state.
- Idempotent Session-keyed initialization cleanup; unconfirmed cleanup protects node reservation until confirmation allows release and binding clearance.
- Ingestor intake/recovery-journal and SynchronizationManager synchronization-state preparation preserve existing evidence durability and scientific timing ownership.

Decisions 295-301 resolved the earlier distributed initialization handoff blocker.
The subsequent implementation uses existing NATS messages and domain components
for readiness, reservation, participant-local preparation, and cleanup-confirmed
rollback. No remote Session replicas or participant-process startup authority
were introduced.

## Validation and boundaries

### Sequential-reuse implementation (Decision 302)

The generic DeviceAdapter lifecycle correction is implemented with automated
regression coverage. Successful device shutdown returns retained adapters to
DECLARED only after adapter-specific cleanup, keeping initialize(config) restricted
to DECLARED. Failed cleanup retains FAILED; unconfirmed local Session cleanup
continues to protect readiness, reservation release, and subsequent binding.
Declared readiness does not open hardware. AcquisitionNode retains instances,
inventory, and deployment configuration; each Session receives its own settings
through resolved SessionConfig rather than inheriting the previous Session's.

Tests cover generic DeviceAdapter/DeviceManager reuse and OpenCV capture release,
Session A -> Session B on retained node/adapter/communication-handler instances,
confirmed initialization-abort reuse, repeated cleanup failures, independent
configuration, and preservation of Session A artifacts and evidence. Sequential
normal-completion coverage originally used fresh central Ingestor/SynchronizationManager
contexts before Decision 313 binding release was implemented. W035 now records
the separately completed Phase 16 Session-binding release slice; it does not
close the broader Slice 28 milestone. The separate Decision 302/Slice 28
validation and audit criteria remain pending under M015. No Controller
reset workaround, new lifecycle state/reset API, concurrent sharing, or recovery
subsystem was introduced; automated coverage alone does not close M015.

### Existing validation boundaries

Automated tests exercise actual message serialization, command/result handlers,
Controller launch, mandatory participant preparation, node-owned cleanup and
reservation release with controlled in-process broker doubles. Live NATS,
multi-process, hardware, independent manual IPython validation, independent audit,
and a Slice 28 validated workflow are not claimed by this milestone. W035 records
separate software validation and audit of Phase 16 binding release, not fulfillment
of M015's remaining launch/deployment validation criteria. M015 is not complete.
The first deployment target (one PC, one Jetson, one camera) is not
a cardinality limit; existing communication boundaries must support separate
processes/machines and multiple nodes/Controllers.

Historical development starts participants manually in independent processes.
Decision 376 requires one long-lived Ingestor-StorageManager process with shared
startup/shutdown/restart, plus independent Controller, SynchronizationManager, and
node processes. Local calls within the pair are permitted; process-crossing access
uses NATS. Composition/reconciliation is not yet implemented or validated.
Controller does not manage NATS or launch participant processes. Required startup
NATS connectivity precedes claimed operational distributed readiness; connection
failure is explicit and does not wait indefinitely or introduce automatic retry.

Client/GUI design, scheduling/device sharing, discovery/deployment configuration,
service supervision, shared multi-Session scheduling, crash/stale-reservation
recovery, leases/heartbeats/timeouts, retry, durable launch auditing, global
collection scheduling, retention/deletion, application restart/journal cleanup,
and Session-wide archive-consumption coordination remain deferred. Q019 and
Q024 remain open; Q022 retains deployment configuration ownership. Completed
M014/W034 and other completed milestones/workflows are unchanged. No validated
Slice 28 workflow is added.

Normal end-of-Session binding release for Controller, Ingestor, and
SynchronizationManager was not implemented by Slice 28; the subsequent narrow
Phase 16 implementation under Decisions 313 and 322 is now complete, manually
software-validated, and independently audited (W035). Duplicate participant
identity policy, deployment/startup
automation, and supervision remain deferred. Decision 302 settles generic device
cleanup/reuse, not implementation of those service binding-release contracts.

---

# Future Milestones

Phase 16 Operational Service Lifetime and Framework Stop/Kill architecture is
accepted in Decisions 304-365. At the earlier checkpoint implementation was
limited to the Session-binding release slice. Decision 323 adds the accepted
framework Evidence Archive partition; individual-service stop/kill/cancel is now
complete, manually software-validated, and independently audited PASS (W036),
including Decision 324 closeout ordering. Progressive coordinated shutdown is
also complete, manually software-validated, and independently re-audited PASS
(W037). Decision 325 replaces the global all-or-nothing precheck with an
informational local survey and progressive dependency-safe shutdown, with separate
authorization for each blocked service and no automatic rollback or restart.
Decision 326's validated two-phase closeout has StorageManager and
Controller prepare actual cleanup and preserve its evidence before Ingestor
retirement, without changing retirement order or W036 individual maintenance.
The narrow Controller/Ingestor/SynchronizationManager
binding-release slice is complete and independently software-validated (W035);
Phase 16 as a whole is not complete. Principal service lifetime is independent
of Session and GUI lifetime; scoped operational
stop/kill remains distinct from existing Session stop/finalization and must not
initiate global processing. Decisions 313-321 settle binding release, general
shutdown versus individual service maintenance, pre-stop evaluation, explicit
directional blockers, exact forced outcomes, and evidence-preservation order.
Session-independent framework evidence uses minimally extended existing
infrastructure; independent startup/returning-service recognition does not resume
interrupted work. Q025 is resolved architecturally, while Q019's Session-wide
evidence-consumption coordination, Q021, and Q024 remain open.
This does not close M015 or establish a completed Phase 16 milestone. W035 records
only the completed Session-binding release slice; W036 records individual-service
maintenance, W037 records coordinated shutdown, W038 records startup/return
integration, and W039 records the completed supported Q024-B recovery/reconciliation
slice after independent validation and corrected re-audit PASS. Controller release
after confirmed cleanup and final persistence, plus empty Ingestor/synchronization binding release, are
implemented. The narrow follow-up also implements evidence-bearing Ingestor release
after exact persistent-message/all-runtime-audit archive coverage and existing
terminal Session Record evidence, and SynchronizationManager release after stopped
time, retired mappings, and durable Ingestor acceptance. Concurrent intake/release,
failed-write retention, and successive reuse have automated coverage, supplemented
by manual IPython validation and independent audit PASS for this narrow slice.
Controller captures Session object identity and checks it after every unsubscribe
await and before retirement, so delayed/overlapping release cannot retire a newer
binding or alter its decisions, subscriptions, command history, or last-release
status. Current archival coverage remains guarded through release commitment.
This does not establish Q019 completeness or M015 closure. Service
supervision and deployment configuration remain future
work. M015 remains open pending independent validation/audit.

Decision 322 accepts persistence for every ControllerActionDecision, including
no-mutation outcomes, through the existing runtime evidence and Evidence Archive
pathway. Controller release additionally requires confirmed archival of its
Session's decisions; publication alone is insufficient. The narrow Slice 1
follow-up implements persistent decision packaging, attached-Ingestor submission,
exact inclusion checks against compiled archive input, and confirmation after
successful archive/final-record writes. Missing decisions or changes during/after
the snapshot cannot authorize release. Confirmed release retires temporary decision
records without deleting durable evidence. W035 validates these owner-specific
release paths under Decisions 313 and 322; it does not itself validate the separate
individual-service maintenance (W036), coordinated shutdown (W037), or startup responsibilities,
close M015, or resolve Q019/Q024.

## Completed individual-service maintenance slice validation

**Status:** Complete - narrow software implementation, manual IPython validation,
and final independent audit PASS (W036).

Individual-service stop, authorized kill, and cancel are implemented and validated.
Decision 324's two-stage cleanup, evidence preservation, and retirement ordering
are satisfied. The original four audit findings and subsequent authorized-kill
premature-completion evidence defect were corrected and validated, including
independent re-audit of the latter. W036 records the manual scenarios and reported
full-suite result: 541 run, 534 passed, 7 optional rendering skips, zero failures.

This completes only individual-service maintenance, not Phase 16 or M015.
Coordinated shutdown is separately validated in W037; startup/returning-service
integration is separately validated in W038. M015 retains its separate launch/reuse validation and audit
criteria; Q019 is CLOSED in W050; Q024 remains open. No hardware or external live NATS validation
is claimed, and no tests were rerun during documentation synchronization.

## Completed progressive framework shutdown slice validation

**Status:** Complete - narrow software implementation, independent manual IPython
validation, and final independent re-audit PASS under Decisions 325-326 (W037).

The validated sequence is informational survey; progressive AcquisitionNode and
SynchronizationManager stops; StorageManager then Controller preparation and
archival confirmation; Ingestor retirement; StorageManager retirement; Controller
retirement. Prepared orderly retirement requires complete current Evidence Archive
coverage of Ingestor's retained final persistent runtime evidence and all intake
audit. Coverage is rechecked after asynchronous callbacks and remains guarded
through retirement commitment; missing coverage prevents confirmed retirement.

- Independent manual validation passed normal shutdown and fault-injection
  scenarios, including earlier-compilation replacement, audit-only loss, and
  audit loss during StorageManager's asynchronous retirement callback.
- Final independent re-audit: PASS, no blocking defects or architectural ambiguities.
- Focused regressions: 174 passed, zero failures or skips.
- Full suite: 574 run, 567 passed, 7 optional rendering skips, zero failures.
- Four independent memory-only negative controls detected removal of the final
  compilation enforcement; the unmodified correction passed regression coverage.

These are preceding validation/audit results, not new tests performed during
documentation closure. W037 records the workflow and preservation correction;
W035/W036 historical results are preserved. No real hardware, live cross-process,
or external NATS deployment validation is claimed. Startup/returning-service
integration is separately validated in W038; Phase 16 remains incomplete.
M015 retains its separate launch/reuse validation criteria, and Q019 is CLOSED in W050; Q024 remains open.

## Completed independent startup and returning-service integration slice validation

**Status:** Complete - narrow software implementation, independent manual IPython
validation, and final independent re-audit PASS under Decisions 327-331 (W038).

Starting and returning services announce existing identity/readiness through NATS;
configured dependencies receive announcements directly and update their own
readiness without Controller relaying or maintaining a registry. Existing
readiness, reservation, cleanup, and ownership protections govern safe reuse.
Explicit administrator resume/drop decisions are framework evidence, not execution.
Startup/return and meaningful readiness/obligation evidence use existing
Ingestor/StorageManager preservation contracts; unavailable archival confirmation
requires an operator warning without inventing another persistence system or
blocking startup when other accepted prerequisites are satisfied.

The first independent audit failed on two P2 readiness defects. Both were corrected
and passed three additional manual validation cells and final independent re-audit
PASS; the initial eight manual cells and correction history are recorded in W038.
Focused regression: 230 passed, zero failures. Full discovery: 603 run, 596 passed,
7 optional rendering skips, zero failures. These are previously executed results,
not validation performed during documentation closure; no hardware or live external
NATS deployment validation is claimed.

W035-W037 and Decisions 325-326 remain complete for their respective narrow scopes.
Phase 16 and M015 remain open;
Q019, Q022, and Q024 remain unresolved. The startup/return slice does not authorize
resume/drop execution; supported Q024-B actions are separately validated in W039.
Deployment/discovery details, process supervision, automatic launch/restart/retry/replay,
and GUI implementation remain outside this scope. The Services tab remains a separate future
design proposal.

## Accepted Q024 service-specific unresolved-work and abandonment contracts

**Status:** Architecture accepted and synchronized in Decisions 332-338;
narrow implementation slice complete with automated regression coverage,
independent manual IPython validation PASS (10 scenarios), and independent
read-only source audit PASS with no blocking findings. These results were reported
for documentation closure, not executed during this documentation task.
Decision 336 remains partially implemented: only guarded release of redundant
producer-owned evidence copies. This does not complete Q024, Phase 16, or M015.

Reuse existing readiness/diagnostic/command interfaces and service-owned records
to report unresolved previous work and distinguish obligation outcome, recovery
possibility, and operational impact. Existing identities and ownership define the
affected scope; limited restrictions require sufficient demonstrated protection,
without assuming other potentially affected resources safe when containment is unknown.

Explicit administrative drop records the administrator, service/obligation,
decision, and available justification and closes work as abandoned/not recovered.
It does not confirm original success, cleanup, resource safety, or recovery.
Unnecessary temporary memory may be released only after recorded abandonment and
applicable evidence-preservation, safety, and closeout obligations are satisfied;
minimum required safety information and durable records/journals remain protected.
Reuse existing producer-owned framework evidence and separate publication,
Ingestor acceptance, and StorageManager archival confirmation.

Implemented readbacks use existing owner records and readiness commands for all
five services. Explicit drop records abandonment separately from actual outcomes;
guarded memory release is limited to redundant interface-owned producer evidence
copies, preserving current complete archival and exact journal-backed acceptance
through commitment. Existing resource guards, administrative markers, idempotent
command/results, and durable journals remain. Resource-specific recovery execution
is separately accepted and independently validated/audited for supported Q024-B
cases in W039; wider cache retirement still lacks the applicable
safety/closeout/idempotency-lifetime contracts.
Automated tests do not replace independent manual validation or audit; both have
now passed for this narrow scope.

W038 and earlier validated workflows retain their completed narrow scopes. No new
workflow is added during this documentation closure. Phase 16 and M015 remain
open. Detailed service-specific recovery procedures, resume/drop execution beyond
this administrative reporting and safe-closeout boundary, journal retention/deletion,
and broader application recovery remain Q024 work. Q019 retains Session-wide evidence
consumption/finalization and Q022 retains deployment configuration/discovery.
No universal/automatic recovery, replay, retry, resumption, deletion, GUI,
supervision, new Session states, or additional recovery subsystem is authorized.

## Q024-B: Service-specific operator-authorized recovery execution

**Status:** Architecture accepted and synchronized in Decisions 339-346;
accepted clarifications 347-348 synchronized; supported service-specific cases
complete with automated regression coverage, independent manual IPython validation,
and final independent read-only re-audit PASS after correction (W039). Phase 16
and M015 remain OPEN; this closes only the supported Q024-B implementation slice.

Final implementation testing: 656 run, 649 passed, 7 optional skips, zero failures.
Initial independent manual validation: PASS (22 checks). Initial independent source
audit: FAIL on one P2 Controller reconciliation defect. After correction, focused
independent manual revalidation passed 16 checks and the final independent re-audit
returned PASS with no blocking defects or architectural ambiguity; it independently
ran 20 relevant automated tests, all passed. Retained scientific-manifest recovery
corrections were completed before the initial source audit. W039 records the seven
implementation units and preserves this failed-then-corrected audit history.
These are prior results, not tests run during documentation closure; no live
external NATS, cross-process, Jetson, or hardware validation is claimed.

Supported implementation covers exact obligation/authorization/command correlation,
durably admitted archive/retained Session Record rewrites, fresh artifact transfer,
independent supported node artifact finalization/device cleanup, Controller
informational reconciliation, and historical synchronization/continuity reporting.
Actual actions and outcome archival are reported separately. Missing trustworthy
inputs, uncertain artifact writes, unowned temporary-copy cleanup, and active-
Session clock restoration are not claimed as supported recovery.

New service-specific recovery attempts require explicit human administrator
authorization for the original obligation, recorded through the existing
administrative evidence interface and referenced by execution commands. Owners
validate authorization, identities, scope, prerequisites, and safety immediately
before attempting work. Authorization does not establish success, abandonment,
or authority for unrelated work. Existing command/results and runtime evidence
preserve successful, failed, and refused attempts and separate actual outcomes
from durable confirmation; no universal recovery operation or registry is added.

Accepted service boundaries:

- StorageManager: Fresh complete artifact transfer with proven temporary-copy
  identity/destination safety and unchanged source; persistent-record rewrites
  require complete trustworthy inputs and actual durable confirmation. No byte-
  level resumption, unexpected final overwrite, invented evidence, or transfer
  of Ingestor compilation ownership.
- Ingestor: No new recovery mechanism. Accepted automatic valid-journal
  reconstruction for an already-known Session remains under Decisions 276-280
  without new administrator authorization; report failures and do not accept
  corrupted completed entries.
- AcquisitionNode: Independently authorized partial scientific-artifact
  preservation and device/resource cleanup, preserving actual records, authoritative
  local artifacts/manifests, terminal Experiment identities, and confirmed reuse safety.
- Controller: Read-only reconciliation of trustworthy records and confirmed
  participant outcomes without authorization merely to read. Missing/uncertain
  outcomes remain unresolved; new operational commands are separately authorized,
  not replayed automatically or used to restore application/lifecycle state.
- SynchronizationManager: Preserve historical timing/mappings and report active-
  Session continuity gaps, affected scope, and uncertainty; establish valid current
  synchronization through existing authority. No fabricated observations, timestamp
  mutation, mapping extension across downtime, or automatic Session failure/discard.

The completed, independently validated/audited Decisions 332-338 narrow slice and
all prior validation records remain intact. Decision 336 remains partially
implemented, limited to guarded release of redundant producer-owned evidence copies.
Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN. Journal retention/deletion,
abandoned journals, application-wide Session discovery, Controller/application
restoration, stale reservations, and remaining memory/cache retirement are deferred.
No new automatic recovery/replay/retry/resumption, process supervision, Session
states, durable deletion, evidence infrastructure, Q019 finalization guarantees,
or Q022 deployment configuration is introduced.

Decision 347 removes the circular pre-repair archive requirement: authorization
and attempt must be durably journal-accepted by Ingestor before the authorized
repair, followed by distinct actual-write and recovery-outcome archival
confirmation. Decision 348 permits historical timing reconciliation and explicit
uncertainty reporting after active Session Time is lost, not an invented clock
restoration or zero-based restart. Healthy mapping updates remain unchanged.

## Remaining Q024 architecture and startup implementation progress

W070A is CLOSED for Decision 392's independently durable Ingestor closed-Session
admission protection before terminal binding release, preserving existing
StorageManager confirmation and journal-integrity guards. Construction,
preparation and intake reject closed identities after restart independently of
temporary journal retention. Empty initialization release remains distinct.
W070A-A1's P2 cross-instance admission/publication race is corrected by holding
the existing root exclusion through admission and release commit. Post-correction
verification passed 60 distinct checks (54 synchronous, six controlled async);
independent manual IPython validation passed 16/16 and final source audit passed
with no remaining confirmed P0-P3 findings. The initial 6/6 manual result and
subsequent P2 finding remain recorded in W070A in validated_workflows.md; counts
are not additive. No live NATS, independent-process deployment, hardware, actual
OS-signal, power-loss or normal Windows asyncio scheduling campaign is claimed.
W070B / Decision 349 implementation is tracked below under Decision 393. Decision 350
deletion and Decisions 353-355 remain outside this slice. Q024 remains OPEN and all unrelated
milestone statuses are unchanged.

W070B (CLOSED) implements Decision 393 journal-independent post-release closeout
using permanent Session evidence, complete intake audit, final record and handoff,
with original verified receipt provenance added only to the existing compilation
summary. Gate A passed before enabling Ingestor-owned retirement. Retirement
requires current permanent proof, durable closed admission, completed binding
release and an intact matching journal when present; root/storage guards span
verification and deletion. Retries reverify proof even when unlink already took
effect. Missing provenance, damaged journals, unconfirmed preservation and active
bindings retain journals. No framework evidence or permanent products are deleted.
Independent ICC IPython validation passed 9/9 probes; independent source audit
passed with no confirmed P0-P3 findings. Implementation verification passed 69
distinct checks (11 Gate A, 20 Gate B and 38 affected existing checks); three
hard-link integration checks were blocked by sandbox permissions, not passed.
No live NATS, physical power-loss or normal Windows asynchronous scheduling
campaign is claimed. See the W070B closure record in validated_workflows.md.
Q024 remains OPEN: Decision 350, Decisions 353-355 and their unresolved operational
contracts are not completed by this bounded Decision 349/393 workflow.

Decision 391 records the accepted best-effort Controller restart/bounded Session
reconnection clarification of Decisions 345/346/351/352. Existing status,
readiness, reservations and durable evidence support reconciliation without
automatically stopping safely recording nodes. Experimenter-requested original-
Session reconnection requires Controller-established safety and scientific
validity; partial operations require proven safety without unreachable participants,
whose identities and obligations remain unresolved. Preserve original recordings,
timestamps and Session identity and document supervision/timing gaps. No extensive
historical replay or substantial new recovery infrastructure is required or
authorized solely for rare reconnection. Existing safe termination/abort and
partial-data preservation remain the fallback when reconnection cannot be safely
established simply; abandonment implies neither data deletion nor resource release.

**ICC preliminary implementation assessment (not an architectural decision):**
defer operational reconnection because a small, safe implementation boundary has
not been established. This recommendation is not an implementation or validation
result. Operational reconnection remains unimplemented, untested and unvalidated;
Q024 remains OPEN. Historical W039/W040 results below are not reconnection validation.

Decisions 349-355 accept Ingestor-owned conditional temporary-journal retirement,
informed operator-authorized terminal loss of identified unrecoverable temporary
evidence, Controller startup reconciliation of known observable participants,
protected node-owned reservations, and principal-service temporary-memory retirement.
They preserve journal-before-ACK, known-Session reconstruction, device safety,
deduplication, and existing service ownership; no automatic application restoration,
Session-object restoration, operational replay, or reservation expiry is accepted.

Decision 354 explicitly supersedes only Decision 323's shared permanent framework
archive layout with `framework/evidence/YYYY-MM/` partitions and the same three
products. Closed monthly partitions are immutable and not rewritten for later
evidence. Session archives and scientific artifact storage are unchanged; temporary
Ingestor journals are not monthly-rotated. Decision 355 requires safe-to-delete
archives to be independent of every later operation/recovery, distinct from being
finalized. Permanent archives are never automatically deleted.

The accepted LLC clarification under Decisions 353-355 permits one operation to
span months with existing identities, without splitting it or rewriting historical
archives. Unfinished-work recovery information must remain independent of finalized
history, and archives declared safe to delete cannot be future recovery inputs.
The subsequent accepted clarification resolves assignment using StorageManager's
local system clock at write time with UTC month boundaries, without scientific
retimestamping or a synchronization dependency. Bounded monthly persistence now
appends new evidence/audit suffixes and verifies cumulative coverage across intact
partitions; existing journals preserve operational state and identities across
restart. Shared-layout historical products remain read-only. Clock failures,
backward month assignment, conflicting history and incomplete writes fail closed.
Complete uncertain writes require current durable reconciliation before reuse;
identified same-month interrupted writes retain existing authorized repair.
Older/unidentified incomplete targets remain unsupported and blocked.
This bounded monthly slice is CLOSED as W071 following independent ICC IPython
validation (6/6 PASS) and independent implementation/source review PASS with no
confirmed P0-P3 findings. Q024 remains OPEN; historical deletion independence and
eligibility, broader memory retirement and other recovery obligations are not closed.

Focused implementation verification passed 59 distinct checks: 35 synchronous
and 24 controlled asynchronous, including 19 new permanent regressions. Controlled
coroutines used an explicit test event loop without socket-pair initialization;
this is not a normal Windows asynchronous scheduling campaign. Default sandbox
temporary paths were inaccessible; successful runs used temporary directories in
the permitted repository workspace. No live NATS, real sockets, OS signals,
hardware or physical power-loss validation is claimed. Historical workflow
records are unchanged; see W071 in validated_workflows.md for the bounded closure.

Supported Decisions 351-352 startup reconciliation is complete, independently
manually validated and independently re-audited PASS after correction (W040),
through the existing NATS service startup path, explicit known identities,
bounded readiness requests, and owner diagnostics. It preserves safe acquisition,
node reservations, independent preservation/cleanup obligations, and unchanged
informational evidence. W040 records ICC review, initial manual validation (28/28),
the failed source audit's P2/P3 findings, correction revalidation (25/25), and final
re-audit PASS with 132 focused tests, two independent probes, and two negative
controls. Codex post-correction testing: 676 run, 669 passed, 7 optional rendering
skips, zero failures. No validation was performed during documentation closure.
Bounded Decision 349/393 journal retirement is complete in W070B; Decision 350
and Decisions 353/355 remain unimplemented; Decision 354 has bounded monthly
implementation independently validated/reviewed and CLOSED in W071. Cumulative confirmation and
maintenance lookup still require retained historical products, so no historical
archive is declared safe to delete. Broader deletion independence remains outside
this slice. Q019 is CLOSED in W050; unavailable auditing
for terminal deletion is an architectural conflict, not an accepted exception.
Remaining memory/idempotency limits and application-wide discovery/restoration
remain open. No new implementation milestone or recovery subsystem is introduced.

Q024-B Decisions 339-348 remain complete, independently validated/audited in W039;
all earlier workflow records are preserved. Decision 336 remains partially
implemented. Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

## Accepted Q019 acquisition closeout and later collection (receiving and publication prerequisites validated)

Decisions 356-365 accept producer-confirmed acquisition evidence completion plus
independent Ingestor consumption proof, Stage A acquisition evidence/audit/summary
and final Session Record preservation, durable StorageManager handoff preservation,
and later operator-selected stopped-Session collection without original bindings.
StorageManager directly preserves its own Stage B collection evidence, distinguishes
that origin without fabricated Ingestor audit. Permanent closure requires a separate
explicit operator request, all applicable collection outcomes durably recorded,
no unresolved evidence writes, and verified consistent durable archive preservation;
it is not automatic after collection or contingent on every artifact being retrieved
or verified. Confirmed closed archives are immutable, including after restart.
W046 closure is complete with independent manual validation and targeted independent
re-audit PASS after correction. Acquisition outcomes and final Session
Records are not rewritten.
Separately authorized Kill Session preserves accessible partial records and safety
while leaving the archive open for later collection; no killed lifecycle state or
automatic collection is accepted.

The accepted low-level contracts require restart-safe receiving position and
verified contiguous acknowledgment progress over the full relevant publication
interval (361); stage/closure information in the existing summary, backed by
verified consistent durability (362); temporary durable outcome/evidence-ID
preservation before direct archival and duplicate-safe evidence-write recovery
without transfer replay (363); a separate small Session-associated JSON handoff in
the existing Session directory and existing persistent information for selection
(364); and complete Normal Stop confirmations versus truthful partial Kill
preservation without weakening resource safety (365).

Decision 366 resolves required producer scope and response ordering: participating
AcquisitionNodes finish applicable evidence generation and durable publication
before existing successful completion responses, including when selected devices
are optional. Controller and SynchronizationManager finish applicable closing-Session
publication before the single marker; locally journaled Ingestor-owned evidence
remains in compilation/persistence without a JetStream round trip. The marker is
not the Stop command. The supported producer/marker prerequisite is complete
with developer automated coverage, independent manual validation, and targeted
independent re-audit PASS after the cursor-race correction (W042);
it neither requires long-lived service shutdown nor changes W041's completed scope.

Decision 361's receiving foundation and routing prerequisite are complete in W041:
developer full suite 710 run, 703 passed, 7 optional skips, zero failures;
independent manual IPython validation 6/6, 2/2, and 3/3 PASS at successive correction
stages; final independent re-audit PASS with 107 focused tests (including seven
real-server tests) and six additional live-NATS probes passed. Both failed audits
and their corrections are preserved in W041. These are previously executed results,
not tests run during documentation closure. Local NATS/software validation does not
claim external-cluster, multi-host, Jetson, or hardware deployment validation.

Bounded Stage A archival under Decision 362 is complete with developer automated
testing, independent manual validation, and independent audit PASS (W043). It requires W041
receipt of the W042 marker, protects current intake through persistence, and checks
the evidence/audit/summary plus final Session Record before confirming Stage A;
the archive remains open and Session lifecycle/bindings are unchanged.
W043 records 16 focused developer tests passed; independent manual IPython
validation 7/7, 5/5, and 5/5 PASS (17/17 total) using local real JetStream; and
independent audit PASS with no confirmed P0-P3 defects or corrections required.
Additional cross-thread archive-rewrite coverage was an optional suggestion,
not a closure condition. These are previously executed/reported results, not
validation performed during documentation closure.
The bounded Decision 364 handoff slice is complete with developer automated testing,
independent manual validation, and independent audit PASS (W044): explicit post-Stage-A compilation,
separate durable JSON/readback after restart, and applicable release protection.
W044 records 24 focused developer tests passed, independent manual IPython
validation 6/6, 5/5, and 6/6 PASS (17/17 total), and independent audit PASS with
no confirmed P0-P3 defects or required corrections. Filesystem/hard-link
prerequisites remain applicable; power-loss behavior was not independently tested.
These are previously executed/reported results, not validation during documentation closure.
It does not alter Stage A products or lifecycle. At W044 closure, Stage B and
Decisions 363/365 remained unimplemented; the bounded subsequent W045 progress is
tracked below. No overall milestone completion is claimed.

**W045 - Complete, bounded collection/evidence persistence; independent manual validation and final targeted re-audit PASS after correction.**
For a known Session, StorageManager may establish the trusted Stage A baseline from
validated existing Session products independently of cached state and original
Controller/Ingestor bindings (clarifications to Decisions 358/362/363). Stage B
preserves acquisition evidence, audit, and final Session Record; directly appends
collection evidence with distinct provenance; and recognizes confirmed evidence
without duplication. Restarted evidence-write recovery preserves established
contents and durable temporary outcomes/IDs under existing authorization, without
automatic refetch, repair, or new preservation infrastructure. Scientific-artifact
preservation is primary; operational-evidence uncertainty is not automatically
scientific-data loss. Mandatory evidence guarantees remain applicable.
The bounded implementation now validates persisted baselines, collects from saved
handoffs, retains durable temporary outcomes, directly appends collection evidence,
updates provenance, and supports existing authorized evidence-only recovery without
refetch. Initial developer testing passed 32 distinct targeted tests, and initial
independent IPython validation passed 9/9 checks. The initial independent audit
returned FAIL with two P2 defects: destructive replacement despite missing or
inconsistent Stage B provenance, and invalid Stage A confirmation from cross-Session
envelopes or incomplete intake audit. Corrections passed 14 developer tests and
3/3 independent manual checks. The final targeted independent re-audit returned
PASS with no remaining confirmed P0-P3 defects. These are previously executed
results, not validation performed during documentation closure.
**W046 - Complete, bounded explicit permanent Evidence Archive closure.**
Initial developer tests 27/27 and independent manual validation 8/8 PASS; initial
audit FAIL with one P2 final-record path-alias bypass; correction tests 6/6 and
independent correction validation 2/2 PASS; targeted independent re-audit PASS with
no remaining confirmed P0-P3 findings. Target/root normalization precedes managed
record identification, preventing bypass after restart without blocking pre-closure
writing. These are prior results, not validation during documentation closure.
No broader milestone closure is recorded.
**W047 - Complete, bounded Normal Stop integration.**
Initial developer tests 19/19 and independent IPython validation 6/6 PASS; initial
audit FAIL with two P2 defects: pre-marker cancellation permitting legacy completion
and late acquisition intake missing from the preserved final Session Record.
Corrections retain the Q019 association before asynchronous shutdown and require
current envelope/audit coverage under existing locks before completion. Correction
developer tests 12/12 and independent validation 3/3 PASS; targeted independent
re-audit PASS with no remaining confirmed P0-P3 findings. Stage B collection and
permanent closure remain separate requests. These are prior results, not new
validation during documentation closure; no broader milestone is closed.
**W048 - Complete, bounded Kill Session integration.**
Explicitly authorized Kill aborts the active Experiment and Session while keeping
participant cleanup, hardware safety, and release obligations separate. Available
evidence and partial handoff preservation do not claim complete receipt; authorized
refresh is pre-Stage-B only. Collection and permanent closure remain separate.
Initial developer tests 45/45 and independent validation 5/5 PASS preceded audit
FAIL with two P2 and one P3 findings. First corrections passed 13/13 developer
tests and 4/4 independent checks; re-audit found the remaining empty-intake P2.
Final correction passed 9/9 developer tests and 2/2 independent checks; final
independent re-audit PASS found no remaining P0-P3 findings. W048 preserves the
full history and Normal Stop guarantees. These are prior results, not new checks
performed during documentation closure; no broader milestone is closed.
**W049 - Complete, eligible-Session selection and multi-Session collection.**
StorageManager enumerates existing saved directories and independently confirms
terminal eligibility and safe collection availability. Controller processes selected
Sessions independently with per-Session and aggregate outcomes; ordinary single-
and multi-Session collection revalidate under existing guards. Initial developer
tests 14/14 and independent manual validation 6/6 PASS preceded audit FAIL with
P2 single-Session bypass and P3 nested fixture cleanup failure. Correction tests
24/24 and independent correction validation 6/6 PASS; final independent audit PASS,
both resolved and no new P0-P3 findings. W049 preserves the history and software-
validation limitations. No broader milestone closure is recorded.
**W050 - Complete, consolidated Q019 software integration; Q019 CLOSED.**
W041-W049 and their historical validation/audit records remain complete. Prior
developer integration tests 7/7 and independent manual checks 2/2 PASS; final
independent integration audit PASS, no confirmed P0-P3 production defects or
required corrections. The successful sequential Normal Stop probe is now a
permanent regression; newly executed developer integration tests 3/3 PASS.
These results do not establish hardware, multi-host deployment, external NATS,
or power-loss guarantees. Q019 closure does not close this milestone or Phase 16.
Eligible-Session selection and overall Q019 integration are complete; Q022 and Q024
remain OPEN.
W041-W044 remain historically complete and unchanged;
Phase 16 and M015 remain OPEN.

Q019 is CLOSED following overall software integration validation of its completed bounded slices (W050).
W042 records only the completed publication prerequisite: initial independent manual
validation 5/5 and 4/4 PASS; initial audit FAIL for the concurrent manifest cursor;
manifest/health lock correction with 10 focused developer tests passed; real
JetStream correction validation 7/7 PASS; and targeted independent re-audit PASS
with no remaining confirmed P0-P3 findings. These are previously executed results,
not new validation during documentation closure, and do not close a milestone.
The receipt proof has linear history-read cost and conservatively requires intact
global stream history from sequence 1; unrelated older history loss can prevent
confirmation. W041 does not establish producer confirmations, Session completion,
or archive preservation. No weaker closeout guarantee is substituted.
W033/M013, W035, W039, and W040 remain historically complete; Decision
336 remains partial; bounded Decision 349/393 is complete in W070B, while Decision
350 and Decisions 353/355 remain unimplemented, bounded monthly Decision 354
implementation is CLOSED in W071 after independent ICC validation/review PASS, and Q024,
Q022, Phase 16, and M015 remain OPEN.

## Completed NATS persistence boundary slice validation

Decision 376 preserves W051 as historical validation but removes the internal
NATS requirement for the combined Ingestor-StorageManager process. W052 completes
bounded local persistence. Decision 377 subsequently removes routine scientific
observations and metadata from envelope intake; that path is no longer required
for routine acquisition. W051/W052 validation histories below remain unchanged.
Active responsibilities retain durability, identity, corruption/readback, and
archival protections. Bounded scientific-local routing and operational-event
preservation are complete after correction, independent validation and final
re-audit PASS (W053); owner-level envelope removal and closeout reconciliation
are complete after independent validation and corrective re-audit PASS (W054).
Future streaming is open, not designed here.

Decision 378 now requires clean replacement, not indefinite envelope compatibility:
installation declarations and Experiment selections govern adapter scientific
production/local persistence. Remove obsolete collection contracts, scientific
envelope mechanisms and dead code/tests/docs only where no accepted responsibility
remains. Preserve scientific provenance, operational evidence, historical readback
and Q019 guarantees. The final independent integration audit must verify functional
preservation and absence of obsolete scientific-envelope architecture. W053 and
W054 close bounded Slices 3A/3B; W055 records final combined implementation
acceptance after functional audit PASS and targeted correction of the sole
clean-replacement P3, without a further independent re-audit as explicitly
determined by the user and ICC for the test-only cleanup.
Project/milestone statuses are unchanged.

**W051 - Complete, bounded Q022 Ingestor-StorageManager ownership boundary.**
Accepted-envelope persistence, current owner readback, journal-verified compilation,
and W041 receipt operations use NATS with stable write identity and fresh correlated
replies. Initial developer tests 32 PASS and independent manual checks 11/11 PASS;
initial audit FAIL for malformed correlation causing duplicate retry writes.
Correction tests 13 PASS, independent revalidation 14/14 PASS, and final independent
re-audit PASS, original P2 resolved with no remaining confirmed P0-P3 findings.
This does not establish full independent-service deployment or live NATS,
multi-host, hardware, or independently tested power-loss guarantees. Q019 remains
CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN with their separate criteria.

## Completed local correlated persistence slice validation

**W052 - Complete, bounded shared-process correlated persistence.**
Explicit local Ingestor-to-StorageManager persistence suppresses legacy automatic
forwarding and preserves W051 identity, retry/restart, corruption/legacy, durable
readback, and Q019 archive protections. Developer tests 17 PASS; independent
IPython validation 16/16 PASS; independent audit PASS with no confirmed P0-P3
defects (eight tests and two probes PASS). Permanent binding-abort ordering
coverage was committed before closure; four focused developer tests PASS.
Shared-lifetime bootstrap/enforcement and durable acquisition-intake reconstruction
remain deferred; synchronous I/O can block the event loop. No live NATS,
multi-host, hardware, or independently tested power-loss guarantees are established.
Q019 remains CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN.

## Completed product-based acquisition slice validation

**W053 - Complete, bounded product acquisition and operational evidence (Slice 3A).**
Installed declarations and Experiment selections govern adapter/manager collection
and local JSONL/HDF5 scientific persistence, separately from lifecycle, health,
failure and manifest evidence. Node legacy collection fallback and routine
scientific-envelope production/forwarding are removed. Initial developer tests
80 distinct PASS and independent IPython validation 17/17 PASS preceded an audit
FAIL for P2 loss of later-device observations after operational intake failure.
The correction attempts scientific preservation across completed collections
before operational intake, aggregating independent failures without false success
or replay. Corrective developer tests 37 distinct PASS (seven permanent new
regressions), independent correction validation 18/18 PASS, and final independent
re-audit PASS with no remaining confirmed P0-P3 findings (13 focused tests and
two negative probes, including injected journal fsync failure). Developer counts
are separate overlapping runs, not an additive unique total. See W053 for scope,
failure semantics and full validation history.

Temporary local storage and simulated devices/brokers do not establish live
multi-host, hardware or power-loss guarantees. W054 now closes bounded Slice 3B
owner-level envelope removal/closeout reconciliation; W055 now records combined
Decision 377-378 implementation acceptance, preserving the initial audit failure
and subsequent targeted P3 correction history.
W051/W052 history and Q019 CLOSED are preserved; Q022, Q024, Phase 16,
and M015 remain OPEN. These are recorded results, not new tests during closure.

## Completed operational-evidence closeout and envelope-removal slice

**W054 - Complete, bounded owner-level replacement (Slice 3B).**
Obsolete scientific-envelope intake/persistence, transport, recovery and
compatibility APIs are removed while operational intake/journaling/audit,
historical-record interpretation and Q019 closeout/collection/closure remain.
Initial independent audit FAIL identified P2 concurrent Normal Stop intake during
release and P3 dead envelope configuration in a product-failure test. Both were
corrected; release retains intake -> preservation locks through synchronous
retirement, not awaits. Final independent corrective re-audit PASS found no
remaining confirmed P0-P3 defects in scope. W054 records all separate developer,
manual validation and audit runs, including 25 corrective audit tests and ten
independent probes. Late intake remains Ingestor-owned and blocks stale release;
reconciliation does not authorize rewriting Stage B or closed archives.

W055 separately closes the combined Decision 377-378 implementation; this does
not close remaining Q022 deployment work. Q019 remains CLOSED; Q022, Q024, Phase 16 and
M015 remain OPEN. Historical W041-W053 validation is unchanged.

## Completed scientific-product replacement integration

**W055 - Complete, final Decision 377-378 implementation acceptance.**
The combined independent audit passed functional integration with 26 selected
tests and four independent probes, and initially failed clean replacement for
one P3: an unused HealthFakeAdapter record_kind argument/assignment. The test-only
cleanup passed nine targeted tests and git diff --check. The user and ICC accepted
that verification without another independent re-audit; no post-correction audit
PASS is claimed. W001-W054 histories and accepted architectural substance remain
unchanged. This does not establish live hardware, multi-host or power-loss
guarantees, full deployment, or future scientific streaming. Remaining Q022 work
includes owner-side NATS interfaces, cross-process orchestration/recovery,
shared-process bootstrap, configuration and installation verification.
Q019 remains CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.

## Completed Q022 Slice 2 Synchronization And Experiment Integration (W056)

Decisions 379-381 resolve the distributed scientific synchronization architecture
gate: measured cross-clock exchanges with delay/variability/uncertainty,
conservatively bounded explicit initial clock-rate assumptions, local authorized
affine mapping application, and preserved mapping history/node-local activation
boundaries. Acceptable synchronization is required at Session acquisition
readiness and before each Experiment. Configurable periodic quality assessment
is distinct from complete resynchronization; temporary degradation retains timing,
provenance and degraded status with existing policy/Controller consequences.
Advanced Q006/Q018 work remains open except for the minimum demonstrably valid
measurement method required by the current implementation. W056 closes this
bounded implementation after independent manual validation and final audit PASS
of 3e573f5, with no confirmed P0-P3 findings. It records all three resolved P2s:
historical timestamp quality, periodic publication recovery and rejected-stop
cancellation. Validation runs overlap and are not an additive test total.
Local JetStream separate-process coverage is not hardware timing, multi-host clock
accuracy or power-loss validation. W001-W055 are unchanged; Q019 remains CLOSED,
and Q022, Q024, Phase 16 and M015 remain OPEN. Remaining Q022 deployment and
installation obligations are not closed by W056.

## Completed Q022 Slice 3 Operational Evidence Transport (W057)

**Status:** CLOSED - bounded implementation, independent IPython validation and
read-only audit PASS of 880b108; no confirmed P0-P3 findings.

AcquisitionNode evidence retention/publication feeds Session-specific JetStream
consumers with subject/payload identity validation, journal/fsync-before-ACK,
stable deduplication, restart recovery and post-callback binding checks.
`read_runtime_evidence_acceptance` verifies exact current journal-backed intake;
publication, acceptance, W041 receipt and archival preservation remain separate,
and neither publication nor acceptance authorizes scientific-artifact release.
Scientific observations remain node-local; StorageManager and handoff ownership
are preserved.

W057 records 52 developer tests, nine additional affected checks, independent
IPython PASS, and audit verification of 50 tests and three probes. Runs overlap
and are not additive. Actual local JetStream separate-process coverage does not
establish multi-host, hardware or power-loss guarantees. Subject consistency is
not authentication; optional callbacks are not a durable retry queue. Broader
Controller/recovery/deployment integration remains outside the closed slice.
Q019 and W001-W056 remain closed with historical records unchanged. Q022, Q006,
Q018, Q024, Phase 16 and M015 remain OPEN.

## Completed Q022 Slice 4 Remote Saved-Session Collection (W058)

**Status:** CLOSED - bounded single saved-Session NATS collection, independent
IPython validation and final read-only audit PASS of d788d2e; no confirmed P0-P3
findings. Controller needs no local Ingestor/StorageManager; the shared receiving
process retains separate component authority, owner eligibility/collection guards
and direct Stage B persistence. Fresh-only subscriptions, complete scoped history
validation and nonce-associated command/destination consistency resolve all three
P2 replay/correlation findings. Durable outcomes support retries without refetch;
publication, acceptance, receipt, archival and release remain separate.

W058 records 39 developer tests, independent IPython 3/3 PASS, 39 audit tests and
three additional fault-injection checks. Counts overlap. Actual local JetStream
separate-process restart/retry verification passed with simulated SFTP; no
multi-host, physical hardware/SFTP or power-loss validation is claimed.
Full cross-process closeout, Stage A/handoff, completion/release, saved-Session
enumeration/batch selection, explicit closure, broader recovery and deployment
configuration/launching/installation verification remain outside this slice.
Q019 and W001-W057 remain CLOSED. Q022, Q006, Q018, Q024, Phase 16 and M015 remain OPEN.

## Completed Q022 Slice 5 Remote Evidence Archive Closure (W059)

**Status:** CLOSED - explicit permanent closure of one saved Evidence Archive
over NATS, independently validated and final focused audit PASS of 31b2c7e;
no confirmed P0-P3 findings. Controller requires no local persistence owners.
StorageManager retains closure eligibility, locks, durable publication and current
matching readback. Durably preserved collection failure does not itself block
closure. Historical rejections stay rejected, fresh retries remain possible, and
successful retries do not rewrite closed products. Closure is not Session
termination, scientific-artifact mutation or service/resource release.

W059 preserves original developer 67 tests PASS and independent IPython 4/4 PASS,
the subsequent audit FAIL (one cached-success history-validation P2), correction
IPython 3/3 PASS and final source audit PASS. Retained successes now pass complete
scoped-history validation, including persisted-resolution conflicts, before owner
reconfirmation. Corrective automated runtime attempts stalled in the sandbox;
the final audit's six attempted tests produced no results and no passes are claimed.
Counts are not additive. Local separate-process JetStream used simulated SFTP;
no multi-host, hardware/physical SFTP or power-loss validation is claimed.

Full cross-process Normal Stop/Kill, Stage A orchestration, release,
enumeration/batch operations, broader recovery and deployment bootstrap remain
outside this slice. Q022, Q006, Q018, Q024, Phase 16 and M015 remain OPEN.
Q019 and W001-W058 remain CLOSED with historical records unchanged.

## Accepted Manual Service CLI Architecture (Decisions 383-388)

**Status:** Bounded launcher/local graceful shutdown CLOSED in W061; remaining
independent role launch paths and service-specific retirement preservation CLOSED
in W063 after independent validation and audit PASS. Remote administrative issuance is CLOSED
in W062 after independent validation and focused re-audit PASS.
One common CLI reuses service launch/readiness/maintenance,
with local Ctrl+C Stop and automatic Cancel when blocked, direct addressed remote
Stop/authorized Kill/Cancel, and exit only after confirmed maintenance and required
final result handling. Existing identities and outcomes are reused; terminal
feedback and exit codes distinguish unconfirmed results from success. Decision
376's shared-process pair remains unchanged. No configuration provisioning,
supervision, forced exit or new lifecycle state is accepted. This is not
completion of Q022. W061 records independent IPython 18/18 initially and 22/22
after two P2 corrections, followed by focused independent re-audit PASS with no
confirmed P0-P3 findings. Counts overlap and are not additive. W061 validated only
the shared pair; W063 now implements the independent roles without extending that
historical validation claim.
Sandbox asynchronous runs stalled before setup; synchronous tests and controlled
probes passed. No live JetStream, actual OS signal delivery, hardware or complete
five-role deployment validation is claimed. W001-W065 and Q019 remain CLOSED;
Q022, Q006, Q018, Q024, Phase 16 and M015 remain OPEN.

### DeviceAdapter Adjustable-Parameter Exposure (W069)

**Status:** CLOSED - Decision 370's adapter-owned constraints, existing node/NATS
inventory exposure, Controller retrieval and validated partial Session overrides
are independently IPython-validated (Part 1: 6/6 PASS; Part 2: 9/9 PASS) and
independently architecturally audited PASS with no confirmed P0-P3 findings.
Installation-only settings and Decision 302 Session isolation remain protected.
The additional probe confirmed selected/unselected adapter behavior only; unrelated
missing local-storage configuration prevented full initialization in that probe.
No live NATS, camera hardware or normal Windows asynchronous scheduling validation
is claimed. See W069 in validated_workflows.md. Q022 remains OPEN for remaining
accepted deployment obligations; all unrelated workflow/question statuses remain
unchanged. No new implementation slice or architecture is introduced.

### Shared-Storage External-Dependent Maintenance Integration (W068)

**Status:** CLOSED - bounded Decisions 389/390 integration is implemented,
independently manually validated and independently audited PASS. Explicit storage-file/CLI
participants replace the isolated-only deployment restriction without discovery.

Each service retains retirement/release authority. Ingestor requires authoritative
instance/attempt-correlated retirement confirmation available before dependent
launcher exit, or Controller's specifically authorized dependency release after
the final archival checkpoint and confirmation of no further Ingestor-dependent
work. Prepared Controller remains operational; dependency release is not retirement.
Unconfirmed, stale or contradictory results retain blockers. Stop/Kill/Cancel and
Decisions 324/326 remain authoritative. Existing NATS and minimal correlation
extensions are reused, not a new registry, supervisor or evidence subsystem.

Shared-pair callbacks now consume instance/attempt-correlated owner readback and
preserved confirmations before launcher exit. Dependent startup registers its
instance before new work; restart cannot reuse prior-instance release. Controller
explicitly releases its dependency only at its preserved final checkpoint, while
remaining operational for the prepared retirement sequence. Missing or conflicting
confirmation retains blockers/processes and explicit retries reuse completed
cleanup. Decision 390 additionally requires ordinary-startup verification of an
intact archive as an exact valid historical prefix of recovered authoritative
evidence and applicable intake audit, followed by archival continuation and
complete current confirmation before eligible release restoration. This
integration is implemented and validated; it is not automatic
interrupted-write repair under Decisions 339/342/347.
Focused simulated-communication tests are provided; controlled execution is not
normal Windows I/O scheduling, live NATS or physical deployment verification.
The initial audit FAIL identified a P2 maintenance-write bypass after rejected
continuation. StorageManager's ordinary-write guard now retains rejection across
all maintenance callers while preserving valid initial creation and authorized
repair. Final independent audit PASS found no remaining confirmed P0-P3 findings.
Implementation: 83 focused tests PASS. Final audit: 41 targeted tests and two
independent probe workflows PASS. Independent manual IPython: 3/3 scenarios PASS
across two executions, after correcting a harness error. Earlier Decision 390 disk
validation passed 5/5; these overlapping runs are not additive. See W068 in
validated_workflows.md for the full history and limitations, including no live
NATS, hardware, real OS signals, power-loss or normal Windows scheduling campaign.
W068 is CLOSED; Q022 remains OPEN for remaining accepted deployment obligations.
W001-W067 and Q019 remain CLOSED; unrelated open statuses are unchanged.

### Manual Installation And Provisioning Integration (W067)

**Status:** CLOSED - manual runbook, five typed JSON examples and guidance validated
against existing strict loaders and CLI interfaces. Independent user-run validation:
4/4 tests PASS, zero failures/errors. Independent architectural audit: PASS, no
confirmed P0-P3 findings. Existing W061-W066 capabilities are integrated without
an installer, new configuration authority or production API change.

The procedure separates computer/account preparation, service/hardware/Session
configuration, manual SSH trust/permissions, exact dummy retrieval, existing
role launch commands, fresh registered-node checks, recommended device acquisition
and node additions/replacements. At W067 closure, file-driven deployment remained
limited by the shared-pair no-external-dependents restriction; actual dependents
required callbacks unavailable through files. W067 documented rather than bypassed
that gap. W068 above separately validates and closes the bounded integration;
W067's historical validation does not validate those new paths.
Real network, SSH/SFTP, hardware, OS signals and complete deployment are unverified.
That callback-composition obligation is closed by W068 above; the runbook alone
does not establish physical distributed-deployment readiness.
W001-W067 and Q019 remain CLOSED; Q022 remains OPEN and unrelated open statuses
are unchanged. See W067 in validated_workflows.md for evidence and limitations.

### Completed Installation Node Communication Verification (W066)

**Status:** CLOSED - independently validated and finally re-audited PASS, with no
confirmed remaining P0-P3 findings. `verify-node --deployment-config PATH --node-id
NODE_ID` uses the Controller service file, explicit node registration and existing
NATS `check_readiness` contract without constructing a Controller owner. Only a
fresh correctly correlated response and successful cleanup establish communication
success; hardware/scientific readiness remains separate. No hardware initialization,
Session modification, reservation or maintenance is performed.

Independent IPython validation passed 17/17 installation communication tests and
11/11 connection regressions (separate runs). Preserve the audit sequence: initial
FAIL for partial client ownership (P2-A), first re-audit FAIL with P2-A resolved
but interrupted cleanup (P2-B), then final focused re-audit PASS with both resolved.
The boundary retains the pre-handshake client and joins one shielded cleanup task,
including repeated cancellation, without trusting `is_closed` alone. An additional
controlled concurrency probe passed with actual asyncio tasks/shield and actual
nats-py/TcpTransport cleanup using simulated I/O, not normal Windows scheduling.
See W066 for the complete evidence and limitations.

No live NATS, real sockets, hardware, OS-signal or complete installation
certification is claimed. Q022 remains OPEN for applicable manual installation/
provisioning integration and remaining accepted deployment requirements. Q019 and
W001-W065 remain CLOSED; Q006/Q018, Q024, Phase 16 and M015 remain OPEN.

### Completed Installation Retrieval Verification (W065)

**Status:** CLOSED - independently validated and audited PASS. The explicit
`verify-retrieval` CLI reuses deployment-local StorageManager endpoints and existing
SSH/SFTP transport to compare a remote dummy file with independently established
expected bytes. PASS requires exact contents and successful temporary cleanup;
storage is bounded and failures omit raw authentication exception details. No
scientific artifacts, Session records, Evidence Archives or lifecycle state change.

Independent IPython validation: 11/11 tests PASS, zero failures/errors. Independent
read-only audit: PASS, no confirmed P0-P3 findings or architectural blockers;
12 focused tests and two probes passed (cumulative size overflow despite a matching
prefix, and cleanup failure preventing PASS). Counts overlap and are not additive.
SSH/SFTP was simulated; no live infrastructure, hardware or actual OS-signal
verification was performed. Two existing collection hard-link regressions were
blocked by Windows sandbox permissions (WinError 5), not claimed as passing.

Q022 remains OPEN for Controller-to-AcquisitionNode installation communication
verification, applicable manual installation/provisioning integration and remaining
accepted deployment requirements. Q019 and W001-W064 remain CLOSED; Q006/Q018,
Q024, Phase 16 and M015 remain OPEN. This closes no other workflow or question.

### Completed Deployment-Local Configuration and Startup Integration (W064)

**Status:** CLOSED - independently validated and audited PASS under Decisions
367-376 and 383-388. Explicit `--deployment-config` service files feed the existing
Controller, AcquisitionNode, SynchronizationManager and shared Ingestor/StorageManager
launchers; roles are not inferred from configuration. General-service settings,
node hardware installation and Session-specific settings remain separate.
Validation precedes operational startup without hardware access or remote
retrieval checks, preserving W061-W063 maintenance and lifecycle safeguards.

File-based shared-storage launching still requires explicit
`no_operational_dependents=true`; deployments with actual external dependents
require their existing maintenance callbacks and are not supported by that
declaration. No configuration authority, provisioning system or launcher is added.

Independent IPython validation: 9/9 configuration tests and configured shared
storage startup integration PASS. Independent read-only audit: PASS, no confirmed
P0-P3 findings or unresolved architectural blockers. Audit checks passed 12
synchronous tests, controlled startup/graceful retirement and two configuration
probes. These overlapping sets are not additive; controlled execution is not
normal async scheduling validation. W064 records the sandbox initialization
limitation without treating a blocked run as a pass.

No live NATS/JetStream, actual SSH/SFTP retrieval, real hardware, OS-signal or
full multi-computer deployment validation is established. Q022 remains OPEN for
applicable installation provisioning/verification, Controller-to-node communication
verification, SSH/SFTP dummy retrieval/content comparison and remaining deployment
integration. Q019 and W001-W063 remain CLOSED; Q006/Q018, Q024, Phase 16 and M015
remain OPEN. No next workflow is selected here.

### Completed Independent Service Launch Paths (W063)

**Status:** CLOSED - Controller, AcquisitionNode and SynchronizationManager
launch independently through the common CLI, reusing readiness/reconciliation,
runtime NATS commands and W061/W062 local/remote maintenance. Ingestor and
StorageManager retain separate ownership within their required shared process.
AcquisitionNode loads installation JSON and constructs the existing OpenCV
adapter without premature hardware access or configuration provisioning.

Authoritative Ingestor acceptance and paired StorageManager preservation confirm
the retiring service's exact stable evidence boundary. Local admission/retirement
guards prevent newer obligations from using older proof, without freezing unrelated
framework intake. Existing Stop/Kill/Cancel semantics and final-result handling
remain unchanged; publication, preservation, resource release and OS exit remain
distinct guarantees.

Independent user-run IPython validation: 60/60 PASS, zero failures/errors/skips.
Independent architectural audit: PASS, no confirmed P0-P3 findings. Audit checks
included 10 synchronous tests, seven controlled coroutine workflows and two
targeted probes, recorded separately rather than summed. One normal async
concurrency attempt stalled before setup in Windows asyncio socket-pair
initialization; controlled execution is not normal async scheduling validation.
See W063 in validated_workflows.md for scope and evidence details.

No live JetStream, actual OS signal delivery, hardware operation or complete
multi-process deployment validation is established. General configuration/
provisioning, installation verification and remaining deployment/integration work
keep Q022 OPEN. Q019 and W001-W062 remain CLOSED; Q006/Q018, Q024, Phase 16 and
M015 remain OPEN. No next slice is selected by this closure.

### Completed Remote Service Maintenance CLI (W062)

**Status:** CLOSED - addressed Stop/explicitly authorized Kill/Cancel reuse existing
NATS maintenance without Controller. Explicit server, target, administrator and
request window are required. Kill/Cancel continue the existing blocked attempt;
later Stop uses a new identity. Scoped fresh replies, bounded waiting and current
correlation preserve owner authority. Cancel retains `failed` / `Administrator
cancelled` and nonzero status; missing/rejected/unconfirmed results are not success.
Separate Ingestor/StorageManager ownership in one process and W061 final-result
handling remain mandatory; maintenance confirmation is not OS process-exit proof.

Independent IPython validation passed 41/41 initially and 42/42 after correction
(overlapping sets, not additive). Initial independent audit FAIL identified one
P3: interrupted authorized Kill falsely said no force was requested. Corrected
feedback acknowledges possible execution, no revocation by interruption and
unconfirmed activity/retirement, with permanent coverage. Focused independent
re-audit PASS found no confirmed P0-P3 findings. Executable sandbox checks passed;
Windows asyncio socket-pair initialization blocked normal asynchronous runs.
No live JetStream, OS-signal, hardware or full deployment validation is claimed.
W062 did not implement the other role launch paths; W063 closes their bounded
implementation and validation as described above.
General configuration, installation and broader Q022 integration remain open;
W062 does not complete Q022 or Q024.

## Completed Sustained Acquisition Execution (G3)

**Status:** CLOSED - bounded software scope after implementation verification
(26 checks), independent ICC IPython validation (5/5 PASS), and separate independent
Codex audit PASS with no confirmed P0-P3 findings. The audit passed 15 automated
checks and two adversarial finalization workflows; counts are not additive.

The existing AcquisitionNode service composition owns autonomous repeated bounded
acquisition for active scientific Experiments without per-iteration Controller
commands or a Controller-connectivity requirement. Existing scientific storage,
timestamps, identities, health evidence, Experiment idle/reactivation and
Stop/Kill/Cancel semantics are preserved. Authorized cleanup joins execution;
acquisition failures retain partial science and evidence while attempting cleanup.

Three distributed closeout checks remain unverified due to Windows hard-link
permissions, independently reproduced by a minimal os.link() control. Controlled
software validation does not establish live PC-Jetson/NATS integration, physical
camera operation/performance, OS-signal, power-loss or normal Windows asynchronous
scheduling behavior. See [G3 closure](validated_workflows.md#g3---sustained-acquisition-execution).
G2/G4/G5 are not completed by this closure. Q022, Q024, M015 and Phase 16 remain
OPEN; accepted architecture and historical W-records are unchanged.

## Completed Q022 Distributed Session Closeout (W060)

**Status:** CLOSED - implemented, independently validated and audited under
Decisions 313 and 382. The Normal Stop marker is last-call after producer confirmations, not
proof of complete receipt by itself. Ingestor verifies the full durable publication
interval and finalizes acquisition intake; later deliveries cannot change finalized
evidence/audit/record. Finalized intake plus StorageManager-verified complete Stage A
and applicable handoff establishes preservation eligibility. Controller alone owns
lifecycle completion and must also satisfy cleanup/safety obligations. Decision
313 keeps each service's release independent; Stage A is not hardware safety or
release authorization. Existing durable products/journals and NATS readback/recovery
must support restart without rewriting finalized evidence or unnecessarily repeating
confirmed preservation. Kill and later Stage B/permanent closure remain distinct.
W060 records independent IPython sets of 9/9 finalized-intake, 7/7 distributed
closeout, 4/4 real JetStream infrastructure, 3/3 separate-process closeout, 8/8
original-correction and 6/6 subscription-release tests. Counts are not additive.
Independent audits confirmed resolution of the three original P2 findings and
the subsequent non-idempotent unsubscribe retry P2. Framework intake remains
independent, pre-marker health is preserved, and remote release requires current
Controller evidence coverage plus fresh authoritative preservation readback.
Confirmed unsubscribe progress survives failed readback and explicit retry.

Final nats-py 2.16.0 cancellation investigation found no reproducible defect;
controlled probes passed, but Windows asyncio socket-pair startup blocked live
task-level cancellation verification. No such runtime pass, multi-host, physical
hardware/SFTP or power-loss guarantee is claimed. See W060 for the complete
validation/correction sequence. Q019 and W001-W060 stay CLOSED; Q022, Q006, Q018,
Q024, Phase 16 and M015 stay OPEN. Broader deployment, maintenance/recovery and
remote enumeration/batch integration are not closed by this slice.

## Completed Session-binding release slice validation

**Status:** Complete - narrow software implementation, manual IPython validation,
and independent audit PASS under Decisions 313 and 322 (W035).

- Manual IPython validation passed, including stale Session A release after
  Session B starts, preservation of B's state/evidence/subscriptions, continued
  acquisition, and normal B cleanup.
- Independent audit: PASS, no blocking defects or architectural ambiguities.
- Independent focused regression: 152 passed, zero failures or skips.
- Full suite: 493 run, 486 passed, 7 optional rendering skips, zero failures.
- Independent memory-only negative controls reproduced the concurrency defect
  when binding-identity checks were disabled.

These are previously reported validation/audit results, not new tests performed
during documentation synchronization. This is controlled software/broker-double
validation, not real hardware, external NATS deployment, or live cross-process
validation. Phase 16 remains incomplete, M015 remains open, and Q019 is CLOSED in W050; Q024 remains open.

### Earlier implementation results (historical)

Follow-up implementation test results: 27 focused Controller decision/release
tests and 137 relevant regressions passed; full discovery ran 465 tests with
458 passed, zero failures, and seven optional rendering skips. These are local
automated results, not independent manual validation or audit evidence.

Planned future milestones include:

- First Jetson CSI camera
- First lick sensor integration
- First synchronized multi-device acquisition
- First Parquet backend
- First microscope integration
- First NWB export
- First distributed acquisition across multiple nodes

These milestones will be added as they are successfully demonstrated.
