# Validated Workflows

This document records the end-to-end workflows that have been implemented and validated by the public test suite.

Each workflow represents a complete vertical slice through one or more architectural boundaries.

The purpose of this document is to answer:

> **"What can the framework do today?"**

rather than:

- why the architecture is designed a certain way (see `architecture_decisions.md`)
- what architectural terms mean (see `glossary.md`)
- where code lives (see `code_map.md`)

As the framework grows, this document should evolve into a catalog of validated capabilities.

---

# W001 — Session Lifecycle

## Purpose

Validate the Phase 1 runtime Session lifecycle.

## Workflow

```text
Session
    │
    ▼
created
    │
    ▼
initialize()
    │
    ▼
start()
    │
    ▼
stop()
    │
    ▼
complete()
```

## Validates

- Session lifecycle transitions
- lifecycle recording
- readiness gating
- cleanup
- normal completion

---

# W002 — Device Readiness

## Purpose

Validate the boundary between configuration, live devices, and Session readiness.

## Workflow

```text
DeviceDeclaration
        │
        ▼
DeviceAdapter
        │
        ▼
DeviceManager
        │
        ▼
DeviceReadinessSummary
        │
        ▼
Session.initialize()
```

## Validates

- Device declarations
- live adapters
- DeviceManager lifecycle coordination
- readiness aggregation
- Session readiness gating
- required vs optional devices

---

# W003 — Service Readiness

## Purpose

Validate that Session initialization consumes readiness summaries from framework services.

## Workflow

```text
InMemoryIngestor
        │
        ▼
ServiceReadiness
        │
        │
InMemoryStorageManager
        │
        ▼
ServiceReadiness
        │
        │
SynchronizationManager
        │
        ▼
ServiceReadiness
        │
        ▼
Session.initialize()
```

## Validates

- shared ServiceReadiness contract
- Session service readiness recording
- required service gating
- Session does not inspect service internals

---

# W004 — Acquisition Envelope Boundary

## Purpose

Validate the acquisition-to-ingestion boundary.

## Workflow

```text
DeviceManager
        │
        ▼
DeviceRecordCollection
        │
        ▼
Acquisition-side caller
        │
        ▼
AcquisitionRecordEnvelope
        │
        ▼
dict
        │
        ▼
AcquisitionRecordEnvelope
        │
        ▼
InMemoryIngestor
        │
        ▼
InMemoryStorageManager
```

## Validates

- DeviceManager does not know Ingestor
- acquisition-side caller creates envelopes
- envelope plain-data round trip
- Ingestor receives envelopes
- StorageManager stores accepted envelopes unchanged

---

# W005 — Phase 1 Session Time

## Purpose

Validate the ownership of Session Time.

## Workflow

```text
SynchronizationManager
        │
        ▼
start()
        │
        ▼
session_time_s
        │
        ▼
Acquisition-side caller
        │
        ▼
records
        │
        ▼
AcquisitionRecordEnvelope
        │
        ▼
Ingestor
        │
        ▼
Storage
```

## Validates

- SynchronizationManager owns Session Time
- adapters do not assign Session Time
- acquisition-side caller attaches Session Time
- Ingestor preserves Session Time
- Storage preserves Session Time

---

# W006 — Session Acquisition Lifecycle

## Purpose

Validate the complete Phase 1 acquisition workflow.

## Workflow

```text
Session created
        │
        ▼
Device declarations
        │
        ▼
Live DeviceAdapters
        │
        ▼
DeviceManager
        │
        ▼
Device readiness
        │
        ▼
Service readiness
    ├── Ingestor
    ├── Storage
    └── SynchronizationManager
        │
        ▼
Session.initialize()
        │
        ▼
Session.start()
        │
        ▼
SynchronizationManager.start()
        │
        ▼
session_start event
        │
        ▼
AcquisitionNode
        │
        ▼
run_one_iteration()
        │
        ▼
DeviceRecordCollection
        │
        ▼
AcquisitionRecordEnvelope
        │
        ▼
dict round-trip
        │
        ▼
InMemoryIngestor
        │
        ▼
InMemoryStorageManager
        │
        ▼
SynchronizationManager.stop()
        │
        ▼
session_stop event
        │
        ▼
Session.stop()
        │
        ▼
Session.complete()
```

## Validates

- Session lifecycle
- device readiness
- service readiness
- Session Time ownership
- session_start acquisition evidence
- bounded acquisition
- acquisition envelope boundary
- envelope serialization boundary
- ingest auditing
- storage boundary
- session_stop acquisition evidence
- normal session completion

---

# W007 - AcquisitionNode Bounded Execution

## Purpose

Validate that AcquisitionNode owns bounded acquisition-side execution without owning Session lifecycle.

## Workflow

```text
Session.initialize()
        |
        v
Session.start()
        |
        v
AcquisitionNode.start_acquisition()
        |
        v
session_start envelope
        |
        v
AcquisitionNode.run_one_iteration()
        |
        v
DeviceManager.collect_records()
        |
        v
AcquisitionRecordEnvelope
        |
        v
dict round-trip
        |
        v
InMemoryIngestor
        |
        v
InMemoryStorageManager
        |
        v
AcquisitionNode.stop_acquisition()
        |
        v
session_stop envelope
        |
        v
Session.stop()
        |
        v
Session.complete()
```

## Validates

- AcquisitionNode receives already-created runtime collaborators
- AcquisitionNode starts and stops Session Time through SynchronizationManager
- AcquisitionNode creates session_start and session_stop acquisition evidence
- AcquisitionNode runs bounded synchronous acquisition iterations
- AcquisitionNode attaches Session Time to untimestamped fake rows
- AcquisitionNode sends envelopes through the plain-data boundary
- Session lifecycle remains separate from acquisition execution

---

# Future Workflows

The following workflows are expected to be added as the framework evolves.

## Planned

- Persistent storage
- Reconstruction
- NWB export
- Multi-node acquisition
- Hardware synchronization
- Device file transfer
- Validation reports

These sections should only be added after the corresponding public workflow has been implemented and validated.
