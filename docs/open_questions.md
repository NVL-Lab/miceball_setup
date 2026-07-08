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

The remaining work is defining the exact folder structure,
mandatory files, optional files, manifests, file-tracking records,
validation outputs, and representation details for each evidence category.

Additional questions:

* What files are mandatory for a valid Session Record?
* What files are optional?
* What manifest format identifies the included evidence?
* How are file-tracking records represented?
* What validation outputs are required?
* How should accepted configuration, lifecycle evidence, readiness evidence, acquisition evidence, ingest audit records, final status, failures, and cleanup evidence be represented in storage?

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

Sender-side robustness now preserves evidence before handoff, but receiver-side validation remains separate. The Ingestor may eventually need to detect malformed envelopes, missing timing, duplicated envelopes, or incomplete sessions.

### Questions

* What envelope validation does Ingestor perform?
* Does Ingestor reject malformed records or preserve them with audit evidence?
* What fields are mandatory for accepted envelopes?
* How does Ingestor represent rejected envelopes?
* Does Ingestor detect missing expected sources, or is that only AcquisitionNode health?
* How are receiver-side failures represented in the Session Record?

### Blocks

* Ingestor hardening
* Session Record failure schema
* Reconstruction validation

---

## Q015: What orchestration follows Phase 5?

### Why this matters

Controller v1 now coordinates one bounded Session sequentially, records canonical Experiment evidence, and activates explicit Experiment runtime health mappings on AcquisitionNode. Phase 5 completes this narrow Experiment lifecycle and health-scope architecture. Validation, abort semantics, multi-session control, and distributed orchestration remain intentionally deferred.

Decisions 095–102 establish canonical Experiment lifecycle ownership, distinguish Readiness and Validation from Experiment, define expected participants as plain-data declarations, define an immutable live-source-keyed runtime health mapping, and scope AcquisitionNode Experiment health evaluation exclusively to that active mapping. Acquisition-health consequences remain tracked separately in Q013.

### Questions

* How is Validation requested and recorded without creating an Experiment?
* What semantics distinguish a future abort command from framework failure and intentional stop?
* What component, if any, coordinates multiple Sessions?
* How is orchestration distributed across multiple Acquisition Nodes?

### Blocks

* Validation orchestration
* Abort semantics
* Multi-session and distributed orchestration

---

## Q016: How is distributed Health Interpretation Evidence consumption recovered and deduplicated?

### Why this matters

Decisions 115-149 settle the communication boundary, and the implemented Controller consumer now independently receives Session-scoped `HealthInterpretationEvidence` through JetStream. Operational recovery and duplicate-presentation behavior remain unresolved.

### Questions

* How are consumer acknowledgement, restart, and duplicate presentation handled without repeating Controller actions?
* How are missing or delayed evidence-consumption outcomes surfaced operationally?

### Blocks

* Distributed health consequence handling
* Multi-node Controller integration

---

## Q017: What is the artifact transfer backend and verification workflow?

### Why this matters

Decisions 118-121 and 147-149 establish a separate, pull-based Artifact Plane. They intentionally do not choose the transfer backend, scheduling, verification, checksums, retention, or destination layout.

### Questions

* Which component requests and performs artifact retrieval?
* What transfer protocol and authentication model are used?
* How are transfer completion and verification represented as durable evidence?
* What checksum, resume, retention, and cleanup policies apply?

### Blocks

* Artifact transfer implementation
* Storage consolidation
* Reconstruction from transferred artifacts

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
