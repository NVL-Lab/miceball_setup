# Future GUI Design Notes

This document preserves ideas for future GUI discussions. It is not an
implementation roadmap, architecture decision record, or source of approved
implementation requirements. GUI implementation belongs outside this repository.

---

## Framework Shutdown Window

**Status:** Proposed GUI design — pending relevant Phase 16 high-level architecture decisions and synchronization.

When an administrator requests operational framework shutdown through the GUI,
the proposed presentation is a dedicated shutdown window that would:

- Display all operational services included in the requested shutdown.
- Show each service's current shutdown status as Controller progresses through
  the shutdown sequence.
- Display the results of the initial local readiness survey.
- Clearly distinguish services that are waiting, stopping, stopped, blocked, or
  failed, and explain why a service is blocked.
- Provide a separate **Kill** button for each blocked service when forced
  termination requires explicit administrator authorization.
- Require a new, explicit authorization for each blocked service; authorization
  for one service would not authorize termination of another.
- Allow the administrator to decline forced termination while preserving the
  actual shutdown outcomes.
- Make clear that services already stopped will not automatically restart.

The proposed window would clearly communicate forced-termination consequences,
including possible loss of unpreserved scientific data or runtime evidence.

### Architectural boundary

Existing accepted contracts separate GUI interaction from Controller coordination
and service-owned cleanup (Decisions 001-002, 305, and 314). They require explicit
authorization for forced continuation of a blocked attempt, truthful confirmed
outcomes, and protection of unrelated scopes (Decisions 308-311 and 315-316).

The proposed progressive shutdown presentation, initial local readiness survey,
and separate per-service authorization behavior remain pending discussion and
synchronization. These notes do not approve a shutdown sequence or authorization
contract. Waiting, stopping, stopped, blocked, and failed are proposed display
labels, not additions to accepted lifecycle states or attempt outcomes. Existing
open architectural questions remain unresolved by this document.

## GUI Closure Versus Framework Shutdown

**Closing the GUI and shutting down the operational framework are separate actions.**

This distinction is already accepted by Decisions 304 and 314: operational
services have GUI-independent lifetimes, and GUI closure is separate from
framework shutdown. The future GUI should communicate this distinction clearly
to administrators, avoiding the assumption that closing the interface
automatically terminates the operational framework. Its presentation remains
part of the proposed GUI design, not an implemented feature.
