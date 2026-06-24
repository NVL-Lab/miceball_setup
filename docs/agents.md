# AGENTS.md

Instructions for AI coding agents working in this repository.

This repository is in the architecture design phase.
Do not treat unresolved architectural questions as implementation requirements.

---

# Primary Rule

Before making changes, read:

```text
README.md
docs/architecture_decisions.md
docs/open_questions.md
AGENTS.md
```

If a requested change conflicts with an accepted architecture decision, stop and report the conflict.

---

# Repository Scope

This repository is for a modular synchronization and acquisition framework for neuroscience experiments.

It is not:

* a GUI repository
* a neuroscience analysis repository
* a publication plotting repository
* a one-off experiment script repository

The GUI is a client of this framework.

---

# Architecture First

Do not invent new architecture.

Use the accepted terminology:

* Acquisition Node
* Controller
* Ingestor
* Synchronization Manager
* Device Adapter
* Device Manager
* Storage Manager
* Reconstruction Manager
* Session time
* Device local time
* Ingest time
* Timing records

Do not introduce synonyms such as:

* master node
* central brain
* data hub
* timestamp server
* clock daemon

unless an architecture decision explicitly accepts them.

---

# No Monoliths

Do not combine unrelated responsibilities.

Accepted ownership boundaries:

* Device Adapter: device-specific communication
* Device Manager: device lifecycle
* Synchronization Manager: session time
* Ingestor: data entry
* Storage Manager: persistence
* Reconstruction Manager: session reconstruction
* Controller: high-level session commands
* Acquisition Node: hardware-facing acquisition runtime

A file or class should have one clear reason to exist.

---

# No Hidden Defaults

Important parameters must not be hidden inside wrapper defaults.

If a parameter affects:

* scientific data
* timing
* synchronization
* storage
* device behavior
* protocol behavior
* reconstruction

then it must be represented in explicit configuration.

Do not bury important behavior in a lower-level function default that higher-level code cannot modify.

---

# Reuse Before Adding

Before creating a new function, class, or module:

1. Check whether equivalent logic already exists.
2. Reuse existing code when it fits the same responsibility.
3. Extend existing code only if doing so keeps the responsibility clear.
4. Create new code only when there is a distinct architectural reason.

Do not duplicate logic because it is faster.

Do not force unrelated logic into a generic helper just to reuse code.

---

# Code Map Must Be Maintained

The repository should maintain:

```text
docs/code_map.md
```

This file should list every public or reusable function/class and give a one-sentence explanation of what it does.

Whenever an agent adds, removes, renames, or moves a function or class, it must update `docs/code_map.md`.

The purpose of the code map is to prevent duplicate helper functions and make reuse easier.

Suggested format:

```text
## module/path.py

- function_or_class_name: One-sentence explanation of responsibility.
```

Do not include long implementation details in the code map.

---

# Utils Are Last Resort

A `utils` area may exist, but it must not become a junk drawer.

Allowed in `utils`:

* genuinely generic path helpers
* simple formatting helpers
* small validation helpers with no domain owner

Not allowed in `utils`:

* synchronization logic
* device lifecycle logic
* storage schemas
* reconstruction logic
* protocol logic
* acquisition logic

Prefer domain ownership.

Example:

```text
sync/time_mapping.py
```

is preferred over:

```text
utils/time_helpers.py
```

when the logic belongs to synchronization.

---

# Keep Files Focused

Avoid vague files such as:

```text
helpers.py
common.py
manager.py
main.py
everything.py
```

Prefer names that describe responsibility:

```text
session_manifest.py
device_capabilities.py
timebase.py
ingest_record.py
storage_manifest.py
```

---

# Avoid Premature Abstraction

Do not create abstract base classes, plugin systems, factories, registries, or dependency-injection systems unless an accepted architecture decision requires them.

Prefer clear boundaries before elaborate abstractions.

---

# Timing Rules

Every data row, sample, frame, or event must have session time or enough stored information to reconstruct session time.

Keep these concepts separate:

* session time
* device local time
* ingest time

Ingest time is for debugging and auditing.
It must not be silently used as scientific acquisition time.

Timing records are part of the raw scientific record.

Do not discard timing records because they appear redundant.

---

# Storage Rules

Intermediate records should remain human-readable and easy to debug.

NWB export is a goal, but NWB should not be the only inspectable storage format.

Do not discard raw data, timing records, error records, or device state records in favor of cleaner-looking outputs.

Raw but complete is better than clean but incomplete.

---

# Plotting Rules

Plotting is allowed only for framework validation and debugging.

Allowed examples:

* timestamp spacing
* dropped frame intervals
* stream alignment
* synchronization anchors
* reconstruction checks

Not allowed:

* neural tuning analysis
* behavioral decoding
* publication figure generation
* experiment-specific scientific analysis

---

# GUI Boundary

Do not add GUI code to this repository.

This repository may define interfaces, contracts, or data structures that a GUI can use.

The GUI itself belongs elsewhere.

---

# Testing Expectations

Tests should verify architectural promises, not only code behavior.

Important examples:

* every sample has session time or reconstructable timing
* ingest time is not used as session time
* timing records are preserved
* failed sessions preserve enough records for diagnosis
* device adapters declare capabilities
* reconstruction can run from stored records only

---

# Documentation Expectations

When adding or changing architecture-relevant code, update the relevant documentation.

Possible documents:

```text
docs/architecture_decisions.md
docs/open_questions.md
docs/code_map.md
README.md
AGENTS.md
```

Do not create final architecture documents unless explicitly requested.

Do not create:

```text
architecture.md
repository_map.md
design_decisions.md
codex_governance.md
```

until the architecture phase accepts those documents.

---

# Stop Conditions

Stop and ask for architectural clarification if a requested change requires deciding:

* what a session is
* what a stream is
* what an event is
* what the storage model is
* what the synchronization anchor format is
* what the device contract is
* what the reconstruction output is
* how multi-node acquisition works

Do not silently decide these in code.

# Simplicity First

Prefer the simplest solution that satisfies the current architectural requirements.

Do not build infrastructure for hypothetical future needs.

Do not introduce additional abstraction layers unless they solve an existing problem or are required by an accepted architectural decision.

Examples of things that should not be added without a documented need:

* plugin systems
* dependency injection frameworks
* service locators
* registries
* event buses
* workflow engines
* distributed coordination systems
* generic factory hierarchies
* complex inheritance trees

Future extensibility should come from clear component boundaries, not from speculative abstraction.

A small amount of duplicated code is preferable to a large abstraction that has not yet demonstrated value.

Rule of Three:

Before introducing a new abstraction, there should usually be at least three concrete use cases that benefit from it.

Prefer:

```text
simple
explicit
readable
testable
```

over:

```text
generic
clever
highly configurable
deeply abstract
```

When deciding between two designs with equivalent functionality, choose the design that is easier for a new lab member to understand.


# Optimize for Auditability

This repository may be developed with AI assistance, but the system must remain understandable and auditable by humans.

Researchers must be able to inspect the code, configuration, timing records, and stored outputs well enough to decide whether an experiment is scientifically valid.

Prefer straightforward designs over clever or deeply abstract designs.

A design that is slightly less elegant but easier to inspect, test, and explain is usually preferred.

The cost of complexity is paid during debugging, validation, and scientific interpretation, even if AI generated the code.
