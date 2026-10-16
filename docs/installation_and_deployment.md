# Installation And Deployment

## Status And Scope

Q022-A Decisions 367-378 are accepted and synchronized. Full configuration/role
bootstrap and independent-service adaptation remain pending; bounded shared-process
launching is closed in W061. The bounded owner
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
W051/W052 record historical correlated scientific-envelope persistence validation.
Slice 3B removes those obsolete APIs under Decisions 377-378 and is complete after
independent validation and corrective re-audit PASS (W054); operational
evidence journaling and owner-side preservation remain authoritative. Shared-lifetime
bootstrap/launch composition is not implemented in this bounded persistence slice.

## Accepted Manual Service Entry Points (Decisions 383-388)

The bounded W061 launcher below is independently validated and audited PASS;
full role composition and the remote operator interface are not implemented. One
common CLI launches/administers the existing Controller, AcquisitionNode,
Ingestor, StorageManager and SynchronizationManager capabilities. Decision 376's
shared Ingestor/StorageManager process lifetime remains mandatory; other roles
operate independently. Reuse initialization, NATS, readiness and maintenance;
the CLI neither provisions configuration nor manages NATS or supervises services.

Ctrl+C invokes local maintenance Stop using the OS username as administrator.
Confirmed completion permits exit only after required final result
publication/handling. Blocked Stop automatically invokes Cancel, reports its
outcome and leaves the process running. Failed or unconfirmed Stop does not
silently exit. There is no interactive Kill or repeated-Ctrl+C forced exit.

A separate terminal sends existing NATS Stop, explicitly authorized Kill or Cancel
directly to an identified service without Controller. Kill continues the same
blocked stop attempt; Cancel ends it without force. Reuse command IDs,
stop-attempt IDs and RuntimeParticipant identities, with a temporary requester ID
per invocation and explicit administrator identity for remote commands. These
identities are records, not new authentication infrastructure.

Feedback distinguishes confirmed completion, blocked, failed, rejected and
unconfirmed, reporting target, attempt, blockers/errors, outstanding obligations
and operator action. Only confirmed successful terminal commands return exit code
0; other terminal outcomes are nonzero. These are presentations of existing
outcomes, not new lifecycle states. Operational retirement is distinct from OS
process exit, Session-binding release, Session/Experiment termination and general
framework shutdown. Existing preservation, cleanup and safety obligations remain.
Configuration provisioning and Q024 recovery remain outside these decisions.

### Common Launcher (W061 Closed)

The package installs `lab-sync-acquisition`; source-tree invocation also works as
`python -m lab_sync_acquisition.service_launcher`. `--help` lists all five logical
roles. Currently `ingestor` and `storage-manager` are aliases for the same paired
process, not independent processes. For example, using explicitly chosen local
paths, identities and a preservation window:

```text
lab-sync-acquisition ingestor --server nats://HOST:4222 --ingestor-id INTAKE_ID --storage-id STORAGE_ID --storage-root PATH --recovery-journal-root PATH --framework-journal PATH --preservation-window-s SECONDS --no-operational-dependents
```

Every setting above is required; server arguments may be repeated. These arguments
pass existing constructor settings, not a new configuration-file schema or a
provisioning mechanism. No credentials or machine-specific settings are committed.
Retrieval-endpoint configuration and installation checks are not supplied here.
The CLI currently supports only an explicitly declared absence of external
operational dependents; it does not silently assume the dependency set is empty.
Do not use that declaration when producers depend on Ingestor. The reusable
`launch_storage_services()` interface accepts the existing explicit
`operational_dependents` callbacks; configuring distributed dependencies through
the CLI is unavailable, not replaced by discovery or fabricated availability.
Controller, AcquisitionNode and SynchronizationManager commands fail before startup
with an actionable diagnostic: their distributed framework-maintenance preservation
dependencies are not yet composed, and node installation requires explicit devices
and adapters. No extra local persistence owner substitutes for those dependencies.
Do not interpret help visibility as verified launch coverage for these roles.

The paired process uses the existing service-owned NATS command handlers, framework
evidence intake and journal, StorageManager preservation, and startup/readiness
announcements. It is not tied to Session lifetime. Ctrl+C requests maintenance
locally using a temporary requester and OS administrator name; it does not cancel
the running maintenance coroutine or escalate repeated interrupts into Kill.
SIGINT protection is installed before the asynchronous startup callback can admit
commands or evidence. Startup interruption cancels and awaits that callback before
attempting local Stop/Cancel; it does not close connections or discard admitted
Session/journal obligations. Cancellation of the launcher itself retains owners
instead of implying retirement. Pre-admission connection errors still fail startup;
partial-admission errors are reported separately and retain the process.
For orderly pair retirement, the existing StorageManager preparation precedes
Ingestor Stop and prepared StorageManager Stop, retaining evidence capabilities
until the accepted retirement boundary. Blocked Stop invokes Cancel for the same
attempt; failed/unconfirmed results retain the process and report obligations.
Already confirmed retirement is not falsely undone on a later failure.

Remote maintenance issuance is not a CLI command in this slice. Existing receiving
handlers remain usable: the launcher waits until final result publication and
delivery ACK finish before counting remote retirement toward process exit. Lost
publication or ACK leaves exit unconfirmed until an existing explicit retry is
handled. Notification carries the complete request and the exact result actually
published and ACKed, with Session/source/destination/command correlation checks.
A conflicting rejection cannot substitute another cached success with the same
command ID. Identical redelivery may publish the retained owner result normally.
Publication/handling confirmation does not claim requester receipt.
After all hosted owners retire, connections drain before normal exit.
Feedback reports existing outcomes, target/command/attempt identities, blockers,
errors and unresolved obligations; only confirmed successful completion exits 0.
Communication cleanup failures retain the process for explicit retry.

Run the focused developer checks with:

```text
python -B -m unittest tests.test_service_launcher -v
```

W061 is CLOSED following independent IPython validation (initial 18/18, then
22/22 after correction; overlapping sets) and focused independent re-audit PASS.
The initial audit FAIL identified cached-success substitution by a conflicting
rejection and unprotected partial-startup interruption; both P2 findings are
resolved with permanent regressions. Sandbox synchronous tests and controlled
coroutine probes passed; normal asynchronous runs stalled before setup in Windows
asyncio socket-pair initialization and are not claimed as passes. No live
JetStream, actual OS signal-delivery, physical hardware, full five-role deployment
or power-loss validation is established. See W061 in validated_workflows.md for
the complete record. Q022 remains OPEN.

## Scientific Data And Operational Evidence Boundary

Decision 377 requires routine scientific observations and per-observation metadata
to remain in AcquisitionNode's LocalStorageManager products, regardless of size.
Classification is by meaning: node-generated operational evidence and manifests
go to Ingestor through NATS, not the observations themselves. Local products retain
existing observation ordering/identity, available acquisition/device timestamps,
Session/Experiment/device/stream provenance and synchronization relationships.
SynchronizationManager remains timing authority; StorageManager later collects
artifacts without changing original scientific ownership or bytes.

Ingestor still owns runtime-evidence intake/audit, journal-before-ACK,
evidence_id deduplication, known-Session reconstruction and compilation. Existing
health/failure, lifecycle/terminal and manifest obligations remain. The bounded
node acquisition implementation now retains start/stop, health and failure
RuntimeEvidenceMessages for durable publication, separately from scientific rows.
No new formats,
evidence categories, or transport for future scientific streaming are defined.

Product-based node acquisition is complete with independent manual validation
and final re-audit PASS after correction (W053). All completed scientific
collections receive local preservation attempts before operational-evidence
handling; independent failures remain visible without false success or automatic
replay. Slice 3B removes obsolete owner-level envelope intake, persistence and
transport, with closeout reconciled against current operational evidence/audit
and manifests. This bounded owner replacement is complete after independent
manual validation and corrective re-audit PASS (W054). The initial audit FAIL
identified the P2 concurrent Normal Stop release/intake race and P3 unused envelope
configuration in a product-failure test; both were corrected. The combined final
Decision 377-378 implementation is accepted in W055 after functional audit PASS
and targeted correction of the sole remaining clean-replacement P3. The user and
ICC determined that no further independent re-audit was needed for that test-only
cleanup; the initial clean-replacement FAIL remains historical.
W051/W052 are historical validated envelope
paths, no longer required for routine scientific acquisition; active durability,
identity, corruption/readback and Q019 preservation/recovery/closure protections
remain. Existing saved products and validation results must not be rewritten.

Decision 378 makes installation-declared scientific products and explicit
Experiment selections authoritative: DeviceAdapters produce their declared and
selected observations/metadata for LocalStorageManager, separately from operational
evidence. AcquisitionNode must not guess meaning from payload size/content or
legacy `runtime_records` labels. The bounded adapter/manager/node path uses
`collect_products(products, *, session_id, experiment_id, acquisition_node_id)`:
`scientific_products` maps selected product IDs to complete observation rows,
and `operational_evidence` contains separate RuntimeEvidenceMessages. Empty
selection performs no scientific reads. Local JSONL/HDF5 persistence retains
the row's metadata and timing; it does not forward observations to Ingestor.
Cleanly replace `collect_records()` / `collect_scientific_records()` and obsolete
scientific-envelope transport, persistence, audit/recovery and compatibility paths,
including dead functions/types, redundant tests and obsolete descriptions. Retain
only interfaces and records serving accepted operational, historical-readback or
other authoritative responsibilities; W051/W052 history is not a compatibility
mandate. Preserve local scientific identity/order/timing/provenance, manifests,
operational events/health/synchronization, and all Q019 preservation/recovery guards.
Obsolete Ingestor/StorageManager envelope APIs are removed in Slice 3B.
New Session Records omit envelope/audit fields; historical fields, when present,
are validated as plain saved data without an active legacy writer. W055 records
final combined implementation acceptance, including functional integration and
the initial obsolete-fixture finding, correction and targeted verification.

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

Local development archival/collection and maintenance preservation use actual
Ingestor/StorageManager collaborators, including synchronous owner guards. Remote
single-Session collection/closure are validated in W058/W059; distributed active
Session closeout and independent release are validated and closed in W060,
described below. Decision 376 permits local Ingestor-StorageManager calls but
requires NATS for Controller and other process-crossing access. Broader remote
maintenance/recovery and deployment adaptation remain pending. Establish the
necessary service-owned NATS interfaces before
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

### Operational Evidence And Owner Readback

Slice 3B removes the W051/W052 scientific-envelope writers, correlated-write
APIs and NATS dispatch. Their historical validation and audit outcomes remain
unchanged in the validated-workflow records; they do not require obsolete code.
Construct `PersistentStorageManager(storage_root, ...)` with a directory, not
an envelope-record filename. Ingestor may hold that existing owner locally under
Decision 376; it does not instantiate a second StorageManager.

- `InMemoryIngestor.receive_runtime_evidence()` retains operational messages and
  manifests with existing journal-before-ACK, identity/deduplication and restart
  semantics. `compile_durable_session_evidence(session_id)` returns journal-verified
  persistent evidence, complete operational intake audit and the manifest handoff,
  not scientific observations or an archival-completion claim.
- `NatsIngestorCommunication` retains `compile_session_evidence` and
  `verify_acquisition_receipt` requests; the latter delegates to W041 owner proof.
- `NatsStorageManagerCommunication` retains readiness and
  `read_session_preservation`; no envelope persistence/readback command remains.
  Maintenance/recovery still requires the existing authorized owner interface.
- `NatsControllerCommunication.request_persistence_command(...)` retains scoped
  readback, fresh-only replies and per-attempt nonce correlation. Missing replies
  and failed readback never establish preservation or authorize release.

Controller's Session Records retain configuration/lifecycle/Experiment outcomes,
not copies of the operational Evidence Archive. Completion and release compare
current persistent operational evidence and the complete intake audit with exact
owner-side archival readback under existing guards. Kill obligations apply even
with no intake or unavailable archival confirmation; manifest handoff coverage
and terminal-state checks remain mandatory. Stage A/B, authorized recovery and
permanent immutability are not replaced by transport acknowledgments.

W054 records independent validation and corrective re-audit PASS for this bounded
replacement; W055 separately records final Decision 377-378 implementation
acceptance, not deployment certification.
Controller release holds intake -> preservation locks through final checks and
binding retirement, never across unsubscription awaits. Later accepted intake
remains Ingestor-owned and blocks release until current preservation is confirmed;
existing Stage A reconciliation is limited to accepted lifecycle boundaries and
cannot rewrite Stage B history or closed archives. Cross-process Controller
closeout, maintenance/recovery and release adaptation, shared-process bootstrap,
role launching and installation checks remain pending. No live deployment,
hardware or independent power-loss guarantee is established here. Q019 remains
CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.

### Acquisition Commands And Experiment Context

**Controller -> AcquisitionNode:** The original local `start_session()`,
`run_one_iteration()`, `stop_session()` and Experiment APIs remain in-process
development workflows. Launched Session startup/stop reuse existing NATS node
commands; Slice 2 adds actively used launched Experiment context/health activation
and finalization, synchronization readiness and current timing readback. Health
assignments in `start_launched_experiment` are keyed explicitly by node identity,
not broadcast across nodes or inferred from scientific product contents.
Canonical Experiment start precedes context delivery, and unsuccessful/cancelled
delivery retains terminal outcome and cleanup uncertainty separately. Remaining
broader closeout/release and external recovery adaptation stays outside this slice.
The node retains
Session-keyed reservations, terminal Experiment/file protections, device safety,
and W042 publication-before-success with concurrency-safe evidence cursors. A
timeout cannot prove cleanup or reservation release. Depends on receiving/timing
interfaces below, not creation of node collaborators in Controller.

### Timing And Synchronization

**Accepted target (Decisions 379-381; not implemented by documentation
synchronization):** SynchronizationManager establishes node-specific mappings
from sufficient measured cross-clock exchanges accounting for network delay,
variability and uncertainty. An initial mapping may use an explicit,
conservatively bounded clock-rate assumption without prior drift estimation.
Only SynchronizationManager determines validity, refinement and replacement;
periodic quality checks are distinct from complete resynchronization.

AcquisitionNode applies the authorized affine mapping locally:
`session_time = session_anchor + scale * (node_local_time - local_anchor)`.
Experiment Time derives from Session Time. Mapping changes apply atomically and
prospectively. Existing scientific observations/artifacts retain required Session,
Experiment, node-local, available device-native and timestamp-quality information;
mapping history and each node-local activation boundary support reconstruction
without requiring a mapping ID on every observation. Scientific observations and
their metadata remain local under Decisions 377-378.

Acceptable synchronization is required at Session acquisition readiness and before
each Experiment. Cadence and quality thresholds are configurable. Temporary
degradation preserves local timing, mapping provenance and explicit degraded
timestamp status; existing TimingQualityPolicy interpretation and Controller
authority determine consequences, not automatic acquisition termination. Reuse
existing NATS, schemas, evidence and storage contracts; do not assume shared
clocks, substitute message arrival time or issue per-observation network timestamp
requests. Q006/Q018 retain advanced algorithms, hardware synchronization and
offline refinement, except for the minimum demonstrably valid measurement method
required for this implementation. No additional clock authority or service is
introduced.

**Slice 2 implementation (complete; independent validation and audit PASS, W056):**

Construct remote nodes with `synchronization_source_id` and no local
SynchronizationManager. Set `SessionConfig.synchronization_configuration` to the
plain-data form of `SynchronizationConfiguration(exchanges, initial_scale,
clock_rate_error_bound, max_uncertainty_s, max_mapping_age_s,
assessment_interval_s, result_window_s, quality_interpretation)`; all values are
explicit, with no scientific timing defaults. `clock_rate_error_bound` bounds
absolute error in Session-seconds per node-local second relative to initial_scale.
The supported degraded-condition policy uses the configured interpretation label;
Controller records its corresponding decision without autonomous termination.

`Controller.start_launched_session()` uses the configured synchronization
participant over NATS before node acquisition. SynchronizationManager starts its
single clock once and intersects causal bounds from multiple timestamped exchanges,
including platform clock resolution and the explicit rate bound, without assuming
symmetric delay. Node-local validity deadlines bound continued use without
per-observation network requests. `assess_synchronization` retains the mapping;
`resynchronize` is an explicit measured replacement request. Periodic assessments
are cancelled on timing closeout/adapter close, not converted into automatic
acquisition termination or recovery.

Use `Controller.start_launched_experiment(...)` and
`stop_launched_experiment(...)` for launched distributed execution. They use
existing product preparation plus NATS context/health activation and scientific
finalization; applicable node evidence is published before successful results.
Canonical lifecycle remains Controller/Session-owned. Each observation uses its
node-local timestamp and applicable activation boundary; native timing remains
separate. New operational mapping activation and quality records use existing
RuntimeEvidenceMessage retention/publication and archival pathways, not scientific
payload forwarding or a new evidence transport.

Node-local quality application boundaries and owner-issued expiry remain retained
as timing-quality runtime evidence, so buffered observations keep acquisition-time
quality across later degradation, reassessment or remapping. Transient periodic
assessment/publication failures retain evidence and resume at the configured
cadence; explicit timing closeout and transport shutdown still cancel assessment.

Command identity and Session scope are admitted before stop cancellation.
Rejected commands cannot cancel monitoring; duplicate stops preserve identity.
Cancellation is awaited outside the runtime lock, before closeout evidence
publication. Failed publication remains unconfirmed and retained for retry.

The optional cross-process developer test uses actual local JetStream with
SynchronizationManager and AcquisitionNode in separate spawned processes. Other
focused workflows use broker doubles and real domain owners. W056 separately
records independent user-run IPython validation and final read-only audit PASS,
including actual local JetStream verification. Neither establishes hardware timing,
multi-host accuracy, power-loss recovery or advanced synchronization guarantees.
W001-W055 remain unchanged; Q006/Q018 remain OPEN; Q019 remains CLOSED and Q022 OPEN.

**Remaining adaptation outside this slice:**

The established in-process APIs continue to use explicit local collaborators for
development/testing; the launched distributed timing/Experiment path above does
not depend on those objects. Broader Controller closeout and deployment bootstrap
remain outside this implementation.
**SynchronizationManager -> Ingestor/StorageManager:** `release_session()` and
`reconcile_timing()` inspect accepted mapping evidence, journal durability, and
framework archival through direct owners. Missing NATS evidence readback and
acceptance/preservation checks depend on the evidence-owner interfaces below.
Retain historical mappings, uncertainty, and the prohibition on untrustworthy
active-Session clock restoration. Local timing helpers are not new services.

### Producer Intake And Publication Confirmation

Decision 377 removes routine scientific envelope delivery and its additional
intake-correlation requirement. Existing RuntimeEvidenceMessage identity,
journal-before-ACK and restart-safe deduplication remain mandatory. Evidence
acceptance, StorageManager persistence confirmation and archival completion
remain distinct.

**AcquisitionNode/Controller/other producers -> Ingestor:** W053 removes node
scientific-envelope production/forwarding. Node `_retain_runtime_evidence()` and
`_record_artifact_manifest()` retain messages before optional development-time
local intake; the NATS node adapter publishes operational evidence/manifests
before applicable command results. Controller decision and
Experiment-rejection evidence also use direct `receive_runtime_evidence()`.
Manifest recovery calls `has_durable_runtime_evidence()` on the same object.
Reuse existing evidence publication/subscription, producer retention and correlated
commands/results. Slice 3 is CLOSED in W057 after independent IPython validation
and read-only audit PASS of 880b108, with no confirmed P0-P3 findings. It extends scoped readback with
`read_runtime_evidence_acceptance`, using `request_persistence_command` and payload
`{"evidence": message.to_dict()}`. Ingestor checks exact current journal coverage
under its existing history guard and returns `durable_acceptance_confirmed` plus
the evidence identity and per-attempt nonce. Missing, stale or timed-out replies
are not confirmation. This is acceptance readback, not complete W041 receipt,
StorageManager persistence or archival confirmation. It does not append evidence.

Intake validates the delivered NATS subject against the evidence Session, source
and type before acceptance, and confirms journal-backed acceptance before Session
ACK. Optional callback cancellation leaves durable intake available for broker
redelivery; identical redelivery does not append another accepted message or rerun
the optional callback. Producers retain unconfirmed publication identities and
reuse existing publication cursors and JetStream durability, not a second intake
transport. Subject consistency is not cryptographic sender authentication; broker
access control remains a deployment responsibility.

Developer verification includes a local JetStream receiver in a separate process,
offline publication, lost publication confirmation, restart and exact acceptance
readback; focused doubles cover journal failure, misrouting, callback cancellation,
duplicate/conflicting content and stale/missing replies. W057 records developer
52-test and nine-check runs, independent IPython PASS, and final audit PASS with
50 tests and three probes; these overlapping counts are not additive. Optional
callbacks are not a durable retry queue. Multi-host, hardware and power-loss
guarantees remain unverified. Neither publication nor acceptance authorizes
scientific-artifact release.
Remaining cross-owner recovery/Controller orchestration is not adapted by this
bounded change, and scientific-envelope delivery is not reintroduced.
Preserve applicable failure reporting, stable evidence identity,
same-content deduplication, retained-manifest retry, and journal-before-ACK.
Publication confirmation, Ingestor acceptance, and complete receipt remain distinct.
Depends on owner runtime-evidence validation and local scientific persistence;
do not turn Ingestor's internal framework partition into another service owner.

### Historical Session Record Interpretation

Existing historical Session Records may contain scientific envelopes and their
intake audit. StorageManager validates those fields when present, rejecting
incomplete or cross-Session information before preservation/collection confirmation.
It does not rewrite them, reconstruct envelope objects, or provide legacy intake,
transport or append APIs. New records use the retained Session/Experiment and
operational archive contracts, without obsolete scientific-envelope fields.

### Receipt, Compilation, And Kill Obligations

**Controller -> Ingestor:** `normal_stop_session()` and
`archive_acquisition_evidence()` require a local `NatsIngestorCommunication`
instance and matching Ingestor object. `_preserve_kill_closeout()` admits Kill
handoff obligations and reads current journal-backed operational evidence and
its complete intake audit. Reuse Ingestor's existing W041
`verify_acquisition_evidence_receipt()`, journal verification, persistent
compilation, and handoff compiler inside the receiving service. Missing NATS
operations expose their owner-confirmed results and admit obligations before
asynchronous shutdown, including empty intake. Preserve marker identity/sequence,
receiving origin, intact history, contiguous ACK proof, journal-before-ACK,
Session isolation, and explicit Kill incompleteness. Missing/invalid proof is not
complete receipt. Depends on producer/record intake; no Controller-owned consumer
or receipt reconstruction is needed.

### Stage A, Session Records, Handoff, And Binding Release

**Accepted contract (Decision 382; bounded implementation CLOSED in W060):** The Normal Stop
marker is last-call after required producer-publication confirmations. Ingestor
independently proves complete durable receipt through the marker, including the
full publication interval, contiguous JetStream receiving progress and journal
consistency, before establishing final acquisition intake. After finalization,
subsequent acquisition deliveries, including duplicates, are rejected/discarded
without changing finalized Stage A evidence, audit or final Session Record.
StorageManager verifies durable corresponding complete Stage A products and the
applicable handoff. Together these establish acquisition-preservation eligibility,
not automatic Session completion or release.

Controller retains lifecycle authority and requires all existing lifecycle,
cleanup and safety obligations plus a correctly correlated owner preservation
result. Publication/ACK alone is insufficient. Existing NATS/JetStream and durable
Session products/journals/readback/recovery must preserve independently verifiable
eligibility across restart; missing, delayed, duplicated, cancelled or superseded
confirmations cannot authorize an inappropriate transition. Do not rewrite
finalized evidence or unnecessarily repeat confirmed Stage A. Each service
independently releases under Decision 313; Stage A does not confirm remote cleanup
or hardware safety. Kill partial-preservation/recovery and later Stage B/explicit
permanent closure remain separate. No new reliability subsystem, transaction
coordinator, registry or Session state is authorized.

**Validated implementation - remote closeout (W060):** A Controller with no local
Ingestor/StorageManager references uses its launched NATS communication plus an
explicit `storage_participant` for `normal_stop_session()` or authorized
`kill_session()`. The receiving Ingestor adapter offers `admit_session_kill`,
`preserve_session_acquisition`, `read_session_closeout`,
`preserve_session_terminal_record` and `release_session`. These use fresh-only
commands, complete scoped durable result history, per-attempt nonce/request
correlation and current owner readback; missing responses never confirm success.

Ingestor stores Kill admission or exact normal finality in its existing recovery
journal. Normal finality follows W041 receipt verification and freezes evidence
identities, marker receipt and the complete audit. Restart retains that audit
instead of generating replacement recovery entries. Later deliveries are discarded
without changing the frozen interval. Ingestor calls its paired StorageManager's
existing writers and guards locally, and reconciles archive evidence, audit,
Session Record, handoff and marker provenance. Partial Kill never claims complete
receipt. Changed intake cannot silently replace historical preservation.

Session finality does not close framework intake: Session-independent messages
still route to the configured framework journal. Early Controller closeout
association protects cancellation without rejecting in-flight health decisions.
Controller verifies their publication before creating the last-call marker; new
health decisions are rejected once that marker exists.

Controller completes only after confirmed normal preservation and its own cleanup
requirements, then preserves terminal lifecycle. Release separately rechecks the
terminal record, obtains SynchronizationManager's guarded timing-evidence release,
applicable node reservation release, and Ingestor release. Uncertainty retains the
Controller binding and obligations. `reconcile_session_closeout()` reads a known
saved scope after restart without restoring application state or a live clock.
Saved readback requires the existing configured journal root and durable products;
interrupted products still require existing authorized recovery. Local development
interfaces remain available and do not require a NATS round trip inside the shared
Ingestor/StorageManager process. Stage B, permanent closure and general service
maintenance remain separate. W060 closes this bounded implementation after
independent user-run validation and independent audits. Its separate validation
sets are 9/9 finalized intake, 7/7 simulated distributed closeout, 4/4 real
JetStream infrastructure, 3/3 separate-process closeout, 8/8 original-correction
and 6/6 subscription-release regressions; overlapping counts are not additive.
Earlier sandbox-blocked execution is not a claimed pass. Final controlled
nats-py 2.16.0 cancellation probes found no reproducible defect, but Windows
asyncio socket-pair startup prevented live task-level cancellation verification.
No multi-host, physical hardware/SFTP or power-loss validation is claimed.

Remote preservation readback includes the exact validated archive runtime
evidence. Controller checks its currently retained evidence against that readback
before release, across asynchronous participant/subscription steps, and against
fresh owner readback immediately before retirement. Missing coverage or cancelled
confirmation retains the binding and evidence. Newly retained post-finality
rejection evidence is not silently discarded, reclassified as framework evidence,
or appended to immutable Stage A by this correction; it blocks release unless
applicable preservation obligations can be authoritatively established.
Successful unsubscribe progress is removed immediately from pending release work;
failed or unconfirmed operations remain pending. Failed final readback retains
the Controller binding without restoring completed unsubscribe obligations, so
explicit retry obtains fresh preservation confirmation without duplicate removal.

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

**Controller -> StorageManager:** Existing local single/multi-Session collection calls
`get_saved_session_collection_status()` and `collect_saved_artifacts()`; listing,
handoff readback, and `close_session_evidence_archive()` are local StorageManager
APIs; W058 adds bounded remote single-Session collection as described below.
Remote enumeration/batch remain unimplemented; explicit closure is exposed by
the Slice 5 implementation below. StorageManager independently enumerates/validates saved
products, rechecks eligibility/availability under collection guards, and retains
stable per-Session evidence IDs and durable outcomes before direct Stage B archival.
Do not send Stage B evidence through Ingestor merely to archive it. Preserve
failure isolation, per-Session results, aggregate reporting, authorized interrupted
write recovery without refetch, and separate explicit permanent closure with
restart-safe immutability. Existing SSH/SFTP file retrieval remains a
StorageManager persistence mechanism under Decision 373, not a Python call to an
AcquisitionNode service owner. Depends on preserved baselines/handoffs, but not
restoration of old Session runtime bindings.

**Current bounded Slice 4 implementation (CLOSED, W058; independent validation
and final audit PASS of d788d2e):** Controller can explicitly request one saved Session's
collection with `await collect_saved_session_artifacts_remote(session_id,
evidence_id=..., communication=..., storage_participant=..., result_window_s=...)`
without local Ingestor or StorageManager references. The existing
`request_persistence_command` supports StorageManager operations
`get_saved_session_collection_status` (nonce only) and `collect_saved_artifacts`
(stable `evidence_id` plus nonce). Collection command identity is the compact JSON
encoding of `[session_id, evidence_id]`, checked by the owner; the Controller
builds it automatically. The receiving service does not cache a successful
collection flag: StorageManager revalidates eligibility, preservation, closure
and handoff under existing collection guards, and exact durable collection
evidence supports retries after lost replies and restart without refetching.

The rejected-command replay correction admits only fresh StorageManager commands
at subscription startup, rather than replaying retained command history. Commands
published while this owner is offline remain unconfirmed and require an explicit
retry. Other participant adapters retain their existing delivery policy.
For collection, the existing `request_nonce` distinguishes each explicit attempt
from delivery of an older attempt with the same Session/evidence command identity.
The adapter serializes collection attempt resolution through result publication,
reuses exact matching results from durable `LAB_COMMAND_RESULTS`, and retains an
unpublished result in memory until publication succeeds. Thus a rejected attempt
does not become executable when eligibility changes. An explicit API retry has
a fresh nonce, revalidates current owner guards, and can reuse the already durable
collection outcome. No operator API, new persistence store or recovery workflow
is introduced.

Result-history readback requires intact file-backed retained history and rejects
unavailable, malformed or detectably incomplete history before collection; the
scan rechecks stream continuity before admitting work. This conservative check
and linear result-history scan are operational limitations, not new power-loss or
broker-history restoration guarantees. Existing storage locks are never held
across NATS readback. All three replay/correlation P2 findings are resolved and
independently verified; W058 preserves the failed audits and corrective history.

Persisted collection-result correlation is validated before an attempt can be
treated as unrelated or absent: required result fields/types, nonempty identities
and nonce, final status/success consistency, subject/body Session/source/operation,
and canonical Session/evidence command identity. Payload Session/status and any
collection evidence must agree with those identities; success requires confirmed
collection preservation. Every record in the scoped scan is checked, even after
finding a matching attempt, and conflicting resolutions fail closed. Within the
Session/owner/operation scope, the nonce identifies the attempt: differing command
or destination identities for that nonce block admission rather than making the
attempt appear absent. Valid
unrelated attempts remain isolated; other Sessions remain outside the scoped
readback. Invalid history blocks collection without rewriting the offending
records or producing new collection evidence. A normal failed command reply may
still be appended to the existing NATS result stream; it is not history repair.

Results retain eligibility/availability information and actual collection outcomes,
including scientific retrieval failures whose evidence was durably preserved.
Controller reports success only for the matching Session/evidence identity with
confirmed collection-evidence archival and successful scientific collection.
Missing or stale replies remain unconfirmed. Publication, intake acceptance,
W041 receipt, Stage A preservation and release authorization are not substituted
for this collection result. No automatic collection or permanent closure occurs.
Stage B evidence remains directly archived by StorageManager, not sent via NATS
to Ingestor. Existing local APIs remain usable for in-process workflows.

Developer coverage includes real local JetStream with Controller and the combined
Ingestor/StorageManager test process separated, simulated SFTP, overlapping
requests and owner restart. This is not live SSH, hardware, multi-host or power-loss
validation. This subset does not adapt active Session Stop/Kill, Stage A/handoff
creation, completion/release, remote saved-Session enumeration/batch selection,
permanent closure or maintenance/recovery orchestration.

### Explicit Remote Saved-Session Archive Closure (Closed, W059)

The bounded implementation exposes the existing permanent Evidence Archive
closure operation, not general Session lifecycle closeout. Call
`await controller.close_saved_session_archive_remote(session_id,
communication=..., storage_participant=..., result_window_s=...)` only as a
separate explicit operator request. No local Controller Ingestor/StorageManager
reference is needed. This bounded Slice 5 is CLOSED in W059 after independent
IPython validation and final focused audit PASS of 31b2c7e, with no confirmed
P0-P3 findings after the cached-success history-validation P2 correction.

`close_session_evidence_archive` uses existing NATS command/results, canonical
compact JSON `[session_id, "close_session_evidence_archive"]` command identity
and fresh per-attempt nonce. This operation creates no new evidence ID or closure
file: StorageManager records closure only in `compilation_summary.json`, through
its existing locked, durable write/readback method. Its existing Stage A/B,
handoff, audit, final-record and unresolved-write checks remain authoritative.
Failed or unknown artifact outcomes do not block closure when durably recorded;
collection success is neither required nor a substitute for archive consistency.
Collection eligibility is not a new lifecycle gate for permanent closure.

The shared saved-Session command admission path retains fresh-only subscriptions,
full operation-scoped history validation, same-nonce identity conflict rejection
and serialization through result publication. Historical rejections cannot become
new executions; explicit API retries use fresh nonces. Successful closure responses
retained after failed/cancelled publication pass the same complete history scan
before reuse; disagreement with a persisted resolution is unconfirmed, not ignored.
Retained rejections remain rejected. Repeated successful closure
requires current owner readback matching the retained/historical closed summary,
then invokes the existing idempotent closure confirmation without rewriting closed
products. Missing or corrupt current preservation invalidates success, including
after cancelled/failed reply publication. Pending replies remain in memory, not a
new durable command store. Missing replies leave the Controller outcome unconfirmed.

Success includes `closure_outcome` from StorageManager and its verified current
`compilation_summary`; Controller checks Session identity, `archive_closed=True`
and `archival_confirmed=True`. It does not complete an active Session, collect
artifacts, release bindings/hardware, or authorize recovery. Local closure
preconditions are unchanged. Full Normal Stop/Kill, Stage A/handoff orchestration,
enumeration/batch closeout, broader maintenance/recovery and role bootstrap remain
outside this boundary. Retained history must be intact and scanning is linear;
simulated SFTP/local JetStream testing does not establish hardware, multi-host or
power-loss guarantees. W059 records the original 67 developer tests and 4/4
independent IPython checks, initial audit FAIL, correction IPython 3/3 PASS and
final audit PASS. Corrective runtime attempts, including six audit tests, stalled
inside the sandbox without results; no automated correction passes are claimed.
Counts are not additive. Q022 remains OPEN; W001-W058 history is unchanged.

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

Completed prerequisites are identified by their validated workflows below.
Remaining items are proposed implementation boundaries, not additional accepted
architecture or claims of implementation/validation:

1. The bounded routine observation/metadata routing and node lifecycle/health
   preservation prerequisite is complete with correction, independent validation
   and final re-audit PASS (W053). Owner-level envelope removal and closeout
   reconciliation are complete after correction, independent validation and
   corrective re-audit PASS (W054), retaining required historical interpretation.
   The combined Decision 377-378 replacement is now accepted in W055 after
   functional audit PASS and targeted correction of its sole clean-replacement
   P3; no further independent re-audit was required by the user and ICC for that
   test-only cleanup. AcquisitionNode-to-Ingestor durable operational evidence
   intake and exact journal-backed acceptance readback are complete in W057 after
   independent validation and audit PASS. Existing receipt/compilation interfaces
   are preserved; broader Controller/recovery/deployment adaptation remains open.
2. Acquisition/Experiment and distributed synchronization runtime integration is
   complete in W056 after corrections, independent manual validation and final
   audit PASS. It reuses existing node commands with local scientific timing,
   context/finalization and publication-before-completion. This does not close
   broader deployment obligations; operational-evidence transport is separately
   closed in W057.
3. Bounded remote single saved-Session collection is CLOSED in W058 after
   independent validation and final audit PASS. Explicit remote permanent closure
   of one saved Evidence Archive is CLOSED in W059 after correction, independent
   validation and focused audit PASS. Q019 Controller Normal Stop/Kill,
   Stage A/handoff and completion/release are CLOSED in W060 after independent
   validation and audits confirmed the original three P2 corrections and the
   subsequent subscription-retry correction (see the Stage A section above).
   Saved-Session enumeration/batch collection and batch closeout remain outside
   that implementation. W060 does not close broader deployment obligations.
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
