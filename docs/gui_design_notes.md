# Future GUI Design Notes

This document preserves ideas for future GUI discussions. It is not an
implementation roadmap or architecture decision record. Explicitly identified
accepted requirements are referenced below; other presentation ideas remain
proposals. GUI implementation belongs outside this repository.

## Accepted Functional Direction

**Status:** User-accepted architecture in Decisions 396-405 and 409-413; documentation only,
not implemented or software-validated GUI/Analysis functionality.

- The GUI is a general-purpose framework client. The complete scientific workflow
  must be operable from the microscope workstation; browser accessibility is
  preferred, while the backend and central services may run elsewhere.
- Services, Setup, and Experiment / Run are conceptual functional areas, not
  approved tabs, tab count, widgets, frontend technology, or a layout. Services
  concerns connectivity/readiness/status/maintenance; Setup concerns identities,
  templates, configuration and products; Run concerns guided scientific steps,
  plots, selections, calibration, progress and results.
  Decision 414 subsequently requires the permanently accessible Services tab
  specifically; the remaining tab count and layout are still unresolved.
- One Session corresponds to one animal and may contain Experiments, Analyses,
  Validation and interactions. Successive animals must not require restarting
  GUI/services; existing closeout and resource-reuse obligations still apply.
- The application owns protocols and editable reusable templates. Steps may be
  scientific operations, Validation, preparation, annotations or review, not
  necessarily Experiments. Actual executed configuration is preserved independently
  of its starting template. Decisions 409-411 settle catalog and template rules;
  detailed persistence, identities, transfer and configuration contracts remain
  unresolved in Q008.
- Analysis is lightweight, Session-scoped, and identified by `analysis_id`, not
  a fabricated Experiment. Execution success is distinct from scientific result
  acceptance/selection. Preserve all attempts/results and the actual inputs used
  later; new selections cannot rewrite completed operations. Application-specific
  dependency interpretation does not become a framework workflow engine.
- Scientific products from Experiments and Analyses share existing local storage
  and collection ownership. Analysis-compatible schemas/invocation are not yet
  designed or implemented. Scientific calculations execute locally where data and
  resources reside, with an existing AcquisitionNode as the intended coordinator,
  not GUI/Controller calculation or a DeviceManager analysis scheduler.
- Commands follow GUI application -> Controller -> AcquisitionNode; requested small
  plots/structured results may flow AcquisitionNode -> GUI application/backend
  without Controller payload relay. Ingestor is not a visualization relay. Detailed
  transport, recipient authorization, correlation and reconnect mechanisms remain
  open; shared paths/overwritten PNGs are not the general result transport.
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
scientific/UX reference, not architectural authority. Decimated cursor display
remains a future possibility, not authorization for general scientific streaming.

### Accepted Catalog, Configuration And Recovery Requirements

Decisions 409-413 supplement the functional direction without implementing it:

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
  differ. Whole-Session template reconstruction is not required. The exact
  Session/Experiment settings split remains open.
- Browser closure, freezing or disconnection does not automatically interrupt
  Sessions, Experiments, Analyses or services. Reopening retrieves authoritative
  current state; lost connectivity implies neither success nor failure and cannot
  trigger automatic repetition. Backend restart permits reconnection without
  restarting Controller/services. GUI is not the sole holder of authoritative
  history or provenance. This is not a general service-restart/recovery policy.
- One controlling GUI is permitted per deployment. A new connection offers Cancel
  or Take Over. Successful takeover invalidates old command authority without
  requiring an old-GUI response; a recovered superseded GUI must obtain authority
  again. Operations/services continue uninterrupted. Independent deployments have
  independent controlling GUIs. Simultaneous control, a monitoring GUI and killing
  the previous browser are not required.

No project-sharing infrastructure, permissions system, configuration schema or
control-authority mechanism is selected. Existing lifecycle, provenance,
deployment-local configuration, SessionConfig, device configuration and node-owned
storage-root authority remain unchanged.

### Unapproved Approaches And Unresolved Contracts

Candidate approaches include a minimal local Analysis invocation interface,
lightweight Controller-authorized request/outcome records, specific NATS result
delivery, tagged operation-origin product identities, concrete input/output and
selection provenance structures, application dependency/invalidation rules,
frontend/backend packaging and widgets, installed-software integration, and
detailed result authorization/correlation/reconnect mechanisms, and control
identity, fencing, lease, heartbeat or stale-instance mechanisms. None is selected
by this synchronization.

See Q026-Q030 and Q008 in [open questions](open_questions.md) for execution and
interruption, persistence/timing/collection, acceptance/provenance, communication
and trust, presentation/deployment, and catalog/template persistence, identities,
transfer and Session/Experiment settings boundaries. No general
protocol editor, template installation framework, historical Analysis platform,
generic workflow engine or broad online processing is required. Decisions 019/021
continue to exclude GUI implementation and scientific analysis pipelines from
this core repository. G4/G5 integration and hardware validation are separate.

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

**Status:** Accepted functional requirements in Decisions 414-418 and 423, not implemented
or validated GUI functionality. Detailed widgets, layouts and technical contracts
remain unresolved under Q030-Q033.

A permanently accessible **Services tab** shows all configured framework services
for inspection, startup guidance and existing administrative operations. This
supplements Decision 398's conceptual functional areas without fixing the rest
of the GUI layout.

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
follows Decision 365. Independent Experiment Kill is not accepted; Q033 returns
that question to HLC without inventing a command or cleanup policy.

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

Decisions 414-418 accept the GUI requirements identified here; concrete widgets
and control layout remain proposals. Those decisions do not change existing
service states, lifecycle behavior, startup or recovery policy. No GUI implementation
or validation is claimed; Q019 is closed in W050 while Q024 and other open
questions retain their existing status.

### Accepted Operational Warnings And Session History

Problems affecting active Sessions/Experiments generate prominent Experiment/Run
warnings. A persistent indicator remains visible throughout the GUI, including
Setup and Services. Distinguish confirmed failures, unknown availability, historical
reports and framework-confirmed resolution. A service problem alone is not an
Experiment failure; GUI cannot independently terminate scientific operations.

Experiment/Run provides reviewable Session-associated warning/error history,
including resolved conditions. Experimenters may minimize or dismiss prominent
notifications without erasing historical evidence, hiding every indication of
unresolved critical conditions, implying technical resolution, authorizing recovery
or discharging obligations. Indicators follow authoritative framework information.

Reuse existing health, readiness, operational evidence, ControllerActionDecision
and lifecycle contracts. Notification delivery, correlation, reconciliation,
dismissal representation and complete historical retrieval remain open in Q032.
Existing persistent evidence is not assumed to provide that query interface.
No GUI scientific log, duplicate archive or general event-history subsystem is
authorized. Exact warning widgets and layouts remain presentation proposals.

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
