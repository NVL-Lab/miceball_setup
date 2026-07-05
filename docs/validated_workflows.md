# Validated Workflows

This document records the end-to-end workflows that have been implemented and validated by the public test suite.

Each workflow represents a complete vertical slice through one or more architectural boundaries.

The purpose of this document is to answer:

> **"What can the framework do today?"**

rather than:

- why the architecture is designed a certain way (see `architecture_decisions.md`)
- what architectural terms mean (see `glossary.md`)
- where code lives (see `code_map.md`)

As the framework grows, this document should evolve into a catalog of validated capabilities.

---

# W001 - Session Lifecycle

## Purpose

Validate the Phase 1 runtime Session lifecycle.

## Workflow

```text
Session
    |
    v
created
    |
    v
initialize()
    |
    v
start()
    |
    v
stop()
    |
    v
complete()
```

## Validates

- Session lifecycle transitions
- lifecycle recording
- readiness gating
- cleanup
- normal completion

---

# W002 - Device Readiness

## Purpose

Validate the boundary between configuration, live devices, and Session readiness.

## Workflow

```text
DeviceDeclaration
        |
        v
DeviceAdapter
        |
        v
DeviceManager
        |
        v
DeviceReadinessSummary
        |
        v
Session.initialize()
```

## Validates

- Device declarations
- live adapters
- DeviceManager lifecycle coordination
- readiness aggregation
- Session readiness gating
- required vs optional devices

---

# W003 - Service Readiness

## Purpose

Validate that Session initialization consumes readiness summaries from framework services.

## Workflow

```text
InMemoryIngestor
        |
        v
ServiceReadiness
        |
        |
InMemoryStorageManager
        |
        v
ServiceReadiness
        |
        |
SynchronizationManager
        |
        v
ServiceReadiness
        |
        v
Session.initialize()
```

## Validates

- shared ServiceReadiness contract
- Session service readiness recording
- required service gating
- Session does not inspect service internals

---

# W004 - Acquisition Envelope Boundary

## Purpose

Validate the acquisition-to-ingestion boundary.

## Workflow

```text
DeviceManager
        |
        v
DeviceRecordCollection
        |
        v
Acquisition-side caller
        |
        v
AcquisitionRecordEnvelope
        |
        v
dict
        |
        v
AcquisitionRecordEnvelope
        |
        v
InMemoryIngestor
        |
        v
InMemoryStorageManager
```

## Validates

- DeviceManager does not know Ingestor
- acquisition-side caller creates envelopes
- envelope plain-data round trip
- Ingestor receives envelopes
- StorageManager stores accepted envelopes unchanged

---

# W005 - Phase 1 Session Time

## Purpose

Validate the ownership of Session Time.

## Workflow

```text
SynchronizationManager
        |
        v
start()
        |
        v
session_time_s
        |
        v
Acquisition-side caller
        |
        v
records
        |
        v
AcquisitionRecordEnvelope
        |
        v
Ingestor
        |
        v
Storage
```

## Validates

- SynchronizationManager owns Session Time
- adapters do not assign Session Time
- acquisition-side caller attaches Session Time
- Ingestor preserves Session Time
- Storage preserves Session Time

---

# W006 - Session Acquisition Lifecycle

## Purpose

Validate the complete Phase 1 acquisition workflow.

## Workflow

```text
Session created
        |
        v
Device declarations
        |
        v
Live DeviceAdapters
        |
        v
DeviceManager
        |
        v
Device readiness
        |
        v
Service readiness
    +-- Ingestor
    +-- Storage
    +-- SynchronizationManager
        |
        v
Session.initialize()
        |
        v
Session.start()
        |
        v
SynchronizationManager.start()
        |
        v
session_start event
        |
        v
AcquisitionNode
        |
        v
run_one_iteration()
        |
        v
DeviceRecordCollection
        |
        v
AcquisitionRecordEnvelope
        |
        v
dict round-trip
        |
        v
InMemoryIngestor
        |
        v
InMemoryStorageManager
        |
        v
SynchronizationManager.stop()
        |
        v
session_stop event
        |
        v
Session.stop()
        |
        v
Session.complete()
```

## Validates

- Session lifecycle
- device readiness
- service readiness
- Session Time ownership
- session_start acquisition evidence
- bounded acquisition
- acquisition envelope boundary
- envelope serialization boundary
- ingest auditing
- storage boundary
- session_stop acquisition evidence
- normal session completion

---

# W007 - AcquisitionNode Bounded Execution

## Purpose

Validate that AcquisitionNode owns bounded acquisition-side execution without owning Session lifecycle.

## Workflow

```text
Session.initialize()
        |
        v
Session.start()
        |
        v
AcquisitionNode.start_runtime()
        |
        v
session_start envelope
        |
        v
AcquisitionNode.run_one_iteration()
        |
        v
DeviceManager.collect_records()
        |
        v
AcquisitionRecordEnvelope
        |
        v
dict round-trip
        |
        v
InMemoryIngestor
        |
        v
InMemoryStorageManager
        |
        v
AcquisitionNode.stop_runtime()
        |
        v
session_stop envelope
        |
        v
Session.stop()
        |
        v
Session.complete()
```

## Validates

- AcquisitionNode receives already-created runtime collaborators
- AcquisitionNode starts and stops Session Time through SynchronizationManager
- AcquisitionNode creates session_start and session_stop acquisition evidence
- AcquisitionNode runs bounded synchronous acquisition iterations
- AcquisitionNode attaches Session Time to untimestamped fake rows
- AcquisitionNode sends envelopes through the plain-data boundary
- Session lifecycle remains separate from acquisition execution

---

# W008 - Persistent JSONL Storage

## Purpose

Validate that accepted acquisition envelopes can cross the StorageManager persistence boundary and be read back from JSONL.

## Workflow

```text
AcquisitionNode
        |
        v
AcquisitionRecordEnvelope
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
accepted_records.jsonl
        |
        v
AcquisitionRecordEnvelope
```

## Validates

- StorageManager remains the persistence boundary
- JSONL is the v1 storage backend
- accepted envelopes are stored as plain-data dictionaries
- stored envelopes read back as AcquisitionRecordEnvelope objects
- ingest audit remains separate from acquisition records
- session_time_s and device-local timing fields are preserved

---

# W009 - Persistent Session Record Finalization

## Purpose

Validate that a completed Session can be finalized into a durable v1 Session Record evidence package.

## Workflow

```text
Session.complete()
        |
        v
finalization caller gathers evidence
        |
        v
PersistentStorageManager.write_session_record()
        |
        v
session_record.json
        |
        v
PersistentStorageManager.read_session_record()
```

## Validates

- finalization code gathers evidence from existing owners
- SessionConfig is preserved as accepted configuration evidence
- Session lifecycle and readiness evidence are preserved
- accepted acquisition envelopes are included in the Session Record
- ingest audit evidence is included separately from acquisition envelopes
- final session status and cleanup evidence are preserved
- StorageManager writes evidence without becoming a Session lifecycle owner

---

# W010 - Local Cross-Process JSONL Handoff

## Purpose

Validate that acquisition-side and ingestion/storage-side demo code can run in separate local shell processes without sharing live runtime objects.

## Workflow

```text
writer shell process
        |
        v
plain-data AcquisitionRecordEnvelope dictionaries
        |
        v
handoff.jsonl
        |
        v
reader shell process
        |
        v
AcquisitionRecordEnvelope.from_dict()
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
accepted_records.jsonl
```

## Validates

- a local JSONL handoff file can act as a demo process boundary
- acquisition-side code emits plain-data envelopes
- ingestion/storage-side code reconstructs envelopes without live acquisition objects
- Ingestor creates audit evidence for each received envelope
- StorageManager writes accepted envelopes to persistent JSONL
- session_start, stream-like, event-like, and session_stop records preserve session_time_s

---

# W011 - Localhost Socket Envelope Transfer

## Purpose

Validate that acquisition-side and ingestion/storage-side demo code can communicate live over localhost without sharing runtime objects.

## Workflow

```text
socket sender shell process
        |
        v
newline-delimited JSON AcquisitionRecordEnvelope dictionaries
        |
        v
localhost TCP socket
        |
        v
socket receiver shell process
        |
        v
AcquisitionRecordEnvelope.from_dict()
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
accepted_records.jsonl
```

## Validates

- live local process-to-process envelope transfer
- no live DeviceAdapter, DeviceManager, AcquisitionNode, or Session object crosses the boundary
- receiver reconstructs envelopes through the public plain-data API
- Ingestor creates audit evidence for received envelopes
- StorageManager writes accepted envelopes to persistent JSONL
- session_start, stream-like, event-like, and session_stop records preserve session_time_s

---

# W012 - OpenCV Camera Metadata Adapter

## Purpose

Validate that a concrete SDK-backed camera adapter can participate in the existing acquisition path without storing image data.

## Workflow

```text
SeeedIMX219OpenCVCameraAdapter
        |
        v
DeviceManager.collect_records()
        |
        v
DeviceRecordCollection
        |
        v
AcquisitionNode
        |
        v
AcquisitionRecordEnvelope
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
accepted_records.jsonl
```

## Validates

- a concrete OpenCV-backed adapter uses the existing DeviceAdapter lifecycle
- camera frames are reduced immediately to lightweight metadata records
- image arrays and encoded image bytes are not placed in acquisition envelopes
- DeviceManager collects metadata records without creating envelopes
- AcquisitionNode attaches session_time_s
- StorageManager persists metadata records through the existing JSONL boundary
- the OpenCV capture is released during adapter shutdown

---

# W013 - OpenCV Camera Metadata Over Localhost Socket

## Purpose

Validate through the automated public test suite that the framework acquisition
path can feed the live localhost socket boundary using deterministic FakeCV2
camera input.

## Workflow

```text
FakeCV2
        |
        v
SeeedIMX219OpenCVCameraAdapter
        |
        v
DeviceManager
        |
        v
AcquisitionNode
        |
        v
newline-delimited JSON socket
        |
        v
demo_socket_ingestor_receiver.py
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
```

## Validates

- the socket sender can use fake OpenCV locally without physical camera hardware
- the concrete OpenCV adapter participates through DeviceManager and AcquisitionNode
- AcquisitionNode creates session_start, camera metadata, and session_stop envelopes
- camera image arrays and encoded image bytes do not cross the socket boundary
- receiver-side Ingestor and StorageManager persist accepted metadata envelopes unchanged

This workflow does not claim automated real-hardware validation. The successful
manual MSMF laptop-webcam run is recorded separately in
`docs/local_cross_process_demo.md`.

---

# W014 - Simulated Remote AcquisitionNode Readiness

## Purpose

Validate one explicitly identified, simulated remote AcquisitionNode sending a
bounded Session to a computer-side Ingestor without defining final transport.

## Workflow

```text
simulated remote AcquisitionNode
        |
        v
AcquisitionNodeReadiness
        |
        v
DeviceManager + fake DeviceAdapter
        |
        v
AcquisitionRecordEnvelope with source_node_id
        |
        v
provisional TCP socket
        |
        v
computer InMemoryIngestor
        |
        v
computer PersistentStorageManager
```

---

Public GitHub repository
        ↓
git clone on Jetson
        ↓
uv project environment
        ↓
framework imports
        ↓
full test suite
        ↓
Phase 2 remote tests

---


## Validates

- node, session, and role identity are explicit readiness evidence
- existing device and service readiness contracts are aggregated rather than replaced
- the Phase 2 demo caller does not start acquisition when required readiness fails
- source_node_id survives the plain-data and process boundary
- Session Time survives transfer unchanged
- computer-side Ingestor audit and JSONL persistence occur
- acquisition cleanup completes after the bounded run
- refused connections produce one demo-local sender failure JSONL record and a nonzero exit
- no retry, replay, buffering, or final transport architecture is introduced

---

# W015 - Jetson-to-Computer Remote Acquisition

## Purpose

Record the first successful manual validation across two physical machines: an
NVIDIA Jetson Orin AcquisitionNode and a Windows ingestion/storage computer.

This is distinct from W011 localhost transfer and W014 simulated remote
validation on one computer.

## Workflow

```text
Jetson Orin
        |
        v
AcquisitionNode
        |
        v
DeviceManager + fake DeviceAdapter
        |
        v
SynchronizationManager
        |
        v
AcquisitionRecordEnvelope
        |
        v
plain-data socket transfer over Wi-Fi
        |
        v
Windows computer socket receiver
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
JSONL persistence
```

## Validates

- the sender and receiver run on two physical machines
- the Jetson connects successfully to the Windows receiver over Wi-Fi
- three envelopes are transmitted, received, and stored
- three ingest audit records are created
- source_node_id, session_id, and source_device_id survive transfer
- Session Time survives transfer unchanged
- sender cleanup completes successfully
- sender connection failure remains covered separately by demo-local JSONL evidence and a nonzero exit

This is a manual hardware/runtime validation, not an automated test-suite claim.

---

# W016 - Jetson USB Camera to Computer Ingestor

## Purpose

Record the first successful two-machine validation using a real USB camera on
an NVIDIA Jetson, the real OpenCV/V4L2 backend, and a Windows computer Ingestor
and StorageManager.

This is distinct from W013's automated FakeCV2 socket workflow, the manual MSMF
laptop-webcam validation, and W015's Jetson fake-adapter transfer.

## Workflow

```text
Jetson USB camera (/dev/video2)
        |
        v
OpenCV / V4L2
        |
        v
SeeedIMX219OpenCVCameraAdapter
        |
        v
DeviceManager
        |
        v
AcquisitionNode
        |
        v
AcquisitionRecordEnvelope
        |
        v
plain-data socket transfer over Wi-Fi
        |
        v
Windows computer socket receiver
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
        |
        v
JSONL persistence
```

## Validates

- a real USB camera on the Jetson is acquired through OpenCV/V4L2
- three envelopes are transmitted, received, accepted, and stored
- three ingest audit records are created
- session_start, camera_frame_metadata, and session_stop evidence persist
- two camera metadata records preserve frame shape, dtype, frame index, read status, and V4L2 backend identity
- session_time_s and device_local_time survive remote transfer
- no image arrays or encoded image payloads cross the socket boundary

This is a manual hardware/runtime validation, not an automated test-suite claim.

---

# W017 - AcquisitionNode Stream Batching v1

## Purpose

Validate count-based and Session-Time-age batching of continuous stream rows
inside AcquisitionNode without changing the envelope, ingestion, or storage
boundaries.

## Workflow

```text
DeviceManager.collect_records()
        |
        v
timestamped stream rows
        |
        v
AcquisitionNode private pending batch
        |
        +-- max_records reached --> AcquisitionRecordEnvelope
        |
        +-- max_batch_age_s reached --> AcquisitionRecordEnvelope
        |
        +-- partial batch at stop --> AcquisitionRecordEnvelope
        |
        v
InMemoryIngestor
        |
        v
InMemoryStorageManager
```

## Validates

- batching configuration comes from SessionConfig.acquisition_configuration
- type_1 batches stream rows by configured max_records
- optional max_batch_age_s flushes partial batches using SynchronizationManager Session Time
- invalid count and age settings disable only their own flush condition
- count-flush leftovers begin a new Session Time age window
- full envelopes contain exactly max_records rows
- partial rows remain pending until stop
- pending rows flush before session_stop evidence
- non-stream records continue through the immediate envelope path
- missing or invalid batching configuration preserves immediate collection behavior
- Ingestor and StorageManager continue receiving ordinary AcquisitionRecordEnvelope objects

---

# W018 - Continuous Batched Stream Demo

## Purpose

Manually validate existing AcquisitionNode batching with larger deterministic
fake streams and persistent JSONL readback.

## Workflow

```text
ContinuousFakeStreamAdapter
        |
        v
DeviceManager
        |
        v
AcquisitionNode count/Session-Time-age batching
        |
        v
AcquisitionRecordEnvelope
        |
        v
InMemoryIngestor
        |
        v
PersistentStorageManager
```

## Validates

- 1,200 fast records produce stream envelope sizes 500, 500, and 200
- 5 slow records produce age-triggered stream envelope sizes 2, 2, and 1
- the final partial batch in each scenario flushes at stop
- both scenarios use deterministic SynchronizationManager-compatible Session Time without sleeping
- each scenario persists session_start, three stream envelopes, and session_stop as JSONL

This is a manual quality/demo validation, not an additional automated test.

---

# W019 - Controller v1 Sequential Session Orchestration

## Purpose

Validate that Controller v1 replaces manual sequencing for one bounded Session while existing components retain ownership of lifecycle, runtime execution, evidence, ingest audit, and persistence.

## Normal Workflow

```text
create_session
        |
initialize_session
        |
start_session
        |
run_one_iteration
        |
stop_session
        |
finalize_session
        |
completed
```

## Validates

- Controller uses `AcquisitionNode.start_runtime()` and `stop_runtime()`
- Session enters running only after runtime start succeeds
- normal stop preserves `session_stop` evidence and moves Session to stopping
- Session Record persistence uses a stopping-state write followed by a completed-state update
- successful finalization leaves a completed Session and durable completed evidence

## Validated Failure Scenarios

- a pre-running runtime start failure leaves the Session failed without passing through running
- AcquisitionNode failed status during an iteration produces a failed command result, cleanup-capable runtime stop, and failed Session outcome
- runtime stop failure produces a failed command result and failed Session outcome
- failure of the first Session Record write leaves the Session failed rather than completed

These tests validate sequential command outcomes only. They do not define Experiment orchestration, abort semantics, retry, asynchronous execution, multi-session control, or distributed orchestration.

---

# W020 - Canonical Experiment Lifecycle Evidence

## Purpose

Validate the first Controller-owned, Session-scoped Experiment lifecycle evidence path without implementing protocol execution, expected participants, Validation, or Experiment-scoped health.

## Workflow

```text
running Session + active Acquisition Runtime
        |
Controller.start_experiment(experiment_id, details=None)
        |
Session-owned experiment_start evidence
        |
Controller.stop_experiment(experiment_id, details=None)
        |
Session-owned experiment_stop evidence
        |
two-step Session Record finalization
```

## Validates

- Experiment start is rejected before Session running
- Experiment stop is rejected when no Experiment is active
- starting a second Experiment while one is active is rejected without implicitly switching Experiments
- stopping an Experiment ID other than the active Experiment is rejected
- after the active Experiment stops, a different Experiment may start and stop normally
- canonical evidence includes `experiment_id`, `event_type`, Session Time when supplied, sequence, and optional details
- stopping an Experiment does not stop the Session or Acquisition Runtime
- persistent Session Record finalization includes canonical Experiment lifecycle evidence
- no device commands, participant enforcement, Validation, protocol execution, or AcquisitionNode-owned Experiment lifecycle are introduced

---

# W021 - Persistent Experiment Descriptors

## Purpose

Validate that each Experiment receives one Session-owned scientific descriptor, separate from its lifecycle evidence.

## Validates

- first start creates one descriptor from `experiment_id` and caller-supplied `details`
- stopping or restarting the same Experiment does not duplicate or replace its descriptor
- different Experiments receive distinct descriptors
- ordered Expected Participant declarations survive plain-data round trip and Session Record persistence
- Expected Participant evidence preserves `participant_id`, `participant_type`, `expected_contribution`, and `required`
- lifecycle evidence continues to record every successful start and stop
- persistent Session Record finalization includes Experiment descriptors
- descriptors do not bind, own, start, stop, validate, enforce, or otherwise manage live runtime resources
- descriptors do not introduce protocol schemas, lifecycle state, or timestamps

---

# W022 - Experiment-Scoped Acquisition Health Scope

## Purpose

Validate that AcquisitionNode applies its existing acquisition-health algorithm only to live sources explicitly present in the active Experiment runtime health mapping.

## Validates

- without an active Experiment runtime mapping, no participant-scoped acquisition-health evaluation occurs
- an active mapping evaluates only its mapped live source IDs
- the active mapping, rather than DeviceDeclaration, supplies each mapped source's Experiment-specific acquisition-health policy assignment
- Session-ready but unmapped sources are ignored
- mapped sources retain the existing first-record grace-window algorithm and evidence
- missing expected evidence produces an `ExperimentScopedHealthObservation` with Experiment, source, participant, contribution, policy, required status, Session Time, and audit details
- observations are inspectable on AcquisitionNode and cross the existing acquisition-envelope evidence path
- observations do not mark AcquisitionNode failed or stop Acquisition Runtime
- runtime mappings remain runtime-only and are not added to Experiment descriptors or Session Records
- no identifier inference or participant binding is introduced

---

# W023 - Acquisition-Health Observation and Policy Definition

## Purpose

Validate that Experiment-scoped health conditions remain evidence and that acquisition-health policy definitions are inspectable plain data rather than executable consequence behavior.

## Validates

- `ExperimentScopedHealthObservation` preserves detected condition evidence without assigning an operational consequence
- `AcquisitionHealthPolicy` round-trips its policy identifier, explicit evaluation parameters, and observation-to-consequence-label interpretation mapping
- policy validation accepts only supported evaluator observation names
- consequence labels are restricted to the accepted vocabulary
- policy definitions do not execute warnings, failures, Controller actions, notifications, retry, or recovery
- policy assignment remains authoritative on `ExperimentRuntimeHealthMapping`, not `DeviceDeclaration`

---

# W024 - Immediate Acquisition-Health Policy Interpretation Evidence

## Purpose

Validate the runtime evidence chain from Session-configured policy definition through Experiment-scoped assignment, Health Observation, and immediate policy interpretation.

## Validates

- `SessionConfig` owns serializable `AcquisitionHealthPolicy` definitions
- policies use named rule-specific `evaluation_rules` rather than legacy raw dictionaries
- `ExperimentRuntimeHealthMapping` assigns a configured policy by `policy_id`
- AcquisitionNode evaluates the assigned `first_evidence` rule for mapped live sources
- each emitted `ExperimentScopedHealthObservation` receives a runtime-unique `observation_id`
- exactly one immediate `HealthInterpretationEvidence` references that ID through `originating_observation_id`
- configured interpretation labels are preserved
- a missing interpretation entry produces `uninterpreted`
- observation and interpretation evidence cross the existing acquisition-envelope path
- interpretation evidence does not stop Acquisition Runtime or mark AcquisitionNode failed
- no Controller action, lifecycle consequence, retry, recovery, notification, or orchestration is introduced

---

# Future Workflows

The following workflows are expected to be added as the framework evolves.

## Planned

- Reconstruction
- NWB export
- Multi-node acquisition
- Hardware synchronization
- Device file transfer
- Validation reports

These sections should only be added after the corresponding public workflow has been implemented and validated.
