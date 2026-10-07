# Code Map

## src/lab_sync_acquisition/__init__.py

- AcquisitionHealthPolicy: Public import for immutable plain-data acquisition-health policy definitions and observation-vocabulary validation.
- ActiveExperimentRuntimeContext: Public import for immutable runtime-only Experiment identity and start Session Time supplied to AcquisitionNode.
- AcquisitionNodeLocalTimeReport: Public import for immutable plain local-time samples reported to SynchronizationManager without becoming synchronization evidence.
- AcquisitionIterationSummary: Public import for the result of one bounded AcquisitionNode iteration.
- AcquisitionNode: Public import for bounded acquisition runtime execution, AcquisitionNode-owned runtime timestamping, separate active Experiment timing and health context, linked observation/interpretation evidence, configured batching, writable failure-evidence readiness, and sender-side failure handling.
- AcquisitionNodeReadiness: Public import for Phase 2 node identity and aggregated device/service readiness evidence.
- AcquisitionRecordEnvelope: Public import for the transferable acquisition record envelope shared across the acquisition-to-ingestion boundary.
- ARTIFACT_MANIFEST_EVIDENCE_TYPE: Public evidence-type vocabulary for artifact lifecycle manifests carried through RuntimeEvidenceMessage and LAB_EVIDENCE.
- Controller: Public import for sequential single-session orchestration using already-created runtime collaborators.
- ControllerActionDecision: Public import for one immutable Controller decision using the normalized local execution vocabulary and derived from explicitly presented HealthInterpretationEvidence.
- ControllerCommandResult: Public import for one Controller command outcome.
- COMMAND_RESULT_STATUSES: Public immutable vocabulary of accepted runtime command-result statuses.
- DeviceAdapter: Public import for the minimum live runtime control interface for one device adapter.
- DeviceAdapterLifecycleError: Public import for invalid live adapter lifecycle operations.
- DeviceAdapterState: Public import for minimum live adapter lifecycle states.
- DeviceDeclaration: Public import for persistent/config declarations of intended session devices.
- ScientificProductDeclaration: Public import for immutable available-product declarations containing schema, storage format, and optional known size/rate and storage requirements.
- ScientificOutputSelection: Public import for immutable Experiment selections referencing source device, AcquisitionNode, and declared product identities without format overrides.
- DeviceLifecycleResult: Public import for per-adapter Device Manager lifecycle call results.
- DeviceManager: Public import for coordinating already-created live Device Adapters.
- DeviceRecordCollection: Public import for records collected by DeviceManager from one already-created adapter.
- DeviceReadiness: Public import for the shared readiness record produced by DeviceManager and consumed by Session.
- DeviceReadinessNotImplementedError: Public import for base adapters without concrete readiness behavior.
- DeviceReadinessSummary: Public import for aggregated Device Manager readiness results.
- ExpectedParticipant: Public import for a plain-data declaration of expected contribution during one Experiment.
- ExperimentDescriptor: Public import for the persistent scientific identity of one Experiment within a Session.
- ExperimentLifecycleEvidence: Public import for canonical Session-owned Experiment start, normal-stop, and failure evidence.
- ExperimentRuntimeHealthMapping: Public import for one explicit live-source Experiment health assignment as plain runtime data.
- ExperimentScopedHealthObservation: Public import for an identified evidence-only Experiment health condition detected by AcquisitionNode.
- HealthInterpretationEvidence: Public import for immutable plain-data evidence explicitly linked to the Health Observation interpreted by AcquisitionHealthPolicy without executing framework action.
- LAB_COMMANDS: Public JetStream subject filter for durable runtime commands.
- LAB_COMMAND_RESULTS: Public JetStream subject filter for durable runtime command results.
- LAB_EVIDENCE: Public JetStream subject filter for durable runtime evidence.
- MESSAGE_CLASSES: Public immutable vocabulary of runtime message classes.
- MAPPING_UPDATE_EVIDENCE_TYPE: Public evidence-type vocabulary for MappingUpdateEvidence carried through RuntimeEvidenceMessage.
- MappingUpdateEvidence: Public import for immutable SynchronizationManager-owned active mapping lifecycle evidence.
- RUNTIME_CONTROL_COMMAND_RESULT_STATUSES: Public immutable final-status subset used by Phase 10 runtime-control commands.
- RuntimeCommandMessage: Public immutable plain-data runtime command message.
- RuntimeCommandResultMessage: Public immutable plain-data runtime command-result message.
- RuntimeEvidenceMessage: Public immutable plain-data durable evidence message carrying producer-supplied persistence intent.
- RuntimeParticipant: Public immutable SessionConfig declaration of one expected runtime component identity.
- UnresolvedCommandOutcome: Public immutable issuer evidence that one expected command target did not return a result within the issuer-defined window.
- GroupCommandOutcome: Public immutable issuer-owned aggregate of returned command results and unresolved expected targets for one component group.
- RuntimeTelemetryMessage: Public immutable plain-data transient telemetry message.
- DeviceStatus: Public import for live adapter status snapshots.
- DurablePublicationError: Public import for explicit durable publication failure context without buffering or retry behavior.
- IngestAuditRecord: Public import for ingest audit evidence recorded for each received acquisition envelope.
- InMemoryIngestor: Public import for the minimal in-memory envelope receiver that can forward accepted envelopes to storage.
- RuntimeEvidenceAuditRecord: Public import for one Ingestor audit record associated with durable runtime evidence intake.
- NatsCommunicationBoundary: Public import for real NATS connection, JetStream stream setup, message serialization, publication, subscription, and transport acknowledgement mechanics.
- NatsControllerCommunication: Public import for Controller-side durable command publication and command-result consumption.
- NatsAcquisitionNodeCommunication: Public import for targeted AcquisitionNode command consumption, local duplicate detection, explicit command execution, command-result publication, and runtime evidence publication.
- NatsIngestorCommunication: Public import for durable runtime evidence consumption into the existing Ingestor ownership boundary.
- InMemoryStorageManager: Public import for the minimal in-memory acquisition envelope storage boundary.
- PersistentStorageManager: Public import for the v1 persistent StorageManager implementation that stores accepted envelopes as JSONL and writes caller-supplied Session Record and Evidence Archive products.
- LifecycleTransition: Public import for recorded lifecycle transitions.
- OpenCVCameraConfig: Public import for explicit OpenCV camera initialization and polling configuration.
- ReadinessCheck: Public import for recorded readiness checks.
- Session: Public import for the runtime session lifecycle model.
- SessionConfig: Public import for the immutable accepted run configuration, including Session-scoped AcquisitionHealthPolicy definitions and its explicit error evidence location, owned by a Session and preserved as part of the Session Record.
- SeeedIMX219OpenCVCameraAdapter: Public import for the concrete OpenCV-backed Seeed IMX219 adapter with metadata-only default collection and explicit local scientific-frame collection.
- SessionLifecycleError: Public import for lifecycle operation failures.
- SessionState: Public import for accepted Phase 1 session lifecycle states.
- ServiceReadiness: Public import for readiness records produced by framework services and consumed by Session initialization.
- SynchronizationManager: Public import for the minimal Phase 1 Session Time owner.
- SynchronizationMapping: Public import for one immutable SynchronizationManager-owned local-to-Session timing relationship.
- build_runtime_subject: Public helper that constructs one concrete Session-scoped runtime routing subject.
- build_group_command_messages: Public helper that fans one command intent out to configured members of one component group.
- aggregate_group_command_results: Public issuer-side helper that combines per-target results and records absent expected targets as unresolved.
- parse_runtime_subject: Public helper that parses one concrete runtime routing subject into plain routing fields.

## src/lab_sync_acquisition/communication.py

- ARTIFACT_MANIFEST_EVIDENCE_TYPE: Identifies artifact-level lifecycle manifests as durable runtime evidence without defining transfer or storage schemas.
- MAPPING_UPDATE_EVIDENCE_TYPE: Identifies MappingUpdateEvidence carried as durable runtime evidence without changing timing ownership.
- RuntimeParticipant: Stores one expected runtime component type and identifier as plain Session configuration data.
- UnresolvedCommandOutcome: Stores inspectable plain-data evidence for one expected target whose command result was absent from the issuer-defined result window.
- GroupCommandOutcome: Stores the issuer-owned aggregate outcome, individual results, and unresolved target evidence for one group command intent.
- RuntimeCommandMessage: Stores one immutable plain-data command intent with explicit source, target, Session, command identity, type, and payload.
- RuntimeCommandResultMessage: Stores one immutable plain-data command result and validates its shared status vocabulary.
- RuntimeEvidenceMessage: Stores one immutable plain-data durable evidence message plus producer-supplied persistence intent without interpreting its domain meaning.
- RuntimeTelemetryMessage: Stores one immutable plain-data transient telemetry message without making it authoritative evidence.
- build_runtime_subject: Builds the accepted message-rooted, Session-scoped routing subject and validates its message class and concrete tokens.
- parse_runtime_subject: Parses an accepted concrete routing subject into plain routing fields.
- build_group_command_messages: Creates one targeted RuntimeCommandMessage per configured participant in an explicitly selected component group.
- aggregate_group_command_results: Computes the issuer-owned group outcome without broker or target-side aggregation and keeps missing results unresolved rather than failed.
- MESSAGE_CLASSES: Lists the accepted command, command-result, evidence, and telemetry message classes.
- COMMAND_RESULT_STATUSES: Lists the shared accepted, progress, succeeded, and failed status vocabulary.
- RUNTIME_CONTROL_COMMAND_RESULT_STATUSES: Lists the succeeded and failed subset for Phase 10 runtime-control commands.
- LAB_COMMANDS: Defines the durable command stream subject filter `messages.*.command.>`.
- LAB_COMMAND_RESULTS: Defines the durable command-result stream subject filter `messages.*.command_result.>`.
- LAB_EVIDENCE: Defines the durable evidence stream subject filter `messages.*.evidence.>`; telemetry intentionally has no JetStream filter constant.

## src/lab_sync_acquisition/acquisition_node_readiness.py

- AcquisitionNodeReadiness: Holds explicit node, session, and role identity while aggregating existing device and service readiness evidence.

## src/lab_sync_acquisition/acquisition_health.py

- AcquisitionHealthPolicy: Stores named rule-specific evaluation substructures and observation-to-interpretation vocabulary, supports plain-data round trips, and validates interpretation keys against supplied supported observations.
- HealthInterpretationEvidence: Records the assigned policy's interpretation of one explicitly referenced Experiment-scoped Health Observation as immutable plain data without executing framework action.

## src/lab_sync_acquisition/acquisition_record.py

- AcquisitionRecordEnvelope: Holds the minimal transferable acquisition record message fields, including optional source node identity, and supports JSON-like plain-data round trips.

## src/lab_sync_acquisition/acquisition_node.py

- AcquisitionIterationSummary: Records the small inspectable summary returned by one bounded acquisition iteration.
- AcquisitionNode: Owns bounded acquisition runtime execution and timestamping, stores separate active Experiment timing and health context, and emits explicitly linked ExperimentScopedHealthObservation and HealthInterpretationEvidence records without executing framework actions.
- AcquisitionNode.activate_experiment_runtime_context: Stores immutable active Experiment identity and start Session Time for Experiment Time derivation without owning lifecycle evidence.
- AcquisitionNode.clear_experiment_runtime_context: Clears active Experiment timing context without stopping Acquisition Runtime or changing health mapping.
- AcquisitionNode.receive_active_synchronization_mapping: Passively replaces AcquisitionNode's stored reference to the SynchronizationManager-owned active mapping without applying mapping mathematics.
- AcquisitionNode.default_local_storage_root: Exposes the explicitly configured persistent root without mutation by Session overrides.
- AcquisitionNode.node_id: Exposes the configured AcquisitionNode identity used by scientific output selections.
- AcquisitionNode.local_storage_manager: Exposes the Session-attached local persistence collaborator without transferring persistence ownership.
- AcquisitionNode.attach_local_storage_manager: Attaches one Session-created LocalStorageManager and device declarations after checking Session/node identity and preventing manager replacement.
- AcquisitionNode.prepare_experiment_scientific_outputs: Returns existing ServiceReadiness evidence after resolving explicit products and requesting one empty local stream per Experiment/device/product, reusing open preparations and preserving/finalizing newly created partial artifacts on failure.
- AcquisitionNode.scientific_output_storage_ids: Returns a readback copy of Experiment/device/product associations with LocalStorageManager runtime write handles.
- AcquisitionNode.finalize_experiment_scientific_outputs: Retires the Experiment's runtime identity and attempts LocalStorageManager finalization of every associated stream, returning finalized manifests or raising an error containing all failures without affecting other Experiments.
- AcquisitionNode.stop_runtime: Stops devices through existing runtime cleanup and attempts finalization of all prepared scientific artifacts, clearing Experiment timing and health context and reporting persistence failures.
- AcquisitionNode.run_one_iteration: Collects selected scientific devices once, timestamps and persists scientific records, sends only lightweight runtime metadata, and attempts to preserve completed partial collections before propagating collection failure through the existing cleanup path.
- AcquisitionNode._persist_scientific_collection: Resolves product and active context, validates product-scoped one-to-one frame/metadata associations for a whole collection before appending, and shares framework timing without transporting frames.
- AcquisitionNode._send_runtime_collection: Applies existing runtime timestamping, health observation, batching, and envelope handoff to one completed lightweight collection.
- AcquisitionNode._preserve_partial_scientific_collections: Attempts local persistence and metadata handoff for completed partial collections, retaining both acquisition and preservation errors when preservation fails.

Scientific camera timestamps are assigned per record after collection by
AcquisitionNode, not precise hardware exposure timestamps. Available
device-native timing remains separate and unchanged; unknown values are not
fabricated. Existing timestamped records retain their timing, and conflicting
scientific/runtime timing is rejected rather than silently rewritten.

## src/lab_sync_acquisition/device.py

- ScientificProductDeclaration: Holds available scientific product identity, type, complete plain-data schema, declared storage format, and optional known characteristics with `to_dict()`/`from_dict()` round trips.
- DeviceDeclaration: Holds persistent Session participation intent, immutable capabilities, and ordered scientific product declarations with unique per-device product identities, without acquisition-health policy assignment.
- DeviceDeclaration.from_dict: Reconstructs device declarations and their scientific products, treating absent products in older representations as an empty collection.

## src/lab_sync_acquisition/controller.py

Slice 21 implementation note (Decision 239): the preparation gate produces
persistent rejection evidence through existing Ingestor intake, with the same
message available in failed command-result details for explicit publication to
independent brokered consumers through caller-managed orchestration. Slice 21
is complete; W030 records manual validation, focused tests, and audit reassessment.

- ControllerCommandResult: Records one command outcome and exposes its command, success, details, and error as plain evidence.
- ControllerActionDecision: Records one health-derived Controller decision with Session, Experiment, source, policy, interpretation, and originating-observation provenance using the normalized local decision vocabulary.
- Controller: Sequentially coordinates one Session with optional keyword-only `component_id="controller"` for producer identity, preserves existing ownership, and orchestrates preparation, lifecycle, runtime cleanup, and final persistence.
- Controller.start_experiment: Accepts keyword-only `scientific_outputs=()`, `preparation_readiness=()`, and `preparation_outcomes=()`, gates start on required readiness and correlated final remote successes, and reports preparation rejection once as persistent runtime evidence in failed result details without lifecycle activation.
- Controller._record_failed_command: Records an unsuccessful command with optional plain diagnostic details, including the produced rejection message for a pre-start preparation failure.
- Controller.stop_experiment: Records canonical normal-stop evidence, clears active runtime context and health mapping, and requests finalization of only that Experiment's streams without stopping the Session or acquisition runtime.
- Controller.execute_controller_action_decision: Executes accepted no-mutation or failure decisions, finalizing Experiment streams for `experiment_fail` and retaining the existing failed-Session cleanup path for `session_fail`.
- Controller.stop_session: Stops runtime and scientific persistence, records normal-stop evidence for any active Experiment, and then stops the Session through its existing lifecycle.
- Controller.initialize_session: Coordinates existing Session initialization with its AcquisitionNode collaborator so Session creates or reuses local storage and records its readiness.

## src/lab_sync_acquisition/device_adapter.py

- DeviceAdapterState: Enumerates the minimum lifecycle states for a live device adapter.
- DeviceReadiness: Records device readiness fields shared by DeviceManager and Session and exposes them as plain data for Session Record evidence.
- DeviceStatus: Reports the current live adapter lifecycle status without scientific data.
- DeviceAdapterLifecycleError: Signals invalid live adapter lifecycle operations.
- DeviceReadinessNotImplementedError: Signals that a live adapter has no concrete readiness implementation.
- DeviceAdapter: Provides the minimum live runtime control interface for one device adapter with externally read-only lifecycle state, explicit required participation metadata, and a concrete-adapter record exposure hook for DeviceManager collection.
- DeviceAdapter.collect_scientific_records: Explicitly collects separate local scientific and lightweight runtime records, defaulting to one existing `collect_records()` call with no scientific data for unchanged adapters.
- _PartialScientificCollectionError: Internal failure carrier retaining a camera's completed scientific/runtime records alongside its original collection exception.

## src/lab_sync_acquisition/device_manager.py

- DeviceLifecycleResult: Records the result of one Device Manager lifecycle call against one adapter.
- DeviceRecordCollection: Records the source device identity, record kind, and unmodified records collected from one already-created adapter.
- DeviceCollectionResult: Holds separate `runtime_records` and optional local-only `scientific_records` DeviceRecordCollections without creating envelopes or transport messages.
- DeviceReadinessSummary: Aggregates shared readiness records across already-created adapters and can be passed to Session initialization.
- DeviceManager: Holds at least one already-created Device Adapter and coordinates lifecycle, readiness, status, and minimal acquisition record collection without creating adapters or envelopes.
- DeviceManager.collect_scientific_records: Collects each adapter once with optional keyword-only `scientific_source_device_ids=None`, keeping unselected adapters metadata-only and retaining completed results in an internal failure carrier if a later collection raises.
- _PartialDeviceCollectionError: Internal failure carrier retaining completed source-identified device collections and the original collection exception for AcquisitionNode preservation.
- DeviceManager._scientific_collection_result: Converts one adapter's separate scientific/runtime collections into source-identified DeviceCollectionResults without assigning framework timing.

## src/lab_sync_acquisition/experiment_runtime.py

- ActiveExperimentRuntimeContext: Stores immutable runtime-only Experiment identity and canonical start Session Time with a plain-data round trip.
- ExperimentRuntimeHealthMapping: Records one immutable live-source-to-Expected-Participant mapping and the authoritative Experiment-scoped acquisition-health policy assignment, with plain-data round trips but no evaluation behavior.
- ExperimentScopedHealthObservation: Records a runtime-unique observation identity, Experiment-scoped health condition, source and participant identity, policy context, Session Time, and audit details as plain evidence without operational consequence.

## src/lab_sync_acquisition/ingestor.py

- IngestAuditRecord: Records ingest order, receive time, accepted status, and reason for one received acquisition envelope and exposes audit evidence as plain data.
- InMemoryIngestor: Receives AcquisitionRecordEnvelope objects and RuntimeEvidenceMessage objects in memory, reports service readiness, records separate ingest audit evidence, compiles persistent runtime evidence by message flag, and optionally forwards accepted envelopes to storage without mutating rows.
- RuntimeEvidenceAuditRecord: Records intake order, receive time, evidence identity, acceptance, and reason for one durable RuntimeEvidenceMessage.
- InMemoryIngestor.receive_runtime_evidence: Accepts and audits durable runtime evidence separately from acquisition-envelope intake.
- InMemoryIngestor.compile_persistent_runtime_evidence: Returns accepted runtime evidence marked persistent plus runtime-evidence intake audit without inferring persistence from evidence meaning.

## src/lab_sync_acquisition/nats_communication.py

- DurablePublicationError: Reports failed JetStream publication with message class, message identity, subject, intended stream, and reason while leaving the original message caller-owned.
- NatsCommunicationBoundary: Owns a real nats-py connection, reports NATS availability through ServiceReadiness, creates accepted JetStream streams, and handles JSON serialization, durable publication acknowledgement, and Core NATS telemetry mechanics without domain semantics.
- NatsControllerCommunication: Publishes unicast or issuer-fanned group commands, consumes and aggregates addressed per-target command results over an issuer-defined window, records missing results as unresolved, and independently presents HealthInterpretationEvidence without relaying evidence.
- NatsAcquisitionNodeCommunication: Consumes targeted readiness, scientific-output preparation, or runtime commands, deduplicates by command_id, and publishes explicit outcomes without owning Experiment lifecycle.
- NatsAcquisitionNodeCommunication.execute_command: Executes `prepare_experiment_scientific_outputs` through the existing node API with explicit Experiment/product identities and returns readiness diagnostics in the existing correlated final command result.
- NatsIngestorCommunication: Consumes durable RuntimeEvidenceMessage records and passes them to InMemoryIngestor for separate evidence intake and audit.

## src/lab_sync_acquisition/service_readiness.py

- ServiceReadiness: Holds the shared framework-service readiness fields consumed by Session initialization and exposes them as plain data for Session Record evidence.

## src/lab_sync_acquisition/opencv_camera.py

- OpenCVCameraConfig: Holds explicit OpenCV camera source, backend, frame polling count, and optional requested capture properties.
- SeeedIMX219OpenCVCameraAdapter: Opens an OpenCV camera, reports readiness, provides metadata-only default collection or explicit local frame-preserving collection, and releases the capture during shutdown.
- SeeedIMX219OpenCVCameraAdapter.collect_scientific_records: Returns actual NumPy frames and separate metadata from the same reads, omits unavailable optional SDK metadata without failing acquisition, and preserves completed partial records if a later read raises without assigning framework timing or retrying reads.

## src/lab_sync_acquisition/storage.py

- InMemoryStorageManager: Reports service readiness, stores accepted AcquisitionRecordEnvelope objects in memory, and exposes all, session-filtered, and source-filtered readback without file writing or transformation.
- PersistentStorageManager: Reports service readiness, stores accepted envelopes, and writes/reads v1 Session Record and Phase 13 Evidence Archive products from caller-supplied evidence.
- PersistentStorageManager.write_initial_session_record: Writes caller-supplied initial Session Record evidence to `session_<session_id>/session_record_initial.json`.
- PersistentStorageManager.write_evidence_archive: Writes compiled persistent runtime evidence, runtime-evidence audit, and compilation summary to the accepted Phase 13 Evidence Archive files.
- PersistentStorageManager.write_final_session_record: Writes caller-supplied final Session Record evidence to `session_<session_id>/session_record_final.json`.

## src/lab_sync_acquisition/synchronization.py

- SynchronizationMapping: Stores the accepted immutable local-to-Session mapping fields with a plain-data round trip.
- AcquisitionNodeLocalTimeReport: Stores one immutable AcquisitionNode local-time report as plain data without representing SynchronizationObservation evidence.
- MappingUpdateEvidence: Stores immutable created, replaced, or retired mapping evidence with optional previous/new mappings and a plain-data round trip.
- MappingUpdateEvidence.to_runtime_evidence_message: Wraps mapping update plain data in the existing RuntimeEvidenceMessage boundary using evidence type `mapping_update_evidence`.
- SynchronizationManager: Owns the Session clock plus per-AcquisitionNode active mapping creation, replacement, retirement, lookup, and in-memory mapping-update evidence without implementing mapping mathematics or drift estimation.
- SynchronizationManager.create_and_activate_mapping: Creates and atomically activates one initial immutable mapping for an AcquisitionNode.
- SynchronizationManager.replace_active_mapping: Atomically replaces one active mapping and records replacement evidence.
- SynchronizationManager.retire_active_mapping: Retires one active mapping and records retirement evidence.
- SynchronizationManager.get_active_mapping: Returns the currently active mapping for one Session and AcquisitionNode.

## src/lab_sync_acquisition/session.py

- SessionState: Enumerates the accepted Phase 1 session lifecycle states.
- SessionConfig: Holds the immutable accepted run configuration, including expected runtime participants, error evidence location, and optional `local_storage_roots` node-ID-to-root overrides, and exposes it as plain Session Record data.
- ReadinessCheck: Records the result of a readiness condition checked during lifecycle transitions and exposes it as plain data for Session Record evidence.
- LifecycleTransition: Records an allowed lifecycle state transition in sequence order and exposes it as plain data for Session Record evidence.
- ExpectedParticipant: Records participant identity, type, expected contribution, and required status as an inert plain-data declaration.
- ScientificOutputSelection: References `source_device_id`, `source_node_id`, and `data_product_id` with plain-data round trips, without duplicating schema or storage requirements.
- ExperimentDescriptor: Records persistent Experiment identity, details, ordered Expected Participants, and unique ordered scientific output selections through plain-data round trips, without resolving selections against live devices.
- Session.ensure_experiment_descriptor: Creates one descriptor with keyword-only `scientific_outputs=()` or returns the existing descriptor, rejecting conflicting nonempty selections rather than silently discarding them.
- ExperimentLifecycleEvidence: Records canonical `experiment_start`, `experiment_stop`, or `experiment_fail` evidence in the Session timeline as plain data.
- SessionLifecycleError: Signals invalid lifecycle operations or failed readiness requirements.
- Session: Owns lifecycle, readiness, Experiment descriptors, canonical Experiment lifecycle evidence, cleanup status, and final status in memory.
- Session.initialize: Accepts keyword-only `acquisition_nodes=()` and creates or reuses one LocalStorageManager per supplied Session/node, honoring Session root overrides ahead of unchanged node defaults and gating initialization on existing service readiness.
- Session.record_service_readiness: Preserves preparation/service results in the existing Session-owned readiness evidence without introducing another readiness mechanism.
- Session.check_experiment_can_start: Checks canonical lifecycle evidence and rejects terminal Experiment identity reuse, including metadata-only executions.
- Session.record_experiment_lifecycle: Records canonical Experiment lifecycle evidence and applies the terminal-identity check to every `experiment_start`, including direct callers.

## src/lab_sync_acquisition/local_storage.py

- ArtifactManifest: Immutable plain-data authoritative local discovery record for one LocalStorageManager-owned scientific artifact.
- LocalStorageEvidence: Immutable plain-data evidence for local stream, manifest, write, finalization, and cleanup operations.
- LocalStorageCompletionSummary: Immutable plain-data summary of local finalization without implying global Session Record completion.
- LocalStorageManager: Owns explicitly selected JSONL or fixed-shape HDF5 incremental local stream persistence with bounded buffering, append-time flush intervals, manifests, evidence, readiness, cleanup, and finalization for one Session and co-located AcquisitionNode.
- LocalStorageManager.check_ready: Verifies that the configured local persistence root is writable using the shared ServiceReadiness contract.
- LocalStorageManager.create_stream: Creates one scientific stream and manifest using keyword-only `storage_format="jsonl"` or `"hdf5"`, with HDF5 requiring explicit `schema.frame_shape` and `schema.frame_dtype`.
- LocalStorageManager.append_rows: Validates scientific timing/context and appends JSONL plain-data rows or HDF5 rows containing a NumPy `frame`, integer `frame_index`, and plain per-frame metadata by storage ID.
- LocalStorageManager.flush: Flushes current writes without finalizing, counting complete JSONL file writes separately from rows whose durability is confirmed by successful file flush and `fsync`.
- LocalStorageManager.finalize_stream: Flushes and closes one stream and records manifest/evidence with JSONL accepted/buffered/written/durable counts or HDF5 accepted/persisted frame counts, rejecting successful finalization when a partial write leaves an uncertain tail.
- LocalStorageManager.finalize_all: Finalizes all created streams and returns a local-only completion summary.
- LocalStorageManager.cleanup: Flushes and closes open local stream resources without deletion and records cleanup completion or failure evidence.
- LocalStorageManager._jsonl_completion_details: Reports JSONL row accounting and write status for failure evidence, manifests, and summaries, leaving `row_count` unknown when a write or file flush leaves an uncertain tail.

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

- main(argv=None): Runs a metadata-only camera iteration, an opt-in scientific acquisition with optional post-validation visualization, or read-only inspection of an existing HDF5 recording without camera/Session startup.
- view_hdf5_frames(path): Reads up to six evenly spaced camera frames read-only, labels recorded indices, converts BGR/BGRA for Matplotlib display, and returns a saved PNG path when graphical display is unavailable.
- _inspect_frames: Reports visualization errors as nonzero CLI exits without changing the recording or acquisition behavior.
- verify_scientific_artifact(manifest, experiment_start_session_time_s, frame_shape, frame_dtype): Reopens a finalized camera HDF5 artifact read-only and verifies manifest counts, declared shape/dtype, ordered indices, aligned runtime timing, and per-frame metadata.
- _camera_source: Converts a CLI camera index to an integer while preserving backend source strings.
- _run_scientific: Orchestrates the existing Controller/AcquisitionNode scientific acquisition and local persistence path using explicit camera-product declarations and selections.
- _require_success: Reports an unsuccessful Controller command without replacing its original error text.
- _cleanup: Attempts camera/runtime and local storage resource cleanup independently and reports cleanup errors without hiding acquisition errors.

## scripts/demo_nats_runtime.py

- main: Manually validates Controller command, AcquisitionNode execution/result/evidence, Ingestor evidence intake, and Core NATS telemetry against a real JetStream-enabled NATS server.
