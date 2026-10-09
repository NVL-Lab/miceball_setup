# Glossary

This document defines the architectural terminology used throughout the repository.

These definitions take precedence over informal usage.

---

# Acquisition Node

A hardware-facing runtime responsible for acquiring data from devices, attaching framework scientific Runtime Timing, generating acquisition records, forwarding records to the Ingestor, evaluating Experiment-scoped acquisition health, executing assigned AcquisitionHealthPolicy interpretation, and recording Health Interpretation Evidence.

AcquisitionNode receives and applies the active immutable SynchronizationMapping, derives Experiment Time when an Experiment is active, reports local AcquisitionNode time samples to SynchronizationManager, and records local timing-quality observations. It does not create SynchronizationObservation evidence, create, validate, modify, activate, or retire mappings, estimate drift, decide when to remap, or interpret device-native clocks online.

The Jetson is the Phase 1 Acquisition Node.

The Acquisition Node is not the GUI, Controller, Ingestor, or Storage Manager.

Under accepted Slice 28 architecture, AcquisitionNode also owns its pre-Session
declared device inventory and atomic Session-keyed exclusive reservation. Its
readiness report separates framework/service readiness, individual device
readiness, and reservation availability. It owns local Session binding and
initialization, physically creates Session-authorized LocalStorageManagers using
deployment-local configuration, and confirms Session-keyed initialization cleanup
before reservation release. These additions are implemented with automated
broker-double coverage; M015 awaits independent manual validation and audit.

---

# Acquisition Runtime

The Session-level runtime owned by an Acquisition Node.

When the Acquisition Runtime is active, the node is active for that Session, Session Time is running, and acquisition evidence may be recorded.

Acquisition Runtime active does not imply that an Experiment is running or that every declared device is streaming or producing records.

---

# Controller

The component responsible for Session launch, runtime assembly, orchestration,
stopping, and finalization, while Session retains lifecycle ownership.

Controller may exist before Session, accepts prospective selections, resolves
readiness and node reservations, then constructs final SessionConfig and creates
Session. It owns rollback until required initialization/preparation establishes
launch success. Slice 28 implements this expanded boundary through brokered
commands; existing sequential local workflows with caller-created collaborators
remain supported.
Runtime participants may be remote; shared Python objects are not an architectural
requirement. Multiple Controllers and AcquisitionNodes remain possible.

Controller requests distributed participant preparation and requires confirmed
success from all mandatory participants. It coordinates rollback, but unconfirmed
node cleanup prevents reservation release. Controller neither starts/stops NATS
nor launches participant processes or selects node-local filesystem roots.

Examples:

* create session
* initialize session
* start session
* stop session
* run bounded acquisition iterations
* finalize session evidence and outcome

The Controller coordinates existing components but does not own Session lifecycle state, Acquisition Runtime execution, Session Time, device lifecycle, ingest audit, or persistent writing.

Decision 275 assigns Controller overall Session processing finalization through
required post-session operations, distinct from scientific acquisition end.
Controller orchestrates collection but does not translate StorageManager's
operational results into StorageManager evidence. Slice 25 implements an explicit
awaited collection-before-finalization path; the Session-wide evidence-drain
guarantee remains Q019.

The GUI and Controller are conceptually separate, even if they run on the same machine.

The Controller owns canonical Experiment lifecycle orchestration. AcquisitionNodes record local execution evidence associated with an active Experiment. Controller records action decisions for Health Interpretation Evidence explicitly presented to it; it does not perform acquisition-health policy interpretation. Controller executes the accepted local no-mutation decisions and the existing Experiment- and Session-failure paths. Notification, retry, recovery, distributed delivery, and other future consequences remain deferred.

---

# Controller Action Decision

An immutable plain-data record of the Controller decision derived from one explicitly presented Health Interpretation Evidence record.

It preserves Session, Experiment, live-source, policy, interpretation, and originating-observation provenance. Phase 8a records and returns one decision per presentation without mutating Session, Experiment, Acquisition Runtime, device, or synchronization state.

A Controller Action Decision is evidence of a decision. It is not itself a lifecycle transition, retry, recovery action, notification, or distributed-delivery mechanism.

The normalized local vocabulary is `record_only`, `record_warning`, `record_recoverable_failure`, `operator_required`, `experiment_fail`, and `session_fail`. The first four execute successfully without lifecycle mutation; the failure decisions use the accepted Experiment- and Session-lifecycle owners.

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

It may expose Device-Native Timing evidence but does not know Session Time, apply SynchronizationMappings, derive Experiment Time, or detect Phase 11 timing-quality failures.

The Device Adapter owns its lifecycle state and device-specific initialization
and cleanup; DeviceManager coordinates lifecycle management. Under Decision 302,
successful shutdown and required cleanup return the retained adapter to DECLARED
for sequential Sessions. That transition has automated regression coverage;
independent validation and audit remain pending under M015.

---

# Device Manager

The component responsible for device lifecycle management.

Responsibilities include:

* initialization
* configuration
* start
* stop
* shutdown

The Device Manager does not own device-specific communication.

Current DeviceManager receives already-created adapters and does not discover
devices or create them from declarations. AcquisitionNode owns declared
inventory; installation, registration, and discovery mechanisms remain deferred.

Decision 302 requires generic lifecycle coordination across sequential Sessions,
not device-specific reset workarounds or adapter recreation. AcquisitionNode
retains the adapter instances and deployment configuration; Controller orchestrates
launch without directly initializing or resetting hardware.

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

Its identity represents one execution. Once stopped, aborted, or failed, it
cannot restart under the same `experiment_id`, including when it has no
scientific outputs or recorded data. Repeating its configuration creates a new
Experiment identity under Controller orchestration (Decision 238).

Examples:

* a behavioral task segment
* a stimulus protocol segment
* a baseline recording or scientific decoder-calibration segment

A Session may contain no active Experiment or multiple sequential Experiment segments, with at most one active Experiment at a time. Controller owns canonical Experiment start/stop orchestration, while Session owns descriptors and lifecycle evidence.

Each Experiment segment has one canonical, Controller-owned lifecycle in the Session timeline and Session Record. An Experiment declares expected participation by selected Session-owned resources without owning those resources.

Canonical terminal evidence distinguishes `experiment_stop` for normal completion from `experiment_fail` for unexpected Experiment-level framework or runtime failure. `experiment_abort` is reserved for future intentional early termination and is not implemented.

Experiment failure ends the active Experiment and clears both its Active Experiment Runtime Context and runtime health mapping. It does not automatically fail the Session or stop Acquisition Runtime.

Session-ready resources are not automatically Experiment participants, and Experiment participants are not necessarily continuously producing records.

---

# Experiment Time

Analysis-ready scientific time relative to the canonical start of one Experiment inside a Session.

Experiment Time is derived from Session Time as `session_time_s - experiment_start_session_time_s`; it is not an independent clock. Controller owns canonical Experiment lifecycle, Session records the Experiment start Session Time, and AcquisitionNode may derive Experiment Time for records acquired while that Experiment is active.

---

# Active Experiment Runtime Context

The explicit runtime-only handoff from Controller to AcquisitionNode for one active Experiment.

It contains `experiment_id` and `experiment_start_session_time_s`. AcquisitionNode may use this context to derive Experiment Time for its local runtime evidence, but it does not own or mutate canonical Experiment lifecycle evidence.

Active Experiment Runtime Context is separate from ExperimentRuntimeHealthMapping. The context carries lifecycle timing needed for runtime timestamping; the health mapping carries only Experiment-scoped health scope and policy assignment. Controller clears both when the Experiment stops or fails.

---

# Experiment Start Session Time

The canonical Session Time at which Controller starts an Experiment and Session records its `experiment_start` lifecycle evidence.

It is handed explicitly to AcquisitionNode as `experiment_start_session_time_s` within Active Experiment Runtime Context. It is the origin used to derive Experiment Time and is not an independent clock.

---

# Experiment Descriptor

The Session-owned plain-data description of one Experiment's scientific identity and declared expected participation.

An Experiment Descriptor is persistent Session evidence. It does not own lifecycle state or live runtime resources, and it does not bind declarations to live objects.

Descriptor configuration may be reused for a new execution, but the new
Experiment has its own `experiment_id` and evidence; reuse does not mean
restarting or replacing the original Experiment's identity.

---

# Experiment Identity

The `experiment_id` identifying one execution within a Session. A terminal
Experiment identity cannot be reused to restart acquisition. A repeated
execution requires a new identity and its own canonical lifecycle, scientific
streams, ArtifactManifests, and acquisition/timing evidence.

---

# Experiment Execution

One bounded execution associated with one Experiment identity. Stopped,
aborted, and failed are terminal lifecycle outcomes. Restarting a device while
an Experiment is still active does not constitute restarting a terminal
Experiment.

---

# Reusable Experiment Configuration

The descriptor configuration, scientific-product selections, participating
devices, and acquisition parameters that may be reused for another Experiment
execution. Configuration reuse does not reuse the previous terminal identity,
reopen finalized streams, or merge the two executions' evidence. This term does
not introduce a new configuration object or public API.

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

Experiment Participant Runtime Mapping, represented by `ExperimentRuntimeHealthMapping`, does not contain Experiment lifecycle timing. Active Experiment Runtime Context is the separate handoff for `experiment_id` and `experiment_start_session_time_s`.

---

# Acquisition-Health Policy

A named configurable definition of acquisition-health evaluation behavior and observation interpretation.

Policy definitions belong to `SessionConfig` and persist as accepted Session configuration. The active Experiment Runtime Health Mapping assigns one configured policy to each mapped live acquisition source for that Experiment. Definition is Session-scoped; assignment is Experiment-scoped runtime intent.

The plain-data policy definition contains a `policy_id`, an `evaluation_rules` mapping of independent named rule substructures, and an interpretation mapping from observation type to consequence label. Observation type and consequence label are distinct: the observation describes what was detected, while the assigned policy supplies configured operational meaning.

Each evaluation rule owns only the parameters its algorithm needs. For example, `first_evidence` may own `record_kind` and `grace_window_s`, while `gap` may own `record_kind` and `max_gap_s`. New rule names may be added without changing the policy's top-level schema.

Supported configured consequence labels are `informational`, `warning`, `recoverable_failure`, `experiment_failure`, and `session_failure`. AcquisitionNode immediately interprets each emitted Health Observation through this mapping and records at most one result as Health Interpretation Evidence. When no interpretation is configured for an observation, the runtime outcome is `uninterpreted`. Framework actions associated with interpretations remain separate and Controller-owned.

Interpretation keys must be supported by the evaluator that validates the policy. Policies do not define evaluator observation capabilities.

Evaluator-specific parameters needed by a supported rule belong in that rule's substructure under `evaluation_rules`. They are evaluation configuration, not source identity or policy assignment.

`DeviceDeclaration` does not contain or assign acquisition-health policy; a device is not globally critical, soft, optional, warning-only, or fatal across every Experiment.

---

# Experiment-Scoped Acquisition Health

Evaluation of whether contributions expected by the active Experiment appeared.

Its scope is determined exclusively by the active Experiment Runtime Health Mapping. With no active mapping, no Experiment-scoped acquisition-health evaluation occurs. With an active mapping, only mapped live acquisition source IDs are evaluated; Session-ready but unmapped resources are excluded.

Experiment-scoped acquisition health is distinct from Session Readiness, which asks whether a resource can safely participate in the Session. The existing first-record grace-window algorithm is validated for mapped sources; additional algorithms, participant enforcement, and Controller action semantics remain deferred.

---

# Experiment-Scoped Health Observation

A condition detected by AcquisitionNode while evaluating acquisition health for live sources in the active Experiment Runtime Health Mapping.

Examples include missing expected evidence, resumed evidence, acquisition rate below expectation, or acquisition resuming after interruption. A Health Observation records what AcquisitionNode observed as Experiment-scoped health evidence; it does not assign operational significance.

A Health Observation is evidence of what was detected and is not inherently a warning, recoverable failure, Experiment failure, Session failure, Controller command, operator notification, recovery action, or retry request. AcquisitionNode interprets it through the assigned AcquisitionHealthPolicy and records that interpretation separately as Health Interpretation Evidence.

Each emitted Experiment-scoped Health Observation has a stable `observation_id` used only as runtime evidence provenance. It is not a database key or a Session, Experiment, persistence, or Controller identifier.

---

# Health Interpretation Evidence

Immutable plain-data Experiment-scoped runtime evidence recording how AcquisitionNode immediately interpreted a Health Observation according to the AcquisitionHealthPolicy assigned through the active Experiment Runtime Health Mapping.

Each emitted Health Observation produces at most one corresponding Health Interpretation Evidence record. Its `originating_observation_id` explicitly references the originating observation's `observation_id`, preserving an auditable one-to-one runtime chain. If the assigned policy has no configured interpretation for the observation, the recorded outcome is `uninterpreted`.

Its fields preserve the originating observation reference, Experiment, live source, Expected Participant, observation type, assigned policy, interpretation label, required status, Session Time, and plain-data details. AcquisitionNode now produces it immediately after its originating observation through the existing evidence-envelope path. Persistence in the final Session Record remains separate work.

Health Interpretation Evidence is original runtime evidence. It is not regenerated or silently reinterpreted during reconstruction. A later reinterpretation under a different policy must be separate derived analysis or reconstruction evidence.

Health Interpretation Evidence records policy interpretation only. It does not itself stop an Experiment, fail a Session, notify an operator, initiate retry or recovery, or perform orchestration. Future Controller behavior owns framework actions based on this evidence.

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

The canonical runtime evidence-intake component responsible for receiving and auditing durable evidence messages and preserving accepted evidence for storage.

The Ingestor owns:

* runtime evidence intake
* intake validation
* ingest auditing
* temporary runtime retention
* compilation of persistent runtime evidence

Decisions 276-280 additionally accept Ingestor-owned local recovery journaling,
evidence_id acceptance deduplication, and restoration of the normal evidence view
for a known Session. Slice 27 explicitly configured recovery journaling is complete
after independent manual software validation and corrected targeted re-audit PASS
(M014, W034). The normal working view remains
in memory. This temporary crash durability is not a producer persistence decision
or a transfer of permanent Evidence Archive ownership from StorageManager.

The Ingestor does not own scientific time, evidence interpretation, lifecycle, scientific meaning, or persistence decisions. It must not infer persistence from evidence type, payload, source component, or domain meaning; it uses the explicit persistence intent carried by `RuntimeEvidenceMessage`.

The Ingestor is not the universal online pipe for every scientific sample, frame, continuous data row, or large artifact byte. Producing components may store authoritative scientific data locally and represent artifact lifecycle through durable manifests.

---

# RuntimeEvidenceMessage

The runtime evidence boundary between evidence-producing components and runtime evidence consumers.

It carries plain runtime evidence across the communication boundary without transferring domain ownership or meaning. Its accepted Phase 13 architecture includes an `is_persistent` flag that records producer-supplied persistence intent.

Evidence-producing components decide whether their own evidence is persistent. Ingestor must not infer persistence from the message's evidence type, payload, source component, or domain meaning.

RuntimeEvidenceMessage does not own lifecycle, scientific interpretation, persistence policy, Session Time, storage semantics, or evidence archive layout.

---

# Persistent Runtime Evidence

Runtime evidence explicitly marked by its producing component as intended for persistent preservation.

Architecture-defined mandatory persistent evidence categories remain mandatory, but the responsible producer sets `is_persistent = True`; Ingestor compiles persistent runtime evidence and StorageManager writes the resulting persistent records.

---

# Control Plane

The NATS-based runtime communication plane for commands, command results, lifecycle, status, health, evidence, metadata, manifests, and transient telemetry. It does not transport large scientific artifacts or define Session Time.

---

# Ingestor Recovery Journal

Accepted Slice 27 append-only local JSONL accepted-message history owned by
Ingestor (Decisions 276-280), implemented with explicit Session/path configuration
and software-validated with corrected independent re-audit PASS (M014, W034).
Complete accepted
RuntimeEvidenceMessages cross a flush/fsync-equivalent durable boundary before
normal working-state update and broker ACK. Both persistence-flag values are
journaled; nonpersistent evidence does not become permanently persistent.
Live acceptance requires reported durability success. On restart, complete valid
journal entries are authoritative for reconstruction even if a prior durability
operation reported failure; that error does not prove that complete bytes were lost.
This is temporary crash-recovery state, not a snapshot, database, ingest audit,
Session Record, permanent Evidence Archive, or replacement for JetStream.
Journal cleanup/retention and application restart/discovery remain Q024.

---

# Durable Ingestor Acceptance

Live-process acceptance follows successful reported journal durability before
working-state update and ACK. A reported append/durability failure prevents that
process's accepted-state update and ACK, and closes further intake until restart
because the durable outcome is uncertain. Restart reconstruction accepts complete
valid journal history, including records surviving a previously reported error;
no commit-marker or transactional protocol is required. JetStream handles normal
redelivery without Ingestor retry machinery. evidence_id identifies acceptance:
identical content is acknowledged without a second journal append or processing;
conflicting content is an error, never an overwrite (Decisions 276-277).

---

# Known-Session Ingestor Reconstruction

Startup for a known Session replays its existing recovery journal into the normal
accepted-evidence view and deduplication knowledge, then resumes intake. Complete
valid journal entries are authoritative even if their previous write
operation reported a durability error; this differs from live-process acceptance.
Identical redelivery of a reconstructed entry is ACKed without reappend or processing.
The existing artifact handoff compiler is reused without a reconstructed marker,
parallel model, special command, or new format. A clearly interrupted final JSONL
entry may be omitted for broker redelivery; completed corruption fails reconstruction,
not silent partial recovery. This is completed, independently software-validated
and corrected re-audited Slice 27 behavior (M014, W034),
not application-wide Session discovery or scientific timing reconstruction.

---

# Ingestor Recovery Evidence

Ingestor-produced RuntimeEvidenceMessage with evidence_type
`ingestor_recovery_evidence` and is_persistent=True after successful known-Session
reconstruction. Conceptual content is Session/Ingestor identity,
recovered_entry_count, and recovery_time using existing envelope conventions,
without duplicate recovered IDs/contents. It enters the normal journal/acceptance
path and later permanent compilation, not a separate evidence store (Decision 279).
Slice 27 is complete (M014, W034) after automated tests, independent manual software
validation, and corrected targeted independent re-audit PASS. W034 preserves
the clarification and audit/correction history.

---

# Artifact Plane

The separate, future pull-based path for transferring large scientific artifacts that remain local during acquisition. Artifact bytes do not travel through NATS.

---

# Artifact Manifest

The authoritative local discovery record for one locally managed scientific artifact. Phase 12 assigns exclusive ownership and persistence of the local `ArtifactManifest` to the co-located LocalStorageManager; AcquisitionNode supplies scientific metadata and LocalStorageManager supplies storage metadata.

An ArtifactManifest is created with its scientific stream and remains valid when that stream is finalized with zero rows. Decisions 248-249 establish one manifest = one scientific artifact = one file. Framework-generated artifacts use `local_storage_path` as their retrieval source; external artifacts use `external_artifact_path`. Each associated framework timing/index file is a separate artifact with its own manifest. `local_managed_paths` describes auxiliary managed paths, not a retrieval list. Its durable `artifact_manifest_id` is distinct from the runtime `storage_id`. Slice 23 source selection and retrieval have software coverage recorded in W032; M011 remains open pending real Jetson/SSH-SFTP deployment validation, and no new external acquisition workflow is implemented.

The implemented Phase 10 `RuntimeEvidenceMessage` form with evidence type `artifact_manifest` remains a transport representation, not a transfer of ArtifactManifest ownership.

An Artifact Manifest is not an acquisition row, frame, sample, artifact byte payload, transfer command, storage layout, checksum record, or transfer implementation.

---

# LocalStorageManager

The co-located runtime collaborator that owns local persistence for exactly one AcquisitionNode. It incrementally writes local scientific streams, owns their creation and finalization, owns their ArtifactManifests, records local storage evidence, and participates in readiness without owning acquisition, Session Time, Experiment lifecycle, transfer, reconstruction, or NWB export.

Accepted Decision 298 distinguishes Session initialization authorization from
physical creation by AcquisitionNode in its own process using deployment-local
roots/configuration. Controller does not instantiate a remote manager or choose
its paths. Slice 28 implements this authorization/creation boundary while retaining
historical local-workflow root overrides.

The implemented core supports JSONL and camera HDF5. Decision 191 defines common
ownership, interfaces, and lifecycle rather than a mandatory file format.
Decisions 232-237 are implemented for explicit local roots, scientific-product
selection, preparation, and persistence, with automated synthetic-frame tests.
Corrective changes await manual validation and a targeted follow-up audit;
real-camera HDF5 validation and Slice 20 closure are not claimed.

---

# Local Scientific Stream

One incrementally written, timestamped local stream for one scientific data product. A stream has its own schema, lifecycle, runtime `storage_id`, and ArtifactManifest relationship; one device may produce multiple streams.

Common stream responsibilities do not require a common file format. JSONL
remains supported and raw camera-frame artifacts use the accepted HDF5 format.

---

# Camera HDF5 Artifact

One local artifact per camera-frame scientific product per Experiment,
owned by LocalStorageManager. It preserves actual image arrays without lossy
compression, frame order, shape, channel organization, supported native dtype,
and aligned per-frame indices and scientific timing. Available static device
metadata are preserved without fabricating unavailable values. This artifact
is implemented and covered by synthetic-array tests; real-camera hardware
validation remains pending.

---

# Local Storage Root

The explicitly resolved base location for AcquisitionNode-local scientific
persistence. Historical local Session overrides do not mutate the persistent
node default or affect subsequent Sessions (Decision 234). Accepted distributed
initialization uses the node's deployment-defined root/configuration instead;
Controller cannot choose or override remote roots via SessionConfig.local_storage_roots
(Decision 298). LocalStorageManager owns actual paths, organized deterministically
by Session and Experiment; the external configuration model remains future work.

---

# Scientific Data Product

One scientifically meaningful output available from a resource, such as measured
data, events, indices, or references into an external artifact. Device
declarations describe available products; Experiment configuration explicitly
selects declared products by existing source device, AcquisitionNode, and
product identities. AcquisitionNode translates selections into local stream
requests without directly writing artifacts.

---

# Scientific-Product Declaration

A device declaration's description of an available scientific product. It
includes, as applicable, the existing product identity, type, scientific schema,
known size/rate, and storage requirements including persistence format. It does
not create storage, invent unavailable characteristics, or add redundant
identities. Experiment selection cannot override its declared storage format.

---

# Experiment Scientific-Output Selection

Explicit Experiment configuration references to declared products using their
existing source device, AcquisitionNode, and scientific product identities.
Selection identifies required outputs without defining new device capabilities
or inferring requirements from connected or healthy devices. Each selected
product maps to one local scientific stream for the Experiment.

---

# Experiment Scientific Stream Preparation

Controller-coordinated Experiment initialization using existing preparation and
readiness results before scientific acquisition. AcquisitionNode translates
selected products into creation requests; LocalStorageManager creates each
stream, artifact, and authoritative ArtifactManifest, including zero-record
streams. This implemented Slice 20.3 responsibility uses the existing lifecycle
and readiness authority and is covered by automated preparation tests.

Decision 239 requires Controller to establish successful required preparation
before canonical `experiment_start`. Optional preparation failure does not block
confirmed required success; selected scientific outputs remain required under
Decisions 209 and 235. Slice 21 now accepts existing service-readiness and group
command outcomes at the Controller start gate; no optional scientific-product
field is introduced. Slice 21 is complete following the manual validations,
focused tests, and independent audit reassessment recorded in W030.

---

# Experiment Start Rejection

A Controller-owned pre-start outcome when required Experiment preparation has
not succeeded. It is reported through the existing Controller command result
and persistent `RuntimeEvidenceMessage` vocabulary
`evidence_type="experiment_start_rejected"`, with `is_persistent=True`.
It creates neither `experiment_start` nor `experiment_fail`, a new lifecycle
state, nor a Session rejection history. Missing required command results remain
unresolved rather than proving success or confirmed remote failure. Ingestor
compiles accepted persistent rejection evidence for the existing Evidence Archive.
Decision 239 establishes this boundary; Controller now produces the message
through existing Ingestor intake and includes its plain form in failed command
result details for explicit broker publication. Slice 21 is complete as recorded
in W030 and M009. Session Record failure diagnostics remain legitimate;
the Evidence Archive preserves the complete persistent runtime evidence.

---

# storage_id

The runtime write handle for one local scientific stream throughout its local artifact lifecycle. It is not the durable discovery identity of the artifact.

---

# artifact_manifest_id

The durable discovery identity of an ArtifactManifest used by later collection, reconstruction, and export. It is distinct from the stream's runtime `storage_id`.

Decisions 240-243 use this identity to associate creation and finalization
manifest evidence for the same artifact within a Session.

---

# Artifact Collection Handoff

Accepted Phase 14, Slice 22 information compiled by Ingestor for a requested
Session from retained artifact_manifest runtime evidence. Each artifact has one
entry containing its complete authoritative ArtifactManifest: finalized when
available, otherwise initial with missing finalization explicitly reported.
Session, Experiment, AcquisitionNode, and artifact identities are preserved.

AcquisitionNode publishes the LocalStorageManager-owned complete manifest at
creation and finalization without taking manifest ownership. Controller initiates
post-session collection and coordinates handoff delivery. StorageManager owns
later retrieval through the separate pull-based Artifact Plane.

AcquisitionNode now produces manifest lifecycle messages through existing local
intake, and the NATS adapter publishes newly produced messages after commands
or explicit publication. Ingestor handoff compilation and Controller finalization
readback are implemented, manually validated, and independently audited with
verdict PASS (W031). M010 is complete. The handoff contains information, not artifact bytes or compiled
diagnostics. The normal Ingestor working view is in memory. Restart reconstruction was
outside Slice 22; Decisions 276-280 accept known-Session journal recovery for
Slice 27, complete after independent software validation and corrected re-audit
PASS (M014, W034), without changing the handoff.
Q019 remains open.

---

# Global Artifact Collection Evidence

StorageManager-owned persistent operational evidence for one completed
post-session collection pass, using the runtime evidence type
`global_artifact_collection_evidence` and `is_persistent=True` (Decisions 271-274).
The RuntimeEvidenceMessage envelope carries `session_id` and `source_id` as the
logical StorageManager identity; its payload carries `started_at`, `finished_at`
and attempted-artifact results: manifest/Experiment/AcquisitionNode
identity, artifact type, collection and verification status, global locator,
copied byte size, and failure information. Manifest identities/type come from
the authoritative handoff, not inference.

There is one compiled record per pass, not one RuntimeEvidenceMessage per artifact,
a duplicate ArtifactManifest, or an aggregate evidence success/failure flag.
Collection uses `success` / `failure`; verification uses the four existing Slice 24
outcomes and is absent/null if no verification occurs. No `not_attempted` or
`unattempted` status is introduced. The evidence does not describe scientific
validity, acquisition outcome, Experiment lifecycle, or local finalization success.

StorageManager publishes through the existing durable runtime-evidence boundary.
Generic Ingestor compilation and the existing same-Session Evidence Archive
preserve it without a new file/archive or evidence owner. Slice 25 implements
packaging and awaited publication through an injected existing callable. Slice 25
is complete (M013, W033) after manual software validation and corrected independent
re-audit PASS; the Session-wide consumption guarantee remains open in Q019.

---

# Operational Collection Time

Ordinary wall-clock audit timestamps `started_at` / `finished_at` spanning the
complete global collection pass, including verification. They are not scientific
Session Time, Experiment Time, AcquisitionNode local time, or synchronization
evidence. Scientific Session Time freezes at acquisition end; no synchronized
operational clock or Ingestor clock dependency is introduced (Decision 273).

---

# Light Verification

StorageManager-owned, bounded structural inspection of a globally copied artifact
after successful retrieval, destination closure, and publication. It does not
interpret, normalize, transform, or scientifically validate data. Retrieval
success and verification outcome are separate dimensions. Decisions 261-270 are
implemented and software-validated Slice 24 architecture (M012 complete, W032),
following corrected independent re-audit PASS.

No separate Verifier component is introduced. Verification uses read-only
structure and small attributes, not full scientific-data scans or mandatory
checksums. It preserves copies even when invalid or verification is inconclusive.

---

# Verification Outcome

The structural-inspection outcome associated with a completed global copy:

- `verified`: every applicable required light check passed.
- `copied_unverified`: copy succeeded but no applicable format/layout contract exists.
- `structurally_invalid`: verification established a violation of the applicable contract.
- `verification_failed`: an operational failure prevented a conclusion.

An expected supported-layout artifact that cannot open as valid HDF5 is
structurally_invalid; operational read/access failure is verification_failed.
The implemented classifier follows underlying file-access failure provenance,
not a whitelist of HDF5 diagnostic text.
Retrieval failure is separate, and verification is not attempted without a
completed copy. None of these outcomes chooses a Session lifecycle consequence.

---

# Current HDF5 Layout Verification

The first accepted light-verification contract, specific to the existing
LocalStorageManager layout rather than its producing device. Required root
datasets are `frames`, `session_time_s`, `experiment_time_s`,
`acquisition_node_local_time_s`, `frame_index`, `timestamp_status`, and
`record_metadata_json`. Checks cover accessible nonzero-size HDF5, matching
embedded artifact_manifest_id, dataset existence, aligned lengths, and agreement
with persisted_frame_count and any available authoritative finalized manifest
count. Missing finalization evidence does not supply an invented expected count.

Zero-record artifacts remain valid. This is not a universal HDF5 schema, a
camera-specific verification owner, JSONL verification, or the existing camera
smoke script's deeper scientific readback. Other layouts/formats and broader
ScientificProduct structural contracts remain future architecture. ArtifactManifest
and ScientificProductDeclaration gain no Slice 24 schema fields.

---

# Verified Collection Outcome

StorageManager aggregate reporting that distinguishes complete verified success
from retrieval failures and copied_unverified, structurally_invalid, or
verification_failed outcomes. Details remain per artifact; Controller need not
interpret dataset names, individual checks, or transport errors. Slice 24 accepts
this reporting responsibility without choosing Session completion/lifecycle policy.
The implemented aggregate requires retrieval success and verified status for
every requested artifact; empty collections remain successful.

---

# LocalStorageCompletionSummary

LocalStorageManager-owned plain completion information produced after local finalization. It describes only local completion and does not imply global Session Record completion, transfer, reconstruction, or NWB export.

---

# Local Storage Evidence

LocalStorageManager-owned evidence about stream and manifest creation/finalization, write or finalization failures, and cleanup completion/failure. It is preserved locally and may also be published as durable runtime evidence when communication is available; LocalStorageManager does not interpret its consequences.

---

# Local Completion

Completion of one LocalStorageManager's local artifact lifecycle. Local completion is independent from global Session Record completion and does not imply artifact transfer, reconstruction, or export.

---

# Stream Creation

Creation of one local scientific stream and its ArtifactManifest during Experiment initialization, before acquisition begins. Stable metadata are recorded once and later appends use the stream's `storage_id`.

---

# Stream Finalization

Closure and completion of one local scientific stream lifecycle. Finalization is distinct from flush, which only persists current batches, and makes the local scientific record immutable.

---

# Empty Scientific Stream

A stream that was created and validly finalized with zero rows. It is valid scientific evidence and is distinct from a stream that was never created.

---

# Local Storage Readiness

The Session-initialization readiness condition confirming that co-located local persistence can safely preserve scientific data and evidence before Experiment stream creation. It does not give LocalStorageManager ownership of Session lifecycle.

---

# Runtime Message

A minimal plain-data command, command-result, evidence, or telemetry message routed through the communication boundary. Implemented runtime messages use Session-scoped NATS subjects; accepted Slice 28 additionally permits participant-scoped pre-Session commands without a Session identity. Session operations and evidence remain Session-scoped. Routing does not transfer domain ownership.

---

# Unresolved Command Outcome

Issuer-owned evidence that an expected runtime participant did not return a command result within the issuer-defined result window.

An unresolved outcome is not automatically a target failure, command failure, Experiment failure, or Session failure. NATS and target components do not aggregate or interpret missing group-command results.

---

# JetStream

The durable NATS messaging facility used for commands, command results, and evidence. JetStream acceptance confirms durable transport acceptance only, not command execution, evidence consumption, ingest audit, or persistent Session Record storage.

---

# Local Device Time

A timestamp, counter, frame number, or clock value generated by an individual device.

Local Device Time may be useful for debugging, reconstruction, and drift analysis.

Local Device Time is not Session Time.

Phase 11 uses the more precise term Device-Native Timing for this device-produced evidence. It is also distinct from AcquisitionNode Local Time.

---

# AcquisitionNode Local Time

The monotonic runtime clock local to one AcquisitionNode.

It is not reset to Session Time and does not own scientific timing. An explicit SynchronizationManager-owned SynchronizationMapping relates it to Session Time. Its record field may be represented as `acquisition_node_local_time_s`.

AcquisitionNode Local Time is distinct from Device-Native Timing exposed by an individual device.

---

# Device-Native Timing

Timing or sequence evidence produced by a device, such as a frame index, sample index, device timestamp, hardware counter, or dropped-frame/sample flag.

The framework preserves Device-Native Timing unchanged. Phase 11 does not synchronize, drift-correct, or interpret device-native clocks online. Device-Native Timing is distinct from framework-owned scientific Session and Experiment Time.

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

Reconstruction may audit timing, estimate drift, flag degraded intervals, and produce Reconstructed Timing. It never silently mutates or replaces raw Runtime Timing.

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

# Session Acquisition End

Scientific acquisition has ended, scientific Session Time freezes, and Experiments
have been appropriately ended; post-session framework processing may remain.
Ending one Experiment within a Session does not trigger Session-wide collection
or finalization (Decision 275).

---

# Session Processing Finalization

Controller-orchestrated completion of required post-session processing and
handling of persistent post-session evidence, after which the Evidence Archive
can be finalized. Session retains lifecycle ownership; this distinction introduces
no new lifecycle state or retroactive acquisition-failure policy. The Session-wide
published-evidence consumption/drain guarantee remains open under Q019.
Slice 25 exposes the explicit stopping-Session collection-before-finalization
sequence (Decision 275), without claiming a Session-wide consumption guarantee.

---

# Session Record

A durable record describing one Session.

Examples include:

* accepted Session Configuration
* Session lifecycle evidence
* device readiness evidence
* service readiness evidence
* session_start and session_stop acquisition events
* accepted acquisition envelopes
* ingest audit records
* accepted durable runtime evidence
* runtime evidence intake audit records
* final session status
* warnings, recoverable failures, and fatal failures
* cleanup evidence

The Session Record preserves what was intended, what was ready, what ran, what was acquired, what was ingested, how the Session ended, and what failed.

The Session Record is separate from the Evidence Archive. The Session Record describes the Session itself; the Evidence Archive stores persistent runtime observations that support the Session Record.

The accepted v1 conceptual persistence layout includes `session_record_initial.json`, `session_record_final.json`, and an `evidence/` directory containing `runtime_evidence.jsonl`, `ingest_audit.jsonl`, and `compilation_summary.json`. Category-specific evidence folders are not part of the v1 concept.

The detailed manifest format, schema evolution, reconstruction outputs, and export formats are defined separately.

---

# Evidence Archive

The persistent archive of runtime observations supporting a Session Record.

The Evidence Archive is written by StorageManager from persistent information compiled by Ingestor. It is not a replacement for the Session Record and does not decide evidence meaning, lifecycle, retention, artifact transfer, reconstruction, NWB export, or global scientific data collection.

The accepted v1 conceptual layout stores persistent runtime evidence in one `runtime_evidence.jsonl` stream, with separate ingest audit and compilation summary files.

Decision 275 requires legitimate post-session persistent evidence to have an
opportunity to be produced before the archive is finally closed. Slice 25 uses
the same archive for global collection evidence, with no category-specific file
or folder. The evidence-enabled Controller path awaits collection publication
before the caller invokes existing finalization. How Controller
knows every durable publication has reached Ingestor before final compilation
remains a Session-wide open question (Q019), not an implemented drain protocol.

---

# Session Time

The master scientific timebase within a Session used to align streams, events, Experiments, and timing records.

Session Time has exactly one owner: the Synchronization Manager.

Components receive Session Time from SynchronizationManager or apply an explicit SynchronizationManager-authorized mapping. Session Time is distinct from AcquisitionNode Local Time, Device-Native Timing, Ingest Time, wall-clock time, broker time, message-arrival time, and other transport timestamps.

Scientific Session Time freezes at acquisition end and is not extended through
post-session collection or verification. Collection-pass evidence uses operational
wall-clock audit timestamps instead (Decision 273).

---

# Runtime Timing

The best current scientific timing attached to data during acquisition.

Runtime Timing is the primary timing path and remains immutable as raw evidence. Later reconstruction may produce separately identified refined timing but must not silently rewrite Runtime Timing.

---

# Reconstructed Timing

Derived timing produced by offline reconstruction after auditing Runtime Timing and its associated evidence.

Reconstructed Timing may refine estimates or identify degraded intervals, but it remains distinguishable from Runtime Timing.

---

# Storage Manager

The component responsible for persistent writing.

Responsibilities include:

* writing records
* organizing records
* validating storage operations

StorageManager receives compiled persistent information and writes persistent records, including the Evidence Archive and final Session Record in the accepted persistence lifecycle.

Decisions 245-260 assign global artifact retrieval to StorageManager. Decisions
261-270 additionally define completed, software-validated light verification of
the global copy (M012, W032); this does not transfer authoritative local artifact
ownership or make StorageManager a scientific interpretation component.

Decisions 271-274 additionally assign StorageManager its own post-session global
collection evidence through the existing durable publication boundary. This is
completed Slice 25 behavior (M013, W033), not a new transport or
scientific interpretation responsibility.

The Storage Manager does not own synchronization, Session lifecycle, Experiment
lifecycle, acquisition, other components' runtime evidence meaning, scientific
interpretation, or Ingestor intake policy.

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

It produces or authorizes synchronization information and detects timing conditions related to Session Time authority. It does not transfer ownership of Session Time to Controller, AcquisitionNode, transport, or a local machine clock.

---

# Synchronization Update

Timing evidence produced by SynchronizationManager when it creates or replaces the active relationship between an AcquisitionNode's monotonic local time and Session Time.

SynchronizationManager owns validation and atomic activation. AcquisitionNode receives and applies the resulting active immutable SynchronizationMapping to subsequently acquired records only. Mapping updates are preserved runtime timing evidence.

---

# SynchronizationMapping

An immutable relationship created and owned by SynchronizationManager for mapping AcquisitionNode local monotonic time to Session Time.

Its minimum plain-data fields are `session_id`, `acquisition_node_id`, `local_time_anchor_s`, `session_time_anchor_s`, `scale`, and `created_session_time_s`.

SynchronizationManager alone creates, activates, replaces, and retires mappings. AcquisitionNode applies the active mapping locally without modifying or validating it. Replacement is atomic and prospective and never retroactively changes records already timestamped during runtime.

The architecture does not require a mapping identifier on every acquired row.

Detailed mapping mathematics remain unresolved under Q006.

---

# Active Synchronization Mapping

The one SynchronizationMapping currently activated by SynchronizationManager for an AcquisitionNode's prospective runtime timestamping.

The active mapping remains SynchronizationManager-owned even while AcquisitionNode applies it locally.

---

# Synchronization Observation

SynchronizationManager-owned runtime timing evidence created from AcquisitionNode local-time reports.

It contains the local-time information needed for SynchronizationManager-owned drift estimation and remapping decisions. AcquisitionNode supplies local-time samples but does not create Synchronization Observation evidence. The observation is evidence, not a mapping and not a remapping decision.

---

# AcquisitionNode Local-Time Report

Plain runtime data reported by AcquisitionNode to SynchronizationManager periodically or when requested.

Its minimum fields are `session_id`, `acquisition_node_id`, `acquisition_node_local_time_s`, `reported_reason`, and `details`.

A local-time report is not Synchronization Observation evidence. SynchronizationManager decides whether to create Synchronization Observation evidence from the report.

---

# Mapping Update Evidence

Scientific Runtime Timing evidence created by SynchronizationManager whenever an active SynchronizationMapping is created, replaced, or retired.

Its minimum fields are `session_id`, `acquisition_node_id`, `update_type`, optional `previous_mapping`, optional `new_mapping`, `created_session_time_s`, `reason`, and `details`.

Mapping updates are not hidden state and never modify previously timestamped runtime evidence.

Mapping Update Evidence remains in SynchronizationManager memory during runtime and is preserved as RuntimeEvidenceMessage through existing Ingestor intake/audit and Session Record finalization. No separate timing-storage component owns it.

Its durable runtime wrapper uses `evidence_type: mapping_update_evidence`, with the MappingUpdateEvidence plain-data form in `RuntimeEvidenceMessage.payload`. This vocabulary value changes neither timing ownership nor communication, ingestion, or Session Record ownership.

---

# Remapping

SynchronizationManager-owned replacement of the active immutable SynchronizationMapping with a newly created immutable mapping.

SynchronizationManager alone decides whether remapping is required. AcquisitionNode neither requests a consequence nor decides when to remap.

---

# Drift Estimation

The SynchronizationManager-owned evaluation of its Synchronization Observation evidence to assess the relationship between AcquisitionNode local time and Session Time.

Its algorithm remains an implementation detail of SynchronizationManager. Drift estimation may lead SynchronizationManager to replace the active mapping; AcquisitionNode does not perform this decision.

---

# Timing Record

A record that describes when data occurred or how timing relationships should be reconstructed.

Examples:

* timestamps
* frame numbers
* sample indices
* synchronization records
* synchronization mappings

Timing Records are part of the raw scientific record.

---

# Timing Audit Evidence

Scientific evidence used to assess runtime timestamp quality and reconstruct timing relationships.

Examples include AcquisitionNode Local Time, Timestamp Status, Synchronization Observations, mapping updates, active and superseded mappings, correction and drift evidence, timing-quality evidence, and preserved Device-Native Timing. It may be stored with data rows or as associated Timing Records.

---

# Timestamp Status

An auditable indication of the timing state or quality under which an AcquisitionNode timestamped a record.

Timestamp Status accompanies Runtime Timing or associated Timing Audit Evidence. It is not a transport timestamp or a replacement for Session Time.

---

# Timing Quality Observation

Evidence of a detected timing condition.

SynchronizationManager detects conditions related to Session Time authority. AcquisitionNode detects conditions related to local runtime timestamping and synchronization mappings. DeviceAdapters do not detect Phase 11 timing-quality failures.

---

# Timing Quality Policy

Experimenter-configured policy that interprets Timing Quality Observations using the accepted operational interpretation vocabulary.

It does not itself execute framework consequences. Controller owns decisions and actions resulting from interpretation evidence.

---

# Timing Quality Interpretation Evidence

Evidence recording how an assigned Timing Quality Policy interpreted one Timing Quality Observation.

It preserves the observation-to-policy-to-interpretation chain. Controller may use it to create and execute a ControllerActionDecision; the interpretation evidence itself does not mutate Session or Experiment lifecycle.

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

The Phase 1-9 unit of acquisition data exchanged between the acquisition side and the Ingestor in the validated bounded-envelope workflows.

An Acquisition Record Envelope contains session identity, source device
identity, record kind, and records in a plain-data form that can cross a process
or computer boundary. Phase 2 envelopes may also contain `source_node_id`;
existing Phase 1 envelopes remain valid without it.

Phase 10 narrows this assumption for large-artifact workflows: NATS carries runtime evidence, metadata, and artifact manifests, while authoritative scientific rows and artifact bytes may remain local rather than crossing the Ingestor online.

---

# Acquisition Node Readiness

Node/deployment-scoped technical readiness evidence created by AcquisitionNode,
queryable before Session creation (Decisions 284-286).

The accepted contract replaces session_id with reserved_for_session_id: str | None.
None means unreserved; a value identifies the reserving Session. Its ready boolean
describes required framework/service prerequisites, not whether every scientific
device is ready. Every declared enabled device has individual DeviceReadiness;
missing adapters or failed determination produce ready=False with a reason.
Controller evaluates those devices against prospective Session selections.

Technical readiness and reservation are independent. A valid ready/unreserved
report means available; ready but reserved for another Session means unavailable.
A valid ready=False report means not ready. No valid current report means unknown
to Controller, not a new readiness enum. Atomic reservation is authoritative;
the report is only a snapshot.

The implemented class uses reserved_for_session_id and aggregates required
services only, retaining complete independent device reports. Controlled
broker-double tests cover this contract; they are not live NATS, cross-process,
or hardware validation. M015 remains pending follow-up validation and audit.

---

# Runtime Participant

A deployment/lab-scoped active framework actor identified by the existing
RuntimeParticipant component_type and component_id, independently of Session.
Examples are Controller, AcquisitionNode, Ingestor, StorageManager, and
SynchronizationManager. Scientific devices are not RuntimeParticipants.

The identity contains no machine/network addresses, subjects, or retrieval paths.
Final SessionConfig specifies expected participation for that Session, not
identity creation. Current code uses these identities for pre-Session commands
and expected Session participation. Discovery/registration remains deferred.

---

# AcquisitionNode Declared Device Inventory

The node-scoped declarations of expected devices and supported scientific
products, owned by AcquisitionNode before Session creation. Reuses
DeviceDeclaration and ScientificProductDeclaration; inventory membership
identifies the owning node without a redundant node ID in each declaration.
Declared devices remain visible when unavailable or disconnected.

This is not automatic discovery or Session-selected availability. Session
selection consumes the inventory and does not redefine it. Slice 28 implements
inventory and upward reporting through existing NATS command/result handlers,
with controlled broker-double coverage rather than live deployment validation.

---

# AcquisitionNode Reservation

Exclusive node-owned allocation to one intended session_id at a time. A Session
may reserve multiple nodes; devices are not separately reserved. Unreserved
nodes atomically accept, the same Session succeeds idempotently, and another
Session is rejected without changing ownership. Only the owning Session identity
may release. No reservation ID, lease, timeout, heartbeat, or central scheduler
is introduced.

Reservation covers acquisition and local artifact finalization, not global
collection. Controller releases after local completion; later retrieval needs
no original reservation and release does not delete local artifacts.

Failed-launch release is qualified by Decision 300: if initialization may have
started, the node must confirm cleanup first. Missing initialization or cleanup
responses leave availability unconfirmed and the reservation protected.

---

# Pre-Session Communication

Accepted participant-scoped commands addressed by RuntimeParticipant
component_type/component_id before Session creation. The general command envelope
may omit session_id for operations such as check_readiness that do not concern a
Session. Reservation, initialization, and acquisition require a real Session ID;
acquisition additionally requires matching active binding. No fabricated Session
ID or second communication framework is used. Existing NATS handlers implement
this contract with controlled broker-double coverage; live distributed deployment
validation is not implied.

---

# Session Binding

AcquisitionNode-owned association with at most one active Session, separate from
its deployment identity, technical readiness, and Session-keyed reservation.
Initialization verifies reservation ownership before establishing binding.
Partial binding is retained for cleanup after preparation failure; binding alone
does not establish acquisition eligibility. Distributed acquisition requires
successful local Session preparation, and abort or runtime cleanup clears that
eligibility. Historical explicitly pre-bound local nodes retain their
caller-prepared workflow. Session-specific acquisition commands must match the
binding. The NATS handler routes and
checks against node state, remains connected across Sessions, and owns no separate
binding authority. No remote Session replica is introduced.

---

# Initialization Confirmation

Explicit participant result confirming its required Session-specific preparation.
For a node this includes binding, selected-device preparation, Session-scoped
LocalStorageManager initialization, and required local preparation. Ingestor
confirms evidence intake/recovery-journal preparation; SynchronizationManager
confirms synchronization-state preparation. Missing/invalid/unresolved results
are unconfirmed, not success or proof of absent remote state. Session retains
the initialization-completion boundary; Controller requires every mandatory
confirmation before declaring launch successful.

---

# Initialization Abort

Idempotent Session-keyed cleanup of potentially partially initialized node
runtime, requested by Controller and performed/confirmed by AcquisitionNode.
Confirmed cleanup precedes reservation release and binding clearance; unconfirmed
cleanup leaves the reservation protected, including when runtime stop succeeds
but subsequent storage cleanup fails. A later explicit abort must complete any
unfinished cleanup before confirming success; this is not an automatic retry.
All potentially initialized mandatory
participants, including previously successful ones, participate in failed-launch
cleanup. Accepted evidence, recovery journals, finalized artifacts, and established
timing evidence are preserved. This is not Experiment abort, a new lifecycle
state, retry, or crash recovery.

---

# Participant Startup and Service Deployment

Current development/validation starts NATS/JetStream separately and participants
manually in independent processes, potentially on different PCs/Jetsons, with
each independently connecting to NATS. Intended deployment uses independently
running long-lived services; manual shells/startup scripts are temporary
development infrastructure, not deployment architecture. Controller does not
launch processes or manage NATS. Required connectivity precedes distributed
readiness; startup connection failure is explicit, not indefinite waiting or
claimed readiness. Supervision, automation, retry/reconnection, registration,
and discovery remain deferred.

---

# Record Kind

A minimal label identifying the broad kind of records being carried.

Examples may include stream, event, timing, file_reference, or other accepted record categories.

The detailed stream/event schema is defined separately.

---

# Service Readiness

A standardized readiness report produced by framework services such as the Ingestor, StorageManager, and SynchronizationManager.

ServiceReadiness.required identifies required framework/service prerequisites.
Accepted Slice 28 launch uses this evidence through Controller before Session
creation as well as existing initialization evidence. Ingestor and
SynchronizationManager readiness are mandatory launch prerequisites; unready,
unreachable, or unknown blocks launch. They do not use exclusive node reservations.
StorageManager is not a launch prerequisite; its later persistence duties and
final-persistence success requirements remain unchanged. Acquisition-local
storage prerequisites are separate from global StorageManager availability.

It does not describe device readiness.

---

# Device Readiness

Technical readiness of one scientific device, separate from Session-selection
criticality. Under accepted Slice 28, DeviceReadiness omits required;
DeviceDeclaration.required determines criticality for selected Session devices.
The implemented DeviceReadiness contract omits that historical required field.

DeviceManager obtains adapter readiness. AcquisitionNode's report additionally
accounts for every declared enabled device, including ready=False with a reason
for missing adapters, disconnection, or failed determination. DeviceReadinessSummary
collects device results, but does not determine node service-only readiness.

It is distinct from Service Readiness.

Decision 302 additionally requires a safely cleaned adapter in DECLARED to be
eligible for existing pre-Session readiness evaluation, without pretending it is
already initialized or acquiring. Failed or unconfirmed cleanup must not report
safe reuse. This sequential-reuse readiness behavior is implemented without
a new readiness enum or preparation operation.

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

Decision 302 accepts successful shutdown and required cleanup returning to
DECLARED, while initialize(config) continues to require DECLARED. The implementation
completes adapter-specific resource release before returning to DECLARED and
retains FAILED if release fails. The legacy SHUTDOWN enum value remains available
but is not the normal cleanup result. DeviceStatus.shutdown reports completed
cleanup even in DECLARED and resets on the next initialization. No state was added.

---

# Declared DeviceAdapter

A retained live adapter with its deployment declaration, eligible for the existing
initialize(config) operation. Under Decision 302, this is also the state reached
after successful shutdown and confirmed required cleanup, not merely after
reservation clearance or closing one handle. Failed or unconfirmed cleanup does
not authorize return to DECLARED or subsequent initialization.

Deployment inventory and configuration remain retained. Session-specific settings
must be supplied for the next Session through its resolved SessionConfig rather
than silently inherited from the previous Session.

---

# Sequential Session Reuse

Consecutive Sessions using the same retained AcquisitionNode and DeviceAdapter
instances after confirmed cleanup and reservation release (Decision 302).
AcquisitionNode coordinates subsequent initialization; DeviceAdapter owns its
state and device-specific work; DeviceManager coordinates lifecycle operations;
Controller evaluates readiness and orchestrates launch without hardware reset.

Previous artifacts and evidence remain preserved, and each Session has its own
configuration and scientific outputs. This is not concurrent sharing, scheduling,
crash recovery, or automatic retry. The generic return-to-DECLARED and readiness
path is implemented with simulated and broker-double regression coverage;
independent manual validation and audit remain pending, and M015 remains open.

---

# Acquisition-side Caller (Historical)

The earlier temporary runtime role that coordinated acquisition-side operations before AcquisitionNode ownership was established.

Examples included collecting records from the DeviceManager, obtaining Session Time from the Synchronization Manager, creating Acquisition Record Envelopes, and forwarding them to the Ingestor.

This is not a current framework component. AcquisitionNode now owns runtime timestamping and the acquisition-side envelope workflow; SynchronizationManager remains the sole owner of Session Time.

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

Persistent Storage begins after persistent information is compiled by the Ingestor and accepted by the Storage Manager for writing.

For v1, accepted Acquisition Record Envelopes may be stored as JSONL, with one envelope dictionary per line.

JSONL is a storage backend detail, not a replacement for the Storage Manager architectural boundary.

The Phase 13 conceptual Evidence Archive also uses JSONL for persistent runtime evidence. Archive evolution, retention/deletion, artifact transfer, reconstruction, NWB export, and global scientific data collection remain future architecture.

---

# Readiness

An automatic framework operation before Session creation during Controller-owned
launch, and during initialization, that determines whether components can safely
participate. Technical readiness remains separate from reservation availability.

Readiness is not operator-initiated and does not create an Experiment.

---

# Readiness Gating

The process of determining whether launch/initialization may proceed from
readiness evidence. In Slice 28 Controller evaluates selected device readiness
using DeviceDeclaration.required and required framework/service readiness before
constructing final SessionConfig. Required device failure blocks launch;
unavailable optional selections may be omitted and must not remain selected.

AcquisitionNodes are launch-critical only when they contain required selected
resources. Existing Session initialization evidence/gates are historical
implementation, not a replacement for accepted pre-Session launch resolution.

---

# Shared Readiness Contract

The common readiness record shared between DeviceManager and Session.

The shared readiness contract is produced by DeviceManager and consumed unchanged by Session.

Shared evidence remains reusable without a new Session-only type. The historical
DeviceReadiness.required/direct required-device gate is superseded by Decision
286: Controller applies Session-selection criticality while node reports carry
technical readiness only. Session retains its recorded readiness evidence.

---

# End-to-End Lifecycle Test

A vertical-slice test that exercises the intended public workflow of the framework using fake components.

An End-to-End Lifecycle Test validates component interaction through public APIs rather than internal implementation details.

It is intended to document expected framework usage as well as verify behavior.

---

---

# Device Declaration

A plain-data declaration reused for AcquisitionNode inventory and selected
Session devices, independent of live hardware availability.

A Device Declaration identifies a device independently of any live hardware connection.

Typical fields include:

* device_id
* device_type
* enabled
* required
* declared_capabilities

AcquisitionNode inventory contains declarations before Session creation. Final
Session Configuration contains selected declarations after launch resolution;
it does not own or create deployment inventory. Inventory membership identifies
the node without another node ID on DeviceDeclaration.

They are used by caller code to explicitly construct live DeviceAdapters.

A Device Declaration is not a live device and does not communicate with hardware.

A Device Declaration describes supported products and Session-selection intent.
Its required flag defines selected-device criticality, not device technical
readiness or permanent node criticality. It does not contain or assign an
acquisition-health policy; the active Experiment Runtime Health Mapping owns
that assignment. No product-level required flag is introduced.

---

# Session Configuration

The final resolved run configuration owned by the Session that will actually run.

Session Configuration declares the intended runtime configuration of a Session, including selected Device Declarations, session parameters, device configuration, synchronization configuration, acquisition configuration, ingestion/storage configuration, protocol intent or reference, and the available `AcquisitionHealthPolicy` definitions.

Session Configuration is also authoritative for expected runtime participants, represented as plain component type and component identifier declarations rather than discovered live services.

Controller constructs SessionConfig after readiness checks, node reservation
outcomes, and optional-resource resolution. It is not a prospective wish list;
unavailable optional resources that were omitted do not remain in selected_devices.
RuntimeParticipant identities exist independently of this Session selection.
Experiment-scoped ScientificOutputSelection remains separate and gains no
required field for Slice 28. The historical workflow still accepts caller-created
SessionConfig; Controller.launch_session implements pre-Session resource resolution
and distributed preparation, pending independent validation and audit.

SessionConfig.local_storage_roots currently represents caller-supplied overrides
in the historical local implementation. Under accepted distributed initialization
(Decision 298), each node uses its deployment-defined root/configuration; Controller
does not select or override remote filesystem roots or artifact paths. No new
deployment configuration format is defined by that clarification.

Acquisition-health policy definitions are persistent Session-scoped configuration. Experiment Runtime Health Mappings assign those definitions to live sources as Experiment-scoped runtime intent.

The accepted Session Configuration is immutable for the duration of the Session.

The accepted Session Configuration is part of the persistent Session Record.

It represents intended execution rather than runtime state.

Session Configuration is validated during Session initialization.

It does not contain runtime objects such as DeviceAdapters, DeviceManagers, or other live framework components.

---

# Session Launch

Controller-owned resolution and runtime assembly for prospective Session
selections. Controller allocates an intended nonreusable Session ID, obtains
current readiness/availability, resolves device criticality, reserves selected
AcquisitionNodes, constructs final SessionConfig, and creates/initializes Session.
Launch succeeds only after acquisition-critical participants complete required
initialization/preparation, not merely when Session exists.

Before success, Controller coordinates cleanup for every mandatory participant
whose initialization may have started and returns operational failure. Nodes
confirm cleanup before reservation release; unconfirmed cleanup leaves the
reservation in place. Each participant prepares and cleans up its own runtime,
without remote Session replicas or a second lifecycle authority. No SessionLaunchIntent, new lifecycle
state, durable pre-Session launch journal, or mandatory Ingestor submission is
introduced. Slice 28 launch is implemented with controlled broker-double tests;
the audit corrections require follow-up validation and audit before M015 closure.

---

# Unknown Readiness

Controller's interpretation when no valid current readiness report is available.
It is not a third boolean value or readiness enum and does not assert confirmed
remote failure. A successful node report instead represents failed device
readiness determination as ready=False with a reason. Missing required Ingestor
or SynchronizationManager readiness blocks launch.

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






