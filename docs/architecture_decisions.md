# Architecture Decisions

This document records accepted architectural decisions for the laboratory synchronization and acquisition framework.

This is a decision log, not the final architecture document.
The final `architecture.md` will be created later from accepted decisions.

---

## Decision 001: The GUI is a client

**Status:** Accepted

The GUI is a client of the synchronization and acquisition framework.

The GUI may define:

* enabled devices
* session parameters
* protocol choices
* user-facing commands

The GUI does not own:

* acquisition timing
* device synchronization
* raw data storage
* session reconstruction
* scientific timestamps

**Rationale:**
The framework must remain usable without a specific GUI implementation. Acquisition timing must remain close to the acquisition system, not the user interface.

**Consequence:**
GUI integration must occur through explicit commands and configuration handoff.

---

## Decision 002: GUI and Controller are conceptually separate

**Status:** Accepted

The GUI and Controller are separate architectural roles, even if they run on the same computer.

The GUI is responsible for user interaction.

The Controller is responsible for high-level session commands, such as:

* create session
* configure session
* start session
* stop session
* abort session

**Rationale:**
Separating GUI from Controller prevents user-interface code from becoming the session authority.

**Consequence:**
The framework should not assume that the GUI process is the same thing as the session command authority.

---

## Decision 003: The Jetson is an Acquisition Node

**Status:** Accepted

The Jetson is a hardware-facing Acquisition Node.

The Jetson owns:

* local hardware communication
* device adapters
* local device lifecycle during acquisition
* acquisition start/stop execution
* local timestamp capture
* forwarding data and events to the Ingestor

The Jetson does not own:

* global experiment design
* GUI logic
* long-term storage policy
* final session reconstruction
* neuroscience analysis

**Rationale:**
The Jetson should be the hardware-facing system, not the whole-system overlord.

**Consequence:**
The Jetson should remain replaceable by another acquisition node in the future.

---

## Decision 004: The Ingestor is a separate architectural entity

**Status:** Accepted

The Ingestor is an independent architectural entity.

It may run:

* on the GUI PC
* on a second laptop
* on the Jetson
* on a storage/server machine

The Ingestor owns:

* receiving data packets and events
* assigning ingest order
* preserving timing records
* validating completeness
* forwarding or writing data to storage
* recording packet arrival time for debugging

The Ingestor does not own:

* scientific time
* session time
* device lifecycle
* protocol execution
* GUI configuration

**Rationale:**
The legacy system blurred ingestion, timing, and storage. This framework separates those responsibilities.

**Consequence:**
Ingestor arrival time must never be treated as the scientific timestamp of a sample or event.

---

## Decision 005: Batch transfer is allowed, but does not define timing

**Status:** Accepted

Acquisition Nodes may transmit data in batches.

For example, the Jetson may send every 500 rows of acquired data to the Ingestor.

However, each row, sample, or event must already contain its timing information before batching.

**Accepted rule:**

```text
Acquire sample -> assign/capture timestamp -> batch -> ingest -> store
```

**Rejected rule:**

```text
Acquire sample -> batch -> ingest -> assign same arrival timestamp to all rows
```

**Rationale:**
Network or inter-process transfer timing is not the same as acquisition timing.

**Consequence:**
Batch size may affect latency, but it must not affect scientific timestamps.

---

## Decision 006: Session time has one owner

**Status:** Accepted

Session time is owned by the Synchronization Manager.

Session time is the shared experiment time used to align all streams and events.

The GUI does not own session time.
The Ingestor does not own session time.
Message queues do not own session time.
Storage does not own session time.

**Rationale:**
The legacy system had no explicit timing authority. This framework must have one.

**Consequence:**
Every stored sample or event must be traceable to session time.

---

## Decision 007: Phase 1 session time may use Jetson monotonic time

**Status:** Accepted

For the first version, session time may be based on the Jetson monotonic clock.

This is acceptable because:

* the most critical data are approximately 30 Hz
* millisecond-level precision is sufficient for the initial setup
* the Jetson is close to the acquisition hardware

Session time must not be based on:

* wall-clock time
* GUI time
* Ingestor arrival time
* Redis/message queue timestamps

**Rationale:**
An external hardware timing source is not required initially if Jetson monotonic time satisfies experimental precision.

**Consequence:**
The architecture must still allow future upgrade to hardware timing anchors if needed.

---

## Decision 008: External hardware timing remains a future-compatible option

**Status:** Accepted

The system should not require an external hardware timing source in Phase 1.

However, the architecture must allow future timing sources, such as:

* hardware pulse trains
* frame counters
* DAQ counters
* TTL synchronization signals
* external clock sources

**Rationale:**
The first system should not be overbuilt, but the architecture should not prevent stronger synchronization later.

**Consequence:**
The Synchronization Manager should be defined conceptually as owning session time, not as being permanently tied to one specific clock source.

---

## Decision 009: Devices may keep local clocks, but local clocks are not session time

**Status:** Accepted

Devices may produce local timestamps, counters, frame numbers, or sample indices.

These local timing records should be preserved when available.

However, local device time is not the same as session time.

**Rationale:**
Device-local time is useful for debugging, reconstruction, and drift detection, but it cannot be treated as the shared experiment clock unless explicitly mapped.

**Consequence:**
Stored data should distinguish clearly between:

* session time
* device local time
* ingest time

---

## Decision 010: Every data row or event must have session time

**Status:** Accepted

Every acquired data row, sample, frame, or event must have a session timestamp or a defined way to reconstruct one.

This is mandatory, not optional.

**Rationale:**
The most important scientific information is the data and when the data happened.

**Consequence:**
Data without timing is incomplete data.

---

## Decision 011: Timing records are part of the raw scientific record

**Status:** Accepted

Timing records are not secondary metadata.

They are part of the raw scientific record.

Timing records include, when applicable:

* sample timestamp
* frame timestamp
* event timestamp
* frame index
* sample index
* device local timestamp
* device local counter
* packet number
* batch number
* dropped-frame flag
* dropped-sample flag
* session start time
* session stop time
* synchronization anchor records
* local-to-session time mapping records

**Rationale:**
If timing records are lost, the session may not be scientifically reconstructable.

**Consequence:**
Timing records must be stored with the same seriousness as behavioral or neural data.

---

## Decision 012: Ingest time is stored for debugging, not scientific alignment

**Status:** Accepted

The Ingestor should record when it received packets or events.

This time is useful for:

* debugging latency
* detecting network delays
* detecting stalled devices
* auditing data transfer

Ingest time should not be used as the scientific acquisition time unless explicitly justified for a specific device or event type.

**Rationale:**
Arrival time is affected by batching, buffering, scheduling, and network delays.

**Consequence:**
Ingest time and session time must be stored as separate concepts.

---

## Decision 013: Offline reconstruction is mandatory

**Status:** Accepted

A complete session must be reconstructable from stored raw data and stored timing records.

Online synchronization may be useful, but it is not sufficient.

**Rationale:**
If reconstruction depends on transient runtime state that was not stored, the session is fragile and difficult to audit.

**Consequence:**
The system must store enough information to rebuild the session timeline after acquisition has ended.

---

## Decision 014: Device Adapter and Device Manager are separate concepts

**Status:** Accepted

A Device Adapter handles device-specific communication.

A Device Manager handles device lifecycle.

Device Adapter responsibilities include:

* communicating with a specific device type
* exposing device capabilities
* receiving device data
* issuing device commands
* reporting device status

Device Manager responsibilities include:

* device discovery
* device initialization
* device configuration
* arming devices
* starting devices
* stopping devices
* shutting devices down
* collecting health/status reports

**Rationale:**
Device-specific communication should not be mixed with whole-session lifecycle coordination.

**Consequence:**
Adding a new device should usually require a new adapter, not changes to orchestration logic.

---

## Decision 015: Device roles should use a common conceptual interface

**Status:** Accepted

The orchestration layer should not care whether a device is a camera, speaker, lick sensor, accelerometer, water port, or future device.

Devices should expose capabilities rather than biological meaning.

Examples of capabilities:

* produces stream
* produces events
* accepts commands
* accepts triggers
* provides local timestamps
* reports health
* produces files
* consumes protocol events

**Rationale:**
The system must be modular and extensible.

**Consequence:**
Device-specific meaning should live in adapters and configuration, not in the orchestration layer.

---

## Decision 016: Configuration must be explicit and propagated

**Status:** Accepted

Runtime behavior must be controlled by explicit configuration, not hidden function defaults.

The architecture should support explicit configuration for:

* session parameters
* device parameters
* synchronization parameters
* storage parameters
* protocol parameters

**Rationale:**
The legacy system allowed wrappers to hide lower-level function parameters, causing defaults to be used unintentionally.

**Consequence:**
Important runtime parameters should be represented in explicit configuration objects or files and passed through the system.

---

## Decision 017: Intermediate outputs should be human-readable

**Status:** Accepted

Intermediate outputs should remain human-readable and easy to debug.

NWB should be supported as a final scientific output, but NWB should not be the only stored/debuggable format.

**Rationale:**
During acquisition and debugging, researchers need to inspect intermediate data and timing records directly.

**Consequence:**
The storage architecture should support both debugging-friendly records and later NWB export.

---

## Decision 018: Storage should follow NWB logic where appropriate

**Status:** Accepted

The internal data model should be compatible with NWB concepts where practical.

This does not mean that every intermediate file must be NWB.

It means that device records, time series, events, metadata, and session structure should be organized in a way that makes later NWB export natural.

**Rationale:**
Final scientific output should support NWB, and early data modeling choices should not make NWB export difficult.

**Consequence:**
The storage model should avoid ad hoc structures that cannot be mapped cleanly to scientific data objects.

---

## Decision 019: The repository is for synchronization and acquisition

**Status:** Accepted

This repository is for the synchronization and acquisition framework.

It is not:

* a GUI repository
* a neuroscience analysis repository
* a plotting-first repository
* a one-off experiment script repository

**Rationale:**
Clear repository scope prevents architectural drift.

**Consequence:**
GUI code, analysis pipelines, and experiment-specific scripts should remain outside the core unless they are needed for framework validation.

---

## Decision 020: Utilities are allowed but must not become a junk drawer

**Status:** Accepted

A `utils` area may exist, but only for genuinely cross-cutting helpers that do not belong to a domain-specific component.

Domain-specific logic should live with its domain.

For example:

```text
sync/time_mapping
```

is preferred over:

```text
utils/time_helpers
```

when the logic belongs to synchronization.

**Rationale:**
Large utility folders often hide architectural boundaries.

**Consequence:**
Before adding something to utilities, decide whether it belongs to a named architectural component.

---

## Decision 021: Plotting is allowed only for framework debugging and validation

**Status:** Accepted

The repository may include plotting tools needed to validate acquisition, timing, synchronization, and reconstruction.

The repository should not become a neuroscience analysis or publication-figure repository.

**Rationale:**
Some plotting is necessary to debug timing and acquisition quality, but analysis plotting belongs elsewhere.

**Consequence:**
Plotting should focus on system validation, such as:

* timestamp spacing
* dropped frames
* stream alignment
* sync anchor visualization
* session reconstruction checks

---

## Decision 022: Source structure is not finalized yet

**Status:** Accepted

The final source tree is not yet decided.

Provisional architectural boundaries include:

* core session model
* devices
* acquisition
* synchronization
* ingestion
* storage
* reconstruction
* export
* protocols
* configuration
* constants
* utilities
* validation plotting
* tests

These boundaries should guide discussion, but they should not yet be treated as final implementation structure.

**Rationale:**
The architecture is still being decided.

**Consequence:**
The repository may contain placeholder folders, but production code should not begin until the major architectural boundaries are accepted.

---

## Decision 023: Streams and events are distinct but complementary

**Status:** Accepted

A Stream is repeated time-indexed data from one source.

Examples:

* camera frames
* accelerometer samples
* sampled lick sensor state
* continuous digital or analog signals

An Event is a discrete timestamped occurrence.

Examples:

* lick detected
* reward delivered
* tone started
* tone stopped
* camera started
* device disconnected
* dropped frame detected

A device may produce:

* streams only
* events only
* both streams and events

**Rationale:**
Different devices naturally produce different kinds of records. High-rate repeated data should not be forced into a generic event model, and sparse occurrences should not be forced into a sampled stream model.

**Consequence:**
Device Adapters must declare which streams and events they produce.

---

## Decision 024: Network transport does not define the data model

**Status:** Accepted

The mechanism used to move data, such as TCP sockets, files, shared memory, or another transport, does not determine whether data are streams or events.

Transport moves records.
The framework data model defines records.

**Rationale:**
The legacy system used TCP sockets, but the architecture should not be tied to that communication method.

**Consequence:**
Changing the transport mechanism should not require redefining Stream, Event, Session, or Timing Record concepts.

---

## Decision 025: A session is one bounded experimental run

**Status:** Accepted

A Session is one bounded experimental run initiated by the Controller using a declared configuration, selected devices, and a session identity.

A Session may last minutes to hours.
Repeated daily runs are separate sessions.

An Experiment is the larger scientific plan.
A Session is one execution of that plan.

**Rationale:**
One experiment may contain many sessions across days. The framework needs the session to be the concrete acquisition and reconstruction unit.

**Consequence:**
Session records should contain all data, events, timing records, configuration, and manifests needed to reconstruct that run.

---

## Decision 026: Session start and experiment start are different

**Status:** Accepted

Session start means acquisition begins.

Experiment start means the protocol begins.

The experiment start is recorded as an event inside the session timeline.

Example:

```text
session_start        t = 0 s
camera_ready         t = 45 s
experiment_start     t = 120 s
tone_start           t = 180 s
experiment_end       t = 3600 s
session_end          t = 3660 s
```

**Rationale:**
Devices may require warmup, stabilization, calibration, or buffering before the scientific protocol begins. Recording this period preserves diagnostic information.

**Consequence:**
The system should record too much rather than start acquisition late. Scientific analysis can later use the `experiment_start` event as the behavioral/protocol beginning.

---

## Decision 027: Intermediate records are table-shaped and stored as Parquet by default

**Status:** Accepted

Intermediate records should use table-shaped data models.

In memory, these records may be represented as DataFrames.

On disk, Parquet is the preferred default format for streams, events, timing records, ingest records, and reconstruction outputs.

CSV may be used for small human-readable debug exports, but should not be the primary storage format for large or typed records.

**Rationale:**
Parquet preserves column types better than CSV and is more efficient for large structured records, while still supporting inspection and debugging workflows.

**Consequence:**
The architecture should define schemas for table-shaped records independently of the specific in-memory representation.

---

## Decision 028: Storage uses raw records first, reconstruction/export later

**Status:** Accepted

The session storage model should preserve raw session records first.

Reconstruction and export should produce derived outputs later.

Raw records include:

* streams
* events
* timing records
* ingest records
* errors
* configuration
* manifests

**Rationale:**
Raw records are the scientific evidence. Reconstruction and NWB export should not replace or overwrite them.

**Consequence:**
Raw records should remain immutable after session close whenever possible.

---

## Decision 029: Reconstruction writes derived outputs and does not silently modify raw records

**Status:** Accepted

Reconstruction is the process of rebuilding a complete session timeline from stored raw streams, events, timing records, configuration, and manifests.

The Reconstruction Manager owns:

* loading stored session records
* validating required files
* mapping local/device time to session time
* checking timestamp continuity
* checking dropped or missing samples
* producing validation reports
* producing export-ready tables

Reconstruction does not own:

* acquisition
* device control
* protocol execution
* neuroscience analysis
* silent rewriting of raw records

**Rationale:**
Reconstruction must be auditable and repeatable from stored records.

**Consequence:**
Reconstruction outputs should be stored separately from raw records.

---

## Decision 030: Device outputs must be mappable to NWB

**Status:** Accepted

Framework Device Adapters are not NWB Device objects.

However, Device Adapters must provide enough metadata and output schema information for later NWB export.

Conceptually:

```text
Framework Device Adapter
    -> stored device metadata + streams/events
    -> NWB Exporter
    -> NWB Device / TimeSeries / BehavioralEvents / related objects
```

**Rationale:**
NWB should shape the internal data model where appropriate, but should not constrain acquisition internals too early.

**Consequence:**
Device metadata, stream schemas, and event schemas should be designed so that later NWB export is natural.

---

## Decision 031: The Controller sends protocol intent; the Acquisition Node records execution

**Status:** Accepted

The Controller owns the protocol plan.

The Acquisition Node executes time-critical protocol actions locally and records what actually happened.

Commands and outcomes must both be recorded.

Example:

```text
reward_commanded at 120.500 s
valve_opened at 120.503 s
valve_closed at 120.553 s
```

**Rationale:**
Scientific interpretation depends on what actually happened, not only what was intended.

**Consequence:**
Protocol commands, device actions, and device outcomes should be stored as timestamped events.

---

## Decision 032: Session lifecycle states

**Status:** Accepted

The Phase 1 session lifecycle is:

```text
created
initialized
running
stopping
completed
failed
aborted
```

Definitions:

* `created`: session identity exists.
* `initialized`: configuration, devices, storage, ingestor, protocol, and timing source are prepared.
* `running`: acquisition has started and session time is running.
* `stopping`: cleanup/finalization is in progress.
* `completed`: session ended normally.
* `failed`: session ended because of unexpected failure.
* `aborted`: session ended because of intentional early termination.

**Rationale:**
This lifecycle is simple but still separates preparation, acquisition, cleanup, and final status.

**Consequence:**
A failed or aborted session is still a session and must be preserved.

---

## Decision 033: State transitions require readiness checks

**Status:** Accepted

State transitions are allowed only when required conditions are satisfied and recorded.

Examples:

`created -> initialized` requires:

* session ID exists
* configuration exists
* selected devices declared
* storage location declared
* protocol plan declared

`initialized -> running` requires:

* required devices connected
* required devices configured
* Ingestor reachable or local buffering enabled
* storage ready
* Synchronization Manager ready
* session time source ready
* device schemas declared
* `session_start` event can be recorded

`running -> experiment_start event` requires:

* acquisition is already running
* session clock is running
* required streams/events are being recorded or explicitly marked unavailable
* protocol executor ready

**Rationale:**
Experiments should not begin until acquisition is truly running and timing is available.

**Consequence:**
Readiness checks should be recorded so that later reconstruction can determine whether a session began under valid conditions.

---

## Decision 034: Cleanup is mandatory and preserves evidence

**Status:** Accepted

Every session must enter a cleanup/finalization phase during `stopping`, regardless of whether it ends normally, fails, or is aborted.

Cleanup includes:

* stopping devices
* flushing buffers
* closing files
* finalizing manifests
* writing final session status
* recording unresolved errors
* releasing hardware resources
* disconnecting from the Ingestor if needed

Cleanup does not mean:

* deleting bad data
* hiding partial files
* making a failed session look successful

**Rationale:**
Real experiments fail. The system must preserve evidence rather than erase it.

**Consequence:**
Final state is assigned after cleanup:

```text
normal stop   -> completed
fatal error   -> failed
user abort    -> aborted
```

---

## Decision 035: Failure is recorded as data

**Status:** Accepted

Failures must be recorded as timestamped events.

Failure categories are:

* warning
* recoverable failure
* fatal failure

Recommended behavior:

* warning: record and continue
* recoverable failure: record, attempt recovery, continue if safe
* fatal failure: record, stop acquisition, preserve partial session

**Rationale:**
Failure information is necessary for debugging and for determining whether a session is scientifically valid.

**Consequence:**
A failed session should contain all data up to failure, all available timing records, and explicit failure records.

---

## Decision 036: Controller failure should not automatically stop acquisition

**Status:** Accepted

Once acquisition has started, the Acquisition Node should be able to continue, complete, or safely stop without requiring the GUI/Controller to remain alive.

**Rationale:**
The GUI/Controller is a command authority, not the acquisition runtime or timing authority.

**Consequence:**
The Acquisition Node must preserve session records even if communication with the Controller is lost.

---

# Accepted Architectural Principles

The following principles summarize the accepted decisions so far.

1. The GUI is a client.
2. The Controller and GUI are conceptually separate.
3. The Jetson is a hardware-facing Acquisition Node.
4. The Jetson is not the whole-system overlord.
5. The Ingestor is an independent architectural entity.
6. The Ingestor does not define scientific time.
7. Session time has one owner: the Synchronization Manager.
8. Phase 1 session time may use Jetson monotonic time.
9. Hardware timing should remain possible later.
10. Devices may have local clocks.
11. Local device time is not session time.
12. Every sample, row, frame, or event must have session time or enough information to reconstruct it.
13. Timing records are part of the raw scientific record.
14. Ingest time is for debugging, not scientific alignment.
15. Offline reconstruction is mandatory.
16. Device Adapter and Device Manager are separate concepts.
17. Devices should expose capabilities through a common conceptual interface.
18. Configuration must be explicit and propagated.
19. Human-readable intermediate outputs are required.
20. NWB compatibility should shape the data model, but NWB is not the only storage/debugging format.
21. Utilities must not hide domain logic.
22. Plotting is allowed only for framework validation and debugging.
23. The final source structure is not yet frozen.
24. Parquet is the preferred default storage format for intermediate records.
25. Raw records are stored first; reconstruction and export create derived records later.
26. Reconstruction must never silently modify raw records.
27. Device outputs must be mappable to NWB.
28. The Controller sends protocol intent; the Acquisition Node records protocol execution and outcomes.
29. The session lifecycle is: created → initialized → running → stopping → completed/failed/aborted.
30. State transitions require readiness checks.
31. Experiments cannot begin until acquisition is confirmed running.
32. Cleanup is mandatory for every session termination path.
33. Cleanup preserves evidence and never hides failures.
34. Failures are recorded as timestamped data.
35. Controller failure should not automatically stop acquisition.
36. Human-readable intermediate outputs are required.
37. Utilities must not become a junk drawer for domain logic.
38. Plotting is allowed only for framework validation and debugging.
39. This repository is for synchronization and acquisition, not GUI development or neuroscience analysis.
40. Architectural decisions are documented before implementation begins.

---

# Open Decisions Not Yet Resolved

The following decisions remain open and should be resolved before writing the final architecture document.

## Session model

* What are the exact session lifecycle states?
* What makes a session valid?
* What makes a session failed-but-reconstructable?
* What is the session identity format?
* What must be present in a session manifest?

## Stream model

* What is a stream?
* How are sampled streams represented?
* How are frame-based streams represented?
* How are sparse event streams represented?
* How are command streams represented?

## Event model

* What is an event?
* Are protocol commands stored as events?
* Are device state changes stored as events?
* Are errors stored as events?
* Are rewards, licks, tones, and camera triggers all events?

## Synchronization model

* What is a synchronization anchor?
* What exact records are required to map local time to session time?
* How is drift represented?
* How is timestamp uncertainty represented?
* What happens if sync records are missing or inconsistent?

## Storage model

* What is the session folder structure?
* What files are mandatory?
* What file formats are acceptable for intermediate storage?
* What is written online versus reconstructed offline?
* What makes a stored session complete?

## Reconstruction model

* What component performs reconstruction?
* What are the outputs of reconstruction?
* Does reconstruction write new files or generate views?
* How are reconstruction errors reported?

## Multi-node acquisition

* Can multiple Acquisition Nodes participate in the same session?
* If yes, who coordinates them?
* How is session time shared across nodes?
* Is this Phase 1 or future architecture?

## Protocol model

* What does the Controller send to the Acquisition Node?
* What does the Acquisition Node execute locally?
* What protocol events must be recorded?
* How much protocol logic belongs in this repository?

## Device contract

* What minimum methods or behaviors must every Device Adapter support?
* How are device capabilities declared?
* How are optional capabilities represented?
* What must be tested before a device is accepted?

## Configuration model

* Should configuration be stored as classes, JSON, YAML, or another format?
* Which configuration is user-facing?
* Which configuration is internal?
* How are defaults declared without being hidden?

## Failure and recovery

* What happens if a device disconnects mid-session?
* What happens if the Ingestor disconnects?
* What happens if storage fails?
* What happens if timing records are incomplete?
* Can a partial session be marked scientifically unusable but still preserved?


# Changes to Existing Decisions!!!!!

## Decision 004: The Ingestor is a separate architectural entity

Replace:

* receiving data packets and events

with:

* receiving records from Acquisition Nodes

Add:

Records may contain:

* data
* events
* timing records
* file references
* deferred-transfer records

Add after the ownership section:

The Ingestor is responsible for creating a complete session record.

The Ingestor does not require all raw bytes to pass through it during acquisition.

Large files may remain on acquisition machines during acquisition and be transferred after session completion.

---

## Decision 011: Timing records are part of the raw scientific record

Add after the timing-record list:

Whenever possible, timestamps should be stored directly with the stream or event they describe.

The timing subsystem is reserved for timing-specific records that are not naturally part of a stream or event.

Examples include:

* session clock declarations
* synchronization records
* drift records
* local-to-session mapping records

---

## Decision 029: Reconstruction writes derived outputs and does not silently modify raw records

Replace:

* producing export-ready tables

with:

* producing validation reports
* producing export-ready records

Add:

For Phase 1, reconstruction is primarily a validation and assembly process rather than a large transformation pipeline.

Its primary purpose is to verify that a stored session is complete, internally consistent, and exportable.

---

# New Decisions

## Decision 037: Session completion is independent of NWB export

**Status:** Accepted

A Session is complete when acquisition has ended, cleanup has completed, and the raw session record has been finalized.

NWB export is a post-session operation.

NWB export status does not determine Session completion.

**Rationale:**
Large files may require transfer, conversion, validation, or upload after acquisition has ended.

These operations should not block future sessions.

**Consequence:**
Multiple sessions may be acquired while previous sessions are awaiting NWB export.

---

## Decision 038: The Ingestor manages records, not necessarily all raw bytes online

**Status:** Accepted

The Ingestor is responsible for creating a complete session record.

Not all device data must be transferred through the Ingestor during acquisition.

Some devices may provide:

* full records during acquisition
* timing records during acquisition
* file references during acquisition
* large files after acquisition

**Rationale:**
Some acquisition systems generate files that are impractical to transfer in real time.

**Consequence:**
The architecture must support both online records and deferred file-transfer workflows.

---

## Decision 039: Timing belongs primarily with the data records it describes

**Status:** Accepted

Streams and Events should contain their own Session Time whenever possible.

Examples:

* frame timestamps
* sample timestamps
* event timestamps

Separate timing records should only be used for timing-specific information that is not naturally part of a stream or event.

**Rationale:**
The most useful location for timing information is alongside the data it describes.

**Consequence:**
Session reconstruction and NWB export should not require separate timestamp lookups for normal records.

---

## Decision 040: Raw acquisition records and NWB exports have separate lifecycles

**Status:** Accepted

Raw acquisition records and NWB exports are separate storage products.

Recommended structure:

```text
raw/
    session_<session_id>/

nwb/
    session_<session_id>/
```

Raw records are working acquisition records.

NWB files are long-term scientific exports.

**Rationale:**
Raw records and NWB exports have different lifecycles, storage requirements, and deletion policies.

**Consequence:**
Experimenters may retain, archive, upload, or delete raw records independently of NWB exports.

---

## Decision 041: Storage capacity must be validated before acquisition begins

**Status:** Accepted

Before acquisition begins, the system must verify that participating machines have sufficient storage capacity.

Examples:

* Acquisition Node
* Ingestor machine
* Microscope PC
* CaBMI PC
* other acquisition systems

**Rationale:**
Running out of storage during acquisition can invalidate a session and is often preventable.

**Consequence:**
Storage-capacity checks are part of session initialization readiness.

---

# Accepted Architectural Principles

Append the following principles:

41. Session completion is independent of NWB export.
42. The Ingestor manages records, not necessarily all raw bytes online.
43. Timing belongs primarily with the data records it describes.
44. Raw acquisition records and NWB exports have separate lifecycles.
45. Storage capacity must be validated before acquisition begins.

---

# Remove

Delete the entire section:

```text
# Open Decisions Not Yet Resolved
```

and everything beneath it.

Open questions now belong exclusively in `open_questions.md`.

