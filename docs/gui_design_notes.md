# Future GUI Design Notes

This document preserves ideas for future GUI discussions. It is not an
implementation roadmap, architecture decision record, or source of approved
implementation requirements. GUI implementation belongs outside this repository.

---

## Services Tab

**Status:** Future GUI design ideas, not accepted architecture or implementation requirements.

The proposed presentation is a permanently accessible **Services tab**, available
for service inspection, startup guidance, and operational shutdown requests.

### Readiness and startup guidance

The future tab could:

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

### Shutdown, authorization, and outstanding obligations

The future tab could also:

- Provide access to existing orderly shutdown and administrator-authorized kill
  operations, with clear separation between readiness checks, ordinary cleanup,
  preparation, and confirmed operational retirement.
- Display the services included in the requested shutdown, initial local survey
  results, and each service's actual progress and confirmed outcomes as Controller
  coordinates closeout. Use existing `blocked`, `failed`, and `completed` attempt
  outcomes, explain blockers, and never present missing confirmation as success.
- Provide a separate **Kill** button for each blocked service, requiring a new,
  explicit administrator authorization for that service. Authorization for one
  service would not authorize termination of another.
- Allow administrators to decline forced termination while preserving actual
  outcomes; explain that already stopped services will not automatically restart.
- Warn about dependencies, affected scope, unresolved obligations, and forced
  termination consequences, including possible loss of unpreserved scientific
  data or runtime evidence. Successful forced retirement does not confirm that
  unresolved cleanup or preservation obligations succeeded.
- Display unresolved obligations from previous operation attempts. Potential
  recovery/abandonment controls remain future presentation ideas within the
  accepted service-owned boundaries described below, not GUI-owned execution policy.

### Operator-facing recovery guidance

**Status:** Future GUI design ideas, not accepted GUI architecture or implementation requirements.

Within the proposed Services tab, the future GUI could:

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
  resource safety, or recovery.
- Show the administrator choice, actual attempted actions, confirmed outcomes,
  remaining obligations, and evidence-preservation warnings separately. Publication
  or command acknowledgment is not recovery success or confirmed archival.
- Explain that partial artifact preservation and device/resource cleanup are
  independent actions: success in one does not establish success or safe reuse in
  the other. Keep existing service-specific kill authorization and forced-action
  warnings separate from recovery authorization.

Q024-B Decisions 339-346 accept framework service-specific recovery boundaries,
not these GUI controls. The GUI remains a client: services own technical assessment,
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
is independently validated and audited after correction in W039. GUI controls
remain future proposals.

These are existing framework contracts, not new GUI requirements. The Services
tab, its controls, and all presentation ideas above remain future design ideas,
not accepted architecture or approved implementation requirements. This document
adds no service states, lifecycle behavior, startup mechanism, or recovery policy
and does not resolve Q019, Q024, or other open architectural questions.

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
  The GUI must not become a browser for viewing scientific artifacts. Artifact
  metadata is not artifact bytes; NWB conversion and Cheaha upload remain separate
  later processing stages, not newly specified GUI execution mechanisms.

Decisions 356-365 accept the framework boundaries, not these presentation ideas.
W041-W049 backend slices are complete; overall Q019 integration validation remains
open, and all GUI features here remain future ideas. Decision 364 accepts StorageManager enumeration
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
