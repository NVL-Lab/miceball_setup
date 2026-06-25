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

The remaining work is defining the exact folder structure,
mandatory files, optional files, manifests, file-tracking records,
and validation outputs.

Additional questions:

* What is the persistent schema for lifecycle transition records, readiness checks, cleanup evidence, and final session status?
* Should runtime lifecycle evidence always be exposed as read-only records, or are there accepted cases where another component may append lifecycle evidence?

---

## Q003: What is the Minimal End-to-End Experiment?

### Why this matters

The architecture should be validated against the smallest useful experiment.

### Questions

* What is the smallest supported experiment?
* Which devices participate?
* Which streams are produced?
* Which events are produced?
* Which timing records are produced?
* What files are written?
* What does successful reconstruction look like?

### Blocks

* Architecture validation
* Initial implementation scope
* Testing strategy

---

## Q004: What belongs in the First Implementation Milestone?

### Why this matters

The architecture is largely defined, but implementation should begin with a focused vertical slice.

### Questions

* What is the first useful end-to-end workflow?
* Should the first milestone use simulated devices?
* Should the first milestone use real devices?
* Should the Ingestor be included immediately?
* Should reconstruction be included immediately?
* What constitutes a successful Phase 1 demonstration?

### Blocks

* First implementation plan
* First Codex development cycle

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

Device validation requirements have not yet been defined.

### Questions

* What lifecycle behavior must be tested?
* What timing behavior must be tested?
* What failure behavior must be tested?
* What schemas must a device declare?
* What makes a device Phase-1 compliant?

### Blocks

* Device validation architecture
* Testing requirements

---

## Q008: What is the Configuration Model?

### Why this matters

The philosophy has been accepted, but the exact configuration model has not.

### Questions

* What is configuration?
* What is runtime state?
* What is user-facing configuration?
* What is internal configuration?
* How are defaults declared?
* How are configuration values propagated?
* Should configuration be represented as YAML, JSON, classes, or another structure?
* What vocabulary and structure should be used for `DeviceDeclaration.declared_capabilities`?

### Blocks

* API design
* Session manifest structure
* Device schema structure

---

# Future Questions

## Q009: Multi-Node Acquisition

### Why this matters

Future experiments may involve multiple acquisition systems participating in the same session.

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

# Architecture Board Rule

No major implementation work should begin until all Critical questions have either:

1. Been answered and accepted, or
2. Been explicitly deferred with a documented rationale.
