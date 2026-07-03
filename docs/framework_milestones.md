# Framework Milestones

This document records major technical milestones in the evolution of the Lab Sync Acquisition framework.

Unlike the Architecture Decisions, which capture *why* the system is designed a certain way, milestones capture *what has been successfully demonstrated*. A milestone represents a significant increase in confidence in the framework through implementation and validation.

---

# M001 — Framework Foundation

**Status:** Completed

## Goal

Establish the core acquisition architecture and ownership boundaries.

## Demonstrated

- Session lifecycle
- SessionConfig ownership
- Device lifecycle
- DeviceManager coordination
- SynchronizationManager ownership of Session Time
- AcquisitionNode execution
- AcquisitionRecordEnvelope boundary
- Ingestor boundary
- Persistent JSONL storage
- Persistent Session Record
- Public workflow tests

## Confidence gained

The core framework architecture supports bounded acquisition, ingestion, persistence, auditability, and clean ownership boundaries.

---

# M002 — Cross-Process Acquisition

**Status:** Completed

## Goal

Demonstrate that acquisition and ingestion can execute in independent processes without sharing live Python objects.

## Demonstrated

```text
Acquisition Process
        │
        ▼
AcquisitionRecordEnvelope (plain JSON)
        │
localhost socket
        │
        ▼
Ingestor Process
```

## Validated

- Cross-process communication
- Plain-data envelope boundary
- Independent producer and consumer processes
- Ingestor persistence through StorageManager
- No shared Python objects

## Confidence gained

The `AcquisitionRecordEnvelope` is a sufficient boundary between acquisition and ingestion. The framework does not require shared memory or shared runtime objects.

---

# M003 — First Real Hardware Integration

**Status:** Completed

## Goal

Replace the fake camera implementation with a real OpenCV camera without changing the framework architecture.

## Hardware

- Laptop integrated webcam
- OpenCV `cv2.VideoCapture`
- Windows Media Foundation (MSMF)

## Demonstrated

```text
Real webcam
        ↓
cv2.VideoCapture
        ↓
OpenCVCameraAdapter
        ↓
DeviceManager
        ↓
AcquisitionNode
        ↓
live localhost socket
        ↓
Ingestor
        ↓
PersistentStorageManager
```

## Validated

- Real SDK integration
- Device lifecycle
- Readiness
- Metadata acquisition
- Session Time assignment
- Cross-process transport
- Persistent storage
- Metadata-only acquisition records
- No image payload transmitted

## Confidence gained

A real hardware SDK can replace the fake implementation without requiring architectural changes.

The acquisition framework supports real devices while preserving the established ownership boundaries.

---

# M004 — Controller v1 Sequential Orchestration

**Status:** Completed

## Goal

Replace manual single-Session sequencing with a minimal synchronous Controller while preserving existing component ownership.

## Demonstrated

- Acquisition Runtime terminology through `start_runtime()` and `stop_runtime()`
- sequential create, initialize, start, iteration, stop, and finalization commands
- Controller command-result evidence
- pre-running, iteration, runtime-stop, and first-write finalization failure outcomes
- two-step Session Record persistence ending with durable completed evidence

## Confidence gained

One bounded Session can be orchestrated and finalized through public framework APIs without introducing GUI behavior, asynchronous execution, retry, or new ownership boundaries.

---

# Future Milestones

Planned future milestones include:

- First Jetson CSI camera
- First lick sensor integration
- First synchronized multi-device acquisition
- First Parquet backend
- First microscope integration
- First complete Session containing Experiment activity
- First NWB export
- First distributed acquisition across multiple nodes

These milestones will be added as they are successfully demonstrated.
