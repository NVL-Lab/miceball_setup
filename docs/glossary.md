# Glossary

This document defines the architectural terminology used throughout the repository.

These definitions take precedence over informal usage.

---

# Acquisition Node

A hardware-facing runtime responsible for acquiring data from devices, generating acquisition records, and forwarding records to the Ingestor.

The Jetson is the Phase 1 Acquisition Node.

The Acquisition Node is not the GUI, Controller, Ingestor, or Storage Manager.

---

# Acquisition Runtime

The Session-level runtime owned by an Acquisition Node.

When the Acquisition Runtime is active, the node is active for that Session, Session Time is running, and acquisition evidence may be recorded.

Acquisition Runtime active does not imply that an Experiment is running or that every declared device is streaming or producing records.

---

# Controller

The component responsible for sequential orchestration and command results for one Session in Controller v1.

Examples:

* create session
* initialize session
* start session
* stop session
* run bounded acquisition iterations
* finalize session evidence and outcome

The Controller coordinates existing components but does not own Session lifecycle state, Acquisition Runtime execution, Session Time, device lifecycle, ingest audit, or persistent writing.

The GUI and Controller are conceptually separate, even if they run on the same machine.

The Controller owns canonical Experiment lifecycle orchestration. AcquisitionNodes record local execution evidence associated with an active Experiment.

---

# Device

A hardware or software component that participates in a session.

Examples:

* camera
* lick sensor
* speaker
* accelerometer
* water delivery system

A Device may produce streams, events, or both.

---

# Device Adapter

The component responsible for communicating with a specific device type.

The Device Adapter owns device-specific communication and exposes device capabilities to the framework.

The Device Adapter does not own device lifecycle management.

---

# Device Manager

The component responsible for device lifecycle management.

Responsibilities include:

* discovery
* initialization
* configuration
* start
* stop
* shutdown

The Device Manager does not own device-specific communication.

---

# Event

A discrete timestamped occurrence.

Examples:

* lick detected
* reward delivered
* tone started
* tone stopped
* device disconnected
* session started

Events are part of the scientific record.

---

# Experiment

A scientific or protocol segment that runs within a Session.

Examples:

* a behavioral task segment
* a stimulus protocol segment
* a baseline recording or scientific decoder-calibration segment

A Session may contain no active Experiment or multiple sequential Experiment segments, with at most one active Experiment at a time. Controller owns canonical Experiment start/stop orchestration, while Session owns descriptors and lifecycle evidence.

Each Experiment segment has one canonical, Controller-owned lifecycle in the Session timeline and Session Record. An Experiment declares expected participation by selected Session-owned resources without owning those resources.

Session-ready resources are not automatically Experiment participants, and Experiment participants are not necessarily continuously producing records.

---

# Experiment Descriptor

The Session-owned plain-data description of one Experiment's scientific identity and declared expected participation.

An Experiment Descriptor is persistent Session evidence. It does not own lifecycle state or live runtime resources, and it does not bind declarations to live objects.

---

# Expected Participant

A plain-data declaration in an Experiment Descriptor describing a Session resource expected to contribute to that Experiment.

Its minimum conceptual fields are `participant_id`, `participant_type`, `expected_contribution`, and `required`. Expected participants may describe Acquisition Nodes, Devices, protocol services, decoders, or other runtime components.

Participation means expected contribution, not continuous record production. An Expected Participant is not a live `DeviceAdapter`, a `DeviceManager` entry, an `AcquisitionNode` object, or a runtime binding.

Only Expected Participants declared by the active Experiment are in scope for Experiment-scoped acquisition-health evaluation. Being Session-ready alone does not place a resource in that scope.

Expected Participant identifiers are not matched implicitly to Device Declarations, live source identifiers, Device Adapters, or Acquisition Nodes. Caller/orchestration must provide an explicit runtime mapping before AcquisitionNode can evaluate the expectation.

---

# Experiment Participant Runtime Mapping

An explicit caller/orchestration-provided mapping for one active Experiment, keyed by live acquisition source ID.

Each entry identifies the Expected Participant satisfied by that source, the acquisition-health policy, whether participation is required, and the expected contribution. One Expected Participant may map to zero, one, or many live sources; one live source may satisfy at most one Expected Participant within the active mapping.

The mapping is immutable for the active Experiment's lifetime and may differ between Experiments in the same Session. It is runtime intent, not persistent resource ownership. AcquisitionNode evaluates only mapped live sources and never infers bindings by comparing identifiers.

The mapping is also the authoritative acquisition-health policy assignment for each mapped live source during that Experiment. A different Experiment may assign a different policy to the same source.

---

# Acquisition-Health Policy

A named configurable definition of acquisition-health evaluation behavior and, in future, consequence behavior.

Policy definitions live in Session or Experiment configuration. The active Experiment Runtime Health Mapping assigns a policy to each mapped live acquisition source for that Experiment.

The plain-data policy definition contains a `policy_id`; optional evaluation values for first-record grace window, maximum gap, and minimum rate; and an interpretation mapping from observation type to consequence label. Observation type and consequence label are distinct: the observation describes what was detected, while the assigned policy supplies configured operational meaning.

Supported consequence labels are `informational`, `warning`, `recoverable_failure`, `experiment_failure`, and `session_failure`. These labels are vocabulary only in the first policy-definition slice: they are validated and stored but have no runtime semantics or actions.

Interpretation keys must be supported by the evaluator that validates the policy. Policies do not define evaluator observation capabilities.

`DeviceDeclaration` does not contain or assign acquisition-health policy; a device is not globally critical, soft, optional, warning-only, or fatal across every Experiment.

---

# Experiment-Scoped Acquisition Health

Evaluation of whether contributions expected by the active Experiment appeared.

Its scope is determined exclusively by the active Experiment Runtime Health Mapping. With no active mapping, no Experiment-scoped acquisition-health evaluation occurs. With an active mapping, only mapped live acquisition source IDs are evaluated; Session-ready but unmapped resources are excluded.

Experiment-scoped acquisition health is distinct from Session Readiness, which asks whether a resource can safely participate in the Session. The existing first-record grace-window algorithm is validated for mapped sources; additional algorithms, consequences, participant enforcement, and Controller policy remain deferred.

---

# Experiment-Scoped Health Observation

A condition detected by AcquisitionNode while evaluating acquisition health for live sources in the active Experiment Runtime Health Mapping.

Examples include missing expected evidence, resumed evidence, acquisition rate below expectation, or acquisition resuming after interruption. A Health Observation records what AcquisitionNode observed as Experiment-scoped health evidence; it does not assign operational significance.

For the first behavioral slice, a Health Observation is evidence only. It is not inherently a warning, recoverable failure, Experiment failure, Session failure, Controller command, operator notification, recovery action, or retry request. Policy interpretation and runtime consequence execution remain separate.

---

# Validation

An operator-initiated operational activity inside a Session that records validation evidence without creating an Experiment.

Examples include playing a test tone, dispensing one reward, acquiring one camera frame, flashing an LED, moving an actuator, or operational calibration such as autofocus.

Not every Device or runtime component must support Validation.

---

# Calibration

A purpose rather than an architectural category.

Operational calibration is represented as Validation. Scientific calibration, such as BMI decoder training, is represented as Experiment.

---

# Failed Session

A Session that terminated because of an unexpected failure.

Failed Sessions are still valid records and must be preserved.

---

# Ingest Time

The time at which the Ingestor receives a record.

Ingest Time is useful for debugging, auditing, and latency analysis.

Ingest Time is not Session Time.

---

# Ingestor

The component responsible for receiving records from Acquisition Nodes and preserving them for storage.

The Ingestor owns:

* record intake
* record validation
* record forwarding
* ingest auditing

The Ingestor does not own scientific time.

---

# Local Device Time

A timestamp, counter, frame number, or clock value generated by an individual device.

Local Device Time may be useful for debugging, reconstruction, and drift analysis.

Local Device Time is not Session Time.

---

# Protocol

The logical description of what an experiment intends to do.

Examples:

* reward schedule
* stimulus schedule
* trial structure
* task logic

The Controller owns protocol intent.

The Acquisition Node records protocol execution.

---

# Project

The larger scientific study or collection of related Sessions.

A Project may contain many Sessions. Project orchestration is not implemented in the current framework.

---

# Raw Record

A record captured directly from acquisition before reconstruction or export.

Examples:

* stream samples
* events
* timing records
* ingest records
* error records

Raw Records are considered immutable after session completion whenever possible.

---

# Reconstruction

The process of rebuilding a complete session timeline from stored records.

Reconstruction operates on stored data and does not require the original runtime processes.

---

# Reconstruction Manager

The component responsible for session reconstruction.

Responsibilities include:

* loading records
* validating records
* rebuilding timelines
* producing reconstruction outputs

The Reconstruction Manager does not perform acquisition or protocol execution.

---

# Session

A bounded temporal and evidence container with accepted configuration, selected devices, lifecycle state, Session Time, and a session identity.

A Session may last minutes or hours.

A running Session does not imply that an Experiment is running or that all declared devices are streaming. It indicates Session lifecycle state, not protocol or device-production state.

---

# Device Streaming

The condition in which one live device is actively producing acquisition records.

Device streaming is source-specific. Session running and Acquisition Runtime active do not imply that every declared device is streaming.

---

# Session Record

A durable evidence package for one Session.

Examples include:

* accepted Session Configuration
* Session lifecycle evidence
* device readiness evidence
* service readiness evidence
* session_start and session_stop acquisition events
* accepted acquisition envelopes
* ingest audit records
* final session status
* warnings, recoverable failures, and fatal failures
* cleanup evidence

The Session Record preserves what was intended, what was ready, what ran, what was acquired, what was ingested, how the Session ended, and what failed.

The final folder layout, manifest format, detailed schemas, reconstruction outputs, and export formats are defined separately.

---

# Session Time

The shared time within a Session used to align streams, events, Experiments, and timing records.

Session Time has exactly one owner: the Synchronization Manager.

Session Time is distinct from Local Device Time and Ingest Time.

---

# Storage Manager

The component responsible for persistent storage of session records.

Responsibilities include:

* writing records
* organizing records
* validating storage operations

The Storage Manager does not own synchronization.

---

# Stream

Repeated time-indexed data from a source.

Examples:

* camera frames
* accelerometer samples
* continuous analog signals
* continuous digital signals

Streams are part of the scientific record.

---

# Synchronization Manager

The component responsible for Session Time.

Responsibilities include:

* defining Session Time
* maintaining Session Time
* providing Session Time to the framework
* supporting reconstruction of timing relationships

The Synchronization Manager is the sole owner of Session Time.

---

# Timing Record

A record that describes when data occurred or how timing relationships should be reconstructed.

Examples:

* timestamps
* frame numbers
* sample indices
* synchronization records
* timing mappings

Timing Records are part of the raw scientific record.

---

# Warning

A non-fatal condition that should be recorded but does not require acquisition to stop.

Examples:

* temporary communication delay
* dropped packet with successful recovery

Warnings are recorded as events.

---

# Recoverable Failure

A failure from which the system can safely continue after recording the failure and performing recovery actions.

Recoverable Failures are recorded as events.

---

# Fatal Failure

A failure that prevents safe continuation of the session.

Fatal Failures result in Session termination after cleanup and preservation of available records.

Fatal Failures are recorded as events.

---

# Record Collection

An acquisition-side collection of records produced by one live Device Adapter and collected through the DeviceManager.

A Device Record Collection identifies the source device, the kind of records collected, and the record rows or payloads.

It is not a transport message and is not sent directly to the Ingestor.

Device Record Collections are converted into Acquisition Record Envelopes by the AcquisitionNode.

---

# Acquisition Record Envelope

The unit of acquisition data exchanged between the acquisition side and the Ingestor.

An Acquisition Record Envelope contains session identity, source device
identity, record kind, and records in a plain-data form that can cross a process
or computer boundary. Phase 2 envelopes may also contain `source_node_id`;
existing Phase 1 envelopes remain valid without it.

---

# Acquisition Node Readiness

Readiness evidence for one explicitly identified acquisition-capable system.

`AcquisitionNodeReadiness` records `node_id`, `session_id`, and role while
aggregating the existing Device Readiness Summary and Service Readiness records.
It does not replace those existing readiness contracts.

It is created by the AcquisitionNode, not by Device Adapters.

---

# Record Kind

A minimal label identifying the broad kind of records being carried.

Examples may include stream, event, timing, file_reference, or other accepted record categories.

The detailed stream/event schema is defined separately.

---

# Service Readiness

A standardized readiness report produced by framework services such as the Ingestor, StorageManager, and SynchronizationManager.

Service Readiness is consumed by Session during initialization to determine whether required services are ready for acquisition.

It does not describe device readiness.

---

# Device Readiness

A readiness summary describing whether one or more Device Adapters are prepared for acquisition.

Device Readiness is produced by the DeviceManager by aggregating the readiness of its managed Device Adapters.

It is distinct from Service Readiness.

---

# Acquisition Evidence

Information recorded as part of the scientific acquisition record.

Examples include acquisition data, session_start events, session_stop events, timing information, and other acquisition-side records.

Acquisition Evidence is created by the AcquisitionNode and preserved by the Ingestor and StorageManager.

It is distinct from Session lifecycle state.

---

# Session Lifecycle

The runtime state of a Session.

Examples include initialized, running, stopped, completed, failed, and aborted.

Session lifecycle is owned by the Session and records framework execution state.

It is distinct from Acquisition Evidence.

---

# Device Lifecycle

The runtime lifecycle of a live Device Adapter.

Typical lifecycle states include:

* declared
* initialized
* ready
* running
* stopped
* shutdown
* failed

Device Lifecycle is owned by the DeviceAdapter and coordinated by the DeviceManager.

It is distinct from Session Lifecycle.

---

# Acquisition-side Caller

The runtime code responsible for coordinating acquisition-side operations outside the responsibilities of individual framework components.

Examples include collecting records from the DeviceManager, obtaining Session Time from the Synchronization Manager, creating Acquisition Record Envelopes, and forwarding them to the Ingestor.

The Acquisition-side Caller is a temporary architectural role. It is not itself a framework component and may later become part of the AcquisitionNode runtime.

---

# Session Start

The acquisition event that begins Session Time for a Session.

At Session Start:

```text
session_time_s = 0.0
```

---

# Session End

The acquisition event that ends Session Time for a Session.

Session End marks the completion of acquisition and defines the final Session Time for the recorded acquisition evidence.

Session End is distinct from the end of the behavioral protocol.

---

# Device Status

A summary describing the current runtime state of a live Device Adapter.

Device Status includes lifecycle state and runtime status information such as initialization, readiness, running, stopped, failed, and shutdown.

Device Status is produced by the DeviceManager.

It describes runtime execution state and is distinct from Device Readiness.

---

# Persistent Storage

The durable preservation of acquisition records beyond runtime memory.

Persistent Storage begins after records leave the Ingestor and are accepted by the Storage Manager.

For v1, accepted Acquisition Record Envelopes may be stored as JSONL, with one envelope dictionary per line.

JSONL is a storage backend detail, not a replacement for the Storage Manager architectural boundary.

The final storage format is defined separately from the Storage Manager architecture.

---

# Readiness

An automatic framework operation during Session initialization that determines whether components can safely participate and whether the Session may proceed.

Readiness is not operator-initiated and does not create an Experiment.

---

# Readiness Gating

The process of determining whether Session initialization may proceed based on readiness evidence.

Session performs Readiness Gating using Device Readiness and Service Readiness.

Required components that are not ready prevent Session initialization.

Optional components are recorded but do not block initialization.

---

# Shared Readiness Contract

The common readiness record shared between DeviceManager and Session.

The shared readiness contract is produced by DeviceManager and consumed unchanged by Session.

Session records the readiness evidence but does not transform or reinterpret the readiness records beyond required-device gating.

---

# End-to-End Lifecycle Test

A vertical-slice test that exercises the intended public workflow of the framework using fake components.

An End-to-End Lifecycle Test validates component interaction through public APIs rather than internal implementation details.

It is intended to document expected framework usage as well as verify behavior.

---

---

# Device Declaration

A persistent configuration object describing an intended participant in a Session.

A Device Declaration identifies a device independently of any live hardware connection.

Typical fields include:

* device_id
* device_type
* enabled
* required
* declared_capabilities

Device Declarations are stored in Session Configuration.

They are used by caller code to explicitly construct live DeviceAdapters.

A Device Declaration is not a live device and does not communicate with hardware.

A Device Declaration establishes Session-level availability and intent. It does not contain or assign an acquisition-health policy; the active Experiment Runtime Health Mapping owns that assignment.

---

# Session Configuration

The accepted run configuration owned by a Session.

Session Configuration declares the intended runtime configuration of a Session, including selected Device Declarations, session parameters, device configuration, synchronization configuration, acquisition configuration, ingestion/storage configuration, and protocol intent or reference.

The accepted Session Configuration is immutable for the duration of the Session.

The accepted Session Configuration is part of the persistent Session Record.

It represents intended execution rather than runtime state.

Session Configuration is validated during Session initialization.

It does not contain runtime objects such as DeviceAdapters, DeviceManagers, or other live framework components.

---

# Lifecycle Evidence

Information recorded during runtime that documents execution of framework lifecycle operations.

Examples include:

* lifecycle transitions
* readiness checks
* cleanup completion
* final status

Lifecycle Evidence describes framework execution state.

It is distinct from Acquisition Evidence, which describes scientific acquisition data and timing.






