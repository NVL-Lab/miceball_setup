# Installation And Deployment

## 1. Scope, Architecture And Verification Status

This is the maintained operational reference, not an installer or deployment
certificate. [AGENTS.md](../AGENTS.md), the [development workflow](architecture_chat_workflow.md)
and [accepted decisions](architecture_decisions.md) remain authoritative.
Replace uppercase placeholders with actual values; framework JSON does not expand
environment variables. Quote shell paths containing spaces. Keep actual
configuration and credentials outside Git.

- Controller independently owns and is the sole launcher of its Sessions.
- All Controller-to-service communication uses NATS regardless of physical placement.
- AcquisitionNodes own devices and node-local scientific recordings.
- Ingestor and StorageManager have separate authorities but share one process,
  computer, startup, shutdown and restart lifetime (Decision 376). Their internal
  calls may be local; external callers use NATS.
- SynchronizationManager is a distinct independently launched service.
- The existing service CLI manages service process lifetimes. The separate GUI
  is intended to operate Sessions/Experiments through the running Controller;
  GUI-to-Controller integration is not yet implemented or validated.
- Do not create another Controller to operate an existing Controller. This guide
  neither prohibits future multiple-Controller deployments nor establishes them
  as currently supported or validated.

| Status | Meaning |
| --- | --- |
| Repository-verified | Implemented interfaces inspected and/or covered by referenced software validation; not physical deployment proof |
| Hardware-validated | Only the named equipment, revision and procedure were physically verified |
| Pending hardware validation | Target equipment/network behavior remains unconfirmed |
| Known blocker | Specific unmet integration requirement or observed environmental failure, not a presumed architectural defect |

G2, G3 and G4-A/B/C are CLOSED within their validated software scopes. Q013's G4
software scope is CLOSED; Q022, Q024, M015 and Phase 16 remain OPEN. G5 remains
incomplete. Historical findings and counts remain in [validated workflows](validated_workflows.md)
and [open-question tracking](open_questions.md); they are not physical passes.

## 2. Prerequisites And Platforms

Use **Python >=3.12,<3.13** on each service computer. The dependency/version
authority is [pyproject.toml](../pyproject.toml).

| Dependency | Where and why |
| --- | --- |
| `nats-py>=2.15,<3`, `numpy>=1.26,<3`, `h5py>=3.11,<4` | Core dependencies installed with the package |
| `paramiko>=3.4,<5` via `artifact-retrieval` | StorageManager computer for SSH/SFTP retrieval |
| OpenCV providing `cv2` | Camera computer; platform/Python/backend-compatible build |
| Matplotlib | Optional visualization, not HDF5 recording/verification |
| `nats-server` with JetStream | Operator-managed broker, separate from the Python client |
| SSH/SFTP server and key-based access | Node computer for required installation retrieval and later collection |

Windows PowerShell and Linux commands follow. Python metadata does not certify
every Windows, Ubuntu, JetPack or ARM combination. Native package/build support,
camera drivers and permissions require platform verification. Do not replace
system Python to obtain 3.12 or assume system `cv2` is visible inside a virtual
environment.

Use writable local storage with adequate capacity. Current capacity checks reject
unknown/remote filesystem backing rather than assume independent free space
(`local_storage.inspect_storage_capacity()`). Atomic publication, fsync and
initial hard-link promotion must work under the actual account/on the actual
volume. Existing-identical-handoff fixtures do not prove first publication.

## 3. Fresh Installation

Obtain the repository URL and reviewed deployment revision from the lab. In these
commands `REPOSITORY_URL` and `DEPLOYMENT_REVISION` are placeholders, not defaults.

### Windows PowerShell

```powershell
git clone REPOSITORY_URL miceball_setup
Set-Location miceball_setup
git checkout DEPLOYMENT_REVISION
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install .
python -m pip check
python -m lab_sync_acquisition.service_launcher --help
```

If activation is blocked, do not weaken institutional policy. Invoke
`.\.venv\Scripts\python.exe` instead of `python`; the installed CLI is
`.\.venv\Scripts\lab-sync-acquisition.exe`.

### Linux / Jetson

```bash
git clone REPOSITORY_URL miceball_setup
cd miceball_setup
git checkout DEPLOYMENT_REVISION
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install .
python -m pip check
python -m lab_sync_acquisition.service_launcher --help
```

Provision missing `venv` support using approved platform procedures. Without
activation use `.venv/bin/python` and `.venv/bin/lab-sync-acquisition`.
On shared storage install the retrieval extra:

```text
python -m pip install ".[artifact-retrieval]"
```

Install a platform-appropriate OpenCV build separately on camera computers, then
check `python -c "import cv2; print(cv2.__version__)"`. Optional visualization:
`python -m pip install matplotlib`. Editable development installs may use
`python -m pip install -e .` or `-e ".[artifact-retrieval]"`; record that choice.
The smoke script imports checkout `src/`; avoid mismatching it with an older
non-editable service installation.

## 4. Inspecting And Updating Existing Installations

Do not recreate a compatible existing environment merely because the checkout
changed. First inspect the actual checkout:

```text
git status --short
git rev-parse HEAD
git remote -v
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show lab-sync-acquisition
.\.venv\Scripts\python.exe -m pip freeze
.\.venv\Scripts\python.exe -m pip check
```

Linux / Jetson:

```bash
.venv/bin/python --version
.venv/bin/python -m pip show lab-sync-acquisition
.venv/bin/python -m pip freeze
.venv/bin/python -m pip check
```

1. Arrange a maintenance window. Resolve active work through its existing
   Controller lifecycle; pending GUI integration does not authorize a bypass.
   Confirm service retirement before replacing running code, especially editable
   installations. Do not update underneath acquisition.
2. Preserve local configuration, keys, scientific files, JetStream data, journals,
   permanent closed-Session records, archives and handoffs. Resolve user changes
   explicitly; do not reset a dirty checkout or delete state to make startup work.
3. Select the reviewed revision manually:

   ```text
   git fetch origin
   git checkout DEPLOYMENT_REVISION
   git rev-parse HEAD
   ```

4. Reuse a compatible Python 3.12 environment. Reinstall a non-editable package
   after source changes with `python -m pip install .` (include the retrieval extra
   on storage). Editable installs need reinstallation when metadata/dependencies
   change. Do not blindly upgrade all dependencies or recreate environments.
5. Run `python -m pip check`, record versions, validate files, restart in dependency
   order and repeat applicable installation/readiness checks.

There is no automatic updater, migration, rollback or general Controller-crash
Session restoration. Check revision/data compatibility before opening durable
state. Uncertainty requires clarification, not state recreation or format guessing.

## 5. NATS / JetStream And Networking

Install an operator-selected `nats-server` binary for the broker machine's actual
OS/architecture from [official downloads](https://nats.io/download/). Extract to
an operator-managed location and add to PATH or invoke its full path. Record its
version; this repo does not prescribe a universally validated server version.

Example external broker configuration, with actual values substituted:

```text
listen: "BROKER_BIND_IP:4222"
jetstream {
  store_dir: "ABSOLUTE_PERSISTENT_JETSTREAM_PATH"
}
```

Use a real assigned interface address for remote clients; loopback is local-only.
Wildcard binding requires matching access controls. This fragment is not a
complete shared-network security configuration: arrange institution-approved
authentication, permissions and encryption before exposure. See the
[NATS configuration reference](https://docs.nats.io/reference/config/) and
[security documentation](https://docs.nats.io/learn/security/encryption).

Validate/run the broker in its own terminal:

```text
nats-server -v
nats-server -t -c NATS_CONFIG_PATH
nats-server -c NATS_CONFIG_PATH
```

Keep JetStream storage durable and writable, not automatically cleaned temporary
storage. Do not casually expire/delete stream history: receiving completeness and
command-history validation depend on it. A single broker is not high availability
or power-loss certification.

- Framework URLs are explicit, e.g. `nats://BROKER_REACHABLE_HOST:4222`.
  Never use `0.0.0.0` as a destination or Windows loopback from Jetson. The example
  port is configurable, not a mandatory framework value.
- Clients connect outbound to the broker. Permit its selected inbound TCP port
  from authorized clients and corresponding egress. Windows-to-Jetson SSH/SFTP is
  a separate connection, normally TCP 22.
- UAB routing, VLAN/client isolation and host firewalls may block peer traffic.
  Obtain actual policy/addresses. A dedicated switch still needs usable addressing
  and firewall configuration.
- A stable resolvable hostname can avoid a changing literal IP. The framework
  supplies no discovery, DNS provisioning or dynamic address management. After
  moving networks, recheck broker bind, URLs, SSH endpoints and trusted host keys.
  Do not blindly accept changed fingerprints; apply file changes through safe restart.
- Current connections use `allow_reconnect=False`; do not promise automatic
  reconnect/restart. Respect retained-owner obligations after communication loss.
- `ensure_streams()` provisions scoped, file-backed `LAB_COMMANDS`,
  `LAB_COMMAND_RESULTS`, `LAB_EVIDENCE`. Accounts need the existing stream,
  consumer, publish and readback permissions. TCP reachability is insufficient.

Optional PowerShell transport check:
`Test-NetConnection BROKER_REACHABLE_HOST -Port 4222`. This tests TCP only, not
JetStream or service readiness. Monitoring ports/clusters are not prerequisites
for this single-broker example. The framework never installs or manages NATS.

<a id="deployment-local-service-files-w064-closed"></a>
## 6. Configuration, Identities, Paths And Credentials

Copy the [five manual examples](../config_templates/manual_installation/README.md)
outside Git: Controller, synchronization, node service, node hardware and shared
storage. Replace all uppercase placeholders. Root templates with null settings
are incomplete skeletons, not runnable deployments.

Every service file requires `servers`, `ingestor_id`, `storage_id`,
`preservation_window_s`. Additional fields:

| Selected CLI role | Additional fields |
| --- | --- |
| `controller` | `service_id`, `synchronization_id`, `known_nodes`, `result_window_s` |
| `synchronization-manager` | `service_id`, `result_window_s` |
| `acquisition-node` | `synchronization_id`, `node_config`, `result_window_s`; optional `service_id` must match hardware `node_id` |
| `ingestor` or `storage-manager` | `storage_root`, `global_artifact_root`, `recovery_journal_root`, `framework_journal`, `retrieval_endpoints`; dependency mode below |

Choose exactly one shared-pair dependency mode:

- Actual dependents: nonempty `external_dependents` list of objects with exactly
  `component_type`, `component_id`, plus positive finite `result_window_s`.
  Types: `controller`, `acquisition_node`, `synchronization_manager`.
- Genuinely isolated pair: `no_operational_dependents: true`, without that list
  or `result_window_s`. Never declare isolation falsely.

Keep node ID, Controller known-node registration, storage endpoint key and
dependent identity consistent. Device/product IDs are separate. Do not start
duplicate service identities. Explicit `known_nodes` may be empty; it does not
select a Session's participants and is not dynamic discovery.

Independent-role windows must be positive/finite. Shared-pair preservation window
may be zero, never negative/nonfinite. General paths resolve beside their JSON;
scientific/error paths in hardware JSON resolve beside that hardware file. Prefer
clear operator-chosen absolute paths. No live reload, environment substitution or
CLI/file merging exists. Invalid/unknown/duplicate fields and references fail.

`retrieval_endpoints` maps node ID to `host`, `username`, `key_filename`, optional
`port` (22) and `known_hosts_path`. Key/known-host references must exist on storage.
Loading does not authenticate/contact nodes. Retrieval uses Paramiko host-key
checking; do not disable it. An empty mapping does not enable later node collection.
Secrets/endpoints do not belong in portable scientific products.

Validate without connection or hardware initialization:

```text
python -c "from lab_sync_acquisition.deployment_configuration import load_service_configuration; load_service_configuration('CONTROLLER_JSON', 'controller'); print('configuration valid; readiness untested')"
```

Repeat for each role/path. Node validation also reads its hardware file without
opening a camera. Session IDs, scientific synchronization policy and Experiment
overrides belong to Session/Experiment configuration, not general-service files.

<a id="common-launcher-w061-closed"></a>
## 7. Existing General-Purpose Service CLI

Use `lab-sync-acquisition --help` or the equivalent
`python -m lab_sync_acquisition.service_launcher --help`. File-mode launch:

```text
lab-sync-acquisition ingestor --deployment-config STORAGE_JSON
lab-sync-acquisition synchronization-manager --deployment-config SYNC_JSON
lab-sync-acquisition acquisition-node --deployment-config NODE_SERVICE_JSON
lab-sync-acquisition controller --deployment-config CONTROLLER_JSON
```

`storage-manager` is an alias for the same paired process: do not start both
storage aliases as independent processes. File mode cannot mix explicit launch
settings; there is no override precedence. Flag mode also exists, for example:

```text
lab-sync-acquisition acquisition-node --server nats://BROKER_HOST:4222 --ingestor-id INTAKE_ID --storage-id STORAGE_ID --synchronization-id SYNC_ID --config HARDWARE_JSON --preservation-window-s 30 --result-window-s 10
```

The windows are illustrative inputs, not guarantees. Flag-mode node startup
defaults to `~/.config/lab-sync-acquisition/acquisition-node.json` if `--config`
is omitted. File mode requires `node_config`. No hidden peer owners, remote process
supervisor, broker management or Session/Experiment operator CLI is supplied.

<a id="remote-service-maintenance-w062-closed"></a>
### Maintenance Stop, Cancel And Kill

Ctrl+C in the service terminal requests local maintenance Stop with the OS username.
A blocked local Stop automatically Cancels its attempt and keeps running.
Failed/unconfirmed Stop also retains the process. Repeated interrupts never
authorize Kill. Interrupted startup is joined before maintenance.

From a separate activated terminal:

```text
lab-sync-acquisition stop --server nats://BROKER_HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN_ID --result-window-s 10
lab-sync-acquisition cancel --server nats://BROKER_HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN_ID --result-window-s 10 --stop-attempt-id BLOCKED_ATTEMPT_ID
lab-sync-acquisition kill --server nats://BROKER_HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN_ID --result-window-s 10 --stop-attempt-id BLOCKED_ATTEMPT_ID --authorize-kill
```

These are alternatives, not instructions to Kill after Cancel. Use the actual
blocked attempt returned by Stop. Target types: `controller`, `acquisition_node`,
`synchronization_manager`, `ingestor`, `storage_manager`. Remote maintenance
uses explicit inputs, not `--deployment-config`. Remote blocked Stop does not
automatically Cancel/escalate. Cancel ends its attempt without undoing completed
cleanup; its existing `failed` / `Administrator cancelled` outcome is nonzero.
Later Stop starts a new attempt. Kill is only a specifically authorized accepted
continuation, never automatic force escalation.

Inspect JSON identity, outcome, blockers, errors, remaining obligations and
`termination_confirmed`. Only confirmed successful maintenance returns zero.
Timeout/interruption can follow real execution: it proves neither retirement nor
nonexecution. Administrator/requester labels are evidence identities, not authentication.

Maintenance Stop is not Session Normal Stop, binding release or permission to
terminate the OS process. Launcher exit additionally requires final result handling
and connection cleanup. Subscription teardown retains pending obligations through
SDK-local closure, UNSUB/flush and callback/task completion; failure/cancellation
does not discharge them. Explicit retry reuses progress, not physical cleanup.

<a id="independent-role-startup-w063-closed"></a>
## 8. Individual Services, Maintenance And Restart

| Owner | Configuration/dependencies | Startup, verification and limits |
| --- | --- | --- |
| Controller | Controller JSON; intake, storage, synchronization and known nodes | Creates one Controller, registers its operational instance and reconciles current peers. All registered nodes need not be online; unreachable means unknown, not failed/stopped. Does not start Sessions or GUI. |
| AcquisitionNode | Service JSON plus hardware file; intake, storage and synchronization | Loads declarations/adapters without opening the camera, installs handlers, enables sustained execution for active Experiments. Inspect startup and `verify-node`; declared eligibility is not opened-camera proof. |
| SynchronizationManager | Synchronization JSON; intake and storage | Independent service/handler. Session clock/mappings begin through lifecycle commands, not process existence. Inspect current startup/dependency diagnostics. No dedicated synchronization CLI is invented. |
| Ingestor / StorageManager | Storage JSON; roots/journals/endpoints/actual dependents | One process, two NATS identities. Reconstructs journals and verifies ordinary framework archive continuation before restoring eligible dependent releases. No implicit corrupt-history repair. |

Use section 7's launch and maintenance commands with the exact owner identity.
Startup emits target/startup diagnostics. `Startup unconfirmed` after admission
can intentionally retain the process for maintenance; remaining alive is not ready.
Owners register with Ingestor before unrelated operational admission. Configured
peers use existing readiness requests/announcements and current responses, not
discovery or ownership-by-heartbeat.

For every role, resolve bindings, preservation and reported blockers before restart.
Storage retirement may be blocked by actual dependents; never omit them to force
exit. The pair prepares StorageManager, retires Ingestor, then completes prepared
storage retirement. One addressed owner's retirement does not prove pair exit.
Confirmed dependent release uses operational-instance/attempt identity and current
owner readback, not disappearance or publication acknowledgment (Decision 389).
Controller's specifically authorized prepared-shutdown dependency release is not
itself Controller retirement.

Safe restart means confirmed owner retirement, final result handling and launcher
exit followed by explicit relaunch with preserved paths/identities. Do not equate
killing a process with graceful restart. Controller restart neither stops safely
recording nodes nor automatically reconnects an interrupted Session.

If cleanup has already finished but final response publication/handling remains
unconfirmed, follow the launcher's reported original-command retry obligation.
Do not invent success, change command identity to repeat physical work, or assume
a fresh terminal invocation can replace every retained-command continuation.

### Durable State And Recovery Boundaries

Preserve journals, archives, handoffs, scientific roots,
`closed_sessions/records.json`, `closed_sessions.initialized` and JetStream history.
An interrupted `closed_sessions/publication.lock` fails closed; it is not an
expiring lease and must not be removed to assume a Session is open.

Ordinary startup validates intact historical archive prefixes before appending
recovery evidence (Decisions 389/390). Ordinary maintenance cannot overwrite
rejected history. Actual interrupted-write repair stays separately authorized under
Decisions 339/342/347; do not delete/recreate state as a repair shortcut.

Framework archives use administrative UTC archival-write months at
`<storage_root>/framework/evidence/YYYY-MM/`. Delayed/recovered evidence is not
backdated; original timing remains unchanged. Historical partitions stay immutable,
confirmation is cumulative, and recovery stays journal-backed. Retain history:
deletion independence/eligibility and broader memory retirement remain open under
Q024. Invalid clock, uncertain writes and corruption retain evidence and block
confirmation pending accepted reconciliation/recovery.

Current monthly recovery can repair an identified same-month interrupted target
through existing authorized mechanisms. Older or unidentified interrupted targets
remain retained and unconfirmed; ordinary new-month writing is not their repair.

The explicit Ingestor API `retire_recovery_journal(session_id)` is only for eligible
temporary Session journals under Decisions 349/392/393, after current permanent
closeout proof, terminal closure, binding release and no reconstruction/deduplication
need. It is not a generic CLI sweep. Framework journals, recordings, archives and
permanent closed-Session records are never its targets.
Normal post-retirement readback uses verified receipt provenance in the existing
compilation summary; partial Kill uses its existing preservation/uncertainty proof.
Historical products lacking that provenance may remain journal-dependent. Never
retire a journal merely because the Session has a terminal label.

## 9. Deployment Topologies And Startup Dependencies

Co-location does not alter lifecycle/transport. A small deployment may place
Controller, synchronization and the shared storage process on one computer with
nodes elsewhere, retaining separate processes/NATS boundaries. Never substitute
direct peer objects for a deployed Controller.

Simplest order: broker/JetStream, shared storage, synchronization and nodes, then
Controller. Peer checks are bounded and can initially report unknown while another
service is offline; inspect current diagnostics after peers are available.
This is manual sequencing, not an automatic deployment orchestrator.

Node startup can be used for early communication diagnosis after broker/storage;
synchronization readiness may remain unknown until its owner is available.
Retire dependent work before expecting shared storage retirement, preserving
Controller prepared-shutdown and evidence obligations. Never fabricate release
confirmation or declare nonexistent isolation.

## 10. Scientific Recording, Synchronization And Preservation

### Device Adapter Configuration And Selection

Node hardware JSON requires exactly `node_id`, `role`, `local_storage_root`,
`error_evidence_location`, `devices`. Each device has `adapter`, `declaration`,
`configuration`. The current file loader supports `seeed_imx219_opencv` only.
It uses explicit OpenCV `VideoCapture(source, backend)`; USB webcam compatibility
is platform/backend-dependent, not guaranteed by the adapter name.

Start with the complete [hardware example](../config_templates/manual_installation/acquisition-node.json).
Choose actual camera index/source, integer `api_preference`, positive
`frames_per_collect`, optional positive width/height/FPS. Declare scientific
product ID, `camera_frames` type, `hdf5` format, actual `frame_shape` and
`frame_dtype`. Illustrated `[480,640,3]`/`uint8` is not a device guarantee.
Backends may ignore requested dimensions/FPS; verify delivered data without
silently converting scientific observations.

Installation source/backend differ from Session baseline and per-Experiment
operating overrides. Existing inventory exposes adjustable parameter constraints;
`Controller.get_node_inventory()` uses NATS without initializing hardware.
A declaration makes a product available; explicit `ScientificOutputSelection`
selects it for an Experiment.

<a id="sustained-acquisition-execution-g3-closed"></a>
### Sustained Acquisition Execution (G3 Closed)

Production node startup enables one owned acquisition task. After activation,
selected scientific products record without repeated Controller iteration commands.
Idle intervals do not read frames. Controller disconnection alone does not stop
recording. Authorized cleanup joins execution and finalizes scientific products.
Camera failures retain partial data/failure evidence and attempt cleanup.
Synchronous device calls are not preemptible hardware deadline guarantees.

<a id="experiment-capacity-and-duration-g2-closed"></a>
### Experiment Capacity And Duration (G2 Closed)

Every Experiment requires `ExperimentConfiguration` with positive finite
`duration_s`, applicable node-keyed `recording_budgets`,
`preservation_budget_bytes` and optional node/device `device_configurations`.
Budgets cover complete writes, metadata and applicable storage/preservation
overhead; they are not guessed from available disk space. StorageManager checks
its actual evidence and configured scientific preservation roots. Shared-volume
accounting adds distinct writes without adding free capacity twice. Unknown or
insufficient capacity rejects activation; readiness is not a disk reservation.

A recording budget may be omitted only with a defensible supported estimate.
Camera estimation requires inclusive `storage_requirements.capacity_estimate`
fields `fixed_bytes`, `bytes_per_observation`, selected FPS/batch, consistent
shape/dtype and a per-observation bound at least as large as the raw frame.
It includes an in-flight batch:
`fixed_bytes + (ceil(duration_s * fps) + frames_per_collect) * bytes_per_observation`.
Preservation has no general estimator; supply its authoritative budget.
There are no invented compression ratios, rates or safety margins.

<a id="timing-and-synchronization"></a>
### Timing And Synchronization

Session configuration includes explicit plain-data `SynchronizationConfiguration`
fields: `exchanges`, `initial_scale`, `clock_rate_error_bound`,
`max_uncertainty_s`, `max_mapping_age_s`, `assessment_interval_s`,
`result_window_s`, `quality_interpretation`. Do not treat test tolerances as
measured physical accuracy. SynchronizationManager establishes mappings using
measured exchanges/uncertainty; nodes apply them locally. Preserve node-local,
available device-native, Session and Experiment times and mapping/quality evidence.
Ingest time never substitutes for acquisition time.

`assess_synchronization` and explicit `resynchronize` are distinct. Controller
sets a common Experiment start; nodes translate its duration deadline to monotonic
time. Expiry finalizes the Experiment, not the Session, and Controller reconciles
valid owner proof. `reconcile_launched_experiment_expiry(id)` supports missed
delivery readback. Later mapping changes/network loss do not reset the captured
deadline. Runtime duration extension is deferred.

### Scientific Storage, Retrieval And Closeout

Scientific observations/metadata remain in local JSONL/HDF5. Ingestor receives
operational lifecycle, health, timing evidence and manifests with durable
journal-before-ACK/deduplication. Publication ACK is neither full receipt nor
StorageManager preservation.

Normal Stop requires current scoped producer cleanup/publication proof, one
last-call marker, complete finalized acquisition intake and StorageManager-verified
Stage A evidence/record/handoff. Controller alone completes lifecycle; each owner
independently releases its binding after its obligations. Missing/corrupt proof,
cancellation and incomplete subscription teardown retain binding/obligations.
Readiness responses cannot prove execution of Stop.

Under Decisions 407/408, Normal Stop admitted first owns cleanup and may complete
despite independently accounted fatal health decisions if all completion guarantees
hold. Fatal closeout admitted first stays failed. Original context, durable decision
accounting, scientific-owner finalization and admission cutoff before immutable
intake remain mandatory. Explicit authorized Kill is distinct partial closeout,
not Normal Stop or proof of complete receipt.

Stage A retains evidence and a durable collection handoff; it does not automatically
copy Jetson frames. Later explicit StorageManager Stage B collection uses SSH/SFTP
and preserves collection outcomes. Permanent archive closure is another explicit
operation. Supported remote APIs include `collect_saved_session_artifacts_remote()`
and `close_saved_session_archive_remote()`; remote enumeration/batch collection
remains unimplemented. Abandonment is not permission to delete retained products.

## 11. Controller Session/Experiment Lifecycle And GUI

The service CLI starts/maintains Controller. The separate GUI is intended to
operate that same owner; GUI integration is pending. There is no requirement for
a separate Controller operator CLI and no defect implied by its absence.

| Purpose | Existing public Controller API |
| --- | --- |
| Inventory | `get_node_inventory(participant, communication=..., result_window_s=...)` |
| Session launch | `launch_session(selections, communication=..., participants=..., config_parameters=..., result_window_s=..., scientific_outputs=...)` |
| Session runtime start | `start_launched_session()` |
| Experiment activation | `start_launched_experiment(id, scientific_outputs=..., configuration=..., storage_participant=...)` |
| Experiment termination | `stop_launched_experiment(id)` |
| Normal closeout | `normal_stop_session(communication=..., storage_participant=..., result_window_s=...)` |
| Binding release | `release_session(communication=..., result_window_s=...)` |

These are integration API references, not shell commands or instructions to create
a second Controller. The existing production launcher retains its owner internally
and has no implemented GUI Session-command integration. This guide invents no
GUI transport, private-state attachment or temporary alternate lifecycle.

Launched operations require retained communication and scoped owner confirmations.
Historical in-process development APIs cannot operate on launched bindings.
`Controller.finalize_session()` and its exclusive completion pipeline were removed
under Decision 419. No replacement completion pipeline exists; standalone Session
primitives do not authorize deployed completion.

Decision 420 retains original-attempt resource cleanup after failed/cancelled
launch, not a recoverable failed Session. Before a subsequent launch it confirms
cleanup/availability or rejects before acquiring new reservations. A successful
new launch allocates a new Session identity. Successfully launched Sessions retain
their distinct failure/preservation/release obligations. Repeated physical Sessions
after terminal release remain a G5 validation target.

<a id="manual-installation-runbook-w067-closed"></a>
## 12. Incremental Validation And Troubleshooting

This is the current manual runbook. W067's example/CLI verification is not physical
commissioning. Use the actual account, revision, configuration and network; keep
installation results outside Git.

1. Inspect both installations and validate configuration.
2. Establish broker JetStream and cross-machine transport connectivity.
3. Start storage first; start node for early communication checks when needed.
   Full readiness may await synchronization/other peers.
4. Start/verify remaining mandatory services through existing CLI/diagnostics.
   Simplest full sequence places Controller after its peers.
5. Independently verify node communication, mandatory installation SSH/SFTP
   retrieval, physical camera initialization and scientific recording.
6. Verify permitted maintenance and confirmed restart without bypassing active work.
7. Once GUI integration exists, exercise the running Controller's launched lifecycle.
   That integration is currently a known blocker, not replaceable by a smoke script.
8. Verify distributed science/timing, preservation, release and a second new Session.
   These physical/distributed steps remain pending.

Device-specific acquisition checks are strongly recommended, not mandatory
framework certification states. Mandatory retrieval installation and ordinary
runtime readiness/preservation requirements remain distinct.

<a id="installation-node-communication-check-w066-closed"></a>
### Installation Node Communication Check (W066 Closed)

With target handler, broker and framework streams available:

```text
lab-sync-acquisition verify-node --deployment-config CONTROLLER_JSON --node-id NODE_ID
```

The ID must be in `known_nodes`. No Controller process is required; this creates
a temporary requester, not another owner. Exit zero requires a fresh correlated
response plus resource cleanup. `communication_confirmed` is separate from
`node_readiness`; a hardware-unready reply can confirm communication. Timeout
means unknown, not stopped. No stream provisioning, hardware initialization,
reservation, Session launch or maintenance is performed.

<a id="installation-retrieval-check-w065-closed"></a>
### Installation Retrieval Check (W065 Closed)

Provision key-based SSH/SFTP and independently verify the node host fingerprint.
Create a small operator-owned dummy file on the node and independently known exact
reference on storage. Do not use scientific artifacts or derive the reference
from the download.

```text
lab-sync-acquisition verify-retrieval --deployment-config STORAGE_JSON --node-id NODE_ID --source-path REMOTE_DUMMY_PATH --expected-file LOCAL_REFERENCE_PATH --max-bytes 4096
```

The illustrative positive bound must cover the actual dummy file. This reads
endpoint settings without NATS/storage startup and reports retrieval/content match;
only PASS is zero. It creates no Session, manifest, Stage A/B claim or certificate.
Remove only operator-created scratch files afterward.

### Troubleshooting

| Symptom | Check and safe response |
| --- | --- |
| Python/import failure | Inspect exact interpreter, `pip show`, `pip check`, checkout/package versions; avoid accidental system-package mixing |
| CLI absent | Activate environment or use its executable / `python -m lab_sync_acquisition.service_launcher` |
| Configuration rejected | Exact role/keys/windows/identities/path references; no variable expansion or CLI/file merging |
| Broker unreachable | Bind versus destination, DNS/IP, TCP port, inbound/egress rules, UAB routing; TCP alone is not JetStream |
| Connected but startup unconfirmed | Stream/consumer permissions, real peer IDs, current dependencies; retained process is not ready |
| Node reply but camera fails | Actual source/backend, exclusive access, permissions and `cv2` environment; declared eligibility is not opened-camera proof |
| Scientific configuration/budget error | Supply current explicit smoke flags; never insert invented defaults or bypass preflight |
| Shape mismatch/no frames | Verify delivered format and declarations; retain partial scientific products and original diagnostics |
| Capacity unknown/insufficient | Inspect all destination volumes, permissions and complete budgets; a network share is not presumed independent capacity |
| Hard-link/archive write failure | Retain archive/journal bytes and bindings; inspect actual filesystem/account; never seed fake proof or overwrite rejected history |
| SSH/SFTP failure | Node SSH service, routing, port, account, key, trusted host key and source path; never disable host-key checks |
| Stop blocked/result lost | Inspect exact attempt/obligations; permitted Cancel or explicit retry, not automatic Kill/process termination |
| Corrupt history/invalid clock | Retain evidence; existing authorized reconciliation/repair only, not directory reset |
| No Session command in service CLI | Expected responsibility separation; GUI integration pending |

## 13. G5 Worked Example: Windows PC And Jetson USB Webcam

This is a worked placement, not general camera/Controller policy. Current UAB
networking and a possible later switch affect addressing, not framework lifecycle.

| Computer | Processes |
| --- | --- |
| Windows | Operator-managed NATS/JetStream; Controller; SynchronizationManager; one combined Ingestor/StorageManager process |
| Jetson Ubuntu | AcquisitionNode, USB webcam, local scientific storage and SSH/SFTP endpoint |

Obtain actual broker interface/address/port, Jetson SSH address/account/fingerprint,
checkout/`.venv` paths, Python/JetPack/OpenCV versions, source/backend/delivered frame
format, writable disk roots/capacity, owner/device/product IDs, synchronization
policy and duration/budgets. Never invent equipment values or commit private files.

### Windows PowerShell

Inspect the existing checkout:

```powershell
Set-Location WINDOWS_CHECKOUT_PATH
git status --short
git rev-parse HEAD
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show lab-sync-acquisition
.\.venv\Scripts\python.exe -m pip check
```

After the safe maintenance/revision review in section 4:

```powershell
git fetch origin
git checkout DEPLOYMENT_REVISION
.\.venv\Scripts\python.exe -m pip install ".[artifact-retrieval]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\Activate.ps1
```

Configure/start NATS per section 5. Copy/edit Controller, synchronization and storage
JSON outside Git, including actual external dependents. In separate activated
terminals run section 7's storage, synchronization and Controller commands,
coordinating node startup below. Controller is not an interactive Session shell.
Perform fresh communication/retrieval verification from section 12.

### Jetson Linux Shell

The Jetson already has a checkout and `.venv`; do not clone/recreate unnecessarily:

```bash
cd JETSON_CHECKOUT_PATH
git status --short
git rev-parse HEAD
.venv/bin/python --version
.venv/bin/python -m pip show lab-sync-acquisition
.venv/bin/python -m pip check
```

After safe retirement and review of changes, reuse a compatible environment:

```bash
git fetch origin
git checkout DEPLOYMENT_REVISION
.venv/bin/python -m pip install .
.venv/bin/python -m pip check
source .venv/bin/activate
python -c "import cv2; print(cv2.__version__)"
```

With exclusive camera access before node reservation/initialization:

```bash
python scripts/manual_opencv_camera_smoke.py 0
python scripts/manual_opencv_camera_smoke.py 0 --scientific --duration 3 --recording-budget-bytes 100000000 --preservation-budget-bytes 100000000 --output-dir /ABSOLUTE/SMOKE_OUTPUT_PATH
```

Source `0` and **100,000,000-byte budgets each are illustrative**, not measured
requirements. Choose actual inclusive budgets. Readiness mode reports
`device_ready=true` and `scientific_observations=0` without reads. Scientific mode
requires budgets, supplies existing `ExperimentConfiguration`, handles expiry
without duplicate termination, and reopens finalized HDF5 to verify nonempty
frames, indices, shape/dtype, aligned timing, identity and manifest counts.
`validation=PASS` requires verification and cleanup; failures preserve partial
products/diagnostics. It does not complete a deployed Session.

This uses the existing local development composition, not Controller/NATS
deployment validation. Simplest procedure: finish smoke testing before node
startup. Never compete with an active reservation/camera owner.
Optional `--show-frames` requires Matplotlib. Existing-file inspection needs no
camera or Session:

```bash
python scripts/manual_opencv_camera_smoke.py --view-hdf5 /ABSOLUTE/RECORDING/frames.h5
lab-sync-acquisition acquisition-node --deployment-config /ABSOLUTE/NODE_SERVICE.json
```

The user reported Jetson readiness-only success. Corrected scientific recording
still needs independent hardware confirmation. Inspect startup, fresh checks and
maintenance/restart. Distributed recording/preservation/release and new-Session
repeat await actual GUI integration and physical validation. Do not introduce
another Controller or temporary interface to skip that gate.

## 14. Known Limitations And Historical References

| Area | Current scope and preserved evidence |
| --- | --- |
| Installation/service CLI | W061-W067 CLOSED software scopes: lifetime, maintenance, independent launching, files, retrieval/communication and examples. W063 includes 60/60 independent checks; W067 4/4. Not physical provisioning proof. |
| External dependents | W068 CLOSED after Decisions 389/390 integration, 3/3 manual scenarios and final audit PASS; preserve maintenance-write bypass correction history. |
| Parameters | W069 CLOSED after 6/6 and 9/9 independent checks/audit PASS. Its boundary probe encountered unrelated storage configuration; not full initialization proof. |
| Journals/archives | W070A/B CLOSED; W071 monthly slice CLOSED after 59 implementation and 6/6 ICC checks. Deletion independence and broader Q024 retirement remain open. |
| Routing/timing/closeout | W051/W052 historical envelopes superseded for routine observations by W053-W055. W056 timing, W057 intake, W058 collection, W059 closure and W060 distributed closeout are completed bounded scopes, not missing launch prerequisites. |
| G2/G3 | Capacity/deadlines and sustained execution CLOSED software scopes; physical timing/performance still unverified. |
| G4/Q013 | G4-A/B/C CLOSED software scopes. G4-A at `2672879`; G4-B re-audit 14 checks; G4-C ICC 12/12 and independent re-audit at `9f6f73b` 16/16 scenarios plus four regression checks PASS, both P2 findings resolved. |
| GUI integration | Known pending integration for operator interaction with the running Controller, not a requirement for another CLI. |
| Physical G5 | Multi-host NATS, SSH/SFTP, scientific webcam recording, synchronization quality, preservation/release and repeated Sessions pending. Readiness-only success is narrower. |

Counts overlap; do not add historical campaigns. Original FAIL reports,
corrections, audits and limitations remain in [validated_workflows.md](validated_workflows.md),
[framework_milestones.md](framework_milestones.md) and [open_questions.md](open_questions.md).
This guide consolidates superseded operational assessments, not accepted decisions
or historical evidence.

For maintenance of this guide, verify interfaces against
[the CLI](../src/lab_sync_acquisition/service_launcher.py),
[role composition](../src/lab_sync_acquisition/service_startup.py),
[configuration validation](../src/lab_sync_acquisition/deployment_configuration.py),
[Controller APIs](../src/lab_sync_acquisition/controller.py) and
[the smoke script](../scripts/manual_opencv_camera_smoke.py), rather than treating
historical prose as a current implementation specification.

Nine previously Windows hard-link-blocked checks remain unconfirmed, not passes.
Initial hard-link promotion was not independently established by final G4 checks,
which used existing-identical handoffs. Broader cancellation/replacement and G2/G3
were not exhaustively revalidated by the final G4-A audit. Controlled checks do
not establish target live NATS/SSH/hardware, OS-signal, power-loss or normal Windows
asyncio scheduling validation. Earlier real local-JetStream tests are not multi-host
certification. The smoke correction has 14 passing software methods and seven
Matplotlib skips, not physical/independent validation or closure.

No automatic supervisor/restart, discovery, dynamic addressing, generalized
network-filesystem capacity coordination, Session reconnection, historical deletion
or GUI integration is promised. The webcam is a temporary validation device.
This guide update closes no milestone and starts no implementation slice.
