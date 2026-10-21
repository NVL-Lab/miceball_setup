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

**Subsequent qualification:** Decision 407 qualifies the fatal-evidence/terminal-
outcome interpretation below for already-admitted Normal Stop; its cleanup,
preservation and safety requirements remain unchanged. Historical text is retained.

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

**W048 clarification (Decision 365):** Kill Session may transition to `aborted`
even when participant cleanup remains unconfirmed. `cleanup_occurred=True` means
the Session performed its local cleanup procedure; it does not confirm successful
cleanup of all participants. Unconfirmed participant cleanup, hardware safety,
and resource-release obligations must be represented separately. Existing safety
requirements and authorized recovery protections remain mandatory. This
clarification does not change Normal Stop guarantees or unrelated lifecycle
behavior and introduces no new lifecycle states or infrastructure.

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

**Subsequent revision:** Decision 377 removes routine scientific-observation
intake through Ingestor, regardless of size; the historical text below is preserved.

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

**Slice 28 clarification (Decisions 283 and 291):** The original Session-first
declaration placement below is historical. AcquisitionNode owns declared device
inventory before Session creation; final SessionConfig selects from that inventory
after Controller resolves readiness, reservations, and optional resources.
Declarations remain independent of live hardware connections.

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

**Sequential-reuse clarification (Decision 302):** Successful shutdown and
required cleanup return a retained adapter to DECLARED. initialize(config)
continues to require DECLARED; no additional lifecycle operation is introduced.

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

**Slice 28 clarification (Decision 283):** AcquisitionNode owns node-scoped
declared inventory; Session owns its resolved selection, not the deployment
inventory. DeviceManager continues to manage already-created adapters.

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

**Partially superseded by Decisions 285, 286, and 291:** The historical `required`
field in DeviceReadiness and its direct required-device gating below are no
longer the accepted launch contract. DeviceReadiness reports technical readiness
without Session criticality; Controller evaluates selected devices using
DeviceDeclaration.required before constructing resolved SessionConfig. Session
retains lifecycle, configuration validation, and recorded readiness evidence;
it does not own adapters or adapter lifecycle.

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

**Partially superseded by Decisions 285-286:** Reuse of shared device readiness
evidence remains accepted, but the historical field list below must omit
`required`. Session-selection criticality is DeviceDeclaration.required, not
adapter-supplied readiness metadata. No parallel Session-only readiness type is
introduced.

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

**Slice 28 clarification (Decisions 283 and 286):** The historical copied
`required` metadata below is not authority for launch criticality or node
readiness. Session selection owns requiredness through DeviceDeclaration.required,
and DeviceReadiness no longer carries it. Adapter construction remains explicit;
adapters do not own deployment inventory or Session selection.

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

**Slice 28 clarification (Decisions 283 and 285):** DeviceManager's adapter-only
boundary remains; AcquisitionNode must report readiness for every declared
enabled device, including ready=False when no adapter exists. The historical
absence of DeviceManager matching must not justify omitting declared devices
from the node report. This does not introduce adapter discovery or a registry.

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

**Partially superseded by Decision 292:** ServiceReadiness.required and the
shared evidence boundary remain accepted. The historical StorageManager
required-service example below does not define a Slice 28 launch prerequisite:
Ingestor and SynchronizationManager readiness are mandatory; StorageManager
readiness is not. StorageManager's later persistence responsibilities and
final-persistence success requirements remain unchanged.

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

**Subsequent revision:** Decision 377 removes mandatory scientific acquisition-envelope
delivery to Ingestor; acquisition and device ownership remain unchanged.

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

**Slice 28 clarification (Decisions 289 and 291):** Controller must resolve
prospective selections, readiness, and reservations before constructing the
final SessionConfig and creating Session. The accepted configuration is not an
unresolved wish list; omitted optional resources do not remain selected.

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

**Subsequent revision:** Decision 377 assigns routine scientific observations and
their metadata to AcquisitionNode's LocalStorageManager, not global envelope intake.
The historical JSONL implementation and validation remain recorded below.

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

**Subsequent revision:** Decision 377 removes mandatory per-observation acquisition
envelopes and their scientific-intake audit from the Session Record. Applicable
configuration, provenance, lifecycle, readiness, operational audit, failure,
cleanup, and terminal evidence remain required; historical text is preserved.

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

**Partially superseded by Decisions 284-286 and 292:** The historical node
report's session_id becomes reserved_for_session_id (optional). Readiness is
queryable before Session creation; its aggregate ready describes required
framework/service prerequisites, not required scientific devices. Controller
evaluates individual selected devices and reservation availability separately.
Ingestor and SynchronizationManager readiness are mandatory launch prerequisites;
StorageManager is not. Acquisition-local persistence prerequisites remain
distinct from global StorageManager availability. Historical Phase 2 validation
is preserved, not evidence that Slice 28 is implemented.

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

**Slice 28 extension (Decisions 281 and 289-294):** The sequential, direct-object
Controller v1 workflow below remains historical implementation. Accepted launch
ownership now includes pre-Session resource resolution, atomic node reservation,
runtime assembly, and rollback across existing communication boundaries; it
must not assume shared Python objects. Session retains lifecycle ownership.
Multiple Controllers and AcquisitionNodes remain possible without introducing
multi-Session scheduling or another startup authority.

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

**Historical finalization note:** The Controller v1 two-write sequence below
records the Phase 4 design and validation. Decisions 226-229 subsequently separate
the Evidence Archive from the Session Record and require final persistence before
successful completion. Current Phase 13 finalization writes the archive and final
record before `Session.complete()`; this note does not assert that the persisted
record contains a post-completion terminal snapshot. That representation remains
for separate architectural review, as does Q019's evidence-consumption guarantee.

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

**Slice 28 clarification (Decisions 284 and 289):** Readiness also occurs before
Session creation under Controller-owned launch. The historical initialization-only
description below is broadened, without turning readiness into Validation or
an Experiment.

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

**Slice 28 clarification (Decisions 282-283 and 287):** Session-owned resources
below means accepted participation/configuration for that execution, not
ownership of deployment identities or declared node inventories. AcquisitionNode
owns its inventory and exclusive reservation authority; Experiment continues
to declare expected contribution from resolved Session resources.

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

**Subsequent clarification:** Decision 407 separates fatal-decision accounting
from Session closeout ownership and clarifies the outcome of already-admitted
Normal Stop. Multiple applicable decisions require independent durable accounting,
not repeated Experiment termination or physical cleanup. Historical text follows.

Experiment lifecycle terminal events are distinct: `experiment_stop` records normal completion, `experiment_fail` records unexpected Experiment-level framework or runtime failure, and `experiment_abort` is reserved for future intentional early termination and is not implemented in Phase 8b.

Controller executes `record_experiment_failure_decision` by asking Session to record canonical `experiment_fail` evidence, ending the active Experiment, and clearing the active Experiment runtime health mapping from both Controller and AcquisitionNode.

Experiment failure does not fail or stop the Session and does not stop Acquisition Runtime.

Controller executes `record_session_failure_decision` through its existing failed-Session path: Acquisition Runtime cleanup is attempted and Session transitions through its accepted stopping/failed lifecycle. No new cleanup semantics are introduced.

This decision does not introduce `experiment_abort`, a generic Experiment end-reason field, notification, retry, recovery, distributed delivery, aggregation, polling, callbacks, or event buses.

**W048 clarification (Decisions 360/365):** Kill Session terminates an active
Experiment using the established canonical `experiment_abort` behavior for
intentional early termination. Unconfirmed participant cleanup is recorded
separately from Experiment termination; the event does not confirm hardware or
resource cleanup. The historical Phase 8b scope above is preserved. This
clarification does not claim W048 implementation or validation.

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

**Subsequent clarification:** Decision 407 preserves this decision vocabulary
while separating each applicable fatal decision's durable accounting from the
Session-scoped cleanup owner and the terminal outcome of already-admitted Normal
Stop. It does not change Experiment-only failure into Session failure.

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

**Slice 28 clarification (Decision 296):** The historical envelopes below
describe Session-scoped runtime operations. The general command envelope may
omit session_id for participant-scoped operations that do not concern a Session.
Session-specific operations still require and validate a real Session identity;
existing command/result conventions remain in use.

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

**Partially superseded by Decision 296:** Session-scoped routing below remains
valid for Session operations and evidence. Pre-Session commands must also be
addressable by RuntimeParticipant identity independently of Session identity,
without empty, placeholder, or fabricated Session IDs. This extends the existing
NATS boundary, not a second communication framework.

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

**Slice 28 clarification (Decision 296):** The filters below record implemented
Phase 10 Session routing, not the full future pre-Session command coverage.
Participant-scoped commands/results reuse the existing durable NATS conventions;
Session evidence remains Session-scoped and telemetry remains Core NATS only.

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

**Slice 28 clarification (Decisions 282 and 289-291):** RuntimeParticipant
identity is deployment/lab-scoped and exists before Session. SessionConfig
remains authoritative for the final expected participation of a created Session,
not for creating those identities or enumerating prospective launch resources.
Controller uses already-available participants before creating that configuration;
discovery and registration remain deferred.

SessionConfig is the authoritative source of expected runtime participants.

Controller determines expected runtime participants from the accepted SessionConfig.

Phase 10 does not introduce runtime discovery or a dynamic service registry.

If an expected participant does not respond to the relevant command or readiness request, that absence is recorded as unresolved command outcome evidence and surfaced to the operator.

Runtime availability may be observed in the future, but it does not replace SessionConfig as the source of expected participation.

## Decision 140

**Slice 28 clarification (Decisions 284-286, 289, and 294):** Readiness requests
also precede Session creation; Controller owns launch gating using current
reports. Missing/invalid current evidence means unknown, not ready=False or
confirmed remote failure. Existing command/result mechanisms remain reusable;
failed pre-Session launches return operational failure and are not forced into
Ingestor or a new durable launch journal. Session retains its own lifecycle and
initialization evidence rather than owning pre-Session resolution.

NATS carries readiness requests but does not redefine readiness.

Before Session start, Controller may issue readiness-related commands to expected runtime participants over NATS.

The responding component runs its existing readiness logic and returns existing readiness evidence in the command_result payload.

NATS does not define a separate readiness model.

Missing readiness command_results are recorded as unresolved command outcome evidence and surfaced to the operator.

Session readiness gating remains owned by Session using readiness evidence from the accepted readiness contracts.

## Decision 141

**Startup clarification (Decision 295):** Required NATS connectivity precedes
operational distributed readiness independently of Session lifecycle. Startup
connection failure is explicit and fails startup rather than waiting indefinitely;
Controller does not manage broker or participant processes.

**Slice 28 clarification (Decisions 289, 292, and 294):** Required brokered
communication must be available for launch. Pre-Session failure is reported
operationally, not through mandatory durable launch evidence. The reference to
storage readiness below concerns acquisition-local persistence prerequisites;
it must not make global StorageManager a launch prerequisite.

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

**Phase 13 destination clarification (Decisions 219-227):** The historical
Session Record wording above now refers to preservation supporting that record.
Producer-marked persistent runtime evidence and runtime-evidence audit are
compiled by Ingestor for StorageManager's separate Evidence Archive. Independent
consumption and evidence ownership remain unchanged.

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

**Subsequent clarification (Decisions 379-381):** The historical Phase 11 scope
above is preserved. Decision 380 now specifies local affine mapping application;
Decisions 379 and 381 establish measured cross-clock validity, synchronization
readiness and degraded timing. Advanced estimation, measurement algorithms,
hardware synchronization and offline refinement remain open under Q006/Q018,
except for the minimum demonstrably valid measurement method required by the
current implementation.

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

**Phase 13 destination clarification (Decisions 219-227):** Preserve the
historical Phase 11 wording above; persistent MappingUpdateEvidence now follows
Ingestor compilation into StorageManager's separate Evidence Archive, not a
conceptual runtime-evidence dump in the Session Record. Timing, intake, and
persistence ownership are unchanged.

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

**Phase 13 destination clarification:** In the historical ownership chain above,
StorageManager remains the persistence owner; Decisions 226-227 distinguish its
Evidence Archive for persistent runtime evidence from the Session Record itself.

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

Local scientific stream persistence uses a common ownership model, interface,
and lifecycle independently of the scientific payload's meaning. This does not
require an identical file format for every scientific data product.

LocalStorageManager retains the common persistence responsibilities and
interfaces while using product-appropriate storage formats. JSONL remains
supported; HDF5 is accepted for raw camera-frame artifacts.

**Clarification:** The original requirement for an identical storage mechanism
refers to common persistence ownership, interfaces, and lifecycle, not a
mandatory common file format. It does not introduce a CameraStorageManager or
a generic storage plugin architecture.

---

## Decision 192: External-artifact timing uses the scientific stream abstraction

**Status:** Accepted

External-artifact timing/index information is stored using the same timestamped scientific stream abstraction.

The distinction between internal and external acquisition exists in the ArtifactManifest, not in the LocalStorageManager write path.

---

## Decision 193: ArtifactManifest describes all locally managed scientific artifacts

**Status:** Accepted

**Clarification / supersession:** Decisions 248-249 supersede the implication
that one external manifest represents both an external file and local timing/index
files. Each scientific file has its own manifest; local_managed_paths is not a
retrieval list. The historical description below is preserved.

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

**Clarified by Decision 298:** Session initialization authorizes creation of
Session-scoped LocalStorageManagers; each AcquisitionNode physically creates its
own manager in its own process using deployment-local storage configuration.
The original wording below does not require direct remote Python-object access
or authorize Controller to choose node filesystem roots. LocalStorageManager
retains local scientific persistence ownership.

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

**Clarification:** Decision 235 now settles explicit selection of declared
scientific products by existing source device, AcquisitionNode, and product
identities. The implementation and external configuration representation remain
separate work; output-selection ownership is no longer unresolved.

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

---

## Decision 219: RuntimeEvidenceMessage remains the runtime evidence boundary

**Status:** Accepted

`RuntimeEvidenceMessage` remains the runtime evidence boundary between evidence-producing components and runtime evidence consumers.

It carries plain runtime evidence across the communication boundary without transferring ownership of the evidence's domain meaning.

`RuntimeEvidenceMessage` does not own lifecycle, scientific interpretation, persistence policy, Session Time, or storage semantics.

---

## Decision 220: RuntimeEvidenceMessage carries explicit persistence intent

**Status:** Accepted

`RuntimeEvidenceMessage` gains an `is_persistent` flag.

This is an architecture decision only until implementation adds the field.

The flag records whether the evidence-producing component marked that runtime evidence as intended for persistent preservation.

---

## Decision 221: Evidence producers decide persistence for their own evidence

**Status:** Accepted

Evidence-producing components decide whether their own evidence is persistent.

Architecture-defined mandatory persistent evidence categories continue to exist, but the producer responsible for that evidence must set:

```text
is_persistent = True
```

The persistence decision belongs to the evidence owner, not to Ingestor or StorageManager.

---

## Decision 222: Ingestor must not infer evidence persistence

**Status:** Accepted

Ingestor must never infer persistence from:

* evidence type
* payload
* source component
* domain meaning

Ingestor uses the explicit persistence intent carried by `RuntimeEvidenceMessage`.

Ingestor does not reinterpret evidence to decide whether it should persist.

---

## Decision 223: Ingestor owns runtime evidence intake and compilation

**Status:** Accepted

Ingestor owns:

* runtime evidence intake
* intake validation
* ingest audit
* temporary runtime retention
* compilation of persistent runtime evidence

Ingestor compiles runtime evidence marked persistent into the information handed to StorageManager.

---

## Decision 224: Ingestor does not own evidence meaning or persistence decisions

**Status:** Accepted

Ingestor does not own:

* evidence interpretation
* lifecycle
* scientific meaning
* persistence decisions

Ingestor may validate intake shape and record ingest audit, but it does not decide domain significance.

---

## Decision 225: StorageManager owns persistence only

**Status:** Accepted

StorageManager owns persistent writing.

StorageManager receives compiled persistent information and writes persistent records.

StorageManager does not decide runtime evidence meaning, Session lifecycle, Experiment lifecycle, acquisition ownership, or Ingestor intake policy.

---

## Decision 226: Session Record and Evidence Archive are separate concepts

**Status:** Accepted

The Session Record and Evidence Archive are separate concepts.

The Session Record describes the Session itself.

The Evidence Archive stores persistent runtime observations supporting the Session Record.

The Evidence Archive does not replace the Session Record, and the Session Record does not become a raw dump of all runtime evidence.

---

## Decision 227: Evidence Archive v1 uses one runtime evidence stream

**Status:** Accepted

The accepted v1 conceptual Evidence Archive layout is:

```text
session_<session_id>/
    session_record_initial.json
    session_record_final.json
    evidence/
        runtime_evidence.jsonl
        ingest_audit.jsonl
        compilation_summary.json
```

Do not introduce category-specific evidence folders in v1.

---

## Decision 228: Persistent evidence lifecycle

**Status:** Accepted

The accepted persistence lifecycle is:

```text
Session start
        ↓
initial Session Record

Session execution
        ↓
Ingestor collects runtime evidence

Session end/failure
        ↓
Ingestor compiles persistent evidence
        ↓
StorageManager writes Evidence Archive
        ↓
StorageManager writes final Session Record
```

This decision defines ownership and order, not an implementation API.

---

## Decision 229: Session completion requires final persistence success

**Status:** Accepted

A Session must not be considered successfully completed until final persistence succeeds.

Final persistence includes the Evidence Archive and final Session Record write.

If final persistence fails, use the existing failed-session path.

Do not introduce a new lifecycle state for persistence failure.

---

## Decision 230: Evidence Archive does not own future storage workflows

**Status:** Accepted

The v1 Evidence Archive does not resolve:

* archive evolution
* retention or deletion
* artifact transfer
* reconstruction
* NWB export
* global scientific data collection

Those topics remain future architecture.

---

## Decision 231: RuntimeEvidenceMessage persistence flag does not create new ownership

**Status:** Accepted

The `is_persistent` flag is evidence-owner intent carried across the runtime evidence boundary.

It does not create:

* a new evidence owner
* a new lifecycle owner
* a new storage owner
* a new evidence category
* a new transport path

RuntimeEvidenceMessage remains the boundary. Ingestor compiles persistent runtime evidence. StorageManager writes persistent records.

---

********************************************************************************

## Decision 232: Raw camera-frame artifacts preserve image data and aligned timing in HDF5

**Status:** Accepted

One camera-frame scientific data product produces one local HDF5 artifact per
Experiment through the existing DeviceAdapter, DeviceManager, AcquisitionNode,
and LocalStorageManager responsibilities. The camera is the first concrete
validation case, not the basis for camera-specific general interfaces.

Persist actual OpenCV-acquired image arrays while preserving original pixel
values, frame order, image shape and channel organization, and native dtype
where supported. Acquisition is append-oriented and uses no lossy compression.
An extendable frame dataset conceptually shaped `(N, height, width, channels)`
is acceptable for fixed-shape color frames; this does not prescribe a complete
HDF5 schema.

Each stored frame remains aligned with its frame index, `session_time_s`,
`experiment_time_s`, `acquisition_node_local_time_s`, and `timestamp_status`.
AcquisitionNode attaches scientific timing before persistence batching under
SynchronizationManager authority. Device-native timestamps remain separate
when available; their absence is represented without fabricated values.

Preserve available device/SDK metadata, including dimensions, dtype, backend,
configured or reported frame rate, and exposure/gain when available. Static
metadata belong at artifact or stream level where appropriate. Camera-specific
metadata are not mandatory for other scientific products.

Scientific identity includes `session_id`, `experiment_id`, `source_node_id`,
`source_device_id`, and `artifact_manifest_id`; `storage_id` remains the separate
runtime write handle. Existing stream creation and manifest requirements in
Decisions 197-218 remain unchanged, including creation before acquisition and
valid zero-record artifacts. Raw image arrays do not travel through NATS or
Ingestor. LocalStorageManager owns the artifact and authoritative manifest.

**Implementation status:** HDF5 camera persistence is implemented and covered
by automated synthetic-array tests. The Slice 20 corrective changes await
manual validation and a targeted follow-up audit; real-camera HDF5 validation
and Slice 20 closure are not claimed.

---

## Decision 233: Persistence batching and handled finalization preserve partial scientific artifacts

**Status:** Accepted

LocalStorageManager persistence batching remains bounded and explicitly
configured under Decisions 205-206. A 20-frame batch is a configurable starting
value for the camera, not a framework-wide constant. Persistence batching is
distinct from AcquisitionNode acquisition-envelope batching.

On normal termination, operator-requested termination, or handled failure,
attempt to preserve pending data, flush, close the artifact, update its manifest,
and produce local completion or failure evidence. This requirement does not
define new termination commands or change Session or Experiment lifecycle.

Partial recordings may remain scientifically usable. Writing, flushing, or
closure failure must not be reported as successful finalization. Existing
ArtifactManifest and LocalStorageCompletionSummary concepts describe local
completion only. For camera artifacts, completion information reflects actual
stored frame count, first and last stored frame indices, acquisition timing,
duration, and finalization outcome where applicable.

---

## Decision 234: Session local storage roots override persistent AcquisitionNode defaults without mutation

**Status:** Accepted

**Partially superseded for distributed launch by Decision 298:** The historical
override behavior below remains a description of the current local implementation,
not Controller authority over remote roots. Distributed initialization uses each
node's deployment-defined root/configuration; Controller must not choose or
override it via SessionConfig.local_storage_roots. LocalStorageManager path
ownership and preservation of persistent defaults remain unchanged.

Each AcquisitionNode has an explicitly resolved persistent default local storage
root. A Session may override that root without modifying the persistent default
or affecting later Sessions.

LocalStorageManager owns actual storage paths and organizes artifacts
deterministically by Session and Experiment. General components must not
hardcode developer-specific or camera-specific paths.

The final external configuration model remains unresolved; this decision does
not prescribe configuration files or introduce a configuration system.

---

## Decision 235: Experiment configuration explicitly selects declared scientific products

**Status:** Accepted

Experiment configuration explicitly selects the scientific products required
for that Experiment. Each selection references the existing source device
identity, AcquisitionNode identity, and scientific product identity.

An Experiment selects products declared by devices under Decision 208; it does
not define new device capabilities or introduce redundant product identities.
Required scientific outputs must not be inferred from connected or healthy
devices.

This resolves the architectural output-selection deferral in Decision 209.
It does not prescribe a new configuration-file system or an implementation API.

---

## Decision 236: Scientific-product declarations own persistence format requirements

**Status:** Accepted

The device's scientific-product declaration defines its storage requirements,
including the appropriate persistence format. Experiments select products and
cannot override their declared storage format.

Under Decision 208, declarations include, as applicable, the existing product
identity, scientific product type, scientific data schema, expected size and
acquisition rate when known, and storage requirements. Unavailable acquisition
characteristics must not be invented.

This preserves Decision 191's common persistence ownership, interface, and
lifecycle while allowing product-specific formats, including camera HDF5 under
Decision 232.

---

## Decision 237: Controller coordinates Experiment scientific stream preparation through existing readiness

**Status:** Accepted

Controller coordinates Experiment initialization and waits for the existing
preparation/readiness results before scientific acquisition begins. No parallel
Experiment lifecycle or independent readiness authority is introduced.

Under Decisions 198-210, AcquisitionNode translates selected scientific products
into local stream-creation requests. LocalStorageManager creates the streams,
storage artifacts, and authoritative ArtifactManifests; AcquisitionNode does
not directly write HDF5 or JSONL artifacts.

Each selected product produces one local scientific stream for the Experiment.
The stream and its ArtifactManifest exist before scientific acquisition begins,
even if no records arrive. An empty finalized stream remains distinct from a
stream that was never created.

Existing Controller, Session, AcquisitionNode, DeviceManager, and
LocalStorageManager ownership boundaries remain unchanged.

**Implementation status:** Slice 20.3 scientific stream preparation and
integration are implemented and covered by automated tests. Slice 20 is
complete; W029 records the successful Jetson hardware validation. Decision 239
adds Slice 21 pre-start rejection requirements; Slice 21 is complete following
the validations and independent audit reassessment recorded in W030 and M009.

---

## Decision 238: Experiment identity represents one execution

**Status:** Accepted

An Experiment identity represents one execution within a Session.

Once an Experiment reaches a terminal lifecycle state (`stopped`, `aborted`,
or `failed`), scientific acquisition cannot restart under that same
`experiment_id`.

If an operator requests another execution using the same configuration,
Controller creates a new Experiment with a new `experiment_id`.

The new Experiment may reuse the previous descriptor, scientific-product
selections, participating devices, and acquisition parameters, but must have
its own canonical lifecycle, scientific streams, ArtifactManifests, and
acquisition/timing evidence.

This applies universally, including Experiments without scientific outputs or
recorded data.

Restarting a device within an active Experiment is distinct from restarting a
terminal Experiment.

**Consequences:**

* Never reopen finalized scientific streams.
* Never silently reuse a terminal Experiment identity.
* Distinguish repeating a configuration from restarting an Experiment execution.
* Preserve existing Session, Controller, and Experiment lifecycle ownership.

This decision does not implement `experiment_abort` or add lifecycle APIs.

**Implementation status:** Session and Controller enforce terminal identity
in Slice 20.3, including executions without scientific outputs. Slice 20 is
complete as recorded in W029; pre-start rejection under Decision 239 remains
separate Slice 21 work, now complete as recorded in W030 and M009.

---

## Decision 239: Required Experiment preparation precedes canonical start

**Status:** Accepted

Controller must establish successful required Experiment preparation before
recording canonical `experiment_start`. AcquisitionNode reports preparation
outcomes but does not decide Experiment lifecycle. Existing preparation and
readiness boundaries are reused; no parallel readiness authority is introduced.

Required preparation failure prevents both `experiment_start` and
`experiment_fail`: an Experiment that never started is not a failed active
Experiment. Controller produces a `RuntimeEvidenceMessage` with:

```text
evidence_type = "experiment_start_rejected"
is_persistent = True
```

The existing Controller command result reports the rejected start. Rejection
evidence uses the existing runtime evidence boundary, Ingestor intake/audit and
persistent-evidence compilation, and StorageManager Evidence Archive writing.
It does not create a Session rejection history or canonical lifecycle event.

Optional preparation failures do not prevent starting when required preparation
succeeds. This does not relax the selected scientific-output requirements in
Decisions 209 and 235-237: required streams and their manifests must be prepared
before scientific acquisition.

Missing required command results remain unresolved under the existing command
outcome model. They cannot establish successful preparation or confirmed remote
failure. Controller must not record canonical start without confirmed successful
required preparation.

LocalStorageManager retains ownership of streams, artifacts, manifests, and
local persistence diagnostics. Controller retains lifecycle orchestration;
Session retains canonical lifecycle evidence. AcquisitionNode reports execution
outcomes. Ingestor and StorageManager retain their existing responsibilities.

No new lifecycle states, evidence subsystem, Session rejection history, or
ownership transfer is introduced.

**Principle:** Required preparation succeeds before canonical Experiment start;
pre-start rejection is persistent runtime evidence, not `experiment_fail`.

**Implementation status:** The Slice 21 implementation extends existing gating
with producer-marked persistent rejection evidence, required/optional service
readiness, and correlated remote preparation outcomes. Scientific preparation
uses the existing remote command dispatcher with caller-managed orchestration.
Slice 21 is complete following three successful manual IPython validations,
62 passing focused audit tests, and independent audit reassessment; W030 and
M009 record validation and completion. The full suite was not rerun during
the audit, and these manual validations do not constitute a live NATS test.

---

## Decision 240: Artifact collection handoff preserves existing component ownership

**Status:** Accepted

LocalStorageManager owns authoritative local scientific artifacts and
ArtifactManifests. AcquisitionNode publishes artifact information through the
existing runtime evidence pathway. Ingestor retains the information and compiles
the post-session collection handoff. Controller initiates post-session collection
and coordinates delivery of the handoff. StorageManager owns global artifact
retrieval and storage.

Artifact bytes travel separately through the pull-based Artifact Plane, never
through Ingestor or NATS. The Session Record, Evidence Archive, and scientific
artifact storage remain separate. AcquisitionNode publication communicates the
LocalStorageManager-owned manifest; it does not create another authoritative
manifest or transfer the ownership established by Decision 201.

**Implementation status:** Slice 22 is implemented, manually validated, and
independently audited with verdict PASS. W031 records validation and M010
records completion; this does not imply artifact-byte retrieval.

---

## Decision 241: Complete authoritative manifests are published at creation and finalization

**Status:** Accepted

AcquisitionNode publishes the complete authoritative ArtifactManifest through
the existing RuntimeEvidenceMessage mechanism, using evidence_type="artifact_manifest".
Publication occurs when LocalStorageManager creates the artifact and its initial
manifest, and when it finalizes the artifact and updates its manifest.

The existing schema is preserved, including artifact_manifest_id, session_id,
experiment_id, AcquisitionNode identity, and existing artifact metadata. No
alternative manifest schema is introduced. These are artifact lifecycle
publications, not per-row evidence. Existing producer-owned persistence intent
and mandatory persistent evidence requirements remain unchanged.

**Implementation status:** AcquisitionNode produces persistent manifest messages
at creation and finalization through local Ingestor intake. The existing NATS
adapter publishes newly produced messages after command execution or explicit
publication. Independent consumers use the existing evidence subscription.
Manual broker-double validation and independent audit passed as recorded in W031.

---

## Decision 242: Artifact information reuses Ingestor runtime evidence retention

**Status:** Accepted

Ingestor receives and retains artifact information using the existing runtime
evidence intake and retention mechanism. No artifact database, pandas dependency,
continuously synchronized artifact registry, or separate persistence mechanism
is introduced.

Current accepted runtime evidence retention is in memory. Reconstruction after
process restart is outside Slice 22; its future roadmap placement remains a
high-level architecture decision.

**Implementation status:** Slice 22 reuses generic in-memory intake and retention;
no restart reconstruction is implemented.
Slice 22 validation and independent audit passed as recorded in W031.

**Later scope clarification (Decisions 276-280):** Slice 27 now accepts an
Ingestor-owned local runtime-evidence recovery journal and reconstruction for a
known Session. Slice 22's historical in-memory implementation and validation
remain unchanged; Slice 27 known-Session recovery is complete after independent
manual software validation and corrected targeted re-audit PASS (M014, W034).

---

## Decision 243: Ingestor compiles one complete manifest entry per artifact

**Status:** Accepted

When requested for a Session, Ingestor selects retained artifact_manifest evidence
belonging to that Session and associates messages by artifact_manifest_id.
It selects the finalized manifest when available; otherwise it selects the
initial manifest and explicitly reports missing finalization evidence.

The compiled handoff contains one entry per artifact with the complete selected
ArtifactManifest and is made available to Controller. Session, Experiment,
AcquisitionNode, and artifact identities are preserved, including session_id,
experiment_id, and artifact_manifest_id. Ingestor does not invent missing fields
or infer scientific meaning.

**Implementation status:** Ingestor handoff compilation is implemented and
Controller exposes its result during Session finalization. Automated tests
cover this path; manual validation and independent audit passed. W031 records
the results and M010 records Slice 22 completion.

---

## Decision 244: Slice 22 ends at artifact collection handoff

**Status:** Accepted

Slice 22 excludes diagnostic association or compilation, artifact-byte transfer,
remote filesystem access or transfer protocols, checksums or artifact copying,
Ingestor restart recovery, new artifact persistence infrastructure, and changes
to Session lifecycle semantics.

Existing runtime evidence and Evidence Archive behavior remain unchanged.
Controller initiation and StorageManager retrieval ownership are settled;
later Artifact Plane retrieval implementation remains outside this slice.

**Implementation status:** Slice 22 is complete following implementation,
manual validation, and independent audit PASS (W031, M010). All exclusions above
remain in force.

---

## Decision 245: Controller initiates StorageManager pull-based artifact collection

**Status:** Accepted

Post-session collection follows the Slice 22 handoff. LocalStorageManager owns
authoritative local scientific artifacts and manifests; AcquisitionNode publishes
manifest evidence; Ingestor retains it and compiles FinalizedArtifactCollectionHandoff.
Controller determines when collection occurs. StorageManager receives the handoff,
resolves source access, pulls bytes, and owns the additional globally managed copy.
Artifact bytes never pass through NATS or Ingestor. AcquisitionNode does not push
bytes. No separate transfer component is introduced.

---

## Decision 246: Slice 23 artifact retrieval uses SSH/SFTP

**Status:** Accepted

StorageManager initiates SSH/SFTP connections to source AcquisitionNode machines
and pulls source files. SSH/SFTP is the only retrieval mechanism in this slice;
no multiple-backend or transfer-plugin framework is introduced.

---

## Decision 247: Retrieval endpoints are deployment-local runtime configuration

**Status:** Accepted

Logical acquisition_node_id resolves to a retrieval endpoint through deployment-local
runtime configuration. Manifests and portable handoffs must not contain hostname/IP,
SSH usernames, passwords, private keys, or authentication tokens. StorageManager
consumes configuration but does not own its conceptual source; Controller/startup
orchestration may supply configuration or a minimal collaborator. A small resolver
is acceptable if necessary, not a NetworkManager, configuration service, or discovery daemon.

---

## Decision 248: One ArtifactManifest represents one scientific file

**Status:** Accepted

One ArtifactManifest represents exactly one scientific artifact, which is exactly
one file. Experiments may produce multiple artifacts. Each external file has its
own manifest. An associated framework timing/index file is a separate artifact
with its own manifest. This supersedes older wording in Decisions 192-193 and 200
only insofar as it implies a combined external-file and timing/index-file manifest;
their common stream lifecycle and persistence ownership remain unchanged.

---

## Decision 249: Existing manifest paths identify the single retrieval source

**Status:** Accepted

For framework-generated artifacts the source is local_storage_path; for externally
generated artifacts it is external_artifact_path. A separate framework timing/index
artifact uses its own local_storage_path. StorageManager retrieves exactly one file
per manifest. local_managed_paths is auxiliary managed-path information, not a
retrieval list. No new locator field is required by this contract.

---

## Decision 250: Global artifact destinations follow artifact identity

**Status:** Accepted

The deterministic destination is:

```text
<global_artifact_root>/<session_id>/<experiment_id>/<acquisition_node_id>/<artifact_manifest_id>/<original_filename>
```

No source_component_id or product identity is added to this hierarchy.

---

## Decision 251: Retrieval attempts the source without a separate existence probe

**Status:** Accepted

StorageManager attempts retrieval directly and handles its outcome. It does not
establish an exists(source) then retrieve(source) sequence.

---

## Decision 252: Artifact retrieval attempts are independent

**Status:** Accepted

Each artifact is attempted independently. One failure must not prevent attempts
for remaining artifacts. There is no fail-fast, retry, or replay machinery.

---

## Decision 253: StorageManager owns per-artifact retrieval outcomes

**Status:** Accepted

Each result includes artifact_manifest_id and outcome (success or failure).
Success includes global_destination; failure includes failure_information.
Do not unnecessarily duplicate identity or source information already available
through the associated manifest/handoff. Detailed retrieval outcomes are StorageManager-owned.

---

## Decision 254: Artifact collection exposes an aggregate outcome

**Status:** Accepted

After attempting the handoff, StorageManager exposes whether collection completed
fully or had failures. Controller need not interpret filenames, paths, SFTP details,
or per-file exceptions. Session lifecycle/completion consequences of aggregate
collection failure remain undecided and outside Slice 23.

**Subsequent clarification (Decision 303):** The former Q017 is resolved: later
global processing failure cannot retroactively change a completed Session.
This does not change Slice 23's retrieval/result contract or required
pre-completion cleanup and persistence.

**Slice 24 clarification:** Decision 270 extends aggregate reporting to include
light-verification outcomes. The historical Slice 23 retrieval aggregate remains
distinct from complete verified collection; no Session lifecycle policy is implied.

---

## Decision 255: Incomplete destinations are not final artifact copies

**Status:** Accepted

Transfer first writes a temporary/incomplete destination in the destination location.
Only successful completion promotes/renames it to the deterministic final filename.
No resumable transfer is introduced.

---

## Decision 256: Retrieval success requires transfer, destination closure, and promotion

**Status:** Accepted

Success requires SFTP transfer without error, successful destination writing/closing,
and successful promotion/rename to the deterministic final destination. Checksum
verification is not required.

**Slice 24 clarification:** This remains the retrieval-success contract.
Decisions 261-270 add separate verification after successful publication of the
global copy; they do not redefine successful retrieval as successful verification.

---

## Decision 257: Existing deterministic destinations are inconsistencies

**Status:** Accepted

One artifact identity has one deterministic global destination and one globally
managed copy. An unexpected existing/colliding destination is an invariant or
inconsistency failure, not overwrite, skip, replace, success-on-existing, or
automatic versioning.

---

## Decision 258: Missing finalization does not exclude artifact collection

**Status:** Accepted

Both finalized artifacts and artifacts missing finalization evidence are retrieval
candidates. The distinction remains identifiable through manifest/handoff state;
missing finalization must not cause an artifact to be discarded.

---

## Decision 259: Retrieval failures are represented without stopping other attempts

**Status:** Accepted

Represent failures including unavailable source nodes, SSH/SFTP connection failure,
invalid source locators/paths, unavailable sources, permission failures, interrupted
transfers, destination write failures, insufficient destination storage, promotion
failure, deterministic destination collisions, and malformed/incomplete required
handoff information. These become per-artifact failures where appropriate without
an elaborate new error taxonomy or stopping remaining attempts.

---

## Decision 260: Global collection leaves authoritative local artifacts unchanged

**Status:** Accepted

Transfer creates an additional StorageManager-owned global copy. LocalStorageManager
continues owning the authoritative local artifact and manifest. StorageManager must
not delete, modify, rename, move, or otherwise mutate the source artifact.

Slice 23 excludes background transfer daemons, retry/replay, resume, checksums,
source cleanup/retention policy, Ingestor restart reconstruction, transfer scheduling
policy, NWB/general export, and Session lifecycle consequences of aggregate failure.

**Implementation status for Decisions 245-260:** SSH/SFTP retrieval and explicit
Controller initiation are implemented with mock-backed automated tests. Slice 23
(M011) remains open pending real Jetson/SSH-SFTP deployment validation. W032
records software retrieval/handoff regressions and manual collection/verification
checks; no real SSH/SFTP deployment validation or M011 closure is claimed.

---

## Decision 261: StorageManager owns light verification of globally copied artifacts

**Status:** Accepted

StorageManager owns lightweight structural verification of the globally managed
copy after it successfully retrieves the artifact. LocalStorageManager retains
ownership of the authoritative local scientific artifact and ArtifactManifest.
Ingestor retains its existing information-intake and handoff responsibilities.
No separate Verifier component is introduced.

Verification asks whether the copy appears structurally valid under its applicable
light-verification contract. It is not scientific validation, interpretation,
normalization, restructuring, transformation, reconstruction, or NWB validation.
StorageManager copies artifacts as-is; scientific interpretation, transformation,
and NWB work remain later phases.

---

## Decision 262: Retrieval and verification have separate outcomes

**Status:** Accepted

Verification begins only after successful transfer, destination writing/closure,
and promotion/publication to the deterministic final destination under Decisions
255-256. Retrieval retains its success/failure outcome independently of subsequent
verification. If retrieval fails and no completed global copy exists, verification
is not attempted. Verification outcomes do not replace the Slice 23 retrieval
vocabulary or turn a successful copy into a failed transfer.

---

## Decision 263: Light verification uses four distinct outcomes

**Status:** Accepted

The accepted verification vocabulary is:

- `verified`: verification completed and every applicable required light check passed.
- `copied_unverified`: retrieval succeeded but no applicable format/layout verification contract exists.
- `structurally_invalid`: verification completed and established a violation of the applicable structural contract.
- `verification_failed`: an operational failure prevented verification from reaching a conclusion, such as a read/access failure.

An artifact expected to use the supported HDF5 layout that cannot be opened as
valid HDF5 is structurally_invalid, not verification_failed. An operational
inability to access/read it is distinct from establishing invalid structure.
Source-missing or copy-failure outcomes do not belong to this vocabulary.

---

## Decision 264: The first light-verification contract is specific to the current LocalStorageManager HDF5 layout

**Status:** Accepted

The first supported contract applies to the HDF5 layout currently produced by
LocalStorageManager, not to the device type that produced the artifact. Its
current root datasets are:

```text
/frames
/session_time_s
/experiment_time_s
/acquisition_node_local_time_s
/frame_index
/timestamp_status
/record_metadata_json
```

This is a format/layout-specific contract, not a universal HDF5 schema and not
camera-specific verifier ownership. Future products may use different HDF5
layouts with their own verification contracts. HDF5 does not imply camera, and
camera does not define general verification interfaces. Slice 24 does not
introduce a verifier plugin framework, registry, or speculative abstractions.

---

## Decision 265: Current-layout HDF5 light checks use structure, identity, and existing counts

**Status:** Accepted

For the supported LocalStorageManager HDF5 layout, required light checks are:

1. The global file is accessible/readable.
2. The file has nonzero byte size; zero scientific records remain valid.
3. The file opens successfully as HDF5.
4. Embedded `artifact_manifest_id` exists and agrees with the identifying ArtifactManifest.
5. The seven required datasets in Decision 264 exist.
6. Their aligned record/frame dimension lengths agree.
7. `persisted_frame_count` agrees with the applicable dataset lengths and, when available, the authoritative persisted count supplied by finalized manifest information.

Creation-manifest information without received finalization evidence must not
be treated as supplying a finalized expected count. Compare only expectations
that actually exist. Empty finalized artifacts remain valid under the existing
stream contract; a nonempty file requirement is not a nonempty-record requirement.

---

## Decision 266: Light verification remains bounded without scientific-data scans or checksums

**Status:** Accepted

Light verification uses read-only opening, dataset/group existence, shapes,
lengths, and small root attributes. It must not require reading every frame,
loading the full scientific dataset, scanning the complete artifact, reading or
numerically validating every timestamp, or reading every per-record metadata
value. Session reconstruction, scientific analysis, and NWB validation are excluded.

Slice 24 does not require SHA hashes, full-file checksum passes, byte-by-byte
source/global comparison, or expensive integrity scans. Checksums and deeper
verification remain possible future architecture.

---

## Decision 267: Verification preserves the copied artifact regardless of outcome

**Status:** Accepted

Verification is descriptive and non-destructive. A structurally_invalid or
verification_failed result does not authorize deleting, modifying, repairing,
rewriting, replacing, or transforming the globally copied artifact. Preserve
the copy, which may contain scientifically valuable partial data. Authoritative
local ownership and unchanged-source requirements remain intact.

---

## Decision 268: Slice 24 reuses existing product and manifest contracts

**Status:** Accepted

Slice 24 does not redesign ArtifactManifest or ScientificProductDeclaration,
add verification-specific `storage_schema`, `frame_shape`, or `frame_dtype`
manifest fields, or formalize a universal scientific-product schema. Existing
contracts are used.

No JSONL structural verifier is defined. Successfully copied artifacts with no
applicable format/layout contract receive copied_unverified. Rules for JSONL,
additional HDF5 layouts, binary electrophysiology, and other scientific formats
remain future work.

The broader ScientificProduct structural contract remains future architecture:
how arbitrary products describe structure, how device/component capabilities
constrain products, how Experiment configuration selects those capabilities,
how instantiated expectations are represented, and how persisted layouts relate
to verification contracts. NWB transformation/standardization is later work.

---

## Decision 269: Per-artifact collection results include separate verification information

**Status:** Accepted

Extend the existing Slice 23 per-artifact result concept to represent
`artifact_manifest_id`, retrieval outcome, `global_destination`,
`verification_outcome`, and `verification_information` without unnecessary
duplication. This defines required information, not a new implementation API.
The retrieval outcome remains distinct; no verification is attempted without
a completed global copy under Decision 262.

Verification information gives a concise explanation where appropriate, such
as missing required datasets, identity mismatch, dataset-length mismatch,
persisted-count mismatch, or an expected HDF5 artifact not opening as valid
HDF5. No exhaustive verification-report subsystem is introduced.

---

## Decision 270: Aggregate collection reflects verification without choosing Session consequences

**Status:** Accepted

StorageManager aggregate reporting reflects both retrieval and verification.
Every requested artifact copied successfully with every applicable verifier
returning verified may represent complete verified success. The aggregate must
also represent collections that are not completely verified/successful because
of copied_unverified, structurally_invalid, verification_failed, or retrieval
failure outcomes. Detailed explanations remain per artifact.

Controller need not understand filenames, HDF5 dataset names, individual checks,
SFTP errors, or verification implementation details. Session lifecycle and
completion consequences remain a future high-level architecture question; Slice
24 does not choose them. No retry/replay, resumable transfer, repair, deletion,
new verification service, or new Session lifecycle policy is introduced.

**Subsequent clarification (Decision 303):** The historical open-policy wording
above is resolved for later global processing: failure cannot retroactively
change a completed Session's lifecycle. Verification outcomes, aggregate
reporting, pre-completion requirements, and the coordination contract are unchanged; Q019 is now CLOSED in W050.

**Implementation status for Decisions 261-270:** Complete (M012, W032), with
26 focused verification tests, 21 retrieval/handoff regressions, and six independent
manual IPython scenarios passed. Final discovery ran 340 tests: 333 passed,
7 optional rendering skips, and no failures. The initial audit failed on the
Decision 263 diagnostic-text classifier; the correction uses failure provenance,
and the targeted independent re-audit passed with Decision 263 satisfied and no
remaining implementation findings. W032 records the previously executed/reported
validation and audit history. No real SSH/SFTP deployment validation is claimed.

---

## Decision 271: StorageManager produces one compiled persistent evidence record per global collection pass

**Status:** Accepted

StorageManager produces one compiled persistent runtime evidence record per
completed post-session global artifact collection pass, using:

```text
evidence_type = global_artifact_collection_evidence
is_persistent = True
```

The record contains a collection-level envelope and a list of per-artifact
results. It is minimal operational evidence, not a duplicate ArtifactManifest.
Its conceptual minimum content is:

```text
session_id
storage_manager_id
started_at
finished_at
artifact_results:
    artifact_manifest_id
    experiment_id
    acquisition_node_id
    artifact_type
    collection_status
    verification_status
    global_artifact_locator
    file_size_copied
    failure_information
```

Existing framework names/style may represent equivalent concepts. Experiment,
AcquisitionNode, and artifact-type information comes from the authoritative
ArtifactManifest/handoff; StorageManager must not independently infer it.
No source-device/product identity, local locator, scientific schema, frame
shape/dtype, checksum, verification method/version, or handoff ID is added.
An unavoidable implementation dependency requiring additional information must
be reported rather than silently expanding the record.

Do not emit one RuntimeEvidenceMessage per artifact or create a separate
evidence artifact, file, or archive. This replaces any tentative per-artifact
persistent-evidence proposal, not the per-artifact return results in Decision 253.
The existing Evidence Archive remains the destination under Decisions 219-231.

---

## Decision 272: Global collection evidence records only attempted artifacts and separate existing outcomes

**Status:** Accepted

Collection status reuses Slice 23's `success` / `failure`: it describes only
creation of the global copy, not acquisition, Experiment lifecycle, local
finalization, or scientific validity. Verification status reuses Decision 263
exactly: `verified`, `copied_unverified`, `structurally_invalid`, and
`verification_failed`. Retrieval and verification remain separate under
Decisions 262 and 269. If collection fails before a completed copy exists and
verification does not occur, verification status is absent/null according to
existing conventions; no `not_attempted` or other verification status is added.

Evidence contains results only for artifacts actually attempted by StorageManager.
Do not manufacture failures for artifacts never reached if a pass terminates,
or introduce an `unattempted` status. Independent attempts remain required by
Decisions 252 and 259; this rule does not authorize fail-fast collection.

The persistent record has no aggregate success/failure field. Existing aggregate
collection reporting to Controller remains governed by Decisions 254 and 270;
evidence must not create a competing overall-success definition.

---

## Decision 273: Global collection evidence uses operational wall-clock timestamps

**Status:** Accepted

`started_at` and `finished_at` cover the entire StorageManager collection pass,
including verification where applicable. They are operational/audit wall-clock
timestamps, not Session Time, Experiment Time, AcquisitionNode local time,
synchronization observations, or scientific timing.

Use an ordinary wall-clock mechanism suitable for audit timestamps, preserving
testability where practical. Do not use
`SynchronizationManager.current_session_time_s`, create a synchronized
operational clock, or couple StorageManager to Ingestor's wall-clock implementation.
Scientific Session Time freezes when acquisition ends and must not be extended
through post-session copying/verification. Decisions 150-152 retain scientific
timing ownership unchanged.

---

## Decision 274: StorageManager owns collection evidence and publishes through the existing durable boundary

**Status:** Accepted

The component that owns the operational facts produces its own evidence.
StorageManager constructs and publishes `global_artifact_collection_evidence`;
Controller orchestrates collection but must not translate StorageManager return
values into StorageManager evidence. This does not transfer ownership of local
artifacts/manifests or let StorageManager interpret other components' evidence.

Reuse RuntimeEvidenceMessage with `is_persistent=True` and the existing durable
publication capability, `NatsCommunicationBoundary.publish_evidence(...)`, or its
appropriate existing adapter/interface. StorageManager currently lacks that
dependency; implementation requires only the smallest appropriate wiring to
the existing capability, without specifying a new public API here.

```text
StorageManager-owned evidence with original session_id
    -> existing durable runtime-evidence publication
    -> generic Ingestor intake and persistent compilation
    -> existing Evidence Archive for the same Session
```

Durable acceptance by the configured JetStream evidence stream satisfies the
existing publication contract; failure is reported through DurablePublicationError.
No StorageManager-specific acknowledgment, event bus, transport, evidence file,
archive, generic communication framework, or special Ingestor persistence logic
is introduced. Decisions 142-146 and 219-231 retain their transport, persistence
intent, intake, compilation, and writing responsibilities.

---

## Decision 275: Session acquisition end is distinct from Session processing finalization

**Status:** Accepted

Session acquisition end means scientific acquisition has ended, scientific
Session Time freezes, and Experiments have been appropriately ended; post-session
framework processing may remain.

Session processing finalization means required post-session processing has
completed and persistent post-session evidence has been handled; the Evidence
Archive can then be finalized.

One Session may contain many Experiments. Ending an individual Experiment does
not trigger global Session artifact collection or Session-wide finalization.
Controller owns overall Session processing finalization and remains active
through required post-session operations. Session retains lifecycle ownership;
Controller does not translate StorageManager evidence.

The Evidence Archive must not be treated as finally complete before legitimate
post-session persistent evidence has had an opportunity to be produced. This
refines the processing order of Decision 228 while preserving Decision 229's
requirement for final persistence before successful Session completion. It does
not introduce a lifecycle state or choose aggregate collection consequences.
Collection evidence must not reopen Experiments, rewrite their lifecycle, change
acquisition success into failure, change local artifact finalization outcomes,
or reinterpret scientific Session success. Global collection remains a separate
operational outcome; further lifecycle policy stays open under Q017.

**Subsequent clarification (Decision 303):** Q017 is resolved: later global
processing failure cannot retroactively change a completed Session's lifecycle.
The historical open-policy wording above does not reopen that question. Required
pre-completion persistence/cleanup and Q019's consumption coordination remain
unchanged; collection evidence and ownership remain governed by Decisions 271-275.

The evidence-enabled implementation exposes an explicit sequence:
`stop_session()`, await `collect_session_artifacts_with_evidence()`, then
`finalize_session()`. Collection publication therefore precedes archive writing
without extending scientific Session Time. The legacy synchronous collection API
remains available without a configured evidence publisher; it is not the
evidence-enabled finalization sequence.

How Controller establishes that all durably published Session evidence has
actually been consumed/accepted by Ingestor before final compilation/archive
closure remains open under Q019. This is Session-wide, not StorageManager-specific.
Slice 25 must not solve it with consumer-ACK waiting, polling, sleeps, arbitrary
delays, evidence-count assumptions, or new broker protocols. If minimum wiring
cannot proceed without deciding that broader protocol, implementation must stop
and report the dependency. No retry/resume/background transfer, checksum, export,
ArtifactManifest/product redesign, scientific timing change, or Evidence Archive
format change is introduced.

**Implementation status for Decisions 271-275:** Complete (M013, W033), with
18 focused tests passed, Slice 23/24 and communication/archive regressions passed,
and full discovery 351 passed plus 7 optional rendering skips (358 total).
Independent manual Scenarios 1-5 and 6B passed; Scenario 6's mistargeted injection
was inconclusive, not a failed implementation validation. The initial audit FAIL
identified P1 (finalization overtaking pending publication) and P2 (copied-size
lookup causing fail-fast). Both were corrected and independently re-audited as
FIXED, with final verdict PASS and Decisions 271-275 satisfied. W033 records the
validation and correction history. No Session-wide consumption guarantee is claimed;
Q019 is CLOSED following overall software integration validation (W050). No new validation was run during documentation closure.

---

## Decision 276: Ingestor journals all accepted runtime evidence before broker acknowledgment

**Status:** Accepted

Phase 14 / Slice 27 introduces a minimal append-only local JSONL recovery journal
owned by Ingestor. Each accepted RuntimeEvidenceMessage is a complete journal entry,
reusing the existing plain-data representation/serialization where practical.
The journal is the durable accepted-message history; the normal in-memory
representation remains its working view, not a periodically saved snapshot.

```text
Producer -> NATS / JetStream -> Ingestor receives RuntimeEvidenceMessage
    -> validate -> durably append complete message to local recovery journal
    -> update normal accepted-evidence working view -> ACK broker delivery
```

**Principle:** Journal before ACK. Buffered write completion is insufficient;
use the simplest appropriate flush/fsync-equivalent local durable-write boundary,
not a transactional storage layer.

**Live-process acceptance:** If append or durability synchronization reports
failure, the current Ingestor process must not update accepted working state
or ACK delivery. Surface the failure through the existing error path and fail
closed for further intake until restart because the durable outcome is uncertain.
The error means the live process cannot claim acceptance; it does not establish
that no complete journal record survived.

**Restart reconstruction:** The recovery journal is authoritative for the
complete durable history available after restart. Every complete, valid entry
is reconstructed as accepted evidence, including an entry that survived an
operation that may previously have reported a durability error. That error is
not durable negative evidence that the record failed to survive. A clearly
incomplete/truncated final JSONL entry is omitted as an interrupted, unaccepted
write; corruption of completed history is a recovery-integrity failure and
must not be silently skipped. Reconstruction remains atomic under Decision 278.

JetStream redelivery and Decision 277 evidence_id semantics converge uncertain
outcomes: if no complete valid entry survived, redelivery follows normal journaled
acceptance; if an entry was reconstructed, identical redelivery is already accepted
and is ACKed without a second append or processing. Conflicting same-ID content
remains an error, never an overwrite or successful acceptance ACK.

No candidate/commit records, commit markers, second durable acceptance record,
or transactional journal protocol is introduced. Live acceptance depends on
reported durability success; restart reconstruction depends on complete valid
journal history. Ingestor adds no retry machinery, second buffering layer,
or severity taxonomy.

Journal all accepted evidence, whether is_persistent is true or false. Crash
durability is not permanent persistence: nonpersistent messages remain excluded
from permanent Evidence Archive selection. The journal is temporary recovery
state, not the Evidence Archive, ingest audit, Session Record, a database, or a
replacement for JetStream. No separate manifest store, generic persistence
service, recovery component, or continuously rewritten snapshot is introduced.

---

## Decision 277: Runtime evidence identity makes Ingestor acceptance idempotent

**Status:** Accepted

RuntimeEvidenceMessage.evidence_id is the acceptance/deduplication key. The
accepted crash window is durable journal append followed by crash before ACK;
after reconstruction, JetStream may redeliver the same message. Do not eliminate
that window by acknowledging earlier.

Same evidence_id and same evidence content means already accepted: do not
journal, add, or process it again; ACK redelivery. Same evidence_id with different
content is an inconsistency/error: do not silently choose a version or overwrite
accepted evidence. No additional identity or sequence-number scheme is introduced.
This applies to Ingestor acceptance, not Controller action execution or producer
publication recovery.

---

## Decision 278: Ingestor reconstructs its normal working view for a known Session

**Status:** Accepted

On startup/restart for the same known Session, Ingestor checks for that Session's
existing recovery journal. If present, it replays accepted RuntimeEvidenceMessages,
rebuilds the normal accepted-evidence view and evidence_id deduplication knowledge,
then resumes intake. Reconstructed logical state is equivalent to the accepted
working view that would have existed without the crash. Controller issues no
special reconstruction command and no parallel reconstructed-state model exists.

The existing Slice 22 artifact handoff compiler operates on that normal restored
view without changed semantics, a second compiler, special format, recovery
version, or reconstructed marker. ArtifactManifest and its ownership are unchanged.

If valid reconstruction cannot be established, surface failure clearly and do
not continue with partially reconstructed state. A clearly incomplete/truncated
FINAL JSONL entry may be treated as an interrupted, unaccepted append: do not
reconstruct it and rely on broker redelivery. Malformed/corrupt earlier completed
entries are recovery-integrity failures, not entries to silently skip. No detailed
failure taxonomy is introduced. Existing failure preservation may be used only
when Ingestor is sufficiently functional to preserve information safely; recovery
evidence is not guaranteed when valid state cannot be established.

---

## Decision 279: Successful Ingestor reconstruction produces persistent recovery evidence

**Status:** Accepted

Ingestor normally starts once per Session. Startup again for the same known
Session with an existing recovery journal establishes recovery startup; no
heartbeat file, crash flag, clean-shutdown marker protocol, or process monitor
is required.

After successful reconstruction, Ingestor creates RuntimeEvidenceMessage with
evidence_type=ingestor_recovery_evidence and is_persistent=True. Its minimal
conceptual information is session_id, Ingestor identity, recovered_entry_count,
and recovery_time, using existing envelope/identity conventions where possible.
Do not duplicate recovered evidence IDs or contents.

This evidence records that accepted state was reconstructed during the Session.
It enters the NORMAL acceptance path: journal it durably, add it to normal
accepted working state, and include it later in permanent evidence compilation
because its persistence flag is true. No separate recovery-evidence storage exists.

---

## Decision 280: Local Ingestor recovery does not define application restart or finalization

**Status:** Accepted

Slice 27 assumes a known Session and recovers runtime-evidence working state
while acquisition or post-session processing may be active. It does not use
permanent Evidence Archive, ingest audit, or Session Record as the primary
recovery source, transfer scientific storage ownership to Ingestor, or redesign
RuntimeEvidenceMessage, ArtifactManifest, handoff, Controller lifecycle,
SynchronizationManager, NATS/JetStream, or permanent record layout.

Journal cleanup/retention is deferred: the journal must remain available long
enough to satisfy crash recovery. Future architecture decides safe deletion,
deletion ownership, abandoned journals, retention across program restart, and
cleanup after successful processing finalization. Application-wide discovery
and selection of unfinished Sessions, multiple unfinished Session recovery,
and complete Controller/application lifecycle restoration are also deferred
(Q024), not implemented through new orchestration or Session cleanup policy.

At this decision's original implementation closure, Q019 remained open; it is now
CLOSED through W041-W050. Local durable Ingestor acceptance/reconstruction alone does not
tell Controller whether all already-published Session evidence has been consumed
before final archive compilation. No consumer drain, polling, delays, expected
counts, StorageManager-specific ACK protocol, or broader finalization protocol
is introduced.

**Implementation status for Decisions 276-280:** Complete (M014, W034), with explicit
known-Session recovery journaling, evidence_id deduplication, startup reconstruction,
and persistent recovery evidence through the existing Ingestor/NATS boundary.
W034 records manual Scenarios 1-5 PASS, Scenario 6's architectural ambiguity and
the clarification of Decision 276, Scenario 6R PASS, the initial audit FAIL for
a separate blocking final-entry integrity defect, its minimal correction,
Scenario 7's nine checks PASS, and targeted independent re-audit PASS. All five
decisions are SATISFIED. Final independently confirmed automated results are
25 recovery tests, 39 storage/communication/NATS regressions, and 82
artifact/Controller regressions passed; full discovery 376 passed, zero failed,
and seven optional rendering skips (383 total). No architectural meaning,
journal protocol, or public API changed during correction or closure.
Slice 26 was redundant with Slice 25 and is not a separate implementation slice;
existing Slice 25 completion (M013, W033) is preserved.

---

## Decision 281: Controller owns Session launch and runtime assembly

**Status:** Accepted

**Clarified by Decisions 295-301:** Controller coordinates independently running
participants over the existing NATS boundary; it neither launches their processes
nor manages NATS. Session retains the initialization-completion boundary while
each participant prepares its own local runtime. No remote Session replicas exist.

Controller owns Session launch, runtime orchestration, stopping, and finalization.
Controller may exist before Session and creates Session through its launch
process; Session does not own Controller. Session retains lifecycle ownership,
and existing acquisition, timing, device, ingest, and persistence owners remain
unchanged. A GUI, CLI, script, or other client may request launch; client design
is outside Slice 28.

Runtime participants may run in different processes or machines. Orchestration
uses existing communication mechanisms and must not assume direct Python-object
access. The first target is one PC, one Jetson, and one camera, not an
architectural cardinality limit. Multiple Controllers and AcquisitionNodes remain
possible. No StartupManager, CleanupManager, UberController, or other startup
authority is introduced.

**Principle**

Controller launches and assembles runtime; domain components retain ownership.

---

## Decision 282: RuntimeParticipant identity is deployment-scoped and Session-independent

**Status:** Accepted

Reuse RuntimeParticipant with component_type and component_id. Its identity is
deployment/lab-scoped and exists independently of Session identity. Controller,
AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager are runtime
participants; scientific devices such as cameras are not.

RuntimeParticipant contains no hostnames, IP addresses, NATS subjects, SSH paths,
or transport addresses. No alternative identity system is introduced. Final
SessionConfig identifies the expected participation for that Session; it does
not create the deployment identities. Slice 28 uses participants already
available to Controller through existing communication mechanisms. Deployment
registration, discovery, and address resolution remain deferred under Q022.

---

## Decision 283: AcquisitionNode owns pre-Session declared device inventory

**Status:** Accepted

Each AcquisitionNode owns a node-scoped declared device inventory independent
of Session creation. Reuse DeviceDeclaration and ScientificProductDeclaration.
Inventory membership associates a declaration with its node; do not add a
redundant node ID to every DeviceDeclaration.

The inventory describes expected devices and their supported scientific products,
not automatic hardware discovery. Declared devices remain visible when
disconnected or not ready. AcquisitionNode exposes declared inventory,
scientific-product capabilities, and current device readiness to Controller.
Session resource selection consumes this inventory rather than creating or
redefining it. DeviceManager retains live adapter lifecycle responsibility.

Deployment configuration file formats, adapter installation/registration, and
automatic discovery are not introduced by this decision.

---

## Decision 284: Node readiness separates technical readiness from reservation and unknown availability

**Status:** Accepted

AcquisitionNodeReadiness is node/deployment-scoped and queryable before Session
creation. Its conceptual session_id is replaced with
reserved_for_session_id: str | None. None means unreserved; a non-null value
identifies the Session holding the reservation. Technical readiness and
reservation are independent: a ready node may be reserved and unavailable to
another Session. Use reserved, not busy.

Controller interprets current evidence as follows:

- Valid ready report, unreserved: available.
- Valid ready report, reserved for another Session: technically ready but unavailable.
- Valid report with ready=False: not ready.
- No valid current report: unknown.

Unknown is Controller's interpretation of missing/invalid current evidence,
not a new readiness enum or an additional boolean readiness value. A report is
a snapshot; successful atomic reservation, not the snapshot, is authoritative.

---

## Decision 285: Node readiness includes every declared enabled device

**Status:** Accepted

Every successful AcquisitionNode readiness report contains a DeviceReadiness
result for every declared enabled device. Missing adapters, disconnected
devices, and failed readiness determination produce ready=False with an
explanatory reason. Enabled declared devices must not silently disappear from
the report. This completeness responsibility belongs to AcquisitionNode and
does not introduce device discovery or move adapter lifecycle out of DeviceManager.

---

## Decision 286: Node technical readiness excludes Session-specific device criticality

**Status:** Accepted

AcquisitionNodeReadiness.ready means the node's required framework/service
prerequisites are ready. It must not become false merely because an unrelated
scientific device is unavailable. Controller evaluates individual device
readiness against devices selected for the prospective Session.

Remove the conceptual Session-specific required field from DeviceReadiness.
Session-selection criticality is DeviceDeclaration.required, not a property
of device technical readiness or globally fixed device criticality. Preserve
ServiceReadiness.required for required framework/service prerequisites.

The historical required-device aggregation in AcquisitionNodeReadiness and
adapter-supplied required-device gating in Decisions 051-052 and 075 are
superseded by this contract. Existing readiness aggregation paths must be
reconciled during implementation, not treated as competing launch authorities.

---

## Decision 287: AcquisitionNode owns atomic Session-keyed exclusive reservations

**Status:** Accepted

AcquisitionNode is the first exclusive reservation unit, not an individual
device. A Session may reserve multiple nodes; each node may be reserved for
only one Session at a time. AcquisitionNode itself owns reservation authority,
without a central scheduler or reservation registry.

Controller requests reservation using the intended session_id. Atomically:

1. Unreserved: reserve for that Session and succeed.
2. Reserved for the same Session: succeed idempotently.
3. Reserved for another Session: reject without changing reservation.

Release is also keyed by session_id; only the owning Session identity may
release its reservation. No reservation IDs, launch tokens, leases, heartbeats,
or timeouts are introduced. Availability reports are snapshots; successful
atomic reservation is authoritative.

---

## Decision 288: Reservation ends after acquisition and local artifact finalization

**Status:** Accepted

**Failed-initialization qualification (Decision 300):** Normal reservation
duration below remains unchanged. If initialization may have started during a
failed launch, cleanup must be confirmed before reservation release; an absent
initialization response does not prove the node is safe to release.

Reservation covers scientific acquisition and local scientific-artifact
finalization, not global artifact collection. Controller releases the node
after acquisition and local artifact finalization are complete.

StorageManager may retrieve artifacts much later, after the node has participated
in other Sessions. Retrieval must not retain or reacquire the original reservation.
Release does not delete or overwrite authoritative local artifacts. Local
retention/deletion authorization and stale-reservation recovery remain future
concerns under Q020 and Q024.

---

## Decision 289: Controller resolves and reserves resources before creating Session

**Status:** Accepted

**Clarified by Decisions 298-301:** After reservation and final configuration
resolution, Controller requests participant-local Session preparation. Launch
requires confirmed success from every mandatory participant, not merely a
readiness snapshot, publish acknowledgment, or newly constructed Session.

The accepted conceptual launch order is:

1. Receive prospective Session resource selections.
2. Allocate an intended session_id at the beginning of the attempt.
3. Obtain current participant, node, and device readiness/availability.
4. Evaluate required and optional scientific resources.
5. Request atomic reservations from selected AcquisitionNodes.
6. Handle reservation failures according to selected resource criticality.
7. Construct final resolved SessionConfig.
8. Create and initialize Session.
9. Declare launch success only after all acquisition-critical participants
   complete required initialization/preparation.

Allocated identity does not mean Session creation or launch succeeded. Failed
launch IDs are never reused. Reuse existing declarations and selections where
appropriate; no SessionLaunchIntent class is introduced solely for prospective
selections. No new Session lifecycle state or complex launch state machine is
introduced.

---

## Decision 290: Selected devices determine launch criticality

**Status:** Accepted

AcquisitionNodes are not intrinsically required or optional. Criticality comes
from scientific resources selected for the prospective Session through
DeviceDeclaration.required:

- Any required selected resource on a node makes that node launch-critical.
- A node with both required and optional selected resources is launch-critical.
- If all selected resources on a node are optional, reservation failure may
  omit those resources without blocking launch.
- Failure of a required selected device blocks launch.
- Unavailable optional devices may be omitted.

No product-level required/optional semantics are added. ScientificOutputSelection
does not gain required for Slice 28. Experiment-scoped scientific-output
selection remains distinct from Session-level device selection, including the
existing required scientific-preparation contract of Decisions 209 and 235-239.

---

## Decision 291: SessionConfig contains only final resolved Session selections

**Status:** Accepted

SessionConfig is the final resolved configuration of the Session that will
actually run, not an unresolved prospective resource wish list. Controller
constructs it after readiness checks, reservation outcomes, and optional-resource
resolution. Session then owns and preserves its accepted configuration under
Decisions 070 and 072.

If camera A is required and camera B is optional but unavailable, only camera A
remains in SessionConfig.selected_devices. Omitted optional resources must not
remain selected. This does not redesign Experiment-scoped scientific-product
selection or introduce a separate prospective-selection data model.

---

## Decision 292: Ingestor and SynchronizationManager are mandatory launch prerequisites

**Status:** Accepted

**Clarified by Decision 301:** Pre-Session service readiness and confirmed
Session-specific preparation are separate requirements. Each participant prepares
its own local state; neither receives an AcquisitionNode-style reservation.

Ingestor and SynchronizationManager readiness are mandatory launch prerequisites.
If either is unready, unreachable, or unknown because no valid response was
obtained, launch fails. They do not use AcquisitionNode-style exclusive reservations.
Required NATS communication readiness remains governed by Decision 141.

StorageManager is not a Session-launch prerequisite and need not be running or
ready for launch. Its global artifact-collection responsibility is separate
from scientific acquisition. This does not waive acquisition-local persistence
requirements, introduce another persistence owner, or alter the existing
final-persistence success requirement of Decision 229. Shared multi-Session
Ingestor/StorageManager scheduling is deferred.

---

## Decision 293: Controller rolls back failed launch reservations

**Status:** Accepted

**Qualified by Decision 300:** Controller must request cleanup wherever
initialization may have started and obtain confirmation before releasing that
node's reservation. Missing/invalid/unresolved initialization or cleanup results
do not prove remote state is absent. An unconfirmed cleanup leaves the reservation
in place; the general release obligation below is not permission for unsafe release.

Until launch succeeds, Controller owns rollback. Failure in required readiness,
reservation, final configuration construction, Session creation, or
acquisition-critical initialization/preparation results in failed launch,
release of every node reservation acquired by that attempt, operational failure
returned to the requester, and no reuse of the allocated Session ID.

Constructing Session alone is insufficient for launch success. After success,
reservations follow normal acquisition/local-finalization duration. Existing
Session lifecycle and domain-owned cleanup/finalization remain intact. No retry,
crash recovery, lease, or complex launch state machine is introduced.

---

## Decision 294: Pre-Session launch failures are operational results, not durable launch journals

**Status:** Accepted

Controller returns operational launch success/failure to the requesting client.
Slice 28 adds no durable pre-Session launch-attempt record, launch journal, or
separate launch evidence subsystem. Failed pre-Session attempts must not be
forced through Ingestor. Existing evidence mechanisms remain available for
normal Session operations; durable unsuccessful pre-Session auditing is deferred.

GUI/client design, central scheduling/device sharing, discovery, deployment
configuration/address resolution, daemon supervision, shared multi-Session
scheduling, Controller crash recovery/stale reservations, leases/timeouts/
heartbeats, retry, collection scheduling, local retention/deletion, application
restart/journal cleanup, and Session-wide evidence consumption before final
archive closure remain future concerns tracked in open_questions.md.

**Implementation status for Decisions 281-294:** Implemented with automated
broker-double tests; M015 remains pending independent manual validation and
audit. No live NATS, multi-process, hardware, manual validation, independent
audit, or new validated workflow is claimed. Completed M014/W034 and
all unrelated completed slices retain their recorded scope and status.

---

## Decision 295: Participant startup and NATS connectivity are independent of Session lifecycle

**Status:** Accepted

During current development and validation, NATS/JetStream is started manually in
a separate process, and Controller, AcquisitionNodes, Ingestor,
SynchronizationManager, StorageManager, and other participants are started
manually in independent processes. Participants may run on different PCs or
Jetsons and each connects independently to the existing NATS infrastructure.

The intended deployment uses independently running, long-lived RuntimeParticipant
services distributed as needed. Manual-shell startup is temporary development
infrastructure; startup scripts are not the intended deployment architecture.
Controller does not start/stop NATS or launch participant processes. Communication
contracts support both manually launched processes and future services.

Required NATS connectivity must be established before claiming operational
distributed readiness. If NATS is unavailable at startup, report a clear
connection error and fail startup rather than wait indefinitely or claim readiness.
Controller cannot launch a distributed Session without its required connectivity.
Connectivity alone proves neither scientific readiness nor resource availability;
communication loss after startup is not successful command completion.

Startup automation, service supervision, daemon management, automatic retry, and
reconnection policy remain deferred. NATS remains external infrastructure.

---

## Decision 296: Pre-Session commands address participants independently of Session identity

**Status:** Accepted

The existing NATS architecture supports communication before a Session exists.
Address participant-scoped commands using the existing RuntimeParticipant
component_type/component_id, independently of Session identity. The general
command envelope may omit session_id for operations not concerning a Session.
Session-specific operations include and validate a real session_id; never use
empty, placeholder, or fabricated Session identities.

- check_readiness: Session ID not required.
- reserve: real intended Session ID required.
- initialize_session: real intended Session ID required.
- Acquisition commands: real Session ID required and must match the active binding.

Reuse existing command/result conventions and the NATS communication boundary,
without a second communication framework. This supplements Decisions 128-130's
historical Session-bound command assumptions without changing evidence ownership.
Shared NATS/JetStream infrastructure remains compatible with future simultaneous
Sessions; Slice 28 does not implement multi-Session scheduling.

---

## Decision 297: AcquisitionNode owns Session binding across a Session-independent communication lifecycle

**Status:** Accepted

NatsAcquisitionNodeCommunication must not require Session binding at construction
or be recreated per Session. It connects before Session creation, accepts
participant-scoped readiness and Session-keyed reservation commands, routes
Session initialization requests to AcquisitionNode, accepts acquisition commands
only for the currently bound Session, and remains connected after binding clears
for subsequent Sessions.

AcquisitionNode owns authoritative reservation and local Session-binding state.
At most one active Session binding is permitted per node. Communication handlers
route commands and validate them against node state; they own no separate binding,
reservation, or lifecycle authority. RuntimeParticipant identity is unchanged.

---

## Decision 298: Remote Session initialization authorizes node-local runtime and storage preparation

**Status:** Accepted

After successful node reservation and final SessionConfig resolution, Controller
initiates remote initialization with the intended session_id, selected devices
assigned to that node, relevant Session-specific device configurations, and
relevant scientific selections, reusing existing configuration structures.
AcquisitionNode verifies the Session ID matches its reservation and owns its
local binding and initialization; existing Experiment-scoped scientific-output
selection is not redesigned.

Decision 197's Session creation responsibility means Session initialization
authorizes creation of Session-scoped LocalStorageManagers. Each AcquisitionNode
physically creates its own LocalStorageManager in its own process using its
deployment-defined local storage root and configuration. LocalStorageManager
retains local scientific persistence, stream, path, artifact, and manifest ownership.

Controller must not choose node filesystem roots, construct local artifact paths,
specify Session/Experiment directory structures, or instantiate remote managers
through direct Python references. SessionConfig.local_storage_roots currently
allows caller-supplied node roots in the historical local implementation. That
field is not an accepted Controller authority to select or override remote roots
in distributed launch; root selection belongs to the node's deployment-local
configuration. This qualifies Decision 234's historical Session-override contract
for distributed launch. No replacement configuration format or API is defined here.

Session retains scientific lifecycle and the initialization-completion boundary;
Controller owns orchestration, not participant-local resources. No remote Session
replicas, new startup managers, or additional lifecycle authority are introduced.

---

## Decision 299: Launch requires confirmed participant initialization results

**Status:** Accepted

Each AcquisitionNode reports initialization through existing NATS command/result
conventions. Confirmed success requires the requested binding established,
selected devices prepared, Session-scoped LocalStorageManager initialized, and
required local Session preparation completed. Explicit failure means initialization
did not complete and includes an explanatory reason.

Missing, invalid, or unresolved responses mean initialization is unconfirmed, not
necessarily failed. Controller must not declare launch successful on unconfirmed
initialization or equate a missing acknowledgment with proof that no remote state
was created. Transport publication acknowledgment is not initialization success.

Every mandatory participant must independently confirm preparation; initialization
need not be simultaneous. No distributed transaction coordination is introduced.

---

## Decision 300: Failed initialization requires confirmed local cleanup before node release

**Status:** Accepted

**Sequential-reuse clarification (Decision 302):** Confirmed device shutdown
and required cleanup permit return to DECLARED for subsequent initialization.
Failed or unconfirmed cleanup never authorizes reuse or reservation release.

Controller owns overall launch rollback; each participant owns cleanup of its own
partially initialized Session runtime. AcquisitionNode provides an idempotent,
Session-keyed initialization-abort operation. The accepted sequence is:

1. Controller requests cleanup of Session initialization that may have started.
2. AcquisitionNode stops and cleans up partially initialized runtime resources.
3. AcquisitionNode confirms cleanup.
4. Controller releases the node reservation.
5. AcquisitionNode clears the active Session binding and becomes available again.

A missing initialization acknowledgment does not authorize immediate reservation
release. If cleanup is unconfirmed, Controller cannot assume the node is clean or
available; its reservation remains to protect potentially active resources.
This qualifies Decision 293's rollback obligation without replacing node-owned
reservation authority or Decision 288's normal local-finalization boundary.

If any mandatory preparation fails or is unconfirmed, Controller coordinates
cleanup for all participants whose initialization may have started, including
previously successful participants. Preserve finalized scientific artifacts,
accepted evidence, durable recovery-journal entries, and established timing
evidence. Report unconfirmed outcomes rather than claim cleanup or release.

No leases, automatic retries, recovery daemons, crash-recovery mechanism, durable
failed-launch journal, or new Session lifecycle state is introduced.

---

## Decision 301: Mandatory services prepare Session-specific state independently of pre-Session readiness

**Status:** Accepted

Controller coordinates Session-specific preparation of all acquisition-critical
participants. Each prepares its own local runtime and reports success/failure
independently. Launch requires confirmed preparation from every mandatory
participant, separately from its pre-Session service readiness.

Controller requests Ingestor preparation of the intended Session's evidence
intake and recovery journal; Ingestor confirms preparation. Decisions 276-280's
authoritative journal durability and recovery semantics remain unchanged. Rollback
does not delete accepted evidence or durable journal entries.

Controller requests SynchronizationManager preparation of Session-specific
synchronization state; SynchronizationManager confirms preparation and retains
scientific timing and synchronization-evidence ownership. Rollback does not alter
established scientific timing evidence. Neither service requires an exclusive
AcquisitionNode-style hardware reservation. StorageManager is not a launch prerequisite.

Controller owns orchestration and rollback; Session owns lifecycle and the
initialization-completion boundary; participants own local preparation; NATS
handlers own communication/routing only. No remote Session replicas exist.
Normal end-of-Session binding lifetimes for Ingestor and SynchronizationManager
remain deferred: this clarification concerns initialization, not shutdown redesign.

Long-running service deployment/supervision, startup automation/scripts,
discovery, registration/address resolution, deployment configuration format,
duplicate participant identity policy, shared multi-Session scheduling, automatic
NATS reconnection/retry, Controller crash/stale-reservation recovery, leases/
timeouts, durable failed-launch auditing, global collection scheduling, and local
artifact deletion remain deferred. Q019 and Q024 stay open; Q022 retains deployment
configuration. Decisions 295-301 resolve the distributed-initialization handoff
blocker and are now implemented with automated broker-double tests; M015 remains
pending independent manual validation and audit.

---

## Decision 302: Successful DeviceAdapter cleanup returns retained adapters to DECLARED for sequential Sessions

**Status:** Accepted

This clarifies the generic DeviceAdapter lifecycle of Decision 048 and the
sequential node participation and cleanup guarantees of Decisions 287-288 and
297-300. It applies to all supported device types, not only OpenCV cameras.

Successful DeviceAdapter shutdown and required cleanup return the adapter to
DECLARED. initialize(config) continues to require DECLARED. Using the existing
lifecycle state names, the normal acquisition path is:

```text
DECLARED
    -> initialize(config)
INITIALIZED
    -> check_ready()
READY
    -> start()
RUNNING
    -> stop()
STOPPED
    -> shutdown() and successful required cleanup
DECLARED
    -> initialize(config) for a subsequent Session
INITIALIZED
```

This diagram does not introduce ACQUIRING or another lifecycle state. It does
not remove cleanup of partially initialized or failed adapters. No reset(),
reinitialize(), prepare_for_next_session(), or other lifecycle operation is added.

A DeviceAdapter instance remains retained by its AcquisitionNode across
sequential Sessions. Neither the adapter instance nor the AcquisitionNode
process needs to be recreated between Sessions. Device deployment/initialization,
Session-specific preparation, runtime start/stop, cleanup, and reservation release
remain distinct responsibilities.

Return to DECLARED is permitted only after successful shutdown and completion
of required cleanup. If cleanup fails or remains unconfirmed, the adapter must
not transition to DECLARED, be reported as safely reusable, or permit subsequent
initialization. A closed handle or a returned shutdown method alone does not
confirm all required cleanup. Existing FAILED handling, unfinished-resource
cleanup, and node reservation protection remain effective; a new Session must
not acquire through an unreleased capture. Local Session cleanup must be
confirmed before reservation release under Decision 300.

Ownership remains:

- DeviceAdapter owns its lifecycle state, device-specific initialization and
  cleanup, and return to DECLARED, retaining its deployment declaration.
- DeviceManager coordinates the generic adapter lifecycle without device-specific
  reset workarounds or adapter recreation.
- AcquisitionNode retains inventory, adapter instances, and deployment-level
  configuration; it coordinates local Session cleanup and subsequent initialization.
- Controller evaluates readiness and orchestrates launch, completion, and
  reservation release. It does not directly reset adapters or initialize hardware.

Returning to DECLARED does not erase the deployment declaration or remove the
device from inventory. Each subsequent Session receives its own Session-specific
configuration through the existing resolved SessionConfig mechanism. Session B
must not silently inherit Session A's Session-specific settings. Configuration
ownership remains unchanged.

Controller checks readiness before Session initialization. A successfully
cleaned DECLARED adapter must therefore be eligible for existing pre-Session
readiness evaluation, distinguished from failed or unconfirmed cleanup. Eligibility
does not mean that the device is already initialized or acquiring. No new readiness
enum or device-preparation operation is introduced. Technical readiness remains
separate from reservation and availability.

**Implementation status:** Implemented with simulated adapter, camera, and
broker-double regression tests covering consecutive Sessions on retained node and
adapter instances, confirmed abort, failed cleanup protection, independent Session
configuration, and preservation of prior artifacts and evidence. Independent
manual validation and audit of this correction remain pending; M015 remains open.
This does not introduce concurrent
Session sharing, scheduling, automatic recovery/retry, new startup authority, or
changes to scientific timing, storage, synchronization, or communication contracts.

**Principle**

Successful cleanup returns a retained adapter to DECLARED; unconfirmed cleanup
never authorizes reuse. Repeating initialization uses the existing lifecycle and
the next Session's own configuration.

---

## Decision 303: Later global processing failures do not retroactively change Session lifecycle

**Status:** Accepted

This resolves Q017 while preserving Decisions 032, 034, 041, and 271-275.

Post-session global artifact collection, verification, transfer, or later export
failures must not retroactively change Session lifecycle. A Session that reached
`completed` under its accepted lifecycle remains `completed`, even if subsequent
global processing operations fail.

These failures are operational outcomes, not Session acquisition lifecycle
outcomes. Scientific acquisition outcome, Experiment lifecycle, local artifact
finalization, global retrieval, verification, and export remain distinct; their
domain-specific result vocabularies are not replaced by a common status model.

The Session lifecycle remains:

```text
created
initialized
running
stopping
completed
failed
aborted
```

This rule does not eliminate failure handling during Session initialization,
acquisition, stopping, or required cleanup before terminal completion. Decisions
228-229 still require successful final persistence before successful completion;
this decision neither changes that order nor defines a terminal-record schema.

Session retains lifecycle ownership. Controller retains orchestration ownership;
StorageManager retains collection, verification, persistence, and its own
operational-evidence responsibilities. No new processing status model, lifecycle
state, notification mechanism, or evidence subsystem is introduced.

Q019's Session-wide evidence consumption and final Evidence Archive closure
coordination remain unresolved. Q020, Q021, Q023, and Q024 retain their separate
future architecture scope. This decision does not settle retention/deletion,
recovery, transfer scheduling, reconstruction, or export implementation.

**Principle**

A completed Session remains completed. Later global processing failures are
reported as operational outcomes, not retroactive acquisition lifecycle failures.

---

## Decision 304: Principal operational services have Session-independent and GUI-independent lifetimes

**Status:** Accepted

The framework's principal operational services - Controller, AcquisitionNode,
Ingestor, StorageManager, and SynchronizationManager - have lifetimes independent
of individual Sessions and the GUI. Their internal components may be retained
and reused according to their existing ownership and lifecycle contracts.

Starting or ending a Session does not inherently create or terminate these
services. They may participate in successive Sessions without service recreation
and may be idle or inactive between acquisition runs. Long-lived does not mean
continuously acquiring or consuming hardware resources, and does not require one
operating-system process per service.

Session remains a bounded runtime entity with its own identity, configuration,
lifecycle, and scientific records. Session-specific runtime objects may be
created, finalized, and released under their existing contracts. DeviceManager
remains owned by AcquisitionNode; DeviceAdapters remain managed runtime objects,
not independently operating services merely because they may be retained.

GUI is a client, not an operational service. It may connect, disconnect, or
restart independently; Controller remains operational independently of GUI
lifetime. Ending a Session does not automatically terminate its participating
operational services.

This foundational lifetime decision preserves bounded-memory requirements,
resource ownership, participant initialization, and DeviceAdapter cleanup/reuse
under Decisions 300 and 302. It does not settle Session-binding release details,
service supervision, or concurrent scheduling, and does not claim that every
current collaborator already supports service reuse.

**Principle**

Operational service lifetime is independent of Session and GUI lifetime;
Session-specific resources retain their existing lifecycle contracts.

---

## Decision 305: Framework stop is scoped Controller-coordinated closeout, not Session stop

**Status:** Accepted

Session stop belongs to the bounded Session lifecycle and its scientific
acquisition/cleanup behavior. Framework `stop` is an operator-requested orderly
closeout of a specified operational scope for maintenance, restart, or downtime.
Ending a Session normally does not automatically trigger framework stop.

Controller coordinates framework stop using existing distributed command and
result mechanisms. GUI may eventually request it, but does not own execution.
Each participating service or component retains ownership of its cleanup,
resource release, and operational behavior; Controller coordinates and evaluates
results rather than taking over component internals.

Framework stop respects the requested scope and protects shared services and
resources serving unrelated scopes. It does not automatically shut down every
running service or expand the operation to the entire framework. NATS remains
external infrastructure under Decision 295.

Framework stop must not initiate post-session artifact collection, verification,
transfer, or export workflows. These retain their existing architectural
contracts. No framework-wide lifecycle state machine or additional Session
lifecycle state is introduced.

---

## Decision 306: Each framework stop request has a durable stop-attempt identity

**Status:** Accepted

Each framework stop request creates a uniquely identified attempt with a durable
`stop_attempt_id`. The attempt preserves its requested scope, operator/requester
identity, relevant timestamps, actions, blocking conditions, and outcome.

Subsequent retries create new attempts with new identities; this does not
introduce an automatic retry mechanism. Stop attempts are distinct from Session
identity and Session lifecycle.

The accepted attempt outcomes are exactly:

```text
completed
blocked
failed
```

These describe framework stop attempts, not Session states or individual
distributed command results. No additional outcome vocabulary, identifier format,
public model, or persisted schema is defined by this decision.

---

## Decision 307: Orderly framework stop requires confirmed closeout conditions

**Status:** Accepted

Before declaring orderly framework stop completed, Controller obtains relevant
participant status/readiness information, uses bounded waiting for responses,
identifies conditions preventing safe or orderly closeout, and confirms the
outcomes required by the stop contract.

Participants retain ownership of cleanup and operational actions. Controller
respects authorized scope and shared-service protections throughout closeout.
Missing, delayed, or unconfirmed participant responses are not evidence of
success. An orderly stop attempt cannot be reported completed while required
closeout conditions remain unresolved.

Waiting durations, response windows, concrete closeout commands, and any polling
details require subsequent low-level definition. This decision invents no timeout
constant, polling protocol, transport mechanism, or component-specific cleanup
behavior beyond existing contracts.

---

## Decision 308: Blocked framework stop is an explicit operator decision point

**Status:** Accepted

A framework stop attempt is `blocked` when unresolved conditions prevent orderly
closeout. Controller reports concise, actionable blocking conditions grouped by
the responsible participant or architectural domain and identifies the affected
scope. Missing responses are unresolved blocking conditions, not confirmed remote
failures or successful closeout.

`blocked` is not successful completion. The operator may authorize forced
closeout through framework `kill` or decline it. No separate health subsystem or
generalized framework status model is introduced.

---

## Decision 309: Framework kill is authorized forced continuation of a blocked stop attempt

**Status:** Accepted

Framework `kill` is available only after a stop attempt reaches `blocked` and
references that existing `stop_attempt_id`. It is not an independent, unrelated
shutdown request. Operator authorization is required.

Once authorized, Controller proceeds without repeating the entire stop
status/readiness check. The original blocking conditions remain recorded, along
with actual forced actions and their outcomes. Kill must not claim that
unresolved work was successfully completed or assume that forced closeout
guarantees successful cleanup or data preservation.

Participating services and components retain responsibility for their own
forced-closeout behavior. Controller coordinates through existing command/result
boundaries; kill remains restricted to authorized scope and protects shared
services and resources serving unrelated scopes. Decisions 300 and 302's
cleanup-confirmation and safe-reuse contracts are unchanged.

Kill must not initiate post-session artifact collection, verification, transfer,
or export workflows. No process-termination API, new adapter state/reset
operation, or component-specific forced-closeout mechanism is defined here.

---

## Decision 310: Declining framework kill ends the blocked attempt as failed

**Status:** Accepted

If the operator declines forced closeout after a blocked stop, the stop attempt
ends as `failed`. Its original blocking conditions remain recorded and no forced
closeout is executed. A later retry requires a new stop attempt with a new
`stop_attempt_id`.

This operational outcome does not automatically change an unrelated Session
lifecycle. Decision 303 continues to protect completed Session lifecycle from
retroactive changes due to later global processing failures.

---

## Decision 311: Framework stop and kill protect shared participants and unrelated scopes

**Status:** Accepted

Shared services must not be indiscriminately terminated by an operation affecting
only one Session or another narrower scope. They may release resources belonging
to the requested scope while remaining operational for unrelated uses.

Exclusive participants may be stopped or moved into a supported inactive/sleep
state as appropriate. This does not invent a new operational or lifecycle state.
Ordinary operator stop/kill authority must not implicitly include administrative
authority to terminate shared infrastructure.

Scope and ownership must be explicit enough to prevent accidental disruption of
unrelated Sessions or services. Stop/kill must not automatically expand from the
requested scope to the entire framework. No complete administrative shutdown,
service-supervision, or permission-management subsystem is introduced.

---

## Decision 312: Framework stop and kill preserve durable attempt evidence through existing boundaries where applicable

**Status:** Accepted

Framework stop/kill must preserve durable evidence of each attempt and its actual
outcomes, distinguishing:

- operator request and authorization;
- stop-attempt identity and requested scope;
- relevant timestamps;
- participant status and blocking conditions;
- orderly closeout actions and results;
- kill authorization, when applicable;
- forced actions and results;
- final attempt outcome.

Reuse existing runtime-evidence, distributed communication, and persistence
mechanisms where applicable. Transport publication alone proves neither durable
storage nor successful participant execution. Do not redesign Session Record,
Evidence Archive, Ingestor, or StorageManager merely to support this phase.

If existing mechanisms cannot support a required durability guarantee, report
the architectural dependency rather than inventing a new subsystem. Evidence
representation and preservation for attempts outside a Session, persistence
confirmation, and ordering of evidence preservation versus service closeout
remain low-level dependencies under Q025; no new evidence type or schema is
chosen here. Q019's Session-wide evidence consumption/final archive coordination
remains independently unresolved.

**Phase 16 implementation status (Decisions 304-312):** Session-binding release
(W035), individual-service maintenance (W036), and progressive two-phase framework
shutdown (W037) are implemented, manually software-validated, and independently
audited PASS. Independent startup/returning-service integration remains unfinished;
Phase 16 and M015 remain open. Existing Session,
Experiment, acquisition, storage, timing, reservation, initialization, and adapter
cleanup/reuse contracts remain unchanged. Q017 remains resolved by Decision 303;
Q019, Q020, Q021, Q023, Q024, and other unresolved questions stay open. No new
operational service, GUI control, supervisor, framework-wide state machine,
transport, public API, persisted schema, or automatic post-session processing is
introduced by the original documentation synchronization.

---

## Decision 313: Operational services independently release confirmed Session bindings for reuse

**Status:** Accepted

The principal operational services retain the Session-independent and
GUI-independent lifetimes accepted in Decision 304. Each service independently
releases its active Session binding when its own Session-specific cleanup and
evidence responsibilities are confirmed:

- Controller releases its active Session reference after terminal cleanup and
  required durable-record obligations.
- Ingestor releases its active Session binding after required evidence is handed
  off or durably preserved.
- SynchronizationManager releases its prepared Session binding after Session
  Time stops and required synchronization evidence obligations are satisfied.
- AcquisitionNode retains its existing cleanup and reuse behavior.

Binding release does not terminate a service, delete durable evidence, or discard
outstanding obligations. Successive Sessions must be supported without
unnecessary service recreation. Bounded-memory requirements and existing
internal component ownership remain unchanged.

This resolves the binding-release ownership and conditions left open by
Decisions 301 and 304; it does not claim implementation or M015 validation.

---

## Decision 314: General framework shutdown and individual service maintenance are distinct operations

**Status:** Accepted

**Partial supersession:** Decision 325 supersedes only the all-or-nothing global
precheck below. The historical wording is retained; all other requirements remain
authoritative.

An administrator may request orderly general framework shutdown through
Controller. Controller evaluates closeout readiness of participating services
and relevant dependencies before stopping any service. If any required condition
is unsatisfied, the entire attempt is blocked, no service is stopped, and
Controller reports blockers for administrator authorization of kill or refusal.

When all checks pass, Controller executes orderly shutdown in dependency-safe
order. If shutdown begins but cannot finish successfully, the attempt is failed;
confirmed results are preserved. No automatic rollback or restart is required.
Each service owns its cleanup; Controller coordinates the overall operation.

An administrator may independently stop or kill an individual service, including
one on another computer, without stopping the entire framework or requiring
Controller orchestration. A local administrative interface may be used. The
target service evaluates closeout conditions and reports blockers, using the
same stop-attempt identity, outcomes, authorization, evidence, and service-owned
cleanup principles. No remote OS process management is introduced.

This specifies the two maintenance scopes under Decisions 305-311. General
framework shutdown remains Controller-coordinated; individual service
maintenance is not a hidden peer-to-peer framework orchestration path. Normal
Experiment stop, Session stop, and GUI close remain separate operations. Narrow
requests do not acquire authority over unrelated shared services or infrastructure.

---

## Decision 315: Maintenance attempts use existing correlation and exact closeout outcomes

**Status:** Accepted

Use existing distributed-command/result infrastructure where applicable. Common
contracts carry target identity, stop_attempt_id, command correlation, blocking
information, and outcome without a new command mechanism.

The accepted attempt outcomes have these meanings:

- completed: requested orderly closeout completed, or authorized forced
  termination was confirmed.
- blocked: pre-stop evaluation found unresolved conditions before shutdown began.
- failed: shutdown began but did not complete, forced termination failed or
  remained unconfirmed, or the administrator declined kill.

Kill is explicitly authorized forced continuation of the same blocked attempt,
using its existing stop_attempt_id without repeating the entire status/readiness
check. Preserve original blockers and actual actions/results. Forced termination
confirmation does not assert that unresolved cleanup or data-preservation work
succeeded. Declining kill executes no forced action; a later retry has a new
attempt identity under Decisions 306 and 310.

If forced termination fails or cannot be confirmed, report failed, identify the
affected service, and inform the administrator that manual intervention is
required. The terminated service need not report its own death; the initiator
preserves the last confirmed results and available evidence.

No additional attempt states, error taxonomy, permission infrastructure,
supervisor, remote OS termination, or automatic process restart is introduced.
Decisions 300 and 302's cleanup-confirmation and safe-reuse contracts remain.

---

## Decision 316: Services own explicit directional closeout dependencies and blockers

**Status:** Accepted

Dependencies are explicit and directional, based on actual operational
requirements. Controller must not infer dependencies merely from communication
traffic or create reciprocal dependencies merely because services communicate.
Each service evaluates its own conditions; Controller additionally evaluates
relevant cross-service dependencies during general shutdown.

- AcquisitionNode: active Session participation, unfinished acquisition/storage/
  evidence obligations, or devices and reservations not safely released block
  orderly stop. An idle AcquisitionNode may stop independently.
- SynchronizationManager: active Session synchronization requirements or
  unfinished synchronization/evidence obligations block orderly stop. An idle
  AcquisitionNode does not by itself block SynchronizationManager.
- StorageManager: active transfers, unfinished writes, or outstanding persistence
  obligations block orderly stop. Completed artifacts awaiting a future manually
  requested transfer do not block shutdown.
- Ingestor: unpreserved accepted evidence or operational services configured to
  depend on it block orderly stop. An operational AcquisitionNode configured to
  send messages to Ingestor blocks its orderly shutdown even without an active
  Session. A running service without an actual Ingestor dependency is not a blocker.
- Controller: an active Session, unfinished Controller-coordinated distributed
  operations, or outstanding Controller-owned cleanup/evidence obligations block
  orderly stop. Other idle services do not automatically block Controller.

Services that have completed closeout cease to be operational blockers. Reuse
existing status, readiness, and participant mechanisms, extending them minimally;
do not introduce a dependency manager or generalized dependency graph.

---

## Decision 317: General shutdown preserves evidence in dependency-safe service order

**Status:** Accepted

**Partial supersession:** Decision 325 supersedes only the initial all-participant
readiness gate below. Dependency-safe evidence preservation and Controller's
last-confirmed readiness-for-retirement principle remain authoritative.

General shutdown begins with complete pre-stop readiness evaluation. Once all
required participants confirm readiness, Controller executes dependency-safe
shutdown in the accepted evidence-preservation order:

```text
Evidence-producing services -> Ingestor -> StorageManager -> Controller
```

SynchronizationManager completes synchronization and evidence obligations before
Ingestor closes. Controller remains operational to coordinate closeout and record
the overall result, and stops last after required final evidence is durably
preserved.

Controller cannot confirm its own termination after exiting. It records readiness
for final termination and initiates exit without requiring a new supervisor.
This does not require the terminated service to report its own death or claim
post-exit confirmation that was not obtained.

No new global evidence-drain subsystem is introduced. Q019's separate Session-wide
consumption/final Evidence Archive coordination remains unresolved.

---

## Decision 318: Existing runtime evidence and Evidence Archive support Session-independent framework evidence

**Status:** Accepted

Ingestor and Evidence Archive are general framework infrastructure even though
their current implementation is Session-specific. Session evidence retains
Session identity. Framework-level evidence, including service startup, readiness,
and stop/kill evidence, may exist without a Session identity.

Extend existing evidence contracts minimally to support this distinction; never
fabricate Session identifiers or create a separate evidence system. Reuse
RuntimeEvidenceMessage, Ingestor, StorageManager, and Evidence Archive boundaries
without transferring evidence meaning or persistence ownership.

Stop-attempt evidence preserves:

- stop_attempt_id;
- target service or framework scope;
- blocking conditions;
- administrator authorization or refusal;
- confirmed orderly and forced actions;
- final outcome;
- failures and unconfirmed termination results.

Decision 306's requester identity and relevant timestamps remain required.
This supplements the historical Session-only scope of Decisions 219-231 and
312; Session Record remains the record of a Session, not a fabricated container
for Session-independent framework evidence. No message schema, persisted format,
archive layout extension, category-specific archive, or new public API is
implemented by this documentation decision.

---

## Decision 319: Required evidence preservation precedes orderly service closeout

**Status:** Accepted

**Partial supersession:** Decision 325 supersedes only the general-shutdown global
precheck wording below. Required service-owned evidence preservation and separate
authorized-kill semantics remain authoritative.

Each service completes required evidence submission before confirming orderly
closeout. Ingestor confirms accepted evidence has been durably preserved before
closing. StorageManager remains available until Ingestor's required evidence
preservation is confirmed, then completes its own outstanding writes.

Individual service maintenance also uses Ingestor and StorageManager to preserve
required evidence before termination. If required evidence cannot be preserved,
orderly stop is blocked. During general shutdown this is subject to Decision 314's
pre-stop evaluation: no service stops while required preconditions are unsatisfied;
failure after shutdown begins is failed under Decision 315.

Authorized kill may proceed despite an evidence-preservation blocker. The
initiator preserves whatever evidence it can confirm; forced termination does
not guarantee complete evidence preservation. Transport publication alone remains
neither Ingestor acceptance nor permanent persistence confirmation.

Reuse existing evidence/persistence infrastructure; do not introduce a new archive,
transport, or persistence subsystem or silently resolve Q019.

---

## Decision 320: Service failure and forced termination do not cascade service lifetime

**Status:** Accepted

If a service stops unexpectedly or is forcibly terminated, other services remain
alive and do not automatically stop or restart. Missing dependencies are reported
through existing health/readiness mechanisms. Operations requiring the missing
service cannot proceed normally; unrelated operations may continue.

Communication can be reestablished when the service returns without restarting
the entire framework. This does not promise automatic recovery of interrupted
Sessions, transfers, or messages, introduce automatic process restart, or change
Session lifecycle. Q011, Q016, and Q024 retain their separate recovery questions.

---

## Decision 321: Operational services start independently and report current dependency readiness

**Status:** Accepted

Each operational service supports independent startup. At startup it:

1. Initializes its own components.
2. Loads existing durable configuration and records required for normal operation.
3. Connects to existing communication infrastructure.
4. Discovers available dependencies through existing mechanisms.
5. Reports actual readiness.
6. Supports operations whose dependencies are available.

A service may start successfully while some dependencies are unavailable.
Readiness reflects dependencies appearing or disappearing. Other services
recognize a restarted service without requiring framework-wide restart.
Unresolved previous operations are reported using existing mechanisms;
interrupted Sessions or transfers are not automatically resumed.

This does not introduce a discovery service, registry, recovery subsystem,
supervisor, remote OS/SSH/systemd process management, automatic rollback after
partial shutdown, or automatic process restart. Deployment configuration remains
Q022; application recovery and recovery-journal retention remain Q024. No GUI,
new Session lifecycle state, or automatic post-session collection, verification,
transfer, export, or transfer scheduling is introduced by maintenance/startup.

**Phase 16 low-level status (Decisions 313-321):** Binding release, individual-service
maintenance, and progressive coordinated shutdown are implemented and validated
in W035-W037; independent startup/returning-service integration remains unfinished.
These contracts resolve Q025's five narrowed
questions without changing the exact historical text of Decisions 304-312.
The original documentation synchronization did not add APIs, schemas, or implementation.
M015 remains open pending independent validation/audit; Q019, Q021, Q024, and
unrelated future questions remain open. Historical validation records are unchanged.

---

## Decision 322: Every ControllerActionDecision is persistent and requires confirmed archival before Controller Session-binding release

**Status:** Accepted

Every `ControllerActionDecision` is persistent, including:

- `record_only`
- `record_warning`
- `record_recoverable_failure`
- `operator_required`
- `experiment_fail`
- `session_fail`

Persistence does not depend on whether the decision produces an operational
consequence or changes lifecycle state. Controller owns each decision and sets
`is_persistent = True` in its corresponding `RuntimeEvidenceMessage`. No further
persistence-selection criteria apply.

Reuse the existing evidence pathway:

```text
Controller -> RuntimeEvidenceMessage -> Ingestor -> StorageManager -> Evidence Archive
```

Controller produces the evidence and declares its persistence. Ingestor owns
intake, validation, audit, temporary retention, and persistent-evidence
compilation. StorageManager owns durable writing. Neither Ingestor nor
StorageManager independently determines whether a Controller decision deserves
persistence. No new evidence hierarchy, subsystem, transport, or storage
mechanism is introduced.

This clarifies Controller's evidence obligations under Decision 313. Controller
may release its active Session binding only after:

1. Required Session cleanup and durable Session Record obligations are complete.
2. Every Controller-owned persistent ControllerActionDecision associated with
   that Session has confirmed durable preservation through the existing Evidence
   Archive pathway.

Successful NATS publication alone is not sufficient. Once those obligations are
confirmed, Controller may release its binding and retire the corresponding
temporary in-memory decision records. Binding release must not delete durable
evidence or discard outstanding obligations.

Decision 226 remains unchanged: Session Record describes the Session; Evidence
Archive stores persistent runtime evidence. ControllerActionDecision evidence
belongs in the Evidence Archive, not as a raw runtime-evidence dump in the Session
Record. Session Record responsibilities are not expanded to satisfy this contract.

This establishes Controller-specific preservation obligations, not a guarantee
that all Session evidence published by all participants has been consumed. It
does not introduce a Session-wide drain or acknowledgment protocol, change global
Evidence Archive finalization semantics, or resolve Q019.

**Implementation status:** The narrow Phase 16 Slice 1 follow-up implements
persistent Controller decision packaging, submission to an attached Ingestor,
and exact decision-message archival confirmation before binding release.
Caller-managed broker publication uses the existing boundary and does not itself
confirm archival. The narrow Decision 313 Session-binding release paths are
implemented and validated in W035, including evidence-bearing
Ingestor/SynchronizationManager release:
Ingestor checks exact persistent-message/runtime-audit archive coverage and existing
terminal Session Record evidence under its intake lock; SynchronizationManager
checks stopped time, retired mappings, and durable Ingestor handoff. Nonpersistent
messages retain producer-declared intent. Q019 remains unresolved architecture,
and progressive coordinated closeout is separately validated in W037. Independent
startup/returning-service integration remains unfinished; Phase 16 and M015 remain open.
Existing accepted requirements and historical validation records are preserved.

---

## Decision 323: Session-independent framework evidence uses the existing Evidence Archive infrastructure

**Status:** Accepted

The existing Evidence Archive supports two evidence scopes. Session evidence
retains its current layout and behavior:

```text
<storage_root>/session_<session_id>/evidence/
    runtime_evidence.jsonl
    ingest_audit.jsonl
    compilation_summary.json
```

Session-independent framework evidence uses the accepted persistent partition:

```text
<storage_root>/framework/evidence/
    runtime_evidence.jsonl
    ingest_audit.jsonl
    compilation_summary.json
```

The framework partition uses a stable deployment-configured StorageManager
location and does not depend on an active Session. Framework
RuntimeEvidenceMessage records use session_id=None, serialized as JSON null.
Extend existing validation and participant-independent evidence routing as
necessary. Reuse Ingestor acceptance, deduplication, recovery journaling,
producer-owned is_persistent, intake audit, and compilation. Reuse StorageManager
archive products, storage locking, and preservation-confirmation principles.
Do not require a Session Record or create a Session binding. Session-scoped
evidence behavior remains unchanged.

StorageManager supports durable confirmation of the exact framework compilation,
including persistent evidence, required intake audit, and compilation summary.
An older snapshot cannot authorize preservation of subsequently accepted evidence
or audit records. Failed or incomplete writes cannot establish confirmation for
the newer snapshot. No new evidence subsystem, revision mechanism, receipt file,
or commit protocol is introduced.

---

## Decision 324: Individual-service maintenance preserves confirmed cleanup evidence before retiring evidence capabilities

**Status:** Accepted

This clarifies individual-service maintenance closeout ordering under Decisions
312, 315, 317, 319, and 323 without changing their existing meaning or ownership:

1. Ordinary service resource cleanup and final operational retirement are
   distinct when retirement would disable required evidence capabilities.
2. Before orderly cleanup, preserve the initial maintenance checkpoint.
3. During ordinary resource cleanup, retain the Ingestor acceptance, journaling,
   and StorageManager archival capabilities necessary to preserve confirmed
   cleanup results.
4. After ordinary cleanup, durably preserve actual confirmed actions, failures,
   and remaining obligations, not merely the intention to close.
5. Before irreversible retirement of evidence capabilities, durably preserve the
   last-confirmed readiness-for-retirement checkpoint.
6. Final operational retirement occurs only after required preservation is
   confirmed. Transport publication acknowledgment alone is not sufficient.
7. Confirmed retirement is distinct from readiness for retirement and from OS
   process death. A readiness checkpoint does not claim that retirement has
   already occurred.
8. The initiating interface determines the final outcome from actual
   confirmation. `completed` requires confirmed operational retirement;
   otherwise report `failed` once cleanup has begun.
9. Ingestor and StorageManager are not required to preserve post-retirement
   events through their own unavailable infrastructure. The initiating interface
   retains the confirmed result and communicates it through the existing
   command/result path where possible.
10. Missing command-result delivery cannot be interpreted as successful
    retirement.
11. Preservation failure before cleanup begins blocks orderly stop. Failures
    after cleanup begins produce `failed` outcomes.
12. A minimal two-phase closeout callback contract or optional final-retirement
    callback is permitted. No new supervisor, evidence subsystem, shutdown
    coordinator, or lifecycle state is introduced.

Decision 315's meanings of `blocked`, `failed`, and `completed` remain unchanged.
Authorized kill remains separate: it may proceed despite evidence-preservation
blockers, retains original blockers and actual confirmed results, and does not
assert complete cleanup or evidence preservation. This clarification neither
expands individual maintenance into general framework shutdown nor resolves
Q019 or Q024. Existing RuntimeEvidenceMessage, Ingestor, StorageManager, Evidence
Archive, and command/result ownership remain unchanged.

**Implementation status:** Individual-service closeout ordering and the four
original audit corrections are implemented and validated. The subsequent
premature-completion finding in authorized kill is corrected, manually validated,
and independently re-audited PASS. W036 records completion of this narrow software
implementation slice, including Decision 324's preservation and retirement
ordering. Phase 16 and M015 remain open; historical validation records are preserved.

---

## Decision 325: General framework shutdown is progressive, not atomic

**Status:** Accepted

This supersedes only Decision 314's all-or-nothing global precheck and the
corresponding initial-gate wording in Decisions 317 and 319. All other accepted
requirements remain authoritative; their historical wording and numbering are
preserved.

Controller performs an initial independent local stop-readiness survey, followed
by sequential dependency-safe shutdown. The survey is informational: not every
participating service must be immediately stoppable before the sequence begins.
Each service evaluates its actual blockers when Controller issues its stop
command. Services already stopped remain stopped if a later service blocks or
fails; there is no automatic restart or rollback.

### Explicit framework shutdown scope

Controller receives an explicit collection of `RuntimeParticipant` identities
identifying the operational services included in the requested shutdown:
participating AcquisitionNodes, SynchronizationManager, Ingestor, StorageManager,
and Controller. This scope is independent of current or previous Sessions and
must not be derived from `SessionConfig.expected_runtime_participants`.

Reuse existing participant identity and scope-validation contracts; do not
introduce a service-discovery registry. Existing protections for shared resources
and unrelated scopes remain authoritative.

### Initial local stop-readiness survey

A minimal, read-only `check_stop_readiness` operation uses existing participant
command/result infrastructure. It:

- Reuses service-owned `maintenance_blockers()` information and applicable local
  closeout checks.
- Reports local blockers and unconfirmed readiness.
- Does not create or activate a stop attempt, initiate cleanup or shutdown, or
  prevent future work merely because the survey occurred.
- Does not treat dependencies expected to disappear later in the shutdown
  sequence as an automatic global starting blocker.

Controller collects responses through existing bounded command-response
mechanisms. Missing responses are unconfirmed, never successful. This survey is
informational, not an all-or-nothing gate.

### Progressive shutdown order

Controller issues actual stop commands sequentially in dependency-safe order:

1. AcquisitionNodes and other evidence-producing operational services.
2. SynchronizationManager.
3. Ingestor.
4. StorageManager.
5. Controller last.

SynchronizationManager must retire before Ingestor. Each service evaluates its
current blockers when its stop command is issued. Controller confirms each
required service's operational retirement before proceeding as though its
dependency has disappeared. Reuse the individual-service `stop`, `kill`, and
`cancel` contracts validated in W036.

### Blocked services and administrator authorization

If a service reports `blocked`, Controller pauses the sequence and reports that
service's actual blockers. The administrator may explicitly authorize kill for
that specific service or decline forced termination. Authorization for one
blocked service does not authorize termination of another.

If forced termination is confirmed, Controller continues with orderly stop
attempts for remaining services. Each subsequent blocked service requires a new,
service-specific authorization. Unconfirmed forced termination is not successful
retirement. If the administrator declines forced termination after shutdown has
begun, the overall attempt ends `failed`; previously stopped services remain
stopped.

Preserve the accepted meanings of `completed`, `blocked`, and `failed`, and
distinguish participant-level outcomes from the overall framework-attempt outcome.
No new lifecycle states are introduced.

### Attempt tracking and evidence

Preserve one overall framework shutdown attempt identity and correlate participant
commands and results with it. Reuse `stop_attempt_id`, `RuntimeParticipant`,
existing command/result correlation, `RuntimeEvidenceMessage`, Ingestor,
StorageManager, and the existing framework Evidence Archive. Framework-level
evidence uses `session_id=None`, serialized as JSON `null`.

Preserve actual initial survey results, participant outcomes, original blockers,
authorization decisions, forced actions, failures, and confirmed overall results.
Apply existing durable preservation requirements, including Decisions 319, 323,
and 324. Controller prepares and durably preserves its final required coordination
evidence while Ingestor and StorageManager remain available, then retires last
under Decision 317's last-confirmed readiness-for-retirement principle.

Do not claim post-exit confirmation or require retired evidence services to
persist events through unavailable infrastructure.

### Boundaries and implementation status

This decision does not authorize GUI implementation, independent startup or
returning-service integration, OS process supervisors or remote process termination,
automatic retry/rollback/restart, new dependency-management or evidence subsystems,
new Session lifecycle states, Q019/Q024 implementation, or reimplementation of
W035/W036. The GUI shutdown design notes remain proposed future interface ideas,
not approved implementation contracts.

**Implementation status:** Progressive Controller-coordinated general shutdown
is implemented, independently manually software-validated, and independently
re-audited PASS under Decisions 325-326 (W037). The Evidence Archive preservation
correction passed regressions and independent validation. Phase 16 and M015 remain
open for their separate remaining criteria; Q019 and Q024 remain unresolved.
Historical validated workflows are preserved.

---

## Decision 326: Two-phase coordinated closeout preserves cleanup evidence before infrastructure retirement

**Status:** Accepted

This supplements Decisions 319, 324, and 325 by specifying how actual cleanup
evidence remains durable during progressive infrastructure shutdown. It does not
reverse Decision 325 or weaken W036's independently validated individual-service
maintenance contract.

### Preparatory cleanup

During Controller-coordinated general framework shutdown, StorageManager and
Controller may perform ordinary resource cleanup before Ingestor retires. A
minimal `prepare_stop` operation uses existing distributed command/result and
W036 maintenance infrastructure. It:

- Performs actual ordinary cleanup and confirms and durably preserves its results.
- Does not retire the service and retains capabilities needed to complete
  coordinated shutdown.
- Is correlated with the participant's maintenance attempt and the overall
  framework `stop_attempt_id`, using a distinct command identity.

Preparation is not a new lifecycle state or completed operational retirement.
Existing W036 individual-service `stop`, `kill`, and `cancel` behavior remains
unchanged outside coordinated shutdown.

### Required shutdown sequence

1. Stop AcquisitionNodes and SynchronizationManager using existing W036
   maintenance, preserving actual results.
2. While Ingestor and StorageManager remain operational, execute StorageManager
   `prepare_stop`, followed by Controller `prepare_stop`.
3. Durably archive actual preparatory cleanup results and coordination evidence.
4. Confirm the final evidence-preservation checkpoint before Ingestor retirement.
5. Retire Ingestor using its existing maintenance closeout, preserving its actual
   cleanup evidence while StorageManager remains available.
6. Retire the previously prepared StorageManager without invoking retired
   Ingestor evidence operations.
7. Retire Controller last, after its remaining coordination obligations and
   last-confirmed readiness checkpoint.

The operational retirement order remains:

```text
AcquisitionNodes -> SynchronizationManager -> Ingestor -> StorageManager -> Controller
```

Preparation does not change this order.

### Evidence guarantees

Before Ingestor retirement, durably preserve all archive-eligible evidence
generated so far, including actual cleanup, preparation, authorizations, failures,
and coordination evidence. The final archival checkpoint distinguishes completed
actions from outstanding obligations and future retirement actions. Anticipated
retirement must not be recorded as completed.

After Ingestor retirement, StorageManager's final retirement confirmation is
retained by Controller through existing command/result contracts. Controller's
final available retirement confirmation is retained by the initiating interface.
These later results are not newly archived Evidence Archive records; the overall
shutdown result is derived only from actual confirmed outcomes.

Framework evidence continues to use `session_id=None`. No new evidence subsystem,
receipt file, archive, or post-retirement persistence mechanism is introduced.

### Failure handling

- Failure to durably preserve required cleanup evidence prevents orderly
  progression across the final archival boundary.
- Preserve actual failed cleanup results and outstanding obligations.
- Successful `prepare_stop` is never sufficient to claim completed operational
  retirement; missing or failed final retirement confirmation is not success.
- Forced termination still requires separate administrator authorization for
  each affected service.
- Previously stopped services remain stopped after later failures; no automatic
  rollback, restart, or retry is introduced.

**Implementation status:** This two-phase coordinated-closeout contract is
implemented, independently manually software-validated, and independently
re-audited PASS (W037). Prepared orderly retirement requires current complete
Evidence Archive coverage of Ingestor's retained final persistent-evidence and
all-intake-audit compilation, checked before and after asynchronous callbacks and
held stable through retirement commitment. Missing coverage prevents confirmed
retirement and completed shutdown. W037 records 174 focused tests passed and
574 full-suite tests run, 567 passed, 7 optional rendering skips, zero failures.
Historical decisions and validation records are preserved. Independent
startup/returning-service integration remains unfinished; Phase 16 and M015 remain
open, and Q019/Q024 remain unresolved.

---

## Decision 327: Starting and returning services announce existing identity and readiness

**Status:** Accepted

Each operational service announces its identity and current readiness through
existing NATS mechanisms when starting or returning after shutdown or interruption.
Use the same announcement format for initial startup and return, reusing
`RuntimeParticipant` identity and `ServiceReadiness` contracts. Include known
unresolved obligations where applicable; do not introduce another identity or
generalized service-description model.

Receiving services do not automatically issue redundant readiness requests in
response to announcements. Current readiness may be checked when operationally
necessary. Required NATS connectivity remains governed by Decision 295.

**Accepted clarification - announcement freshness:** Historical readiness
announcements must never establish current operational readiness. Use existing
NATS/JetStream delivery controls so dependency-readiness subscribers receive only
newly published announcements. Preserve Ingestor's existing durable evidence
consumption, including historical evidence required for preservation and recovery.
A fresh announcement does not require an immediate redundant readiness check;
a service that missed an announcement may use the existing `check_readiness`
command when operationally necessary. No new message schemas, expiry timestamps,
polling, discovery mechanisms, or additional infrastructure are introduced.

---

## Decision 328: Configured dependencies directly update service-owned readiness

**Status:** Accepted

Already-running services receive announcements directly from their configured
dependencies and update their own dependency readiness. Controller does not relay
announcements or maintain a discovery registry.

Reuse `ServiceReadiness`, `AcquisitionNodeReadiness`, and existing interpretations
of missing current evidence as `unknown` under Decision 284. Do not introduce new
service status enums or lifecycle states. Keep technical readiness, reservation,
communication availability, and unresolved obligations distinct.

This makes Decision 321's dependency-readiness behavior explicit without changing
service ownership or settling deployment configuration and discovery details in Q022.

**Accepted clarification - dependency disappearance:** When an existing
communication operation or readiness check cannot confirm a dependency's current
availability, previously confirmed operational availability must no longer be
treated as current. Reuse Decision 284's `unknown` interpretation; do not report
`ready=False` without actual evidence of technical unreadiness. Preserve last-known
readiness as historical information, distinct from currently confirmed readiness.
Disappearance may remain undetected until a communication operation or an
operationally necessary check occurs; no proactive detection guarantee is required.
No automatic Session/Experiment failure, recovery, restart, or replay follows.
This introduces no heartbeats, polling, expiry policies, lifecycle states,
discovery registries, or additional persistence mechanisms.

---

## Decision 329: Returned services use existing readiness and ownership protections

**Status:** Accepted

A returned service with normal readiness and no conflicting unresolved obligations
is usable under existing contracts. Outstanding obligations restrict only the
operations or resources they affect, subject to existing readiness, cleanup, and
ownership protections.

No special re-admission procedure or automatic recovery is introduced. Service
return does not establish that interrupted work has resumed or unresolved cleanup
has succeeded. Decisions 300, 302, 313, 320, and 321 remain authoritative.

---

## Decision 330: Administrator resume/drop decisions are evidence, not recovery execution

**Status:** Accepted

Record explicit administrator resume/drop decisions concerning unresolved previous
work through existing framework evidence mechanisms. Recording a decision does
not establish that recovery, deletion, cleanup, or other execution has occurred.

Resume/drop execution mechanics remain deferred to Q024. This decision does not
define those mechanics, resolve application recovery, or authorize automatic
resumption or deletion. It preserves the distinction between an administrator's
decision and evidence of an actual result.

---

## Decision 331: Startup and return evidence reuse existing preservation boundaries

**Status:** Accepted

Produce framework evidence for startup/return, meaningful readiness changes,
unresolved-work reports, administrator decisions, and actual results when available.
Avoid redundant unchanged-readiness evidence.

Reuse `RuntimeEvidenceMessage`, producer-owned persistence intent, Ingestor,
StorageManager, and the existing framework Evidence Archive with `session_id=None`
under Decisions 219-225, 318, and 323. NATS publication alone does not establish
durable archival. Keep NATS publication, Ingestor acceptance, and StorageManager
archival confirmation distinct.

A service may start without Ingestor or StorageManager when its other accepted
prerequisites are satisfied. The operator must receive a warning when durable
Evidence Archive preservation cannot be confirmed. Preserve existing producer
evidence obligations; do not introduce a second persistence system, automatic
replay, or automatic recovery. Required NATS connectivity remains governed by
Decision 295.

Existing status, readiness, command results, and evidence may support a future
Services tab. No GUI-owned authority, new status model, or GUI implementation is
authorized. The permanent Services-tab concept in `docs/gui_design_notes.md` remains
a separate future proposal, not accepted implementation architecture.

Q019 retains Session-wide evidence-consumption/finalization coordination; Q024
retains recovery journals and resume/drop execution; Q022 retains deployment
configuration and discovery details. Process supervision, automatic service
launching/restarting, GUI development, new Session states, and automatic retry/replay
remain outside this work.

**Implementation status for Decisions 327-331:** Accepted startup/return low-level
architecture is synchronized and implemented. This narrow integration slice has
completed automated testing, independent manual IPython validation, and independent
re-audit PASS after correction of the two initial P2 findings, as documented in W038.
W035-W037 and Decisions 325-326 retain their completed narrow-slice status.
Q019 is CLOSED in W050; Phase 16, M015, Q022, and Q024 remain open.

---

## Decision 332: Services report unresolved previous work through existing interfaces

**Status:** Accepted

Each service reports unresolved previous work using its existing records and
accepted responsibilities. Reuse `ServiceReadiness`, service-owned diagnostics,
`check_readiness`, `ServiceMaintenanceInterface`, and framework evidence.

No universal unresolved-work model, recovery registry, new recovery-report command,
or reporting subsystem is introduced. Existing interfaces remain the reporting
boundary; this decision does not invent a shared diagnostic schema.

---

## Decision 333: Unresolved-work classification separates outcome, recovery possibility, and operational impact

**Status:** Accepted

Within existing service-owned diagnostics and evidence, distinguish independently:

- Obligation outcome: proven completed, unresolved, or explicitly abandoned.
- Recovery possibility: potentially recoverable using supported service-owned
  mechanisms, or requiring administrator intervention.
- Operational impact: restrictions on affected scopes versus broader service
  restrictions.

Recoverable does not mean recovered. Abandoned does not mean completed. These
dimensions do not introduce global recovery states or enums, change Session
lifecycle, or redefine existing maintenance-attempt outcomes.

---

## Decision 334: Unresolved-work protection uses existing affected-scope identities

**Status:** Accepted

Reuse existing identities and service-owned references, including
`RuntimeParticipant`, Session, Experiment, device, artifact, evidence, command,
transfer, synchronization mapping, and stop attempt as appropriate. No universal
recovery ID or scope model is introduced.

A service may restrict only the affected scope when it can establish that the
restriction is sufficient. If it cannot prove an unsafe condition is limited to
a specific scope, it must not assume other potentially affected resources are safe.

Existing reservation, cleanup, binding-release, and service-readiness protections
remain authoritative, including Decisions 300-302, 313, and 329. Reporting or
classifying an obligation does not bypass those protections.

---

## Decision 335: Administrative drop abandons an obligation without proving recovery or safety

**Status:** Accepted

Reuse `ServiceMaintenanceInterface.record_administrator_decision(...)` and the
existing framework evidence pathway. Record the administrator, affected service
and obligation, explicit decision, and available justification using existing
service-owned information.

An explicit administrative drop closes the obligation administratively as
abandoned/not recovered. It does not prove the original work succeeded, cleanup
completed, resources became safe, or recovery occurred.

Preserve the distinction between administrative decision, actual action, confirmed
outcome, and archival confirmation. This supplements Decision 330's evidence-only
decision contract with the narrow administrative-abandonment boundary; it does not
authorize recovery execution, data deletion, or release of unsafe resources.

---

## Decision 336: Safe administrative abandonment permits bounded-memory cleanup without durable deletion

**Status:** Accepted

After administrative abandonment has been recorded and applicable
evidence-preservation, resource-safety, and closeout obligations are satisfied,
release temporary in-memory information no longer necessary for correctness.

Retain the minimum information still required to protect unsafe resources or
unresolved safety obligations. Administrative abandonment alone does not establish
the conditions for cleanup or authorize discarding outstanding safety obligations
under Decision 313.

Do not automatically delete durable evidence, scientific records, or recovery
journals. Their retention/deletion policies remain separately governed or deferred,
including the journal lifecycle left open by Decision 280 and Q024.

---

## Decision 337: Unresolved-work assessment retains service-specific ownership and confirmation

**Status:** Accepted

Existing service-specific responsibilities remain unchanged:

- StorageManager: durable writes, archives, transfers, confirmations, and storage
  consistency.
- Ingestor: evidence intake, validation, audit, retention, accepted recovery
  journals, and compilation.
- AcquisitionNode: acquisition participation, devices, resource cleanup, local
  artifacts, manifests, and completion evidence.
- Controller: commands, coordination, participant outcomes, Session/Experiment
  orchestration, and administrative attempts.
- SynchronizationManager: timing evidence, mappings, stopped-time obligations,
  and synchronization closeout.

Services establish completion only from trustworthy existing records and confirmed
state, not intent, transport acknowledgment, missing responses, or incomplete
evidence. No additional owner, recovery subsystem, or reporting mechanism is created.

---

## Decision 338: Unresolved-work and abandonment evidence reuse existing preservation boundaries

**Status:** Accepted

Reuse `RuntimeEvidenceMessage`, Ingestor, StorageManager, and the existing framework
Evidence Archive. Preserve evidence of unresolved-work reports, recovery
assessments, classifications, administrator decisions, and actual confirmed outcomes.

Keep producer persistence intent, publication, Ingestor acceptance, and
StorageManager archival confirmation distinct under Decisions 219-225, 323, and
331. Avoid redundant unchanged evidence. No additional persistence mechanism is
introduced.

Detailed service-specific recovery procedures, execution of resume/drop beyond
the accepted administrative reporting and safe-closeout boundary, journal
retention/deletion, and broader application recovery remain open Q024 work.
This slice does not authorize universal or automatic recovery, replay, retry,
resumption, deletion, GUI implementation, process supervision, or new Session states.
Q019 retains Session-wide evidence consumption/finalization; Q022 retains deployment
configuration and discovery.

**Implementation status for Decisions 332-338:** Accepted low-level Q024 contracts
have a completed narrow implementation slice with automated coverage: owner-specific
diagnostics through existing readiness, explicit abandonment evidence, and guarded
release of redundant producer-owned evidence copies. Independent manual IPython
validation PASSED (10 scenarios), and the independent read-only source audit PASSED
with no blocking findings, as reported for this documentation closure; no new
validation was executed during closure. Decision 336 remains partially implemented,
limited to that guarded release of redundant copies. Broader application recovery,
journal lifecycle, resume/drop execution, resource-specific cleanup, and wider cache
retirement remain OPEN and unimplemented where their contracts are not established.
W038 and prior validated workflows retain their completed narrow-slice status.
Q019 is CLOSED in W050; Phase 16, M015, Q022, and Q024 remain open.

---

## Decision 339: Service-specific recovery attempts require explicit obligation-scoped administrator authorization

**Status:** Accepted

Q024-B recovery remains service-specific. There is no universal `recover()`,
`resume()`, or `retry()` operation, recovery manager, or registry.

New recovery operations require explicit human administrator authorization for a
specific obligation. Reuse `ServiceMaintenanceInterface.record_administrator_decision(...)`
to record the decision and existing command/result infrastructure for authorized
execution. Recording authorization remains distinct from executing recovery under
Decision 330.

Immediately before execution, the owning service validates authorization,
obligation identity, affected scope, current prerequisites, and safety.
Authorization permits an attempt, not guaranteed success or unrelated work.
Service return never automatically initiates a new recovery operation.

---

## Decision 340: Recovery assessment and operator choices remain service-owned and distinct

**Status:** Accepted

Each service assesses its unresolved obligations using trustworthy existing
records and diagnostics. Distinguish obligations with no established recovery
action, obligations with a concrete potentially safe recovery procedure, and
obligations already proven complete.

The operator may authorize recovery, leave work unresolved, or explicitly abandon
it. These choices are distinct: leaving work unresolved is not abandonment.
Assessment and authorization do not prove that recovery occurred.

---

## Decision 341: Recovery execution correlates existing identities and preserves actual outcomes

**Status:** Accepted

Reuse `RuntimeParticipant`, the original service-owned obligation identity,
administrator-decision `evidence_id`, execution `command_id`, and existing
command/result and runtime-evidence identities. Execution requests reference
both the original obligation and the specific authorization.

Distinguish unresolved-work report, administrator decision, attempted action,
actual outcome, and durable archival confirmation. Reuse `RuntimeEvidenceMessage`,
Ingestor, StorageManager, and the existing Evidence Archive. Preserve successful,
failed, and refused attempts, including relevant precondition failures and
remaining obligations.

Command acknowledgment does not prove successful recovery. Failed recovery does
not imply abandonment. No new evidence infrastructure is introduced.

---

## Decision 342: StorageManager owns authorized fresh-transfer and persistent-write recovery attempts

**Status:** Accepted

Two operator-authorized StorageManager recovery cases are accepted:

1. **Interrupted artifact transfer:** Perform a fresh complete transfer using
   trustworthy original source, authoritative manifest, retrieval configuration,
   and existing transfer mechanisms. Do not alter the original local artifact.
   Replace an incomplete temporary copy only when its identity and relationship
   to the interrupted operation are proven. Never overwrite an unexpected final
   destination. Preserve existing retrieval verification requirements. Refuse
   when source, identity, configuration, or destination safety is uncertain.
   No byte-level transfer resumption is introduced.
2. **Interrupted persistent-record write:** Repeat an Evidence Archive or Session
   Record write only when complete trustworthy inputs remain available. Reuse
   existing persistence and consistency mechanisms. Ingestor retains compilation
   ownership; StorageManager must not invent missing evidence. Confirm the actual
   durable result. Refuse missing, inconsistent, or untrustworthy inputs.

These explicit authorized attempts extend the earlier slice scope without adding
automatic retry/replay or changing Decisions 245-270's source ownership,
non-overwriting final publication, and verification boundaries. This does not
resolve Q019's Session-wide evidence-completeness or finalization questions.

---

## Decision 343: Ingestor retains accepted automatic known-Session journal reconstruction

**Status:** Accepted

Q024-B introduces no new Ingestor recovery mechanism. Preserve Decisions 276-280:
automatic reconstruction of accepted runtime evidence from a valid durable
recovery journal for an already-known Session, with evidence-ID deduplication
and normal intake/compilation afterward.

Report reconstruction failures without inventing missing evidence or silently
accepting corrupted completed entries. This existing automatic reconstruction
does not require new administrator authorization. Application-wide unfinished-
Session discovery remains deferred; the exclusion of new automatic recovery
does not remove this already accepted reconstruction.

---

## Decision 344: AcquisitionNode artifact preservation and resource cleanup are independent authorized actions

**Status:** Accepted

Two independent operator-authorized AcquisitionNode recovery actions are accepted:

1. **Scientific-artifact preservation:** Preserve genuinely available partial
   scientific records, complete supported local artifact finalization, and update
   authoritative manifests and evidence using existing LocalStorageManager
   mechanisms. Do not fabricate records, reopen terminal Experiments, or resume
   acquisition under old Experiment identities.
2. **Device/resource cleanup:** Attempt unfinished cleanup with actual shutdown
   and cleanup confirmation. Preserve adapter lifecycle, reservation, Session-
   binding, and resource-safety protections. Unconfirmed resources cannot be
   considered reusable.

Success in one action does not establish success in the other. LocalStorageManager
retains authoritative artifact/manifest ownership, and existing lifecycle and
cleanup protections, including Decisions 238, 300-302, and 313, remain in force.

---

## Decision 345: Controller reconciliation records proven outcomes without automatic operational replay

**Status:** Accepted

Controller may reconcile trustworthy existing durable evidence and confirmed
participant outcomes without authorization merely to read those records.
Record only proven outcomes, keep missing or uncertain results unresolved, and
preserve partial results.

Do not infer success from transport acknowledgment, intent, missing response,
or partial confirmation. Do not automatically replay commands, restart terminal
Experiments, advance Session lifecycle, or restore the application.

Any new operational command required for recovery is separately authorized and
subject to existing safety and scope contracts. Reconciliation does not confer
device, persistence, or timing ownership on Controller.

---

## Decision 346: Synchronization recovery preserves historical timing and requires trustworthy current information

**Status:** Accepted

Outside an active Session, normal operation may resume after valid synchronization
is established through existing mechanisms. During an active Session, preserve
historical timing evidence and mappings, identify gaps in timing continuity, and
report affected scope and uncertainty.

Do not extend old mappings across downtime, fabricate synchronization observations,
or overwrite recorded timestamps. New active synchronization must rely on
trustworthy current information and existing SynchronizationManager authority.

A synchronization service crash alone must not automatically discard or fail the
Session. Preserve available scientific data and historical timing information.
Read-only reconciliation does not require administrator authorization; any new
operational recovery attempt remains subject to Decision 339.

**Implementation status for Q024-B (Decisions 339-346):** Architecture accepted;
supported service-specific cases are complete, independently manually validated,
and independently audited after correction, as recorded in W039.
Controller informational reconciliation, obligation-scoped authorized archive/record
rewrites and fresh transfers, independent node artifact finalization/device cleanup,
and historical timing/uncertainty reporting reuse existing owners and evidence paths.
Missing trustworthy inputs and unsupported partial-artifact repairs are refused;
active-Session clock restoration and application restoration are not implemented.
Final implementation testing ran 656 tests: 649 passed, 7 optional skips, zero
failures. Initial independent manual IPython validation passed 22 checks. The
initial independent source audit failed on one P2 Controller reconciliation defect;
the correction safely handles optional/non-mapping command details and preserves
unassociated uncertainty without inventing Session identity or participant completion.
Focused independent revalidation passed 16 checks; the final independent read-only
re-audit returned PASS with no blocking defects or architectural ambiguity and
independently passed 20 relevant automated tests. Retained scientific-manifest
recovery corrections preceded the initial source audit. These are prior validation
results, not validation executed during documentation closure.
The completed, independently validated and audited
Decisions 332-338 narrow slice remains unchanged; Decision 336 remains partially
implemented, limited to guarded release of redundant producer-owned evidence
copies. Q024-B accepts the service-specific execution boundaries above, not a
universal recovery system, automatic replay/retry/resumption, process supervision,
new Session states, application-wide restoration, automatic durable deletion,
new evidence infrastructure, Q019 finalization guarantees, or Q022 deployment
configuration. Recovery-journal retention/deletion, abandoned journals,
application-wide Session discovery, Controller/application restoration, stale
reservations, and remaining memory/cache retirement remain deferred. Q024, Q019,
Q022, Phase 16, and M015 remain OPEN.

---

## Decision 347: Evidence Archive repair requires durable Ingestor acceptance without circular archival prerequisites

**Status:** Accepted

For operator-authorized recovery of an interrupted Evidence Archive write, the
administrator explicitly authorizes the identified obligation through the existing
administrator-decision mechanism. Both authorization and recovery attempt must be
durably accepted by Ingestor through its existing recovery journal before
StorageManager executes the repair. NATS publication alone is not durable acceptance.

Confirmed durable Ingestor acceptance is sufficient to permit the repair attempt
when all other StorageManager recovery prerequisites are satisfied. Do not require
successful preservation in the unavailable Evidence Archive before repairing it.
If durable acceptance cannot be established, refuse execution and leave the
obligation unresolved.

StorageManager may repeat the interrupted write using complete trustworthy inputs,
must verify actual durable-write success, and subsequently preserves recovery
evidence including the actual outcome through the existing Evidence Archive path.
Actual write confirmation and subsequent recovery-evidence archival confirmation
remain distinct. No separate journal, evidence system, archive, or Q019 finalization
guarantee is introduced.

---

## Decision 348: Lost active Session Time is reported without invented clock restoration

**Status:** Accepted

If SynchronizationManager crashes during an active Session and loses the trustworthy
reference needed to continue Session Time, preserve trustworthy historical
synchronization evidence and mappings and scientific recordings with their original
timestamps. Explicitly report continuity gaps, uncertainty, and affected scope.
Inform the operator of the interruption and possible scientific timing degradation.

Never reactivate an old mapping across downtime without trustworthy justification,
restart Session Time at zero for the same ongoing Session, or fabricate a missing
time relationship. When trustworthy information is insufficient, report that active
synchronization recovery cannot safely be completed. Do not automatically fail,
abort, or discard the Session merely because SynchronizationManager crashed.

Outside an active Session, normal synchronization may resume through existing
mechanisms once valid synchronization is established. Ordinary healthy mapping
updates retain existing behavior and require no new administrator authorization.
No new active-Session clock-restoration mechanism is authorized in Q024-B.

**Implementation status for Decisions 347-348:** Accepted clarifications synchronized;
supported archive repair now requires journal-backed authorization and attempt
acceptance before writing, with actual-write and outcome-archival confirmation
reported separately. Historical timing reconciliation reports lost continuity and
blocks zero-based restart for a diagnosed ongoing scope without restoring its clock.
The supported cases completed automated testing, independent manual validation,
and final independent re-audit PASS as recorded in W039. Earlier validation and
audit records, including the initial failure and correction, are preserved.
Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

---

## Decision 349: Ingestor owns conditional retirement of temporary recovery journals

**Status:** Accepted

Ingestor owns the lifecycle of its temporary recovery journals. Automatically
retire/delete a journal only when all applicable conditions are confirmed:

- Its work is no longer active or awaiting recovery.
- Required persistent evidence and intake audit are durably preserved.
- Applicable Session finalization requirements are confirmed.
- The journal is no longer required for crash reconstruction or deduplication.

Retain the journal if any condition is uncertain. Administrative abandonment
alone is insufficient; no automatic age-based expiration or daily/monthly
temporary-journal rotation is accepted.

Decisions 276-280's journal-before-ACK, known-Session reconstruction, and
deduplication contracts remain authoritative. Journaling nonpersistent evidence
does not make it permanent Evidence Archive content. This resolves the journal
lifecycle ownership and conditional-deletion deferral in Decision 280 and supplies
the separately governed journal-retirement policy deferred by Decision 336.
Automatic deletion is permitted only for temporary journals under these confirmed
conditions, not permanent records or merely because memory was released or an
obligation abandoned.

Q019 still owns unresolved Session-wide final evidence-consumption/closure
conditions. This decision does not invent confirmation of those conditions.

---

## Decision 350: Terminal deletion of unrecoverable temporary evidence requires explicit authorization

**Status:** Accepted

A human operator may explicitly authorize discarding identified permanently
unrecoverable temporary evidence after being informed of potential permanent loss.
A failed recovery attempt never automatically authorizes deletion.

Preserve the original obligation/data identity, administrator authorization,
known loss, actual execution outcome, and durable evidence wherever possible.
Abandonment/loss is not successful preservation; authorization is not confirmed
deletion or resource safety. Reuse existing Q024-B authorization, command/result
correlation, and evidence-integrity protections.

This is a distinct authorized terminal action, not indiscriminate `drop`, automatic
journal expiry, or deletion of permanent framework archives. If required auditing
or persistence cannot be established because the evidence subsystem is unavailable,
record the architectural conflict for clarification rather than invent an exception.

---

## Decision 351: Every Controller startup reconciles observable known participants

**Status:** Accepted

Every Controller startup reconciles observable states of known runtime participants
through existing communication, readiness, and status interfaces. It need not
determine whether a previous Controller instance crashed. Each principal service
owns inspection/reporting of its durable evidence and unfinished obligations.

Distinguish confirmed active, stopped, failed, and unknown participant states.
These are observed participant conditions, not new lifecycle states.
Loss of Controller's in-memory Session does not prove acquisition stopped. If an
AcquisitionNode continues recording safely, Controller must not automatically stop
it. The operator may authorize coordinated stopping/preservation; handle nodes
independently, report only confirmed results, and retain unreachable participants
as unknown.

Multiple unfinished Sessions may be reported when supported by existing trustworthy
evidence, without a recovery registry or Session replicas. This extends Decision
345's informational reconciliation scope but does not restore Session objects,
restart Experiments, replay operations, or restore application orchestration state.

---

## Decision 352: Controller failure does not invalidate node-owned reservations

**Status:** Accepted

AcquisitionNode retains authoritative Session-keyed reservation ownership. A
Controller crash does not invalidate reservations. Reconciliation reports
reservation and actual acquisition state and protects running acquisition.

For a stopped node, evaluate local scientific-artifact finalization and device
cleanup independently. Use existing authorized recovery and Session-keyed release
mechanisms only after applicable safety and finalization are confirmed. Unconfirmed
cleanup cannot authorize release; one node's success never proves another's success.

Local scientific finalization remains separate from global artifact collection.
No reservation leases, automatic expiration, arbitrary timeouts, or centralized
registry are introduced. Existing node authority and cleanup protections remain
in force; this resolves the reconciliation boundary previously deferred under Q024,
not an automatic reservation-release policy.

---

## Decision 353: Principal services retire unnecessary temporary working information

**Status:** Accepted

Controller, AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager
must retire unnecessary temporary working information after applicable preservation
and safety conditions. This includes completed, abandoned, and permanently
unresolved work.

Retain the minimum evidence and state needed for unresolved-obligation reporting,
resource protection, deduplication, and preventing unsafe command reexecution.
Permanent records remain independent of temporary memory. Administrator `drop`
alone does not authorize indiscriminate memory retirement or unsafe resource release.

This extends Decision 336 beyond guarded release of redundant producer evidence
copies without removing its safeguards. Existing Ingestor accepted-evidence/
deduplication state and service-maintenance command/result/attempt caches require
attention during implementation. No universal memory manager or constant-RAM
guarantee under unlimited unresolved work is introduced; genuine operational limits
must be documented.

---

## Decision 354: Permanent framework Evidence Archives use calendar-month partitions

**Status:** Accepted

This decision explicitly supersedes the shared framework Evidence Archive layout
in Decision 323, which is preserved historically. Its evidence ownership, durable
write, exact confirmation, audit linkage, and integrity requirements remain.

Use one permanent framework evidence partition per calendar month:

```text
<storage_root>/framework/evidence/YYYY-MM/
    runtime_evidence.jsonl
    ingest_audit.jsonl
    compilation_summary.json
```

Newly archived framework evidence belongs in the appropriate new monthly partition;
historical event timestamps remain unchanged. Closed monthly archives are not
rewritten when later evidence arrives. New writes must not rebuild years of
historical framework evidence.

Session Evidence Archive organization and scientific artifact storage are unchanged.
Monthly partitioning applies to permanent framework evidence, not temporary Ingestor
journals. No daily/weekly rotation options, calendar-timezone rules, or additional
configuration requirements are established here.

---

## Decision 355: Finalized historical archives and safe-to-delete archives are distinct

**Status:** Accepted

A finalized archive accepts no further writes and is immutable. An archive is safe
to delete only when no future framework operation or crash recovery depends on it.
Deleting an archive confirmed safe to delete must not interfere with any later
framework operation or recovery.

Permanent historical archives must not remain the authoritative operational recovery
store. Unfinished operations and cross-month obligations must retain required
recovery/safety information independently of deletable historical monthly archives.
A finalized archive may still be unsafe to delete; report outstanding dependencies
accurately.

Permanent framework archives are never automatically deleted at month end or merely
because they become safe to delete. Manual deletion remains the user's choice.
Scientific and institutional retention requirements are separate from technical
deletion safety.

Existing framework preservation confirmation and maintenance evidence lookup must
honor this guarantee. The current shared-archive implementation's exact-compilation
checks and archive-dependent maintenance lookups do not yet establish cross-month
dependency independence. The missing operational contracts remain identified under
Q024 for clarification; this decision introduces no cross-month recovery subsystem.

### Accepted LLC clarification: monthly archives and cross-month continuity

An operation may begin in one calendar month and finish in another without
splitting the operation or rewriting historical archives. Evidence belongs in
its appropriate monthly partition and is correlated using existing operation
identities.

Services must retain the operational information necessary for unfinished work
independently of finalized historical archives. Once a historical archive is
declared safe to delete, future recovery must not depend on that archive. Reuse
existing persistence and operation identities; no new recovery database, registry
or elaborate reconstruction mechanism is authorized.

This accepted clarification supplements Decisions 353-355 without replacing
their historical text or assigning a new decision number. It does not specify
the authoritative timestamp or timezone for monthly partition assignment; Decision
354's explicit deferral of calendar-timezone rules remains unresolved. Q024 tracks
that implementation prerequisite separately from the accepted continuity rule.

### Accepted LLC clarification: administrative UTC archival month

Framework Evidence Archive monthly partitions are administrative, not scientific
timing records. StorageManager assigns evidence using its local system clock at
archival write time, with UTC calendar-month boundaries. Original event, receipt,
Session, node and synchronization timestamps remain unchanged. Delayed and
recovered evidence belongs to the month of its actual archival write, not its
historical event time. SynchronizationManager participation and synchronization
quality are not required.

Invalid or unavailable clock information fails closed: retain evidence, report
failure and permit safe retry. Interrupted or uncertain writes require
reconciliation before retry, without duplicate evidence across monthly partitions.
Unconfirmed writes do not establish preservation. Historical archives remain
immutable; cross-month operations retain their existing identities and necessary
operational recovery state. No new time authority, synchronization dependency,
archive registry or recovery subsystem is authorized.

This subsequent accepted clarification resolves the timestamp/timezone deferral
recorded above and in Decision 354 without renumbering or rewriting earlier
decisions. Decision 355's independent recovery and deletion-safety requirements
remain mandatory.

**Current bounded implementation status (W071 CLOSED):** Monthly framework writes and
cross-month cumulative confirmation are implemented through the existing
StorageManager APIs. Codex verification passed 59 distinct checks; independent ICC
IPython validation passed 6/6 checks and independent implementation/source review
passed with no confirmed P0-P3 findings. See W071 in validated_workflows.md for
scope and validation limitations. New evidence/audit
suffixes use administrative UTC write-time partitions; older products are not
rewritten. Existing shared-layout archives remain verified read-only prefixes.
Existing framework journals retain operational reconstruction/deduplication state.
No historical archive is declared safe to delete: confirmation and maintenance
lookup still depend on retained archives. Decision 355 deletion eligibility and
Decision 353 memory retirement are not established by this slice. Incomplete
partitions fail closed; existing authorized repair supports an identified
same-month interrupted target, not automatic repair or reassignment of an older
or unidentified interrupted partition. Q024 remains OPEN.

**Implementation status for Decisions 349-355:** Accepted architecture synchronized
with supported Decisions 351-352 startup reconciliation implemented for explicitly
known participants through existing NATS startup/readiness and owner diagnostics.
Automated coverage exercises active, stopped, failed, and unknown observations,
independent node obligations/reservations, cancellation, and unchanged-evidence
deduplication. This supported slice is complete with ICC review, independent manual
validation, correction revalidation, and final independent re-audit PASS in W040;
the initial failed audit and both corrections are preserved there.
Decisions 349-350 and 353-355 remain unimplemented. Q024-B
Decisions 339-348 remain complete and independently validated/audited in W039.
Decision 336 remains partially implemented. Q024, Q019, Q022, Phase 16, and M015
remain OPEN. Q019 closure conditions and safe-to-delete operational dependencies
must not be resolved by implementation assumptions.

---

## Decision 356: Acquisition evidence completeness requires producer confirmations and independent consumption proof

**Status:** Accepted

Relevant acquisition-stage producers complete their evidence production and
confirm successful durable publication. Controller waits for required producer
confirmations, then publishes one Session-scoped acquisition-evidence-completion
marker through the existing JetStream evidence infrastructure.

Ingestor independently verifies that all earlier required acquisition evidence was
durably accepted, using ordered JetStream evidence and verified consumer
acknowledgment progress. Receiving the marker alone is insufficient. Producer
publication, durable Ingestor acceptance, and StorageManager archival confirmation
remain distinct.

Reuse Decisions 276-280's journal-backed acceptance and recovery contracts. Do not
introduce per-producer terminal markers, count registries, arbitrary sleeps,
polling, or another evidence transport. Exact contiguous-consumption proof remains
a Q019 low-level technical verification question, not an implementation assumption.
This supplements Decisions 223-224 without transferring compilation, meaning,
persistence-selection, or lifecycle ownership.

---

## Decision 357: Session Evidence Archives separate acquisition preservation from later final closure

**Status:** Accepted

The Session Evidence Archive has two preservation stages using the existing
archive, not another archive or a new Session lifecycle state.

**Stage A - acquisition preservation:** After acquisition stopping and applicable
evidence-completeness confirmation, Ingestor compiles accepted persistent
acquisition evidence and intake audit. StorageManager durably writes acquisition
evidence, intake audit, compilation summary, and the final Session Record.
Confirmed Stage A preservation satisfies acquisition-side final-persistence
obligations for successful Session completion and applicable participant
Session-binding release. The Session may reach `completed` before scientific-
artifact collection. Applicable cleanup, handoff, and evidence obligations remain
required; principal services retain their Session-independent lifetimes.

**Stage B - later collection and permanent archive closure:** After operator-
requested global collection, StorageManager appends its own collection evidence
directly to the same `runtime_evidence.jsonl`, updates `compilation_summary.json`
to distinguish Ingestor-accepted evidence from directly persisted StorageManager
evidence, verifies durable preservation, and permanently closes the archive.
The archive remains available for Stage B after Stage A. Stage B must not modify
acquisition evidence, its existing Ingestor audit, the final Session Record, or
the completed scientific acquisition outcome. Once final closure is confirmed,
the archive is immutable; recovery cannot silently rewrite historical outcomes.

This qualifies Decisions 228-229 and 275: required acquisition-side final
persistence is Stage A, not a requirement to finish global collection first.
Controller coordinates later collection; StorageManager confirms Stage B
preservation and closes the archive. Session retains lifecycle ownership.
Session Record and Evidence Archive remain separate under Decision 226. Recorded
collection failures are valid operational outcomes and do not retroactively
change a completed Session, consistent with Decision 303. NWB conversion and
Cheaha upload remain later scientific processing stages.

**Accepted LLC clarification (permanent closure):** Permanent closure requires a
separate explicit operator request, not automatic closure after collection. Decision
362 records the closure conditions and their distinction from artifact outcomes.

---

## Decision 358: StorageManager directly preserves its later collection evidence in the Session archive

**Status:** Accepted

StorageManager constructs its own persistent `RuntimeEvidenceMessage` for actual
collection outcomes and directly preserves it in the existing Session Evidence
Archive during Stage B. Do not route this evidence back through Ingestor or
fabricate Ingestor audit entries for directly persisted evidence. Compilation
summary distinguishes the two preservation origins without a new archive.

Preserve evidence identity, source and Session association, auditability,
duplicate-ID protection, durability, integrity, and crash safety. Interrupted
evidence persistence cannot imply success or automatically repeat artifact
transfer. Do not introduce self-referential archival evidence. The exact integrity
and interrupted-write recovery contracts remain Q019 low-level questions.

This explicitly qualifies Decisions 223-225 for later StorageManager-owned
collection evidence and supersedes Decision 274's Ingestor routing/compilation
requirement for that Stage B evidence. Ingestor still owns acquisition evidence
intake, audit, and compilation; producer-controlled persistence and Decision 224's
prohibition on interpreting others' evidence remain intact. StorageManager does
not acquire Session lifecycle, scientific interpretation, or local artifact
ownership. Historical W033/M013 implementation and validation are preserved.

**Accepted LLC clarification (W045 - scientific data priority):** Preservation of
scientific artifacts is the primary objective. Operational evidence remains
important for diagnostics and auditability, but does not justify unnecessary
recovery infrastructure. Stage B retrieves scientific artifacts created and
finalized by their respective Experiments; it does not reopen or modify them.
Uncertainty about operational evidence must not automatically be represented as
loss or corruption of scientific data. Previously accepted mandatory evidence
guarantees and existing partial-artifact/missing-finalization contracts remain in force.

---

## Decision 359: Durable collection handoff permits later collection without original Session bindings

**Status:** Accepted

At acquisition closeout, Ingestor compiles the existing ArtifactManifest collection
handoff and supplies it to StorageManager. StorageManager durably preserves it
under the appropriate Session identity. The original Controller and Ingestor
Session bindings may then be released once their applicable obligations are
satisfied, preserving Decisions 313 and 322's safety and evidence requirements.

Later, the long-lived Controller coordinates operator-selected collection for one
or multiple stopped Sessions without restoring their original Session bindings.
StorageManager retrieves the preserved handoff, resolves AcquisitionNode endpoints
using deployment-local configuration, and performs retrieval and verification.
Scientific artifacts remain locally owned by AcquisitionNodes until collected;
manifest information is not artifact bytes. Existing local ownership is not
transferred by handoff preservation.

This qualifies Decisions 240 and 243's handoff availability/delivery boundary.
Ingestor retains compilation ownership and StorageManager retains retrieval and
persistence ownership. No automatic collection, new authoritative ArtifactManifest
registry, or implicit retry/resumption is accepted. Durable representation,
post-restart lookup, and eligible-Session selection remain Q019 low-level questions;
no new API, storage schema, or deployment mechanism is defined here.

---

## Decision 360: Kill Session is authorized forced acquisition closeout without immediate archive closure

**Status:** Accepted

Kill Session is explicitly operator-authorized forced Session closeout, distinct
from Normal Stop and service-level Kill. Preserve accessible acquisition evidence,
available scientific files, a partial Session Record, and unresolved conditions
promptly where possible. Preserve hardware and resource-safety requirements.
Do not invent a `killed` Session lifecycle state or infer successful cleanup from
forced closeout.

Killed Sessions remain eligible for later operator-requested scientific-artifact
collection, including attempts involving incomplete, missing, or corrupted files.
Kill does not automatically initiate global collection. The partial Session
Evidence Archive remains open for the later collection-evidence stage; do not
permanently finalize it solely because the Session was killed. Once StorageManager
confirms Stage B preservation and finalizes the archive, it is immutable. Later
recovery does not silently rewrite historical outcomes.

This qualifies Decisions 228-229 and 275's closeout/finalization boundary for
forced partial acquisition closeout, without changing service-level maintenance
authority or adding a lifecycle state. Normal versus forced partial acquisition-
evidence closeout confirmations remain Q019 low-level questions; this decision
does not choose their command contracts or required confirmation representation.

**Implementation status for Decisions 356-360:** Accepted Q019 architecture
synchronized; bounded Normal Stop integration is complete with independent validation
and targeted re-audit PASS after correction (W047). W041 separately completes Decision 361's receiving foundation and routing
prerequisite after independent validation and final re-audit PASS. Q019
remains OPEN for overall integration validation; eligible-Session selection is complete in W049. Explicit permanent archive closure is complete in W046.
W043/W044 separately complete bounded Stage A and durable handoff; bounded Stage B
collection/evidence persistence is complete with independent manual validation and
final targeted independent re-audit PASS after correction (W045).
Earlier decisions, implementation records, and validation results remain historical;
W033/M013, W035, W039, and W040 retain their completed validated scopes. Decisions
349-350 and 353-355 remain unimplemented; Decision 336 remains partial. Q024, Q022,
Phase 16, and M015 remain OPEN; W041 does not close these broader contracts.

---

## Decision 361: Ingestor retains durable evidence-receiving progress and independently proves acquisition completeness

**Status:** Accepted

Reuse the existing JetStream evidence infrastructure. Ingestor reliably retains
its Session-specific evidence-receiving position across service restarts. Each
required acquisition-stage producer confirms completed evidence publication;
Controller publishes one Session-scoped acquisition-evidence-completion marker
after obtaining those confirmations.

Ingestor independently establishes durable receipt and acceptance of all required
evidence preceding that marker using verified, contiguous JetStream acknowledgment
progress covering the full relevant publication interval. Marker receipt,
successful producer publication, or acknowledgment of isolated messages does not
prove completeness. Gaps, missing history, unknown receiving position, or missing
producer confirmations prevent successful Normal Stop completeness confirmation.
Preserve Decisions 276-280's journal-before-ACK, reconstruction, and deduplication
guarantees.

JetStream may internally call its receiving mechanism a consumer; this is not a
new architectural service or framework component named Consumer. No per-producer
completion markers, count registries, arbitrary waits, polling, or additional
evidence transports are introduced.

This specifies Decision 356's receiving-progress contract. Exact JetStream behavior
and feasibility must be independently verified during implementation. If the
supported infrastructure cannot establish the required proof, report the
limitation rather than weakening the guarantee.

**Implementation status (receiving foundation only):** Ingestor-side Session
subscription now retains a durable explicit-ACK receiving position and confirms
ACKs only after existing journal acceptance. Readback verifies exact journal-backed
completion-marker receipt, original receiving identity, intact stream-origin history,
and coherent contiguous ACK progress, with rechecks after asynchronous operations.
The journal-continuity audit correction reconciles Session-matching publications through
the marker with exact current retained journal contents under Ingestor's intake
guard; lost or incomplete journal history cannot be replaced by historical ACKs.
The subsequent correction uses Ingestor's existing canonical serializer for
type-sensitive content and duplicate-identity comparison, including marker checks.
The existing three-stream provisioning uses disjoint five-/six-token filters and
in-place legacy-filter correction without stream recreation. Developer automated
tests include an isolated local JetStream server and controlled broker doubles.
The receiving-foundation slice is complete with developer automated testing,
independent manual IPython validation, and final independent re-audit PASS in W041.
W041 preserves both failed audits, their corrections, and stage-specific validation
results; this is not complete acquisition closeout. The subsequent supported
producer-confirmation/marker prerequisite under Decision 366 is complete with automated
coverage, independent manual validation, and targeted independent re-audit PASS after
correction (W042). Bounded Normal Stop orchestration is complete after correction
in W047; Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048). Decision 362's bounded Stage A slice is
complete with automated testing, independent manual validation, and independent
audit PASS (W043); bounded Stage B collection/direct evidence persistence is
complete with independent manual validation and final targeted independent re-audit
PASS after correction (W045). W046 explicit closure is complete with independent
validation and targeted re-audit PASS after correction. Decision 365's bounded
Normal Stop is complete after independent validation and targeted re-audit PASS
after correction (W047); Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048). The bounded Decision 364 handoff is complete
with automated testing, independent manual validation, and independent audit PASS
(W044). Missing history or an unknown receiving origin cannot establish completeness;
no narrower publication-interval boundary is invented. Q019 is CLOSED following overall software integration validation (W050).

---

## Decision 362: The existing compilation summary distinguishes archive stages and confirmed permanent closure

**Status:** Accepted

Retain the single Session Evidence Archive and its existing three evidence
products. Stage A durably preserves Ingestor-compiled persistent acquisition
evidence, intake audit, compilation summary, and the separate final Session Record.
Confirmed Stage A preservation satisfies acquisition-side final-persistence
obligations for successful Session completion and applicable Session-binding
release. The archive remains open for later Stage B collection evidence.

In Stage B, StorageManager directly appends its own collection evidence to
`runtime_evidence.jsonl` and updates the existing `compilation_summary.json`,
distinguishing Ingestor-accepted evidence from directly persisted StorageManager
evidence. The summary records whether Stage A has completed or the archive has
been permanently closed following Stage B. No separate closure file, additional
Evidence Archive, or new Session lifecycle state is introduced; no specific new
field names or values are chosen here.

A status field alone does not prove durability or consistency. Permanent closure
requires verified consistency and durable preservation of the archive products;
after confirmed permanent closure, the archive is immutable. Preserve original
acquisition evidence, Ingestor intake audit, final Session Record, and acquisition
outcome. This specifies Decision 357's stage and closure-information contract.

**Accepted LLC clarification (permanent Evidence Archive closure):**

- Permanent closure requires a separate, explicit operator request; it does not
  occur automatically after Stage B artifact collection.
- Closure does not require every scientific artifact to have been successfully
  retrieved or verified.
- All applicable collection outcomes must be durably recorded, with no unresolved
  evidence writes.
- StorageManager must verify consistency and durable preservation of the existing
  Session Evidence Archive before confirming closure.
- Once permanently closed, the archive is immutable, including after restart.

Scientific-artifact collection outcomes, evidence preservation, Session lifecycle,
and permanent archive closure remain separate. This clarification is accepted;
W046 permanent closure is complete with developer testing, independent manual
validation, and targeted independent re-audit PASS after correction. W041-W045 remain complete and Q019
remains OPEN. No new lifecycle state, database, registry, or
recovery infrastructure is introduced.

**Implementation status (W046 explicit closure):**
`PersistentStorageManager.close_session_evidence_archive(session_id)` validates
the current persisted Stage A/B evidence, intake audit, provenance, final Session
Record, and handoff under the existing preservation lock. Pending/unconfirmed writes
block closure, but durably recorded unsuccessful or unknown collection outcomes do
not. Only the existing summary changes, through fsynced temporary contents and atomic
publication followed by supported directory fsync and current product readback.
Repeated/restarted closure reconfirms closed contents without rewriting. Failed
publication or durability/readback cannot return success. Applicable ordinary and
authorized write paths enforce immutability; generic final-record writes serialize
with closure. W046 records initial developer tests 27/27 PASS, initial independent
IPython validation 8/8 PASS, initial audit FAIL with one P2 path-alias immutability
defect, correction tests 6/6 PASS, independent correction validation 2/2 PASS, and
targeted independent re-audit PASS with no remaining confirmed P0-P3 findings.
The corrected guard resolves the complete target path and configured storage root
before identifying the managed final record, preserving pre-closure writing while
preventing equivalent-path bypass after restart. These are prior results, not new
validation during documentation closure. Bounded Normal Stop is complete in W047;
Eligible-Session selection is complete in W049; overall Q019 software integration validation is complete in W050.

**Accepted LLC clarification (W045 - trusted Stage A baseline):** For a known
Session, StorageManager may establish a trustworthy Stage A preservation baseline
by reading and validating persisted Session products, independently of previous
in-memory state and original Controller/Ingestor Session bindings. The relevant
existing products are `evidence/runtime_evidence.jsonl`, `evidence/ingest_audit.jsonl`,
`evidence/compilation_summary.json`, `session_record_final.json`, and
`artifact_collection_handoff.json` for the applicable collection handoff.
StorageManager verifies internal consistency and Session association using existing
identities, counts, evidence provenance, completion information, and persistence
guarantees. A `stage_a_complete` flag alone is insufficient. No separate preservation
registry, database, additional snapshot record, or new evidence infrastructure is
required. Original acquisition evidence must not be reconstructed or overwritten
from a new Ingestor compilation merely to establish this baseline.

**W048 clarification (partial Kill preservation):** Decision 365 permits later
operator-requested scientific-artifact collection using available verified
artifact information from partial Kill preservation. Partial preservation must
remain distinguishable from complete Stage A preservation; it must not fabricate
complete receipt, marker provenance, or missing information. Existing identity,
consistency, durable preservation, and recovery requirements remain applicable to
the information actually preserved. This does not weaken Normal Stop's complete
preservation requirements or implement partial-baseline support.

Decision 364's W048 clarification defines the permitted partial-handoff refresh
boundary before the first Stage B collection attempt, without authorizing changes
to historical evidence or collection outcomes.

Stage B preserves original acquisition evidence, the existing Ingestor intake
audit, and the final Session Record unchanged. It appends StorageManager collection
evidence to the existing runtime-evidence file and updates the existing compilation
summary with separate evidence origins and applicable Stage B preservation
information. Previously confirmed Stage B evidence is recognized without
duplication; duplicate evidence IDs cannot generate duplicate archive records.
Permanent archive immutability remains required after confirmed closure. Missing,
conflicting, incomplete, or untrustworthy evidence is reported without inventing
preservation success. This clarification is accepted; bounded W045 implementation
is complete with focused developer testing, independent manual validation, and
final targeted independent re-audit PASS after correction. Q019 is CLOSED following overall software integration validation (W050).

**Implementation status (Stage A slice):** Explicit Controller archival now verifies
W041 receipt of its confirmed W042 marker and protects the current journal/intake
snapshot before StorageManager persists the existing evidence/audit/summary and
final Session Record. The summary records Stage A completion, open-archive status,
marker identity/sequence, and Ingestor origin IDs; exact current readback is required.
Failure is not confirmation and interrupted writes require existing authorized
recovery. This bounded slice is complete with 16 focused developer tests passed,
independent manual IPython validation 17/17 PASS using local real JetStream, and
independent audit PASS with no confirmed P0-P3 defects or corrections required
(W043). Additional cross-thread archive-rewrite coverage was suggested only as an
optional improvement. It does not complete or release the Session, persist Decision 364's
handoff, implement Stage B, or provide full Normal Stop/Kill integration.

---

## Decision 363: StorageManager durably retains collection outcomes before direct archival

**Status:** Accepted

Each collection attempt has a unique persistent evidence ID. After determining
actual collection outcomes, StorageManager temporarily and durably preserves the
outcome and corresponding evidence ID before appending the associated persistent
evidence to the Session Evidence Archive. It verifies durable archival before
treating the evidence as preserved; the temporary outcome record may be retired
only when safe.

Duplicate evidence IDs must not produce duplicate archival records. Distinguish
existing complete evidence from incomplete, conflicting, or interrupted writes.
An interrupted or uncertain archive write cannot establish successful archival
or permanent closure. A durably preserved collection outcome can support recovery
of evidence persistence without repeating scientific-file transfer. If collection
ended before temporary outcome durability was established, the outcome remains
unconfirmed; do not invent success.

Recovery respects existing Q024 authorization, evidence, preservation, and safety
contracts. No automatic scientific-file retries, unrestricted archive repair,
historical-result rewriting, or self-referential archival evidence are authorized.
The temporary record is not another permanent Evidence Archive or artifact
registry. Its filename and schema are not specified here. This specifies Decision
358's direct-write integrity and interrupted-persistence recovery contract.

**Accepted LLC clarification (W045 - interrupted writes and recovery):** A restarted
StorageManager may examine the existing Session archive without the original live
Ingestor compilation or cached Stage A snapshots, using Decision 362's clarified
persisted-product baseline. Recovery preserves established Stage A contents and
previously confirmed Stage B evidence, distinguishes intact evidence from
interrupted or conflicting writes, and retains this decision's durable temporary
collection outcomes and evidence IDs. Interrupted evidence persistence must not
automatically trigger scientific-artifact transfer again or imply successful
permanent archive closure. Existing authorization and recovery constraints remain
applicable; no new recovery subsystem or automatic repair policy is authorized.
Documentation synchronization itself did not implement or validate this clarification.

**Implementation status (bounded Stage B collection/evidence persistence):**
StorageManager validates existing known-Session products and the saved handoff
after restart or another Session's archival, without old bindings or a new
compilation. Explicit collection reuses existing retrieval/light verification;
actual results and a stable evidence ID are fsync/readback-preserved temporarily
before direct runtime-evidence append and provenance update. Exact current
readback confirms preservation separately from collection success. Existing
authorized `recover_archive_write` can complete the identified pending evidence
write without refetch, duplicate records, or historical replacement. Corrupt or
conflicting products remain unconfirmed. Original acquisition evidence, audit,
record, and prior confirmed collection evidence are preserved; the archive stays
OPEN. W045 is complete with 32 initial developer tests passed, initial independent
IPython validation 9/9 PASS, initial audit FAIL with two P2 findings, 14 correction
tests passed, independent correction validation 3/3 PASS, and final targeted
independent re-audit PASS with no remaining confirmed P0-P3 defects. Corrections
prevent missing/inconsistent provenance from authorizing destructive archive
replacement and reject cross-Session acquisition envelopes or incomplete intake
audit as a trustworthy persisted Stage A baseline. These are prior results, not
new validation during documentation closure. W046 explicit closure is complete with
independent validation and targeted re-audit PASS after correction; eligible-Session selection is complete in W049; overall Q019 software integration validation is complete in W050; bounded Normal Stop and Kill are complete in W047/W048.
Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

---

## Decision 364: StorageManager preserves the Session collection handoff as a separate durable JSON file

**Status:** Accepted

At acquisition closeout, Ingestor compiles the existing ArtifactManifest handoff.
StorageManager durably preserves it as a small Session-associated JSON file in the
existing Session storage directory, separate from scientific artifacts and the
Evidence Archive. Preservation must be verified before the handoff obligation is
satisfied. Original Controller and Ingestor Session bindings may be released after
all their applicable obligations are confirmed.

Later operator-selected collection uses the saved handoff, including after service
restart. StorageManager validates its information and resolves AcquisitionNode
endpoints using deployment-local settings; collection does not restore old Session
bindings. Preserve existing compilation semantics: prefer finalized manifests,
retain initial manifests when finalization evidence is missing, and report missing
finalization. A killed Session may have a partial or unconfirmed handoff.

**W048 clarification (partial handoff refresh):** StorageManager may refresh a
partially preserved ArtifactManifest handoff using additional verified manifest
evidence obtained through authorized recovery. Refresh is permitted only before
the first Stage B collection attempt begins. It must preserve existing evidence,
follow the existing Ingestor compilation rules, and be durably verified.

Once any Stage B collection attempt begins, including a failed or incomplete
attempt, the handoff becomes immutable. Historical evidence, collection outcomes,
and permanent Evidence Archive closure must never be rewritten. Normal Stop
guarantees remain unchanged. Reuse existing evidence, handoff, persistence, and
recovery mechanisms; introduce no new infrastructure.

This clarification does not implement or validate refresh support. The historical
W044 non-overwriting implementation and validation below remain unchanged; W048
must integrate the permitted pre-collection partial refresh and first-attempt
immutability boundary without weakening those Normal Stop protections.

Use existing persistent Session information for eligible-Session selection. Missing,
inconsistent, or unavailable information remains explicitly unresolved, not guessed.

**Accepted LLC clarification (eligible-Session predicate):** Ordinary
operator-selected scientific-artifact collection requires a durably confirmed
terminal Session state: `completed`, `failed`, or `aborted`. A Session still
recorded as `stopping` is not eligible until its termination status is resolved
through existing recovery mechanisms. Incomplete, missing, or corrupted scientific
files and unconfirmed participant cleanup do not disqualify an otherwise eligible
Session. Eligibility does not authorize hardware or resource release. Reuse
existing persisted Session information without a Session registry, new lifecycle
states, or application restoration. This clarifies Decisions 359 and 360's
stopped-Session and killed-Session collection descriptions. Eligibility is distinct
from collection availability as clarified below; multi-Session selection follows
the accepted clarification below.

**Accepted LLC clarification (enumeration and selection ownership):** StorageManager
enumerates saved Sessions using existing persistent Session directories and records,
without a Session registry. Controller coordinates operator selection of one or
multiple Sessions. Each candidate Session must be independently validated for
eligibility using existing persisted information and the predicate above.
Multi-Session selection follows the accepted clarification below.

**Accepted LLC clarification (eligibility versus collection availability):** A
Session with a durably confirmed terminal state (`completed`, `failed`, or
`aborted`) remains eligible even when its saved collection information is incomplete
or corrupted. Eligibility and collection availability are distinct. Collection may
proceed only when StorageManager verifies the persisted information required for
safe artifact retrieval and evidence persistence. Missing, incomplete, or corrupted
scientific artifacts alone do not prevent collection attempts. Missing, inconsistent,
corrupted, or interrupted preservation information blocks collection until resolved
through existing authorized recovery mechanisms. Permanently closed Evidence
Archives cannot accept further collection. Report eligibility, collection
availability, and reasons for any blockage separately. Persisted `stopping` remains
ineligible. No new lifecycle states, infrastructure, or recovery mechanisms are
introduced; enumeration and selection ownership above remain unchanged.

**Accepted LLC clarification (multi-Session selection):** Operators may select
only Sessions confirmed eligible and available for scientific-artifact collection.
Unavailable Sessions remain visible in the saved-Session listing but cannot be
selected; report the reason for unavailability. When multiple Sessions are selected,
Controller processes each independently. A collection failure for one Session does
not prevent collection of the others. Results report each Session's collection
outcome, with an overall summary distinguishing complete success, partial success,
and failure. No all-or-nothing transaction, special ordering, or automatic retries
are required. Existing per-Session collection, recovery, and archive-closure
guarantees remain unchanged. This completes the selection clarification of
Decisions 359-360 without implementing selection or closing Q019.

No authoritative ArtifactManifest registry, Session registry, application-restoration
system, or automatic collection is accepted. No exact handoff filename, new API,
or additional registry schema is defined. This specifies Decision 359's durable
representation and binding-independent collection contract.

**Consolidated Q019 implementation status (W050):** W041-W049 are complete with
their individual independent validation/audits. Overall developer integration
tests 7/7 and independent manual IPython checks 2/2 PASS preceded final independent
integration source audit PASS, with no confirmed P0-P3 production defects or
required corrections. The successful additional sequential Normal Stop probe is
now permanent regression coverage; newly executed developer integration tests
3/3 PASS. No further independent validation/audit or production changes are claimed
for that regression addition. Q019 is CLOSED within its supported software scope;
simulated broker/SFTP integration does not establish hardware, multi-host deployment,
external NATS deployment, or power-loss guarantees. Q022, Q024, Phase 16, and M015
remain OPEN. Historical W041-W049 records and accepted contracts are unchanged.

**Implementation status (eligible-Session selection):** W049 is complete with
independent manual validation and final independent read-only audit PASS after
correction. StorageManager enumerates saved directories, confirms lifecycle
independently of collection availability, and revalidates under collection guards.
Controller coordinates single/multi-Session collection using existing per-Session
mechanisms and reports individual outcomes plus complete/partial success or failure.
Initial developer tests 14/14 and manual checks 6/6 PASS preceded audit FAIL with
P2 single-Session eligibility bypass and P3 silently failing nested fixture cleanup.
Corrections enforce eligibility by default for ordinary collection while preserving
explicit internal Stage B/recovery exceptions, and register cleanup with the active
test owner. Correction tests 24/24 and independent checks 6/6 PASS preceded final
audit PASS: both findings resolved, no new P0-P3 findings. W049 records the full
history, six audit tests, resource probe, and software-only validation limitations.
Q019 is CLOSED following overall software integration validation (W050).

**Implementation status (bounded durable handoff):** Ingestor's existing compiler
is reused under protected durable journal/intake coverage after current Stage A
confirmation. Controller exposes an explicit preservation step without completing
or releasing the Session. StorageManager writes `artifact_collection_handoff.json`
separately in the existing Session directory using fsynced same-directory temporary
contents, non-overwriting publication, supported directory durability, and exact
readback. Identical retries reconfirm preservation; corrupt/conflicting files are
refused without repair. Known-Session readback after restart needs no original
runtime binding. Applicable Q019 release guards require current handoff coverage.
This bounded slice is complete with 24 focused developer tests passed, independent
manual IPython validation 17/17 PASS, and independent read-only audit PASS with
no confirmed P0-P3 defects or required corrections (W044). Existing hard-link and
filesystem durability prerequisites remain applicable; power-loss behavior was not
independently tested. Bounded Stage B collection/evidence persistence is separately
complete with independent manual validation and final targeted re-audit PASS after
correction (W045). W046 explicit closure is complete with independent validation
and targeted re-audit PASS after correction; bounded Normal Stop is complete in W047.
Bounded Kill integration is complete in W048; eligible-Session selection is complete with independent validation and final audit PASS after correction (W049). W041-W043 and all broader open statuses
are unchanged.

---

## Decision 365: Normal Stop requires complete acquisition preservation while Kill Session preserves confirmed partial information

**Status:** Accepted

**Normal Stop:** Requires all applicable acquisition-stage producer publication
confirmations, Ingestor verification of complete durable acceptance of required
acquisition evidence, and StorageManager confirmation of complete Stage A
preservation. Partial or uncertain evidence cannot justify successful normal
acquisition completion.

**Kill Session:** Requires explicit operator authorization and attempts to preserve
all accessible acquisition evidence and scientific files. It does not require
impossible completeness confirmation from unreachable participants. Explicitly
record known missing, incomplete, unconfirmed, or unresolved evidence and cleanup
obligations. StorageManager identifies Stage A preservation as partial where
completeness cannot be established. Partial preservation confirms only what was
actually preserved, not successful acquisition, artifact retrieval, complete
cleanup, or safe hardware release. Resource release still requires existing
device and hardware safety confirmations.

**W048 clarification:** Kill Session terminates an active Experiment using
`experiment_abort`, with unconfirmed participant cleanup recorded separately.
Preserve all available evidence and explicitly identify missing or uncertain
information; never claim complete preservation when it cannot be established.
Later operator-requested scientific-artifact collection remains permitted using
available verified artifact information, including when acquisition preservation
is partial. Reuse existing lifecycle, evidence, storage, and recovery mechanisms;
do not weaken Normal Stop guarantees or introduce new infrastructure. The
implementation-facing partial-baseline clarification is recorded in Decision 362.
This documentation synchronization does not implement or validate W048.

**W048 clarification (Session lifecycle and cleanup):** Kill Session may transition
the Session to `aborted` even when participant cleanup remains unconfirmed.
`cleanup_occurred=True` means the Session performed its local cleanup procedure,
not that all participants were successfully cleaned up. Unconfirmed participant
cleanup, hardware safety, and resource-release obligations must be represented
separately; existing safety requirements and authorized recovery protections
remain mandatory. This qualifies Decision 034's cleanup wording for Kill only.
Experiment termination remains `experiment_abort` under Decision 113; neither
that event nor Session abortion confirms participant cleanup, complete evidence
preservation, or safe resource release. Normal Stop guarantees and Decision 364's
pre-Stage-B partial-handoff refresh boundary remain unchanged. No new lifecycle
states or infrastructure are required. This clarification does not implement or
validate W048.

**Both:** Preserve accessible acquisition evidence promptly; do not automatically
start global artifact collection. Support later operator-requested collection,
including killed Sessions and incomplete scientific files, while preserving Stage B
direct collection evidence and permanent archive closure requirements. No `killed`
Session lifecycle state is introduced. Unknown outcomes must not be misrepresented
as either confirmed success or confirmed failure. This specifies Decisions 356-360's
normal and forced partial evidence-closeout requirements without changing ownership.

**Implementation status for Decisions 361-365:** Low-level Q019 contracts accepted
and synchronized. Decision 361's receiving foundation and routing prerequisite are
complete with automated testing, independent manual validation, and final independent
re-audit PASS after both corrections (W041). The supported Decision 366 producer/marker
prerequisite is complete with automated coverage, independent manual validation,
and targeted independent re-audit PASS after correction (W042). Q019 overall software integration validation complete (W050)
remains pending. The bounded Stage A slice under Decision 362 is complete
with automated testing, independent manual validation, and independent audit PASS
(W043); bounded Stage B collection/Decision 363 persistence is complete with
independent manual validation and final targeted independent re-audit PASS after
correction (W045); W046 explicit closure is complete with independent validation
and targeted re-audit PASS after correction. Decision 365's bounded Normal Stop
integration is complete with independent manual validation and targeted independent
re-audit PASS after both P2 corrections (W047). Initial developer tests 19/19 and
independent IPython checks 6/6 passed before the initial audit FAIL: pre-marker
cancellation could enable legacy completion, and late acquisition intake could be
omitted from the final record. Corrections retain the existing Q019 association
before asynchronous shutdown and compare current envelopes/audits with the durable
final record under existing guards before completion. Correction developer tests
12/12 and independent checks 3/3 passed; final re-audit found no remaining confirmed
P0-P3 findings. These are prior validation results, not new checks during documentation
closure. Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048).
The bounded Decision 364
handoff is complete with automated testing, independent manual validation, and
independent audit PASS (W044).
These decisions resolve the contract
questions identified in Decisions 356-360; their
historical text is preserved. Q019 implementation and independent verification
are complete in W041-W050; Q019 is CLOSED. No broker
configuration, additional schema, or new public API is specified. W033/M013, W035,
W039, and W040 retain their completed historical scopes. Decision 336 remains
partial; Decisions 349-350 and 353-355 remain unimplemented. Q024, Q022, Phase 16,
and M015 remain OPEN. W041 closes only the receiving-foundation slice.

---

## Decision 366: Session acquisition-completion responses confirm producer publication before the Controller marker

**Status:** Accepted

This clarifies Decisions 356 and 361's required acquisition-stage producer scope
and publication-completion boundary, using existing Session participation,
communication, and command/result contracts.

**AcquisitionNode completion:** An AcquisitionNode that actually participates in
acquisition for a Session must finish applicable acquisition work, evidence
generation, and successful durable publication before returning its existing
successful acquisition-completion response. That response also confirms completion
of all its applicable acquisition-stage evidence publication, regardless of whether
its selected devices are required or optional. An optional device not selected or
used creates no additional publication obligation. Accepted Session configuration
and actual participant execution establish the relevant identities.

A command result emitted before subsequent applicable artifact-manifest, health,
or other evidence publication cannot count as completion confirmation. Failed,
missing, or uncertain publication cannot support successful completion. Controller
requires no separate publication-confirmation messages, producer registry, count
mechanism, or per-producer terminal evidence marker.

**Controller and SynchronizationManager publication:** Before publishing the
Session's marker, Controller finishes publishing all its own applicable
acquisition-stage evidence associated with the closing Session and coordinates
completion of SynchronizationManager's applicable Session timing and mapping
evidence publication, including mapping evidence generated during acquisition
closeout. Reuse existing interfaces and communication mechanisms. Timing ownership
remains with SynchronizationManager; Controller does not assume Ingestor's
acceptance, completeness verification, compilation, or persistence responsibilities.

These obligations are Session-scoped. Long-lived Controller and
SynchronizationManager services remain operational and may produce evidence for
other Sessions or outside a Session. No general service shutdown, service-wide
evidence drain, global publication barrier, or new synchronization lifecycle is
required.

**Ingestor-owned evidence:** Ingestor-generated evidence, including recovery evidence
written directly to its durable journal, need not be published to JetStream merely
to return to Ingestor. Applicable locally generated Session evidence remains included
in Ingestor's compilation and persistence obligations. Existing receiving,
journaling, compilation, and persistence responsibilities and pathways are unchanged.

**Accepted completion sequence:**

1. Controller requests orderly acquisition shutdown through existing Session
   coordination mechanisms.
2. Participating AcquisitionNodes complete applicable acquisition work, evidence
   generation, and durable publication.
3. Their existing successful completion responses confirm publication completion.
4. Controller ensures completion of its own applicable Session evidence publication
   and SynchronizationManager's applicable Session evidence publication.
5. Controller publishes exactly one Session-scoped `acquisition_evidence_completion`
   marker through the existing JetStream evidence infrastructure.
6. Ingestor independently verifies complete durable acceptance of the evidence
   preceding that marker using Decision 361's W041-validated receiving foundation.
7. Subsequent acquisition preservation and Session finalization follow the existing
   accepted Q019 contracts.

The marker is not the Stop command: it establishes the acquisition-stage evidence
publication boundary for that Session. Neither durable JetStream publication nor
marker acceptance alone proves complete Ingestor receipt, StorageManager archival,
or successful Session completion. Missing, failed, or uncertain required
confirmations prevent publication of a successful acquisition-evidence-completion
boundary. A component must not generate additional applicable acquisition-stage
evidence after confirming publication completion in a way that invalidates that
boundary.

**Implementation status:** The supported producer-confirmation and marker-publication
prerequisite is complete with developer automated coverage, independent manual
IPython validation, and targeted independent read-only re-audit PASS after the P2
correction (W042). AcquisitionNode evidence precedes subscribed
command results; retained messages survive publication failure. SynchronizationManager
stops the prepared Session clock, retires that Session's mappings, and publishes
retained timing evidence before its result. Controller's explicit publication API
requires correlated node stops and synchronization confirmation, refuses unfinished
health processing, then publishes its own Session evidence and a stable marker.
Repeated confirmed calls emit no new marker; interruption preserves the same identity
for explicit retry. Existing finalization/release guards also retain owned rejection
and marker evidence until exact preservation is confirmed. This does not integrate
complete Normal Stop or Stage A/Stage B archival.
The initial audit FAIL for concurrent manifest-cursor advancement, the manifest/health
asynchronous-lock correction, 10 focused automated tests passed, initial manual
validation 5/5 and 4/4 PASS, correction validation 7/7 PASS on real JetStream, and
final targeted re-audit PASS with no remaining confirmed P0-P3 findings are preserved
in W042. Publication progress advances only after each entry's durable acknowledgment.
W041's receiving foundation remains independently validated and complete. Decisions
Bounded Kill integration is complete in W048; broader Q019 is CLOSED following overall software integration validation (W050); bounded
Normal Stop is complete after correction in W047. No new
component, transport, polling, sleeps, lifecycle state, or evidence pathway is added.
Q024, Q022, Phase 16, and M015 remain OPEN.

---

## Decision 367: One installed framework package uses explicit service-role launching

**Status:** Accepted

Install the framework as one software package containing its principal services
and supported DeviceAdapters. Select Controller, Ingestor, StorageManager,
SynchronizationManager, or AcquisitionNode explicitly when launching. Configuration
does not implicitly select which services run. Preserve independent long-lived
service operation; introduce neither separate packages per service nor an
orchestration framework. Exact executable names and CLI syntax are implementation
details, not fixed by illustrative commands in the Q022-A handoff.

---

## Decision 368: Installation uses separate deployment-local configuration files

**Status:** Accepted

Reuse Decision 076: actual machine/lab values, credentials, and private keys remain
outside Git. Committed templates and configuration definitions may be copied and
customized locally. General service configuration supplies NATS connection details,
service storage locations, StorageManager retrieval endpoints/authentication
references, and other machine-specific operational settings. It remains distinct
from AcquisitionNode hardware configuration. No configuration database, central
configuration-management service, or secret-management infrastructure is introduced.

The initial version is file-based. A future setup utility may produce the same
files, but runtime loading and validation use the same mechanism regardless of
file producer. No interactive installer is required. AcquisitionNode loads its
installation configuration at startup, supporting a default local location and
an explicit path. Installation-configuration changes require service restart;
live reload is not required. Session-specific operator parameters remain separate
and do not require node restart. Exact file format and default location are
implementation details unless they require architectural clarification.

---

## Decision 369: AcquisitionNode installation explicitly identifies devices and adapters

**Status:** Accepted

Each AcquisitionNode maintains persistent installation configuration identifying
its node identity, installed devices, explicitly selected adapter for each device,
device-specific physical connection settings, and local scientific storage
configuration. Preserve Decision 298's node authority over local storage roots;
Controller does not choose remote scientific-file paths. Neither automatic
hardware discovery nor a new adapter plugin system is required.

This is device-independent: the first camera deployment is an example, not the
general hardware contract. Other supported hardware and adapters may have
different connection/configuration requirements. Installation-only identity,
adapter selection, connection information, and fixed deployment settings remain
distinct from operator-adjustable Session settings.

---

## Decision 370: Adapters define Session-specific operator-adjustable parameters

**Status:** Accepted

Each DeviceAdapter defines which parameters are exposed for operator adjustment
and their applicable validation constraints, including allowed values or ranges
where appropriate. Use the existing AcquisitionNode inventory mechanism to
expose installed devices and these parameter definitions. Controller makes the
definitions available to a future GUI without hard-coded device-specific controls.

Operator selections use existing Session configuration mechanisms; the adapter
validates them before applying them. Preserve Decision 302: Session-specific
settings must not silently persist into subsequent Sessions. Installation-only
settings remain separate under Decisions 368-369. This accepts no GUI
implementation or universal camera-specific parameter set.

---

## Decision 371: Configuration validity and hardware readiness remain distinct

**Status:** Accepted

AcquisitionNode validates installation configuration at startup. Missing or invalid
configuration yields a clear diagnostic and prevents acquisition from proceeding.
Configured hardware that is unavailable or technically unready is reported using
existing ServiceReadiness, AcquisitionNodeReadiness, and related contracts.
Successful configuration loading does not establish hardware readiness. No new
readiness states or installation-certification system are introduced.

StorageManager validates its local retrieval configuration at startup; actual
node connectivity is checked when retrieval is requested. An offline node does
not prevent StorageManager startup. Preserve existing Session initialization,
reservation, cleanup, and safety requirements.

---

## Decision 372: Persistent node identities use explicit Controller registration

**Status:** Accepted

Assign each AcquisitionNode a persistent unique identity during installation.
Controller's deployment-local configuration contains an explicit list of known
AcquisitionNode identities. Register a node by adding its identity; Controller
must restart to load registered-node additions or changes. No live registration,
configuration reload, automatic lab-wide discovery, registration database, or
centralized service registry is required.

Duplicate AcquisitionNode identities are reported as conflicts; ambiguous identities
must not be used for Session launch until corrected. Coordinate infrequent
installation restarts between Experiments while preserving safeguards for ongoing
acquisition. Reuse Decisions 327-328 and 351-352: identity/readiness announcements
use existing NATS, and Controller requests current readiness/status from configured
known nodes at startup or restart. Historical announcements are evidence, not
current availability; unreachable nodes remain unknown, not automatically failed
or stopped. Controller restart must not automatically stop safely running node
acquisition. No heartbeat, periodic polling, or replacement reconciliation system
is introduced. Q022-A supplies deployment-local participants to existing mechanisms.

---

## Decision 373: SSH/SFTP setup and verified dummy retrieval are installation obligations

**Status:** Accepted

SSH/SFTP retrieval setup is mandatory when installing an AcquisitionNode, using
key-based authentication. StorageManager's deployment-local configuration maps
logical node identity to retrieval connection information such as host, username,
and private-key path. Credentials/private keys stay outside Git; endpoints and
authentication do not enter portable ArtifactManifests, compiled handoffs, or
scientific evidence, preserving Decision 247 and Q019 ownership.

Installation configures SSH/SFTP and StorageManager retrieval settings, verifies
connectivity, retrieves a small dummy file, and verifies that retrieved contents
match the source. A node is not fully installed until required retrieval setup
succeeds. This is an installation procedure, not a continuously enforced Session
reachability gate. Preserve Decision 371's offline-node startup distinction and
existing retrieval-time connectivity checks. Dummy-file matching does not add a
checksum or deep-verification policy for scientific artifacts.

---

## Decision 374: Manual installation verifies communication and recommends device tests

**Status:** Accepted

The initial documented manual installation procedure installs the common package,
creates applicable local service and node hardware configuration, configures and
tests SSH/SFTP, registers node identities, and verifies node NATS connectivity
and Controller-to-node readiness request/response through existing interfaces.
Separate installation communication tests between every pair of services are
unnecessary. Ingestor Session readiness and evidence acceptance retain their
existing initialization and Q019 completeness requirements; NATS connection alone
does not prove particular evidence acceptance.

Strongly recommend a capability-appropriate basic acquisition test for each newly
installed device: initialize/communicate, acquire representative data, inspect
output/local persistence where applicable, stop safely, release resources, and
record installation results. Initially these may be manual and device-specific.
They are not mandatory software-enforced prerequisites: no commissioning
certification, required test-status field, runtime gate based on documentation,
or universal acquisition-test interface is introduced. Actual failures remain
subject to ordinary readiness, initialization, and safety requirements. No GUI,
graphical installer, installation service, discovery, or unnecessary deployment
machinery is accepted. A future utility may automate the same file-based workflow.

**Q022-A implementation status (Decisions 367-374):** Accepted and synchronized.
Bounded common launching, remote maintenance and remaining independent launch paths
are closed in W061-W063. Deployment-local general-service configuration loading,
validation and startup integration for all five logical roles are independently
validated and audited PASS (W064, CLOSED), preserving separate node hardware and
Session configuration and the shared Ingestor/StorageManager process. File-based
shared-storage launching still requires explicit no external operational dependents;
actual dependents require existing maintenance callbacks. Explicit installation
dummy-file retrieval/content comparison is independently validated and audited PASS
(W065, CLOSED), using simulated SSH/SFTP. Explicit Controller-to-node installation
communication verification through existing NATS readiness requests is independently
validated and finally re-audited PASS (W066, CLOSED), without another Controller
owner or scientific lifecycle changes. Both partial-client ownership and interrupted
cleanup P2 findings are resolved; 17/17 communication and 11/11 connection tests
passed independent IPython runs. Controlled cleanup concurrency is not live NATS,
real-socket or normal Windows scheduling validation. Bounded manual runbook and
five configuration examples are independently validated (4/4 tests) and audited
PASS with no confirmed P0-P3 findings (W067, CLOSED). This does not establish
physical provisioning or full distributed deployment: shared-storage external-dependent
maintenance callback composition remains an explicit implementation obligation.
Parameter-definition exposure, actual deployment checks and remaining integration
remain outstanding; configuration validity is not readiness.
Q019 remains CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN. General framework
support remains separate from first-deployment/device-specific validation.

---

## Decision 375: Independently launched operational services communicate exclusively through NATS

**Status:** Accepted

**Subsequent revision:** Decision 376 supersedes the independent-process and
NATS-only communication requirements for the Ingestor-StorageManager pair.
The original accepted text and historical W051 validation below are preserved.

Controller, Ingestor, StorageManager, SynchronizationManager, and every
AcquisitionNode are independently launched services and may run on different
computers. All inter-service communication uses NATS. Direct Python-object
access between services was permitted during development and testing, but is not
the intended deployment architecture. Direct Python calls remain appropriate
within an individual service.

Each service remains the authoritative owner of its operations, state, locks,
evidence, and persistence responsibilities. Adapt all existing cross-service
interactions to NATS, including Controller-Ingestor-StorageManager receipt
verification, preservation, archival confirmation, and authorized recovery under
Q019 and its dependencies. Independently deployed services must not require
shared Python objects or silently instantiate additional service owners.

Requests require trustworthy confirmations. Failures, missing responses, and
timeouts never establish successful completion. Retries preserve existing
identity, durability, idempotency, and recovery protections. NATS publication,
durable Ingestor acceptance, independently verified acquisition receipt, and
StorageManager archival confirmation remain distinct under Decisions 276-280
and 356-366.

This resolves the Q022-A independent-service composition boundary and qualifies
Decision 304's historical process-neutral lifetime description for deployment,
without changing service ownership, responsibilities, or Session-independent
lifetime. No communication infrastructure beyond NATS, new lifecycle states,
weakened Q019 preservation/recovery guarantees, or implicit co-launching of other
roles is authorized.

**Implementation status:** The bounded Ingestor-StorageManager NATS persistence,
readback, journal-verified compilation, and W041 receipt foundation is complete
with independent manual validation and final independent re-audit PASS after the
malformed-correlation correction (W051). Full independent-service deployment
remains unimplemented and unvalidated. Existing NATS participant commands, evidence publication,
and readiness integration are reusable. Acquisition/Experiment and distributed
synchronization runtime integration is complete in W056. AcquisitionNode-to-Ingestor
durable operational evidence transport and exact journal-backed acceptance readback
are complete with independent validation and audit PASS in W057 (880b108), without
reintroducing scientific intake or conflating publication, acceptance, complete
receipt and archival preservation. Bounded Controller-driven single saved-Session
collection over NATS is complete with independent validation and final audit PASS
of d788d2e (W058), after three replay/result-correlation P2 corrections. Remote
collection reuses owner eligibility/persistence guards and verified durable outcomes;
it does not implement full closeout, remote enumeration/batch selection or closure.
Bounded explicit remote permanent Evidence Archive closure is separately complete
in W059 after independent validation and final focused audit PASS of 31b2c7e.
The cached-success history-validation P2 is resolved: complete scoped history and
current owner readback precede confirmation, without rewriting closed products.
This adds no Session termination or release authority. Corrective automated runtime
attempts stalled in the sandbox; no correction test passes are claimed.
Broader preservation, collection, release,
and maintenance/recovery still contain development-time
direct-object dependencies. Establish the required service-owned NATS interfaces
before enabling deployment launch paths that depend on them. Historical accepted
decisions and validated workflows remain preserved; Q019 remains CLOSED in W050,
while Q022, Q024, Phase 16, and M015 remain OPEN. Those earlier validations do not
establish fully independent-service deployment compliance with this decision.

---

## Decision 376: Ingestor and StorageManager share one deployment process

**Status:** Accepted

**Subsequent revision:** Decision 377 removes the acquisition-envelope delivery
identity/intake-journaling/retry requirement for routine scientific observations.
The shared-process topology and runtime-evidence guarantees remain unchanged.

Ingestor and StorageManager remain distinct software components with separate
responsibilities, state, locks, and persistence authority, but must execute on the
same computer within the same process. They share startup, shutdown, and restart
lifetime and restart together. Direct Python calls between these components are
permitted. This supersedes Decision 375's independently launched/separate-process
requirement for this pair and its requirement that their mutual communication use
NATS; it does not supersede their ownership or preservation responsibilities.

Controller, SynchronizationManager, and every AcquisitionNode remain independently
deployed. All communication crossing process boundaries uses NATS. Controller
accesses both Ingestor and StorageManager capabilities exclusively through NATS.
No new database, registry, infrastructure, or scientific-data ownership change is
introduced. Distinct component identities and authoritative operations remain;
a shared process does not merge their state or persistence authority.

W051 remains a historically validated NATS implementation. Durable accepted-envelope
persistence, stable persistence-command identity, retry idempotency/conflict
detection, restart-safe correlation, journal-before-acknowledgment, exact owner
readback, corruption rejection, legacy-record compatibility, and Q019 preservation,
recovery, and immutable-archive protections remain required. Reconciliation should
reuse existing local interfaces without unnecessary internal NATS messaging,
duplicate authoritative state, or independent lifecycles for the pair.

AcquisitionNode-to-Ingestor delivery remains a process-crossing NATS interaction:
stable envelope-delivery identity, durable intake correlation, journal-before-ACK,
and restart-safe deduplication must distinguish retries from separate identical
scientific observations. Intake acknowledgment, StorageManager persistence
confirmation, and archival completion are distinct; none substitutes for another.

**Implementation status:** Accepted and synchronized; shared-process composition
and acquisition-intake reconciliation are not yet implemented or independently
validated. W051 history remains unchanged. Q019 remains CLOSED; Q022, Q024,
Phase 16, and M015 remain OPEN.

---

## Decision 377: Routine scientific observations remain in local scientific storage

**Status:** Accepted

**Subsequent clarification:** Decision 378 requires clean replacement of obsolete
collection/scientific-envelope mechanisms, not indefinite legacy API compatibility.
Historical decisions, validated outcomes and necessary record interpretation remain.

Routine scientific observations and their per-observation metadata are preserved
through AcquisitionNode's co-located LocalStorageManager, regardless of size.
They no longer pass through Ingestor as AcquisitionRecordEnvelope messages.
Classify information by meaning, not size or existing code labels. AcquisitionNode
may inspect locally stored observations to generate operational evidence; only
the resulting operational evidence is delivered to Ingestor.

Responsibilities remain distinct:

- LocalStorageManager owns local observations, associated metadata, and scientific products.
- AcquisitionNode owns acquisition execution and operational evidence generation.
- Ingestor owns runtime evidence, manifest intake, intake audit, durable evidence
  recovery, and compilation, not scientific per-observation intake.
- SynchronizationManager owns authoritative scientific timing and synchronization.
- StorageManager owns global artifact collection, Session records, and evidence persistence.

Scientific products preserve existing observation/frame identity and ordering,
available acquisition timestamps and device-provided timestamps, Session,
Experiment, device and stream provenance, synchronization relationships,
authoritative timing evidence, artifact lifecycle/manifests, and offline
reconstruction. Decisions 154-158 and 178-186 remain applicable. No new
per-observation fields, persistence formats, components, or storage ownership are
introduced. Finalized scientific artifacts retain their existing protections.

This qualifies Decisions 042, 063, 071, and 073 by removing mandatory scientific
acquisition-envelope intake and corresponding per-observation Session Record
requirements. Related historical envelope descriptions in Decisions 059-064,
069 and 074 apply to their historical implementations, not a requirement to route
routine observations through Ingestor. Acquisition/device responsibilities and
applicable identities remain. Decision 376's envelope-delivery identity, durable
scientific-intake correlation/journaling and retry requirements no longer apply
to routine scientific observations. Its Ingestor-StorageManager shared-process
topology remains; all process-crossing communication still uses NATS.

Operational lifecycle and terminal evidence, acquisition health/failure reports,
timing/synchronization evidence and ArtifactManifests remain required through
existing lifecycle/runtime-evidence mechanisms, with existing owners and producer
persistence intent. Current node `session_start`/`session_stop` events and health
observations carried by acquisition envelopes must not be lost when adapting that
path; preserve their operational meaning through those existing mechanisms, not
scientific-observation envelopes. No new evidence categories are defined.
Decisions 219-225, 240-244 and 276-280 remain authoritative for runtime-evidence
acceptance, journal-before-ACK, identity/deduplication, restart reconstruction,
intake audit, manifest handoff and persistent compilation.

Q019 Decisions 356-366's producer confirmations, verified receipt, Stage A/B,
durable handoff, Normal Stop/Kill, release, recovery and permanent closure
guarantees remain. Acquisition-evidence completeness concerns required operational
evidence and manifests, not transport of routine scientific observations.
Historical envelopes/audits in already preserved Session Records and archives
must not be deleted or rewritten by this revision.

W051/W052 remain historically validated implementations. Their scientific-envelope
persistence path is no longer required for routine acquisition, but applicable
durability, identity, corruption rejection, readback and archival protections
remain required for active responsibilities. Historical decisions, numbering and
validation/audit results are preserved; obsolete code is not claimed removed.

**Implementation status:** Bounded product-based node acquisition and operational
evidence preservation (Slice 3A) are complete, independently manually validated
and re-audited PASS after correction (W053). The initial audit FAIL identified
lost later-device scientific observations after operational intake failed; the
correction attempts preservation across completed collections before operational
handling and retains independent failure reporting without replay. Owner-level
envelope removal and operational Session Record/closeout reconciliation are
complete with independent manual validation and corrective re-audit PASS after
the P2 release-race and P3 obsolete-fixture corrections (W054). The combined
Decision 377-378 implementation is complete and accepted in W055: independent
functional integration PASS (26 selected tests and four probes), followed by
correction of the sole clean-replacement P3 and nine targeted tests PASS. The user
and ICC explicitly determined that no further independent re-audit was required
for that test-only cleanup; no post-correction re-audit PASS is claimed.
Future real-time scientific streaming remains an open architectural question;
no transport or infrastructure is selected.
Q019 remains CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 378: Declared and selected scientific products replace legacy collection

**Status:** Accepted

Device installation declares the scientific products a device supports. Experiment
configuration explicitly selects which registered products will be recorded.
Those declarations and selections are authoritative for scientific acquisition
and LocalStorageManager persistence, reusing Decisions 208-210 and 235-236.
DeviceAdapters must explicitly support their declared scientific products and
distinguish scientific observations and associated metadata from operational
evidence. AcquisitionNode must not infer scientific meaning from content, size,
or legacy naming. This clarifies Decision 377's meaning-based boundary without
introducing a new component, scientific format or streaming infrastructure.

The target contract is:

```text
Installation declares supported scientific products
    -> Experiment explicitly selects registered products
    -> DeviceAdapter produces those scientific observations/metadata
    -> AcquisitionNode coordinates LocalStorageManager persistence

DeviceAdapter/AcquisitionNode operational evidence
    -> existing runtime-evidence mechanisms -> Ingestor
```

Implementation must cleanly replace legacy `collect_records()` /
`collect_scientific_records()` contracts and routine scientific-envelope delivery
from AcquisitionNode to Ingestor. Remove superseded scientific-envelope
persistence, auditing, recovery and compatibility machinery, dead functions,
unused types, redundant tests and obsolete documentation where they no longer
serve an accepted responsibility. W051/W052 are historical validated outcomes,
not justification to retain superseded architecture. Interfaces/records still
needed for operational evidence, historical record interpretation or other
authoritative responsibilities remain; this is not authorization to delete or
rewrite preserved scientific artifacts, journals, Session Records or archives.

Preserve observation identity/order, timestamps, Session/Experiment/device/stream
provenance, local persistence, global collection and offline reconstruction.
Preserve operational lifecycle/terminal events, acquisition health/failures,
synchronization evidence and ArtifactManifests with their existing owners.
RuntimeEvidenceMessage identity, producer persistence intent, journal-before-ACK,
deduplication, reconstruction and compilation remain authoritative. Q019 evidence
completeness, Normal Stop, Kill, Stage A/B, authorized recovery and permanent
archive immutability must survive the replacement. Decision 376's shared-process
topology and NATS across process boundaries remain unchanged.

**Required integration audit:** After replacement, independent final integration
audit must verify both functional preservation of these scientific, operational
and Q019 guarantees and absence of obsolete scientific-envelope architecture.
Passing replacement tests alone does not establish closure.

**Implementation status:** Slice 3A is complete with independent manual validation
and final re-audit PASS after correction (W053). Installed/selected product-based
adapter/manager/node acquisition replaces legacy collection in the active node
path, with local scientific persistence and separate operational evidence.
Slice 3B owner-level scientific-envelope removal and closeout reconciliation are
complete with independent manual validation and corrective re-audit PASS after
the P2 release-race and P3 obsolete-fixture corrections (W054), retaining required
historical interpretation and Q019 protections. The combined Decision 377-378
replacement is implemented and accepted in W055. The independent combined audit
passed functional integration but initially failed clean replacement for one P3:
unused HealthFakeAdapter record_kind configuration. Its removal passed nine
targeted tests; the user and ICC accepted targeted verification without a further
independent re-audit for this narrowly scoped test-only correction. The initial
audit result is preserved, not restated as a post-correction audit PASS. Historical
decision numbering and W051/W052 records remain unchanged. Future real-time
scientific streaming remains architecturally open. Q019 remains CLOSED;
Q022, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 379: Cross-clock measurement establishes node-specific mapping validity

**Status:** Accepted

SynchronizationManager establishes node-specific mappings using sufficient
measured cross-clock exchanges, accounting for network delay, variability and
uncertainty. Initial mappings may use an explicit, conservatively bounded
clock-rate assumption without prior drift estimation. Clocks on different
computers must not be assumed synchronized.

Periodic synchronization-quality checks are distinct from complete
resynchronization. SynchronizationManager alone determines mapping validity,
refinement and replacement. Cadence and quality thresholds remain configurable;
this decision invents no accuracy thresholds or additional acceptance criteria.

Reuse existing NATS communication, synchronization schemas and evidence pathways.
Q006/Q018 remain open for advanced drift estimation, measurement algorithms,
hardware synchronization and offline refinement, except for the minimum
demonstrably valid measurement method required by the current implementation.

**Implementation status:** Implemented in Q022 Slice 2, independently manually
validated and finally audited PASS (W056, commit 3e573f5), including periodic
publication recovery and command-admission corrections. This is bounded local
JetStream/software validation, not multi-host accuracy, hardware timing or
power-loss verification. W001-W055 remain historical records. Q019 remains CLOSED;
Q006/Q018, Q022, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 380: AcquisitionNode applies authorized affine mappings with preserved provenance

**Status:** Accepted

AcquisitionNode applies the SynchronizationManager-authorized affine mapping
locally:

```text
session_time = session_anchor + scale * (node_local_time - local_anchor)
```

The existing SynchronizationMapping fields `session_time_anchor_s`,
`local_time_anchor_s` and `scale` supply those mapping values. Experiment Time
derives from Session Time and the Experiment start Session Time (Decision 151).
Mapping changes apply atomically and prospectively; already timestamped runtime
records are not rewritten. SynchronizationManager retains mapping authority;
local application does not create another clock authority.

Preserve the existing required Session, Experiment, AcquisitionNode-local,
available device-native and timestamp-quality information with scientific
observations and artifacts, consistent with Decisions 153-158, 164-165 and 179.
Preserve mapping history and the AcquisitionNode-local activation boundary of
each mapping, enabling reconstruction without requiring a mapping ID on every
observation. Reuse existing scientific-storage and evidence contracts; scientific
observations and their per-observation metadata remain AcquisitionNode-local
under Decisions 377-378.

**Implementation status:** Local affine application, activation provenance and
acquisition-time quality history are implemented, independently validated and
finally audited PASS in W056. Buffered observations retain historical quality
through degradation, recovery, reassessment and mapping expiry/replacement;
persisted scientific records are not rewritten. W053-W055 outcomes are unchanged.
Q019 remains CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 381: Synchronization readiness and degraded timing use existing policy authority

**Status:** Accepted

Require acceptable synchronization at Session acquisition readiness and before
each Experiment. Perform configurable periodic synchronization-quality
assessments. These assessments do not inherently require complete
resynchronization (Decision 379).

Temporary synchronization degradation does not automatically terminate
acquisition. Preserve local timing, applicable mapping provenance and explicit
degraded timestamp status. Existing TimingQualityPolicy interpretation and
Controller authority determine operational consequences; this decision adds no
lifecycle states or fixed timing-quality thresholds.

Never substitute NATS arrival times for scientific Session Time or assume clocks
on different computers are synchronized. Use local authorized mapping application,
not per-observation network timestamp requests. Reuse existing NATS communication,
synchronization schemas, evidence pathways and scientific storage. No additional
service, clock authority or legacy compatibility machinery is introduced.

Together, Decisions 379-381 resolve the minimum distributed scientific
synchronization architecture gate for Q022 Slice 2. Q006/Q018 retain their
advanced scope as qualified by Decision 379; these open questions do not defer
the minimum demonstrably valid measurement method required for implementation.

**Implementation status:** Readiness, periodic assessment and degraded scientific
timing are implemented and independently validated, with final audit PASS in
W056 after all three P2 corrections. That record preserves earlier failed audits,
overlapping verification runs and validation limitations. Advanced Q006/Q018
scope remains OPEN. Q019 remains CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.
W001-W055 are unchanged.

---

## Decision 382: Finalized acquisition intake and verified Stage A establish distributed preservation eligibility

**Status:** Accepted

The existing acquisition-evidence completion marker is the last-call boundary
for Normal Stop. Controller obtains the required producer-publication
confirmations and publishes the Session-scoped marker. Ingestor independently
verifies complete durable acceptance through that marker, including contiguous
JetStream receipt and journal consistency. A marker alone is insufficient: the
full required publication interval must first be proven complete under the
existing receipt contracts.

Ingestor establishes the authoritative final acquisition-intake boundary. Once
finalized, subsequent acquisition-evidence deliveries for that Session, including
duplicates, are rejected or discarded without modifying finalized Stage A
evidence, intake audit or final Session Record. This qualifies the mutable-intake
coverage assumptions of the earlier closeout implementation; it does not weaken
the completeness proof required before finalization.

StorageManager durably preserves and verifies the corresponding complete Stage A
products: acquisition evidence, intake audit, final Session Record and applicable
artifact handoff, with existing summary/provenance and preservation checks.
Finalized intake together with verified Stage A preservation establishes
authoritative acquisition-preservation eligibility. Controller retains exclusive
Session lifecycle authority. Completion additionally requires all existing
lifecycle, cleanup and safety obligations; neither Ingestor nor StorageManager
independently transitions the Session to `completed`.

Reuse existing NATS/JetStream reliability mechanisms. Publication or delivery
acknowledgment alone does not prove Stage A preservation. Controller requires an
authoritative, correctly correlated preservation result. Missing, delayed,
duplicated, cancelled or superseded confirmations cannot authorize an
inappropriate lifecycle transition. No separate messaging-reliability subsystem
or distributed transaction coordinator is introduced.

Preservation eligibility remains independently verifiable after Controller or
Ingestor/StorageManager restart, using existing durable Session products,
journals and accepted recovery/readback mechanisms. Do not rewrite finalized
acquisition evidence or unnecessarily repeat previously confirmed Stage A
preservation. If eligibility cannot be established, completion remains unconfirmed.

Decision 313 remains unchanged: each operational service independently releases
its Session binding only after its own cleanup, preservation and safety
obligations are satisfied. Stage A preservation alone establishes neither
hardware safety, cleanup completion nor remote resource-release eligibility.
Preserve Normal Stop versus Kill, including partial Kill preservation and its
accepted recovery protections, and Stage A versus later Stage B collection and
separate explicit permanent Evidence Archive closure. This decision does not
turn partial Kill preservation into complete Normal Stop receipt.

This clarifies Decisions 313, 357-365 and 375-376 without changing component
ownership, adding Session states, a Session registry, another Evidence Archive
or new infrastructure. The Ingestor/StorageManager shared-process topology and
NATS across process boundaries remain unchanged. No new message schema or
implementation-specific finalization mechanism is specified here.

**Implementation status:** Accepted and synchronized, not yet implemented or
independently validated. This resolves the distributed acquisition-preservation
boundary question identified before cross-process Session closeout implementation;
the implementation must preserve the remaining lifecycle/release requirements.
Q019 and W001-W059 remain CLOSED with historical outcomes unchanged. Q022,
Q006, Q018, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 383: One common manual CLI reuses service launch and maintenance interfaces

**Status:** Accepted

One common framework CLI launches and administers Controller, AcquisitionNode,
Ingestor, StorageManager and SynchronizationManager using their existing
initialization, communication, readiness and maintenance interfaces. It does not
create separate service implementations or provision configuration.

Independent service operation remains governed by Decisions 295, 304 and 321.
Decision 376's shared Ingestor/StorageManager process and lifetime remain unchanged;
the CLI does not split that pair or implicitly launch other independent roles.
All process-crossing communication remains NATS-based. This accepts manual entry
points, not supervision, automatic restart, discovery or NATS process management.

**Implementation status:** Bounded common launcher and shared-process
Ingestor/StorageManager launching are independently validated and re-audited PASS
after correction (W061, CLOSED). The other three role paths with service-specific
remote preservation and node installation loading are independently validated
(IPython 60/60) and independently audited PASS with no confirmed P0-P3 findings
(W063, CLOSED);
addressed remote maintenance is independently validated and re-audited PASS
after the feedback correction (W062, CLOSED). Deployment-local service-file loading
and startup integration are independently validated and audited PASS (W064, CLOSED).
The bounded manual installation runbook/examples are independently validated and
audited PASS (W067, CLOSED); W065/W066 separately close retrieval/communication
verification tooling. Actual provisioning, live deployment verification and
shared-storage external-dependent maintenance callback composition remain
outstanding under Q022. The isolated-only declaration must not bypass actual
dependency obligations.

---

## Decision 384: Ctrl+C requests local maintenance Stop without forced process exit

**Status:** Accepted

Ctrl+C invokes the running service's existing maintenance Stop locally. Confirmed
completion permits normal exit subject to Decision 386. A blocked Stop triggers
automatic Cancel; the launcher reports that outcome and keeps the process running.
Failed or unconfirmed Stop must not silently terminate the process.

There is no interactive Kill prompt or repeated-Ctrl+C forced termination. Reuse
the existing maintenance attempt and cleanup/evidence obligations; Ctrl+C is not
Session Normal Stop, Kill Session or Controller-coordinated framework shutdown.

**Implementation status:** Bounded local Stop/Cancel and protected startup are
implemented, independently validated and re-audited PASS (W061, CLOSED).

---

## Decision 385: Separate terminals address service maintenance directly over NATS

**Status:** Accepted

A separate terminal may issue Stop, explicitly authorized Kill and Cancel directly
to an identified service using existing NATS commands and maintenance identities,
independently of Controller. Kill continues the same blocked stop attempt. Cancel
ends that attempt without force. Existing authorization, cleanup, evidence and
retirement protections remain mandatory.

This does not introduce Controller-dependent administrative maintenance, a new
network protocol, service discovery or a parallel command-processing mechanism.
It does not change Session/Experiment lifecycle authority or framework shutdown.

**Implementation status:** Addressed remote Stop/authorized Kill/Cancel CLI is
implemented, independently validated and focused re-audited PASS (W062, CLOSED).
It adds no role launch paths or Controller dependency and preserves existing
Cancel outcomes and shared-process ownership.

---

## Decision 386: Launcher exit follows confirmed maintenance and final result handling

**Status:** Accepted

OS process exit is distinct from service operational retirement. The launcher
exits only after confirmed completed maintenance and required final command-result
publication/handling. Blocked, failed and unconfirmed outcomes must not be mistaken
for successful process termination. This does not require a service to confirm
its own death after exit.

Existing maintenance/shutdown contracts, including Decisions 305-321 and 324-328,
remain authoritative. Decision 313 independent Session-binding release and
Decision 382 preservation eligibility do not by themselves authorize process exit.
No new lifecycle state, supervision service or evidence store is introduced.

**Implementation status:** Bounded launcher exit gating is independently validated
and re-audited PASS (W061, CLOSED), including exact published-and-acknowledged
request/result identity after correction. This does not claim requester receipt.

---

## Decision 387: Manual CLI reuses maintenance identities without adding authentication

**Status:** Accepted

Reuse existing command IDs, stop-attempt IDs and RuntimeParticipant identities.
Generate a temporary requester ID for each terminal invocation. Use the OS username
for local Ctrl+C administrator identity; require explicit administrator identity
for remote commands. Identity recording is not a new authentication system and
does not replace existing explicit Kill authorization.

**Implementation status:** Local launcher identities are implemented and validated
in W061 (CLOSED). Explicit remote administrator and temporary requester identities
are implemented and independently validated in W062 (CLOSED), without new
authentication infrastructure.

---

## Decision 388: Terminal feedback reports existing outcomes and confirmed success only

**Status:** Accepted

Terminal feedback distinguishes confirmed completion, blocked, failed, rejected
and unconfirmed results without introducing framework outcome states. Exit code 0
is reserved for confirmed successful terminal commands; otherwise use nonzero.
Report target identity, attempt ID, blockers, errors, unresolved obligations and
necessary operator action. Missing responses or publication alone cannot be
reported as confirmed completion or successful process termination.

Decisions 383-388 accept the Manual Service Entry Points handoff without resolving
Q022 configuration provisioning, Q024 recovery or unrelated open questions. Q019
and W001-W060 remain CLOSED; Q022, Q006, Q018, Q024, Phase 16 and M015 remain OPEN.

**Implementation status:** Bounded launcher feedback and confirmed-success exit
handling are independently validated and re-audited PASS (W061, CLOSED). Remote
CLI feedback and exit statuses are independently validated and focused re-audited
PASS after the interrupted-Kill feedback P3 correction (W062, CLOSED).
Unsupported role launch paths and full deployment remain outside these closures.

---

## Decision 389: External-dependent retirement confirmation

**Status:** Accepted

This records the user-approved LLC clarification "External-Dependent Retirement
Confirmation" for W068. It supplements Decisions 316, 324-326, 375-376 and
383-388 without rewriting their historical requirements or changing service
ownership, individual maintenance semantics or coordinated shutdown order.

### Authority and communication

Ingestor removes a configured external-dependent blocker only after confirmed
operational retirement of that dependent, or Controller's specifically authorized
dependency release during coordinated shutdown. Each service owns its retirement
and dependency-release conditions. Ingestor consumes authoritative confirmation;
it does not become another service's retirement authority.

Reuse existing NATS maintenance commands, results, RuntimeParticipant identities
and request/result correlation. Retirement confirmation must be delivered and
available to Ingestor before the dependent launcher exits. Publication
acknowledgment alone does not establish that requirement. Preserve Decision 324's
initiating-interface authority for determining actual final outcomes, and
Decision 386's distinction between operational retirement and OS process exit.

### Instance scope, freshness and failure behavior

Confirmations identify the dependent RuntimeParticipant, operational instance,
maintenance attempt and final outcome. A prior-instance confirmation cannot
authorize removal of a blocker after that service restarts. Handle duplicates
and retries safely without allowing contradictory results to authorize release.

Missing, stale, contradictory, incorrectly correlated or unavailable confirmation
retains the blocker. Timeout, readiness failure, disappearance, preparation alone
and publication acknowledgment are insufficient. Do not infer completed retirement
or dependency release from technical unreadiness or lack of a current response.

### Prepared Controller

Controller remains operational after `prepare_stop`. Its specifically authorized
dependency release during coordinated shutdown requires explicit confirmation
that all required Ingestor-dependent obligations are durably preserved, the final
archival checkpoint has been reached, and no further Ingestor-dependent work will
be created. Preparation alone does not establish these conditions.

This releases only the dependency; it does not establish Controller retirement.
Preserve Decision 326's preparation, final archival boundary and operational
retirement ordering, including Controller retiring last. No anticipated retirement
may be represented as completed.

### Implementation discretion and boundaries

Implementation may select minimal representations and correlation extensions
consistent with these existing contracts. This clarification does not prescribe
a new message schema, identifier encoding or independent evidence store.

Preserve existing Stop, explicitly authorized Kill and Cancel semantics. No new
supervisor, registry, independent lifecycle authority, automatic restart, rollback
or parallel retirement-evidence subsystem is introduced. Decision 376's shared
Ingestor/StorageManager process and distinct ownership remain unchanged.

**Implementation status:** Accepted and synchronized; this resolves W068's
external-dependent confirmation architecture blocker. Callback composition,
instance-correlated confirmation delivery and launcher-exit integration remain
unimplemented and unvalidated in W068. W068 and Q022 remain OPEN; Q019 and
W001-W067 remain CLOSED. Q006/Q018, Q024, Phase 16 and M015 remain OPEN.

---

## Decision 390: Ordinary framework archive continuation after restart

**Status:** Accepted

This records the user-approved LLC clarification for W068. It supplements
Decisions 323, 376 and 389 while preserving the interrupted-write recovery
requirements of Decisions 339, 342 and 347.

### Ordinary continuation and verification

Ordinary restart with an intact historical framework Evidence Archive and newly
accepted Ingestor recovery evidence is normal archival continuation, not
automatically interrupted-write recovery.

Ingestor reconstructs its authoritative journal and compilation. StorageManager
verifies that the existing durable archive is intact, internally consistent, and
an exact valid historical prefix of the recovered authoritative evidence and
applicable intake audit. Historical confirmation alone is insufficient.

After successful prefix verification, existing compilation and archival mechanisms
may preserve additional accepted recovery evidence. StorageManager must verify
the complete current compilation before confirming preservation.

### Startup and dependent-release restoration

Integrate reconciliation into ordinary startup before restoring eligible
dependent-release state. Ingestor and StorageManager retain their authoritative
responsibilities and Decision 376's shared-process deployment requirements.

W068 may reconsider previously confirmed external-dependent releases only after
current archival confirmation. All Decision 389 identity, operational-instance,
maintenance-attempt, freshness, contradiction and supersession requirements remain
mandatory; archival continuation does not independently establish release.

### Failure behavior and boundaries

Missing, inconsistent, unverifiable or corrupted history, failed continuation, or
unavailable current confirmation retains the dependency blocker. Never infer
success, overwrite conflicting evidence, truncate the journal, or silently invoke
interrupted-write repair.

Actual interrupted-write recovery remains governed by Decisions 339, 342 and 347,
including applicable administrator authorization. No new recovery manager,
evidence subsystem, supervisor or lifecycle authority is authorized.

**Implementation status:** Accepted and synchronized; ordinary-startup prefix
verification and continuation integration remain to be implemented and validated
in W068. W068 and Q022 remain OPEN; existing closed workflow and question statuses
are unchanged.

---

## Decision 391: Best-effort Controller restart and bounded Session reconnection

**Status:** Accepted

This records the user-approved Q024 clarification of Decisions 345, 346, 351 and
352. It preserves their historical reconciliation, timing and reservation
contracts while defining the bounds for experimenter-requested reconnection.

### Priorities and restart reconciliation

Recovery is best-effort. Scientific integrity, operational safety and simplicity
take priority over recovering an interrupted Session. Controller restart uses
existing participant status, readiness, reservation and durable evidence
mechanisms. Controller must not automatically stop AcquisitionNodes that continue
recording safely. Read-only reconciliation remains distinct from operational
reconnection; complete historical replay or event-by-event Controller
reconstruction is not required.

### Bounded experimenter-requested reconnection

Reconnection to the original Session is permitted only at the experimenter's
request and only when Controller can automatically establish operational safety
and scientific validity. The experimenter may decline reconnection but cannot
override failed safety requirements. Existing authorization and service-owned
safety/release conditions remain applicable; a reconnection request does not
authorize unrelated recovery actions.

Partial reconnection is permitted only for operations proven safe without
unreachable participants. Their identities and obligations remain unresolved;
absence of a response does not establish safety or completion.

Preserve the original Session identity, scientific recordings and timestamps.
Document supervision gaps and timing uncertainty through existing evidence
mechanisms, retaining SynchronizationManager authority and historical timing
protections under Decision 346. Reconnection does not justify rewriting timestamps
or inventing missing scientific or operational history.

### Safe fallback and scope limits

When safe reconnection cannot be established simply, prefer existing safe
termination/abort and partial-data preservation mechanisms under their existing
authorization and safety conditions. This is not permission to automatically stop
safely recording nodes. Abandonment does not imply deletion of recordings or
release of unconfirmed resources.

No elaborate recovery subsystem, new registry, extensive event replay or
substantial new infrastructure is authorized solely for rare reconnection
scenarios. This clarification does not implement operational reconnection or
change existing lifecycle or service ownership.

**Implementation status:** Accepted and synchronized only. Bounded operational
Session reconnection is not implemented, tested or validated. Q024 remains OPEN;
existing accepted decisions and completed workflow records remain unchanged.

---

## Decision 392: Ingestor durably enforces closed Session admission

**Status:** Accepted

Once a Session is authoritatively finalized and released, Ingestor permanently
rejects subsequent ingestion, preparation and reopening of that Session identity.
Ingestor owns independently durable closed-Session records, which may reside
alongside deployment-local recovery journals and must survive process and
deployment restarts independently of those temporary journals. Journal retirement
must never delete closed-Session records.

Establish durable closure before relinquishing the Session binding, retaining
existing preservation, terminal-state, journal-integrity and release-safety
requirements. If closure status cannot be reliably determined, affected operations
fail closed. StorageManager remains authoritative for preservation confirmation,
not closed-Session admission.

W070A is bounded to this admission protection; it does not authorize temporary
journal deletion, terminal deletion, Controller reconnection, new Session states,
or Decisions 353-355 cleanup. Existing accepted architecture remains unchanged.
Independent validation and audit are required before implementation closure.

**Implementation status:** W070A is CLOSED after correction of P2 W070A-A1's
cross-instance admission/publication race, 60 distinct implementation checks PASS,
independent manual IPython validation 16/16 PASS and final independent source audit
PASS with no remaining confirmed P0-P3 findings. Scope, historical audit sequence
and verification limitations are recorded in W070A in validated_workflows.md.
W070B / Decision 349 implementation is tracked under Decision 393. Q024 remains OPEN,
and Decision 391 operational reconnection remains deferred.

---

## Decision 393: W070B closeout verification and journal retirement

**Status:** Accepted

Post-release closeout verification must remain available independently of temporary
Ingestor recovery journals. Reuse the permanent Session Evidence Archive,
compilation summary, final Session Record, artifact collection handoff and current
StorageManager preservation confirmation. Extend the existing compilation summary
only for finality/receipt provenance unavailable from those permanent products;
do not create another persistent closeout record or duplicate evidence/audit files.

Preserve permanent runtime evidence and complete intake-audit coverage,
authoritative finalization receipt provenance, terminal Session state, preservation
consistency, existing Controller response semantics and the distinction between
normal finalization and partial Kill. The original complete accepted-message-ID
list, including nonpersistent identities, need not be reconstructed solely for
historical deduplication after closure. Existing `kill_preservation` evidence may
support partial-Kill verification only where it authoritatively establishes the
required state. Missing, corrupt, incomplete or conflicting proof fails closed.

Ingestor may retire only an identified eligible temporary Session journal after
confirming terminal closure, completed Ingestor binding release, current durable
StorageManager preservation, applicable normal-finalization or partial-Kill proof,
successful journal-independent closeout verification, and no remaining journal
requirement for crash reconstruction or deduplication. Decision 392's independently
durable closed-Session rejection remains mandatory. Establish journal-independent
verification before enabling retirement, and preserve safe retry/reconciliation
after interruption around deletion without claiming unverifiable success.

Uncertainty retains journals. Closed-Session records, framework evidence,
scientific artifacts, Evidence Archives and Session Records are not retirement
targets. No age-based expiry, automatic rotation, abandonment-based deletion or
Decision 350 terminal-loss policy change is authorized. Decisions 276-280 and 349,
existing ownership and Controller closeout guarantees remain authoritative. No new
service, database, generic cleanup framework, Controller reconnection or Decisions
353-355 cleanup is authorized.

**Implementation status:** W070B implements permanent post-release closeout
readback and guarded retirement of identified canonical Session journals. Gate A
passed before retirement was enabled; final focused verification passed 11 Gate A
checks, 20 Gate B checks and 38 affected existing checks (distinct, not additive
to earlier overlapping runs). Three existing hard-link integration checks were
blocked by Windows sandbox permissions and are not claimed as passing.
W070B is CLOSED following independent ICC IPython validation (9/9 probes PASS)
and independent source audit PASS with no confirmed P0-P3 findings. No live NATS
or physical power-loss testing is claimed; controlled asynchronous checks are
not a normal Windows scheduling campaign. See W070B in validated_workflows.md.
Q024 remains OPEN for outstanding recovery obligations; W070A remains CLOSED.
Historical normal archives without permanent receipt
provenance retain their journal-based verification and are not retirement-eligible.

---

## Decision 394: Configured Experiment duration and per-Experiment storage capacity readiness

**Status:** Accepted

Every Experiment has a configured duration established before it begins. That
duration determines automatic Experiment termination under the existing accepted
lifecycle architecture and defines the recording time horizon for storage-capacity
estimation. Runtime duration extension is deferred. No competing Experiment
lifecycle authority is introduced.

Device installation/declaration and Experiment-specific operating configuration
are distinct. Devices provide supported capabilities and relevant scientific
storage characteristics; Experiments select operating parameters such as
acquisition rate and resolution. Reuse existing scientific-product declarations
and configuration contracts. Estimate capacity from the selected configuration,
configured duration and actual scientific storage representation, without invented
frame rates, dimensions, compression ratios, overhead percentages or safety margins.
When a defensible estimate cannot be calculated, an explicitly configured
authoritative byte budget is permitted. Existing meanings of
`expected_data_size_bytes` and related fields are not silently reinterpreted.

Capacity readiness is checked before each Experiment, not merely once per Session.
Experiments may select different devices, configurations, durations and scientific
outputs. Checks cover destinations where that Experiment's scientific data and
required preservation products will be written, correctly accounting for shared
filesystems. Insufficient or indeterminate required capacity cannot establish
successful readiness. Existing LocalStorageManager, StorageManager, readiness,
preservation and lifecycle ownership remain authoritative. This applies equally
to GUI-driven and headless Controller operation and clarifies Decisions 045, 208,
217 and 235-237 without replacing them.

The future GUI must clearly warn the experimenter before Experiment start when
available storage is insufficient for its configured requirements. Where known,
show the affected destination, required capacity and available capacity. The GUI
uses authoritative framework readiness and cannot bypass failed capacity readiness.
This requirement is recorded in `gui_design_notes.md`; GUI implementation remains
outside this repository.

**Implementation history:** Initial inspection found no configured-duration
automatic Experiment termination mechanism to reuse; implementation waited for
the expiry execution/delegation clarification accepted in Decision 395.

**Implementation status (G2 CLOSED; bounded software scope):** Per-Experiment
capacity readiness and duration expiry are implemented, independently validated
by ICC and finally audited PASS by separate Codex review with no remaining
confirmed P0-P3 findings. See [G2 closure](validated_workflows.md#g2---experiment-capacity-preflight-and-autonomous-duration-expiry)
for correction history and limitations. No live deployment/hardware validation is
claimed. G3 remains CLOSED; Q022, Q024, M015 and Phase 16 remain OPEN.

---

## Decision 395: Common Experiment deadlines are enforced autonomously by AcquisitionNodes

**Status:** Accepted

Every Experiment has a duration configured before start; it governs both expiry
and the storage-estimation horizon under Decision 394. Runtime duration extension
remains deferred. Duration is measured from one common Experiment start time, not
each node's recording activation. SynchronizationManager supplies the accepted
mappings, and required synchronization readiness must pass before start.

Each participating AcquisitionNode translates the common Experiment deadline to
its local monotonic clock using the accepted mapping. It autonomously ends the
affected Experiment's acquisition at expiry, finalizes its local scientific
products and evidence, and preserves duration-expiry evidence. Controller
disconnection does not disable expiry. Once a valid deadline is established,
temporary synchronization communication loss does not independently disable it.
This adds neither a new synchronization authority nor a timing tolerance.

Controller retains canonical Experiment and Session lifecycle ownership and
reconciles valid expiry evidence through existing lifecycle/evidence mechanisms,
including delayed delivery after disconnection. Expiry ends the Experiment, not
the Session. Preserve G3 autonomous execution and existing Stop/Kill/Cancel,
acquisition-failure, finalization and preservation contracts; no competing
lifecycle authority or general recovery framework is introduced.

Capacity is checked independently before each Experiment using configured
duration, selected scientific outputs, device operating parameters, actual stored
representation and required recording/preservation destinations. Shared
filesystems must be accounted for correctly. Explicit authoritative byte budgets
are permitted when defensible estimation is unavailable. Insufficient or
indeterminate capacity prevents readiness; existing declaration meanings remain
unchanged. Decision 394 and its future GUI warning remain authoritative.

**Implementation status:** Accepted and synchronized before G2 implementation.
This resolves the expiry execution/delegation prerequisite reported during
Decision 394 inspection; it does not claim an older timer implementation existed.
G2 is now CLOSED within its validated software scope after ICC independent
validation and final separate Codex audit PASS, following the documented P2
corrections. Runtime duration extension remains deferred.
Q022, Q024, M015 and Phase 16 remain OPEN; G3 closure is unchanged.

**Bounded G2 implementation update:** ExperimentConfiguration carries duration,
node operating overrides and explicit recording/preservation budgets. Existing
storage readiness checks capacity before each Experiment; nodes capture the
authorized local deadline, finalize independently and retain expiry evidence.
Controller reconciles exact expiry evidence without ending the Session. Declared
encoded-size bounds support estimation where available; otherwise explicit
budgets are required. Independent validation/audit and implementation verification
remain distinct evidence; see [G2 closure](validated_workflows.md#g2---experiment-capacity-preflight-and-autonomous-duration-expiry)
and installation_and_deployment.md. This closure does not establish live NATS,
hardware, OS-signal, power-loss or normal Windows asynchronous scheduling behavior.

---

## Decision 396: The GUI is a general-purpose framework client accessible from the microscope workstation

**Status:** Accepted

The experimenter must be able to operate the complete scientific workflow from
the microscope workstation. Browser-accessible deployment is preferred; the GUI
application/backend and central services may execute elsewhere. AcquisitionNode
and scientific processing execute where the relevant data and hardware are
available, typically the microscope computer for CaBMI.

The GUI owns interaction, not framework lifecycle, synchronization, acquisition,
or persistence authority. Framework operation is GUI-independent. Time-critical
scientific execution must not depend on browser responsiveness, GUI connectivity,
Controller round trips, or NATS latency. Different laboratories may use different
GUIs and protocols; a CaBMI-specific GUI is not mandatory.

This extends Decisions 001-002 while preserving Decisions 019 and 021: GUI code
and scientific analysis pipelines remain outside the core repository. Recording
framework integration requirements does not authorize their implementation.

---

## Decision 397: One animal's Session may contain Experiments and Analyses

**Status:** Accepted

One framework Session corresponds to one animal. It may contain multiple
Experiments and Analyses, Validation, and operator interactions. A laboratory day
may contain multiple Sessions and experimenters. After closing one animal's
Session, another must be preparable without restarting the GUI or framework
services. Existing Session closure, resource reuse, evidence preservation, and
artifact collection contracts remain authoritative.

Experimenter, project, and template context may persist between Sessions, but
each Session retains its own identity and authoritative records. Detailed metadata
ownership remains unresolved under Q008.

This broadens Decisions 092-096's conceptual Session contents without classifying
Analysis as Experiment or Validation. Controller's canonical Experiment lifecycle
authority is unchanged; service lifetimes remain independent under Decision 304.

---

## Decision 398: Services, Setup, and Experiment or Run are conceptual GUI areas

**Status:** Accepted

The GUI conceptually separates:

- Services: connectivity, readiness, operational status, maintenance, and service information.
- Setup: experimenter, project, animal, protocol/template, device/configuration
  selection, scientific products, and configuration review.
- Experiment / Run: guided scientific steps, plots, selections, calibration,
  progress, results, and controls.

These are functional areas, not an accepted tab count, widget layout, frontend
technology, or implementation design. Existing readiness, maintenance, and
shutdown authority and Decision 394's insufficient-storage warning are preserved.
Presentation proposals remain in [GUI design notes](gui_design_notes.md).

---

## Decision 399: Scientific protocols and editable templates belong to the application

**Status:** Accepted

The GUI/application owns scientific protocols and templates, not the core
framework. A protocol defines ordered steps, dependencies, and optional operations.
A step may be an Experiment, Validation, Analysis, operator preparation or
interaction, or scientific annotation/review; not every step is an Experiment.

Templates provide editable starting configurations. Experimenters may modify
selected settings, devices, and optional steps and retain modifications as future
templates. Actual scientific execution configuration must be preserved independently
of its original template. Metadata/template ownership and propagation remain open.

The initial CaBMI application may reuse useful legacy GUI/protocol concepts.
Legacy GUI and MATLAB code are scientific/user-experience references, not framework
architectural authority. Neither a general protocol editor, a template installation
framework, nor a core workflow engine is required by the initial scope.

---

## Decision 400: Repetition and scientific selection preserve every attempt and actual inputs

**Status:** Accepted

Repeating an operation never erases earlier scientific results. Every executed
attempt and its products remain scientifically traceable. The GUI/application
interprets protocol-specific dependencies; the framework preserves necessary
scientific identities and provenance. Changed ROI masks may require dependent
baseline processing, ensemble selection, and calibration to be repeated; changed
neuron selections or calibration inputs may require recalibration before dependent
CaBMI execution. Earlier dependent results cannot simply be treated as current
for a revised workflow.

Successful Analysis execution is distinct from scientific acceptance or selection.
Valid persistent outputs must be preserved even when not selected. Experimenter
acceptance/selection must be traceable, and later Experiments or Analyses identify
the actual results and inputs used. New selections cannot retroactively change
completed operations or overwrite historical results. Detailed dependency,
selection, approval, and provenance representations remain unresolved.

---

## Decision 401: Analysis is a lightweight first-class Session-scoped scientific operation

**Status:** Accepted

Each Analysis has a unique `analysis_id` and may consume products from earlier
Experiments or Analyses and produce new scientific products. Its originating
operation is identified by `analysis_id`, never a fabricated `experiment_id`.

Analysis is distinct from Experiment and Validation. Producing results does not
make it inherit the full Experiment lifecycle, participant management, device
readiness, or Stop/Kill machinery. This qualifies Decision 096's historical
scientific-calibration-as-Experiment classification: scientific calculation and
calibration between Experiments may be Analysis, while operational tests remain
Validation and acquisition/closed-loop execution may remain Experiments.

The initial scope is scientific calculation associated with the active Session,
not historical data reopening, arbitrary offline processing, or a general job
platform. Invocation, minimum requests/outcomes/failure evidence, interruption,
and relationship to Session closure remain open under Q026. This decision
defines no new lifecycle states or executable interface.

---

## Decision 402: Experiment and Analysis products share scientific persistence ownership

**Status:** Accepted

Scientific products may originate from an Experiment (`experiment_id`) or an
Analysis (`analysis_id`) with equal standing under existing local scientific
persistence. Reuse LocalStorageManager, authoritative ArtifactManifests, and
existing global artifact collection rather than another persistence system.

Preserve producing Session/operation identity, scientific input/source-product
identities, relevant configurations and calculation parameters, outputs and their
input relationships, actual results selected/used later, and earlier repeated
results. Finalized products remain immutable; derived products remain separate,
with exactly one LocalStorageManager owner per scientific record and common
persistence ownership independently of payload meaning (Decisions 185-186, 191).

This extends the Experiment-oriented scope of Decisions 178-218, 208-211,
235-237, 240 onward, and 377-378. Device-declared acquisition product selection
does not already implement Analysis invocation. Existing Experiment-specific
stream, timing, manifest, and collection representations require later design
for Analysis; no schema or implementation support is asserted here.

Scientific results are not routine operational evidence and must not enter
Ingestor as scientific observations. Existing local scientific ownership,
manifest intake, pull-based global collection, and artifact/runtime-plane
separation remain authoritative. Occasional visualization delivery under
Decision 404 is not transfer of authoritative artifact bytes through NATS.

---

## Decision 403: Scientific execution remains local without turning DeviceManager into an Analysis scheduler

**Status:** Accepted

Hardware/software directly involved in acquisition or closed-loop execution may
use DeviceAdapter where compatible; CaBMI closed-loop processing is a candidate.
Between-Experiment Analysis is separate, not automatically a DeviceAdapter
operation. Scientific processing executes where required data and computational
resources reside.

The intended direction is an appropriate existing AcquisitionNode coordinating
local Analysis, not GUI or Controller performing scientific calculations.
DeviceManager must not become a general analysis scheduler. The exact local
invocation and installed-software integration interfaces remain unresolved.
Decision 164's acquisition timestamp ownership and existing adapter/acquisition
boundaries are unchanged; no Analysis timing schema is defined here.

---

## Decision 404: Controller command authority is distinct from direct GUI scientific-result delivery

**Status:** Accepted

Command/control direction is `GUI application -> Controller -> appropriate
AcquisitionNode`. Controller coordinates framework-controlled operations,
including authorized Session-associated Analysis requests. Scientific
visualization/result direction is `AcquisitionNode -> GUI application/backend`:
requested small plots and structured results need not pass through Controller.
Controller receives the coordination outcome/status, not necessarily the
visualization payload. Ingestor is not a scientific-observation or visualization
relay. A browser may communicate with its GUI backend; NATS participation grants
that backend no lifecycle authority.

Reuse existing NATS infrastructure where appropriate, preserving Decisions
115-149's brokered messaging, scientific artifact separation, publication/evidence
guarantees, and distinction between telemetry and authoritative stored records.
The direct result direction is logical, not authorization for a peer-to-peer
transport. Precise transport, subjects, schemas, recipient authorization,
correlation, and delivery/disconnection behavior remain unresolved under Q029.

Initial scope is occasional plots and small structured results, not continuous
imaging or general online/inter-node scientific streaming. Shared filesystem
paths or repeatedly overwritten PNGs are not the general accepted result
transport. This direction does not claim existing Analysis or GUI delivery support.

---

## Decision 405: The initial CaBMI workflow is a concrete use case, not a mandatory protocol

**Status:** Accepted

The initial scientific use case is:

1. Acquire approximately two minutes of imaging.
2. Run rapid Suite2p locally to identify ROIs.
3. Acquire approximately 15 minutes of baseline activity using those masks.
4. Inspect fluorescence and select four suitable neurons.
5. Simulate the neural cursor and calculate target T.
6. Review calibration, modify selections/parameters, and repeat calculations as appropriate.
7. Execute the closed-loop CaBMI Experiment locally.

Initial imaging, baseline acquisition, and closed-loop CaBMI are candidates for
separate Experiments. ROI identification, baseline-derived calculations, neuron
selection, and target calibration are Analyses, not automatically Experiments.
Operational tests remain Validation where appropriate. Scientific recordings
remain LocalStorageManager-owned; time-critical CaBMI execution is independent
of GUI/network round trips. Future decimated live cursor visualization may be
desirable but does not authorize general inter-node scientific streaming.

Decisions 396-405 record user-accepted HLC direction conveyed by the LLC handoff,
not implementation or software validation. Concrete Suite2p/CaBMI integration,
GUI packaging, and low-level Analysis contracts are still subject to later
accepted design. G4/G5 integration and hardware validation remain separate;
no milestone or open deployment/recovery question is closed by this synchronization.

---

## Decision 406: Normal Stop retains cleanup ownership while accounting for authoritative fatal health decisions

**Status:** Accepted

**Partially superseded by Decision 407:** The mandatory FAILED consequence of an
applicable fatal decision during already-admitted Normal Stop is superseded.
Original Session/Experiment context, durable accounting and sole-cleanup-owner
protections remain authoritative. The original accepted text below is retained
for traceability; read its terminal-outcome and processing wording with Decision 407.

An already-admitted Normal Stop retains ownership of its ongoing closeout. A
subsequently received authoritative `session_fail` health decision must not start
competing cleanup, duplicate remote stops, or automatic Kill. Normal Stop does
not immunize the Session from fatal failure: the decision must be durably recorded
and associated with the affected Session and applicable Experiment context, and
its canonical failure consequence must be accounted for without starting a
competing cleanup operation. Where applicable and authoritative, the canonical
terminal Session outcome is `failed`, not `completed`.

The health decision may be marked processed only after its required evidence and
lifecycle consequence have been accounted for; rejection of a competing command
alone is insufficient. Existing cleanup, preservation, final-intake and binding
obligations continue unchanged. Missing, failed or uncertain confirmations never
become successful confirmations. Ordinary Normal Stop without a fatal decision
retains its existing behavior.

This is the user-approved LLC clarification of Decisions 113-114 and 382 for G4,
not a new Session state, lifecycle authority, parallel closeout workflow, recovery
or preservation mechanism. Recording it does not claim implementation validation,
independent audit or G4 closure.

---

## Decision 407: Session closeout separates terminal lifecycle outcome from fatal health accounting

**Status:** Accepted

**Subsequent clarification:** Decision 408 resolves the admission, applicability
and late-intake integration questions identified below. The original Decision 407
text is retained for traceability; its implementation remains pending.

This records the user-accepted HLC direction titled "G4-A Simplification of Fatal
Health Decisions and Session Closeout", reconciled in the LLC-to-ICC handoff.
It partially supersedes Decision 406 and clarifies Decisions 113-114; it does not
claim implementation, validation, audit PASS or G4-A closure.

Session lifecycle describes how a Session ended; health evidence records what
happened. When Normal Stop was already admitted and all existing completion
guarantees are satisfied, the Session may be `completed` despite recorded fatal
health decisions. The presence of such evidence does not by itself require a
`failed` terminal outcome in that case. Evidence is not erased or reclassified to
justify completion. This is a bounded qualification of the earlier terminal-
outcome wording, not a change to the existing scientific or safety obligations.

Decision 406's requirement that applicable fatal decisions necessarily force
`failed` during already-admitted Normal Stop is superseded. Its protections for
original Session/Experiment context, durable decision accounting and sole cleanup
ownership remain. An individual fatal decision does not independently own physical
Session cleanup. One logical Controller-owned, Session-scoped closeout coordinator
governs physical cleanup coordination; service owners retain their independent
cleanup, scientific finalization, preservation, safety and release responsibilities.
Already-admitted Normal Stop is not displaced by a competing fatal cleanup path.

Each applicable fatal decision must be independently durably accounted for using
its own evidence and original Session/Experiment provenance. Multiple decisions
can be accounted for after canonical Experiment termination without repeating that
termination or physical cleanup. Independent decision accounting does not require
one new canonical terminal event per decision. Processing confirmation still
requires the decision's durable evidence and applicable lifecycle/closeout
consequence to be accounted for; rejecting competing cleanup or acknowledging
publication alone is insufficient. Under the already-admitted Normal Stop case,
this no longer means requiring a new FAILED transition for each fatal input.

Every asynchronous outcome, including errors and diagnostics, remains attributable
to its originating Session and operation. Work completing after release or
replacement must not modify a replacement Session, including its diagnostics.

Decisions 313, 322, 360, 365 and 382 remain unchanged: scientific finalization,
required producer publication, complete durable acquisition intake, verified
Stage A preservation, terminal Session Record obligations and each service's
independent binding-release and safety requirements still apply. Every persistent
ControllerActionDecision still requires confirmed archival before Controller
binding release. Missing, failed or uncertain cleanup/preservation is not success.
Finalized acquisition intake and immutable historical evidence are not reopened
by this decision. Authorized Kill retains its distinct emergency and partial-
preservation semantics; interruption, retained obligations and safe explicit retry
remain governed by the existing contracts. Standalone fatal failure does not
automatically acquire Normal Stop's full archival/release procedure, and
Experiment-only failure remains Experiment-only.

No new Session states, services, generic transaction frameworks, ownership
registries or unnecessary reconciliation machinery are authorized. Integration
questions not specified by this accepted direction remain explicit in
[Q013](open_questions.md#q013-what-further-framework-behavior-follows-controlleractiondecision-execution);
this synchronization selects no new late-intake or delayed-admission rule.

**Implementation status:** Accepted and synchronized only. Current G4-A behavior,
the latest pre-synchronization P2/P3 audit findings, and remaining clarification
and implementation work are tracked in Q013. G4-A and Q013 remain OPEN.

---

## Decision 408: Controller closeout admission, fatal-decision applicability and health-decision cutoff clarify Decision 407

**Status:** Accepted

This records the explicitly user-accepted LLC handoff titled "G4-A Decision 407
Admission and Applicability Clarifications". It clarifies Decision 407 and resolves
the three integration blockers recorded in Q013 without rewriting Decisions
113-114, 313, 322, 365, 382, 406 or 407 or their historical implementation reports.

### Authoritative closeout admission

The first Session closeout operation formally admitted by Controller owns physical
closeout coordination. Receiving or accepting a fatal decision does not itself
admit fatal Session closeout. Normal Stop admitted first retains ownership even
when an earlier accepted fatal decision awaits execution. That decision remains
independently accountable and does not automatically force `failed` under this
Normal Stop ownership. Fatal Session closeout admitted first retains its existing
`failed` behavior; later Normal Stop cannot displace it. Admission ordering uses
existing authoritative Controller/Session coordination, not incidental coroutine
scheduling.

### Independent fatal-decision applicability

Applicability is established at authoritative acceptance against the original
Session/Experiment context. Multiple applicable decisions accepted while an
Experiment was active remain applicable after its terminal transition. Accounting
for them does not require duplicate Experiment termination or physical cleanup.
New decisions about already-terminated Experiments are not automatically
applicable. Verified redelivery retains the existing decision's original identity
and applicability rather than establishing a new context. Every asynchronous
success, failure, cancellation and diagnostic outcome remains attributable to its
originating Session and operation and cannot modify a replacement Session.

### Mandatory health-decision admission cutoff

Controller closes admission of new Session-associated health decisions before
committing final acquisition-intake finalization under Decision 382. Admission
closure and decision acceptance must be authoritatively ordered using existing
Controller coordination, with no admission gap between cutoff and finalization.
After closure:

- Reject newly presented Session-associated health decisions.
- Continue accounting for previously accepted decisions.
- Permit verified redelivery of previously accepted decisions without treating it
  as new admission.
- Never report rejected late deliveries as successfully processed new decisions.
- Do not reopen finalized acquisition evidence, intake audit or Session Records.

The cutoff itself establishes neither durability nor preservation nor permission
to complete Normal Stop. All applicable accepted decisions must be accounted for
and preserved before successful completion. Decisions 313, 322, 365 and 382 remain
authoritative: independent service release, every accepted Controller decision's
required archival, complete Normal Stop preservation and immutable finalized
intake are not weakened. Decision 407's partial supersession of Decision 406 and
its retained original-context, durability and sole-cleanup-owner protections
remain unchanged. No new policies, states, services, archives, registries or
generalized synchronization mechanisms are authorized.

**Implementation status:** Accepted and synchronized only. The completed G4-A
pre-implementation impact/invariant review identified these three blockers;
this clarification resolves their architectural requirements, not their
implementation. ICC implementation scope authorization, implementation and
independent verification remain pending. G4-A and Q013 remain OPEN; G4-B/G4-C
remain deferred. See [Q013](open_questions.md#q013-what-further-framework-behavior-follows-controlleractiondecision-execution)
for the preserved blocker and audit history.

---

# Accepted Architectural Principles

The following principles summarize the accepted decisions so far.

Decisions 356-360 qualify the historical Session closeout and collection-evidence
contracts in Decisions 223-225, 228-229, 240, 243, and 274-275. Stage A confirms
acquisition preservation for completion/binding release; later operator-requested
collection uses a durable StorageManager-held handoff and direct Stage B collection
evidence before permanent archive closure. Kill Session preserves partial closeout
without automatically collecting artifacts or permanently closing that archive.
Decisions 361-365 subsequently specify contiguous durable receiving progress,
summary-based stage/closure information, temporary durable collection outcomes,
a separate Session-associated JSON handoff, and normal/forced closeout confirmations.
Decision 361's receiving foundation is complete with independent manual validation
and final independent re-audit PASS after correction (W041).
The supported Decision 366 producer/marker prerequisite is complete with developer
automated coverage, independent manual validation, and targeted independent
re-audit PASS after correction (W042). Bounded Normal Stop and Kill are complete in W047/W048; overall Q019 software integration validation is complete in W050. Bounded Stage A under Decision 362 is complete
with automated testing, independent manual validation, and independent audit PASS
(W043); bounded Stage B collection/Decision 363 persistence is complete with
independent manual validation and final targeted independent re-audit PASS after
correction (W045); W046 explicit closure is complete with independent validation
and targeted re-audit PASS after correction. Decision 365's bounded Normal Stop
integration is complete with independent validation and targeted re-audit PASS
after correction (W047); Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048).
Decision 364's bounded
durable handoff is complete with automated testing, independent manual validation,
and independent audit PASS (W044);
eligible-Session selection is complete with independent validation and final audit PASS after correction (W049). Q019 is CLOSED following overall software integration validation (W050); historical completed
scopes remain unchanged.

Decision 366 resolves the producer-publication scope: participating AcquisitionNodes
publish applicable evidence before existing successful completion responses,
independently of device optionality; Controller and SynchronizationManager complete
their applicable closing-Session publication before the single marker. Locally
journaled Ingestor-owned evidence needs no JetStream round trip. These clarified
coordination contracts are complete for the supported prerequisite with automated
coverage, independent manual validation, and targeted independent re-audit PASS
after correction (W042); W041 and ownership are unchanged.

Decisions 349-355 subsequently resolve additional Q024 ownership and behavioral
boundaries. Supported Decisions 351-352 startup reconciliation is complete with
independent manual validation and final independent re-audit PASS after correction
in W040; the other new contracts remain unimplemented. Decision 354 supersedes only
Decision 323's shared framework archive layout; Decision 349 extends Decision 280's journal
lifecycle boundary, and Decision 353 extends Decision 336's temporary-memory scope.
Historical decision text and validation records remain authoritative for their
original scopes; W039 completion and Q019's unresolved closure conditions remain.

Earlier entries retain their historical decision context. Decisions 313-321
subsequently resolve the service-binding and Q025 deferrals recorded in entries
301 and 304-312; those original decisions are preserved, not implementation claims.
Decision 322 subsequently clarifies persistent Controller decision evidence and
the Controller-specific archival obligation before binding release; it does not
resolve Q019 or claim implementation.

Decision 325 supersedes the global all-or-nothing precheck summarized in entry
314 and corresponding initial-gate wording in Decisions 317 and 319. Read those
historical entries with the progressive shutdown clarification; all other
requirements remain authoritative.

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
51. Historical Session device gating is superseded for Slice 28 by Controller evaluation of selected DeviceDeclaration.required against technical readiness; DeviceManager retains live adapter ownership.
52. Shared device readiness evidence remains reusable, but its historical required field is superseded by Decision 286.
53. Live DeviceAdapters are explicitly constructed outside DeviceManager v1.
55. DeviceAdapter receives copied declaration fields, not DeviceDeclaration.
56. A component should only validate information it owns.
57. Ingestor owns the handoff of accepted records to StorageManager while StorageManager remains a separate storage boundary.
58. Architectural terminology is defined once and used consistently throughout the repository.
59. DeviceManager and Ingestor share transferable acquisition record envelopes rather than live adapter-owned or manager-owned objects.
60. AcquisitionRecordEnvelope supports a minimal JSON-like plain-data round trip without choosing a transport or serialization protocol.
61. StorageManager v1 proves in-memory persistence boundary behavior and small readback without deciding final storage format.
62. Shared service readiness avoids inspection of service internals; Decision 292 supersedes StorageManager as a launch prerequisite while retaining required Ingestor and SynchronizationManager readiness.
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
75. Historical Phase 2 node readiness is superseded by pre-Session, reservation-aware reports with service-only aggregate readiness under Decisions 284-286.
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
93. Pre-running framework failures may fail an initialized Session; the historical Controller v1 two-write sequence is qualified by Decisions 226-229's archive/record separation and final persistence before completion, without claiming a persisted terminal snapshot.
94. Project is the scientific study; Session is the acquisition/evidence container; Experiment is protocol activity inside a Session.
95. Controller owns canonical Session-scoped Experiment lifecycle; AcquisitionNodes record local execution evidence.
96. Readiness, Validation, and Experiment are distinct; Calibration is a purpose rather than an architectural category.
97. Experiments declare expected contribution from resolved Session resources without owning deployment identities or node inventory (Decisions 282-283).
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
129. Session runtime subjects remain message-rooted and routing-only; Decision 296 extends commands with participant-scoped pre-Session addressing without fabricated Session identities.
130. Commands, command results, and evidence use separate JetStream streams; telemetry uses Core NATS only.
131. Message consumers follow existing component ownership; Ingestor preserves durable evidence and Controller consumes decision-relevant evidence.
132. Transport acknowledgement and explicit command result are separate outcomes.
133. Command results share accepted, progress, succeeded, and failed status vocabulary; Phase 10 runtime control uses final statuses only.
134. Commands target one component or one component group, with one result per executing component.
135. Group command-result aggregation belongs to the command issuer.
136. Missing command results become unresolved outcome evidence interpreted by the command issuer.
137. Command receivers use command_id for local duplicate detection.
138. Runtime component identity consists of component_type and component_id independent of deployment location.
139. SessionConfig is authoritative for final expected Session participation, not deployment identity or prospective launch inventory; discovery remains deferred.
140. Existing communication carries pre-Session readiness requests; Controller interprets missing/invalid reports as unknown, and no durable launch journal is introduced.
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
175. MappingUpdateEvidence uses existing runtime-evidence ingestion and, under Decisions 219-227, persistent compilation into the separate Evidence Archive without a new storage component.
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
191. Local scientific persistence shares ownership, interfaces, and lifecycle while permitting product-appropriate formats, including JSONL and camera HDF5.
192. External-artifact timing and index information use the same stream abstraction.
193. ArtifactManifest describes every locally managed scientific artifact and exists even for zero-row streams.
194. LocalStorageManager finalization means local completion only.
195. SynchronizationManager retains synchronization-evidence ownership; persistence requires explicit handoff.
196. Future global StorageManager consumes finalized local discovery information without taking original ownership.
197. Session initialization authorizes one LocalStorageManager per AcquisitionNode; Decision 298 clarifies physical creation by each node using deployment-local roots, with local storage participating in readiness.
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
209. Experiments explicitly select declared scientific products under Decision 235; external configuration representation remains future work.
210. One requested scientific data product maps to one local stream.
211. Each product has an independent stream, schema, lifecycle, and manifest relationship.
212. LocalStorageCompletionSummary describes local finalization only.
213. Empty finalized streams are valid and distinct from streams never created.
214. Local storage failures are preserved locally and may also be published as durable runtime evidence.
215. Future global StorageManager never writes live local streams.
216. LocalStorageManager records explicit local stream, manifest, failure, and cleanup evidence.
217. Local storage readiness must succeed before Experiment storage creation.
218. "No stream" and "empty stream" are architecturally distinct.
219. RuntimeEvidenceMessage remains the runtime evidence boundary.
220. RuntimeEvidenceMessage carries explicit producer-supplied persistence intent through `is_persistent`.
221. Evidence producers decide persistence for their own evidence, including mandatory persistent categories.
222. Ingestor never infers persistence from evidence type, payload, source, or domain meaning.
223. Ingestor owns runtime evidence intake, validation, audit, temporary retention, and persistent-evidence compilation.
224. Ingestor does not own evidence interpretation, lifecycle, scientific meaning, or persistence decisions.
225. StorageManager owns persistent writing only.
226. Session Record and Evidence Archive are separate concepts.
227. Evidence Archive v1 uses one runtime evidence stream plus ingest audit and compilation summary.
228. Persistent evidence lifecycle runs from initial Session Record through Ingestor collection and final archive/record writes.
229. Session completion requires final persistence success and otherwise uses the existing failed-session path.
230. Evidence Archive v1 does not resolve archive evolution, retention, artifact transfer, reconstruction, NWB, or global scientific collection.
231. The RuntimeEvidenceMessage persistence flag does not create new ownership.
232. Camera HDF5 artifacts preserve raw arrays, available metadata, frame indices, and aligned scientific timing through existing local persistence ownership.
233. Explicit persistence batching and handled finalization preserve partial artifacts without claiming success after write, flush, or closure failure.
234. Historical local root overrides preserve node defaults; Decision 298 qualifies distributed launch to use node deployment roots without Controller-selected overrides, retaining LocalStorageManager path ownership.
235. Experiment configuration explicitly selects declared products by existing source device, AcquisitionNode, and product identities without inferring outputs from connected or healthy devices.
236. Scientific-product declarations own persistence format requirements; Experiments select products without overriding formats or inventing unavailable characteristics.
237. Controller coordinates preparation through existing readiness; AcquisitionNode requests one LocalStorageManager-owned stream and manifest per selected product before scientific acquisition.
238. Each Experiment identity represents one execution; terminal identities cannot restart, and repeated configurations require new Experiment identities and independent lifecycle, streams, manifests, and timing evidence.
239. Required preparation precedes canonical Experiment start; pre-start rejection uses persistent runtime evidence, optional failures do not override required success, and missing required results remain unresolved.
240. LocalStorageManager owns artifacts and manifests; AcquisitionNode publishes information, Ingestor compiles the handoff, Controller initiates collection, and StorageManager retrieves bytes separately.
241. Complete authoritative manifests are published as artifact_manifest evidence at creation and finalization.
242. Slice 22 artifact information reuses the normal Ingestor working view; Decisions 276-280 accept later known-Session journal recovery without changing the existing handoff.
243. Session-scoped handoff compilation groups by artifact_manifest_id and prefers finalized manifests, explicitly reporting missing finalization otherwise.
244. Slice 22 excludes diagnostics compilation, byte transfer, restart recovery, new persistence infrastructure, and lifecycle changes.
245-260. Slice 23 accepts Controller-initiated StorageManager SSH/SFTP pull collection, deployment-local endpoint resolution, one scientific file per manifest, explicit source paths, deterministic destinations, independent attempts and outcomes, temporary promotion, collision failure, inclusion of missing-finalization candidates, and unchanged authoritative local ownership. Software validation is recorded in W032; M011 remains open pending real Jetson/SSH-SFTP deployment validation. Decision 303 prevents later global processing failure from retroactively changing a completed Session.
261. StorageManager owns light structural verification of global copies without taking local artifact ownership or interpreting scientific data.
262. Retrieval and verification have separate outcomes; verification follows successful transfer, closure, and publication only.
263. Verification outcomes are verified, copied_unverified, structurally_invalid, and verification_failed.
264. The first verification contract applies to the current LocalStorageManager HDF5 layout, not all HDF5 or a particular device type.
265. Current-layout light checks compare accessibility, nonzero file size, HDF5 opening, identity, required datasets, aligned lengths, and existing persisted counts; zero-record artifacts remain valid.
266. Verification remains bounded and excludes scientific-data scans and mandatory checksums.
267. Invalid or inconclusive verification preserves the global copy unchanged.
268. Existing product and manifest contracts remain unchanged; other layouts, JSONL verification, and broader structural-contract design remain future work.
269. Per-artifact results represent separate retrieval and verification information without a new reporting subsystem.
270. Aggregates reflect retrieval and verification separately from Session lifecycle; Decision 303 resolves the former Q017 without changing those outcomes. Slice 24 is complete (M012, W032) following software validation and corrected independent re-audit PASS.
271. StorageManager produces one compiled persistent global_artifact_collection_evidence record per completed collection pass, not one message per artifact or a duplicate manifest.
272. Collection evidence contains only attempted artifacts with separate existing collection/verification outcomes and no aggregate evidence status.
273. Collection-pass timestamps are operational wall-clock audit time, never extended scientific Session Time.
274. StorageManager owns and publishes its collection evidence through the existing durable boundary; Ingestor compiles it for the same Session's existing Evidence Archive.
275. Session acquisition end precedes required post-session processing; Controller prevents finalization overtaking active collection/publication, while the Session-wide evidence-drain/consumption guarantee remains open in Q019. Slice 25 is complete (M013, W033) after software validation and corrected independent re-audit PASS.
276. Live Ingestor acceptance requires reported durability success before working-state update and ACK; failure closes further intake until restart, where complete valid journal history is authoritative even after a prior uncertain error. Crash durability does not change permanent persistence intent.
277. evidence_id deduplicates identical Ingestor redelivery; conflicting content is an error, not an overwrite.
278. Known-Session journal replay rebuilds the normal evidence/handoff view; only a clearly interrupted final entry may be omitted, not earlier corruption.
279. Successful reconstruction creates persistent ingestor_recovery_evidence through normal acceptance, without copied recovered contents or a separate store.
280. Slice 27 recovery is complete after independent manual software validation and corrected targeted re-audit PASS (M014, W034); journal lifecycle and application restart remain Q024, while Session-wide consumption/finalization coordination remains Q019.
281. Controller owns pre-Session launch, runtime assembly, stopping, and finalization across existing communication boundaries without taking domain ownership.
282. RuntimeParticipant reuses component_type/component_id as deployment identity independent of Session, without device or transport-address identities.
283. AcquisitionNode owns declared inventory before Session; membership identifies the node and Session selects existing declared devices/products.
284. Pre-Session node reports separate technical ready from reserved_for_session_id; missing/invalid current reports are Controller-interpreted unknown, not a new readiness value.
285. Every successful node report includes readiness and explanatory failure reasons for every declared enabled device, including missing adapters.
286. Node ready aggregates required framework/service prerequisites only; DeviceReadiness omits required and DeviceDeclaration.required determines Session-selection criticality.
287. AcquisitionNode owns atomic exclusive reservation with same-Session idempotency and owner-keyed release, without a central registry or lease.
288. Reservations last through acquisition and local finalization, not later global retrieval, and release never deletes local artifacts.
289. Controller allocates a nonreusable intended Session ID, resolves/reserves resources, creates Session, and waits for required initialization/preparation before launch success.
290. Selected device criticality determines node launch criticality; optional omissions add no product-level required semantics.
291. SessionConfig contains the final resolved selection, never omitted optional resources or an unresolved wish list.
292. Ingestor and SynchronizationManager readiness are mandatory for launch; global StorageManager readiness is not, while local persistence and final writing retain their requirements.
293. Controller coordinates failed-launch rollback and operational failure; Decision 300 requires confirmed cleanup before releasing nodes whose initialization may have started, without new lifecycle states or retry policy.
294. Pre-Session launch results do not introduce durable launch journaling; Slice 28 implementation has automated coverage while M015 awaits independent validation and audit, with deferred concerns remaining open.
295. Participants start independently of Session and Controller; required NATS startup connectivity must succeed before operational distributed readiness, without indefinite waiting or automatic retry.
296. Pre-Session commands address RuntimeParticipant identity without fabricated Session IDs; Session-specific operations require real identities and reuse existing NATS command/result conventions.
297. AcquisitionNode owns reservation and Session binding; its communication handler remains connected across Sessions without a separate authority or per-Session recreation.
298. Remote initialization follows reservation and resolved configuration; nodes prepare local runtime and physically create Session-authorized LocalStorageManagers using node deployment roots, not Controller-selected paths.
299. Launch requires confirmed preparation from every mandatory participant; missing/invalid/unresolved results prove neither success nor absence of remote state.
300. Failed initialization invokes participant-local cleanup; confirmed cleanup precedes node reservation release and subsequent binding clearance, preserving artifacts, evidence, and timing.
301. Ingestor and SynchronizationManager independently confirm Session-specific preparation without hardware reservations; recovery durability and timing ownership remain unchanged, normal service binding lifetimes stay deferred, and M015 remains pending.
302. Successful DeviceAdapter shutdown and required cleanup return retained adapters to DECLARED for sequential Sessions; failed/unconfirmed cleanup prohibits reuse, pre-Session readiness distinguishes safe reuse, and each Session supplies its own configuration. Implementation has automated regression coverage; independent validation/audit and M015 closure remain pending.
303. Later global collection, verification, transfer, or export failures are operational outcomes and cannot retroactively change a completed Session's lifecycle; required pre-completion failure handling remains, and Q019's supported consumption/final archive coordination is complete in W050.
304. Controller, AcquisitionNode, Ingestor, StorageManager, and SynchronizationManager have Session-independent and GUI-independent lifetimes; Session-specific objects and managed devices retain their existing ownership, cleanup, reuse, and bounded-memory contracts.
305. Controller coordinates operator-requested framework stop for an explicit scope, distinct from Session stop, without automatically initiating collection, verification, transfer, or export.
306. Every stop request has a durable stop_attempt_id and preserves scope, requester, timestamps, actions, blockers, and completed/blocked/failed outcome, separate from Session and command results.
307. Orderly stop requires bounded participant-response waiting and confirmed required closeout conditions; missing or unconfirmed results are not success, and concrete windows/commands remain low-level work.
308. Blocked stop reports actionable unresolved conditions by responsible participant/domain and scope, allowing the operator to authorize kill or decline.
309. Kill is operator-authorized forced continuation of the same blocked stop attempt, without repeating the entire readiness check or claiming unresolved work completed; original blockers and actual forced results remain recorded.
310. Declining kill ends that attempt as failed without forced action; a later retry has a new identity and does not automatically change an unrelated Session lifecycle.
311. Stop/kill protect shared services and unrelated scopes; narrow operator authority is not administrative infrastructure termination authority.
312. Stop/kill require durable attempt/outcome evidence using existing boundaries where applicable; transport acceptance is neither persistence nor execution confirmation, and unresolved low-level durability details stay in Q025, without resolving Q019. Q025 is now architecturally resolved; W036-W037 validate maintenance/shutdown, not completion of Phase 16.
313. Services independently release confirmed Session bindings for successive-Session reuse without terminating services, losing evidence, or discarding outstanding obligations.
314. General framework shutdown is Controller-coordinated and stops no service if pre-stop evaluation blocks; individual administrative service maintenance is independent and service-owned.
315. Maintenance outcomes are completed for confirmed orderly/authorized forced termination, blocked before shutdown begins, and failed for incomplete shutdown, failed/unconfirmed force, or declined kill; kill continues the same attempt.
316. Explicit directional operational dependencies and service-owned blockers govern closeout; communication alone does not imply a dependency or require a dependency manager.
317. General shutdown preserves evidence in producer -> Ingestor -> StorageManager -> Controller order; Controller records readiness for its own exit and stops last without a supervisor.
318. Framework evidence may lack Session identity through minimally extended existing runtime-evidence/Ingestor/Evidence Archive contracts; Session evidence retains its identity and no separate evidence system is introduced.
319. Required evidence submission and confirmed durable preservation precede orderly closeout; authorized kill preserves whatever the initiator can confirm without promising complete preservation or resolving Q019.
320. Unexpected stop or forced termination does not automatically stop/restart other services; missing dependencies affect required operations without promising interrupted-work recovery.
321. Services start independently, load required durable configuration/records, use existing communication/dependency mechanisms, report actual readiness, and recognize returning services without automatic Session/transfer recovery. Q025 is resolved architecturally; independent startup/returning-service integration remains unfinished, and Phase 16/M015 remain open.
322. Every ControllerActionDecision is producer-marked persistent through the existing RuntimeEvidenceMessage/Ingestor/StorageManager/Evidence Archive pathway; Controller binding release requires confirmed archival of its Session's decisions plus required cleanup and Session Record obligations, not merely NATS publication. Temporary decisions may then be retired without deleting durable evidence; the narrow Decision 313/322 binding-release implementation is validated in W035, while Phase 16 remains incomplete and Q019 CLOSED in W050.
323. Session-independent framework evidence uses the existing framework/evidence partition with JSON-null Session identity and exact persistent-message, intake-audit, and summary confirmation, without a Session Record, fabricated Session binding, new receipt file, or commit protocol.
324. Individual-service maintenance preserves confirmed cleanup and readiness-for-retirement evidence before retiring required evidence capabilities; only actual retirement confirmation permits a completed result, without impossible post-retirement self-persistence.
325. General framework shutdown uses explicit Session-independent participant scope, an informational local readiness survey, and progressive dependency-safe stops; each blocked service needs separate kill authorization, stopped services remain stopped, and existing evidence preservation contracts apply. Coordinated shutdown is implemented, manually software-validated, and independently re-audited PASS (W037).
326. Coordinated shutdown prepares actual StorageManager and Controller cleanup and durably preserves its evidence before Ingestor retirement; later retirement confirmations use existing command/results, not invented archive records. Preparation is not retirement, the operational retirement order is unchanged, and W036 remains unchanged outside coordinated shutdown. This contract is implemented, manually software-validated, and independently re-audited PASS (W037); Phase 16 and M015 remain open.
327. Starting and returning operational services announce existing RuntimeParticipant identity and ServiceReadiness through existing NATS mechanisms, including known unresolved obligations; receiving services do not automatically issue redundant readiness requests.
328. Services receive configured-dependency announcements directly and update their own readiness; Controller neither relays announcements nor maintains a registry, and existing readiness interpretations and distinct reservation/communication/obligation concepts remain unchanged.
329. Returned services with normal readiness and no conflicting obligations are usable under existing contracts; obligations restrict affected operations/resources without special re-admission or automatic recovery.
330. Explicit administrator resume/drop decisions are recorded through existing framework evidence; recording does not confirm execution, whose mechanics remain deferred to Q024.
331. Startup/return, meaningful readiness changes, unresolved work, administrator decisions, and available actual results use existing framework evidence/preservation boundaries; unavailable archival confirmation requires an operator warning, not blocked startup when other accepted prerequisites are met or a second persistence system. Startup/return is implemented with automated coverage; independent manual validation and audit remain pending. The Services tab is a future proposal and Phase 16/M015 remain open.

332. Services report unresolved previous work through existing readiness, diagnostics, commands, administrative interfaces, and framework evidence, without a universal recovery model, registry, or new reporting command.
333. Obligation outcome, recovery possibility, and operational impact are independent service-owned classification dimensions, not global states; recoverable is not recovered and abandoned is not completed.
334. Existing identities define affected scopes; narrow restrictions require demonstrated sufficiency, and unproven scope containment cannot establish safety for other potentially affected resources.
335. Explicit administrative drop records the administrator, service/obligation, decision, and available justification and closes work as abandoned/not recovered, without proving completion, cleanup, safety, or recovery.
336. Recorded abandonment permits release of unnecessary temporary memory only after applicable preservation, safety, and closeout obligations are satisfied; minimum safety information and durable records/journals remain protected.
337. Existing service-specific owners assess their own obligations and confirm completion from trustworthy records and state, never intent, transport acknowledgment, missing responses, or incomplete evidence.
338. Unresolved-work reports, recovery assessments, classifications, administrator decisions, and confirmed outcomes reuse existing producer persistence intent and Ingestor/StorageManager framework archival boundaries; the narrow reporting/abandonment/producer-memory slice has automated coverage, independent manual IPython validation PASS (10 scenarios), and independent source audit PASS with no blocking findings. Decision 336 remains partially implemented; broader recovery/journal lifecycle and execution remain OPEN Q024 work.
339. New service-specific recovery attempts require explicit human administrator authorization for one obligation and current owner-validated safety/prerequisites; service return does not initiate recovery and no universal recovery operation or registry is introduced.
340. Owners distinguish absent recovery procedures, potentially safe procedures, and proven completion; authorizing recovery, leaving unresolved, and abandoning are separate choices.
341. Recovery requests correlate the original obligation, authorization evidence, execution command, and existing participant/result identities; reports, decisions, attempts, actual outcomes, and archival confirmation remain distinct, with successful/failed/refused attempts preserved through existing evidence.
342. StorageManager may attempt authorized fresh complete artifact transfers and persistent-record rewrites with trustworthy inputs and current safety, preserving original artifacts, non-overwriting final destinations, verification, and Ingestor compilation ownership without resolving Q019.
343. Q024-B adds no Ingestor recovery mechanism or authorization requirement for accepted automatic valid-journal reconstruction of an already-known Session; corruption is not accepted and application-wide discovery stays deferred.
344. AcquisitionNode scientific-artifact preservation and device/resource cleanup are independent authorized actions; actual records, authoritative local manifests, terminal Experiment identities, and confirmed resource-safety protections remain authoritative.
345. Controller may read and reconcile trustworthy durable evidence and confirmed participant outcomes without authorization, but records only proven results and neither automatically replays commands nor advances lifecycle or restores the application.
346. Synchronization recovery preserves historical timing/mappings, reports active-Session continuity gaps and uncertainty, and uses trustworthy current synchronization without fabricated observations, timestamp mutation, or automatic Session failure. Supported Q024-B cases are complete with automated coverage, independent manual validation, and final independent re-audit PASS after correction (W039); broader Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.
347. Authorized interrupted Evidence Archive repair requires journal-backed durable Ingestor acceptance of authorization and attempt before execution, not successful archival in the unavailable target; actual write success and subsequent outcome archival remain separate, without new evidence infrastructure or Q019 guarantees.
348. Loss of the active Session Time reference requires preserved historical timing/scientific recordings and explicit continuity/uncertainty reporting, never zero-based restart, fabricated relationships, unjustified old-map activation, or automatic Session failure; no active-Session clock-restoration mechanism is authorized, and healthy mapping updates remain unchanged.
349. Ingestor owns temporary journal retirement only after inactive/recovery, persistent-evidence/audit, applicable finalization, and reconstruction/deduplication obligations are confirmed; uncertainty retains journals and Q019 closure contracts are implemented and validated in W050; journal retirement remains unimplemented.
350. Explicit informed operator authorization may permit terminal deletion of identified unrecoverable temporary evidence; loss, authorization, execution, and safety remain distinct, with no invented auditing exception when evidence infrastructure is unavailable.
351. Every Controller startup reconciles observable known participants and owner-reported unfinished work, preserving unknown states and safe active acquisition without Session/application restoration or operational replay.
352. Controller failure does not invalidate node-owned Session reservations; authorized recovery and release require independently confirmed local finalization and device safety, not leases or automatic expiry.
353. All principal services retire unnecessary temporary work after preservation/safety conditions while retaining reporting, resource protection, deduplication, and command-reexecution safeguards; Decision 336 remains partially implemented.
354. Permanent framework Evidence Archives use YYYY-MM partitions with the existing three products, superseding Decision 323's shared layout without changing Session archives, scientific artifacts, timestamps, or temporary journals.
355. Finalized means immutable, not necessarily safe to delete; confirmed safe deletion must never affect later operation/recovery, and historical archives are never automatically deleted. Decisions 349-350 and 353-355 remain unimplemented; supported Decisions 351-352 startup reconciliation is complete, independently manually validated and independently re-audited PASS after correction in W040; Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.
356. Controller publishes one Session-scoped acquisition-evidence-completion marker after required producer publication confirmations; Ingestor independently verifies earlier durable acceptance using ordered JetStream evidence and acknowledgment progress, with exact contiguous proof still open.
357. Confirmed Stage A acquisition evidence/audit/summary and final Session Record preservation permits successful Session completion and applicable binding release before later operator-requested collection; Stage B preserves collection evidence and permanently closes the same archive without altering acquisition outcomes.
358. StorageManager directly persists its own persistent collection RuntimeEvidenceMessages in the Session archive, with separate provenance, no Ingestor routing or fabricated audit, and identity/durability/integrity/crash-safety protections; interrupted persistence is not success or automatic transfer replay.
359. Ingestor compiles the existing handoff at acquisition closeout and StorageManager durably preserves it; later Controller-selected stopped-Session collection needs no original Session binding, new manifest registry, discovery, or automatic collection.
360. Kill Session is separately authorized forced closeout preserving accessible evidence, files, partial Session Record, unresolved conditions, and safety; later collection remains eligible and the partial archive stays open until confirmed Stage B closure, without a killed lifecycle state. bounded Normal Stop is complete with independent validation and targeted re-audit PASS after correction (W047); Bounded Kill Session integration is complete with independent validation and final re-audit PASS after corrections (W048); the supported producer/marker prerequisite is complete with automated coverage, independent manual validation, and targeted independent re-audit PASS after correction (W042); Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.
361. Ingestor retains Session-specific receiving progress across restarts and proves complete earlier durable acceptance through verified contiguous JetStream acknowledgment progress; marker receipt or isolated ACKs are insufficient, and exact feasibility must be independently verified without weakening the guarantee.
362. The existing compilation summary records Stage A completion and Stage B permanent closure with distinct evidence origins; status alone is not preservation proof, and verified consistent durable closure makes the single archive immutable.
363. StorageManager temporarily durably preserves each actual collection outcome and unique evidence ID before direct archival; confirmed archival and duplicate protection permit safe temporary retirement and authorized evidence-write recovery without repeating transfer.
364. Ingestor's existing handoff is verified durably preserved by StorageManager as a separate Session-associated JSON file in the existing Session directory; later selected collection validates it without old bindings, invented registries, or guessed missing information.
365. Normal Stop requires producer confirmations, complete durable Ingestor acceptance, and complete Stage A preservation; authorized Kill Session preserves confirmed accessible partial information without claiming completeness or safe resource release. Decision 361's receiving foundation is complete with independent manual validation and final independent re-audit PASS after correction (W041); the supported producer/marker prerequisite is complete with automated coverage, independent manual validation, and targeted independent re-audit PASS after correction (W042); bounded Stage A under Decision 362 is complete with automated testing, independent manual validation, and independent audit PASS (W043); bounded Decision 364 durable handoff is complete with automated testing, independent manual validation, and independent audit PASS (W044); bounded Stage B collection/Decision 363 evidence persistence is complete with independent manual validation and final targeted independent re-audit PASS after correction (W045); W046 explicit permanent closure is complete with independent manual validation and targeted independent re-audit PASS after correction; bounded Normal Stop integration is complete with independent validation and targeted re-audit PASS after correction (W047); Bounded Kill Session integration is complete in W048; eligible-Session selection is complete with independent validation and final audit PASS after correction (W049), and overall Q019 software integration validation is complete in W050. Q019 is CLOSED in W050; Q024, Q022, Phase 16, and M015 remain OPEN.

366. Participating AcquisitionNodes confirm durable acquisition-stage evidence publication through their existing successful completion responses regardless of selected-device optionality; Controller and SynchronizationManager finish applicable closing-Session publication before the single marker, while locally journaled Ingestor evidence needs no JetStream round trip. The supported publication prerequisite is complete with automated coverage, independent manual validation, and targeted independent re-audit PASS after correction (W042); W041 is unchanged and Q019 is CLOSED following overall software integration validation (W050).

367. One installed framework package uses explicit service-role launching, not configuration-selected services or a new orchestration framework.
368. Installation uses file-based local configuration outside Git, with separate general service and node hardware settings, startup loading, and restart for changes.
369. AcquisitionNode installation explicitly configures persistent identity, devices, adapters, connections, and node-owned scientific storage without discovery or camera-specific assumptions.
370. Adapters expose validated Session-adjustable parameter definitions through existing inventory and configuration, without leaking overrides into subsequent Sessions or implementing a GUI.
371. Configuration validity is distinct from hardware readiness; invalid node configuration prevents acquisition, while offline nodes do not prevent StorageManager startup.
372. Persistent unique node identities use explicit Controller registration loaded on restart, duplicate conflicts, and existing startup/readiness reconciliation without a registry or automatic stopping.
373. Installation requires key-based SSH/SFTP setup and verified dummy retrieval using local endpoint/authentication references, not a continuously enforced Session connectivity gate.
374. Initial manual installation verifies NATS and Controller-node readiness communication; device acquisition tests are strongly recommended, not mandatory runtime certification. Q022-A is accepted and synchronized, not implemented or independently validated; Q019 remains CLOSED and Q022, Q024, Phase 16, and M015 remain OPEN.

375. Historically required all principal services to communicate through NATS; Decision 376 supersedes separate deployment and internal NATS for the Ingestor-StorageManager pair, preserving ownership and trustworthy confirmations.
376. Ingestor and StorageManager share one computer/process and startup/shutdown/restart lifetime with permitted local calls and distinct ownership; all process-crossing communication, including Controller access, uses NATS. Decision 377 qualifies scientific-envelope intake while preserving active durability and archival guarantees.
377. Routine scientific observations and their metadata stay in AcquisitionNode-local scientific products regardless of size; Ingestor receives operational runtime evidence and manifests, not routine scientific envelopes. Historical W051/W052 remain validated; implementation reconciliation and future streaming are not completed or defined here.
378. Installation declarations and explicit Experiment selections govern adapter scientific production and local persistence; cleanly replace obsolete collection/envelope architecture while retaining active operational and archival responsibilities, with final independent integration audit of functionality and obsolete-path removal.
379. SynchronizationManager establishes node-specific mappings from sufficient measured cross-clock exchanges accounting for delay, variability and uncertainty; bounded initial clock-rate assumptions are explicit, and configurable quality checks are distinct from complete resynchronization.
380. AcquisitionNode applies authorized affine mappings locally and prospectively, derives Experiment Time from Session Time, and preserves required scientific timing, mapping history and local activation boundaries without per-observation mapping IDs.
381. Acceptable synchronization is required at Session acquisition readiness and before each Experiment; configurable periodic assessments preserve degraded timing/provenance, with consequences governed by existing TimingQualityPolicy and Controller authority, never transport timestamps or assumed shared clocks.
382. The Normal Stop marker is last-call, not proof by itself; Ingestor finalizes acquisition intake only after complete durable receipt verification, and finalized intake plus verified Stage A establishes preservation eligibility without transferring Controller lifecycle or independent service-release authority.

---

Open questions now belong exclusively in `open_questions.md`.

