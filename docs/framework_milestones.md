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
later global processing failure; Q019 remains open. M011 stays open pending real
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
Complete closeout and Decisions 362-365 remain unimplemented.
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
Q019 remains OPEN: durable Ingestor recovery does not prove Session-wide consumption
to Controller before archive closure. M013 and M012 stay complete; M011 stays open.
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

Current development starts NATS/JetStream and each participant manually in
independent processes. Intended deployment uses long-lived independent services.
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
criteria; Q019 and Q024 remain open. No hardware or external live NATS validation
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
M015 retains its separate launch/reuse validation criteria, and Q019/Q024 remain open.

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
Q024, Q019, Q022, Phase 16, and M015 remain OPEN. Journal retention/deletion,
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
Decisions 349-350 and 353-355 remain unimplemented.
Existing shared-archive confirmation and maintenance lookup dependencies require cross-month
operational clarification before safe deletion can be confirmed. Q019 still owns
unresolved Session-wide final evidence consumption/closure; unavailable auditing
for terminal deletion is an architectural conflict, not an accepted exception.
Remaining memory/idempotency limits and application-wide discovery/restoration
remain open. No new implementation milestone or recovery subsystem is introduced.

Q024-B Decisions 339-348 remain complete, independently validated/audited in W039;
all earlier workflow records are preserved. Decision 336 remains partially
implemented. Q024, Q019, Q022, Phase 16, and M015 remain OPEN.

## Accepted Q019 acquisition closeout and later collection (receiving and publication prerequisites validated)

Decisions 356-365 accept producer-confirmed acquisition evidence completion plus
independent Ingestor consumption proof, Stage A acquisition evidence/audit/summary
and final Session Record preservation, durable StorageManager handoff preservation,
and later operator-selected stopped-Session collection without original bindings.
StorageManager directly preserves its own Stage B collection evidence, distinguishes
that origin without fabricated Ingestor audit, and confirms permanent archive
closure. Acquisition outcomes and final Session Records are not rewritten.
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

Complete Controller Normal Stop/Kill orchestration and
Decisions 362-365 remain unimplemented. No overall milestone completion is claimed.
Q019 remains OPEN for remaining implementation and independent verification.
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
336 remains partial, Decisions 349-350 and 353-355 remain unimplemented, and Q024,
Q022, Phase 16, and M015 remain OPEN.

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
validation. Phase 16 remains incomplete, M015 remains open, and Q019/Q024 remain open.

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
