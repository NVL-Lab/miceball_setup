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

The socket and acquisition-envelope workflows below remain valid historical demonstrations of implemented boundaries. They are not the accepted Phase 10 runtime transport architecture: Phase 10 adopts brokered NATS communication, keeps large scientific artifacts local during acquisition, and has not yet been implemented or validated.

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

Phase 11 clarifies the current ownership behind this earlier Phase 1 workflow:
SynchronizationManager remains the sole Session Time owner, and AcquisitionNode
now fulfills the former acquisition-side caller role by attaching framework
scientific timing. DeviceAdapters do not know Session Time or apply timing
mappings. This clarification does not claim Phase 11 synchronization behavior
has been implemented or validated.

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
- AcquisitionNode attaches Session Time, monotonic AcquisitionNode local time, and `runtime_timestamped` status to rows it timestamps
- Controller hands active Experiment identity and canonical start Session Time to AcquisitionNode separately from the runtime health mapping
- AcquisitionNode derives Experiment Time only while that Experiment context is active
- DeviceAdapter-produced rows remain unaware of Session Time, Experiment Time, and timing mappings
- SynchronizationManager creates, replaces, retires, and exposes immutable active mappings per AcquisitionNode
- SynchronizationManager preserves mapping creation, replacement, and retirement evidence in memory
- MappingUpdateEvidence converts to the existing durable RuntimeEvidenceMessage boundary with evidence type `mapping_update_evidence` and its complete plain-data payload
- AcquisitionNode passively replaces its active mapping reference without creating, validating, or applying mapping mathematics
- acquired rows retain Slice 1 timing fields without a per-row mapping identifier
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
- historical Controller v1 Session Record persistence uses a stopping-state write followed by a completed-state update
- historical successful finalization leaves a completed Session and durable completed evidence

## Validated Failure Scenarios

- a pre-running runtime start failure leaves the Session failed without passing through running
- AcquisitionNode failed status during an iteration produces a failed command result, cleanup-capable runtime stop, and failed Session outcome
- runtime stop failure produces a failed command result and failed Session outcome
- failure of the first Session Record write leaves the Session failed rather than completed

These tests validate sequential command outcomes only. They do not define Experiment orchestration, abort semantics, retry, asynchronous execution, multi-session control, or distributed orchestration.

This preserves the original Phase 4 validation claim. Current Phase 13
finalization writes the separate Evidence Archive and final Session Record before
`Session.complete()`. W019 does not establish that the current final record is a
post-completion terminal snapshot; that representation remains for separate
review, and Q019's evidence-consumption coordination remains open.

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
historical Controller v1 two-step Session Record finalization
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

**Current architecture clarification:** The diagram records the historical
canonical lifecycle workflow, not the full current `start_experiment()`
signature or preparation path. Slice 20 adds scientific-output preparation
before canonical start. Decision 239 requires confirmed successful required
preparation and persistent `experiment_start_rejected` evidence for pre-start
rejection, not `experiment_fail`. Its optional-preparation and missing-result
rules are now implemented in Slice 21 but are not validated by this historical
W020 workflow. W030 separately records the completed Slice 21 manual validations
and independent audit reassessment.

---

# W021 - Persistent Experiment Descriptors

## Purpose

Validate that each Experiment receives one Session-owned scientific descriptor, separate from its lifecycle evidence.

## Validates

- first start creates one descriptor from `experiment_id` and caller-supplied `details`
- stopping an Experiment does not duplicate or replace its descriptor; repeating its configuration requires a new Experiment identity
- different Experiments receive distinct descriptors
- ordered Expected Participant declarations survive plain-data round trip and Session Record persistence
- Expected Participant evidence preserves `participant_id`, `participant_type`, `expected_contribution`, and `required`
- lifecycle evidence continues to record every successful start and stop
- persistent Session Record finalization includes Experiment descriptors
- descriptors do not bind, own, start, stop, validate, enforce, or otherwise manage live runtime resources
- descriptors do not introduce protocol schemas, lifecycle state, or timestamps

**Architecture clarification:** Earlier validation permitted same-identity
restart. Decision 238 now requires a new Experiment
identity for every execution after a terminal outcome, even without recorded
data. It supersedes that restart assumption, not the historical validation
record. Session/Controller terminal-identity enforcement is now covered by
automated tests, including metadata-only executions and new-identity repeats.
The user reported Step 4 manual validation complete; the comprehensive Slice 20
audit subsequently identified data-integrity defects. Corrective regression
tests cover partial-data preservation, frame associations, and JSONL accounting.
Slice 20 is now complete following corrective work, four successful independent
manual software validations, automated regression tests, and the reported
Jetson scientific-camera acquisition and visual inspection recorded in W029.

**Slice 21 clarification:** Decision 239 does not add rejection history to
Session or convert a rejected preparation attempt into an Experiment execution.
The current start path prepares outputs before ensuring the descriptor and
recording canonical start. Rejection evidence belongs to the existing
runtime Evidence Archive, separate from descriptors and lifecycle evidence.
W021's historical descriptor validation does not validate Slice 21; W030
separately records its completed validation.

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

# W025 - Evidence-Only Controller Action Decisions

## Purpose

Validate that Controller maps explicitly presented Health Interpretation Evidence to one inspectable action decision without executing framework consequences.

## Validates

- `Controller.process_health_interpretation()` accepts exactly one explicitly supplied interpretation record
- each presentation records and returns exactly one `ControllerActionDecision`
- informational and uninterpreted evidence map to `record_only`
- warning evidence maps to `record_warning`
- recoverable-failure evidence maps to `record_recoverable_failure`
- Experiment-failure evidence maps to `experiment_fail`
- Session-failure evidence maps to `session_fail`
- decisions preserve Session, Experiment, source, policy, interpretation, and originating-observation provenance
- Controller exposes decisions in presentation order through a read-only tuple
- `record_only`, `record_warning`, `record_recoverable_failure`, and `operator_required` execute successfully without lifecycle mutation
- no polling, callback, delivery mechanism, retry, recovery, notification, aggregation, or distributed orchestration is introduced

---

# W026 - Controller Failure-Decision Execution

## Purpose

Validate Phase 8b execution of Experiment- and Session-failure ControllerActionDecisions through existing lifecycle owners.

## Validates

- `Controller.execute_controller_action_decision()` executes accepted failure decisions explicitly
- `experiment_fail` decisions record canonical `experiment_fail` Session-owned evidence
- Experiment failure ends the active Experiment and clears Controller and AcquisitionNode runtime health mappings
- Experiment failure leaves Session and Acquisition Runtime running
- `session_fail` decisions use the existing runtime cleanup and failed-Session path
- Session failure stops and shuts down devices through existing cleanup behavior
- normal `experiment_stop` remains normal completion evidence
- `experiment_abort` and generic Experiment end reasons are not introduced
- no notification, retry, recovery, distributed delivery, aggregation, polling, callback, or event bus is introduced

---

# W027 - Brokered NATS Runtime Communication

## Purpose

Manually validate the first real brokered runtime path against a local JetStream-enabled NATS server without changing domain ownership or introducing communication recovery behavior.

## Workflow

```text
Controller communication client
        |
RuntimeCommandMessage through JetStream
        |
AcquisitionNode communication consumer
        |
existing start_runtime / run_one_iteration / stop_runtime behavior
        |
RuntimeCommandResultMessage through JetStream
        |
Controller command-result consumer

AcquisitionNode RuntimeEvidenceMessage
        |
JetStream evidence stream
        |
Ingestor runtime-evidence intake and audit

RuntimeTelemetryMessage
        |
Core NATS only
        |
monitoring subscriber
```

## Validates

- command, command-result, and evidence messages use their separate accepted JetStream streams
- one Session-scoped AcquisitionNode consumer receives and executes `start_runtime`, `run_one_iteration`, and `stop_runtime`
- three commands produce three successful explicit command results
- JetStream publication acknowledgement remains separate from command success
- duplicate detection remains local and keyed by `command_id`
- one durable runtime evidence message reaches separate Ingestor evidence intake and audit
- expected runtime participants persist in SessionConfig and distributed readiness uses existing readiness evidence
- required NATS communication readiness participates in the existing Session initialization gate
- failed durable publication reports `DurablePublicationError` context without retry, buffering, or local persistence
- Controller and Ingestor independently consume the same durable health-interpretation evidence without relay or republish
- Controller uses its existing `process_health_interpretation()` behavior for distributed decision-relevant evidence
- one transient telemetry message crosses Core NATS without a JetStream telemetry stream
- telemetry remains non-authoritative and produces no lifecycle or persistence effects
- artifact manifests use `RuntimeEvidenceMessage` and `LAB_EVIDENCE` as lightweight artifact-level evidence
- Ingestor audits artifact manifests without treating them as acquisition envelopes
- artifact bytes do not cross NATS and no artifact-transfer backend is introduced
- unique demo Session identity and Session-scoped command consumption prevent stale cross-Session replay
- one group command intent fans out to configured members of one explicit component group, with one result per executing target
- the issuer aggregates returned group results and records missing expected readiness responses as unresolved rather than failed
- NATS and target components do not aggregate group outcomes
- Session Time and lifecycle behavior remain owned by existing domain components
- no reconnect, retry/replay policy, buffering architecture, broker/target-side aggregation, artifact transfer, clock synchronization, or new lifecycle semantics are introduced

The brokered command, readiness, group-command, unresolved-outcome, independent evidence-consumer, artifact-manifest, and telemetry paths were manually validated against a real local JetStream server. This remains a manual validation rather than an automated live-server test required by the normal test suite.

The artifact-manifest bullets above validate the Phase 10 transport and intake path only. Phase 12 Decisions 178-218 assign authoritative local ArtifactManifest ownership to LocalStorageManager, whose local stream lifecycle is now implemented separately. This historical brokered workflow does not validate local scientific collection or HDF5 persistence.

---

# W028 - Persistent Runtime Evidence in Evidence Archive

## Purpose

Validate that Controller finalization gathers Ingestor-owned durable runtime evidence and runtime-evidence audit records into the separate Phase 13 Evidence Archive without changing acquisition-envelope storage.

## Validates

- accepted `RuntimeEvidenceMessage` records persist in `evidence/runtime_evidence.jsonl`
- `RuntimeEvidenceAuditRecord` intake evidence persists separately in `evidence/ingest_audit.jsonl`
- artifact manifests remain lightweight runtime evidence and introduce no artifact bytes or transfer behavior
- accepted acquisition envelopes and their ingest audit remain unchanged and separate
- StorageManager writes evidence supplied by the finalization caller without taking runtime-evidence ownership
- no Session or Experiment lifecycle semantics, retry, replay, reconnect, or buffering behavior changes

This workflow validates persistence of the runtime-evidence representation. It does not validate the separately implemented Phase 12 LocalStorageManager, authoritative local ArtifactManifest lifecycle, or LocalStorageCompletionSummary, nor the future global collection path.

---

# W029 - Slice 20 Jetson Scientific Camera HDF5 Validation

**Status:** Completed - Slice 20

## Purpose

Record the user-reported successful end-to-end NVIDIA Jetson hardware validation
using `scripts/manual_opencv_camera_smoke.py`, separately from simulated tests.

## Workflow

```text
Controller
    -> AcquisitionNode
    -> DeviceManager
    -> OpenCVCameraAdapter
    -> LocalStorageManager
    -> finalized HDF5 artifact and ArtifactManifest
    -> closed acquisition resources
    -> HDF5 reopening and validation
    -> read-only recorded-frame visualization
```

Real camera frames remained local scientific data; they were not sent through
Ingestor. Canonical Experiment lifecycle, framework timestamp ownership, stream
preparation, local persistence, and manifest ownership retained their existing
boundaries.

## Hardware validation

The reported Jetson scientific acquisition passed with:

- 10-second acquisition
- 256 recorded frames
- frame shape `(480, 640, 3)` (640 x 480 pixels, three channels)
- frame dtype `uint8`
- frame indices 0-255
- successful HDF5 persistence and reopening
- finalized artifact and manifest
- `validation=PASS`

The subsequent visualization test also succeeded on the Jetson: recorded HDF5
frames were displayed and visually inspected using the existing script.

## Commands

Scientific acquisition and validation from the repository root:

```bash
python scripts/manual_opencv_camera_smoke.py 0 --scientific --duration 10 --width 640 --height 480 --output-dir ./camera_smoke_output
```

Scientific acquisition with post-validation visual inspection:

```bash
python scripts/manual_opencv_camera_smoke.py 0 --scientific --duration 10 --width 640 --height 480 --output-dir ./camera_smoke_output --show-frames
```

Separate read-only inspection of the resulting recording:

```bash
python scripts/manual_opencv_camera_smoke.py --view-hdf5 /path/to/recorded/frames.h5
```

Use the validated camera source/backend for the target Jetson; `0` is the script's
default camera index. Replace the illustrative recording path with the actual
`artifact_path` printed by acquisition. Visualization requires optional
Matplotlib. Without a graphical display it saves a PNG contact sheet beside the
recording; the reported Jetson run successfully displayed the frames.

## Software validation

- Four independent manual software validations passed.
- Full automated suite with optional Matplotlib dependencies: 284 passed.
- Supported Python 3.12 suite: 277 passed, seven optional rendering tests skipped.

Automated camera tests use simulated hardware and are not the Jetson hardware
validation. The hardware acquisition and subsequent visual inspection were
performed separately and reported by the user. These are recorded results, not
new test executions during this documentation update.

## Completion

Slice 20 is complete. At its closure, the next implementation phase remained
for the architecture chat to determine; this workflow introduces no new
architecture or future implementation requirements.

---

# W030 - Slice 21 Pre-start Experiment Preparation Failure

**Status:** Completed - Slice 21

## Purpose

Record three successful, user-reported independent manual IPython validations
using existing public framework workflows and test fixtures, the focused
automated audit results, and the subsequent independent audit reassessment.

## Workflow

```text
Required preparation and caller-collected remote outcomes
    -> Controller start gate
    -> confirmed required success: canonical experiment_start
    -> required failure or unresolved outcome: rejected command result
        -> persistent experiment_start_rejected RuntimeEvidenceMessage
        -> Ingestor intake, audit, and persistent evidence compilation
        -> StorageManager Evidence Archive writing
```

AcquisitionNode reports preparation outcomes; Controller orchestrates lifecycle
and Session records canonical lifecycle evidence. LocalStorageManager retains
stream, artifact, manifest, and local persistence diagnostic ownership.
Distributed preparation uses caller-managed orchestration: the caller collects
remote results through the existing communication boundary and supplies the
outcome to Controller. These validations are not a live NATS broker end-to-end
test and do not establish automatic remote preparation inside start_experiment.

## Manual IPython validation

Three independent scenarios passed:

1. **Required scientific preparation failure:** An unknown required scientific
   product rejected start without creating an active Experiment. The Session
   remained running; one persistent rejection matching the generated evidence
   was archived. No Experiment lifecycle events were recorded, and Session
   finalization succeeded.
2. **Optional preparation failure:** An optional service reported unavailable
   while required preparation succeeded. Experiment start succeeded without
   rejection evidence; normal experiment_start and experiment_stop events were
   recorded. The Session Record preserved the optional failure, and Session
   finalization succeeded.
3. **Missing required distributed response:** A required remote participant
   returned no preparation result. The supplied aggregate remained unresolved
   with the original command ID and unresolved reason preserved. Start was
   rejected without an active Experiment; the Session remained running.
   Exactly one matching rejection was archived, no Experiment lifecycle events
   were recorded, and Session finalization succeeded.

These are completed manual validations reported by the user, not proposed
tests or newly executed validations during documentation synchronization.

## Automated validation

The focused independent audit executed:

```text
python -B -m unittest tests.test_experiment_start_rejection tests.test_scientific_output_preparation tests.test_controller tests.test_nats_communication tests.test_experiment_scientific_finalization
```

Result: **62 tests passed.** The full suite was not rerun during the audit.
Automated tests are deterministic software checks, distinct from manual IPython
validation and live broker or camera hardware validation.

## Completion

Independent audit reassessment concluded CONDITIONAL PASS with documentation
synchronization as the only remaining closure requirement. That synchronization
is complete; Slice 21 is closed and M009 records the milestone.

Session Record failure diagnostics are legitimate under Decisions 073 and 226.
The complete rejection message currently appears twice within the Session
Record, while one matching message is archived. This is a minor, nonblocking
representation observation, not an architectural violation. Simplifying those
copies while retaining diagnostics and adding a composed distributed-preparation
test using existing NATS broker doubles are optional future improvements;
neither is required for closure. Additional live NATS validation is not required.

---

# W031 - Phase 14 / Slice 22 Artifact Collection Handoff

**Status:** Completed - Slice 22 (M010)

## Purpose

Record successful implementation, manual IPython validation, and independent
audit of Decisions 240-244 without claiming artifact-byte retrieval or global
collection.

## Workflow

```text
LocalStorageManager creates the artifact and authoritative initial manifest
    -> AcquisitionNode produces persistent artifact_manifest RuntimeEvidenceMessage
    -> existing local intake or NATS evidence publication to an independent Ingestor
LocalStorageManager finalizes the artifact and authoritative manifest
    -> AcquisitionNode produces finalized manifest evidence with the same identity
Ingestor retains runtime evidence
    -> Session-scoped compilation groups by artifact_manifest_id
    -> one complete finalized manifest per artifact when available
    -> otherwise initial manifest with missing_finalization_evidence=True
Controller.finalize_session()
    -> obtains the separate artifact_collection_handoff in command-result details
    -> preserves existing Evidence Archive and Session Record finalization behavior
```

LocalStorageManager remains the authoritative artifact and manifest owner.
Complete manifest serialization preserves Session, Experiment, AcquisitionNode,
and artifact identities. The handoff is separate from the Session Record and
Evidence Archive; no handoff persistence product or artifact-byte transfer is
introduced. Controller obtains information for later collection, not confirmation
that artifacts have been globally collected.

## Manual IPython validation

The implementation coordinator reported all five scenarios passing:

1. **Normal artifact lifecycle - PASS:** Initial and finalized manifest evidence
   preserved stable artifact identity. Compilation returned one entry containing
   the complete finalized authoritative manifest.
2. **Missing finalization - PASS:** Compilation retained the complete initial
   manifest, explicitly reported missing finalization, and invented no metadata.
3. **Controller integration and persistent outputs - PASS:** The finalization
   result exposed the correct Session/artifact handoff while existing Session
   Record and Evidence Archive outputs remained intact and separate.
4. **Explicit NATS publication with broker double - PASS:** Caller-managed local
   operations used explicit publication of newly produced initial/finalized
   evidence through the existing JetStream boundary. Repeated publication did
   not duplicate already successfully published messages on the same adapter.
5. **Subscribed-command publication with broker double - PASS:** The existing
   composed workflow exercised automatic publication after subscribed commands
   and independent Ingestor consumption. This interactively invoked an existing
   automated workflow; it was not independent live-broker validation.

Manual checks used existing fixtures and simulated devices. Broker doubles do
not establish live NATS connectivity or durability.

## Automated tests and independent audit

- Implementation full suite: **290 passed, seven optional rendering tests skipped**.
- Independent audit: **72 focused tests passed**.
- Audit verdict: **PASS**; Decisions 240-244 satisfied; no blocking defects found.

The focused audit command was:

```text
python -B -m unittest tests.test_artifact_collection_handoff tests.test_controller tests.test_experiment_start_rejection tests.test_scientific_output_preparation tests.test_nats_communication tests.test_experiment_scientific_finalization tests.test_storage
```

These are previously executed or reported results. No tests or manual validations
were run during this documentation closure. The full suite was not rerun during
the independent audit.

## Limitations and completion

Slice 22 and M010 are complete for the artifact collection handoff only.
No artifact-byte retrieval or global collection, live NATS validation, hardware
acquisition validation, Ingestor restart recovery, or diagnostic association/
compilation is included. Future Artifact Plane retrieval and restart-recovery
roadmap placement remain open questions.

**Later architecture clarification:** Decisions 276-280 place known-Session
Ingestor journal recovery in completed Slice 27 (M014), with independent manual
software validation and corrected targeted re-audit PASS recorded separately in W034.
This does not extend W031's historical validation or change its handoff semantics.
Application-wide recovery/journal lifecycle remain Q024; evidence drain remains Q019.

Additional real two-node coverage, manifest-specific publication-failure checks,
and malformed-manifest failure tests were nonblocking audit suggestions, not new
architectural requirements or prerequisites for closure.

---

# W032 - Phase 14 / Slice 24 Light Verification of Globally Copied Artifacts

**Status:** Completed - Slice 24 (M012)

## Purpose

Record implementation, final automated validation, six independent manual
IPython scenarios, and corrected independent re-audit PASS for Decisions 261-270.
This validates the software verification contract, not real Jetson/SSH-SFTP
deployment behavior. M011 remains open for that separate deployment validation.

## Workflow

```text
LocalStorageManager persists the authoritative artifact and ArtifactManifest
    -> existing Ingestor artifact-collection handoff
    -> Controller.collect_session_artifacts()
    -> StorageManager pulls one artifact per manifest through the Artifact Plane
    -> closes the temporary destination and publishes the deterministic global copy
    -> bounded, read-only verification of the completed global copy
    -> separate per-artifact retrieval and verification outcomes
    -> aggregate result returned without new Session lifecycle consequences
```

The current framework HDF5 contract applies when manifest details declare
`storage_format="hdf5"` and `external_artifact_path` is absent. External HDF5,
even with a compatible layout, and unsupported formats remain copied_unverified.
Checks use file accessibility/nonzero byte size, read-only HDF5 opening, embedded
artifact identity, shapes of the seven current datasets (`frames`,
`session_time_s`, `experiment_time_s`, `acquisition_node_local_time_s`,
`frame_index`, `timestamp_status`, `record_metadata_json`), and existing persisted
counts. Finalized manifest counts are compared only when authoritative finalization
evidence exists. Zero-record artifacts are valid; zero-byte files are not.

Retrieval failure has no verification outcome. HDF5 structural rejection without
underlying operational file-access failure is structurally_invalid; genuine
operational access/read failure preventing a conclusion is verification_failed.
Classification does not depend on a whitelist of HDF5 diagnostic strings.
Invalid or inconclusive verification preserves the completed copy. Aggregate
success requires every requested artifact to retrieve successfully and be verified;
empty collections retain the existing successful result.

## Independent manual IPython validation

All six independently designed scenarios were reported PASS:

1. **Normal current framework HDF5:** Retrieval succeeded, verification was
   verified, and aggregate succeeded was True. The deterministic copy existed,
   source and copied bytes were preserved, and no incomplete transfer remained.
2. **Valid zero-record HDF5:** Verification was verified and aggregate succeeded
   was True, distinguishing zero records from a zero-byte file.
3. **Three independent structural defects:** Missing required dataset, embedded
   identity mismatch, and dataset-length mismatch all copied successfully and
   were structurally_invalid. Aggregate succeeded was False, all copies were
   preserved, and artifact attempts remained independent.
4. **Invalid HDF5 versus operational failure:** Invalid bytes were
   structurally_invalid; simulated PermissionError was verification_failed.
   Both retrievals succeeded, both copies were preserved, and aggregate succeeded
   was False.
5. **Applicability boundary:** Unsupported JSONL and external HDF5 deliberately
   matching the current framework layout both copied successfully but remained
   copied_unverified, with aggregate succeeded False. Slice 23 external source
   selection remained intact.
6. **Missing finalization and independent retrieval failure:** Initial-only
   framework HDF5 verified using its valid embedded count despite a contradictory
   non-authoritative manifest count; no finalized count was invented. Another
   artifact's retrieval failed and received no verification outcome. Aggregate
   succeeded was False.

These were local framework software scenarios with simulated retrieval boundaries,
not real Jetson, SSH/SFTP server, or hardware acquisition validation.

## Automated validation

- Focused Slice 24 verification: **26 passed**.
- Slice 23 retrieval/handoff regressions: **21 passed**.
- Full suite: **340 run, 333 passed, 7 optional rendering skips, 0 failures**.
- The real current-layout corrupt-header regression also passed independently;
  it is included in the 26 focused tests, not an additional test in that count.
- Final test and independent reproduction processes exited normally with code 0;
  no native crash was observed in final validation.

These are previously executed/reported results. No tests, reproduction, or manual
validation were run during this documentation closure.

## Independent audit history

The initial independent audit returned **FAIL**: Decision 263 was partially
satisfied because a diagnostic-text whitelist misclassified the legitimate
corrupt-header diagnostic `bad byte number in an address` as verification_failed.

The correction removed that whitelist and classified failure by underlying I/O
provenance. A regression used a real current-layout artifact with a corrupted
HDF5 header. The targeted independent re-audit returned **PASS**, independently
reproducing the original diagnostic and confirming the public collection result:
retrieval success, structurally_invalid verification, and a preserved global copy.
Genuine operational failures remained verification_failed; verification remained
bounded/read-only, with no architectural expansion or regression.

Decision 263 is satisfied. No blocking or nonblocking implementation findings
remain from the final re-audit, and no further implementation change is required
before Slice 24 closure.

## Limitations and completion

Slice 24 and M012 are complete for Decisions 261-270's software contract.
M011 remains open pending real Jetson/SSH-SFTP deployment validation.
No checksum, full-file/scientific scan, arbitrary or external HDF5 validation,
scientific-correctness claim, repair, transformation, NWB conversion, retry,
replay, recovery, or new Session lifecycle policy is included.

Decision 303 subsequently resolves Q017: later global processing failure cannot
retroactively change a completed Session's lifecycle. This is an architecture
clarification, not additional validation performed for W032. Required
pre-completion cleanup/persistence and Q019 remain unchanged. Broader product/layout
contracts and
deeper verification remain open in Q020; durable operational evidence and
retry/resume remain in Q021, and source-existence/reachability policy in Q023.
Software closure does not resolve those future architectural questions.

---

# W033 - Phase 14 / Slice 25 Post-session Global Artifact Collection Evidence

**Status:** Completed - Slice 25 (M013)

## Purpose

Record completed implementation of Decisions 271-275, independent manual
software validation, correction of the initial audit's two blockers, and final
independent re-audit PASS. This validates the collection-evidence software
contract, not real Jetson/SSH-SFTP deployment or a Session-wide evidence drain.

## Workflow

```text
Controller.stop_session()
    -> scientific acquisition ends; Session is stopping; Session Time freezes
    -> await Controller.collect_session_artifacts_with_evidence()
    -> StorageManager independently retrieves and lightly verifies artifacts
    -> one compiled persistent RuntimeEvidenceMessage for the completed pass
    -> existing durable evidence publication
    -> generic Ingestor intake and persistent compilation when consumed
    -> Controller.finalize_session()
    -> existing Evidence Archive and final Session Record writing
    -> Session completion
```

StorageManager, not Controller, constructs and publishes
`global_artifact_collection_evidence` with `is_persistent=True`. The existing
envelope preserves Session and StorageManager source identity plus evidence ID.
Payload fields are only `started_at`, `finished_at`, and `artifact_results`.
The timestamps use ordinary operational wall-clock time and cover collection
and verification, not scientific Session/Experiment time.

Each attempted artifact result contains `artifact_manifest_id`, `experiment_id`,
`acquisition_node_id`, `artifact_type`, `collection_status`, `verification_status`,
`global_artifact_locator`, `file_size_copied`, and `failure_information`.
Identity/type come from the authoritative manifest/handoff. Collection uses
`success` / `failure`; verification independently uses `verified`,
`copied_unverified`, `structurally_invalid`, or `verification_failed`.
Failed retrieval has null verification, locator, and size. No aggregate evidence
status, duplicate manifest, invented unattempted result, or separate archive is
introduced. Empty completed passes publish one record with `artifact_results=[]`.

Collection while acquisition is running is rejected. Finalization rejects an
already-active collection/publication operation without waiting or lifecycle
mutation. Overlapping collection is rejected; the original operation's guard
is released in `finally` after success, failure, or cancellation. Ending an
individual Experiment does not initiate Session-wide collection. Collection
does not change acquisition/Experiment outcomes, local finalization, scientific
Session Time, or scientific Session-success policy.

## Independent manual IPython validation

The following results were reported from independent local software validation
using genuine framework objects/artifacts and simulated publication/retrieval
boundaries, not real Jetson, SSH/SFTP server, or live NATS validation:

1. **Scenario 1 - PASS: successful multi-artifact collection.** Two genuine
   framework HDF5 artifacts were attempted and appeared in exactly one persistent
   compiled publication. Both were success + verified with correct identities,
   locators, copied sizes, wall-clock bounds, and the three-field payload without
   aggregate evidence status. The broker first accepted without delivery, leaving
   zero Ingestor persistent records. Delivery of the same already-published message
   through the generic NATS/Ingestor callback produced one persistent record.
2. **Scenario 2 - PASS: mixed outcomes.** Retrieval failure for the first artifact
   yielded failure and null verification/locator/size. The second copied successfully
   but was structurally_invalid; its global copy remained present. Both were
   attempted and represented in one compiled evidence record.
3. **Scenario 3 - PASS: durable publication failure.** Retrieval/verification
   completed success + verified; one publication attempt raised
   DurablePublicationError without retry. The completed copy and correct copied
   size remained intact.
4. **Scenario 4 - PASS: acquisition-end/finalization boundary.** Running-Session
   collection was rejected. stop_session() froze scientific Session Time and
   entered stopping. An empty pass published one persistent record and left the
   Session stopping; later finalization completed without advancing Session Time.
   The broker deliberately did not deliver the publication, so Ingestor retained
   zero records and the archive contained no collection evidence. This demonstrates
   unresolved Q019; it does not establish a consumption guarantee.
5. **Scenario 5 - PASS: corrected P1.** A controlled publisher remained pending.
   finalize_session() returned `RuntimeError: Artifact collection/publication is
   in progress`; the Session remained stopping and scientific Session Time frozen.
   After release, collection succeeded, still leaving the Session stopping, and
   finalization then completed normally with Session Time still frozen.
6. **Scenario 6 - INCONCLUSIVE.** The initial P2 challenge wrapped the SFTP output
   rather than the actual temporary destination whose position the corrected code
   reads. This was an invalid failure-injection target, not failed implementation
   validation.
7. **Scenario 6B - PASS: corrected P2.** The first of two genuine framework HDF5
   artifacts used a temporary destination whose tell() raised OSError. It remained
   success + verified with null copied size and failure information; its copy
   was preserved. The second was still attempted, succeeded + verified, retained
   its copy, and reported size 91496. Both appeared in one evidence record and
   the aggregate collection remained successful.

## Automated validation

- Slice 25 focused tests: **18 passed**.
- Slice 23 retrieval/handoff regressions: **21 passed**.
- Slice 24 verification regressions: **26 passed**.
- Controller/communication/Evidence Archive regressions: **47 passed**.
- Full discovery: **358 total, 351 passed, 7 optional rendering skips, 0 failures**.

These are previously executed/reported implementation and independent re-audit
results. No tests, manual validation, or new audit were run during this closure.

## Independent audit history

The initial audit returned **FAIL** with exactly two blocking findings:

- **P1:** Finalization could overtake pending collection evidence publication.
  Controller-local active-operation protection now rejects finalization and
  overlapping collection, with deterministic release on success/failure/cancellation.
- **P2:** An unprotected destination Path.stat() for copied size could abort the
  pass before later attempts. Size now comes from the temporary output's byte
  position; supported position failures yield null size without changing actual
  outcomes, removing the copy, or stopping subsequent attempts.

Targeted manual validations passed. The final code-first independent re-audit
returned **PASS**, found P1 and P2 **FIXED**, and found Decisions 271-275
**SATISFIED**. No blocking finding, new blocking race, guard-cleanup defect,
public API signature change from the corrections, or Slice 23/24 regression
remained. The two existing public async collection APIs were assessed as
acceptable/minimal. No further implementation change was required for closure.

## Limitations and completion

Slice 25 and M013 are complete. M011 remains open pending real Jetson/SSH-SFTP
deployment validation; M012 remains complete.

**Q019 remains OPEN:** durable publication is not Ingestor consumption. The guard
only prevents finalization from overtaking an already-started collection/publication
operation. It does not prove that published evidence has been consumed/accepted
before archive compilation. The workflow above records generic archive inclusion
when evidence has been consumed; it does not promise automatic drain or delivery.

No consumer-ACK waiting, polling, sleeps/delays, expected-count assumptions, new
broker protocol, retry/replay/resume, background collection, checksum/deep
verification, new archive/transport, reconstruction/export, or new Session or
Experiment outcome policy was included in this historical validation. Decision 303
subsequently resolves Q017 by preserving completed Session lifecycle despite later
global processing failure; no new validation is claimed here. Closure does not
resolve Q019 or other deferred architecture.

---

# W034 - Phase 14 / Slice 27 Ingestor Crash Recovery and Handoff Reconstruction

**Status:** Completed - Slice 27 (M014)

## Purpose

Record the implemented and validated known-Session Ingestor recovery contract
of Decisions 276-280, including Decision 276's uncertain-durability clarification,
the initial audit FAIL, the minimal integrity correction, independent manual
validation, and final targeted independent re-audit PASS.

## Workflow

```text
RuntimeEvidenceMessage arrives at Ingestor
    -> validate identity/content and evidence_id deduplication
    -> append complete new message to the Ingestor recovery journal
    -> flush/fsync durable boundary reports success
    -> update normal accepted runtime-evidence working view
    -> application callback where applicable
    -> ACK broker delivery

Restart for the same known Session with an existing recovery journal
    -> validate/stage complete journal history
    -> omit/repair only a clearly interrupted final append
       (corrupt completed history fails startup instead)
    -> reconstruct normal accepted evidence and evidence_id deduplication knowledge
    -> journal/accept persistent ingestor_recovery_evidence through normal intake
    -> resume broker intake
    -> identical redelivery converges as already_accepted and is ACKed
```

Configure `InMemoryIngestor(session_id=..., recovery_journal_path=...,
component_id=...)` with an explicit known Session and caller-chosen path in an
existing parent directory. `NatsIngestorCommunication.subscribe_evidence()`
requires matching Session journal configuration. Legacy local in-memory use
remains separate from broker intake.

The journal contains complete accepted RuntimeEvidenceMessages, both persistent
and nonpersistent. It is temporary crash-recovery state, not the Evidence Archive,
Session Record, ingest audit, database, or a replacement for JetStream.
`compile_persistent_runtime_evidence()` still selects messages only through
`is_persistent`; journaling does not turn nonpersistent messages into permanent
evidence. Restored messages feed the existing
`compile_artifact_collection_handoff()` without a special reconstructed handoff.
Original intake-audit timestamps are not reconstructed; startup creates recovered
intake audit records at reconstruction time.

Same evidence_id and canonical content is already accepted: no new journal append,
working-state entry, or application callback, and broker redelivery is ACKed.
Conflicting same-ID content is an error, never an overwrite or successful ACK.

Reported append/durability failure prevents live accepted-state/audit update,
application callback, and ACK, and fails closed for further new intake until
restart. The durable outcome is uncertain: a reported failure does not prove
that complete bytes were lost. On restart, complete valid surviving journal
entries are authoritative, even after a prior reported fsync error. Genuine
interrupted final bytes may be removed; corrupt completed history is fatal.
Staging prevents exposure of a partially reconstructed working view.

Successful reconstruction generates one persistent `ingestor_recovery_evidence`
record for that startup through normal journaled acceptance. Its existing
envelope preserves Session/Ingestor identity; payload records recovered-entry
count before adding recovery evidence and ordinary operational wall-clock time,
not scientific Session Time or copies of recovered IDs/content.

## Independent manual IPython validation

These results were reported from independent software validation using the
current framework and actual NATS/Ingestor callback path with controlled delivery
and failure injection. They do not establish live JetStream server crash/recovery
or hardware deployment validation.

1. **Scenario 1 - PASS:** Journal-before-ACK on the NATS callback path. Injected
   durability failure produced no ACK, accepted working state, or acceptance
   audit; Ingestor became unready/fail-closed.
2. **Scenario 2 - PASS:** Crash-window/restart/redelivery convergence. Original
   evidence was reconstructed, recovery evidence generated, and identical
   redelivery ACKed as already_accepted without duplicate journal/application
   processing; persistence intent was preserved.
3. **Scenario 3 - PASS:** Clearly interrupted final append was omitted/repaired;
   completed corruption caused reconstruction failure, not partial continuation.
4. **Scenario 4 - PASS:** Conflicting same-ID content raised an error without ACK,
   journal/state replacement, or callback; original accepted content survived.
5. **Scenario 5 - PASS:** Restored initial/finalized artifact-manifest evidence
   produced the same Slice 22 handoff as uninterrupted operation; recovery
   evidence did not alter finalized-manifest selection.
6. **Original Scenario 6 - ARCHITECTURAL AMBIGUITY DISCOVERY:** Real fsync completed
   before the operation reported failure. Live acceptance/ACK correctly did not
   occur, yet complete valid bytes survived and were reconstructed on restart.
   Architecture review clarified Decision 276 in place, not through replacement
   or a new decision. This is neither a final PASS nor an implementation FAIL.
7. **Scenario 6R - PASS:** Under clarified Decision 276, failure reported after
   real fsync left no live state/audit/ACK/application callback and closed new
   intake. Restart recovered the surviving entry exactly once and produced
   persistent recovery evidence. Identical redelivery was ACKed as already_accepted
   without duplicate append/state/callback; the original remained nonpersistent.
8. **Scenario 7 - PASS, all nine checks:** After the integrity correction,
   corrupt `"node".` and `"node"e+` final entries each failed startup and left
   their journal unchanged (four checks). Genuine interrupted numeric exponent
   permitted recovery, reconstructed prior evidence exactly once, omitted the
   interrupted evidence, produced one normal recovery record, and removed the
   interrupted tail (five checks).

## Architecture clarification and independent audit history

Initial implementation was followed by manual Scenarios 1-5. Scenario 6's
uncertain-fsync result prompted architecture review and the existing Decision
276 clarification: live acceptance requires reported durability success, while
restart accepts complete valid surviving history. Automated regression coverage
was added and independent manual Scenario 6R passed. No candidate/commit protocol
was introduced.

The initial independent audit then returned **FAIL** for one DIFFERENT blocking
**P2 recovery-integrity defect**. Numeric-looking suffixes after completed strings,
including `"source_id":"node".` and `"source_id":"node"e+`, could be silently
discarded as interrupted numbers even though appending a missing tail could not
make them valid JSON. Decisions 276 and 278 were PARTIAL; 277, 279, and 280 were
SATISFIED. This was a genuine implementation failure, not the earlier fsync ambiguity.

The minimal correction required an appropriate adjacent numeric prefix/context;
decimal continuation requires an integer and unfinished exponent requires a
number without an existing exponent. Illegal suffixes after completed values
are rejected. Public APIs, journal format, ownership, protocol, and accepted
architecture did not change. Scenario 7 then passed all nine checks.

The targeted code-first independent re-audit returned **PASS**, found the original
P2 **FIXED**, and assessed Decisions 276-280 as all **SATISFIED**. Independent
temporary probes passed for **102 corruption cases**, **80 genuine numeric-truncation
cases**, and **one complete valid record without a final newline**. No false-positive
or false-negative defect was found in the challenged contexts; no blocking finding
or further implementation correction remained.

## Final automated validation

Final post-correction implementation results were independently confirmed during
the re-audit:

- Slice 27 recovery: **25 passed, 0 failed**.
- Storage/communication/NATS regressions: **39 passed, 0 failed**.
- Artifact handoff/retrieval/verification/global evidence/Controller/start-rejection
  regressions: **82 passed, 0 failed**.
- Full discovery: **383 total, 376 passed, 0 failed, 7 optional rendering skips**.

These are previously executed implementation/re-audit results, not tests run
during this documentation closure. Independent manual IPython results above are
separate validation evidence. No new tests, manual validation, or audit were run
for closure.

## Limitations and completion

Slice 27 and M014 are complete. M011 remains OPEN pending real Jetson/SSH-SFTP
deployment validation; M012 and M013 remain COMPLETE.

**Q019 remains OPEN:** Ingestor journal recovery does not establish how Controller
knows all Session evidence durably published to JetStream was consumed/accepted
before final archive closure. No Session-wide drain/finalization protocol is validated.

**Q024 remains OPEN:** Restart assumes an already-known Session. Application-wide
unfinished-Session discovery/selection, Session resumption, complete Controller/
application lifecycle restoration, multiple unfinished-Session orchestration,
safe journal deletion, cleanup/retention, and abandoned-journal handling are deferred.

This is software closure only: no live JetStream server crash/recovery beyond the
exercised software boundary, hardware deployment, real Jetson/SSH-SFTP, producer
publication recovery, new retry service, or scientific artifact reconstruction
beyond the existing handoff semantics was validated.

---

# W035 - Phase 16 Session-binding Release and Sequential Service Reuse

**Status:** Complete - narrow software implementation, manual IPython validation,
and independent audit PASS under Decisions 313 and 322.

## Purpose

Validate service-owned Session-binding release for Controller, Ingestor, and
SynchronizationManager after their own cleanup and evidence obligations are
confirmed, including isolation of a newer Session from delayed asynchronous release.

## Workflow

```text
Session A ends acquisition and fulfills cleanup obligations
    -> Ingestor compiles persistent messages and all runtime intake audit
    -> StorageManager writes Evidence Archive and final Session Record
    -> Controller confirms its decisions against current archival coverage
    -> Controller refreshes terminal Session Record and unsubscribes
    -> Controller revalidates captured Session object identity and preservation
    -> Controller retires only that binding under the storage guard
    -> Ingestor releases after exact archive/terminal-record coverage
    -> retained services can prepare and acquire for Session B
```

Each service releases independently; this is not a new global release order or
drain protocol. SynchronizationManager releases only after Session Time stops,
active mappings retire, and each mapping update has exact journal-backed Ingestor
acceptance. It does not require subsequent StorageManager archival and must confirm
that acceptance while Ingestor still retains the accepted evidence.

Ingestor holds intake then storage locks through release commitment. Its archive
coverage includes persistent runtime messages and every required runtime intake
audit, including nonpersistent, rejected, and duplicate intake. Nonpersistent
messages remain nonpersistent; acquisition envelopes retain their existing path.
Current archival confirmation remains stable through commitment, and failed or
partial rewrites cannot authorize release using an earlier confirmation.

Controller captures the Session object and its subscriptions, checks binding
identity after each unsubscribe await and before retirement, and holds no storage
guard across an await. Only one overlapping release can retire the binding. A stale
release returns failure for its original Session without recording against or
changing a newer binding, decisions, subscriptions, command history, or last-release
status. Cancellation propagates without retirement; unsubscribe errors preserve
the binding and evidence obligations. Already completed unsubscriptions are not
automatically rolled back. Durable records and recovery journals are not deleted.

## Independent manual IPython validation

Reported manual validation passed for refusal without preservation confirmation,
late-intake invalidation, release after complete archival, recovery-journal
preservation, and subsequent Ingestor reuse. Synchronization validation passed for
running-time/active-mapping/unconfirmed-handoff refusal, durable mapping-evidence
acceptance without downstream archival, and reuse.

The final asynchronous correction passed manual validation with release A paused
during unsubscription, another release completing A, and Session B starting before
the stale operation resumed. B's state, evidence, and subscriptions were preserved;
acquisition continued and normal B cleanup succeeded.

## Automated validation and independent audit

- Independent focused regression: **152 passed, 0 failed, 0 skipped**.
- Full discovery: **493 run, 486 passed, 0 failed, 7 optional rendering skips**.
- Independent final audit: **PASS**, no blocking defects or architectural
  ambiguities; the previous asynchronous Session-isolation defect is resolved.
- Deterministic regressions exercise overlapping release at both unsubscribe
  positions, newer-Session preservation, cancellation, unsubscribe exceptions,
  current archival enforcement, failure retention, and successive reuse through
  real framework components with controlled broker doubles.
- Independent memory-only negative controls disabled the identity checks and
  reproduced the concurrency defect. Expected negative-control failures are
  separate from the passing regression-suite results; no repository files changed.

These are previously executed and reported validation/audit results, not tests or
manual validation performed during this documentation synchronization. Earlier
implementation results remain historical records in framework_milestones.md.

## Limitations and completion

Only this narrow Session-binding release implementation slice is complete. Phase
16 remains incomplete: scoped framework stop/kill, administrative maintenance,
Session-independent framework evidence, and independent startup/returning-service
integration are not validated by W035. M015 remains OPEN with its separate remaining
completion criteria; this workflow is not broad Slice 28 closure.

Q019's Session-wide evidence-consumption/final-archive guarantee and Q024's
application restart, journal lifecycle, and recovery orchestration remain OPEN.
No new lifecycle states, automatic recovery, evidence subsystem, or global
acknowledgment/drain protocol was introduced. This is software/broker-double
validation, not real hardware, live cross-process, or external NATS deployment
validation.

---

# W036 - Phase 16 Individual-service Maintenance and Confirmed Retirement

**Status:** Complete - narrow software implementation, manual IPython validation,
and final independent audit PASS, including Decision 324 closeout ordering.

## Purpose

Validate target-owned individual-service stop, authorized kill, and cancel through
the existing maintenance interface and command/result/evidence pathways. This is
distinct from Session-binding release (W035) and general coordinated framework
shutdown.

## Workflow

```text
Orderly stop evaluates service-owned blockers
    -> preserve initial maintenance checkpoint before cleanup
    -> perform ordinary resource cleanup while evidence capabilities remain available
    -> durably preserve confirmed actions, failures, and remaining obligations
    -> preserve readiness-for-retirement checkpoint
    -> recheck obligations and atomically commit operational retirement
    -> initiating interface retains the confirmed command result
```

Pre-cleanup preservation failure blocks orderly stop; failure after cleanup starts
produces a failed outcome. Readiness for retirement and successful resource cleanup
do not imply confirmed retirement or OS process death. Evidence-owning services
need not preserve their own post-retirement events through unavailable infrastructure.
Missing command-result delivery is not successful retirement.

Authorized kill remains forced continuation of the same blocked attempt with
explicit authorization; cancel declines that continuation. Forced cleanup may
leave obligations unresolved. A truthful cleanup checkpoint uses `outcome=None`;
only confirmed operational retirement permits a completed result. Active-operation
checking and retirement commitment share the admission lock without an await.

## Independent manual IPython validation

Reported manual validation passed, including the authorized-kill failure scenario:
an admitted StorageManager collection remained active during stop and kill.
Orderly stop returned `blocked`, authorized kill returned `failed`, and
`termination_confirmed=False`. The durable framework Evidence Archive contained
outcomes `["blocked", None, "failed"]`, with forced cleanup actions and remaining
obligations recorded and no false completed termination evidence.

Successful authorized retirement was also independently exercised. Its confirmed
command result and retained evidence remained consistent without requiring
impossible post-retirement self-persistence by a retired evidence service.

## Automated validation and independent audit

- Two targeted authorized-kill regression tests passed.
- Focused regressions: **141 passed** across maintenance, framework evidence,
  Ingestor recovery, Session-binding release, and NATS communication tests.
- Full discovery: **541 run, 534 passed, 0 failed, 7 optional rendering skips**.
- Final independent audit: **PASS**; no blocking defects.
- The original four audit findings were corrected and validated: two-stage
  preservation/retirement ordering, asynchronous child-task admission protection,
  outstanding producer-owned persistent evidence guards, and explicit Ingestor
  operational-dependency rechecks.
- The subsequent authorized-kill premature-completion evidence defect was
  corrected and independently re-audited; controlled events exercised the active
  collection failure window and successful evidence-service retirement.

These are preceding implementation, manual validation, and independent audit
results, not new tests or validation executed during this documentation task.
Historical results and W035 are preserved.

## Limitations and completion

Only the individual-service maintenance implementation slice is complete.
At the W036 validation checkpoint, coordinated shutdown and independent
startup/returning-service integration were unfinished. W037 and W038 now separately
record validated coordinated shutdown and startup/return integration. Phase 16
remains incomplete and M015 remains OPEN with
its separate launch/reuse validation and audit criteria. Q019 and Q024 remain OPEN.

This is software validation, including controlled broker doubles, not real hardware,
live cross-process, or external NATS deployment validation. No new lifecycle state,
supervisor, evidence subsystem, automatic replay/recovery, or remote OS process
management was introduced.

---

# W037 - Phase 16 Progressive Framework Shutdown and Complete Archival Coverage

**Status:** Complete - narrow software implementation, independent manual IPython
validation, and final independent re-audit PASS under Decisions 325-326.

## Purpose

Validate Controller-coordinated shutdown of an explicit Session-independent
RuntimeParticipant scope using existing NATS command/result, W036 maintenance,
RuntimeEvidenceMessage, Ingestor, and StorageManager boundaries. Services retain
their own cleanup and retirement responsibilities; the informational survey is
not an all-or-nothing shutdown gate.

## Workflow

```text
Informational local stop-readiness survey
    -> preserve survey and evaluate fresh blockers at each actual stop
    -> progressively stop AcquisitionNodes, then SynchronizationManager
    -> StorageManager prepare_stop, then Controller prepare_stop
    -> archive actual preparation/coordination evidence and confirm final checkpoint
    -> Ingestor preserves its cleanup/readiness evidence and final intake compilation
    -> retire Ingestor
    -> retire prepared StorageManager with complete current archival coverage
    -> retire prepared Controller last with complete current archival coverage
    -> initiating interface retains actual confirmations and the overall result
```

Preparation performs ordinary cleanup while retaining required operational
capabilities; it is not retirement or a new lifecycle state. Prepared retirement
does not repeat ordinary cleanup or create post-Ingestor archival obligations.
Later retirement confirmations remain command/results, not newly archived records.

Before Ingestor retires, StorageManager retains its final compilation of all
accepted persistent runtime evidence and all intake audit, including duplicate,
rejected, and nonpersistent-message intake. Nonpersistent messages are not promoted
to persistent evidence. Prepared orderly retirement compares current durable
runtime evidence, intake audit, and compilation summary against confirmed products
and the retained complete requirement, before and after asynchronous callbacks.
Preservation and admission locks protect final retirement commitment without
spanning an await. Missing coverage prevents confirmed retirement and completed
shutdown, even if the retiring service's own evidence remains present.

Each blocked participant requires a separate explicit administrator authorization
for kill; declining authorization, failed kill, missing results, or unconfirmed
retirement cannot produce completed shutdown. Authorized kill retains W036's
separate semantics and does not promise complete evidence preservation. Already
stopped services remain stopped without automatic rollback or restart.

## Independent manual IPython validation

Reported independent validation passed the complete five-service shutdown and
fault injections for authorization denial, failed kill, archival failure, and
missing retirement confirmation. Following the preservation correction:

- An earlier valid compilation retaining prepared-service evidence but losing
  later Ingestor evidence/audit correctly rejected retirement.
- Removing intake audit while retaining all runtime evidence correctly rejected
  retirement.
- Audit-only loss during StorageManager's asynchronous retirement callback was
  rejected by the final guard.

## Automated validation and independent audit

- Focused regressions: **174 passed, zero failures or skips**, covering framework
  shutdown, individual maintenance, framework evidence, Session-binding release,
  NATS communication, and Ingestor recovery.
- Full discovery: **574 run, 567 passed, 0 failed, 7 optional rendering skips**.
- Final independent re-audit: **PASS**, Decisions 325-326 satisfied, no blocking
  defects or architectural ambiguities.
- Controlled-event regressions exercised earlier-compilation replacement,
  audit-only loss before/during retirement, partial archive rewrites, and complete
  duplicate/rejected/nonpersistent intake-audit preservation.
- Independent public-workflow checks confirmed mixed-intake audit loss rejects
  retirement, restored complete coverage restores confirmation, and the
  post-callback guard prevents a false completed outcome.
- Four memory-only negative controls reproduced regression failures when final
  compilation enforcement was disabled; no repository files were altered.

These are preceding implementation, manual validation, and independent audit
results, not new tests performed during documentation closure. The initial FAIL
identified incomplete archival coverage; the corrected preservation guard passed
independent validation and re-audit. W035/W036 historical validation is preserved.

## Limitations and completion

Only the progressive coordinated-shutdown implementation under Decisions 325-326
is closed here. At the W037 checkpoint, startup/return integration was unfinished;
W038 separately records its completion. Phase 16 remains incomplete and M015
remains OPEN with its separate launch/reuse
validation and audit criteria; Q019 and Q024 remain OPEN.

This is controlled software/broker-double validation, not real hardware, live
cross-process, or external NATS deployment validation. No new lifecycle state,
evidence subsystem, supervisor, automatic recovery, or remote OS termination is
introduced. Nonblocking test improvements identified by the audit are not new
architectural requirements.

---

# W038 - Phase 16 Service Startup/Return Integration

**Status:** Complete - narrow software implementation, independent manual IPython
validation, and final independent read-only re-audit PASS under Decisions 327-331.

## Purpose

Validate independent operational-service startup/return announcements, direct
configured-dependency readiness updates, protected service reuse, and truthful
framework evidence preservation through existing communication and service owners.
This is distinct from Session-binding release (W035), individual-service maintenance
(W036), and coordinated framework shutdown (W037).

## Workflow

```text
Independently started or returning service confirms required NATS connectivity
    -> subscribes directly to newly published configured-dependency announcements
    -> announces existing RuntimeParticipant identity and ServiceReadiness
    -> reports known unresolved obligations without claiming recovery
    -> receiving services update current readiness separately from last-known reports
    -> explicit readiness checks run only when operationally necessary
    -> unconfirmed communication invalidates affected current availability as unknown
    -> persistent framework evidence reaches Ingestor and StorageManager
    -> separate acceptance/archival confirmation, or warning with retained obligations
```

Historical announcements cannot establish current operational readiness. Fresh-only
dependency subscriptions do not change Ingestor's historical durable-evidence
consumption or recovery. A fresh announcement does not trigger a redundant check;
there is no proactive dependency-disappearance detection guarantee.

Current readiness, last-known readiness, technical readiness, communication
availability, reservations, and unresolved obligations remain distinct. Unknown
availability is missing current confirmation, not a fabricated `ready=False`
report. It prevents false Controller readiness while preserving historical reports.
Returning services remain subject to existing reservation, cleanup, retirement,
and ownership protections; return does not confirm interrupted work has resumed.

Private ordering counters prevent an earlier readiness result from overwriting
newer announcements or checks within the same communication binding. Result
application is atomic under the existing admission lock; old communication-binding
callbacks cannot affect a replacement binding. No synchronous lock spans an await. Unresolved
group results invalidate only missing configured dependencies. Publication failures
invalidate only the affected attempted dependency, not successful, unattempted, or
unrelated dependencies; the original publication failure still propagates.

Startup/readiness, unresolved-work reports, and explicit administrator resume/drop
choices use producer-marked persistent `RuntimeEvidenceMessage` records with
`session_id=None`. Recording a choice does not execute recovery, delete data, or
clear obligations. NATS publication, journal-backed Ingestor acceptance, and current
StorageManager archival confirmation are separate observations. Missing archival
confirmation produces an operator warning and retains producer-owned evidence,
without blocking startup when other accepted prerequisites are satisfied.
Session Record and Evidence Archive ownership and W035-W037 protections are unchanged.

## Independent manual IPython validation

The initial implementation passed eight independent manual validation cells covering:

- Public interfaces, dependency-readiness transitions, and current versus last-known reports.
- Fresh-only NATS announcements versus historical evidence consumption.
- Preservation warnings and evidence-only administrator resume/drop choices.
- Actual Ingestor acceptance, StorageManager archival, and archive-corruption detection.
- Late startup, service return, communication loss, and explicit readiness checks.
- AcquisitionNode reservations, unresolved obligations, and protected reuse.

After the first audit's corrections, three additional independent manual cells passed:

- Delayed readiness results could not overwrite newer announcements or corrupt last-known readiness.
- Unresolved group responses invalidated only missing configured dependencies.
- Group publication failures invalidated only the affected attempted dependency,
  leaving successful and unattempted peers unchanged.

Unknown current availability prevented false Controller readiness. No automatic
termination, recovery, or administrative action occurred.

## Automated validation and independent audit

- **Initial independent audit: FAIL.** It identified two P2 defects: delayed
  readiness results could overwrite newer announcements, and unresolved group
  outcomes/publication failures could leave affected availability falsely confirmed.
- Both defects were corrected before the additional manual validation and final audit.
- **Final independent read-only re-audit: PASS.** Both original findings were
  resolved; no new blocking implementation defects or architectural conflicts were found.
- Focused suite: **230 passed, zero failures or skips**, covering startup, NATS
  communication, framework evidence, Session launch/binding release, maintenance,
  and coordinated shutdown.
- Full discovery: **603 run, 596 passed, 0 failed, 7 optional rendering skips**.
- Deterministic regressions cover the original same-binding race, overlapping checks
  in both delivery orders, selective unresolved-result invalidation, and selective
  publication-failure invalidation.
- Additional independent automated probes passed for a delayed result after newer
  unknown availability, cancelled group publication, and old-binding group completion
  while a new-binding readiness check remained pending.

These are previously executed and reported implementation, manual validation, and
independent audit results, not tests or IPython validation run during this
documentation-only closure. The initial failed audit is not replaced by an
uncorrected-success claim. W035-W037 completion status and validation records remain intact.

## Limitations and completion

Only the startup/return integration slice under Decisions 327-331 is complete.
Phase 16 remains OPEN. M015 retains its separate remaining launch/reuse validation
and audit criteria; Q019, Q022, and Q024 remain OPEN.

Validation used real framework components, including Ingestor journaling and
StorageManager archival, with controlled software/NATS broker doubles. It does
not establish live external NATS deployment, cross-process, or hardware validation.
No automatic recovery/replay, resume/drop execution, supervision, heartbeat
monitoring, polling, service discovery, new lifecycle state, GUI authority, or new
persistence mechanism was implemented. Deferred behavior is not a closure requirement
for this slice and is not resolved by this workflow.

---

# W039 - Q024-B Service-Specific Authorized Recovery and Reconciliation

**Status:** Complete - supported software implementation under Decisions 339-348,
independent manual IPython validation, and final focused independent read-only
re-audit PASS after correction of the initial audit finding.

## Purpose

Validate narrow service-owned recovery attempts and informational reconciliation
using existing obligations, administrator decisions, command/results, runtime
evidence, Ingestor journals, and StorageManager preservation. This extends the
Decisions 332-338 reporting/abandonment slice without closing broader Q024.

## Workflow and seven implementation units

```text
Owner reports an existing unresolved obligation and current prerequisites
    -> administrator explicitly authorizes the specific operational attempt
    -> command references the original obligation and authorization evidence
    -> owner confirms durable intake, identity, scope, prerequisites, and safety
    -> owner executes only the supported action, or refuses it
    -> actual outcome and remaining obligations are retained through existing evidence
    -> subsequent archival confirmation is reported separately from action success
```

Read-only Controller and timing reconciliation need no administrator authorization
merely to inspect trustworthy records; they do not execute operational recovery.

1. **Authorization and execution correlation:** Existing administrator decisions
   identify the exact service-owned obligation, operation, and execution command.
   Owners revalidate immediately before action. Duplicate commands retain their
   original result; a subsequent recovery attempt requires new explicit authorization.
   Failed/refused attempts and incomplete preservation remain observable obligations.
2. **StorageManager persistent-write recovery:** Authorized Evidence Archive
   rewrites use current trustworthy Ingestor compilation; Session Record rewrites
   use retained complete original inputs. Authorization and attempt require
   journal-backed Ingestor acceptance before repair, not preservation in the
   unavailable archive. Actual durable write and later outcome archival are distinct.
3. **StorageManager fresh artifact transfer:** Reuse the original handoff and
   retrieval/verification path for a fresh complete attempt, without modifying the
   authoritative source or overwriting an unexpected final destination. Temporary
   copies are reclaimed only with proven identity; no byte-level resumption occurs.
4. **AcquisitionNode scientific-artifact preservation:** Supported local finalization
   preserves genuinely available records and authoritative manifests. If finalized
   manifest acceptance fails, a new authorized attempt resubmits the retained
   identical evidence using its original identity and Ingestor deduplication,
   without refinalizing records or changing artifact bytes. Local-finalization
   success is separate; complete recovery requires required manifest durability.
5. **AcquisitionNode device/resource cleanup:** Independently authorized cleanup
   requires actual confirmation and retains existing device lifecycle, reservation,
   Session-binding, terminal Experiment, and resource-reuse protections. Artifact
   preservation success does not establish device cleanup, or vice versa.
6. **Controller informational reconciliation:** Read existing confirmed participant
   outcomes and current durable preservation without replay or lifecycle changes.
   Preserve partial results, missing/conflicting outcomes, and uncertainty. Optional
   and non-mapping command details cannot crash reconciliation or invent a Session
   association; only explicit matching Session identities establish scoped command
   outcomes. Command success is not proof of participant completion. Evidence is
   serializable, and unchanged findings do not generate redundant evidence.
7. **SynchronizationManager historical reconciliation:** Preserve journal-backed
   timing/mappings and report continuity gaps, uncertainty, and affected scope.
   Loss of trustworthy active Session Time does not authorize zero-based restart,
   old-mapping reactivation across downtime, timestamp mutation, fabricated
   observations, or automatic Session failure. Healthy synchronization behavior
   remains unchanged.

These units preserve service ownership and existing evidence mechanisms. NATS
publication, durable Ingestor acceptance, actual action success, and StorageManager
archival confirmation remain distinct. Missing trustworthy inputs or unsupported
repairs are refused; failed preservation retains evidence and warnings. Ingestor's
existing automatic reconstruction from a valid journal for an already-known Session
under Decisions 276-280 is unchanged, not a new Q024-B recovery unit.

## Independent manual IPython validation

- Initial independent validation: **PASS, 22 behavioral checks** across the
  supported Q024-B scope.
- After the Controller correction, focused independent revalidation: **PASS,
  16 behavioral checks**, covering both original failures, correct Session
  association, unassociated uncertainty, durable evidence, deduplication, and
  absence of lifecycle changes or command replay.

## Automated validation and independent audit

- Retained scientific-manifest recovery corrections were completed before the
  initial full source audit, including identical-evidence resubmission after
  failed acceptance without repeating scientific finalization.
- **Initial independent source audit: FAIL.** One blocking P2 finding: Controller
  reconciliation assumed dictionary details. A rejected Session start with
  `details=None` and successful acquisition with `AcquisitionIterationSummary`
  both raised `AttributeError` through ordinary public workflows.
- The correction handles optional, mapping, and non-mapping details safely,
  preserves unassociated uncertainty, and avoids invented Session association
  or participant completion. Public-workflow regressions cover both failures
  and mixed scoped/non-mapping results, serialization, and unchanged runtime state.
- Final implementation full suite: **656 run, 649 passed, 0 failed, 7 optional
  rendering skips**.
- **Final focused independent read-only re-audit: PASS.** The original P2 finding
  was resolved; no blocking defects or architectural ambiguity remained within
  the focused scope. The earlier audit found no other blocking Q024-B issues.
- The final re-audit independently ran **20 relevant automated tests, all passed**,
  covering reconciliation and Controller workflows.

These are previously executed implementation tests and reported independent
manual validation/audit results, not tests or IPython validation run during this
documentation-only closure. The initial failed audit remains part of the record;
the initial implementation is not described as an uncorrected audit success.

## Limitations and completion

Only the supported Q024-B implementation slice is complete. Decision 336 remains
partially implemented: guarded release of redundant producer-owned evidence copies.
Broader Q024 remains OPEN, including journal retention/deletion, abandoned journals,
application-wide discovery/restoration, stale reservations, remaining memory/cache
retirement, and recovery/cleanup outside supported contracts. Q019, Q022, Phase 16,
and M015 remain OPEN; W035-W038 and earlier validation records remain intact.

Validation uses controlled software/NATS broker doubles and real framework
intake/persistence, not live external NATS, cross-process, Jetson, or hardware
validation. No universal recovery system, new automatic replay/retry, application
restoration, new Session states, active-Session clock restoration, GUI recovery,
supervision, or new evidence infrastructure is claimed. Missing trustworthy
information remains unresolved rather than invented.

---

# W040 - Q024 Controller Startup Reconciliation and Node-Owned Reservation Protection

**Status:** Complete - supported software implementation under Decisions 351-352,
ICC review, independent manual IPython validation, correction revalidation, and
final focused independent read-only re-audit PASS after correction.

## Purpose

Validate automatic informational Controller startup reconciliation of explicitly
known participants while preserving safe ongoing acquisition, node-owned Session
reservations, and existing evidence-preservation and authorized recovery boundaries.
This extends the supported read-only reconciliation scope without restoring Session
objects or closing broader Q024.

## Workflow

```text
Controller starts through NatsServiceMaintenanceCommunication.start()
    -> subscribes and announces readiness using existing communication/evidence
    -> obtains bounded check_readiness replies from explicitly known participants
    -> reads current owner-reported conditions and existing Session identities
    -> reports active, stopped, failed, or unknown observations independently
    -> retains informational findings through the existing framework evidence path
    -> confirms journal acceptance and safe archival separately, or reports warnings
```

Participants come from explicit `startup_participants` or existing configured
dependencies, with an explicit positive result window for nonempty scopes. There
is no automatic discovery. Missing replies or unusable diagnostics remain unknown,
not proof of participant failure, stopped acquisition, or successful cleanup.
Multiple nodes and their owner-reported Session identities are assessed independently.

Safe acquisition continues after Controller replacement. AcquisitionNode remains
authoritative for Session-keyed reservations. Local scientific finalization,
durable manifest acceptance, device cleanup, reservation release, and later global
collection remain distinct. Reconciliation does not restore a Session, replay
operations, restart an Experiment, advance lifecycle, automatically stop acquisition,
or release an unsafe reservation.

Startup/readiness evidence cannot silently repair an unconfirmed Evidence Archive.
Initial creation and healthy updates remain supported; existing corrupt, missing,
inconsistent, or otherwise unconfirmed products remain untouched. Safety is checked
after asynchronous publication and durable acceptance under existing intake/storage
locks. New evidence remains producer-retained and durably journal-accepted where
possible, with truthful preservation warnings and unconfirmed archival reported
separately. Malformed optional diagnostic collections cannot abort subsequent
participant observations or fabricate Session identities or confirmed outcomes.
Authorized Q024-B recovery remains a separate operator-authorized operation with
its existing prerequisites; W039 and Decisions 339-348 retain their completed scope.

## Implementation checkpoints

- Initial implementation: `99e80f502f376519b5e8fd4e461d0281d39e85eb`.
- Corrections: `e62fa4ebbdcbd4b5b07dd39c806df86df5648b4c`.

## Independent manual IPython validation

- Initial independent validation: **PASS, 28/28 checks**.
- Focused correction revalidation: **PASS, 25/25 checks**.

## Automated validation and independent audit

- Codex full automated suite after correction: **676 run, 669 passed, 0 failed,
  7 optional rendering skips**.
- **Initial independent source audit: FAIL.** Blocking P2: startup readiness
  announcement silently repaired an unconfirmed Evidence Archive. Nonblocking P3:
  malformed optional diagnostic collections could abort reconciliation.
- Both findings were corrected: readiness announcements use the existing guarded
  preservation path, and optional collection containers are checked before iteration.
- **Final focused independent read-only re-audit: PASS.** Both original findings
  were RESOLVED; no new blocking findings or architectural ambiguities remained.
- The final re-audit independently executed **132 focused tests, all passed**,
  covering startup, reconciliation, authorized recovery, NATS, and framework shutdown.
- Two additional independent probes passed: ordinary readiness publication left a
  corrupt archive untouched; an interrupted StorageManager write during paused
  startup invalidated archival confirmation without deadlock or implicit repair.
- Two in-memory negative controls reproduced the original defects when their
  respective guards were disabled, demonstrating meaningful regression coverage.

These are previously executed Codex automated tests, independent manual validation,
and independent audit results, not validation performed during documentation
closure. The initial failed audit is preserved; the initial implementation is not
described as having passed without corrections. The final re-audit did not repeat
full discovery; its focused tests and probes are distinct from the Codex full suite.

## Limitations and completion

Only the supported Decisions 351-352 slice is complete. Decision 336 remains
partially implemented. Decisions 349-350 and 353-355 remain accepted but
unimplemented, including Decision 354's monthly Evidence Archive partitioning;
validation uses the existing shared framework archive layout.

Broader Q024 remains OPEN: application-wide discovery/restoration, unresolved
journal lifecycle, remaining temporary-state retirement, and recovery beyond
supported contracts remain deferred. Known-node reservation protection is complete,
not an automatic stale-reservation cleanup or application restoration mechanism.
Q019, Q022, Phase 16, and M015 remain OPEN. W035-W039 and prior validation records
remain unchanged.

Validation used controlled software/NATS broker doubles and real framework
intake/persistence. No hardware, live external NATS, cross-process, or Jetson
deployment validation is claimed. No universal recovery system, recovery registry,
Session replica, new lifecycle state, or automatic reservation expiry was introduced.

---

# W041 - Q019 Decision 361 Ingestor Receiving Foundation and JetStream Routing

**Status:** Complete - narrow receiving-foundation implementation and routing
prerequisite, developer automated testing, independent manual IPython validation,
and final targeted independent read-only re-audit PASS after two P2 corrections.

## Purpose

Validate restart-safe, journal-backed Session evidence receipt through an existing
completion marker, without confusing receipt with producer confirmations, Normal
Stop, Session completion, or Evidence Archive preservation. Broader Q019 remains OPEN.

## Workflow

```text
Provision/update the existing three durable JetStream streams in place
    -> route Session-scoped and Session-independent messages with disjoint filters
    -> subscribe Ingestor with a durable Session-specific receiving position
    -> journal accepted evidence before server-confirmed ACK
    -> receive a Session-scoped acquisition_evidence_completion marker
    -> verify current receiving identity, retained history, and contiguous ACK progress
    -> reconcile the Session publication prefix through the marker with the journal
    -> confirm receipt only while exact retained journal coverage remains verified
```

The five-/six-token stream filters preserve commands, command results, and evidence
in `LAB_COMMANDS`, `LAB_COMMAND_RESULTS`, and `LAB_EVIDENCE`; telemetry remains Core NATS.
Fresh provisioning and in-place legacy-filter updates preserve unrelated settings,
stored messages, and consumer state. Configuration conflicts are surfaced rather
than silently discarded; streams are not deleted/recreated. Updates across the
three streams are not transactional; errors may leave partial configuration progress.

Session-specific durable receipt survives supported client/Ingestor restarts.
Ingestor preserves journal-before-`ack_sync()`, evidence-ID deduplication, redelivery,
known-Session reconstruction, recovery evidence, and Session isolation. Filtered
consumer sequences are not confused with global stream sequences; an ACK floor
alone cannot prove completeness.

`verify_acquisition_evidence_receipt(marker)` checks journal-backed marker acceptance,
original receiving identity, intact history, and coherent contiguous ACK progress.
It reconciles every Session-matching publication through the marker with the actual
retained journal by identity and canonical content, including duplicate-ID and both
marker comparisons. JSON type differences remain conflicts; object-key order does
not. Ingestor's intake lock covers the final synchronous confirmation, with no await
inside that guard and asynchronous readback rechecks before commitment.

Missing ACKs, history gaps, lost/truncated/conflicting journal coverage, unverifiable
receiving origin, and relevant asynchronous state changes prevent confirmation.
Historical broker ACKs cannot substitute for lost journal contents; confirmation
does not repair missing history or introduce another receiving/evidence subsystem.

## Implementation checkpoint

Final independently audited commit: `8fbfbca1bf218d119da2e517158cd57a7d3b3c46`.

## Independent manual IPython validation

ICC coordinated these checks against the user's local NATS installation at different
implementation/correction stages. They were not all rerun against the final commit.

- Initial receiving-foundation validation: **6/6 PASS** - complete receipt, restart
  recovery, missing stream history rejected, missing ACK progress rejected, missing
  durable receiving state rejected, and unknown receiving origin rejected.
- First P2 correction validation: **2/2 PASS** - intact journal after restart permits
  confirmation; lost journal with surviving broker ACK history prevents confirmation.
- Second P2 correction validation: **3/3 PASS** - conflicting `True` versus `1` and
  `False` versus `0` are rejected; an identical duplicate is accepted.

## Automated validation and independent audit

- Developer final full suite: **710 run, 703 passed, 0 failed, 7 optional skips**.
- **Initial independent audit: FAIL.** P2: a lost journal, surviving durable consumer,
  and fresh marker could falsely confirm complete receipt. P3: stale architecture
  status summaries. Both were corrected through exact published-prefix/journal
  reconciliation and status synchronization.
- **First targeted independent re-audit: FAIL.** The original P2 and P3 were resolved,
  but a second P2 remained: Python/dataclass equality could treat distinct canonical
  contents such as `true` and `1` as equal, letting conflicting same-ID publications
  conceal lost evidence. The correction reused Ingestor's canonical serializer.
- **Final targeted independent read-only re-audit: PASS.** Both P2 findings and P3
  were resolved; no remaining P0-P3 findings or implementation correction was
  required before this narrow closure.
- The final audit independently ran **107 focused tests, all passed**, including
  **seven real-server tests**; controlled broker-double tests are distinct from
  these isolated live-server checks.
- **Six additional independent isolated live-NATS probes: PASS.** `True` versus `1`,
  `False` versus `0`, `1` versus `1.0`, nested JSON type differences, and `+0.0` versus `-0.0`
  conflicts were rejected; an identical duplicate with an intact journal was accepted.

These are previously executed developer automated tests, independent manual
validation, and independent audit results, not tests performed during documentation
closure. The final focused audit is distinct from the reported developer full suite;
both earlier failed audits remain part of the validation history.

## Limitations and completion

W041 closes only Decision 361's receiving foundation and JetStream routing
prerequisite. Receipt verification has linear broker-history read cost and currently
requires intact global stream history from sequence 1. Losing unrelated older
history can prevent confirmation; this conservative failure-closed limitation is
not a full Session-closeout guarantee.

The following remain unimplemented: acquisition-stage producer publication-
confirmation orchestration; Controller publication of the marker after those
confirmations; Controller Normal Stop/Kill integration; Decision 362 Stage A/Stage B
preservation and permanent archive closure; Decision 363 temporary durable collection
outcomes; Decision 364 durable handoff and later stopped-Session collection; and
Decision 365 complete Normal Stop/partial forced closeout.

Q019, Q024, Q022, Phase 16, and M015 remain OPEN. Decisions 349-350 and 353-355
remain unimplemented; Decision 336 remains partial. W033/M013, W035, W039, W040,
and all earlier completed records retain their historical scopes.

Validation used controlled software/broker doubles and isolated/local real NATS.
No external NATS cluster, multi-host, Jetson, or hardware deployment validation is
claimed. No framework Consumer service, extra evidence transport, producer count
registry, per-producer terminal marker, polling, or new lifecycle state was introduced.

---

# W042 - Q019 Decision 366 Producer Publication Confirmation and Completion Marker

**Status:** Complete - narrow producer-confirmation and marker-publication
prerequisite, developer automated testing, independent manual IPython validation,
and targeted independent read-only re-audit PASS after the P2 correction.

## Purpose

Validate publication of applicable acquisition-stage evidence before successful
producer completion responses and the single Controller Session-scoped marker.
Use W041's existing Ingestor receiving foundation to verify durable receipt
separately. This completes the publication prerequisite, not broader Q019 closeout.

## Workflow

```text
Existing acquisition stop/cleanup orchestration
    -> participating AcquisitionNodes generate and durably publish applicable evidence
    -> existing successful node completion responses confirm publication
    -> SynchronizationManager finishes closing-Session timing/mapping publication
    -> Controller confirms producers and completed health processing
    -> Controller durably publishes its own applicable Session evidence
    -> Controller durably publishes one acquisition_evidence_completion marker
    -> Ingestor independently verifies receipt through the marker using W041
```

Every AcquisitionNode actually participating in acquisition has the publication
obligation, including nodes with selected optional devices. Unused optional devices
create no obligation. Initial and finalized ArtifactManifest messages retain their
artifact identity; applicable manifest, health, and pending runtime evidence precede
successful node completion responses. Failed, missing, or uncertain publication
prevents completion confirmation and marker publication.

SynchronizationManager stops prepared Session Time, retires only the closing
Session's mappings, and publishes applicable retained timing/mapping updates,
including closeout updates, before confirming. Other Session mappings and the
long-lived service remain independent. Ingestor-owned locally journaled recovery
evidence is not republished through JetStream.

After existing brokered stop/cleanup, callers explicitly use
`Controller.publish_acquisition_evidence_completion(communication=..., result_window_s=...)`.
It requires correlated successful participating-node stops and synchronization
publication confirmation, refuses unfinished Controller health processing, and
publishes owned decisions, rejection evidence, and pending scoped publications
before the marker. Successful results expose `details["marker"]` and
`details["publication_confirmed"]`. Interrupted operations retain evidence identity
for explicit retry; confirmed repeated calls emit no new marker. An uncertain ACK
can lead to identical retransmission, using existing evidence-ID deduplication.

Separate asynchronous locks serialize manifest and health publication passes.
Snapshot selection, durable publication, and cursor advancement are protected
together; each entry advances progress only after its acknowledgment. Failure or
cancellation releases the lock without skipping evidence and preserves retry
identity. A waiting callback rereads current progress rather than advancing a
stale cursor. No synchronous lock is held across publication awaits.

The marker is not the Stop command, Ingestor receipt proof, Evidence Archive
confirmation, or Session completion. W041 verifies the actually published prefix;
producer guarantees separately establish that applicable evidence was published.

## Independent manual IPython validation

- Initial successful two-node publication, including an optional device, ordering,
  synchronization/Controller evidence, and W041 receipt: **5/5 PASS**.
- Initial failed producer publication, unsuccessful cleanup confirmation, retained
  evidence, and marker withholding: **4/4 PASS**. The logged NATS exception was
  deliberately injected.
- After correction, real JetStream concurrency reproduction: **7/7 PASS**.
  Exactly one initial `open` manifest and one `finalized` manifest were published,
  followed by the successful stop response and completion marker. Cleanup-only
  connection-reset logs resulted from the manual harness stopping its temporary
  server before closing clients, not a demonstrated framework failure.

## Automated validation and independent audit

- **Initial independent audit: FAIL.** One blocking P2: overlapping Session-scoped
  artifact preparation and Session-independent `get_inventory` callbacks could
  publish the same initial manifest and independently increment the shared cursor.
  The later finalized manifest was skipped despite successful stop/marker results.
  Broker-double and real JetStream probes reproduced this; W041 correctly confirmed
  the published prefix but could not detect the producer's omitted message.
- The correction serializes manifest publication and the equivalent health cursor
  path with separate asynchronous locks, retaining the existing identities,
  acknowledgment, publication order, and retry contracts.
- Developer impact-selected correction tests: **10 passed, 0 failed, 0 skipped**.
  Coverage includes the exact overlapping-callback reproduction, withholding the
  marker while finalized publication is pending, failure/cancellation with waiting
  callbacks and identical retry, overlapping health publication and later evidence,
  and actual real JetStream publication followed by W041 receipt verification.
  Existing selected checks cover producer ordering, delayed/failed publication,
  retained caller-managed evidence, health Session isolation, and evidence transport.
- **Independent targeted read-only re-audit: PASS.** The original P2 was resolved;
  no confirmed remaining P0-P3 findings or directly related architectural violations
  were identified. Source review found no concrete issue requiring additional
  test execution; no suites were rerun during the targeted re-audit.

These are previously executed developer tests and independent manual/audit results,
not tests or IPython validation performed during this documentation closure. The
initial failed audit is preserved; the implementation is not described as having
passed without correction. No full-suite result is claimed for this correction.

## Limitations and completion

Only Decision 366's producer-confirmation/marker prerequisite is complete. W041's
historical record remains unchanged: its then-unimplemented producer work is the
subsequent scope closed here. W041 receiving-history limitations still apply.

Q019 remains OPEN for complete Controller Normal Stop/Kill integration, Decision
362 Stage A/Stage B preservation and permanent archive closure, Decision 363
temporary durable collection outcomes, and Decision 364 durable artifact handoff
and later stopped-Session collection. Decision 365 complete normal/partial forced
closeout remains unimplemented. Marker publication alone does not advance lifecycle
or implement these archival and collection responsibilities.

Q024, Q022, Phase 16, and M015 remain OPEN. Decision 336 remains partial and
Decisions 349-350 and 353-355 remain unimplemented. Earlier validated workflows
retain their historical scopes. Validation used controlled software/broker doubles
and isolated/local real JetStream, not an external NATS cluster, multi-host, Jetson,
or camera hardware deployment. No producer registry, per-producer terminal marker,
new evidence transport, automatic retry/replay, polling, or lifecycle state is added.

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
