# Lab Sync Acquisition



A modular synchronization and acquisition framework for neuroscience experiments.



## Overview



This repository is developing a hardware-agnostic framework for:



* data acquisition

* device synchronization

* timing management

* session storage

* session reconstruction



The framework is intended to support behavioral and neural experiments involving multiple devices, including:



* cameras

* lick sensors

* water delivery systems

* speakers

* accelerometers

* future sensors and actuators



The framework is independent of any specific experiment and independent of any specific graphical user interface.



A separate GUI may configure and control experiments, but the GUI is considered a client of the framework rather than part of the framework itself.

In framework terminology, a Project is the larger scientific study, a Session
is one bounded acquisition/evidence run, and an Experiment is scientific or
protocol activity inside a running Session.



---



## Project Goals



The framework aims to provide:



* a common device abstraction

* explicit ownership of synchronization and timing

* reproducible session reconstruction

* human-readable intermediate outputs

* compatibility with NWB export

* support for future hardware expansion



---



## Motivation



This project is informed by lessons learned from a previous acquisition system that suffered from:



* no explicit timing authority

* independently generated timestamps

* no drift handling

* no periodic synchronization

* incomplete synchronization implementation

* complex process interactions

* unclear ownership of responsibilities



The architecture of this framework is being designed specifically to avoid those failure modes.



---



## Current Status



The project is currently in the architecture design phase.



Small parts of the implementation have begun.

The Phase 2 envelope path has been manually validated over Wi-Fi between an
NVIDIA Jetson Orin AcquisitionNode and a Windows ingestion/storage computer.
The same two-machine path has also been validated with a real Jetson USB camera
using OpenCV/V4L2 and metadata-only acquisition envelopes.

Phase 4 Controller v1 now provides validated sequential orchestration for one
bounded Session, including normal completion, runtime failure outcomes, cleanup,
and two-step persistent Session Record finalization.

Phase 5 now provides validated Controller-owned Experiment lifecycle, persistent
Experiment descriptors and Expected Participant declarations, explicit runtime
health mappings that assign Experiment-specific acquisition-health policies,
and AcquisitionNode health evaluation scoped only to mapped live acquisition
sources. Device declarations describe Session availability rather than global
health-policy consequence.

Phase 6 adds evidence-only Experiment-scoped health observations and immutable
plain-data acquisition-health policy definitions. Observation type remains
separate from consequence, policy assignment remains Experiment-scoped, and
runtime warning/failure/Controller behavior is intentionally deferred.

The current Phase 7 slice adds SessionConfig-owned policy definitions with
rule-specific `evaluation_rules`, immediate AcquisitionNode policy
interpretation, and explicitly linked Health Interpretation Evidence. These
interpretations remain evidence only; Controller actions and lifecycle
consequences are intentionally deferred.

Phase 8a adds explicit, evidence-only `ControllerActionDecision` records for
Health Interpretation Evidence presented directly to Controller. Decision
execution, lifecycle consequences, notification, recovery, and distributed
evidence delivery remain intentionally deferred.

Phase 8b executes Experiment- and Session-failure decisions through existing
lifecycle owners. Experiment failure records canonical `experiment_fail`
evidence and ends only the active Experiment; Session failure reuses the
existing failed-Session cleanup path.



The project follows an architecture-first development process. Architectural decisions are discussed and documented before the corresponding implementation is added to the framework.


---



## Architecture Documents



### Accepted Decisions



See:



```text

docs/architecture\_decisions.md

```



This document contains architectural decisions that have been accepted by the architecture board.



### Open Questions



See:



```text

docs/open\_questions.md

```



This document tracks unresolved architectural questions that must be addressed before implementation begins.



### Local Cross-Process Demo



See:



```text

docs/local_cross_process_demo.md

```



This document explains the live two-shell localhost socket demos, including the basic plain-envelope sender and the OpenCV camera-adapter metadata sender.



---



## Guiding Principles



* The GUI is a client, not the owner of acquisition timing.

* Session time has a single owner.

* Timing information is part of the scientific record.

* Offline reconstruction must be possible from stored records.

* Devices should be modular and interchangeable.

* Configuration should be explicit rather than hidden in implementation defaults.

* Intermediate outputs should remain easy to inspect and debug.



---



## Repository Status



The repository structure, storage model, synchronization model, and device contracts are still under discussion.



No production implementation should be considered stable until the architectural design phase is complete.



