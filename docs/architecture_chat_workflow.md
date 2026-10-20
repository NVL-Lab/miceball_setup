# Architecture Chat Development Workflow

## Purpose And Scope

This is the authoritative procedural reference for development roles, architectural
authority, implementation, independent validation, audit, and documentation
closure. It governs how development is conducted, not the scientific framework's
architecture. It is neither an implementation roadmap nor a new architecture
decision. [AGENTS.md](../AGENTS.md) retains mandatory repository engineering rules.

All handoffs between HLC, LLC, ICC, Codex, and successor chats, including successor
chats within the same role, must reference this authoritative workflow document
rather than restate, duplicate, redefine, or reinterpret its roles,
responsibilities, authority, or workflow rules. Every handoff must:

1. Direct the receiving chat or agent to read
   `docs/architecture_chat_workflow.md` and the relevant current architecture
   decisions.
2. Describe only the task being transferred, its current status, relevant accepted
   decisions, unresolved questions, and expected next action.
3. Avoid repeating general role descriptions, responsibilities, authority
   boundaries, or workflow instructions.
4. Never override or reinterpret this document. If a handoff conflicts with it,
   the receiving chat or agent must follow this document and report the
   inconsistency.

## Architectural Authority

**Only the user can accept architectural decisions.** Acceptance may be expressed
through clear affirmative responses such as "accept," "yes," "OK," "fine," "good,"
or "agreed." Acceptance must refer to an identifiable proposed decision. Silence,
ambiguous responses, or continued discussion do not constitute acceptance.

Do not infer acceptance from assistant recommendations, ICC instructions, Codex
implementation, or passing tests. Unclear acceptance leaves the proposal
unresolved and requires returning it through this workflow for user acceptance.

Existing formally recorded accepted decisions retain their authority; this rule
does not retroactively invalidate them. Ordinary implementation choices within
accepted contracts are distinct from architectural decisions.

The responsibility gradient is:

```text
HLC -> LLC -> ICC -> Codex
```

Moving right increases implementation involvement, not architectural authority.
No development, validation, or auditing role independently accepts architecture.

## HLC - High-Level Chat

HLC owns discussion of conceptual architecture, component responsibilities, and
system behavior.

- Reads architecture documentation; does not inspect source code.
- Proposes architectural decisions for explicit user acceptance.
- Does not produce implementation instructions or independently accept architecture.

## LLC - Low-Level Chat

LLC translates accepted conceptual architecture into minimal software contracts
and interfaces.

- Reads architecture documentation first.
- May inspect existing GitHub source only when architecturally necessary to
  understand interfaces or resolve compatibility questions, without taking over
  implementation or auditing.
- Does not implement code, directly modify repository files, or prepare Codex
  implementation prompts.
- Prepares architectural handoffs for ICC and returns high-level conflicts to HLC.
- Does not independently accept architecture.

## ICC - Implementation Coordinator Chat

ICC coordinates implementation of accepted architecture, not architectural design
or acceptance.

- Receives accepted architecture from LLC and coordinates documentation
  synchronization before implementation.
- Prepares Codex implementation instructions and reviews implementation reports.
- Reviews the proposed scope against the pre-implementation impact and
  invariant-coverage analysis before authorizing implementation.
- May inspect code to understand implementation, assess reports, and plan
  independent validation.
- Coordinates independent manual IPython validation, independent audits, and
  documentation closure.
- Does not independently propose, select, accept, or modify architecture; returns
  unresolved architectural questions to LLC or HLC.

## Codex - Coding Agent

Codex implements accepted architecture under ICC instructions.

- Inspects and modifies source within the authorized scope, adds and runs
  appropriate tests, and updates required implementation documentation.
- Reports implementation results, discrepancies, limitations, and architectural
  conflicts.
- May make ordinary implementation choices within accepted contracts, but may not
  independently establish or alter architectural requirements, component ownership,
  interfaces, lifecycle guarantees, or evidence-preservation obligations.
- Stops and reports when implementation requires an unresolved architectural
  decision; does not independently decide or modify architecture.

## Independent Validation And Audit

These roles verify public behavior and compliance with accepted architecture.
Manual IPython validation is coordinated by ICC. Independent auditing separately
evaluates implementation and architectural compliance. Validators and auditors
report findings to ICC; neither role accepts or changes architecture.

Codex's automated tests are necessary for implementation but do not replace
independent validation or audit. Manual validation and independent audit are
distinct stages, not alternate names for the same check.

## Required Implementation Sequence

```text
Accepted architecture
    -> Documentation synchronization
    -> Proportional impact and invariant-coverage review
    -> ICC scope review and implementation authorization
    -> Codex implementation and automated tests
    -> ICC review of Codex report
    -> Independent manual IPython validation
    -> Independent audit
    -> Documentation closure
    -> Next slice
```

No implementation begins before accepted architecture is synchronized. ICC reviews
the implementation report before manual validation. Documentation-only tasks do
not automatically require implementation validation, but must preserve accepted
architecture and authorized scope.

## Pre-Implementation Impact And Invariant Review

Before changes affecting existing behavior or architectural contracts, Codex must
complete an impact and invariant-coverage review that:

- Identifies the accepted requirements and invariants affected by the change.
- Traces relevant public entry points, internal callers, state transitions,
  failure handlers, retries, and local/distributed variants.
- Identifies producers and consumers of affected state, authority, and evidence.
- Distinguishes paths that already enforce the invariant, delegate to shared
  enforcement, or require correction.
- Identifies existing tests and meaningful coverage gaps.
- Separates confirmed defects from suspected risks and unrelated issues.
- Establishes a coherent proposed implementation boundary before coding.

Review depth must be proportional to the change. Simple, isolated changes need
only a concise assessment, not a framework-wide inventory or large matrix.
Cross-cutting lifecycle, concurrency, persistence, and distributed-state changes
require broader analysis of the affected paths and boundaries.

ICC must review the proposed implementation scope against this analysis before
authorizing implementation. Missing or conflicting architectural requirements
follow the existing LLC/HLC clarification process below; scope review does not
authorize new architecture. Codex's engineering obligations for enforcement,
consolidation, and regression reproduction are defined in
[AGENTS.md](../AGENTS.md#impact-analysis-and-invariant-enforcement).

## Implementation Reporting

Implementation work affecting existing behavior must include a concise report of:

- The impact and invariant-coverage assessment, entry points examined, and their
  enforcement coverage.
- Confirmed defects and corrections, distinguished from suspected risks and
  unrelated issues.
- A code consolidation assessment: existing mechanisms reused, redundant code
  removed or consolidated, and earlier patches retained with reasons.
- Remaining gaps and limitations, including complexity or cleanup outside the
  authorized scope.
- Tests selected, their impact-based rationale, and actual results.

Report depth must remain proportional to the change. Trivial changes do not
require lengthy reports or large matrices. These reports do not replace
independent manual validation, independent audit, or the existing closure rules.

## Handling Architectural Conflicts

Codex reports contradictions or missing architectural requirements to ICC and
stops the affected implementation. ICC returns the issue to LLC or HLC as
appropriate. The user explicitly accepts any resulting clarification before
documentation synchronization and implementation resume.

No role silently resolves architectural uncertainty outside its responsibility.
An audit finding that requires architectural clarification follows this same path,
not an implementation-only correction.

## Explicit Acceptance And Documentation Synchronization

Separate proposals, explicit user acceptance, and repository recording. Codex may
document an explicitly user-accepted decision when instructed by ICC; **recording
a decision does not itself constitute acceptance**.

Synchronization records accepted contracts without inventing requirements or
resolving deferred questions. If acceptance or the required contract is unclear,
return it for clarification rather than implementing an assumption.

## Slice Validation And Closure

A slice is not marked validated or complete before its required independent
validation and audit pass. Implementation completion and passing Codex tests
alone are insufficient for closure.

Audit findings return through ICC to implementation for correction and subsequent
verification, unless they require architectural clarification. ICC coordinates
documentation closure after successful validation and audit. Preserve historical
records, distinguish reported evidence from newly executed checks, and do not
close a broader phase or milestone solely because one narrow slice is complete.
