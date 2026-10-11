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
  resume/drop controls may be considered later, but their behavior remains
  undefined until relevant recovery architecture is accepted. These notes define
  no resumption, deletion, abandonment, or automatic recovery semantics.

### Architectural boundary

Existing accepted contracts separate GUI interaction from Controller coordination
and service-owned cleanup (Decisions 001-002, 305, and 314). Decisions 284, 295,
and 320-321 define readiness interpretation, independent startup, and dependency
behavior without automatic interrupted-work recovery. Decisions 308-311 and
315-316 preserve explicit authorization, truthful outcomes, and unrelated scopes;
Decisions 325-326 establish progressive shutdown, service-specific authorization,
and two-phase closeout.

These are existing framework contracts, not new GUI requirements. The Services
tab, its controls, and all presentation ideas above remain future design ideas,
not accepted architecture or approved implementation requirements. This document
adds no service states, lifecycle behavior, startup mechanism, or recovery policy
and does not resolve Q019, Q024, or other open architectural questions.

## GUI Closure Versus Framework Shutdown

**Closing the GUI and shutting down the operational framework are separate actions.**

This distinction is already accepted by Decisions 304 and 314: operational
services have GUI-independent lifetimes, and GUI closure is separate from
framework shutdown. The future GUI should communicate this distinction clearly
to administrators, avoiding the assumption that closing the interface
automatically terminates the operational framework. Its presentation remains
part of the proposed GUI design, not an implemented feature.
