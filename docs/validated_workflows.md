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

**Current architecture qualification (Decision 377):** Routine scientific
observations and per-observation metadata now belong in AcquisitionNode-local
scientific products regardless of size; Ingestor receives operational evidence
and manifests. The bounded node acquisition/operational-evidence replacement is
complete, independently validated and re-audited after correction in W053. Scientific
envelope workflows, including W051/W052, remain historical validated capabilities,
not mandatory routine-acquisition pathways. Their results and historical records
are unchanged; active evidence durability and Q019 archival guarantees remain.

Decision 378 requires clean replacement of obsolete collection and scientific-
envelope mechanisms, not indefinite legacy API compatibility. W051/W052 remain
historical validations, not a reason to retain superseded code. Necessary
operational/historical-readback responsibilities remain; the replacement's final
independent integration audit must verify preserved functionality and absence of
obsolete architecture. Owner-level Slice 3B replacement is complete after
correction, independent validation and corrective re-audit PASS (W054). W055 records
final combined Decision 377-378 implementation acceptance after functional audit
PASS and targeted correction of the sole clean-replacement P3. The initial failed
clean-replacement verdict remains recorded; the user and ICC accepted targeted
verification without another independent re-audit for that test-only cleanup.

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

# W043 - Q019 Stage A Acquisition Evidence Archival

**Status:** Complete - bounded Stage A archival implementation, developer automated
testing, independent manual IPython validation, and independent read-only audit PASS.

## Purpose

Validate acquisition evidence preservation under Decisions 357 and 362 after
W041's durable receipt proof of the W042 completion marker. This completes Stage A
archival only, not Session completion, binding release, or broader Q019 closeout.

## Workflow

```text
Existing acquisition stop/cleanup and W042 producer/marker confirmation
    -> Controller requests W041 verification of durable receipt through the marker
    -> Ingestor confirms current durable journal coverage under its intake guard
    -> Ingestor compiles persistent runtime evidence and complete runtime intake audit
    -> StorageManager durably writes evidence, audit, and compilation summary
    -> StorageManager durably writes the separate final Session Record
    -> StorageManager records Stage A completion and an OPEN archive in the summary
    -> current exact readback confirms all products through Stage A commitment
```

Call `await controller.archive_acquisition_evidence(communication=ingestor_communication)`
after the confirmed W042 marker. The matching Ingestor receiving adapter must
independently verify durable receipt; marker publication or acceptance alone cannot
authorize successful archival. Current journal coverage is checked again before
compilation, so historical ACK progress cannot substitute for a lost journal.

The existing Ingestor compilation selects accepted persistent runtime evidence
using only producer-controlled `is_persistent`. Applicable locally journaled
Ingestor evidence is included without republishing it to JetStream. Complete
retained runtime intake audit includes duplicate, rejected, and nonpersistent
intake; nonpersistent messages are not added to the archive merely for coverage.

StorageManager persists the existing Session products:

- `evidence/runtime_evidence.jsonl`
- `evidence/ingest_audit.jsonl`
- `evidence/compilation_summary.json`
- `session_record_final.json`

Session Record and Evidence Archive remain separate. The summary records counts,
evidence identities, `stage_a_complete=True`, completion-marker identity and stream
sequence, Ingestor evidence provenance, and `archive_closed=False`. A flag or
historical write result is insufficient: confirmation requires exact current
readback of the evidence, audit, summary, and final Session Record.

Intake, StorageManager preservation, and Controller admission locks protect the
synchronous compilation, persistence, readback, and commitment in that order.
No synchronous lock is held across asynchronous receipt verification. Overlapping
Stage A requests are rejected; cancellation during verification does not write
products. Failed or partial persistence invalidates confirmation and preserves
the journal and Session binding. Interrupted persistence requires existing
authorized recovery, not implicit repair by ordinary retry. Explicit retry after
incomplete receipt and repeated healthy Stage A calls remain supported.

Successful results expose `details["stage_a_complete"]`, `details["archive_closed"]`,
receipt information, and persisted paths. The Session remains stopping and bound;
Stage A does not advance lifecycle, release resources, or close the Evidence Archive.

## Independent manual IPython validation

- Successful end-to-end Stage A archival using local real JetStream: **7/7 PASS**.
- Incomplete receipt, rejection, and successful explicit retry: **5/5 PASS**.
- Injected persistence failure, preserved journal, rejected unsafe retry, and
  retained Session binding: **5/5 PASS**.

Total independent manual validation: **17/17 PASS**.

## Automated validation and independent audit

- Developer impact-selected automated tests: **16 passed**. Ten new public-workflow
  checks cover full persistent evidence/all-audit preservation, incomplete ACK
  progress and retry, lost journal coverage, archive/record/summary write failures,
  corruption, healthy repetition, cancellation/overlap, and receiver isolation.
  Six existing directly affected checks cover legacy archive/record writing,
  exact preservation and release, failed rewrite invalidation, guarded concurrent
  rewriting, and the existing bounded Controller Session workflow.
- **Independent read-only source audit: PASS.** No confirmed P0-P3 defects,
  architectural violations, or required corrections were found. It reviewed
  receipt gating, protected compilation, exact current readback, failure behavior,
  concurrency, and unchanged ownership/lifecycle boundaries.
- Additional deterministic cross-thread archive-rewrite coverage was suggested
  as an optional test improvement, not a defect or closure condition. No additional
  tests were run during the audit because no concrete unresolved suspicion
  warranted execution under impact-based testing.

These are previously executed developer tests and independent manual/audit results,
not software tests or IPython validation performed during documentation closure.
No full-suite result is claimed for this slice; no failed audit or correction is
being omitted from this Stage A history.

## Limitations and completion

Only the bounded Stage A archival implementation is complete. W041 and W042 retain
their unchanged historical records and independently validated scopes. W041's
receiving-history limitations still apply. Validation used controlled software/
broker doubles and local real JetStream, not an external NATS cluster, multi-host,
Jetson, or camera hardware deployment.

Q019 remains OPEN for Stage B operator artifact collection and permanent Evidence
Archive closure, Decision 363's temporary durable collection outcomes, Decision
364's durable ArtifactManifest handoff, and full Decision 365 Normal Stop/Kill
integration. Stage A does not substitute an in-memory handoff for the deferred
durable handoff, perform global collection, or authorize premature binding release.

Q024, Q022, Phase 16, and M015 remain OPEN. No new service, lifecycle state,
registry, evidence transport, automatic retry/replay, or recovery mechanism is
introduced by this slice.

---

# W044 - Q019 Durable ArtifactManifest Handoff

**Status:** Complete - bounded handoff implementation under Decisions 359/364,
developer automated testing, independent manual IPython validation, and independent
read-only source audit PASS.

## Purpose

Validate durable preservation of Ingestor's existing ArtifactManifest collection
handoff so it remains readable without original Session runtime bindings, including
after StorageManager restart. This completes the bounded handoff slice, not Stage B
collection, permanent archive closure, or full Normal Stop/Kill integration.

## Workflow

```text
Confirmed W043 Stage A preservation after W041/W042 receipt/publication prerequisites
    -> Controller requests explicit handoff preservation
    -> current durable journal/intake and Stage A coverage are protected and checked
    -> Ingestor compiles the existing ArtifactManifest handoff
    -> StorageManager writes and fsyncs same-directory temporary JSON contents
    -> non-overwriting publication and supported directory fsync preserve the handoff
    -> exact current readback confirms preservation
    -> later known-Session readback needs no original runtime bindings
```

After confirmed Stage A, call `controller.preserve_artifact_collection_handoff()`.
Controller checks current Stage A evidence/audit coverage against the protected
Ingestor compilation and verifies durable journal coverage. The existing compiler
groups accepted artifact-manifest evidence by artifact identity within the Session,
prefers finalized manifests, and retains initial manifests when finalized evidence
is missing. Missing or uncertain finalization remains explicit through
`missing_finalization_evidence` and the retained manifest information. Neither
missing artifacts nor successful finalization is invented.

StorageManager persists `session_<session_id>/artifact_collection_handoff.json`
using the existing `session_id` plus `artifacts` handoff representation. This file
is separate from `session_record_final.json`, the Evidence Archive, and scientific
artifact bytes. The handoff identifies artifacts; it is not collection success.

`PersistentStorageManager.write_artifact_collection_handoff(session_id, handoff)`
uses its preservation lock, fsynced/closed temporary contents, a same-directory
non-overwriting hard link, supported directory fsync, and exact readback. Identical
retries reconfirm durability without replacing or rewriting existing contents.
Conflicting or corrupted existing files are refused, not silently repaired.
Interrupted persistence remains unconfirmed; an explicit identical retry can
confirm complete matching contents after a failed publication/durability step.
Malformed identities, inconsistent finalization flags, duplicate artifacts/JSON
fields, and invalid handoff structure cannot establish preservation.

`PersistentStorageManager.read_artifact_collection_handoff(session_id)` validates
the saved handoff with a new StorageManager instance without the original
Controller, Ingestor, or AcquisitionNode Session bindings. No registry, discovery,
Session restoration, or scientific-file retrieval is needed for known-Session readback.

Applicable Q019 Controller and Ingestor release guards require current handoff
coverage, not merely a historical preservation result. Comparisons distinguish
JSON types. Controller rechecks after asynchronous unsubscription; Ingestor retains
intake/preservation guards through release commitment. Delayed preservation
requests cannot record their outcome in a subsequent Session's binding/history.
Existing non-Q019 paths retain their historical scope.

Handoff preservation itself does not complete or release the Session, alter Stage A
products, or close the Evidence Archive. The Evidence Archive remains OPEN for later Stage B.

## Independent manual IPython validation

- Durable preservation, new StorageManager restart readback, identical retry,
  unchanged Stage A and lifecycle: **6/6 PASS**.
- Finalized versus missing/uncertain finalization and independent handoff
  persistence: **5/5 PASS**.
- Conflicting/corrupted handoffs, rejected overwrite, interrupted publication,
  and safe explicit retry: **6/6 PASS**.

Total independent manual validation: **17/17 PASS**.

## Automated validation and independent audit

- Developer impact-selected automated checks: **24 passed**. Fifteen new tests
  cover durable roundtrip/restart, initial/uncertain and empty handoffs, identical
  retry, competing writers, corruption and malformed data, persistence interruption,
  protected post-Stage-A integration, release safety, and delayed-request isolation.
  Nine existing directly relevant checks cover Stage A success/failure, manifest
  grouping and initial-only compilation, journal-restored handoff compilation,
  legacy/stale Controller release, and exact/concurrent Ingestor release.
- **Independent read-only implementation audit: PASS.** No confirmed P0-P3 defects
  or required corrections. Source review verified the supported Decisions 359/364
  boundaries, preservation/readback, concurrency, identity consistency, and release
  safety. No additional probes or suites were executed during the audit because
  no concrete unresolved suspicion warranted them under impact-based testing.

These are previously executed developer tests and independent manual/audit results,
not software tests or IPython validation performed during documentation closure.
No full-suite result or new deployment validation is claimed for this slice.

## Limitations and completion

Only the bounded durable handoff slice is complete. W041-W043 retain their unchanged
historical records and independently validated scopes. Existing hard-link support,
same-filesystem publication, and platform-specific filesystem durability
prerequisites remain applicable. Power-loss behavior was not independently tested.
Validation concerns software/local persistence, not external NATS deployment,
multi-host, Jetson, or camera hardware operation. No new handoff repair operation
or automatic retry/replay is introduced.

Q019 remains OPEN for Stage B artifact collection and collection-evidence
persistence, permanent Evidence Archive closure, eligible-Session selection, and
full Normal Stop/Kill integration. Later Stage B use of the saved handoff remains
deferred. Q024, Q022, Phase 16, and M015 remain OPEN. No accepted architecture,
component ownership, lifecycle state, or evidence transport is changed.

---

# W045 - Q019 Stage B Artifact Collection and Persistent Evidence

**Status:** Complete - bounded Stage B collection/evidence-persistence implementation,
developer automated testing, independent manual IPython validation, and final
targeted independent read-only re-audit PASS after correction.

## Purpose

Validate later collection from W044's durable ArtifactManifest handoff under
Decisions 357, 358, 362, and 363 and their accepted LLC clarifications. StorageManager
uses a trustworthy persisted Stage A baseline without original Session bindings,
preserves actual collection outcomes, and directly archives its own evidence.
This completes collection/evidence persistence only, not permanent archive closure
or full Normal Stop/Kill integration.

## Workflow

```text
Explicit collection request for a known Session and stable evidence identity
    -> validate persisted Stage A products and W044 handoff under preservation lock
    -> retrieve scientific artifacts through existing Artifact Plane mechanisms
    -> retain actual retrieval/verification results and uncertain outcomes
    -> durably preserve temporary collection outcome and evidence identity
    -> append StorageManager evidence directly to the Session Evidence Archive
    -> update compilation summary with separate preservation origins
    -> exact current readback confirms archival independently of collection success
    -> safely retire the temporary outcome; Evidence Archive remains OPEN
```

Use `controller.collect_saved_session_artifacts(session_id, evidence_id=attempt_id)`
or `storage.collect_saved_artifacts(session_id, evidence_id=attempt_id)`. Retain the
caller-supplied unique identity for repeated requests and result readback. Existing
storage-root/component identity and deployment-local retrieval configuration remain
required; no Session restoration or participant discovery is performed.

StorageManager validates existing `runtime_evidence.jsonl`, `ingest_audit.jsonl`,
`compilation_summary.json`, `session_record_final.json`, and
`artifact_collection_handoff.json` after restart or another Session's archival.
Counts, evidence identities, provenance, completion information, Session associations,
and file/supported-directory durability are checked; a status flag or historical
cached confirmation is insufficient. Cross-Session acquisition envelopes and
incomplete intake-audit records cannot establish preservation confirmation.

Collection reuses existing source selection, deterministic non-overwriting
destinations, independent artifact attempts, and light verification. Scientific
sources remain unchanged. Retrieval success, verification, aggregate collection
result, temporary-outcome durability, archival confirmation, and preservation
warnings remain distinct. Failure and unknown outcomes are retained without
inventing success or treating evidence uncertainty as scientific-data loss.

`artifact_collection_outcome.json` durably retains the actual collection message
and stable evidence ID before append. StorageManager directly appends its persistent
`RuntimeEvidenceMessage` to the existing archive, without a JetStream round trip or
fabricated Ingestor audit. Summary provenance distinguishes Ingestor-accepted
acquisition evidence from directly persisted StorageManager evidence. Original
acquisition evidence, intake audit, final Session Record, handoff, and previously
confirmed collection evidence remain protected. Missing or inconsistent provenance
cannot authorize destructive replacement by an acquisition compilation.

Reusing an already confirmed identity returns its outcome without refetch or
duplicate evidence. Interrupted persistence remains unconfirmed. Existing
`ServiceMaintenanceInterface` recovery requires a new explicit administrator
`resume` decision and correlated `recover_archive_write` command with
`obligation={"session_id": session_id, "evidence_id": attempt_id}`. Journal-backed
authorization/attempt acceptance precedes recovery. A trustworthy matching pending
outcome can complete evidence append/summary persistence after restart without the
old Session intake, repeated scientific transfers, or replacement of confirmed
history. Conflicting or untrustworthy products are refused, not silently repaired.

## Independent manual IPython validation

- Initial Stage B independent manual validation: **9/9 PASS**.
- Independent correction validation of the two audit findings: **3/3 PASS**.

These are separate validation stages; the initial successful scenarios did not
establish that the subsequent source audit would pass without correction.

## Automated validation and independent audit

- Initial developer impact-selected automated checks: **32 distinct tests passed**.
- Initial independent source audit: **FAIL**, with two confirmed P2 defects:
  missing/inconsistent provenance could permit replacement of existing Stage B
  evidence, and cross-Session acquisition envelopes or incomplete intake audit
  could establish an invalid persisted Stage A baseline.
- Corrections strengthened pre-write archive consistency/provenance protection,
  validated envelope Session association and required audit fields, and retained
  the separately authorized interrupted-write recovery path.
- Developer correction checks: **14 passed**, including targeted regressions for
  both findings and directly affected creation, persistence, and recovery behavior.
- Final targeted independent read-only re-audit: **PASS**. Both original P2 findings
  were resolved; no remaining confirmed P0-P3 defects were found within scope.
  One additional temporary-directory probe confirmed authorized acquisition-archive
  repair after Ingestor journal reconstruction with durable acceptance and actual
  write confirmation. No full suite or unrelated regressions were rerun.

These are previously executed developer tests and independent validation/audit
results, not tests run during documentation closure. No full-suite result is
claimed for W045.

## Limitations and completion

Only the bounded Stage B collection and persistent collection-evidence slice is
complete. Preservation does not complete/release a Session or permanently close
the Evidence Archive. Known-Session lookup is not application-wide discovery.
Owner preservation locking serializes operations; multiple simultaneously
authoritative StorageManagers sharing one directory are not supported.

If interruption precedes temporary-outcome durability, missing outcomes are not
reconstructed from artifact existence; only still-retained live outcomes can be
preserved. Existing hard-link/filesystem and fsync prerequisites apply; power-loss
behavior was not independently tested. Validation used controlled software and
SSH/SFTP boundary doubles, not live external NATS, multi-host, Jetson, or hardware
acquisition validation. No automatic retry/refetch, new recovery subsystem,
evidence transport, registry, or lifecycle state is introduced.

W041-W044 retain their unchanged historical records and validated scopes. Q019
remains OPEN for permanent Evidence Archive closure, full Normal Stop/Kill
integration, eligible-Session selection, and overall integration validation.
Q024, Q022, Phase 16, and M015 remain OPEN.

---

# W046 - Q019 Permanent Evidence Archive Closure

**Status:** Complete - bounded explicit permanent closure implementation, developer
automated testing, independent manual IPython validation, and targeted independent
read-only re-audit PASS after correction.

## Purpose

Validate the separate operator-requested permanent closure contract under Decisions
357, 358, 362, and 363 and the accepted explicit-closure clarification. W045 collection
and evidence preservation do not automatically close an archive. This slice does
not implement Normal Stop/Kill orchestration or complete Q019.

## Workflow

```text
Separate explicit operator closure request for a known Session
    -> StorageManager checks unresolved writes under its preservation lock
    -> validate current persisted Stage A/B products, provenance, and final record
    -> fsync/readback confirms consistency and durability without cached bindings
    -> publish archive_closed=True in the existing compilation summary
    -> current readback reconfirms protected contents and closure
    -> ordinary and authorized writes cannot mutate closed products after restart
```

Call `storage.close_session_evidence_archive(session_id)` using the existing storage
root and original StorageManager component identity. No original Session binding,
SSH connection, new transport, or Session restoration is required. Collection
outcomes, evidence preservation, Session lifecycle, and archive closure remain
separate. Closure does not require successful retrieval or verification of every
scientific artifact: failed or unknown collection outcomes may coexist with closure
when all applicable outcomes are durably recorded.

StorageManager reuses the persisted Stage A/B baseline to check evidence identities,
Session associations, counts, provenance, complete intake audit, final Session
Record, and durable handoff. Pending outcomes, unresolved writes, conflicting or
incomplete products, and unconfirmed preservation block closure. A status flag,
cached confirmation, or successful artifact result alone cannot establish closure.

Only `evidence/compilation_summary.json` changes. Fsynced same-directory temporary
contents are atomically published, with supported directory fsync and current
product readback through commitment. Acquisition evidence, collection evidence,
intake audit, final Session Record, handoff, and scientific artifacts remain
unchanged. The existing preservation lock serializes closure with collection,
record writing, and recovery; overlapping closure requests publish only once.

Success returns `session_id`, `archive_closed=True`, `archival_confirmed=True`, and
product paths. Unsuccessful publication, durability, or readback raises instead of
confirming closure. If interruption follows summary publication, mutation remains
blocked; explicit retry, including after restart, reconfirms current closed contents
without rewriting or reopening them. Corruption remains unconfirmed, not silently
repaired. Existing authorized evidence recovery remains distinct and cannot modify
closed products. No extra closure file or self-referential evidence is introduced.

## Independent manual IPython validation

- Initial independent validation: **8/8 PASS**.
- Independent P2 correction validation: **2/2 PASS**.

These are separate validation stages. The initial successful scenarios did not
establish immutability for every equivalent path spelling.

## Automated validation and independent audit

- Initial developer impact-selected tests: **27/27 PASS** (17 new closure tests and
  10 directly affected persistence/recovery regressions).
- Initial independent source audit: **FAIL**, with one confirmed P2 defect.
  `session_session/nested/../session_record_final.json` bypassed the generic record
  guard because it inspected the unresolved parent name. After closure and restart,
  the protected final Session Record could be overwritten while the archive still
  reported closed. An independent temporary-directory probe reproduced the defect;
  two existing nearby tests passed but did not cover that alias after closure.
- Correction resolves the complete target path and configured storage root before
  identifying the managed final record. Public signatures and existing closure
  contracts are unchanged.
- Developer correction tests: **6/6 PASS**. The new regression reproduced the defect
  before correction and covers original/restarted owners and an aliased storage
  root; a positive regression preserves legitimate pre-closure writing. Selected
  existing tests cover alias concurrency, closed-write rejection, authorized record
  recovery, and normal record writing.
- Final targeted independent read-only re-audit: **PASS**. The original P2 finding
  was resolved, with no remaining confirmed P0-P3 findings within scope. No additional
  tests or probes were necessary during that re-audit under impact-based testing.

These are previously executed developer tests and independent validation/audit
results, not software tests or a new audit performed during documentation closure.
No full-suite result is claimed for W046.

## Limitations and completion

Only explicit permanent Evidence Archive closure is complete. W041-W045 retain
their unchanged historical records and validated scopes. Existing single-owner,
filesystem/fsync, and owner-access prerequisites apply; multiple simultaneously
authoritative StorageManagers sharing a directory remain unsupported. Power-loss
behavior was not independently tested. Validation used controlled local software
and SSH/SFTP boundary doubles, not live external NATS, multi-host, Jetson, or hardware
acquisition validation. No registry, database, new lifecycle state, automatic replay,
recovery subsystem, or scientific transformation is introduced.

Q019 remains OPEN for full Normal Stop/Kill integration, eligible-Session selection,
and overall integration validation. Q024, Q022, Phase 16, and M015 remain OPEN. Archive
closure does not complete or release the Session or close these broader milestones.

---

# W047 - Q019 Normal Stop Integration

**Status:** Complete - bounded Normal Stop implementation, developer automated
testing, independent manual IPython validation, and targeted independent read-only
re-audit PASS after correction of two P2 findings.

## Purpose

Validate Normal Stop under Decisions 356, 357, 362, 364, and 365, using the completed
W041 receipt, W042 producer/marker, W043 Stage A, and W044 durable handoff mechanisms.
Normal Stop completion is separate from later operator-requested Stage B collection
and separately requested permanent Evidence Archive closure.

## Workflow

```text
Explicit Normal Stop for the launched Session
    -> retain the Session's Q019 closeout association before asynchronous shutdown
    -> stop/finalize participating AcquisitionNodes and confirm their publications
    -> release only confirmed-clean node reservations and record active Experiment end
    -> confirm SynchronizationManager and Controller closing-Session publications
    -> durably publish the Session acquisition_evidence_completion marker
    -> independently verify complete durable Ingestor receipt through W041
    -> archive current protected Stage A evidence, audit, summary, and final record
    -> compile and durably preserve the separate ArtifactManifest handoff
    -> recheck current preservation under intake/storage/admission locks
    -> Session completes; Evidence Archive remains OPEN
```

Call `await controller.normal_stop_session(communication=controller_communication,
receiving=ingestor_communication, result_window_s=..., reason=None)` with the original
launch communication, matching Ingestor receiver, and configured StorageManager.
The launch window bounds node shutdown requests; the explicit result window bounds
producer closeout requests. No new command schema, lifecycle state, transport, or
service ownership is introduced.

Completion requires confirmed producer publication, independent receipt verification,
current durable Stage A readback, marker identity, all required Controller-owned
evidence, and matching durable handoff. Current acquisition envelopes and their
audit must match the preserved final Session Record. Intake, StorageManager
preservation, and Controller admission locks remain held in that order through
the synchronous completion commitment; no synchronous lock spans an await.

Cancellation propagates and clears temporary operation admission, but retains the
Session's Q019 association, evidence, journals, and outstanding obligations. Failed
or uncertain preservation cannot permit legacy finalization or binding release.
Node cleanup failures retain the existing failed-Session behavior. Late accepted
or rejected acquisition intake blocks completion when record/audit coverage is
missing, without replacing the preserved baseline. Explicit retry can persist
changed intake through existing Stage A interfaces, without repeating confirmed
node shutdown or refinalizing scientific files. Unsafe or interrupted products
still require existing authorized recovery, not implicit repair.

Normal Stop does not automatically collect artifacts, permanently close the archive,
or release retained service bindings. Existing explicit binding release preserves
the terminal Session Record. Later Stage B uses the durable saved handoff without
restoring original bindings; permanent closure remains a separate operator request.

## Independent manual IPython validation

- Initial independent validation: **6/6 PASS**.
- Independent correction validation: **3/3 PASS**.

These are separate validation stages; the initial passing scenarios did not cover
the two subsequently reproduced failure windows.

## Automated validation and independent audit

- Initial developer impact-selected tests: **19/19 PASS**.
- Initial independent read-only audit: **FAIL**, with two confirmed P2 defects.
  Cancellation before marker creation allowed legacy finalization to complete
  without receipt verification, Stage A preservation, or durable handoff. A separate
  controlled cross-thread probe accepted late acquisition intake after handoff
  preservation; Normal Stop completed while the final Session Record omitted the
  envelope and its audit. Stored scientific data was not demonstrated lost.
- Correction establishes the existing Q019 association before the first await and
  retains it through failure/cancellation. Completion now compares current envelopes
  and audits against the durable final record under existing locks, rejecting missing
  coverage without substituting an unarchived snapshot.
- Developer correction tests: **12/12 PASS** - four new regressions and eight directly
  affected existing tests. Coverage includes pre-marker cancellation, missing
  synchronization confirmation, late accepted and rejected intake, preservation
  of existing products/journals, explicit retry, and unchanged public interfaces.
- Final targeted independent read-only re-audit: **PASS**, both original P2 findings
  resolved, with no remaining confirmed P0-P3 findings. No additional tests were
  necessary during that source re-audit under impact-based testing.

These are previously executed developer tests and independent validation/audit
results, not software tests or another audit performed during documentation closure.
No full-suite result is claimed for W047.

## Limitations and completion

Only bounded Normal Stop integration is complete. W041-W046 retain unchanged
historical validation records and scopes. Controlled local software/broker-double
coverage and reported IPython checks do not establish live external NATS, multi-host,
Jetson, hardware, or power-loss validation. Existing W041 receiving-origin/history
requirements and StorageManager filesystem/durability prerequisites still apply.
No automatic replay, recovery subsystem, scientific transformation, eligible-Session
discovery, or implicit Stage B/closure operation is introduced.

Q019 remains OPEN for Kill Session integration, eligible-Session selection, and
overall integration validation. Q024, Q022, Phase 16, and M015 remain OPEN.

---

# W048 - Q019 Kill Session Integration

**Status:** Complete - bounded Kill implementation, targeted developer testing,
independent manual IPython validation, and final independent read-only re-audit
PASS after correction of all previously identified findings.

## Purpose

Validate explicitly authorized Kill under Decisions 034, 113, 313, and 357-365,
using existing evidence, handoff, storage, lifecycle, and recovery mechanisms.
Kill preserves available information without claiming Normal Stop completeness.

## Workflow

Call `await controller.kill_session(communication=controller_communication,
result_window_s=..., operator_authorized=True, reason=None)` for the launched
Session with its original evidence owners.

```text
Explicit operator-authorized Kill
    -> retain the bound Ingestor's Kill handoff obligation before any suspension
    -> record experiment_abort for an active Experiment and abort the Session
    -> attempt participant shutdown; report actual cleanup results and uncertainty
    -> preserve available journal-backed evidence, intake audit, partial summary,
       final aborted Session Record, and verified ArtifactManifest handoff
    -> retain outstanding safety, preservation, and resource-release obligations
```

Local `cleanup_occurred=True` does not confirm participant cleanup or hardware
safety. Partial preservation does not establish complete acquisition receipt;
unavailable information and unconfirmed cleanup remain explicit. Kill neither
automatically collects scientific artifacts nor permanently closes the archive.

Later operator-requested Stage B collection can use the durable partial handoff
without original runtime bindings. Additional verified manifests from authorized
recovery may refresh it only before the first Stage B attempt. Any attempt,
including failed or incomplete collection, makes the handoff immutable. Existing
historical evidence, collection outcomes, and permanent archive closure remain
protected. Repeated Kill reports the verified durable closure state without mutation.

Ingestor release requires matching current durable preservation and handoff
coverage, including admitted Kill obligations with empty intake or unavailable
archival confirmation. Failed release retains the binding, evidence, and journal.
Kill retry and Controller release reject current acquisition envelopes or intake
audit not represented in the immutable final Session Record. Intake and storage
guards protect synchronous confirmation; release rechecks after asynchronous
unsubscription without holding synchronous preservation locks across an await.
Unsafe writes require existing authorized recovery, not implicit repair or replay.

## Independent manual IPython validation

- Initial independent validation: **5/5 PASS**.
- First correction revalidation: **4/4 PASS**.
- Final empty-intake correction revalidation: **2/2 PASS**.

## Automated validation and independent audit

- Original developer impact-selected tests: **45/45 PASS**.
- Initial independent audit: **FAIL**, two P2 findings and one P3 finding.
  Partial Kill without a completion marker could release Ingestor without durable
  handoff; late accepted acquisition envelopes or rejected-intake audit could be
  omitted from the immutable final record while preservation was reconfirmed;
  repeated Kill incorrectly reported an already closed archive as open.
- First corrections require partial-Kill handoff coverage, exact current
  acquisition-envelope/audit coverage, and verified closure-state reporting.
  Developer correction tests: **13/13 PASS**.
- Subsequent independent re-audit: **FAIL**, remaining P2 empty-intake case.
  Failed compilation-summary persistence left confirmation unavailable; release
  incorrectly interpreted that absence as no Kill preservation obligation.
- Final correction registers a binding-local Kill handoff obligation before
  asynchronous shutdown, retains it through failure/cancellation, and clears it
  only after confirmed release. Targeted developer tests: **9/9 PASS**.
- Final independent read-only re-audit: **PASS**, all previous defects resolved,
  with no remaining confirmed P0-P3 findings. It independently ran four focused
  tests covering failed summary persistence, cancellation/retry, empty-intake
  handoff failure/retry, and concurrent intake during release unsubscription;
  **4 passed, zero failures or skips**.

These are prior developer testing and independent validation/audit results, not
tests or another audit performed during documentation closure. No full-suite
result is claimed for W048.

## Limitations and completion

Only bounded Kill integration is complete. W041-W047 historical records remain
unchanged. This record does not claim live external NATS, multi-host, Jetson,
hardware, or power-loss validation. Existing journal, receiving, filesystem,
and explicit authorized-recovery prerequisites remain applicable. No automatic
recovery, application restoration, new lifecycle state, or evidence subsystem is
introduced. Normal Stop completeness and resource-safety requirements are unchanged.

Q019 remains OPEN for eligible-Session selection and overall integration
validation. Q022, Q024, Phase 16, and M015 remain OPEN.

---

# W049 - Q019 Eligible-Session Selection and Multi-Session Collection

**Status:** Complete - bounded implementation, targeted developer testing,
independent manual validation, and final independent read-only audit PASS after
correction of the original P2 and P3 findings.

## Purpose

Validate Decisions 359, 360, and 364's saved-Session enumeration, independent
eligibility and collection-availability assessment, and operator-selected collection
using existing W041-W048 persistence, handoff, recovery, and closure mechanisms.

## Workflow and interfaces

```text
StorageManager enumerates existing persistent Session directories and records
    -> independently confirms each candidate's lifecycle and collection availability
    -> retains unavailable candidates with separate blockage reasons
Operator selects one or multiple confirmed eligible and available Sessions
    -> Controller independently processes each selected Session
    -> StorageManager revalidates under collection guards before retrieval/persistence
    -> existing per-Session collection preserves actual outcomes and evidence
    -> report individual results and complete_success, partial_success, or failure
```

- `PersistentStorageManager.list_saved_sessions()` lists saved candidates without
  a registry, original runtime bindings, or application restoration.
- `get_saved_session_collection_status(session_id)` reports Session identity,
  confirmed lifecycle state, eligibility, availability, and separate reasons.
- `collect_saved_artifacts(session_id, *, evidence_id, require_eligible=True)`
  enforces ordinary selection requirements by default. Explicit `False` preserves
  existing internal Stage B/recovery preconditions, not ordinary operator selection.
- `Controller.collect_saved_session_artifacts(session_id, *, evidence_id)` enforces
  the same requirements for the existing single-Session operator entry point.
- `collect_selected_session_artifacts(selections)` accepts a Session-ID-to-stable-
  evidence-ID mapping and reuses per-Session collection independently. Ineligible or
  unavailable candidates are rejected without collection; individual failures do
  not prevent processing other valid candidates. Results include assessments,
  collection outcomes/errors, and an overall summary.

Eligibility requires durably confirmed `completed`, `failed`, or `aborted`;
`stopping` or unverified terminal information does not qualify. Scientific-file
incompleteness, absence, corruption, or unconfirmed participant cleanup does not
independently disqualify a terminal Session. Collection availability separately
requires verified safe preservation information. Missing, inconsistent, corrupted,
or interrupted preservation blocks ordinary collection pending existing authorized
recovery; permanently closed archives cannot accept further collection.

Listing is observational; collection revalidates under existing preservation and
handoff guards. Stable evidence identities preserve idempotency without automatic
refetch, repair, retries, or cross-Session transactions. No special ordering is
required. Selection does not authorize hardware/resource release or change lifecycle.
Existing handoff freezing, immutable records/history, and archive closure remain intact.

## Validation and audit history

- Initial developer tests: **14/14 PASS**.
- Initial independent manual IPython validation: **6/6 PASS**.
- Initial independent read-only audit: **FAIL**. P2: the existing single-Session
  API omitted eligibility enforcement, allowing retrieval from persisted `stopping`.
  P3: nested W049 `IsolatedAsyncioTestCase` fixture cleanup silently failed because
  the nested fixture had no initialized runner, causing temporary-resource problems.
- Corrections explicitly enforce eligibility in ordinary Controller APIs and
  change StorageManager's default after caller review. Internal Stage B/recovery
  callers explicitly retain different preconditions where permitted. W049 fixture
  cleanup callbacks register with the active owner; tests verify both resource
  removal and observable cleanup failure without skipping remaining callbacks.
- Corrective developer tests: **24/24 PASS**.
- Independent manual correction validation: **6/6 PASS**; the Windows HDF5
  temporary-file cleanup error did not recur.
- Final independent read-only audit: **PASS**. Both original findings fully
  resolved; no new confirmed P0-P3 findings. Six focused tests passed with zero
  failures or skips. An independent mixed-selection resource probe confirmed zero
  test errors/failures, removed temporary root, and zero additional open HDF5 files.

These are prior developer tests and independent validation/audit results, not tests
or another audit performed during documentation closure. No full-suite result is
claimed. No production resource-lifecycle defect was demonstrated by the fixture issue.

## Limitations and remaining work

Enumeration uses the configured records directory, not discovery of other storage
roots, and does not pre-probe scientific sources. Validation is software/fixture-
based; it does not establish live external NATS, multi-host, Jetson, hardware,
deployment, or power-loss guarantees. Existing filesystem, journal, receiving,
and authorized-recovery prerequisites remain applicable. GUI presentation remains
future work outside this repository; no new lifecycle, registry, or recovery
infrastructure is introduced. W041-W048 historical records remain unchanged.

Q019 remains OPEN for overall integration validation across its completed bounded
slices, including their combined lifecycle, preservation, recovery, and collection
boundaries. W049 does not establish that broader validation or close Q019.
Q022, Q024, Phase 16, and M015 remain OPEN.

---

# W050 - Q019 Consolidated Session Preservation and Collection Integration

**Status:** Complete - W041-W049 independently validated/audited, overall
independent manual integration validation PASS, and final independent integration
source audit PASS with no confirmed P0-P3 production defects. Q019 is CLOSED.

## Scope and accepted contracts

Decisions 356-366 and the accepted Decision 364 selection clarifications are
implemented through the completed W041-W049 slices:

- W041: durable Session-specific receiving progress, journal-before-confirmed-ACK,
  independent receipt proof, and non-overlapping JetStream routing.
- W042: producer publication confirmations and stable Controller completion marker.
- W043: protected Stage A evidence/audit/summary and separate final Session Record.
- W044: verified durable ArtifactManifest handoff independent of runtime bindings.
- W045: Stage B collection and direct durable collection evidence with authorized
  interrupted-write recovery and no implicit refetch.
- W046: separate explicit permanent closure and immutable archived products.
- W047: complete Normal Stop preservation before successful completion.
- W048: authorized Kill, Experiment abort, explicit partial preservation and safety
  obligations, and authorized pre-collection partial-handoff refresh.
- W049: persisted enumeration, terminal eligibility versus collection availability,
  independent single/multi-Session collection, and aggregate outcome reporting.

Historical slice records and their failed audits, corrections, and validation
results remain unchanged. Closure does not change accepted contracts or owners.

## Composite integration scenarios

`tests/test_session_preservation_integration.py` uses actual domain and command
owners with controlled broker/SFTP doubles:

1. Scientific acquisition and Normal Stop, durable receipt and preservation,
   handoff and safe service release, retained-service reuse for Kill with Experiment
   abort, restart enumeration, saved single/multi-Session collection, idempotency,
   and explicit permanent closure. Source bytes, historical evidence/audit/records,
   retained Kill reservations, and post-closure rejection are checked.
2. Interrupted collection-evidence persistence, unavailable status after restart,
   rejected unauthorized recovery, accepted specifically authorized recovery,
   stable-outcome readback without refetch, and subsequent closure.
3. Permanent sequential-Normal-Stop regression: both Sessions produce actual
   scientific output, retain separate durable marker/receipt and finalized handoff
   identities, safely release and reuse the same services/adapters, preserve the
   first Session's bytes/records, and appear eligible and available after restart.

The third scenario is named
`test_successive_normal_stops_preserve_separate_sessions`. Test-double delivery
selects the current Session's consumer by filter and delivers only matching
history; it does not feed one Session's history into another's journal.

## Validation and audit evidence

- Prior developer integration testing: **7/7 PASS** (two composite workflows and
  five impact-selected existing controls).
- Independent manual IPython integration validation: **2/2 PASS**, including
  temporary-resource cleanup.
- Final comprehensive independent read-only source audit: **PASS**, no confirmed
  P0-P3 production defects and no required correction. Both committed composites
  passed independently (**2 tests, zero failures/skips**). An additional temporary
  sequential Normal Stop probe passed after matching real Session-filtered broker
  delivery; initial probe failures were test-double delivery issues, not production
  defects. The audit recommended retaining the successful probe as permanent coverage.
- Closure preparation added that permanent regression. Newly executed developer
  tests: **3/3 PASS**, covering the new scenario and the two existing composites
  directly affected by the test delivery helper. No production code was changed,
  no full suite was run, and no additional independent validation/audit is claimed.
- `git diff --check` and documentation consistency checks passed during closure.

## Limitations and remaining work

Integration validation uses simulated broker/SFTP infrastructure. It does not
establish live hardware, external NATS deployment, multi-host/Jetson operation,
or power-loss guarantees. The integrated scientific product is JSONL and correctly
reports `copied_unverified`; validated HDF5 verification remains in the slice
coverage. Existing intact broker-history, journal, hard-link/filesystem, and
durability prerequisites remain applicable.

Q019 closure does not implement automatic recovery, application restoration,
journal deletion, scientific transformation, a GUI, or new lifecycle states.
Q022, broader Q024 (including deferred journal/resource retirement), Phase 16, and
M015 remain OPEN, with their existing separate implementation, deployment, and
validation criteria unchanged. W050 closes Q019's supported evidence-closeout,
collection, selection, and overall software integration scope only.

---

# W051 - NATS Ingestor-StorageManager Persistence Boundary

**Status:** Complete, independently validated and audited after correction.

## Implemented workflow and interfaces

Under Decisions 137 and 375, `NatsIngestorCommunication.persist_accepted_envelope()`
delivers previously accepted Session intake to the existing StorageManager owner
through NATS. `NatsStorageManagerCommunication` executes `persist_envelope`,
`read_envelopes`, and `read_session_preservation` through authoritative owner
methods and locks. Stable command/requester/target identities accompany envelopes
in the existing records JSONL; no new persistence store or service owner is created.

StorageManager flushes/fsyncs writes, performs supported directory synchronization,
and verifies exact current owner-side readback before durability confirmation.
Identical retries, including after restart, reconfirm rather than append;
conflicting command reuse is rejected. Fresh-only NATS replies and per-attempt
`request_nonce` correlation reject historical and delayed responses. Failed,
timed-out, or cancelled requests retain Ingestor's accepted intake.

Ingestor's `compile_session_evidence` and `verify_acquisition_receipt` NATS
operations reuse journal-verified compilation and W041 receipt proof. Publication,
journal acceptance, receipt, and archival confirmation remain distinct.
Point-in-time owner readback is not a distributed lock or permission to release
or complete a Session. Existing Q019 recovery and immutable-archive guards remain.

Every present `persistence_command` block is validated before retry matching or
confirmation. Malformed, null, incomplete, or invalid identity metadata is refused
without appending, truncating, rewriting, or automatically repairing history.
Legitimate legacy records without that field remain supported.

## Validation and audit evidence

- Initial developer testing: **32 targeted tests PASS**.
- Initial independent manual IPython validation: **11/11 PASS**.
- Initial independent audit: **FAIL**, one P2: damaged persisted correlation was
  mistaken for an absent command, allowing duplicate envelope writes on retry.
- Correction: validation in StorageManager's locked record reader before matching
  and readback; public NATS regressions for null/incomplete metadata, restart,
  unchanged history, and legacy compatibility.
- Corrective developer testing: **13 targeted tests PASS**.
- Independent manual IPython revalidation: **14/14 PASS**.
- Final independent read-only re-audit: **PASS**, original P2 resolved and no
  remaining confirmed P0-P3 findings. Five committed focused tests and one
  temporary probe passed; the probe covered four additional malformed metadata
  cases, new-command rejection, direct confirmation rejection, and unchanged bytes.

These are previously executed results, not new testing during documentation closure.

## Limitations and remaining work

Validation uses actual service owners/adapters with broker doubles; it establishes
no live NATS, multi-host, hardware, or independently tested power-loss guarantees.
Completely removed correlation metadata is indistinguishable from genuine legacy
history; no tamper-proof integrity guarantee is claimed.

This bounded slice does not establish full independent-service deployment.
Controller closeout/release, AcquisitionNode and SynchronizationManager adaptation,
cross-process maintenance and authorized recovery, role launchers, and installation
verification remain outstanding. Q022 remains OPEN. Q019 remains CLOSED in W050;
Q024, Phase 16, and M015 remain OPEN. Historical workflows are unchanged.

---

# W052 - Shared-Process Correlated Envelope Persistence

**Status:** Complete, independently validated and audited.

## Implemented workflow and interfaces

Decision 376 permits local communication between distinct Ingestor and StorageManager
owners within one process. Construct `InMemoryIngestor` with its existing
`PersistentStorageManager` and `correlated_persistence=True`. In this explicit
mode, `receive_envelope()` retains accepted intake without legacy automatic
uncorrelated forwarding. `await persist_accepted_envelope(envelope,
command_id=...)` calls the same authoritative StorageManager correlated writer
locally, without internal NATS, a second owner, or another persistence mechanism.
Legacy construction and transport-callback behavior remain supported.

Stable command/requester/target identity remains in existing records JSONL.
StorageManager retains persistence locking, flush/fsync, supported directory
synchronization, correlation validation, and exact current readback. Identical
retries, including after reconstructing both components, do not append; conflicting
command reuse is refused. Invalid correlation/history cannot authorize repair or
duplicate append, and legitimate uncorrelated legacy records remain compatible.

Ingestor retains its binding lock through synchronous local owner confirmation,
using existing intake-to-storage lock ordering. Concurrent Session-binding abort
cannot overtake persistence; subsequent persistence against the aborted binding
is rejected without another append. Persistence failure retains accepted intake.
A failed runtime-evidence journal blocks confirmation; existing runtime evidence
journal-before-acknowledgment behavior is unchanged. Persistence confirmation is
not acquisition-intake durability or archival completion.

W051's NATS adapters remain compatible for existing external/compatibility use.
Existing Q019 preservation, authorized recovery, and immutable archive protections
remain; closed archives reject new writes while identical persistence readback
can reconfirm already stored records without changing archived products.

## Validation and audit evidence

- Developer verification: **17 distinct targeted tests PASS**.
- Independent user-run manual IPython validation: **16/16 PASS**.
- Independent read-only audit: **PASS**, no confirmed P0-P3 defects.
- Audit checks: **eight focused tests and two temporary probes PASS**, including
  binding-abort ordering and rejection of combined legacy/correlated forwarding.
- The binding-abort probe was retained as
  `test_binding_abort_waits_for_local_persistence` in
  `tests/test_local_persistence.py`; **four focused developer tests PASS**.
  Explicit events coordinate actual owner calls without sleeps or mocked locks;
  byte readback verifies no append after abort. Its presence in committed HEAD
  was verified before closure (file commit
  `cb7dc6160aed96e794840bfc6a61012105b8af84`).

These are previously executed results, not new software testing or independent
validation during documentation closure. W051's history is unchanged.

## Limitations and remaining work

Synchronous local disk I/O may block the calling event loop and cannot be
interrupted by task cancellation during the synchronous section. Restart coverage
resupplies acquisition intake; durable AcquisitionNode-to-Ingestor intake
reconstruction remains unimplemented. Shared-process bootstrap and lifetime
enforcement are deferred, not established merely by constructing both components.
No independently validated live NATS, multi-host, hardware, or power-loss
guarantees are claimed.

Q022 remains OPEN for acquisition/Experiment/synchronization adaptation,
Controller closeout/release, external maintenance/recovery, configuration/launch
and installation verification. Q019 remains CLOSED; Q024, Phase 16, and M015
remain OPEN. This closes only the supported local persistence slice.

---

# W053 - Product-Based Scientific Acquisition and Operational Evidence

**Status:** Complete, independently validated and audited after correction;
bounded Q022 Slice 3A under Decisions 377-378.

## Implemented workflow and interfaces

Installation-declared `ScientificProductDeclaration` records define supported
products; explicit Experiment `ScientificOutputSelection` records determine what
is acquired. `DeviceAdapter.collect_products(products, *, session_id,
experiment_id, acquisition_node_id)` produces selected declaration-keyed rows
separately from operational RuntimeEvidenceMessages.
`DeviceManager.collect_products(products_by_device, *, session_id, experiment_id,
acquisition_node_id)` coordinates adapters and retains completed partial results.
Empty product selections perform no scientific reads. No legacy
`collect_records()` or `collect_scientific_records()` fallback remains in the
active node collection pathway.

`AcquisitionNode.run_one_iteration()` coordinates selected observations and their
per-observation metadata into LocalStorageManager products, not Ingestor intake.
JSONL/HDF5 persistence retains applicable observation identity/order, available
native timestamps, framework Session/Experiment timing, provenance, and artifact
manifests. Non-frame metadata stays with its scientific observation without
frame-name inference. Iteration counts describe rows accepted by local storage;
they do not replace its flush/finalization durability confirmation.
AcquisitionNode no longer produces, batches, or forwards routine scientific
envelopes.

Session start/stop, acquisition-health observations and interpretations, failures,
and artifact manifests remain separate operational evidence. Retained immutable
RuntimeEvidenceMessage snapshots preserve producer/Session identity across
publication failure and retry. `publish_new_runtime_evidence()` and the existing
manifest publisher complete applicable durable publication before Session-scoped
command results. Ingestor retains journal-before-ACK, evidence-ID deduplication,
known-Session reconstruction, and persistent compilation. Publication, durable
acceptance, complete receipt, and archival remain distinct confirmations.

## Audited failure and correction

The initial audit found a P2: DeviceManager collected both devices, but an
operational-evidence intake exception while processing the first result stopped
AcquisitionNode before persisting the second device's already-acquired observation.
The first artifact finalized with one row and the second with zero.

Correction `2afac85` attempts scientific persistence across all completed results
before operational-evidence handling. Individual row, product, device, and
evidence errors do not unnecessarily prevent other writable observations from
receiving persistence attempts. Partial-collection results follow the same
preservation path. Single failures remain identifiable; multiple independent and
nested failures retain their original exceptions. Failure-evidence handling errors
do not mask the acquisition failure. Failed iterations report failure and prevent
ordinary iteration replay; retained evidence is not duplicated.

Failed writes are reported, not claimed recovered. No new durable scientific
retry mechanism, evidence transport, or automatic replay was introduced.
Scientific finalization and existing Q019 receipt, Stage A/B, handoff, Normal
Stop/Kill, release, authorized recovery, and immutable archive protections remain.

## Validation and audit evidence

- Initial developer verification: **80 distinct targeted tests PASS**.
- Initial independent user-run manual IPython validation: **17/17 PASS**, covering
  selected products, local observations/metadata/timing/provenance, manifests,
  lifecycle evidence, unselected products, no scientific-envelope intake,
  operational durability/deduplication, restart reconstruction, and partial failure.
- Initial independent source audit: **FAIL**, the P2 scientific-observation loss
  after operational-evidence intake failure described above.
- Corrective developer verification: **37 distinct targeted tests PASS**, including
  seven permanent regressions for two-device intake failure, independent scientific
  writes, multiple errors, partial collection, other products/rows, and failure-
  evidence error reporting, with preservation, lifecycle and publication controls.
- Independent user-run corrective manual IPython validation: **18/18 PASS**.
- Final independent read-only re-audit of `2afac85`: **PASS**, original P2 resolved,
  no remaining confirmed P0-P3 findings. **13 focused regression tests and two
  independently constructed negative probes PASS**. The probes combined row
  serialization, invalid/duplicate operational evidence, nested ExceptionGroups
  and failure-evidence errors, and injected an actual Ingestor journal `fsync`
  failure. Writable scientific observations survived without false acceptance,
  successful iteration, or scientific replay.

These are previously executed results, not new software tests, manual validation,
or another audit during documentation closure. Developer runs overlap; the initial
and corrective counts are separate, not an additive unique-test total.

## Limitations and remaining work

Verification used temporary local storage, simulated devices and broker doubles.
It establishes no live external NATS, multi-host deployment, hardware, or power-loss
guarantees; an injected `fsync` failure is not power-loss validation. A persistence attempt
does not guarantee successful storage, and unavailable evidence acceptance remains
unconfirmed. This is not complete independent-service deployment.

Slice 3B still owns removal of obsolete Ingestor scientific-envelope intake/audits,
StorageManager scientific-envelope persistence/recovery, NATS commands and
compatibility paths, redundant exports/tests/demos/active documentation, and
reconciliation of owner-level Session Records, Normal Stop/Kill, release blockers,
compilation, recovery, and archival closeout. Retain historical interpretation only
where accepted contracts require it; do not rewrite preserved records. Decision
378's final independent integration audit must verify functional preservation and
absence of obsolete scientific-envelope architecture after replacement.

W051/W052 remain unchanged historical validations, not justification for keeping
superseded code. Only Slice 3A is closed. Decision 378's overall replacement and
Q022 remain OPEN; Q019 remains CLOSED. Q024, Phase 16, and M015 remain OPEN.

---

# W054 - Operational Evidence Closeout and Scientific-Envelope Removal

**Status:** Complete, independently validated and audited after correction;
bounded Q022 Slice 3B under Decisions 313 and 376-378.

## Implemented boundary and interfaces

Scientific observations and per-observation metadata remain AcquisitionNode-local
in LocalStorageManager products under the installed/selected product contract
validated in W053. Ingestor no longer accepts or persists routine scientific
observations. Obsolete scientific-envelope intake, journaling, auditing,
compilation, recovery, correlated persistence, NATS commands/dispatch, exports,
compatibility paths and redundant tests/demos are removed, not retained as shims.
The removed Ingestor APIs include `receive_envelope()`,
`persist_accepted_envelope()`, `accepted_envelopes`, `ingest_audit`, and the
scientific `correlated_persistence` constructor option.

`InMemoryIngestor.receive_runtime_evidence()` retains operational evidence and
ArtifactManifests, journal-before-ACK, evidence identity/conflict rejection,
deduplication, complete runtime intake auditing and known-Session reconstruction.
`compile_persistent_runtime_evidence()` and
`compile_durable_session_evidence(session_id)` retain persistent compilation and
journal-verified operational evidence, audit and manifest-handoff readback. W041
receipt verification remains independent of publication and archival confirmation.

`PersistentStorageManager(storage_root, *, global_artifact_root=None,
retrieval_endpoints=None, evidence_publisher=None, component_id="storage")` takes
an explicit directory root, not a scientific-envelope record filename. It retains
Session Records, Evidence Archives, global scientific-artifact collection,
authorized recovery and permanent closure, without observation appenders or
correlated envelope writers. Ingestor and StorageManager remain distinct owners
with permitted local calls under Decision 376; no second owner is instantiated.

`NatsIngestorCommunication` retains operational compilation and verified-receipt
requests. `NatsStorageManagerCommunication` retains readiness and preservation
readback. Existing fresh-only replies and per-attempt correlation remain; no
envelope persistence/readback command remains. This is not complete cross-process
orchestration or shared-lifetime bootstrap.

## Preserved closeout and release guarantees

Normal Stop still requires producer publication confirmation, its completion
marker, independently verified durable receipt, Stage A preservation and durable
ArtifactManifest handoff before completion. Kill preserves available operational
evidence with explicit uncertainty rather than claiming complete receipt or
participant cleanup. Admitted Kill obligations block release even with empty
intake or unavailable archival confirmation. Scientific-envelope counts or
receipts are no longer completion requirements.

New Session Records preserve configuration, lifecycle, Experiment outcomes and
cleanup context separately from operational archive contents. Strict plain-data
interpretation of historical Session Record envelope/audit fields remains where
required; no legacy writers are restored and historical products are not rewritten.
Current operational evidence, the complete intake audit and manifest coverage
govern preservation and release. Stage A/B, saved-Session eligibility/collection,
authorized interrupted-write recovery without refetch, immutable permanent
closure, and successive service reuse retain their existing contracts.

Controller release locks Ingestor intake before StorageManager preservation,
retaining both through the final synchronous checks and binding retirement,
never across asynchronous unsubscription. Intake completed before the final
guard invalidates stale confirmation; intake attempted inside it waits.
Evidence accepted after Controller retirement remains Ingestor-owned. Ingestor
retains its binding/evidence and rejects release against stale archival coverage.
Existing compilation and Stage A reconciliation can preserve additional coverage
only within accepted lifecycle boundaries; Stage B history and closed archives
are not rewritten, and no automatic recovery is introduced.

## Audit findings and corrections

The initial independent audit of `4f7ee65` returned **FAIL**:

- **P2:** Normal Stop Controller release could miss concurrent accepted evidence,
  rejected intake, or duplicate redelivery after its final intake snapshot. Release
  succeeded with 11 current audit entries but only 10 archived; Ingestor's own
  release guard retained the evidence. The correction extends existing intake ->
  preservation locking across authoritative checks and Controller retirement.
- **P3:** A product-acquisition failure test retained unused envelope-handoff
  policy configuration. The obsolete fields were removed while preserving the
  actual `collect_products()` failure regression.

Three deterministic race regressions reproduced the P2 before correction. Six
permanent regressions cover all three intake variants during unsubscription and
final readback, retained evidence/audit, stale-archive rejection and serialized
retirement. The final independent corrective re-audit of
`7f500684e7288a20ead03400038ac9989f7064c1` returned **PASS**: both findings resolved,
with no remaining confirmed P0-P3 findings in the corrective scope.

## Verification history

- Initial developer full regression: **848 run, 841 passed, 7 optional skips**.
- Initial independent user-run IPython validation: **9/9 manual checks and 3/3
  Session-preservation integration tests PASS**.
- Initial independent audit: **FAIL**, the P2/P3 above; **21 focused tests PASS**
  with independent negative probes, including the three release-race reproductions.
- Corrective developer verification: **32 focused tests PASS**; full regression
  **854 run, 847 passed, 7 optional skips, zero failures/errors**.
- Independent user-run corrective IPython validation: **9/9 PASS**, comprising
  the six race regressions and three preservation integration tests.
- Final independent corrective re-audit: **PASS**, with **25 focused tests and
  10 independent deterministic probes PASS**. Probes exercised the three intake
  variants at unsubscription, final readback and immediately before retirement,
  plus cancellation with waiting intake. They also checked accepted-boundary
  reconciliation, release/reuse and cross-Session rejection.

These are recorded prior results, not tests or a new audit during documentation
closure. Runs overlap and must not be combined into a unique-test total.

## Limitations and remaining scope

Verification used simulated devices, broker/SFTP infrastructure and temporary local
storage; it does not establish live hardware, multi-host deployment or power-loss
guarantees. Synchronous storage I/O can block the calling event loop. Remaining
cross-process Controller, acquisition/Experiment, synchronization,
maintenance/recovery and release adaptation, shared-process bootstrap/lifetime
enforcement, configuration, role launching and installation checks are not closed.

W041-W053 retain their historical records, including superseded W051/W052
scientific-envelope validation. W054 closes only Slice 3B. The combined Decision
377-378 replacement still requires final independent functional integration and
legacy-removal (zombie-code) auditing across AcquisitionNode, DeviceAdapter,
DeviceManager, Ingestor, StorageManager, Controller and NATS boundaries. No final
Decision 378 acceptance is claimed. Q019 remains CLOSED; Q022, Q024, Phase 16 and
M015 remain OPEN.

---

# W055 - Scientific-Product Replacement Integration and Final Acceptance

**Status:** Complete, final implementation acceptance of Decisions 377-378,
following W053/W054 independent validation/audits, the combined integration audit,
and targeted verification of its remaining test-only P3 correction.

## Accepted implementation and integration scope

Installation-declared ScientificProductDeclarations and explicit Experiment
ScientificOutputSelections govern DeviceAdapter/DeviceManager collection.
AcquisitionNode coordinates LocalStorageManager JSONL/HDF5 persistence of
scientific observations and associated metadata regardless of size. Identity,
ordering, available native timestamps, framework timing and provenance remain
with local artifacts. Scientific observations and per-observation metadata do
not enter Ingestor; manifests describe artifacts without embedding observations.

Operational lifecycle/terminal, health/failure, timing and manifest evidence retain
their authoritative owners and existing RuntimeEvidenceMessage mechanisms.
Ingestor retains journal-before-ACK, identity/conflict checks, deduplication,
known-Session reconstruction, intake auditing and durable compilation. Publication,
durable receipt and archival confirmation remain distinct. Controller closeout
and StorageManager preservation/collection use operational evidence and manifest
coverage, not obsolete scientific-envelope counts or receipts.

The combined independent audit traced declaration -> selection -> product
collection -> local persistence/finalization -> manifest publication -> operational
intake -> Controller closeout -> StorageManager preservation and global collection.
It covered partial acquisition, scientific writes, operational validation/intake,
journal and publication failures, missing producer completion, Normal Stop/Kill,
Stage A/B, handoff/release guards, restart, saved-Session selection, authorized
recovery, idempotency, permanent closure and successive service reuse.
Completed scientific observations receive independent preservation attempts;
failed attempts remain failures, not claims of recovered observations or replay.

Repository-wide inspection covered source, tests, exports, demos/scripts and active
documentation. Historical decisions/workflows and strict saved-record interpretation
remain legitimate history; active operational messaging, health policies, local
buffering and journal/publication identity mechanisms remain required. Superseded
scientific-envelope collection, intake/persistence, transport, recovery and
compatibility paths are removed rather than retained as shims. W051/W052 retain
their historical results, not an active scientific-envelope requirement.

## Combined audit result and P3 correction

The final combined independent audit returned **functional integration PASS** and
**clean replacement FAIL**, hence **overall FAIL** at that checkpoint. No confirmed
production P0-P2 defects were found. The sole P3 was
`HealthFakeAdapter.__init__()` in `tests/test_acquisition_health.py`: an obsolete
`record_kind` argument and unused `self._record_kind` assignment remained from the
removed `collect_records()` contract. The accepted-looking setting had no effect.

Correction `aabc4a3774cb60c2e3f60b0a1c07a6201540d5bc` removes only that argument
and assignment. No callers required changes; active health-policy `record_kind`
fields remain intact. No production code, compatibility alias or replacement
parameter was introduced. The correction is committed; the user reports it pushed.

The user and ICC explicitly determined that another independent re-audit was
unnecessary for this narrowly scoped test-only cleanup: the combined functional
audit remains valid and targeted verification is sufficient to resolve the P3.
Final implementation acceptance closes Decisions 377-378's replacement scope on
that basis. This is not a post-correction independent clean-replacement audit PASS
and does not erase the original failed audit or W053/W054 correction histories.

## Validation and verification evidence

- W053 records Slice 3A independent manual validation, initial P2 audit failure,
  scientific-observation preservation correction, and successful final re-audit.
- W054 records Slice 3B independent validation, initial P2/P3 audit failure,
  corrections and successful final corrective re-audit. Both records are unchanged.
- Combined independent audit: **26 selected tests PASS** across product acquisition,
  scientific/operational failure preservation, producer publication, journal and
  readback, Normal Stop/Kill, release, saved collection, recovery and immutability.
- **Four independent negative/integration probes PASS:** large non-frame metadata
  through local artifacts/collection/closure without scientific intake; invalid
  operational identity with preserved scientific output and partial Kill;
  actual journal fsync failure with retained obligations and no false closeout;
  foreign scientific Session identity rejected while another device's valid
  observation remains independently preserved.
- P3 corrective verification: **9 targeted tests PASS** (six acquisition-health
  tests and three adapter product-contract checks for selected, unselected and
  invalid products); `git diff --check` PASS. Sandbox temporary-file permissions
  required an approved rerun, not a production correction.

These are previously executed checks, not new software tests, independent manual
validation or another audit during documentation closure. Counts describe separate
runs and are not an additive unique-test total.

## Limitations and remaining Q022 work

Verification used temporary local storage, simulated devices and broker/SFTP
infrastructure. It establishes no live hardware, multi-host deployment or
independently demonstrated power-loss guarantee. Injected fsync failure is not
power-loss validation; preservation attempts are not proof of successful writes.
Synchronous persistence can block the event loop. Physical synchronization and
complete independent-service deployment are not established by this acceptance.

Remaining Q022 work includes owner-side NATS operational-evidence acceptance and
readback, acquisition/Experiment and synchronization adaptation, cross-process
Controller closeout/collection/release, maintenance/authorized recovery,
shared-process bootstrap/lifetime enforcement, configuration/explicit-role launch
and installation verification. Use the existing dependency map in
`installation_and_deployment.md` before enabling dependent launch paths; local
owner locks cannot be replaced by assumed distributed locks or cached confirmation.
Future online scientific streaming remains an unresolved, out-of-scope possibility,
not a prerequisite or an implemented feature of Decisions 377-378.

W001-W054 and accepted architectural substance/numbering remain unchanged.
Q019 remains CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN. Only the combined
Decision 377-378 implementation replacement is accepted and closed here.

---

# W056 - Distributed Synchronization and Experiment NATS Integration

**Status:** Complete - Q022 Slice 2; independently validated and audited.

## Implemented scope

AcquisitionNode, Experiment operations and SynchronizationManager communicate
through existing NATS commands and correlated results. SynchronizationManager
owns measured cross-clock exchanges, conservative explicit rate bounds, mapping
validity and configurable periodic quality assessment. AcquisitionNode applies
authorized affine Session-Time mappings locally and prospectively, derives
Experiment Time, and retains mapping activation and quality history. Session
acquisition and each Experiment require acceptable synchronization; degradation
retains explicit timing quality under existing policy and Controller authority.

Launched Experiment context, health activation and finalization use NATS and
preserve applicable evidence publication before successful responses. Scientific
observations and native/local timing remain in AcquisitionNode-local storage;
Ingestor receives operational evidence and manifests, not scientific observations.
Existing Q019 preservation, release and archive protections remain unchanged.

Public entry points include Controller.start_launched_session(),
start_launched_experiment() and stop_launched_experiment(), explicit
SessionConfig.synchronization_configuration, AcquisitionNode's
synchronization_source_id, and NatsSynchronizationManagerCommunication.

## Audit findings and corrections

The initial independent audit of d9624adf07289e2e7135958a80078f7ab4b9c14f
returned FAIL with two P2 findings:

- Buffered observations used processing-time synchronization readiness. Retained
  acquisition-time quality transitions, expiry and mapping boundaries now prevent
  later recovery or degradation from relabeling earlier observations. Local and
  available native timestamps remain intact; persisted records are not rewritten.
- A transient timing-publication exception terminated periodic assessment.
  Recoverable cycle failures now retain stable evidence identities and resume at
  the configured cadence; cancellation and shutdown still terminate monitoring.

Re-audit of b37ff381b9df395e19583758c24e486a73dfab25 confirmed those fixes but
returned FAIL with another P2: a conflicting stop_runtime command cancelled
monitoring before admission. Command identity and Session scope now precede
stop-related effects. Serialized admission preserves duplicate-command identity;
periodic cancellation is awaited outside the runtime lock to avoid deadlock.
Rejected stops leave acquisition and monitoring running. Valid stops publish
required retained evidence before success, and failed publication supports retry.

Final independent read-only audit of **3e573f5: PASS**, with no confirmed P0-P3
findings. All three P2 findings are resolved; no closure is inferred from an
earlier failed audit.

## Validation evidence

- Developer corrective verification: 45 distinct targeted tests passed, including
  seven historical-quality/publication-recovery regressions. Final rejected-stop
  correction verification: 42 targeted tests passed, including local JetStream.
- Independent user-run IPython validation passed for historical degraded quality
  after recovery, preservation of local/native timestamps, transient publication
  recovery and resumed evidence publication, and handler task cleanup.
- Independent user-run IPython validation passed for conflicting stop rejection,
  continued owner/node operation and subsequent periodic assessments, followed by
  successful valid shutdown.
- Final audit verification: 34 distributed synchronization tests passed, five
  directly affected preservation/timing-publication tests passed, and one
  additional read-only live JetStream probe passed. Coverage includes actual local
  JetStream with separate participant processes. The additional probe covered
  rejected/wrong-Session stops, overlapping stops, injected publication failure,
  retained evidence, retry and stable duplicate results.

These are overlapping verification runs, not an additive unique-test total.
Earlier developer test failures caused by coarse local-clock ticks and assumed
distinct activation times were corrected with explicit clock-boundary coordination;
they were test assumptions, distinct from the three confirmed production P2s.
Injected publication exceptions are expected negative-test evidence, not successful
publication. No tests or independent audit were repeated for documentation closure.

## Limitations and status

Local JetStream, separate local processes, simulated devices and broker doubles
do not establish multi-host clock accuracy, physical hardware timing, power-loss
recovery or advanced synchronization guarantees. Q006/Q018 remain OPEN for their
advanced scope. Full deployment bootstrap, remaining external-service integration
and installation verification are not established by this record.

Only Q022 Slice 2 is CLOSED here. Q019 remains CLOSED; Q022, Q024, Phase 16 and
M015 remain OPEN. W001-W055 and accepted decision substance/numbering are unchanged.

---

# W057 - AcquisitionNode-to-Ingestor Durable Operational Evidence over NATS

**Status:** CLOSED - Q022 Slice 3; independently validated and audited.

## Implemented scope and interfaces

AcquisitionNode retains immutable operational evidence and manifest identities
before existing NATS publication. Unconfirmed publication remains retained for
retry, and publication cursors advance only after durable JetStream confirmation.
Scientific observations and per-observation metadata remain AcquisitionNode-local
regardless of size; no scientific-envelope intake or replacement streaming path
is introduced. StorageManager and artifact-handoff responsibilities are unchanged.

Ingestor uses the existing Session-specific durable JetStream consumer, validates
subject/payload Session, source and evidence-type consistency before intake, and
persists and fsyncs new journal entries before server-confirmed ACK. Stable
evidence identities suppress duplicate accepted messages and journal appends;
conflicting content is rejected. Receiver restart reconstructs accepted identity
state through existing journal recovery. Binding identity is revalidated following
asynchronous callbacks before Session ACK. Failed journal persistence prevents
acceptance/ACK and retains the existing recovery obligations.

`NatsControllerCommunication.request_persistence_command(participant, command_type,
session_id, payload, result_window_s, *, command_id)` now supports
`read_runtime_evidence_acceptance` with `{"evidence": message.to_dict()}`.
`NatsIngestorCommunication` delegates this read-only request to the authoritative
Ingestor's existing journal-history guard. Successful readback reports
`durable_acceptance_confirmed=True` for exact current journal-backed evidence,
with evidence identity and per-attempt reply correlation. Missing, stale,
mismatched or timed-out responses are not confirmation. Damaged or missing
journal contents cannot establish acceptance confirmation. Constructors and
existing ownership boundaries are unchanged; no additional persistence owner,
transport or recovery infrastructure is introduced.

Evidence publication, durable intake acceptance, complete acquisition receipt
under W041, and archival preservation are four separate guarantees. Neither
publication nor acceptance authorizes scientific-artifact release. W041 receipt,
Q019 closeout/release protections, Stage A/B preservation, artifact handoff and
permanent archive immutability remain authoritative; W056 timing/Experiment
integration remains closed and unchanged.

## Consolidated verification evidence

- Developer verification: **52 targeted tests PASS** for intake/readback, receipt,
  publication ordering, scientific boundaries and preservation integration.
- Additional developer verification: **9 directly affected checks PASS** for
  journal/ACK, recovery, callback delivery fixtures and framework evidence.
- Developer actual local JetStream verification with a separate Ingestor process
  passed offline publication, lost publication confirmation, retry, receiver
  restart and deduplication checks.
- Independent user-run IPython validation: **PASS**. Publication alone did not
  establish durable intake; journal-backed intake confirmed exact acceptance;
  duplicate delivery did not duplicate accepted evidence or journal entries;
  conflicting evidence identity was rejected; journal corruption invalidated
  acceptance confirmation.
- Final independent read-only audit of **880b108: PASS**, with no confirmed
  P0-P3 findings. Audit execution included **50 targeted tests PASS**, including
  actual local JetStream with a separate Ingestor process and affected lifecycle,
  preservation, scientific timing and producer-publication integration.
- **Three additional independent probes PASS:** callback failure with concurrent
  redelivery; release during a paused callback; and malformed readback requests,
  mismatched replies and missing journal history.

These counts describe overlapping verification runs and must not be summed into
a unique-test total. Local JetStream coverage is part of the cited runs, not an
additional additive test count. No software tests or further independent audit
were performed for this documentation-only closure.

## Limitations and remaining boundaries

NATS subject consistency is not sender authentication; broker access control
remains a deployment responsibility. Optional callbacks are not a durable retry
queue: failure leaves journaled evidence available, but identical redelivery does
not rerun the callback. Exact acceptance readback is point-in-time journal
verification, not complete receipt, archival confirmation or release permission.

Multi-host, hardware and power-loss guarantees remain unverified. Broader
Controller orchestration, cross-process recovery and deployment integration are
outside this slice. No scientific streaming architecture is selected.

W057 and Q022 Slice 3 are CLOSED. Q022 overall remains OPEN; Q019 and the prior
W001-W056 closure records are preserved. Q006, Q018, Q024, Phase 16 and M015 remain
OPEN. Accepted architectural decision substance and numbering are unchanged.

---

# W058 - Controller Remote Saved-Session Collection over NATS

**Status:** CLOSED - bounded Q022 Slice 4; independently validated and audited.

## Implemented scope and interfaces

`Controller.collect_saved_session_artifacts_remote(session_id, *, evidence_id,
communication, storage_participant, result_window_s)` requests collection for one
explicitly selected saved Session without local Ingestor/StorageManager references.
Existing NATS command/results communicate with the separate shared
Ingestor/StorageManager process. StorageManager retains authority over eligibility,
availability, locks, retrieval and durable Stage B evidence through existing
`get_saved_session_collection_status()` and `collect_saved_artifacts()` methods.
Eligibility and preservation are revalidated under owner collection guards.

The command identity is the canonical compact JSON pair `[session_id, evidence_id]`.
Each explicit retry has a fresh request nonce; redelivery retains the old attempt
identity. Fresh-only StorageManager subscriptions prevent automatic execution of
retained commands after restart. Commands published while the owner is offline
remain unconfirmed and require an explicit retry. Collection attempts are
serialized through result publication; unpublished resolutions are retained in
memory until publication succeeds. Exact durable `LAB_COMMAND_RESULTS` readback
supports restart-safe reuse, while existing durable collection evidence permits
retry without refetching scientific files.

Complete scoped result history is validated before admission, including records
after a matching result. Missing, unavailable, detectably incomplete, malformed,
inconsistent or conflicting history fails closed without retrieval, new collection
evidence or history repair. Within the Session/owner/operation scope, the nonce
identifies the attempt; conflicting command or destination identities block
admission. Valid unrelated nonces, other Sessions and other operations remain
isolated. Normal failure replies may still be appended; this is not history repair.
Success requires matching Session/evidence identity, confirmed collection-evidence
preservation and successful scientific collection. Missing replies and unconfirmed
outcomes remain uncertain, not successful.

Publication, operational intake acceptance, W041 complete receipt, Stage A/B
preservation and release authorization remain distinct. Scientific observations
remain AcquisitionNode-local; Stage B evidence is archived directly by
StorageManager. Existing local APIs, handoff, recovery, historical preservation,
permanent closure and release protections are unchanged.

## Validation and correction history

Earlier independent audits returned FAIL with three successive P2 findings:

- P2-A: A historical collection rejection could execute after restart when
  eligibility changed. Fresh-only subscriptions and durable attempt-result
  matching prevent replay; fresh explicit retries remain possible.
- P2-B: Malformed persisted correlation could make rejection appear absent.
  Complete scoped-history validation now fails closed on missing nonce,
  subject/source inconsistency and other invalid correlation.
- P2-C: The original nonce with changed command/destination identity could appear
  unrelated. Nonce-scoped matching and identity consistency checks reject it,
  including conflicting records after a matching resolution.

All three findings were corrected and independently verified.

- Developer verification: **39 targeted tests PASS**, covering admission,
  duplicates, concurrency, retries, cancellation, malformed history, evidence
  readback and preservation integration, including actual local JetStream
  separate-process restart scenarios.
- Independent user-run IPython: **3/3 PASS** for same-nonce destination conflict,
  same-nonce canonical command conflict, and a valid distinct attempt succeeding.
  These identity fault injections used controlled broker-history fixtures.
- Final independent read-only audit of **d788d2e: PASS**, no confirmed P0-P3
  findings. Audit execution included **39 targeted tests PASS** and three
  additional fault-injection checks for destination, command and conflicting
  history after a matching resolution. Rejections caused zero retrievals and
  preserved historical products/results.
- Actual local JetStream verification passed with a separate shared
  Ingestor/StorageManager process: restart-only replay prevention, old rejected
  nonce rejection, fresh explicit retry and durable-outcome reuse without refetch.

These verification runs overlap and are not additive. The additional audit probe
run stalled under sandbox execution and passed outside it; no application defect
was established. No software tests or new audit were performed during this
documentation-only closure.

## Limitations and remaining boundaries

This is single saved-Session collection, not full cross-process Normal Stop/Kill,
Stage A receipt/handoff orchestration, automatic saved-Session enumeration or batch
collection, permanent closure, or resource-release orchestration. Configuration,
explicit-role launching, broader maintenance/recovery and deployment integration
remain outside this slice. Existing owner-local closure functionality is unchanged.

Retained-result-history scanning is linear and depends on required history being
available and intact. Unpublished in-memory results are not a new durable store.
SFTP was simulated; physical SSH/SFTP, hardware, multi-host production and
power-loss guarantees were not validated.

W058 and bounded Q022 Slice 4 are CLOSED. Q022 overall remains OPEN. Q019 and
W001-W057 remain CLOSED with historical records preserved. Q006, Q018, Q024,
Phase 16 and M015 remain OPEN. No accepted architectural decision is changed.

---

# W059 - Controller Remote Saved-Session Evidence Archive Closure over NATS

**Status:** CLOSED - bounded Q022 Slice 5; independently validated and audited.

## Implemented scope and interfaces

`Controller.close_saved_session_archive_remote(session_id, *, communication,
storage_participant, result_window_s)` sends a separate explicit closure request
over NATS without local Ingestor/StorageManager references. This closes one saved
Session's Evidence Archive, not the Session lifecycle or its resource obligations.
StorageManager retains closure eligibility, locks, consistency/preservation guards,
durable publication and readback through its existing
`close_session_evidence_archive(session_id)` method. Missing prerequisites and
unresolved preservation writes prevent closure. Durably preserved failed or unknown
collection outcomes do not automatically prevent otherwise valid closure.

The NATS operation is `close_session_evidence_archive`, with canonical compact JSON
`[session_id, "close_session_evidence_archive"]` command identity and fresh
per-attempt nonce. StorageManager records closure in the existing
`compilation_summary.json`; no new evidence ID, closure file or persistence owner
is introduced. Success requires matching Session identity, owner-confirmed
`closure_outcome` and current matching closed-archive readback. A cached response
or historical success alone is insufficient.

Fresh-only command subscriptions and complete scoped-result-history validation
prevent historical rejections from becoming executable when prerequisites change.
Fresh explicit retries remain possible. Duplicate/overlapping requests, lost
replies, cancellation and owner restart preserve existing guards. Successful
retries reconfirm current preservation without rewriting the closed archive.
Retained successful responses undergo the same complete history scan before
archive reconfirmation; malformed correlation, same-nonce identity conflicts and
persisted resolutions conflicting with the retained outcome fail closed.
Retained rejections remain rejected. Pending responses are in memory, not a new
durable store; missing replies never establish confirmation.

Closure neither terminates a Session nor releases services, bindings or hardware.
It does not collect or mutate scientific artifacts. Scientific observations stay
AcquisitionNode-local; existing Stage A/B, recovery and release ownership remains.

## Validation and correction history

- Original developer verification: **67 targeted tests PASS**, including local
  JetStream with a separate shared Ingestor/StorageManager process, closure,
  collection, preservation and NATS readback coverage.
- Original independent user-run IPython validation: **4/4 PASS** for explicit
  closure without release, historical rejection/fresh retry, lost reply/restart
  reuse without rewrite, and corrupted archive readback rejection.
- Subsequent independent audit of **6742383: FAIL**, one confirmed P2. A successful
  closure response retained after result-publication failure could bypass complete
  scoped-result-history validation on identical redelivery. Injected scoped
  history missing `request_nonce` incorrectly allowed a successful reply.
- Correction: retained-success reuse now enters the existing full history
  validator before current archive reconfirmation and rejects disagreement with a
  persisted resolution. Permanent regressions cover malformed history without
  archive rewrite/history repair and conflicting retained/persisted resolutions.
  Python syntax validation and `git diff --check` passed; sandbox runtime attempts
  stalled without results. **No automated test passes are claimed for the correction.**
- Independent user-run IPython correction validation: **3/3 PASS**. Malformed
  scoped history blocked cached success; a conflicting persisted resolution blocked
  cached success; a valid retry succeeded without rewriting the closed archive.
- Final focused independent read-only audit of **31b2c7e: PASS**, no confirmed
  P0-P3 findings. Source inspection confirmed the corrected admission path and
  preservation of existing closure guards. Six relevant automated tests were
  attempted inside the sandbox, stalled without results and were stopped. No
  automated passes, elevated permissions or out-of-sandbox execution were claimed
  for that re-audit.

The verification runs describe distinct stages and must not be summed into an
additive test total. Sandbox execution limitations are not application failures.
No software tests or new audit were performed for this documentation-only closure.

## Limitations and remaining boundaries

This does not establish full cross-process Normal Stop/Kill, Stage A receipt/handoff
orchestration, resource release, saved-Session enumeration/batch operations, broader
maintenance/recovery or deployment bootstrap. Required retained history must remain
available and intact; scanning is linear. Local separate-process JetStream coverage
used simulated SFTP and does not establish multi-host, hardware/physical SFTP or
power-loss validation. Corrective automated runtime verification remains limited
by the reported sandbox stalls; independent correction validation and audit passed.

W059 and bounded Q022 Slice 5 are CLOSED. Q022 overall remains OPEN. Q019 and
W001-W058 remain CLOSED with historical records unchanged. Q006, Q018, Q024,
Phase 16 and M015 remain OPEN. Accepted architecture and decision numbering are
unchanged.

---

# W060 - Distributed Session Closeout and Independent Release over NATS

**Status:** CLOSED - implemented, independently validated and audited under
Decisions 313 and 382 and their existing preservation/lifecycle dependencies.

## Implemented scope

Controller coordinates Normal Stop and explicitly authorized Kill across
independently deployed AcquisitionNode, SynchronizationManager and the paired
Ingestor/StorageManager process using NATS, without local persistence-owner
references. Scientific observations and per-observation metadata stay node-local.

Normal Stop obtains required producer-publication confirmations and publishes the
Session-scoped completion marker. Ingestor independently verifies the complete
publication interval, contiguous durable receipt and journal consistency before
finalizing acquisition intake. Late and duplicate acquisition deliveries cannot
change finalized evidence, intake audit or the final Session Record. Framework
evidence retains its independent intake boundary.

The paired StorageManager owns durable Stage A publication and verification of
evidence, audit, Session Record and applicable artifact handoff. Finalized intake
and verified Stage A establish acquisition-preservation eligibility, not lifecycle
completion by themselves. Controller alone applies terminal lifecycle transitions
after its existing cleanup/safety obligations. Kill preserves available evidence
with explicit uncertainty and an aborted lifecycle, never claiming complete
Normal Stop receipt or confirmed participant cleanup.

Correlated owner confirmation, durable readback and restart reconciliation support
explicit retries without rewriting finalized products or unnecessarily repeating
confirmed preservation. Publication, durable intake acceptance, complete receipt,
Stage A preservation, lifecycle completion and release remain distinct guarantees.
Missing, cancelled or unconfirmed results do not authorize completion or release.

Each service independently satisfies its own cleanup, preservation and safety
obligations before releasing its binding. Controller requires coverage of its
current owned evidence through asynchronous release and final authoritative
readback. Successfully unsubscribed subscriptions are immediately retired from
pending release work; failed or unconfirmed obligations remain available for
explicit retry. Failed final readback retains the Controller binding and evidence
without repeating completed unsubscribe operations. Stage B collection and
permanent Evidence Archive closure remain separately requested operations.

## Validation and correction history

Independent user-run IPython validation passed the following separately reported
sets; overlapping runs are not an additive total:

- **9/9** finalized-intake and preservation tests.
- **7/7** distributed closeout tests using the simulated broker.
- **4/4** real JetStream infrastructure tests.
- **3/3** real JetStream closeout tests with independent service processes,
  covering Normal Stop/post-finalization immutability, Kill uncertainty/release
  protection, and lost preservation reply with restart and explicit retry.
- **8/8** targeted regressions for the original three P2 corrections.
- **6/6** subscription-release retry and readback regressions.

The initial independent audit failed with three P2 findings: Session finality
incorrectly blocked framework evidence; early closeout association prematurely
blocked health processing before the marker; remote release could discard newer
Controller evidence absent from preservation. Corrections restored independent
framework routing, permitted in-flight health before last-call, and required
current Controller evidence coverage through release and final readback.
Independent re-audit confirmed all three resolved but identified a further P2:
successful unsubscriptions remained pending after failed final readback, so retry
could raise BadSubscriptionError. Immediate confirmed-unsubscribe bookkeeping and
non-idempotent subscription regressions corrected that defect. Focused independent
re-audit passed that correction; no confirmed finding remains outstanding.

A final focused investigation of ambiguous unsubscribe cancellation with installed
nats-py **2.16.0** found no reproducible defect. Four controlled core/JetStream
unsubscribe probes and a Controller cancellation/readback/retry probe passed.
The installed client's flush path catches CancelledError, permitting successful
unsubscribe bookkeeping before another await. These probes used real client
methods with controlled transport/coroutine suspension, not live Task.cancel()
execution. Windows asyncio stalled creating its socket pair before task-level
verification could run. No task-level pass or speculative correction is claimed.
Earlier sandbox-blocked automated attempts likewise are not runtime passes;
independent user-run results above remain the reported validation evidence.

## Limitations and status

Local separate-process JetStream coverage is not multi-host clock-accuracy,
physical hardware/SFTP or power-loss validation. Ambiguous unsubscribe task-level
cancellation remains environment-limited as described above. This record does not
claim application restoration, full deployment bootstrap, broader remote
maintenance/recovery or remote saved-Session enumeration/batch integration.
No new software tests or independent audit were performed during this
documentation-only closure.

W060 is CLOSED. Q022 remains OPEN; Q019 and W001-W059 remain CLOSED with their
historical records preserved. Q006, Q018, Q024, Phase 16 and M015 remain OPEN.
Accepted architectural decisions are unchanged.

---

# W061 - Common Service Launcher and Local Graceful Shutdown

**Status:** CLOSED - implemented, independently validated and independently
re-audited PASS under Decisions 376 and 383-388 and existing maintenance contracts.

## Implemented scope

The installed `lab-sync-acquisition` console entry point exposes five logical role
names. Only `ingestor` and `storage-manager` launch, as aliases for one shared
process containing two distinct authoritative owners. Startup requires explicit
existing constructor settings and an operational-dependency declaration. The CLI
supports only an explicit declaration of no external operational dependents;
`launch_storage_services()` accepts existing configured dependency callbacks.
Controller, AcquisitionNode and SynchronizationManager paths reject startup
without creating hidden owners. Configuration provisioning is not implemented.

`ServiceLauncher` installs interrupt protection before asynchronous operational
admission. Interrupted initialization is cancelled and awaited before existing
local maintenance Stop/Cancel. Ctrl+C uses a temporary requester and OS username;
blocked Stop automatically Cancels the same attempt and retains the process.
Failed or unconfirmed shutdown retains unresolved obligations. Repeated interrupts
never authorize Kill. Pre-admission startup failure is not orderly retirement.

The pair reuses StorageManager preparation, Ingestor Stop and prepared
StorageManager retirement. Services remain alive independently of Session lifetime.
Process exit requires confirmed retirement of every owner, required final result
handling and communication cleanup. Remote notification carries the exact request
and result only after result publication and command acknowledgment; conflicting
rejections cannot substitute cached success. Identical retries remain valid.
Publication/acknowledgment does not establish requester receipt. Existing service
authority, maintenance identities, evidence obligations and outcomes are unchanged.
Remote administrative command issuance is not supplied by this CLI slice.

## Validation and correction history

- Initial independent user-run IPython validation: **18/18 PASS**.
- Initial independent audit: **FAIL**, two confirmed P2 findings. A conflicting
  rejection could substitute an unpublished successful retirement cached by command
  ID. SIGINT/task cancellation during partial startup could bypass maintenance
  after operational admission.
- Corrections pass the exact published-and-acknowledged request/result pair to the
  launcher and establish interrupt protection before startup, cancelling and
  awaiting initialization before maintenance. Permanent regressions cover both
  defects, identity conflicts, retained obligations and early startup failure.
- Independent user-run IPython validation after correction: **22/22 PASS**, zero
  failures, errors or skips. This overlaps the initial set; counts are not additive.
- Focused independent read-only re-audit: **PASS**, no confirmed P0-P3 findings.
  Five synchronous CLI tests and three controlled coroutine probes passed,
  covering conflicting rejection, publication failure/retry and ACK failure/retry,
  with successful temporary-resource cleanup. These are not live task/signal tests.

Codex sandbox verification also included passing synchronous tests and controlled
coroutine probes. Normal asynchronous execution stalled in Windows asyncio
socket-pair initialization before test setup. Those blocked runs are not passes
or application failures; independent IPython results remain separate evidence.
No new implementation tests or audit were performed for documentation closure.

## Limitations and status

No live JetStream, physical hardware, full five-role deployment, actual OS
signal-delivery or power-loss validation is established by these results.
Unsupported role composition, remote administrative issuance, file-based
configuration/provisioning and broader deployment integration remain outstanding.
No supervision, automatic restart, discovery or new lifecycle states are supplied.

W061 is CLOSED. Q022 remains OPEN. Q019 and W001-W060 remain CLOSED with historical
records unchanged; Q006, Q018, Q024, Phase 16 and M015 remain OPEN.

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
