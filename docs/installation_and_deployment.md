# Installation And Deployment

**November 24, 2026 architecture update; November 27 final clarification, not deployment instructions:**
[Decision 456](architecture_decisions.md#decision-456-communication-retention-scientific-preservation-and-operational-recovery-have-distinct-lifetimes)
separates broker delivery obligations, permanent scientific evidence and temporary
operational recovery. Permanent Ingestor intake auditing is no longer required;
obsolete recovery information must be eligible for retirement after applicable
obligations resolve. The final accepted
[Decision 457](architecture_decisions.md#decision-457-native-delivery-interests-and-selective-evidence-retention-bound-operational-recovery)
specifies the exact 14 persistent/six nonpersistent assignments, InterestPolicy,
durable required service consumers/non-durable GUI consumers, recipient-addressed
results, history-independent delivery/owner outcomes and crash-safe compaction at
existing checkpoint boundaries. Implementation, validation and safe treatment of
existing data remain pending. Do not enable InterestPolicy before required
interests exist and acknowledged-history dependencies are removed. In-place
conversion is reported supported, not validated; no conversion or migration is
authorized here. Existing journal/audit/checkpoint descriptions
below document current or historical behavior, not compliance with the amendment.
Do not change JetStream, delete state or bypass preservation checks on this basis.
The [destructive test-reset record](deployment_test_reset.md) remains historical
evidence, not an implementation or migration procedure for Decision 456.

## Accepted graphical installer direction (Decision 453; implementation deferred)

**Development priority:** Decision 453 remains accepted and unchanged. Technical
investigation, implementation design review and preliminary Windows packaging
feasibility assessment are complete. GI-A/C, GI-B, GI-D, GI-E and GI-F functionality,
further packaging feasibility tests and installer initialization-default selection
are intentionally deferred. The existing CLI installer remains the deployment
mechanism while the scientific framework and operational GUI are completed and
validated. Resume through ICC when the relevant service, configuration, storage,
GUI and deployment contracts are sufficiently stable and operationally validated.

[Decision 453](architecture_decisions.md#decision-453-self-contained-graphical-installation-shares-cli-operations-and-permits-bounded-local-nats-provisioning)
accepts a self-contained Tkinter/ttk installer with a managed Python 3.12 runtime
and packaged dependencies, retaining the CLI over shared installation operations.
The seven steps are computer functions, NATS configuration, role configuration,
scientific storage, optional Advanced Settings, review/install and truthful
completion. GUI-only, NATS-only and combined roles are included. Intended Windows
x86-64, Linux x86-64 and ARM64/Jetson support still requires platform verification.

The accepted future installer may discover/provision a separate local NATS
instance and, with explicit choices, start it and configure OS startup. New
instances prepare required authentication, permissions, persistent storage and
Controller claim-store prerequisites without acquiring Controller authority or
modifying existing servers. This narrowly qualifies earlier external-NATS
exclusions; the currently implemented CLI still does not provision NATS.

One versioned non-secret laboratory connection file carries necessary shared
configuration and upfront service identities, never credentials, local paths,
catalogs or synchronization settings. Credentials use separate protected inputs.
Software may be installed with configuration explicitly incomplete; reopening
finishes configuration without reinstalling. Invalid files must never be published.
Existing update/retirement, preservation and Decision 445 confidentiality checks
remain mandatory. Decisions 451/452 supply existing synchronization initialization
and catalog persistence; updates must preserve their saved administrative data.

The following procedures describe existing implementations and historical evidence,
not the future installer's availability. Scientific framework services and the
operational GUI must not be launched/restarted by the installer. No deployment,
implementation or compatibility validation is established by this synchronization.

### Retained graphical installer design and preliminary feasibility

This is a planning/evidence record, not implementation authorization or closure.
The source-grounded technical investigation used `2950c002e813c37e2075920c87b834aa6c9e3478`;
the preliminary Windows feasibility assessment used
`483324b83a0cf0b55ad74ca4231124ca8ecff9cd`. Preserve the following conclusions when
work resumes rather than repeating the full investigation:

- **GI-A/C together:** Extract shared discovery, planning and execution from the
  existing CLI; retain authoritative configuration loaders, credential validation,
  durable publication, cancellation and update/retirement safeguards. Support
  software-only/incomplete configuration and reopening without unnecessary
  reinstallation. Do not build a parallel installer or persistent wizard database.
- **GI-B:** Adapt one strict versioned non-secret file to existing role consumers.
  The proposed minimum uses endpoints, authority account/bucket/key, stable core
  service/GUI-client identities and explicit node declarations. Exact role-specific
  derivation and validation still require review before implementation. Preserve
  separate local credentials, existing identities and Controller authorization;
  do not introduce distributed configuration or repeated unnecessary transfers.
- **GI-D/E:** Keep bounded local NATS provisioning/OS integration distinct from the
  seven-step Tkinter frontend. Reuse shared operations; never launch framework
  services or the operational GUI. Preserve existing servers and scientific data.
- **GI-F:** Use a clean managed Python 3.12 runtime with Tcl/Tk, separately packaged
  core/GUI wheels and platform-specific native dependencies. Start with a
  diagnosable one-folder executable candidate; a frozen frontend does not replace
  the normal managed interpreter needed by service launch commands. Clean upstream
  runtime/wheel provenance, licenses, checksums and target compatibility still need
  verification; existing development/application binaries are not release payloads.
- **Decisions 451/452:** Reuse the single synchronization defaults definition,
  validator, initialization boundary and existing GUI catalog/settings persistence.
  Preserve saved administrative settings, catalog ownership/removal safeguards,
  revision protection and historical identities; no duplicate defaults or stores.

Preliminary Windows observations: the development environment had Anaconda Python
3.12.13, nats-py 2.15.0, NumPy 2.5.3, h5py 3.16.0, aiohttp 3.14.5 and Paramiko 4.0.0;
PyInstaller/cx-Freeze and OpenCV were unavailable there. A disposable copy of an
already available Python 3.12.14 runtime ran independently of Conda/Python path
settings, initialized Tcl 8.6.12 and SSL, and passed SQLite write/read. A copied
NATS 2.14.3 executable passed `--version` only; no broker was started.

Copying the complete installed dependency set failed at NumPy native loading:
that development build depends on external Conda/MKL DLLs. HDF5 and framework/GUI
imports were not reached in that probe. This supports clean binary-wheel assembly,
not cloning Conda. No clean upstream download/install, frozen Tk executable,
graphical rendering, fresh-account/VM installation, authenticated NATS operation,
Linux/ARM64 or Jetson compatibility was established. Further feasibility work is
deferred, not passed. Source-supported packaging candidates are not qualified
release versions or redistribution approval.

Initialization findings: generic templates contain null preservation/result
windows; manual examples explicitly label 30/10 seconds illustrative, not accepted
defaults. Repository deployment evidence does not establish the values used by
the successful distributed run. Reuse saved operational configuration; choosing
new initialization values remains deferred. Decision 444's accepted 180-second
registration budget remains unchanged, and Decision 451's scientific result window
must not be reused as a maintenance/preservation default.

Decision 451's GUI synchronization initialization uses one backend-owned definition:
exchanges 3, initial scale 1.0, clock-rate error bound 0.001, maximum uncertainty
0.5 s, maximum mapping age 20 s, assessment interval 5 s, result window 2 s,
quality interpretation warning. These approved initial software defaults are not
experimentally validated laboratory tolerances. Installation initializes absent
settings, with optional Advanced Settings overrides; updates preserve saved
administrative settings. Existing backends initialize missing values without
mandatory manual first-run setup. Malformed saved values must be reported, not
silently reset. The future graphical installer reuses the same mechanism.

Windows operators: [CMD deployment quick runbook](#windows-cmd-deployment-quick-runbook).

## Controller replacement authority — Package 1 implementation

Decision 436 Package 1 adds manual occupied-claim recovery and service-side
Controller registration/admission and is CLOSED at
`994119f6ece36172c28456c51b4b6cd7565c9d8e` after developer tests, independent ICC
live-JetStream validation and independent Codex re-audit PASS. See the
[validation scope and limitations](validated_workflows.md#q024-package-1---controller-replacement-authority).
This does not certify an installation. Package 2 service-owned disposition and
monthly recovery is now CLOSED; see its
[audit scope and validation exception](validated_workflows.md#q024-package-2---service-owned-disposition-and-monthly-recovery).
Q024 remains OPEN for deferred Decision 435 and broader Decision 353 retirement
beyond redundant working copies; no new deployment/recovery procedure is added here.

Every participating service configuration now supplies the same explicit
`controller_claim_account`, `controller_claim_bucket` and `controller_claim_key`,
plus a positive `result_window_s`. These settings apply to Acquisition Node,
Synchronization Manager and the paired Ingestor/Storage Manager as well as
Controller. Explicit CLI launches use the corresponding
`--controller-claim-account`, `--controller-claim-bucket`,
`--controller-claim-key` and `--result-window-s` flags. Do not mix these flags with
`--deployment-config`. Existing account, persistent/non-expiring storage,
durability and retained-history prerequisites continue to apply; the framework
does not provision or resize the authority bucket.

Inspect an occupied claim using the installed entry point, substituting the
installation's actual server/account/bucket/key:

```text
lab-sync-acquisition inspect-controller-claim --server nats://HOST:4222 --controller-claim-account ACCOUNT --controller-claim-bucket BUCKET --controller-claim-key KEY --result-window-s 5
```

Independently verify termination of the exact reported Controller operational
instance using host/process evidence. Readiness, network silence, Stop/Kill
acknowledgments and operational retirement alone do not prove OS-process
termination. If termination or instance matching cannot be verified, retain the
claim. The framework does not introduce a remote process supervisor.

Only after that verification, explicitly authorize clearing the inspected owner
and revision:

```text
lab-sync-acquisition clear-controller-claim --server nats://HOST:4222 --controller-claim-account ACCOUNT --controller-claim-bucket BUCKET --controller-claim-key KEY --result-window-s 5 --claim-owner INSPECTED_INSTANCE_ID --claim-revision INSPECTED_REVISION --administrator-id OPERATOR --authorize-claim-clear --verify-prior-termination --termination-evidence "Independent host/process verification reference"
```

The termination flag and evidence reference are an operator attestation, not
automatic process detection. Clearing compares the exact inspected owner/revision
and uses revision-conditional deletion. Changed claims, unavailable storage,
cancellation or missing acknowledgments do not confirm successful recovery.
Never substitute a newly observed revision automatically or clear a replacement's
claim to resolve uncertainty. Manual clearing does not start a Controller.

Ordinary interactive Controller startup now offers this same manual recovery after
a definitive occupied-key refusal (developer implementation; independent validation
and audit pending). It displays the exact inspected scope/owner/revision, requires
administrator identity, independent installation-wide termination verification,
an evidence reference and explicit clearing authorization. Blank input, EOF and
non-interactive startup authorize nothing. Only confirmed conditional clearing
permits one subsequent ordinary acquisition; a changed claim or uncertain outcome
stops startup. Acquisition timeout/cancellation never resets its one-attempt guard.
There is no automatic takeover, process termination or new authority mechanism.

Once the replacement acquires authority, its transport obtains a fresh
registration acknowledgment from each service needed for an operation. The
acknowledgment and command identify that service's operational lifetime. Restarted
services require reconfirmation; superseded Controller commands are rejected
before execution or cached-result replay. Existing admitted work, Session
ownership, producer evidence and administrator maintenance remain intact. An
unavailable unrelated service does not prevent registration with another service.
Transport reconnection does not transfer authority or reconstruct a Session.

### Package 1 programmatic interfaces

`NatsCommunicationBoundary` retains its existing constructor
`(component_type, component_id, servers=("nats://127.0.0.1:4222",))` and adds:

```python
configure_controller_authority(*, account, bucket, key, timeout_s)  # explicit immutable scope
await inspect_controller_claim(*, account, bucket, key, timeout_s)  # ControllerClaimSnapshot
await clear_controller_claim(snapshot, *, administrator_id, authorized,
    termination_verified, termination_evidence, timeout_s)  # None; uncertainty raises
await register_controller(participant, *, result_window_s)  # acknowledged instance identities
```

The exported frozen `ControllerClaimSnapshot(account, bucket, key,
operational_instance_id, revision)` exposes those five fields. Service-side
`ControllerCommandAdmission(maintenance)` is a shared implementation component;
`register(command, snapshot)` and `admit(command)` use the existing owner admission
lock, with volatile `recognized` state and no separate durable registry.
`ServiceMaintenanceInterface` retains its constructor and existing public methods;
its readiness diagnostics now include `recognized_controller` (initially `None`).

The plain-data constructors gain optional correlation fields:

```python
RuntimeCommandMessage(command_id, session_id, command_type, source_id, target_id, payload,
    issuer_type=None, controller_instance_id=None, controller_claim_revision=None,
    receiver_instance_id=None)
RuntimeCommandResultMessage(result_id, command_id, session_id, source_id, target_id,
    status, success, reason, payload, controller_instance_id=None)
```

Delivery-lifetime metadata is checked before existing command caches; logical
histories and results retain Controller-instance ownership. A replacement cannot
accept an old owner's operational reply merely because its component or command
ID matches. Readback and service-owned preservation retain their existing scope
and correlation checks. Independent administrator traffic retains existing
operation-specific authorization; issuer metadata is not a new authentication
system.

The terminal implementation also exposes
`recover_controller_claim(*, servers, account, bucket, key, timeout_s, clear=False,
expected_owner=None, expected_revision=None, administrator_id=None,
authorized=False, termination_verified=False, termination_evidence=None,
report=print)`. It returns `0` on confirmed inspection/clearing and raises on
uncertainty; the installed CLI reports failure with a nonzero exit status.
Both launch functions now require explicit claim settings, and paired storage
startup also requires a positive `result_window_s`; no new defaults provision
authority storage.

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
software scope is CLOSED. Phase 16 operational software scope is CLOSED using
W035-W038; Q022, Q024 and M015 remain OPEN. The November 23, 2026 Ubuntu-Jetson
report establishes bounded real-camera acquisition/readable HDF5 and sequential
Session execution, not complete G5 or historical-collection validation. G5 remains
incomplete. Historical findings and counts remain in [validated workflows](validated_workflows.md#november-23-2026-ubuntu-jetson-acquisition-and-sequential-execution)
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
| `nats-server` with JetStream | External operational dependency, separate from the Python client; online availability is not a software-installation gate under Decision 440 |
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

### Guided Setup From An Existing Checkout (Decision 421)

**CLOSED within validated and independently audited software scope (Decision 446):**
The existing planner follows Discover ->
Present findings -> Confirm or choose -> Validate -> Configure. It inspects local
role files first and offers new-laboratory versus add/update-computer choices.
An explicitly selected existing service JSON can supply shared identities, timing
settings, declared participants, authority scope and endpoint candidates, not
foreign credentials or computer-specific paths. Conflicting local/imported scope
is rejected; existing local files are never overwritten. Imported shared fields
are checked before presentation; full authoritative role validation still applies
to the resulting local configurations.

One NATS candidate requires confirmation; multiple candidates require explicit
selection, preserving the chosen URL order and existing SDK selection behavior.
No network scanning, speculative endpoint probing or broker provisioning occurs.
When no endpoint is known, supply the administrator's address through hidden input.
Reachability never establishes laboratory membership. For new systems, the
installer attempts `$SYS.REQ.USER.INFO` using a selected connection after credential
entry. Successful authenticated readback can supply the account for confirmation;
denied/offline/unverified readback cannot invent it. Supply a known administrator-
provided account to continue offline with valid configuration. Conventional
`controller_authority` / `controller` bucket/key names are proposals for explicit
confirmation, not newly created resources or defaults for joining an existing lab.
Offline installation and Decisions 440/445 remain unchanged.
See [Decision 446](architecture_decisions.md#decision-446-guided-installation-discovers-configuration-before-requesting-operator-choices).

The role menu offers `ingestor-storage` as one default-selected job: both logical
services use the existing `storage-services.json` and single `ingestor` launcher.
Legacy `ingestor`/`storage-manager` inputs still select that same pair, not separate
deployments. Local endpoint discovery excludes credentials and treats hostname
case, default ports and root-path spelling consistently. Existing service files,
URL order and service-specific authentication remain unchanged. Distinct local
address lists require explicit selection for new roles; credentials are entered
separately for each new role and are never inherited from another service.
An existing paired service may retain a zero preservation window. Adding an
independent service then requests a positive window for that new role only;
applicable positive values are reused and authoritative validation still applies.
Independent Ubuntu existing-laboratory installation and Windows re-audit PASS are
recorded in the [closure evidence](validated_workflows.md#decision-446---guided-installer-software-scope),
including the preservation-window P2 correction and four-file audit overlay.
Live Ubuntu validation of the corrected scenario is DEFERRED, not passed.
The earlier connection/cleanup warning has no established cause; TCP reachability
did not establish authenticated connectivity for that installer run.
Software installation remains distinct from operational readiness and broader
deployment validation; Q022 remains OPEN.

Role selection accepts existing role names or displayed numbers: Controller,
attached-equipment AcquisitionNode, SynchronizationManager, and paired data intake/
storage. Existing settings are reused; missing local hardware leaves that role
deferred. Bounded local hardware/key/host-file candidates require confirmation;
file existence does not prove device availability or SSH trust. Declared dependency
candidates are shown with readable roles and can be selected by number; `none`
still requires a genuinely isolated pair. Final findings hide credentials and
show selected scope, paths, timing windows and pending prerequisites. Existing
retirement attestation and final installation consent remain mandatory.

**Session artifact destinations (Decision 450 Package A): framework implemented;
independent validation/audit and GUI integration pending.** The configured
`global_artifact_root` remains the default. StorageManager owns approved additional
directories and immutable Session bindings; new distributed Sessions submit an
approved identity in `SessionConfig.storage_location`, not a path. Controller
requires correlated StorageManager admission before launch success, in addition
to exact initial Session Record preservation. Administrator registration/update
and destination listing use existing Controller/NATS interfaces. Additional
directories must already exist and be suitable; no mounting, disk provisioning
or migration is performed. Disabling a destination prevents new admissions, not
existing collection/recovery; removal is refused for retained bindings. An
unavailable bound directory never falls back. Legacy Sessions retain the existing
installation-root interpretation rather than reinterpreting historical free text.
The owner registry and binding records remain under `storage_root`, separate from
scientific artifacts, node-local recording and Ingestor journals. New accepted
Session configuration records mark that a binding is required; missing bindings
fail closed. This does not authorize GUI Package B or certify operational disks.

**Scientific storage selection (Decision 447-A): implemented; independent validation
and audit pending.** Guided setup presents retained storage paths and read-only
local volume candidates, with filesystem free bytes when available. Ubuntu uses
recognized local mounted filesystems; Windows uses native local drive metadata.
An explicitly confirmed primary destination supplies separate `records`,
`artifacts`, `journals` and `framework.jsonl` paths for a new paired configuration.
The labelled fallback is `CONFIG_DIR/data` on the configuration filesystem, not
an automatically selected largest/dedicated disk. Manual paths are supported.

Discovery creates no directories or probe files. Missing targets, inaccessible
paths and unknown capacity are reported without treating parent free space as
proof of an intended mount or writable scientific destination. Backing identity
is rechecked after selection, after installation consent and before storage
directory creation. Existing paired and AcquisitionNode paths remain unchanged;
node hardware configuration retains its separate contract. Directory creation is
post-confirmation only, and failure does not relocate or overwrite existing data.
Access metadata and directory creation do not establish persistence, future
Experiment capacity or operational readiness. Quotas, physical disk failures and
all filesystem races are not certified by installation. Unlisted destinations may
be entered explicitly; no disk formatting, partitioning, mounting or migration occurs.

**Optional GUI setup (Decision 447-B): implemented; independent validation and
audit pending.** The installer discovers checkout availability and installed
`miceball-gui` metadata, offers separate package installation or explicit reuse,
and leaves core-only installation supported. GUI validation constructs the existing
app without starting it, with mandatory installed-package/dependency validation
before configuration publication.

Connection settings use the existing connection-file contract (default
`CONFIG_DIR/gui-connection.json`). Existing files are preserved; new GUI credentials
are entered separately, never copied silently from service configurations. Confirm
Controller/client identity, bind host/port, exact browser origin and request timeout.
The installer prints a native-shell `python -m miceball_gui.backend` command with
`--deployment-config`, not passwords, and the confirmed browser address.

Already suitable local Controller files are not rewritten. Otherwise the exact
`external_client_id` / `browser_control_required` changes require explicit approval,
complete staged validation, retained unrelated values and unchanged-file checks
before a narrow replacement. Normal new-file publication remains exclusive.
Windows replacement preserves native access controls; POSIX replacement retains
owner/mode and checks security metadata. On an unconfirmed Windows replacement,
a protected `.gui-controller-backup-*` file may remain for operator recovery;
inspect retained files before restarting. This is not a general replacement API.
Declined changes or a remote Controller remain explicitly pending on the owning
computer; imported files are not edited remotely. Restart instructions are manual.
No automatic disk provisioning, data relocation, service restart, Controller claim
or scientific operation is authorized. GUI-free service installation remains
supported. See [Decision 447](architecture_decisions.md#decision-447-guided-installation-selects-scientific-storage-and-optionally-prepares-the-separate-gui-package).
Independent validation/audit of both additions remain pending. Developer checks
do not extend Decision 446's closed evidence or
certify Ubuntu deployment. The current Ubuntu/Jetson deployment is unchanged;
Q022 remains OPEN.

The existing `scripts/install_framework.py` prepares one local installation; it
does not start or supervise services. Use Python 3.12 on Windows or Linux, from
the reviewed checkout. It reuses a compatible checkout-local `.venv` or creates
one; an unrelated activated environment is not the target environment. Python,
Git, nats-py and applicable local configuration inputs remain installation
prerequisites. NATS is an external operational dependency, not an online-broker
requirement for software installation under accepted Decision 440.

**Implementation status:** Decision 440 supersedes only Decision 439's mandatory
broker-connectivity gate. The bounded correction now reports failed/unverified
connection or cleanup as PENDING / NOT VERIFIED and continues installation after
confirmation. Required local prerequisites and configuration validation still
block on failure. Developer verification is complete; independent validation,
audit and actual Ubuntu installation remain pending.

| Boundary | Accepted contract |
| --- | --- |
| Software installation | Required local prerequisites and confirmation apply; an operational broker is not required |
| Deployment configuration | Required fields, including NATS URLs, must validate; validity does not prove remote resources exist or are usable |
| Operational connectivity | Attempt verification when possible; unavailable/unverified results are PENDING / NOT VERIFIED and do not block installation |
| Actual service readiness | Existing runtime readiness and admission apply; Controller operation still requires Decision 436 authority |

**Prepare the verification interpreter first.** If this checkout already has a
compatible `.venv`, the installer uses that interpreter for its immediate `nats`
import and broker check. Otherwise it uses the Python 3.12 interpreter running
the script. It does not silently switch interpreters when nats-py is missing.
Verify the applicable interpreter before starting:

```bash
# Ubuntu: existing checkout-local environment, or invoking Python if no .venv exists
.venv/bin/python -I -B -c 'import nats; print("nats import OK")'
python3.12 -I -B -c 'import nats; print("nats import OK")'
```

```powershell
# Windows: choose the applicable one, not both
.\.venv\Scripts\python.exe -I -B -c "import nats; print('nats import OK')"
py -3.12 -I -B -c "import nats; print('nats import OK')"
```

If import fails, stop and have nats-py `>=2.15,<3` explicitly provided in that
interpreter outside the installer. Where package installation into that interpreter
is permitted, use its `-m pip install "nats-py>=2.15,<3"` command. On an
externally managed Ubuntu system Python, do not use `sudo pip` or bypass system
package protection: use an already prepared compatible Python installation or
normal lab-managed Python environment. The installer does not create a temporary
verification environment. Import success is not broker readiness. Prepare the
[external broker](#5-nats--jetstream-and-networking) before operation, not as a
software-installation gate.

For the Ubuntu computer hosting **both Ingestor and StorageManager**, run from
the repository root:

```bash
python3.12 scripts/install_framework.py --config-dir "$HOME/.config/lab-sync-acquisition"
```

At the local-role prompt choose `ingestor` (or `storage-manager`), not two
processes. Add `controller synchronization-manager` if those roles also belong
on this computer. New identifiers offer editable defaults (`ingestor-1`,
`storage-manager-1`, `controller-1`, `synchronization-manager-1`); Enter accepts
the displayed value. These are proposed names, not automatic allocation or
discovery: use the same actual identities throughout the deployment.
Supply the deployment's actual NATS URL(s), Ingestor/StorageManager
identities, shared Controller authority account/bucket/key, preservation window,
positive result window, and storage directory. The account is the real NATS
account ID, not a display name. The persistent authority bucket must exist and
satisfy Decision 436 before Controller operation; merely installing configuration
does not verify it. Reuse the same authority settings on every participating computer.
Declare actual external dependents as comma-separated `TYPE/ID` entries using
`controller`, `acquisition_node` and `synchronization_manager`. Use `none` only
for a genuinely isolated pair, never for an offline but configured dependent.
For collection, provide each node's SSH host/user, existing private key, port and
verified known-hosts file (or already configured system host keys). Empty
retrieval endpoints do not establish collection capability.

Valid existing files and deployment-specific settings are preserved byte-for-byte;
missing files are generated, not existing files silently migrated. Incompatible
existing configuration must be resolved explicitly. Shared identity/authority
disagreements block setup. All required values are collected first. The selected
checkout's authoritative loader checks generated and existing files before the
installation plan/confirmation when its dependencies are
available in the target or bootstrap interpreter. Missing import dependencies
defer that preflight explicitly; validation remains mandatory after installation
and before publishing new configuration. Other validation failures block setup.
Generated validation inputs use disposable temporary storage, not final config
or scientific directories. Existing files retain their original relative-path base.
Under Decision 440, missing required local prerequisites such as nats-py block
setup. Failed/unavailable broker verification instead leaves operational
connectivity PENDING / NOT VERIFIED and allows the normal installation plan,
confirmation, environment/dependency preparation and valid configuration
publication. No broker, Jetson or other framework service need be online for
software installation. Successful connectivity is reported only after verified
connection and cleanup. There is no alternate mode or installer-owned broker
management; the existing bounded connection check is unchanged.
Installing without NATS connectivity does not remove pip's normal requirement
for dependencies to be available from a package source or existing cache.
Updates require confirmation that affected services have retired with their
obligations resolved. No transactional package rollback is claimed.

After setup, inspect the report and generated `storage-services.json`. Exit `0`
means setup checks passed without reported pending/deferred work, `2` means
pending/deferred work or a declined plan, `1` means a blocking local prerequisite,
configuration or installation error, and `130` means operator cancellation.
Installation can complete and publish valid configuration with exit `2` when
NATS remains PENDING / NOT VERIFIED; read the completion and outstanding-prerequisite
reports separately. No exit code certifies actual service readiness.
Ctrl+C before confirmation reports
no installation changes; afterward it reports potentially incomplete work, never
transactional rollback. A NATS check confirms only connection/cleanup using the
runtime-compatible URL authentication, not
JetStream authority provisioning, evidence preservation or service readiness.
It also does not certify authentication policy: a broker allowing anonymous
connections can accept an anonymous URL. Required broker/account permissions and
authority resources remain separate deployment and runtime checks.
Validate the file independently before starting services:

```bash
.venv/bin/python -c 'import pathlib; from lab_sync_acquisition.deployment_configuration import load_service_configuration; load_service_configuration(pathlib.Path.home()/".config/lab-sync-acquisition/storage-services.json", "ingestor"); print("configuration valid")'
```

Resolve outstanding operational prerequisites and applicable readiness/admission
checks before running services. Printing a command is not operational-readiness
confirmation. For the shared storage pair, the **single** printed `LAUNCH:` command
is equivalent to:

```bash
.venv/bin/python -m lab_sync_acquisition.service_launcher ingestor --deployment-config "$HOME/.config/lab-sync-acquisition/storage-services.json"
```

Record actual startup/readiness and retirement results separately. Repeat setup
only after resolved retirement, checking that configuration and existing
scientific bytes remain unchanged. Follow the existing communication/retrieval
checks below for the other computers; guided setup is neither centralized
provisioning nor real-deployment validation. Q022 remains OPEN.

### Manual Installation Alternative

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

### What To Prepare Before Service Operation

NATS is the network broker carrying commands, results and operational evidence
between framework processes. JetStream is its persistent messaging facility;
Controller exclusivity also uses an existing JetStream KV bucket. Scientific
artifact files remain under the framework's scientific storage/collection
contracts, not in a replacement broker database.

Choose one reachable broker computer with stable addressing and persistent local
storage. It may share the StorageManager computer, but this is not required.
Only the broker host needs `nats-server`; clients need the broker URL and their
actual credentials. The framework installer never installs, configures, starts
or supervises the broker. Software installation and configuration may proceed
before the broker is operational under Decision 440; arrange the broker before
service operation. Run framework setup separately on each computer. Broker
prerequisites do not require an online AcquisitionNode or replace later
device/readiness/retrieval checks.

The operator or NATS administrator must provide: reachable URL(s), credentials
supported by the current runtime, the actual account ID, the existing authority
bucket name and shared claim key, plus reviewed permissions and persistent-storage
settings for operation. Software configuration may record an intended deployment
URL while connectivity remains PENDING / NOT VERIFIED; never assume that recording
it creates NATS or proves readiness. Do not fabricate credentials or authority
identities to fill required configuration fields.

### Accepted Controller Authority Prerequisite (Decision 436)

Controller may run on any suitable computer, but only one operational Controller
is permitted system-wide. The accepted design requires one atomic, persistent,
non-expiring JetStream KV claim identifying its operational instance. All
Controllers must use the same installation authority in a shared authoritative
JetStream account, persistent KV storage and verified durability configuration.
Occupied, missing, unavailable or unverifiable authority storage must deny startup.
No TTL, election, automatic failover or time-based takeover is permitted.

Slice 1 implements claim acquisition/admission and conditional retirement release,
and is CLOSED within bounded software scope after independent ICC manual
validation and separate Codex audit PASS at
`acdf7a02613fea63df730da52ddf8aa12b1cf3a3`; see the
[validation/correction record](validated_workflows.md#q024-slice-1---controller-exclusivity-claim-and-operational-admission).
This does not establish fully deployed installation-wide exclusivity or implement
manual recovery or service-side Controller registration/supersession.
Concrete bucket/provisioning inputs, access permissions and broker durability
settings must be established and verified for the installation before deployment
can claim exclusivity. The example below does not establish those settings or
certify claim persistence.

Install an operator-selected `nats-server` binary for the broker machine's actual
OS/architecture from [official downloads](https://nats.io/download/). Extract to
an operator-managed location and add to PATH or invoke its full path. Record its
version; this repo does not prescribe a universally validated server version.
On Ubuntu select the Linux archive for that computer's architecture, not the
Jetson's by assumption; on Windows select the matching Windows archive. The
optional `nats` administration CLI is a separate binary from `nats-server` and
nats-py. Obtain it from the [official CLI project](https://github.com/nats-io/natscli).
Check `nats-server -v` and, if used, `nats --version` after extraction. No systemd,
Windows service registration or automatic startup is required by this procedure.
Keep binaries, broker configuration, secrets and storage outside the repository.

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
Complete the account/authentication steps below before exposing this listener.

Validate/run the broker in its own terminal:

```text
nats-server -v
nats-server -t -c NATS_CONFIG_PATH
nats-server -c NATS_CONFIG_PATH
```

For a path containing spaces, quote it. For example, after substituting actual
operator-managed paths:

```bash
# Ubuntu, from the directory containing the extracted binary
./nats-server -t -c "$HOME/.config/nats/nats-server.conf"
./nats-server -c "$HOME/.config/nats/nats-server.conf"
```

```powershell
# Windows; C:\Tools\NATS is an example installation location
& 'C:\Tools\NATS\nats-server.exe' -t -c 'C:\ProgramData\NATS\nats-server.conf'
& 'C:\Tools\NATS\nats-server.exe' -c 'C:\ProgramData\NATS\nats-server.conf'
```

### Accounts, Credentials And Permissions

Have the broker administrator configure a framework account with JetStream enabled
and the required system-account responder. Users authenticate into that account;
an account identity is not a username, password or Controller service ID. Follow
the official [account setup](https://docs.nats.io/learn/security/accounts-and-multitenancy)
and [authentication instructions](https://docs.nats.io/learn/security/authentication-basics).
Use administrator-approved credentials, not sample passwords. Keep system-account
administrator credentials out of framework service files.

The existing runtime passes `servers` URLs to nats-py. Supported URL forms include
`nats://USER:PASSWORD@HOST:PORT` and `tls://USER:PASSWORD@HOST:PORT` with credentials
compatible with the SDK's URL parsing. TLS uses existing SDK/system trust; this
installer does not add certificate bypasses. These are format illustrations, not
credentials to copy. Current deployment loaders do not expose separate JWT/NKey
credentials-file or custom client-certificate options. Do not configure a broker
to require those options and assume the framework will supply them. If local
security requirements cannot be met by current runtime inputs, stop for an
explicit interface decision rather than disabling security.

[Decision 445](architecture_decisions.md#decision-445-explicit-nats-username-and-password-preserve-authentication-compatibility)
is implemented with optional explicit `nats_username`/`nats_password` configuration and
exact SDK argument forwarding, rejection of partial/empty or mixed URL/explicit
credentials, and credential-safe output. Add both nonempty string fields to the
existing deployment JSON, with no userinfo in any `servers` URL, or omit both to
retain legacy URL-only behavior. Passwords are not trimmed, encoded or decoded.
The installer reads connection inputs without echo and preserves existing files;
verification receives credentials through stdin, never subprocess arguments.
The bounded authentication scope is CLOSED after independent Ubuntu manual
validation and Windows audit PASS; see the [closure evidence and limitations](validated_workflows.md#decision-445---nats-authentication-compatibility).
Successful authentication does not establish complete end-to-end deployment or
completion of all deployment work. Decision 446 has its own
[bounded software closure and deferred live-validation exception](validated_workflows.md#decision-446---guided-installer-software-scope);
Q022 remains OPEN.

GUI and addressed maintenance/claim commands can read connection fields from an
existing deployment file using `--deployment-config PATH` instead of `--server`.
GUI identities/origin and maintenance target/authority/authorization flags remain
explicit and unchanged. These paths read only connection fields from that file;
they do not launch its service role or grant Controller authority. There are no
password command-line flags; keep credential files outside Git with appropriate
OS access restrictions.

Restrict broker configuration, client configuration and private keys to appropriate
OS users; keep secrets out of Git, shared logs and shell history. nats CLI contexts
are external administration settings, not automatically consumed by framework
services. The installer sends its connection settings through child stdin rather
than command arguments and does not print them. The guided URL input itself is
visible in the terminal; use an appropriately private terminal.

Review permissions against the actual selected roles, not a universal wildcard
allow-list. They must support applicable runtime command/result/evidence subjects,
request/reply inboxes, JetStream stream/consumer operations and durable publication
acknowledgments. Controller authority additionally needs own-account
`$SYS.REQ.USER.INFO`, existing KV inspection/readback, atomic claim creation and
revision-conditional release. Preserve Decision 422's restricted external-client
subjects: GUI/client credentials must not grant internal service or maintenance
authority. Broker authentication is distinct from cooperative human GUI ownership.
The installer neither proves this full permission set nor changes it.

### Obtain And Verify The Three Authority Values

This administrator-assisted procedure remains the fallback when shared values
cannot be discovered. Decision 446's guided software now supports selected-file
reuse, authenticated account readback and confirmed conventional bucket/key
proposals for new systems. It does not invent accounts, change existing shared
authority settings or provision broker resources. Independent validation/audit and
real Ubuntu deployment verification remain pending.

Use the **same account and credentials as the framework**, via an administrator-
prepared nats CLI context (`FRAMEWORK_CONTEXT` below is a placeholder):

```text
nats --context FRAMEWORK_CONTEXT account info
nats --context FRAMEWORK_CONTEXT request '$SYS.REQ.USER.INFO' '{}'
```

These are external readback commands, not installer actions or framework lifecycle
commands. Single quotes protect `$SYS` in both Bash and PowerShell. The exact
`data.account` value returned by the second command is `controller_claim_account`;
do not substitute a friendly display label. If it times out or is denied, check
the system-account responder and request/reply permissions with the administrator.
See the [NATS user-info implementation](https://github.com/nats-io/nats-server/blob/main/server/events.go).

The administrator chooses and provisions `controller_claim_bucket` once in that
same account. It must be file-backed, non-expiring, without prohibited global
eviction limits, mirrors, sources or transformations. See the precise checks in
[Controller claim implementation](#controller-claim-implementation-q024-slice-1).
For a **new** bucket only, the administrator may use:

```text
nats --context FRAMEWORK_CONTEXT kv add AUTHORITY_BUCKET --storage file --ttl 0s
nats --context FRAMEWORK_CONTEXT kv info AUTHORITY_BUCKET
```

Inspect the resulting configuration; do not assume unspecified CLI defaults
establish all framework guarantees. Never recreate an existing bucket or purge
history to make a check pass. These commands use the existing
[NATS KV administration interface](https://github.com/nats-io/natscli/blob/main/cli/kv_command.go).
Enter the bucket name, not the underlying `KV_...` stream name.

`controller_claim_key` is the agreed shared key within that bucket, used by all
computers for this installation, not a new key for each host. Obtain it from the
administrator/deployment record. Do **not** create a placeholder value: a vacant
key is normal before first Controller startup. An occupied claim requires the
existing explicit inspection/recovery procedure, not installer clearing.

Minimal installer connection success does not certify these resources, JetStream
or complete permissions. `account info`, KV inspection and subsequent actual
service startup/readiness are separate checks. None certifies physical crash or
power-loss durability.

### Laboratory Example, Not A Framework Default

The current proposed lab topology places NATS, Controller, SynchronizationManager
and the single paired Ingestor/StorageManager process on Ubuntu `192.168.50.1`.
The Jetson AcquisitionNode is `192.168.50.2`. A broker listener on the Ubuntu
interface and client URLs addressing `192.168.50.1` permit both computers to use
the same broker. Port `4222` is illustrative; use the configured value. Add actual
runtime-compatible authentication/TLS, reviewed firewall access and matching
authority settings; these addresses alone are not a complete deployment config.
Do not use Jetson loopback to reach Ubuntu. Guided setup on Ubuntu selects
`controller synchronization-manager ingestor`; the Jetson selects
`acquisition-node` with its existing hardware declaration. This topology and the
specific addresses are test/deployment inputs, not universal framework settings.

### Troubleshooting And Safe Broker Restart

| Observation | Check before retrying |
| --- | --- |
| Connection refused/timeout | Broker process, actual listener, destination address/port, route and both host/network firewall rules; a planned URL is not a running broker |
| Local client works, Jetson fails | Loopback-only bind, wrong interface, subnet/routing or firewall; do not use `0.0.0.0` as a client destination |
| Authentication rejected | Actual configured user/password and account, URL parsing, TLS/trust requirements; import success is unrelated |
| Connection passes, JetStream fails | JetStream enabled for server and client account, persistent store access/capacity, and JetStream API permissions |
| Authority account unverified | Exact `data.account`, system-account responder and own-account request/reply permissions |
| Authority bucket missing/invalid | Administrator provisioned it in the same account with required persistence/retention; never let startup create a replacement |
| Publish/consumer permission denied | Role-specific subject/API permissions and inbox replies; do not replace restricted client permissions with blanket access |
| Broker restarts but obligations remain | Existing uncertain-publication, service retirement and explicit retry requirements still apply; reconnect is not successful closeout |

For a planned restart, coordinate with operators and resolve relevant framework
operations through their supported Stop/retirement procedures. Stop the broker
gracefully using its existing launch method, then restart with the **same** reviewed
configuration and persistent store. Do not delete JetStream files, streams,
consumers or occupied Controller claims as troubleshooting. Preserve logs without
publishing credentials. After restart recheck connectivity and relevant readback;
do not automatically replay lifecycle commands or uncertain publications.

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
- After a successful initial connection, Decision 423 enables nats-py's automatic
  transport reconnection with unlimited runtime attempts and its existing bounded
  reconnect wait (currently two seconds). Initial connection failure/cancellation
  handling is unchanged. Intentional boundary closure stops reconnecting.
  SDK-managed subscriptions and the existing JetStream context are reused; service
  owners are not recreated. Ingestor and StorageManager reconnect independently
  while retaining their mandatory shared process lifetime.
- Transport restoration does not replay Session, Experiment, Stop, Kill, Cancel or
  release operations, retry uncertain publications, or establish evidence intake,
  archival or cleanup success. Use existing explicit retry and confirmation
  contracts. Missing JetStream history is not silently repaired or reprovisioned
  on reconnect. Q011 remains OPEN for unpublished-message recovery; this software
  correction does not establish physical Windows-sleep/deployment validation.
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
`preservation_window_s`, positive `result_window_s`, `controller_claim_account`,
`controller_claim_bucket` and `controller_claim_key`. Additional fields:

| Selected CLI role | Additional fields |
| --- | --- |
| `controller` | `service_id`, `synchronization_id`, `known_nodes` |
| `synchronization-manager` | `service_id` |
| `acquisition-node` | `synchronization_id`, `node_config`; optional `service_id` must match hardware `node_id` |
| `ingestor` or `storage-manager` | `storage_root`, `global_artifact_root`, `recovery_journal_root`, `framework_journal`, `retrieval_endpoints`; dependency mode below |

Independent roles additionally accept optional positive finite
`registration_window_s` (default `180`), or `--registration-window-s` for explicit
CLI startup. This is one overall instance-discovery/registration budget, not a
preservation, release or result timeout. Decision 444's working-tree implementation
retains services and readiness observation after unconfirmed registration, resuming
on fresh Ingestor announcements or explicit checks; independent validation and
deployment verification remain pending. Controller authority prerequisites remain.

The launcher emits bounded deployment diagnostics to stderr for registration,
readiness and reconciliation stages, using correlation/instance identifiers and
monotonic elapsed durations without payload or configuration dumps. A
`response.published` line confirms publication, not receipt by the requester;
reconciliation findings can be preserved while dependencies remain unresolved.
Existing JSON stdout is unchanged. These developer-verified diagnostics do not
establish the cause or resolution of the Windows unknown-readiness observations;
independent validation and audit remain separate.

**Implemented correction; independent validation and audit pending:** Default terminal
diagnostics retain meaningful startup/registration outcomes, actionable
readiness failures, timeouts and blocked operations. Routine successful readiness
traffic, command correlation/transport traces and detailed successful historical
verification/preservation stages use DEBUG, enabled by
`LAB_SYNC_DEPLOYMENT_DEBUG=1`. Bounded field filtering, flushed stderr and JSON
stdout stay unchanged.

The same correction distinguishes Controller-wide infrastructure
readiness from operation-specific AcquisitionNode admission. Configured unused
nodes remain individually observable (including Unknown) and in reconciliation,
but do not automatically block Controller-wide readiness. Selected Session
participants, Controller authority and outstanding safety obligations retain their
existing checks. No service readiness or deployment validation is claimed here.

Choose exactly one shared-pair dependency mode:

- Actual dependents: nonempty `external_dependents` list of objects with exactly
  `component_type`, `component_id`, plus positive finite `result_window_s`.
  Types: `controller`, `acquisition_node`, `synchronization_manager`.
- Genuinely isolated pair: `no_operational_dependents: true`, without that list
  (the shared authority `result_window_s` remains required). Never declare isolation falsely.

[Decision 442](architecture_decisions.md#decision-442-operational-dependency-evidence-and-explicit-terminal-maintenance-choices-preserve-retirement-safety)
distinguishes configured AcquisitionNode membership from an established operational
dependency. A never-registered node need not start for shutdown. Registration-
history authority is established by existing applicable
startup, reconstruction, integrity, historical verification and preservation
checks, as clarified by the Decision 442 supplement. Genuine first initialization
permits initially empty history under the existing initialization contract; offline
status or an absent in-memory instance alone is insufficient. Actual unresolved
dependencies remain blocking and fully resolved dependencies must not remain
blocking under existing confirmation requirements. Unverified history fails
closed; a newly empty journal or successful preservation alone cannot override
detected recovery/historical problems. Undetectable catastrophic history loss
remains unresolved under Q022, outside this correction; no new persistence or
public interface is authorized. The working-tree correction uses verified history
instead of treating missing confirmation alone as a node dependency; independent
manual validation and audit remain pending. Do not remove actual
dependents, declare false isolation or clear history to force retirement.

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

### Windows CMD Deployment Quick Runbook

Use separate **Windows CMD** terminals with the installed Python environment
activated. These filenames match the guided installer; configuration stays outside
Git under `%USERPROFILE%\.config\lab-sync-acquisition`. The installer's Windows
`LAUNCH:` lines instead use **PowerShell** syntax (`&` and single-quoted arguments);
do not paste those lines into CMD.

With external NATS/JetStream already available, start the shared storage process:

```bat
python -m lab_sync_acquisition.service_launcher ingestor --deployment-config "%USERPROFILE%\.config\lab-sync-acquisition\storage-services.json"
```

This launches both Ingestor and StorageManager. Do not launch a second process
using the `storage-manager` alias. After checking their startup output, start:

```bat
python -m lab_sync_acquisition.service_launcher synchronization-manager --deployment-config "%USERPROFILE%\.config\lab-sync-acquisition\synchronization-manager.json"
```

Bring up the required AcquisitionNodes using their own deployment files, then
start Controller (with its existing authority bucket/settings available):

```bat
python -m lab_sync_acquisition.service_launcher controller --deployment-config "%USERPROFILE%\.config\lab-sync-acquisition\controller.json"
```

Inspect `target`/`startup` output: `publication_confirmed`, `acceptance_confirmed`
and `archival_confirmed` are separate checks. Inspect current service/dependency
readiness too; an initial startup snapshot can contain unknown dependencies.
`Startup unconfirmed` or a retained process is not successful readiness. Session
launch still requires Controller's authoritative prerequisites, not just this order.

For shutdown, Ctrl+C requests local maintenance Stop. A blocked attempt offers
explicit K (authorized maintenance Kill) or C (Cancel); neither repeated Ctrl+C
nor EOF authorizes Kill. Cancel does not undo completed cleanup. See
[maintenance](#maintenance-stop-cancel-and-kill) for addressed commands and paired
preparation restrictions. Retire dependent work before expecting storage to stop.

For retained startup or dependency-confirmation failures, keep the terminal and
capture both peer logs, exact instance/attempt/command identities and result fields.
Startup registration does not automatically retry. If local retirement completed
but delivery remains unconfirmed, Ctrl+C retries the launcher's retained completion,
not a fresh physical Stop. Archived evidence alone does not prove requester receipt.
Do not use `taskkill` as framework recovery or reset journals, archives, configuration
or NATS state. If a process was forcibly ended, assess its preserved obligations
before explicit return under Decision 329; do not label the old exit graceful.
See [restart and retained-result guidance](#independent-role-startup-w063-closed).

### Destructive disposable test-deployment reset

The [November 24, 2026 reset record](deployment_test_reset.md) documents the
observed historical-delivery/accumulation symptoms, the authorized destructive
Ubuntu/Jetson test reset, required safety precautions and authority-store
reinitialization. It is not production recovery or an implemented factory reset.
The precise historical-processing cause and architectural corrections remain under
LLC discussion; short healthy operation after reset does not establish long-term
stability. Future reset architecture remains unresolved in
[Q035](open_questions.md#q035-framework-factory-reset-and-clean-deployment-reinitialization).

### Validated Ubuntu GUI Launch

After starting the deployment services above using their platform-appropriate
commands, launch the separately installed GUI from an Ubuntu terminal. The
following exact command was successfully used during deployment on November 24,
2026; it records successful GUI launch, not broader GUI or deployment validation:

```bash
cd ~/Documents/Github/miceball_setup
.venv/bin/miceball-gui \
  --deployment-config "$HOME/.config/lab-sync-acquisition/controller.json" \
  --controller controller-1 \
  --client miceball-gui-1 \
  --origin http://localhost:8043 \
  --host 127.0.0.1 \
  --port 8043 \
  --timeout 10 \
  --catalog-path "$HOME/.config/lab-sync-acquisition/gui-catalog.sqlite3"
```

Open <http://localhost:8043> in the browser. The checkout path (including `Github`
capitalization), virtual environment, configuration path, Controller/client
identities, origin, bind address, port and timeout are installation-specific
values, not generic defaults; retain the option syntax when adapting them.
Preserve the existing catalog at the explicit `--catalog-path` above. This Ubuntu
installation uses `controller.json` directly and has no `gui-connection.json`;
no additional connection file is required. G2 and Phase 16 remain CLOSED.

<a id="remote-service-maintenance-w062-closed"></a>
### Maintenance Stop, Cancel And Kill

Ctrl+C in the service terminal requests local maintenance Stop with the OS username.
The historical W061 implementation automatically Cancelled a blocked local attempt
and kept running. The working-tree correction implements the accepted
[Decision 442](architecture_decisions.md#decision-442-operational-dependency-evidence-and-explicit-terminal-maintenance-choices-preserve-retirement-safety)
replacement below; independent manual validation and audit remain pending:

- An interactive terminal presents the actual blocked attempt, blockers and
  obligations, offering K to explicitly authorize existing Kill for that exact
  attempt, or C to invoke existing Cancel.
- Paired shutdown retains StorageManager preparation around Ingestor retirement.
  Blocked preparation offers explicit cancellation, not premature StorageManager
  retirement. Cancelling does not undo cleanup already performed.
- With unavailable input, EOF or a non-interactive terminal, neither Kill nor
  Cancel is automatic. Retain the exact blocked attempt and obligations, report
  existing administrative alternatives and keep maintenance communication available.
  Input unavailability does not permit process exit.

Kill is not OS-level forced termination. Failed/unconfirmed Stop retains the
process; repeated interrupts never authorize Kill. Interrupted startup is joined
before maintenance. Terminal input is cancellable and does not block maintenance
communication. Current developer testing does not establish deployed terminal or
cross-machine validation.

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

### Controller Claim Implementation (Q024 Slice 1)

Use the same `controller_claim_account`, `controller_claim_bucket` and
`controller_claim_key` for every possible Controller host in the installation.
The account is the actual NATS account identifier returned by
`$SYS.REQ.USER.INFO`, not an arbitrary display name. The existing connection must
authenticate into that account and be allowed to query its own account identity,
inspect the designated KV stream, atomically create the claim and conditionally
delete it. Account verification requires the broker's existing system-account
user-info responder to be configured and accessible. Failure to verify denies
startup; no separate privileged connection is opened.

Provision authority storage outside Controller startup using existing NATS
administration. The implementation checks file storage, no bucket expiry, no
global message/byte eviction limits, limits retention, and no mirror/source or
subject transformation that substitutes another authority. Claim creation sets
no message TTL. A missing bucket is an error, never automatically provisioned.
Verify broker/account identity, persistent paths, permissions and actual
durability configuration separately; stream metadata does not certify fsync,
power-loss survival, multi-host deployment or administrative deletion protection.

For direct CLI startup provide `--controller-claim-account ACCOUNT`,
`--controller-claim-bucket BUCKET` and `--controller-claim-key KEY` alongside the
existing required Controller arguments. Configuration-based startup reads the
same three fields from Controller JSON. Claim acquisition/release uses the
explicit `result_window_s` as its bounded timeout.

For direct Python/in-process use, create the existing Controller and matching
`ServiceMaintenanceInterface`, then connect an existing
`NatsCommunicationBoundary("controller", participant_id, servers)` and call:

```python
revision = await maintenance.acquire_controller_authority(
    boundary, account=account, bucket=bucket, key=key, timeout_s=timeout_s)
```

Construction and diagnostic readback remain synchronous and do not connect
implicitly. Operational calls require the confirmed claim, including existing
work, collection, deletion and archive closure. Existing readiness, registration,
Session and maintenance prerequisites still apply. In-process callers must migrate
to this explicit acquisition workflow; there is no local/no-broker exemption.

After existing Stop/Kill execution returns its exact successful retirement result,
direct callers finish with `await maintenance.complete_retirement(command, result)`
before closing transport. Launchers and remote handlers perform this completion
themselves. It preserves existing dependent-confirmation obligations, then releases
the exact owner/value and acquired revision conditionally. Preparation does not
release. Cleanup callbacks execute before retirement commits and cannot release.

Crash/disconnection and uncertain acquisition retain the claim. Acquisition is
one-shot per boundary: uncertain acknowledgment never admits work, speculatively
deletes ownership or automatically retries acquisition. Release failure leaves
Controller retired and final completion pending; retry completion without repeating
physical cleanup. A missing key after an uncertain delete is not treated as proof
of successful release, and a replacement owner's revision is never adopted.
Conditional deletion retains the operational-instance bytes and expected acquired
revision in the existing KV DEL record. Retry reads the first retained record for
that key after acquisition; only its exact subject, DEL operation, owner and
conditional revision establish prior completion. This permits completion after a
lost acknowledgment without publishing a deletion against a replacement.

Reconciliation is bounded by the configured timeout and retained KV history. A KV
history depth of at least two preserves the deletion through one replacement's
acquisition; depth one may overwrite it immediately. Further replacements/writes
can also exhaust bounded history. Missing, overwritten, unavailable or mismatched
proof fails closed and remains an authority-release obligation, not a claim that
final command-result delivery failed. The code does not resize buckets or create
another evidence store, and it does not certify unlimited retention of release
proof. Choose and verify adequate existing bucket history for the installation.

Controller owns its coordinated-shutdown task. Unrelated authorized forced
retirement cancels and joins that task before committing retirement; it cannot
release authority while an in-flight coordinator can still issue commands. The
coordinator's own matching participant attempt keeps the existing final-retirement
path, and dispatch rechecks admission after suspended continuations. This is local
task cleanup and existing attempt correlation, not a new lifecycle or global freeze.
No stale-claim clearing tool or takeover is included. Follow the accepted manual
recovery requirements below without inventing a current recovery procedure.

Focused developer checks (not independent validation/audit), with an installed
NATS server selected explicitly:

```powershell
$env:LAB_SYNC_NATS_SERVER = "ABSOLUTE_PATH_TO_NATS_SERVER_EXE"
python -B -m unittest tests.test_controller_authority tests.test_deployment_configuration tests.test_manual_installation -v
```

The tests launch isolated brokers and use fictional account credentials; they do
not connect to the installation. Broker-dependent checks skip when no binary is
configured. Other directly affected regressions cover framework preparation/final
retirement, pending result publication/ACK, and independent-role CLI dispatch.
Legacy in-process callers and test fixtures that operated a bare Controller need
the explicit authority setup above; passing these focused checks does not claim
that the full historical suite or every manual demo has been migrated or run.

### Durable State And Recovery Boundaries

Decision 436 permits claim release after Normal Stop or authorized Kill only when
Controller operational retirement is confirmed and irreversible, conditional on
the owning instance and expected claim revision. Requests, acknowledgments,
preparation and Ingestor dependency release alone are insufficient. Retired
Controllers cannot resume operational work; Decision 386 final result handling
and launcher-exit requirements still apply. Operational retirement and OS-process
existence are distinct.

A crash retains the claim. Subsequent authorized manual recovery must verify
termination of the previous Controller and condition clearing on the exact
inspected claim/revision. Disconnection is not termination. Package 1 provides the
[manual recovery and service registration workflow](#controller-replacement-authority--package-1-implementation);
its closure does not authorize bypassing maintenance or unconditional JetStream deletion. Services must recover/reconfirm registered
Controller instance authority after restart; GUI controls use framework mechanisms.

Preserve journals, archives, handoffs, scientific roots,
`closed_sessions/records.json`, `closed_sessions.initialized` and JetStream history.
An interrupted `closed_sessions/publication.lock` fails closed; it is not an
expiring lease and must not be removed to assume a Session is open.

Ordinary startup validates intact historical archive prefixes before appending
recovery evidence (Decisions 389/390). Ordinary maintenance cannot overwrite
rejected history. Actual interrupted-write repair stays separately authorized under
Decisions 339/342/347; do not delete/recreate state as a repair shortcut.

Framework evidence replay can add journal-backed duplicate intake audit after a
successful startup announcement. Dependent registration/confirmation therefore
continues the verified intact archive prefix before checking exact current
preservation and instance history. Failed writes, corrupt/missing history and
unconfirmed readback still refuse admission; this is not interrupted-write repair.
This correction has developer regression coverage, not independent deployment
validation or audit closure. A retained startup failure does not automatically
retry registration; preserve its result reason and use existing maintenance before
an explicitly authorized service relaunch.

Framework archives use administrative UTC archival-write months at
`<storage_root>/framework/evidence/YYYY-MM/`. Delayed/recovered evidence is not
backdated; original timing remains unchanged. Historical partitions stay immutable,
confirmation is cumulative, and recovery stays journal-backed. Under Decision 437,
retain existing monthly partitioning and never automatically delete old historical
journal files. Operators are responsible for archival/deletion decisions. File
age, including more than two months, does not establish safe deletion. The framework
does not certify historical files safe to delete or introduce safe-to-delete
markers, automatic historical retirement or extra dependency tracking solely for
their deletion.

**Deleting historical journal files may remove evidence required for recovery, reconciliation, or unresolved operational obligations, potentially causing framework errors or preventing recovery.**

This operator-managed historical-file policy is separate from Decision 435's
deferred in-memory maintenance-history retirement optimization and does not relax
existing evidence-preservation or operational safety obligations.
Invalid clock, uncertain writes and corruption retain evidence and block
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

**Developer implementation; independent validation/audit pending (Decisions 454-455):**
`frames_per_collect` is device-specific Administrator-adjustable technical batching
configuration, not scientific FPS or Experiment duration. Decision 455 approves
the OpenCV-specific initial value `1` for newly configured cameras, with optional
Advanced Settings override and preservation of valid retained per-device values;
it is not a universal or scientifically validated optimum. Later adjustment belongs
in Parameters in
Administrator mode, with authoritative configured-value readback and no changes
to active acquisition or accepted execution snapshots. The CLI stages optional
Advanced administrative settings using adapter-owned validation and preserves
valid retained values. The node runtime implements owner-side durable
publication to the actual startup hardware file, preserving unrelated fields and
preventing silent lost updates. Modifications require an unreserved node outside
an active Session and no conflicting lifecycle work. Saved and loaded values remain
separate: normal AcquisitionNode restart applies the change, with post-restart
readback confirming loading. Unconfirmed saves require saved-value readback before
another write, not automatic retry. No GUI backend device persistence, live reload
or automatic restart. Width, height and FPS remain experimenter-adjustable;
Package C independent verification remains pending and Decision 453 stays deferred.
Update the core package on Controller and AcquisitionNode computers and the GUI
package on its backend computer before using the new operation. Apply saved values
only by normal, authorized AcquisitionNode shutdown/restart when obligations permit;
refresh inventory afterward to confirm loaded values. No live deployment was changed
by developer verification. Publication serializes cooperating runtime/installer
writers using a sibling lock file, rejects stale revisions and verifies exact
readback. This is not atomic content-CAS against external writers that ignore the
lock. Windows uses ReplaceFile access-control preservation and file synchronization;
POSIX additionally synchronizes the parent directory. Physical power-loss durability
and POSIX ACL behavior were not established by the Windows developer checks.

<a id="sustained-acquisition-execution-g3-closed"></a>
### Sustained Acquisition Execution (G3 Closed)

Production node startup enables one owned acquisition task. After activation,
selected scientific products record without repeated Controller iteration commands.
Idle intervals do not read frames. Controller disconnection alone does not stop
recording. Authorized cleanup joins execution and finalizes scientific products.
Camera failures retain partial data/failure evidence and attempt cleanup.
Synchronous device calls are not preemptible hardware deadline guarantees.

**Developer implementation; independent validation/audit pending:** Decision 395's
[acquisition-independence clarification](architecture_decisions.md#accepted-clarification-scientific-acquisition-does-not-await-evidence-publication)
uses separate adapter-owned collection/publication tasks, finite serialized flushes
and SDK reconnect notification. Local expiry/finalization can precede publication;
producer-completion and preservation barriers still require their existing proof.
RAM retention supports finite Experiments and temporary interruptions, not
indefinite disconnection or restart-durable unpublished recovery. Resource
exhaustion prevention and hard-real-time acquisition are not guaranteed. Existing
G3 validation is not proof of physical outage continuity; Ubuntu-Jetson outage
testing remains pending. G2 and Phase 16 remain CLOSED.

<a id="experiment-capacity-and-duration-g2-closed"></a>
### Experiment Capacity And Duration (G2 Closed)

**Developer implementation; independent validation/audit pending:**
Decision 394's [accepted Expected size clarification](architecture_decisions.md#accepted-expected-size-and-adjustable-budget-clarification-2026-11-23)
adds automatic available installation metadata, read-only preparation estimates,
preservation proposals and owner-enforced minimum budgets. Historical G2 closure
does not validate these additions; physical deployment verification remains pending.

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
Existing explicit declarations remain supported. The installer initializes missing
HDF5 camera `capacity_estimate` metadata from the storage-owned `hdf5_camera_v1`
profile when shape/dtype are available; it does not invent FPS or probe hardware.
When preflight dependencies are unavailable, metadata initialization is deferred
until package installation, without another Advanced prompt; source-byte checks
and existing conditional publication still protect concurrent configuration edits.
The profile uses uncompressed raw frame bytes plus 4 KiB per frame and 128 KiB
fixed overhead, including an in-flight batch. Selected dimensions resolve the
same schema for estimation and stream creation. Missing rate or representation
information leaves estimation unavailable and requires an explicit budget.

Production-writer software measurements (Python 3.12.14, NumPy 2.3.5, h5py 3.16.0,
HDF5 2.0.0; finalized HDF5 plus metadata/manifest sidecars):

| Shape / dtype | Frames / collection | Raw bytes | Stored bytes | Estimate bytes |
| --- | --- | --- | --- | --- |
| 2x4x3 uint8 | 1 / 1 | 24 | 93,289 | 139,312 |
| 48x64 uint16 | 32 / 8 | 196,608 | 299,672 | 540,672 |
| 480x640x3 uint8 | 4 / 1 | 3,686,400 | 3,777,645 | 4,759,552 |
| 480x640x3 uint8 | 60 / 8 | 55,296,000 | 55,411,883 | 63,078,400 |
| 720x1280x3 uint8 | 8 / 4 | 22,118,400 | 22,209,707 | 33,357,824 |
| 24x32 float32 | 256 / 16 | 786,432 | 995,235 | 2,080,768 |

These support a conservative planning allowance, not an exhaustive encoded-byte
bound or physical camera validation. StorageManager reuses estimated scientific
copies, adds a 128 KiB ordinary operational-metadata allowance at its evidence
root, and retains distinct roots/shared-filesystem checks. Unestimable scientific
copies require explicit preservation fallback. A scalar explicit preservation
budget covers each required root; it is never divided among destinations.

Controller-mediated `estimate_experiment_storage` is read-only and separate from
start-time capacity admission. GUI Expected size counts the scientific dataset
once; it does not add preservation copies. Budget controls appear for adjustments
or missing estimates. Explicit overrides survive recalculation, cannot reduce an
available automatic minimum, and can return to automatic mode. Accepted/running
configurations remain immutable. Estimates impose no runtime quota or new Stop.

Developer verification uses `tests/test_expected_size.py`, five focused installer
methods, production Parameters/configuration browser checks, and
`GUIIntegrationTests.test_storage_estimation_is_read_only_before_and_after_session_admission`
against an isolated authenticated broker. Independent validation/audit and physical
camera/Jetson/Ubuntu storage checks remain pending. The complete changed owner/API
inventory is in [the code map](code_map.md#expected-size-integration-decision-394-clarification-independent-verification-pending).

Focused Windows CMD verification (activated development environment; Node,
Playwright and the selected browser must already be available):

```bat
set PYTHONPATH=src;gui\src
set LAB_SYNC_BROWSER_CHANNEL=msedge
python -B -m unittest tests.test_expected_size gui.tests.test_expected_size gui.tests.test_parameters_browser ^
 gui.tests.test_backend.GUIIntegrationTests.test_storage_estimation_is_read_only_before_and_after_session_admission ^
 gui.tests.test_connected_feedback.ConnectedFeedbackTests.test_parameter_usability_and_string_fidelity_in_browser ^
 tests.test_install_framework.FrameworkInstallerTests.test_camera_estimation_metadata_initialized_without_changing_settings ^
 tests.test_install_framework.FrameworkInstallerTests.test_camera_metadata_initialized_after_dependencies_become_available ^
 tests.test_install_framework.FrameworkInstallerTests.test_explicit_camera_estimation_metadata_is_preserved ^
 tests.test_install_framework.FrameworkInstallerTests.test_device_advanced_settings_preserve_independent_values_and_existing_role_bytes ^
 tests.test_install_framework.FrameworkInstallerTests.test_invalid_or_cancelled_device_advanced_settings_preserve_hardware -v
python -B -m unittest tests.test_experiment_capacity -v
node --test gui/tests/test_connected_state.mjs gui/tests/test_parameter_context.mjs gui/tests/test_recording_selection.mjs
```

Latest developer outcomes across focused runs: 8/8 owner/API methods, 5/5
installer methods and 3/3 production-browser methods PASS, with no skips. The
browser regression exposed estimate-completion rerendering of a native invalid
numeric draft; completion now updates feedback without rebuilding inputs, and
the three browser methods passed after correction. The connected-state,
parameter-context and recording-selection Node selection passed 17/17. Python
syntax and changed JavaScript syntax checks passed, as did `git diff --check`.
The G2 selection ran 31 methods: 25 passed and the six fixture errors below
remained; all six reproduced against a disposable archive of committed HEAD.

The capacity regression selection has six independently reproduced committed-HEAD
fixture errors: five omit required Controller authority and one contradicts its
retained destination configuration. These prevent their target local paths from
being exercised; they were not corrected in this feature. A passing idle-expiry
fixture also emits an unconfirmed-publication diagnostic; its pass does not certify
delivery of that expiry evidence. The separate `test_configuration_values.mjs`
selection has one committed-HEAD control-double error (`hasAttribute` absent).
These limitations do not constitute new validation or closure of historical G2.

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

Developer implementation (independent validation/audit pending): periodic and
explicit synchronization publication and final producer flush share per-Session
confirmed-identity progress. Successfully published history is not sent again;
failed, cancelled or acknowledgment-uncertain publications retain their stable
identities for retry. A fresh communication handler replays retained evidence;
this is not a new persistent recovery mechanism. Assessment frequency, evidence
retention, Ingestor acceptance and closeout deadlines are unchanged. No resolution
of the physical G5 preservation failures is claimed.

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
and `close_saved_session_archive_remote()`. Q034 Slice 2 adds Controller-mediated
`read_storage_sessions()`, `read_storage_session()` and `delete_original_artifacts()`;
implementation is pending independent validation/audit. Collection and Storage
requests require explicit `experimenter_name` and boolean `administrator_mode`.
The accepted Session owner is `session_parameters["experimenter"]`; unknown or
ambiguous owners require cooperative administrator mode, never inferred identity.
NATS `client_id` remains routing data, not a human login.

Use the existing external Controller client/receiver, with broker permission for
the exact `controller_external.CONTROLLER_ID.CLIENT_ID.OPERATION` subjects.
Storage enumeration uses `session_id=None`; Session readback, collection and
deletion identify the original Session. Use new request IDs for fresh readback;
identical IDs retain existing pending/completed snapshot semantics. No second
Controller or GUI integration is introduced. Selected Sessions can be requested
independently; collection still transfers a whole Session through StorageManager.

Deletion requires explicit `operation_id`, `experiment_ids` (a nonempty list, or
`None` for the entire Session), `confirmed=True` and
`warning_acknowledged=True`, as well as operator context. Manual deletion has no
collection prerequisite. Optional collection `deletion` parameters use the same
scope/confirmations and remain absent by default; exact verified durable collection
proof is mandatory for that policy. `copied_unverified` is not verified proof.
Lost replies never establish success. Repeating an operation ID only reads its
durable outcome; a retry uses a new ID with `retry_of` naming the prior operation,
renewed admission and unchanged original targets. Scientific global copies,
metadata and evidence remain untouched. Local intent/outcomes are retained under
the configured AcquisitionNode root's `deletion_operations/`; do not remove those
records to make an uncertain operation look new. Abandonment is not permission
to delete retained products. Validate only with disposable scientific originals
until the separate ICC validation and audit have accepted this backend.

## 11. Controller Session/Experiment Lifecycle And GUI

The service CLI starts/maintains Controller. GUI Integration Unit 1 now implements
a separately packaged Python web backend operating that same owner through the
existing external NATS interface; independent ICC validation and audit are pending.
There is no requirement for
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
and the GUI never attaches to that private object. For connected operation, set
the Controller deployment's existing `external_client_id` to the designated GUI
backend identity and add `browser_control_required: true`. Keep broker permissions
restricted to that identity's exact external subjects and request inboxes, including
the new control/state/outcome/inventory operations. The default false retains the
existing non-GUI testing-client contract; it is not a GUI bypass route.

Install the core and separate `gui/` project, then run the explicitly configured
`miceball-gui` entry point; see [connected GUI setup](../gui/README.md#connected-backend-integration-unit-1)
for arguments, configuration input and limitations. One backend NATS client binds
server-assigned WebSocket identities; Controller enforces View Only/Take Over.
Reconnection performs state/outcome reads, never lifecycle replay. Backend restart
does not recreate service owners, and Controller restart does not reconstruct a
running Session from preserved metadata. Q031/Q032, scientific visualization,
Analysis/Validation, Storage GUI and service administration remain outside Unit 1.
This implementation status does not establish deployment validation or close Q029.

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

### GUI Catalogs And Backend Services Presentation (Decision 449)

**Package A developer implementation; independent validation and audit pending.**
[Decision 449](architecture_decisions.md#decision-449-gui-backend-installations-own-durable-catalogs-and-expose-one-contextual-parameters-workspace)
does not close the separate Decision 447 installer or Decision 448 Activity History
scopes. Package B Parameters navigation remains pending.

One GUI backend per laboratory deployment is recommended, not mandatory. Browsers
on the same or different computers share the catalogs of the backend they connect
to. A separate backend installation maintains independent catalogs; installations
do not automatically share or synchronize them. Hosting the GUI on the Controller
computer is optional and does not change Controller authority.

Each backend installation owns durable application catalogs for experimenters,
animals, projects, protocols, project-scoped Session Templates, saved reusable
Steps and other applicable existing reusable configurations. Projects own protocols
and Session Templates; selecting a Session Template before launch is optional.
Catalogs survive browser closure, backend restart and ordinary software updates.
They must live outside replaceable installed package files and cannot reside solely
in browser memory.

**Catalog location/configuration:** Supply `--catalog-path ABSOLUTE_SQLITE_PATH`
to `miceball-gui` / `python -m miceball_gui.backend`. Choose a writable local path
outside installed package files, such as `/var/lib/miceball-gui/catalog.sqlite3`;
create/permission its parent for the backend's operating-system user. The installer
prints `gui-catalog.sqlite3` beside deployment configuration, without starting the
backend or creating a catalog. Keep the same path during ordinary software updates.
No database server or ORM is needed: Python SQLite stores one versioned catalog
document/revision transactionally. Origin/Host checks protect writes; cooperative
catalog owner identities are not human authentication. Revision conflicts refuse
overwrites and retain the browser draft for explicit review/retry. Corrupt or
unsupported existing files are refused rather than recreated.

**Backup and restoration:** Preserve a consistent backup of the application-owned
catalog storage, including the information needed to retain identities, project
relationships and applicable uniqueness/editing rules. Restoration must not race
catalog writes or silently replace established identities and relationships.
Stop every backend using the file before backup or restoration. After a crash,
allow SQLite recovery by reopening the existing file through the backend, then
stop cleanly before copying. Retain any hot journal with the original database
until recovery; do not discard sidecars or copy a live database. Copy the cleanly
closed SQLite file to a separate backup, and restore a verified backup to the
configured path only while stopped. Restart and check catalog readback and IDs;
close or reload browser pages before editing rather than submitting pre-restore
drafts/revisions against the restored backup.
Do not reset IDs or infer missing associations from historical Session names.
Catalog backup is separate
from scientific Session/Experiment records and evidence preservation, and restoring
catalogs does not authorize rewriting historical records or recovering scientific
execution. Package updates must preserve catalog data rather than reset it.

Use a simple durable application-owned mechanism, without a separate catalog
service, database server, cross-installation synchronization or new authentication.
The GUI backend will appear in Services using the existing style, its own status,
actual host, relevant configuration and catalog location where available. It is
not a Controller-managed scientific participant and has no unsupported self-Stop,
self-Kill, self-Restart or recovery controls. The unified Activity History remains
informative and page-local under Decision 448; catalog durability does not extend
its retention. These operator-facing facts belong in framework documentation,
not an additional GUI catalog-locality warning.

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
| Physical G5 | November 23 Ubuntu-Jetson GUI launch, camera acquisition, readable HDF5 on Ubuntu, Normal Stop and sequential Session/Experiment execution reported. Historical discovery found five Sessions; subsequent SSH collection remained unconfirmed. Synchronization accuracy, complete integrity/preservation, deletion and physical failure recovery remain unverified. See the dated G5 record; full G5 remains OPEN. |

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
