# Lab Sync Acquisition



A modular synchronization and acquisition framework for neuroscience experiments.

Q024 Slice 1 implements Decision 436 Controller claim acquisition/admission and
post-retirement conditional release and is CLOSED within bounded software scope
after independent ICC manual validation and separate Codex audit PASS. See the
[validation and correction record](docs/validated_workflows.md#q024-slice-1---controller-exclusivity-claim-and-operational-admission).
This does not certify fully deployed installation-wide exclusivity.
Direct Controller construction grants no operational authority.
Controller startup requires explicit installation claim settings and an existing
verified persistent JetStream KV bucket; see
[Controller authority](docs/installation_and_deployment.md#controller-claim-implementation-q024-slice-1).
Manual stale-claim recovery and service-side registration/supersession are not
implemented by Slice 1. Package 1 is CLOSED at commit
`994119f6ece36172c28456c51b4b6cd7565c9d8e` after developer testing,
independent ICC live-JetStream validation and independent Codex re-audit PASS; see the
[operator workflow](docs/installation_and_deployment.md#controller-replacement-authority--package-1-implementation).
Q024 remains OPEN pending Package 2 (service-owned disposition and recovery); Decision 435 retirement remains deferred.

Q022-A installation/deployment architecture is accepted in Decisions 367-378.
Its bounded NATS Ingestor-StorageManager persistence foundation is complete with
independent validation and final re-audit PASS after a malformed-correlation
correction (W051). Full deployment implementation remains outstanding. The intended
initial procedure
uses one package, explicit service roles, local service/node configuration outside
Git, explicit known-node registration, and SSH/SFTP plus NATS/readiness installation
checks. Device acquisition smoke tests are recommended, not runtime gates. See
[Installation And Deployment](docs/installation_and_deployment.md) for the accepted
manual procedure and current reusable interfaces/gaps. Q022 remains OPEN.
Decision 376 revises Decision 375: Ingestor and StorageManager share one computer
and process, startup/shutdown/restart lifetime, and permitted local Python calls
while retaining separate ownership. Controller, SynchronizationManager, and nodes
remain independently deployed; every process-crossing interaction uses NATS,
including Controller access to both components. W051 remains historically
validated; bounded local correlated persistence is complete with independent
validation and audit PASS (W052). Decision 377 now requires routine scientific
observations and per-observation metadata to remain in node-local scientific
products regardless of size; Ingestor receives operational evidence and manifests.
W051/W052 remain historically validated, but routine scientific-envelope transport
and persistence are no longer required. Bounded product-based adapter/manager/node
acquisition and operational evidence preservation are complete with independent
manual validation and final re-audit PASS after correction (W053). The initial
audit found lost later-device observations after operational intake failed; the
correction attempts all completed scientific collections first and reports
independent failures without replay. Bounded shared-lifetime launching is closed
in W061; complete deployment bootstrap remains deferred. Future real-time
scientific streaming is architecturally open.
Decision 378 requires clean replacement of legacy collection/scientific-envelope
paths: installation declares supported products, Experiments explicitly select
them, and adapters produce scientific observations/metadata for local storage
separately from operational evidence. W051/W052 history does not mandate obsolete
API compatibility. Slice 3B is complete after independent validation and corrective
re-audit PASS (W054). It removes owner-level scientific-envelope intake,
correlated persistence, exports and demos, and reconciles closeout against
operational evidence/audit and manifests. The initial audit FAIL identified a P2
Normal Stop release/intake race and P3 obsolete test configuration; both were
corrected and independently re-audited with no remaining confirmed P0-P3 findings.
The combined Decision 377-378 implementation is complete and accepted in W055.
The final audit passed functional integration (26 tests and four probes), initially
failed clean replacement for one unused test-fixture setting, and that P3 cleanup
passed nine targeted tests. The user and ICC accepted targeted verification
without another independent re-audit for this test-only correction. Q022 remains OPEN.
Remaining process-crossing direct-owner dependencies still need adaptation before
fully functional independent-role deployment. Historical Q019 validation remains
complete and does not claim this deployment adaptation has been validated.

Decisions 379-381 define the minimum distributed synchronization contract for
Q022 Slice 2: measured cross-clock exchanges establish
node-specific mappings; AcquisitionNode applies authorized affine mappings
locally with preserved timing and activation-boundary provenance. Synchronization
readiness and configurable periodic quality checks remain distinct from complete
resynchronization; temporary degradation is recorded and governed by existing
policy/Controller authority. No per-observation network timestamp requests or
assumed shared clocks are authorized. Advanced Q006/Q018 work remains open.

Slice 2 now implements measured NATS synchronization, local affine timestamping
with activation provenance/degraded status, and launched Experiment context and
finalization. Supply explicit `SynchronizationConfiguration` values through
`SessionConfig.synchronization_configuration`; remote nodes name their timing
authority with `synchronization_source_id`, without a shared clock object.
Developer testing includes separate processes against local JetStream, not
hardware or multi-host validation. Independent validation and final audit PASS
close this bounded slice in W056; Q022 remains OPEN. See the implementation boundary and public entry points in
[Installation And Deployment](docs/installation_and_deployment.md#timing-and-synchronization).

Q022 Slice 3 is CLOSED in W057 after independent IPython validation and audit
PASS of 880b108. AcquisitionNode operational evidence and manifests use durable
Session-specific NATS intake with identity checks, journal/fsync-before-ACK,
deduplication, restart recovery and exact journal-backed acceptance readback.
Scientific observations remain node-local. Publication, acceptance, complete
receipt and archival preservation are distinct; publication or acceptance does
not authorize artifact release. Subject consistency is not authentication, and
optional callbacks are not a durable retry queue. Multi-host, hardware and
power-loss guarantees remain unverified; broader Q022 deployment integration
remains OPEN. See [W057](docs/validated_workflows.md#w057---acquisitionnode-to-ingestor-durable-operational-evidence-over-nats).

Q022 Slice 4 is CLOSED in
[W058](docs/validated_workflows.md#w058---controller-remote-saved-session-collection-over-nats):
Controller can explicitly collect one saved Session through NATS without local
Ingestor/StorageManager references. StorageManager retains eligibility, collection
and persistence authority. All three replay/result-correlation P2 findings are
resolved; independent validation and final audit PASS of d788d2e confirm bounded
retry/restart behavior. Local JetStream used separate processes and simulated SFTP.
Distributed closeout and independent release are closed separately in W060;
remote enumeration/batch selection, configuration/launching and broader deployment
remain outstanding. Q022 stays OPEN.

Q022 Slice 5 is CLOSED in
[W059](docs/validated_workflows.md#w059---controller-remote-saved-session-evidence-archive-closure-over-nats):
Controller can explicitly request permanent closure of one saved Evidence Archive
over NATS. StorageManager retains closure authority and current durable readback;
closure neither terminates Sessions nor releases services or scientific artifacts.
The cached-success history-validation P2 was corrected, independently validated
and passed focused audit of 31b2c7e. Corrective automated runtime attempts stalled
inside the sandbox without results; no correction test passes are claimed.
Multi-host, hardware/SFTP and power-loss validation remain unestablished.

Distributed Session closeout is CLOSED in
[W060](docs/validated_workflows.md#w060---distributed-session-closeout-and-independent-release-over-nats):
Normal Stop/Kill, finalized acquisition intake, verified Stage A, restart
reconciliation and independent service release are implemented, independently
validated and audited. Controller alone owns lifecycle completion; preservation
does not authorize hardware/resource release. Audits confirmed the three original
P2 corrections and the non-idempotent unsubscribe retry correction. Final
nats-py 2.16.0 cancellation probes found no reproducible defect; live task-level
verification was blocked by Windows asyncio startup. Q022 remains OPEN.



## Overview

### Manual Service Launcher (W061-W063 Closed)

`lab-sync-acquisition --help` (or `python -m lab_sync_acquisition.service_launcher --help`)
lists the five logical roles. W061 supplies the required shared `ingestor` /
`storage-manager` process with explicit settings and operational dependencies.
W063 closes the three independent launch paths with remote producer-specific
preservation and node installation loading after independent IPython validation
(60/60) and independent architectural audit PASS with no confirmed P0-P3 findings.
No hidden service owners are created. Ctrl+C uses existing local Stop/Cancel, never
implicit Kill; remote retirement waits for final result publication/handling.
See [launcher usage and limitations](docs/installation_and_deployment.md#common-launcher-w061-closed)
and [W061](docs/validated_workflows.md#w061---common-service-launcher-and-local-graceful-shutdown).
W061 is CLOSED after independent IPython validation (22/22) and focused re-audit
PASS following two P2 corrections. No live JetStream, actual OS signal-delivery,
hardware or full five-role deployment validation is claimed. Q022 remains OPEN.

See [independent role startup](docs/installation_and_deployment.md#independent-role-startup-w063-closed)
for required identities, known-node registration, dependency settings, supported
adapter configuration and the remaining deployment limitations.

Remote addressed maintenance is CLOSED in W062 after independent validation and
focused re-audit PASS: `lab-sync-acquisition stop|kill|cancel` uses explicit servers,
target type/identity, administrator and result window. Kill additionally requires
the blocked stop-attempt ID and explicit authorization; Cancel uses that attempt
without force. No Controller is required and no extra service is launched.
Cancel retains its existing failed/cancelled result and nonzero exit code.
Interrupted authorized Kill warns of possible execution, not revocation or
confirmed retirement. See [remote maintenance usage](docs/installation_and_deployment.md#remote-service-maintenance-w062-closed)
and [W062](docs/validated_workflows.md#w062---remote-service-maintenance-cli) for the
41/41 then 42/42 validation and initial FAIL/correction/final PASS history.
No live JetStream, real OS-signal, hardware or full deployment validation is
claimed for W062 or W063. W063 is CLOSED within the documented scope; Q022
remains OPEN for configuration/provisioning, installation verification and
remaining deployment/integration work. See
[W063](docs/validated_workflows.md#w063---independent-service-launch-paths-and-distributed-retirement-preservation)
for validation evidence and the distinction between controlled coroutine checks
and normal asynchronous execution.

W064 adds explicit `--deployment-config PATH` service-file input to the same
launchers, with separate node hardware configuration and local retrieval settings.
See [service-file usage](docs/installation_and_deployment.md#deployment-local-service-files-w064-closed)
and `config_templates/`. W064 is CLOSED after independent IPython validation and
architectural audit PASS. Shared-storage file launches still require an explicit
no-external-dependents declaration; actual dependents need their existing
maintenance callbacks. This is not installation provisioning or complete
deployment verification; Q022 remains OPEN. See
[W064](docs/validated_workflows.md#w064---deployment-local-configuration-and-service-startup-integration).

W065 adds an explicit `lab-sync-acquisition verify-retrieval` installation check
using the StorageManager service file, a configured node, a remote dummy file and
independent local expected bytes. See
[retrieval verification](docs/installation_and_deployment.md#installation-retrieval-check-w065-closed).
W065 is CLOSED after independent IPython validation and audit PASS; simulated
SSH/SFTP checks do not establish live installation or hardware readiness. Q022
remains OPEN for remaining installation and deployment work.

W066 adds `lab-sync-acquisition verify-node --deployment-config PATH --node-id NODE_ID`
using the Controller service file and existing NATS readiness request/response.
It checks only the selected registered node, without launching a Controller or
changing scientific operation. A current response can confirm communication even
when hardware is unready. See
[node communication verification](docs/installation_and_deployment.md#installation-node-communication-check-w066-closed).
W067 integrates an operator-run [manual installation runbook](docs/installation_and_deployment.md#manual-installation-runbook-w067-closed)
and [typed local-file examples](config_templates/manual_installation/README.md).
It is CLOSED after independent 4/4 validation and architectural audit PASS, with
no installer or complete distributed-deployment claim:
W068 is CLOSED after independent manual validation and final audit PASS, covering
explicit external-dependent callback composition, instance/attempt-correlated
confirmation and ordinary archive continuation under Decisions 389/390, including
the corrected P2 maintenance-write bypass. Configure `external_dependents` and `result_window_s`
in the shared storage file; never substitute a false no-dependents declaration.
The runbook alone is not physical deployment verification.
W066 is CLOSED after independent validation and final re-audit PASS, including both
NATS cleanup P2 corrections. Verification used simulated I/O, not live NATS, real
sockets, hardware or OS signals. Q022 remains OPEN for applicable manual
installation/provisioning integration and remaining accepted deployment work.



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
synthetic NumPy frames. `DeviceManager.collect_products()` returns source-identified
`DeviceCollectionResult` objects with selected `scientific_products` and separate
`operational_evidence`; the camera's scientific rows retain the original `frame`
array, frame index and available metadata locally. Empty product selection does
not acquire scientific observations. Neither DeviceAdapter nor
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

G2 is CLOSED within its software-validated scope under Decisions 394-395.
Experiment starts now require explicit `ExperimentConfiguration` with duration
and confirmed recording/preservation capacity; nodes enforce the common deadline
autonomously. See [capacity and duration usage](docs/installation_and_deployment.md#experiment-capacity-and-duration-g2-closed)
and the [G2 validation record](docs/validated_workflows.md#g2---experiment-capacity-preflight-and-autonomous-duration-expiry)
for failure/retry behavior and live-deployment/hardware limitations. Runtime
duration extension remains deferred; Q022, Q024, M015 and Phase 16 remain OPEN.

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
The historical Slice 22 Controller completion API is retired under Decision 419.
Ingestor compilation and StorageManager durable handoff readback expose
session_id and artifacts entries containing artifact_manifest and
missing_finalization_evidence without completing a Session. Slice 22
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
the historical direct-owner sequence, now retired under Decision 419. Supported
completion uses `await Controller.normal_stop_session(...)` on a launched NATS
Session with scientific cleanup, complete acquisition intake and verified Stage A
preservation, followed by `await Controller.release_session(communication=...,
result_window_s=...)` after confirmed closeout. Later collection is separate.
Local development acquisition does not provide Controller Session completion
or binding release. Publication failures use the existing
DurablePublicationError/command-result path. Copied size comes from the temporary
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
Q019's evidence-consumption/final archive coordination is complete in W041-W050.
M011 remains open pending real Jetson/SSH-SFTP
deployment validation, and M012 remains complete. W033 records Slice 25's software
validation, not live NATS or real Jetson/SSH-SFTP deployment validation. The legacy
unconfigured synchronous collection path remains supported.

Accepted Q019 Decisions 356-365 now qualify that historical routing/finalization
model. Decision 361's Ingestor-side receiving foundation and JetStream routing
prerequisite are complete with automated testing, independent manual IPython
validation, and final independent re-audit PASS after both corrections (W041).
Validation used local NATS/software, not an external cluster, multi-host, Jetson,
or hardware deployment. W048 Kill is complete with independent manual validation and final re-audit PASS after corrections. Decision 362's
explicit Stage A slice is complete with developer automated testing, independent
manual validation, and independent audit PASS (W043); bounded Stage B collection
and Decision 363 evidence persistence are complete with independent manual
validation and final targeted independent re-audit PASS after correction (W045),
while W046 explicit permanent closure is complete with independent manual validation
and targeted independent re-audit PASS after correction. Decision 365's bounded
Normal Stop integration is complete after correction and independent re-audit PASS
(W047); W048 Kill is complete with independent validation and final re-audit PASS after corrections;
Decision 364's bounded durable handoff is complete
with automated testing, independent manual validation, and independent audit PASS (W044).
Session evidence uses a durable explicit-ACK receiving position and journal-before-
server-confirmed-ACK acceptance. Receipt readback verifies an existing completion
marker against journal acceptance, retained stream-origin history, and contiguous
broker progress, reconciling Session-matching publications with the current retained
journal using canonical, type-sensitive contents. It does not certify producer
confirmations, successful Normal Stop, Session completion, or archive preservation.
Missing/truncated history or unknown original receiving state remains unconfirmed.
Accepted Decision 366 resolves producer scope without new confirmation messages:
participating AcquisitionNodes must durably publish applicable evidence before
their existing successful acquisition-completion responses, even with optional
selected devices; unused optional devices add no obligation. Controller and
SynchronizationManager finish applicable closing-Session evidence publication
before the single marker, without service-wide shutdown or publication barriers.
Ingestor-owned locally journaled evidence needs no JetStream round trip and remains
included in compilation/persistence. The supported publication prerequisite is
complete with automated coverage, independent manual validation, and targeted
independent re-audit PASS after the concurrent manifest/health cursor correction
(W042). The marker is not the Stop command and is not proof of archival or
Session completion.
The accepted future closeout flow remains: required acquisition-stage producers
confirm durable publication before Controller publishes one Session-scoped
completion marker. Ingestor must independently verify earlier required durable
acceptance using restart-safe Session-specific receiving progress and verified
contiguous JetStream acknowledgment coverage of the full relevant publication
interval; marker receipt or isolated ACKs are insufficient. Confirmed Stage A writes
acquisition evidence, intake audit, summary, and final Session Record, satisfying
acquisition-side completion and applicable binding-release obligations before
scientific collection. StorageManager durably preserves the existing handoff for
later operator-selected stopped-Session collection without restoring original
bindings, using a separate small Session-associated JSON handoff in the existing
Session directory and existing persistent Session information for selection.
In Stage B it directly appends its own persistent collection evidence
to the same archive, distinguishes origins in the summary without fabricated
Ingestor audit, and confirms durability. Permanent closure requires a separate
explicit operator request, not automatic closure after collection. All applicable
collection outcomes must be durably recorded, with no unresolved evidence writes,
and StorageManager must verify archive consistency and durable preservation.
Closure does not require every artifact to be retrieved or verified; once closed,
the archive is immutable, including after restart. Closure does not rewrite
acquisition evidence, audit, final Session Record, or acquisition outcome, and
remains distinct from collection outcomes, evidence preservation, and Session lifecycle.
The existing summary records Stage A completion versus permanent Stage B closure;
status alone is not durability proof. Before direct archival, StorageManager
temporarily durably preserves the actual collection outcome and unique evidence ID.
Duplicate protection and verified archival permit safe temporary retirement and
authorized evidence-write recovery without repeating scientific-file transfer.

Kill Session preservation is exposed through `Controller.kill_session(*, communication,
result_window_s, operator_authorized, reason=None)`. It records `experiment_abort`
and local Session abortion, reports participant cleanup uncertainty separately,
retains reservations, and does not initiate collection or permanent closure.
`PersistentStorageManager.refresh_partial_artifact_collection_handoff(session_id,
*, ingestor)` accepts additional verified manifests from existing authorized
recovery only before collection starts, preserving historical evidence and the
final record. W048 is independently validated and audited PASS after corrections.

Separately authorized Kill Session preserves accessible evidence/files, partial
Session Record, unresolved conditions, and safety where possible. It neither
automatically collects artifacts nor permanently closes the partial archive;
killed Sessions remain eligible for later collection, without a new lifecycle
state. Normal Stop requires complete producer, durable acceptance, and Stage A
confirmations. Kill identifies partial preservation when completeness is unavailable;
that confirms only preserved content, not acquisition success or safe resource
release. Unknown outcomes remain unconfirmed. The low-level contracts are accepted,
but Q019 is CLOSED following overall software integration validation (W050); eligible-Session selection is complete in W049. The receiving
proof has linear history-read cost and requires intact global stream history from
sequence 1; losing unrelated older history can block confirmation.
Q019 is **CLOSED** for the supported evidence-closeout and collection software
scope (W050). W041-W049 are complete; overall independent manual validation 2/2
PASS and final independent integration audit PASS found no confirmed P0-P3
production defects. Permanent regression coverage now includes two successive
Normal Stop Sessions with scientific output; its developer integration run passed
3/3 tests. Broker/SFTP infrastructure is simulated, with no demonstrated live
hardware, multi-host/external deployment, or power-loss guarantees. Q022, Q024,
Phase 16, and M015 remain open under their existing separate criteria.

W049 saved-Session selection is complete with independent manual validation and
final independent audit PASS after correcting single-Session eligibility bypass
and fixture cleanup. StorageManager lists candidates with separate eligibility,
availability, and reasons; Controller independently collects selected Sessions
and reports individual outcomes plus complete success, partial success, or failure.
The validation is software/fixture-based, not hardware, deployment, or power-loss
verification. W049 records the full failed-audit/correction history.
No exact new filenames, fields, or APIs are
defined here. W033/M013, W035, W039, and W040
remain complete for their historical scopes; Q024, Q022, Phase 16, and M015 remain
OPEN. NWB conversion and Cheaha upload remain later scientific processing stages.

After existing brokered acquisition stop/cleanup, explicitly call
`await controller.publish_acquisition_evidence_completion(communication=communication,
result_window_s=5.0)`. Its ControllerCommandResult exposes `details["marker"]` and
`details["publication_confirmed"]` on success. It requires correlated successful
node completion results and one configured synchronization participant. Pending
health inputs or missing/failed publication prevent the marker. Repeated confirmed
calls reuse the same boundary; interrupted calls retain its identity for explicit
retry, with no background retries. Independently use Ingestor's existing receipt
verification; marker publication does not complete the Session or write an archive.

The next explicit operation is
`await controller.archive_acquisition_evidence(communication=ingestor_communication)`.
It requires the matching Ingestor receiving adapter, verifies durable receipt of
the confirmed marker using W041, and protects journal/intake coverage while
StorageManager writes the existing Evidence Archive and `session_record_final.json`.
The summary records Stage A completion, marker identity/sequence, and Ingestor
evidence provenance with `archive_closed=False`. Confirmation requires current
product/record readback, not the flag alone. Failed or uncertain writes are not
successful Stage A; interrupted persistence remains subject to existing authorized
recovery. The operation leaves the Session stopping and does not release bindings,
retrieve artifacts, write the durable handoff, or implement Stage B/Normal Stop/Kill.
This bounded slice is complete with 16 focused developer tests passed, independent
manual IPython validation 17/17 PASS using local real JetStream, and independent
audit PASS with no confirmed P0-P3 defects (W043). Remaining Q019 work was subsequently completed in W044-W050;
W041/W042 remain complete and unchanged.

After confirmed Stage A, explicitly call
`controller.preserve_artifact_collection_handoff()` to durably preserve Ingestor's
existing compilation at `session_<session_id>/artifact_collection_handoff.json`.
The separate JSON retains complete manifests and missing-finalization flags;
it neither contains scientific bytes nor establishes collection success.
`storage.read_artifact_collection_handoff(session_id)` validates the saved handoff
after restart without original Controller/Ingestor/AcquisitionNode bindings.
Publication is non-overwriting, with fsync/readback confirmation; identical retries
reconfirm durability, while corrupt or conflicting existing files are refused.
Applicable Q019 binding release requires current handoff coverage. This bounded
slice is complete with 24 focused developer tests passed, independent manual
IPython validation 17/17 PASS, and independent audit PASS with no confirmed P0-P3
defects (W044). It does not change W041-W043, complete/release the Session, select eligible Sessions,
perform Stage B collection, or close the archive. Q019 is CLOSED following overall software integration validation (W050).

The bounded W045 Stage B implementation is complete with developer automated
testing, independent manual validation, and final targeted independent re-audit
PASS after correction. Given the
same explicit `storage_root` directory, logical StorageManager `component_id`, configured
`global_artifact_root`, and node-keyed SSH endpoints, it needs no old Session binding:

```python
from uuid import uuid4

attempt_id = uuid4().hex  # Retain this unique identity for readback/repeated requests.
result = controller.collect_saved_session_artifacts(session_id, evidence_id=attempt_id)
details = result.details
```

The synchronous StorageManager entry point is
`storage.collect_saved_artifacts(session_id, evidence_id=attempt_id)`;
`storage.get_persisted_session_preservation_confirmation(session_id)` checks
persisted products without cached Stage A snapshots, reconfirming file and supported
directory durability without changing bytes (existing products require owner
read/write access for fsync). Collection result, temporary
outcome durability, archival confirmation, and preservation warning remain separate
in returned details. StorageManager appends its own evidence directly and updates
summary provenance without JetStream or fabricated intake audit; the archive stays
OPEN and existing scientific sources, Stage A evidence, audit, and final record are
unchanged. Reusing a confirmed ID reads its result without another transfer;
pending evidence never triggers automatic refetch or repair.

W045 preserves the full validation history: 32 initial developer tests passed,
initial independent IPython validation 9/9 PASS, initial source audit FAIL with
two P2 findings, 14 correction tests passed, independent correction validation
3/3 PASS, and final targeted re-audit PASS with no remaining confirmed P0-P3 defects.
The corrections prevent missing/inconsistent provenance from authorizing archive
replacement and reject cross-Session envelopes or incomplete intake audit as a
trusted Stage A baseline. These are prior results, not new tests during closure.

Interrupted evidence writes use the existing ServiceMaintenanceInterface:
record a new explicit `resume` decision for `recover_archive_write` tied to its
command ID and `obligation={"session_id": session_id, "evidence_id": attempt_id}`,
then execute that correlated command. Existing framework journal-backed
authorization and attempt acceptance remain required, including after restart;
original Session intake is unnecessary. Recovery completes only a trustworthy
matching temporary outcome/append and summary. Invalid baselines or conflicting
bytes are refused. If a crash precedes outcome durability, missing outcomes are
not reconstructed from artifact existence; only still-retained live outcomes can
be preserved. Known-Session lookup is not application-wide discovery. Filesystem
hard-link/fsync prerequisites still apply, and power-loss behavior is unvalidated.
W046 now exposes the separate explicit operator entry point
`storage.close_session_evidence_archive(session_id)`. It returns `archive_closed=True`,
`archival_confirmed=True`, the Session identity, and product paths only after current
durability and consistency checks. Failed retrieval, failed verification, and durably
recorded unknown collection outcomes need not prevent closure; unresolved writes or
unconfirmed products do. It updates only the existing compilation summary, preserving
all other products. No artifact collection call invokes closure automatically.
Repeated requests, including after restart, reconfirm existing closed contents without
rewriting. An interrupted publication or fsync/readback raises rather than reporting
success; explicit retry can reconfirm safely, never reopen a closed archive or refetch
artifacts. Archive writes, generic managed final-record writes, handoff writes, and
authorized archive/record recovery cannot mutate closed products.
W046 is complete: initial developer tests 27/27 and independent IPython validation
8/8 PASS; initial audit FAIL with one P2 final-record path-alias bypass; correction
tests 6/6 and independent correction validation 2/2 PASS; targeted independent
re-audit PASS with no remaining confirmed P0-P3 findings. The guard now resolves
the complete target and storage root before identifying the managed final record.
These are prior validation results, not new tests during documentation closure.
Bounded W047 Normal Stop integration is complete with independent manual validation
and targeted independent re-audit PASS after correction. Initial developer tests
19/19 and independent IPython checks 6/6 passed; the initial audit found two P2
defects. Corrections passed 12/12 developer tests and 3/3 independent checks; final
re-audit found no remaining confirmed P0-P3 findings. The retained Q019 association
prevents cancellation from enabling legacy completion, and current operational evidence/audits
must match the durable final record before completion. For a launched Session, call
`await controller.normal_stop_session(communication=controller_communication,
receiving=ingestor_communication, result_window_s=...)`. The existing launch window
bounds node shutdown requests; the supplied window bounds producer closeout requests.
It composes node cleanup/publication, the W042 marker, W041 receipt verification,
Stage A persistence, and the durable artifact handoff before Session completion.
Current journal/archive/handoff coverage remains protected through completion.
It never automatically collects artifacts, closes the archive, or releases retained
service bindings. Existing explicit binding release preserves the terminal Session
Record; later Stage B uses the saved handoff. Uncertain receipt or preservation
cannot confirm Normal Stop; unsafe persistence still requires authorized recovery.
Q019 is CLOSED following overall software integration validation (W050); eligible-Session selection is complete in W049. W041-W044, Q024, Q022,
Phase 16, and M015 statuses are unchanged.

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
Q019's supported Session-wide evidence-consumption/finalization integration is
complete, with consolidated independent validation and audit PASS (W050).
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

Historical development/validation starts participants manually. Under Decision
376, intended deployment uses one combined Ingestor-StorageManager process and
independent Controller, SynchronizationManager, and node processes, potentially
on different PCs/Jetsons. Controller does not manage NATS or launch processes.
Required connectivity must succeed before distributed readiness, without
indefinite startup waiting or automatic retry/reconnection policy. Pre-Session
commands use participant identity without fabricated Session IDs; Session
operations require real identities. Service supervision, startup automation,
and duplicate identity policy remain deferred. Decision 313 now defines normal
service Session-binding release after confirmed cleanup/evidence obligations;
the narrow Phase 16 Session-binding release slice is now complete, manually
software-validated, and independently audited PASS (W035). Controller has
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
Slice 28 workflows remain historical evidence, not closure of its sequential-reuse
requirements. W035 separately validates the Phase 16 service binding-release path.

Phase 16 Operational Service Lifetime and Framework Stop/Kill architecture is
accepted in Decisions 304-365. The narrow Controller/Ingestor/SynchronizationManager
Session-binding release slice under Decisions 313 and 322 is complete, manually
software-validated, and independently audited PASS (W035). Remaining Phase 16
responsibilities are unfinished; Phase 16 completion is not claimed.
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
framework-wide lifecycle, service supervisor, or GUI control is implemented.
Individual-service stop/kill/cancel now has a target-owned administrative interface
and existing NATS command/result entry points. This narrow implementation slice is
complete, manually software-validated, and independently audited PASS (W036),
including Decision 324 closeout ordering and the authorized-kill evidence correction.
This does not claim hardware or live external NATS deployment validation.
Decisions 313-321 settle independent Session-binding release,
general shutdown versus individual administrative maintenance, all-participant
pre-stop evaluation, directional service-owned blockers, and exact forced-action
outcomes. Decision 325 supersedes the all-or-nothing global precheck: an
informational local survey precedes progressive dependency-safe stops, using
explicit Session-independent participant scope and separate authorization for
each blocked service. Already stopped services remain stopped; coordinated
shutdown is implemented, manually software-validated, and independently re-audited
PASS (W037). General shutdown preserves evidence in
producer -> Ingestor -> StorageManager -> Controller order; individual service maintenance may use a local
administrative interface without Controller orchestration or remote OS control.
Decision 326 accepts preparatory StorageManager and Controller cleanup with durable
evidence preservation before Ingestor retirement. Retirement order is unchanged;
later confirmations remain command results, not newly archived evidence. The
validated sequence is informational survey; AcquisitionNode and SynchronizationManager
stops; StorageManager then Controller preparation and archival confirmation;
Ingestor retirement; StorageManager retirement; Controller retirement. Prepared
orderly retirement requires complete current Evidence Archive coverage of the final
persistent runtime evidence and all intake audit, including rejected, duplicate,
and nonpersistent-message intake. Missing coverage, including loss during an
asynchronous retirement callback, prevents confirmed retirement and completed
shutdown. W037 records the independent preservation-guard re-audit PASS, 174 focused
tests passed, and 574 full-suite tests run (567 passed, 7 optional rendering skips,
zero failures). These are preceding validation results, not new tests run during
documentation closure or hardware/live external NATS validation.
Framework evidence may lack Session identity through minimally extended existing
Ingestor/Evidence Archive infrastructure. Decision 323's `framework/evidence/`
partition now supports journal-backed framework intake and exact archive/audit/
summary confirmation without a Session Record. Independent startup and returning-service recognition do not
promise automatic recovery of interrupted work. Q025 is resolved architecturally,
with coordinated shutdown validated in W037 and independent startup/returning-service
integration under Decisions 327-331 complete, independently manually software-validated,
and independently re-audited PASS after correction of two P2 readiness findings
(W038). This is controlled software/broker-double validation, not live external
NATS deployment or hardware validation. Phase 16 remains open. These contracts reuse identity,
readiness, configured-dependency announcements, and framework evidence without a
registry, recovery subsystem, or new persistence mechanism. Recording administrator
resume/drop decisions alone does not execute recovery; supported explicitly
authorized Q024-B actions are separately validated in W039. Q019,
Q021, Q024, and deployment configuration remain open.
Q017 remains resolved.
M015 remains open with its separate launch/reuse validation criteria; historical
validation records are preserved.

The supported Q024-B service-specific recovery and reconciliation slice under
Decisions 339-348 is complete, independently manually validated, and independently
re-audited PASS after correction (W039). Existing service owners support exact
obligation-scoped administrator authorization, trusted Evidence Archive/retained
Session Record rewrites, fresh non-overwriting artifact transfers, independent
local scientific-artifact preservation and device cleanup, informational Controller
outcome reconciliation, and historical synchronization/continuity reporting.
Durable Ingestor acceptance precedes operational recovery; actual actions,
remaining obligations, and subsequent archival confirmation remain separate.
Retained finalized-manifest evidence can be resubmitted on a newly authorized
attempt without repeating scientific finalization; required durable acceptance
must be confirmed before reporting complete artifact recovery.

Initial independent manual validation passed 22 checks. The initial independent
source audit failed on one P2 Controller reconciliation defect involving optional
and non-mapping command details. Its correction preserves unassociated uncertainty
without inventing Session identity or participant completion. Focused independent
revalidation passed 16 checks; the final independent re-audit returned PASS and
independently passed 20 relevant automated tests. Final implementation testing:
656 run, 649 passed, 7 optional skips, zero failures. These are prior software
results, not live external NATS, cross-process, Jetson, or hardware validation.

Ingestor's existing automatic known-Session valid-journal reconstruction is unchanged.
No universal recovery system, new automatic replay, application restoration,
new Session states, active-Session clock restoration, or new evidence infrastructure
is introduced. Decision 336 remains partial: only guarded release of redundant
producer-owned evidence copies. Broader Q024 remains OPEN, including journal
retention/deletion, abandoned journals, application-wide discovery/restoration,
stale reservations, and remaining memory/cache retirement. Q019, Q022, Phase 16,
and M015 remain OPEN; W035-W038 retain their historical validation records.

Additional Q024 architecture is accepted in Decisions 349-355. Supported startup
reconciliation under Decisions 351-352 is complete, independently manually validated
and independently re-audited PASS after correction (W040). Bounded Decision 349/393
retirement is CLOSED in W070B; Decision 354 has bounded monthly implementation
independently validated/reviewed and CLOSED in W071, while Decisions 350 and 353/355 remain
unimplemented. The architecture assigns conditional temporary-journal
retirement to Ingestor,
permits explicitly informed terminal deletion of identified unrecoverable temporary
evidence, requires Controller startup reconciliation of observable known participants,
protects node-owned reservations after Controller failure, and extends service-owned
temporary-memory retirement without sacrificing safety or deduplication.
It does not automatically restore Session objects or stop safe active acquisition.

`NatsServiceMaintenanceCommunication.start()` now automatically obtains Controller
participant observations. Supply explicit `startup_participants` using existing
`RuntimeParticipant` identities, or reuse configured dependencies, with an explicit
positive `startup_result_window_s` for nonempty scopes. The returned
`reconciliation` separates each node's active/stopped/failed/unknown condition,
Session-keyed reservation, local finalization, manifest acceptance, and cleanup.
No omitted participant is discovered, no Session is restored, and no acquisition
or release command is executed. A bare Controller constructor is not a deployment
startup; subsequent authorized preservation/cleanup remains separate.

W040 preserves the initial failed source audit (P2 unsafe archive repair and P3
malformed optional diagnostics), both corrections, and the final independent PASS.
Initial manual validation passed 28/28 checks; correction revalidation passed 25/25.
Codex's corrected full suite ran 676 tests: 669 passed, 7 optional rendering skips,
zero failures. The final independent re-audit passed 132 focused tests and two
probes; two negative controls reproduced the original defects. Startup/readiness
leaves unconfirmed archives untouched with retained/journal-accepted evidence where
possible and preservation
warnings; malformed optional collections cannot prevent other observations.
This is software/broker-double validation, not hardware, live external NATS,
cross-process, or Jetson validation. Broader Phase 16 and M015 remain OPEN.

Decision 354 supersedes Decision 323's shared permanent framework archive layout
with `<storage_root>/framework/evidence/YYYY-MM/`, using the existing evidence,
intake-audit, and compilation-summary files. Bounded monthly implementation now
assigns new evidence/audit using StorageManager's system clock at archival write
time with UTC month boundaries; older partitions are not rewritten and existing
shared-layout history stays read-only. Cumulative confirmation and existing
journals preserve cross-month identities and recovery information. The bounded
slice is CLOSED in W071 after 59 distinct Codex checks, independent ICC IPython
validation (6/6 PASS) and implementation/source review PASS with no confirmed
P0-P3 findings. See validated_workflows.md for limitations; no live NATS, hardware,
OS-signal, physical power-loss or normal Windows asynchronous scheduling validation
is claimed. Monthly partitioning does not rotate temporary journals, alter
Session archives/scientific artifacts, or change historical timestamps.
Decision 355 distinguishes immutable finalized archives from archives confirmed
safe to delete: deletion must not affect later operation or recovery. Permanent
archives are never automatically deleted. Cross-month confirmation/maintenance
deletion independence, unavailable-evidence auditing and memory limits remain
outstanding; no archive is declared safe to delete by this slice. Incomplete
historical writes fail closed rather than being implicitly repaired or reassigned.
No replacement recovery infrastructure is chosen.
Q024-B/W039 completion is unchanged. Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

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
temporary decisions, never durable evidence. The audited release slice under
Decisions 313 and 322 is complete. Evidence-bearing Ingestor release checks exact archived persistent
messages and all runtime-evidence intake audit against the current intake snapshot,
plus existing terminal Session Record and manifest preservation.
Concurrent intake and release commit are serialized; nonpersistent messages remain
nonpersistent. Ingestor holds StorageManager's preservation guard through release
commitment so concurrent archive or final-record writes cannot invalidate its
confirmation. Controller checks its decisions against the current archive, not
only historical finalization, and holds the same guard through its final
synchronous commit after asynchronous unsubscription. No guard is held across
an await; future archive writes are not frozen. Controller checks captured Session
object identity after every unsubscription await and before retirement; stale
operations cannot alter a newer binding, decisions, subscriptions, command history,
or last-release status. SynchronizationManager can release retired mapping state after
Session Time stops and exact journal-backed Ingestor acceptance is confirmed,
without waiting for archival. Both retire temporary state without deleting durable
files. W035 records manual IPython validation, independent audit PASS with no blocking
defects or architectural ambiguities, 152 passing focused tests, and full discovery
of 493 tests (486 passed, 7 optional rendering skips, zero failures). Independent
negative controls reproduced the concurrency defect with identity checks disabled.
These are previously executed software validations, not real hardware or external
NATS deployment validation. Phase 16 remains incomplete, M015 open, and Q019/Q024
unresolved. Session Record
construction now keeps raw runtime evidence and its intake audit in the separate
Evidence Archive, preserving Session context without obsolete scientific-envelope intake in
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

## Development Workflow

Contributors and coding agents must follow [AGENTS.md](AGENTS.md) for mandatory
repository engineering instructions. See
[Architecture Chat Development Workflow](docs/architecture_chat_workflow.md) for
the complete role boundaries, explicit user architectural acceptance rules, and
implementation, independent validation, audit, and closure sequence.


---



## Architecture Documents



### Accepted Decisions



See:



```text

docs/architecture\_decisions.md

```



This document records accepted architectural decisions. Only the user can
explicitly accept new architecture; existing formally recorded accepted decisions
remain authoritative.



### Open Questions



See:



```text

docs/open\_questions.md

```



This document tracks unresolved architectural questions. Questions required by a
particular implementation slice must be resolved and accepted before that slice
begins; deferred future work is not an implementation requirement.



### Local Cross-Process Demo



See:



```text

docs/local_cross_process_demo.md

```



This historical record describes retired two-shell socket demonstrations; its
recorded outcomes remain, but the scientific-envelope demos are no longer runnable.



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



