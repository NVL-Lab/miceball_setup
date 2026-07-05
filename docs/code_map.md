# Code Map

## src/lab_sync_acquisition/__init__.py

- AcquisitionHealthPolicy: Public import for immutable plain-data acquisition-health policy definitions and observation-vocabulary validation.
- AcquisitionIterationSummary: Public import for the result of one bounded AcquisitionNode iteration.
- AcquisitionNode: Public import for bounded acquisition runtime execution, active Experiment runtime mapping as the sole health-policy assignment path, configured batching, writable failure-evidence readiness, and sender-side failure handling.
- AcquisitionNodeReadiness: Public import for Phase 2 node identity and aggregated device/service readiness evidence.
- AcquisitionRecordEnvelope: Public import for the transferable acquisition record envelope shared across the acquisition-to-ingestion boundary.
- Controller: Public import for sequential single-session orchestration using already-created runtime collaborators.
- ControllerCommandResult: Public import for one Controller command outcome.
- DeviceAdapter: Public import for the minimum live runtime control interface for one device adapter.
- DeviceAdapterLifecycleError: Public import for invalid live adapter lifecycle operations.
- DeviceAdapterState: Public import for minimum live adapter lifecycle states.
- DeviceDeclaration: Public import for persistent/config declarations of intended session devices.
- DeviceLifecycleResult: Public import for per-adapter Device Manager lifecycle call results.
- DeviceManager: Public import for coordinating already-created live Device Adapters.
- DeviceRecordCollection: Public import for records collected by DeviceManager from one already-created adapter.
- DeviceReadiness: Public import for the shared readiness record produced by DeviceManager and consumed by Session.
- DeviceReadinessNotImplementedError: Public import for base adapters without concrete readiness behavior.
- DeviceReadinessSummary: Public import for aggregated Device Manager readiness results.
- ExpectedParticipant: Public import for a plain-data declaration of expected contribution during one Experiment.
- ExperimentDescriptor: Public import for the persistent scientific identity of one Experiment within a Session.
- ExperimentLifecycleEvidence: Public import for canonical Session-owned Experiment start/stop evidence.
- ExperimentRuntimeHealthMapping: Public import for one explicit live-source Experiment health assignment as plain runtime data.
- ExperimentScopedHealthObservation: Public import for an evidence-only Experiment health condition detected by AcquisitionNode.
- DeviceStatus: Public import for live adapter status snapshots.
- IngestAuditRecord: Public import for ingest audit evidence recorded for each received acquisition envelope.
- InMemoryIngestor: Public import for the minimal in-memory envelope receiver that can forward accepted envelopes to storage.
- InMemoryStorageManager: Public import for the minimal in-memory acquisition envelope storage boundary.
- PersistentStorageManager: Public import for the v1 persistent StorageManager implementation that stores accepted envelopes as JSONL.
- LifecycleTransition: Public import for recorded lifecycle transitions.
- OpenCVCameraConfig: Public import for explicit OpenCV camera initialization and polling configuration.
- ReadinessCheck: Public import for recorded readiness checks.
- Session: Public import for the runtime session lifecycle model.
- SessionConfig: Public import for the immutable accepted run configuration, including its explicit error evidence location, owned by a Session and preserved as part of the Session Record.
- SeeedIMX219OpenCVCameraAdapter: Public import for the concrete OpenCV-backed metadata-only adapter for a Seeed IMX219 camera.
- SessionLifecycleError: Public import for lifecycle operation failures.
- SessionState: Public import for accepted Phase 1 session lifecycle states.
- ServiceReadiness: Public import for readiness records produced by framework services and consumed by Session initialization.
- SynchronizationManager: Public import for the minimal Phase 1 Session Time owner.

## src/lab_sync_acquisition/acquisition_node_readiness.py

- AcquisitionNodeReadiness: Holds explicit node, session, and role identity while aggregating existing device and service readiness evidence.

## src/lab_sync_acquisition/acquisition_health.py

- AcquisitionHealthPolicy: Stores explicit evaluation parameters and observation-to-consequence-label vocabulary, supports plain-data round trips, and validates interpretation keys against supplied supported observations without executing policy.

## src/lab_sync_acquisition/acquisition_record.py

- AcquisitionRecordEnvelope: Holds the minimal transferable acquisition record message fields, including optional source node identity, and supports JSON-like plain-data round trips.

## src/lab_sync_acquisition/acquisition_node.py

- AcquisitionIterationSummary: Records the small inspectable summary returned by one bounded acquisition iteration.
- AcquisitionNode: Owns bounded acquisition runtime execution, scopes health evaluation to its active Experiment mapping, and exposes evidence-only ExperimentScopedHealthObservation records without assigning consequences.

## src/lab_sync_acquisition/device.py

- DeviceDeclaration: Holds persistent Session participation intent and immutable capabilities without acquisition-health policy assignment.

## src/lab_sync_acquisition/controller.py

- ControllerCommandResult: Records one command outcome and exposes its command, success, details, and error as plain evidence.
- Controller: Sequentially coordinates one Session, activates and clears the active Experiment runtime health mapping on AcquisitionNode without persisting or evaluating it, creates Experiment descriptors and canonical lifecycle evidence, handles runtime failure outcomes and cleanup, and performs two-step Session Record finalization.

## src/lab_sync_acquisition/device_adapter.py

- DeviceAdapterState: Enumerates the minimum lifecycle states for a live device adapter.
- DeviceReadiness: Records device readiness fields shared by DeviceManager and Session and exposes them as plain data for Session Record evidence.
- DeviceStatus: Reports the current live adapter lifecycle status without scientific data.
- DeviceAdapterLifecycleError: Signals invalid live adapter lifecycle operations.
- DeviceReadinessNotImplementedError: Signals that a live adapter has no concrete readiness implementation.
- DeviceAdapter: Provides the minimum live runtime control interface for one device adapter with externally read-only lifecycle state, explicit required participation metadata, and a concrete-adapter record exposure hook for DeviceManager collection.

## src/lab_sync_acquisition/device_manager.py

- DeviceLifecycleResult: Records the result of one Device Manager lifecycle call against one adapter.
- DeviceRecordCollection: Records the source device identity, record kind, and unmodified records collected from one already-created adapter.
- DeviceReadinessSummary: Aggregates shared readiness records across already-created adapters and can be passed to Session initialization.
- DeviceManager: Holds at least one already-created Device Adapter and coordinates lifecycle, readiness, status, and minimal acquisition record collection without creating adapters or envelopes.

## src/lab_sync_acquisition/experiment_runtime.py

- ExperimentRuntimeHealthMapping: Records one immutable live-source-to-Expected-Participant mapping and the authoritative Experiment-scoped acquisition-health policy assignment, with plain-data round trips but no evaluation behavior.
- ExperimentScopedHealthObservation: Records an Experiment-scoped health condition, source and participant identity, policy context, Session Time, and audit details as plain evidence without operational consequence.

## src/lab_sync_acquisition/ingestor.py

- IngestAuditRecord: Records ingest order, receive time, accepted status, and reason for one received acquisition envelope and exposes audit evidence as plain data.
- InMemoryIngestor: Receives AcquisitionRecordEnvelope objects in memory, reports service readiness, records separate ingest audit evidence, and optionally forwards accepted envelopes to in-memory or persistent storage without mutating rows.

## src/lab_sync_acquisition/service_readiness.py

- ServiceReadiness: Holds the shared framework-service readiness fields consumed by Session initialization and exposes them as plain data for Session Record evidence.

## src/lab_sync_acquisition/opencv_camera.py

- OpenCVCameraConfig: Holds explicit OpenCV camera source, backend, frame polling count, and optional requested capture properties.
- SeeedIMX219OpenCVCameraAdapter: Opens a Seeed IMX219-compatible OpenCV camera, reports readiness, reduces polled frames to metadata-only records, and releases the capture during shutdown.

## src/lab_sync_acquisition/storage.py

- InMemoryStorageManager: Reports service readiness, stores accepted AcquisitionRecordEnvelope objects in memory, and exposes all, session-filtered, and source-filtered readback without file writing or transformation.
- PersistentStorageManager: Reports service readiness, stores accepted envelopes, and writes/reads a v1 Session Record including Experiment descriptors and canonical Experiment lifecycle evidence.

## src/lab_sync_acquisition/synchronization.py

- SynchronizationManager: Owns the minimal Phase 1 session clock, reports synchronization service readiness, starts Session Time at 0.0 seconds, exposes current Session Time, and can freeze final timing state.

## src/lab_sync_acquisition/session.py

- SessionState: Enumerates the accepted Phase 1 session lifecycle states.
- SessionConfig: Holds the immutable accepted run configuration, including the explicit Session error evidence location, and exposes it as plain data for the persistent Session Record.
- ReadinessCheck: Records the result of a readiness condition checked during lifecycle transitions and exposes it as plain data for Session Record evidence.
- LifecycleTransition: Records an allowed lifecycle state transition in sequence order and exposes it as plain data for Session Record evidence.
- ExpectedParticipant: Records participant identity, type, expected contribution, and required status as an inert plain-data declaration.
- ExperimentDescriptor: Records the persistent scientific identity, caller-supplied details, and ordered Expected Participants of one Experiment as plain Session Record data.
- ExperimentLifecycleEvidence: Records canonical `experiment_start` or `experiment_stop` evidence in the Session timeline as plain data.
- SessionLifecycleError: Signals invalid lifecycle operations or failed readiness requirements.
- Session: Owns lifecycle, readiness, Experiment descriptors, canonical Experiment lifecycle evidence, cleanup status, and final status in memory.

## scripts/demo_cross_process_acquisition_writer.py

- main: Writes demo plain-data AcquisitionRecordEnvelope dictionaries to a local JSONL handoff file.

## scripts/demo_cross_process_ingestor_reader.py

- main: Reads demo handoff envelope dictionaries, reconstructs AcquisitionRecordEnvelope objects, sends them to InMemoryIngestor, and persists accepted envelopes through PersistentStorageManager.

## scripts/demo_continuous_batched_stream.py

- main: Runs deterministic count- and Session-Time-age-triggered continuous fake-stream scenarios through AcquisitionNode and persistent JSONL storage.

## scripts/demo_socket_acquisition_sender.py

- main: Sends demo newline-delimited AcquisitionRecordEnvelope dictionaries to a localhost receiver over a disposable socket demo boundary.

## scripts/demo_socket_opencv_camera_sender.py

- main: Runs the OpenCV camera adapter with default fake input or explicit real cv2 through DeviceManager and AcquisitionNode, then sends metadata-only envelopes over the disposable localhost socket demo boundary.

## scripts/demo_socket_ingestor_receiver.py

- main: Receives demo newline-delimited envelope dictionaries over localhost, reconstructs AcquisitionRecordEnvelope objects, sends them to InMemoryIngestor, and persists accepted envelopes through PersistentStorageManager.

## scripts/demo_remote_acquisition_node_sender.py

- main: Runs one identified simulated remote AcquisitionNode session over the provisional socket and writes demo-local JSONL failure evidence before a nonzero exit when connection or sending fails.

## scripts/manual_opencv_camera_smoke.py

- main: Runs one optional bounded metadata-only AcquisitionNode iteration against a real OpenCV camera and releases the camera without writing image or video files.
