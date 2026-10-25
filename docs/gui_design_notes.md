# Future GUI Design Notes

This document preserves ideas for future GUI discussions. It is not an
implementation roadmap or architecture decision record. Explicitly identified
accepted requirements are referenced below; other presentation ideas remain
proposals. Under Decision 426, GUI implementation belongs in the separately
packaged top-level `gui/` project in this repository, outside the existing
`lab-sync-acquisition` package and distribution.

## Accepted Functional Direction

**Status:** User-accepted architecture in Decisions 396-405, 409-418 and 424-428.
GUI/Analysis/Validation/visualization implementation is pending; Decision 424's
bounded framework metadata implementation and independent audit are complete/PASS,
with deployment validation and Q008 closure still pending.

- The GUI is a general-purpose framework client. The complete scientific workflow
  must be operable from the microscope workstation through a laboratory-network
  web GUI without cloud dependence. A separate Python backend process runs by
  default, not obligatorily, on the Controller computer; it uses external NATS,
  never Controller-internal shortcuts. Web frameworks/libraries remain unselected.
- Decision 425 supplements the older conceptual areas with six permanent tabs:
  **Setup, Session, Parameters, Experiment, Analysis, Services**. Navigation never
  interrupts operations. These are presentation boundaries, not lifecycle owners.
- One Session corresponds to one animal and may contain Experiments, Analyses,
  Validation and interactions. Successive animals must not require restarting
  GUI/services; existing closeout and resource-reuse obligations still apply.
- The application owns protocols and editable reusable templates. Steps may be
  scientific operations, Validation, preparation, annotations or review, not
  necessarily Experiments. Actual executed configuration is preserved independently
  of its starting template. Decisions 409-411 settle catalog and template rules;
  Decision 424 settles final accepted Session values and launch-time durability;
  Decision 427 settles protocol authoring, name-only association and reusable
  template defaults without a protocol snapshot/version requirement. Remaining
  detailed catalog/template representation stays in Q008.
- Analysis is lightweight, Session-scoped, and identified by `analysis_id`, not
  a fabricated Experiment. Execution success is distinct from scientific result
  acceptance/selection. Preserve completed valid results, including unselected
  results, and actual inputs/parameters. Discard incomplete failed/cancelled
  computational outputs without altering original inputs or earlier valid results;
  retain applicable operational evidence. New selections cannot rewrite completed
  operations. Application-specific
  dependency interpretation does not become a framework workflow engine.
- Scientific products from Experiments and Analyses share existing local storage
  and collection ownership. Results require no timestamps, fabricated Experiment
  identity or Experiment timing fields; acquired-data timing remains unchanged.
  Technical schema/invocation implementation is pending. Scientific calculations
  execute locally where data and
  resources reside, with an existing AcquisitionNode as the intended coordinator,
  not GUI/Controller calculation or a DeviceManager analysis scheduler.
- Commands follow GUI application -> Controller -> AcquisitionNode through NATS;
  selected visualization flows AcquisitionNode -> NATS -> GUI backend -> browser,
  without Controller payload relay or backend scientific calculation. Ingestor is
  not a visualization relay. Detailed schemas, recipient authorization, correlation,
  buffering and reconnect implementation remain pending; shared paths/overwritten
  PNGs are not the general result transport.
- Time-critical acquisition/closed-loop execution is independent of browser,
  Controller and network round trips. Framework services remain GUI-independent.

Decision 405 preserves the initial CaBMI use case: approximately two minutes of
imaging, local rapid Suite2p ROI identification, approximately 15 minutes of
baseline with those masks, inspection/selection of four neurons, neural-cursor
simulation and target T calculation, iterative calibration review, then local
closed-loop CaBMI. Imaging/baseline/closed-loop runs are candidate Experiments;
ROI identification, baseline calculations, neuron selection and target calibration
are Analyses. Operational tests remain Validation. This is not a mandatory protocol
or a specified Suite2p/CaBMI integration interface. Legacy GUI/MATLAB code is a
scientific/UX reference, not architectural authority. Decision 425 accepts selected
bounded scientific feedback, not general scientific streaming or large artifacts.

### Accepted Protocols, Templates And Recorded Inputs

Decision 427 records the accepted reconciliation, not implemented functionality.
Experimenters create, edit, reorder, copy and save protocols from the existing
Setup tab using scientific-application-supplied operations. Ordinary Session
preparation selects a protocol and adjusts permitted optional steps/capabilities.
Scientific coherence belongs to the experimenter; no generic protocol execution
engine or automatic scientific dependency validator is required.

Session configuration retains the selected protocol name, not a complete ordered
protocol definition copied into every Session. The owner explicitly supersedes
the earlier fixed-protocol-snapshot requirement; `protocol_plan` does not require
such a snapshot. Expected project-level protocol stability is not framework-enforced.
No snapshot/version-management system is required. Accepted Session values remain
immutable, externally readable and durably preserved under Decisions 291/424.
Session/Experiment configuration and execution evidence preserve actual configured
and performed work; later protocol edits cannot rewrite historical records.

Session templates supply reusable starting defaults, potentially protocol
selection, optional functionality, Session settings and preferred devices, not
execution authority. Final accepted Session configuration governs. Templates need
no immutable full protocol copies, new service or version mechanism; retain existing
template editing rules and no template-provenance requirement.

Match exact protocol capability identifiers to installation-time
`DeviceDeclaration.declared_capabilities`, never infer them from device type.
One device may supply several capabilities; multiple devices may collectively
satisfy requirements, respecting explicit distinct-device requirements. Sequential
steps may reuse devices; hardware-free steps need no capabilities. No GUI capability
catalog, automatic device allocation or resource scheduler is introduced.

Decision 428 requires each Experiment to acquire scientific data using at least
one participating data-acquisition device. Hardware-free protocol steps remain
permitted as non-Experiment operations: Analysis processes existing scientific
data, Validation is a distinct scientific validation operation, and operator
interaction is an experimenter action or decision. Their existing contracts
remain unchanged. Zero recorded outputs as an execution outcome are not zero
configured participants. No new deadline owner or Controller mechanism is added.

When supported by the scientific application, operators may select recorded inputs
from this Session, another Session or another project. Processing those inputs
alone is Analysis, not an Experiment; this qualifies Decision 427's earlier
recorded-input wording. The experimenter, not GUI, judges scientific suitability.
Preserve existing access, identity, provenance, readiness and historical integrity;
no universal scientific-input validator or historical Session reopening is implied.
The general recorded-input execution interface is missing, not defined here.

### Accepted Tab Interactions And Device Scope

Setup prepares experimenter/project/animal context, Session name/identity,
templates, editable Session values, storage information under existing owner
authority, device choices, readiness and launch. Installed nodes/devices remain
visible when offline/unreachable with explanations; installation membership is
not live readiness, and communication loss is not hardware failure. Reuse node
declarations/inventory, not a GUI registry. Controller confirms applicable
availability/readiness before Session selection/launch. Accepted Setup becomes
read-only after launch; after closeout it supports the next Session without restart.

Session shows the application protocol checklist on the left and selected-step
controls on the right, including optional/repeated/revisited steps. The selected
step determines Experiment type; edit duration/Experiment values before launch,
select participating Session devices with template-prefilled checkboxes, and use
Configure Parameters to navigate to Parameters. Non-Experiment steps have their
own controls/navigation. Keep Session status/readiness/notifications and applicable
Session Stop/Kill accessible; do not create a core workflow engine or mandatory
historical scientific browser.

Controller reserves whole AcquisitionNodes, not devices independently across
Sessions. Session inclusion selects individual devices; each Experiment selects
participants independently of recorded products, including outputless devices.
The experimenter selects actual devices before launch; final accepted identities
remain fixed throughout that Session. Manual or automatic replacement requires a
new Session. Required-device readiness
must be checked before each Experiment; an unavailable device blocks Experiments
requiring it, not unrelated Experiments, and does not necessarily end the Session.
Existing health/safety consequences remain authoritative. Decision 427 Slice 1
now scopes Experiment preparation/readiness/activation to explicit participants
and retains that scope through expiry/finalization; independent validation and
audit remain pending. See the implementation interfaces in `code_map.md`.
Apply Experiment overrides only to participants as appropriate; deselected devices
remain in the Session's node reservation. Parameters groups actual supported
settings by selected device, adds/hides controls as participation changes and
shares working values with any legitimate duplicate view. Executed settings are
read-only during the active Experiment.

Successful Experiment start navigates to Experiment: show identity/status,
elapsed/configured duration, progress, relevant feedback/notifications and Stop.
Completion leaves final status/results visible until the next Experiment; Session
permits subsequent preparation. Duration/capacity gates and autonomous expiry stay
under Decisions 394-395; runtime duration extension remains deferred.

Analysis presents the selected Analysis step's application-specific interaction,
controls and results according to actual state; with none selected, direct the
operator to select a step in Session. CaBMI examples do not mandate universal
Analysis types or widgets. Only one Analysis is active per Session; required
cleanup precedes another admission.

### Accepted Validation, Visualization And Closeout

Validation is selected-device acquisition into memory inside a Session, not an
Experiment or persistent test recording. Successful data acquisition without
reported errors suffices for the recording-function check. Allow manual Stop,
automatic Stop at a Setup-configurable maximum duration and applicable preview;
clean temporary activity without changing installation/reservations. Incompatible
device activation is prohibited; compatible use requires existing ownership and
isolation guarantees. Applicable operational evidence remains required.

Only experimenter-selected visualization streams transmit, initially one image
and up to two scientific streams; multiple traces in a plot may count as one.
Initial targets are approximately 1-2 fps previews and 5-10 scientific updates/s
where appropriate, not permanent limits or guarantees. Camera inspection belongs
to applicable Validation/operation presentation, not required Setup preview.
Optional bounded visualization must degrade/drop safely for slow/disconnected
viewers without delaying acquisition, storage, synchronization or local closed-loop
computation. No extra transport is authorized; full-resolution video is deferred.

Normal Session Stop coordinates active Experiment Stop with acquired-data
preservation, Analysis cancellation with incomplete-result disposal and confirmed
cleanup, and Validation Stop/cleanup before existing closeout. No relevant active
work means existing closeout. No separate lifecycle/cleanup authority is added;
emergency Kill, Stage A, intake finality, preservation, binding release and safe
retry remain unchanged. Early Experiment Stop permits another Experiment in the
Session; independent Experiment Kill is not required initially.

### Accepted Catalog, Configuration And Recovery Requirements

Decisions 409-413 and 424-425 govern these requirements; the GUI remains pending:

- The application owns an editable experimenter/project/animal/template catalog.
  Projects have one primary experimenter; another actual Session experimenter is
  recorded separately. Animals are project-local; cross-project copies are
  independent, without biological identity tracking across projects. Selected
  metadata enters authoritative Session history at creation and cannot be changed
  by later catalog edits. GUI catalog ownership is not scientific-history ownership
  and does not make Controller the scientific metadata owner.
- Lab templates are shared immutable references that experimenters may copy, not
  overwrite. Personal templates are owned, creatable, copyable, editable and
  overwritable by their experimenter. Copying someone else's configuration makes
  an independent copy by default. Before or after an Experiment, working edits
  may become a new personal template, overwrite an owned template or stay unsaved.
- Templates may concern Sessions or selected Experiment types; not every Experiment
  needs one. Reusable templates, working configuration, accepted execution values
  and immutable historical configuration are distinct. Completed Experiment and
  Session history cannot change with later edits; Experiments in one Session may
  differ. Templates prefill editable fields; experimenters may change values before
  submission. Only final accepted values matter: no template identity, provenance
  or comparison with defaults must be preserved. Whole-Session template
  reconstruction is not required. Detailed settings representation remains open;
  accepted Session-level configuration and later Experiment-specific configuration
  remain separate under Decision 424.
- Controller accepts Session-level metadata and configuration at launch. Accepted
  values remain fixed throughout that Session; GUI working edits and later catalog
  changes cannot modify them or historical Session records. Experiment-specific
  configuration may be prepared during an active Session under existing constraints
  and validation contracts without changing accepted Session-level values.
- Under Decision 424, successful Session launch requires authoritative confirmation
  that all accepted Session metadata and configuration are durably preserved through
  existing Ingestor/StorageManager mechanisms, independently of Controller memory.
  A Controller crash after successful launch must not erase them. Missing, failed
  or uncertain preservation is not launch success. An initial Session Record does
  not prove scientific finalization, Stage A or terminal preservation, collection,
  completion or release. Existing failed-launch cleanup and authorized write-recovery
  rules remain unchanged; no record repair/deletion or automatic recovery policy
  is added. Bounded implementation and independent Codex audit PASS at `5da9b35`
  are recorded in Q008; deployment validation and final closure remain pending.
  Reuse configuration readback and initial-record preservation; do not restart them.
- Browser closure, freezing or disconnection does not automatically interrupt
  Sessions, Experiments, Analyses or services. Reopening retrieves authoritative
  current state; lost connectivity implies neither success nor failure and cannot
  trigger automatic repetition. Backend restart permits reconnection without
  restarting Controller/services. GUI is not the sole holder of authoritative
  history or provenance. This is not a general service-restart/recovery policy.
- One GUI connection controls at a time; others may observe. A new connection
  offers Take Over or View Only. Takeover makes the previous controller read-only
  without its response; reconnect cannot restore superseded authority. Distinct
  browser identities pass through the shared Python backend's existing authorized
  NATS identity; backend prevents impersonation and Controller owns grants,
  observer permissions and enforcement. No per-browser NATS clients/credentials
  or general authentication infrastructure are required. Exact identity mechanism
  and takeover ordering remain implementation details under existing broker,
  request-correlation, Session-binding and deduplication guarantees.
- Reconnect retrieves Controller-authoritative configuration, lifecycle/operation
  state, control ownership, relevant device/service status and unacknowledged
  notifications, including work that continued while disconnected, without replay.

No project-sharing or general authentication infrastructure is introduced. Concrete
configuration schemas/control-grant implementation remain bounded technical work.
Existing lifecycle, provenance, deployment-local configuration, SessionConfig,
device configuration and node-owned
storage-root authority remain unchanged.

### Unapproved Approaches And Unresolved Contracts

Remaining implementation choices include concrete node-hosted Analysis invocation,
request/outcome and provenance schemas, installed-software integration, selected
NATS visualization schemas/buffering/recipient checks, bounded authoritative state
reads, browser identity/grant details, notification acknowledgment/history reads,
web frameworks and widgets. These choices must satisfy Decision 425 rather than
reopen accepted architecture or add a general scheduler, registry or recovery system.

See Q026-Q030 and Q008 in [open questions](open_questions.md) for execution and
interruption implementation, persistence/collection, acceptance/provenance, communication
and trust, presentation/deployment, and catalog/template persistence, identities,
transfer and Session/Experiment settings boundaries. The application protocol
editor is accepted under Decision 427; no template installation framework,
historical Analysis platform, generic workflow engine or broad online processing
is required. Decisions 019/021
continue to exclude GUI implementation and scientific analysis pipelines from the
core `lab-sync-acquisition` package and distribution. Decision 426 places the
separately packaged GUI project under top-level `gui/` in this repository; it does
not admit scientific analysis pipelines into the core. G4/G5 integration and
hardware validation are separate.

---

## Insufficient Storage Warning

**Status:** Accepted future GUI requirement under Decision 394; not implemented.

Before starting an Experiment, the GUI must clearly inform the experimenter when
available storage is insufficient for that Experiment's configured requirements.
Where known, identify the affected destination, required capacity and available
capacity. Use the framework's authoritative per-Experiment readiness result; the
GUI cannot bypass failed capacity readiness or substitute its own readiness
authority. Headless Controller operation is subject to the same framework gate.
No GUI functionality is implemented or validated by this documentation.

## Services Tab

**Status:** Accepted functional requirements in Decisions 414-418, 423 and 425, not implemented
or validated GUI functionality. Detailed widgets, layouts and technical contracts
remain unresolved under Q030-Q033.

A permanently accessible **Services tab** shows all configured framework services
for inspection, startup guidance and existing administrative operations. This
implements the Services presentation within Decision 425's six-tab layout; it does
not become a service/process owner.

### Readiness and startup guidance

The tab must provide the following accepted readiness and guidance behavior:

- Display configured services, their current or last-known readiness, and the
  timestamp of the most recent confirmed status. Distinguish historical reports
  from current confirmation and unknown/unconfirmed availability using existing
  readiness terminology, not new service states.
- Identify missing dependencies and explain which operations cannot proceed and
  which remain available.
- Explain which services need to be started and suggest a startup order where
  known; do not invent an order where the accepted contracts do not specify one.
- Let users request readiness checks, distinguishing technical readiness from
  local stop-readiness survey results and actual closeout blockers.
- Clearly state that services start independently: the GUI does not launch
  services or control operating-system processes.
- Distinguish each service's connected, reconnecting/disconnected, restored and
  unknown connectivity under Decision 423. Transport restoration does not imply
  lifecycle replay, successful prior publication, readiness, cleanup or
  preservation. This is an accepted future presentation requirement, not
  implemented GUI functionality or a new service lifecycle state.

Automatically refresh status at a configurable default interval of **10 seconds**;
relevant incoming framework information updates affected presentation promptly.
Distinguish current confirmation, stale/last-known reports, unknown availability
and confirmed problems. Do not keep a disappeared service labeled currently
confirmed available when checks can no longer establish availability. Decisions
284/328 remain authoritative; announcements alone do not implement proactive
disappearance detection. Freshness, queries, timeouts and announcement contracts
remain open in Q031. No heartbeat, registry, monitoring service or guaranteed
detection latency is authorized.

### Shutdown, authorization, and outstanding obligations

Selectable trust-based administrator mode hides administrative controls from
ordinary experimenter mode, without passwords or login infrastructure. It prevents
accidental action, not unauthorized access as a security boundary. Mode selection
is neither operation authorization nor satisfaction of technical prerequisites.
Do not introduce authentication, role management or framework authorization
infrastructure. Accepted controls expose existing Stop/Kill/Cancel, framework
shutdown and supported recovery/abandonment operations:

- Provide access to existing orderly shutdown and administrator-authorized kill
  operations, with clear separation between readiness checks, ordinary cleanup,
  preparation, and confirmed operational retirement.
- Display the services included in the requested shutdown, initial local survey
  results, and each service's actual progress and confirmed outcomes as Controller
  coordinates closeout. Use existing `blocked`, `failed`, and `completed` attempt
  outcomes, explain blockers, and never present missing confirmation as success.
- Require explicit administrator authorization for each blocked service's Kill;
  authorization for one does not authorize another. A separate **Kill** button
  per service is a presentation proposal, not a mandated widget.
- Allow administrators to decline forced termination while preserving actual
  outcomes; explain that already stopped services will not automatically restart.
- Warn about dependencies, affected scope, unresolved obligations, and forced
  termination consequences, including possible loss of unpreserved scientific
  data or runtime evidence. Successful forced retirement does not confirm that
  unresolved cleanup or preservation obligations succeeded.
- Display unresolved obligations from previous operation attempts to all
  experimenters, within the accepted service-owned boundaries below.

Ordinary experimenters retain applicable normal Session/Experiment operations,
including established Stop/Kill controls. Session Kill differs from service Kill,
framework shutdown and administrative recovery. Its active-Experiment consequence
follows Decision 365. Decision 425 resolves the initial GUI requirement: no
independent Experiment Kill is required; Q033 retains only deferred future scope.

### Operator-facing recovery guidance

**Status:** Accepted requirements under Decision 416; detailed presentation remains
unresolved. Within Services, provide the following distinctions:

- Group unresolved obligations by responsible service and show which recovery
  actions are supported, unsupported, or not yet established. Distinguish work
  already proven complete from work for which a potentially safe procedure exists.
- Display known facts, uncertain conditions, affected resources/scopes, operational
  consequences, and current prerequisites from service-owned assessments; do not
  invent a technical assessment when information is unavailable.
- Let an administrator explicitly authorize a supported attempt for a particular
  obligation, leave it unresolved, or abandon it. Explain that authorization
  permits an attempt, not guaranteed success or unrelated work, and that leaving
  unresolved differs from abandonment. Abandonment does not prove cleanup,
  resource safety, recovery or deletion.
- Show the administrator choice, actual attempted actions, confirmed outcomes,
  remaining obligations, and evidence-preservation warnings separately. Publication
  or command acknowledgment is not recovery success or confirmed archival.
- Explain that partial artifact preservation and device/resource cleanup are
  independent actions: success in one does not establish success or safe reuse in
  the other. Keep existing service-specific kill authorization and forced-action
  warnings separate from recovery authorization.

Decision 416 accepts these GUI requirements within Q024-B Decisions 339-346's
existing framework recovery boundaries. The GUI remains a client: services own technical assessment,
immediate prerequisite/safety checks, and authorized execution through existing
interfaces. These ideas define no detailed control behavior, command schema,
automatic recovery, data deletion, process supervision, or new recovery authority.
Unsupported procedures and broader application recovery remain undefined/deferred;
the GUI must not present them as available operations.

### Architectural boundary

Existing accepted contracts separate GUI interaction from Controller coordination
and service-owned cleanup (Decisions 001-002, 305, and 314). Decisions 284, 295,
and 320-321 define readiness interpretation, independent startup, and dependency
behavior without automatic interrupted-work recovery. Decisions 308-311 and
315-316 preserve explicit authorization, truthful outcomes, and unrelated scopes;
Decisions 325-326 establish progressive shutdown, service-specific authorization,
and two-phase closeout. Decisions 332-338 establish narrow service-owned reporting
and administrative abandonment; Decisions 339-346 accept Q024-B's service-specific
operator-authorized execution boundaries; their supported framework implementation
is independently validated and audited after correction in W039. The newly
accepted GUI controls themselves remain unimplemented and unvalidated.

Decisions 414-418 and 425 accept the GUI requirements identified here; widget
details beyond the accepted layout remain implementation choices/proposals. They
do not change existing
service states, lifecycle behavior, startup or recovery policy. No GUI implementation
or validation is claimed; Q019 is closed in W050 while Q024 and other open
questions retain their existing status.

### Accepted Operational Warnings And Session History

Decision 425 replaces automatic resolution-based notification removal with
operator acknowledgment, qualifying Decisions 417-418. Both warnings and errors
show severity, source, description and occurrence timestamp and remain visible
until acknowledged. Controller owns notifications and acknowledgment state across
reconnection; the GUI cannot override it. The persistent bottom-left indicator
across all six tabs shows current unacknowledged notifications, distinguishes
severity and opens details; Session/Experiment views show relevant notifications.

Acknowledgment removes a notification from that indicator, not historical Services
evidence. It proves neither underlying resolution, service recovery, deletion,
authorization nor permission to resume unsafe operations. Do not automatically
remove notifications on inferred service recovery. Existing health monitoring,
readiness, safety decisions and restrictions are unaffected; a service problem
alone is not canonical Experiment failure and GUI cannot terminate operations.
Decision 418's reviewable Session-associated history in Experiment/Run remains
available independently of acknowledgment and Services history access.

Reuse Controller, service evidence, Ingestor and StorageManager. Notification
delivery/correlation, acknowledgment reconciliation and historical readback remain
implementation work in Q032; persistence alone is not a completed query interface.
No GUI warning database, duplicate archive or automatic-resolution subsystem is
authorized. Presentation minimization cannot replace Controller acknowledgment.

## Session Closeout, Collection, and Archived Evidence

**Status:** Future GUI design ideas, not accepted GUI architecture or implementation requirements.

The future GUI could:

- Present Normal Stop and separately operator-authorized **Kill Session** distinctly
  from service-level Kill and operational framework shutdown. Explain partial
  preservation, possible data/evidence loss, and unresolved resource-safety
  conditions; authorization is not proof of successful cleanup.
- Show actual participant progress, elapsed time, the last confirmed progress,
  and unresolved conditions, never treating missing confirmation as completion.
- Distinguish Stage A acquisition preservation/Session completion from later
  Stage B collection-evidence preservation and permanent archive closure. Explain
  that killed Sessions retain a partial archive open for later collection.
- Provide a future dropdown or multi-select table of saved Sessions that may need
  scientific-data collection, showing Session identity and lifecycle status,
  including `completed`, `failed`, and `aborted`. Operators could select one or
  multiple confirmed eligible and available Sessions for collection without automatic collection or restoration of
  their original bindings. Proposed collection labels are not collected, partially
  collected, fully collected, failed, or unresolved; these are future presentation
  ideas, not accepted backend states or definitions; no detailed mapping of these
  presentation labels is defined here.
  Display actual retrieval, verification, and evidence-preservation outcomes
  separately from acquisition. This feature is not current Q019 implementation
  or an accepted GUI requirement.
- Add a future **collection-availability column** to that table, distinguishing
  Session eligibility from whether collection can currently proceed and explaining
  why it is unavailable or requires recovery. Reflect Decision 364's accepted
  backend distinction: scientific-file defects alone do not block collection
  attempts, unconfirmed preservation information requires existing authorized
  recovery, and permanently closed archives cannot accept further collection.
  This is future GUI functionality, not current Q019 implementation or a new GUI
  contract; retain lifecycle/collection-status displays and multi-selection.
- In the future table, keep unavailable Sessions visible but disable their
  selection controls. Display a reason explaining why collection is blocked for
  each unavailable Session. This proposed GUI behavior reflects the accepted
  backend selection boundary; it is not implemented GUI functionality in Q019.
- Present future collection scheduling only after the relevant Q021 architecture
  is accepted. No scheduling policy or command contract is defined here.
- Explain missing/incomplete/corrupted files and guide manual recovery within
  supported service-owned contracts. Unsupported procedures remain undefined;
  evidence-persistence interruption must not be presented as authority to replay
  artifact transfer or rewrite a permanently closed archive.
- Offer archived evidence viewing by Session or date for operational inspection.
  This proposal is not a general historical scientific-artifact browser; the
  active-Session requested scientific results accepted in Decision 404 are a
  distinct scope, with delivery details still unresolved. Artifact
  metadata is not artifact bytes; NWB conversion and Cheaha upload remain separate
  later processing stages, not newly specified GUI execution mechanisms.

Decisions 356-365 accept the framework boundaries, not these presentation ideas.
W041-W049 backend slices are complete; overall Q019 software integration validation is complete in W050, and all GUI features here remain future ideas. Decision 364 accepts StorageManager enumeration
from existing persistent directories/records and Controller-coordinated operator
selection, with independent eligibility validation for each candidate, not these
GUI presentation ideas or unresolved collection-status semantics. These notes add
no GUI commands, lifecycle states, recovery authority, or implementation
requirements. Closing the GUI remains distinct from
both Session closeout and operational framework shutdown.

## GUI Closure Versus Framework Shutdown

**Closing the GUI and shutting down the operational framework are separate actions.**

This distinction is already accepted by Decisions 304 and 314: operational
services have GUI-independent lifetimes, and GUI closure is separate from
framework shutdown. The future GUI should communicate this distinction clearly
to administrators, avoiding the assumption that closing the interface
automatically terminates the operational framework. Its presentation remains
part of the proposed GUI design, not an implemented feature.
