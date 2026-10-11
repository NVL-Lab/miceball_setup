# Code Map

## Phase 16 accepted responsibility clarification (Slice 1 partially implemented)

Decisions 304-321 establish Session-independent and GUI-independent lifetime for
Controller, AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager.
Session-specific collaborators remain subject to existing creation, binding,
cleanup, and bounded-memory contracts; DeviceManager and DeviceAdapters are not
new independently operating services. This is not a claim that all current
collaborators already implement successive-Session reuse.

Controller will coordinate general framework shutdown through existing
distributed command/result boundaries; individual administrative service
maintenance may be independent through a local interface. Participants retain
closeout ownership and independently release confirmed Session bindings under
Decision 313. These responsibilities are distinct from implemented Session
stop/finalization and must not initiate collection, verification, transfer, or
export. General shutdown evaluates all required preconditions before stopping
any service and preserves evidence in producer -> Ingestor -> StorageManager ->
Controller order. Decisions 318-319 accept Session-independent framework evidence
through existing infrastructure, not a separate evidence system. Independent
startup/readiness and returning-service recognition do not resume interrupted
work. Q025 is resolved architecturally; Q019 and Q024 remain open.
No future stop/kill API, runtime model, persisted schema, or validated behavior is
listed as implemented here.

Decision 322 additionally makes every ControllerActionDecision persistent,
including no-mutation outcomes. Accepted ownership remains Controller-produced
RuntimeEvidenceMessage with is_persistent=True -> Ingestor compilation ->
StorageManager Evidence Archive writing. Controller binding release requires
confirmed archival of all its Session's decisions plus required cleanup and
Session Record obligations, not merely publication. The narrow follow-up now
implements decision-message packaging, submission to an attached Ingestor, and
owner-specific confirmation of the exact messages in the current successfully
written archive, held stable through binding-release commitment. Without an attached Ingestor, retained messages are available for
caller-managed publication through the existing boundary; publication alone
cannot confirm archival. Local Session start and finalization require an explicit
Ingestor reference and report its absence without using a node-owned fallback.
Controller Session Records retain acquisition-envelope audit and Session context,
but do not include raw runtime evidence or runtime-evidence intake audit; those
are written through the Evidence Archive. Q019 remains open and Phase 16 is unvalidated.

## Slice 28 implementation (independent validation and audit pending)

Decisions 281-301 now have a Controller-owned pre-Session launch path over the
existing NATS command/result boundary. Controlled broker-double tests exercise
real message serialization, handlers, resource resolution, participant-local
preparation, cleanup-confirmed rollback, and local-finalization reservation
release. They are not live NATS, multi-process, hardware, manual IPython, or
independent audit validation. M015 remains pending; no new workflow is claimed.

**Implemented correction (Decision 302):** Successful device shutdown and required
device cleanup return retained adapters to DECLARED; failed cleanup retains FAILED.
DeviceAdapter completes adapter-specific resource cleanup before the generic state
transition, and DeviceManager coordinates it without device-specific resets.
AcquisitionNode retains instances and deployment configuration, applies each
Session's own configuration, and withholds safe-reuse readiness and reservation
release until all required local Session cleanup is confirmed. Declared readiness
does not initialize hardware or authorize acquisition. Controller only evaluates
readiness and orchestrates launch/release. Simulated and broker-double regression
tests cover sequential reuse; independent validation/audit and M015 closure remain
pending. No public reset operation or lifecycle state was added.

Controller may be constructed without local participant references. AcquisitionNode
still receives its existing deployment-local runtime collaborators and explicit
device declarations; no remote Python references or Session replicas are sent.
Missing/invalid reports remain unknown, and unconfirmed initialization or cleanup
never becomes assumed success. Node reservations remain protected without cleanup
confirmation. Session retains the initialization-completion and lifecycle boundary.

Participants independently connect to external NATS. Session-specific commands
use real identities; readiness/inventory commands may omit Session identity.
Ingestor prepares a deployment-local recovery journal before subscribing to Session
evidence. SynchronizationManager prepares Session state without new timing math.
Nodes create their own LocalStorageManagers using deployment roots. Historical
direct-object Session initialization still permits explicit local root overrides;
distributed launch rejects Controller-selected node roots.

Existing local Experiment orchestration and persistence/finalization APIs remain
available; Slice 28 does not add remote Experiment lifecycle activation or a new
remote evidence-compilation/persistence protocol. Normal binding release is now
partially implemented under Decision 313. Controller explicitly releases a terminal
reference after confirmed runtime cleanup and successful final persistence, retaining
a bounded last-release outcome and leaving durable files untouched. Ingestor and
SynchronizationManager can release empty bindings (synchronization also requires
stopped Session Time). Evidence-bearing Ingestor release now requires the exact
persistent-message and complete runtime-audit snapshot confirmed by StorageManager,
plus terminal lifecycle evidence in the existing final Session Record. Acquisition
envelopes and their audit retain their existing persistence path. Intake and release
commit share a lock; additional intake invalidates earlier archive coverage.
Ingestor also holds StorageManager's preservation guard through commitment,
with intake locked before storage. Archive/final-record writers never acquire
Ingestor intake. Controller rechecks current archival coverage after asynchronous
unsubscription and holds the same storage guard through its synchronous commit;
it never holds that guard across an await. Release captures the Session object
identity and its subscriptions, rechecks identity after each unsubscription await
and before retirement, and returns stale-operation failures without recording
them against a newer binding. Archive rewrites and release commits
are serialized, without freezing future archive writes or resolving Q019/Q024.
SynchronizationManager releases after active mappings retire, Session Time stops,
and every mapping update has confirmed journal-backed Ingestor acceptance, without
waiting for subsequent archival. Controller
decision-bearing release now requires exact decision-message inclusion in
successfully written archive input, with changes after compilation invalidating
that confirmation. Confirmed release retires temporary decisions and leaves
durable evidence intact. No Q019 drain protocol is implemented. Automated
broker-double tests exercise successive Sessions with empty central evidence-owner
bindings; this is not independent/manual validation or full Decision 313 completion.
Follow-up tests additionally exercise Controller-specific evidence-bearing release,
subset/stale compilation, publication without archival confirmation, failure
retention, evidence-bearing service reuse, and concurrent intake/release. These
are automated implementation checks, not independent validation or audit.
The existing local Controller release refreshes the terminal Session Record before
Ingestor release; synchronization handoff is confirmed while Ingestor retains its
accepted evidence. These checks do not establish Session-wide producer completeness.

Discovery, deployment configuration, scheduling, stale reservations/restart,
retention/deletion, durable pre-Session auditing, and Q019's evidence-consumption
guarantee remain deferred. M014/W034 retain completed Slice 27 scope and status.

## src/lab_sync_acquisition/__init__.py

- AcquisitionHealthPolicy: Public import for immutable plain-data acquisition-health policy definitions and observation-vocabulary validation.
- ActiveExperimentRuntimeContext: Public import for immutable runtime-only Experiment identity and start Session Time supplied to AcquisitionNode.
- AcquisitionNodeLocalTimeReport: Public import for immutable plain local-time samples reported to SynchronizationManager without becoming synchronization evidence.
- AcquisitionIterationSummary: Public import for the result of one bounded AcquisitionNode iteration.
- AcquisitionNode: Public import for bounded acquisition runtime execution, AcquisitionNode-owned runtime timestamping, separate active Experiment timing and health context, linked observation/interpretation evidence, configured batching, writable failure-evidence readiness, and sender-side failure handling.
- AcquisitionNodeReadiness: Public import for node-scoped required-service readiness, independent per-device reports, and Session-keyed reservation status.
- AcquisitionRecordEnvelope: Public import for the transferable acquisition record envelope shared across the acquisition-to-ingestion boundary.
- ARTIFACT_MANIFEST_EVIDENCE_TYPE: Public evidence-type vocabulary for artifact lifecycle manifests carried through RuntimeEvidenceMessage and LAB_EVIDENCE.
- Controller: Public import for local single-session orchestration or pre-Session distributed resource resolution, reservation, launch, and cleanup orchestration.
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
- RuntimeParticipant: Public immutable component_type/component_id identity currently used in SessionConfig to declare expected runtime participation.
- UnresolvedCommandOutcome: Public immutable issuer evidence that one expected command target did not return a result within the issuer-defined window.
- GroupCommandOutcome: Public immutable issuer-owned aggregate of returned command results and unresolved expected targets for one component group.
- RuntimeTelemetryMessage: Public immutable plain-data transient telemetry message.
- DeviceStatus: Public import for live adapter status snapshots.
- DurablePublicationError: Public import for explicit durable publication failure context without buffering or retry behavior.
- IngestAuditRecord: Public import for ingest audit evidence recorded for each received acquisition envelope.
- InMemoryIngestor: Public import for envelope intake and runtime evidence intake with optional explicit known-Session recovery journaling.
- RuntimeEvidenceAuditRecord: Public import for one Ingestor audit record associated with durable runtime evidence intake.
- NatsCommunicationBoundary: Public import for real NATS connection, JetStream stream setup, message serialization, publication, subscription, and transport acknowledgement mechanics.
- NatsControllerCommunication: Public import for Controller-side durable command publication and command-result consumption.
- NatsAcquisitionNodeCommunication: Public import for targeted AcquisitionNode command consumption, local duplicate detection, explicit command execution, command-result publication, and runtime evidence publication.
- NatsIngestorCommunication: Public import for durable runtime evidence consumption into the existing Ingestor ownership boundary.
- NatsSynchronizationManagerCommunication: Public import for participant-scoped readiness and Session preparation/abort command handling without transport-owned timing semantics.
- InMemoryStorageManager: Public import for the minimal in-memory acquisition envelope storage boundary.
- PersistentStorageManager: Public import for the v1 persistent StorageManager implementation that stores accepted envelopes as JSONL and writes caller-supplied Session Record and Evidence Archive products.
- SshRetrievalEndpoint, ArtifactRetrievalResult, ArtifactCollectionResult: Public imports for deployment-local SSH configuration and StorageManager artifact collection results.
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
- RuntimeParticipant: Stores one plain component type and identifier, currently referenced by Session configuration, without transport addresses or a second identity system.
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

- AcquisitionNodeReadiness(node_id, reserved_for_session_id, role, device_readiness, service_readiness): Holds node-scoped readiness with reservation identity and computes ready from required services only, while retaining independent per-device results.

## src/lab_sync_acquisition/acquisition_health.py

- AcquisitionHealthPolicy: Stores named rule-specific evaluation substructures and observation-to-interpretation vocabulary, supports plain-data round trips, and validates interpretation keys against supplied supported observations.
- HealthInterpretationEvidence: Records the assigned policy's interpretation of one explicitly referenced Experiment-scoped Health Observation as immutable plain data without executing framework action.

## src/lab_sync_acquisition/acquisition_record.py

- AcquisitionRecordEnvelope: Holds the minimal transferable acquisition record message fields, including optional source node identity, and supports JSON-like plain-data round trips.

## src/lab_sync_acquisition/acquisition_node.py

- AcquisitionIterationSummary: Records the small inspectable summary returned by one bounded acquisition iteration.
- AcquisitionNode: Owns bounded acquisition runtime execution and timestamping, stores separate active Experiment timing and health context, and emits explicitly linked ExperimentScopedHealthObservation and HealthInterpretationEvidence records without executing framework actions.
- AcquisitionNode.status(): Includes existing local cleanup confirmation as `cleanup_confirmed` for safe Session-binding release, alongside runtime, reservation, and active-context status.
- AcquisitionNode.__init__(session_id=None, device_manager=None, synchronization_manager=None, ingestor=None, node_id=None, role=None, acquisition_configuration=None, acquisition_health_policies=(), error_evidence_location=None, *, default_local_storage_root=None, device_declarations=None): Allows pre-Session construction with deployment-local collaborators and inventory, capturing adapter deployment configuration independently of subsequent Session-specific overrides while preserving the historical bound local path.
- AcquisitionNode.declared_devices: Returns the node's declared DeviceDeclaration/ScientificProductDeclaration inventory independently of Session selection and device availability.
- AcquisitionNode.reserved_for_session_id: Returns the current exclusive Session reservation or None under the node-owned lock.
- AcquisitionNode.reserve(session_id): Atomically acquires an unreserved node, confirms the same owner's reservation idempotently, or rejects another owner without changing state.
- AcquisitionNode.release_reservation(session_id): Clears only the owner's confirmed-clean, nonrunning, locally finalized binding without deleting artifacts or waiting for global retrieval.
- AcquisitionNode.initialize_session(session_id, selected_devices, device_configurations=None, scientific_outputs=()): Checks the reservation and prepares selected adapters/storage/outputs using that Session's overrides or retained deployment configuration, retaining partial binding for cleanup and returning ServiceReadiness without a Session replica.
- AcquisitionNode.abort_session_initialization(session_id): Clears acquisition eligibility and confirms matching local device/storage cleanup only when every required stage succeeds, preserving reservation protection on failure and permitting later explicit completion without deleting evidence or finalized artifacts.
- AcquisitionNode.prepare_local_storage(session_id, declarations, root_path=None): Physically creates and attaches Session-authorized local storage using the node deployment root or an explicit historical local-workflow override.
- AcquisitionNode.check_node_readiness(additional_service_readiness=()): Reports every enabled declared device, including missing adapters, with service-only aggregate readiness and separate reservation state.
- AcquisitionNode._inventory_readiness: Completes deployment inventory readiness using DeviceManager results or explicit missing-adapter diagnostics without Session requiredness.
- AcquisitionNode.activate_experiment_runtime_context: Stores immutable active Experiment identity and start Session Time for Experiment Time derivation without owning lifecycle evidence.
- AcquisitionNode.clear_experiment_runtime_context: Clears active Experiment timing context without stopping Acquisition Runtime or changing health mapping.
- AcquisitionNode.receive_active_synchronization_mapping: Passively replaces AcquisitionNode's stored reference to the SynchronizationManager-owned active mapping without applying mapping mathematics.
- AcquisitionNode.default_local_storage_root: Exposes the explicitly configured persistent root without mutation by Session overrides.
- AcquisitionNode.node_id: Exposes the configured AcquisitionNode identity used by scientific output selections.
- AcquisitionNode.local_storage_manager: Exposes the Session-attached local persistence collaborator without transferring persistence ownership.
- AcquisitionNode.attach_local_storage_manager: Attaches one Session-authorized LocalStorageManager and device declarations after checking Session/node identity and preventing manager replacement.
- AcquisitionNode.prepare_experiment_scientific_outputs: Returns existing ServiceReadiness evidence after resolving explicit products and requesting one empty local stream per Experiment/device/product, reusing open preparations and preserving/finalizing newly created partial artifacts on failure.
- AcquisitionNode.scientific_output_storage_ids: Returns a readback copy of Experiment/device/product associations with LocalStorageManager runtime write handles.
- AcquisitionNode.finalize_experiment_scientific_outputs: Retires the Experiment's runtime identity and attempts LocalStorageManager finalization of every associated stream, returning finalized manifests or raising an error containing all failures without affecting other Experiments.
- AcquisitionNode.start_runtime(): Requires active binding and successful Session preparation before starting acquisition, retaining compatibility with historical explicitly pre-bound caller-prepared nodes.
- AcquisitionNode.stop_runtime: Clears acquisition eligibility, stops devices, and finalizes prepared scientific artifacts, confirming cleanup only after successful completion while retaining existing failure reporting and Experiment context clearance.
- AcquisitionNode.run_one_iteration: Requires successful preparation and running acquisition, collects selected scientific devices once, timestamps and persists scientific records, and preserves completed partial collections before propagating failure through existing cleanup.
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
- Controller.controller_action_decision_evidence: Returns retained persistent RuntimeEvidenceMessages for Controller decisions, using existing evidence identities and plain decision payloads for caller-managed publication.
- Controller.process_health_interpretation(evidence): Records one decision and its persistent runtime message per presentation, submitting to an attached Ingestor without changing lifecycle.
- Controller._record_action_decision(decision): Retains one persistent message per decision instance before optional Ingestor submission, including externally supplied executable decisions, without duplicating an already recorded instance.
- Controller._controller_decision_evidence_snapshot(session_id): Copies Session-specific owned message identities and contents for exact compilation and archival confirmation.
- Controller._require_controller_decision_archival(session_id): Blocks release unless all current owned decision messages match the successful finalization snapshot.
- Controller: Sequentially coordinates one Session with optional keyword-only `component_id="controller"` for producer identity, preserves existing ownership, and orchestrates preparation, lifecycle, runtime cleanup, and final persistence.
- Controller.__init__(acquisition_node=None, ingestor=None, storage_manager=None, session_record_path=None, synchronization_manager=None, *, component_id="controller"): Supports Controller creation before Session and without remote participant references while retaining existing local collaborators.
- Controller.launch_session(selections, *, communication, participants, config_parameters, result_window_s, scientific_outputs=()): Asynchronously allocates a fresh intended Session ID, resolves node-scoped device selections, reserves resources, constructs final SessionConfig, confirms participant preparation, and returns operational success or cleanup-aware rollback diagnostics.
- Controller.start_launched_session(): Starts reserved nodes through correlated NATS commands and then starts the Session, returning ControllerCommandResult and attempting cleanup if startup fails.
- Controller.stop_launched_session(reason=None): Stops and locally finalizes all reserved nodes through NATS, releases only confirmed-clean reservations, and stops the Session without waiting for global collection.
- Controller.get_status(): Returns Session/command status, the bounded last released terminal outcome, and the local AcquisitionNode snapshot or None, without fabricating remote runtime status.
- Controller.release_session(): Asynchronously releases only its captured terminal Session binding after confirmed cleanup and current archival under StorageManager's preservation guard, revalidating object identity after every unsubscription await and before retirement; stale operations return a failed ControllerCommandResult for the original Session without changing the current binding or command history, while cancellation propagates and retains outstanding obligations.
- Controller._session_ingest_state(): Snapshots existing intake views to detect acceptance/audit changes after final persistence or during subscription release.
- Controller.start_experiment: Accepts keyword-only `scientific_outputs=()`, `preparation_readiness=()`, and `preparation_outcomes=()`, gates start on required readiness and correlated final remote successes, and reports preparation rejection once as persistent runtime evidence in failed result details without lifecycle activation.
- Controller._record_failed_command: Records an unsuccessful command with optional plain diagnostic details, including the produced rejection message for a pre-start preparation failure.
- Controller.stop_experiment: Records canonical normal-stop evidence, clears active runtime context and health mapping, and requests finalization of only that Experiment's streams without stopping the Session or acquisition runtime.
- Controller.execute_controller_action_decision: Records persistent evidence for an externally supplied accepted decision once, then executes unchanged no-mutation or failure semantics, finalizing Experiment streams for `experiment_fail` and retaining the failed-Session cleanup path for `session_fail`.
- Controller.stop_session: Stops runtime and scientific persistence, records normal-stop evidence for any active Experiment, and then stops the Session through its existing lifecycle.
- Controller.initialize_session: Retains the historical direct-object workflow, with Session-authorized local storage now physically created by AcquisitionNode and criticality evaluated from selected DeviceDeclarations.
- Controller.start_session(): Requires an explicit Ingestor reference before local runtime startup, then starts acquisition, starts the Session, and writes the initial Session Record through existing persistence.
- Controller._session_record_evidence(): Gathers Session configuration, lifecycle, readiness, cleanup, command failures, Experiment evidence, accepted acquisition envelopes, and their audit without copying runtime evidence or runtime-evidence audit into the Session Record.

## src/lab_sync_acquisition/device_adapter.py

- DeviceAdapterState: Enumerates the minimum lifecycle states for a live device adapter.
- DeviceReadiness(device_id, ready, reason, capabilities_available): Records technical device readiness without requiredness, which is evaluated from selected DeviceDeclaration.required.
- DeviceStatus: Reports the current live adapter lifecycle status without scientific data.
- DeviceAdapterLifecycleError: Signals invalid live adapter lifecycle operations.
- DeviceReadinessNotImplementedError: Signals that a live adapter has no concrete readiness implementation.
- DeviceAdapter: Provides the minimum live runtime control interface for one device adapter with externally read-only lifecycle state, explicit required participation metadata, and a concrete-adapter record exposure hook for DeviceManager collection.
- DeviceAdapter.collect_scientific_records: Explicitly collects separate local scientific and lightweight runtime records, defaulting to one existing `collect_records()` call with no scientific data for unchanged adapters.
- DeviceAdapter.shutdown: Completes adapter-specific cleanup after initialization/readiness/failure or normal stop, then returns to DECLARED; failed cleanup retains FAILED and completed shutdown is idempotent.
- DeviceAdapter._shutdown_resources: Adapter-specific resource-release hook executed before the generic successful-cleanup transition.
- DeviceAdapter.initialize(config): Requires DECLARED and applies fresh configuration for the next initialization without a reset operation.
- DeviceAdapter.check_ready: Reports declared eligibility without opening hardware or changing state, while initialized acquisition readiness remains concrete-adapter-owned.
- DeviceStatus.shutdown: Reports completed device cleanup even when the reusable adapter state is DECLARED, resetting on subsequent initialization.
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
- InMemoryIngestor: Receives envelopes and runtime evidence, optionally journals/reconstructs the normal evidence view for a known Session, deduplicates evidence_id content, and compiles persistent evidence without interpreting meaning.
- InMemoryIngestor.__init__(storage_manager=None, *, session_id=None, recovery_journal_path=None, component_id="ingestor", recovery_journal_root=None): Preserves explicit known-Session recovery while optionally configuring a deployment root for later Session-specific preparation.
- InMemoryIngestor.prepare_session(session_id): Creates or reconstructs the intended Session recovery journal from its deployment root before confirming evidence intake preparation.
- InMemoryIngestor.abort_session_initialization(session_id): Disables prepared intake while preserving durable journal entries and accepted evidence, clearing empty preparation bindings without deleting files.
- InMemoryIngestor.release_session(session_id, *, storage_manager=None): Releases a matching healthy binding, requiring exact persistent runtime evidence/all runtime-audit archive coverage and existing terminal Session Record/acquisition-envelope preservation for evidence-bearing bindings; intake and storage guards remain held through temporary-state retirement without deleting journals.
- InMemoryIngestor.has_durable_runtime_evidence(evidence): Confirms exact journal-backed message acceptance for a producer handoff, returning False for memory-only intake or uncertain journal state without claiming final archival.
- InMemoryIngestor._initialize_recovery_journal: Reuses journal creation/reconstruction and ordinary recovery-evidence intake for constructor and distributed preparation paths.
- InMemoryIngestor.session_id: Returns the configured known Session identity or None for legacy in-memory use.
- InMemoryIngestor.recovery_journal_path: Returns the caller-supplied journal Path or None for legacy in-memory use.
- RuntimeEvidenceAuditRecord: Records intake order, receive time, evidence identity, acceptance, and reason for one durable RuntimeEvidenceMessage.
- InMemoryIngestor.receive_runtime_evidence: Validates evidence, durably journals new messages before working-state acceptance when configured, audits intake, acknowledges identical content as already accepted, and raises on conflicting evidence_id content.
- InMemoryIngestor._sync_journal_directory: Durably records initial journal creation in its parent directory on POSIX systems.
- InMemoryIngestor._evidence_content: Validates message identity and configured Session scope and serializes full content for journal storage and deduplication.
- InMemoryIngestor._append_runtime_evidence: Appends one complete UTF-8 JSONL message and flushes/fsyncs before acceptance, refusing further new intake after a failed append until restart.
- InMemoryIngestor._restore_runtime_evidence: Stages valid journal entries before restoring the normal evidence view, repairs only an interrupted final append, and rejects completed corruption or conflicting identities.
- InMemoryIngestor._is_interrupted_json: Recognizes incomplete final JSON tokens without treating completed malformed lines as interrupted writes.
- InMemoryIngestor.compile_persistent_runtime_evidence: Returns a detached, consistent snapshot of accepted persistent runtime messages and all runtime-evidence audit records under the intake lock without inferring persistence from evidence meaning.

Slice 27 (Decisions 276-280) is complete (M014, W034) after independent manual
software validation and corrected targeted re-audit PASS. W034 preserves the
uncertain-durability clarification and initial audit FAIL/correction history.
Supply session_id and
recovery_journal_path together; the caller chooses the exact file location and
its parent directory must already exist. Legacy local in-memory use remains
available without these arguments; broker evidence subscriptions require a
matching journal, either constructor-configured or prepared through
prepare_session(session_id) with recovery_journal_root.
Journal entries preserve messages, not original ingest audit timestamps: startup
generates intake audit records marked recovered at reconstruction time. The
existing Slice 22 compiler is unchanged. No journal cleanup or Session discovery
is implemented (Q024); acceptance deduplication is not Controller action
deduplication, and Session-wide consumption/finalization remains open (Q019).

## src/lab_sync_acquisition/nats_communication.py

- DurablePublicationError: Reports failed JetStream publication with message class, message identity, subject, intended stream, and reason while leaving the original message caller-owned.
- NatsCommunicationBoundary: Owns a real nats-py connection, reports NATS availability through ServiceReadiness, creates accepted JetStream streams, and handles JSON serialization, durable publication acknowledgement, and Core NATS telemetry mechanics without domain semantics.
- NatsControllerCommunication: Publishes unicast or issuer-fanned group commands, consumes and aggregates addressed per-target command results over an issuer-defined window, records missing results as unresolved, and independently presents HealthInterpretationEvidence without relaying evidence.
- NatsControllerCommunication.check_ready(): Returns required NATS communication readiness for launch gating.
- NatsControllerCommunication.request_command(participant, command_type, session_id, payload, result_window_s): Publishes once and awaits the correlated final result, returning None for missing/invalid confirmation without retry or assuming remote state is absent.
- NatsControllerCommunication.subscribe_command_results(session_id, callback=None): Accepts None for participant-scoped results and a real Session ID for Session-scoped results.
- NatsCommunicationBoundary.ensure_streams(): Retains Session stream filters and adds messages.command.> and messages.command_result.> to their existing JetStream streams for pre-Session commands, leaving evidence and Core NATS telemetry unchanged.
- NatsAcquisitionNodeCommunication.subscribe_commands(): Returns two subscriptions for participant-scoped and Session-scoped addressed commands, keeping the same handler usable across binding changes.
- NatsAcquisitionNodeCommunication: Consumes targeted readiness, scientific-output preparation, or runtime commands, deduplicates by command_id, and publishes explicit outcomes without owning Experiment lifecycle.
- NatsAcquisitionNodeCommunication.execute_command: Executes `prepare_experiment_scientific_outputs` through the existing node API with explicit Experiment/product identities and returns readiness diagnostics in the existing correlated final command result.
- NatsIngestorCommunication: Consumes durable RuntimeEvidenceMessage records and passes them to InMemoryIngestor for separate evidence intake and audit.
- NatsIngestorCommunication.subscribe_commands(): Returns participant- and Session-scoped subscriptions for readiness, journal preparation and evidence-subscription establishment, or initialization abort with intake-subscription cleanup before confirmation.
- NatsSynchronizationManagerCommunication(boundary, synchronization_manager): Routes readiness and Session prepare/abort commands to the timing owner over existing command/result streams.
- NatsSynchronizationManagerCommunication.subscribe_commands(): Returns participant- and Session-scoped command subscriptions without implementing transport synchronization or remapping.
- _participant_result: Builds an existing correlated final command-result message for one service-owned operation.
- _execute_service_command: Delegates readiness, Session preparation, or abort to the service owner and retains existing command-ID deduplication.
- _subscribe_participant_commands: Establishes the two addressed command subscriptions reused by mandatory service handlers.
- NatsIngestorCommunication.subscribe_evidence(session_id, callback=None): Requires a matching Session recovery journal and ACKs after successful durable acceptance, invoking the callback only for newly accepted evidence, not identical redelivery.

## src/lab_sync_acquisition/service_readiness.py

- ServiceReadiness: Holds the shared framework-service readiness fields consumed by Session initialization and exposes them as plain data for Session Record evidence.

## src/lab_sync_acquisition/opencv_camera.py

- OpenCVCameraConfig: Holds explicit OpenCV camera source, backend, frame polling count, and optional requested capture properties.
- SeeedIMX219OpenCVCameraAdapter: Opens an OpenCV camera, reports readiness, provides metadata-only default collection or explicit local frame-preserving collection, and releases the capture during shutdown.
- SeeedIMX219OpenCVCameraAdapter.shutdown(): Uses generic shutdown to report FAILED and retain the capture after release failure, returning to DECLARED only after successful release with idempotent subsequent shutdown.
- SeeedIMX219OpenCVCameraAdapter.initialize(config): Accepts OpenCVCameraConfig or its plain-data mapping through the existing DECLARED lifecycle, owning each capture before fallible setup and retaining FAILED plus the capture if initialization cleanup cannot release it.
- SeeedIMX219OpenCVCameraAdapter.check_ready(): Reports declared eligibility without opening capture, and checks initialized capture readiness separately.
- SeeedIMX219OpenCVCameraAdapter.collect_scientific_records: Returns actual NumPy frames and separate metadata from the same reads, omits unavailable optional SDK metadata without failing acquisition, and preserves completed partial records if a later read raises without assigning framework timing or retrying reads.

## src/lab_sync_acquisition/storage.py

- InMemoryStorageManager: Reports service readiness, stores accepted AcquisitionRecordEnvelope objects in memory, and exposes all, session-filtered, and source-filtered readback without file writing or transformation.
- PersistentStorageManager: Reports service readiness, stores accepted envelopes, and writes/reads v1 Session Record and Phase 13 Evidence Archive products from caller-supplied evidence.
- PersistentStorageManager constructor: Accepts `records_path` and keyword-only `global_artifact_root=None`, `retrieval_endpoints=None`, `evidence_publisher=None`, and `component_id="storage"`; the publisher is an existing async runtime-evidence publication callable and component_id supplies the evidence source identity.
- SshRetrievalEndpoint(host, username, port=22, key_filename=None, known_hosts_path=None): Immutable deployment-local SSH configuration keyed by logical AcquisitionNode ID, using trusted host keys and optional explicit private-key/known-hosts files.
- ArtifactRetrievalResult(artifact_manifest_id, outcome, global_destination=None, failure_information=None, verification_outcome=None, verification_information=None): Immutable per-artifact result whose `to_dict()` preserves retrieval success/failure separately from verification information, absent when retrieval failed.
- ArtifactCollectionResult(artifact_results): Immutable aggregate whose `succeeded` requires every requested artifact to have retrieval success and verified status, with `to_dict()` retaining ordered per-artifact details without lifecycle interpretation; empty collections remain successful.
- PersistentStorageManager.collect_artifacts(handoff): Independently retrieves one file per manifest through SSH/SFTP, including missing-finalization candidates, then lightly verifies completed global copies without changing authoritative sources or Session products.
- PersistentStorageManager.collect_artifacts_with_evidence(handoff): Awaits publication of one persistent global_artifact_collection_evidence message after a completed pass, preserving separate per-artifact retrieval/verification outcomes and operational wall-clock bounds.
- Configured evidence publication requires the awaited collection method; collect_artifacts rejects that configuration rather than silently bypassing publication, while legacy unconfigured synchronous collection remains supported.
- PersistentStorageManager._verify_artifact: Selects the current framework-managed HDF5 contract from existing manifest format metadata and checks read-only structure, identity, and counts without reading scientific datasets or altering copies.
- _VerificationReader: Private read-only HDF5 file-access wrapper tracking actual I/O failure without retaining callback tracebacks, so format rejection is classified independently of diagnostic wording.
- PersistentStorageManager._retrieve_artifact: Selects the existing manifest source, captures copied size from the temporary file position when available, and returns the deterministic destination/size after closed-file non-overwriting promotion and best-effort temporary removal.
- PersistentStorageManager._pull_sftp_file: Uses Paramiko to open the source directly and copy bounded chunks through SFTP without a source existence/stat pre-probe.
- PersistentStorageManager.write_initial_session_record: Writes caller-supplied initial Session Record evidence to `session_<session_id>/session_record_initial.json`.
- PersistentStorageManager.write_evidence_archive: Writes compiled persistent runtime evidence, runtime-evidence audit, and compilation summary to the unchanged Phase 13 files, retaining exact successful write input and invalidating prior confirmation on a failed rewrite.
- PersistentStorageManager.write_final_session_record: Writes caller-supplied final Session Record evidence to `session_<session_id>/session_record_final.json`, confirming its path only after successful writing.
- PersistentStorageManager.get_session_preservation_confirmation(session_id): Returns a detached snapshot of exact archived message/audit dictionaries and the existing successfully written final Session Record for the latest matching Session, or None when required writes lack confirmation; the snapshot alone does not guard a later release commit.
- PersistentStorageManager.session_preservation_guard(session_id): Synchronous context manager yielding current confirmation while holding the archive/final-record write lock through the caller's release commit; callers must not await or acquire a new Ingestor intake lock while holding it.

## src/lab_sync_acquisition/synchronization.py

- SynchronizationMapping: Stores the accepted immutable local-to-Session mapping fields with a plain-data round trip.
- AcquisitionNodeLocalTimeReport: Stores one immutable AcquisitionNode local-time report as plain data without representing SynchronizationObservation evidence.
- MappingUpdateEvidence: Stores immutable created, replaced, or retired mapping evidence with optional previous/new mappings and a plain-data round trip.
- MappingUpdateEvidence.to_runtime_evidence_message: Wraps mapping update plain data in the existing RuntimeEvidenceMessage boundary using evidence type `mapping_update_evidence`.
- SynchronizationManager: Owns the Session clock plus per-AcquisitionNode active mapping creation, replacement, retirement, lookup, and in-memory mapping-update evidence without implementing mapping mathematics or drift estimation.
- SynchronizationManager.prepare_session(session_id): Confirms Session-specific preparation independently of pre-Session service readiness, rejecting a different active preparation binding.
- SynchronizationManager.abort_session_initialization(session_id): Clears only matching preparation state without altering mapping or established timing evidence.
- SynchronizationManager.release_session(session_id, *, ingestor=None): Releases matching stopped preparation after mappings retire and each mapping update has exact durable Ingestor acceptance, retiring temporary history without waiting for downstream archival or terminating the service.
- SynchronizationManager.create_and_activate_mapping: Creates and atomically activates one initial immutable mapping for an AcquisitionNode.
- SynchronizationManager.replace_active_mapping: Atomically replaces one active mapping and records replacement evidence.
- SynchronizationManager.retire_active_mapping: Retires one active mapping and records retirement evidence.
- SynchronizationManager.get_active_mapping: Returns the currently active mapping for one Session and AcquisitionNode.

## src/lab_sync_acquisition/session.py

- SessionState: Enumerates the accepted Phase 1 session lifecycle states.
- SessionConfig: Holds the immutable accepted run configuration, including expected runtime participants, error evidence location, and current historical `local_storage_roots` overrides; Decision 298 does not authorize Controller-selected remote roots.
- ReadinessCheck: Records the result of a readiness condition checked during lifecycle transitions and exposes it as plain data for Session Record evidence.
- LifecycleTransition: Records an allowed lifecycle state transition in sequence order and exposes it as plain data for Session Record evidence.
- ExpectedParticipant: Records participant identity, type, expected contribution, and required status as an inert plain-data declaration.
- ScientificOutputSelection: References `source_device_id`, `source_node_id`, and `data_product_id` with plain-data round trips, without duplicating schema or storage requirements.
- ExperimentDescriptor: Records persistent Experiment identity, details, ordered Expected Participants, and unique ordered scientific output selections through plain-data round trips, without resolving selections against live devices.
- Session.ensure_experiment_descriptor: Creates one descriptor with keyword-only `scientific_outputs=()` or returns the existing descriptor, rejecting conflicting nonempty selections rather than silently discarding them.
- ExperimentLifecycleEvidence: Records canonical `experiment_start`, `experiment_stop`, or `experiment_fail` evidence in the Session timeline as plain data.
- SessionLifecycleError: Signals invalid lifecycle operations or failed readiness requirements.
- Session: Owns lifecycle, readiness, Experiment descriptors, canonical Experiment lifecycle evidence, cleanup status, and final status in memory.
- Session.initialize: Accepts confirmed readiness from distributed preparation or historical `acquisition_nodes=()` authorization, delegates physical local storage creation to nodes, and owns the initialization-completion transition without remote Session replicas.
- Session.record_service_readiness: Preserves preparation/service results in the existing Session-owned readiness evidence without introducing another readiness mechanism.
- Session.check_experiment_can_start: Checks canonical lifecycle evidence and rejects terminal Experiment identity reuse, including metadata-only executions.
- Session.record_experiment_lifecycle: Records canonical Experiment lifecycle evidence and applies the terminal-identity check to every `experiment_start`, including direct callers.

## src/lab_sync_acquisition/local_storage.py

- ArtifactManifest: Immutable plain-data authoritative local discovery record for one LocalStorageManager-owned scientific artifact.
- LocalStorageEvidence: Immutable plain-data evidence for local stream, manifest, write, finalization, and cleanup operations.
- LocalStorageCompletionSummary: Immutable plain-data summary of local finalization without implying global Session Record completion.
- LocalStorageManager: Owns explicitly selected JSONL or fixed-shape HDF5 incremental local stream persistence with bounded buffering, append-time flush intervals, manifests, evidence, readiness, cleanup, and finalization for one Session and co-located AcquisitionNode.
- LocalStorageManager.check_ready: Verifies that the configured local persistence root is writable using the shared ServiceReadiness contract.
- LocalStorageManager.create_stream: Creates one framework scientific file and manifest using keyword-only `storage_format="jsonl"` or `"hdf5"` (explicit HDF5 shape/dtype), with `external_artifact_path=None`; the obsolete combined external-file argument is removed and external files/timing files require separate manifests.
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

## Phase 14 / Slice 22 Integration - Completed

Decisions 240-244 are implemented through these existing components:

M010 is complete following manual IPython validation and independent audit PASS;
W031 records results and limitations. Slice 22 implements no artifact-byte retrieval;
the separate Slice 23 implementation below still awaits real Jetson/SSH-SFTP
deployment validation (M011), distinct from W032's software validation.

- LocalStorageManager retains artifact and manifest ownership; existing manifests and finalization results supply complete discovery information.
- AcquisitionNode.artifact_manifest_evidence: Returns produced persistent RuntimeEvidenceMessage snapshots containing complete initial and finalized manifests, also submitted to the attached local Ingestor at the scientific lifecycle boundaries.
- AcquisitionNode._record_artifact_manifest: Packages each manifest lifecycle state once using the authoritative to_dict representation without transferring local ownership.
- NatsAcquisitionNodeCommunication.publish_new_artifact_manifest_evidence(): Publishes newly produced manifest messages through the existing JetStream evidence boundary, invoked after subscribed command execution or explicitly for caller-managed local operations.
- InMemoryIngestor.compile_artifact_collection_handoff(session_id): Groups retained Session-scoped artifact_manifest messages by manifest identity, selects complete finalized or initial manifests, and returns session_id plus artifacts entries containing artifact_manifest and missing_finalization_evidence.
- Controller.finalize_session(): Requires an explicit Ingestor reference and every owned decision message in persistent compilation, writes runtime evidence/audit to the archive separately from the Session Record, rejects changed decision snapshots before completion, and confirms exact decision archival for release without asserting Session-wide consumption or retrieving artifact bytes.
- StorageManager owns Artifact Plane retrieval and global storage; byte retrieval was outside Slice 22 and is now implemented separately in Slice 23, with real Jetson/SSH-SFTP deployment validation still pending under M011.

Generic persistent-evidence compilation and Evidence Archive writing remain
unchanged. Slice 27 adds known-Session restart reconstruction without modifying
this compiler; diagnostics compilation and application-wide restart remain deferred.

## Phase 14 / Slice 23 Integration - Pending Real Deployment Validation

- Controller.collect_session_artifacts(): Explicitly initiates collection after the Session ends, compiles the existing handoff, and returns aggregate results in ControllerCommandResult.details without changing Session lifecycle or persistent Session products.
- Controller.collect_session_artifacts_with_evidence(): Requires a stopping Session and stopped acquisition runtime, guards active collection/publication against overlapping collection or finalization, and releases the guard on success, failure, or cancellation without translating evidence or changing lifecycle.

Install the optional SSH dependency with `pip install -e ".[artifact-retrieval]"`.
PersistentStorageManager maps logical node IDs to SshRetrievalEndpoint objects;
Paramiko uses trusted known-hosts and explicit keys or existing agent/local keys.
No endpoint configuration is added to portable evidence. External manifests are
consumed as supplied; no new external acquisition/registration workflow is introduced.
Promotion requires hard-link support in the global destination filesystem; lack of
support is a retrieval failure, not an overwrite fallback. M011 remains open
pending real Jetson/SSH-SFTP deployment validation; W032 records software coverage.

## Phase 14 / Slice 24 Responsibility - Completed

Decisions 261-270 assign StorageManager bounded, non-destructive light verification
after a global copy is successfully transferred, closed, and published. Retrieval
and verification outcomes remain separate, with per-artifact information and
aggregate reporting. The first contract applies to the existing LocalStorageManager
HDF5 layout, not a device type or all HDF5. The contract applies when existing
manifest details declare `storage_format="hdf5"` and `external_artifact_path` is
absent; other copies are copied_unverified. Checks use shapes and small attributes,
including finalized manifest persisted counts only when available. Controller
does not interpret verification checks or choose new Session lifecycle policy.
M012 is complete. W032 records automated results, six independent manual IPython
scenarios, the initial audit failure, and corrected targeted re-audit PASS.
Classification follows underlying operational file-access failure provenance,
not an HDF5 diagnostic-text whitelist. No public API changed during closure.

## Phase 14 / Slice 25 Responsibility - Complete (M013, W033)

Decisions 271-275 assign StorageManager one compiled persistent
`global_artifact_collection_evidence` record per completed global collection pass.
It contains operational wall-clock bounds and actual attempted-artifact outcomes
from the authoritative manifest/handoff; collection and verification remain
separate, and no aggregate evidence status or duplicate manifest is introduced.

Existing reusable surfaces are RuntimeEvidenceMessage,
NatsCommunicationBoundary.publish_evidence(),
InMemoryIngestor.receive_runtime_evidence()/compile_persistent_runtime_evidence(),
and PersistentStorageManager.write_evidence_archive(). StorageManager receives
the existing async publication callable, for example boundary.publish_evidence,
without owning the boundary, interpreting transport, or adding an evidence queue.

Controller coordinates Session processing finalization after acquisition end
and required post-session processing; ending one Experiment does not trigger
Session-wide collection. The explicit evidence-enabled sequence is stop_session(),
await collect_session_artifacts_with_evidence(), then finalize_session(). Generic
Ingestor compilation and archive writing are unchanged. finalize_session() rejects
an active collection/publication operation without waiting or mutating lifecycle.
Unavailable copied-size metadata is null and does not change retrieval/verification
outcomes or prevent later artifact attempts. Durable publication alone
does not guarantee Ingestor consumption before finalization; that Session-wide
guarantee remains OPEN in Q019, with no ACK wait or drain protocol implemented.
M013 is complete. W033 records manual software validation, the initial audit FAIL,
P1/P2 corrections, and final independent re-audit PASS. M011 remains open and
M012 remains complete; Q019 is not resolved by software closure.

Decision 303 resolves the former Q017 without changing these APIs or result
vocabularies: later global collection, verification, transfer, or export failure
cannot retroactively change a completed Session's lifecycle. Required
pre-completion failure handling remains unchanged, as does Q019's unresolved
Session-wide consumption/final archive coordination.
