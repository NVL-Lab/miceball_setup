# Installation And Deployment

## Status And Scope

Q022-A Decisions 367-376 are accepted and synchronized. Configuration/launching
and full independent-service adaptation remain pending; the bounded owner
persistence/readback foundation below is independently validated and audited
after correction (W051). This is the initial manual installation contract and a
current-interface reference, not a working installer or deployment certification.
The framework remains device-independent; a first camera deployment does not
define general adapter/configuration requirements. Q022 remains OPEN.

Decision 376 revises Decision 375: one Ingestor-StorageManager process runs on one
computer, with shared startup, shutdown, and restart lifetime. The two components
retain separate responsibilities, state, locks, and persistence authority and may
communicate through local Python calls. Controller, SynchronizationManager, and
each AcquisitionNode remain independently deployed; every process-crossing
interaction uses NATS. Controller accesses both combined-process components only
through NATS. No new registry, database, or scientific ownership is introduced.
The explicit local correlated persistence path is implemented with developer
coverage; independent validation and audit remain pending. Shared-lifetime
bootstrap/launch composition is not implemented in this bounded persistence slice.

## Accepted Manual Procedure

1. Install the common software package and dependencies needed by the chosen
   supported devices/services. Select the service role explicitly at launch;
   configuration does not implicitly start services. Final role CLI syntax is
   not yet implemented or prescribed.
2. Create installation-local configuration outside the Git repository from
   committed templates/definitions. Keep NATS/service storage/retrieval settings
   distinct from node hardware settings. Credentials and private keys stay outside
   Git and portable Session evidence.
3. Assign the node's persistent unique identity, identify installed devices,
   select adapters explicitly, and configure their physical connections and
   node-owned scientific storage. Do not infer hardware through discovery.
4. Configure key-based SSH/SFTP access and the StorageManager mapping from logical
   node identity to endpoint/authentication references. Verify connectivity,
   retrieve a small dummy file, and confirm retrieved bytes match the source.
   Required retrieval setup must succeed before the node is fully installed.
5. Add the identity to Controller's local known-node list and restart Controller
   to load it. Report duplicate identities as conflicts; do not launch against
   ambiguous identity. Coordinate restarts between Experiments without bypassing
   existing active-acquisition safeguards.
6. Start Controller, SynchronizationManager, and nodes independently, and start
   Ingestor and StorageManager together in their combined process. Verify node NATS connectivity and
   Controller-to-node readiness request/response through existing communication.
   Historical announcements are not current readiness; missing replies mean
   unknown availability, not confirmed failure or stopped acquisition.
7. Strongly recommend a device-appropriate acquisition smoke check: communicate,
   acquire representative data, inspect output/local persistence, stop safely,
   release resources, and record results. This is not a mandatory runtime gate,
   commissioning certificate, or universal acquisition-test interface.

Installation changes require service restart; live reload/registration is not
required. AcquisitionNode startup supports both a default local configuration
location and an explicit path. Exact syntax, file format, and default location
remain ordinary implementation choices. Future setup utilities must use the same
runtime file-loading/validation mechanism; no interactive installer is required.

Valid configuration is not proof of hardware readiness. Invalid/missing node
configuration must diagnose the problem and prevent acquisition. Existing readiness
reports actual hardware/service conditions. StorageManager validates local retrieval
configuration at startup but checks node connectivity when retrieval is requested;
temporarily offline nodes do not block its startup. Installation checks do not
require continuously reachable SSH/SFTP during scientific Sessions. NATS connection
alone does not establish durable Ingestor acceptance or Q019 completeness.

## Current Reusable Interfaces And Gaps

| Boundary | Existing foundation | Missing integration |
| --- | --- | --- |
| Package/launch | `pyproject.toml` builds one `lab-sync-acquisition` package, Python 3.12, with optional `artifact-retrieval`; scripts demonstrate manual startup | General explicit-role entry point and supported configuration bootstrap |
| Local configuration | Constructors accept NATS servers, journals, storage roots, retrieval endpoints, and node declarations | File loader, templates/definitions, startup validation, default/explicit node paths |
| Node/device setup | `AcquisitionNode`, `DeviceDeclaration`, `DeviceManager`, concrete adapters and retained deployment device settings | File-to-object construction and explicit supported adapter selection |
| Operator parameters | `SessionConfig.device_configurations`, node initialization overrides, adapter `initialize(config)` and concrete validation | Generic adapter-defined parameter constraints, inventory exposure, Controller readback |
| Readiness/startup | Existing node/service reports, NATS `check_readiness`/`get_inventory`, fresh announcements, `Controller.reconcile_outcomes()` | Load known-node identities from local files and integrate configuration diagnostics |
| Scientific retrieval | `SshRetrievalEndpoint`, configured node-to-endpoint mapping, StorageManager SSH/SFTP pull with host-key checks | Startup-local endpoint validation and explicit verified installation dummy retrieval |

Current demos and optional manual hardware checks are not a general installer.
Concrete camera configuration is an adapter example, not the generic parameter
contract. No principal-service package split, registry, database, plugin framework,
GUI, supervision, automatic discovery, or new readiness state is needed here.

Controller archival/collection and maintenance preservation currently use actual
Ingestor/StorageManager collaborators, including synchronous owner guards. They
are not remote APIs merely because NATS participant commands exist. Decision 376
permits local Ingestor-StorageManager calls but requires NATS for Controller and
other process-crossing access; adapting these paths is pending
implementation. Establish the necessary service-owned NATS interfaces before
enabling launch paths that depend on them. Missing responses, failures, and
timeouts must remain unconfirmed; retries must retain existing identity,
durability, idempotency, and recovery protections.

## Cross-Service Implementation Boundaries

This source assessment groups current interactions by receiving owner; it does
not approve new command names, payload schemas, distributed locks, or a generic
remote-object subsystem. Reuse `RuntimeParticipant`, `RuntimeCommandMessage`,
`RuntimeCommandResultMessage`, existing routing/streams, and
`NatsControllerCommunication.request_command()`/group outcomes. These already
correlate requester, receiving identity, Session, and command, with bounded result
waiting. Existing publication does not itself confirm receiver execution.

The call-path descriptions below identify existing owner responsibilities, not
separate processes for the combined pair. Ingestor-to-StorageManager and
StorageManager-to-Ingestor readback, release guards, compilation, and recovery
inputs may remain local under Decision 376. Only external callers require NATS
adaptation; do not replace permitted local synchronization with remote requests.

### Implemented Owner Persistence Foundation

The first bounded slice uses the existing command/result streams and owners:

W051 is historical validation of this NATS boundary, not a requirement to retain
internal NATS under Decision 376. Reuse local interfaces while preserving its
durability, stable identity, retry/conflict, restart, readback, corruption/legacy,
and archive/recovery guarantees. Do not duplicate owners or separate the pair's
process lifetimes. Local persistence is now supported by constructing the existing
Ingestor with its PersistentStorageManager owner and `correlated_persistence=True`.
`receive_envelope()` retains validated intake without an uncorrelated append;
`await persist_accepted_envelope(envelope, command_id=...)` performs the existing
owner's durable correlated write/readback locally. Keep command identity stable
on retry. Exceptions retain intake and do not establish confirmation. Legacy
constructor behavior and W051 NATS adapters remain compatible; no second owner
or internal NATS request is created by this mode. Both owners can be constructed
and restarted together by the same process; general lifecycle bootstrap is deferred.
Acquisition intake reconstruction/acknowledgment is not implemented here.
Independent validation and audit of this local adaptation remain pending.

- `NatsIngestorCommunication.persist_accepted_envelope(envelope, *,
  storage_participant, command_id, result_window_s)` sends already accepted
  current-Session intake to StorageManager, with no local StorageManager reference.
- `NatsStorageManagerCommunication(boundary, storage_manager).subscribe_commands()`
  receives `persist_envelope`, `read_envelopes`, and `read_session_preservation`.
  StorageManager executes its own methods and returns actual failure or current
  durability/readback results; missing products do not establish archival.
- Ingestor's existing command handler receives `compile_session_evidence` and
  `verify_acquisition_receipt`. Compilation requires current journal coverage and
  includes existing persistent evidence, complete intake audit, acquisition
  records/audit, and handoff. Receipt invokes the existing W041 owner proof.
- `NatsControllerCommunication(boundary).request_persistence_command(participant,
  command_type, session_id, payload, result_window_s, *, command_id)` handles these
  Session-scoped operations. It automatically adds an echoed transient
  `request_nonce` and uses fresh-only results, rejecting retained history and
  delayed replies from earlier attempts. A timed-out result is `None`, not success.

Keep the write `command_id` stable for identical retries. StorageManager retains
the command/requester/target correlation as `persistence_command` alongside that
envelope in its existing records JSONL. No new record file, evidence transport,
registry, or service owner is created. Distinct commands may preserve distinct
observations with identical values; conflicting reuse is rejected. Existing
envelope readback and final Session Records retain their ordinary envelope shape.
File flush/fsync, supported directory synchronization, and exact current readback
precede durability confirmation, including retries after StorageManager restart.
Corrupt/incomplete history is refused without rewriting or automatic repair.

The original in-process interfaces remain available. Network failure,
cancellation, missing replies, or a changed Ingestor binding cannot clear accepted
intake or establish false current persistence. This slice does not migrate
acquisition-side intake, Controller Stage A/Normal Stop/Kill orchestration,
framework evidence/maintenance, authorized recovery, or cross-owner release
commitment. Compilation/readback results are point-in-time owner observations,
not a distributed lock or permission to complete/release a Session.

Developer testing: 25 new owner-boundary tests and 7 directly impacted existing
regressions passed (32 total), using real framework adapters with broker doubles.
Independent manual validation passed initially (11/11) and after correction
(14/14). The initial audit failed for malformed persisted correlation allowing
duplicate writes; the correction passed 13 developer tests and final independent
re-audit PASS with no remaining confirmed P0-P3 findings (W051). Present correlation
must contain valid command/requester/target metadata; invalid history is refused
unchanged, and legacy records without metadata remain supported. Complete removal
of metadata cannot be distinguished from genuine legacy history.
Live NATS, multi-host, hardware, and independently tested power-loss guarantees
are not established. Configuration and role launching remain
unimplemented; Q022, Q024, Phase 16, and M015 remain OPEN and Q019 remains CLOSED.

### Acquisition Commands And Experiment Context

**Controller -> AcquisitionNode:** Local `start_session()`, `run_one_iteration()`,
`stop_session()`, `start_experiment()`, `_end_experiment()`, and release checks
directly read/control node runtime, Experiment context, health mapping, scientific
finalization, and device cleanup. Reuse existing inventory/readiness, reservation,
Session initialization/rollback, scientific-output preparation, and
start/iteration/stop NATS commands. Missing coverage includes remaining Experiment
context/health activation and end/finalization operations, current owner diagnostics,
and binding release where no equivalent command exists. The node must retain
Session-keyed reservations, terminal Experiment/file protections, device safety,
and W042 publication-before-success with concurrency-safe evidence cursors. A
timeout cannot prove cleanup or reservation release. Depends on receiving/timing
interfaces below, not creation of node collaborators in Controller.

### Timing And Synchronization

**AcquisitionNode/Controller -> SynchronizationManager:** Node readiness,
start/stop, acquisition timestamps, and Controller Experiment lifecycle timestamps
read a direct synchronization object (`current_session_time_s`, `start()`,
`stop()`). Mapping operations also remain SynchronizationManager-owned.
Reuse existing Session preparation/readiness, serialized local-time/mapping
records, and `NatsSynchronizationManagerCommunication` closing-Session timing
publication. Add the missing owner requests/readback or existing-mechanism
delivery needed for timing and mapping use; do not substitute NATS arrival/ingest
time for scientific Session time or instantiate a second authoritative clock.
**SynchronizationManager -> Ingestor/StorageManager:** `release_session()` and
`reconcile_timing()` inspect accepted mapping evidence, journal durability, and
framework archival through direct owners. Missing NATS evidence readback and
acceptance/preservation checks depend on the evidence-owner interfaces below.
Retain historical mappings, uncertainty, and the prohibition on untrustworthy
active-Session clock restoration. Local timing helpers are not new services.

### Producer Intake And Publication Confirmation

Decision 376 requires stable AcquisitionNode envelope-delivery identity and
durable intake correlation with journal-before-ACK and restart-safe deduplication.
Retries are not separate identical observations. Intake acceptance, local
StorageManager persistence confirmation, and archival completion remain distinct.

**AcquisitionNode/Controller/other producers -> Ingestor:** Node `_send_envelope()`
and `_record_artifact_manifest()` call intake directly; Controller decision and
Experiment-rejection evidence also use direct `receive_runtime_evidence()`.
Manifest recovery calls `has_durable_runtime_evidence()` on the same object.
Reuse existing evidence publication/subscription and producer retention, existing
acquisition-envelope serialization, and existing correlated commands/results.
Missing functionality is NATS delivery/owner responses for acquisition envelopes
and exact evidence-acceptance readback, not another evidence transport. Preserve
envelope validation/audit, sender handoff-failure policy, stable evidence identity,
same-content deduplication, retained-manifest retry, and journal-before-ACK.
Publication confirmation, Ingestor acceptance, and complete receipt remain distinct.
Depends on owner intake validation and StorageManager persistence forwarding;
do not turn Ingestor's internal framework partition into another service owner.

### Accepted Acquisition Record Persistence

**Ingestor -> StorageManager (local under Decision 376):** `receive_envelope()` directly invokes
`store_envelopes()`, and Controller later reads stored Session envelopes for the
Session Record. Ingestor owns acceptance and audit; StorageManager owns record
writing/readback. Reuse envelope serialization, existing persistent record APIs,
and local calls with authoritative results. Adapted local interfaces must report actual storage
outcomes and preserve Session/source association and existing failure semantics;
neither a transport ACK nor a missing result is durable storage confirmation.
Reconcile this local boundary before enabling acquisition intake that relies on it.

### Receipt, Compilation, And Kill Obligations

**Controller -> Ingestor:** `normal_stop_session()` and
`archive_acquisition_evidence()` require a local `NatsIngestorCommunication`
instance and matching Ingestor object. `_preserve_kill_closeout()` admits Kill
handoff obligations and reads current journal-backed evidence, acquisition
envelopes, and both intake audits. Reuse Ingestor's existing W041
`verify_acquisition_evidence_receipt()`, journal verification, persistent
compilation, and handoff compiler inside the receiving service. Missing NATS
operations expose their owner-confirmed results and admit obligations before
asynchronous shutdown, including empty intake. Preserve marker identity/sequence,
receiving origin, intact history, contiguous ACK proof, journal-before-ACK,
Session isolation, and explicit Kill incompleteness. Missing/invalid proof is not
complete receipt. Depends on producer/record intake; no Controller-owned consumer
or receipt reconstruction is needed.

### Stage A, Session Records, Handoff, And Binding Release

**Controller/Ingestor -> StorageManager:** Controller directly writes Stage A,
partial Kill preservation, initial/final Session Records, and the handoff, then
reads preservation confirmations; completion/release compare current Ingestor
contents with durable products under shared guards. Ingestor `release_session()`
likewise uses `session_preservation_guard()` and handoff readback directly.
Reuse StorageManager writers, persisted-product validation/readback, and NATS
request/results. Missing handlers must preserve exact compilation/audit/envelope
coverage, final-record Session identity, marker provenance, fsync/readback,
non-overwriting handoff semantics, and immutable historical/closed contents.
Adapt completion and release to trustworthy current owner confirmations, not
cached flags, borrowed remote context managers, or shared locks. Revalidate
Session/operation identity after network waits; late accepted or rejected intake,
cancellation, and stale release must not bypass obligations or retire a new
binding. Depends on Ingestor receipt/compilation and StorageManager persistence
interfaces; Stage A is not collection or permanent closure.

### Partial-Handoff Refresh And Authorized Recovery Inputs

**StorageManager -> Ingestor:** `refresh_partial_artifact_collection_handoff()`
directly reads journal-backed compilations, handoff contents, administrator
authorization, and actual scientific-recovery evidence. Archive/transfer recovery
also reads trusted compilation/manifests through maintenance's Ingestor object.
Reuse existing compilers/acceptance verification and the already routed
obligation-scoped recovery commands. Missing NATS readback must establish exact
scope and trustworthy inputs before StorageManager acts under its own preservation
and collection guards. Preserve prior evidence/audit prefixes, authorization and
execution correlation, refusal of ambiguous inputs, no automatic refetch, and
handoff immutability once any collection attempt begins. Depends on evidence
confirmation and maintenance authorization interfaces, not an unrestricted
replacement-handoff operation.

### Saved-Session Collection And Permanent Closure

**Controller -> StorageManager:** Single/multi-Session collection directly calls
`get_saved_session_collection_status()` and `collect_saved_artifacts()`; listing,
handoff readback, and `close_session_evidence_archive()` are local StorageManager
APIs rather than remote service operations. Reuse those APIs through scoped NATS
owner requests/results. StorageManager independently enumerates/validates saved
products, rechecks eligibility/availability under collection guards, and retains
stable per-Session evidence IDs and durable outcomes before direct Stage B archival.
Do not send Stage B evidence through Ingestor merely to archive it. Preserve
failure isolation, per-Session results, aggregate reporting, authorized interrupted
write recovery without refetch, and separate explicit permanent closure with
restart-safe immutability. Existing SSH/SFTP file retrieval remains a
StorageManager persistence mechanism under Decision 373, not a Python call to an
AcquisitionNode service owner. Depends on preserved baselines/handoffs, but not
restoration of old Session runtime bindings.

### Framework Maintenance, Recovery, And Reconciliation

**Each service's maintenance interface -> Ingestor/StorageManager:**
`_preserve_message()`, `_require_recovery_authorization()`, retirement guards,
and owner diagnostics directly await journal acceptance, inspect archive safety,
compile/write/read archives, and share intake/persistence locks. Controller
`reconcile_outcomes()` and SynchronizationManager `reconcile_timing()` also use
direct acceptance/archival readback. Reuse fresh readiness subscriptions, startup
reconciliation, bounded correlated maintenance/recovery commands, retained
producer evidence, and existing owner-local recovery/preservation methods.
Missing NATS requests must distinguish publication, durable acceptance, current
archival, actual execution, and remaining obligations. Decision 347 requires
authorization and attempt acceptance before repair, without circular dependence
on successful repair of the unavailable archive. Unsafe archives cannot be
silently repaired by startup. Owner admission/retirement checks must remain
effective across asynchronous callbacks; prepared retirement requires complete
evidence and audit coverage without a new post-Ingestor dependency. Cross-service
dependent callbacks and Controller shutdown's direct owner-identity checks also
need owner-reported confirmations, not assumed shared objects. Depends on the
evidence/persistence interfaces before independent-role startup is fully enabled.

## Recommended Implementation Order

These are proposed implementation boundaries, not additional accepted architecture
or claims of implementation/validation:

1. Reconcile the combined process using existing local persistence/readback
   interfaces with W051 guarantees, and owner-side NATS intake, acceptance,
   receipt/compilation and external readback operations using existing
   envelopes/routing. Test exact identity, duplicates/conflicts, journal/ACK and
   write failure, missing/stale results, cancellation, and receiving-owner guards.
2. Adapt acquisition/Experiment and synchronization interactions to those
   interfaces and existing node commands. Test scientific timing, parameter/context
   isolation, local finalization, sender failures, reservations, and producer
   publication-before-completion without duplicate service owners.
3. Adapt Q019 Controller Normal Stop/Kill, Stage A/handoff, completion/release,
   saved collection, and explicit closure coordination. Test current coverage,
   network-wait races, late intake, partial Kill, restart readback, batch isolation,
   idempotency, and archive immutability using independently owned services.
4. Adapt framework startup evidence, reconciliation, maintenance and authorized
   recovery, including partial-handoff refresh and prepared retirement. Test
   durable authorization/attempt before action, missing results, failed cleanup,
   corrupted archives, pre-collection refresh, and no post-retirement self-write.
5. Enable configuration/explicit-role bootstrap only after its required remote
   interfaces exist; wire local known identities, adapters, validated paths and
   retrieval settings, then installation checks. Configuration parsing/templates
   can be prepared independently, but may not implicitly instantiate other owners.
   Validate role isolation, invalid files, offline nodes, fresh readiness,
   Controller restart reconciliation, and verified installation dummy retrieval.

The former ownership/transport question is resolved. The principal implementation
risk is preserving current cross-owner coverage and admission guarantees across
network suspension: local locks must remain local, and cached confirmations must
not replace final owner verification. Any essential guarantee that cannot be
satisfied within existing contracts must return through ICC for clarification;
this assessment does not select a distributed transaction or new recovery system.

## Validation Boundaries

Future implementation needs focused software tests of configuration loading,
role selection, explicit identities/adapter construction, parameter constraints and
successive Session isolation, startup/readiness communication, and installation
dummy retrieval. Test invalid configuration, ambiguous known identities, offline
nodes, mismatched dummy contents, and failure diagnostics without manufacturing
scientific readiness or evidence acceptance.

Independent manual validation and source audit follow implementation under the
authoritative workflow. Real deployment/device validation remains separately
identified. Q019 is CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN. Historical
validated workflows and existing service ownership/safety contracts are unchanged.
