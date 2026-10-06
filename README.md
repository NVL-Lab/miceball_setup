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
and two-step persistent Session Record finalization.

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
Ingestor-accepted durable runtime evidence and its intake audit.

Phase 10 is implemented through the accepted brokered Control Plane boundary,
including configured group-command fan-out, issuer-owned result aggregation,
and unresolved missing-response evidence. Recovery policy and the pull-based
Artifact Plane backend remain intentionally deferred.

The readiness, publication-failure, independent Controller/Ingestor evidence
consumption, artifact-manifest, and Core NATS telemetry paths have also been
manually validated against a real local JetStream broker.

Phase 12 Local Storage and Session Record architecture is accepted in
Decisions 178-218. Its first implementation slice now provides the co-located
`LocalStorageManager` core for readiness, incremental JSONL scientific streams,
authoritative local artifact manifests, local storage evidence, flush,
finalization, and local completion summaries. Slice 20.3 implements Session,
Controller, and AcquisitionNode integration for explicitly selected scientific
products. Global collection, transfer, reconstruction, and export remain future
slices.

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
a blocking hardware read can overrun it. This script has simulated test coverage;
Jetson hardware validation is still pending and Slice 20 is not declared closed.
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

The corrective changes await manual validation and a targeted follow-up audit.
Real-camera HDF5 validation and Slice 20 closure are not claimed.

Reproducing the manual runtime validation requires a separate
JetStream-enabled NATS server:

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



