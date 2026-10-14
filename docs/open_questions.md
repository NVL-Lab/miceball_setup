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

### Why this matters

Decisions 154-176 establish synchronization ownership and minimum plain-data
schemas while requiring drift, correction, mapping-update, timestamp-status,
and timing-quality evidence while preserving runtime timestamps.
SynchronizationManager owns runtime drift estimation and remapping decisions;
the mapping mathematics, uncertainty representation, detailed drift model, and
reconstruction estimators remain open.

### Questions

* Can drift vary during a session?
* What mathematics relate `local_time_anchor_s`, `session_time_anchor_s`, and `scale`?
* How should timestamp uncertainty be represented?
* What precision and units are required for each timing-evidence field?
* How are reconstructed drift estimates linked to the runtime mappings they audit?
* How is runtime drift-estimation evidence represented without exposing the SynchronizationManager algorithm as architecture?

### Blocks

* Future synchronization features
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
SessionConfig.local_storage_roots. External representation/provisioning remains
open; root authority is settled, not a new configuration-model requirement.

Deployment-local retrieval configuration and its initialization handoff are
tracked separately in Q022, as future work after Phase 14.

Decisions 281-301 settle Slice 28's ownership and ordering: AcquisitionNode owns
pre-Session inventory, Controller resolves selections/readiness/reservations,
and SessionConfig is the final accepted configuration. Reuse existing device
and product declarations without SessionLaunchIntent or product requiredness.
External deployment/configuration representation and propagation remain open;
these settled selection and launch semantics are not Q008 schema questions.

### Questions

* What external configuration file format should be used?
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
monotonic clock. Detailed
distributed synchronization transport, schemas, and failure behavior remain
future work.

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

**Status:** Open

Phase 11 defines ownership of synchronization evidence and active mappings, but intentionally does not define the mathematical synchronization model.

The following remain future architecture decisions:

- detailed SynchronizationObservation schema
- local-time sample reporting cadence
- drift estimation method
- synchronization mapping update criteria
- timing uncertainty representation
- mapping refinement strategy
- reconstruction timing estimators

The future synchronization design must preserve the accepted Phase 11 principles:

- SynchronizationManager remains the owner of Session Time.
- SynchronizationManager owns synchronization evidence creation and mapping lifecycle.
- AcquisitionNode reports local timing information and applies accepted mappings.
- Runtime Timing remains immutable.
- Any reconstructed or refined timing remains distinguishable from Runtime Timing.

This question does not block current Phase 11 implementation slices that only require mapping ownership and evidence preservation.


Q019: How is Session-wide evidence consumption coordinated before processing finalization?
**Status:** OPEN - high-level contracts accepted in Decisions 356-360 and low-level
contracts resolved/accepted in Decisions 361-365. Decision 361's receiving foundation
and routing prerequisite are complete with automated testing, independent manual
IPython validation, and final independent re-audit PASS after correction (W041).
Kill Session integration, eligible-Session selection, and overall integration
validation remain pending. Decision 362's bounded Stage A slice is complete
with automated testing, independent manual validation, and independent audit PASS
(W043); bounded Stage B collection/Decision 363 persistence is complete with
independent manual validation and final targeted independent re-audit PASS after
correction (W045); W046 explicit closure is complete with independent manual
validation and targeted re-audit PASS after correction. Decision 365's bounded
Normal Stop integration is complete with independent validation and targeted
re-audit PASS after correction (W047); W048 Kill has a developer implementation
awaiting independent validation and audit.
Decision 364's bounded
durable handoff is complete with automated testing, independent manual validation,
and independent audit PASS (W044).
Q019 is not complete.

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
Kill Session integration awaits independent validation/audit, not unresolved producer selection
or a new registry; bounded Normal Stop is complete in W047.

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
  developer implementation; independent validation and audit remain pending. This is not a new unresolved Experiment
  event-mapping question.
  Decisions 034/365 also permit Session transition to `aborted` when participant
  cleanup remains unconfirmed. `cleanup_occurred=True` records local Session
  cleanup, not confirmed cleanup of all participants. Participant cleanup, hardware
  safety, and resource-release obligations remain separately represented, with
  existing safety and authorized recovery protections mandatory. The Session
  lifecycle clarification is resolved; W048 independent validation and audit remain
  pending, without changing Normal Stop guarantees or closing Q019.
  Decision 364 now permits StorageManager to refresh a partial handoff from
  additional verified manifests obtained through authorized recovery, following
  existing Ingestor compilation rules and confirmed durability while preserving
  existing evidence. Only pre-Stage-B refresh is permitted: the first collection
  attempt, even if failed or incomplete, makes the handoff immutable. Historical
  evidence, collection outcomes, and permanent archive closure cannot be rewritten.
  This resolves the partial-handoff evolution question, not W048 implementation or
  validation; Normal Stop guarantees and broader open work remain unchanged.

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
  replacement or baseline confirmation. Q019 remains OPEN for
  Kill Session integration, eligible-Session selection, and overall
  integration validation.
- **Durable handoff and selection:** The bounded Decision 364 handoff slice is
  complete with automated testing, independent manual validation, and independent audit PASS (W044):
  explicit protected post-Stage-A compilation, separate durable JSON, known-Session
  readback after restart, and applicable binding-release protection. Missing
  finalization stays explicit; corrupt/conflicting contents are not implicitly
  repaired. Later eligible-Session selection and full closeout integration remain
  unimplemented; no new registry or restoration mechanism is introduced.
- **Closeout integration:** Decision 365's bounded Normal Stop confirmations are
  complete with independent validation and targeted re-audit PASS after correction
  (W047). Explicit partial Kill preservation now has a developer implementation
  awaiting independent validation and audit,
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

These are accepted low-level contracts awaiting implementation and verification,
not four unresolved architectural choices. Any inability to satisfy them returns
for architectural review; this task chooses no speculative broker configuration.

Blocks
Remaining Q019 Session closeout integration
Overall integration validation and later eligible-Session selection
Forced partial acquisition-evidence closeout integration

Q019 remains OPEN. Decisions 356-365 and clarification 366 settle the high-level
and low-level contracts above. W041-W046 complete only the receiving,
publication, bounded Stage A archival, durable handoff, and bounded Stage B
collection/evidence-persistence and explicit permanent closure slices; remaining implementation and overall
integration validation are pending.
The bounded W047 Normal Stop path is complete with independent manual validation
and targeted re-audit PASS after correction. Initial developer tests 19/19 and
manual checks 6/6 PASS preceded an initial audit FAIL with two P2 findings:
pre-marker cancellation permitting legacy completion, and late intake omitted
from the final record. Corrections passed 12/12 developer tests and 3/3 independent
checks; final targeted re-audit PASS found no remaining confirmed P0-P3 findings.
It composes W041-W044 prerequisites before
normal completion without automatically invoking Stage B or permanent closure.
Kill integration, eligible-Session selection, and overall integration validation
remain open; W047 closes only the bounded Normal Stop workflow, not Q019.
The original
Slice 25 exclusions remain historical; they do not prohibit the newly accepted
verified acknowledgment proof.
Do not implement that proof through assumptions, polling, sleeps, count registries,
or another transport. Q024, Q022, Phase 16, and M015 retain their open statuses;
no broader Q019 completion is claimed.


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

**Status:** OPEN / FUTURE - a future phase after Phase 14, not another Phase 14 slice

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
placement without another node ID in DeviceDeclaration. Participant registration,
discovery, adapter installation/configuration, address resolution, and deployment
file formats remain open here. Session launch ownership does not resolve them.

Decision 298 settles root authority: remote AcquisitionNodes use their own
deployment-defined local storage roots/configuration. Controller does not choose
those roots or artifact paths, and the current SessionConfig.local_storage_roots
override path is historical, not remote launch authority. This resolves ownership,
not the future deployment configuration file format or provisioning mechanism.
Manual independent-process startup is development infrastructure; intended
long-lived service deployment/supervision remains future work (Decision 295).
Decision 304 explicitly settles the Session-independent and GUI-independent
lifetime of the five principal operational services, without requiring one
process per service. Deployment automation, supervision, and configuration
mechanisms remain unresolved here. Decisions 313-321 settle maintenance,
independent startup/readiness, and service-owned Session-binding release without
choosing deployment formats, a discovery/registration system, or supervision.
Q025 is resolved architecturally. Session-binding release (W035) and individual-service
maintenance (W036) are complete and software-validated. Progressive two-phase
coordinated shutdown is also complete, manually software-validated, and
independently re-audited PASS (W037); independent startup/returning-service
integration under Decisions 327-331 is complete, independently manually
software-validated, and independently re-audited PASS after correction of the two
P2 readiness findings (W038). Configured dependencies
receive startup/return announcements directly; this does not settle deployment
provisioning, configuration formats, or discovery details or authorize a registry.

Decision 302 additionally settles retained adapter reuse without process or adapter
recreation: AcquisitionNode retains deployment configuration, but subsequent
Session-specific settings come from that Session's resolved SessionConfig and
must not be silently inherited. The generic return-to-DECLARED/readiness contract
is implemented with automated coverage; independent validation and audit remain
pending under M015. Deployment file formats and provisioning below
remain open; no new configuration model or lifecycle API is introduced.

### Questions

* How is deployment-local configuration created and maintained from repository templates?
* How are deployment participants and declared devices installed/registered, discovered if desired, and exposed to Controller without assuming automatic lab-wide discovery?
* What policy applies to duplicate RuntimeParticipant identities in deployment?
* How are node-owned local storage roots/configuration provisioned without Controller selecting remote filesystem paths?
* How is logical `acquisition_node_id` mapped to retrieval endpoint information?
* Where do SSH/SFTP host aliases, hostnames, usernames, key paths, and authentication references live, and how are they provisioned locally?
* How is local-only configuration loaded and supplied to StorageManager through startup, Controller, or Session initialization?
* How should existing readiness checks determine whether required retrieval configuration exists?
* How are machine-specific values kept out of committed files, ArtifactManifest, Ingestor handoffs, portable Session evidence, and Experiment configuration while honoring Decisions 076 and 247?
* How can this remain explicit and minimal without prematurely introducing a NetworkManager, dynamic discovery service, secret manager, database, transfer scheduler, or retry/replay system?

### Blocks

* Future deployment configuration and initialization architecture after Phase 14
* Future initialization/readiness validation of deployment-local retrieval configuration

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
separate from a completed Session's lifecycle; Q019 remains open.

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
final independent re-audit PASS after correction in W040; Decisions 349-350 and
353-355 remain unimplemented.
Remaining implementation and unresolved operational contracts keep Q024 OPEN.
Q024-B service-specific operator-authorized execution architecture
is accepted in Decisions 339-348; supported cases have automated implementation
coverage and are complete with independent manual validation and final independent
re-audit PASS after correction, documented in W039. Q024 remains OPEN.

### Why this matters

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
Q019, Q022, Phase 16, and M015 remain OPEN. No new validation was executed during
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
infrastructure. Broader Q024, Q019, Q022, Phase 16, and M015 remain OPEN.

### Newly resolved architecture and implementation status

The following ownership and behavioral questions are resolved architecturally in
Decisions 349-355. Supported Decisions 351-352 are complete, independently manually
validated and independently re-audited PASS after correction (W040); Decisions
349-350 and 353-355 remain unimplemented:

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
  staged archival confirmation. W041 validates only the receiving foundation;
  complete closeout implementation and verification remain pending. Applicable
  confirmations must be integrated with Decision 349's
  journal-retirement prerequisites. Existing local acceptance and current archive
  confirmation do not implement the accepted Session-wide guarantee; no journal
  retirement policy is resolved by this documentation synchronization.
- **Cross-month preservation and lookup:** Current Ingestor framework compilation
  and `framework_preservation_guard()` compare cumulative evidence/audit against one
  archive; StorageManager writes/reads that shared archive, and maintenance/Controller
  lookups require its records. How will exact coverage and authorization/outcome
  lookup remain valid across monthly partitions without rewriting closed archives
  or making safe-to-delete history an operational recovery dependency?
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

Calendar-timezone rules and additional monthly-partition configuration have not
been accepted and must not be invented. Scientific/institutional retention remains
separate from technical deletion safety; safe permanent-archive deletion is manual.

### Blocks

* Implementation of accepted Decisions 349-350 and 353-355, including Q019-dependent journal retirement
* Cross-month preservation/lookup and historical deletion-safety contracts
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
Q019 remains separately
OPEN and Slice 28 does not invent a Session-wide evidence-drain protocol.

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
permanent calendar-month partitions. Current code and W036-W040 validation still
use the shared layout; the newly accepted monthly/deletion-safety contracts are
not implemented and do not reopen Q025's resolved maintenance/shutdown boundaries.

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
Phase 16 — Operational Service Lifetime and Framework Stop/Kill (Decisions 304-366 accepted; Q025 resolved architecturally; narrow Session-binding release under Decisions 313/322 complete, manually software-validated and independently audited PASS in W035; individual-service maintenance complete, manually software-validated and independently audited PASS in W036; progressive two-phase coordinated shutdown complete, manually software-validated and independently re-audited PASS in W037; startup/return under Decisions 327-331 complete, independently manually software-validated and independently re-audited PASS after correction in W038; supported Q024-B cases under Decisions 339-348 complete with automated coverage, independent manual validation, and final independent re-audit PASS after correction in W039; supported Decisions 351-352 startup reconciliation/reservation protection complete, independently manually validated and independently re-audited PASS after correction in W040; Decisions 349-350 and 353-355 remain unimplemented; Decision 361 receiving foundation and routing prerequisite complete with automated testing, independent manual validation, and final independent re-audit PASS after correction in W041; Decision 366's supported producer/marker prerequisite is complete with automated coverage, independent manual validation, and targeted independent re-audit PASS after correction in W042; bounded Stage A under Decision 362 is complete with automated testing, independent manual validation, and independent audit PASS in W043; bounded Decision 364 durable handoff is complete with automated testing, independent manual validation, and independent audit PASS (W044); bounded Stage B collection/Decision 363 evidence persistence is complete with independent manual validation and final targeted re-audit PASS after correction (W045); W046 explicit permanent closure is complete with independent manual validation and targeted independent re-audit PASS after correction; bounded Normal Stop integration is complete with independent validation and targeted re-audit PASS after correction (W047); Kill Session integration and eligible-Session selection remain unimplemented, and overall Q019 integration validation remains pending; Q019, Q024, Q022, Phase 16, and M015 remain open)
Phase 17 — Device Acceptance / Validation
Phase 18 — End-to-End Demo Architecture

The Configuration Model remains future work under Q008/Q022; its phase placement
is not reassigned by this Phase 16 decision synchronization.

Runtime artifact-transfer scheduling and monitoring remain future work under
Q021; they are not silently included in Slice 28 by the earlier roadmap label.
