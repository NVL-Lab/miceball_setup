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

* receiving records from Acquisition Nodes. Records may contain:
	-data
	-events
	-timing records
	-file references
	-deferred-transfer records
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

The Ingestor is responsible for creating a complete session record.
The Ingestor does not require all raw bytes to pass through it during acquisition.
Large files may remain on acquisition machines during acquisition and be transferred after session completion.

**Rationale:**
To separate ingestion, timing, and storage.

**Consequence:**
Ingestor arrival time must never be treated as the scientific timestamp of a sample or event.

---

## Decision 005: Batch transfer is allowed, but does not define timing

**Status:** Accepted

Acquisition Nodes may transmit data in batches. UPDATE: Acquisition Nodes should transmit continuous acquisition data in batches. Individual row transport remains acceptable for sparse events or debugging. Each row must retain its own timing information before batching.

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

Session time is the shared time within a Session used to align streams, events, Experiments, and timing records.

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

Whenever possible, timestamps should be stored directly with the stream or event they describe.
The timing subsystem is reserved for timing-specific records that are not naturally part of a stream or event.
Examples include:

* session clock declarations
* synchronization records
* drift records
* local-to-session mapping records

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

Terminology update: Decision 094 names the larger scientific plan a `Project`.
An `Experiment` is a bounded scientific or protocol activity inside a Session.

**Rationale:**
One Project may contain many Sessions across days. The framework needs the Session to be the concrete acquisition and reconstruction unit.

**Consequence:**
Session records should contain all data, events, timing records, configuration, and manifests needed to reconstruct that run.

---

## Decision 026: Session start and experiment start are different

**Status:** Accepted

Terminology update: under Decision 094, Session start means the Session evidence container and Acquisition Runtime begin.

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

This is a future storage direction. Phase 1 validates the StorageManager
boundary with the JSONL backend accepted in Decision 071; that JSONL validation
does not settle the final Parquet schemas or storage layout.

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
* producing validation reports
* producing export-ready records

Reconstruction does not own:

* acquisition
* device control
* protocol execution
* neuroscience analysis
* silent rewriting of raw records

For Phase 1, reconstruction is primarily a validation and assembly process rather than a large transformation pipeline.
Its primary purpose is to verify that a stored session is complete, internally consistent, and exportable.

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

## Decision 41: Session completion is independent of NWB export

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

## Decision 042: The Ingestor manages records, not necessarily all raw bytes online

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

## Decision 043: Timing belongs primarily with the data records it describes

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

## Decision 044: Raw acquisition records and NWB exports have separate lifecycles

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

## Decision 045: Storage capacity must be validated before acquisition begins

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


----

## Decision 046: Software mapping should start with guardrails, not a full skeleton

**Status:** Accepted

Architectural concepts may have more than one software representation.

Some concepts exist as runtime objects or services during acquisition.
Some concepts exist as persistent records after or during acquisition.
Some concepts require both.

The implementation should begin with a minimal vertical slice rather than a complete pre-planned source skeleton.

**Accepted rules:**

* A Session is not just a folder.
* The runtime Session represents lifecycle state and session control.
* The stored Session Record represents the evidence produced by the session.
* A Device has runtime lifecycle state.
* Device Adapters handle device-specific communication.
* The Device Manager coordinates device lifecycle.
* Stream rows and Event rows should contain Session Time directly whenever possible.
* Event records must include enough information to distinguish event category, type, and source.
* Important behavior must be controlled by explicit configuration, not hidden lower-level defaults.

**Implementation stop rule:**

If implementation requires deciding the meaning, boundary, or ownership of any of the following concepts, implementation must stop and request architectural clarification:

* Session
* Session Record
* Stream
* Event
* Timing Record
* Configuration
* Device
* Device Adapter
* Device Manager
* Synchronization Manager
* Ingestor
* Storage Manager
* Reconstruction Manager

**Rationale:**

The architecture should prevent dangerous hidden assumptions without overengineering a complete software structure before the first working vertical slice exists.

**Consequence:**

Codex and other implementation agents should implement only what the first vertical slice requires. They should not create speculative skeletons, plugin systems, generic factories, or unused abstraction layers.  

---

## Decision 047: Configuration declares intended devices before live adapters exist

**Status:** Accepted

Configuration declares intended devices before any live hardware connection exists.

A selected device is represented first as a `DeviceDeclaration` in `SessionConfig`.

`DeviceDeclaration` is a persistent/config concept with:

* device ID
* device type
* enabled flag
* required flag
* declared capabilities

Device Adapters create and control live device connections later.

The Device Manager coordinates live device lifecycle later.

**Rationale:**
Session configuration must explicitly state which devices are intended for the session without implying that hardware has already been discovered, connected, configured, or started.

**Consequence:**
Session initialization may validate declared device configuration fields, but it must not validate live hardware, create adapters, or introduce a Device Manager.

---

## Decision 048: Minimum live Device Adapter interface proves manageability

**Status:** Accepted

A live Device Adapter proves that one device can be managed at runtime.

It does not yet need to produce scientific data.

The minimum live `DeviceAdapter` interface is:

* `device_id`
* `device_type`
* `declared_capabilities`
* `initialize(config)`
* `check_ready()`
* `start()`
* `stop()`
* `shutdown()`
* `get_status()`

The minimum interface must not include:

* `read_sample`
* `read_frame`
* `emit_event`
* `write_file`
* `send_command`
* `trigger`
* `calibrate`
* `reconnect`

`DeviceDeclaration` is configuration and persistent intent.

`DeviceAdapter` is live runtime control for one device type.

The Device Manager will later coordinate many adapters.

Session should not call hardware-specific methods.

**Rationale:**
The first live-device slice should prove lifecycle manageability without pretending that acquisition, streams, events, commands, or hardware-specific behavior have been designed.

**Consequence:**
Device Adapter lifecycle status and readiness may be represented now, but scientific data production, hardware communication details, and multi-adapter coordination remain out of scope.

---

## Decision 049: DeviceManager receives already-created adapters

**Status:** Accepted

DeviceManager receives already-created DeviceAdapters.

DeviceManager is responsible for:

* holding adapters
* calling adapter lifecycle methods
* aggregating readiness results
* collecting status summaries
* returning lifecycle results

DeviceManager is not responsible for:

* creating adapters
* looking up adapters by device type
* registering adapter classes
* discovering plugins
* interpreting device-specific configuration

Session owns selected DeviceDeclarations.

DeviceManager owns live DeviceAdapters.

The connection between DeviceDeclarations and concrete DeviceAdapters is intentionally deferred.

**Rationale:**
The first device lifecycle slice should validate lifecycle coordination without forcing architectural decisions about adapter factories, registration systems, plugin discovery, or declaration-to-adapter binding.

**Consequence:**
DeviceManager can be implemented and tested using already-created fake adapters. Adapter creation remains a future architectural decision.

---

## Decision 050: DeviceManager v1 empty-manager and failure policy

**Status:** Accepted

An empty DeviceManager is invalid in v1.

DeviceManager must be created with at least one already-created DeviceAdapter.

DeviceManager catches adapter lifecycle/readiness exceptions, records them in lifecycle/readiness result objects, and continues applying the operation to remaining adapters.

DeviceManager does not decide whether a failure is session-fatal.

Fatal/nonfatal interpretation is deferred to later session readiness or policy logic.

For v1, initialize_all(config) passes the supplied config object through unchanged to each adapter.

Per-device initialization configuration is deferred.

**Rationale:**

DeviceManager v1 exists to coordinate live participating adapters. A manager with zero adapters is more likely to indicate wiring or configuration error than a meaningful ready state.

Continuing across adapters preserves evidence from all devices and avoids one adapter failure hiding the status of others.

**Consequence:**

Readiness aggregation no longer relies on all([]).

Partial failures are returned as explicit result objects.

Session-level interpretation of required/optional device failure remains a future decision.

---

## Decision 051: Session initialization may use DeviceManager readiness summaries

**Status:** Accepted

Session owns DeviceDeclarations, lifecycle state, and recorded readiness summaries.

DeviceManager owns already-created live DeviceAdapters, adapter lifecycle calls, and adapter readiness aggregation.

During Session.initialize(), Session may receive or be given a DeviceManager readiness summary.

Session may use that summary to decide whether initialization readiness passes.

Session must not own DeviceAdapters.

Session must not call DeviceAdapter methods directly.

Session must not create DeviceManager.

Session must not create DeviceAdapters.

Session must not bind DeviceDeclarations to DeviceAdapters.

For this slice, readiness summary records must include:

* device_id
* required
* ready
* reason
* capabilities_available

A required device that is not ready causes Session.initialize() to fail.

An optional device that is not ready is recorded but does not block Session.initialize().

The connection between DeviceDeclarations and concrete DeviceAdapters remains deferred.

**Rationale:**

This is the smallest boundary between Session and live device lifecycle. It allows Session initialization to depend on device readiness evidence without giving Session ownership of hardware communication or adapter lifecycle.

**Consequence:**

Session can record readiness evidence and gate initialization on required devices, while DeviceManager remains the owner of live adapters.

---

## Decision 052: DeviceManager and Session use one readiness record contract

**Status:** Accepted

The readiness record produced by DeviceManager and the readiness record consumed and recorded by Session are the same contract.

DeviceManager produces readiness records.

Session consumes and records readiness records.

Session does not transform readiness records into a separate Session-only readiness type.

Session does not reinterpret adapter readiness beyond required-device gating during initialize.

The shared readiness record must include:

* device_id
* required
* ready
* reason
* capabilities_available

**Rationale:**

The first Session-DeviceManager bridge should be a real vertical slice, not two parallel readiness schemas.

Using one readiness record avoids an unnecessary translation layer and keeps the boundary simple.

**Consequence:**

DeviceManager.check_readiness() output can be passed directly to Session.initialize().

Tests must demonstrate actual DeviceManager-to-Session compatibility.

---

## Decision 053: Live DeviceAdapters are explicitly constructed outside DeviceManager v1

**Status:** Accepted

`DeviceDeclaration` declares intended device participation.

`DeviceAdapter` is the live runtime object that controls one device.

`DeviceManager v1` receives already-created live `DeviceAdapter` instances and coordinates their lifecycle.

A `DeviceDeclaration` does not automatically create a `DeviceAdapter`.

`DeviceManager` does not create adapters.

`DeviceManager` does not resolve `device_type` into an adapter class.

`DeviceManager` does not discover devices.

`DeviceManager` does not use factories, registries, plugin systems, service locators, or hardware discovery.

For now, the bridge from declaration to live adapter is explicit manual construction by caller/test/user code:

```python
declarations = [...]
adapters = [...]
manager = DeviceManager(adapters)
```

The caller is responsible for constructing adapters with the configuration needed by that adapter.

Only information needed for live adapter identity and lifecycle/readiness should cross into the adapter.

Declaration-only information remains in `DeviceDeclaration` and `SessionConfig`.

**Rationale:**

This preserves the accepted ownership boundaries:

* `Session` owns `DeviceDeclarations`, session lifecycle, and readiness evidence.
* `DeviceAdapter` owns one live device.
* `DeviceManager` owns live adapters only after they have already been constructed.

Creating adapters inside `DeviceManager` would force premature decisions about factories, registries, plugin systems, hardware discovery, and declaration-to-adapter binding.

**Consequence:**

The first implementation keeps adapter construction explicit and boring.

Future adapter-creation architecture may be considered only after multiple real adapters exist and the repeated construction pattern proves a need.

---

## Decision 055: DeviceAdapter receives copied declaration fields, not DeviceDeclaration

**Status:** Accepted

A `DeviceAdapter` receives only the declaration fields required for live device participation.

A `DeviceAdapter` does not receive, retain, or depend on a full `DeviceDeclaration` object.

Allowed to cross from `DeviceDeclaration` into `DeviceAdapter` v1:

```text
device_id
device_type
declared_capabilities
required
```

Declaration-only fields remain outside the adapter:

```text
enabled
```

`enabled` is a configuration/selection concern.

A disabled device should normally not become a live adapter.

The intended boundary is:

```text
DeviceDeclaration
    persistent/session intent

caller code
    filters enabled declarations
    manually constructs adapters from allowed fields

DeviceAdapter
    live runtime participant

DeviceManager
    manages live adapters
```

**Rationale:**

`DeviceDeclaration` is a persistent configuration concept.

`DeviceAdapter` is a live runtime concept.

Passing a full `DeviceDeclaration` into a `DeviceAdapter` would blur the boundary between session configuration and live device control.

Using copied fields preserves separation of responsibilities and keeps adapter construction explicit.

**Consequence:**

A `DeviceAdapter` is not a wrapper around `DeviceDeclaration`.

Adapter construction remains explicit caller code.

Future adapter-construction mechanisms, if any, should continue to preserve this boundary.

---

## Decision 056: DeviceManager does not validate declaration-to-adapter matching in v1

**Status:** Accepted

`DeviceManager` validates and coordinates live `DeviceAdapter` lifecycle, readiness, and status.

`DeviceManager` does not validate whether live adapters match `DeviceDeclaration` records.

For v1:

```text
DeviceManager receives adapters.
DeviceManager trusts that caller code supplied the intended adapters.
DeviceManager does not know DeviceDeclarations.
```

---

## Decision 057: Ingestor owns accepted-record handoff to StorageManager

**Status:** Accepted

The Ingestor owns the handoff of accepted records to the Storage Manager.

Tests and caller code should not manually pass the same accepted records to both the Ingestor and the Storage Manager as independent steps.

Minimum boundary:

```text
DeviceManager
    collects records

Ingestor
    receives DeviceRecordCollection objects
    accepts records
    preserves accepted records unchanged
    forwards accepted records to StorageManager

StorageManager
    receives accepted records
    stores them unchanged
    exposes stored records for verification
```

The Ingestor and Storage Manager remain separate components.

The Storage Manager remains responsible for storing accepted records.

For v1, storage may remain in memory and does not define:

* file format
* folder layout
* Parquet schema
* NWB mapping
* session record structure
* manifest format
* reconstruction behavior
* full stream schema

**Rationale:**

The first acquisition-to-storage path should be a real framework path rather than a test manually coordinating independent components.

Keeping the Ingestor responsible for forwarding accepted records preserves the architectural boundary while avoiding premature storage design.

**Consequence:**

An in-memory Ingestor may be constructed with an optional in-memory Storage Manager.

When the Ingestor receives accepted records, it forwards those same records to storage without transforming records, assigning timestamps, or defining persistent schemas.

---

## Decision 058: The glossary is the authoritative source of architectural terminology

**Status:** Accepted

The repository glossary (`docs/glossary.md`) is the authoritative source for the definitions of architectural concepts and terminology.

All architecture discussions, implementation discussions, documentation, tests, and code should use the accepted glossary terms consistently.

New architectural concepts should not be introduced implicitly during implementation. If a new concept is required, it should first be discussed and, if accepted, added to the glossary before becoming part of the architecture.

**Principle**

One concept. One definition. One name.

**Rationale**

A shared vocabulary prevents ambiguity between architecture discussions, implementation, documentation, and AI coding agents. Consistent terminology reduces duplicate concepts, conflicting names, and architectural drift over time.

**Consequences**

* `docs/glossary.md` is the authoritative reference for architectural terminology.
* Existing terms should be reused rather than creating synonyms.
* New architectural terms should be added to the glossary before they are adopted by the implementation.
* Architecture, documentation, tests, and code should use the accepted glossary terminology consistently.


---

## Decision 059: Ingestor receives transferable acquisition record envelopes

**Status:** Accepted

The boundary between acquisition and ingestion is not a live `DeviceManager` object calling a live `Ingestor` object.

The boundary is:

```text
Acquisition side emits record messages.
Ingestor side receives record messages.
```

`DeviceManager` and `Ingestor` should not need to import or share live objects.

They share a minimal transferable acquisition record envelope.

Minimum envelope fields:

```text
session_id
source_device_id
record_kind
records
```

Each row inside `records` must contain:

```text
session_time
```

Ingestor v1 receives envelopes and creates separate ingest audit evidence:

```text
ingest_order
ingest_received_at
accepted
reason
```

Accepted envelopes are forwarded to `StorageManager`.

Rows are not mutated by the Ingestor.

`source_device_id` and row `session_time` are preserved unchanged.

This decision supersedes the object-sharing interpretation of Decision 057 for the DeviceManager-to-Ingestor boundary.

**Rationale:**

Acquisition and ingestion may later run in different processes or on different computers.

A transferable envelope keeps the boundary explicit without deciding network transport, serialization protocol, file format, session folder layout, or final session record structure.

**Consequence:**

Ingestor tests should pass through the envelope shape.

The in-memory workflow may still run in one Python process, but the Ingestor receives acquisition record envelopes rather than adapter-owned or manager-owned collection objects.

Storage v1 stores accepted envelopes unchanged in memory for verification.

---

## Decision 060: AcquisitionRecordEnvelope is plain-data round-trippable

**Status:** Accepted

`AcquisitionRecordEnvelope` must be convertible to and from a JSON-like plain-data form.

Minimum round trip:

```text
AcquisitionRecordEnvelope
    -> dict / JSON-like plain-data form
    -> AcquisitionRecordEnvelope
```

The plain-data form contains only:

* strings
* numbers
* booleans
* `None`
* lists
* dicts

The plain-data form does not include live runtime objects.

The round trip must preserve:

* `session_id`
* `source_device_id`
* `record_kind`
* `records`
* row `session_time`

The round trip does not define:

* network transport
* serialization protocol
* socket communication
* Redis
* files
* file format
* folder layout
* Parquet
* NWB
* session record structure
* manifest format
* reconstruction
* real devices
* full stream schema

**Rationale:**

Acquisition Nodes and Ingestors may later be different processes or computers.

A plain-data envelope round trip proves the boundary can cross process-like seams without sharing live `DeviceAdapter`, `DeviceManager`, or `DeviceRecordCollection` objects.

**Consequence:**

Acquisition-side code can create an envelope, convert it to plain data, and ingest-side code can reconstruct an envelope from that plain data before validation and storage handoff.

Rows remain unchanged by the envelope round trip.

---

## Decision 061: StorageManager v1 proves in-memory persistence boundary behavior

**Status:** Accepted

StorageManager v1 proves persistence boundary behavior, not the final storage format.

Minimum behavior:

```text
StorageManager v1
    receives accepted ingest records/envelopes
    keeps them unchanged
    exposes small readback/inspection API
```

For v1, `InMemoryStorageManager` stores accepted `AcquisitionRecordEnvelope` objects unchanged in memory.

It preserves:

* `session_id`
* `source_device_id`
* `record_kind`
* `records`
* row `session_time`

Ingest audit remains separate from stored device records.

StorageManager v1 may expose small inspection methods for:

* all stored envelopes
* stored envelopes for a given `session_id`
* stored envelopes for a given `source_device_id`

This decision does not define:

* files
* Parquet
* folder layout
* session manifest
* reconstruction
* Session integration
* NWB
* networking
* transport protocol
* serialization protocol
* full stream schema
* final Session Record structure

**Rationale:**

Before wiring storage readiness into Session, the framework needs a small, inspectable proof that accepted records become retained session evidence.

In-memory readback validates the storage boundary while deferring final persistence design.

**Consequence:**

`InMemoryStorageManager` remains intentionally boring.

It supports readback and filtering by existing envelope fields without mutating rows or interpreting stream schemas.

---

## Decision 062: Session initialization consumes service readiness summaries

**Status:** Accepted

Session readiness gating consumes readiness summaries from services.

It does not inspect service internals.

Minimum shared service readiness result:

```text
component_id
component_type
required
ready
reason
```

For Ingestor:

```text
component_id: ingestor
component_type: ingestor
required: true
ready: true/false
reason: ...
```

For StorageManager:

```text
component_id: storage
component_type: storage_manager
required: true
ready: true/false
reason: ...
```

`InMemoryIngestor` and `InMemoryStorageManager` may expose `check_ready()` methods that return this shared service readiness record.

`Session.initialize()` may receive service readiness records.

`Session.initialize()` records supplied service readiness records.

`Session.initialize()` fails if any required service readiness record has `ready=False`.

Session must not inspect:

* how Ingestor accepts records
* how StorageManager stores or reads back records
* storage internals
* ingest audit internals

No records need to flow during initialization.

This service readiness contract is for framework services such as Ingestor and StorageManager. It does not replace the live device readiness contract.

**Rationale:**

Session initialization should gate on readiness evidence produced by participating services without coupling Session to their internal behavior.

This keeps service readiness narrow while preserving the existing device readiness boundary.

**Consequence:**

Session can record and gate on service readiness summaries before acquisition records flow.

Final readiness framework, service discovery, storage capacity validation, reconstruction readiness, and multi-node readiness remain deferred.

---

## Decision 063: Acquisition-side code creates transferable record envelopes

**Status:** Accepted

`DeviceManager` produces acquisition-side `DeviceRecordCollection` objects.

Before records cross the boundary to the `Ingestor`, acquisition-side caller code wraps each collection in an `AcquisitionRecordEnvelope`.

The ownership boundary is:

```text
DeviceManager
    collects DeviceRecordCollection

acquisition-side caller
    creates AcquisitionRecordEnvelope

Ingestor
    receives AcquisitionRecordEnvelope
```

`DeviceManager` does not:

* create `AcquisitionRecordEnvelope`
* know the ingest message format
* know transport concerns

`Ingestor` does not:

* receive `DeviceRecordCollection`
* know live adapter collection details
* know `DeviceManager`

`Session` does not:

* transform acquisition records
* create acquisition envelopes

No dedicated `EnvelopeBuilder` component exists in Phase 1.

Envelope creation is explicit acquisition-side caller code until repeated real implementations demonstrate the need for a shared abstraction.

**Rationale:**

The acquisition/ingest boundary represents a transferable message contract rather than shared runtime objects.

Keeping envelope creation outside both `DeviceManager` and `Ingestor` preserves their responsibilities while avoiding the premature introduction of another architectural component.

**Consequence:**

Acquisition-side code is responsible for converting runtime record collections into transferable envelopes before they cross into the ingestion boundary.

---

## Decision 064: SynchronizationManager owns Session Time

**Status:** Accepted

The framework owns Session Time through a `SynchronizationManager`.

`Session Time` is the shared temporal reference for all acquisition records belonging to a session.

The ownership boundary is:

```text
SynchronizationManager
    owns Session Time

acquisition-side caller
    obtains Session Time
    attaches session_time to acquisition records

AcquisitionRecordEnvelope
    carries timestamped records

Ingestor
    receives timestamped records

StorageManager
    stores timestamped records
```

`SynchronizationManager` is responsible for:

* starting the session clock
* reporting readiness
* providing the current Session Time

`SynchronizationManager` does not:

* collect acquisition records
* own device lifecycle
* own session lifecycle
* perform ingestion
* perform storage

`DeviceAdapter` does not:

* invent Session Time
* own the session clock

For Phase 1 fake acquisition, adapters may produce untimestamped payload rows. The acquisition-side caller attaches `session_time` obtained from the `SynchronizationManager` before creating an `AcquisitionRecordEnvelope`.

`Ingestor` does not:

* assign timestamps
* modify timestamps

`StorageManager` does not:

* assign timestamps
* modify timestamps

`Session` does not:

* assign timestamps to acquisition records

This decision intentionally excludes:

* hardware synchronization
* synchronization anchors
* drift estimation
* clock correction
* timestamp uncertainty
* multi-node synchronization

These remain future architectural work.

**Rationale:**

Session Time is a framework concern rather than a device concern.

Separating timestamp ownership from adapters ensures that all acquisition records share a common temporal reference while preserving clear ownership boundaries between acquisition, synchronization, ingestion, and storage.

**Consequence:**

Before acquisition records cross into the ingestion boundary, acquisition-side code is responsible for obtaining the current Session Time from the `SynchronizationManager` and attaching it to each record.


---


## Decision 065: Synchronization Manager v1 owns Phase 1 Session Time

**Status:** Accepted

Session Time is the session-scoped monotonic scientific timebase for one Session.

For Phase 1:

```text
Session Time = elapsed seconds since acquisition session_start
```

The `session_start` acquisition event defines:

```text
session_time_s = 0.0
```

Session Time is:

* relative
* monotonic
* session-scoped
* stored in seconds
* owned by the Synchronization Manager
* based on Jetson monotonic time in Phase 1

Session Time is not:

* wall-clock time
* GUI time
* Ingestor arrival time
* Device Local Time
* network/message timestamp

## Scientific guarantee

For Phase 1, Session Time guarantees that all streams and events from the Acquisition Node are timestamped against the same monotonic session clock.

It does not yet guarantee:

* hardware-level synchronization
* sub-millisecond precision
* multi-node clock alignment
* drift correction across independent machines

Millisecond-level timing is sufficient for Phase 1 because the most timing-critical signal is currently approximately 30 Hz.

## Relation to device clocks

Devices may produce local timestamps, counters, frame indices, or local clock values.

These should be preserved when available, but:

```text
Device Local Time != Session Time
```

If both exist, both should be stored.

## Lifecycle relationship

Session Time starts when acquisition starts, not when the behavioral protocol starts.

```text
session_start       session_time_s = 0.0
experiment_start    timestamped event inside Session
experiment_end      timestamped event inside Session
session_end         final acquisition time
```

Warmup, stabilization, calibration, and buffering may therefore be recorded before the behavioral protocol begins.

## Software boundary

The Synchronization Manager owns Session Time.

The Acquisition Node starts Session Time by asking the Synchronization Manager to start the session clock when acquisition enters `running`.

Conceptually:

```text
Controller sends start_session intent
Acquisition Node passes readiness checks
Synchronization Manager starts Session Time
session_start event is recorded at session_time_s = 0.0
Acquisition begins
```

Components do not invent Session Time.

Session Time is provided to acquisition components through the Acquisition Node runtime.

Conceptually:

```text
Device Adapter -> Acquisition Node runtime -> Synchronization Manager -> session_time_s
```

For Phase 1, adapters may receive session timestamps from the acquisition runtime when records are created.

## Out of scope for v1

Synchronization Manager v1 does not solve:

* hardware synchronization
* drift estimation
* drift correction
* synchronization anchors
* multi-node clock alignment
* timestamp uncertainty modeling
* external time references
* transport timing

## Principle

Synchronization Manager v1 owns Session Time; it does not solve the full synchronization problem.

## Consequences

* Adapters do not assign or invent Session Time.
* Ingestor does not assign or invent Session Time.
* Storage Manager does not assign or invent Session Time.
* Session coordinates lifecycle but does not define clock semantics.
* Acquisition-side runtime obtains Session Time from the Synchronization Manager.
* Every stream sample, frame, or event must have Session Time or enough stored information to reconstruct it.


---

## Decision 066: Session start and stop are acquisition event records

**Status:** Accepted

`session_start` and `session_stop` are ordinary acquisition event records.

Minimum representation:

```text
record_kind: event
source_device_id: acquisition_node
```

`session_start`:

```python
{
    "event_category": "session_lifecycle",
    "event_type": "session_start",
    "session_time_s": 0.0,
}
```

`session_stop`:

```python
{
    "event_category": "session_lifecycle",
    "event_type": "session_stop",
    "session_time_s": SynchronizationManager.stop(),
}
```

Ownership:

- `SynchronizationManager` defines Session Time but does not create event records.
- `Session` records runtime lifecycle only.
- Acquisition-side caller code creates the event records and sends them to the Ingestor.
- Ingestor and StorageManager preserve them unchanged.

`session_stop` marks the end of acquisition time.

`Session.completed`, `failed`, and `aborted` occur after cleanup.

---

## Decision 068: AcquisitionNode v1 owns bounded synchronous acquisition execution

**Status:** Accepted

`AcquisitionNode` is the software owner of acquisition execution.

It does not own the `Session` object or Session lifecycle.

For Phase 1, `AcquisitionNode` receives already-created runtime collaborators, including:

* session identity
* DeviceManager
* SynchronizationManager
* Ingestor boundary

It does not construct adapters, managers, synchronization services, ingestors, or storage.

`AcquisitionNode v1` uses a bounded synchronous execution model.

It may expose a small public interface for:

* acquisition-side readiness
* starting acquisition
* running one acquisition iteration
* stopping acquisition
* aborting acquisition
* reporting acquisition status

`AcquisitionNode` is responsible for:

* starting and stopping Session Time through SynchronizationManager
* creating `session_start` and `session_stop` acquisition evidence
* starting, collecting from, stopping, and shutting down devices through DeviceManager
* creating acquisition envelopes
* sending envelopes to the Ingestor boundary

It is not responsible for:

* Session lifecycle
* Controller behavior
* GUI behavior
* adapter construction
* storage policy
* transport
* scheduling/threading/async execution
* reconstruction
* neuroscience analysis

**Principle**

AcquisitionNode owns acquisition execution, not Session lifecycle.

**Rationale**

The current tests manually coordinate Session, SynchronizationManager, DeviceManager, Ingestor, and StorageManager. That orchestration is now an acquisition runtime responsibility and should belong to AcquisitionNode, while preserving the existing ownership boundaries.

**Consequence**

The next implementation can replace test-owned acquisition orchestration with a minimal `AcquisitionNode` without introducing transport, threading, persistent storage, reconstruction, or direct Session ownership.

---

## Decision 069: DeviceManager collects records; AcquisitionNode creates envelopes

**Status:** Accepted

DeviceAdapters expose acquisition records but do not create `AcquisitionRecordEnvelope` objects or communicate with the Ingestor.

DeviceManager collects adapter records and returns `DeviceRecordCollection` objects.

Minimum `DeviceRecordCollection` fields:

* source_device_id
* record_kind
* records

AcquisitionNode converts `DeviceRecordCollection` objects into `AcquisitionRecordEnvelope` objects and attaches Session Time as needed.

DeviceAdapters do not assign Session Time, but may preserve device-local timing information.

**Principle**

DeviceAdapters expose acquisition records; DeviceManager returns `DeviceRecordCollection`; AcquisitionNode creates `AcquisitionRecordEnvelope`.

---

## Decision 070: Session owns accepted run configuration

**Status:** Accepted

`SessionConfig` represents the accepted configuration for one Session run.

The Controller may assemble configuration, but the Session owns the accepted configuration.

`DeviceDeclaration` says what participates.

Device configuration says how each device should be used.

`SessionConfig` may include:

* session parameters
* device declarations
* device configuration
* synchronization configuration
* acquisition runtime configuration
* ingestion/storage configuration
* protocol intent or reference

Runtime owners receive only the configuration relevant to their responsibility.

**Principle**

The Controller assembles configuration; the Session owns the accepted run configuration.

---

## Decision 071: Persistent storage v1 uses JSONL

**Status:** Accepted

`StorageManager` remains the architectural component responsible for persistent storage of accepted acquisition records.

For v1, `StorageManager` uses JSONL as the persistent storage backend.

Each line stores one accepted `AcquisitionRecordEnvelope` in its plain-data dictionary representation.

Ingest audit records remain separate from acquisition records.

This decision does not define the final storage format. Future implementations may replace the JSONL backend without changing `StorageManager` ownership.

**Principle**

`StorageManager` is the architectural boundary; JSONL is the v1 storage backend.

---

## Decision 072: SessionConfig is part of the Session Record

**Status:** Accepted

The accepted `SessionConfig` is part of the persistent Session Record.

The Controller assembles the configuration.

The Session owns the accepted `SessionConfig`.

`SessionConfig` is immutable for the duration of the Session.

Runtime components receive only the configuration relevant to their responsibilities and must not modify the accepted `SessionConfig`.

This decision establishes that the accepted configuration is preserved as part of the Session Record. It does not define:

* storage format
* serialization
* file location
* session folder layout
* versioning

**Rationale**

The accepted configuration is part of the scientific evidence required to understand, reproduce, reconstruct, and audit a Session.

**Consequence**

Future Session Record implementations must persist the accepted `SessionConfig` alongside the other Session evidence.

---

## Decision 073: Persistent Session Record v1 contents

**Status:** Accepted

A persistent Session Record is the durable evidence package for one Session.

For v1, the Session Record must include enough information to audit a completed, failed, or aborted Session.

Minimum required contents:

* accepted `SessionConfig`
* Session lifecycle evidence
* device readiness evidence
* service readiness evidence
* `session_start` acquisition event
* `session_stop` acquisition event, if available
* accepted acquisition envelopes
* ingest audit records
* final session status
* warnings, recoverable failures, and fatal failures, if any
* cleanup evidence

The Session Record records what was intended, what was ready, what ran, what was acquired, what was ingested, how the Session ended, and what failed.

This decision defines required evidence, not the final storage implementation.

It does not define:

* Parquet schemas
* NWB export
* reconstruction outputs
* final folder layout
* manifest format
* real device schemas
* transport
* scheduler/threading behavior

**Rationale**

A Session is scientifically auditable only if stored evidence preserves both acquisition data and execution context. Raw acquisition envelopes alone are insufficient because they do not capture accepted configuration, readiness, lifecycle, ingest audit, cleanup, or final status.

**Consequence**

Future storage implementations must preserve these evidence categories as part of the Session Record. Phase 1 may use simple JSON/JSONL representations until the final storage structure is defined.

---

## Decision 074: Persistent Session Record finalization ownership

**Status:** Accepted

No separate `SessionRecordManager` exists in v1.

The persistent Session Record is assembled from evidence owned by existing components.

Ownership remains:

* `Session` owns accepted `SessionConfig`, lifecycle evidence, readiness evidence, cleanup evidence, and final session status.
* `AcquisitionNode` creates acquisition evidence, including `session_start` and `session_stop` events.
* `Ingestor` owns ingest audit evidence.
* `StorageManager` writes persistent evidence.

A finalization caller may gather the required evidence pieces and pass them to the `StorageManager`.

The finalization caller is orchestration code, not a new architectural owner.

`Session` does not write directly to storage.

`StorageManager` does not own Session lifecycle, acquisition execution, or ingest auditing.

This decision does not define:

* final folder layout
* manifest format
* Parquet schemas
* NWB export
* reconstruction outputs
* transport
* scheduler/threading behavior

**Rationale**

The framework already has clear evidence owners. Creating a `SessionRecordManager` before repeated finalization workflows exist would add a premature abstraction and risk blurring ownership boundaries.

**Consequence**

The first persistent Session Record implementation should pass existing evidence into the `StorageManager` explicitly. A dedicated Session Record owner may be considered later only if repeated workflows show that the orchestration role has become a real component.

---

## Decision 075: Phase 2 remote AcquisitionNode readiness

**Status:** Accepted

Phase 2 hardens Phase 1 for remote AcquisitionNode deployment.

Phase 2 validates one remote AcquisitionNode while keeping the design compatible with multiple future acquisition-capable systems.

A real or remote AcquisitionNode session may start only if readiness evidence shows:

* required devices ready
* Session Time ready
* Ingestor reachable or explicit local fallback available
* storage path ready for every machine expected to write data
* cleanup/finalization path available

Each acquisition-capable system must have explicit identity evidence:

* `node_id`
* `session_id`
* role declaration
* local storage readiness, if it writes files
* connection/readiness status with the Ingestor
* cleanup/finalization evidence

For v1, node readiness is represented by `AcquisitionNodeReadiness`.

`AcquisitionNodeReadiness` aggregates existing readiness evidence rather than replacing it:

* device readiness uses existing `DeviceReadinessSummary`
* service readiness uses existing `ServiceReadiness`

The acquisition envelope may include optional `source_node_id`.

New Phase 2 remote-acquisition workflows should populate `source_node_id`.

Existing Phase 1 envelope records remain valid without `source_node_id`.

Do not encode node identity into `source_device_id`.

Network transfer may fail. Acquisition evidence must still be preserved, or the session must fail safely with evidence.

This decision does not define:

* final network architecture
* Redis
* retries
* async runtime
* transport abstraction
* multi-node acquisition
* multi-node synchronization
* storage capacity threshold policy
* local fallback implementation
* Parquet
* NWB

**Rationale**

Remote deployment introduces operational risk even when the data model is unchanged. The first Phase 2 contract should prove safe readiness and identity evidence without turning transport into a new architecture.

**Consequence**

The next implementation may add a small node-readiness record and optional `source_node_id` envelope field, then validate one simulated remote AcquisitionNode sending plain-data envelopes to one computer Ingestor.

---

## Decision 76: Public Repository and Local Configuration

**Status:** Accepted

The Lab Sync Acquisition framework is maintained as a public repository.

No confidential, machine-specific, or institution-specific information shall be committed to the repository.

Examples include, but are not limited to:

- IP addresses
- hostnames
- usernames
- passwords, tokens, or API keys
- SSH keys
- hardware serial numbers
- local filesystem paths
- calibration files
- machine-specific configuration
- lab-specific deployment information

Whenever runtime configuration is required, the repository should provide a committed example/template configuration file (for example `config.example.*`).

Each deployment (Jetson, acquisition computer, controller, developer workstation, etc.) should maintain its own local configuration file derived from the example.

Local configuration files containing machine-specific information must be excluded from version control (for example via `.gitignore`).

The framework source code should never depend on confidential values being hard-coded into the repository.

**Rationale**

Maintaining the framework as a public repository improves reproducibility, collaboration, and deployment while protecting confidential laboratory information. Example configuration files also provide clear documentation for new users and deployments.

**Consequence**

All future configuration features should distinguish between:

- committed example/template configuration
- local deployment-specific configuration

Only the example/template files belong in the repository.

---

## Decision 077: Continuous acquisition batching is owned by AcquisitionNode

**Status:** Accepted

Acquisition Nodes should batch continuous acquisition records before sending them to the Ingestor.

Batching is owned by the AcquisitionNode. DeviceAdapters produce timed records; DeviceManager collects records; AcquisitionNode groups records into AcquisitionRecordEnvelope objects.

Batching does not change timing ownership. Each row must already contain Session Time or enough timing information to reconstruct it before batching.

For v1, batches may be flushed by record count, elapsed batch age, normal stop, abort, or failure cleanup.

Retry behavior is part of Phase 3 acquisition robustness. Retry belongs to the AcquisitionNode transmission responsibility and must preserve failure/retry/drop evidence.

**Rationale:**
Continuous streams should avoid row-by-row transmission without moving timing responsibility away from acquisition.

**Consequence:**
Ingestor and StorageManager remain envelope-oriented and do not need to know whether an envelope contains one record or many records.

---

## Decision 078: AcquisitionNode batching implementation v1

**Status:** Accepted

The v1 implementation of continuous acquisition batching follows these principles:

- `AcquisitionNode` owns batching state.
- Pending batches are private runtime state within `AcquisitionNode`.
- Pending batches are created lazily only after records are produced.
- Batching is performed per stream identity (`source_node_id`, `source_device_id`, `record_kind`).
- Only `stream` records are batched in v1. Other record kinds continue using the existing immediate-envelope path.
- Batching behavior is configured through `SessionConfig.acquisition_configuration`.
- The selected batching policy is part of the accepted `SessionConfig` and therefore part of the persistent Session Record.
- v1 supports a single batching policy shared by all stream-producing devices. Future versions may introduce additional policies or per-device policies without changing ownership boundaries.

**Rationale**

This implementation keeps batching entirely within the existing `AcquisitionNode` responsibility, preserves the existing acquisition-envelope boundary, and avoids introducing new architectural components or downstream changes.

**Consequence**

`DeviceAdapter`, `DeviceManager`, `Ingestor`, and `StorageManager` remain unchanged. `AcquisitionRecordEnvelope` remains the transfer boundary regardless of whether it contains one record or many.
```

---

## Decision 079: Device declarations carry device-specific acquisition policy assignments

**Status:** Accepted

Device-specific acquisition policy assignments belong with the device declaration.

A `DeviceDeclaration` should identify not only which device participates in a Session, but also which acquisition policies apply to that device when relevant.

Examples include:

- batching policy
- handoff failure policy
- future storage or timing-related acquisition policies

Policy definitions may remain in `SessionConfig.acquisition_configuration`, but policy assignment should be declared with the device rather than in a separate source-to-policy map.

**Rationale**

When adding or modifying a device, the acquisition behavior associated with that device should be visible in one place. This avoids scattered configuration maps and reduces the risk that a new device is declared without its required acquisition policies.

**Consequence**

Future implementation should extend `DeviceDeclaration` or the accepted device configuration structure so that each device can declare relevant acquisition policy names, such as `batch_policy` and `handoff_failure_policy`. `AcquisitionNode` may use these assignments when applying source-specific behavior, while policy meanings remain defined in acquisition configuration.

---

## Decision 080: AcquisitionRecordEnvelope is the atomic handoff unit

**Status:** Accepted**

`AcquisitionRecordEnvelope` is the atomic unit for acquisition handoff.

Once records are placed into an envelope, handoff, retry, failure, preservation, or drop behavior operates on the entire envelope and never on individual records.

**Rationale:**
The framework needs one clear unit of transfer and failure accounting.

**Consequence:**
Record-level retry or partial-envelope handoff is out of scope unless a future architecture explicitly replaces the envelope boundary.

---

## Decision 081: AcquisitionNode owns sender-side handoff failure evidence

**Status:** Accepted

Handoff failure evidence is mandatory for every failed envelope handoff attempt.

Failure policy determines the consequence of the failure, not whether evidence is recorded.

Sender-side handoff failure evidence is owned by the `AcquisitionNode`, because the failure occurred before the envelope successfully crossed the handoff boundary.

`Ingestor` owns receiver-side ingest audit for envelopes it receives.

`StorageManager` owns persistence of accepted envelopes.

**Rationale:**
Failure ownership should follow where the failure occurred.

**Consequence:**
Policies such as `must_preserve` or `best_effort` may decide whether failed envelopes are preserved, retried, dropped, or cause abort, but they may not suppress failure evidence.

---

## Decision 082: Handoff failure policies define sender-side failure consequences

**Status:** Accepted

Phase 3 defines two sender-side handoff failure policies:

```text
must_preserve
    failure evidence required
    failed envelope must be preserved locally if not handed off
    repeated failures may abort acquisition

best_effort
    failure evidence required
    failed envelope may be dropped
    acquisition continues

---

## Decision 083: Sender-side handoff v1 uses one attempt per envelope 

**Status:** Accepted

For v1, each `AcquisitionRecordEnvelope` receives one sender-side handoff attempt.

If handoff fails, the `AcquisitionNode` applies the assigned handoff failure policy immediately.

There is no retry queue, delayed retry, replay backlog, or blocking resend loop in v1.

For `must_preserve`, the failed envelope is preserved locally, failure evidence is recorded, and consecutive failed handoff attempts may abort acquisition.

For `best_effort`, failure evidence is recorded, the failed envelope may be dropped, and acquisition continues.

**Rationale:**
The first robustness slice should preserve evidence and define failure consequences without introducing a replay system.

**Consequence:**
Consecutive failures mean consecutive failed handoff attempts for newly emitted `must_preserve` envelopes, not retry attempts from a backlog.

---

## Decision 084: System error evidence location is configured per Session

**Status:** Accepted

Each Session must have a configured location for system error and failure evidence.

Framework components that produce runtime error evidence must write or report that evidence to the configured Session error evidence location.

User notification is separate from error evidence preservation.

The AcquisitionNode must not own GUI popups, alerts, or user-facing notification behavior.

**Rationale:**
Failure evidence must be preserved even when no user interface is available.

**Consequence:**
AcquisitionNode may record sender-side handoff failures there, while future Controller or GUI components may surface user-facing alerts from preserved evidence or runtime status.

---

## Decision 085: Must-preserve handoff failure threshold aborts AcquisitionNode

**Status:** Accepted

For `must_preserve` handoff failures, the failure threshold is configured in `SessionConfig.acquisition_configuration`.

Only failed handoff attempts for newly emitted `must_preserve` envelopes count toward the threshold.

A successful envelope handoff resets the consecutive failure count.

When the threshold is reached, the `AcquisitionNode` records failure evidence for the triggering envelope, stops accepting new acquisition iterations, and marks acquisition status as failed.

Session failure and cleanup remain owned by caller/Session orchestration, not by the `AcquisitionNode`.

**Rationale:**
`must_preserve` needs operational meaning without introducing retry, replay, Controller behavior, or GUI notification.

**Consequence:**
Consecutive failure counting belongs to sender-side handoff behavior and does not define a general error taxonomy.

---

## Decision 086: Failed AcquisitionNode remains cleanup-capable

**Status:** Accepted

If `AcquisitionNode` enters failed status, it must reject new acquisition iterations but remain capable of stop and cleanup operations.

During stop after failure, `AcquisitionNode` should flush pending batches when possible, record `session_stop` if possible, stop devices, shut down devices, and preserve cleanup evidence.

`AcquisitionNode` does not own `Session.fail()` or final Session lifecycle state.

**Rationale:**
Acquisition failure should prevent further acquisition but must not prevent evidence-preserving cleanup.

**Consequence:**
Failure status blocks new acquisition iterations, not cleanup.

---

## Decision 087: Acquisition health is evaluated by AcquisitionNode

**Status:** Accepted

Acquisition health describes whether an expected acquisition source is producing valid acquisition evidence during a running Session.

Acquisition health is distinct from handoff failure.

Acquisition-health policy definitions live in `SessionConfig.acquisition_configuration`.

Device-specific acquisition-health policy assignments live with the corresponding `DeviceDeclaration`.

`AcquisitionNode` is the primary evaluator of acquisition health because it owns acquisition execution, record collection, batching, envelope creation, and sender-side evidence.

`DeviceAdapters` may optionally report device-specific health information, but adapter-reported health supplements AcquisitionNode evaluation and does not replace it.

For v1, acquisition health produces explicit health evidence without introducing retry, replay, GUI notification, async execution, or Session lifecycle ownership.

---

## Decision 088: Acquisition health behavior is determined by the assigned device policy

**Status:** Accepted

`AcquisitionNode` does not infer acquisition-health behavior from device type.

Instead, `AcquisitionNode` reads the acquisition-health policy assigned in the corresponding `DeviceDeclaration`.

Policy definitions remain in `SessionConfig.acquisition_configuration`.

The assigned policy determines how acquisition health is evaluated.

For this implementation slice, health-policy failure must produce explicit acquisition-health evidence only.

Do not make AcquisitionNode fail yet.

Do not introduce warning/fatal policy consequences yet.

Do not infer health behavior from required devices, device type, or record kind.

---

## Decision 089: Acquisition health policy assignments reach AcquisitionNode through explicit source policy mapping

**Status:** Accepted

`AcquisitionNode` must not infer acquisition-health policy assignments by matching `DeviceDeclaration.device_id` to live adapter or `DeviceRecordCollection.source_device_id`.

Declaration-to-adapter binding remains deferred.

For v1, caller/orchestration code passes an explicit acquisition-health source policy mapping into `AcquisitionNode`.

The mapping keys are live acquisition source IDs, matching `DeviceRecordCollection.source_device_id`.

The mapping values are acquisition-health policy names defined in `SessionConfig.acquisition_configuration`.

Conceptually:

```text
DeviceDeclaration
    declares intended policy assignment

caller/orchestration
    performs explicit declaration-to-live-source wiring

AcquisitionNode
    receives source_id -> acquisition_health_policy_name mapping
    evaluates policies against DeviceRecordCollection.source_device_id
```

`AcquisitionNode` may only evaluate acquisition health for source IDs present in this explicit mapping.

`AcquisitionNode` does not validate whether the mapping came from a particular `DeviceDeclaration`.

**Rationale:**
Existing architecture intentionally defers declaration-to-adapter matching. Assuming equal IDs would silently introduce that binding. An explicit source policy mapping lets acquisition health proceed without changing DeviceManager ownership or adapter construction architecture.

**Consequence:**
The implementation must add explicit `AcquisitionNode` input for source health-policy assignments rather than giving `AcquisitionNode` full `DeviceDeclaration` access.

---

## Decision 090: AcquisitionNode requires writable failure-evidence location before acquisition starts

**Status:** Accepted

`AcquisitionNode` must verify that the configured Session failure/error evidence location is writable before acquisition starts.

If the configured failure/error evidence location is missing, unavailable, or not writable, acquisition readiness fails.

`AcquisitionNode` must not enter running acquisition when failure evidence cannot be preserved.

This applies before any acquisition records are collected, batched, or handed off.

**Rationale:**
Once acquisition starts, failures must be preservable. If failure evidence cannot be written, then failed or partial Sessions become unauditable.

**Consequence:**
Acquisition start/readiness must include a failure-evidence writability check. This does not introduce GUI notification, Controller behavior, retry, replay, or Session failure ownership.

---

## Decision 091: AcquisitionNode exposes Acquisition Runtime terminology while preserving acquisition compatibility methods

**Status:** Accepted

`AcquisitionNode` exposes Acquisition Runtime terminology for its Session-level runtime lifecycle.

The preferred public terminology is:

```text
check_ready()
start_runtime()
run_one_iteration()
stop_runtime()
get_status()
```

`start_runtime()` means the AcquisitionNode enters the active runtime for a Session: Session Time may start, acquisition evidence can be recorded, batching/envelope creation may occur, and cleanup/failure behavior becomes active.

`start_runtime()` does not mean every declared device is streaming, an Experiment is active, or every Session-ready device is producing records.

For compatibility, existing `start_acquisition()` and `stop_acquisition()` methods may remain as wrappers around `start_runtime()` and `stop_runtime()` during transition.

Acquisition Runtime states are conceptually:

```text
created
ready
runtime_active
stopping
runtime_stopped
failed
cleanup_failed
```

A failed AcquisitionNode rejects new acquisition iterations but remains cleanup-capable.

**Principle**

AcquisitionNode runtime active means the Session acquisition runtime is capable of recording evidence; it does not imply all devices are streaming.

---

## Decision 092: Controller v1 owns single-session sequential orchestration

**Status:** Accepted

Controller v1 owns sequential orchestration for one Session run.

Controller v1 coordinates existing components through Session creation/opening, initialization, runtime start, bounded iteration calls, intentional stop, finalization, and final Session outcome.

Controller v1 does not absorb ownership from Session, AcquisitionNode, SynchronizationManager, DeviceManager, Ingestor, or StorageManager.

Ownership remains:

```text
Session
    owns lifecycle state, accepted SessionConfig, readiness evidence,
    cleanup/finalization evidence, and final Session status

AcquisitionNode
    owns Acquisition Runtime execution, session_start/session_stop evidence,
    batching, envelope creation, sender-side handoff failure evidence,
    acquisition health evaluation, and cleanup-capable runtime stop

SynchronizationManager
    owns Session Time

DeviceManager
    owns live DeviceAdapters and adapter lifecycle coordination

Ingestor
    owns receiver-side ingest audit and accepted-envelope handoff to StorageManager

StorageManager
    owns persistent writing of evidence

Controller
    owns single-session orchestration and command results
```

Controller v1 may expose:

```text
create_session(config)
initialize_session()
start_session()
run_one_iteration()
stop_session(reason=None)
finalize_session()
get_status()
```

Controller v1 does not expose `abort_session()` as a separate command.

For v1:

```text
stop = command
abort = future semantic interpretation or metadata
failure = framework/runtime-detected outcome
```

Controller requests initialization, but Session performs readiness gating.

Controller starts the Session-level Acquisition Runtime, but does not imply that an Experiment is active or that all declared devices are streaming.

Controller v1 must not treat these as equivalent:

```text
Session.running
Acquisition Runtime active
Experiment running
Device streaming
```

A Session may be running while no Experiment is active. A device may be Session-ready but intentionally idle.

Experiment segments, validation segments, device-streaming schedules, experiment-scoped acquisition health, network command transport, GUI behavior, async service runtime, multi-session Overlord behavior, and multi-node orchestration are out of scope for Controller v1.

Controller v1 directly records only command/orchestration result evidence. It coordinates evidence owned by Session, AcquisitionNode, Ingestor, and StorageManager without taking ownership of that evidence.

**Principle**

Controller commands and orchestrates one Session.
Session owns lifecycle.
AcquisitionNode owns runtime execution.
Device streaming is source-specific and not implied by Session start.

---

## Decision 093: Controller failure outcomes and two-step Session Record finalization

**Status:** Accepted

A Session may transition directly from `initialized` to `failed` when a pre-running framework or runtime failure prevents acquisition from safely starting.

Session completion requires persistent Session Record finalization. Controller v1 uses two persistence steps:

```text
Acquisition Runtime stops
        ↓
Session.stop()
        ↓
StorageManager writes Session Record using current stopping evidence
        ↓
Session.complete()
        ↓
StorageManager updates the Session Record with final completed status and lifecycle evidence
```

If the first Session Record write fails, Controller calls `Session.fail()` and records a failed `ControllerCommandResult`.

If the final completed-record update fails after `Session.complete()`, Controller reports the failed command result and does not invent rollback semantics.

Session continues to own lifecycle and final status. StorageManager continues to own persistent writing. Controller owns orchestration and command outcomes.

**Rationale:**
Pre-running failures must be representable without falsely claiming that acquisition ran, and completed Sessions must have durable final evidence.

**Consequence:**
Normal completion requires a successful stopping-state write followed by a completed-state update. Framework failures use existing Session failure lifecycle behavior without adding abort, retry, or new ownership.

---

## Decision 094: Project, Session, and Experiment are distinct concepts

**Status:** Accepted

A Project is the larger scientific study or collection of related Sessions.

A Session is one bounded acquisition/evidence run with Session lifecycle, Session Time, Acquisition Runtime, accepted configuration, and a persistent Session Record.

An Experiment is a bounded scientific or protocol activity inside a running Session.

A Project may contain many Sessions.

A Session may contain zero, one, or many Experiments.

Session start means the Session evidence container and Acquisition Runtime begin. It does not mean an Experiment has started.

Experiment start and Experiment end are recorded as timestamped evidence inside the running Session.

Device participation, protocol behavior, validation periods, and acquisition-health expectations may eventually be scoped to Experiments rather than to the entire Session.

**Principle**

* Project is the scientific study.
* Session is the acquisition/evidence container.
* Experiment is protocol activity inside a Session.

---

## Decision 095: Experiment lifecycle is Controller-owned and Session-scoped

**Status:** Accepted

Experiment lifecycle is Controller-owned and Session-scoped. There is one canonical Experiment lifecycle per Experiment segment within a Session.

The canonical lifecycle belongs to the Session timeline and Session Record, not to individual AcquisitionNodes.

Future canonical lifecycle events are conceptually `experiment_start`, `experiment_stop`, `experiment_abort`, and `experiment_fail`.

AcquisitionNode(s) do not own Experiment lifecycle. AcquisitionNode(s) record local execution evidence associated with the active Experiment.

This mirrors the accepted boundary: Controller owns protocol intent; AcquisitionNode owns execution evidence.

The design must remain compatible with multiple AcquisitionNodes participating in one Session. Canonical Experiment lifecycle events must not assume `source_device_id = acquisition_node`.

```text
Experimenter
        ↓
Controller
        ↓
Session timeline / Session Record
        ↓
AcquisitionNode(s)
        ↓
local execution evidence
```

---

## Decision 096: Readiness, Validation, and Experiment are distinct architectural concepts

**Status:** Accepted

Readiness, Validation, and Experiment are distinct architectural concepts. They must not collapse into one Experiment abstraction.

**Readiness** is an automatic framework operation during Session initialization. It determines whether components can safely participate and whether the Session may proceed. It is not operator-initiated and is not an Experiment.

**Validation** is operator-initiated operational activity inside a Session. It records validation evidence without creating an Experiment, and not every device must support it. Examples include playing a test tone, dispensing one reward, acquiring one camera frame, flashing an LED, or moving an actuator.

**Experiment** is scientific or protocol activity bounded inside a running Session. It owns scientific meaning rather than operational checks. Examples include baseline recording, behavioral tasks, fear conditioning, BMI training, stimulation protocols, and decoder calibration.

**Calibration** is a purpose, not an architectural category. Operational calibration is Validation; scientific calibration is Experiment.

```text
autofocus              → Validation
play test tone         → Validation
acquire one frame      → Validation
BMI decoder training   → Experiment
```

**Principle**

```text
Readiness
    framework operation

Validation
    operator-initiated operational activity inside a Session

Experiment
    scientific/protocol activity inside a running Session

Calibration
    purpose, not an architectural category
```

---

## Decision 097: Experiment declares expected participants

**Status:** Accepted

The Session owns available resources. The Experiment declares which Session resources are expected to participate.

Resources remain owned by the Session. The Experiment owns only the expectation that selected resources contribute to that Experiment. This is broader than devices.

```text
Session
        ↓
available resources

Experiment
        ↓
expected participants
```

```text
Session-ready ≠ Experiment participant
Experiment participant ≠ continuously producing acquisition
Participation = expected contribution
```

Future expected participants may include AcquisitionNodes, Devices, protocol services, decoders, and other runtime components.

Future experiment-scoped acquisition health should be evaluated only against expected participants declared by the active Experiment.

---

## Decision 098: Experiment expected participants are plain-data declarations

**Status:** Accepted

Experiment expected participants are stored in an `ExperimentDescriptor`.

They are plain-data declarations of expected contribution during an Experiment, not live runtime objects. They do not create, own, bind, start, stop, or manage live resources.

```text
ExperimentDescriptor
    persistent intent / expected participation

Controller
    uses descriptor to command Experiment lifecycle

Session
    records descriptor as Session evidence

AcquisitionNode(s)
    receive only relevant runtime intent later

Live resources
    remain owned by existing runtime owners
```

```text
ExpectedParticipant
    != live DeviceAdapter
    != DeviceManager entry
    != AcquisitionNode object
    != runtime binding
```

The minimum conceptual fields are:

```text
participant_id
participant_type
expected_contribution
required
```

Examples include:

```text
camera_001
    participant_type: device
    expected_contribution: camera_frame_metadata

jetson_001
    participant_type: acquisition_node
    expected_contribution: behavior_acquisition

decoder_001
    participant_type: decoder
    expected_contribution: decoder_predictions
```

`ExpectedParticipant` is to `ExperimentDescriptor` what `DeviceDeclaration` is to `SessionConfig`: persistent intent first, runtime binding later.

---

## Decision 099: Expected participants define Experiment-scoped acquisition health scope

**Status:** Accepted

Experiment-scoped acquisition health is evaluated only for the Expected Participants declared by the active Experiment.

Resources that are Session-ready but are not Expected Participants in the active Experiment must not produce Experiment-scoped acquisition-health failures.

`ExpectedParticipant` declares expectation only. It does not bind itself to live acquisition sources, `DeviceAdapter` objects, `DeviceManager` objects, `AcquisitionNode` objects, or acquisition-health policies. A separate runtime mapping will be introduced later.

```text
ExpectedParticipant
        |
caller/orchestration mapping
        |
live acquisition source id
        +
acquisition-health policy
        |
AcquisitionNode
```

```text
Session readiness
    can this resource participate?

Expected participant
    should this resource contribute now?

Experiment-scoped acquisition health
    did the expected contribution appear?
```

This decision defines only the scope of evaluation. It intentionally does not define runtime binding, participant enforcement, health policy assignment, health evaluation algorithms, Validation behavior, or distributed orchestration.

---

## Decision 100: Experiment expected-participant assignments reach AcquisitionNode through explicit runtime mapping

**Status:** Accepted

`ExpectedParticipant` declarations do not bind themselves to live acquisition sources.

`AcquisitionNode` must not infer Experiment-scoped acquisition-health assignments by matching `ExpectedParticipant.participant_id` to `DeviceDeclaration.device_id`, `DeviceRecordCollection.source_device_id`, live `DeviceAdapter` identifiers, or `AcquisitionNode` identifiers.

Instead, caller/orchestration provides an explicit runtime mapping.

```text
ExperimentDescriptor
    contains ExpectedParticipant declarations

        |

caller/orchestration

        |

maps Expected Participants to

    live acquisition source IDs
    +
    acquisition-health policies

        |

AcquisitionNode

        |

evaluates Experiment-scoped acquisition health only from that mapping
```

**Principle**

```text
Declaration is not binding.

ExpectedParticipant
    declares expected contribution.

Runtime mapping
    defines which live source satisfies that expectation.

AcquisitionNode
    never guesses the mapping.
```

This mirrors the existing explicit boundaries between `DeviceDeclaration` and `DeviceAdapter`, and between acquisition-health policies and live source assignments. The framework consistently separates persistent declarations, runtime binding, and runtime execution.

---

## Decision 101: Experiment runtime health mapping contract

**Status:** Accepted

For each active Experiment, caller/orchestration provides `AcquisitionNode` with an explicit Experiment runtime health mapping.

The mapping is keyed by live acquisition source ID. Each live source entry identifies the Expected Participant it satisfies, the acquisition-health policy to apply, whether participation is required, and the expected contribution.

```text
ExperimentDescriptor
    ExpectedParticipant(participant_id="camera_001")
            |

caller/orchestration mapping

            |

live_source_id = "camera-adapter-source-17"

    expected_participant_id = "camera_001"
    acquisition_health_policy = "camera_frames_required"
    required = True
    expected_contribution = "camera_frame_metadata"

            |

AcquisitionNode
```

An Expected Participant may map to zero, one, or many live sources. A live acquisition source may satisfy at most one Expected Participant within one active Experiment mapping.

The runtime mapping is immutable for the lifetime of one active Experiment. Different Experiments within the same Session may activate different runtime mappings.

`AcquisitionNode` evaluates Experiment-scoped acquisition health only for live acquisition source IDs present in the active mapping. It must not infer mappings from Expected Participant identifiers, `DeviceDeclaration` identifiers, `DeviceAdapter` identifiers, `AcquisitionNode` identifiers, or `DeviceRecordCollection` source identifiers.

```text
Controller / orchestration
        starts Experiment
                |
provides ExperimentDescriptor
        + Experiment runtime health mapping
                |
AcquisitionNode activates mapping
                |
evaluates Experiment-scoped acquisition health
                |
mapping is cleared or replaced when Experiment ends
```

**Principle**

```text
ExpectedParticipant
    declares expectation.

Runtime mapping
    identifies which live acquisition source satisfies that expectation.

AcquisitionNode
    evaluates only the explicit mapping and never guesses.
```

This extends the framework's separation of persistent declarations, runtime binding, and runtime execution.

---

## Decision 102: Active Experiment runtime health mapping scopes AcquisitionNode health evaluation

**Status:** Accepted

When an active Experiment runtime health mapping is present, `AcquisitionNode` acquisition-health evaluation is scoped only to the live acquisition source IDs present in that mapping.

```text
No active Experiment runtime health mapping
        |
No Experiment-scoped acquisition-health evaluation

Active Experiment runtime health mapping
        |
Evaluate only mapped live acquisition source IDs
```

Session-ready resources that are not present in the active mapping must not participate in Experiment-scoped acquisition-health evaluation.

`AcquisitionNode` must not infer mappings, bind Expected Participants, inspect `DeviceDeclaration` objects, inspect `DeviceAdapter` identities, inspect `AcquisitionNode` identities, or evaluate unmapped live sources as Experiment participants.

This decision defines only the scope of evaluation. It intentionally does not define acquisition-health algorithms, health consequences, participant enforcement, Controller policy, runtime mapping persistence, or protocol execution.

**Principle**

```text
No active Experiment mapping
        |
No Experiment-scoped acquisition-health evaluation

Active Experiment mapping
        |
Evaluate only mapped live acquisition source IDs
```

This completes the runtime ownership chain:

```text
ExperimentDescriptor
        |
ExpectedParticipant
        |
Runtime mapping
        |
AcquisitionNode
        |
Experiment-scoped acquisition-health evaluation
```

The runtime mapping determines the scope of evaluation. `AcquisitionNode` never guesses that scope.



--- ********************************************************************************

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
24. Parquet remains the preferred future format for table-shaped intermediate records; Phase 1 uses the JSONL backend defined by Decision 071.
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
41. Session completion is independent of NWB export.
42. The Ingestor manages records, not necessarily all raw bytes online.
43. Timing belongs primarily with the data records it describes.
44. Raw acquisition records and NWB exports have separate lifecycles.
45. Storage capacity must be validated before acquisition begins.
46. Establish guardrails before implementation; establish structure after experience
47. Configuration declares intended devices before live adapters exist.
48. The minimum live Device Adapter interface proves runtime manageability before scientific data production.
49. DeviceManager receives already-created DeviceAdapters and coordinates lifecycle calls without creating adapters.
50. DeviceManager v1 requires at least one already-created DeviceAdapter, records adapter failures as results, and continues processing remaining adapters.
51. Session initialization may use supplied device readiness summaries for gating while DeviceManager remains the owner of live adapters.
52. DeviceManager and Session use one shared readiness record contract.
53. Live DeviceAdapters are explicitly constructed outside DeviceManager v1.
55. DeviceAdapter receives copied declaration fields, not DeviceDeclaration.
56. A component should only validate information it owns.
57. Ingestor owns the handoff of accepted records to StorageManager while StorageManager remains a separate storage boundary.
58. Architectural terminology is defined once and used consistently throughout the repository.
59. DeviceManager and Ingestor share transferable acquisition record envelopes rather than live adapter-owned or manager-owned objects.
60. AcquisitionRecordEnvelope supports a minimal JSON-like plain-data round trip without choosing a transport or serialization protocol.
61. StorageManager v1 proves in-memory persistence boundary behavior and small readback without deciding final storage format.
62. Session initialization consumes shared service readiness summaries and does not inspect service internals.
63. Acquisition-side code creates `AcquisitionRecordEnvelope` objects before records cross to the Ingestor. `DeviceManager`, `Session`, and `Ingestor` do not own this transformation.
64. SynchronizationManager owns Session Time; acquisition-side code attaches `session_time` to records before they become `AcquisitionRecordEnvelope`s.
65. Synchronization Manager v1 owns Session Time; it does not solve the full synchronization problem.
66. Session start and stop are stored as ordinary acquisition event records; Session lifecycle remains separate.
67. Session owns lifecycle; Acquisition Node owns acquisition execution.
68. AcquisitionNode v1 owns bounded synchronous acquisition execution, not Session lifecycle.
69. DeviceManager collects acquisition records into Collections; AcquisitionNode creates Envelopes.
70. The Controller assembles configuration; the Session owns the accepted run configuration.
71. StorageManager is the persistent storage boundary; JSONL is the v1 storage backend.
72. The accepted SessionConfig is part of the persistent Session Record.
73. The persistent Session Record is the durable evidence package for one Session.
74. Existing components own evidence; StorageManager writes evidence; no new manager yet.
75. Phase 2 remote AcquisitionNode sessions require explicit node identity and aggregated readiness evidence before acquisition starts.
76. The repository is public; all machine- or lab-specific configuration must be stored in untracked local configuration files, while committed example/template configuration files are provided for users to copy and customize.
77. Continuous acquisition batching is owned by the AcquisitionNode.
78.  `AcquisitionNode` does the batching
79. Device-specific acquisition policy assignments belong with the corresponding `DeviceDeclaration`. Policy definitions remain in `SessionConfig.acquisition_configuration`, while each device declares which policy names it uses.
80. Envelope doesn't split for failure
81. Sender-side handoff failure evidence is owned by the AcquisitionNode
82. Handoff failure policies define sender-side failure consequences
83. Sender-side handoff v1 performs one handoff attempt per envelope
84. System error evidence location is configured per Session.
85. A configured consecutive must-preserve handoff failure threshold marks AcquisitionNode acquisition status failed.
86. A failed AcquisitionNode rejects new iterations but remains capable of evidence-preserving cleanup.
87. AcquisitionNode evaluates acquisition health separately from handoff failure.
88. Acquisition-health behavior comes only from explicitly assigned device policy.
89. Caller code passes explicit live-source acquisition-health policy mappings into AcquisitionNode.
90. AcquisitionNode requires a writable configured Session failure-evidence location before acquisition starts.
91. AcquisitionNode runtime active means the Session acquisition runtime is capable of recording evidence; it does not imply all devices are streaming.
92. Controller commands and orchestrates one Session. Session owns lifecycle. AcquisitionNode owns runtime execution. Device streaming is source-specific and not implied by Session start.
93. Pre-running framework failures may fail an initialized Session; normal completion uses stopping-state persistence followed by completed-state Session Record update.
94. Project is the scientific study; Session is the acquisition/evidence container; Experiment is protocol activity inside a Session.
95. Controller owns canonical Session-scoped Experiment lifecycle; AcquisitionNodes record local execution evidence.
96. Readiness, Validation, and Experiment are distinct; Calibration is a purpose rather than an architectural category.
97. Experiments declare expected participation by Session-owned resources without owning those resources.
98. Experiment expected participants are plain-data declarations; live-resource binding remains separate and deferred.
99. Experiment-scoped acquisition health evaluates only Expected Participants declared by the active Experiment.
100. Expected-participant assignments reach AcquisitionNode through explicit caller/orchestration runtime mapping; AcquisitionNode never infers bindings from identifiers.
101. Each active Experiment uses an immutable live-source-keyed runtime health mapping supplied explicitly to AcquisitionNode by caller/orchestration.
102. AcquisitionNode performs no Experiment-scoped health evaluation without an active mapping and evaluates only live source IDs present in that mapping.

---



Open questions now belong exclusively in `open_questions.md`.

