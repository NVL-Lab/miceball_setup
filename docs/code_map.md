# Code Map

## Accepted Q022-A Installation Contracts (Not Implemented)

Decisions 367-378 accept one installed package with explicit role launching,
file-based local service/node configuration, explicit adapters and persistent node
registration, adapter-defined Session-adjustable parameters, and manual installation
verification. See [installation_and_deployment.md](installation_and_deployment.md).
Existing constructors, `AcquisitionNode.declared_devices`/readiness,
`SessionConfig.device_configurations`, adapter initialization, NATS inventory and
readiness commands, `NatsServiceMaintenanceCommunication.start()` with configured
participants, `Controller.reconcile_outcomes()`, and StorageManager endpoint/pull
interfaces are reusable. There is no general role CLI, deployment file loader,
generic adjustable-parameter inventory, or installation dummy-retrieval interface
yet. Configuration validity is not hardware readiness; device smoke tests are
recommended, not commissioning/runtime gates. Q019 remains CLOSED; Q022/Q024/Phase 16/M015
remain OPEN.

Decision 376 revises Decision 375: Ingestor and StorageManager share one process,
startup/shutdown/restart lifetime, and permitted local calls while retaining distinct
ownership. Controller, SynchronizationManager, and nodes remain independently
deployed; all process-crossing interactions, including Controller access to both
components, use NATS. Bounded remote single saved-Session collection is closed in
W058; remaining Controller/Ingestor/StorageManager closeout,
enumeration/batch collection, release, and maintenance/recovery paths
still use development-time direct collaborators and cross-owner guards; these
are not deployed remote interfaces. Reuse existing command/result envelopes,
participant identities, correlated requests, evidence publication, receipt proof,
and owner-local validation/persistence. See the cross-service dependency map and
recommended implementation order in
[installation_and_deployment.md](installation_and_deployment.md). NATS publication
alone is not acceptance, complete receipt, or archival. Historical Q019 validation
remains intact.

## Durable Operational Evidence Transport (Closed, W057)

AcquisitionNode-to-Ingestor NATS operational evidence intake and exact
`read_runtime_evidence_acceptance` readback are independently validated and audited
PASS in W057. Existing journal, durable consumer, deduplication and binding guards
remain authoritative. Publication, acceptance, W041 receipt and StorageManager
archival are distinct; scientific observations stay node-local and acceptance
does not authorize artifact release. Subject consistency is not authentication;
optional callbacks are not a durable retry queue. Broader Controller/recovery
and deployment integration remain open, as do Q022, Q006/Q018, Q024, Phase 16 and
M015. Q019 and W001-W056 closure records are unchanged.

## Remote Saved-Session Collection (Closed, W058)

`Controller.collect_saved_session_artifacts_remote()` uses
`NatsControllerCommunication.request_persistence_command()` and
`NatsStorageManagerCommunication.subscribe_commands()` for one explicitly selected
saved Session without local owner references. StorageManager's
`get_saved_session_collection_status()` and `collect_saved_artifacts()` retain
eligibility, preservation, locking and retrieval authority. Fresh-only commands,
complete scoped result-history checks and same-nonce identity conflict rejection
resolve all three P2 findings; exact durable outcomes permit retry/restart reuse
without refetch. Independent IPython validation and final audit PASS of d788d2e
are recorded in W058. This is not full remote closeout, enumeration/batch,
closure/release or maintenance/recovery. Scientific observations stay node-local;
Stage B evidence stays StorageManager-owned. Q022 remains OPEN.

## Remote Saved-Session Evidence Archive Closure (Closed, W059)

`Controller.close_saved_session_archive_remote()` requests one saved archive's
explicit permanent closure through existing NATS command/results without local
Ingestor/StorageManager references. `NatsStorageManagerCommunication` admits both
new and retained-success requests through complete scoped-history validation,
rejects identity/resolution conflicts, and requires current matching owner readback.
StorageManager's existing `close_session_evidence_archive()` retains locks,
consistency checks and durable summary publication. Repeated success does not
rewrite closed products; retained rejection is not readmitted after prerequisites
change. Closure does not terminate Sessions or release services/resources.
W059 records original developer 67 tests PASS, independent IPython 4/4 PASS,
the cached-history P2 correction, correction IPython 3/3 PASS and final focused
audit PASS of 31b2c7e. Corrective runtime attempts stalled in the sandbox without
results; no correction automated passes are claimed. Broader Q022 remains OPEN.

## Distributed Synchronization And Experiment NATS Integration (Complete, W056)

Decisions 379-381 resolve the minimum Q022 Slice 2 synchronization architecture:
SynchronizationManager measures cross-clock exchanges accounting for network
delay, variability and uncertainty, and alone determines mapping validity and
replacement. Initial clock-rate assumptions must be explicit and conservatively
bounded. AcquisitionNode applies the authorized affine mapping locally,
atomically and prospectively, preserving required scientific timing, mapping
history and node-local activation boundaries without per-observation mapping IDs.
Session acquisition readiness and each Experiment require acceptable
synchronization; periodic quality assessment is configurable and distinct from
complete resynchronization. Degradation preserves local timing/provenance and
explicit degraded status, with existing policy/Controller consequences.

The Slice 2 implementation now wires measured synchronization into launched
Session startup, local scientific timestamping and launched Experiment
preparation/context/finalization. Remote nodes use an explicit
`synchronization_source_id`, without a local SynchronizationManager or Ingestor
owner. Existing direct-owner workflows remain supported for in-process use.
Configuration is explicit in SessionConfig.synchronization_configuration; causal
exchange bounds include measured clock resolution, delay/variability and the
configured rate-error bound, without assuming symmetric delay. Periodic assessment
does not replace mappings; explicit resynchronization can replace them. The
supported degraded condition uses the configured interpretation label and records
a Controller-owned decision, not automatic termination. Independent validation
and final audit PASS are recorded in W056, including historical quality,
periodic publication recovery and rejected-stop admission corrections.
Advanced Q006/Q018 work remains open; W001-W055 and
Q019 CLOSED are preserved; Q022, Q024, Phase 16 and M015 remain OPEN.

W051/W052 remain historical validation of superseded NATS/local scientific-envelope
persistence. Slice 3B removes that intake, correlated persistence and dispatch,
without replacing scientific transport. Operational RuntimeEvidenceMessage
identity, journal-before-ACK, deduplication/reconstruction, receipt, compilation
and preservation readback remain active. Fresh-only results and per-attempt
nonce correlation protect the retained NATS readback operations. StorageManager
now takes an explicit directory `storage_root`; it owns Session Records,
Evidence Archives and scientific-artifact collection, not observation appends.
Lifecycle bootstrap, remaining cross-process Controller/maintenance adaptation,
configuration and role launching remain outstanding; Slice 2 timing/Experiment
runtime integration is described below.

The bounded product-acquisition replacement is complete with independent manual
validation and final re-audit PASS after the scientific-observation-loss correction
(W053). All completed scientific collections receive preservation attempts before
operational intake; independent errors remain failures without automatic replay.
`collect_products()` follows installed
declarations and Experiment selections; node scientific observations and their
metadata go only to LocalStorageManager. Node envelope forwarding/batching is
removed; lifecycle, health and failure RuntimeEvidenceMessages use retained,
serialized durable publication before command responses. Slice 3B reconciles owner
closeout against current operational evidence/audit and manifest coverage, retaining
plain historical Session Record validation without legacy writers. This bounded
replacement is complete after independent validation and corrective re-audit PASS
(W054). The combined Decision 377-378 replacement is implemented and accepted in
W055 after functional audit PASS and targeted correction of the sole residual P3.
No future streaming or deployment validation is claimed.

Decision 378 now requires clean replacement: installation declarations and
Experiment selections govern supported adapter scientific production and local
persistence, separately from operational evidence without content/size/name
heuristics. Legacy collection contracts, scientific-envelope transport/persistence/
audit/recovery/compatibility machinery, and dead functions/types/tests must be
removed when no accepted responsibility remains. Entries below map existing code,
not approved target APIs. Retain operational evidence and historical-readback
responsibilities; preserve Q019 guarantees. W055 records the combined functional
audit PASS, initial clean-replacement FAIL, and subsequent removal of the obsolete
HealthFakeAdapter constructor setting with nine targeted tests PASS. The user and
ICC determined that no further independent re-audit was needed for this test-only
cleanup; the completed replacement is accepted, not a new post-correction audit PASS.

W054 records initial developer verification (841 passed, seven optional skips),
independent validation, initial audit FAIL for the P2 release race and P3 obsolete
test configuration, both corrections, and final corrective re-audit PASS. Corrective
developer checks passed 32 focused tests and 847 full-regression tests with seven
optional skips; independent re-audit passed 25 tests and ten probes. These are
separate overlapping runs, not complete deployment; final Decision 377-378
implementation acceptance is recorded separately in W055.

Q019 is CLOSED following W041-W049 slice completion and W050 overall software
integration validation/audit PASS. The permanent sequential Normal Stop regression
uses Session-filtered test delivery; no production API changed during closure.
Q022, Q024, Phase 16, and M015 remain OPEN. Hardware, multi-host deployment,
external NATS deployment, and power-loss guarantees are not established by this closure.

## Accepted Q019 closeout architecture (W041-W049 bounded slices validated; overall software integration validated in W050)

Decisions 356-365 qualify historical Session closeout and collection-evidence
contracts. The accepted flow is producer publication confirmations, one
Controller Session-scoped completion marker, independently verified Ingestor
consumption, and Stage A acquisition evidence/audit/summary plus final Session
Record preservation. Stage A permits successful completion and applicable binding
release without waiting for scientific collection. StorageManager durably preserves
Ingestor's existing handoff for later operator-selected stopped-Session collection
without restoring original bindings; its own collection evidence is directly
appended in Stage B with distinct summary provenance. Permanent closure requires a
separate explicit operator request, all applicable collection outcomes durably
recorded, no unresolved evidence writes, and verified consistent durable archive
preservation. It does not require every artifact to be retrieved or verified;
confirmed closed archives are immutable, including after restart. W046 explicit
closure is complete with independent manual validation and targeted independent
re-audit PASS after correction. Closure is separate from collection outcomes and Session lifecycle.
Decision 361 requires restart-safe Session-specific receiving progress and verified
contiguous JetStream acknowledgment coverage of the full relevant publication
interval. Decision 362 records stages/closure in the existing summary, requiring
verified consistent durability rather than trusting a status field. Decision 363
requires temporary durable outcome/evidence-ID preservation before direct archival,
duplicate protection, and safe evidence-write recovery without transfer replay.
Decision 364 specifies a separate small JSON handoff in the existing Session
directory, validation after restart, and existing persistent Session information
for selection. No exact filename, new API, or registry schema is specified.
Decision 365 requires complete Normal Stop confirmations; authorized Kill Session
preserves explicitly partial information and existing safety without automatic
collection or permanent archive closure. Unknown outcomes remain unconfirmed.

W048's synchronized clarification in Decisions 113, 362, 364, and 365 uses canonical
`experiment_abort` for an active Experiment during Kill Session, separately records
unconfirmed cleanup, preserves available evidence without inventing completeness,
and permits later operator-requested collection from available verified artifact
information. Bounded W048 Kill and partial preservation are complete with independent manual validation and final re-audit PASS after corrections.
Decisions 034/365 permit Kill to transition the Session to `aborted` despite
unconfirmed participant cleanup. `cleanup_occurred=True` denotes the Session's
local cleanup procedure only; participant cleanup, hardware safety, and resource-
release obligations remain separately represented and protected by existing safety
and authorized recovery requirements. This does not weaken Normal Stop guarantees.
The complete-receipt Stage A writer retains its Normal Stop checks. A separate Kill
entry point preserves available journal-backed evidence, the intake audit, final
aborted Session Record, explicit uncertainty, and the existing handoff without
claiming complete receipt or releasing participant reservations. Persisted partial
baselines support later collection without original runtime bindings.
Decision 364 permits a partial handoff to incorporate additional verified manifest
evidence from authorized recovery only before the first Stage B collection attempt.
Refresh must preserve existing evidence, follow the Ingestor compiler, and confirm
durability. Beginning any collection attempt, including failed or incomplete
attempts, makes the handoff immutable; historical evidence, collection outcomes,
and permanent archive closure cannot be rewritten. Refresh checks existing durable
administrator/recovery evidence, appends new accepted evidence and audit without
changing historical bytes or the final record, and verifies handoff/summary readback.
The existing summary durably records collection start before partial-handoff
retrieval. Collection, refresh, closure, and archive repair serialize on the stable
final record using nonblocking OS file locks as well as the existing owner lock;
no lock file is introduced. Interrupted writes require explicit existing authorized
archive repair, including for an explicitly identified partial archive after restart.
W048 is complete with targeted developer testing, independent manual validation, and final re-audit PASS after corrections. No new lifecycle state, infrastructure,
automatic collection, or implicit archive closure is specified.

Admitted Kill obligations are retained before asynchronous shutdown, independently
of archive success. Ingestor release requires matching durable handoff and evidence
coverage even with empty intake or unavailable confirmation. Kill retry and
Controller release reject current operational evidence/audit not represented in
durable preservation; final Session identity/lifecycle and historical contents
remain protected. Repeated Kill reports verified durable closure state.
W048 records both failed audit rounds, their corrections, and the final PASS.

Decision 366's supported publication prerequisite is complete with automated
coverage, independent manual validation, and targeted independent re-audit PASS
after the cursor-race correction (W042): participating
AcquisitionNodes publish applicable evidence before existing successful completion
responses, regardless of selected-device optionality. Controller and
SynchronizationManager complete applicable closing-Session publication before the
single marker; Ingestor's locally journaled evidence needs no JetStream round trip.
AcquisitionNode command handlers now publish evidence before results and retain
unconfirmed publications for explicit later operations. No separate producer
confirmation message is added; W041's receiving foundation remains unchanged.
After existing stop orchestration, callers explicitly invoke
`Controller.publish_acquisition_evidence_completion(communication=..., result_window_s=...)`.
It requires a stopping Session, confirmed cleanup, correlated successful node stops,
and one configured synchronization participant. Active or unconsumed Controller
health inputs block publication without polling or replay; current retained broker
history is read back when a health subscription exists. Controller closes only its
own Session publication boundary and publishes retained decisions, rejection
evidence, and unconfirmed scoped publications before the stable marker. Interrupted
publication retains message identities; later explicit calls can republish identical
messages, while confirmed repeated calls do not emit another marker. No receipt,
archival, successful Normal Stop, or Session completion is claimed by this API.

The receiving foundation, producer/marker prerequisite, and bounded Stage A
archival are validated in W041-W043; bounded Normal Stop integration is complete
with independent validation and targeted re-audit PASS after correction (W047).
W048 Kill is complete with independent manual validation and final re-audit PASS after corrections;
overall Q019 software integration validation is complete in W050.
The function entries below also describe historical paths, including Ingestor-routed
collection evidence and stopping-Session collection before finalization. Do not
interpret those implementations as Stage A/Stage B or Kill Session support.
Session intake binds a durable explicit-ACK JetStream consumer to the existing
journal, preserving journal-before-server-confirmed-ACK and known-Session
deduplication/recovery. `verify_acquisition_evidence_receipt(marker)` checks exact
journal-backed marker acceptance, original stream/consumer identity, retained
history, and contiguous ACK progress, with asynchronous readback rechecks. It reads
Session-matching broker publications through the marker and reconciles their exact
identities/content against the current retained journal, not message-count equality.
Content and duplicate-ID comparisons reuse Ingestor's canonical serializer and
preserve JSON type distinctions, including both marker checks.
Ingestor holds its intake lock through the final synchronous confirmation, rejecting
missing, incomplete, conflicting, or unverifiable journal coverage without repair.
The minimal marker uses the existing RuntimeEvidenceMessage with evidence_type
`acquisition_evidence_completion`; this readback does not certify producer
confirmations, Normal Stop completeness, or archival preservation.
Without a trusted narrower Session interval, confirmation requires intact stream
history from sequence 1. Missing/truncated history (even unrelated history), unknown
original receiving position, consumer replacement/configuration drift, or broker
failure remains unconfirmed; a missing durable position is not silently repaired.
The receipt foundation and disjoint routing prerequisite are complete with automated
testing, independent manual IPython validation, and final independent re-audit PASS
after both corrections (W041), using isolated local JetStream and controlled doubles.
Verification has linear broker-history read cost; no external-cluster or hardware
validation is claimed. W042 separately closes the producer/marker prerequisite.
The bounded Stage A archival slice is complete with developer automated testing,
independent manual IPython validation, and independent audit PASS (W043).
After W042 publication, use
`await controller.archive_acquisition_evidence(communication=ingestor_communication)`.
It verifies W041 receipt, protects current journal/intake coverage, and passes the
existing persistent compilation and actual Session Record evidence to StorageManager.
The existing summary adds `stage_a_complete`, `archive_closed=False`, marker identity/
sequence, and Ingestor evidence-origin IDs. Current exact readback of all products
and the final Session Record is required; a status flag alone is not confirmation.
Intake, storage, and Controller admission locks cover synchronous persistence/commit
in that order, with no lock held during asynchronous receipt verification.
The Session remains stopping and bound; no handoff is written or resources released.
Interrupted writes require existing authorized recovery, not ordinary retry repair;
retry after incomplete receipt and repeated healthy Stage A writes remain supported.
The bounded Decision 364 handoff slice is complete with developer automated testing,
independent manual IPython validation, and independent audit PASS (W044). After Stage A, explicitly
call `controller.preserve_artifact_collection_handoff()`; protected journal/intake
compilation is persisted separately as `session_<session_id>/artifact_collection_handoff.json`.
StorageManager uses fsynced same-directory temporary contents, non-overwriting
hard-link publication, supported directory fsync, and exact readback. Identical
retries reconfirm durability without rewriting; conflicting/corrupt files are
refused. Unconfirmed writes remain visible in existing unfinished-record diagnostics.
`storage.read_artifact_collection_handoff(session_id)` validates known-Session
readback after restart without original runtime bindings. Applicable Q019 Controller
and Ingestor release guards require current handoff coverage. Legacy non-Q019 release
paths are unchanged. No lifecycle completion or release is performed by preservation.
Bounded Stage B collection/direct evidence persistence is complete with developer
automated testing, independent manual validation, and final targeted independent
re-audit PASS after correction (W045). The initial audit failed on two P2 findings;
corrections block inconsistent provenance from authorizing archive replacement and
reject cross-Session envelopes or incomplete intake audit as a trusted baseline.
`Controller.collect_saved_session_artifacts(session_id, evidence_id=...)` delegates
to StorageManager without restoring a Session binding. Persisted evidence, audit,
summary, final record, and handoff establish a known-Session baseline after restart
or another Session's archival; file/supported-directory fsync and reread reconfirm
durability without content replacement. Collection uses existing retrieval/light verification.
`artifact_collection_outcome.json` temporarily retains the existing collection
message and stable caller-supplied identity before direct append; summary origin
IDs distinguish Ingestor evidence from StorageManager evidence. Original acquisition
bytes, audit, final record, and handoff remain unchanged. Current readback, not a
status flag, confirms preservation; no JetStream publication or invented audit is used.
An identified pending append requires the existing authorized `recover_archive_write`
operation with `obligation={"session_id": ..., "evidence_id": ...}`. It can complete
only the matching append/summary, never refetch artifacts or rewrite confirmed
history. Unknown interruption outcomes are distinct from proven scientific loss.
The existing preservation lock serializes owner operations; known-Session lookup
does not discover all pending work. This does not support multiple simultaneously
authoritative StorageManagers sharing a directory. Explicit permanent closure is
available through `storage.close_session_evidence_archive(session_id)`; it validates
current products under the preservation lock, atomically publishes a fsynced summary,
and reconfirms all products before returning. Failed/unknown artifact outcomes do
not block closure when their evidence is durable. Pending writes or inconsistent
products do block it. Repeated/restarted requests reconfirm closed contents without
rewriting them. Generic final-record writing and authorized recovery honor closure;
record serialization/write is serialized with closure. W046 is complete: initial
developer tests 27/27 and independent manual validation 8/8 PASS; initial audit FAIL
for the unresolved-path guard; normalized target/root correction with developer
tests 6/6 and independent validation 2/2 PASS; final targeted re-audit PASS with no
remaining confirmed P0-P3 findings. Historical failure and correction are retained.
Bounded Normal Stop is complete in W047; W048 Kill is complete with independent validation and final re-audit PASS after corrections. W049 eligible-Session selection is complete with independent manual validation and final independent audit PASS after correction;
overall Q019 software integration validation is complete in W050.
W033/M013, W035, W039, and W040 retain
their validated scopes. Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN. No
additional architectural API or storage schema is defined here.

## Phase 16 accepted responsibilities (binding release, maintenance, shutdown, and startup/return slices complete)

The implemented historical Decision 323 uses the Evidence Archive's deployment-scoped
`framework/evidence/` partition for Session-independent runtime evidence with
`session_id=None`. It requires exact evidence/audit/summary preservation without
a Session Record. Individual-service stop/kill/cancel remains separate from
Session-binding release and coordinated framework shutdown; W036 records its
completed software validation and independent audit.

Decision 354 now supersedes that shared framework layout architecturally with
`framework/evidence/YYYY-MM/` partitions; implementation still uses the shared
path. Decisions 349-350 and 353-355 are accepted, not implemented or validated.
Supported Decisions 351-352 startup reconciliation is complete, independently
manually validated and independently re-audited PASS after correction in W040.
Q024-B remains complete in W039 and Decision 336 remains partially implemented.

The existing `InMemoryIngestor.compile_framework_runtime_evidence()` and
`framework_preservation_guard()` operate on cumulative retained evidence/audit.
`PersistentStorageManager.write_framework_evidence_archive()` rewrites the shared
products; `get_framework_preservation_confirmation()` reads and compares their
entire current contents. Maintenance preservation guards and Controller
reconciliation depend on those confirmations. Monthly archival and safe historical
deletion therefore require clarified cross-month coverage/lookup dependencies;
current code does not establish independence from deletable history. Q024 records
these gaps without specifying a new recovery subsystem or API. Q019 final closure,
Q022, Phase 16, and M015 remain open.

### Decisions 351-352 startup integration (complete, independently validated and audited)

W040 records ICC review, independent manual validation and correction revalidation,
the initial failed audit, and final independent re-audit PASS after both corrections.
This completes only the supported startup reconciliation/reservation-protection slice.

The existing `NatsServiceMaintenanceCommunication.start()` now invokes Controller
reconciliation automatically after startup subscriptions and announcements. Known
remote identities come from explicit `startup_participants`, or the existing
configured dependency participants when no broader scope is supplied; this is not
discovery or a registry. A nonempty scope requires explicit positive
`startup_result_window_s`, bounding publication and result waiting for each existing
`check_readiness` request. A bare Controller constructor performs no remote startup
or discovery, and an empty configured scope cannot identify omitted participants.

Startup evidence uses the already configured maintenance RuntimeParticipant identity
and Ingestor/StorageManager dependencies; ordinary Session orchestration still
requires its own explicit collaborators. Current correlated replies carry
existing service-owned diagnostics. Node reports
keep actual acquisition/failure, Session binding/reservation, local finalization,
manifest acceptance, and device cleanup separate. Controller reports active,
stopped, failed, or unknown observations and owner-reported Session identities,
not Session replicas or inferred participant completion. Node conditions derive
from actual running/failure flags; other service conditions use explicit operational
retirement confirmation, not technical readiness alone. Legacy readiness-only
replies lacking these conditions remain unknown. Each participant is
independent; missing/failed communication stays unknown without stopping acquisition
or releasing reservations. Repeated unchanged findings reuse reconciliation evidence
through the existing framework preservation path. Existing separately authorized
Q024-B preservation/cleanup and Session-keyed release remain owner-guarded; no new
coordinated recovery command or canonical Session restoration is implemented.

Startup/readiness announcements retain and journal new evidence before checking
existing archive safety under the preservation locks; damaged or unconfirmed
products remain untouched and generate preservation warnings, not automatic repair.
Optional malformed diagnostic collections do not prevent observing other participants.

Decisions 304-321 establish Session-independent and GUI-independent lifetime for
Controller, AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager.
Session-specific collaborators remain subject to existing creation, binding,
cleanup, and bounded-memory contracts; DeviceManager and DeviceAdapters are not
new independently operating services. This is not a claim that all current
collaborators already implement successive-Session reuse.

Controller coordinates general framework shutdown through existing
distributed command/result boundaries; individual administrative service
maintenance may be independent through a local interface. Participants retain
closeout ownership and independently release confirmed Session bindings under
Decision 313. These responsibilities are distinct from implemented Session
stop/finalization and must not initiate collection, verification, transfer, or
export. Decision 325 accepts an explicit Session-independent `RuntimeParticipant`
scope, an informational local `check_stop_readiness` survey, and sequential
dependency-safe stops with blocker evaluation at each actual stop command.
SynchronizationManager retires before Ingestor, then StorageManager and Controller;
each blocked service requires separate kill authorization, without restarting
already stopped services. Controller preserves required coordination evidence
while Ingestor and StorageManager remain available. This coordinated shutdown
implementation is complete, manually software-validated, and independently
re-audited PASS (W037). Decision 326 accepts a coordinated
`prepare_stop` operation for StorageManager followed by Controller while Ingestor
is operational: actual cleanup results and the final preservation checkpoint are
archived before Ingestor retirement. Preparation is not operational retirement.
Prepared StorageManager and Controller then retire in the accepted order without
invoking retired evidence capabilities; later confirmations are retained through
existing command/results, not described as newly archived evidence. The
prepared-retirement guards require complete current Evidence Archive coverage of
Ingestor's retained final persistent evidence and all intake audit, including
rejected, duplicate, and nonpersistent-message intake. They check before and after
asynchronous callbacks and hold preservation/admission locks through commitment;
missing coverage prevents orderly retirement confirmation. No synchronous lock
spans an await and no new post-Ingestor archival obligation is introduced.
`Controller.shutdown_framework()` coordinates these stages; W036 remains unchanged outside
coordinated shutdown. Decisions 318-319 accept Session-independent
framework evidence through existing infrastructure, not a separate evidence system. Independent
startup/readiness and returning-service recognition do not resume interrupted
work. Q025 is resolved architecturally; Q019 is CLOSED in W050; Q024 remains open.
Individual-service maintenance now has a narrow implementation through the
target-owned ServiceMaintenanceInterface and existing participant commands.
It is manually software-validated and independently audited PASS (W036). Progressive
two-phase coordinated shutdown is separately validated in W037; independent
startup/returning-service integration is complete and separately validated in W038.
Phase 16/M015 remain open;
W035's Session-binding release validation is unchanged.

Decisions 327-331 now accept and synchronize startup/return announcements using
existing RuntimeParticipant/ServiceReadiness contracts, direct configured-dependency
updates, protected reuse, and framework evidence for unresolved work and explicit
administrator decisions. This narrow startup/return implementation slice is complete,
independently manually software-validated, and independently re-audited PASS (W038)
after correction of the two initial P2 readiness findings.
Existing service-owned administrative,
NATS, readiness, and framework evidence interfaces are extended below, without
a registry or another service-management component. Execution beyond supported
Q024-B cases remains Q024,
deployment/discovery details remain Q022, and Session-wide consumption remains Q019.

### Q024 narrow implementation (complete, independently validated and audited)

The narrow Decisions 332-338 implementation slice has automated coverage,
independent manual IPython validation PASS (10 scenarios), and independent read-only
source audit PASS with no blocking findings, as reported for documentation closure.
Decision 336 remains partially implemented: only guarded release of redundant
producer-owned evidence copies. No new validation was executed during closure.

Decisions 332-338 now have service-owned `maintenance_diagnostics(ingestor,
storage_manager)` readbacks on Controller, AcquisitionNode, InMemoryIngestor,
PersistentStorageManager, and SynchronizationManager. Existing `check_readiness`
results and changed readiness evidence carry these owner-specific diagnostics,
not a universal recovery schema. Actual completion, administrative abandonment,
recoverability assessments, and affected/broader restrictions remain distinct.

Explicit drop adds an abandoned obligation outcome to the existing administrator
decision evidence without executing recovery or claiming cleanup. After current
complete framework archival, exact journal-backed acceptance, and existing
resource/closeout/admission checks, a drop referencing an `evidence_id` or
`stop_attempt_id` may retire redundant interface-owned producer evidence copies.
Intake, archival, and admission locks protect that synchronous memory commitment;
no lock spans publication or an await. Administrative decisions, command/result
and attempt history, resource guards, scientific records, and journals remain.
The actual release checkpoint is retained before submission; failure to archive
that checkpoint leaves a visible preservation obligation, not an invented undo.

Reporting is informational and does not authorize unrelated work; existing owner
guards remain authoritative. Resource-specific abandonment/cleanup beyond the
supported Q024-B cases below, wider cache retirement with undefined idempotency
lifetimes, and application recovery remain deferred. W035-W038 are
unchanged; this narrow implementation slice is complete, independently validated,
and independently audited. Broader Q024 application recovery, journal lifecycle,
and execution/cleanup beyond supported Q024-B cases remain OPEN. Q019, Q022,
Q024, Phase 16, and M015 remain open.

### Q024-B supported implementation (complete, independently validated and audited)

Decisions 339-348 have completed supported service-owned recovery and informational
reconciliation with automated coverage, independent manual validation, and final
independent read-only re-audit PASS after correction (W039), not application restoration
or closure of broader Q024.
Existing `record_administrator_decision(administrator_id, "resume", details)`
records authorization with `details.operation`, `details.obligation`, and the
exact execution `details.command_id`. A concrete existing-envelope command
references `authorization_evidence_id` and the same `obligation`; the owner
rechecks journal acceptance, scope, dependencies, concurrency, and safety before
action. Duplicate command identities return their original result, not a retry;
cancellation before action retains failure, while cancellation after confirmed
action retains its actual outcome with an incomplete-preservation warning.

Supported actions are archive rewrites from current trusted Ingestor compilation,
Session Record rewrites from retained complete original inputs, fresh artifact
transfers through existing retrieval/verification, independent supported local
artifact finalization, and unfinished device cleanup. Authorization and attempt
must be journal-accepted before action. Actual success and subsequent outcome
archival remain distinct, with visible warnings and retained evidence on failure.
Fresh transfer also creates/submits the existing persistent global collection
evidence. Unproven temporary copies are not reclaimed, unexpected final copies
are not overwritten, uncertain scientific writes are not repaired, and resources
are not automatically released.

Controller `reconcile_outcomes` reads retained participant/command evidence and
current durable preservation without commands or lifecycle changes. Missing and
conflicting outcomes stay unresolved; unchanged findings add no redundant evidence.
Optional/non-mapping command details remain unassociated uncertainty; only explicit
matching Session identities establish Session-scoped command outcomes. Supported
artifact recovery resubmits retained identical finalized-manifest evidence only
on a separately authorized attempt when durable acceptance remains unconfirmed,
without refinalizing scientific records or claiming success without that acceptance.
SynchronizationManager `reconcile_timing` reads journal-backed historical mappings
and reports continuity/uncertainty using explicit active-Session context, without
activating old mappings or restoring a clock. Diagnosed ongoing lost-time scopes
cannot silently restart at zero. Informational evidence is retained but does not
implicitly repair an unconfirmed archive, including corruption during publication.
Ingestor known-Session reconstruction, W035-W038, and historical validation records
remain unchanged. W039 preserves the initial failed audit, correction, focused
revalidation, and final PASS. Decision 336 remains partial; broader Q024, Q019,
Q022, Phase 16, and M015 remain OPEN.

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
Controller Session Records retain Session context without scientific envelopes
or their obsolete audit; raw runtime evidence and runtime-evidence intake audit
are written through the Evidence Archive. The narrow Controller/Ingestor/
SynchronizationManager release slice is complete, manually software-validated,
and independently audited PASS (W035); Phase 16 remains incomplete and Q019/Q024
remain open.

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
remote evidence-compilation/persistence protocol. The narrow Session-binding
release slice under Decisions 313 and 322 is now complete (W035). Controller explicitly releases a terminal
reference after confirmed runtime cleanup and successful final persistence, retaining
a bounded last-release outcome and leaving durable files untouched. Ingestor and
SynchronizationManager can release empty bindings (synchronization also requires
stopped Session Time). Evidence-bearing Ingestor release now requires the exact
persistent-message and complete runtime-audit snapshot confirmed by StorageManager,
plus terminal lifecycle evidence in the existing final Session Record. Historical
scientific-envelope fields remain read-only saved data. Intake and release
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
bindings.
Follow-up tests additionally exercise Controller-specific evidence-bearing release,
subset/stale compilation, publication without archival confirmation, failure
retention, evidence-bearing service reuse, and concurrent intake/release. These
are automated implementation checks. W035 separately records manual IPython
validation and independent audit PASS, including overlapping/stale release,
preservation of the newer Session, continued acquisition, and cleanup. Independent
focused tests passed 152; full discovery ran 493 with 486 passed, 7 optional skips,
and zero failures. Negative controls reproduced the original concurrency defect
with identity checks disabled. These are prior validation results, not tests run
during documentation synchronization or real hardware/external NATS validation.
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
- InMemoryIngestor: Public import for operational evidence and manifest intake with optional explicit known-Session recovery journaling.
- RuntimeEvidenceAuditRecord: Public import for one Ingestor audit record associated with durable runtime evidence intake.
- NatsCommunicationBoundary: Public import for real NATS connection, JetStream stream setup, message serialization, publication, subscription, and transport acknowledgement mechanics.
- NatsControllerCommunication: Public import for Controller-side durable command publication and command-result consumption.
- NatsAcquisitionNodeCommunication: Public import for targeted AcquisitionNode command consumption, local duplicate detection, explicit command execution, command-result publication, and runtime evidence publication.
- NatsIngestorCommunication: Public import for durable runtime evidence consumption into the existing Ingestor ownership boundary.
- NatsStorageManagerCommunication: Public import for current owner preservation readback over existing NATS command/results.
- NatsSynchronizationManagerCommunication: Public import for measured synchronization, readiness, Session preparation and timing closeout through the authoritative timing owner.
- NatsServiceMaintenanceCommunication: Public import for service-owned startup/readiness announcements and participant-scoped administrative commands using existing NATS pathways.
- ServiceMaintenanceInterface: Public import for service-owned dependency readiness, framework evidence, correlated stop/kill/cancel, and evidence-confirmed operational retirement.
- PersistentStorageManager: Public import for durable Session Records, Evidence Archives and scientific-artifact collection.
- SshRetrievalEndpoint, ArtifactRetrievalResult, ArtifactCollectionResult: Public imports for deployment-local SSH configuration and StorageManager artifact collection results.
- LifecycleTransition: Public import for recorded lifecycle transitions.
- OpenCVCameraConfig: Public import for explicit OpenCV camera initialization and polling configuration.
- ReadinessCheck: Public import for recorded readiness checks.
- Session: Public import for the runtime session lifecycle model.
- SessionConfig: Public import for the immutable accepted run configuration, including Session-scoped AcquisitionHealthPolicy definitions and its explicit error evidence location, owned by a Session and preserved as part of the Session Record.
- SeeedIMX219OpenCVCameraAdapter: Public import for the OpenCV-backed adapter producing explicitly selected frames with their local scientific metadata.
- SessionLifecycleError: Public import for lifecycle operation failures.
- SessionState: Public import for accepted Phase 1 session lifecycle states.
- ServiceReadiness: Public import for readiness records produced by framework services and consumed by Session initialization.
- SynchronizationManager: Public import for the minimal Phase 1 Session Time owner.
- SynchronizationMapping: Public import for one immutable SynchronizationManager-owned local-to-Session timing relationship.
- build_runtime_subject: Public helper that constructs concrete Session-scoped or accepted participant/framework-scoped runtime routing subjects.
- build_group_command_messages: Public helper that fans one command intent out to configured members of one component group.
- aggregate_group_command_results: Public issuer-side helper that combines per-target results and records absent expected targets as unresolved.
- parse_runtime_subject: Public helper that parses one concrete runtime routing subject into plain routing fields.

## src/lab_sync_acquisition/communication.py

- ARTIFACT_MANIFEST_EVIDENCE_TYPE: Identifies artifact-level lifecycle manifests as durable runtime evidence without defining transfer or storage schemas.
- MAPPING_UPDATE_EVIDENCE_TYPE: Identifies MappingUpdateEvidence carried as durable runtime evidence without changing timing ownership.
- RuntimeParticipant: Stores one plain component type and identifier, currently referenced by Session configuration, without transport addresses or a second identity system.
- UnresolvedCommandOutcome: Stores inspectable plain-data evidence for one expected target whose command result was absent from the issuer-defined result window.
- GroupCommandOutcome: Stores the issuer-owned aggregate outcome, individual results, and unresolved target evidence for one group command intent.
- RuntimeCommandMessage: Stores one immutable plain-data command intent with explicit source, target, Session, command identity, type, and payload, allowing Session-independent check_stop_readiness and prepare_stop alongside existing administrative commands.
- SERVICE_RECOVERY_COMMAND_TYPES: Lists the five concrete owner-specific administrative command vocabulary values accepted by the existing message envelope and NATS routes, without a new message schema or universal recovery command.
- RuntimeCommandResultMessage: Stores one immutable plain-data command result and validates its shared status vocabulary.
- RuntimeEvidenceMessage: Stores one immutable plain-data evidence message with real Session identity or framework session_id=None plus producer-supplied persistence intent without interpreting meaning.
- RuntimeTelemetryMessage: Stores one immutable plain-data transient telemetry message without making it authoritative evidence.
- build_runtime_subject: Builds and validates Session-scoped routing or participant-scoped commands/results and framework evidence with session_id=None, without adding Session-independent telemetry.
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

## src/lab_sync_acquisition/acquisition_node.py

- AcquisitionIterationSummary(iteration_index, collections_seen, scientific_observations): Reports device collections and scientific observations accepted by LocalStorageManager, without envelope counters or per-iteration durability claims.
- AcquisitionNode: Owns bounded acquisition runtime execution and timestamping, stores separate active Experiment timing and health context, and emits explicitly linked ExperimentScopedHealthObservation and HealthInterpretationEvidence records without executing framework actions.
- AcquisitionNode.status(): Includes existing local cleanup confirmation as `cleanup_confirmed` for safe Session-binding release, alongside runtime, reservation, and active-context status.
- AcquisitionNode.__init__(session_id=None, device_manager=None, synchronization_manager=None, ingestor=None, node_id=None, role=None, acquisition_health_policies=(), error_evidence_location=None, *, default_local_storage_root=None, device_declarations=None, synchronization_source_id=None): Configures local development synchronization or an explicit remote NATS timing authority (never both), local product inventory/storage and optional in-process operational intake.
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
- AcquisitionNode.synchronization_source_id: Exposes the configured remote synchronization identity, or None for a local development owner.
- AcquisitionNode.mapping_activation_history: Returns detached snapshots of Session-scoped mappings and node-local activation boundaries.
- AcquisitionNode.accept_synchronization_quality(session_id, source_id, quality): Checks transport/schema scope, rejects historical readback, and atomically retains the owner's mapping/quality with local application boundaries through existing runtime evidence.
- AcquisitionNode.activate_experiment_runtime(context, health_mapping): Applies prepared Experiment timing and health context idempotently after acceptable synchronization, rejecting conflicting active context without resetting health counts.
- AcquisitionNode._synchronization_readiness: Reports current or acquisition-time validity using prospective quality application history and owner-issued expiry without owning mapping-quality decisions.
- AcquisitionNode._session_time(local_time_s=None): Applies the active authorized affine mapping locally, or reads the explicit in-process development owner.
- AcquisitionNode._collect_iteration: Holds the node reservation lock through collection/preservation so mapping activation is prospective and atomic.
- AcquisitionNode._record_degraded_timing: Retains one supported degraded-condition policy interpretation per assessment without executing a stop policy.
- AcquisitionNode.default_local_storage_root: Exposes the explicitly configured persistent root without mutation by Session overrides.
- AcquisitionNode.node_id: Exposes the configured AcquisitionNode identity used by scientific output selections.
- AcquisitionNode.local_storage_manager: Exposes the Session-attached local persistence collaborator without transferring persistence ownership.
- AcquisitionNode.attach_local_storage_manager: Attaches one Session-authorized LocalStorageManager after checking Session/node and installed product identities and preventing manager replacement.
- AcquisitionNode.prepare_experiment_scientific_outputs: Returns existing ServiceReadiness evidence after resolving explicit products and requesting one empty local stream per Experiment/device/product, reusing open preparations and preserving/finalizing newly created partial artifacts on failure.
- AcquisitionNode.scientific_output_storage_ids: Returns a readback copy of Experiment/device/product associations with LocalStorageManager runtime write handles.
- AcquisitionNode.finalize_experiment_scientific_outputs: Retires the Experiment's runtime identity and attempts LocalStorageManager finalization of every associated stream, returning finalized manifests or raising an error containing all failures without affecting other Experiments.
- AcquisitionNode.start_runtime(): Requires binding, preparation and acceptable synchronization, retains Session-start evidence and starts devices without resetting the remote clock on retries.
- AcquisitionNode.stop_runtime: Stops devices and finalizes selected artifacts, retaining persistent Session-stop evidence and explicit uncertainty before propagating finalization failures.
- AcquisitionNode.run_one_iteration(): Attempts local preservation of all completed scientific collections before operational intake, aggregating collection, persistence and evidence failures without replay or scientific-envelope intake.
- AcquisitionNode._persist_product_collection: Validates selected product and observation provenance and attempts each scientific row through LocalStorageManager with its complete metadata/timing, retaining errors while continuing other writable rows and products.
- AcquisitionNode.runtime_evidence: Returns the retained append-order operational messages for durable publication and retry.
- AcquisitionNode._retain_runtime_evidence: Retains an immutable producer snapshot with identity/conflict checks before optional local operational-evidence acceptance.
- AcquisitionNode._record_acquisition_failure: Records the actual acquisition error as persistent operational evidence and prevents further iterations until existing recovery/preparation permits reuse.
- AcquisitionNode._with_session_time: Converts remote-mode observation local time through its applicable activation boundary, preserves native timing, rejects conflicting supplied Session Time, derives Experiment Time and marks degraded timing without rewriting historical rows.
- AcquisitionNode._evaluate_acquisition_health: Retains linked operational observations and interpretations once per active source without creating scientific envelopes.
- AcquisitionNode._preserve_scientific_artifact: Finalizes one identified supported unfinished local artifact or reuses its finalized manifest, permitting success only after durable manifest acceptance while preserving local success separately and never reopening acquisition.
- AcquisitionNode._cleanup_device_resources: Attempts shutdown only for identified devices in the original retained Session participation, recording partial confirmations without releasing reservations or finalizing scientific artifacts implicitly.
- AcquisitionNode._confirm_recovered_cleanup: Confirms existing local cleanup only when all relevant adapters are safely declared and all local artifacts are finalized, without releasing the Session binding.

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
- Controller.process_timing_quality_interpretation(message): Validates Session/participant scope, idempotently records the configured timing-policy decision and retains its evidence for completion-marker publication without autonomous lifecycle action.
- Controller._record_action_decision(decision): Retains one persistent message per decision instance before optional Ingestor submission, including externally supplied executable decisions, without duplicating an already recorded instance.
- Controller._controller_decision_evidence_snapshot(session_id): Copies Session-specific owned message identities and contents for exact compilation and archival confirmation.
- Controller._controller_owned_session_evidence_snapshot(session_id): Copies persistent decisions, retained preparation-rejection messages, and any produced completion marker for exact Session-scoped preservation checks.
- Controller._require_controller_decision_archival(session_id, confirmation): Blocks release unless decisions and owned evidence remain archived, also requiring current matching durable handoff coverage for a Session with its Q019 completion marker.
- Controller: Sequentially coordinates one Session with optional keyword-only `component_id="controller"` for producer identity, preserves existing ownership, and orchestrates preparation, lifecycle, runtime cleanup, and final persistence.
- Controller.__init__(acquisition_node=None, ingestor=None, storage_manager=None, session_record_path=None, synchronization_manager=None, *, component_id="controller"): Supports Controller creation before Session and without remote participant references while retaining existing local collaborators.
- Controller.launch_session(selections, *, communication, participants, config_parameters, result_window_s, scientific_outputs=()): Asynchronously allocates a fresh intended Session ID, resolves node-scoped device selections, reserves resources, constructs final SessionConfig, confirms participant preparation, and returns operational success or cleanup-aware rollback diagnostics.
- Controller.shutdown_framework(participants, *, communication, stop_attempt_id, administrator_id, result_window_s, authorize_kill=None): Surveys an explicit Session-independent scope and coordinates progressive W036 retirement with StorageManager/Controller preparation, exact pre-Ingestor archival, separately bounded per-service authorization, and retained later confirmations in ControllerCommandResult.details.
- Controller.start_launched_session(): Establishes configured remote synchronization before starting reserved nodes through correlated NATS commands, returning ControllerCommandResult and attempting cleanup if startup fails.
- Controller.stop_launched_session(reason=None): Stops and locally finalizes all reserved nodes through NATS, releases only confirmed-clean reservations, records the Controller-owned end of any active Experiment without refinalizing node files, and stops the Session without waiting for global collection.
- Controller.start_launched_experiment(experiment_id, *, scientific_outputs=(), runtime_health_mapping=None, details=None): Requires measured synchronization and output preparation, records canonical start before delivering node-specific timing/health context over NATS, and preserves failed/cancelled activation outcomes and cleanup uncertainty.
- Controller.stop_launched_experiment(experiment_id, details=None): Confirms each node's finalization and evidence publication before recording canonical Experiment stop with fresh authoritative Session Time.
- Controller._start_launched_session: Serializes Session startup with other runtime transitions, starts configured remote synchronization once and requires correlated node acquisition confirmations.
- Controller._stop_launched_session: Retains confirmed node-release facts for retry when final clock readback is unavailable, without replaying cleanup against released nodes.
- Controller._synchronization_participant: Resolves exactly one explicitly configured synchronization authority for the bound Session.
- Controller._request_launched_runtime: Requires fresh owner success, validates timing/readiness readback and rechecks Session binding after network suspension.
- Controller.publish_acquisition_evidence_completion(*, communication, result_window_s): Asynchronously confirms Session-scoped node and synchronization publication plus completed Controller health processing, publishes owned/retained evidence and one stable marker, and returns ControllerCommandResult without receipt, archival, or lifecycle completion.
- Controller.archive_acquisition_evidence(*, communication): Verifies receipt of its confirmed W042 marker through the matching NatsIngestorCommunication, archives current protected Ingestor compilation and existing Session Record evidence, and returns confirmed Stage A paths without lifecycle completion, collection, or binding release.
- Controller.preserve_artifact_collection_handoff(): Compiles journal-backed artifact information after current Stage A confirmation and returns verified durable handoff preservation without changing lifecycle or releasing bindings.
- Controller.normal_stop_session(*, communication, receiving, result_window_s, reason=None): Associates the Session with Q019 before asynchronous shutdown and retains that requirement through failure/cancellation, then coordinates cleanup, producer/marker publication, independently verified receipt, Stage A archival, durable handoff, and completion without automatic collection, binding release, or archive closure.
- Controller.kill_session(*, communication, result_window_s, operator_authorized, reason=None): Explicitly aborts the active Experiment and Session, preserves partial acquisition evidence and handoff, retains correlated cleanup uncertainty and reservations, and never initiates collection or permanent closure.
- Controller._preserve_kill_closeout(session): Confirms current journal-backed partial archive and handoff under intake, persistence, and admission guards without claiming complete receipt.
- Controller._complete_preserved_acquisition(session): Rechecks current journal, Stage A operational evidence/all-audit coverage, final Session Record, owned evidence, marker and handoff under intake/storage/admission locks before completion without replacing an unconfirmed baseline.
- Controller.get_status(): Returns Session/command status, the bounded last released terminal outcome, and the local AcquisitionNode snapshot or None, without fabricating remote runtime status.
- Controller.reconcile_outcomes(*, session_id=None, participants=None, communication=None, result_window_s=None): Reads existing scoped outcomes or bounded current observations of explicit remote participants, retaining unassociated uncertainty and changed informational evidence without operational replay or lifecycle mutation.
- Controller._validate_participant_reconciliation(participants, result_window_s): Checks explicit unique remote principal-service identities and the issuer-defined bounded observation window without discovering participants.
- Controller._observe_known_participants(participants, communication, result_window_s): Reads correlated readiness/owner diagnostics independently, ignoring malformed optional collections without inventing Session identities or performing recovery.
- Controller.reconciliation_evidence: Returns detached retained persistent informational findings for existing publication and preservation paths.
- Controller._reconcile_framework_attempt: Correlates confirmed final participant results against the original framework attempt and archived evidence without treating missing results or intent as completion.
- Controller.check_ready(): Returns Session-independent service readiness, combining confirmed configured dependencies and refusing to fabricate a ready/unready report when dependency availability is unknown.
- Controller.release_session(): Asynchronously releases only its captured terminal Session binding after confirmed cleanup and current archival, holding Ingestor intake then StorageManager preservation locks through final synchronous checks and retirement for Normal Stop and Kill, never across unsubscription awaits; stale operations fail without changing a newer binding, while cancellation retains outstanding obligations.
- Controller._session_ingest_state(): Snapshots existing intake views to detect acceptance/audit changes after final persistence or during subscription release.
- Controller.start_experiment: Accepts keyword-only `scientific_outputs=()`, `preparation_readiness=()`, and `preparation_outcomes=()`, gates start on required readiness and correlated final remote successes, and reports preparation rejection once as persistent runtime evidence in failed result details without lifecycle activation.
- Controller._record_failed_command: Records an unsuccessful command with optional plain diagnostic details, including the produced rejection message for a pre-start preparation failure.
- Controller.stop_experiment: Records canonical normal-stop evidence, clears active runtime context and health mapping, and requests finalization of only that Experiment's streams without stopping the Session or acquisition runtime.
- Controller.execute_controller_action_decision: Records persistent evidence for an externally supplied accepted decision once, then executes unchanged no-mutation or failure semantics, finalizing Experiment streams for `experiment_fail` and retaining the failed-Session cleanup path for `session_fail`.
- Controller.stop_session: Stops runtime and scientific persistence, records normal-stop evidence for any active Experiment, and then stops the Session through its existing lifecycle.
- Controller.initialize_session: Retains the historical direct-object workflow, with Session-authorized local storage now physically created by AcquisitionNode and criticality evaluated from selected DeviceDeclarations.
- Controller.start_session(): Requires an explicit Ingestor reference before local runtime startup, then starts acquisition, starts the Session, and writes the initial Session Record through existing persistence.
- Controller._session_record_evidence(): Gathers Session configuration, lifecycle, readiness, cleanup, command failures and Experiment evidence without duplicating the operational Evidence Archive or scientific observations in the Session Record.
- Controller._require_kill_runtime_coverage(session_id, record): Requires matching Session identity and exact current operational evidence/all-audit archival coverage under existing intake/preservation guards before Kill reconfirmation or release.
- Controller._session_ingest_state(): Captures current operational messages and the complete intake audit for finalization/release race detection without obsolete scientific-envelope counters.

## src/lab_sync_acquisition/device_adapter.py

- DeviceAdapterState: Enumerates the minimum lifecycle states for a live device adapter.
- DeviceReadiness(device_id, ready, reason, capabilities_available): Records technical device readiness without requiredness, which is evaluated from selected DeviceDeclaration.required.
- DeviceStatus: Reports the current live adapter lifecycle status without scientific data.
- DeviceAdapterLifecycleError: Signals invalid live adapter lifecycle operations.
- DeviceReadinessNotImplementedError: Signals that a live adapter has no concrete readiness implementation.
- DeviceAdapter: Provides device-owned lifecycle/readiness and explicit product collection, keeping scientific rows separate from operational messages.
- DeviceAdapter.collect_products(products, *, session_id, experiment_id, acquisition_node_id): Produces selected declaration-keyed scientific row collections separately from operational RuntimeEvidenceMessages, rejecting unsupported selections and doing no scientific work for an empty selection.
- DeviceAdapter.shutdown: Completes adapter-specific cleanup after initialization/readiness/failure or normal stop, then returns to DECLARED; failed cleanup retains FAILED and completed shutdown is idempotent.
- DeviceAdapter._shutdown_resources: Adapter-specific resource-release hook executed before the generic successful-cleanup transition.
- DeviceAdapter.initialize(config): Requires DECLARED and applies fresh configuration for the next initialization without a reset operation.
- DeviceAdapter.check_ready: Reports declared eligibility without opening hardware or changing state, while initialized acquisition readiness remains concrete-adapter-owned.
- DeviceStatus.shutdown: Reports completed device cleanup even when the reusable adapter state is DECLARED, resetting on subsequent initialization.
- _PartialScientificCollectionError: Retains completed product rows and separate operational messages alongside the original acquisition exception.

## src/lab_sync_acquisition/device_manager.py

- DeviceLifecycleResult: Records the result of one Device Manager lifecycle call against one adapter.
- DeviceCollectionResult(source_device_id, scientific_products, operational_evidence): Carries source-identified product-keyed row tuples separately from operational messages, without envelopes.
- DeviceReadinessSummary: Aggregates shared readiness records across already-created adapters and can be passed to Session initialization.
- DeviceManager: Coordinates already-created adapters and their lifecycle, readiness, status and explicit product selections without creating adapters or envelopes.
- DeviceManager.collect_products(products_by_device, *, session_id, experiment_id, acquisition_node_id): Calls each adapter once with explicit declarations or an empty selection and retains completed partial results when a later device fails.
- _PartialDeviceCollectionError: Retains earlier valid source-identified collections even when a later adapter's partial result is invalid, preserving original and validation errors for node-local persistence/reporting.
- DeviceManager._product_collection_result: Checks the explicit product/operational result structure and rejects unselected products before source-identified collection results reach the node.

## src/lab_sync_acquisition/experiment_runtime.py

- ActiveExperimentRuntimeContext: Stores immutable runtime-only Experiment identity and canonical start Session Time with a plain-data round trip.
- ExperimentRuntimeHealthMapping: Records one immutable live-source-to-Expected-Participant mapping and the authoritative Experiment-scoped acquisition-health policy assignment, with plain-data round trips but no evaluation behavior.
- ExperimentScopedHealthObservation: Records a runtime-unique observation identity, Experiment-scoped health condition, source and participant identity, policy context, Session Time, and audit details as plain evidence without operational consequence.

## src/lab_sync_acquisition/ingestor.py

- InMemoryIngestor: Receives operational runtime evidence and manifests, journals/reconstructs the evidence view for a known Session, deduplicates evidence_id content, and compiles persistent evidence without scientific-observation intake.
- InMemoryIngestor.__init__(storage_manager=None, *, session_id=None, recovery_journal_path=None, component_id="ingestor", recovery_journal_root=None, framework_recovery_journal_path=None, evidence_scope="session"): Preserves known-Session intake and optionally creates a deployment-scoped framework partition using the same Ingestor implementation without a Session binding.
- InMemoryIngestor.prepare_framework_evidence(recovery_journal_path): Configures framework journal-backed intake once, retaining accepted messages and original duplicate/rejected intake audit across recovery independently of Session release.
- InMemoryIngestor.compile_framework_runtime_evidence(): Returns only producer-marked persistent framework messages and all framework intake audit records through the existing compilation mechanism.
- InMemoryIngestor.await_durable_runtime_evidence(evidence, timeout_s): Boundedly observes exact local journal-backed acceptance using futures, without polling, retrying, or equating JetStream publication with acceptance.
- InMemoryIngestor.framework_preservation_guard(storage_manager): Holds framework intake and StorageManager preservation steady while checking exact current persistent-message/all-audit coverage, without a Session Record.
- InMemoryIngestor.maintenance_blockers(ingestor, storage_manager): Reports unresolved journal integrity or incompletely preserved Session intake without deciding lifecycle or inferring dependencies.
- InMemoryIngestor.prepare_session(session_id): Creates or reconstructs the intended Session recovery journal from its deployment root before confirming evidence intake preparation.
- InMemoryIngestor.abort_session_initialization(session_id): Disables prepared intake while preserving durable journal entries and accepted evidence, clearing empty preparation bindings without deleting files.
- InMemoryIngestor.release_session(session_id, *, storage_manager=None): Releases a matching healthy binding only after exact archive/terminal-record preservation and matching Q019 durable handoff coverage for completion-marker archives or admitted Kill obligations, including empty intake and unavailable confirmation, retaining intake/storage guards through retirement without deleting journals.
- InMemoryIngestor._require_kill_handoff(session_id): Retains the matching binding's admitted Kill handoff obligation before shutdown suspension, independently of archival success.
- InMemoryIngestor.has_durable_runtime_evidence(evidence): Confirms exact journal-backed message acceptance for a producer handoff, returning False for memory-only intake or uncertain journal state without claiming final archival.
- InMemoryIngestor.durable_runtime_evidence_history_guard(session_id, journal_path, evidence): Read-only context manager yielding exact retained Session-journal coverage confirmation while holding intake/binding steady through synchronous receipt-result commitment; it permits additional local recovery evidence and performs no reconstruction or archival.
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
- InMemoryIngestor.compile_durable_session_evidence(session_id): Returns detached journal-verified operational evidence, its complete intake audit and the existing artifact handoff without claiming receipt completeness or archival.

Slice 27 (Decisions 276-280) is complete (M014, W034) after independent manual
software validation and corrected targeted re-audit PASS. W034 preserves the
uncertain-durability clarification and initial audit FAIL/correction history.
Supply session_id and
recovery_journal_path together; the caller chooses the exact file location and
its parent directory must already exist. Legacy local in-memory use remains
available without these arguments; broker evidence subscriptions require a
matching journal, either constructor-configured or prepared through
prepare_session(session_id) with recovery_journal_root.
Session journal entries preserve messages, not original ingest audit timestamps: startup
generates intake audit records marked recovered at reconstruction time. The
framework partition journals original intake audit alongside accepted messages,
including duplicate and rejected intake, using the same Ingestor recovery path. The
existing Slice 22 compiler is unchanged. No journal cleanup or Session discovery
is implemented (Q024); acceptance deduplication is not Controller action
deduplication, and Session-wide consumption/finalization remains open (Q019).

## src/lab_sync_acquisition/nats_communication.py

- DurablePublicationError: Reports failed JetStream publication with message class, message identity, subject, intended stream, and reason while leaving the original message caller-owned.
- NatsCommunicationBoundary: Owns a real nats-py connection, reports NATS availability through ServiceReadiness, creates accepted JetStream streams, and handles JSON serialization, durable publication acknowledgement, and Core NATS telemetry mechanics without domain semantics.
- NatsControllerCommunication: Publishes unicast or issuer-fanned group commands, consumes and aggregates addressed per-target command results over an issuer-defined window, records missing results as unresolved, and independently presents HealthInterpretationEvidence without relaying evidence.
- NatsControllerCommunication.check_ready(): Returns required NATS communication readiness for launch gating.
- NatsControllerCommunication.request_command(participant, command_type, session_id, payload, result_window_s, *, command_id=None): Publishes once and awaits the bounded correlated result; when startup integration is attached to the same boundary, it also informs the service owner of missing results or explicit readiness observations without inferring technical unreadiness or using stale subscription bindings.
- NatsControllerCommunication.request_runtime_command(participant, command_type, session_id, payload, result_window_s, *, command_id=None): Uses a fresh-only per-attempt result subscription and nonce for Session runtime work, retaining owner command identity independently of delivery attempts.
- NatsControllerCommunication.subscribe_command_results(session_id, callback=None, *, new_only=False, result_filter=None): Preserves historical result consumption by default and optionally limits delivery/filtering for current owner requests.
- NatsControllerCommunication.session_acquisition_completion(participant, session_id): Reads the successful result for this issuer's latest exactly correlated stop_runtime request, not an unrelated or historical response.
- NatsControllerCommunication.confirm_session_health_processing(session_id, controller): Reads retained Session health publications against completed bound subscription callbacks, refusing unknown history or unfinished inputs without processing/replaying them.
- NatsControllerCommunication.publish_evidence(message): Retains Controller-owned publication failures and requires the existing durable stream acknowledgment, rejecting conflicting retained identities.
- NatsControllerCommunication.unpublished_session_evidence(session_id): Returns detached unconfirmed publication messages for only the requested Session.
- NatsCommunicationBoundary.ensure_streams(): Provisions fixed five-/six-token filters on the three existing streams, narrows recognized legacy filters before adding missing coverage, and preserves stored messages, consumers, custom subjects, and unrelated settings without deleting/recreating streams; incompatible custom filters surface a broker error.
- NatsCommunicationBoundary.subscribe_readiness_announcements(participant, callback): Subscribes the existing framework evidence subject with DeliverPolicy.NEW and AckPolicy.NONE so operational readiness never comes from retained history or redelivery; Ingestor's durable historical consumer is unchanged.
- NatsAcquisitionNodeCommunication.subscribe_commands(): Returns two addressed command subscriptions, publishing generated and retained scoped evidence before results so successful runtime completion confirms publication while keeping the handler reusable across bindings.
- NatsAcquisitionNodeCommunication: Consumes targeted readiness, scientific-output preparation, or runtime commands, deduplicates by command_id, and publishes explicit outcomes without owning Experiment lifecycle.
- NatsAcquisitionNodeCommunication.execute_command: Executes existing node commands and includes available owner diagnostics in readiness results while preserving readiness-only compatibility and scientific-output preparation behavior.
- NatsIngestorCommunication: Consumes durable RuntimeEvidenceMessage records and passes them to InMemoryIngestor for separate evidence intake and audit.
- NatsIngestorCommunication.subscribe_commands(): Routes readiness/preparation/abort and scoped current compilation/receipt requests to the existing Ingestor owner, publishing results before command ACK.
- NatsIngestorCommunication._execute_evidence_readback(command): Delegates scoped compilation, exact journal-backed runtime-evidence acceptance and W041 marker-receipt verification to the Ingestor owner with current-request reply correlation and explicit failed/unconfirmed results.
- NatsStorageManagerCommunication(boundary, storage_manager): Binds one existing authoritative StorageManager to matching NATS participant identity without constructing another owner.
- NatsStorageManagerCommunication.subscribe_commands(): Admits fresh StorageManager commands, serializes collection attempt resolution through durable result publication before ACK, and keeps administrative execution within the configured owner maintenance interface.
- NatsStorageManagerCommunication.execute_command(command): Routes scoped preservation/status readback, eligible saved-Session collection and separately explicit permanent archive closure to the authoritative storage owner without arbitrary remote methods or recovery/release bypasses.
- NatsStorageManagerCommunication._validate_saved_session_request(command): Checks the exact collection or explicit archive-closure payload, nonce and canonical Session/evidence or Session/operation command identity.
- NatsStorageManagerCommunication._execute_saved_session_attempt(command, *, retained_result=None): Validates complete operation-scoped history and same-nonce identity before execution or reuse, rejecting disagreement with a retained successful closure before current archive reconfirmation.
- NatsStorageManagerCommunication._reconfirm_archive_closure(command, result): Requires matching current closed-archive preservation before reconfirming a retained or historical successful closure through the owner.
- NatsStorageManagerCommunication._read_saved_session_result(record, operation): Validates persisted result correlation, subject/body routing and collection-evidence or closed-summary identity before matching.
- _subscribe_participant_commands(boundary, receive, *, new_only=False): Subscribes to existing scoped/independent participant command subjects, optionally admitting only commands published after startup for StorageManager.
- _validate_owner_request(boundary, command): Validates target, requester, command, Session, connectivity, and transient reply correlation for the bounded owner operations.
- NatsControllerCommunication.request_persistence_command(participant, command_type, session_id, payload, result_window_s, *, command_id): Makes one bounded scoped owner request with fresh-only results and an echoed per-attempt nonce, preserving the stable command ID while rejecting historical and late retry confirmations.
- Controller.collect_saved_session_artifacts_remote(session_id, *, evidence_id, communication, storage_participant, result_window_s): Coordinates explicit single saved-Session collection through NATS without local service references, requiring matching durable collection evidence and retaining failures or missing responses as unconfirmed.
- Controller.close_saved_session_archive_remote(session_id, *, communication, storage_participant, result_window_s): Explicitly requests permanent closure of one saved Evidence Archive through NATS, requiring matching owner-verified closure and summary without Session completion or resource release.
- NatsSynchronizationManagerCommunication(boundary, synchronization_manager): Routes measured synchronization, readiness, Session preparation and timing closeout over existing command/result streams while retaining timing authority in SynchronizationManager.
- NatsSynchronizationManagerCommunication.subscribe_commands(): Serializes command admission and rejects conflicting identities or mismatched stop Sessions before cancelling periodic work outside the runtime lock, then routes owner operations with existing correlated results and idempotency.
- NatsSynchronizationManagerCommunication.close(): Cancels periodic assessment and unsubscribes transport callbacks without terminating acquisition or changing Session lifecycle.
- NatsSynchronizationManagerCommunication._measure_node: Collects causal NATS exchanges and requests owner-side validity assessment before confirmed mapping delivery.
- NatsSynchronizationManagerCommunication._deliver_quality: Requires correlated node acceptance of owner-issued mapping/quality state.
- NatsSynchronizationManagerCommunication._publish_timing: Publishes stable owner-created timing evidence without closing Session Time.
- NatsSynchronizationManagerCommunication._periodic_assessment: Performs configured serialized checks, retaining unconfirmed evidence across transient cycle failures until later publication or explicit closeout, without automatically resynchronizing or stopping nodes.
- _participant_result: Builds an existing correlated final command-result message for one service-owned operation.
- _execute_service_command: Delegates readiness/preparation/abort to the owner, includes configured maintenance identity and actual retirement confirmation in readiness replies, and retains command-ID deduplication.
- NatsIngestorCommunication.subscribe_evidence(session_id, callback=None): Validates delivered subject against Session/source/type identity before intake, uses a stable Session-specific durable explicit-ACK consumer with matching-journal acceptance before server-confirmed ACK, and rechecks binding after optional callbacks while preserving framework intake for None.
- NatsIngestorCommunication.verify_acquisition_evidence_receipt(marker): Reconciles Session-filtered publications through the marker with exact retained journal evidence under the Ingestor guard, plus receiving-origin/history and contiguous ACK checks; returns receipt confirmation/reason and broker sequences without repair, Session completion, or archival confirmation.
- NatsIngestorCommunication._session_consumer_name(session_id): Derives a stable broker-safe durable consumer name from the Session identity without changing evidence identities.
- NatsIngestorCommunication._receiving_history_intact(stream): Checks retained stream-origin coverage and missing/lost history using broker metadata, not producer evidence-count expectations.
- NatsIngestorCommunication._validate_session_consumer(consumer, stream, session_id): Rejects mismatched durable identity, stream epoch, Session filter, delivery/ACK configuration, or receiving-origin metadata.
- NatsIngestorCommunication._acknowledgment_progress_valid(consumer, last_sequence): Checks coherent stream/consumer ACK and delivery counters before treating broker progress as usable evidence.
- NatsControllerCommunication.maintenance_requests: Returns detached administrative command intent (including survey and preparation), attempt identity, and authorization retained by the existing command issuer independently of received command results.
- NatsServiceMaintenanceCommunication(boundary, maintenance, *, startup_participants=None, startup_result_window_s=None): Integrates existing startup/readiness communication, with Controller-only explicit remote observation scope (defaulting to configured dependencies) and an explicit positive result window for nonempty scopes.
- NatsServiceMaintenanceCommunication.start(): Requires connected NATS, subscribes dependencies, announces startup/return, and automatically obtains Controller participant reconciliation through bounded readiness requests; fresh announcements still do not trigger redundant checks and no process is launched.
- NatsServiceMaintenanceCommunication.close(): Removes its subscriptions and invalidates current dependency reports while preserving last-known reports, service state, and producer evidence obligations.
- NatsServiceMaintenanceCommunication.publish_readiness(): Publishes only meaningful readiness/obligation changes and creates no new archival work after resource closeout begins.
- NatsServiceMaintenanceCommunication.request_dependency_command(participant, command_type, session_id, payload, result_window_s): Reuses the existing bounded correlated command issuer, invalidating current availability on unconfirmed communication without interpreting a confirmed command failure as technical unreadiness or allowing an older communication binding to alter a newer one.
- NatsServiceMaintenanceCommunication.check_dependency_readiness(participant, result_window_s): Performs an explicit operational check and returns ServiceReadiness or None for unknown, preserving historical readiness separately.
- NatsServiceMaintenanceCommunication._observe_dependency_result(participant, command_type, result, observation_version): Updates configured service-owned dependency readiness from existing command outcomes, rejecting confirmed readiness results superseded by subsequent observations within the same communication binding.
- NatsControllerCommunication._notify_dependency_result(observation, command_type, result): Notifies the existing service-owned observer for single requests, unresolved group outcomes, or failed group publications without masking the original result or publication failure.
- NatsControllerCommunication.publish_group_command(...): Preserves existing fan-out behavior and invalidates only the dependency whose attempted publication fails, leaving successful or unattempted peers unaffected.
- NatsControllerCommunication.await_group_command_outcome(...): Preserves issuer aggregation and informs the existing dependency observer of unresolved targets without fabricating technical unreadiness.
- NatsServiceMaintenanceCommunication.subscribe_commands(): Routes maintenance and check_readiness requests through existing JetStream command/result subscriptions without changing cleanup, kill authorization, or lifecycle ownership.
- _execute_maintenance_command: Connects existing service handlers to their configured administrative interface and brokered evidence publisher without a local publication fallback.

## src/lab_sync_acquisition/service_maintenance.py

- ServiceMaintenanceInterface(service, participant, *, ingestor, storage_manager, preservation_window_s, close_resources, operational_dependents=None, evidence_publisher=None, retire_resources=None, dependency_participants=()): Attaches one service-owned administrative interface with existing maintenance callbacks and an explicit caller-provided tuple of dependency identities, without discovery or a deployment-file model.
- ServiceMaintenanceInterface.execute_command(command): Serializes/deduplicates existing maintenance and concrete owner-specific recovery commands; prepared retirement still requires complete retained Ingestor evidence/all-audit coverage through commitment without invoking retired intake or repeating cleanup.
- ServiceMaintenanceInterface._require_recovery_authorization: Requires exact obligation/operation/command/participant correlation and durable journal acceptance of an existing resume decision, rejecting a later matching drop.
- ServiceMaintenanceInterface._execute_authorized_recovery: Journals a specific attempt before owner execution under intake/persistence/admission guards and records actual succeeded/failed/refused outcomes separately from archival confirmation.
- ServiceMaintenanceInterface.prepared: Reports confirmed ordinary cleanup awaiting final retirement, not a lifecycle state or completed stop; only StorageManager and Controller support preparation with an explicit framework attempt identity.
- ServiceMaintenanceInterface.command_results: Returns detached correlated last-confirmed results with separate completed/blocked/failed outcomes and termination confirmation.
- ServiceMaintenanceInterface.evidence: Returns retained producer-owned persistent framework evidence, including startup/readiness, administrator choices, maintenance attempts, and preservation failures.
- ServiceMaintenanceInterface.dependency_readiness: Returns a detached mapping of configured RuntimeParticipants to current ServiceReadiness or None for unknown.
- ServiceMaintenanceInterface.last_known_dependency_readiness: Returns historical confirmed reports, never substituted for missing current operational readiness.
- ServiceMaintenanceInterface.receive_dependency_readiness(participant, readiness): Updates or invalidates only a configured dependency's current report and advances private ordering counters so earlier checks cannot overwrite subsequent observations, without changing Session lifecycle, reservations, or cleanup obligations.
- ServiceMaintenanceInterface.dependency_reports(): Returns current dependency records or raises RuntimeError for missing current evidence, retaining the existing boolean readiness schema.
- ServiceMaintenanceInterface.announce_readiness(*, startup=False): Creates persistent startup/return or changed-readiness evidence with journal acceptance and guarded archival that never repairs unconfirmed existing products, while suppressing unchanged snapshots.
- ServiceMaintenanceInterface.record_administrator_decision(administrator_id, decision, details): Records persistent resume/drop choices with a separate unresolved/abandoned obligation outcome, returning guarded temporary-producer-copy release and its preservation observations without executing recovery, deleting durable data, or clearing safety obligations.
- ServiceMaintenanceInterface.terminated: Reports confirmed operational-service retirement rather than OS process death.
- ServiceMaintenanceInterface._retirement_guard(force=False): Commits retirement under intake/storage/admission locks as applicable and retains final Ingestor compilation without imposing orderly preservation prerequisites on authorized kill.
- ServiceMaintenanceInterface._preserve_message(message, status=None, *, archive=True, require_existing_archive=False): Reuses publication, journal acceptance, and archival while permitting journal-only repair admission and rechecking protected archive validity after asynchronous publication.
- ServiceMaintenanceInterface._readiness_payload(): Packages participant, readiness, actual operational retirement confirmation, dependency reports, and owner diagnostics without guessing technical unreadiness or acquisition state.
- ServiceMaintenanceInterface._diagnostic_payload(): Adds owner-specific diagnostics and actual maintenance-attempt confirmations to existing readiness responses without defining a shared recovery schema.
- ServiceMaintenanceInterface._administrative_outcome(reference): Projects explicit abandonment from retained administrator choices matching existing service-owned references, without a registry or mutation of original outcomes.
- ServiceMaintenanceInterface._release_abandoned_evidence(decision): Retires only unnecessary producer copies under existing complete-preservation/resource/admission guards and retains abandonment markers plus actual release evidence.
- ServiceMaintenanceInterface._record_framework_evidence(message, status=None, *, archive=True, require_existing_archive=False): Retains producer evidence and exposes separate publication/acceptance/archival observations and warnings, including informational findings and authorized recovery outcomes.
- service_operation(new_work=False): Tracks service operations, including existing administrative interfaces and their outgoing NATS dependency requests, rejecting new unrelated work during pending maintenance while permitting nested admitted calls only within the same task or thread, not through inherited child-task context.

Startup and administrator-decision APIs return detached evidence plus separate
`publication_confirmed`, `acceptance_confirmed`, and `archival_confirmed` submission
observations; an unchanged snapshot returns its previous submission result, not a
new current archival confirmation. `preservation_warning` and logging expose unconfirmed archival
without blocking independent startup. Producers retain the original evidence in
the existing evidence readback; orderly closeout still checks every outstanding
persistent record. No unpublished-message queue, retry, replay, or second archive
is created. Known obligations come from existing owner diagnostics, not discovery
of abandoned applications. Delivery loss is detected only by existing operations
or explicit checks; there is no proactive detection guarantee. Startup/readiness
is independently validated and audited in W038; the supported Q024-B extensions
are complete with automated coverage, independent manual validation, and final
independent re-audit PASS after correction in W039.

Maintenance must be configured with an explicit service-owned resource closeout
callback and preservation window. Local callers may use attached intake;
configured NATS handlers publish evidence through JetStream and boundedly await
actual acceptance through the configured Ingestor confirmation interface.
Publication acknowledgment alone cannot complete stop.

Decision 324 closeout ordering is implemented, manually software-validated, and
independently audited PASS (W036). `close_resources(force)` confirms ordinary cleanup and must
leave required evidence intake, journaling, archival, and result capabilities
available. Optional `retire_resources(force)` closes the remaining capabilities
after durable readiness preservation. Both callbacks must return exactly `True`;
without the optional callback, final retirement closes operational admission only,
not an OS process or caller-owned transport connection.

Orderly maintenance preserves `initial`, `cleanup_confirmed`, and
`ready_for_retirement` checkpoints using the existing runtime evidence pathway.
Pending checkpoints use `outcome=None`, not a new attempt or lifecycle state;
they never claim completed retirement. The initiating interface retains the final
`completed` result only after confirmed retirement, and the existing command/result
path delivers it where available. Missing delivery is not success. No post-retirement
self-preservation through unavailable Ingestor/StorageManager infrastructure is
required. Preservation failure before cleanup blocks stop; failure after cleanup
begins produces `failed`. Authorized kill semantics remain separate and unchanged.

Authorized kill best-effort preserves a `cleanup_confirmed` checkpoint with
`outcome=None` before final retirement. Active-operation checking and operational
retirement commitment occur together under the admission lock, without an await;
only confirmed retirement produces a retained `completed` command result. Active
operations instead produce `failed` evidence with confirmed cleanup actions and
remaining obligations. No completed evidence is published before confirmation,
and retired evidence services need not archive their own final event.

Orderly preservation guards require exact journal-backed acceptance and current
archival of every retained persistent maintenance message, including prior failed
publications. Explicit producer-managed submission through the existing pathway
may fulfill an outstanding obligation; maintenance does not replay old messages.
Configured Ingestor dependency predicates and service-owned obligations are
rechecked before final resource retirement and at operational-admission commitment.
The synchronous commitment uses intake, storage-preservation, then admission
locking; no such lock is held across an awaited callback. No new supervisor,
evidence subsystem, shutdown coordinator, lifecycle state, automatic replay, or
recovery is introduced. Phase 16 and M015 remain open.

## src/lab_sync_acquisition/service_readiness.py

- ServiceReadiness: Holds the shared framework-service readiness fields consumed by Session initialization and exposes them as plain data for Session Record evidence.
- dependency_readiness_reports(service): Reads the attached service-owned dependency records, preserving unknown as missing current evidence instead of a fabricated boolean report.
- apply_dependency_readiness(service, readiness): Combines confirmed required framework prerequisites with local readiness without substituting last-known historical reports.

## src/lab_sync_acquisition/opencv_camera.py

- OpenCVCameraConfig: Holds explicit OpenCV camera source, backend, frame polling count, and optional requested capture properties.
- SeeedIMX219OpenCVCameraAdapter: Opens a camera, reports readiness, acquires selected scientific frame products only, and releases the capture during shutdown.
- SeeedIMX219OpenCVCameraAdapter.shutdown(): Uses generic shutdown to report FAILED and retain the capture after release failure, returning to DECLARED only after successful release with idempotent subsequent shutdown.
- SeeedIMX219OpenCVCameraAdapter.initialize(config): Accepts OpenCVCameraConfig or its plain-data mapping through the existing DECLARED lifecycle, owning each capture before fallible setup and retaining FAILED plus the capture if initialization cleanup cannot release it.
- SeeedIMX219OpenCVCameraAdapter.check_ready(): Reports declared eligibility without opening capture, and checks initialized capture readiness separately.
- SeeedIMX219OpenCVCameraAdapter.collect_products(products, *, session_id, experiment_id, acquisition_node_id): Reads selected camera products only, retaining ordered NumPy frames with their available per-frame metadata and completed partial rows without repeated reads or fabricated timestamps.

## src/lab_sync_acquisition/storage.py

- PersistentStorageManager: Owns durable Session Records, Evidence Archives, saved-Session selection, recovery and global scientific-artifact collection without scientific-envelope persistence.
- PersistentStorageManager(storage_root, *, global_artifact_root=None, retrieval_endpoints=None, evidence_publisher=None, component_id="storage"): Uses an explicit directory root for existing Session/framework products, retaining node-keyed retrieval settings and collection-evidence publication.
- PersistentStorageManager.storage_root: Returns the configured directory root, not a scientific-envelope record file.
- PersistentStorageManager._require_historical_session_intake(record, session_id): Validates any historical envelope/audit fields as plain saved data without recreating legacy writers or accepting incomplete/cross-Session history.
- PersistentStorageManager.write_session_record: Serializes and durably writes caller-supplied Session Record evidence under the preservation lock, refusing managed final-record mutation after archive closure.
- SshRetrievalEndpoint(host, username, port=22, key_filename=None, known_hosts_path=None): Immutable deployment-local SSH configuration keyed by logical AcquisitionNode ID, using trusted host keys and optional explicit private-key/known-hosts files.
- ArtifactRetrievalResult(artifact_manifest_id, outcome, global_destination=None, failure_information=None, verification_outcome=None, verification_information=None): Immutable per-artifact result whose `to_dict()` preserves retrieval success/failure separately from verification information, absent when retrieval failed.
- ArtifactCollectionResult(artifact_results): Immutable aggregate whose `succeeded` requires every requested artifact to have retrieval success and verified status, with `to_dict()` retaining ordered per-artifact details without lifecycle interpretation; empty collections remain successful.
- PersistentStorageManager.collect_artifacts(handoff): Independently retrieves one file per manifest through SSH/SFTP, including missing-finalization candidates, then lightly verifies completed global copies without changing authoritative sources or Session products.
- PersistentStorageManager.collect_artifacts_with_evidence(handoff): Awaits publication of one persistent global_artifact_collection_evidence message after a completed pass, preserving separate per-artifact retrieval/verification outcomes and operational wall-clock bounds.
- PersistentStorageManager._record_collection_evidence: Creates and retains the same compiled global collection message for ordinary collection and an explicitly authorized fresh transfer.
- PersistentStorageManager.collect_saved_artifacts(session_id, *, evidence_id, require_eligible=True): Requires terminal eligibility and safe preservation under collection guards by default; explicit False preserves existing internal Stage B/recovery preconditions and idempotent outcome readback without automatic refetch.
- PersistentStorageManager._read_saved_session_eligibility(session_id): Confirms persisted Session identity, lifecycle/final-status agreement, and record durability independently of collection preservation information.
- PersistentStorageManager.get_saved_session_collection_status(session_id): Reports current persisted lifecycle, eligibility, collection availability, and separate blockage reasons without transfer or recovery.
- PersistentStorageManager.list_saved_sessions(): Enumerates existing Session directories and independently assesses each, retaining incomplete or unavailable candidates in readback without a registry.
- PersistentStorageManager.get_persisted_session_preservation_confirmation(session_id): Validates existing Stage A/B products, coverage, identities, provenance, and handoff after restart without cached Session bindings, returning detached products or None for uncertainty.
- PersistentStorageManager.close_session_evidence_archive(session_id): Handles a separate explicit closure request by validating current durable coverage, refusing unresolved writes, atomically recording closure in the existing summary, and readback-confirming immutable contents without requiring artifact success.
- PersistentStorageManager._require_open_session_archive(session_id): Refuses ordinary or authorized mutation of a closed or unconfirmed Session archive using current persisted summary information.
- PersistentStorageManager._require_session_record_writable(path): Resolves the complete target and configured storage root before identifying and protecting a managed final Session Record from generic or recovery writes after closure.
- PersistentStorageManager._collection_outcome_path(session_id): Locates the temporary outcome message in the existing known-Session directory.
- PersistentStorageManager._read_preservation_json(contents): Reads preservation JSON while rejecting duplicate fields and non-finite values.
- PersistentStorageManager._require_complete_runtime_audit(audit): Validates all existing RuntimeEvidenceAuditRecord fields and intake ordering without inventing missing timestamps or reasons.
- PersistentStorageManager._read_stage_b_baseline(session_id, pending=None, *, allow_handoff_refresh=False): Validates complete or explicitly partial Kill preservation, intake audit, Session associations, product coverage, and manifests, with the refresh-only mismatch allowance unavailable to collection or closure.
- PersistentStorageManager._handoff_collection_guard(session_id): Uses the unchanged final Session Record for nonblocking OS serialization of handoff refresh, collection, closure, and archive repair across StorageManager instances.
- PersistentStorageManager._validate_collection_outcome(session_id, message): Validates the retained owner/Session/evidence identity and separate success, failure, or unknown collection outcomes.
- PersistentStorageManager._collection_evidence_line(message): Serializes one stable collection message with type-sensitive JSON identity for append and retry checks.
- PersistentStorageManager._write_collection_outcome(message): Non-overwritingly publishes and fsync/readback-confirms the temporary actual outcome before any direct archival append.
- PersistentStorageManager._append_collection_evidence(message, *, expected_baseline=None): Preserves confirmed historical bytes, completes only the matching outcome append and provenance update, verifies current durable products, and safely retires the temporary outcome.
- PersistentStorageManager._saved_collection_result(message): Reconstructs existing ArtifactCollectionResult objects from retained outcome evidence without reexecuting collection.
- PersistentStorageManager._require_rewritable_session_archive(session_id, *, recovery_compilation=None): Checks actual archive coverage, provenance, and intake before ordinary replacement, refusing direct collection evidence despite missing origin metadata and permitting only identified trusted acquisition prefixes during authorized repair.
- Configured evidence publication requires the awaited collection method; collect_artifacts rejects that configuration rather than silently bypassing publication, while legacy unconfigured synchronous collection remains supported.
- PersistentStorageManager._verify_artifact: Selects the current framework-managed HDF5 contract from existing manifest format metadata and checks read-only structure, identity, and counts without reading scientific datasets or altering copies.
- _VerificationReader: Private read-only HDF5 file-access wrapper tracking actual I/O failure without retaining callback tracebacks, so format rejection is classified independently of diagnostic wording.
- PersistentStorageManager._retrieve_artifact: Selects the existing manifest source, captures copied size from the temporary file position when available, and returns the deterministic destination/size after closed-file non-overwriting promotion and best-effort temporary removal.
- PersistentStorageManager._pull_sftp_file: Uses Paramiko to open the source directly and copy bounded chunks through SFTP without a source existence/stat pre-probe.
- PersistentStorageManager.write_initial_session_record: Writes caller-supplied initial Session Record evidence to `session_<session_id>/session_record_initial.json`.
- PersistentStorageManager.write_evidence_archive: Writes compiled persistent runtime evidence, runtime-evidence audit, and compilation summary to the unchanged Phase 13 files, retaining exact successful write input and invalidating prior confirmation on a failed rewrite.
- PersistentStorageManager._write_session_evidence_archive(session_id, compiled_runtime_evidence, *, authorized_recovery=False): Reuses the existing locked/fsynced Session archive writer with ordinary replacement checks or the already-authorized acquisition-repair path, without changing public signatures.
- PersistentStorageManager.write_final_session_record: Writes caller-supplied final Session Record evidence to `session_<session_id>/session_record_final.json`, confirming its path only after successful writing.
- PersistentStorageManager.write_acquisition_stage(session_id, compiled_runtime_evidence, *, receipt, **session_record_evidence): Reuses archive/record writers and fsync/readback, adds Stage A/open/provenance metadata to the existing summary only after required products are confirmed, and refuses implicit repair of interrupted or unconfirmed existing persistence.
- PersistentStorageManager.write_kill_acquisition_stage(session_id, compiled_runtime_evidence, *, uncertainties, **session_record_evidence): Reuses acquisition persistence with explicitly partial Kill metadata, preserving uncertainty without fabricating receipt or completion-marker provenance.
- PersistentStorageManager._write_acquisition_stage: Shares durable product writing between verified Normal Stop and explicitly partial Kill while keeping their confirmation requirements separate.
- PersistentStorageManager._publish_preservation_summary(path, summary): Atomically publishes fsynced existing-summary metadata and verifies directory durability and exact readback.
- PersistentStorageManager.get_acquisition_stage_preservation_confirmation(session_id): Requires exact current evidence/audit/summary and final-record preservation plus Stage A complete/open metadata, rather than trusting a stored flag or historical success.
- PersistentStorageManager.write_artifact_collection_handoff(session_id, handoff): Durably publishes the existing compiled handoff in the Session directory with non-overwriting publication, exact readback, and identical-content retries.
- PersistentStorageManager.refresh_partial_artifact_collection_handoff(session_id, *, ingestor): Verifies journal-backed authorized manifest recovery, appends accepted evidence and audit, and refreshes an open partial handoff only before collection starts.
- PersistentStorageManager.read_artifact_collection_handoff(session_id): Validates saved handoff identities, structure, and finalization uncertainty without any original Session binding, refusing missing/corrupt/unconfirmed contents.
- PersistentStorageManager._validate_artifact_collection_handoff(session_id, handoff): Checks the existing portable handoff structure and consistent Session/artifact identities without interpreting scientific contents.
- PersistentStorageManager._artifact_collection_handoff_path(session_id): Locates the separate handoff JSON using a validated single-component Session identity.
- PersistentStorageManager._sync_artifact_handoff_directory(path): Confirms supported directory durability after handoff publication or identical retry.
- PersistentStorageManager._read_artifact_collection_handoff_contents(session_id, path): Reads and validates handoff JSON while refusing duplicate fields instead of silently selecting conflicting values.
- PersistentStorageManager.get_session_preservation_confirmation(session_id): Canonically compares current archive products, including the retained complete compilation summary, and final Session Record with successful write inputs, returning detached confirmation including the summary or None; the snapshot alone does not guard commitment.
- PersistentStorageManager._write_record_contents: Writes serialized Session Record or Stage A summary contents with flush/fsync and supported directory durability, without creating lifecycle evidence.
- PersistentStorageManager._read_archive_products: Reads the existing evidence/audit/summary products for exact current-write confirmation, without interpreting evidence meaning.
- PersistentStorageManager._framework_evidence_write_safe: Allows new protected informational/recovery evidence archival only for a pristine target or currently confirmed archive, not implicit repair of existing unconfirmed products.
- PersistentStorageManager._recover_archive_write: Uses existing journal-backed authorization/attempt admission to recover either legacy compiled archival or an identified durable Stage B outcome append without refetching scientific artifacts or requiring the old Session intake.
- PersistentStorageManager._recover_archive_write_contents: Retains the existing repair contracts and partial Kill provenance for explicit interrupted-write recovery without refreshing a handoff or executing artifact transfer.
- PersistentStorageManager._recover_session_record_write: Repeats an interrupted initial/final record write only from complete retained original inputs, confirming actual contents without advancing Session lifecycle.
- PersistentStorageManager._recover_artifact_transfer: Makes one authorized fresh complete transfer from the original failed collection and authoritative handoff through existing destination/source/verification mechanisms, retaining normal global collection evidence.
- PersistentStorageManager.session_preservation_guard(session_id): Synchronous context manager yielding current confirmation while holding the archive/final-record write lock through the caller's release commit; callers must not await or acquire a new Ingestor intake lock while holding it.
- PersistentStorageManager.write_framework_evidence_archive(compiled_runtime_evidence): Writes and flushes/fsyncs existing evidence/audit/summary products under storage_root/framework/evidence, invalidating previous confirmation before a rewrite.
- PersistentStorageManager.get_framework_preservation_confirmation(): Compares all three current durable framework products with the exact successful compilation, without requiring a Session Record or accepting stale/partial writes.
- PersistentStorageManager.framework_preservation_guard(*, require_closeout=False): Holds the existing storage lock through a synchronous preservation check and retirement commit, optionally requiring exact final Ingestor evidence/all-audit coverage retained before its retirement; archive rewrites do not replace that requirement.
- PersistentStorageManager._retain_framework_closeout_compilation(compilation): Retains detached final Ingestor coverage within the existing confirmation mechanism without writing new archive products or interpreting evidence.
- PersistentStorageManager.maintenance_blockers(ingestor, storage_manager): Reports failed persistence or unpreserved owned collection evidence, while active operations are separately tracked and future collections are not blockers.
- PersistentStorageManager.maintenance_diagnostics(ingestor, storage_manager): Reports unfinished archive/path scopes and original collection-result preservation using existing identities without repairing persistence or releasing artifacts.
- Controller.maintenance_blockers(ingestor, storage_manager): Reports active Session, unfinished work, cleanup, final-record, and current decision-archive obligations without requiring other idle services to stop.
- Controller.maintenance_diagnostics(ingestor, storage_manager): Reports owned bindings, confirmed previous release, framework-attempt outcomes, and the last informational reconciliation separately from administrative abandonment without coordinating recovery.
- AcquisitionNode.maintenance_blockers(ingestor, storage_manager): Reports owned Session participation, reservations, unfinished acquisition/streams, unpreserved manifests, and unreleased devices.
- AcquisitionNode.maintenance_diagnostics(ingestor, storage_manager): Reports participation/reservation, actual running/failure flags, device shutdown, stream finalization, and durable manifest handoffs without weakening node-owned safety guards.
- SynchronizationManager.maintenance_blockers(ingestor, storage_manager): Reports running Session Time, active mappings, and mapping evidence without confirmed durable Ingestor acceptance.
- SynchronizationManager.maintenance_diagnostics(ingestor, storage_manager): Reports clock/mapping obligations and journal-backed handoff confirmation, retaining broader timing restrictions when Session scope cannot be established.
- InMemoryIngestor.maintenance_diagnostics(ingestor, storage_manager): Reports retained Session intake, journal failures, and supported known-journal recoverability without claiming recovery or deleting evidence/journals.
- Principal-service _close_maintenance_resources(force): Reuses each target's existing resource cleanup without clearing evidence, deleting journals, or cascading closeout to other services.

## src/lab_sync_acquisition/synchronization.py

- SynchronizationMapping: Stores the accepted immutable local-to-Session mapping fields with a plain-data round trip.
- AcquisitionNodeLocalTimeReport: Stores one immutable AcquisitionNode local-time report as plain data without representing SynchronizationObservation evidence.
- MappingUpdateEvidence: Stores immutable created, replaced, or retired mapping evidence with optional previous/new mappings and a plain-data round trip.
- MappingUpdateEvidence.to_runtime_evidence_message: Wraps mapping update plain data in the existing RuntimeEvidenceMessage boundary using evidence type `mapping_update_evidence`.
- SynchronizationManager: Owns the Session clock, measured affine mapping validity and lifecycle, quality evidence and publication identities without advanced drift estimation.
- SynchronizationConfiguration(exchanges, initial_scale, clock_rate_error_bound, max_uncertainty_s, max_mapping_age_s, assessment_interval_s, result_window_s, quality_interpretation): Requires explicit finite measurement/rate/age/cadence bounds and a supported degraded-condition policy label, with to_dict/from_dict round trips.
- SynchronizationManager.configure_distributed_session(session_id, configuration): Validates and binds explicit immutable Session synchronization configuration under the mapping lock.
- SynchronizationManager.distributed_configuration: Exposes the immutable configured distributed measurement contract.
- SynchronizationManager.start_distributed_session(session_id): Starts the prepared single Session clock once, refusing stopped-clock restoration and preserving its epoch on retries.
- SynchronizationManager.assess_cross_clock_exchanges(session_id, node_id, exchanges, *, replace_mapping, source_id): Intersects causal measured offset intervals including clock resolution/rate error, owns validity and optional mapping replacement, and retains quality evidence.
- SynchronizationManager.session_timing_evidence(session_id, source_id): Returns stable mapping-update and quality evidence identities for current Session publication without archival claims.
- SynchronizationManager.mark_synchronization_unavailable(session_id, node_id, source_id, reason): Preserves the measured relationship while reporting failed quality assessment without fabricated clock information.
- SynchronizationManager.prepare_session(session_id): Confirms Session-specific preparation independently of pre-Session service readiness, rejecting a different active preparation binding.
- SynchronizationManager.abort_session_initialization(session_id): Clears only matching preparation state without altering mapping or established timing evidence.
- SynchronizationManager.complete_session_evidence_publication(session_id, *, source_id, publisher): Stops prepared Session Time, retires only that Session's mappings, retains stable message identities and publishes its timing evidence before confirmation, guarding further timing changes without service retirement or archival claims.
- SynchronizationManager.release_session(session_id, *, ingestor=None): Releases matching stopped preparation only after mapping updates and distributed quality evidence have exact durable Ingestor acceptance, then retires temporary history without terminating the service.
- SynchronizationManager.create_and_activate_mapping: Creates and atomically activates one initial immutable mapping for an AcquisitionNode.
- SynchronizationManager.replace_active_mapping: Atomically replaces one active mapping and records replacement evidence.
- SynchronizationManager.retire_active_mapping: Retires one active mapping and records retirement evidence.
- SynchronizationManager.get_active_mapping: Returns the currently active mapping for one Session and AcquisitionNode.
- SynchronizationManager.reconcile_timing(session_id, *, active_session, ingestor): Asynchronously reads journal-backed historical mapping updates and reports current-reference confirmation, continuity gaps, scope, and uncertainty without restoring a clock or activating old mappings.
- SynchronizationManager.timing_reconciliation_evidence: Returns detached retained persistent timing findings for existing evidence preservation.
- SynchronizationManager._lost_time_scopes: Derives diagnosed ongoing lost-time restrictions from retained findings, preventing zero-based restart/current-time fabrication without a recovery registry.

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

## scripts/manual_opencv_camera_smoke.py

- main(argv=None): Checks camera readiness without scientific reads, explicitly selects scientific acquisition with optional post-validation visualization, or inspects existing HDF5 recordings read-only.
- view_hdf5_frames(path): Reads up to six evenly spaced camera frames read-only, labels recorded indices, converts BGR/BGRA for Matplotlib display, and returns a saved PNG path when graphical display is unavailable.
- _inspect_frames: Reports visualization errors as nonzero CLI exits without changing the recording or acquisition behavior.
- verify_scientific_artifact(manifest, experiment_start_session_time_s, frame_shape, frame_dtype): Reopens a finalized camera HDF5 artifact read-only and verifies manifest counts, declared shape/dtype, ordered indices, aligned runtime timing, and per-frame metadata.
- _camera_source: Converts a CLI camera index to an integer while preserving backend source strings.
- _run_scientific: Orchestrates the existing Controller/AcquisitionNode scientific acquisition and local persistence path using explicit camera-product declarations and selections.
- _require_success: Reports an unsuccessful Controller command without replacing its original error text.
- _cleanup: Attempts camera/runtime and local storage resource cleanup independently and reports cleanup errors without hiding acquisition errors.

## scripts/demo_nats_runtime.py

- DemoOperationalAdapter: Provides a ready demo adapter whose empty scientific selection performs no reads.
- main: Manually validates Controller command, AcquisitionNode execution/result/evidence, Ingestor evidence intake, and Core NATS telemetry against a real JetStream-enabled NATS server.

## Phase 14 / Slice 22 Integration - Completed

Decisions 240-244 are implemented through these existing components:

M010 is complete following manual IPython validation and independent audit PASS;
W031 records results and limitations. Slice 22 implements no artifact-byte retrieval;
the separate Slice 23 implementation below still awaits real Jetson/SSH-SFTP
deployment validation (M011), distinct from W032's software validation.

- LocalStorageManager retains artifact and manifest ownership; existing manifests and finalization results supply complete discovery information.
- AcquisitionNode.artifact_manifest_evidence: Returns produced persistent RuntimeEvidenceMessage snapshots containing complete initial and finalized manifests, also submitted to the attached local Ingestor at the scientific lifecycle boundaries.
- AcquisitionNode.health_runtime_evidence: Returns health messages retained at production with original Session/node-scoped identities, preventing interrupted publication or later reuse from relabeling them.
- AcquisitionNode._record_artifact_manifest(manifest, *, resubmit_unconfirmed=False): Packages each manifest lifecycle state once and permits explicitly authorized recovery to resubmit its identical retained message only while durable Ingestor acceptance is unconfirmed, without changing normal finalization or local ownership.
- NatsAcquisitionNodeCommunication.publish_new_artifact_manifest_evidence(): Serializes overlapping publication passes through an asynchronous lock and advances the manifest cursor only after each entry's durable acknowledgment, retaining failed/cancelled entries for later publication before command results.
- NatsAcquisitionNodeCommunication.publish_new_runtime_evidence(): Serializes retained lifecycle/health/failure publication without changing original identities and advances progress only after durable acknowledgment.
- NatsAcquisitionNodeCommunication.publish_evidence(message): Retains unconfirmed node-owned messages for explicit later publication and requires durable acknowledgment before removing the obligation.
- InMemoryIngestor.compile_artifact_collection_handoff(session_id): Groups retained Session-scoped artifact_manifest messages by manifest identity, selects complete finalized or initial manifests, and returns session_id plus artifacts entries containing artifact_manifest and missing_finalization_evidence.
- Controller.finalize_session(): Retains legacy finalization for Sessions without a Q019 marker; for a produced Q019 marker it refuses unconfirmed publication and requires current Stage A/handoff coverage before completion, without rewriting the acquisition archive or discarding its summary metadata.
- StorageManager owns Artifact Plane retrieval and global storage; byte retrieval was outside Slice 22 and is now implemented separately in Slice 23, with real Jetson/SSH-SFTP deployment validation still pending under M011.

The historical implemented persistent-evidence compilation and Evidence Archive
writing paths remain unchanged. Accepted Decisions 357-359 require subsequent
two-stage persistence and durable handoff integration; those changes are not
implemented. Slice 27 adds known-Session restart reconstruction without modifying
this compiler; diagnostics compilation and application-wide restart remain deferred.

## Phase 14 / Slice 23 Integration - Pending Real Deployment Validation

- Controller.collect_session_artifacts(): Explicitly initiates collection after the Session ends, compiles the existing handoff, and returns aggregate results in ControllerCommandResult.details without changing Session lifecycle or persistent Session products.
- Controller.collect_session_artifacts_with_evidence(): Requires a stopping Session and stopped acquisition runtime, guards active collection/publication against overlapping collection or finalization, and releases the guard on success, failure, or cancellation without translating evidence or changing lifecycle.
- Controller.collect_saved_session_artifacts(session_id, *, evidence_id): Coordinates explicit eligible/available known-Session collection with under-lock StorageManager enforcement and returns results plus archival confirmation without restoring bindings or changing Session lifecycle.
- Controller.collect_selected_session_artifacts(selections): Independently assesses a Session-ID-to-stable-evidence-ID mapping, blocks unavailable candidates, reuses per-Session collection, and reports individual outcomes plus complete_success, partial_success, or failure without automatic retries.

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
closeout guarantee remains OPEN in Q019. Decision 361's new transport ACK
confirmation/receipt readback does not implement Controller closeout orchestration.
M013 is complete. W033 records manual software validation, the initial audit FAIL,
P1/P2 corrections, and final independent re-audit PASS. M011 remains open and
M012 remains complete; Q019 is not resolved by software closure.

Decision 303 resolves the former Q017 without changing these APIs or result
vocabularies: later global collection, verification, transfer, or export failure
cannot retroactively change a completed Session's lifecycle. Required
pre-completion failure handling remains unchanged. Q019's Session-wide consumption/
staged archive coordination is accepted in Decisions 356-365; the receiving
foundation and Decision 366 producer/marker prerequisite do not provide full
staged closeout. W042 records independent validation and targeted re-audit PASS
for the latter prerequisite after correction. Explicit Stage A archival is complete
with developer tests, independent manual validation, and independent audit PASS
(W043); bounded Stage B collection/evidence persistence is complete with independent
manual validation and final targeted independent re-audit PASS after correction
(W045); W046 explicit permanent closure is complete with independent manual
validation and targeted independent re-audit PASS after correction. Bounded W047
Normal Stop orchestration is complete with independent manual validation and
targeted independent re-audit PASS after both P2 corrections. Initial developer
tests 19/19 and manual checks 6/6 passed; initial audit FAIL exposed pre-marker
cancellation enabling legacy completion and late acquisition intake omitted from
the final record. Correction tests 12/12 and independent checks 3/3 passed, followed
by re-audit PASS with no remaining confirmed P0-P3 findings. It uses the launched
command/result boundary and a
matching W041 Ingestor receiver; incomplete preservation retains the stopping
binding, while node cleanup failures use the existing failed-Session path.
Cancellation propagates, releases operation admission, and retains obligations.
Explicit retry resumes closeout without repeating confirmed node shutdown or
automatically repairing unsafe products. Successful repeated completion rechecks
current coverage without rewriting products. The existing independent release
workflow still refreshes the pre-completion final record with the terminal outcome;
Stage B collection remains a later explicit request and permanent closure is never
automatic. Kill integration and overall closeout validation remain deferred.

## tests/test_normal_stop.py

- NormalStopTests: Exercises public brokered Normal Stop ordering, multiple/optional nodes, active Experiment termination, independently verified receipt, persistence and handoff failures, current-archive corruption, cancellation/overlap, explicit retries, Q019-aware finalization, and unchanged scientific files using existing transport doubles.
- NormalStopTests.connect_receipt(): Connects the existing broker-double durable receipt callback and controlled marker-time delivery without substituting framework owners or receipt verification.
- NormalStopTests._exercise_late_operational_intake(accepted): Exercises cross-thread accepted operational evidence or rejected-intake audit after handoff preservation, completion refusal, unchanged historical products and explicit retry before safe release.

## tests/test_acquisition_stage_archival.py

- AcquisitionStageArchivalTests: Exercises W041/W042-to-Stage-A persistence, full persistent evidence/all-audit coverage, receipt uncertainty, journal loss, write failures, cancellation, scope isolation, and safe explicit repetition through public APIs and existing broker doubles.

## tests/test_durable_artifact_handoff.py

- DurableArtifactHandoffTests: Exercises durable manifest handoff readback, missing finalization, malformed data, interruption, concurrent publication, safe retry, and known-Session restart lookup through real persistence.
- CloseoutArtifactHandoffTests: Exercises the explicit post-Stage-A Controller step, protected journal/archival prerequisites, failure retention, unchanged Stage A products, and applicable release protection with later binding-independent readback.

## tests/test_stage_b_collection.py

- StageBCollectionTests: Exercises known-Session Stage B using real persistence and SSH-only doubles, including W043/W044 integration, restart/other-Session baselines, independent failure/unknown outcomes, direct evidence provenance, concurrent idempotency, corruption, interruption, authorized evidence-only recovery, and unchanged historical products.
- StageBCollectionTests.test_cross_session_historical_intake_cannot_confirm_baseline(): Checks historical saved-record validation without legacy writers, retaining conflicting bytes and blocking collection.
- StageBCollectionTests.test_incomplete_historical_intake_cannot_confirm_preservation(): Checks missing historical audit fields block confirmation and collection without modifying saved data.

## tests/test_remote_saved_collection.py

- CollectionBroker: Models durable command-result history independently from simulated reply delivery/drop for collection transport tests.
- CollectionBroker.stream_info(name): Exposes independent result-stream history metadata for authoritative attempt readback.
- CollectionBroker.get_msg(stream, **options): Reads retained result publications through the same filtered stream API used by the production adapter.
- CollectionBroker.publish(subject, data, stream): Retains owner result publications even when the simulated requester loses the reply.

- run_storage_owner(url, root, files, ready, stop): Runs shared-process Ingestor/StorageManager owners with simulated SFTP and real NATS for remote collection tests.
- RemoteSavedCollectionTests: Exercises Controller-driven remote saved-Session collection through real storage guards and NATS request/result adapters.
- RemoteSavedCollectionTests.subscribe(storage): Replaces only the test storage transport subscriptions to exercise restart readback with a new owner.
- RemoteSavedCollectionTests.collect(identity="collection", session="session"): Issues explicit collection through the Controller's public remote method.
- RemoteSavedCollectionTests.test_lost_reply_retry_and_owner_restart_do_not_refetch(): Verifies missing replies remain unconfirmed and stable retry reuses durable outcomes across owner restart.
- RemoteSavedCollectionTests.test_ineligible_corrupt_and_closed_sessions_do_not_transfer(): Checks stopping, damaged preservation and closed archives cannot authorize new retrieval or archive mutation.
- RemoteSavedCollectionTests.test_collection_failure_reports_durable_outcome_without_false_success(): Distinguishes preserved failure evidence from successful scientific collection.
- RemoteSavedCollectionTests.test_wrong_identity_stale_reply_and_missing_service_remain_unconfirmed(): Rejects mismatched collection command identity and refuses stale or absent owner replies.
- RemoteSavedCollectionTests.test_repeated_overlapping_requests_preserve_one_collection_identity(): Exercises concurrent caller requests without repeated scientific transfer.
- RemoteSavedCollectionTests.test_owner_revalidates_after_status_before_transfer(): Refuses retrieval when persisted lifecycle changes after the preliminary status snapshot.
- RemoteSavedCollectionTests.test_rejected_attempt_stays_rejected_but_explicit_retry_can_collect(): Keeps repeated delivery of a rejected nonce rejected across owner restart while allowing an explicit fresh-nonce retry.
- RemoteSavedCollectionTests.test_unconfirmed_result_history_blocks_new_collection(): Refuses collection when result-history readback is unavailable or retained history has gaps.
- RemoteSavedCollectionTests.test_rejected_attempt_survives_failed_reply_publication(): Retains an unpublished rejection so later delivery cannot reevaluate it after eligibility changes.
- RemoteSavedCollectionTests._reject_corrupted_result(change): Reproduces rejected collection, controlled result corruption, eligibility resolution and owner reconstruction through the public command path while checking no transfer, archive change or repair.
- RemoteSavedCollectionTests.test_missing_persisted_nonce_cannot_reactivate_rejected_collection(): Refuses redelivery when a prior rejection lost its required nonce.
- RemoteSavedCollectionTests.test_persisted_source_mismatch_cannot_reactivate_rejected_collection(): Refuses redelivery when a stored rejection disagrees with its source subject.
- RemoteSavedCollectionTests.test_same_nonce_destination_conflict_blocks_rejected_replay(): Rejects a preserved attempt nonce with altered destination without transfer or history repair.
- RemoteSavedCollectionTests.test_same_nonce_command_conflict_blocks_rejected_replay(): Rejects a preserved attempt nonce with altered canonical command identity without transfer or history repair.
- RemoteSavedCollectionTests.test_same_nonce_conflicts_after_matching_history_block_collection(): Checks conflicting unrelated nonce resolutions even after finding the requested attempt, preserving evidence and historical results.
- RemoteSavedCollectionTests.test_invalid_result_correlation_blocks_collection(): Exercises missing fields, malformed correlation types, Session/command/status mismatches and invalid payloads through actual owner-history matching.
- RemoteSavedCollectionTests.test_valid_unrelated_attempts_and_other_sessions_remain_isolated(): Allows valid explicit collection despite unrelated valid attempt and other-Session results.
- RemoteSavedCollectionTests.test_conflicting_attempt_resolutions_block_collection(): Rejects contradictory persisted resolutions instead of choosing the first matching record.
- RemoteSavedCollectionTests.test_success_result_requires_matching_collection_evidence(): Refuses successful-history replay with corrupted evidence, Session or source identity without refetching or changing archives.
- RemoteSavedCollectionTests.test_cancelled_result_publication_retains_rejection(): Preserves the original rejected attempt through publication cancellation and later redelivery.
- RemoteSavedCollectionTests.test_rejected_collection_is_not_replayed_after_process_restart(): Reproduces rejected stopping-Session collection followed by eligibility resolution and owner restart, proving no automatic transfer or evidence write with real JetStream.
- RemoteSavedCollectionTests._separate_process_collection(*, reject_first): Coordinates real local JetStream storage-process restart and public readback barriers for success/rejection workflows without arbitrary sleeps.
- RemoteSavedCollectionTests.test_separate_storage_process_collects_and_retries_after_restart(): Uses real local JetStream with separate Controller/storage processes, overlapping requests and restart-safe saved outcome readback.

## tests/test_nats_evidence_readback.py

- EvidenceReadbackBroker: Reuses controlled command/result and evidence delivery for authoritative operational readback without scientific-envelope transport.
- NatsEvidenceReadbackTests: Exercises current journal-verified compilation, W041 receipt, restart/corruption readback, authorization boundaries and missing/stale/mismatched replies through public NATS adapters.
- NatsEvidenceReadbackTests.request(peer, operation, payload=None, *, session="session", identity="read"): Issues a current scoped owner request with the existing per-attempt correlation mechanism.
- NatsEvidenceReadbackTests.preserve_session(): Creates real Stage A and handoff products for current owner-readback tests without scientific observation intake.
- NatsEvidenceReadbackTests.test_exact_acceptance_requires_journal_intake_not_publication(): Separates publication from exact durable acceptance and rejects conflicting content or damaged journal readback.
- NatsEvidenceReadbackTests.test_misrouted_evidence_is_not_accepted_or_acknowledged(): Rejects Session/source/type mismatches between evidence and its delivered subject before intake or ACK.
- NatsEvidenceReadbackTests.test_failed_journal_delivery_recovers_after_restart_without_duplicate(): Leaves failed journal delivery unacknowledged and deduplicates stable evidence identity after restart.
- NatsEvidenceReadbackTests.test_acceptance_readback_rejects_wrong_session_and_stale_replies(): Keeps wrong-Session, stale and missing confirmations unconfirmed through the public requester.
- NatsEvidenceReadbackTests.test_cancelled_intake_callback_redelivers_without_duplicate_acceptance(): Preserves journal-before-ACK and avoids repeated callback side effects after cancellation and redelivery.

## tests/test_operational_evidence_transport.py

- run_evidence_receiver(url, journal, ready, stop): Runs the authoritative Ingestor and its NATS subscriptions in a spawned process with explicit test startup/shutdown coordination.
- OperationalEvidenceTransportTests: Exercises operational evidence publication and exact intake readback across a real local JetStream process boundary.
- OperationalEvidenceTransportTests.test_publication_retry_and_receiver_restart_preserve_exact_intake(): Checks offline publication, lost publication confirmation, stable retry and receiver restart without duplicate accepted evidence or scientific intake.

## tests/test_kill_session.py

- KillSessionTests._exercise_late_kill_operational_intake(accepted): Checks late accepted evidence or rejected audit blocks Kill reconfirmation/release while preserving the immutable historical products and retained journal.
- KillSessionTests.test_empty_kill_retains_binding_when_summary_write_fails(): Exercises admitted Kill with broker evidence delivery unavailable, proving empty intake cannot bypass a failed preservation obligation.

## tests/test_permanent_archive_closure.py

- PermanentArchiveClosureTests: Exercises explicit closure, durable failed/unknown collection outcomes, pending writes and authorized recovery, corruption, interruption/restart, concurrent requests, and immutable Session archive products through public StorageManager interfaces.

## tests/test_producer_publication_completion.py

- PublicationBroker: Reuses existing transport doubles to record publication ordering and inject controlled acknowledgment failures or pauses without substituting framework owners.
- HealthNode: Test-only AcquisitionNode fixture with explicit missing-frame policy for real health-evidence production.
- interpretation(identity="observation"): Constructs valid health interpretation input for public Controller/communication workflows.
- ProducerPublicationCompletionTests: Exercises producer publication, overlapping command callbacks and health passes, failed/cancelled publication retry, correlation, pending health work, stable marker interruption/repetition, and scope isolation through public APIs.
- RealProducerPublicationTests: Exercises overlapping Session-scoped preparation and Session-independent inventory callbacks plus two-node evidence publication through isolated JetStream, followed by actual W041 receipt verification.

## tests/evidence_receipt_fixtures.py

- EvidenceReceiptBroker: Test-only JetStream state double for deterministic receipt, redelivery, missing-history, and invalid-progress workflows, reused by existing transport fixtures.
- EvidenceReceiptBroker.get_msg(stream, seq=None, subject=None, next=False): Supplies sequence/subject-filtered test history readback for public receipt reconciliation workflows.

## tests/nats_server_fixture.py

- temporary_jetstream_server(): Starts an optional isolated local NATS test process on a temporary port/storage directory and always cleans it up; it is not framework service startup or deployment supervision.

## tests/test_product_acquisition.py

- ProductAdapter: Supplies explicit selected non-frame observations and separately identified operational messages for public workflow tests.
- ProductAcquisitionTests: Covers installed-product authority, local scientific preservation despite independent write/intake failures, aggregated errors, lifecycle/health evidence, publication retry and journal reconstruction.
- ProductAcquisitionTests.node: Prepares installed declarations, selected Experiment outputs and owner-cleaned local storage through public interfaces.
- ProductAcquisitionTests.two_device_node: Prepares two selected device/product collections with real local storage and Ingestor intake for independent failure-preservation workflows.
- ProductAcquisitionTests.finalized_rows: Finalizes scientific artifacts and reads their rows using the node's public product-to-storage associations.

## tests/test_scientific_acquisition_persistence.py

- ScientificEventAdapter: Supplies explicitly keyed non-frame products, including controlled invalid scope for rejection workflows.
- ScientificAcquisitionPersistenceTests.workflow: Provides a scoped Controller/node/local-storage workflow with explicit installed declarations and Experiment selection, reused by collection-failure tests.
- ScientificAcquisitionPersistenceTests.saved_metadata: Reads finalized per-observation HDF5 metadata for public preservation assertions.

## tests/test_scientific_collection_failures.py

- FailingCollectionAdapter: Injects a later device's acquisition failure without producing unselected scientific observations.
- ScientificCollectionFailureTests: Verifies preservation of earlier complete observations through later reads, device failures, invalid partial results and combined persistence errors.
- ScientificCollectionFailureTests.assert_preserved_frame: Checks finalized bytes, provenance, timing and absence of scientific-envelope intake through actual owner readback.

## tests/test_distributed_synchronization.py

- configuration(**changes): Supplies explicit test synchronization bounds and a degraded-condition interpretation without production defaults.
- declaration(): Supplies one registered non-frame scientific product for transport and local-preservation workflows.
- DistributedSynchronizationTests: Exercises measured startup, Experiment lifecycle, affine mapping/provenance, scoped health context, degraded quality, cancellation, retries, publication failures and release safety through real owners and broker adapters.
- DistributedSynchronizationTests.collect_buffered: Delivers controlled buffered scientific observations through the public iteration command for acquisition-time mapping/quality and local artifact checks.
- DistributedSynchronizationTests.advance_local_clock: Waits for a strictly later representable local clock tick so buffered-observation transition tests do not depend on platform timer granularity.
- MeasuredClockBoundsTests: Verifies causal offset bounds under asymmetric delay/variability, explicit configuration rejection and detached stable timing evidence readback.
- run_participant(role, url, directory, ready, stop): Runs a test node or synchronization owner in a spawned process, with harness-only startup/shutdown signaling and NATS-only framework communication.
- CrossProcessTimingTests: Exercises independent node/clock processes against optional real local JetStream, checking scientific timing and finalized local output without shared service owners.

## tests/test_remote_archive_closure.py

- RemoteArchiveClosureTests: Exercises explicit single saved-Session permanent closure through real Controller, NATS adapters and StorageManager guards without local Controller owner references.
- RemoteArchiveClosureTests.asyncSetUp(): Reuses saved-Session collection fixtures with all cleanup owned by the active test case.
- RemoteArchiveClosureTests.close(session="session"): Requests explicit permanent closure through the Controller public NATS API.
- RemoteArchiveClosureTests.test_explicit_closure_preserves_products_and_does_not_release_services(): Confirms collection alone leaves the archive open and explicit closure preserves history without Session completion or service release.
- RemoteArchiveClosureTests.test_failed_collection_does_not_prevent_verified_closure(): Closes an archive containing durably preserved unsuccessful retrieval outcomes.
- RemoteArchiveClosureTests.test_missing_and_unresolved_preservation_prevent_closure(): Rejects absent or pending preservation until existing authorized recovery succeeds.
- RemoteArchiveClosureTests.test_rejected_attempt_remains_rejected_after_prerequisites_recover(): Preserves historical rejection across restart while permitting a fresh explicit request.
- RemoteArchiveClosureTests.test_lost_reply_restart_and_overlapping_retries_do_not_rewrite_closure(): Reuses closed products after lost replies, owner restart and overlapping requests without rewrite.
- RemoteArchiveClosureTests.test_closed_history_cannot_substitute_for_current_durable_archive(): Rejects historical success when current persisted closure is corrupted.
- RemoteArchiveClosureTests.test_cancelled_result_publication_retains_closure_but_requires_current_readback(): Refuses cached success after publication cancellation and subsequent archive corruption.
- RemoteArchiveClosureTests.test_failed_result_publication_can_retry_without_rewriting_closed_archive(): Retries an unpublished result without repeating closure publication.
- RemoteArchiveClosureTests.test_stale_success_response_cannot_confirm_another_request(): Rejects a prior attempt's successful reply for a fresh request.
- RemoteArchiveClosureTests.test_pending_closure_retry_rejects_malformed_history_without_rewrite(): Rejects cached closure success after failed reply publication when scoped history lacks a nonce, preserving archive and historical bytes.
- RemoteArchiveClosureTests.test_pending_closure_retry_rejects_conflicting_resolution(): Rejects cached closure success when persisted history resolves the same attempt differently.
- RemoteArchiveClosureTests.test_success_history_requires_matching_closed_summary(): Rejects malformed successful closure history without repairing archive or results.
- RemoteArchiveClosureTests.test_corrupt_attempt_history_blocks_closure_without_repair(): Rejects conflicting identities, missing nonce and source mismatch before closure.
- RemoteArchiveClosureTests.test_conflicting_tail_blocks_reuse_of_matching_resolution(): Validates conflicting records even after a matching closure resolution.
- RemoteArchiveClosureTests.test_missing_service_and_invalid_closure_request_remain_unconfirmed(): Leaves missing owner replies and malformed operation identity unconfirmed.
- RemoteArchiveClosureTests.test_separate_owner_restart_requires_explicit_closure_and_reuses_closed_archive(): Uses real local JetStream and a spawned shared Ingestor/StorageManager process to verify rejection, restart-only replay prevention, fresh closure and restart reuse.
