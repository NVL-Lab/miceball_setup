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

Decisions 178-218 now separate AcquisitionNode-local scientific persistence and local completion from future global Session Record completion. The future global StorageManager will consume finalized `ArtifactManifest`, `LocalStorageCompletionSummary`, and local storage evidence without taking ownership of original local records. Its implementation and the exact global integration schema remain unresolved.

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
* When and how are reconnect, retry, or replay permitted?
* May newer durable messages publish after an earlier publication failure?
* How are successful recovery and permanently unpublished messages recorded?
* If future local preservation is accepted, what ownership and storage limits apply?

### Current direction

Do not infer recovery behavior from JetStream durability. Publication recovery remains a separate future architecture decision.

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
concurrent sharing, multi-Session scheduling, or normal service binding lifetimes.

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
* What are normal end-of-Session binding lifetimes for Ingestor and SynchronizationManager beyond accepted initialization/rollback?
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

## Q017: What Session lifecycle consequence follows artifact collection or verification failure?

**Status:** OPEN / FUTURE - high-level architecture

### Why this matters

Decisions 245-260 settle the Slice 23 contract: StorageManager pulls one file per
manifest using SSH/SFTP and deployment-local endpoint configuration, writes a
deterministic global copy through a temporary destination, and reports independent
per-artifact and aggregate outcomes. Local ownership remains unchanged. This
architecture has software validation recorded in W032; real Jetson/SSH-SFTP
deployment validation remains pending (M011 open).

Slice 23 reports collection outcomes but does not decide whether failure fails
the Session, leaves it completed, produces a warning, requires operator action,
or has another lifecycle consequence. That policy requires an explicit decision
in a future high-level architecture phase, not another Slice 23 requirement.

Decisions 261-270 accept Slice 24 light verification and separate retrieval,
per-artifact verification, and aggregate reporting, implemented and software-validated
with M012 complete (W032). They do not resolve this question: copied_unverified,
structurally_invalid, verification_failed, and
retrieval failure do not themselves authorize Session lifecycle changes.

Decisions 271-275 accept persistent post-session collection evidence and
distinguish Session acquisition end from Session processing finalization.
Collection failure must not retroactively change acquisition success, Experiment
lifecycle, or local finalization. Further operational/lifecycle consequences
remain open here; publication/consumption coordination before archive closure
is tracked separately in Q019. Slice 25 is complete (M013, W033) after independent
manual software validation and corrected independent re-audit PASS.

Acquisition outcome, Experiment lifecycle outcome, local artifact finalization,
global artifact collection, and Session lifecycle/final completion are distinct.
Local completion is independent of global Session Record completion. Transfer
creates additional managed copies without transferring ownership of the original
local scientific record; post-session collection is not acquisition.

### Questions

* Does failed post-session collection prevent successful Session completion?
* Can a Session remain completed while global collection is failed, partial, or pending?
* Should collection or verification failure, or copied_unverified status, require a warning or operator action while preserving completed acquisition status?
* Should consequences depend on whether an artifact is required or optional, or whether it finalized locally?
* Should consequences differ for a missing source file, unreachable node, missing retrieval configuration, permission denial, failed copy, or failed verification?
* Which, if any, of Session lifecycle, Experiment lifecycle, local artifact status, and global collection status should change?

Decisions 240-244 settle ownership: Controller initiates post-session collection,
Ingestor compiles the manifest handoff, and StorageManager owns retrieval and
global storage. Slice 22 does not implement the Artifact Plane transfer backend;
Slice 23 implements that backend; real Jetson/SSH-SFTP deployment validation
remains pending (M011 open), separate from W032's software validation.

Related questions are kept separate: deployment initialization in Q022, source
existence/reachability in Q023, extended global-copy verification and retention in
Q020, extended transfer progress evidence, resume, and retry in Q021, and
Session-wide evidence consumption before final archive closure in Q019.

### Blocks

* Future high-level collection-consequence policy
* Future Session completion policy for failed or partial global collection

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
**Status:** OPEN / FUTURE - Session processing/finalization architecture

Why this matters

Phase 12 established LocalStorageManager ownership of local scientific persistence. Decisions 219-231 establish that Ingestor compiles persistent runtime evidence and StorageManager writes the Evidence Archive and final Session Record. The framework still needs to define how the future global StorageManager assembles finalized local discovery information and scientific artifacts without taking ownership of the original local scientific records.

Decisions 271-275 settle the narrow global collection evidence model: StorageManager
produces one compiled persistent record per completed pass through the existing
durable evidence boundary. Scientific acquisition end is not Session processing
finalization, and the Evidence Archive must not be treated as finally complete
before legitimate post-session evidence has an opportunity to be produced.
The accepted model is implemented through explicit awaited publication before
finalization; it does not resolve the broader
Session-wide consumption guarantee below.

Questions
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
Which finalized local evidence must every LocalStorageManager provide?
How does Controller know that all durably published evidence associated with a
Session has actually been consumed/accepted by Ingestor before compiling and
finally closing the Evidence Archive?
What Session-wide publication/consumption ordering, JetStream consumer acknowledgment
state, evidence draining, final shutdown guarantees, and Controller coordination
establish that condition for all persistent runtime evidence?
How is durable transport acceptance distinguished from Ingestor acceptance and
final persistent archive completion?
W033's manual Scenario 4 deliberately accepted publication without delivery:
Ingestor retained zero collection records and finalization produced an archive
without that undelivered evidence. This demonstrates the open consumption gap,
not a Slice 25 implementation failure. The corrected active-operation guard
prevents overtaking publication, but does not resolve post-publication consumption.
How are multiple LocalStorageManagers reconciled into one global Session view?
How are missing LocalStorageManagers or incomplete evidence represented?
What evidence remains local even after global collection?
Blocks
Global evidence integration beyond the v1 Evidence Archive
Global evidence persistence
Future global integration beyond the accepted handoff; no Slice 22 lifecycle change
Future Session-wide processing/finalization and evidence-drain guarantees

This remains OPEN and belongs to a future Session processing/finalization
architecture phase. It is not StorageManager-specific. Slice 25 must not invent
consumer-ACK waiting, polling, sleeps, arbitrary delays, evidence-count assumptions,
or new broker protocols. If minimum Slice 25 ordering/wiring requires deciding
this protocol, implementation must stop and report the dependency.


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
Slice 23 retrieval success, require nonempty scientific records, redesign manifests, or resolve Session
lifecycle policy (Q017). Source reachability remains distinct under Q023.
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
remain separate in Q020; Session consequences remain in Q017.

### Questions

* Should future source-existence checks occur before acquisition, after local finalization, during handoff compilation, at retrieval, or at multiple stages?
* Who owns each check, distinguishing LocalStorageManager local-file knowledge, Ingestor evidence intake, and StorageManager remote reachability?
* How should local existence differ from remote reachability, and when, if ever, should existence checks also inspect size or metadata?
* How should a missing local artifact, manifest with absent file, unreachable node, missing endpoint, permission denial, or invalid path be represented?
* Should verification failure affect local artifact outcome or global collection only? Any Session lifecycle consequence remains the high-level question in Q017.
* How should future checks preserve the independence of local completion and global collection?
* How can checks avoid deep verification or large-file reads solely to answer existence, and avoid embedding network-reachability assumptions in portable manifests or handoffs?

### Blocks

* Future source-verification and readiness-time checking architecture
* Future source-verification failure representation, without changing Slice 23

## Q024: What is the application restart and recovery-journal lifecycle?

**Status:** OPEN / FUTURE - outside Slice 27

### Why this matters

Decisions 276-280 accept Ingestor crash recovery for an already-known Session,
not application-wide recovery or a journal deletion policy. Q020's scientific
artifact retention is distinct from temporary Ingestor recovery-state lifecycle;
Q019 still owns evidence-consumption/finalization coordination. Q022 retains
deployment-local configuration responsibilities.

### Questions

* When is a recovery journal safe to delete, and which existing owner performs deletion?
* How are journals retained across program restart and handled when Sessions are abandoned?
* What cleanup is permitted after successful Session processing finalization without losing required recovery state?
* How does a restarted application discover and select unfinished Sessions, rather than starting Ingestor with an already-known Session?
* How are multiple unfinished Sessions and complete Controller/application lifecycle restoration handled?
* How does future recovery orchestration relate to Q019's separate evidence-consumption/finalization guarantee?
* How does Controller crash recovery find and release stale AcquisitionNode reservations without changing node-owned reservation authority?
* What future leases, timeouts, or heartbeats, if any, are accepted beyond Slice 28's atomic Session-keyed reservation without automatic expiry?

### Blocks

* Future recovery-journal cleanup/retention and abandoned-journal handling
* Application-wide restart/discovery/resumption and lifecycle restoration

These questions do not block accepted known-Session journal recovery and must
not become Slice 27 implementation requirements. Decisions 287-294 also defer
Controller crash recovery and stale-reservation handling; ordinary failed-launch
rollback is accepted, not application restart recovery. Q019 remains separately
OPEN and Slice 28 does not invent a Session-wide evidence-drain protocol.

Decision 300 accepts initialization cleanup confirmation before node release.
An unconfirmed cleanup protects the reservation; how future crash/recovery or
stale-reservation handling resolves that condition remains deferred here, without
automatic expiry, retry, leases, or a new recovery service in Slice 28.

---

I also recommend slightly adjusting the roadmap now:

Phase 13 — Global StorageManager (Evidence)
Phase 14 — Global StorageManager (Finalized Scientific Data)
Phase 15 — Controller-owned Session Launch & Runtime Assembly (launch path and Decision 302 sequential reuse implemented; independent validation/audit and M015 closure pending)
Phase 16 — Configuration Model
Phase 17 — Device Acceptance / Validation
Phase 18 — End-to-End Demo Architecture

Runtime artifact-transfer scheduling and monitoring remain future work under
Q021; they are not silently included in Slice 28 by the earlier roadmap label.
