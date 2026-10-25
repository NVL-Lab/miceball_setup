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

**Accepted GUI/application direction:** Decisions 397-399 require per-animal
Session identity, reusable editable templates, and preservation of actual executed
configuration independently of its template. Decisions 409-411 additionally
settle editable application catalog ownership, historical Session metadata,
lab/personal template editing rules and immutable historical configuration.
Decision 424 records the accepted Session metadata and launch-time durability
clarification below. Decision 427 settles protocol name association, template
defaults and capability matching without a snapshot requirement. Decision 425
records the completed bounded implementation
and independent audit PASS at `5da9b35`. Q008 remains OPEN pending deployment
validation, closure and remaining configuration-model scope.

The application catalog contains experimenters, projects, project-local animals
and templates. A project has one primary experimenter, but records the actual
Session experimenter separately when different. Cross-project animal copies are
independent. Selected context enters authoritative Session history at creation;
later catalog edits cannot change it. GUI catalog ownership does not transfer
scientific-record ownership to GUI or Controller.

Lab templates are shared immutable references; personal templates are owner-
editable and overwritable. Copies of another experimenter's configuration are
independent by default. Working edits may be saved as new personal templates,
overwrite an owned personal template, or remain unsaved before or after an
Experiment. Templates may cover Sessions or selected Experiment types; some
Experiments need none. Reusable templates, working configuration, accepted
execution configuration and immutable history are distinct. Different Experiments
may use different configurations; whole-Session template reconstruction is not
required. No project-sharing or permissions infrastructure is authorized.

### Accepted protocol, capability and input boundaries (Decision 427)

Experimenters create, edit, reorder, copy and save protocols using application
operations via the existing Setup tab. Ordinary preparation selects a protocol
and adjusts permitted optional steps/capabilities. Scientific coherence belongs
to the experimenter; no generic protocol engine/dependency validator is required.
Session templates supply reusable defaults such as protocol selection, optional
functionality, Session settings and preferred devices, not execution authority.

The owner explicitly supersedes the earlier fixed-protocol-snapshot requirement.
Retain the selected protocol name in immutable accepted Session configuration;
do not copy complete protocol definitions into every Session or interpret
`protocol_plan` as requiring them. Protocol stability during a project is expected,
not enforced. No protocol snapshot, version-management system or new template service is
required. Decisions 291/424 still govern accepted-value immutability, readback and
durable launch confirmation; actual Session/Experiment configurations and execution
evidence preserve what was configured/performed without new provenance obligations.

Use installation-time `DeviceDeclaration.declared_capabilities` and exact matching,
not inferred device types. A device may supply several capabilities; several
devices may jointly satisfy step requirements, respecting distinct-device
requirements. Reuse devices across sequential steps; hardware-free steps need no
capabilities. No GUI capability catalog, automatic allocation or scheduler.
Actual Session-selected identities are fixed; any replacement requires a new
Session. Node reservations and Experiment participation remain distinct.

Required-device readiness is checked before each Experiment. An unavailable
device blocks dependent Experiments, not unrelated ones, without necessarily
terminating the Session or bypassing existing health/safety consequences. Decision
427 Slice 1 implements explicit participation through preparation, activation,
collection, expiry and finalization, correcting the all-adapter/all-node mismatch.
Independent validation and audit remain pending; this does not close Q008.

Decision 428 resolves the zero-device admission boundary: an Experiment acquires
scientific data using at least one participating data-acquisition device.
Hardware-free protocol steps remain permitted as Analysis, Validation or operator
interaction, not zero-device Experiments. Analysis processes existing scientific
data; Validation and operator interaction remain distinct operations under their
existing contracts. Zero recorded outputs as an execution outcome do not mean
zero configured participants. Existing autonomous AcquisitionNode deadline
ownership is unchanged; participation/admission enforcement remains pending.

Supported recorded inputs may come from the current Session, another Session or
another project. Processing existing data alone is Analysis, not an Experiment,
under Decision 428's qualification of Decision 427. Scientific
suitability belongs to the experimenter, not GUI. Existing access, identity,
provenance and historical integrity remain; there is no universal input validator.
The general recorded-input execution contract remains missing and is not invented
here. Protocol/template authoring and matching implementation also remain pending.
These settled boundaries do not close Q008 or repeat Decision 424 implementation.

### Accepted Session metadata and launch boundary (Decision 424)

Templates prefill editable fields, and experimenters may change them before
submission. Only final accepted values matter; no template identity, provenance
or comparison with defaults is required. Controller accepts Session-level
metadata and configuration at launch; those values remain fixed throughout the
Session. Subsequent GUI catalog edits cannot change historical Session records.
Experiment-specific configuration remains separate and may be prepared during
the active Session within existing constraints and validation contracts.

Successful launch requires Controller to obtain authoritative confirmation that
the complete accepted Session metadata and configuration have been durably
preserved through the existing Ingestor/StorageManager architecture. A Controller
crash after launch success must not erase them. Failed or uncertain preservation
does not authorize successful launch reporting. This qualifies Decision 228's
historical initial-record timing, without replacing Decisions 226-229's record,
archive or final-preservation responsibilities.

An initial-record confirmation establishes neither scientific finalization,
Stage A or terminal preservation, collection nor release. Decision 420's
failed-launch resource cleanup and Decision 342's authorized persistent-write
recovery remain unchanged. No failed-Session reconstruction, metadata database,
automatic recovery or additional failed-launch record repair/deletion policy is
introduced.

**Bounded implementation and independent audit complete; deployment validation pending:** Existing
`SessionConfig.session_parameters` and configuration transfer are reused. Session
now retains fixed accepted values with detached readback, the external interface
adds `read_session_configuration` for a matching bound Session, and launch waits
for exact durable initial Session Record confirmation from the existing paired
Ingestor/StorageManager owner. Initial preservation is not Stage A or terminal
preservation. Failure/cancellation uses existing cleanup; uncertain writes retain
Decision 342 recovery requirements, without automatic failed-Session recovery.
The accepted ICC evidence records separate independent Codex audit PASS with no
confirmed P0-P3 findings. This is not deployment validation or Q008 closure. Do
not restart the completed work. See [implementation interfaces](code_map.md#q008-session-metadata-decision-424-implemented-audit-pass-deployment-validation-pending).
Detailed catalog/template representation beyond this accepted boundary remains
within Q008; GUI takeover and broader state/result delivery remain under Q029/Q030.

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
* What broader default declaration/application policy is needed beyond Decision
  427's settled Session-template defaults and Decision 424's accepted-value boundary?
* How are accepted configuration values propagated to runtime owners?
* Which concrete capability identifiers/representations implement Decision 427's
  exact matching, collective capability coverage and distinct-device requirements?
  Installation declarations and no GUI capability catalog are already settled.
* Which concrete catalog identities and metadata fields are represented and
  transferred within Decision 424's accepted ownership and preservation contract?
* How are lab/personal templates persisted and transferred under their accepted
  editing rules? Decision 424 requires no retained template identity, provenance
  or default comparison in accepted execution/history.
* Which detailed settings representations implement Session-template defaults
  versus separate Experiment configuration under Decisions 424/427?
* How is accepted configuration propagated to the relevant runtime owners?

Remaining low-level metadata/configuration contracts require accepted design. They do not
reopen accepted installation settings or Session/device configuration boundaries.

### Blocks

* API design
* Session manifest structure
* Device schema structure


---

## Q026: What is the lightweight Analysis execution contract?

**Status:** OPEN - Decisions 401, 403 and 425 settle ownership, interruption and
admission requirements; implementation and detailed invocation remain outstanding.

Analysis is Session-scoped with a unique `analysis_id`, distinct from Experiment
and Validation. It must not inherit full Experiment lifecycle/readiness/Stop/Kill
machinery merely to produce products. Controller authorization and local execution
ownership are accepted. Decision 425 settles the former Session-closeout question:
Normal Session Stop cancels active Analysis, discards incomplete results and
confirms cleanup before closeout. It stops Validation with cleanup, and stops an
active Experiment under existing acquired-data preservation. Kill is unchanged.
Only one Analysis may be active per Session, and cleanup must finish before
readmission. Analysis cannot interfere with acquisition/closed-loop work;
Validation cannot activate a device in incompatible work. Compatible use may be
permitted under existing ownership/isolation guarantees. No separate lifecycle or
cleanup authority is introduced.

Validation is an in-Session selected-device function check acquiring into memory,
not an Experiment or required persistent test recording. It supports manual Stop,
a Setup-configurable duration limit and applicable preview, preserving installation
and reservation ownership. Applicable operational evidence remains required.

Remaining technical work includes:

- How does an existing AcquisitionNode invoke installed Analysis capabilities?
- What minimum request, outcome, and failure evidence is required?
- How do existing Controller/node commands implement accepted interruption,
  cleanup and compatible-resource admission without competing ownership?
- How does execution stay simpler than Experiment execution?
- What concrete installed-software interfaces support Suite2p or CaBMI?

Reuse Controller-authorized NATS and existing node execution/persistence owners.
Concrete invocation/schema and installed-software integration remain implementation
design work; no general scheduler, job platform or recovery subsystem is authorized.

## Q027: How do Analysis products use existing scientific persistence and collection?

**Status:** OPEN - Decisions 402 and 425 settle common ownership, output provenance
and absence of required result timing; compatible implementation remains pending.

The application configures expected outputs. Reuse `analysis_id`, artifact
identities/manifests and existing LocalStorageManager/Ingestor/StorageManager
preservation/collection. Results identify actual input data and Analysis parameters.
They require no acquisition/execution timestamps or fabricated Experiment identity
or timing fields. Existing acquisition-artifact timing requirements are unchanged.
Preserve completed valid results even when not selected; discard incomplete
failed/cancelled temporary outputs without altering inputs or earlier valid results.

- How do Experiment-specific stream creation, declarations and
  ArtifactManifests accommodate `analysis_id` without a fabricated `experiment_id`?
- How are calculation parameters, source-product identities, and outputs represented?
- How do Analysis products participate in existing artifact collection without
  another scientific persistence system?

Technical schema representation may be chosen during implementation under Decision
425; no particular new field or storage mechanism is mandated. Preserve Decisions
185-186/191 ownership
and immutability, existing artifact-plane responsibilities, and scientific versus
operational evidence separation. Q002 retains broader Session Record evolution.

## Q028: How are scientific result acceptance and dependency provenance represented?

**Status:** OPEN - Decisions 400 and 425 settle traceability, valid-result retention,
input/parameter provenance and invalid temporary-output disposal; representation
and implementation remain outstanding.

Successful Analysis execution is distinct from experimenter acceptance/selection.
Preserve completed valid unselected results; failures/cancellations produce no
accepted result and can be rerun with the same inputs and different parameters
after cleanup. This is not permission to discard partial Experiment recordings.

- How are successful Analysis execution and experimenter acceptance represented separately?
- How are selected results referenced by later Analyses or Experiments?
- What is persisted about repeated attempts, superseded selections, and actual inputs?
- Where is the boundary between application-owned dependency interpretation and
  framework-preserved provenance?

Concrete input/output structures, selected-result identifiers, and application
dependency/invalidation representations remain proposals. Later selections cannot
rewrite earlier products or recorded inputs of completed operations.
Decision 427 settles input scope: supported recordings may originate in this
Session, another Session or another project. Scientific suitability remains the
experimenter's responsibility, not a GUI validator. Existing identity/access and
provenance apply; the missing general recorded-input execution contract is an
implementation gap, not authority to reopen historical Sessions or alter evidence.

## Q029: What contracts deliver authorized scientific results to the GUI?

**Status:** OPEN - Decisions 404, 412-413 and 425 settle command/result direction,
selected NATS visualization, browser control identity, takeover and authoritative
reconnection requirements; detailed interfaces and implementation remain pending.
Decision 422 resolves the initial G5 external lifecycle boundary. Following launch-boundary validation,
the authorized bounded extension implements Session start, Experiment start/stop
and expiry readback, Normal Stop, saved collection and release through the same
Controller. Independent deployment validation and separate audit remain pending;
no CLI or combined orchestration command is added. See
[code map](code_map.md#decision-422-external-controller-lifecycle-implementation-independent-validation-pending).

The initial collection-before-release blocker was reproduced as an overly broad
Ingestor archive/intake comparison. The bounded correction applies existing
origin-scoped acquisition coverage and exact audit equality to release and
maintenance, preserving StorageManager confirmation and other release guards.
Acquisition-only archives without provenance retain exact whole-archive equality.
Focused tests cover both operation orders and fail-closed damaged/interrupted
preservation. Independent validation and audit of this correction remain pending;
no lifecycle ordering or recovery policy change is introduced.

Decision 422 accepts Controller-targeted pre-Session launch requests through a
minimal external envelope using existing Controller identity and NATS routing,
without distorting participant runtime commands. The running Controller remains
the sole lifecycle authority and delegates to existing lifecycle methods.
Client-generated request IDs prevent duplicate execution during that Controller
service lifetime: identical requests return the recorded result or pending
status; conflicting parameters are rejected. Timeout is not failure or
cancellation. No persistent request journal or cross-restart outcome guarantee
is required, and uncertain operations must not be automatically replayed after
Controller restart.

One designated G5 testing client uses minimum existing access restrictions; a
thin CLI and the future GUI share the reusable external interface, not separate
lifecycle implementations. The historical launch-only foundation and extension
do not implement GUI takeover or broad state/result readback. Decision 425 now
settles the browser-control direction, not broader authentication or multi-Controller
coordination. G5 remains incomplete.

GUI connectivity loss cannot establish operation success/failure or trigger
automatic repetition. Reopening retrieves authoritative Session/operation state;
backend restart must permit reconnection without operational service restarts.
One GUI connection controls at a time; others may observe. A new connection offers
Take Over or View Only, and takeover makes the previous controller read-only
without its cooperation. Distinct browser identities pass through the shared
Python backend's existing authorized NATS client. Controller owns grants, observer
permissions and enforcement; backend prevents browser identity impersonation.
No per-browser NATS credentials/clients or general authentication infrastructure
are required. Exact identity mechanism and takeover ordering are implementation
details subject to existing correlation, Session binding, broker authorization
and deduplication. Operations continue during disconnect/takeover; reconnect alone
cannot restore superseded authority. Independent deployments remain independent.

Reconnect reads authoritative accepted configuration, lifecycle/operation state,
control ownership, relevant device/service status and unacknowledged notifications.
Decision 424 configuration readback/durability is implemented and audited PASS;
reuse it while extending other bounded state reads, without replaying operations.

- How are Controller-authorized requests correlated with direct AcquisitionNode-to-GUI results?
- How are intended recipients identified and authorized?
- What happens when the GUI disconnects before receiving a result?
- Which existing NATS contracts can be reused, and what limited extensions are needed?
- How is current authoritative state retrieved after browser/backend recovery?
- How are accepted distinct browser identities and Controller grants implemented
  through the shared backend without impersonation or stale control?

Decision 425 selects AcquisitionNode -> NATS -> backend -> browser visualization;
Controller coordinates/authorizes, not payload relay, and Ingestor is not a relay.
Backend forwards without scientific calculations. Only selected streams transmit:
initially one image and up to two scientific streams (multiple traces may share
one plot/stream), targeting about 1-2 fps and 5-10 scientific updates/s as applicable.
These are initial targets, not guarantees/permanent limits. Optional traffic and
buffering are bounded; degrade/drop visualization without compromising acquisition,
storage, synchronization or closed-loop work. No additional transport is authorized.
Concrete schemas, recipient authorization, buffering/backpressure and readback
interfaces remain implementation work; large artifact transfer is not visualization.

## Q030: What GUI presentation and deployment design implements the accepted functional areas?

**Status:** OPEN - Decision 425 settles web/Python deployment and six permanent
tabs, supplementing Decisions 396-405 and 409-418. Decision 426 settles repository
placement and separate packaging under top-level `gui/`. GUI implementation and
remaining library/widget choices are outstanding; these accepted choices are not
reopened.

The UI must distinguish immutable lab references, editable personal templates,
working edits and immutable execution history, and offer Take Over or View Only.
Other browsers may observe; simultaneous control is not permitted. The GUI is
not the sole holder of execution history/provenance. A separate Python backend
uses external NATS even when hosted by default on the Controller computer.
The browser UI operates on the laboratory network without cloud dependence;
GUI implementation resides in this repository's separately packaged top-level
`gui/` project and remains outside the existing `lab-sync-acquisition` distribution.
Q008 tracks configuration, Q029 communication/control; web frameworks/libraries
remain implementation choices.

Six permanent tabs are Setup, Session, Parameters, Experiment, Analysis and
Services. Accepted interactions include application protocol checklist/selected-step
controls, read-only accepted Setup after launch, participant-specific Parameters
read-only during execution, navigation without interruption, and final Experiment
results remaining visible until the next Experiment. Analysis is application-specific;
no mandatory historical scientific browser or core workflow engine is introduced.
Decision 427 adds Setup-accessible creation/editing/reordering/copying/saving of
application protocols, name-only Session association and reusable template defaults.
This accepted editor direction is not implemented by presentation placeholders;
no protocol snapshot/versioning or automatic scientific dependency validator is
required. Functional implementation remains under the normal ICC workflow.

Decisions 414-418 now require a permanently accessible Services tab, automatic
status refresh (configurable default 10 seconds), trust-based administrator mode,
inspectable obligations and persistent operational warnings/history. Administrator
mode hides administrative controls from ordinary experimenter mode but is not a
security boundary or operation authorization. Existing normal scientific controls
remain available; service maintenance is distinct from Session Kill. Detailed
control details and confirmation presentation remain implementation work. Decision
425 fixes the bottom-left unacknowledged warning/error indicator and operator
acknowledgment, not condition-resolution-based removal. See Q031-Q033 for remaining
technical work and the deferred non-initial Experiment Kill scope; no GUI feature
is implemented or validated by this documentation.

Detailed Services presentation, status-refresh mechanisms, maintenance interaction,
internal frontend/backend packaging details, frameworks and widgets require
implementation design within the accepted web/Python/six-tab and Decision 426
project boundary. See
[GUI design notes](gui_design_notes.md) for accepted requirements versus unapproved
presentation proposals. Existing readiness, service lifecycle, and
shutdown contracts remain authoritative; no GUI implementation is claimed.

General historical Analysis, broad online processing, inter-node scientific
streaming, and a generic workflow engine remain outside the initial accepted scope.

---

## Q031: How is GUI service-status freshness established?

**Status:** OPEN - Decisions 414 and 425 accept refresh/freshness and offline
inventory visibility; detailed status/readback implementation remains pending.

Installed membership remains visible even offline, using node-owned declarations
without a GUI registry. Controller confirms launch readiness independently;
missing communication means unknown availability, not proven hardware failure.
Controller reserves whole nodes; device selection/Experiment participation does
not authorize device-level cross-Session reservation. See Decision 425.

- Which existing readiness queries and announcements supply each configured
  service's current or last-known status and confirmation timestamp?
- What freshness, timeout and invalid-response rules distinguish confirmed
  availability, stale status, unknown availability and confirmed problems?
- How do configurable periodic refresh (default 10 seconds) and prompt incoming
  updates reconcile without stale results replacing newer authoritative reports?

Preserve Decisions 284/328. Announcements alone do not establish proactive
disappearance detection. No framework heartbeat, registry, monitoring service or
guaranteed detection latency is selected. Q030 retains presentation choices.

## Q032: How are GUI operational warnings delivered, associated and retrieved?

**Status:** OPEN - Decision 425 replaces automatic notification-resolution behavior
with operator acknowledgment, qualifying Decisions 417-418. Implementation and
complete notification/history readback interfaces remain pending.

Both warnings and errors contain severity, source, description and occurrence
timestamp. They remain visible until acknowledged. Controller owns notification
and acknowledgment state across reconnect; acknowledgment removes a notification
from the bottom-left unacknowledged indicator, not historical Services evidence.
Acknowledgment establishes neither condition resolution, service recovery,
historical deletion nor permission to resume unsafe work. Existing health,
readiness, safety and operational restrictions remain authoritative. Do not build
an automatic resolution subsystem or a GUI warning database.

- How are health/readiness/operational evidence and decisions correlated to the
  affected Session/Experiment, including historical and resolved conditions?
- How are notifications and authoritative acknowledgments delivered/reconciled
  after disconnect, retry or takeover without duplicate scientific actions?
- Which existing authoritative persistent records can be queried for complete
  Session-associated warning/error history, and what retrieval contract is missing?
- How are acknowledgment and historical readback implemented using existing
  Controller/service evidence and persistence, without discharging obligations?

GUI cannot classify scientific lifecycle failure independently or terminate
operations. Persistent evidence is not assumed to be an implemented queryable
warning-history API. No GUI scientific log, duplicate archive or general
event-history subsystem is authorized. Q029 retains transport/authority details;
Q030 retains presentation and Q024 service-owned recovery work.

## Q033: Is independent Experiment Kill required, and what would it mean?

**Status:** OPEN / deferred beyond initial GUI scope. Decision 425 resolves the
initial requirement: independent Experiment Kill is not required. This is not
authorization for a new command, nor implementation or milestone closure.

Decision 415 preserves existing Session Kill under Decisions 360/365 and ordinary
Experiment Stop, which preserves available data and allows another Experiment
within the Session; it does not establish independent Experiment Kill. Any future
requirement beyond the accepted initial scope, its distinction from Session Kill,
command authority,
authorization, lifecycle consequence, scientific finalization and cleanup behavior
require explicit accepted architecture. Do not implement or infer those semantics
from GUI controls or service-level Kill.

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

**Status:** OPEN. Decision 423 resolves automatic transport reconnection, not the
remaining unpublished-message recovery scope. Its bounded implementation arms
SDK reconnection after initial handshake and makes intentional closure stop it;
independent validation and audit remain pending. No publication-replay or lifecycle
recovery policy is added.

### Why this matters

Decision 143 keeps durable-message ownership with the producer until successful
JetStream publication. Decisions 124 and 142 require communication-failure
evidence. Decision 423 now resolves their deferred transport-reconnection policy;
it does not establish successful publication or resolve buffering, publication
retry/replay, or recovery of uncertain and unpublished messages.

### Questions

* What future recovery mechanism, if any, is accepted after an explicit `DurablePublicationError`?
* What publication retry, replay, or reconciliation policy, if any, applies to uncertain or unpublished messages after Decision 423 transport reconnection?
* May newer durable messages publish after an earlier publication failure?
* How are successful recovery and permanently unpublished messages recorded?
* If future local preservation is accepted, what ownership and storage limits apply?

### Current direction

Do not infer recovery behavior from JetStream durability. Publication recovery remains a separate future architecture decision.

Decision 423 specifies automatic nats-py reconnection for running services, using
bounded backoff with no fixed overall retry-count or elapsed-time limit.
Intentional service closure stops reconnection. Reuse SDK-managed subscription
restoration and inspect existing JetStream readiness/evidence-delivery mechanisms
before proposing additions. No custom coordinator, unnecessary configuration,
new command journal or persistence mechanism is authorized. Ingestor and
StorageManager reconnect independently while retaining their shared process
lifetime under Decision 376.

Transport restoration does not automatically replay Session, Experiment, Stop,
Kill, Cancel or release operations. It does not resolve uncertain publication,
establish preservation, or waive maintenance and shutdown obligations. Existing
durable-evidence and safety contracts remain authoritative. This specifies the
transport part of Decisions 320-321 without claiming automatic recovery of
interrupted Sessions or transfers. The remaining publication-recovery questions
above stay OPEN.

Slice 27's accepted Ingestor journal recovery (Decisions 276-280) concerns evidence
after transport publication and normal JetStream redelivery, not unpublished
producer messages. It does not resolve this publication-recovery question.

---

## Q013: What further framework behavior follows ControllerActionDecision execution?

**Status:** CLOSED within the accepted G4 software scope. G4-A, G4-B and G4-C are
CLOSED; deployment validation remains separate. See
[G4-A closure](validated_workflows.md#g4-a---deployed-lifecycle-isolation-and-fatal-health-accounting)
at `2672879`, [G4-B closure](validated_workflows.md#g4-b---historical-controller-completion-retirement-and-release-retry)
and [G4-C closure](validated_workflows.md#g4-c---scoped-startup-and-failed-launch-resource-cleanup)
following the accepted independent audit at `9f6f73b`. Historical OPEN/pending
statements below describe their respective implementation stages, not current status.

### Accepted G4-A Simplification (Decision 407)

The user-accepted HLC simplification and reconciled LLC handoff are synchronized
in Decision 407. Session lifecycle records how a Session ended; health evidence
records what happened. Already-admitted Normal Stop may produce COMPLETED despite
fatal health decisions only when all existing completion guarantees are satisfied.
Decision 407 partially supersedes Decision 406's mandatory FAILED consequence in
that case, retaining original-context, durable-accounting and sole-cleanup-owner
protections. It clarifies Decisions 113-114 so multiple applicable fatal decisions
are independently accounted for without repeated Experiment termination or
physical cleanup. Individual decisions do not own competing physical cleanup;
one logical Controller-owned Session closeout coordinator governs it, with
independent service-owned obligations unchanged.

Asynchronous outcomes, including failures and diagnostics, must remain scoped to
their originating Session and operation and cannot modify a replacement Session.
Scientific finalization, complete Normal Stop intake/Stage A preservation,
Controller decision archival, independent binding release, authorized Kill,
interrupted cleanup and safe retry remain required under Decisions 313, 322,
360, 365 and 382. No new infrastructure or lifecycle states are accepted.

The Decision 407/408 restructuring and final deployed-lifecycle isolation
correction are implemented, independently validated and audited PASS within
G4-A's closed software scope. The historical Alternative B reports below
describe the earlier mandatory-FAILED contract; their passing results do not
establish Decision 407/408 compliance. The previous independent audit returned
FAIL as recorded below, not an audit result for the new restructuring.
The completed pre-implementation impact/invariant review identified the three
architectural blockers resolved by Decision 408 below. ICC implementation scope
authorization was granted for this coherent implementation. Implementation results
remain distinct from the subsequent independent validation, audit and closure.
Other notification/escalation questions below remain open.

### Accepted Admission And Applicability Clarifications (Decision 408)

The explicitly user-accepted LLC handoff resolves the three blockers below:

- **Closeout admission:** The first Session closeout formally admitted through
  authoritative Controller/Session coordination owns physical closeout. Fatal
  receipt or acceptance alone is not closeout admission. Normal Stop admitted
  first retains ownership even if an earlier accepted fatal decision awaits
  execution; independent accounting does not automatically force FAILED. Fatal
  closeout admitted first retains FAILED and cannot be displaced by Normal Stop.
- **Applicability:** Authoritative acceptance establishes applicability against
  original Session/Experiment context. Decisions accepted while the Experiment
  was active remain independently applicable after termination, without repeated
  termination or cleanup. New decisions about terminated Experiments are not
  automatically applicable. Verified redelivery retains original identity and
  applicability; all asynchronous outcomes remain attributed to the original
  Session/operation, never a replacement Session.
- **Admission cutoff:** Controller authoritatively orders acceptance and closure
  of new Session-associated health-decision admission before committing Decision
  382 intake finalization, without an admission gap. Thereafter new decisions are
  rejected, accepted decisions still require accounting, and verified redelivery
  is permitted without new admission. Rejected late deliveries are not successful
  processing. Finalized evidence, audit and Session Records stay immutable.

Cutoff alone proves neither durability, preservation nor completion eligibility.
All applicable accepted decisions require accounting and preservation before
successful completion; Decisions 313, 322, 365 and 382 remain authoritative.
These architectural requirements are implemented in the bounded restructuring
and final correction closed below. G4-B and G4-C are also CLOSED as recorded below;
Q013 is CLOSED within that accepted software scope.

### G4-A Closure (Validated Software Scope)

**Status: CLOSED at implementation commit `2672879`.** ICC independent IPython
validation passed **3/3** single-node checks. The separate independent Codex audit
returned **PASS, no confirmed P0-P3 findings**, including five additional two-node
adversarial workflows. ICC accepted the audit and authorized documentation-only
closure. See the [validated-workflow record](validated_workflows.md#g4-a---deployed-lifecycle-isolation-and-fatal-health-accounting)
for the exact evidence and limits; this closes neither G4 nor Q013.

**Final deployed lifecycle isolation:** Controller is the sole deployed Session
launcher and uses NATS for all deployed service communication, irrespective of
computer placement. The architecture-to-code reconciliation distinguished accepted
Decision 375/376 deployment from historical direct-object development. A Controller
with direct service collaborators cannot launch a NATS Session; rejection precedes
reservation and canonical mutation. Once launched, synchronous development
lifecycle/health execution, legacy finalization and direct-owner preservation/
collection cannot operate on that binding. Existing launched owner commands handle
scientific finalization for every reserved node, Normal Stop, Kill and release.
Optional object references no longer choose a competing deployed closeout path.

The duplicate Controller-side direct-owner Normal Stop/Kill pipeline, partial-Kill
archive helper, marker-specific local completion helper and unreachable local
release branches were removed. Pure in-process constructors, lifecycle APIs and
manual demonstrations remain supported development tools, not another deployment
architecture. No new finalization cache, mode registry or lifecycle authority was
added. Existing Decision 407/408 admission, independent durable fatal accounting,
cutoff/redelivery, scoped confirmations, cancellation/retry and original-Session
attribution remain required. Previous hybrid test expectations below are historical,
not current support guarantees. G4-A is CLOSED; G4/Q013 remain OPEN, while
G4-B/G4-C and broader Q022 deployment adaptations remain outside this closure.

**Implementation verification:** 142 distinct selected test methods passed under
controlled asyncio execution (116 ownership/accounting/owner-startup methods,
17 capacity/expiry/acquisition/correlation/publication controls, two failure
controls, six additional Normal Stop/Kill readback controls and one stopped-Session
finalization-boundary check). The seven new
deployment-boundary methods cover pre-admission rejection, historical API
isolation, every-node scientific finalization and retained pure in-process use.
Regression-first checks reproduced hybrid launch acceptance before the correction;
the development workflow control already passed. Hybrid borrowed-lock tests were
removed rather than treated as a second deployment contract; existing launched
finalized-intake, current-proof and release/readback tests cover owner boundaries.

Public constructor/method signatures are unchanged, changed Python files parse,
and documentation/diff checks passed. Successful archival checks use actual
preservation/readback with existing-identical handoff fixtures; they do not
establish initial hard-link promotion. An unmodified initial-promotion control
was attempted and blocked by Windows `os.link()` permission denial (`WinError 5`),
not counted as a pass. An interim fixture-migration run was interrupted and rerun
after removing an invalid queued-call test deadlock; it is not validation evidence.
No live NATS, physical hardware, OS signals, power-loss or normal Windows asyncio
scheduling validation is claimed. Initial hard-link promotion was not independently
validated; broader cancellation/replacement and G2/G3 behavior were not exhaustively
revalidated by the final audit. ICC validation and separate audit subsequently
passed as recorded above. No implementation tests or audit were rerun for closure.

### Historical Decision 407/408 Implementation Reports

The reports below preserve their original implementation and audit-stage status,
including earlier FAIL findings and pending-validation statements. Current G4-A
closure is recorded above; these historical statements do not reopen the slice
or close the separately deferred G4-B/G4-C work.

The existing Controller coordination now orders health acceptance against a
mandatory cutoff before completion-marker publication and final acquisition
intake. Accepted evidence retains applicability and original context; multiple
decisions survive Experiment termination without matching an earlier termination
payload. Verified redelivery reuses the accepted decision. New post-cutoff inputs
are rejected, not marked successfully processed or added to immutable evidence.
Accepted but unaccounted fatal decisions block the marker until explicit processing
and retry establish the required proof.

The first formally admitted Session closeout owns coordination through the
existing retained cleanup progress. Decision receipt/acceptance does not select
that owner. Normal Stop can complete despite accounted fatal evidence only with
all existing scientific finalization, producer, intake, Stage A, terminal-record
and release guarantees. Standalone fatal closeout retains FAILED, bindings and
its distinct cleanup/preservation obligations. Experiment-only failure and
authorized Kill retain their existing boundaries.

Positive health acknowledgment requires exact retained decision evidence,
authoritative durable Ingestor acceptance and the applicable admitted-closeout
or lifecycle consequence. It does not await full Normal Stop archival or equate
publication with preservation. Pending/cancelled processing cannot authorize ACK.
Accounting proof is derived from retained command results, not a second cache.
Original asynchronous command context is retained at the shared result-recording
boundary; late success, error or cancellation cannot alter a replacement Session.

Superseded exact-payload termination matching, FAILED-only acknowledgment,
per-decision failure during Normal Stop and the redundant retained Normal Stop
Experiment-context field were removed. Existing cleanup command identities,
scoped producer proof, independent trust-boundary checks and genuine operational
failure/retry handling remain. Public constructors and method signatures are
unchanged. See the [code map](code_map.md)
for entry-point coverage and reusable mechanisms.

**Implementation verification:** 110 distinct selected methods passed under
controlled asyncio execution: nine new decision-accounting methods, twelve shared
coordination methods, 46 local/distributed ownership methods, six Controller action
methods, sixteen remote health methods, eleven Normal Stop/fatal overlap methods,
four scoped-correlation controls and six selected G2/G3 controls. The permanent
independent-decision and late-diagnostic regressions also reproduced the previous
P2/P3 against the committed pre-change Controller/communication code and passed
with the restructuring. This is implementation verification, not an independent
audit. AST parsing, unchanged-public-signature checks and `git diff --check` passed.

Two initial-handoff archival-success methods in `test_fatal_health_normal_stop`
were attempted but blocked by Windows hard-link promotion (`WinError 5`); they
are not counted among the 110 passes. Successful disk-backed closeout controls
reuse the existing identical-handoff fixture and production preservation/readback,
not successful initial hard-link promotion. The controlled loop omits socket-pair
initialization and uses simulated transport; no normal Windows asynchronous
scheduling campaign, live NATS, hardware, OS signals or physical power-loss
verification is claimed. Independent ICC IPython validation and a separate audit
remain required; G4-A/Q013 remain OPEN.

### Decision 407/408 Post-Audit Proof And Identity Correction (Pending ICC Validation)

The separate post-restructuring audit returned FAIL with two confirmed P2 findings:

- **P2-A:** Local `experiment_fail` could record its canonical terminal event and
  then fail scientific finalization. Replay or a second applicable decision could
  report confirmed processing while the actual scientific manifest remained open.
- **P2-B:** Partial health provenance matching could map a new envelope with changed
  diagnostic content or timestamps to an earlier decision after completed Normal
  Stop, ACK it and mark it processed despite the health admission cutoff.

Both failures were reproduced with permanent regressions before production edits.
The bounded correction reuses scientific-owner finalization at the shared decision
accounting boundary. Local terminal evidence is not finalization proof: unfinished
streams must resume successfully before Experiment-only processing is confirmed.
Already-finalized streams are verified through the owner's idempotent finalizer
without repeated flush/write work or duplicate canonical events. Launched-only
termination retains its existing scoped finalization-before-event contract; mixed
local/launched retries cannot bypass local owner proof. Normal Stop remains sole
cleanup owner and independently requires scientific preservation and safe release.

Health and timing input replay now share locked evidence acceptance and cutoff
enforcement. Retained health decisions include the complete original interpretation
or RuntimeEvidenceMessage in `details.interpretation`, including diagnostics,
timestamps and envelope provenance. Transport inputs have stable decision-evidence
identities. Changed content or a new envelope cannot impersonate accepted input;
exact replay preserves original decision time and applicability without requiring
a new clock read. No parallel replay registry or finalization cache was added.
Receiver identity/pending/ACK checks remain separate trust/concurrency boundaries.

**Public interface:** `Controller.process_health_interpretation(evidence)` now
accepts either HealthInterpretationEvidence or its complete RuntimeEvidenceMessage.
The receiver supplies the latter. Payload-only direct calls remain valid, but
cannot prove a subsequently presented transport envelope's identity. To allow
verified transport redelivery after cutoff, direct callers must originally supply
that same envelope. The delayed-delivery regression now does so explicitly.
Controller constructors and all other public signatures remain unchanged.

**Implementation verification:** 74 distinct selected test methods passed under
controlled asyncio execution: fourteen new proof/identity methods, nine prior
decision-accounting methods, six Controller-action methods, sixteen remote-health
methods, twelve shared-coordination methods and seventeen selected ownership,
Kill, correlation, G2/G3 and retirement controls. The new regressions cover actual
disk-backed stream state, failed/cancelled finalization and retries, no duplicate
terminal events, incomplete Stop/release, health/timing replay and rejection,
concurrent acceptance, and unchanged completed archives. This is implementation
verification, not independent validation or audit PASS.
AST parsing of the four changed Python files, public-signature comparison and
`git diff --check` also passed; only the accepted input-type annotation above
changed among Controller's public signatures.

Successful archival controls use the existing identical-handoff fixture and
production preservation/readback, not initial hard-link promotion. Previously
Windows-blocked archival-success tests were not rerun or counted as passing.
No live NATS, hardware, OS-signal, power-loss or normal Windows asynchronous
scheduling validation is claimed. ICC independent validation and a separate audit
remain required. G4-A/Q013 remain OPEN; G4-B/G4-C remain deferred.

### Remote Scientific-Finalization Proof Correction (Pending ICC Validation)

ICC independently validated the preceding proof/identity correction with 2/2
IPython checks. The subsequent independent audit nevertheless returned FAIL with
one confirmed P2: remote-only accounting still substituted canonical Experiment
termination for scientific-owner confirmation. Accepted Session-failure cleanup
could remain unconfirmed while a separately preaccepted Experiment-failure
decision was processed and ACKed with an open remote stream. A second manifestation
used synchronous local termination on a remote-only Controller, mutating canonical
state before failing for lack of local ownership. These share the same incomplete
proof/admission boundary; they do not reopen Decisions 407/408.

Permanent regressions reproduced the failures before production edits. The bounded
correction consolidates the existing launched finalization loop into
`_finalize_launched_experiment_outputs(session, experiment_id)`, reused by initial
termination and subsequent decision accounting. Explicit local scientific ownership
uses existing direct owner verification; remaining reserved owners require bounded,
participant/operation-scoped NATS finalization responses with matching Experiment
identity. Missing, failed, cancelled, lost or wrong-operation confirmation prevents
affirmative Experiment processing and ACK. The original Session is checked across
asynchronous boundaries. The shared local-transition guard now rejects absent
local ownership before canonical or resource mutation.

No finalization cache, new public API, coordinator or lifecycle state was added.
Existing owner finalizers verify already-closed streams without repeated disk
flush/write work. Independent decisions retain their original acceptance and each
requires proof; retries do not append duplicate terminal events or alter a later
Experiment. FAILED Session outcome, incomplete runtime cleanup, retained binding
and preservation obligations remain truthful even after scientific finalization
recovers. Normal Stop retains its separate admitted-owner accounting semantics and
independent producer, intake, archival and release requirements. See the code-map
coverage matrix for local, remote-only and mixed callers.

**Implementation verification:** 80 distinct selected methods passed under
controlled asyncio execution: six new remote-proof methods, fourteen earlier
proof/identity methods, nine decision-accounting methods, six Controller-action
methods, sixteen remote-health methods, twelve coordination methods and seventeen
selected ownership, correlation, Kill, G2/G3 and retirement controls. The new tests
exercise actual disk manifests and real owner responses, unavailable/stalled/
cancelled/lost finalization, wrong-operation rejection, retry and no repeated disk
finalization, independent decisions, local-only rejection, later-Experiment isolation
and empty-product finalization. An initial compatibility run found one mixed-owner
failure caused by an unnecessary NATS round trip under a 10 ms fixture window;
the correction reuses the explicit local owner instead. These are implementation
checks, not independent validation or audit PASS for this correction.

No live NATS, hardware, OS-signal, power-loss or normal Windows asynchronous
scheduling validation is claimed. Successful archival controls use the existing
identical-handoff fixture; Windows-blocked initial hard-link promotion checks are
not counted as passing. Independent ICC validation and a separate audit remain
required. G4-A/Q013 remain OPEN; G4-B/G4-C remain deferred.

### Historical Integration Blockers (Resolved By Decision 408)

The following questions preserve the completed review's pre-408 context. Decision
408 supplies the accepted boundaries above; they are not outstanding blockers.

- **Evidence first arriving after finalized intake:** Decision 382 rejects or
  discards later acquisition deliveries without changing finalized evidence,
  audit or Session Record, while Decision 322 requires archival of every
  Session-associated ControllerActionDecision before binding release. If a newly
  received fatal input is still applicable after that immutable boundary, what
  accepted path establishes its required durable accounting without reopening
  those products? Decision 407 does not select rejection, deferral, another
  archival path or retrospective outcome change as the answer.
- **Delayed execution and first admission:** Where fatal evidence is received or
  recorded before Normal Stop but its execution is delayed, which existing
  authoritative admission establishes closeout ordering? The accepted direction
  does not specify whether receipt, decision acceptance, execution admission or
  cleanup admission determines the order. Scheduler order or execution-time
  observation must not silently become a new architectural rule.
- **Applicability after Experiment termination:** Independent accounting of
  multiple already-applicable fatal decisions is accepted and does not require
  matching a previous decision's complete payload or repeating termination.
  The remaining question is how applicability is established for a newly
  received decision about an already-terminated Experiment, distinguishing its
  original context from genuinely stale or unrelated input. This synchronization
  does not authorize accepting arbitrary historical Experiment identities.

### Completion Entry-Point Coverage

**G4-B / Decision 419: CLOSED within validated software scope.**
Removed historical Controller completion and its finalizer-dependent local release,
record-writing helper and archival snapshot cache. Unsupported local release
retains lifecycle, resource ownership and binding. Existing NATS closeout/release,
owner record construction and standalone Session lifecycle remain unchanged.
Maintenance reuses exact current Controller-owned evidence readback and existing
handoff verification rather than the deleted snapshot cache; unconfirmed final
persistence continues to block maintenance. Tests migrate shared owner guarantees
to archival APIs and launched closeout fixtures, not another completion pipeline.
ICC accepted independent validation and the separate Codex re-audit PASS, with
no confirmed remaining P0-P3 findings, and authorized documentation closure.
At G4-B closure, G4/Q013 and G4-C remained OPEN; their subsequent software closure
is recorded below. G5 was not started by that closure. See [G4-B closure](validated_workflows.md#g4-b---historical-controller-completion-retirement-and-release-retry).

**G4-B subscription teardown correction and independent re-audit:** Actual nats-py
2.15.0 can close local subscription interest before UNSUB transport drain fails;
repeating `unsubscribe()` then raises `BadSubscriptionError`. Controller retains
the existing pending handle until connected transport reconciliation and local
task cleanup succeed. A retry resends UNSUB rather than treating local closure,
transport failure or an invalid-subscription exception as release confirmation.
Cancellation, disconnected transport and preservation uncertainty retain the
binding. No new completion path or release authority is introduced. Focused
actual-SDK tests use simulated transport and real disk-backed owner closeout;
eight focused release methods passed under controlled asyncio execution,
including three SDK regressions, existing cancellation, corruption and failed
preservation checks. Existing-identical handoff fixtures do not validate initial
hard-link promotion. No live NATS, real sockets, hardware, OS-signal, power-loss
or normal Windows asyncio scheduling validation is claimed. The initial
independent audit returned FAIL for this inherited P2, also reproduced against
pre-G4-B `770113f`; no evidence loss or false release was observed. ICC focused
validation then passed 4/4 checks. The independent Codex re-audit passed 14
distinct checks (eight release regressions and six independent adversarial
workflows), confirming the P2 resolved with no remaining confirmed P0-P3 findings.
These stages are not additive validation totals.

Implementation verification: 45 distinct focused methods passed (34 affected
methods, 10 selected owner/finalization regressions and one standalone Session
completion control; overlapping reruns are not additional passes). Eighteen
synchronous checks passed without event-loop substitution. Asynchronous checks
used controlled scheduling, including the existing-identical-handoff fixture;
normal Windows asyncio scheduling and initial hard-link promotion are not
validated. Nine further integration checks remain unconfirmed in the restricted
environment; hard-link permission failures were observed and are not passes.
No live NATS, hardware, OS-signal or power-loss validation is claimed.

**Accepted G4-B direction (Decision 419):** Retire the historical in-process
Controller Session completion workflow instead of adding a second proof pipeline.
Assess removal of `Controller.finalize_session()` and exclusively supporting
code/tests; preserve legitimate standalone Session primitives and shared owner
mechanisms. Supported deployed completion remains NATS-only regardless of service
co-location. This paragraph records the original architectural authorization;
implementation and closure are recorded above. At that authorization, Q013 remained
OPEN and G4-C/G5 were outside its scope. Earlier G4-B proof-gap reports below are
historical motivation, not authorization to strengthen the retired workflow.

**Historical pre-removal scope assessment (resolved by Decision 419 removal):**
The requirement that every completion guarantee be satisfied is unchanged; no
legacy or alternate completion entry point receives an exemption. The impact
review must trace `normal_stop_session()`, `finalize_session()` and their local,
remote and internal completion/preservation consumers. The known legacy proof
gap remains G4-B, not a newly resolved policy question or an authorized scope
expansion. ICC must review implementation coverage/scope; return any genuine
contract conflict found there to LLC/HLC rather than weakening proof requirements.

### G4-C Failed-Launch Cleanup Clarification (Decision 420)

**Status: CLOSED within validated software scope under Decision 420.** The final
independent validation and audit evidence follows the preserved stage history below.
The user-accepted simplified direction resolves the pre-Session cleanup-entry-point
question: a failed launch is not recovered as a Session. Only minimum original
reservation/Session identity, affected participant scope and necessary cleanup
progress carry forward. Failed/cancelled launches attempt participant-owned
cleanup; incomplete or uncertain cleanup leaves affected resources unavailable.

The next `launch_session()` first attempts leftover cleanup through existing
scoped NATS commands and authoritative participant state, under existing Controller
serialization. It proceeds with an entirely new Session only after cleanup and
availability are confirmed; otherwise it rejects the new launch before acquiring
new reservations and identifies unresolved resources. Original-attempt scoping
must protect unrelated/replacement Sessions. Cancellation cannot discard cleanup
obligations or imply successful release.

No failed-Session continuation, scientific-initialization retry, new public
recovery API, parallel lifecycle or persistent failed-launch journal is authorized.
Decision 352 continues to govern participant reservations after Controller failure.
The earlier pre-Session rollback recommendation was not synchronized as a
decision; Decision 420 records cleanup-only semantics and qualifies the historical
no-retry wording in Decisions 293/294/300 without changing their accepted bodies.

**G4-C implementation (now independently validated and closed):** Launch and
runtime-start reserve/initialize/start/abort/release requests use existing scoped
NATS requests; pre-Session readiness/inventory retain `session_id=None`. The
existing operation lock serializes launch, cleanup and runtime transitions. One
existing cleanup-progress envelope retains original-attempt participant scope,
command identities, uncertain side effects and subscription teardown. Failed
launches discard their Session object, not unresolved resources. A later launch
first resolves old cleanup and current participant-owned availability, then
creates a new Session with a new ID. Readiness alone is insufficient. A Session
that successfully launched but later failed runtime startup retains its separate
lifecycle, preservation and release obligations.

Shared abort/release sequencing replaces the duplicate rollback loops. Cached
service responses echo the current attempt nonce; existing diagnostics report
resource bindings through NATS. Unconfirmed cleanup remains a Controller
maintenance blocker. No new recovery API, lifecycle, lock, registry or journal
is introduced. Implementation verification passed 40 distinct focused methods
under controlled asyncio execution, including 13 new methods. Four initial
regressions reproduced the original defects before production edits. A broader
initial test-discovery attempt also exposed pre-existing test failures; those
are not claimed as passes or resolved by this slice.

The final checks cover correlation, cancellation, competing admission, missing
availability proof, lost replies, original-owner protection, new Session identity,
scientific/evidence retention, and selected G4-A/B Normal Stop/Kill/release paths.
No live NATS, hardware, OS-signal, power-loss or normal Windows asyncio scheduling
validation is claimed. Existing-identical-handoff fixtures do not establish
initial hard-link promotion; the nine previously Windows-blocked checks remain
unconfirmed. At that implementation stage G4-C and G4/Q013 remained OPEN pending
ICC independent validation and separate audit; their final closure is recorded below.

**G4-C P2 audit corrections (implementation only):** ICC's initial five behavioral
scenarios passed 5/5, but the independent source/behavior audit at `4e6c383`
returned FAIL with two P2 findings. An invalid affirmative optional-node
reservation reply could omit the node and discard acquired ownership; Ingestor
initialization-abort teardown could become stuck after SDK-local subscription
closure followed by transport failure. These remain historical audit findings,
not an independent PASS for the corrections.

The bounded corrections route every unresolved affirmative reservation outcome
through the existing release/retention branch, while preserving genuine optional
reservation rejection. Ingestor abort now reuses existing SDK-aware teardown and
removes its owned subscription only after that cleanup completes. No new cleanup
state, mechanism, public API or architectural decision is introduced. Completing
subscription teardown does not discharge retained Ingestor evidence obligations.

Five permanent regression methods were added; the four initial methods reproduced
both findings before production changes. Corrected verification passed 31 distinct
focused methods under controlled asyncio execution, including missing/false/string
optional confirmations with successful or blocked cleanup, genuine rejection,
actual nats-py 2.15.0 teardown failure/recovery/cancellation and healthy teardown,
unchanged journal bytes, retained evidence, and selected ownership/cancellation,
Normal Stop/Kill/release regressions. This count overlaps earlier runs and is not
an additive validation total. The existing live-infrastructure, hardware,
OS-signal, power-loss, Windows scheduling and hard-link limitations above remain.
At the correction handoff, renewed ICC validation and independent re-audit were
pending; the following accepted evidence completes those requirements.

**G4-C / Q013 final software closure:** ICC independently passed 7/7 correction
scenarios, following the earlier 5/5: **12/12 PASS**. Separate Codex independent
re-audit at `9f6f73b` returned **PASS, no confirmed P0-P3 findings**, with **16/16
scenarios plus four selected regression checks PASS**. Independent probes covered
optional reservation retention/recovery, actual SDK teardown/task cancellation,
source/requester attribution and abort reply integrity; existing regressions
covered preservation/corruption blockers and stable closeout retries. Both P2
findings above were confirmed resolved. ICC accepted the audit and authorized
documentation-only closure. G4-A/B/C and G4/Q013 are CLOSED within the accepted
software scope; Decision 420 and prior decisions/history remain unchanged.

This is not deployment certification. Live NATS, hardware, OS-signal, power-loss,
normal Windows asyncio, initial hard-link promotion and the nine previously blocked
integration checks remain unverified. Q022, Q024, M015 and Phase 16 remain open;
G5 is not started here. See [G4-C closure](validated_workflows.md#g4-c---scoped-startup-and-failed-launch-resource-cleanup).

### Historical Implementation And Validation Reports

The following reports retain their original implementation/architecture context,
including Decision 406's former FAILED requirement. They are historical evidence,
not claims that the newly accepted Decision 407 is already implemented.

**G4 implementation update (not validated/closed):** Launched Controller Sessions
now subscribe to health/timing interpretations and invoke
`execute_launched_controller_action_decision()` without a local AcquisitionNode.
Non-mutating actions remain non-mutating. Experiment failure reuses remote
scientific finalization and canonical lifecycle ownership; Session failure attempts
each remote runtime stop and retains the failed Session binding and archival
obligations. Missing/failed confirmations remain explicit rather than successful
cleanup or preservation. Independent validation and audit remain pending. This
adds no notification, escalation, maintenance Kill, or recovery policy.

### Why this matters

Decisions 103-114 establish the runtime health evidence chain and normalized local Controller decision execution. `record_only`, `record_warning`, `record_recoverable_failure`, and `operator_required` succeed without lifecycle mutation; `experiment_fail` and `session_fail` use their accepted lifecycle owners. Remaining architecture concerns any future behavior beyond these local semantics.

### Questions

* Should warning, recoverable-failure, or operator-required decisions later trigger external notification or acknowledgement behavior?
* What explicit future decision would authorize escalation beyond their current no-mutation semantics?
* How does Controller execute repeated or conflicting decisions?

Decision 406 resolves the G4 Normal Stop/fatal-health precedence question:
Normal Stop retains cleanup ownership, but an applicable authoritative fatal
decision requires durable evidence and canonical failure accounting before it
may be marked processed. It cannot merely be rejected as competing cleanup.
Existing final-intake and preservation contracts remain unchanged; G4 remains OPEN.

The consolidated G4 ownership correction is implemented but awaits ICC independent
validation and a separate audit. Experiment admission cannot overlap admitted
closeout; AcquisitionNode serializes preparation and cleanup and rejects
preparation after runtime closure. Controller retains one per-participant
Stop/release progress record across Normal Stop, health cleanup and Kill, while
current scoped producer proof independently gates completed Normal Stop retries,
binding release and maintenance eligibility. Uncertain owner operations retain
their command identity; definitive failures permit a new explicit attempt.
Known historical Stop contradictions and identifiable malformed results remain
invalid across supersession, temporary-request filtering and exact replay without
invalidating an independent fresh attempt. Cleanup retries use existing adapter
and scientific-stream states to resume unfinished obligations, not repeat
completed device transitions. Preserved partial Kill archives remain immutable;
later cleanup does not imply newly confirmed preservation. This changes neither
accepted architecture nor G4's OPEN status.

Implementation verification for this consolidated correction passed 166 distinct
test methods across focused controlled-asyncio runs (19 new lifecycle-integrity
methods plus directly affected confirmation, health, binding-release and G2/G3
regressions; repeated runs are not added). This is not independent validation or
an audit. Disk-backed checks exercise existing identical handoff readback, not
initial hard-link promotion; previously Windows-permission-blocked archival tests
are not claimed as passing. Live NATS, hardware, real OS signals, power loss,
Controller restart recovery and normal Windows asynchronous scheduling remain
outside this verification.

**G4-A local ownership remediation (implemented; pending ICC validation/audit):**
Local Session initialization/start, bounded iteration and Experiment transitions
now respect the existing admitted/interrupted closeout association and runtime
transition lock. Invalid requests are rejected before resource side effects.
Local fatal-health execution shares Decision 406 context validation and canonical
failure accounting with the launched executor; exact durable local Ingestor
acceptance is required before confirming health processing. Retained decisions
can retry acceptance after failure without competing cleanup. Canonical failure
no longer invokes a second scientific finalization after runtime-owner cleanup.
No additional lifecycle state, ownership cache or cleanup service was added.
The entry-point/test matrix is in `docs/code_map.md`, with permanent regressions
in `tests/test_local_closeout_ownership.py`.

G4-A verification passed 75 distinct focused methods, including 14 new methods;
the two new synchronous methods also passed without event-loop modifications
using a workspace-permitted temporary directory. Async checks used controlled
SelectorEventLoop scheduling, not normal Windows scheduling. Two older Controller
tests failed identically against unmodified HEAD because they omit the mandatory
Experiment configuration; they were not changed or counted as passes. Two existing
archival-success tests remain blocked by Windows hard-link permission failures
and are not counted as passing. Live NATS, hardware, OS signals and physical
power-loss behavior remain unverified. G4-A awaits ICC validation and independent
audit. G4-B (legacy completion proof) and G4-C (startup/rollback correlation) remain
outstanding; G4 and Q013 remain OPEN.

**G4-A timing/failure-accounting P2 correction (implemented; pending renewed ICC
validation and independent audit):** The shared `_mark_session_failed()` now
contains failure of optional Session Time acquisition only. Canonical
`experiment_fail`, active-context clearing and existing FAILED transitions still
run with `None` and explicit timing uncertainty; evidence-recording and lifecycle
exceptions are not suppressed. The original failure reason/details and available
timing are retained. No second Node Stop or scientific finalization is introduced.
All nine reviewed callers retain the same shared accounting mechanism; Normal
Stop ownership, durable acceptance, cleanup and preservation guards are unchanged.

Regression-first execution reproduced four affected paths (local acquisition,
local fatal action, local Stop and launched Stop), with two controls passing.
Post-correction verification passed all ten new methods. The impact-based set
produced 51 distinct passes: 22 synchronous methods without event-loop changes
and 29 methods under controlled SelectorEventLoop scheduling. Counts overlap
the earlier implementation verification and must not be added to it. One existing
`test_failed_runtime_start_protects_unconfirmed_cleanup` assertion failed because
the reservation was released; the identical assertion failed with HEAD's original
failure-accounting method restored in memory (the only production change).
That baseline failure is not counted as a pass or corrected in this slice.
A bounded normal Windows async attempt stalled before test setup in socket-pair
initialization and is not a pass. The previously blocked hard-link archival
success checks were not rerun or counted. Live NATS, hardware, OS signals,
power loss and normal Windows async scheduling remain unverified. This is
implementation verification only; G4-A/G4/Q013 remain OPEN, and G4-B/G4-C are
unchanged and out of scope.

**G4-A admission-context and interrupted-resource-work correction (implemented;
pending ICC validation and independent audit):** Local Normal Stop retains the
Experiment snapshot established with its first valid Session association; remote
Normal Stop captures it when creating the validated closeout attempt. A valid
original `None` is retained across cancellation, canonical Experiment termination
and repeated retries. Existing remote owner/mode validation now precedes admission
mutation, so rejected retries cannot replace the snapshot. An admitted local Kill
cannot be mistaken for Normal Stop merely because it has a marker association.
Launched Experiment start and shared manual/fatal termination now respect the
retained closeout fence as well as the active task/lock. No new field, cache,
helper or lifecycle authority was introduced. Failure association, exact fatal
context validation, durable acceptance, cleanup/progress, preservation and
verified retirement remain separate; the earlier optional-timing correction is
unchanged. G4-B/G4-C are not modified.

All six required regression-first methods failed before production changes:
local/remote context loss, rejected-owner retry mutation, and interrupted
launched start/manual end/experiment_fail admission. After correction, all 15
new methods passed. Impact-based verification passed 64 distinct methods: 10
synchronous methods without event-loop changes and 54 methods under controlled
SelectorEventLoop scheduling, including the 15 new methods. Repeated runs and
overlap with previous verification are not additive. Coverage includes the three
cancellation windows, fatal decisions before/after cancellation and during retry,
originally empty context, mismatched identity, missing acceptance confirmation,
preservation failure/retry, permitted Kill conversion, verified retirement and
fresh context in a subsequent Session, plus selected existing G2/G3 workflows.
Successful disk-backed controls verified normal completion and failed-terminal
preservation/readback without duplicate cleanup. They reuse the existing
identical-handoff fixture, not initial hard-link promotion. Two test setup issues
were corrected: local setup uses native local Experiment termination, and the
successive-Session receipt double delivers only its current subject filter.
No production scope expansion was needed. A normal Windows async attempt stalled
before setup in socket-pair initialization and is not counted as passing.
Previously blocked hard-link checks and the previously reported baseline
launched-start assertion were not rerun or counted. No live NATS, hardware,
OS-signal, power-loss or normal Windows async scheduling validation is claimed.
This is implementation verification only; G4-A, G4 and Q013 remain OPEN pending
the separate ICC validation and independent audit stages.

**G4-A symmetric admission correction (implemented; pending ICC validation and
independent audit):** Following the consolidated ownership review and ICC scope
authorization, local-owner Normal Stop now checks the existing Experiment-operation
lock before mutating retained admission/context. This aligns its admission with
remote Normal Stop and Kill. No additional production method, helper, lock, field,
cache, public signature or architectural contract changed. Retained original
context (including None), post-cancellation fencing, remote owner/mode validation,
canonical-only fatal accounting, optional timing uncertainty and independent
cleanup/preservation confirmation remain unchanged. Rejection cannot reserve
closeout ownership while an Experiment transition is still executing.

Regression-first verification reproduced nine local-owner admission failures
across preparation, activation, time readback, manual/failure finalization, queued
fatal execution and cancellation. Remote-owner and Kill controls passed. After
the correction, seven new methods covering 31 parametrized workflows passed.
The directly affected selection passed 63 distinct methods: 53 under controlled
SelectorEventLoop scheduling and ten synchronous methods without event-loop
changes. Counts include the new methods; reruns and earlier records are not
additive. Coverage includes both ownership orderings, rejected-admission
immutability, single physical cleanup, one actual scientific finalization per
product, applicable durable fatal acceptance, preserved FAILED outcomes,
unconfirmed archival failure, retry, Kill conversion, verified retirement and
fresh subsequent Session context. The entry-point and ordering matrices are in
`code_map.md`.

Test-harness corrections distinguished idempotent finalization readback from
actual stream finalization, used launched activation before launched termination,
and supplied an explicit one-second fixture result window rather than the reused
local fixture's 0.01-second window. Fatal-before-Experiment-end tests pause Node
Stop, not the later synchronization Stop. These changes do not weaken production
contracts or alter existing tests. Existing successful-preservation controls use
the identical-handoff path, not initial hard-link promotion. Previously
Windows-hard-link-blocked archival checks and the reported baseline startup
failure were not rerun or counted. No ordinary Windows async, live NATS, hardware,
OS-signal or power-loss validation is claimed. No additional production correction
was established by this matrix. G4-A/G4/Q013 remain OPEN; G4-B and G4-C remain
deferred. Independent ICC validation and a separate audit still follow.

**G4-A Alternative B shared coordination (implemented; pending ICC validation
and independent audit):** Following ICC scope authorization, launched Normal Stop
and standalone fatal Session failure now share the existing Controller participant
cleanup traversal, command identities and scoped proof. Synchronous local Stop and
failure callers share Node-status-aware cleanup. Fatal canonical accounting is
independent of physical cleanup: an applicable consequence is retained before
cancellable Experiment-lock waiting, and current ownership is re-evaluated after
handover. If Normal Stop owns cleanup, fatal processing accounts for evidence and
FAILED without competing resource work. Standalone fatal failure retains bindings,
reservations and unconfirmed preservation; it does not invoke Normal Stop's full
archival/release procedure. Its existing bounded owner wait is retained without
changing Normal Stop's execution-task ownership.

The health receiver now requires affirmative Session/evidence-scoped durable
acceptance and canonical FAILED proof before ACK/processed status. Missing,
incomplete or cancelled accounting is not success. Identical pending duplicates
remain unprocessed; confirmed redelivery reuses accounting and cleanup. A confirmed
fatal consequence is distinct from a missing cleanup result or archival failure.
The existing health-publication barrier continues to prevent completion while
required inputs remain unprocessed.

The separate fatal participant loop and duplicate canonical transition branch
were consolidated into existing cleanup and failure-accounting mechanisms; the
Normal-Stop-only accounting helpers were generalized rather than retained as
parallel wrappers. Existing admission guards, retained original context, producer
confirmation, cancellation/progress, binding-retention and preservation checks
remain at their independent boundaries. No stored flag, lock, Session state,
service or public signature was added. Kill and Experiment-only termination were
not refactored; G4-B and G4-C remain out of scope.

Regression-first execution produced eight failing assertions/subcases in the
start/end handover and missing-proof workflows, while standalone/cancellation
controls passed. An additional local-context regression reproduced cleanup before
rejection of an unrelated fatal request; shared validation/canonical accounting
now precedes local physical cleanup as well. Available canonical timing is retained
before cleanup rather than discarded when the clock later becomes unavailable.
Final impact-based verification passed 82 distinct methods:
68 under controlled SelectorEventLoop scheduling and 14 synchronous checks without
event-loop modifications, including twelve new coordination methods. Reruns and
earlier verification are not additive. Actual owners and disk-backed products
cover fatal/Normal Stop orderings, cancellation, partial/lost/stalled cleanup,
fresh acceptance readback, positive processing/replay, preservation failure and
successful FAILED terminal readback. Existing selected tests cover ordinary
completion, verified retirement and Session replacement, Kill, G2 and G3.
The pre-canonical-start control queues fatal execution and makes Normal Stop
runnable at the actual Experiment-lock release, verifying the post-wait ownership
handover separately from immediate canonical failure during activation/termination.

A legacy local fatal-action fixture was corrected to start the named Experiment
and prepare an explicit durable Ingestor journal; evidence-only/non-mutating
controls still pass. The timing fixture now distinguishes a valid timestamp
captured before cleanup from timing unavailable during later failure accounting.
Applying the fatal timeout to Normal Stop initially changed
its task/suspension behavior and failed ownership regressions; the final shared
traversal preserves that bound only for standalone fatal execution. The default
sandbox temporary directory denied synchronous fixture setup; reruns used a
permitted workspace temporary location. Successful archival controls use the
existing-identical-handoff path, not initial hard-link promotion. Previously
Windows-hard-link-blocked success checks are not counted. No normal Windows async,
live NATS, hardware, OS-signal or power-loss validation is claimed. These are
implementation results, not independent validation or audit. G4-A/G4/Q013 remain
OPEN pending ICC review and the separate validation/audit stages.

### Latest Alternative B Independent Audit (FAIL; Before Decision 407)

The separate post-implementation audit reported one confirmed P2 and one P3.
Its observations and required corrective work are not removed or declared resolved
by the subsequent architectural simplification:

- **P2, lost context for distinct accepted fatal decisions:** Two decisions were
  accepted and durably preserved while the same Experiment was active. After the
  first established FAILED and cleared active context, the second was rejected
  repeatedly because the prior canonical event required exact decision-payload
  matching. Both local- and remote-owner compositions reproduced this, with one
  physical Stop, no second acknowledgment and retained unprocessed input.
- **P3, replacement-Session diagnostic contamination:** A delayed public launched
  fatal-action readback completed after verified FAILED preservation, original
  binding release and creation of a replacement Session. The stale failure was
  rejected but then recorded in the replacement's command history/last result.
  Remote reproduction verified the original archive, finalized products and one
  physical Stop; the local variant was blocked by Windows hard-link permissions.

The audit's acknowledgment-loss/redelivery and cancellation-before-readback
controls passed, along with five selected existing regression methods. It used
actual owners, temporary disk persistence, simulated transport and controlled
asyncio scheduling; no ordinary Windows async, live NATS, hardware, OS-signal or
power-loss validation was established. Earlier reported 82-method implementation
verification and ICC's fatal-processing/redelivery PASS remain separate historical
stages, not proof that these findings or Decision 407 implementation are complete.
G4-A, G4 and Q013 remain OPEN.

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

**Generic installer (Decision 421): bounded implementation; independent validation
and audit pending.**
The reviewed LLC-to-ICC design adds a small shared Python installation-time
bootstrap utility, invoked from an existing checkout with compatible Python.
It prepares/updates the environment and existing-schema service configuration,
preserves valid configuration and durable scientific data, checks applicable
configuration/connectivity, reports completed/deferred/blocked work, prints the
existing launch commands and exits. Runtime loaders and the common service CLI
remain authoritative. Missing valid node hardware declarations leave AcquisitionNode
setup incomplete; NATS stays external and is not installed or managed. No new
Controller, operator interface, runtime lifecycle, scientific hardware installer,
OS/Python provisioning or migration framework is authorized. The accepted design
is now implemented in the bounded slice below, not independently validated or
closed. See
[Decision 421](architecture_decisions.md#decision-421-generic-installation-time-bootstrap-reuses-framework-configuration-and-service-launching).

`scripts/install_framework.py` is a standard-library bootstrap invoked with
compatible Python from an existing checkout. It reuses or creates `.venv`, installs
that checkout through its isolated interpreter, validates ordinary role JSON with
existing loaders, preserves existing files, normalizes shared storage selection,
checks local identity/dependency relationships, and prints the existing service
commands. Updates require explicit operator confirmation of resolved retirement;
missing network replies are never retirement proof. Configuration publication is
exclusive, with handled incomplete writes removed. A later failure can leave
complete new files/directories or a partially changed environment; no transactional
package rollback or physical power-loss guarantee is claimed. Missing hardware
and unconfirmed NATS checks remain deferred, not readiness success. The installer
neither starts services nor provisions Python, hardware or the broker. Focused
implementation checks use real loaders/files with simulated package, Git and network
operations. Implementation verification passed 20 installer methods and two
directly reused configuration-loader regressions (22 total), plus the script's
help entry point; sandbox temporary-directory permissions required approved
execution outside the sandbox. These are not real installation or live-network
passes. Real fresh installation/update and Windows/Linux/Jetson deployment
still require ICC/user validation and separate audit. Canonical-guide synchronization
and workflow closure are deferred. Q022 and G5 remain OPEN/incomplete.

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
strongly recommended but are not certification fields or runtime gates. The initial
installation workflow was manual; Decision 421 subsequently accepts a generic
interactive command-line bootstrap using the same files and loaders, with
implementation still pending. No GUI installer or runtime service manager is
introduced. See
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
