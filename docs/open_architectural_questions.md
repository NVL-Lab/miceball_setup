# Open Architectural Questions

This document tracks unresolved architectural questions.

A question remains open until an explicit architectural decision has been accepted and recorded in `architecture_decisions.md`.

The purpose of this document is to guide architecture discussions before implementation begins.

---

# Priority Levels

**Critical**

* Blocks architecture decisions.
* Should be resolved before major implementation begins.

**Important**

* Affects repository structure or component interfaces.
* Can be resolved after core architecture is stable.

**Future**

* Important for later phases but not required for initial implementation.

---

# Q001: What is a Session?

**Priority:** Critical

## Why this matters

The session is the central object of the entire framework.

Almost every component depends on a clear definition of:

* what a session is
* when a session begins
* when a session ends
* what information belongs to a session

Without a session definition, storage, synchronization, reconstruction, and protocol execution remain ambiguous.

## Questions

* What is the exact definition of a session?
* Is a failed acquisition still a session?
* Is a session valid if one device fails?
* Can a session exist without acquired data?
* What information must exist for a session to be considered reconstructable?

## Blocked decisions

* Session lifecycle
* Session storage structure
* Reconstruction requirements

---

# Q002: What is the Session Lifecycle?

**Priority:** Critical

## Why this matters

All major components interact through session state changes.

The architecture needs a shared understanding of lifecycle states.

## Questions

* What states exist?
* What transitions are legal?
* What states are terminal?
* What states are recoverable?

Possible examples:

```text
created
configured
initialized
armed
running
stopping
completed
failed
aborted
```

These are examples only and not accepted decisions.

## Blocked decisions

* Controller responsibilities
* Device Manager responsibilities
* Failure handling

---

# Q003: What is a Stream?

**Priority:** Critical

## Why this matters

Most acquired data will be streams.

Examples:

* camera frames
* accelerometer samples
* analog signals
* digital signals

The framework needs a common definition.

## Questions

* What qualifies as a stream?
* What minimum information must every stream contain?
* Are camera frames a stream?
* Are analog samples a stream?
* Are command logs a stream?

## Blocked decisions

* Storage architecture
* Device interface design
* NWB mapping

---

# Q004: What is an Event?

**Priority:** Critical

## Why this matters

Many devices produce events rather than continuous data.

Examples:

* lick detected
* reward delivered
* tone started
* tone stopped
* session started
* session stopped

The framework needs a consistent event model.

## Questions

* What is an event?
* What metadata must every event contain?
* Are protocol actions events?
* Are device state changes events?
* Are errors events?

## Blocked decisions

* Synchronization architecture
* Storage architecture
* Reconstruction architecture

---

# Q005: How Should Streams and Events Relate?

**Priority:** Critical

## Why this matters

Some data naturally look like streams.

Some data naturally look like events.

Some devices produce both.

The framework needs a coherent model.

## Questions

* Are streams and events separate concepts?
* Are events specialized streams?
* Are streams collections of timestamped events?
* Can a device produce both simultaneously?

## Blocked decisions

* Storage architecture
* Device abstraction

---

# Q006: What is a Synchronization Anchor?

**Priority:** Critical

## Why this matters

The synchronization architecture depends on this concept.

The current design assumes synchronization anchors exist, but they have not yet been defined.

## Questions

* What qualifies as a synchronization anchor?
* What information must be stored?
* How are anchors represented?
* How are anchors used during reconstruction?

## Blocked decisions

* Synchronization architecture
* Reconstruction architecture

---

# Q007: How Should Drift Be Represented?

**Priority:** Important

## Why this matters

The architecture should support future devices that may drift relative to session time.

Even if drift correction is not initially implemented, the architecture should know how drift information would be represented.

## Questions

* Is drift stored explicitly?
* Is drift estimated during reconstruction?
* Can drift vary during a session?
* How should uncertainty be represented?

## Blocked decisions

* Future synchronization features

---

# Q008: What Must Be Stored Online?

**Priority:** Critical

## Why this matters

Some information is generated during acquisition.

Some information could be reconstructed later.

The architecture needs a clear boundary.

## Questions

* What must be written immediately?
* What can be reconstructed later?
* What must never be reconstructed because it would be lossy?

## Blocked decisions

* Storage architecture
* Reconstruction architecture

---

# Q009: What Makes a Session Reconstructable?

**Priority:** Critical

## Why this matters

One of the primary goals of the framework is session reconstruction.

The architecture needs a formal definition.

## Questions

* What information is required?
* What information is optional?
* What information can be regenerated?
* What information is irreplaceable?

## Blocked decisions

* Storage architecture
* Validation architecture

---

# Q010: What Is the Session Record?

**Priority:** Critical

## Why this matters

The framework ultimately exists to produce a session record.

The architecture currently lacks a precise definition.

## Questions

* What files belong to a session?
* What records belong to a session?
* Is the session record a folder?
* Is the session record a database?
* Is it both?

## Blocked decisions

* Storage architecture
* Export architecture

---

# Q011: What Is the Device Contract?

**Priority:** Critical

## Why this matters

Device modularity depends on a stable contract.

Without a contract, every new device becomes a custom integration.

## Questions

* What capabilities must every device support?
* What capabilities are optional?
* How are capabilities declared?
* How does a device expose its streams and events?

## Blocked decisions

* Device Adapter design
* Device validation tests

---

# Q012: What Must Be Tested Before Accepting a New Device?

**Priority:** Important

## Why this matters

The framework should not allow devices that violate synchronization or acquisition requirements.

## Questions

* What minimum tests are required?
* What timing behavior must be verified?
* What lifecycle behavior must be verified?
* What failure behavior must be verified?

## Blocked decisions

* Validation architecture

---

# Q013: What Is the Storage Model?

**Priority:** Critical

## Why this matters

The storage model determines how sessions are persisted.

## Questions

* Folder-based?

* File-based?

* Database-assisted?

* Hybrid?

* What files are mandatory?

* What files are optional?

## Blocked decisions

* Reconstruction architecture
* Export architecture

---

# Q014: What Is the Reconstruction Model?

**Priority:** Critical

## Why this matters

Reconstruction is one of the primary responsibilities of the framework.

## Questions

* What component performs reconstruction?
* What inputs are required?
* What outputs are produced?
* How are reconstruction errors reported?

## Blocked decisions

* Storage architecture
* Validation architecture

---

# Q015: What Is the Protocol Model?

**Priority:** Critical

## Why this matters

The framework must support protocol-driven experiments.

The architectural boundary between Controller and Acquisition Node remains undefined.

## Questions

* What commands can be issued?
* What commands must be recorded?
* What executes locally?
* What executes remotely?

## Blocked decisions

* Controller architecture
* Session architecture

---

# Q016: Can Multiple Acquisition Nodes Participate in a Session?

**Priority:** Future

## Why this matters

Future experiments may involve multiple acquisition systems.

Examples:

* Jetson + microscope PC
* Jetson + behavioral PC
* multiple cameras on separate machines

## Questions

* Is multi-node acquisition supported?
* If supported, who coordinates nodes?
* How is session time shared?

## Blocked decisions

* Future synchronization architecture

---

# Q017: What Is the Configuration Model?

**Priority:** Important

## Why this matters

The framework has already identified hidden defaults as a major failure mode.

Configuration architecture should prevent that problem.

## Questions

* What is configuration?
* What is runtime state?
* What is user-facing?
* What is internal?
* How are defaults declared?

## Blocked decisions

* Repository organization
* API design

---

# Q018: How Should Failure Be Represented?

**Priority:** Important

## Why this matters

Failures are expected in real experiments.

The framework must preserve information about them.

## Questions

* What is a recoverable failure?
* What is a fatal failure?
* How are failures stored?
* Can failed sessions still be reconstructed?

## Blocked decisions

* Session lifecycle
* Validation architecture

---

# Q019: What Is Required For NWB Export?

**Priority:** Future

## Why this matters

The framework intends to support NWB.

The architecture should understand what information is required.

## Questions

* What information must always be captured?
* Which internal concepts map directly to NWB?
* Which concepts require translation?

## Blocked decisions

* Export architecture

---

# Q020: What Is the Minimal End-to-End Experiment?

**Priority:** Critical

## Why this matters

The architecture should be validated against the simplest useful experiment.

Example:

```text
GUI
↓
Controller
↓
Jetson Acquisition Node
↓
Lick Sensor
↓
Ingestor
↓
Storage
↓
Reconstruction
```

The architecture should be able to explain every component involved.

## Questions

* What is the smallest supported experiment?
* What information must be produced?
* What does successful reconstruction look like?

## Blocked decisions

* Architecture validation
* Initial implementation scope

---

# Architecture Board Rule

No implementation work should begin until the Critical questions have either:

1. Been answered and accepted, or
2. Been explicitly deferred with a documented rationale.
