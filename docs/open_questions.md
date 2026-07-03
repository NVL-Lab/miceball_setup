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

## Q001: What is a Synchronization Anchor?

### Why this matters

The synchronization architecture assumes synchronization anchors may exist, but they have not yet been formally defined.

### Questions

* What qualifies as a synchronization anchor?
* Is a synchronization anchor required in Phase 1?
* If Phase 1 uses Jetson monotonic time, what timing records are still required?
* What information must be stored if hardware synchronization is added later?
* How are synchronization anchors used during reconstruction?

### Blocks

* Detailed synchronization schema
* Future hardware timing support
* Reconstruction validation rules

---

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

## Q006: How Should Drift Be Represented?

### Why this matters

Future devices may not perfectly follow session time.

### Questions

* Should drift be represented explicitly?
* Should drift be estimated during reconstruction?
* Can drift vary during a session?
* How should timestamp uncertainty be represented?
* What precision is required for Phase 1?

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

## Q009: Multi-Node Acquisition

### Why this matters

Future Sessions may involve multiple acquisition systems participating in the same Session.

Examples:

* Jetson + microscope PC
* Jetson + DAQ PC
* Jetson + behavioral PC

### Questions

* Is multi-node acquisition supported conceptually?
* How is session time shared across nodes?
* Who coordinates nodes?
* What records are required for reconstruction?

### Current Direction

Architecturally allow this in the future, but do not implement it in Phase 1.

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

## Q011: What is the retry and replay model for failed handoff envelopes?

### Why this matters

The first handoff failure slice preserves failure evidence and may preserve failed envelopes locally, but it does not retry or replay them.

### Questions

* Should failed envelopes be retried immediately, later, or only manually?
* Is there a retry queue or local backlog?
* Are newer envelopes allowed to continue sending while older failed envelopes remain unsent?
* How are successful retries recorded?
* How are permanently unsent envelopes represented in the Session Record?
* Who initiates replay: AcquisitionNode, Controller, or offline reconstruction tooling?
* What local storage limits apply to failed-envelope preservation?

### Current direction

Do not implement retry/replay in the first handoff failure slice. Preserve sender-side failure evidence first, then design retry/replay explicitly as a later Phase 3 robustness decision.

---

## Q013: What is the acquisition-health consequence model?

### Why this matters

Acquisition health v1 can produce health evidence, but the architecture has not decided when health failures are warnings, recoverable failures, fatal acquisition failures, or Session failures.

### Questions

* Which health failures should only record evidence?
* Which health failures should stop acquisition?
* Which health failures should mark the AcquisitionNode failed?
* Which health failures should cause Controller/Session failure handling?
* Are consequences configured per health policy?
* How are repeated health failures represented?

### Blocks

* Fatal/warning health behavior
* Session failure integration
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

## Q015: What orchestration follows Controller v1?

### Why this matters

Controller v1 now coordinates one bounded Session sequentially. Experiment-level and distributed orchestration remain intentionally deferred.

### Questions

* How are Experiment segments represented and orchestrated within a Session?
* How does acquisition health apply to a specific Experiment segment?
* What semantics distinguish a future abort command from framework failure and intentional stop?
* What component, if any, coordinates multiple Sessions?
* How is orchestration distributed across multiple Acquisition Nodes?

### Blocks

* Experiment orchestration
* Experiment-scoped health
* Abort semantics
* Multi-session and distributed orchestration

