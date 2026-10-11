# Lab Sync Acquisition



A modular synchronization and acquisition framework for neuroscience experiments.



## Overview



This repository is developing a hardware-agnostic framework for:



* data acquisition

* device synchronization

* timing management

* session storage

* session reconstruction



The framework is intended to support behavioral and neural experiments involving multiple devices, including:



* cameras

* lick sensors

* water delivery systems

* speakers

* accelerometers

* future sensors and actuators



The framework is independent of any specific experiment and independent of any specific graphical user interface.



A separate GUI may configure and control experiments, but the GUI is considered a client of the framework rather than part of the framework itself.

In framework terminology, a Project is the larger scientific study, a Session
is one bounded acquisition/evidence run, and an Experiment is scientific or
protocol activity inside a running Session.



---



## Project Goals



The framework aims to provide:



* a common device abstraction

* explicit ownership of synchronization and timing

* reproducible session reconstruction

* human-readable intermediate outputs

* compatibility with NWB export

* support for future hardware expansion



---



## Motivation



This project is informed by lessons learned from a previous acquisition system that suffered from:



* no explicit timing authority

* independently generated timestamps

* no drift handling

* no periodic synchronization

* incomplete synchronization implementation

* complex process interactions

* unclear ownership of responsibilities



The architecture of this framework is being designed specifically to avoid those failure modes.



---



## Current Status



The project is currently in the architecture design phase.



Small parts of the implementation have begun.

The Phase 2 envelope path has been manually validated over Wi-Fi between an
NVIDIA Jetson Orin AcquisitionNode and a Windows ingestion/storage computer.
The same two-machine path has also been validated with a real Jetson USB camera
using OpenCV/V4L2 and metadata-only acquisition envelopes.

Phase 4 Controller v1 now provides validated sequential orchestration for one
bounded Session, including normal completion, runtime failure outcomes, cleanup,
and the historically validated two-step persistent Session Record finalization.
Phase 13 subsequently separates the Evidence Archive from the Session Record and
writes both before `Session.complete()`; this does not claim a persisted
post-completion terminal snapshot, whose representation remains for separate review.

Phase 5 now provides validated Controller-owned Experiment lifecycle, persistent
Experiment descriptors and Expected Participant declarations, explicit runtime
health mappings that assign Experiment-specific acquisition-health policies,
and AcquisitionNode health evaluation scoped only to mapped live acquisition
sources. Device declarations describe Session availability rather than global
health-policy consequence.

Phase 6 adds evidence-only Experiment-scoped health observations and immutable
plain-data acquisition-health policy definitions. Observation type remains
separate from consequence, policy assignment remains Experiment-scoped, and
runtime warning/failure/Controller behavior is intentionally deferred.

The current Phase 7 slice adds SessionConfig-owned policy definitions with
rule-specific `evaluation_rules`, immediate AcquisitionNode policy
interpretation, and explicitly linked Health Interpretation Evidence. These
interpretations remain evidence only; Controller actions and lifecycle
consequences are intentionally deferred.

Phase 8a adds explicit, evidence-only `ControllerActionDecision` records for
Health Interpretation Evidence presented directly to Controller. Decision
execution, lifecycle consequences, notification, recovery, and distributed
evidence delivery remain intentionally deferred.

Phase 8b executes Experiment- and Session-failure decisions through existing
lifecycle owners. Experiment failure records canonical `experiment_fail`
evidence and ends only the active Experiment; Session failure reuses the
existing failed-Session cleanup path.

Phase 9 normalizes local `ControllerActionDecision` vocabulary. Record-only,
warning, recoverable-failure, and operator-required decisions execute
successfully without lifecycle mutation; `experiment_fail` and `session_fail`
retain their accepted lifecycle behavior.

Phase 10 brokered NATS communication architecture has been accepted and
documented. Phase 10b now provides the first real nats-py communication
boundary for durable commands, command results, evidence, and transient Core
NATS telemetry. The local JetStream workflow has been manually validated with
three successful AcquisitionNode runtime commands, explicit command results,
durable evidence intake, and transient telemetry. It does not yet implement
reconnect, retry, replay, recovery, artifact transfer, or production deployment.

The current readiness slice records expected runtime component identities in
`SessionConfig`, carries AcquisitionNode readiness requests and existing
readiness evidence through the command/result path, and represents NATS
availability through the existing required service-readiness gate.

The independent-consumer slice allows Ingestor and Controller to consume the
same durable evidence through separate JetStream consumers. Controller uses its
existing health-interpretation decision behavior, while Ingestor independently
preserves and audits evidence. Telemetry remains transient Core NATS data with
no lifecycle or persistence effects.

Artifact lifecycle manifests now use the existing durable runtime-evidence
path with an explicit `artifact_manifest` evidence type. This adds no artifact
bytes, transfer backend, storage layout, or checksum behavior;
authoritative scientific data remain local to the producing component.

Controller finalization now preserves the Phase 13 separation: the Session
Record describes the Session, while the separate Evidence Archive stores
Ingestor-compiled producer-marked persistent runtime evidence and runtime-evidence
intake audit. This describes the accepted conceptual separation; reconciliation
of runtime evidence also retained in current Session Record contents remains for
separate architectural review.

Phase 10 is implemented through the accepted brokered Control Plane boundary,
including configured group-command fan-out, issuer-owned result aggregation,
and unresolved missing-response evidence. Recovery policy remains deferred.
The separate Slice 23 SSH/SFTP Artifact Plane implementation is described below.

The readiness, publication-failure, independent Controller/Ingestor evidence
consumption, artifact-manifest, and Core NATS telemetry paths have also been
manually validated against a real local JetStream broker.

Phase 12 Local Storage and Session Record architecture is accepted in
Decisions 178-218. Its first implementation slice now provides the co-located
`LocalStorageManager` core for readiness, incremental JSONL scientific streams,
authoritative local artifact manifests, local storage evidence, flush,
finalization, and local completion summaries. Slice 20.3 implements Session,
Controller, and AcquisitionNode integration for explicitly selected scientific
products. Global retrieval, light verification, and collection-pass evidence are
implemented in the later slices described below; broader global integration,
transfer scheduling, reconstruction, and export remain future work.

Local HDF5 scientific persistence is now implemented and covered by synthetic
array tests. Select `storage_format="hdf5"` in
`LocalStorageManager.create_stream()` and supply
`schema={"frame_shape": [height, width, channels], "frame_dtype": "uint8"}`
(two-dimensional grayscale shapes are also supported). JSONL remains the default.
Append rows containing a NumPy `frame`, integer `frame_index`, `experiment_id`,
`session_time_s`, `experiment_time_s`, `acquisition_node_local_time_s`, and
`timestamp_status`. Frame shape and dtype must match the declared schema;
pixel values are stored without conversion or compression.

The local artifact is `frames.h5` alongside the existing readable metadata and
manifest JSON files. Its extendable `frames` dataset has shape
`(N, *frame_shape)`. Aligned one-dimensional datasets contain `frame_index`,
the three scientific time fields, and UTF-8 `timestamp_status`.
`record_metadata_json` preserves the other per-frame information, including
optional device-native timestamps with missing values left absent.
The `metadata_json` attribute stores static stream metadata; artifact identity
and committed `persisted_frame_count` are also stored as attributes.

Use the existing `max_buffered_rows` and `max_flush_interval_s` constructor
options for bounded persistence batching; 20 frames is an explicit example,
not a framework default. With no row buffer configured, HDF5 flushes each frame.
Buffered arrays are copied to preserve pixels when callers reuse their arrays.
The interval is checked during append; idle periods require an explicit
`flush()` call. Finalization flushes the remainder and closes the artifact.

### Manual Camera HDF5 Check (Jetson)

From the repository root, the existing smoke script defaults to one metadata-only
iteration on camera index 0, with no image persistence:

```bash
python scripts/manual_opencv_camera_smoke.py
```

The original positional camera source and `--error-evidence-location` arguments
remain supported. Opt in to scientific acquisition and post-closure HDF5 readback:

```bash
python scripts/manual_opencv_camera_smoke.py 0 --scientific --duration 10 --width 640 --height 480 --output-dir ./camera_smoke_output
```

For optional visual inspection after successful acquisition, HDF5 validation,
and camera cleanup, add `--show-frames`:

```bash
python scripts/manual_opencv_camera_smoke.py 0 --scientific --duration 10 --show-frames
```

Inspect an existing recording without OpenCV, camera access, or Session startup:

```bash
python scripts/manual_opencv_camera_smoke.py --view-hdf5 ./path/to/frames.h5
```

Visualization requires optional Matplotlib (`python -m pip install matplotlib`);
ordinary smoke checks do not import or require it. The viewer reads only six
evenly spaced frames (or all available frames when fewer than six exist), labels
them with their recorded frame indices, and converts OpenCV BGR/BGRA to RGB/RGBA.
Grayscale is supported; wider integer color pixels are scaled to their dtype
range for display only. The original HDF5 file is always opened read-only.
This is visual inspection, not a replacement for scientific HDF5 validation.

With a graphical Matplotlib backend the contact sheet opens in a window. On
headless systems, with a noninteractive backend, or if graphical display fails,
the viewer saves `frames_contact_sheet.png` next to `frames.h5` and prints
`contact_sheet=<absolute path>`. `MPLBACKEND=Agg` can explicitly request this
PNG behavior. Repeated inspection replaces the contact-sheet PNG, never the
recording. Missing/unreadable/empty recordings or visualization failures return
a nonzero status without altering the recording.

This uses Controller Session/Experiment commands, explicit camera-product
declarations/selections, AcquisitionNode collection, and LocalStorageManager
persistence. It does not write frames directly or send raw arrays to Ingestor.

Options:

- `camera_source`: optional index (default 0) or OpenCV source/pipeline string.
- `--api-preference`: OpenCV backend integer (default `cv2.CAP_ANY`).
- `--scientific`: enable raw-frame HDF5 acquisition and verification.
- `--show-frames`: inspect recorded frames after successful scientific validation.
- `--view-hdf5 PATH`: inspect an existing recording without acquisition; cannot
  be combined with `--scientific`.
- `--duration`: positive acquisition-loop duration in seconds (default 10).
- `--output-dir`: output root (default `camera_smoke_output`).
- `--width`, `--height`: requested capture dimensions; scientific defaults 640x480,
  while metadata-only mode leaves them unset.
- `--channels`: scientific shape declaration, 1, 3, or 4 (default 3); 1 declares
  a two-dimensional grayscale frame. It does not convert camera frames.
- `--frame-dtype`: scientific dtype declaration (default `uint8`), not conversion.
- `--fps`: optional requested camera frame rate.
- `--frames-per-collect`: bounded camera batch size (default 1).
- `--max-buffered-rows`: explicit scientific persistence batch size (default 20).
- `--error-evidence-location`: failure evidence root (default `<output-dir>/errors`).

Each scientific run has a unique Session subdirectory below the output root.
The script prints the exact `artifact_path`; `frames.h5`, `metadata.json`, and
`artifact_manifest.json` live together in the framework-managed scientific stream
directory. Session Records and runtime metadata are also retained for diagnosis.

Example successful output (values and paths vary; additional diagnostics omitted):

```text
camera_device=0
experiment_id=camera-validation
artifact_path=.../frames.h5
frame_count=250
frame_shape=(480, 640, 3)
frame_dtype=uint8
frame_indices=(0, 249)
session_time_range_s=(0.1, 10.1)
experiment_time_range_s=(0.01, 10.01)
manifest_status=finalized
finalization=finalized
validation=PASS
```

PASS means nonempty, finalized, readable HDF5 with consistent manifest counts,
declared shape/dtype, ordered indices, aligned Session/Experiment Time, and
readable per-frame metadata. Optional native timestamps may be absent. FAIL
returns a nonzero exit status and preserves available artifacts/error diagnostics;
interruption returns 130. Neither result establishes wider scientific validity.

Use the supported Python 3.12 environment with NumPy and h5py installed, plus a
Jetson-compatible OpenCV build and camera/backend access. No display or external
service is required. CSI cameras may need an appropriate source pipeline and
`--api-preference`; USB cameras commonly use an index. Capture backends may ignore
requested dimensions: set the declaration to the actual frame shape/dtype if
validation reports a mismatch. Duration is checked between bounded collections;
a blocking hardware read can overrun it. Slice 20 is complete: the user-reported
Jetson hardware validation recorded 256 `uint8` frames at 640 x 480 x 3 over
10 seconds, with indices 0-255, finalized artifact and manifest, successful HDF5
reopening, and `validation=PASS`. Recorded-frame display and visual inspection
also succeeded on the Jetson. See W029 in
[`docs/validated_workflows.md`](docs/validated_workflows.md) for the acquisition,
`--show-frames`, and `--view-hdf5` commands and M008 in
[`docs/framework_milestones.md`](docs/framework_milestones.md) for completion.
Manifests and local completion summaries distinguish accepted from successfully
persisted frames and report frame/time bounds, duration, and finalization outcome.
Handled write, flush, and closure failures produce local evidence and do not
claim successful finalization. Failed HDF5 streams do not accept further writes.

JSONL failure evidence, manifests, and completion summaries distinguish
`accepted_row_count`, `buffered_row_count`, `written_row_count`, and
`durable_row_count`. Written rows count complete file-write calls; durability
is confirmed only after successful flush and `fsync`. An incomplete write or
failed file flush leaves an uncertain tail: `row_count` is null and successful
finalization is rejected. A caller may explicitly flush or finalize after an
`fsync` failure without re-appending already written rows; no automatic retry
or recovery is introduced.

Explicit local scientific camera collection is also implemented and tested with
synthetic NumPy frames. `DeviceManager.collect_scientific_records()` returns
`DeviceCollectionResult` objects with separate `runtime_records` and optional
`scientific_records`; the camera's scientific rows contain the original `frame`
array plus frame index and available device metadata. Both collections are
produced by the same camera reads. The adapter's `collect_records()` and the
manager's existing default path remain metadata-only. Neither DeviceAdapter nor
DeviceManager assigns Session Time or Experiment Time. Scientific results are
local collections and are not automatically enveloped, transported, or ingested.
OpenCV zero-valued optional properties are ambiguous with unsupported-property
responses and are left absent rather than treated as measured metadata.
Exceptions from optional native-timestamp, FPS, exposure, or gain queries also
leave that metadata absent without failing a frame read or ending acquisition.
Genuine camera read exceptions retain the existing partial-data failure path.

Experiment/AcquisitionNode-to-local-storage integration is implemented and
covered by automated synthetic-frame workflows. AcquisitionNode validates
product-scoped frame/metadata associations before writing a collection.
Completed frames and lightweight metadata survive later camera-read or adapter
exceptions; the original failure is still reported through the existing
Controller failure path. If partial-data persistence also fails, both errors
remain visible. No implicit hardware retry is performed.

Slice 20 software validation includes four successful independent manual
validations and 284 passing automated tests in the environment with optional
Matplotlib dependencies. The supported Python 3.12 suite passed 277 tests with
seven optional rendering tests skipped. These simulated automated tests are
distinct from the successful real Jetson acquisition and visual inspection
recorded in W029. Slice 20 is complete; subsequent Slice 21 completion is
recorded separately in W030 and M009.

Slice 21 is complete under Decision 239 following three successful manual
IPython validations, 62 passing focused audit tests, and independent audit
reassessment. W030 records validation scope and M009 records completion.
`start_experiment()` accepts keyword-only `preparation_readiness=()` (existing `ServiceReadiness`
records) and `preparation_outcomes=()` (existing `GroupCommandOutcome` records).
Required failures and unresolved results block canonical start; optional
service failures are recorded without blocking confirmed required success.
Selected scientific outputs remain required.

Phase 14 / Slice 22 Artifact Collection Handoff architecture is accepted in
Decisions 240-244 and is complete (M010), following implementation, successful
manual IPython validation, and independent audit PASS. W031 records the results
and limitations. AcquisitionNode produces
complete LocalStorageManager-owned initial and finalized manifest messages
through the existing runtime evidence pathway. Its NATS adapter publishes newly
produced messages after commands or explicit publication. Ingestor can
compile one complete manifest entry per artifact for a requested Session,
preferring finalization evidence and explicitly reporting its absence.
Controller initiates post-session collection and coordinates the handoff;
StorageManager owns later retrieval through the separate Artifact Plane.
Slice 22 does not implement artifact-byte transfer, diagnostics compilation,
restart recovery, new persistence infrastructure, or Session lifecycle changes.
Controller's finalize_session result exposes artifact_collection_handoff with
session_id and artifacts entries containing artifact_manifest and
missing_finalization_evidence. Current Ingestor retention is in memory. Slice 22
validation used simulated devices and NATS broker doubles, not live NATS or
hardware acquisition; artifact-byte retrieval was not implemented by Slice 22.

Slice 23 (Decisions 245-260, M011) now provides SSH/SFTP pull retrieval through
`PersistentStorageManager.collect_artifacts(handoff)` and explicit post-session
`Controller.collect_session_artifacts()`. Install the optional dependency with
`pip install -e ".[artifact-retrieval]"` and supply `global_artifact_root` plus
deployment-local `retrieval_endpoints` keyed by AcquisitionNode ID. Each manifest
selects one source file; auxiliary managed paths are not a retrieval list.
Collection returns per-artifact and aggregate outcomes without changing Session
completion policy or authoritative local files. Automated tests use SSH/SFTP doubles;
the Slice 24 software validation also exercises retrieval and handoff behavior
(W032). Real Jetson/SSH-SFTP deployment validation remains pending; M011 is open.

Phase 14 / Slice 24 light-verification architecture is accepted in Decisions
261-270 and is complete (M012, W032), with 26 focused verification tests,
21 retrieval/handoff regression tests, six independent manual IPython scenarios,
and a corrected independent re-audit PASS. The final full suite ran 340 tests:
333 passed, seven optional rendering tests skipped, and no failures. These are
previously executed/reported software results, not real SSH/SFTP validation.
It assigns
StorageManager bounded, non-destructive structural checks after successful global
copy publication, separate from retrieval success and scientific validation.
The first contract covers the current LocalStorageManager HDF5 layout, not all
HDF5 or a device-specific verifier; zero-record artifacts remain valid. Other
formats are copied_unverified. Per-artifact retrieval success remains separate
from verification; aggregate `succeeded` requires successful retrieval and verified
status for every requested artifact (empty collections remain successful).
No manifest redesign or Session lifecycle consequence policy is introduced.
Existing retrieval remains Slice 23 behavior.

The initial audit's HDF5 diagnostic-text classification defect was corrected:
structural rejection without an underlying operational file-access failure is
structurally_invalid; an operational access/read failure preventing a conclusion
is verification_failed. Completed copies remain unchanged in either case.

Phase 14 / Slice 25 Post-session Global Artifact Collection Evidence is accepted
in Decisions 271-275 and is complete (M013, W033), following independent manual
software validation and corrected independent re-audit PASS. StorageManager owns
one compiled persistent `global_artifact_collection_evidence`
record per completed pass through the existing runtime-evidence boundary and
same-Session Evidence Archive. It records attempted-artifact collection/verification
outcomes without a duplicate manifest or aggregate evidence status. Collection-pass
timestamps are operational wall-clock audit time, not scientific Session Time.

Session acquisition end freezes scientific Session Time and ends scientific
acquisition; required post-session processing may remain. Controller orchestrates
Session processing finalization after that work and handling of persistent evidence.
Ending one Experiment does not trigger Session-wide collection. The archive must
not be treated as finally complete before legitimate post-session evidence can
be produced. Configure PersistentStorageManager with the existing async
`evidence_publisher` callable and logical `component_id`; the explicit sequence is
`Controller.stop_session()`, await `Controller.collect_session_artifacts_with_evidence()`,
then `Controller.finalize_session()`. Publication failures are reported through
the existing DurablePublicationError/Controller command-result path. Finalization
rejects active collection/publication without lifecycle mutation; the guard clears
after success, failure, or cancellation. Copied size comes from the temporary
file position; unavailable size is null without changing actual outcomes or
preventing later attempts. W033 records the initial audit FAIL, both corrections,
manual Scenarios 1-5 and 6B PASS (Scenario 6 inconclusive), and final re-audit PASS.
Final tests: 18 Slice 25, 21 retrieval/handoff, 26 verification, and 47
Controller/communication/archive passed; full discovery 351 passed and 7 optional
rendering skips (358 total). These are prior results, not new closure validation. The
Session-wide evidence-drain/Ingestor-consumption guarantee remains OPEN in Q019
and is not implemented; durable acceptance is not proof of consumption.
Decision 303 resolves Q017: later global collection, verification, transfer, or
export failure cannot retroactively change a Session that reached `completed`.
These are operational outcomes, not Session acquisition lifecycle outcomes.
Required pre-completion cleanup and final persistence remain necessary, and
Q019's evidence-consumption/final archive coordination remains open.
M011 remains open pending real Jetson/SSH-SFTP
deployment validation, and M012 remains complete. W033 records Slice 25's software
validation, not live NATS or real Jetson/SSH-SFTP deployment validation. The legacy
unconfigured synchronous collection path remains supported.

Phase 14 / Slice 27 Ingestor Crash Recovery and Handoff Reconstruction implements
Decisions 276-280 and is complete (M014, W034), following independent manual
software validation, correction of the initial audit's one blocking defect,
and targeted independent re-audit PASS.
Slice 26 was redundant with Slice 25 and did not become a separate implementation slice. Slice 27 adds an
Ingestor-owned append-only local JSONL recovery journal for all accepted runtime
evidence, regardless of permanent persistence intent, with durable journal-before-ACK
acceptance, evidence_id deduplication, and normal-view restoration for a known
Session. The existing artifact handoff compiler is reused; successful recovery
produces persistent ingestor_recovery_evidence through normal acceptance.
Configure `InMemoryIngestor(session_id=..., recovery_journal_path=...,
component_id=...)` with an explicit known Session and caller-chosen JSONL path;
the parent directory must already exist. Broker evidence subscriptions require
matching journal configuration. Legacy local in-memory use remains available.
W034 preserves the actual history: manual Scenarios 1-5 PASS; Scenario 6 exposed
an uncertain-fsync architectural ambiguity, clarified within Decision 276;
Scenario 6R PASS; initial audit FAIL for a separate corrupt-final classification
defect; minimal correction; Scenario 7's nine checks PASS; targeted re-audit PASS
with Decisions 276-280 all SATISFIED. No journal format or public API changed.
Final automated results, confirmed independently: 25 recovery tests, 39
storage/communication/NATS regressions, and 82 artifact/Controller regressions
passed; full discovery 376 passed, zero failed, and seven optional rendering
skips (383 total). These are prior validation results, not tests run during closure.
Journal cleanup/retention and application-wide restart/discovery remain Q024;
Q019's Session-wide evidence-consumption/finalization guarantee remains OPEN.
Software closure does not validate hardware deployment, real Jetson/SSH-SFTP,
or live JetStream server crash/recovery. M011 remains open; M012 and M013 remain
complete.

Phase 15 / Slice 28 Controller-owned Session Launch and Runtime Assembly is
implemented for the launch path in Decisions 281-301; M015 remains open with
Decision 302 sequential reuse implemented and covered by automated regressions;
independent validation and audit of the correction remain pending.
Controller resolves prospective selections and current readiness,
requests atomic node-owned reservations, constructs final SessionConfig with
unavailable optional selections omitted, and waits for required initialization/
preparation before launch success. RuntimeParticipant identity and AcquisitionNode
declared inventory exist independently of Session. Accepted node reports replace
session_id with reserved_for_session_id, retain complete per-device readiness,
and aggregate required framework/service prerequisites only. DeviceReadiness
no longer carries required; DeviceDeclaration.required governs selected-device
criticality. Missing/invalid current reports mean unknown to Controller, not a
new readiness enum.

Ingestor and SynchronizationManager readiness are mandatory launch prerequisites;
global StorageManager availability is not. Existing local persistence and final
archive-writing responsibilities remain unchanged. Reservations last through
acquisition/local finalization, not later global retrieval. Current direct-object,
caller-created SessionConfig examples retain the historical local workflow.
Automated Slice 28 tests exercise real framework objects and NATS handlers with
controlled broker doubles; they do not constitute live NATS, multi-process,
hardware, or manual IPython validation. No Slice 28 validated workflow or
independent audit completion is claimed; M014/W034 remain complete.
Discovery/configuration, scheduling, crash/stale-reservation recovery, durable
pre-Session launch auditing, retention/deletion, and Q019/Q024 remain deferred.

Accepted distributed initialization clarifies that Session authorizes local
storage creation while each node physically creates its LocalStorageManager
using deployment-local roots, not Controller-selected remote paths. Participants
confirm Session-specific preparation independently of readiness; missing results
are unconfirmed, and node cleanup must be confirmed before failed-launch
reservation release. Node binding remains node-owned and its communication
handler stays connected across binding changes. These contracts are implemented
through Controller.launch_session(), node-owned reserve/initialize/abort/release
operations, and participant-specific preparation handlers. See docs/code_map.md
for signatures. Distributed launch does not accept local_storage_roots;
historical local Session initialization still supports explicit local overrides.

For development/validation, NATS/JetStream and framework participants start
manually in independent processes, potentially on different PCs/Jetsons, and
each connects independently. Intended deployment uses long-lived independent
services; Controller does not manage NATS or launch participant processes.
Required connectivity must succeed before distributed readiness, without
indefinite startup waiting or automatic retry/reconnection policy. Pre-Session
commands use participant identity without fabricated Session IDs; Session
operations require real identities. Service supervision, startup automation,
and duplicate identity policy remain deferred. Decision 313 now defines normal
service Session-binding release after confirmed cleanup/evidence obligations;
that integration is partially implemented in Phase 16 Slice 1. Controller now has
explicit `await release_session()` after confirmed cleanup/final persistence.
Ingestor and SynchronizationManager also support narrow evidence-bearing release
after confirmed archival or durable mapping-evidence handoff, respectively.
Existing records remain intact. M015 remains pending and M014/W034 unchanged.

Decision 302 accepts generic sequential reuse of retained DeviceAdapter instances:
successful shutdown and required cleanup return to DECLARED, failed/unconfirmed
cleanup prohibits reuse, and safely reusable declared adapters participate in
existing pre-Session readiness. AcquisitionNode retains deployment inventory and
configuration; each Session supplies its own Session-specific settings through
resolved SessionConfig. This transition/readiness behavior is implemented with
simulated and broker-double regression coverage; independent manual validation
and audit remain pending. No new reset operation, lifecycle state, or Controller
hardware initialization responsibility is introduced. Previously validated
workflows remain historical evidence, not validation of sequential Session reuse.

Phase 16 Operational Service Lifetime and Framework Stop/Kill architecture is
accepted in Decisions 304-322; Slice 1 binding release is partially implemented
with automated tests, but independent validation and Phase 16 completion are not claimed.
Controller, AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager
have lifetimes independent of Sessions and GUI. They may be idle between runs;
Session-specific objects still follow their existing creation, finalization,
cleanup, and reuse contracts. This does not require one OS process per service
or continuous acquisition, and does not make DeviceManager/DeviceAdapters
independently operating services.

Framework stop is operator-requested scoped orderly closeout, not Session stop.
Controller coordinates existing distributed commands/results; participants own
their actions and shared resources serving unrelated scopes remain protected.
Each request has a durable stop_attempt_id with completed/blocked/failed outcomes
separate from Session lifecycle. Kill is authorized forced continuation only of
the same blocked attempt; declining kill ends it as failed without forced action.
Neither operation initiates artifact collection, verification, transfer, or export,
and normal Session end does not automatically stop operational services. No new
framework-wide lifecycle, service supervisor, GUI control, stop/kill API, or schema
is implemented. Decisions 313-321 settle independent Session-binding release,
general shutdown versus individual administrative maintenance, all-participant
pre-stop evaluation, directional service-owned blockers, and exact forced-action
outcomes. General shutdown preserves evidence in producer -> Ingestor ->
StorageManager -> Controller order; individual service maintenance may use a local
administrative interface without Controller orchestration or remote OS control.
Framework evidence may lack Session identity through minimally extended existing
Ingestor/Evidence Archive infrastructure; current implementation remains
Session-specific. Independent startup and returning-service recognition do not
promise automatic recovery of interrupted work. Q025 is resolved architecturally,
with implementation beyond the limited Decision 313 paths still pending; Q019,
Q021, Q024, and deployment configuration remain open.
Q017 remains resolved.
Existing milestone statuses and validation records are unchanged.

Decision 322 accepts persistence for every ControllerActionDecision, including
no-mutation outcomes, with Controller-supplied is_persistent=True through the
existing Ingestor/StorageManager Evidence Archive pathway. Controller binding
release requires confirmed archival of its Session's decisions, not merely NATS
publication. The narrow Slice 1 follow-up now packages decisions with their plain
payloads, submits them to an attached Ingestor, and confirms exact inclusion in
successfully written archive input before release. The public
`controller_action_decision_evidence` property also supplies the same retained
messages for caller-managed publication through the existing boundary. Late or
missing decisions invalidate release confirmation; successful release retires
temporary decisions, never durable evidence. Decision 313 stays partially
implemented. Evidence-bearing Ingestor release now checks exact archived persistent
messages and all runtime-evidence intake audit against the current intake snapshot,
plus existing terminal Session Record and acquisition-envelope preservation.
Concurrent intake and release commit are serialized; nonpersistent messages remain
nonpersistent. Ingestor holds StorageManager's preservation guard through release
commitment so concurrent archive or final-record writes cannot invalidate its
confirmation. Controller checks its decisions against the current archive, not
only historical finalization, and holds the same guard through its final
synchronous commit after asynchronous unsubscription. No guard is held across
an await; future archive writes are not frozen. SynchronizationManager can release retired mapping state after
Session Time stops and exact journal-backed Ingestor acceptance is confirmed,
without waiting for archival. Both retire temporary state without deleting durable
files. These are narrow implementation paths with automated tests, not independent
validation or audit. Phase 16 remains unvalidated, M015 open, and Q019 unresolved. Session Record
construction now keeps raw runtime evidence and its intake audit in the separate
Evidence Archive, preserving Session context and acquisition-envelope audit in
the Session Record. Local Session start and finalization require an explicit
Controller Ingestor reference; the optional constructor remains available for
brokered orchestration without introducing a node-owned Ingestor fallback.

The existing NATS dispatcher accepts `prepare_experiment_scientific_outputs`
with payload `{"experiment_id": ..., "scientific_outputs": [...]}` using output
selection `to_dict()` values. Use existing `publish_group_command()` and
`await_group_command_outcome()` to collect required remote preparation results,
then pass the correlated outcome to Controller. Accepted/progress results are
not preparation success. This does not introduce remote lifecycle activation.

Preparation rejection returns an unsuccessful command result whose
`details["rejection_evidence"]` is a persistent `RuntimeEvidenceMessage` plain
dictionary. Controller submits it once to its local Ingestor for normal Evidence
Archive finalization, without recording `experiment_start` or `experiment_fail`.
For an independent brokered consumer, reconstruct this same message with
`RuntimeEvidenceMessage.from_dict()` and publish it once through existing
`NatsCommunicationBoundary.publish_evidence()`. Set Controller's keyword-only
`component_id` to match that boundary's source identity. No automatic second
delivery to the same Ingestor, relay, retry, or new rejection-history component
is introduced.

Reproducing the existing Phase 10 brokered runtime demo requires a separate
JetStream-enabled NATS server; this is not a Slice 21 closure requirement:

```text
nats-server -js
python scripts/demo_nats_runtime.py --server nats://127.0.0.1:4222
```



The project follows an architecture-first development process. Architectural decisions are discussed and documented before the corresponding implementation is added to the framework.


---



## Architecture Documents



### Accepted Decisions



See:



```text

docs/architecture\_decisions.md

```



This document contains architectural decisions that have been accepted by the architecture board.



### Open Questions



See:



```text

docs/open\_questions.md

```



This document tracks unresolved architectural questions that must be addressed before implementation begins.



### Local Cross-Process Demo



See:



```text

docs/local_cross_process_demo.md

```



This document explains the live two-shell localhost socket demos, including the basic plain-envelope sender and the OpenCV camera-adapter metadata sender.



---



## Guiding Principles



* The GUI is a client, not the owner of acquisition timing.

* Session time has a single owner.

* Timing information is part of the scientific record.

* Offline reconstruction must be possible from stored records.

* Devices should be modular and interchangeable.

* Configuration should be explicit rather than hidden in implementation defaults.

* Intermediate outputs should remain easy to inspect and debug.



---



## Repository Status



The repository structure, storage model, synchronization model, and device contracts are still under discussion.



No production implementation should be considered stable until the architectural design phase is complete.



