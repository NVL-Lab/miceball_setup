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

**Superseded in part by Decision 105:** The acquisition-health policy assignment portion of this decision is no longer authoritative. A `DeviceDeclaration` value may serve only as a transitional default or template; the active `ExperimentRuntimeHealthMapping` owns the acquisition-health policy assignment for an Experiment. Other policy categories described here are not changed by Decision 105.

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

**Superseded by Decision 105:** Acquisition-health policy assignments belong to the active `ExperimentRuntimeHealthMapping`, not to `DeviceDeclaration`. Any declaration-level value is transitional/template data only.

`AcquisitionNode` is the primary evaluator of acquisition health because it owns acquisition execution, record collection, batching, envelope creation, and sender-side evidence.

`DeviceAdapters` may optionally report device-specific health information, but adapter-reported health supplements AcquisitionNode evaluation and does not replace it.

For v1, acquisition health produces explicit health evidence without introducing retry, replay, GUI notification, async execution, or Session lifecycle ownership.

---

## Decision 088: Acquisition health behavior is determined by the assigned device policy

**Status:** Accepted

**Superseded in part by Decision 105:** The policy still determines evaluation behavior, but the authoritative assignment is Experiment-scoped through `ExperimentRuntimeHealthMapping`, not read from the corresponding `DeviceDeclaration`.

`AcquisitionNode` does not infer acquisition-health behavior from device type.

Instead, `AcquisitionNode` reads the acquisition-health policy assigned in the active `ExperimentRuntimeHealthMapping`.

Policy definitions remain in `SessionConfig.acquisition_configuration`.

The assigned policy determines how acquisition health is evaluated.

For this implementation slice, a detected acquisition-health condition must produce explicit acquisition-health observation evidence only. Operational significance is evaluated separately.

Do not make AcquisitionNode fail yet.

Do not introduce warning/fatal policy consequences yet.

Do not infer health behavior from required devices, device type, or record kind.

---

## Decision 089: Acquisition health policy assignments reach AcquisitionNode through explicit source policy mapping

**Status:** Accepted

**Superseded in part by Decisions 100, 101, and 105:** The explicit live-source mapping principle remains accepted. The authoritative mapping is now the active Experiment-scoped `ExperimentRuntimeHealthMapping`, which assigns policy while connecting an Expected Participant to a live source. `DeviceDeclaration` is not the assignment owner.

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

Resources that are Session-ready but are not Expected Participants in the active Experiment must not produce Experiment-scoped health observations.

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

---

## Decision 103: Experiment-scoped acquisition health is expressed as health observations

**Status:** Accepted

`AcquisitionNode` owns Experiment-scoped acquisition-health evaluation for the active Experiment runtime mapping.

Whenever that evaluation detects a condition relevant to Experiment-scoped acquisition health, it produces an Experiment-scoped Health Observation.

Health Observations describe acquisition-health state without interpreting operational significance. Examples include:

* expected acquisition evidence missing
* expected acquisition evidence resumed
* acquisition rate below expectation
* acquisition resumed after interruption
* other Experiment-scoped acquisition-health conditions

Experiment-scoped Health Observations are recorded as Experiment-scoped health evidence.

For this first behavioral slice, observations produce evidence only. They do not imply warnings, recoverable failures, Experiment failure, Session failure, Controller behavior, operator notification, recovery, or retry.

**Principle**

```text
AcquisitionNode
        |
Experiment-scoped health evaluation
        |
Health Observation
        |
Health evidence

Policy interpretation is recorded separately from Health Observation evidence.
```

---

## Decision 104: Observation type is not consequence

**Status:** Accepted

An Experiment-scoped Health Observation describes a condition detected by acquisition-health evaluation. The observation type does not itself define a warning, recoverable failure, Experiment failure, Session failure, Controller action, operator notification, or recovery action.

Operational meaning is supplied separately by the acquisition-health policy assigned through the active `ExperimentRuntimeHealthMapping`. The same observation type may therefore have different configured consequence labels in different Experiments.

This decision separates detection evidence from its future runtime interpretation. It does not define consequence execution.

**Clarified by Decision 107:** AcquisitionNode executes the assigned policy interpretation and records Health Interpretation Evidence. Controller-owned framework actions remain separate.

**Principle**

```text
Observation type
    describes what was detected.

Assigned acquisition-health policy
    supplies configured operational meaning.
```

---

## Decision 105: Acquisition-health policy assignment is Experiment-scoped

**Status:** Accepted

Acquisition-health policies continue to exist as named policy definitions.

Policy definitions live in Session or Experiment configuration. Policy assignment belongs to the active `ExperimentRuntimeHealthMapping`.

**Clarified by Decision 110:** Policy definitions belong specifically to persistent `SessionConfig`; only assignment is Experiment-scoped runtime intent.

`DeviceDeclaration` declares Session-level availability and intent. It does not permanently define whether a device is critical, soft, optional, warning-only, fatal, or otherwise operationally consequential for all Experiments.

The same Session-ready live source may receive different acquisition-health policies in different Experiments.

```text
DeviceDeclaration
    declares Session availability / intent

ExpectedParticipant
    declares Experiment expectation

ExperimentRuntimeHealthMapping
    maps ExpectedParticipant to live source
    assigns Experiment-specific acquisition-health policy

Acquisition-health policy
    defines configurable evaluation
    and future consequence behavior
```

Earlier documentation that treated `DeviceDeclaration` as the authoritative owner of acquisition-health policy assignment is superseded. Declaration-level policy values are, at most, transitional defaults or templates and are not the authoritative Experiment-scoped assignment.

**Principle**

```text
A device is not globally critical or soft.

The active Experiment runtime mapping assigns the acquisition-health policy that applies during that Experiment.
```

---

## Decision 106: AcquisitionHealthPolicy is a plain-data policy definition

**Status:** Accepted

`AcquisitionHealthPolicy` is an immutable plain-data definition containing:

* a policy identifier
* explicit acquisition-health evaluation parameters
* an interpretation mapping from observation type to consequence label

The supported consequence-label vocabulary is:

* `informational`
* `warning`
* `recoverable_failure`
* `experiment_failure`
* `session_failure`

Policy validation ensures that interpretation keys are supported by a supplied evaluator observation vocabulary and that consequence labels belong to the accepted vocabulary.

This decision defines configuration and validation only. It does not execute consequences, change Controller behavior, fail Experiments or Sessions, notify operators, retry, or recover.

**Superseded in part by Decision 107:** AcquisitionNode now owns execution of the policy's observation interpretation and production of Health Interpretation Evidence. The prohibition on framework actions, lifecycle changes, notification, retry, and recovery remains authoritative.

**Superseded in part by Decision 111:** The flat `evaluation` parameter structure has evolved into rule-specific `evaluation_rules`. The policy remains an immutable plain-data definition with explicit interpretation vocabulary.

**Principle**

```text
AcquisitionHealthPolicy
    defines evaluation configuration
    and observation interpretation vocabulary.

Runtime consequence execution
    remains separate and deferred.
```

---

## Decision 107: AcquisitionNode executes AcquisitionHealthPolicy interpretation

**Status:** Accepted

`AcquisitionNode` executes the `AcquisitionHealthPolicy` assigned through the active `ExperimentRuntimeHealthMapping`.

Policy execution consists of interpreting Experiment-scoped Health Observations according to the assigned acquisition-health policy. It produces Health Interpretation Evidence recording the policy-assigned interpretation of each Health Observation.

For example:

```text
Observation:
    first_evidence_missing

Assigned policy:
    critical_camera

Health interpretation:
    experiment_failure
```

Policy execution ends with production of Health Interpretation Evidence.

`AcquisitionNode` does not stop an Experiment, fail a Session, notify the operator, retry or recover, invoke Controller behavior, or perform framework orchestration. Framework actions based on Health Interpretation Evidence remain the responsibility of the Controller.

**Principle**

```text
Health Observation
        |
Assigned AcquisitionHealthPolicy
        |
AcquisitionNode executes policy interpretation
        |
Health Interpretation Evidence
        |
Controller executes framework action
```

---

## Decision 108: AcquisitionHealthPolicy interpretation is immediate and one-to-one with health observations

**Status:** Accepted

When `AcquisitionNode` produces an `ExperimentScopedHealthObservation`, it immediately executes the assigned `AcquisitionHealthPolicy` interpretation for that observation.

Each emitted Health Observation produces at most one corresponding `HealthInterpretationEvidence` record. Interpretation evidence references the originating Health Observation and preserves an auditable runtime chain.

```text
Health Observation evidence
        |
Immediate assigned-policy interpretation
        |
Health Interpretation Evidence
```

Policy interpretation is runtime evidence, not a derived reconstruction product. Interpretations are not regenerated or silently reinterpreted after the fact. Any future offline reinterpretation using different policy definitions must be recorded as separate derived analysis or reconstruction evidence and must not modify the original runtime interpretation evidence.

If an observation has no configured interpretation under the assigned `AcquisitionHealthPolicy`, the runtime records the interpretation outcome as `uninterpreted` rather than inventing a consequence.

Allowed interpretation outcomes are:

* `informational`
* `warning`
* `recoverable_failure`
* `experiment_failure`
* `session_failure`
* `uninterpreted`

Interpretation evidence records what the runtime policy meant when the observation occurred. It remains evidence only and does not execute Controller behavior, stop an Experiment, fail a Session, retry, recover, notify operators, perform orchestration, or execute framework actions.

**Principle**

```text
Health Observation emitted
        |
Immediate one-to-one policy interpretation
        |
Health Interpretation Evidence emitted

Health Interpretation Evidence
        !=
Framework action
```

---

## Decision 109: Health interpretation evidence explicitly references its originating health observation

**Status:** Accepted

Each `ExperimentScopedHealthObservation` produced by `AcquisitionNode` has a stable runtime identity used solely to preserve provenance between runtime evidence records.

Each `HealthInterpretationEvidence` explicitly references its originating `ExperimentScopedHealthObservation`.

```text
ExperimentScopedHealthObservation

    observation_id

            |
            v

HealthInterpretationEvidence

    originating_observation_id
```

Observation identity preserves an auditable evidence chain. It is not a persistence identifier, database key, Session identifier, Experiment identifier, or Controller identifier. It is only the runtime identity of one emitted Health Observation.

```text
Health Observation
        |
Observation evidence
        |
Health Interpretation Evidence
```

Multiple interpretation records must not reference the same runtime observation unless a future architecture decision explicitly introduces multi-stage interpretation. Under the current architecture, one observation produces at most one interpretation evidence record.

This decision does not define identifier format, UUID versus integer representation, persistence implementation, storage layout, or Controller behavior. It defines only the required provenance relationship.

**Principle**

```text
Every runtime interpretation explicitly identifies
the runtime observation it interpreted.
```

---

## Decision 110: AcquisitionHealthPolicy definitions are Session-scoped configuration and Experiment-scoped assignment

**Status:** Accepted

`AcquisitionHealthPolicy` definitions belong to `SessionConfig`. They represent the set of acquisition-health policies available during a Session.

An `ExperimentRuntimeHealthMapping` assigns one of those policy definitions to a live source for the currently active Experiment.

```text
SessionConfig
    owns AcquisitionHealthPolicy definitions

            |
            v

ExperimentRuntimeHealthMapping
    assigns AcquisitionHealthPolicy
    to one live source

            |
            v

AcquisitionNode
    executes the assigned policy
```

Policy definition and policy assignment are distinct. One Session may contain multiple policy definitions, and the same live source may receive different policy assignments in different Experiments within that Session.

```text
SessionConfig
    soft_camera
    critical_camera

Experiment A
    camera_001 -> soft_camera

Experiment B
    camera_001 -> critical_camera
```

Policy definitions are persistent Session configuration. Policy assignments are runtime Experiment intent.

The Controller or equivalent orchestration layer is responsible for making configured policy definitions available to `AcquisitionNode` together with the active `ExperimentRuntimeHealthMapping`.

Evaluator-specific parameters required to execute an evaluation rule, such as `record_kind` for first-record evaluation, belong inside the appropriate `evaluation` section of the `AcquisitionHealthPolicy` definition. They are evaluation parameters, not device identity or policy assignment. This introduces no new evaluator capability model.

**Clarified by Decision 111:** The appropriate evaluation section is the named rule-specific substructure within `evaluation_rules`.

This decision defines ownership only. It does not define Controller implementation, transport mechanism, serialization format, runtime caching, or policy execution semantics.

**Principle**

```text
Policy definition is Session-scoped configuration.

Policy assignment is Experiment-scoped runtime intent.
```

---

## Decision 111: AcquisitionHealthPolicy evaluation uses rule-specific substructures

**Status:** Accepted

`AcquisitionHealthPolicy` remains a plain-data policy definition. Its evaluation portion is organized into independent evaluation rules rather than a flat collection of unrelated parameters.

Each evaluation rule owns only the parameters required for that rule.

```text
AcquisitionHealthPolicy

    policy_id

    evaluation_rules

        first_evidence
            ...

        gap
            ...

        rate
            ...

        future rule names...

    interpretation
```

For example:

```text
AcquisitionHealthPolicy

    policy_id: critical_camera

    evaluation_rules:

        first_evidence:
            record_kind: camera_frame_metadata
            grace_window_s: 2.0

        gap:
            record_kind: camera_frame_metadata
            max_gap_s: 1.0

        rate:
            record_kind: camera_frame_metadata
            minimum_rate_hz: 25

    interpretation:

        first_evidence_missing: experiment_failure
        frame_gap: warning
        frame_rate_low: warning
```

Evaluation rules represent independent health-evaluation algorithms. Each rule owns the parameters needed to evaluate the observation family it produces. Future participant types may introduce additional evaluation rules without changing the top-level policy schema.

This decision supersedes the flat `evaluation` parameter structure introduced in Decision 106. It does not change policy ownership, assignment, interpretation ownership, or framework-action boundaries.

**Principle**

```text
Evaluation parameters belong to
the evaluation rule that uses them.

Evaluation rules own parameters.

Policies own evaluation rules.

Assignments own policies.
```

---

## Decision 112: Controller records evidence-only action decisions for explicitly presented health interpretations

**Status:** Accepted

Controller owns decisions derived from `HealthInterpretationEvidence` when that evidence is explicitly presented to it.

For each presented interpretation, Controller produces exactly one immutable plain-data `ControllerActionDecision` and records it as Controller evidence.

```text
ExperimentScopedHealthObservation
        |
HealthInterpretationEvidence
        |
Controller
        |
ControllerActionDecision
```

Phase 8a maps interpretation labels to evidence-only decisions:

**Superseded in vocabulary by Decision 114:** The Phase 8 labels below are retained as historical context; current local decision names are defined by Decision 114.

```text
informational       -> record_only
uninterpreted       -> record_only
warning             -> record_warning_decision
recoverable_failure -> record_recoverable_failure_decision
experiment_failure  -> record_experiment_failure_decision
session_failure     -> record_session_failure_decision
```

These decisions preserve interpretation and originating-observation provenance but do not mutate Session, Experiment, AcquisitionNode, DeviceManager, or SynchronizationManager lifecycle or runtime state.

This decision does not define evidence delivery, polling, callbacks, subscriptions, event buses, transport, aggregation, distributed coordination, lifecycle consequences, retry, recovery, notification, operator acknowledgement, or GUI behavior.

**Principle**

```text
Health interpretation explicitly presented
        |
Controller records one action decision
        |
Framework consequence remains separate
```

---

## Decision 113: Controller executes Experiment- and Session-failure action decisions through existing lifecycle owners

**Status:** Accepted

**Superseded in vocabulary by Decision 114:** The lifecycle ownership and behavior remain accepted; the current decision names are `experiment_fail` and `session_fail`.

Experiment lifecycle terminal events are distinct: `experiment_stop` records normal completion, `experiment_fail` records unexpected Experiment-level framework or runtime failure, and `experiment_abort` is reserved for future intentional early termination and is not implemented in Phase 8b.

Controller executes `record_experiment_failure_decision` by asking Session to record canonical `experiment_fail` evidence, ending the active Experiment, and clearing the active Experiment runtime health mapping from both Controller and AcquisitionNode.

Experiment failure does not fail or stop the Session and does not stop Acquisition Runtime.

Controller executes `record_session_failure_decision` through its existing failed-Session path: Acquisition Runtime cleanup is attempted and Session transitions through its accepted stopping/failed lifecycle. No new cleanup semantics are introduced.

This decision does not introduce `experiment_abort`, a generic Experiment end-reason field, notification, retry, recovery, distributed delivery, aggregation, polling, callbacks, or event buses.

**Principle**

```text
Experiment failure
    ends the active Experiment
    but does not imply Session failure.

Session failure
    uses the existing failed-Session cleanup path.
```

---

## Decision 114: ControllerActionDecision uses normalized local execution vocabulary

**Status:** Accepted

Controller maps health interpretations to the following local decision vocabulary:

```text
informational       -> record_only
uninterpreted       -> record_only
warning             -> record_warning
recoverable_failure -> record_recoverable_failure
experiment_failure  -> experiment_fail
session_failure     -> session_fail
```

`record_only`, `record_warning`, `record_recoverable_failure`, and `operator_required` are successful local executions that record decision evidence without lifecycle mutation.

`experiment_fail` records canonical `experiment_fail` evidence, ends only the active Experiment, clears its runtime health mapping, and leaves Session running.

`session_fail` uses the existing failed-Session lifecycle and cleanup path.

This decision normalizes the Phase 8 decision labels. It does not introduce distributed delivery, notification, retry, recovery, aggregation, GUI behavior, or `experiment_abort`.

**Principle**

```text
ControllerActionDecision names the local decision directly.
Evidence-only decisions succeed without lifecycle mutation.
Failure decisions use their already accepted lifecycle owners.
```



## Decision 115: The framework uses a brokered runtime messaging architecture

**Status:** Accepted

The framework uses a brokered messaging architecture for runtime communication.

Runtime components communicate through the messaging infrastructure rather than establishing direct peer-to-peer communication.

The messaging infrastructure acts as the communication hub.

The Controller is a messaging client, not the communication hub.

This architecture allows components to be independently deployed, restarted, replaced, and extended without changing communication topology.

---

## Decision 116: NATS is the runtime transport layer

**Status:** Accepted

NATS is the runtime transport layer for the Lab Sync Acquisition framework.

NATS is responsible only for transporting runtime messages.

NATS does not own:

- Session Time
- scientific timing
- lifecycle semantics
- evidence interpretation
- storage
- scientific data ownership

Transport remains independent from scientific meaning.

---

## Decision 117: Runtime communication is classified by delivery requirements

**Status:** Accepted

The framework defines three runtime communication classes.

### JetStream Commands

Critical runtime commands use JetStream.

Examples include:

- start_session
- stop_session
- start_experiment
- stop_experiment
- abort
- validation requests

Command messages are:

- durable
- acknowledged
- idempotent
- reliably delivered

### JetStream Evidence

Evidence messages use JetStream.

Examples include:

- lifecycle evidence
- HealthInterpretationEvidence
- ControllerActionDecision
- action outcome evidence
- artifact manifests
- storage warnings

Loss of evidence is not acceptable.

### Core NATS Telemetry

Transient runtime telemetry uses Core NATS.

Examples include:

- GUI previews
- cursor display
- neuron activity preview
- live monitoring
- debug visualization
- heartbeat display

Telemetry is best effort.

Loss of transient telemetry is acceptable.

---

## Decision 118: Runtime communication is separated from artifact transfer

**Status:** Accepted

The framework separates runtime communication from artifact transfer.

### Runtime Communication Plane

Uses NATS.

Carries:

- commands
- acknowledgements
- lifecycle
- health
- evidence
- metadata
- synchronization records
- manifests
- transient telemetry

### Artifact Transfer Plane

Does not use NATS.

Responsible for transferring large scientific artifacts after acquisition.

---

## Decision 119: Large scientific artifacts are never transported through NATS

**Status:** Accepted

Large scientific artifacts remain local during acquisition.

Examples include:

- microscope recordings
- camera recordings
- Neuropixels/Open Ephys recordings
- other large binary scientific artifacts

Large artifacts are transferred later through the artifact transfer workflow.

NATS is never used as the transport path for these artifacts.

---

## Decision 120: Persistent scientific data remain local while runtime telemetry may be streamed

**Status:** Accepted

The authoritative scientific record is always the locally stored acquisition data.

Persistent scientific data are stored locally by the producing AcquisitionNode during acquisition.

Future artifact transfer retrieves these authoritative data after acquisition.

NATS may transport selected low-rate runtime telemetry for:

- GUI visualization
- online monitoring
- online processing
- debugging

Telemetry transported through NATS is not the authoritative scientific record.

---

## Decision 121: Artifact transfer is pull-based

**Status:** Accepted

AcquisitionNodes publish artifact manifests.

Phase 12 Decision 201 supersedes the ownership implication of this sentence: LocalStorageManager exclusively owns and persists the authoritative local ArtifactManifest. AcquisitionNode remains the orchestration-facing collaborator and does not become the manifest owner.

AcquisitionNodes never initiate artifact transfer.

Artifact transfer is initiated by the storage/transfer side.

This architecture separates acquisition from storage consolidation and allows transfer scheduling independently from acquisition.

---

## Decision 122: Transport does not define scientific time

**Status:** Accepted

Scientific timing is independent of the runtime transport.

Transport latency, message ordering, and message arrival time never define scientific time.

Scientific timing remains part of the scientific data and synchronization architecture.

---

## Decision 123: The NATS server is laboratory infrastructure

**Status:** Accepted

The NATS server is laboratory infrastructure.

The expected deployment is on the laboratory Overlord PC.

The Overlord PC is a deployment role only.

Deployment location does not define architectural ownership.

---

## Decision 124: Communication failures are framework failures

**Status:** Accepted

NATS is required for coordinated runtime operation.

If NATS is unavailable before a Session begins:

- the Session cannot start.

If NATS becomes unavailable during a Session:

- communication failure handling begins
- components preserve local evidence
- the Controller determines the resulting framework actions

The detailed recovery policy remains future work.

---

## Decision 125: Deployment topology does not define ownership

**Status:** Accepted

Framework ownership is independent of deployment topology.

Components may execute on the same machine or on separate machines without changing architectural ownership.

Examples include:

- Controller
- GUI
- Ingestor
- StorageManager
- NATS

Deployment decisions must not introduce hidden architectural dependencies.

---

## Decision 126: Runtime communication follows a hub-and-spoke topology

**Status:** Accepted

Runtime communication follows a hub-and-spoke architecture.

Components communicate through NATS.

Components should not establish hidden direct communication paths simply because they execute on the same machine.

Communication follows explicit transport boundaries rather than deployment topology.

The default communication pattern is:

- Commands
    - Controller → AcquisitionNode(s)

- Evidence
    - AcquisitionNode(s), Controller → Ingestor

- Telemetry
    - Publishers → Any interested subscribers

The Ingestor is the canonical consumer of durable evidence.

The GUI is a consumer of transient telemetry.

The Controller is a consumer of runtime status and a producer of commands.

The communication topology is independent of physical deployment.

---

## Decision 127

NATS communication is owned by a communication boundary, not by domain components.

Domain components produce and consume plain framework records.

The communication boundary serializes, publishes, subscribes, acknowledges, and reconstructs those records across NATS.

NATS subjects and streams route messages but do not define lifecycle ownership, Session Time, evidence meaning, or artifact storage.

## Decision 128

Phase 10 v1 uses minimal message envelopes.

Command message:

```
command_id
session_id
command_type
source_id
target_id
payload
```

Command result:

```
result_id
command_id
session_id
source_id
target_id
status
success
reason
payload
```

Evidence message:

```
evidence_id
session_id
evidence_type
source_id
payload
```

Telemetry message:

```
session_id
telemetry_type
source_id
payload
```

No separate idempotency key, causation chain, schema registry, global correlation model, or exhaustive provenance envelope is introduced in v1.

## Decision 129

Phase 10 subject hierarchy is message-rooted, Session-scoped, and routing-only.

Subjects use:

```
messages.<session_id>.<message_class>.<component_type>.<component_id>.<message_type>
```

Allowed message_class values:

```
command
command_result
evidence
telemetry
```

The root `messages` identifies Lab Sync Acquisition runtime messages on the NATS broker.

The `session_id` remains in the subject because Session is the runtime evidence boundary.

Subjects route messages only. They do not encode physical machine location, deployment topology, ownership, lifecycle semantics, Session Time, command success, evidence meaning, artifact storage, or scientific validity.

## Decision 130

Phase 10 separates durable message classes into distinct JetStream streams.

JetStream streams:

```
LAB_COMMANDS
    messages.*.command.>

LAB_COMMAND_RESULTS
    messages.*.command_result.>

LAB_EVIDENCE
    messages.*.evidence.>
```

Telemetry subjects are not stored in JetStream:

```
messages.*.telemetry.>
```

Telemetry uses Core NATS only.

Commands, command results, and evidence do not share one durable stream in v1.

## Decision 131

Consumers follow existing component ownership.

Command consumers are target components.

Command-result consumers are command issuers.

Evidence consumers are separated by responsibility.

The Ingestor is the canonical preservation consumer for durable evidence.

The Controller may also consume selected evidence types when that evidence requires Controller decision-making, such as HealthInterpretationEvidence.

The Controller is not the evidence archive.

Telemetry consumers are GUI and monitoring clients.

Consumers do not gain ownership of a domain concept merely because they subscribe to its messages.

## Decision 132

Command delivery uses transport acknowledgement plus explicit command result.

JetStream publish acknowledgement means only that NATS accepted the message into the durable stream.

It does not mean the target component executed the command.

Every durable command must produce a command_result message.

Command success is represented only by command_result evidence, not by NATS delivery acknowledgement.

Lifecycle mutation remains owned by the target domain component, not by NATS.

## Decision 133

Command results use a shared status vocabulary with Phase-specific allowed subsets.

Command result status vocabulary:

```
accepted
progress
succeeded
failed
```

For Phase 10 runtime control commands, only final statuses are used:

```
succeeded
failed
```

A runtime control command_result is published after the target component finishes processing the command.

accepted and progress are reserved for future long-running command families, such as artifact transfer, reconstruction, or upload workflows.

## Decision 134

Commands target either one component or one component group.

A unicast command targets one component, and only that component executes it.

A group command targets a component group, such as all AcquisitionNodes in a Session.

Each eligible component in that group may execute the command.

Each executing component publishes its own command_result.

Brokered communication is preserved because commands still move through NATS.

A group command is not one shared lifecycle mutation. It is one command intent fan-out with separate execution outcomes from each participating component.

## Decision 135

Group command aggregation belongs to the command issuer.

A group command may produce zero, one, or many command_result messages.

Each executing component reports only its own result.

NATS does not aggregate group command results.

The target components do not decide the group-level outcome.

The command issuer, usually Controller, interprets returned command_results and decides whether the group command succeeded, failed, timed out, or requires operator action.

## Decision 136

Missing command results are interpreted by the command issuer.

A command may have an expected result window defined by the command issuer.

If no command_result is received within that window, the missing result is recorded as unresolved command outcome evidence.

A missing result is not automatically equivalent to target failure, Session failure, Experiment failure, or command failure.

NATS does not infer failure from missing command_result messages.

## Decision 137

Command receivers use command_id for duplicate detection.

Every command has a command_id.

If a target component receives the same command_id more than once, it must not execute the command more than once.

The target component may republish the previous command_result for that command_id.

Duplicate detection is local to the receiving component.

For Phase 10, command_id is sufficient. No separate idempotency_key is introduced.

## Decision 138

Runtime communication identifies components by type and identifier.

Every communicating runtime component has:

```
component_type
component_id
```

component_type identifies the architectural role.

component_id uniquely identifies one runtime instance of that role within the deployment.

Component identity is independent of physical computer, network address, operating system, deployment topology, and laboratory location.

Component identity is used for message routing and execution ownership only.

It does not imply ownership of Session, Experiment, Session Time, or any other architectural concept.

## Decision 139

SessionConfig is the authoritative source of expected runtime participants.

Controller determines expected runtime participants from the accepted SessionConfig.

Phase 10 does not introduce runtime discovery or a dynamic service registry.

If an expected participant does not respond to the relevant command or readiness request, that absence is recorded as unresolved command outcome evidence and surfaced to the operator.

Runtime availability may be observed in the future, but it does not replace SessionConfig as the source of expected participation.

## Decision 140

NATS carries readiness requests but does not redefine readiness.

Before Session start, Controller may issue readiness-related commands to expected runtime participants over NATS.

The responding component runs its existing readiness logic and returns existing readiness evidence in the command_result payload.

NATS does not define a separate readiness model.

Missing readiness command_results are recorded as unresolved command outcome evidence and surfaced to the operator.

Session readiness gating remains owned by Session using readiness evidence from the accepted readiness contracts.

## Decision 141

NATS availability is required communication readiness before distributed Session start.

For a distributed Session, NATS availability must be checked before Session start.

If NATS is unavailable before Session start, the distributed Session cannot start.

The failure is recorded as communication readiness evidence and surfaced to the operator.

NATS availability does not replace device readiness, service readiness, storage readiness, or Session readiness gating.

NATS does not own readiness. It only provides communication capability.

## Decision 142

NATS unavailability during a Session creates communication-failure evidence, not automatic lifecycle mutation.

If NATS becomes unavailable during a running Session, components that detect the failure record local communication-failure evidence when possible.

AcquisitionNodes continue following their existing local safety and evidence preservation rules.

NATS unavailability does not automatically fail the Session, fail the active Experiment, stop Acquisition Runtime, or discard evidence.

Controller decides any lifecycle consequence after communication state is known or restored.

Reconnect, retry, replay, and operator-intervention policy remain future communication-failure recovery work.

## Decision 143

Durable message producers retain ownership until successful publication.

When a component produces a durable command_result or evidence message, that component remains responsible for preserving the message until it has been successfully published to JetStream.

Failure to publish does not transfer ownership to NATS or any other component.

The message must not be discarded solely because communication is unavailable.

How unpublished messages are buffered, retried, replayed, or recovered is implementation detail and future communication-failure recovery architecture.

Phase 10 defines only the ownership boundary.

## Decision 144

Durable publication success means JetStream stream acceptance.

For durable message classes, publication is considered successful only when JetStream confirms that the message was accepted into the intended stream.

JetStream acceptance means the transport layer durably accepted the message.

It does not mean a consumer processed the message, a command executed successfully, Controller acted on evidence, Ingestor archived evidence, or StorageManager persisted the Session Record.

Downstream outcomes must be represented by separate command_result, evidence, ingest audit, or storage evidence according to the responsible component's ownership.

## Decision 145

Durable evidence is published once and consumed independently.

A component that produces durable evidence publishes it once to the appropriate JetStream evidence subject.

Multiple components may independently consume the same evidence according to their existing responsibilities.

Controller consumes evidence that requires Controller decision-making.

Ingestor consumes durable evidence for preservation as part of the Session Record.

Components do not relay, forward, or republish evidence on behalf of other components.

NATS is the communication hub.

## Decision 146

Telemetry is transient, real-time, display-oriented, and non-authoritative.

Telemetry messages use Core NATS subjects only:

```
messages.<session_id>.telemetry.<component_type>.<component_id>.<telemetry_type>
```

Telemetry may be consumed by GUI, monitoring tools, or debugging tools.

Telemetry can be real-time.

Telemetry loss is acceptable.

Telemetry is not evidence.

Telemetry is not authoritative scientific data.

Telemetry may contain display/preview data such as cursor position, selected neuron preview, live visualization summaries, heartbeat display, or monitoring information.

Telemetry does not require command_result, ingest audit, storage preservation, or replay.

A component must not make lifecycle, Session, Experiment, or scientific-validity decisions based only on telemetry.

## Decision 147

Artifact manifests are artifact-level durable evidence, not acquisition-event evidence.

Artifact manifests describe artifact lifecycle boundaries.

They are not emitted per sample, frame, image, event, or acquisition row.

Typical manifest moments:

```
artifact planned/opened
artifact closed/finalized
artifact failed/incomplete
artifact transferred/verified later
```

Artifact manifests support discovery, audit, later pull-based transfer, and reconstruction.

During acquisition, scientific data and timing records are written locally by the producing component.

NATS carries artifact manifests, health/status evidence, lifecycle evidence, command outcomes, and telemetry, but not artifact bytes or per-frame scientific data streams.

The Ingestor may consume artifact manifests and runtime evidence, but it is not the required online path for every scientific data row.

## Decision 148

Ingestor is the runtime evidence intake, not the universal scientific data pipe.

Ingestor consumes and audits durable runtime messages such as:

```
lifecycle evidence
health evidence
ControllerActionDecision evidence
command_result evidence
artifact manifests
storage/transfer evidence
lightweight metadata
```

Ingestor is not required to receive every scientific sample, frame, image, continuous data row, or large artifact byte during acquisition.

Scientific data may be written locally by the producing component and later included in the Session Record through artifact manifests and pull-based transfer.

This clarifies and narrows earlier acquisition-envelope/ingestion assumptions for large-artifact workflows.

The Ingestor remains responsible for evidence intake and audit, but not for being the online transport path for all scientific data.

## Decision 149

During acquisition, only runtime communication and display telemetry remain on the Control Plane.

During active acquisition, NATS communication is limited to runtime information required for coordination, monitoring, and display.

Typical runtime messages include:

```
commands
command_results
health evidence
lifecycle evidence
status updates
warnings/failures
artifact lifecycle manifests
telemetry for real-time display/preview
synchronization messages in a future phase
```

Scientific data, timing records, and large artifacts remain local to the producing component until artifact transfer.

Telemetry may be real-time, but it is display/monitoring data, not authoritative scientific data.

Runtime communication supports orchestration and observation, not scientific data transport.

## Decision 150: SynchronizationManager owns Session Time

**Status:** Accepted

The SynchronizationManager owns scientific Session Time.

Session Time is the master scientific timebase for a Session.

No AcquisitionNode, GUI, Controller, Ingestor, StorageManager, transport layer, local machine clock, or DeviceAdapter owns or defines Session Time.

Components may use Session Time only by receiving it from the SynchronizationManager or by applying an explicit SynchronizationManager-authorized mapping.

**Principle**

```text
One Session Time.
One owner.
SynchronizationManager owns it.
```

## Decision 151: Experiment Time is derived from Session Time

**Status:** Accepted

Experiment Time is not an independent clock.

Experiment Time is derived from Session Time using the Session Time at which the Experiment started.

Conceptually:

```text
experiment_time_s =
    session_time_s - experiment_start_session_time_s
```

The Session records `experiment_start_session_time_s`.

The Controller owns Experiment lifecycle and records the canonical Experiment start evidence. AcquisitionNode may use the active Experiment start Session Time to attach `experiment_time_s` to acquired records.

Session Time remains necessary to align data across the whole Session, including warmup, validation, inter-Experiment periods, and multiple Experiments.

## Decision 152: AcquisitionNode local clocks are not reset to Session Time

**Status:** Accepted

An AcquisitionNode may have one local monotonic runtime clock.

The AcquisitionNode local clock must not be reset to match Session Time.

Instead, synchronization updates adjust the relationship between:

```text
AcquisitionNode local time
        <->
Session Time
```

The local clock remains monotonic and auditable.

DeviceAdapters do not maintain independent Session-Time mappings in Phase 11.

## Decision 153: Acquired data carry analysis-ready timing

**Status:** Accepted

Each acquired data record should carry analysis-ready scientific timing whenever practical.

Minimum normal timing fields:

```text
session_time_s
experiment_time_s, when an Experiment is active
```

Normal analysis should not require reconstructing basic timestamps for every row.

Timing belongs primarily with the data records it describes.

## Decision 154: Timing audit evidence is preserved

**Status:** Accepted

In addition to analysis-ready timing, the framework preserves timing audit evidence.

Examples include:

```text
acquisition_node_local_time_s
timestamp_status
synchronization update evidence
mapping/correction evidence
device-native timing evidence, when provided
```

Timing audit evidence supports validation, drift assessment, debugging, reconstruction, and scientific interpretation.

These fields may be stored directly with data rows when practical or as associated timing records when cleaner.

## Decision 155: Runtime timing is the primary timing path

**Status:** Accepted

Data are stored immediately with the best current runtime timing.

Runtime timestamps are not silently rewritten.

Offline reconstruction may validate timing and may produce refined derived timing outputs, but reconstructed timing must remain distinguishable from runtime timing.

Conceptually, derived outputs may contain fields such as:

```text
session_time_s_runtime
session_time_s_reconstructed
experiment_time_s_runtime
experiment_time_s_reconstructed
```

or an equivalent representation.

## Decision 156: Synchronization cadence and tolerance are configurable

**Status:** Accepted

Synchronization cadence is configurable.

Missed-synchronization tolerance and drift/correction thresholds are configurable.

These values are not hard-coded architectural constants.

The accepted Session configuration determines the synchronization cadence, missed-update tolerance, acceptable correction magnitude, acceptable drift, and timing-degradation thresholds.

## Decision 157: Transport timestamps are not scientific time

**Status:** Accepted

NATS timestamps, message arrival times, broker times, wall-clock times, and ingest times are not scientific Session Time.

Transport may deliver synchronization records, but transport does not define time.

Scientific timing comes only from the SynchronizationManager or from explicit SynchronizationManager-authorized timing mappings.

## Decision 158: Timing records are part of the scientific record

**Status:** Accepted

Synchronization updates, local-to-Session timing evidence, timestamp-status records, drift evidence, rejected synchronization updates, and timing-quality evidence are part of the scientific record.

They must be preserved with the same seriousness as stream, event, and artifact timing.

They support audit, reconstruction, and scientific interpretation of timing accuracy.

## Decision 159: Reconstruction audits timing but does not replace runtime evidence

**Status:** Accepted

Reconstruction may validate timing consistency, estimate drift, flag degraded intervals, and produce refined derived timing.

Reconstruction must not silently mutate raw runtime timestamps.

Raw runtime timing evidence remains preserved.

Any reconstructed or refined timing is derived evidence and remains distinguishable from runtime timing.

## Decision 160: Timing quality policy is experimenter-configured

**Status:** Accepted

Timing failure behavior is policy-defined, not hard-coded.

Timing quality follows the same ownership pattern as acquisition health:

```text
Timing condition detected
        ->
TimingQualityObservation
        ->
TimingQualityPolicy interpretation
        ->
TimingQualityInterpretationEvidence
        ->
ControllerActionDecision
```

SynchronizationManager and AcquisitionNode may detect timing conditions.

TimingQualityPolicy interprets detected timing conditions.

Controller decides and executes any framework consequence.

Example configured interpretations:

```text
camera timing degraded for 5 s        -> warning
microscope timing degraded for 5 s    -> experiment_failure
Session master clock unavailable      -> session_failure
```

Supported timing interpretation labels should mirror the accepted operational vocabulary:

```text
informational
warning
recoverable_failure
experiment_failure
session_failure
operator_required
uninterpreted
```

## Decision 161: Timing-quality detection ownership

**Status:** Accepted

**Clarified by Decisions 168 and 171:** SynchronizationManager owns mapping
validation, drift estimation, and remapping decisions. AcquisitionNode may
report local-time samples and detect degraded local application state,
but it does not validate mappings, estimate drift, or decide to remap.

SynchronizationManager detects timing conditions related to the Session Time authority.

Examples include:

```text
Session Time unavailable
synchronization update cannot be produced
authoritative clock degraded
master timing source unavailable
```

AcquisitionNode detects timing conditions related to local runtime timestamping.

Examples include:

```text
missed synchronization update
stale timing mapping
excessive correction
excessive drift
rejected synchronization update
degraded timestamp status while recording data
```

Both may emit TimingQualityObservation evidence.

DeviceAdapters do not detect Phase 11 timing-quality failures. They may expose device-native timing evidence only.

## Decision 162: AcquisitionNode validates synchronization updates before applying them

**Status:** Accepted

**Superseded by Decisions 168 and 171:** SynchronizationManager now owns creation,
validation, activation, replacement, retirement, drift estimation, and the
decision to remap. AcquisitionNode receives and applies the active immutable
mapping locally without validating or modifying it. The prospective,
non-retroactive timing guarantees remain authoritative.

An AcquisitionNode does not blindly accept every synchronization update.

A received synchronization update is validated before it becomes the active timing mapping.

Validation may include:

```text
session_id matches current Session
SynchronizationManager identity is expected
Session Time is monotonic
AcquisitionNode local time is monotonic
correction magnitude is within configured tolerance
drift estimate is within configured tolerance
```

If the update is accepted, the AcquisitionNode atomically replaces its current timing mapping.

If the update is rejected, the AcquisitionNode preserves the previous mapping, records the rejected update as timing evidence, emits TimingQualityObservation evidence, and continues according to the configured timing policy.

The framework does not assume that the global update is always correct; it preserves evidence when the apparent drift could come from either the local clock or the Session Time authority.

## Decision 163: Synchronization mapping replacement is atomic and prospective

**Status:** Accepted

Synchronization mapping replacement is atomic from the AcquisitionNode's point of view.

A newly accepted synchronization update affects only subsequently acquired records.

Previously timestamped records are never modified during runtime.

Rejected or superseded mappings remain auditable timing evidence.

This preserves deterministic runtime timestamping and prevents silent retroactive correction.

## Decision 164: AcquisitionNode owns runtime timestamping

**Status:** Accepted

DeviceAdapters produce or expose acquisition records.

DeviceManager collects those records.

AcquisitionNode attaches framework scientific timing to collected records.

The AcquisitionNode attaches:

```text
session_time_s
experiment_time_s, when an Experiment is active
acquisition_node_local_time_s
timestamp_status
```

DeviceAdapters do not need to know Session Time.

DeviceAdapters do not apply synchronization mappings.

DeviceAdapters do not derive Experiment Time.

## Decision 165: Device-native timing is preserved but not interpreted online

**Status:** Accepted

Some devices may expose device-native timing evidence.

Examples include:

```text
frame_index
sample_index
device_timestamp
hardware_counter
dropped-frame flag
dropped-sample flag
```

Phase 11 preserves these values unchanged when available.

Phase 11 does not synchronize, drift-correct, or interpret device-native clocks online.

Device-native timing evidence is stored for audit, debugging, reconstruction, and future export.

## Decision 166: Scientific timing and device-native timing are separate concepts

**Status:** Accepted

The framework distinguishes scientific timing from device-native timing.

Scientific timing is framework-owned and interpreted by the synchronization architecture.

Device-native timing is produced by the device, preserved by the framework, and interpreted only when needed by future reconstruction, validation, or export.

```text
Scientific timing
    owned/interpreted by framework

Device-native timing
    owned by producing device
    preserved unchanged
    not interpreted online in Phase 11
```

This prevents AcquisitionNode from becoming a multi-device clock-reconstruction engine.

## Decision 167: Active Experiment timing reaches AcquisitionNode as runtime context

**Status:** Accepted

Controller owns canonical Experiment lifecycle orchestration and records `experiment_start` evidence in the Session timeline using Session Time.

AcquisitionNode does not own Experiment lifecycle, but it may need the active Experiment start Session Time to derive Experiment Time for local runtime evidence.

Therefore, when Controller starts an Experiment, it must provide AcquisitionNode with explicit active Experiment runtime context containing:

- `experiment_id`
- `experiment_start_session_time_s`

This handoff is separate from `ExperimentRuntimeHealthMapping`.

`ExperimentRuntimeHealthMapping` continues to contain only Experiment-scoped health scope and policy assignment. It must not be overloaded with lifecycle timing.

AcquisitionNode stores the active Experiment runtime context only while that Experiment is active. It may use it to compute:

```text
experiment_time_s = session_time_s - experiment_start_session_time_s
```

for AcquisitionNode-owned runtime evidence.

AcquisitionNode must not reinterpret, create, or mutate canonical Experiment lifecycle evidence. Canonical Experiment lifecycle remains Controller-owned and Session-recorded.

When the active Experiment stops or fails, Controller clears both:

- the active Experiment runtime context
- the active Experiment runtime health mapping

**Principle**

```text
Experiment lifecycle timing is Controller/Session evidence.

Experiment runtime timing context is handed to AcquisitionNode explicitly.

Health mapping remains health mapping only.
```

## Decision 168: SynchronizationManager owns active synchronization mappings

**Status:** Accepted

SynchronizationManager is the sole owner of active SynchronizationMappings.

Only SynchronizationManager may:

- create a new mapping
- activate a mapping
- replace the active mapping
- retire a mapping

AcquisitionNode must never create, modify, validate, or activate mappings.

AcquisitionNode receives the active mapping from SynchronizationManager and applies it locally.

Synchronization mappings are immutable after activation.

Mapping updates occur by atomically replacing the active mapping.

The synchronization algorithm itself remains an implementation detail of SynchronizationManager.

## Decision 169: SynchronizationManager decides when remapping is required

**Status:** Accepted

**Superseded by Decision 171:** AcquisitionNode reports local-time samples but
does not produce SynchronizationObservation evidence. SynchronizationManager
creates that evidence from the reports and retains ownership of drift
estimation and remapping decisions.

AcquisitionNode periodically, or when requested, produces synchronization observations containing its local acquisition-node time.

SynchronizationManager consumes these observations.

SynchronizationManager performs drift estimation.

SynchronizationManager alone decides whether the current mapping should be replaced.

If remapping is required, SynchronizationManager creates a new immutable mapping and distributes it to AcquisitionNode.

AcquisitionNode never decides when remapping is needed.

## Decision 170: Mapping updates are runtime timing evidence

**Status:** Accepted

Mapping creation/replacement is scientific runtime timing evidence.

SynchronizationManager preserves mapping update information.

Mapping replacement is not hidden runtime state.

Mapping updates never modify previously timestamped runtime evidence.

We explicitly decided not to store a mapping identifier on every acquired row.

## Decision 171: SynchronizationManager creates SynchronizationObservation evidence

**Status:** Accepted

AcquisitionNode does not produce SynchronizationObservation evidence.

AcquisitionNode reports AcquisitionNode local-time samples to SynchronizationManager periodically or when requested.

SynchronizationManager creates SynchronizationObservation evidence from those local-time reports because SynchronizationObservation is synchronization evidence used for drift estimation and remapping.

SynchronizationManager owns:

- Session Time
- creation of SynchronizationObservation evidence
- drift estimation
- remapping decisions
- SynchronizationMapping creation
- mapping validation
- mapping activation
- mapping replacement
- mapping retirement
- MappingUpdateEvidence

AcquisitionNode owns only:

- reporting local AcquisitionNode time samples
- receiving the active immutable SynchronizationMapping
- applying that mapping prospectively to newly acquired records
- attaching Runtime Timing to records
- preserving timestamp status and local timing-quality evidence

Existing `session_time_s` values remain unchanged.

Runtime Timing remains immutable. Reconstruction may later produce separate Reconstructed Timing but must not silently rewrite Runtime Timing.

No drift model or timing-uncertainty model is defined by this decision.

## Decision 172: SynchronizationMapping is immutable SynchronizationManager-owned plain data

**Status:** Accepted

`SynchronizationMapping` is immutable plain data owned by SynchronizationManager.

Its minimum schema is:

```text
session_id
acquisition_node_id
local_time_anchor_s
session_time_anchor_s
scale
created_session_time_s
```

SynchronizationManager alone creates, validates, activates, replaces, and retires SynchronizationMappings.

AcquisitionNode receives the active immutable mapping and applies it prospectively without modifying or validating it.

The internal mathematical representation and detailed mapping algorithm remain unspecified in Phase 11 and remain open under Q006.

## Decision 173: AcquisitionNode local-time reports are not SynchronizationObservations

**Status:** Accepted

AcquisitionNode reports local-time samples to SynchronizationManager.

The minimum local-time report schema is:

```text
session_id
acquisition_node_id
acquisition_node_local_time_s
reported_reason
details
```

A local-time report is not SynchronizationObservation evidence.

SynchronizationManager decides whether a local-time report becomes SynchronizationObservation evidence and owns creation of that evidence.

## Decision 174: MappingUpdateEvidence records active mapping lifecycle changes

**Status:** Accepted

SynchronizationManager creates `MappingUpdateEvidence` whenever an active SynchronizationMapping is created, replaced, or retired.

Its minimum schema is:

```text
session_id
acquisition_node_id
update_type
previous_mapping, optional
new_mapping, optional
created_session_time_s
reason
details
```

MappingUpdateEvidence is scientific Runtime Timing evidence.

Mapping lifecycle changes are not hidden runtime state and never modify previously acquired records.

## Decision 175: MappingUpdateEvidence uses the existing runtime-evidence preservation path

**Status:** Accepted

MappingUpdateEvidence is preserved:

- in SynchronizationManager memory during runtime
- as `RuntimeEvidenceMessage`
- through the existing runtime-evidence ingestion path
- in the Session Record through the existing StorageManager finalization path

SynchronizationManager creates and owns MappingUpdateEvidence. Ingestor owns runtime-evidence intake and audit. StorageManager writes caller-supplied evidence during existing Session Record finalization.

No new timing-storage component is introduced.

## Decision 176: Synchronization mapping ownership handoff is explicit

**Status:** Accepted

AcquisitionNode reports local-time samples to SynchronizationManager.

SynchronizationManager:

- creates SynchronizationObservation evidence
- creates SynchronizationMappings
- validates mappings
- activates mappings
- replaces and retires mappings
- creates MappingUpdateEvidence
- performs drift estimation
- decides when remapping is required

AcquisitionNode:

- receives the active immutable SynchronizationMapping
- applies that mapping prospectively to newly acquired records
- does not create, validate, modify, activate, replace, or retire mappings
- does not create SynchronizationObservation or MappingUpdateEvidence
- does not estimate drift or decide when to remap

Runtime Timing remains immutable. Mapping updates never modify previously acquired records.

## Decision 177: MappingUpdateEvidence uses explicit runtime evidence type

**Status:** Accepted

`MappingUpdateEvidence` is preserved as durable runtime evidence using:

```text
evidence_type: mapping_update_evidence
```

The `RuntimeEvidenceMessage.payload` contains the plain-data form of the MappingUpdateEvidence.

Ownership remains unchanged:

```text
SynchronizationManager
    creates MappingUpdateEvidence

RuntimeEvidenceMessage
    carries the evidence through the communication boundary

Ingestor
    audits and preserves durable runtime evidence

StorageManager / Session Record
    preserves the accepted evidence
```

NATS carries the evidence but does not define timing meaning.

`mapping_update_evidence` is a runtime evidence type vocabulary value only.

It does not create:

- a new component
- a new transport path
- a new timing owner
- a new Session Record owner

## Phase 11 ownership chain

The accepted Phase 11 ownership chain is:

```text
SynchronizationManager
    owns Session Time
    owns active synchronization mappings
    receives AcquisitionNode local-time reports
    creates synchronization observation evidence
    performs drift estimation
    decides when remapping is required
    preserves mapping update evidence
    owns immutable plain-data mapping creation and lifecycle

Controller
    owns Experiment lifecycle
    records experiment_start_session_time_s

AcquisitionNode
    owns runtime timestamping
    reports local AcquisitionNode time samples
    receives and applies the active immutable mapping
    does not validate, modify, or activate mappings
    attaches session_time_s
    derives experiment_time_s
    records timing-quality observations

DeviceAdapter
    owns device communication
    may expose device-native timing evidence
    does not know Session Time

Storage
    preserves runtime timing
    preserves timing audit evidence
    preserves device-native timing unchanged

Reconstruction
    audits and may refine timing
    never mutates runtime timing evidence
```

The central Phase 11 principle is:

```text
Scientific timing is a framework concern.
Device-native timing is device evidence.
```

---

## Decision 178: Introduce a LocalStorageManager

**Status:** Accepted

Each AcquisitionNode owns one LocalStorageManager running on the same machine.

The LocalStorageManager exists specifically to avoid sending authoritative scientific data over the network during acquisition.

AcquisitionNode owns acquisition execution and runtime timestamping.

LocalStorageManager owns local persistence.

A LocalStorageManager must never be deployed remotely from the AcquisitionNode it serves.

---

## Decision 179: All acquired scientific data are timestamped

**Status:** Accepted

Framework-written scientific data store timing directly with every acquired record.

Required timing fields:

- `session_time_s`
- `experiment_time_s`
- `acquisition_node_local_time_s`
- `timestamp_status`

There is no untimestamped scientific data.

---

## Decision 180: Scientific data exist inside Experiments

**Status:** Accepted

Every scientific record therefore contains:

- `experiment_id`
- `experiment_time_s`

Session-level records outside Experiments remain runtime evidence, lifecycle evidence, timing evidence, health evidence, validation evidence, manifests, configuration, or telemetry.

---

## Decision 181: External scientific artifacts retain their original bytes

**Status:** Accepted

When external software or hardware writes scientific artifacts (TIFFs, videos, vendor files, future Neuropixels/Open Ephys files), the framework does not rewrite those bytes.

Instead it stores local framework timing/index information.

External software never owns scientific timing.

---

## Decision 182: LocalStorageManager owns local persistence for one AcquisitionNode

**Status:** Accepted

It may persist:

- framework scientific records
- timing/index streams
- artifact manifests
- local synchronization/timestamping records
- local storage evidence
- cleanup/finalization evidence

It does not own:

- acquisition execution
- Session Time
- SynchronizationManager authority
- Experiment lifecycle
- device communication
- artifact transfer
- reconstruction
- NWB export

---

## Decision 183: Artifact manifests are authoritative local discovery records

**Status:** Accepted

Artifact manifests are the authoritative local discovery records for later pull-based collection.

---

## Decision 184: Local completion is independent from global Session Record completion

**Status:** Accepted

Local completion is independent from global Session Record completion.

---

## Decision 185: Finalized local scientific records are immutable

**Status:** Accepted

Local scientific records become immutable after finalization.

Derived products must be created separately.

---

## Decision 186: Every local scientific record has exactly one LocalStorageManager owner

**Status:** Accepted

Every local scientific record has exactly one owning LocalStorageManager.

Only that LocalStorageManager owns creation and finalization of those records.

---

## Decision 187: Artifact transfer creates additional managed copies

**Status:** Accepted

Transfer never changes ownership of the original local scientific records.

Retention and cleanup remain separate policy decisions.

---

## Decision 188: LocalStorageManager is a runtime collaborator of AcquisitionNode

**Status:** Accepted

Caller/orchestration creates one LocalStorageManager per AcquisitionNode.

AcquisitionNode owns acquisition and timestamping.

LocalStorageManager owns local persistence.

---

## Decision 189: LocalStorageManager performs incremental writing

**Status:** Accepted

Scientific streams are opened before acquisition data flow and remain open during acquisition.

Data are appended incrementally.

Entire Experiments are never accumulated in memory before writing.

---

## Decision 190: Scientific stream metadata are written once

**Status:** Accepted

Scientific stream metadata are written once when the stream is created.

Subsequent writes reference the stream using a runtime `storage_id` and append only changing timestamped rows.

Stable metadata are not repeatedly transmitted.

---

## Decision 191: LocalStorageManager stores streams independently of payload meaning

**Status:** Accepted

The payload may represent:

- measured scientific data
- events
- frame/sample indices
- references into external artifacts

The storage mechanism is identical regardless of payload type.

---

## Decision 192: External-artifact timing uses the scientific stream abstraction

**Status:** Accepted

External-artifact timing/index information is stored using the same timestamped scientific stream abstraction.

The distinction between internal and external acquisition exists in the ArtifactManifest, not in the LocalStorageManager write path.

---

## Decision 193: ArtifactManifest describes all locally managed scientific artifacts

**Status:** Accepted

Framework-generated artifacts contain the LocalStorageManager path.

Externally generated artifacts contain:

- external artifact path
- LocalStorageManager-managed path(s)

Every ArtifactManifest contains:

- `experiment_id`
- `session_id`
- `acquisition_node_id`
- `source_component_id`
- artifact type
- lifecycle state

ArtifactManifest is created when the corresponding scientific stream is created.

It exists even if zero rows are ultimately written.

---

## Decision 194: LocalStorageManager finalization means only local completion

**Status:** Accepted

It does not imply:

- global Session Record completion
- artifact transfer
- reconstruction
- NWB export

---

## Decision 195: SynchronizationManager remains the synchronization-evidence owner

**Status:** Accepted

LocalStorageManager only persists synchronization-related information through explicit handoff.

---

## Decision 196: Future global StorageManager consumes finalized local discovery information

**Status:** Accepted

Future global StorageManager consumes:

- ArtifactManifest
- LocalStorageCompletionSummary
- local storage evidence

Original local scientific record ownership never transfers.

---

## Decision 197: Session creates LocalStorageManagers during initialization

**Status:** Accepted

Session creates one LocalStorageManager for each AcquisitionNode during Session initialization.

LocalStorageManager participates in readiness but does not own Session or Experiment lifecycle.

---

## Decision 198: Controller never communicates directly with LocalStorageManager

**Status:** Accepted

Experiment initialization flows:

```text
Controller
    -> AcquisitionNode
    -> LocalStorageManager
```

AcquisitionNode requests creation of all local scientific streams required for that Experiment.

---

## Decision 199: Stream creation separates scientific context from storage realization

**Status:** Accepted

LocalStorageManager requests scientific metadata from AcquisitionNode during stream creation.

AcquisitionNode provides scientific context.

LocalStorageManager provides storage realization.

ArtifactManifest is owned and persisted by LocalStorageManager.

---

## Decision 200: Internal and external acquisition share stream creation

**Status:** Accepted

Internal and external acquisition use identical local scientific stream creation.

The only architectural difference is the ArtifactManifest.

---

## Decision 201: ArtifactManifest is owned exclusively by LocalStorageManager

**Status:** Accepted

Scientific metadata are supplied by AcquisitionNode.

Storage metadata are supplied by LocalStorageManager.

This supersedes earlier wording in Decision 121 that assigned artifact-manifest publication directly to AcquisitionNode. AcquisitionNode remains the orchestration-facing collaborator, but LocalStorageManager is the authoritative owner of the local ArtifactManifest.

---

## Decision 202: storage_id and artifact_manifest_id are distinct

**Status:** Accepted

`storage_id`:

- runtime write handle
- exists through the local artifact lifecycle

`artifact_manifest_id`:

- durable discovery identity
- used for later collection/reconstruction/export

---

## Decision 203: AcquisitionNode translates Experiment requirements into stream creation

**Status:** Accepted

LocalStorageManager never discovers devices or required outputs.

---

## Decision 204: Streams are created during Experiment initialization

**Status:** Accepted

Local scientific streams are created during Experiment initialization before acquisition begins.

---

## Decision 205: LocalStorageManager buffering is bounded and batch-oriented

**Status:** Accepted

LocalStorageManager uses bounded buffering only for batching according to the existing batching architecture.

Flush occurs according to configured batch size and/or maximum flush interval.

This buffering is purely a persistence implementation detail.

---

## Decision 206: Flush and finalization are distinct operations

**Status:** Accepted

Flush persists current batches.

Finalization closes the stream and completes its local lifecycle.

---

## Decision 207: A stream represents one scientific data product

**Status:** Accepted

A local scientific stream represents one scientific data product, not one device.

One device may produce multiple scientific streams.

---

## Decision 208: Device declarations define available scientific data products

**Status:** Accepted

Device declarations define available scientific data products and their storage requirements.

This includes information such as:

- product identifier
- product type
- schema
- expected size/rate
- storage requirements

Device declarations do not create storage.

---

## Decision 209: Experiments select required scientific outputs

**Status:** Accepted

Experiments select the scientific outputs required from participating resources.

The mechanism by which Experiments declare outputs is future Experiment architecture.

LocalStorageManager does not determine required outputs.

---

## Decision 210: One requested data product maps to one stream

**Status:** Accepted

AcquisitionNode translates required Experiment outputs into LocalStorageManager stream creation requests.

One requested data product corresponds to one local scientific stream.

---

## Decision 211: Scientific products have independent stream lifecycles

**Status:** Accepted

Each scientific data product receives an independent LocalStorageManager stream.

Each stream has:

- independent `storage_id`
- independent schema
- independent lifecycle
- independent ArtifactManifest relationship

The AcquisitionNode maintains the mapping:

```text
data product -> storage_id
```

for the lifetime of the local artifact lifecycle.

---

## Decision 212: LocalStorageManager produces LocalStorageCompletionSummary

**Status:** Accepted

LocalStorageManager produces a LocalStorageCompletionSummary after local finalization.

This describes only local completion.

---

## Decision 213: Empty finalized streams remain valid artifacts

**Status:** Accepted

ArtifactManifest is created when the corresponding stream is created.

Empty finalized streams remain valid scientific artifacts.

Creating a stream with zero rows is distinct from never creating the stream.

---

## Decision 214: Local storage failures are recorded immediately

**Status:** Accepted

Local storage failures are recorded immediately as local storage evidence.

When runtime communication is available they may also be published as durable runtime evidence.

If not delivered online they remain locally preserved and later become part of the global Session Record through future artifact collection.

LocalStorageManager never interprets the consequence of those failures.

---

## Decision 215: Future global StorageManager never writes live local streams

**Status:** Accepted

Future global StorageManager consumes finalized local discovery information only.

It never writes into live local streams.

---

## Decision 216: LocalStorageManager records local storage evidence

**Status:** Accepted

Local storage evidence includes:

- stream created
- stream finalized
- manifest created
- manifest finalized
- write failure
- finalization failure
- cleanup completed
- cleanup failed

---

## Decision 217: LocalStorageManager participates in Session readiness

**Status:** Accepted

Readiness verifies that local persistence is available before Experiment storage creation.

If local persistence cannot safely preserve scientific data or evidence, readiness fails.

---

## Decision 218: No stream and empty stream are distinct states

**Status:** Accepted

A stream created and finalized with zero rows is valid scientific evidence.

"No stream" and "empty stream" are architecturally distinct states.

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
79. Superseded in part by Decision 105: DeviceDeclaration does not authoritatively assign acquisition-health policy; any such value is transitional/template data only.
80. Envelope doesn't split for failure
81. Sender-side handoff failure evidence is owned by the AcquisitionNode
82. Handoff failure policies define sender-side failure consequences
83. Sender-side handoff v1 performs one handoff attempt per envelope
84. System error evidence location is configured per Session.
85. A configured consecutive must-preserve handoff failure threshold marks AcquisitionNode acquisition status failed.
86. A failed AcquisitionNode rejects new iterations but remains capable of evidence-preserving cleanup.
87. AcquisitionNode evaluates acquisition health separately from handoff failure.
88. Acquisition-health behavior comes from the policy explicitly assigned by the active Experiment runtime mapping; DeviceDeclaration is not authoritative.
89. Caller code passes explicit live-source acquisition-health policy mappings into AcquisitionNode; Decisions 100, 101, and 105 define the active Experiment runtime mapping as the authoritative form.
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
103. AcquisitionNode records Experiment-scoped health conditions as Health Observation evidence; operational significance is evaluated separately.
104. Observation type describes a detected condition; the assigned acquisition-health policy supplies configured operational meaning.
105. Acquisition-health policy assignment is Experiment-scoped and belongs to the active ExperimentRuntimeHealthMapping, not DeviceDeclaration.
106. AcquisitionHealthPolicy is an immutable plain-data definition; framework consequence actions remain separate from policy interpretation.
107. AcquisitionNode executes assigned AcquisitionHealthPolicy interpretation and produces Health Interpretation Evidence; Controller-owned framework actions remain separate.
108. Every emitted Health Observation is interpreted immediately at runtime with at most one corresponding Health Interpretation Evidence record; uninterpreted observations are recorded explicitly.
109. Every Health Interpretation Evidence record explicitly references the stable runtime identity of the Health Observation it interpreted.
110. AcquisitionHealthPolicy definitions are persistent SessionConfig data; ExperimentRuntimeHealthMapping provides Experiment-scoped assignment to live sources.
111. AcquisitionHealthPolicy evaluation parameters live in independent named evaluation_rules substructures owned by the rules that use them.
112. Controller records exactly one evidence-only ControllerActionDecision for each explicitly presented HealthInterpretationEvidence without mutating framework lifecycle or runtime state.
113. Controller executes Experiment-failure decisions as canonical experiment_fail evidence without failing Session, and executes Session-failure decisions through the existing failed-Session cleanup path.
114. ControllerActionDecision uses normalized local decision names; evidence-only decisions execute successfully without lifecycle mutation.
115. Runtime components communicate through brokered messaging rather than peer-to-peer paths.
116. NATS is the runtime transport layer and does not own domain meaning.
117. JetStream carries durable commands and evidence; Core NATS carries transient telemetry.
118. Runtime communication and artifact transfer are separate planes.
119. Large scientific artifacts never travel through NATS.
120. Authoritative scientific data remain local during acquisition while selected telemetry may stream.
121. Artifact transfer is pull-based and is never initiated by AcquisitionNodes.
122. Transport does not define Session Time or scientific timing.
123. The NATS server is laboratory infrastructure; its deployment location does not define ownership.
124. NATS is required before coordinated Session start; runtime communication failure preserves evidence and leaves consequences to Controller.
125. Deployment topology does not define architectural ownership.
126. Runtime communication follows an explicit NATS hub-and-spoke topology.
127. A communication boundary owns NATS mechanics while domain components use plain framework records.
128. Phase 10 v1 uses minimal command, command-result, evidence, and telemetry message envelopes.
129. Runtime subjects are message-rooted, Session-scoped, and routing-only.
130. Commands, command results, and evidence use separate JetStream streams; telemetry uses Core NATS only.
131. Message consumers follow existing component ownership; Ingestor preserves durable evidence and Controller consumes decision-relevant evidence.
132. Transport acknowledgement and explicit command result are separate outcomes.
133. Command results share accepted, progress, succeeded, and failed status vocabulary; Phase 10 runtime control uses final statuses only.
134. Commands target one component or one component group, with one result per executing component.
135. Group command-result aggregation belongs to the command issuer.
136. Missing command results become unresolved outcome evidence interpreted by the command issuer.
137. Command receivers use command_id for local duplicate detection.
138. Runtime component identity consists of component_type and component_id independent of deployment location.
139. SessionConfig is authoritative for expected runtime participants; Phase 10 adds no runtime discovery.
140. NATS carries readiness requests without redefining readiness ownership or evidence.
141. NATS availability is required communication readiness before distributed Session start.
142. Runtime NATS unavailability creates communication-failure evidence without automatic lifecycle mutation.
143. Durable message producers retain ownership until JetStream publication succeeds.
144. Durable publication succeeds only when the intended JetStream stream accepts the message.
145. Durable evidence is published once and consumed independently without component relaying.
146. Telemetry is transient, display-oriented, non-authoritative, and unsuitable as the sole basis for lifecycle or scientific-validity decisions.
147. Artifact manifests are artifact-level durable evidence rather than per-record acquisition evidence.
148. Ingestor is runtime evidence intake, not a universal online scientific-data pipe.
149. During acquisition, the Control Plane carries runtime communication and display telemetry, not scientific data or artifact bytes.
150. SynchronizationManager is the sole owner of scientific Session Time.
151. Experiment Time is derived from Session Time and the canonical Experiment start Session Time.
152. AcquisitionNode local monotonic clocks are not reset to Session Time; authorized mappings relate them.
153. Acquired records carry analysis-ready Session Time and, during an Experiment, Experiment Time whenever practical.
154. Timing audit evidence is preserved alongside analysis-ready timing.
155. Runtime timing is primary; reconstructed timing is separate derived evidence and never silently replaces it.
156. Synchronization cadence, tolerance, correction, drift, and degradation thresholds are explicit Session configuration.
157. Transport, broker, wall-clock, arrival, and ingest timestamps are not scientific time.
158. Synchronization, mapping, drift, timestamp-status, rejection, and timing-quality records are scientific evidence.
159. Reconstruction audits and may refine timing but never mutates raw runtime timing evidence.
160. Experimenter-configured TimingQualityPolicy interprets observations; Controller owns framework consequences.
161. SynchronizationManager detects authority-side conditions and owns mapping validation/drift decisions; AcquisitionNode reports local-time samples and detects local runtime timestamping conditions without deciding remapping.
162. AcquisitionNode validates synchronization updates before atomically accepting a new mapping.
    Superseded by Decisions 168 and 171 for mapping validation and activation ownership; prospective non-retroactive application remains authoritative.
163. Accepted mapping replacement is atomic and prospective; previous records remain unchanged.
164. AcquisitionNode attaches framework scientific timing; DeviceAdapters do not know or derive Session or Experiment Time.
165. Phase 11 preserves device-native timing unchanged without online clock interpretation.
166. Scientific timing and device-native timing remain distinct framework and device concepts.
167. Controller explicitly hands active Experiment identity and start Session Time to AcquisitionNode as runtime context separate from health mapping.
168. SynchronizationManager solely owns immutable active synchronization mappings and their lifecycle.
169. Superseded by Decision 171: AcquisitionNode does not produce SynchronizationObservation evidence.
170. Mapping updates are preserved runtime timing evidence and do not require a mapping identifier on every acquired row.
171. AcquisitionNode reports local-time samples; SynchronizationManager creates SynchronizationObservation evidence and owns drift estimation and remapping.
172. SynchronizationMapping is immutable SynchronizationManager-owned plain data with an accepted minimum schema.
173. AcquisitionNode local-time reports use a minimum plain-data schema and are not SynchronizationObservation evidence.
174. SynchronizationManager creates MappingUpdateEvidence for active mapping creation, replacement, and retirement.
175. MappingUpdateEvidence uses existing runtime-evidence ingestion and Session Record preservation paths without a new storage component.
176. AcquisitionNode reports samples and passively applies mappings; SynchronizationManager owns observation, mapping, drift, remapping, and update-evidence behavior.
177. MappingUpdateEvidence uses runtime evidence type `mapping_update_evidence` with its plain-data form as RuntimeEvidenceMessage payload.
178. Each AcquisitionNode has one co-located LocalStorageManager for authoritative local persistence.
179. Every framework-written scientific record carries explicit runtime timing fields.
180. Scientific data belong to Experiments; Session-level records outside Experiments are evidence, configuration, manifests, or telemetry.
181. External scientific artifact bytes are not rewritten; framework timing and index information are stored locally.
182. LocalStorageManager owns local persistence without absorbing acquisition, timing authority, lifecycle, transfer, reconstruction, or export.
183. Artifact manifests are authoritative local discovery records for later pull collection.
184. Local completion is independent from global Session Record completion.
185. Finalized local scientific records are immutable and derived products remain separate.
186. Each local scientific record has exactly one LocalStorageManager owner.
187. Artifact transfer creates managed copies without transferring original ownership.
188. LocalStorageManager is a caller-created runtime collaborator of AcquisitionNode.
189. LocalStorageManager writes scientific streams incrementally.
190. Stable stream metadata are written once; appends use `storage_id` and changing rows.
191. Local scientific stream persistence is independent of payload meaning.
192. External-artifact timing and index information use the same stream abstraction.
193. ArtifactManifest describes every locally managed scientific artifact and exists even for zero-row streams.
194. LocalStorageManager finalization means local completion only.
195. SynchronizationManager retains synchronization-evidence ownership; persistence requires explicit handoff.
196. Future global StorageManager consumes finalized local discovery information without taking original ownership.
197. Session creates one LocalStorageManager per AcquisitionNode during initialization, and local storage participates in readiness.
198. Controller communicates with LocalStorageManager only through AcquisitionNode.
199. AcquisitionNode supplies scientific context; LocalStorageManager supplies storage realization and owns ArtifactManifest.
200. Internal and external acquisition share local stream creation and differ through ArtifactManifest.
201. LocalStorageManager exclusively owns ArtifactManifest.
202. `storage_id` is a runtime write handle; `artifact_manifest_id` is a durable discovery identity.
203. AcquisitionNode translates Experiment requirements into stream creation; LocalStorageManager does not discover outputs.
204. Experiment scientific streams are created before acquisition begins.
205. Local persistence buffering is bounded batching only.
206. Flush persists current batches; finalization closes the local stream lifecycle.
207. One local scientific stream represents one scientific data product, not one device.
208. Device declarations describe available products and storage requirements but do not create storage.
209. Experiments select required scientific outputs; the declaration mechanism remains future architecture.
210. One requested scientific data product maps to one local stream.
211. Each product has an independent stream, schema, lifecycle, and manifest relationship.
212. LocalStorageCompletionSummary describes local finalization only.
213. Empty finalized streams are valid and distinct from streams never created.
214. Local storage failures are preserved locally and may also be published as durable runtime evidence.
215. Future global StorageManager never writes live local streams.
216. LocalStorageManager records explicit local stream, manifest, failure, and cleanup evidence.
217. Local storage readiness must succeed before Experiment storage creation.
218. "No stream" and "empty stream" are architecturally distinct.

---



Open questions now belong exclusively in `open_questions.md`.

