# Open Architectural Questions

This document tracks unresolved architectural questions.

A question remains open until an explicit architectural decision has been accepted and recorded in `architecture_decisions.md`.

Resolved questions should be removed from this file and recorded in `architecture_decisions.md`.

---

# Priority Levels

**Critical**

* Blocks implementation.
* Should be resolved before major development begins.

**Important**

* Affects interfaces, validation, or future extensibility.
* Can be resolved after core architecture is stable.

**Future**

* Important for future versions but not required for Phase 1.

---

# Critical Questions

## Q002: What is the Final Session Record Structure?

Current Direction

The architecture has accepted:

raw/
    session_<session_id>/

nwb/
    session_<session_id>/

Raw acquisition records and NWB exports have separate lifecycles.

Decision 073 defines the minimum evidence categories that belong in the persistent Session Record.

Decisions 178-218 separate AcquisitionNode-local scientific persistence and local
completion from global Session Record completion. StorageManager already writes
the Phase 13 persistence products and implements the accepted artifact retrieval,
light verification, and collection-evidence slices. These capabilities do not
transfer ownership of original local records or settle the broader global
integration schema and diagnostic compilation.

Decisions 219-231 separate the Session Record from the Evidence Archive, assign persistent runtime-evidence compilation to Ingestor, assign persistent writing to StorageManager, and accept the v1 conceptual layout:

```text
session_<session_id>/
    session_record_initial.json
    session_record_final.json
    evidence/
        runtime_evidence.jsonl
        ingest_audit.jsonl
        compilation_summary.json
```

The remaining work is defining schema evolution,
mandatory and optional record contents, manifests, file-tracking records,
validation outputs, and representation details for each evidence category.

Additional questions:

* How should the accepted v1 layout evolve as archive requirements mature?
* What fields are mandatory within each accepted Session Record and Evidence Archive file?
* What fields are optional?
* What manifest format identifies the included evidence?
* How are file-tracking records represented?
* What validation outputs are required?
* How should accepted configuration, lifecycle evidence, readiness evidence, acquisition evidence, ingest audit records, final status, failures, and cleanup evidence be represented within the accepted Session Record and Evidence Archive concepts?
* What retention and deletion policy applies to Evidence Archive contents?

---


# Important Questions

## Q006: What is the detailed drift and timing-uncertainty representation?

**Status:** OPEN - minimum distributed synchronization contracts are resolved by
Decisions 379-381; advanced timing/estimation and offline refinement remain open.

### Why this matters

Decisions 154-176 establish synchronization ownership and minimum plain-data
schemas while requiring drift, correction, mapping-update, timestamp-status,
and timing-quality evidence while preserving runtime timestamps.
SynchronizationManager owns runtime drift estimation and remapping decisions.
Decisions 379-381 now require measured cross-clock exchanges accounting for
network delay, variability and uncertainty, authorize explicit conservatively
bounded initial clock-rate assumptions, and specify local affine application:
`session_time = session_anchor + scale * (node_local_time - local_anchor)`.
Mapping history and node-local activation boundaries remain reconstructable
without per-observation mapping IDs. Readiness and periodic quality assessment
requirements are accepted, with configurable cadence/thresholds and existing
TimingQualityPolicy/Controller consequences for degradation.

### Questions

* Can drift vary during a session?
* Which advanced drift-estimation and measurement algorithms are needed beyond
  the minimum demonstrably valid cross-clock measurement method required now?
* How should detailed timestamp uncertainty be represented beyond the accepted
  requirement to account for uncertainty and preserve degraded timestamp status?
* What additional precision requirements are needed beyond existing timing schemas?
* What hardware synchronization models and offline refinement methods are needed?
* How are reconstructed drift estimates linked to the runtime mappings they audit?
* How is runtime drift-estimation evidence represented without exposing the SynchronizationManager algorithm as architecture?

### Blocks

* Advanced synchronization features, not the accepted minimum Q022 Slice 2 method
* Reconstruction quality reporting

---

## Q007: What Must Be Tested Before Accepting a New Device?

### Why this matters

The OpenCV camera slice demonstrates basic lifecycle, readiness, metadata-only
record collection, Session Time attachment, persistence, and clean shutdown.
General acceptance requirements for new devices are not yet defined.

### Questions

* What failure behavior must be tested?
* What timing quality and precision must be demonstrated?
* What record and capability schemas must a device declare?
* What automated and manual hardware checks make a device Phase-1 compliant?

### Blocks

* Device validation architecture
* Testing requirements

---

## Q008: What is the Configuration Model?

### Why this matters

The framework now has explicit `SessionConfig` buckets, separate
`DeviceDeclaration` participation intent, and concrete adapter configuration
objects such as `OpenCVCameraConfig`. The final external representation and
propagation policy remain unresolved.

Decision 234 settles local storage root precedence: each AcquisitionNode has
an explicitly resolved persistent default and a Session may override it without
mutating that default or affecting later Sessions in the historical local path.
Decision 298 qualifies distributed initialization: the node uses deployment-local
roots/configuration and Controller cannot select/override remote roots through
SessionConfig.local_storage_roots. Decisions 368-369 now settle initial file-based
deployment-local provisioning; broader configuration representation/propagation
remains open, and root authority is unchanged.

Deployment-local retrieval configuration and installation are tracked separately
in Q022: Decisions 367-374 are accepted and synchronized, with implementation
and independent verification pending.

Decisions 281-301 settle Slice 28's ownership and ordering: AcquisitionNode owns
pre-Session inventory, Controller resolves selections/readiness/reservations,
and SessionConfig is the final accepted configuration. Reuse existing device
and product declarations without SessionLaunchIntent or product requiredness.
Broader configuration representation and propagation remain open outside Q022-A;
these settled selection and launch semantics are not Q008 schema questions.

### Questions

* What external configuration representation is needed beyond Q022-A's accepted
  file-based installation scope? Its exact initial file format is an implementation choice.
* What is the policy for declaring and applying defaults?
* How are accepted configuration values propagated to runtime owners?
* What vocabulary and structure should be used for `DeviceDeclaration.declared_capabilities`?

### Blocks

* API design
* Session manifest structure
* Device schema structure


---

# Future Questions

## Q001: What is the future hardware Synchronization Anchor schema?

### Why this matters

Decisions 150-166 establish Session Time ownership, synchronization updates,
runtime timing evidence, and prospective local-to-Session mappings. A future
hardware Synchronization Anchor format has not yet been defined.

### Questions

* What qualifies as a synchronization anchor?
* What information must be stored if hardware synchronization is added later?
* How are synchronization anchors used during reconstruction?
* How does a hardware anchor relate to the accepted synchronization-update and timing-mapping evidence?

### Blocks

* Future hardware timing support
* Hardware-anchor reconstruction validation rules

---

## Q009: Multi-Node Acquisition

### Why this matters

Future Sessions may involve multiple acquisition systems participating in the same Session.

Examples:

* Jetson + microscope PC
* Jetson + DAQ PC
* Jetson + behavioral PC

### Questions

* How are active SynchronizationManager-owned mappings distributed to each AcquisitionNode?
* What exact mapping/update schema is shared across nodes?
* How are timing-quality observations from multiple nodes correlated for reconstruction?
* What deployment and failure behavior is required beyond the accepted ownership model?

### Current Direction

Multi-node acquisition is architecturally supported. SynchronizationManager
owns one Session Time and all active SynchronizationMappings; each
AcquisitionNode applies its received active mapping without resetting its local
monotonic clock. Decisions 379-381 resolve measured cross-clock validity, local
affine application/provenance, readiness and degraded timing for Q022 Slice 2;
process-crossing communication uses existing NATS contracts. Advanced multi-node
timing, hardware synchronization and reconstruction questions remain open.

---

## Q010: NWB Export Mapping

### Why this matters

The framework intends to support NWB export.

### Questions

* What metadata must always be captured?
* Which internal concepts map directly to NWB?
* Which concepts require translation?
* Which devices require special handling during export?

### Current Direction

Design internal records so that NWB export is straightforward, but do not let NWB drive the Phase 1 architecture.

---

## Q011: What is the recovery model for unpublished durable messages?

### Why this matters

Decision 143 keeps durable-message ownership with the producer until successful JetStream publication. Decisions 124 and 142 require communication-failure evidence but intentionally defer reconnect, retry, replay, buffering, and recovery behavior.

### Questions

* What future recovery mechanism, if any, is accepted after an explicit `DurablePublicationError`?
* What automatic reconnection, retry, or replay policy, if any, applies to publication recovery beyond Decisions 320-321's accepted communication reestablishment when a service returns?
* May newer durable messages publish after an earlier publication failure?
* How are successful recovery and permanently unpublished messages recorded?
* If future local preservation is accepted, what ownership and storage limits apply?

### Current direction

Do not infer recovery behavior from JetStream durability. Publication recovery remains a separate future architecture decision.

Decisions 320-321 permit independent service startup and communication
reestablishment when a service returns, without framework-wide restart. They do
not define automatic retry/replay, unpublished-message recovery, or automatic
resumption of interrupted Sessions or transfers; those questions remain open.

Slice 27's accepted Ingestor journal recovery (Decisions 276-280) concerns evidence
after transport publication and normal JetStream redelivery, not unpublished
producer messages. It does not resolve this publication-recovery question.

---

## Q013: What further framework behavior follows ControllerActionDecision execution?

### Why this matters

Decisions 103-114 establish the runtime health evidence chain and normalized local Controller decision execution. `record_only`, `record_warning`, `record_recoverable_failure`, and `operator_required` succeed without lifecycle mutation; `experiment_fail` and `session_fail` use their accepted lifecycle owners. Remaining architecture concerns any future behavior beyond these local semantics.

### Questions

* Should warning, recoverable-failure, or operator-required decisions later trigger external notification or acknowledgement behavior?
* What explicit future decision would authorize escalation beyond their current no-mutation semantics?
* How does Controller execute repeated or conflicting decisions?

### Blocks

* Fatal/warning health behavior
* Operator notification

## Q014: What is the receiver-side Ingestor validation model?

### Why this matters

Sender-side robustness now preserves evidence before handoff, while Decisions 219-231 assign Ingestor runtime evidence intake, intake validation, ingest audit, temporary runtime retention, and persistent runtime-evidence compilation. The detailed receiver-side validation model remains separate. The Ingestor may eventually need to detect malformed envelopes or messages, missing timing, duplicated evidence presentation, or incomplete sessions.

Decisions 276-280 settle accepted RuntimeEvidenceMessage crash durability and
evidence_id duplicate/conflict handling in completed Slice 27 (M014, W034),
independently software-validated with corrected targeted re-audit PASS.
General envelope/domain validation remains open; it must not reopen that settled
runtime-message acceptance identity or imply journaled nonpersistent evidence
becomes permanently persistent.

### Questions

* What envelope validation does Ingestor perform?
* Does Ingestor reject malformed records or preserve them with audit evidence?
* What fields are mandatory for accepted envelopes?
* How does Ingestor represent rejected envelopes?
* Does Ingestor detect missing expected sources, or is that only AcquisitionNode health?
* How are receiver-side failures represented in the Session Record?
* What validation rules apply before persistent runtime evidence is included in the compiled Evidence Archive handoff?
* How are finalized local manifests, completion summaries, and local storage evidence represented across the Session Record and Evidence Archive?

### Blocks

* Ingestor hardening
* Session Record failure schema
* Reconstruction validation

---

## Q015: What orchestration remains beyond accepted Session launch?

### Why this matters

Controller v1 implements sequential orchestration for one bounded Session,
canonical Experiment evidence, and explicit runtime health mappings on
AcquisitionNode. Phase 5 completed that narrow lifecycle/health-scope architecture.
Slice 28 now accepts pre-Session distributed launch ownership; Validation, abort
commands, and broader multi-Session scheduling/supervision remain deferred.

Decisions 095–102 establish canonical Experiment lifecycle ownership, distinguish Readiness and Validation from Experiment, define expected participants as plain-data declarations, define an immutable live-source-keyed runtime health mapping, and scope AcquisitionNode Experiment health evaluation exclusively to that active mapping. Acquisition-health consequences remain tracked separately in Q013.

The architectural scientific-output declaration and selection portion of Q015
is resolved by Decisions 208-210 and 235-237. Devices declare available products
and their storage requirements; Experiment configuration selects products by
existing source device, AcquisitionNode, and product identities without
overriding storage format. Controller coordinates preparation through existing
readiness, AcquisitionNode requests streams, and LocalStorageManager creates
them before scientific acquisition. Slice 20.3 implements this path and
terminal identity enforcement; Slice 20 is complete as recorded in W029.
External configuration
representation and propagation remain under Q008.

Decision 239 settles pre-start preparation failure ownership: Controller must
confirm required preparation before canonical start, records persistent
`experiment_start_rejected` runtime evidence on rejection, and does not record
`experiment_fail` for an execution that never started. Optional failures do not
block required success, and missing required results remain unresolved. These
are accepted Slice 21 requirements now implemented, manually validated, and
independently audited; Slice 21 is complete as recorded in W030 and M009,
not an open ownership question. They do not change
required scientific-output selection or introduce
a Session rejection history. Representation/propagation work remains under
Q008; the remaining orchestration questions below remain open.

Decisions 281-301 now settle Controller-owned pre-Session launch/runtime
assembly, node-owned inventory and atomic reservation, service-only node
readiness, selected-device criticality, resolved SessionConfig, and failed-launch
rollback. Controller may exist before Session and uses existing communication
boundaries with participants already available to it. The existing Slice 28 launch
path and sequential reuse have automated broker-double tests; M015 remains open
pending independent validation and audit of the correction and is not validated
by earlier workflows.
Those ownership/ordering questions are no longer open. Unknown is absence of a
valid current report, not a new readiness enum; no product-level criticality or
device-level reservation is introduced.

Decision 302 resolves the sequential device-reuse lifecycle ambiguity: successful
shutdown and required cleanup return retained adapters to DECLARED, while failed
or unconfirmed cleanup prohibits reuse. Safely reusable declared adapters must
participate in existing pre-Session readiness, and each Session supplies its own
configuration. This is accepted architecture, not another open lifecycle question;
implementation has automated regression coverage, with independent validation
and audit pending under M015. It does not resolve
concurrent sharing or multi-Session scheduling. Decision 313 subsequently settles
normal binding release after each service's confirmed cleanup/evidence obligations;
the narrow Phase 16 Session-binding release slice, including the Controller-specific
decision archival/release contract in Decision 322, is now complete, manually
software-validated, and independently audited PASS (W035).
Evidence-bearing Ingestor/SynchronizationManager release has narrow paths for
exact persistent-message/runtime-audit archival coverage and durable synchronization
handoff respectively. This does not resolve Session-wide consumption or application
recovery. W035 also validates asynchronous overlapping release and preservation
of a subsequent Session binding; it does not fulfill M015's separate remaining
validation criteria or claim real hardware/external NATS deployment validation.

Decisions 295-301 resolve the distributed initialization handoff: pre-Session
participant commands use existing NATS conventions without fabricated Session
IDs; nodes own binding/local initialization; Session authorizes node-process
LocalStorageManager creation; all mandatory participants confirm preparation.
Controller coordinates participant-local cleanup on failed/unconfirmed launch,
but unconfirmed node cleanup prevents reservation release. These accepted
responsibilities are implemented, not open ownership questions.

Decision 238 resolves terminal Experiment identity reuse: each identity is one
execution, including without scientific outputs. Repeating a configuration
requires a new Experiment identity and independent lifecycle, streams,
manifests, and acquisition/timing evidence. Device restart within an active
Experiment remains distinct. The Slice 20.3 implementation dependency concerning
same-identity restart is therefore resolved; abort-command implementation and
the other orchestration questions below remain deferred.

### Questions

* How is Validation requested and recorded without creating an Experiment?
* What semantics distinguish a future abort command from framework failure and intentional stop?
* What future client/GUI/CLI interfaces request Controller-owned launch?
* What central scheduling, device-level sharing, or shared multi-Session Ingestor/StorageManager scheduling, if any, is accepted beyond Slice 28?
* What daemon/service supervision and coordination between multiple Controllers, if any, is needed without changing deployment-independent ownership?
* What future startup automation replaces temporary manual-shell development startup without making Controller a process supervisor?
* What future durable pre-Session launch auditing is accepted beyond operational results, without forcing failed attempts through Ingestor?

### Blocks

* Validation orchestration
* Abort semantics
* Future shared multi-Session scheduling and service supervision beyond accepted launch/initialization

---

## Q016: How is distributed Health Interpretation Evidence consumption recovered and deduplicated?

### Why this matters

Decisions 115-149 settle the communication boundary, and the implemented Controller consumer now independently receives Session-scoped `HealthInterpretationEvidence` through JetStream. Operational recovery and duplicate-presentation behavior remain unresolved.

Decisions 276-280 settle only Ingestor acceptance/reconstruction deduplication.
They do not decide Controller restart or repeated-action execution, so Q016 remains open.

### Questions

* How are consumer acknowledgement, restart, and duplicate presentation handled without repeating Controller actions?
* How are missing or delayed evidence-consumption outcomes surfaced operationally?

### Blocks

* Distributed health consequence handling
* Multi-node Controller integration

---

## Q018: Synchronization observation, drift estimation, and mapping refinement model

**Status:** OPEN - Decisions 379-381 resolve the minimum distributed scientific
synchronization gate for Q022 Slice 2, not advanced synchronization design.

Phase 11's historical mapping-ownership scope is now supplemented by measured
cross-clock exchanges, the accepted local affine formula, and synchronization
readiness at Session acquisition and before each Experiment. Configurable
periodic quality assessment is distinct from complete resynchronization.
SynchronizationManager alone determines validity, refinement and replacement.
Initial mappings may use an explicit, conservatively bounded clock-rate assumption
without prior drift estimation. Temporary degradation retains timing/provenance
and degraded status; existing policy and Controller authority govern consequences.

The following remain open beyond the minimum demonstrably valid measurement
method required for the current implementation:

- advanced cross-clock measurement and drift-estimation algorithms
- richer SynchronizationObservation and timing-uncertainty representations
- advanced mapping-refinement and update strategies
- hardware synchronization
- offline refinement and reconstruction timing estimators

Cadence and quality thresholds are configurable, not newly chosen constants;
their accepted configurability is no longer an unresolved architectural question.

The future synchronization design must preserve the accepted Phase 11 principles:

- SynchronizationManager remains the owner of Session Time.
- SynchronizationManager owns synchronization evidence creation and mapping lifecycle.
- AcquisitionNode reports local timing information and applies accepted mappings.
- Runtime Timing remains immutable.
- Any reconstructed or refined timing remains distinguishable from Runtime Timing.

This question does not block the accepted minimum Q022 Slice 2 synchronization
implementation. It does not authorize deferring valid cross-clock measurement,
assuming shared clocks, or substituting transport time for scientific time.


Q019: How is Session-wide evidence consumption coordinated before processing finalization?
**Status:** CLOSED - W041-W049 implementation and independent validation/audits,
overall independent manual integration validation 2/2 PASS, and final independent
integration audit PASS with no confirmed P0-P3 production defects (W050).
The successful sequential Normal Stop probe is retained as a permanent regression;
new developer integration tests 3/3 PASS. The detailed contracts and historical
slice evidence below are preserved; Q022, Q024, Phase 16, and M015 remain OPEN.
High-level contracts accepted in Decisions 356-360 and low-level
contracts resolved/accepted in Decisions 361-365. Decision 361's receiving foundation
and routing prerequisite are complete with automated testing, independent manual
IPython validation, and final independent re-audit PASS after correction (W041).
Eligible-Session selection and overall software integration validation are complete
in W049/W050. Decision 362's bounded Stage A slice is complete
with automated testing, independent manual validation, and independent audit PASS
(W043); bounded Stage B collection/Decision 363 persistence is complete with
independent manual validation and final targeted independent re-audit PASS after
correction (W045); W046 explicit closure is complete with independent manual
validation and targeted re-audit PASS after correction. Decision 365's bounded
Normal Stop integration is complete with independent validation and targeted
re-audit PASS after correction (W047); W048 Kill is complete with independent validation and final re-audit PASS after corrections.
Decision 364's bounded
durable handoff is complete with automated testing, independent manual validation,
and independent audit PASS (W044).
Q019 is complete within its supported software integration scope (W050).

Decision 366 resolves the producer-confirmation scope ambiguity architecturally:
every AcquisitionNode actually participating in Session acquisition completes
applicable evidence generation and durable publication before its existing
successful completion response, regardless of selected-device optionality. Unused
optional devices add no obligation. Controller and SynchronizationManager finish
their applicable closing-Session evidence publication before the single marker;
Ingestor-owned locally journaled evidence needs no JetStream round trip and remains
part of compilation/persistence. The supported publication prerequisite is complete
with developer automated coverage, independent manual validation, and targeted
independent re-audit PASS after correction (W042);
Bounded Kill integration is complete in W048; eligible-Session selection is complete in W049 without a new registry. Bounded Normal Stop is complete in W047.

Accepted architecture

- Required acquisition-stage producers finish evidence production and confirm
  durable publication. Controller then publishes one Session-scoped acquisition-
  evidence-completion marker using existing JetStream evidence. Ingestor must
  independently prove earlier required durable acceptance using verified contiguous
  JetStream acknowledgment progress across the full relevant publication interval.
  Session-specific receiving position must survive restarts; gaps, missing history,
  unknown position, or missing confirmations prevent completeness confirmation.
  Receipt of the marker or isolated ACKs are insufficient (Decision 361).
- Stage A preserves Ingestor-compiled persistent acquisition evidence, intake
  audit, compilation summary, and the final Session Record. Confirmed preservation
  satisfies acquisition-side completion and applicable binding-release obligations;
  successful Session completion need not wait for global scientific collection.
- Stage B follows operator-requested collection. StorageManager directly appends
  its own persistent RuntimeEvidenceMessages to the same Session runtime evidence
  file, distinguishes direct persistence from Ingestor acceptance in the summary,
  and confirms durability. Permanent closure requires a separate explicit operator
  request, all applicable collection outcomes durably recorded, no unresolved
  evidence writes, and StorageManager verification of archive consistency and
  durable preservation. It is not automatic after collection and does not require
  every scientific artifact to have been retrieved or verified. A permanently closed
  archive is immutable, including after restart. No fabricated Ingestor
  audit, acquisition-evidence rewrite, final Session Record change, or retroactive
  acquisition outcome change is permitted. The existing compilation summary records
  Stage A completion versus permanent Stage B closure; status alone proves neither
  consistent nor durable preservation (Decision 362).
- StorageManager temporarily durably retains actual collection outcomes and their
  unique evidence IDs before direct archival. Verified archival permits safe
  temporary retirement; duplicate IDs cannot duplicate archive records. Authorized
  evidence-write recovery may use a durable outcome without repeating file transfer.
  Interrupted writes or outcomes lacking temporary durability remain unconfirmed
  (Decision 363); no specific temporary filename/schema is accepted.
- Ingestor compiles the existing ArtifactManifest handoff at acquisition closeout;
  StorageManager durably preserves it for later operator-selected collection of
  one or multiple stopped Sessions without restoring original Session bindings.
  Decision 364 specifies a small Session-associated JSON file in the existing
  Session directory, separate from artifacts and the Evidence Archive. Verify its
  durability, validate saved information, use deployment-local endpoints and
  existing persistent Session information for selection, and report missing or
  inconsistent information rather than inventing it. No exact filename/API is set.
- Separately authorized Kill Session preserves accessible evidence, available
  files, a partial Session Record, unresolved conditions, and resource safety where
  possible. It does not automatically collect artifacts or permanently close the
  partial archive. Killed Sessions remain eligible for later collection; confirmed
  Stage B closure makes the archive immutable. Decision 365 requires complete
  producer/acceptance/Stage A confirmation for Normal Stop, but permits explicitly
  identified partial preservation for Kill when completeness cannot be established.
  Partial preservation does not prove acquisition success, retrieval, cleanup, or
  safe hardware release. Existing device/resource safety remains required; unknown
  is neither confirmed success nor confirmed failure. No killed state is added.
  The W048 clarification in Decisions 113, 362, and 365 specifies `experiment_abort`
  for the active Experiment, separates unconfirmed cleanup from that termination,
  and permits later collection from available verified artifact information while
  explicitly retaining partial preservation and missing/uncertain information.
  Normal Stop completeness requirements are unchanged. W048 now has a bounded
  completed implementation with independent validation and final re-audit PASS after corrections (W048). This is not a new unresolved Experiment
  event-mapping question.
  Decisions 034/365 also permit Session transition to `aborted` when participant
  cleanup remains unconfirmed. `cleanup_occurred=True` records local Session
  cleanup, not confirmed cleanup of all participants. Participant cleanup, hardware
  safety, and resource-release obligations remain separately represented, with
  existing safety and authorized recovery protections mandatory. The Session
  lifecycle clarification is resolved; W048 independent validation and final re-audit PASS are complete, without changing Normal Stop guarantees or closing Q019.
  Decision 364 now permits StorageManager to refresh a partial handoff from
  additional verified manifests obtained through authorized recovery, following
  existing Ingestor compilation rules and confirmed durability while preserving
  existing evidence. Only pre-Stage-B refresh is permitted: the first collection
  attempt, even if failed or incomplete, makes the handoff immutable. Historical
  evidence, collection outcomes, and permanent archive closure cannot be rewritten.
  This resolves the partial-handoff evolution question; W048 implementation and validation are complete; Normal Stop guarantees and broader open work remain unchanged.

Decisions 356-360 qualify historical Decisions 223-225, 228-229, 240, 243, and
274-275. They reuse existing owners, evidence infrastructure, and Decisions
276-280's journal-backed guarantees, not terminal markers per producer, count
registries, arbitrary sleeps, polling, a new transport, or a new manifest registry.

Why this matters

Phase 12 established LocalStorageManager ownership of local scientific persistence.
Decisions 219-231 establish Ingestor compilation and StorageManager writing of the
Evidence Archive and final Session Record. Q019's accepted contracts now specify
acquisition completeness, two-stage archival, and durable later collection handoff
without transferring ownership of local scientific records. W041-W043 validate
the bounded receiving, publication, and Stage A archival slices; remaining
implementation and technical guarantees still require verification.

Historical implementation and validation

Decisions 271-275 historically settled the narrow global collection evidence model: StorageManager
produces one compiled persistent record per completed pass through the existing
durable evidence boundary. Scientific acquisition end is not Session processing
finalization, and the Evidence Archive must not be treated as finally complete
before legitimate post-session evidence has an opportunity to be produced.
That historical model is implemented through explicit awaited publication before
finalization; it does not resolve the broader
Session-wide consumption guarantee below.

Decision 322 settles Controller-specific persistence and binding-release
obligations: every ControllerActionDecision is persistent, and Controller must
confirm durable archival of all its decisions for that Session before releasing
the binding. Publication alone is insufficient. The narrow Phase 16 Slice 1
follow-up implements packaging, attached-Ingestor submission, and confirmation of
exact Controller decision messages against current confirmed archival held stable
through release commitment. This narrow implementation is manually software-validated
and independently audited PASS (W035), not an open persistence-selection question.
This does not establish that all participants' published evidence has been consumed,
change global finalization semantics, or resolve the Session-wide questions below.

Decisions 240-244 settle the Slice 22 handoff: Ingestor groups Session-scoped
manifest evidence by artifact_manifest_id, selects the complete finalized
manifest or initial manifest with missing finalization reported, and makes the
handoff available to Controller. Controller coordinates delivery to StorageManager.
Compilation is implemented, manually validated, and independently audited with
verdict PASS; Slice 22 is complete (W031, M010). Diagnostic association remains
outside Slice 22, as do its historical restart-recovery and Artifact Plane
retrieval exclusions. Decisions 276-280 now accept known-Session Ingestor journal
recovery in completed Slice 27 (M014, W034), independently software-validated
with corrected re-audit PASS, using the unchanged handoff compiler.

Known-Session reconstruction of the normal Ingestor evidence/handoff view is
settled by Decisions 276-280 and completed under M014 after independent manual
software validation and corrected targeted re-audit PASS (W034). Recovery-journal
cleanup and application-level Session discovery/resumption remain deferred in Q024.
W033's manual Scenario 4 deliberately accepted publication without delivery:
Ingestor retained zero collection records and finalization produced an archive
without that undelivered evidence. This demonstrates the open consumption gap,
not a Slice 25 implementation failure. The corrected active-operation guard
prevents overtaking publication, but does not resolve post-publication consumption.
W033/M013, W035, W039, and W040 remain historically complete for their validated
scopes; none establishes the new complete Decisions 356-365 closeout contracts.
W041 separately validates Decision 361's receiving foundation and routing prerequisite
after both audit corrections, not a full acquisition-closeout guarantee.

Remaining implementation and technical-verification work

- **Producer/receipt integration:** Integrate W042's validated producer-confirmation
  and marker prerequisite with W041 receipt proof into complete acquisition
  closeout. The supported implementation publishes node
  evidence before existing successful completion responses, confirms synchronization
  publication, and explicitly publishes Controller-owned evidence before one stable
  marker. It refuses unfinished Controller health processing without replay or polling.
  No complete Normal Stop/archival integration is claimed. Receipt alone does not prove these
  obligations, successful Normal Stop, Session completion, or archive preservation.
  The current proof requires intact global stream history from sequence 1 and has
  linear broker-history read cost; losing unrelated older history can block proof.
  Missing history or gaps cannot be waived.
- **Stage information and interrupted writes:** W043 completes independent validation
  and audit of the bounded Stage A slice: W041 receipt of the W042 marker, current complete
  persistent evidence/all runtime audit plus final Session Record, exact readback,
  and an open archive. The Session remains stopping and bound; no durable handoff
  is substituted. W045 separately completes bounded Stage B collection/direct-storage
  origins, temporary outcome durability, duplicate protection, and authorized
  evidence-write recovery. W046 separately validates explicit permanent closure;
  full integration remains pending.
- **Stage B trusted baseline (accepted LLC clarification for W045):** The prior
  preservation-baseline blocker is resolved architecturally. For a known Session,
  StorageManager may validate persisted runtime evidence, intake audit, compilation
  summary, final Session Record, and applicable durable handoff independently of
  cached state or original Controller/Ingestor bindings. Existing identities,
  counts, provenance, completion information, and persistence guarantees establish
  internal consistency and Session association; a Stage A flag alone is insufficient.
  No preservation registry, database, additional snapshot record, or new evidence
  infrastructure is required. Acquisition evidence must not be rebuilt from a new
  Ingestor compilation to establish the baseline. Stage B preserves acquisition
  evidence, intake audit, and final Session Record, recognizes confirmed direct
  evidence without duplication, and respects confirmed permanent closure.
  Restarted evidence-write recovery retains durable temporary outcomes/IDs and
  existing authorization constraints, without automatic artifact refetch or repair.
  Missing/conflicting/incomplete/untrustworthy evidence remains unconfirmed.
  Scientific-artifact preservation is primary; operational-evidence uncertainty
  does not automatically mean scientific-data loss or corruption, and mandatory
  evidence guarantees still apply. Bounded W045 collection/direct persistence is
  complete with existing authorized evidence-only recovery, independent manual
  validation, and final targeted independent re-audit PASS after correction.
  W045 records 32 initial developer tests passed, 9/9 initial independent manual
  checks passed, initial audit FAIL with two P2 defects, 14 correction tests passed,
  3/3 independent correction checks passed, and final re-audit PASS with no remaining
  confirmed P0-P3 defects. Corrected guards reject missing/inconsistent provenance,
  cross-Session acquisition envelopes, and incomplete intake audit before unsafe
  replacement or baseline confirmation. Eligible-Session selection and overall
  software integration validation are complete; Q019 is CLOSED in W050.
- **Durable handoff and selection:** The bounded Decision 364 handoff slice is
  complete with automated testing, independent manual validation, and independent audit PASS (W044):
  explicit protected post-Stage-A compilation, separate durable JSON, known-Session
  readback after restart, and applicable binding-release protection. Missing
  finalization stays explicit; corrupt/conflicting contents are not implicitly
  repaired. Eligible-Session selection is complete with independent validation and
  final independent audit PASS after correction (W049); overall Q019 software integration validation is complete in W050.
  No new registry or restoration mechanism is introduced.
- **Eligible-Session selection complete, independently validated/audited (W049):** Decision 364's
  accepted clarification requires durably confirmed `completed`, `failed`, or
  `aborted` for ordinary operator-selected collection. Persisted `stopping` is
  ineligible until termination status is resolved through existing recovery.
  Incomplete, missing, or corrupted scientific files and unconfirmed participant
  cleanup do not disqualify an otherwise eligible Session; eligibility does not
  authorize hardware or resource release. Existing persisted information is reused.
  StorageManager enumerates saved Sessions from existing persistent Session
  directories and records without a registry; Controller coordinates operator
  selection of one or multiple Sessions. Each candidate is independently validated
  using existing persisted information. A durably confirmed terminal Session remains
  eligible despite incomplete or corrupted saved collection information. Collection
  availability is separate: StorageManager must verify the persisted information
  required for safe retrieval and evidence persistence. Scientific-file defects
  alone do not block attempts; missing, inconsistent, corrupted, or interrupted
  preservation information blocks collection until existing authorized recovery
  resolves it. Permanently closed archives cannot accept further collection.
  Eligibility, availability, and blockage reasons are reported separately.
  Operators may select only confirmed eligible and available Sessions. Unavailable
  Sessions remain listed, cannot be selected, and report an unavailability reason.
  Controller processes selected Sessions independently; one collection failure
  does not prevent the others. Results include each Session's collection outcome
  and an overall summary of complete success, partial success, or failure. No
  all-or-nothing transaction, special ordering, or automatic retries are required.
  The additional multi-Session selection semantics are resolved, preserving
  per-Session collection, recovery, and closure protections. Q019 is CLOSED after
  overall integration validation (W050). W049 completes StorageManager enumeration,
  independent lifecycle/availability readback, and Controller single/multi-Session
  collection using existing mechanisms. Initial developer tests 14/14 and manual
  validation 6/6 PASS preceded audit FAIL with P2 eligibility bypass and P3 nested
  fixture cleanup failure. Corrections passed 24/24 developer tests and 6/6
  independent checks; final audit PASS found both resolved and no new P0-P3 findings.
  Q019 is CLOSED following W050; W041-W048 and all other
  open statuses are unchanged. The full history and limitations are recorded in W049.
- **Closeout integration:** Decision 365's bounded Normal Stop confirmations are
  complete with independent validation and targeted re-audit PASS after correction
  (W047). Explicit partial Kill preservation is complete with independent validation and final re-audit PASS after corrections (W048),
  retaining safety, uncertainty, and binding-release obligations.
- **Permanent archive closure:** The accepted Decision 362 clarification resolves
  the separate-request and closure-eligibility contract above. W046 explicit closure
  is complete with initial developer tests 27/27 and manual validation 8/8 PASS;
  initial audit FAIL with one P2 path-alias defect; correction tests 6/6 and
  independent correction validation 2/2 PASS; targeted independent re-audit PASS
  with no remaining confirmed P0-P3 findings. Complete target/root normalization
  prevents final-record immutability bypass after restart and preserves valid
  pre-closure writes. These are prior results, not new validation during closure;
  W045's completed collection/evidence persistence never automatically closes the
  archive or changes Session lifecycle. W046 does not close Q019.

These are accepted low-level contracts with bounded W041-W049 implementation and
validation complete, not four unresolved architectural choices. Overall integration
validation remains pending. Any inability to satisfy them returns
for architectural review; this task chooses no speculative broker configuration.

Closure
All supported Q019 implementation and overall software integration requirements
are complete in W041-W050. No Q019 implementation blocker remains. Broader
deployment validation and Q022/Q024/Phase 16/M015 work are not closed here.

Q019 is CLOSED following overall software integration validation (W050). Decisions 356-365 and clarification 366 settle the high-level
and low-level contracts above. W041-W046 complete only the receiving,
publication, bounded Stage A archival, durable handoff, and bounded Stage B
collection/evidence-persistence and explicit permanent closure slices. W047-W049
complete bounded Normal Stop, Kill, and selection; overall integration validation
remains pending.
The bounded W047 Normal Stop path is complete with independent manual validation
and targeted re-audit PASS after correction. Initial developer tests 19/19 and
manual checks 6/6 PASS preceded an initial audit FAIL with two P2 findings:
pre-marker cancellation permitting legacy completion, and late intake omitted
from the final record. Corrections passed 12/12 developer tests and 3/3 independent
checks; final targeted re-audit PASS found no remaining confirmed P0-P3 findings.
It composes W041-W044 prerequisites before
normal completion without automatically invoking Stage B or permanent closure.
Eligible-Session selection is complete in W049; overall integration validation
remains open. W047-W049 close their bounded workflows, not Q019.
The original
Slice 25 exclusions remain historical; they do not prohibit the newly accepted
verified acknowledgment proof.
Do not implement that proof through assumptions, polling, sleeps, count registries,
or another transport. Q024, Q022, Phase 16, and M015 retain their open statuses;
Consolidated Q019 completion is recorded in W050 without closing broader milestones.


Q020: What is the global finalized scientific-data collection model?
Why this matters

After local scientific records are finalized, the framework must define how finalized artifacts become globally managed copies while preserving the ownership boundaries established for LocalStorageManager.

Questions
Controller initiation and StorageManager retrieval ownership are settled by
Decision 240; Slice 22 implements information handoff only, not byte collection.
Decisions 248-260 define the single-file global copy, manifest-identity destination,
successful transfer/closure/promotion, and unchanged local ownership. Implementation
has software coverage in W032; real Jetson/SSH-SFTP deployment validation remains
pending (M011 open). These ownership and v1 success questions are no longer open.
Decisions 261-270 settle StorageManager light-verification ownership and the first
contract for the current LocalStorageManager HDF5 layout. This architecture is
implemented and software-validated (M012 complete, W032); it does not redefine
Slice 23 retrieval success, require nonempty scientific records, or redesign
manifests. Decision 303 resolves the former Q017: later global processing failure
does not retroactively change a completed Session's lifecycle. Source reachability
remains distinct under Q023, and evidence-consumption coordination remains Q019.
What future format/layout contracts should cover JSONL, additional HDF5 layouts, binary electrophysiology, and other scientific products?
What future checksum or deeper verification policy, if any, extends the bounded Slice 24 contract?
How should a future broader ScientificProduct structural contract describe arbitrary products and instantiated expectations, relate device/component capabilities to Experiment selections, and relate persisted layouts to verification contracts without assuming a universal HDF5 schema?
What retention or deletion policies separate local and global copies?
What future cleanup policy applies to local and global copies?
Blocks
Global scientific storage
Reconstruction
Export


Q021: What is the runtime artifact-transfer orchestration model?
Why this matters

The framework intentionally separates runtime acquisition from large-artifact movement. Future versions require an orchestration model that determines when transfers occur without interfering with acquisition.

Questions
What later runtime scheduling policy complements accepted Controller-initiated post-session collection?
How is AcquisitionNode availability monitored?
When may transfers begin?
How are interrupted transfers resumed or retried?
How is transfer progress represented?
Decisions 287-288 settle that acquisition reservations end after local artifact
finalization and do not cover global collection. Later retrieval needs no
original reservation, even after the node participates in another Session.
Monitoring and global collection scheduling remain future work, not authority
to retain/reacquire acquisition reservations or delete source artifacts.
Decisions 271-274 settle post-session collection-pass evidence: one StorageManager-owned
compiled persistent global_artifact_collection_evidence record containing actual
per-artifact collection and verification outcomes through the existing evidence
path. This is completed Slice 25 behavior (M013, W033), not an open
ownership/granularity question. Session-wide archive-finalization coordination
remains Q019.
What additional operational progress evidence, if any, is required during future
scheduled or resumable transfer beyond the accepted completed-pass evidence?
Blocks
Online deployment
Large-artifact movement
Distributed operation

---

## Q022: What is the deployment-local configuration and initialization model?

**Status:** OPEN - Q022-A installation/deployment design is accepted and synchronized
in Decisions 367-378; the bounded Ingestor-StorageManager NATS persistence slice is
complete with independent validation and final re-audit PASS after correction
(W051). The local correlated persistence adaptation is also complete with
independent validation and audit PASS (W052). Product-based node acquisition and
operational-evidence preservation are complete with independent manual validation
and final re-audit PASS after correction (W053, bounded Slice 3A). Owner-level
replacement/closeout reconciliation is complete after independent validation and
corrective re-audit PASS (W054, bounded Slice 3B). The combined Decision 377-378
replacement is implemented and accepted in W055 after functional audit PASS and
targeted correction of its sole clean-replacement P3. The user and ICC accepted
verification without another independent re-audit for this test-only cleanup.
Remaining deployment work is pending.
Q022 as a whole is not closed. Q019 remains CLOSED in W050.

**G2 CLOSED within validated software scope (Decisions 394-395):** Every Experiment
has a configured duration before start, governing automatic termination and the
capacity-estimation horizon. Selected device operating configuration, scientific
storage representation and declared characteristics determine estimates; an
explicit authoritative byte budget is permitted when estimation is not defensible.
Existing size/rate fields are not reinterpreted. Each Experiment must pass capacity
readiness for its recording and required preservation destinations, accounting for
shared filesystems; insufficient or indeterminate capacity blocks readiness for
GUI and headless operation alike. The accepted future GUI warning is recorded in
gui_design_notes.md, not implemented here.

The initial inspection found no existing automatic duration expiry mechanism.
Accepted Decision 395 resolves execution/delegation: nodes translate the common
Experiment deadline through authorized synchronization mappings and enforce it
locally, including during Controller disconnection or subsequent synchronization
communication loss. Nodes finalize products and preserve expiry evidence;
Controller reconciles the canonical Experiment end without ending the Session.
The bounded implementation under Decisions 394-395 now carries explicit
ExperimentConfiguration, per-destination capacity readiness, mapped local expiry
and Controller reconciliation. Unsupported estimation requires explicit budgets;
unconfirmed filesystem capacity/identity fails readiness. Failed preparation
preserves the Session baseline; post-start activation failure resolves canonical
lifecycle and reports scientific cleanup uncertainty separately. ICC independent
adversarial validation and final separate Codex read-only audit passed with no
remaining confirmed P0-P3 findings, after the documented P2 corrections. See
[G2 closure](validated_workflows.md#g2---experiment-capacity-preflight-and-autonomous-duration-expiry)
for evidence and limitations and installation_and_deployment.md for APIs.
Runtime duration extension remains deferred. No live deployment/hardware,
OS-signal, power-loss or normal Windows asynchronous scheduling validation is
claimed. Q022 remains OPEN; this does not close Q024, M015 or Phase 16.

**G3 CLOSED within validated software scope:** The AcquisitionNode
service launcher now enables one adapter-owned sustained execution task. Active
Experiments with selected scientific outputs repeatedly use the existing bounded
iteration, local scientific storage, timestamping and operational evidence paths
without per-iteration Controller requests. Experiment finalization/runtime stop
quiesces the task; service cleanup disables and joins it. Controller disappearance
is not a stop trigger. Bounded callers remain supported without automatic
scheduling. This does not implement G2 capacity preflight, G4 remote health-action
execution, G5 hardware deployment validation, or close Q022/M015/Phase 16. See
the G3 section in installation_and_deployment.md and the focused
tests in tests/test_sustained_acquisition.py. Implementation verification passed
26 checks; independent ICC IPython validation passed 5/5; separate independent
Codex audit PASS found no confirmed P0-P3 findings, with 15 automated checks and
two adversarial workflows passed. These stages are not additive totals. Three
distributed closeout checks remain unverified because Windows hard-link
permissions blocked promotion; a minimal os.link() control reproduced the failure.
Live PC-Jetson/NATS integration, camera hardware/performance, OS-signal, power-loss
and normal Windows asynchronous scheduling validation are not established. See
[G3 closure](validated_workflows.md#g3---sustained-acquisition-execution) for evidence
and limitations. Q022 remains OPEN; this does not close Q024, M015 or Phase 16.

Decisions 379-381 resolve Slice 2's distributed scientific synchronization
architecture gate: measured cross-clock validity, local affine application and
provenance, readiness and degraded timing. This bounded implementation is complete
with independent validation and final audit PASS (W056); advanced Q006/Q018 scope
stays OPEN. Q022 remains OPEN for remaining deployment integration and verification.

AcquisitionNode-to-Ingestor durable operational evidence over NATS is complete
with independent IPython validation and audit PASS in W057 (Slice 3). Exact
journal-backed acceptance readback remains distinct from publication, W041
complete receipt, archival preservation and artifact-release authorization.
Remaining Controller orchestration, recovery and deployment integration are not
closed by W057; Q022 remains OPEN.

Bounded Slice 4 remote single saved-Session collection is CLOSED in W058 after
independent IPython validation and final audit PASS of d788d2e. All three P2
replay/result-correlation defects are resolved, including same-nonce identity
conflicts. Controller uses NATS without local owner references; StorageManager
revalidates eligibility/preservation and reuses durable outcomes without refetch.
Full cross-process Normal Stop/Kill, Stage A receipt/handoff, completion/release,
saved-Session enumeration/batch coordination, broader authorized
recovery, configuration/role launching and installation verification remain open.
This closes only the implemented Slice 4 boundary, not Q022.

Explicit Controller-driven remote permanent closure of one saved Evidence Archive
is CLOSED in W059 after initial audit FAIL, cached-success history-validation P2
correction, independent IPython correction validation 3/3 PASS and final focused
audit PASS of 31b2c7e. Owner consistency/durability checks, complete scoped history
and current archive readback remain required; closure does not terminate the
Session, release resources or alter scientific products. Corrective automated
runtime attempts stalled inside the sandbox without results. Full cross-process
enumeration/batch, broader recovery and bootstrap remain open; distributed
closeout/release and Stage A are closed separately in W060;
Q022 is not closed.

### Distributed completion and release clarification (Decision 382)

**Architecture resolved; bounded implementation CLOSED in W060.** The Normal Stop completion
marker is last-call after required producer-publication confirmations. Ingestor
must independently prove the full publication interval, contiguous durable receipt
and journal consistency before finalizing acquisition intake. Subsequent
acquisition deliveries, including duplicates, cannot modify finalized Stage A
evidence, audit or final Session Record. Finalized intake plus StorageManager's
verified complete Stage A/handoff establishes acquisition-preservation eligibility;
an earlier mutable snapshot or the marker alone does not.

Controller alone transitions Session lifecycle after all existing cleanup and
safety obligations. Correctly correlated owner preservation results and existing
durable readback/recovery must support restart and fail closed on missing or
superseded confirmation without rewriting finalized evidence or unnecessarily
repeating confirmed Stage A. Each service still independently satisfies Decision
313 before releasing its binding; preservation does not establish hardware safety
or resource-release eligibility. Partial Kill, later collection and explicit
permanent closure remain distinct.

Decision 382's distributed closeout implementation is independently validated and
audited in W060: finalized intake, durable Stage A, Normal Stop/Kill, restart
reconciliation and independent release. Audits confirmed corrections to framework
routing, pre-marker health, current Controller evidence coverage and subscription
release retry bookkeeping. The final nats-py 2.16.0 cancellation investigation
found no reproducible defect; controlled probes passed, while Windows asyncio
startup blocked live task-level verification. No application restoration,
multi-host/hardware or power-loss validation is claimed. Q022 remains OPEN for
its remaining deployment, remote enumeration/batch and broader maintenance/recovery
obligations; Q006/Q018, Q024, Phase 16 and M015 remain OPEN. W001-W059 are unchanged.

### Manual service entry points resolved (Decisions 383-388)

The accepted CLI boundary reuses one common package and existing service
initialization/readiness/maintenance. It preserves the shared Ingestor/StorageManager
process and other independent roles. Local Ctrl+C requests maintenance Stop;
blocked Stop automatically Cancels and keeps running. Separate terminals directly
address existing NATS Stop/authorized Kill/Cancel without Controller; Kill continues
the same blocked attempt. Exit waits for confirmed maintenance and required final
result handling. Existing identities, temporary per-invocation requesters, local OS
username and explicit remote administrator identities are not new authentication.
Terminal feedback separates existing outcomes and reserves exit code 0 for
confirmed success. No forced repeated-Ctrl+C exit or interactive Kill is accepted.

This resolves manual CLI behavior, not configuration provisioning or Q024 recovery.
Bounded common launching/local graceful shutdown is CLOSED in W061 after
independent IPython validation (22/22) and focused re-audit PASS following two P2
corrections. W063 closes the remaining Controller, AcquisitionNode and
SynchronizationManager launch paths using service-specific remote evidence
preservation after independent IPython validation (60/60, zero failures/errors/
skips) and independent architectural audit PASS with no confirmed P0-P3 findings. The LLC
confirmed existing architecture is sufficient: unrelated producers may continue
after a retiring service establishes its own stable evidence boundary. General
configuration provisioning remains outstanding. Addressed remote Stop/Kill/Cancel
issuance is CLOSED in W062 after independent IPython validation (41/41 initially,
42/42 after correction; overlapping sets) and focused independent re-audit PASS.
The initial audit's interrupted-Kill feedback P3 is resolved without changing
authorization or maintenance semantics. This adds no service launch paths or
Controller dependency. W063 is CLOSED; general configuration/provisioning,
installation verification, remote enumeration/batch integration and broader
maintenance/recovery and deployment integration remain outside this slice.
Q022 remains OPEN. Q019 and W001-W066 remain CLOSED. Existing Q006/Q018, Q024,
Phase 16 and M015 statuses are unchanged. See installation_and_deployment.md for
the supported entry points and validated_workflows.md for verification limitations.

### Shared-storage external-dependent maintenance (W068 CLOSED)

Decision 389 records the accepted LLC External-Dependent Retirement Confirmation
clarification and resolves W068's architectural blocker. Ingestor removes a
dependent blocker only on confirmed retirement for the identified operational
instance/maintenance attempt, or Controller's specifically authorized dependency
release at the coordinated final archival checkpoint. Confirmation must be
delivered and available to Ingestor before the dependent launcher exits; missing,
stale, contradictory or incorrectly correlated confirmation retains the blocker.
Preparation, disappearance and publication acknowledgment alone are insufficient.

Controller's release confirms preserved Ingestor-dependent obligations and no
further such work; it is not Controller retirement. Existing Stop/Kill/Cancel,
Decision 324 final-confirmation authority and Decision 326 ordering remain intact.
Minimal representation/correlation extensions are implementation choices, not a
new lifecycle authority or retirement-evidence subsystem.

W068 now implements explicit external-dependent participants in storage service
files/CLI, service-owned instance IDs and startup admission registration, scoped
NATS confirmation/readback and existing-framework-journal/archive-backed callback
state. Deployed owners retain their process until Ingestor confirms their exact
retirement result; explicit retry does not repeat cleanup. New dependent instances
reestablish blockers before unrelated operational admission. Prepared Controller
releases only its dependency at the coordinated final archival checkpoint and
cannot create further Ingestor-dependent work. It remains able to coordinate
subsequent retirement commands and retires last.

The truthful isolated path remains supported; no false no-dependents declaration
is needed or permitted for external mode. Decision 390 resolves ordinary
shared-owner restart: an intact archive must be verified as an internally
consistent exact historical prefix of recovered authoritative evidence and
applicable intake audit before additional accepted recovery evidence is archived.
Complete current confirmation precedes reconsideration of Decision 389 releases.
This startup integration is implemented and validated. Unavailable or
invalid history/confirmation retains blockers; actual interrupted-write repair
remains under Decisions 339/342/347, not silent continuation. No new recovery
mechanism or authority is introduced. W068 is CLOSED after the P2 ordinary
maintenance-write bypass correction, independent manual IPython validation (3/3
scenarios PASS across two executions, after a harness correction), and final audit
PASS with no remaining confirmed P0-P3 findings. Implementation verification: 83
focused tests PASS; final audit: 41 targeted tests and two independent probe
workflows PASS. Earlier Decision 390 disk validation: 5/5 PASS. Runs overlap and
are not additive; see W068 in validated_workflows.md for the complete history.
Q022 remains OPEN for remaining accepted deployment work. W001-W067 and
Q019 remain CLOSED. No live networking, hardware, OS signals or full physical
deployment verification is claimed.

### Manual installation integration (W067 CLOSED)

W067 integrates the existing W061-W066 interfaces into the installation guide's
operator runbook and typed placeholder examples, without provisioning software or
new configuration fields. It covers machine preparation, separate service/hardware
files, SSH trust/permissions and independent dummy-byte comparison, manual startup,
fresh registered-node communication checks, recommended device tests and planned
node additions/replacements. W067 is CLOSED after independent user-run validation
(4/4 tests PASS, zero failures/errors) and independent architectural audit PASS,
with no confirmed P0-P3 findings. The five examples and documented CLI procedure
match existing interfaces within their explicitly bounded scope.

At W067 closure the shared CLI's isolated-only restriction prevented complete
file-driven deployment. W067 documented rather than bypassed that gap; W068 above
now closes callback composition under Decisions 389/390 after separate validation
and audit. Do not use an empty callback map or false declaration to proceed.
W067's historical validation does not validate W068's new implementation.
Real network/SSH, hardware/backend/permissions, OS signals and complete deployment
remain operator verification. W069's parameter-exposure validation/audit is CLOSED;
remaining accepted deployment integration obligations remain OPEN under Q022.
Q022 remains OPEN for remaining accepted
deployment obligations. Q019 and W001-W067 remain CLOSED; unrelated
question/milestone statuses are unchanged. See W067 in validated_workflows.md.

### DeviceAdapter adjustable-parameter exposure (W069 CLOSED)

Decision 370's bounded implementation now exposes adapter-owned Session parameter
definitions in existing AcquisitionNode/NATS `get_inventory` responses under
`session_parameter_definitions`, keyed by installed device identity. Controller
`get_node_inventory(...)` retrieves fresh correlated definitions without creating
a Session or initializing devices. `SessionConfig.device_configurations` remains
the operator-selection path; node preparation validates partial overrides against
adapter definitions and resolves them against unchanged installation defaults.
The OpenCV adapter exposes acquisition settings, not camera source/backend
connection overrides. Successful cleanup and later initialization preserve
Decision 302's Session isolation. This does not implement a GUI, discovery or a
new configuration authority. W069 is CLOSED after independent IPython validation
(Part 1: 6/6 PASS; Part 2: 9/9 PASS) and independent architectural audit PASS with
no confirmed P0-P3 findings. A separate probe confirmed selected/unselected adapter
isolation but subsequently failed on unrelated missing local-storage configuration;
it does not prove full Session initialization. Q022 remains OPEN for remaining
accepted deployment work. No live NATS, camera hardware or normal Windows
asynchronous scheduling validation is claimed. See W069 in validated_workflows.md.

### Q022-A accepted scope

W066 implements an explicit `verify-node` installation communication check through
the existing Controller deployment file and NATS `check_readiness` contract, with
fresh node/operation-scoped replies and complete request correlation. It constructs
no Controller owner and performs no reconciliation or scientific lifecycle work.
Current hardware-unready reports may confirm communication without establishing
scientific readiness. W066 is CLOSED after independent IPython validation (17/17
communication tests and 11/11 connection regressions, separate runs) and final
focused re-audit PASS with no remaining confirmed P0-P3 findings. Initial audits
found partial client ownership (P2-A), then interrupted cleanup (P2-B); both are
resolved. Cleanup retains the owned client/task until completion despite repeated
caller cancellation. A controlled concurrency probe passed using actual asyncio
tasks/shield and nats-py/TcpTransport with simulated I/O. Controlled execution is
not normal Windows scheduling validation; no live NATS, real sockets, hardware or
OS-signal validation is claimed. Q022 remains OPEN for applicable manual
provisioning/installation integration and remaining accepted deployment requirements.

W065 implements explicit installation-time SSH/SFTP dummy-file retrieval and exact
comparison through the common CLI and StorageManager's existing endpoint/transport
interfaces. The expected file is independently established; bounded temporary
downloads are cleaned without scientific/Session writes. Reading retrieval inputs
does not waive the paired operational launcher's external-dependent callbacks.
W065 is CLOSED after independent IPython validation (11/11 PASS) and independent
audit PASS with no confirmed P0-P3 findings or architectural blockers. The audit
passed 12 focused tests and two additional probes; overlapping counts are not
additive. This is not live installation verification, a certification system or
a runtime gate. Controller-to-node installation communication verification is
separately closed in W066; applicable manual provisioning/installation integration
and remaining accepted deployment requirements remain open under Q022.

W064 implements deployment-local general-service JSON loading, validation and
integration with all existing launch paths, separate from the node hardware file.
Explicit file mode does not merge with constructor flags or alter existing flag
launching. Local retrieval settings are passed to StorageManager without checking
remote connectivity. W064 retained the paired CLI's explicit no-external-dependents
limitation; W068 now implements configured external composition without claiming
it was covered by W064 validation. W064 is CLOSED after independent IPython validation (9/9 configuration tests
and shared-storage startup integration PASS) and independent architectural audit
PASS with no confirmed P0-P3 findings or unresolved architectural blockers.
Q022 remains OPEN for applicable installation provisioning, installation
verification, Controller-to-node communication verification, SSH/SFTP dummy-file
retrieval/content comparison and remaining deployment integration. No broader
question or milestone is closed here; see W064 for verification limitations.

One installed package is launched with an explicit service role. Installation uses
local files outside Git, derived from committed templates, with general service
settings distinct from AcquisitionNode hardware configuration. Node configuration
identifies persistent node/device identities, explicit adapter choices, physical
connections, and node-owned scientific storage. Installation changes require
service restart; node startup supports a default configuration location and an
explicit path. File format, exact path, and final CLI syntax are implementation
choices, not unresolved architecture.

Adapters define exposed operator parameters and constraints; inventory exposes
them to Controller for future GUI clients. Session overrides use existing config
mechanisms and adapter validation without retaining prior-Session overrides.
Startup configuration validity and actual hardware readiness are separate.

Decision 376 revises Decision 375: Ingestor and StorageManager share one computer,
process and startup/shutdown/restart lifetime, retaining distinct components and
permitted local Python calls. Controller, SynchronizationManager, and nodes remain
independently deployed; all process-crossing access, including Controller access
to both components, uses NATS. Every receiving component
retains its own operations, state, locks, evidence, and persistence authority.
Local collaborators within the pair are permitted; process-crossing direct
collaborators still require adaptation. Duplicate authoritative owners are not a
deployment solution. Requests require trustworthy confirmations; missing results,
timeouts, and failures are not success. Existing identity, durability, idempotency,
and recovery guarantees remain mandatory.

Controller's local known-node list supplies existing startup/restart reconciliation;
list changes require Controller restart. Duplicate node identities are conflicts
and cannot be used ambiguously for launch. No registry, discovery, polling, or
automatic stopping/recovery is introduced. General non-node identity policy is
not expanded by this AcquisitionNode-specific clarification.

Required installation checks cover key-based SSH/SFTP setup, verified dummy-file
retrieval, node NATS connectivity, and Controller-to-node readiness communication.
An offline node does not block StorageManager startup, and NATS connectivity is
not evidence acceptance. Capability-appropriate device acquisition tests are
strongly recommended but are not certification fields or runtime gates. Initial
installation is manual, not a GUI/interactive installer. See
[installation_and_deployment.md](installation_and_deployment.md) for the accepted
procedure, current reuse/gaps, and validation boundaries. W051 closes only the
NATS persistence/receipt/compilation foundation, not full independent-service
deployment, Controller closeout/release, acquisition/timing adaptation,
cross-process maintenance/recovery, configuration/launching, or installation
verification; broader Q022/Q024/Phase 16/M015 remain open.

### Why this matters

Decision 076 establishes public-repository configuration boundaries: deployment
values belong in untracked local configuration derived from committed templates,
not hard-coded or committed machine-specific values. Decision 247 settles
endpoint ownership: StorageManager consumes deployment-local configuration that
resolves logical `acquisition_node_id` to a retrieval endpoint; portable manifests
and handoffs do not carry endpoint or authentication information.

Slice 23 may consume an already-provided retrieval configuration/resolver. It
does not define creation, loading, initialization-time validation, or propagation
through startup/Controller/Session initialization. Q008 retains the broader
configuration-model questions; this entry isolates deployment initialization.

Slice 28 (Decisions 281-301) uses existing communication mechanisms and
participants already available to Controller. RuntimeParticipant contains only
component_type/component_id; AcquisitionNode inventory membership supplies device
placement without another node ID in DeviceDeclaration. Decisions 367-374 now
settle explicit node registration, adapter installation configuration, and local
retrieval mapping without discovery. Session launch ownership remains distinct;
the accepted deployment contracts still require implementation and verification.

Decision 298 settles root authority: remote AcquisitionNodes use their own
deployment-defined local storage roots/configuration. Controller does not choose
those roots or artifact paths, and the current SessionConfig.local_storage_roots
override path is historical, not remote launch authority. This resolves ownership,
not the file format; Decisions 368-369 settle file-based local provisioning while
leaving exact formats as implementation choices.
Manual independent-process startup is development infrastructure; intended
long-lived service deployment/supervision remains future work (Decision 295).
Decision 304 explicitly settles the Session-independent and GUI-independent
lifetime of the five principal operational services, without requiring one
process per service. Decision 376 requires a combined Ingestor-StorageManager
process and NATS for communication crossing process boundaries. Deployment automation
and supervision remain unresolved; Decisions 367-374 settle the initial manual
file-based configuration scope.
Decisions 313-321 settle maintenance,
independent startup/readiness, and service-owned Session-binding release without
choosing deployment formats, a discovery/registration system, or supervision.
Q025 is resolved architecturally. Session-binding release (W035) and individual-service
maintenance (W036) are complete and software-validated. Progressive two-phase
coordinated shutdown is also complete, manually software-validated, and
independently re-audited PASS (W037); independent startup/returning-service
integration under Decisions 327-331 is complete, independently manually
software-validated, and independently re-audited PASS after correction of the two
P2 readiness findings (W038). Configured dependencies
receive startup/return announcements directly; Decisions 367-374 supply their
deployment-local configuration without authorizing discovery or a registry.

Decision 302 additionally settles retained adapter reuse without process or adapter
recreation: AcquisitionNode retains deployment configuration, but subsequent
Session-specific settings come from that Session's resolved SessionConfig and
must not be silently inherited. The generic return-to-DECLARED/readiness contract
is implemented with automated coverage; independent validation and audit remain
pending under M015. Initial file-based provisioning is now accepted under Q022-A;
exact formats remain implementation choices. No lifecycle API is introduced.

### Remaining boundaries and implementation work

* Implement the accepted role launcher, file loading/validation, parameter inventory,
  explicit known-node configuration, and installation checks without new infrastructure.
* Independently validate and audit supported installation workflows, keeping actual
  deployment/device tests separate from framework software checks.
* Broader configuration-model questions remain in Q008. Service supervision and
  deployment automation beyond manual explicit startup are not settled by Q022-A.
* The composition/access question is resolved by Decision 376. Reconcile local
  Ingestor-StorageManager interfaces with W051 guarantees and shared lifetime;
  local correlated persistence is complete in W052, while bootstrap/lifetime
  enforcement remains deferred. Decision 377 supersedes scientific-envelope
  delivery/intake-journal work: routine observations and metadata remain in
  LocalStorageManager products regardless of size. Preserve operational lifecycle,
  health/failure, timing and manifest evidence through existing mechanisms and
  RuntimeEvidenceMessage journal-before-ACK/deduplication/reconstruction guarantees.
  W053 closes bounded node product acquisition/operational preservation after the
  P2 observation-loss correction, independent validation and final re-audit PASS.
  Active node scientific-envelope production/forwarding is removed. W054 closes
  Slice 3B removal/reconciliation of obsolete owner-level intake/audits,
  persistence/recovery, transport/compatibility APIs, Session Records, Normal Stop/Kill, release
  blockers, compilation and archival closeout after correction, independent
  validation and corrective re-audit PASS. Historical products and required
  interpretation remain preserved; superseded APIs are removed, not retained as
  compatibility shims. Implement service-owned NATS requests/results for currently
  direct receipt, compilation,
  persistence, readback, timing, collection, release, and recovery interactions
  before enabling dependent role launch paths. Local owner guards cannot be
  replaced by cached confirmations or assumed shared/distributed locks. The
  dependency map in installation_and_deployment.md records current gaps, not
  implemented remote APIs or new architectural contracts.
* No automatic discovery, live reload/registration, GUI installer, configuration
  database, or mandatory device commissioning gate is required by this scope.
* Future real-time scientific streaming remains architecturally OPEN; Decision
  377 selects neither its transport nor additional infrastructure. No extension
  of the Ingestor journal to routine scientific envelopes is required by Q022.
* Decision 378 resolves the adapter meaning/legacy-compatibility gate: installation
  declares supported products, Experiments explicitly select them, and adapters
  must support those products and distinguish scientific observations/metadata
  from operational evidence. Do not infer meaning from content, size or old names.
  Bounded product-based acquisition is complete in W053 and owner-level replacement
  in W054. W055 closes the combined implementation after independent functional
  integration PASS and removal of its sole remaining obsolete fixture setting,
  with nine targeted tests PASS. No further independent re-audit was required by
  the user and ICC for that test-only correction. Cross-process deployment,
  configuration/bootstrap and installation verification remain separate Q022 work.
* AcquisitionNode duplicate-ID policy is accepted; do not infer a new general
  policy for all RuntimeParticipant kinds or a global identity registry.

### Blocks

* Q022-A implementation and independent installation/startup verification.
* Combined-pair and independent-role launching depend on the remaining Decision 376
  NATS service interfaces, not another choice of composition or transport.
* Broader Q022 completion, including any remaining accepted-scope questions.

---

## Q023: When, where, and by whom should artifact source existence be verified?

**Status:** OPEN / FUTURE

### Why this matters

Local finalization evidence, manifest/handoff evidence, current source
existence/reachability, and global-copy verification answer different questions
and are not equivalent statuses:

* Local finalization evidence: did LocalStorageManager report the artifact finalized?
* Manifest/handoff evidence: did Ingestor receive evidence describing the artifact?
* Source existence/reachability: can the source still be found and opened or reached when collection is attempted?
* Global-copy verification: was the retrieved copy successfully stored and checked under the accepted retrieval contract?

LocalStorageManager knows about local creation/finalization; Ingestor retains
manifest/completion evidence; StorageManager encounters remote reachability
through retrieval. None of these alone proves the other statuses.

Decision 251 remains accepted: Slice 23 attempts retrieval directly, without a
separate `exists(source)` pre-probe. Its minimal retrieval checks and reported
outcomes do not settle a broader source-verification or readiness-time policy.
This question introduces no new required check and does not amend Decision 251.
Decision 256 does not require checksum verification. Decisions 261-270 accept
separate post-copy light verification for the current HDF5 layout, not source
existence checks. Extended layout contracts and deeper global-copy verification
remain separate in Q020. Decision 303 keeps later global processing failures
separate from a completed Session's lifecycle; Q019 is CLOSED following overall software integration validation (W050).

### Questions

* Should future source-existence checks occur before acquisition, after local finalization, during handoff compilation, at retrieval, or at multiple stages?
* Who owns each check, distinguishing LocalStorageManager local-file knowledge, Ingestor evidence intake, and StorageManager remote reachability?
* How should local existence differ from remote reachability, and when, if ever, should existence checks also inspect size or metadata?
* How should a missing local artifact, manifest with absent file, unreachable node, missing endpoint, permission denial, or invalid path be represented?
* How should future source-verification failures be reported while preserving authoritative local finalization evidence and separate global collection outcomes? Decision 303 prevents retroactive changes to a completed Session's lifecycle.
* How should future checks preserve the independence of local completion and global collection?
* How can checks avoid deep verification or large-file reads solely to answer existence, and avoid embedding network-reachability assumptions in portable manifests or handoffs?

### Blocks

* Future source-verification and readiness-time checking architecture
* Future source-verification failure representation, without changing Slice 23

## Q024: What is the application restart and recovery-journal lifecycle?

**Status:** OPEN - narrow low-level contracts accepted in Decisions 332-338;
narrow reporting/abandonment/producer-memory implementation slice complete with
automated coverage, independent manual IPython validation PASS (10 scenarios), and
independent read-only source audit PASS with no blocking findings, as reported for
documentation closure. Decision 336 remains partially implemented. Decisions
349-355 now accept additional journal retirement, informed terminal deletion,
startup reconciliation, reservation protection, service-owned memory retirement,
monthly framework archives, and deletion-safety boundaries. Supported Decisions
351-352 startup reconciliation is complete with independent manual validation and
final independent re-audit PASS after correction in W040. Bounded Decision 349/393
journal retirement is CLOSED in W070B after independent ICC validation and source
audit PASS. Decision 354's bounded monthly implementation is CLOSED in W071 after
independent ICC IPython validation (6/6 PASS) and implementation/source review PASS,
with no confirmed P0-P3 findings; Decision 350 and Decisions 353/355 remain unimplemented.
Remaining implementation and unresolved operational contracts keep Q024 OPEN.
Q024-B service-specific operator-authorized execution architecture
is accepted in Decisions 339-348; supported cases have automated implementation
coverage and are complete with independent manual validation and final independent
re-audit PASS after correction, documented in W039. Q024 remains OPEN.

### Accepted Controller restart and bounded reconnection policy

Decision 391 supplements Decisions 345, 346, 351 and 352. Recovery is best-effort:
scientific integrity, operational safety and simplicity take priority over
recovering an interrupted Session. Restart uses existing participant status,
readiness, reservations and durable evidence; safely recording AcquisitionNodes
must not be stopped automatically.

Experimenter-requested reconnection to the original Session is permitted only
when Controller can automatically establish safety and scientific validity. The
experimenter may decline but cannot override failed safety requirements. Partial
reconnection is limited to operations proven safe without unreachable participants;
their identities and obligations remain unresolved. Preserve original Session
identity, recordings and timestamps, documenting supervision gaps and timing
uncertainty. Complete historical replay/event-by-event Controller reconstruction
is not required.

If safe reconnection cannot be established simply, prefer existing safe
termination/abort and partial-data preservation under existing authority and
safety guards, not automatic interruption of safely recording nodes. Abandonment
does not delete recordings or release unconfirmed resources. No elaborate recovery
subsystem, registry, extensive replay or substantial new infrastructure is
authorized solely for rare reconnection cases.

**ICC preliminary implementation assessment (not an architectural decision):**
ICC recommends deferring operational reconnection because a small, safe
implementation boundary has not been established. This is implementation planning,
not a new architectural restriction or evidence of implementation. Operational
reconnection is not implemented, tested or validated. Q024 remains OPEN; W039/W040
and all other historical validation outcomes are unchanged.

### Why this matters

**W070A / Decision 392 (CLOSED):** Ingestor now
persists closed Session identities before releasing terminal, exactly preserved
intake. Deployment-local closed-Session records are independent of temporary
journals and reject construction, preparation and late/redelivered intake across
restart. Missing/corrupt/unreadable closure information fails closed. Empty
initialization-binding release is not terminal Session closure. StorageManager
still confirms preservation, not admission. W070A is independently validated and
audited PASS; Q024 remains OPEN. W070B / Decision 349 conditional journal retirement
implementation is tracked under Decision 393 below. No terminal deletion, Decision 353-355 cleanup or Controller
reconnection is implemented here.

The initial W070A implementation passed 6/6 independent manual scenarios, but
source audit identified P2 W070A-A1: publication exclusion did not span actual
admission across root-sharing Ingestor instances. The bounded correction holds
the existing root-local exclusion through admission/recovery/acceptance and
release validation/publication, retaining stale-lock uncertainty and independent
framework routing. Post-correction Codex verification passed 60 distinct checks
(54 synchronous and six controlled asynchronous), including seven new deterministic
concurrency/interruption regressions. Final independent manual IPython validation
passed 16/16 checks and final source audit passed with no remaining confirmed
P0-P3 findings. These runs are not additive to the initial manual count. No live
NATS, independent-process deployment, hardware, real OS-signal, physical crash,
power-loss or normal Windows asyncio scheduling validation is claimed. See W070A
in validated_workflows.md. Remaining Q024 recovery work and deferred Decision 391
operational reconnection are unchanged.

**W070B / Decision 393 (CLOSED):** The accepted LLC clarification makes post-release
closeout verifiable from existing permanent Session products rather than requiring
the temporary journal. The implementation retains the verified finalization
receipt in the existing compilation summary, derives marker/audit response fields
from permanent products and preserves normal versus partial-Kill semantics.
Gate A passed before enabling `InMemoryIngestor.retire_recovery_journal(session_id)`.
That explicit operation requires durable closed admission and completed binding
release, current paired-StorageManager preservation, valid terminal/finality proof,
and intact matching journal contents before deletion under shared root exclusion.
Unconfirmed or interrupted outcomes never substitute for success; retries verify
permanent proof again. Historical normal archives without the necessary receipt
provenance retain their journal; no archive backfill or new closeout store is added.
Independent ICC manual IPython validation passed 9/9 probes, and independent
source audit passed with no confirmed P0-P3 findings. Implementation verification
passed 69 distinct checks; three hard-link integration checks were sandbox-blocked,
not passed. No live NATS, physical power-loss or normal Windows asynchronous
scheduling campaign is claimed. W070A/W070B are CLOSED; Q024 remains OPEN for
Decision 350, Decisions 353-355 and the remaining operational contracts below.
Historical workflow records are preserved; see W070B in validated_workflows.md.

Decisions 276-280 accept Ingestor crash recovery for an already-known Session;
Decision 349 now settles conditional journal retirement ownership without
changing their journal-before-ACK or deduplication guarantees. Q020's scientific
artifact retention is distinct from temporary Ingestor recovery-state lifecycle;
Q019 still owns evidence-consumption/finalization coordination. Q022 retains
deployment-local configuration responsibilities.

Decision 330 accepts recording explicit administrator resume/drop decisions
through existing framework evidence, not execution of recovery, deletion, or
cleanup. Decision 329 permits safe service reuse under existing protections,
not automatic resumption. Decisions 332-338 now accept service-specific reporting,
classification, administrative abandonment, and conditional bounded-memory cleanup.
Their original scope does not implement the newly accepted Decisions 349-355.
W038 remains complete for its existing startup/return scope; the earlier Q024
contracts have a completed, independently validated and audited narrow implementation
slice, not closure of Q024 as a whole. Existing readiness paths report owner-specific
obligations and explicit abandonment. Guarded release is limited to redundant
interface-owned producer evidence copies after complete current archival and
safety/closeout confirmation;
Decision 336 therefore remains partially implemented.
Administrative markers, command/result correctness, unsafe resources, service
bindings, and journals remain protected. Resource-specific administrative cleanup
now has the accepted narrow Q024-B execution boundaries and supported implementation
below, not authority inferred from a drop decision. Decision 353 now accepts wider
service-owned memory retirement, retaining safety/idempotency obligations; the
minimum operational state and limits still require implementation/clarification.
Q019 is CLOSED in W050; Q022, Phase 16, and M015 remain OPEN. No new validation was executed during
this documentation closure.

### Accepted narrow contracts

* Decision 332: Report unresolved previous work through existing readiness, service-owned diagnostics, `check_readiness`, administrative interfaces, and framework evidence; no universal model, registry, or new report command.
* Decision 333: Distinguish obligation outcome, recovery possibility, and operational impact independently; recoverable does not mean recovered and abandoned does not mean completed.
* Decision 334: Reuse existing affected-scope identities and restrict narrowly only when sufficient protection can be established; uncertain containment cannot prove other resources safe.
* Decision 335: Explicit administrator drop closes an obligation as abandoned/not recovered, not completed or safe; preserve administrator, service/obligation, decision, and available justification through the existing evidence pathway.
* Decision 336: Release unnecessary temporary memory only after recorded abandonment and applicable preservation, resource-safety, and closeout conditions; retain required safety information and do not automatically delete durable records or journals.
* Decision 337: Existing service-specific owners establish completion from trustworthy records and confirmed state, not intent, transport acknowledgment, missing responses, or incomplete evidence.
* Decision 338: Preserve reports, assessments, classifications, choices, and confirmed outcomes through existing producer persistence intent, Ingestor acceptance, and StorageManager framework archival; avoid redundant unchanged evidence.

### Q024-B: Service-specific operator-authorized recovery execution

**Status:** Architecture accepted in Decisions 339-348; supported cases implemented
and complete with automated coverage, independent manual IPython validation, and
final independent read-only re-audit PASS after correction (W039).
Accepted addendum Decisions 347-348 resolve pre-repair preservation admission and
the lost active Session Time boundary; their supported cases have automated coverage.
This extends previously deferred execution boundaries without changing the
completed Decisions 332-338 validation/audit record or Decision 336's partial scope.

W039 preserves the initial 22-check manual validation PASS, initial source audit
FAIL on one P2 Controller reconciliation defect, its correction, 16-check focused
manual revalidation PASS, and final focused re-audit PASS with 20 independently
passing automated tests. Final implementation testing ran 656 tests: 649 passed,
7 optional skips, zero failures. This closes only the supported Q024-B slice,
not broader Q024; no validation was executed during documentation closure.

Implemented cases are obligation-scoped archive/retained Session Record rewrites,
fresh artifact transfer using the original handoff, independent supported local
artifact finalization/device cleanup, Controller informational reconciliation, and
journal-backed historical timing/continuity reporting. Authorization and attempts
require durable intake before action; actual success and outcome archival remain
separate. Informational evidence does not implicitly repair an unconfirmed archive.
Lost inputs, uncertain partial artifacts, unowned temporary-copy cleanup, active-
Session clock restoration, and application restoration remain unsupported.

* Decisions 339-340: New recovery attempts require explicit human administrator
  authorization for a specific obligation and immediate owner validation of
  identity, scope, prerequisites, and safety. Owners distinguish no established
  recovery action, a potentially safe procedure, and proven completion; leaving
  work unresolved is not abandonment.
* Decision 341: Requests reference original obligations and specific authorization
  evidence using existing participant/evidence/command/result identities. Preserve
  successful, failed, and refused attempts through existing evidence, separately
  from acknowledgment and archival confirmation.
* Decision 342: StorageManager may attempt authorized fresh complete transfers
  and persistent-record rewrites only with trustworthy inputs and confirmed
  destination/persistence safety, without source mutation, unexpected final
  overwrites, byte-level resumption, invented evidence, or Q019 guarantees.
* Decision 343: Existing valid-journal reconstruction for an already-known Session
  remains automatic under Decisions 276-280, without new administrator authorization
  or a new Ingestor recovery mechanism. Report reconstruction failures; do not
  silently accept corrupted completed entries.
* Decision 344: AcquisitionNode partial scientific-artifact preservation and
  device/resource cleanup are independent authorized actions using existing local
  persistence and confirmed cleanup protections, not resumption of old Experiments.
* Decision 345: Controller may read and reconcile trustworthy records/confirmed
  outcomes without authorization for reading; uncertain results remain unresolved.
  New operational commands require separate authorization, not automatic replay,
  lifecycle advancement, or application restoration.
* Decision 346: SynchronizationManager preserves historical timing and active-
  Session continuity gaps/uncertainty and establishes new synchronization only
  from trustworthy current information. Do not extend old mappings across downtime,
  fabricate observations, overwrite timestamps, or automatically fail/discard a
  Session because of synchronization-service crash. Read-only reconciliation needs
  no administrator authorization.

Q024-B does not resolve journal retention/deletion, abandoned journals,
application-wide unfinished-Session discovery, Controller/application restoration,
stale reservations, or remaining memory/cache retirement. No universal recovery
infrastructure, automatic replay/retry/resumption, process supervision, new Session
states, automatic durable deletion, new evidence infrastructure, Q019 finalization
guarantees, or Q022 deployment configuration are introduced. Q024, Q019, Q022,
Phase 16, and M015 remain OPEN. Detailed execution contracts not specified by the
accepted boundaries must not be invented during documentation synchronization.

### Accepted Q024-B implementation-preparation clarifications

- Decision 347: An interrupted Evidence Archive repair requires durable Ingestor
  journal acceptance of the specific administrator authorization and attempt before
  execution. Prior preservation in the unavailable archive is not required. All
  other trustworthy-input/safety prerequisites remain; actual write confirmation
  and later outcome archival are separate. No Q019 guarantee is added.
- Decision 348: Loss of the trustworthy active Session Time reference permits
  historical reconciliation and reporting of gaps, uncertainty, and affected scope,
  not zero-based restart or an invented restoration mechanism. Preserve timestamps
  and recordings; do not automatically fail/abort/discard the Session. Healthy
  mapping updates remain unchanged and need no new administrator authorization.

These two preparation questions are resolved architecturally, not by new recovery
infrastructure. Broader Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

### Newly resolved architecture and implementation status

The following ownership and behavioral questions are resolved architecturally in
Decisions 349-355. Supported Decisions 351-352 are complete, independently manually
validated and independently re-audited PASS after correction (W040); Decisions
350 and 353/355 remain unimplemented; bounded monthly Decision 354 implementation
is independently validated/reviewed and CLOSED in W071, and bounded Decision 349/393 retirement is
complete and independently validated/audited in W070B:

- Ingestor owns conditional temporary-journal retirement; uncertain obligations,
  reconstruction/deduplication needs, or Q019 finalization confirmation retain it.
  Abandonment is insufficient and daily/monthly temporary-journal rotation is not accepted.
- Explicit informed authorization may permit terminal deletion of identified
  unrecoverable temporary evidence; failed recovery never automatically authorizes loss.
- Every Controller startup reconciles known observable participants. Services own
  durable/unfinished-work inspection; safe active acquisition is not automatically
  stopped and unreachable participants remain unknown. No Session objects or
  application orchestration state are automatically restored.
- Node-owned Session reservations survive Controller failure. Local artifact
  finalization and device cleanup are evaluated independently before authorized
  recovery/release; no leases, arbitrary timeouts, or automatic expiration are accepted.
- All five principal services retire unnecessary temporary working information
  only after preservation/safety conditions, retaining protection and idempotency state.
- Decision 354 explicitly supersedes Decision 323's shared framework layout with
  permanent `framework/evidence/YYYY-MM/` partitions. Closed archives are immutable;
  Session archives and scientific artifacts are unchanged.
- Finalized is distinct from safe to delete. Confirmed safe deletion must not affect
  later operation/recovery; permanent archives are never automatically deleted.

### Remaining operational contracts and implementation dependencies

- **Q019 dependency:** Decisions 361-365 specify acquisition completeness and
  staged archival confirmation. W041 validates the receiving foundation;
  W042-W048 validate the bounded publication, persistence, collection, closure,
  Normal Stop, and Kill slices. Overall Q019 integration validation is complete in W050. Applicable
  confirmations are integrated with bounded Decision 349/393 journal retirement
  in W070B. Eligible canonical closed-Session journals require current permanent
  closeout proof and released bindings; local acceptance alone is insufficient.
  Legacy archives lacking required receipt provenance remain journal-dependent.
- **Accepted cross-month continuity clarification:** An operation may begin in
  one calendar month and finish in another without splitting its identity or
  rewriting historical archives. Evidence belongs in the appropriate monthly
  partition using existing operation correlations. Services retain unfinished-work
  recovery information independently of finalized historical archives; future
  recovery cannot depend on archives declared safe to delete. The accepted
  clarification under Decisions 353-355 authorizes no new recovery database,
  registry or elaborate reconstruction mechanism.
- **Monthly assignment (resolved architecturally):** The subsequent accepted
  clarification of Decision 354 uses StorageManager's local system clock at
  archival write time and UTC calendar-month boundaries. Partitions are
  administrative; delayed/recovered evidence is not backdated, and scientific or
  receipt timestamps are unchanged. No synchronization service is required.
  Invalid/unavailable clocks fail closed; uncertain writes require reconciliation
  before retry without duplicate cross-partition evidence. Unconfirmed writes
  never establish preservation. Decision 355 remains authoritative.
- **Cross-month implementation (W071 CLOSED):** Codex verification passed 59
  distinct checks; independent ICC IPython validation passed 6/6 and independent
  implementation/source review passed with no confirmed P0-P3 findings. No live
  NATS, hardware, OS-signal, physical power-loss or normal Windows asynchronous
  scheduling validation is claimed. See W071 in validated_workflows.md. Existing
  StorageManager framework APIs now append newly archived evidence/audit to UTC
  write-month partitions and verify exact cumulative coverage for existing guards
  and maintenance callers. Older partitions and shared-layout historical prefixes
  remain unchanged. Existing framework journals reconstruct operational evidence,
  deduplication and audit independently of archive payloads. No archive is declared
  safe to delete: preservation confirmation and maintenance lookup still require
  retained historical products. Broader deletion independence remains outstanding.
  Incomplete/corrupt partitions block continuation and maintenance; existing
  authorized repair is limited to identified same-month interrupted targets.
  Repair/reassignment of an older or unidentified interrupted partition is not
  implemented. Missing clock information retains journaled evidence for safe retry.
- **Deletion-safety confirmation:** What existing owner-held recovery/safety
  information independently preserves unfinished and cross-month obligations,
  deduplication, and unsafe-command-reexecution protection, and what establishes that
  no future operation/recovery depends on a historical archive? The guarantee is
  accepted; the operational contract is not yet specified. No new recovery store
  or subsystem is chosen here.
- **Unavailable auditing:** How can required authorization, known-loss, and execution
  auditing for terminal deletion be established when the evidence subsystem is
  unavailable? Record the conflict for architectural clarification; no exception
  permitting unaudited deletion is accepted.
- **Memory retirement:** What minimum accepted-evidence/deduplication and
  maintenance command/result/attempt information remains necessary after completed,
  abandoned, or permanently unresolved work? Document genuine operational limits;
  unlimited unresolved work does not imply constant memory consumption.
- Application-wide unfinished-Session discovery/selection beyond trustworthy known
  participants, Session/application restoration, and unsupported recovery procedures
  remain deferred. Multiple unfinished Sessions may be reported only from existing
  trustworthy evidence; this does not establish a registry or restoration mechanism.

UTC write-time assignment is now accepted; no additional monthly-partition
configuration is introduced. Scientific/institutional retention remains
separate from technical deletion safety; safe permanent-archive deletion is manual.

### Blocks

* Decision 350, Decisions 353/355, and remaining Decision 354 work outside the bounded monthly implementation
* Remaining cross-month deletion independence, older/unidentified interrupted-target repair support and historical deletion-safety contracts
* Unavailable-evidence auditing conflict and remaining memory-retirement limits
* Application-wide discovery/restoration and unsupported recovery procedures

These questions do not block accepted known-Session journal recovery and must
not become Slice 27 or narrow Decisions 332-338 implementation requirements.
Q024-B's accepted service-specific execution boundaries do not authorize universal
or new automatic recovery, replay, retry, resumption, deletion, GUI implementation,
process supervision,
new Session states, or an additional recovery subsystem. Q022 retains deployment
configuration and discovery. Decisions 351-352 now accept startup reconciliation
and protected reservation handling without changing Decisions 287-294's node
authority. Ordinary failed-launch rollback is distinct from application restoration.
Q019 remains CLOSED in W050; the historical Slice 28 scope is unchanged.

Decision 300 accepts initialization cleanup confirmation before node release.
An unconfirmed cleanup protects the reservation. Decision 352 accepts independent
local-finalization/device-safety assessment and authorized Session-keyed release;
its supported startup reconciliation/reservation-protection integration is complete,
independently manually validated and independently re-audited PASS after correction
in W040. This does not implement automatic stale-reservation cleanup or application
restoration, and no automatic expiry, retry, leases, or new recovery service is
introduced.

---

## Q025: What low-level contracts implement scoped framework stop/kill and durable attempt evidence?

**Status:** RESOLVED architecturally by Decisions 313-321 and 323-326 - individual-service maintenance validated (W036); progressive two-phase coordinated shutdown validated and independently re-audited PASS (W037)

### Accepted boundaries

Decisions 304-312 settle principal operational service lifetime, Controller-owned
coordination, participant-owned actions, scope protection, durable stop-attempt
identity, and the exact `completed`, `blocked`, `failed` attempt vocabulary.
Kill is operator-authorized continuation of a blocked attempt; declining it ends
that attempt as failed. These are not open ownership or lifecycle questions.
Session end does not automatically terminate operational services, and stop/kill
must not initiate collection, verification, transfer, or export.

Decision 323 specifies the existing Evidence Archive's stable deployment-scoped
`framework/evidence/` partition for framework evidence with `session_id=None`.
Exact persistent-evidence, intake-audit, and compilation-summary preservation
does not require a Session Record or fabricated Session binding. This resolves
the concrete archive-location dependency; it does not resolve Q019 or Q024 or
by itself establish implementation or validation.

Decision 354 now explicitly supersedes only that shared framework layout with
permanent calendar-month partitions. Current code has bounded UTC write-month
implementation independently validated/reviewed and CLOSED in W071; historical W036-W040 results
remain shared-layout validation, not monthly validation. Safe historical deletion
is not implemented and Q025's resolved boundaries are unchanged.

### Resolved low-level contracts

Existing RuntimeParticipant identities, Session associations, distributed
command/result envelopes, issuer-configured bounded result windows, and command
correlation are reusable mechanisms. Stop-attempt identity, explicit kill
authorization, and correlation with the original blocked attempt are accepted
requirements requiring implementation integration, not reopened ownership or
protocol questions.

1. Scope: general shutdown is Controller-coordinated; individual administrative
   maintenance targets its service independently. Existing participant identity,
   resource ownership, and protection of unrelated shared scopes remain
   authoritative (Decisions 314 and 316). Decision 325 requires explicit
   Session-independent RuntimeParticipant scope, not SessionConfig participants.
   The initial local survey is informational, not an all-or-nothing gate;
   actual blockers are evaluated sequentially when each stop command is issued.
2. Closeout: services own explicit directional dependencies, readiness/blockers,
   cleanup, and forced actions. Active Session obligations block orderly stop;
   confirmed binding release is independent of service termination (Decisions
   313-314 and 316).
3. Outcomes: pre-stop blockers produce blocked; incomplete shutdown, failed or
   unconfirmed force, and declined kill produce failed. Confirmed orderly closeout
   or authorized forced termination produces completed, without asserting that
   unresolved cleanup succeeded (Decision 315).
   Decision 325 distinguishes each participant's outcome from the overall attempt:
   a blocked service pauses the sequence and requires separate kill authorization;
   declining force after shutdown begins ends the overall attempt as failed.
   Already stopped services remain stopped without automatic restart or rollback.
4. Evidence: framework-level evidence may lack Session identity using minimally
   extended existing RuntimeEvidenceMessage, Ingestor, and Evidence Archive
   contracts; Session evidence retains real Session identity. No fabricated
   Session or separate evidence system is allowed (Decision 318).
5. Preservation: services submit required evidence, Ingestor confirms durable
   preservation, StorageManager completes its writes, and Controller stops last.
   Authorized kill preserves whatever the initiator can confirm (Decisions 317
   and 319).
   Decision 326 resolves the coordinated cleanup-evidence handoff: StorageManager
   and Controller perform actual `prepare_stop` cleanup and archive its results
   while Ingestor remains operational. The final archival checkpoint distinguishes
   completed actions from outstanding retirement obligations. Later retirement
   confirmations remain existing command/results, not newly archived evidence.
   This contract is implemented and validated in W037. Prepared orderly retirement
   checks complete current persistent-evidence and all-intake-audit coverage through
   commitment, including after asynchronous callbacks; incomplete coverage prevents
   confirmed retirement. This does not resolve Q019 or Q024.

All five narrowed architecture questions are resolved. Decision 323's framework
partition and individual-service administrative stop/kill/cancel now have narrow
implementation paths using existing runtime messages, journals, compilation,
and exact preservation checks. W036 records successful manual software validation
and final independent audit PASS for individual-service maintenance, including
Decision 324 closeout ordering. W037 separately records successful manual validation
and independent re-audit PASS for coordinated shutdown and its complete Evidence
Archive preservation guard. W038 records completed startup/returning-service
integration under Decisions 327-331, independent manual software validation, and
final independent re-audit PASS after correction of the two initial P2 findings.
Phase 16 and M015 remain open.
Transport publication alone is not permanent persistence, and the framework
partition never requires a Session Record or fabricated Session binding.

### Boundaries

Q019 remains the separate Session-wide consumption/final Evidence Archive
coordination question. Q020, Q021, Q023, and Q024 remain open. Q017 stays resolved
by Decision 303; no completed Session is retroactively failed by later global
processing. Service supervision/configuration remain in Q022 and broader
configuration questions; restart recovery remains Q024. Accepted administrative
maintenance adds no permission infrastructure, remote OS process management,
framework-wide state machine, new Session state, automatic retry, or remote process
termination. W036 validates the narrow individual-service maintenance slice;
W035 remains limited to Session-binding release. W037 validates progressive
coordinated shutdown, not broader Phase 16 or M015 completion. Independent startup/returning-service
recognition does not resume interrupted Sessions, transfers, or messages.

---

The roadmap distinguishes accepted architecture from implemented milestones:

Phase 13 — Global StorageManager (Evidence)
Phase 14 — Global StorageManager (Finalized Scientific Data)
Phase 15 — Controller-owned Session Launch & Runtime Assembly (launch path and Decision 302 sequential reuse implemented; independent validation/audit and M015 closure pending)
Phase 16 — Operational Service Lifetime and Framework Stop/Kill (Decisions 304-366 accepted; Q025 resolved architecturally; narrow Session-binding release under Decisions 313/322 complete, manually software-validated and independently audited PASS in W035; individual-service maintenance complete, manually software-validated and independently audited PASS in W036; progressive two-phase coordinated shutdown complete, manually software-validated and independently re-audited PASS in W037; startup/return under Decisions 327-331 complete, independently manually software-validated and independently re-audited PASS after correction in W038; supported Q024-B cases under Decisions 339-348 complete with automated coverage, independent manual validation, and final independent re-audit PASS after correction in W039; supported Decisions 351-352 startup reconciliation/reservation protection complete, independently manually validated and independently re-audited PASS after correction in W040; bounded Decision 349/393 is CLOSED in W070B after independent ICC validation and source audit PASS; Decision 354's bounded monthly implementation is CLOSED in W071 after independent ICC validation/review PASS; Decision 350 and Decisions 353/355 remain unimplemented; Decision 361 receiving foundation and routing prerequisite complete with automated testing, independent manual validation, and final independent re-audit PASS after correction in W041; Decision 366's supported producer/marker prerequisite is complete with automated coverage, independent manual validation, and targeted independent re-audit PASS after correction in W042; bounded Stage A under Decision 362 is complete with automated testing, independent manual validation, and independent audit PASS in W043; bounded Decision 364 durable handoff is complete with automated testing, independent manual validation, and independent audit PASS (W044); bounded Stage B collection/Decision 363 evidence persistence is complete with independent manual validation and final targeted re-audit PASS after correction (W045); W046 explicit permanent closure is complete with independent manual validation and targeted independent re-audit PASS after correction; bounded Normal Stop integration is complete with independent validation and targeted re-audit PASS after correction (W047); Bounded Kill Session integration is complete in W048; eligible-Session selection is complete with independent validation and final audit PASS after correction (W049), and overall Q019 software integration validation is complete in W050; Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain open)
Phase 17 — Device Acceptance / Validation
Phase 18 — End-to-End Demo Architecture

Q022-A file-based installation configuration is accepted in Decisions 367-374 and
awaits implementation/verification. The broader Configuration Model remains future
work under Q008/Q022; its phase placement
is not reassigned by this Phase 16 decision synchronization.

Runtime artifact-transfer scheduling and monitoring remain future work under
Q021; they are not silently included in Slice 28 by the earlier roadmap label.
