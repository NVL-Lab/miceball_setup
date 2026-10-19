# Installation And Deployment

## Status And Scope

Q022-A Decisions 367-378 are accepted and synchronized. Bounded shared-process
launching is closed in W061, remote maintenance in W062 and the remaining
independent role launch paths in W063. Deployment-local service JSON loading and
startup integration are independently validated and audited PASS (W064, CLOSED).
W065/W066 installation checks are closed; W067 integrates the manual runbook and
typed examples below (CLOSED after independent validation and audit PASS). Actual manual
provisioning and deployment/integration remain operator work, with the shared-pair
external-dependent integration CLOSED in W068 under Decisions 389/390 after
independent manual validation and audit PASS. The bounded owner
persistence/readback foundation below is independently validated and audited
after correction (W051). This is the initial manual installation contract and a
current-interface reference, not a working installer or deployment certification.
The framework remains device-independent; a first camera deployment does not
define general adapter/configuration requirements. Q022 remains OPEN.

Decision 376 revises Decision 375: one Ingestor-StorageManager process runs on one
computer, with shared startup, shutdown, and restart lifetime. The two components
retain separate responsibilities, state, locks, and persistence authority and may
communicate through local Python calls. Controller, SynchronizationManager, and
each AcquisitionNode remain independently deployed; every process-crossing
interaction uses NATS. Controller accesses both combined-process components only
through NATS. No new registry, database, or scientific ownership is introduced.
W051/W052 record historical correlated scientific-envelope persistence validation.
Slice 3B removes those obsolete APIs under Decisions 377-378 and is complete after
independent validation and corrective re-audit PASS (W054); operational
evidence journaling and owner-side preservation remain authoritative. Shared-lifetime
bootstrap/launch composition is not implemented in this bounded persistence slice.

## Accepted Manual Service Entry Points (Decisions 383-388)

The bounded W061 launcher below is independently validated and audited PASS;
W063 closes the remaining role launch paths and node configuration loading after
independent IPython validation (60/60) and independent architectural audit PASS.
W062 remote administrative issuance
below is CLOSED after independent validation and focused re-audit PASS. One
common CLI launches/administers the existing Controller, AcquisitionNode,
Ingestor, StorageManager and SynchronizationManager capabilities. Decision 376's
shared Ingestor/StorageManager process lifetime remains mandatory; other roles
operate independently. Reuse initialization, NATS, readiness and maintenance;
the CLI neither provisions configuration nor manages NATS or supervises services.

Ctrl+C invokes local maintenance Stop using the OS username as administrator.
Confirmed completion permits exit only after required final result
publication/handling. Blocked Stop automatically invokes Cancel, reports its
outcome and leaves the process running. Failed or unconfirmed Stop does not
silently exit. There is no interactive Kill or repeated-Ctrl+C forced exit.

A separate terminal sends existing NATS Stop, explicitly authorized Kill or Cancel
directly to an identified service without Controller. Kill continues the same
blocked stop attempt; Cancel ends it without force. Reuse command IDs,
stop-attempt IDs and RuntimeParticipant identities, with a temporary requester ID
per invocation and explicit administrator identity for remote commands. These
identities are records, not new authentication infrastructure.

Feedback distinguishes confirmed completion, blocked, failed, rejected and
unconfirmed, reporting target, attempt, blockers/errors, outstanding obligations
and operator action. Only confirmed successful terminal commands return exit code
0; other terminal outcomes are nonzero. These are presentations of existing
outcomes, not new lifecycle states. Operational retirement is distinct from OS
process exit, Session-binding release, Session/Experiment termination and general
framework shutdown. Existing preservation, cleanup and safety obligations remain.
Configuration provisioning and Q024 recovery remain outside these decisions.

### Common Launcher (W061 Closed)

The package installs `lab-sync-acquisition`; source-tree invocation also works as
`python -m lab_sync_acquisition.service_launcher`. `--help` lists all five logical
roles. Currently `ingestor` and `storage-manager` are aliases for the same paired
process, not independent processes. For example, using explicitly chosen local
paths, identities and a preservation window:

```text
lab-sync-acquisition ingestor --server nats://HOST:4222 --ingestor-id INTAKE_ID --storage-id STORAGE_ID --storage-root PATH --recovery-journal-root PATH --framework-journal PATH --preservation-window-s SECONDS --no-operational-dependents
```

Every setting above is required; server arguments may be repeated. These arguments
pass existing constructor settings, not a new configuration-file schema or a
provisioning mechanism. No credentials or machine-specific settings are committed.
Retrieval-endpoint configuration and installation checks are not supplied here.
W068 additionally supports explicitly configured external operational dependents
through `--external-dependent TYPE/ID` entries and positive `--result-window-s`,
or the service-file mode below. The isolated declaration is never inferred and
must not be used when producers depend on Ingestor. `launch_storage_services()`
retains existing direct `operational_dependents` callbacks for in-process use and
adds `external_dependents` with `result_window_s` for distributed composition.
Neither path discovers dependents or fabricates their availability.
W063 adds Controller, AcquisitionNode and SynchronizationManager startup below.
These roles use remote authoritative preservation, never extra local persistence
owners. Their bounded validation and audit are recorded in W063; this does not
establish full deployment verification.

The paired process uses the existing service-owned NATS command handlers, framework
evidence intake and journal, StorageManager preservation, and startup/readiness
announcements. It is not tied to Session lifetime. Ctrl+C requests maintenance
locally using a temporary requester and OS administrator name; it does not cancel
the running maintenance coroutine or escalate repeated interrupts into Kill.
SIGINT protection is installed before the asynchronous startup callback can admit
commands or evidence. Startup interruption cancels and awaits that callback before
attempting local Stop/Cancel; it does not close connections or discard admitted
Session/journal obligations. Cancellation of the launcher itself retains owners
instead of implying retirement. Pre-admission connection errors still fail startup;
partial-admission errors are reported separately and retain the process.
For orderly pair retirement, the existing StorageManager preparation precedes
Ingestor Stop and prepared StorageManager Stop, retaining evidence capabilities
until the accepted retirement boundary. Blocked Stop invokes Cancel for the same
attempt; failed/unconfirmed results retain the process and report obligations.
Already confirmed retirement is not falsely undone on a later failure.

Remote maintenance issuance was not a CLI command in W061; W062 adds it below.
Existing receiving
handlers remain usable: the launcher waits until final result publication and
delivery ACK finish before counting remote retirement toward process exit. Lost
publication or ACK leaves exit unconfirmed until an existing explicit retry is
handled. Notification carries the complete request and the exact result actually
published and ACKed, with Session/source/destination/command correlation checks.
A conflicting rejection cannot substitute another cached success with the same
command ID. Identical redelivery may publish the retained owner result normally.
Publication/handling confirmation does not claim requester receipt.
After all hosted owners retire, connections drain before normal exit.
Feedback reports existing outcomes, target/command/attempt identities, blockers,
errors and unresolved obligations; only confirmed successful completion exits 0.
Communication cleanup failures retain the process for explicit retry.

Run the focused developer checks with:

```text
python -B -m unittest tests.test_service_launcher -v
```

W061 is CLOSED following independent IPython validation (initial 18/18, then
22/22 after correction; overlapping sets) and focused independent re-audit PASS.
The initial audit FAIL identified cached-success substitution by a conflicting
rejection and unprotected partial-startup interruption; both P2 findings are
resolved with permanent regressions. Sandbox synchronous tests and controlled
coroutine probes passed; normal asynchronous runs stalled before setup in Windows
asyncio socket-pair initialization and are not claimed as passes. No live
JetStream, actual OS signal-delivery, physical hardware, full five-role deployment
or power-loss validation is established. See W061 in validated_workflows.md for
the complete record. Q022 remains OPEN.

### Independent Role Startup (W063 Closed)

All three independent roles reuse `ServiceLauncher` and existing runtime,
readiness and maintenance handlers. Examples with explicitly chosen settings:

```text
lab-sync-acquisition controller --server nats://HOST:4222 --service-id CONTROL_ID --ingestor-id INTAKE_ID --storage-id STORAGE_ID --synchronization-id CLOCK_ID --known-node NODE_ID --preservation-window-s SECONDS --result-window-s SECONDS
lab-sync-acquisition synchronization-manager --server nats://HOST:4222 --service-id CLOCK_ID --ingestor-id INTAKE_ID --storage-id STORAGE_ID --preservation-window-s SECONDS --result-window-s SECONDS
lab-sync-acquisition acquisition-node --server nats://HOST:4222 --ingestor-id INTAKE_ID --storage-id STORAGE_ID --synchronization-id CLOCK_ID --config PATH --preservation-window-s SECONDS --result-window-s SECONDS
```

Controller requires repeated `--known-node` entries or explicit `--no-known-nodes`;
it performs existing startup reconciliation without restoring Sessions or stopping
active acquisition. Other roles check their explicitly configured dependencies
using existing readiness requests. Missing dependencies remain unknown; no
registry, discovery, heartbeat or automatic restart is added. Both time windows
must be positive and finite. Ingestor/StorageManager remain a shared process.
Configure their actual operational-dependent callbacks through the existing
`launch_storage_services()` API when dependencies exist; the paired CLI's
`--no-operational-dependents` declaration must not be used for such a deployment.

AcquisitionNode defaults to `~/.config/lab-sync-acquisition/acquisition-node.json`
or uses `--config`. This is runtime loading, not provisioning. A local file has
the following shape (illustrative values only; actual configuration stays outside
Git). Paths are absolute or relative to the file's directory:

```json
{
  "node_id": "NODE_ID",
  "role": "acquisition",
  "local_storage_root": "SCIENTIFIC_STORAGE_PATH",
  "error_evidence_location": "ERROR_EVIDENCE_PATH",
  "devices": [{
    "adapter": "seeed_imx219_opencv",
    "declaration": {
      "device_id": "DEVICE_ID", "device_type": "camera",
      "enabled": true, "required": true,
      "declared_capabilities": ["frames"], "scientific_products": []
    },
    "configuration": {"camera_source": 0, "api_preference": 0, "frames_per_collect": 1}
  }]
}
```

Declarations reuse `DeviceDeclaration`/`ScientificProductDeclaration`; configure
the products actually supported by the installed adapter. The empty product list
above declares no scientific products; Experiments select from declared products.
The concrete OpenCV adapter is currently the
only production adapter implemented in this repository, not a general camera
assumption or automatic hardware discovery. Unsupported adapter names fail
explicitly. Loading constructs declared adapters without opening hardware;
actual initialization and readiness remain with the adapter during Session
preparation. Installation baselines are supplied explicitly to AcquisitionNode
and reused across Sessions, separate from Session overrides. An optional
`--service-id` for a node must match its persisted `node_id`. Restart is required
to load installation or registered-node changes; there is no live reload.

Distributed maintenance publishes retained operational evidence over existing
NATS subjects, then requests `preserve_service_evidence` from the configured
Ingestor. The paired owners verify exact journal-backed acceptance, preserve and
read back framework evidence/audit/summary under their own locks, and identify
the actual StorageManager in the result. Existing Session products are verified,
never rewritten or implicitly repaired. Identical already-preserved boundaries
do not rewrite products. Fresh nonce-correlated replies, complete scoped result
history and retained-result checks reject stale, incomplete or conflicting
confirmations. This operation is not scientific acquisition receipt, Stage B
collection, recovery, hardware release authorization or OS process-exit proof.

The producer checks its complete required evidence and current local obligations
again under its admission lock before retirement. Changed owned evidence cannot
use an older confirmation; unrelated producers may keep operating and appending
evidence. Missing confirmation or corrupt products block orderly Stop without
discarding retained obligations. Explicit Kill retains existing uncertainty and
authorization semantics. No global freeze or new maintenance lifecycle is added.
Command subscribers request fresh delivery so restart cannot replay historical
Stop or Session-launch commands. Node maintenance notifies the launcher only
after the exact result is published and the command acknowledged.

Startup runs under W061 interrupt protection. Partial admission and blocked or
unconfirmed Stop retain the process; W062 remote administration remains available.
General service configuration files, configuration provisioning, installation
checks and broader distributed maintenance/recovery integration remain outside
W063. Interrupted/corrupt archives still require existing authorized recovery;
startup does not repair them. W063 is CLOSED; Q022 remains OPEN for remaining
configuration/provisioning, installation verification and deployment/integration.

Independent user-run IPython validation passed 60/60 tests with zero failures,
errors or skips. Independent read-only architectural audit PASS found no confirmed
P0-P3 findings. The audit passed 10 focused synchronous tests, seven controlled
coroutine workflows and two additional targeted probes (current corruption after
prior confirmation, and cancellation before confirmation). These are separate
verification sets, not an additive total. A normal async concurrency attempt
stalled before setup during Windows asyncio socket-pair initialization; controlled
execution does not establish normal asynchronous scheduling. No live JetStream,
actual OS signal delivery, hardware operation, complete multi-process deployment,
multi-host timing or power-loss validation is established by W063. See its
validated_workflows.md record for consolidated evidence and limitations.

Focused tests:

```text
python -B -m unittest tests.test_independent_service_startup tests.test_service_launcher tests.test_service_maintenance_cli -v
```

### Deployment-Local Service Files (W064 Closed)

Decisions 367-373 and 376 remain authoritative. The role is always selected on
the command line, never inferred from a file. The existing launchers accept an
explicit general-service file:

```text
lab-sync-acquisition controller --deployment-config PATH
lab-sync-acquisition acquisition-node --deployment-config PATH
lab-sync-acquisition synchronization-manager --deployment-config PATH
lab-sync-acquisition ingestor --deployment-config PATH
lab-sync-acquisition storage-manager --deployment-config PATH
```

The last two commands still launch the same shared-process pair. No independent
Ingestor-only or StorageManager-only process is added. `--deployment-config` is
an alternative input mode: combining it with constructor-setting flags (including
`--config`) is rejected, not merged. There is no CLI/file override precedence,
environment-variable fallback, automatic general-file search or live reload.
Without this option all previously supported explicit flag commands remain
available; the node's existing default hardware-file path and `--config` behavior
are unchanged. Remote administrative commands retain their explicit W062 inputs.

Committed `config_templates/` files are definitions/examples, not usable deployment
values or an installer. Copy the applicable templates outside Git and explicitly
fill the placeholders, including time windows currently set to `null`. Actual
machine values, credentials and keys must remain outside Git. The AcquisitionNode
service template references a separate hardware installation file; its example
uses the existing supported OpenCV adapter, not a framework-wide camera assumption.

All general files require `servers`, `ingestor_id`, `storage_id` and
`preservation_window_s`. Role-specific required fields are:

| Selected role | Additional required fields |
| --- | --- |
| Controller | `service_id`, `synchronization_id`, `known_nodes`, `result_window_s` |
| SynchronizationManager | `service_id`, `result_window_s` |
| AcquisitionNode | `synchronization_id`, `node_config`, `result_window_s`; optional `service_id` must match the hardware file's persistent `node_id` |
| Ingestor or StorageManager shared pair | `storage_root`, `global_artifact_root`, `recovery_journal_root`, `framework_journal`, `retrieval_endpoints`; choose `no_operational_dependents: true` OR a nonempty `external_dependents` list plus positive `result_window_s` |

`known_nodes` is an explicit unique list, possibly empty, for existing startup
reconciliation; it does not select Session participants. Time windows follow
existing launch contracts: positive finite values for independent roles,
nonnegative finite preservation window for the shared pair. Paths resolve
relative to the file containing them, or may be absolute. Node hardware paths
remain relative to the separate hardware file. Settings are read at startup and
are not watched; changes take effect on explicit restart.

### Framework Evidence Archive Months (W071 Closed)

New permanent framework evidence and intake audit use
`<storage_root>/framework/evidence/YYYY-MM/` with the existing three archive
products. StorageManager samples its local system clock at archival write time
and assigns the administrative UTC month. Event/receipt/scientific timestamps are
unchanged; delayed and recovered evidence is not backdated. No SynchronizationManager
or new configuration is required. Earlier partitions are not rewritten, and
existing shared-layout products remain read-only verified history.

Keep the framework recovery journal and all historical partitions. Existing
confirmation/maintenance lookups still need retained history; this implementation
does not establish safe-to-delete eligibility, delete archives, or retire framework
journals. Per-partition summaries retain the month and cumulative evidence/audit
start offsets for continuity and duplicate detection, not a separate registry.
Confirmation still verifies all retained products and has cumulative read/memory
cost; bounded-memory retirement is not implemented.

Clock failure or invalid values retain accepted evidence and report failure.
An uncertain write cannot be retried as an ordinary new-month write. Restart
reconciliation verifies intact prefixes against the journal and confirms durable
readback before appending new recovery evidence. Incomplete/corrupt histories
remain blocked without implicit repair. Existing administrator-authorized repair
can reconstruct an identified same-month interrupted target; older or unidentified
interrupted targets remain unsupported, retained and unconfirmed. Do not remove
or recreate missing products to force startup. No live deployment or power-loss
validation is claimed. W071 is CLOSED after 59 distinct Codex checks, independent
ICC IPython validation (6/6 PASS) and independent implementation/source review PASS
with no confirmed P0-P3 findings. No hardware, OS-signal or normal Windows
asynchronous scheduling validation is claimed. See W071 in validated_workflows.md;
Q024 remains OPEN for historical deletion independence/eligibility, broader memory
retirement and other recovery obligations.

W070A / Decision 392 adds Ingestor-owned `closed_sessions/records.json` and
`closed_sessions.initialized` beneath `recovery_journal_root` (or beside an
explicit known-Session journal when no deployment root is supplied). These are
durable admission records, not temporary journals or Evidence Archive products.
Keep the same deployment-local root across restart and preserve both products;
do not remove them during journal cleanup or recreate an uncertain store as empty.
Missing, inconsistent or unreadable initialized records block affected admission.
`closed_sessions/publication.lock` excludes closure and Session admission across
all Ingestor instances sharing the root. It is held from the admission check
through constructor recovery, preparation, journal acceptance/checkpoints, or
release preservation checks and binding retirement. Contention fails closed
without waiting or automatic retry. A lock left by an interrupted process is
never expired, reclaimed, or treated as evidence that the Session remains open.
Session-independent framework intake remains separate from this root exclusion.
These safeguards do not change the accepted service deployment/ownership topology.

Terminal release retains current archival/terminal-state/journal checks and writes
closure through a flushed/fsynced temporary file, atomic replacement, directory
sync on POSIX, and readback before clearing the binding. Failed publication or
readback retains the binding; explicit retry reconfirms closure. Empty aborted
initialization release is not terminal closure. W070A deletes no journals, and
memory-only intake cannot confirm terminal release without durable closure storage.
W070A is CLOSED after the W070A-A1 concurrency correction, independent manual
IPython validation (16/16 PASS) and final independent source audit PASS with no
remaining confirmed P0-P3 findings. Implementation verification passed 60 distinct
checks; see W070A in validated_workflows.md for the initial audit/correction history
and limits. No live NATS, independent-process deployment, hardware, actual OS-signal,
physical crash, power-loss or normal Windows asyncio scheduling validation is
claimed. W070B implementation is described below; Q024 remains OPEN.

W070B / Decision 393 adds `ingestor.retire_recovery_journal(session_id)` for an
explicitly identified `recovery_journal_root/session_SESSION_ID.jsonl`, not an
arbitrary path or directory sweep. The paired StorageManager must currently verify
the permanent evidence/audit/summary, terminal Session Record and handoff, and the
Session must be durably closed with its Ingestor binding released. Permanent Normal
Stop readback uses the original verified receipt retained as
`acquisition_evidence_completion.receipt` in the existing compilation summary;
partial Kill uses its existing explicit preservation/uncertainty evidence without
claiming complete receipt. Original evidence and audit are not duplicated into a
new closeout product. Historical normal archives missing receipt provenance remain
journal-dependent and are not automatically rewritten or retirement-eligible.

The method returns `True` only after verified retirement/absence and applicable
directory synchronization; failed proof, publication or deletion raises rather
than reporting success. If interruption occurs after unlink, the journal may
already be absent, but permanent closeout remains verifiable and an explicit retry
must reverify proof before confirming retirement. Corrupt journals are retained,
not repaired or treated as Decision 350 terminal loss. Framework journals and
closed-Session records are never targets. Explicit custom journal paths without
the deployment journal root are outside this bounded retirement API.
W070B is CLOSED following independent ICC IPython validation (9/9 probes PASS)
and independent source audit PASS with no confirmed P0-P3 findings. Q024 remains
OPEN for remaining recovery obligations. Focused tests seed a valid
empty artifact handoff and use simulated communication; they do not verify initial
hard-link handoff publication, live NATS, hardware, or physical crash/power loss.
Three existing hard-link integration checks were sandbox-blocked and are not
claimed as passing; no normal Windows asynchronous scheduling campaign is claimed.

`retrieval_endpoints` explicitly maps logical node IDs to the existing
`SshRetrievalEndpoint`: required `host`, `username`, `key_filename`, optional
`port` (existing SSH default 22) and `known_hosts_path`. Key/known-host references
must be existing local files; ports and nonempty endpoint fields are validated.
The loader does not parse private keys, authenticate, contact nodes or retrieve
files. The StorageManager receives these settings and `global_artifact_root`
through its existing constructor; host-key checking and connectivity remain
retrieval-time responsibilities. An empty mapping explicitly configures no
retrieval endpoints; later collection from an unconfigured node fails normally.
Offline nodes do not block startup, and valid paths do not prove SSH access.

W068 represents each external dependent as an existing RuntimeParticipant object:
`{"component_type": "acquisition_node", "component_id": "NODE_ID"}`. Supported
external roles are Controller, AcquisitionNode and SynchronizationManager, using
`controller`, `acquisition_node` and `synchronization_manager` respectively. IDs
must be unique within their role. The external list and isolated declaration are
mutually exclusive; missing, empty or invalid declarations fail before startup.
The original template remains an isolated-mode skeleton; the manual-installation
storage example now demonstrates external dependents. No registry or discovery is
introduced. W064's historical validation does not validate W068's new integration.

The loader rejects malformed JSON, duplicate or unknown fields, missing settings,
invalid identities/URLs/windows, duplicate registered nodes, invalid local
references and invalid hardware configuration before operational startup.
Hardware prevalidation reuses the existing reader without constructing another
service owner or opening hardware. Valid configuration is not service connectivity,
hardware readiness, scientific readiness or installation certification. Session
IDs, device overrides and scientific timing policies are not general-service
settings and unknown Session-specific fields are rejected.

W064 is CLOSED. Independent IPython validation passed 9/9 configuration tests and
the configured shared-storage startup integration. Independent read-only audit
PASS found no confirmed P0-P3 defects or unresolved architectural blockers:
12 focused synchronous tests, controlled startup/graceful retirement and two
additional configuration probes passed. Counts overlap and are not additive;
controlled execution does not establish normal async scheduling. No live NATS/
JetStream, actual SSH/SFTP retrieval, hardware operation, OS-signal handling or
full multi-computer deployment verification is claimed. See W064 in
validated_workflows.md for the consolidated evidence and environment limitations.

Q022 remains OPEN for applicable installation provisioning, installation
verification including Controller-to-node communication and SSH/SFTP dummy-file
retrieval/content comparison, and remaining deployment integration. Broader
recovery is not completed by this slice. Focused checks:
`python -B -m unittest tests.test_deployment_configuration -v`.

### Installation Retrieval Check (W065 Closed)

Decision 373 requires successful SSH/SFTP setup and dummy-file retrieval/content
comparison when installing a node. W065 adds an explicitly invoked installation
operation, not a Session command, long-lived service, certification registry or
continuously enforced runtime gate. It reuses StorageManager's existing
`_pull_sftp_file()` and the same deployment-local `retrieval_endpoints` mapping.

1. On the StorageManager computer install the optional retrieval dependency:
   `pip install -e ".[artifact-retrieval]"` for an editable checkout. Use a
   lab-approved SSH key pair and have the AcquisitionNode administrator authorize
   its public key for a dedicated retrieval account. Keep the private key local,
   readable only by its intended account; never commit it or put it in Session
   configuration. This command provisions neither keys nor accounts and adds no
   passphrase/secret-management system.
2. Verify the node SSH host-key fingerprint through a trusted channel and arrange
   trusted system host keys or a deployment-local `known_hosts_path`. Do not disable
   host checking or automatically trust an unverified key. The existing client
   loads system keys, optionally the configured host-key file, and retains its
   normal rejection behavior for untrusted hosts.
3. Configure the logical node's `host`, `username`, `port` and `key_filename` in
   the StorageManager general-service file, optionally `known_hosts_path`. Paths
   resolve relative to that file. The installation reader validates the same
   endpoint definitions as W064, reading only StorageManager identity/root and
   retrieval settings. It does not start the shared service pair or evaluate
   operational dependencies. Do not falsely set `no_operational_dependents=true`
   to run this check; the operational-launch restriction remains unchanged.
4. On the AcquisitionNode, choose a scratch path outside scientific artifacts
   and create a small known-content file. For example, on a Linux node:

   ```text
   python -c "from pathlib import Path; Path('/tmp/lab-sync-install-check.bin').write_bytes(b'lab-sync-install-check-v1\n')"
   ```

   On the StorageManager computer, in a deployment-local scratch directory
   outside Git, independently create the expected bytes from the same literal:

   ```text
   python -c "from pathlib import Path; Path('retrieval-expected.bin').write_bytes(b'lab-sync-install-check-v1\n')"
   ```

   Use binary writes to avoid platform newline/encoding differences. Do not make
   the expected file from the download being tested. The node administrator, not
   Controller, chooses the scratch path; node scientific storage ownership is
   unchanged.
5. On the StorageManager computer invoke:

   ```text
   lab-sync-acquisition verify-retrieval --deployment-config PATH --node-id NODE_ID --source-path /tmp/lab-sync-install-check.bin --expected-file retrieval-expected.bin --max-bytes 65536
   ```

   The action reads the expected file independently, uses a short-lived
   StorageManager installation operation without operational service startup,
   and opens the remote file read-only using the configured SSH/SFTP transport.
   `--max-bytes` is an explicit positive bound for expected bytes and temporary
   downloaded bytes; oversized files fail rather than filling a scientific
   destination. Download files are automatically closed/deleted on success,
   transfer failure, mismatch or interruption. No source file, artifact manifest,
   Session record, evidence archive or journal is modified. The command does not
   create an unsupported standalone StorageManager service under Decision 376.
6. Inspect the JSON result: logical `node_id`, `retrieval_succeeded`,
   `content_match`, `outcome` and `failure_reason`. Only completed retrieval with
   exact byte equality and successful temporary cleanup reports `PASS`/exit 0.
   Retrieval failure or mismatch reports `FAIL`/exit 1; invalid command arguments
   return a nonzero usage error. Successful retrieval of truncated/wrong bytes
   still fails comparison. Exceptions report categories rather than raw transport
   text, which could contain sensitive data. Record the result in local
   installation notes. Remove only your designated scratch fixture/expected file
   manually afterward; the command never deletes remote files.

Common failures:

- Unknown node: correct the logical identity or its deployment-local mapping.
- Missing local reference/expected file: check the service-file paths and read
  permissions; no remote retrieval is attempted for invalid local inputs.
- Authentication/permission error: verify the configured username, authorized
  public key and supported private-key authentication setup, plus remote-file
  read permissions. Do not add private-key material or passphrases to reports.
- Host-key error: verify the fingerprint with the administrator before correcting
  trusted host keys; never bypass verification to obtain a PASS.
- Connection error: check hostname, port, SSH server, network routing and firewall.
- Missing source: verify the exact scratch path on the node, not an artifact path
  inferred by Controller.
- Mismatch or size limit: check the independently known literal, binary newline
  handling, truncation and the chosen limit; recreate only the designated dummy
  fixture if needed. A failed transfer may have written partial temporary bytes,
  but they are not promoted or reported as successful verification.
- `ModuleNotFoundError`: install the optional `artifact-retrieval` dependency.

This operation uses the existing client's connection behavior, not a new timeout
or retry protocol. Ctrl+C aborts the check, cleans temporary files and reports no
successful verification; it never issues service Kill. A PASS verifies only this
tested retrieval path and contents at that time. It proves neither ongoing
reachability, scientific completeness, hardware readiness nor Session readiness.
Controller-to-node NATS installation verification remains separate. Automated
checks use simulated SSH/SFTP, not a live installation. W065 is CLOSED after
independent IPython validation (11/11 PASS) and independent audit PASS with no
confirmed P0-P3 findings or architectural blockers. The audit passed 12 focused
tests and two additional probes for cumulative overflow and cleanup failure;
these overlapping verification counts are not additive. No live infrastructure,
hardware or actual OS-signal verification was performed. Two existing collection
hard-link regressions were blocked by Windows sandbox permissions (WinError 5),
not claimed as passing. See W065 in validated_workflows.md. Q022 remains OPEN for
Controller-to-node installation communication verification, applicable manual
provisioning/installation integration and remaining accepted deployment work.

### Installation Node Communication Check (W066 Closed)

Use the existing Controller deployment-local service file and an explicitly
registered node identity:

```text
lab-sync-acquisition verify-node --deployment-config PATH_TO_CONTROLLER_JSON --node-id NODE_ID
```

Start the target AcquisitionNode and the deployment's existing NATS/JetStream
infrastructure first. The check reads the Controller file through the same strict
loader as startup, including `servers`, `known_nodes` and `result_window_s`; it
does not merge command-line connection/window overrides or alter registration.
Unknown nodes and duplicate configured identities fail before connection. Only
the selected node must respond; other registered nodes need not be online.

The terminal creates a temporary requester connection, not another Controller
service. It uses `NatsControllerCommunication` to issue the existing Session-free
`check_readiness` command. A fresh-only result subscription is scoped to the node
and operation; command, requester, source, Session and per-request nonce must
match. Historical announcements, cached reports, publication acknowledgment and
other operations are not current communication proof. The command does not
provision or change NATS streams.

JSON output reports `node_id`, `outcome`, `communication_confirmed`,
`node_readiness` and `failure_reason`. Exit 0/PASS requires a valid current response
and successful verification-resource cleanup. Hardware/device unreadiness or
node-level `ready: false` does not fail communication verification: the existing
readiness report is retained separately for inspection, including reservation
and individual device/service reports. A rejected request, invalid/stale/mismatched
reply, timeout, configuration/transport failure or unconfirmed cleanup returns
nonzero. Timeout means current availability is unknown, not that acquisition has
stopped. If a valid response arrives after an invalid one within the window,
the current valid response may establish communication. Interruption leaves the
verification unconfirmed and attempts bounded subscription/connection cleanup.
No automatic maintenance, recovery or retry follows.

The partial-connection P2 correction retains the nats-py client before awaiting
connection establishment. Handshake failure or cancellation closes that owned
client and its transport; an incomplete startup is closed directly rather than
drained. The interrupted-cleanup correction retains one boundary-owned cleanup
task: caller cancellation does not cancel that operation, and repeated close
calls join the same operation rather than trusting nats-py's early `is_closed`
flag. Cancellation is propagated only after cleanup completes; a failed cleanup
retains its owned references and remains unconfirmed. A new connection cannot
replace an owned client. Cancellation reporting can therefore wait for the
library cleanup to finish; no cleanup task is intentionally detached from its
awaiting owner. Successful connections retain the existing graceful drain behavior and
`allow_reconnect=False`. The correction does not add retry policy or change the
readiness protocol. Both cleanup P2 findings are resolved by final focused
independent re-audit PASS; no live connection or real-socket validation is claimed.

The check does not initialize/open hardware, reserve devices, launch a Session,
modify scientific/Session products or perform Controller reconciliation. It does
not certify hardware/scientific readiness, Ingestor evidence acceptance or complete
installation. Subject/identity consistency is not sender authentication. Ordinary
Controller registration changes still require Controller restart.

W066 is CLOSED. Independent user-run IPython validation passed 17/17 installation
communication tests and 11/11 connection regressions (separate runs). The audit
history is initial FAIL for partial-client ownership (P2-A), first re-audit FAIL
with P2-A resolved but interrupted cleanup (P2-B), then final focused PASS with
both resolved and no remaining confirmed P0-P3 findings. An additional controlled
concurrency probe passed using actual asyncio tasks/shield and nats-py/TcpTransport
cleanup with simulated I/O: concurrent close callers joined one operation despite
repeated caller cancellation, and actual writer close/wait-closed each completed
once. Automated fixtures use simulated NATS with real AcquisitionNode command/
readiness handling. No live NATS, real sockets, hardware or actual OS-signal
verification is claimed. Normal async execution stalled in the Windows sandbox;
IPython's running loop and controlled execution do not establish normal Windows
asynchronous scheduling validation. See W066 in validated_workflows.md. Q022 remains
OPEN for applicable manual installation/provisioning and remaining accepted
deployment integration; this is not complete installation certification.

### Remote Service Maintenance (W062 Closed)

An independent terminal can address an existing service owner without a running
Controller. Use the common installed command (or the same arguments after
`python -m lab_sync_acquisition.service_launcher`):

```text
lab-sync-acquisition stop --server nats://HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN --result-window-s SECONDS
lab-sync-acquisition kill --server nats://HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN --result-window-s SECONDS --stop-attempt-id BLOCKED_ATTEMPT_ID --authorize-kill
lab-sync-acquisition cancel --server nats://HOST:4222 --target-type acquisition_node --target-id NODE_ID --administrator-id ADMIN --result-window-s SECONDS --stop-attempt-id BLOCKED_ATTEMPT_ID
```

Target types are `controller`, `acquisition_node`, `ingestor`, `storage_manager`
and `synchronization_manager`; the owner must already have its existing NATS
maintenance handler running. This does not enable additional role launch paths.
Every invocation requires explicit servers, target, administrator and a positive
finite request window. Stop creates a new attempt; Kill and Cancel require the
blocked attempt printed by Stop. Kill additionally requires `--authorize-kill`.
Each invocation has a fresh temporary requester and command ID. These identities
are not authentication. There is no automatic retry, Cancel or Kill after a remote
timeout/blocker. An interrupted or timed-out request may already have executed;
inspect the target and retained obligations rather than assuming it was undone.
Interrupted Stop/Cancel feedback states that no automatic force escalation was
requested. Interrupted explicitly authorized Kill instead warns that it may have
been submitted or executed: interruption does not revoke the request, and neither
continued activity nor retirement may be assumed without confirmation.

The terminal uses existing NATS command/result APIs, a fresh-only subscription
scoped to the target owner and operation before publication, and matching command,
requester, Session and attempt identities. A bounded request covers connection,
subscription, publication and result waiting; cleanup also has bounded waits.
Missing, malformed or mismatched results never establish success. JSON feedback
reports actual outcomes, target/requester/command/attempt/administrator identities,
blockers, failures, unresolved obligations and operator action. Only confirmed
successful completion returns 0; blocked, rejected, failed or unconfirmed results
return nonzero. Existing maintenance represents Cancel as outcome `failed` with
reason `Administrator cancelled`; Cancel ends the blocked attempt without force
but consequently returns nonzero. A subsequent Stop uses a new attempt identity.

An owner retirement result is not proof of OS process exit. Ingestor and
StorageManager remain distinct addressed owners in one process; both must satisfy
their own retirement and final-result obligations before the W061 launcher exits.
The terminal does not launch a Controller, create service owners, supervise or
terminate processes, configure dependencies, or implement recovery. Existing
owner-side idempotency, preservation and safety checks remain authoritative.

Focused checks:

```text
python -B -m unittest tests.test_service_maintenance_cli tests.test_service_launcher.LauncherCommandTests -v
```

W062 is CLOSED. Independent IPython passed 41/41 initially and 42/42 after correction
(overlapping runs). The initial audit FAIL identified one interrupted-authorized-
Kill feedback P3; permanent regression coverage and focused independent re-audit
PASS resolved it, with no confirmed P0-P3 findings. See validated_workflows.md for
the preserved audit sequence. Executable sandbox checks passed, but Windows
asyncio socket-pair initialization limited normal asynchronous runs; no blocked
run is claimed as a pass. Controlled checks are not live JetStream, actual
OS-signal delivery, hardware, multi-host or full deployment validation. Q022
remains OPEN. W062 did not implement the remaining launch paths; W063 closes
their bounded implementation above, not the broader deployment work.

## Scientific Data And Operational Evidence Boundary

Decision 377 requires routine scientific observations and per-observation metadata
to remain in AcquisitionNode's LocalStorageManager products, regardless of size.
Classification is by meaning: node-generated operational evidence and manifests
go to Ingestor through NATS, not the observations themselves. Local products retain
existing observation ordering/identity, available acquisition/device timestamps,
Session/Experiment/device/stream provenance and synchronization relationships.
SynchronizationManager remains timing authority; StorageManager later collects
artifacts without changing original scientific ownership or bytes.

Ingestor still owns runtime-evidence intake/audit, journal-before-ACK,
evidence_id deduplication, known-Session reconstruction and compilation. Existing
health/failure, lifecycle/terminal and manifest obligations remain. The bounded
node acquisition implementation now retains start/stop, health and failure
RuntimeEvidenceMessages for durable publication, separately from scientific rows.
No new formats,
evidence categories, or transport for future scientific streaming are defined.

Product-based node acquisition is complete with independent manual validation
and final re-audit PASS after correction (W053). All completed scientific
collections receive local preservation attempts before operational-evidence
handling; independent failures remain visible without false success or automatic
replay. Slice 3B removes obsolete owner-level envelope intake, persistence and
transport, with closeout reconciled against current operational evidence/audit
and manifests. This bounded owner replacement is complete after independent
manual validation and corrective re-audit PASS (W054). The initial audit FAIL
identified the P2 concurrent Normal Stop release/intake race and P3 unused envelope
configuration in a product-failure test; both were corrected. The combined final
Decision 377-378 implementation is accepted in W055 after functional audit PASS
and targeted correction of the sole remaining clean-replacement P3. The user and
ICC determined that no further independent re-audit was needed for that test-only
cleanup; the initial clean-replacement FAIL remains historical.
W051/W052 are historical validated envelope
paths, no longer required for routine scientific acquisition; active durability,
identity, corruption/readback and Q019 preservation/recovery/closure protections
remain. Existing saved products and validation results must not be rewritten.

Decision 378 makes installation-declared scientific products and explicit
Experiment selections authoritative: DeviceAdapters produce their declared and
selected observations/metadata for LocalStorageManager, separately from operational
evidence. AcquisitionNode must not guess meaning from payload size/content or
legacy `runtime_records` labels. The bounded adapter/manager/node path uses
`collect_products(products, *, session_id, experiment_id, acquisition_node_id)`:
`scientific_products` maps selected product IDs to complete observation rows,
and `operational_evidence` contains separate RuntimeEvidenceMessages. Empty
selection performs no scientific reads. Local JSONL/HDF5 persistence retains
the row's metadata and timing; it does not forward observations to Ingestor.
Cleanly replace `collect_records()` / `collect_scientific_records()` and obsolete
scientific-envelope transport, persistence, audit/recovery and compatibility paths,
including dead functions/types, redundant tests and obsolete descriptions. Retain
only interfaces and records serving accepted operational, historical-readback or
other authoritative responsibilities; W051/W052 history is not a compatibility
mandate. Preserve local scientific identity/order/timing/provenance, manifests,
operational events/health/synchronization, and all Q019 preservation/recovery guards.
Obsolete Ingestor/StorageManager envelope APIs are removed in Slice 3B.
New Session Records omit envelope/audit fields; historical fields, when present,
are validated as plain saved data without an active legacy writer. W055 records
final combined implementation acceptance, including functional integration and
the initial obsolete-fixture finding, correction and targeted verification.

## Manual Installation Runbook (W067 Closed)

This integrates W061-W066 capabilities, not a deployment orchestrator or proof of
a working laboratory installation. W067 is CLOSED after independent user-run
validation (4/4 tests, zero failures/errors) and independent architectural audit
PASS with no confirmed P0-P3 findings. The five examples conform to existing strict
loaders, with consistent identities/settings and documented CLI interfaces.
Physical provisioning, live networks/SSH, hardware and full deployment remain
unverified. W068 closes the external-dependent integration below after separate
validation/audit. See W067/W068 in validated_workflows.md. Follow the steps for a new deployment; use the node-change
procedure at the end for additions/replacements. Four focused synchronous checks
validate the examples with actual loaders, identity relationships, CLI dispatch/
help and standalone retrieval configuration. Dispatch tests replace runtime startup;
they do not demonstrate services running. From a checkout with the package installed:

```text
python -B -m unittest tests.test_manual_installation -v
```

### Prepare Computers And Accounts

Use Python **3.12** (`>=3.12,<3.13` in `pyproject.toml`) in an operator-managed
virtual environment on each service computer. From a locally obtained checkout
at the chosen deployment revision:

```text
python -m venv VENV_PATH
VENV_PYTHON -m pip install .
VENV_PYTHON -m pip check
VENV_PYTHON -m lab_sync_acquisition.service_launcher --help
```

`VENV_PYTHON` means the environment's actual executable (`VENV_PATH/bin/python`
on POSIX or `VENV_PATH/Scripts/python.exe` on Windows); activate that environment
for the `lab-sync-acquisition` commands below. Record the chosen revision and
dependency versions in operator installation notes, not a new framework state.
Core dependencies are nats-py, NumPy and h5py; pip installs their declared ranges.
The shared storage computer additionally installs `VENV_PYTHON -m pip install
".[artifact-retrieval]"` for Paramiko. Camera computers need a platform-appropriate
OpenCV build providing `cv2`, camera drivers/backends and device permissions;
these are manual platform requirements, not installed by the core package.

| Computer responsibility | Local owners and operator preparation |
| --- | --- |
| Controller | One Controller process; service identity, known nodes and peer identities |
| Shared storage | One process containing distinct Ingestor and StorageManager owners; writable Session/journal/global artifact paths, retrieval credentials and maintenance callbacks for actual dependents |
| Synchronization | One SynchronizationManager process and its configured peers; scientific synchronization policy stays Session-specific |
| Each node | One AcquisitionNode process; installed adapters, hardware permissions, scientific storage/error-evidence paths and SSH/SFTP account |
| Existing NATS infrastructure | Operator-provided reachable JetStream, suitable stream permissions, storage/retention and network/security configuration |

Compatible roles may share a physical computer but remain separate processes,
except for the mandatory shared Ingestor/StorageManager process. Do not run both
storage role aliases simultaneously. This framework does not install/start NATS,
manage remote processes, create accounts, change firewalls or supervise services.

### Prepare Deployment-Local Files

Copy the relevant files from
[`config_templates/manual_installation`](../config_templates/manual_installation/README.md)
into an operator-chosen directory **outside Git** on each computer. The original
top-level templates remain deliberately incomplete skeletons; the manual examples
provide typed values and show all required file relationships. Replace uppercase
placeholders manually; the loader does not expand environment variables. Choose
the illustrated windows, camera backend/source, shape/dtype and collection settings
explicitly for the installation; these values are not scientific timing defaults.

Keep `CONTROLLER_ID`, `INGESTOR_ID`, `STORAGE_ID`, `SYNCHRONIZATION_ID` and each
persistent `ACQUISITION_NODE_ID` consistent across files. The node identity must
match its Controller `known_nodes` entry and StorageManager retrieval mapping key.
Give every installed device a stable distinct device identity and declare its
supported scientific products. The hardware example currently uses the file
loader's supported `seeed_imx219_opencv` adapter; it is not a general camera
assumption or authorization for unsupported adapters.

General-service relative paths resolve beside that service file; hardware-file
scientific/error paths resolve beside the hardware file. Choose writable storage
and error-evidence locations and check capacity/permissions under the actual
service account. Keep keys and private values outside Git and portable Session
products. Do not reuse private example directories as scientific output.
Configuration changes take effect after restart, with no live reload.

Validate each edited service file locally without connecting or opening hardware:

```text
python -c "from lab_sync_acquisition.deployment_configuration import load_service_configuration; load_service_configuration('CONTROLLER_JSON', 'controller'); print('configuration valid; readiness untested')"
```

Use the same public call with `synchronization-manager`, `acquisition-node`,
`ingestor` or `storage-manager` and its file path as appropriate. Node service
validation reads its separate hardware file; it does not construct an adapter.
SSH key/known-host references must already exist for storage validation. Missing
or invalid values must be corrected before startup; do not suppress diagnostics
or combine file inputs with explicit launch-setting flags.

**W068 external-dependent maintenance (CLOSED):** configure actual dependents, not
an empty callback map or a false isolated declaration. For example:

```json
{
"external_dependents": [
  {"component_type": "controller", "component_id": "CONTROLLER_ID"},
  {"component_type": "synchronization_manager", "component_id": "SYNCHRONIZATION_ID"},
  {"component_type": "acquisition_node", "component_id": "ACQUISITION_NODE_ID"}
],
"result_window_s": 10
}
```

Merge these fields into the existing complete storage JSON; this fragment omits
the other required storage settings and is not a standalone service file.
Alternatively append repeated `--external-dependent controller/CONTROLLER_ID`,
`--external-dependent synchronization_manager/SYNCHRONIZATION_ID` and
`--external-dependent acquisition_node/ACQUISITION_NODE_ID` plus explicit positive
`--result-window-s SECONDS` to the flag-based shared-pair command, replacing
`--no-operational-dependents`. Both storage role names still launch one process.

Each deployed owner has a new operational-instance ID while keeping its persistent
RuntimeParticipant identity. Existing maintenance handlers are available during
startup; unrelated operational work remains closed until the current instance is
registered with the configured Ingestor. The Ingestor validates fresh owner readback
and retains instance-scoped callback state using its existing framework journal
and StorageManager archive. A new instance reestablishes the blocker before its
operational admission. Unconfigured identities are rejected, not discovered.

After actual Stop or authorized Kill retirement, the owner delivers its exact
command/result/attempt confirmation to Ingestor. Ingestor verifies fresh owner
readback and preserves its acceptance before confirming. The launcher cannot exit
until this exchange and existing final-result handling complete. Lost replies,
cancellation or unavailable participants leave exit unconfirmed; explicit retry
reuses the retained retirement result without repeating cleanup. Unknown/malformed,
stale or contradictory confirmation keeps the blocker. There is no automatic
dependent shutdown, Kill escalation, polling or restart.

If a blocked shared-pair Stop is cancelled, Cancel ends that attempt without
reopening resources already cleaned up. A later explicit Stop uses a fresh attempt
and can complete once the dependent obligations are authoritatively released.

Confirmed releases remain usable after the dependent exits. Decision 390 requires
ordinary startup to reconcile an intact historical framework archive before
restoring eligible dependent releases: Ingestor reconstructs its journal and
compilation; StorageManager verifies archive integrity, internal consistency and
exact historical-prefix agreement with recovered evidence and applicable intake
audit. Existing archival mechanisms may then preserve additional accepted recovery
evidence, with complete current-compilation verification before confirmation.
Journal history or historical confirmation alone is insufficient. Decision 389's
instance, attempt, freshness, contradiction and supersession checks still apply.

This ordinary continuation integration is implemented and validated in W068.
StorageManager's ordinary-write guard also prevents maintenance from overwriting
history rejected by continuation, while preserving legitimate initial creation.
Until current preservation is confirmed, callbacks remain
blocked. Missing, conflicting, corrupted or unverifiable history and failed
continuation cannot authorize release, conflicting overwrite, journal truncation
or silent repair. Actual interrupted-write recovery remains separately subject to
Decisions 339/342/347 and applicable administrator authorization; ordinary restart
is not automatically such recovery. No new recovery subsystem is introduced.
Local legacy callbacks remain supported for development; deployed communication
uses NATS.

Focused regression entry point (no live infrastructure required):

```text
python -B -m unittest tests.test_external_dependent_maintenance -v
```

Codex verification uses controlled socket-free scheduling with actual asyncio
tasks; it does not establish normal Windows socket-pair scheduling, actual OS
signals, live JetStream or separate-machine behavior. W068 is CLOSED after
independent manual IPython validation (3/3 scenarios across two executions after
correction of a harness error) and final independent audit PASS with no remaining
confirmed P0-P3 findings. The initial P2 maintenance-write bypass was corrected
and independently confirmed resolved. See W068 in validated_workflows.md for
overlapping verification runs and limitations; no power-loss validation is claimed.

Decision 389 now resolves W068's confirmation architecture: each dependent owns
its retirement/release, and Ingestor requires correctly correlated operational
instance/attempt confirmation delivered before the dependent launcher exits.
Only Controller's specifically authorized dependency release at the final archival
checkpoint, with preserved obligations and no further Ingestor-dependent work,
allows its dependency to be released while Controller remains operational.
Missing/stale/contradictory confirmation retains the blocker; preparation,
disappearance and publication acknowledgment are insufficient. This is
implemented by the bounded W068 path, not a new lifecycle state or retirement
authority. Controller's coordinated release additionally freezes its own new work
and further Ingestor-dependent evidence; it can continue the existing prepared
retirement sequence without writing through retired Ingestor. W068 is CLOSED;
Q022 remains OPEN and no full physical deployment verification is claimed.

### DeviceAdapter Session Parameters (W069 Closed)

`AcquisitionNode.get_inventory()` and the existing NATS `get_inventory` command
return `session_parameter_definitions`, keyed by installed device ID alongside
unchanged `devices` declarations/products and synchronization authority.
`await controller.get_node_inventory(participant, communication=communication,
result_window_s=...)` retrieves a fresh correlated snapshot for clients without
creating a Session, reserving devices or opening hardware. Availability of
definitions is not acquisition readiness. No GUI or additional transport is added.

Each adapter implements `get_session_parameter_definitions()` as a mapping from
parameter names to plain-data constraints. Supported `type` values are `integer`,
`number`, `boolean` and `string`; constraints use `allowed_values`, `minimum`,
`maximum`, `exclusive_minimum`, and `nullable` (absent means false). Bounds and
choices are adapter-owned, not a universal camera parameter set. Adapters exposing
no Session-adjustable settings return an empty mapping.

Use the existing `SessionConfig.device_configurations` mapping for partial
per-device overrides, for example `{"camera": {"frames_per_collect": 2, "fps": 30}}`.
Omitted device overrides, empty mappings and omitted parameter keys preserve the
deployment baseline. Explicit null is accepted only for a nullable parameter.
Unknown/installation-only keys, wrong types, booleans used as numbers, nonfinite
numbers and constraint violations are rejected without coercion before applying
Session settings. Configuration selection is not permission to alter installation
connections. The OpenCV adapter exposes `frames_per_collect` (integer >= 1),
nullable `frame_width`/`frame_height` (positive integers), and nullable `fps`
(positive finite number); `camera_source` and `api_preference` remain installation
settings. Existing hardware setup/readiness remains adapter-owned.

Node preparation resolves each Session against detached deployment defaults, not
the previous Session's active configuration. Successful shutdown returns adapters
to DECLARED under Decision 302; existing failed-cleanup/reservation protections
still prevent unsafe reuse. W069 is CLOSED after independent IPython validation
(6/6 and 9/9 PASS) and architectural audit PASS with no confirmed P0-P3 findings.
The additional selection-boundary probe did not complete full initialization
because of unrelated missing local-storage configuration. No live NATS, camera
hardware or normal Windows asynchronous scheduling validation is claimed; see
W069 in validated_workflows.md. Q022 remains OPEN for remaining deployment work.

### Provision And Verify Retrieval

On the node, the administrator enables an existing SSH server with SFTP, creates
or selects the retrieval account, and authorizes the approved public key. The
account needs traversal/read permissions on the chosen dummy path and, later,
node-owned artifact paths; it need not own or alter scientific output. On the
storage computer protect the corresponding private key and verify the node host
fingerprint through a trusted channel before adding it to the trusted known-hosts
file. Do not disable host-key verification or assume an interactive passphrase
prompt is supported by this transport. Use the configured, lab-approved usable
key reference; this procedure adds no secret-management mechanism.

Follow the exact binary dummy-file and independently prepared expected-file
instructions in [Installation Retrieval Check](#installation-retrieval-check-w065-closed),
then on the StorageManager computer run:

```text
lab-sync-acquisition verify-retrieval --deployment-config STORAGE_JSON --node-id NODE_ID --source-path REMOTE_FILE --expected-file EXPECTED_FILE --max-bytes 65536
```

This check needs the SSH/SFTP endpoint and optional retrieval dependency, not a
running Controller, NATS or shared service process. Its subset configuration
reader does not require a false no-dependents declaration. PASS requires exact
independently expected bytes and successful cleanup within bounded temporary
storage. Authentication/host trust, missing file, size, transfer, permission or
content failures need operator correction and an explicit rerun. Do not derive
expected bytes from the download. Remove only operator-created scratch files
afterward, never scientific artifacts. This does not deeply verify scientific
artifact contents or authorize their release.

### Launch And Verify Communication

With NATS/JetStream already available and the shared pair's **actual external
dependents configured**, start the pair first, then SynchronizationManager, nodes,
and Controller in separate terminals under their service accounts. These are
manual entry points, not an automatic dependency-ordering mechanism:

```text
lab-sync-acquisition ingestor --deployment-config STORAGE_JSON
lab-sync-acquisition synchronization-manager --deployment-config SYNC_JSON
lab-sync-acquisition acquisition-node --deployment-config NODE_SERVICE_JSON
lab-sync-acquisition controller --deployment-config CONTROLLER_JSON
```

The first command uses either the explicit external-dependent file mode or the
truthful isolated mode above. Never use a false declaration. `storage-manager` is an alias for the
same pair, never a second process. Startup diagnostics/readiness distinguish local
configuration, NATS connectivity and peer availability. A process staying alive
is not evidence of readiness or successful Session initialization. StorageManager
validates retrieval settings without requiring remote SSH nodes online.
Controller checks configured peers with bounded waits; **all registered nodes
need not be online to start Controller**. Unreachable peers remain unknown, not
failed or stopped. No hardware initialization or Session launch is implied here.

Once the selected node's command handler and NATS are available, run in a separate
terminal with the Controller deployment file:

```text
lab-sync-acquisition verify-node --deployment-config CONTROLLER_JSON --node-id NODE_ID
```

No Controller process is required for this check. Inspect `communication_confirmed`
separately from `node_readiness`: a valid hardware-unready reply may PASS
communication. Timeout/mismatched/unconfirmed replies return nonzero and mean
availability is unknown, never stopped acquisition. Diagnose addressing,
registration, permissions and connectivity, then rerun explicitly. Current replies,
not historical announcements, establish communication.

For retirement, Ctrl+C requests existing maintenance Stop, automatically Cancels
a blocked attempt and keeps running. Failed/unconfirmed Stop also retains the
process. Repeated interrupts do not authorize Kill. Use the existing
[remote maintenance commands](#remote-service-maintenance-w062-closed) for addressed
Stop, explicit authorized Kill continuation or Cancel; maintenance is not Session
Normal Stop, and one owner's retirement is not proof the shared process exited.

### Recommended Device Check And Node Changes

Strongly recommend a representative acquisition/inspection/cleanup check for each
new device, recorded manually, without adding a certification state or runtime
gate. There is no general Session/Experiment operator CLI or universal device-test
command. Use existing public Session/Experiment interfaces with explicit product
selection, or a supported device-specific manual script. For the current camera,
`python scripts/manual_opencv_camera_smoke.py --help` describes the existing
hardware smoke workflow from a checkout. It constructs a local demonstration
composition, not independent production services: run it only with exclusive
camera access, outside an active node reservation, and choose an output directory
outside Git. Install its device/backend dependencies first. Select scientific
recording explicitly and inspect finalized observations, timing/provenance and
manifests; stop and release the hardware safely. Other hardware may require vendor
tools/manual actions until its adapter and installation loader are supported.
No success from the communication check substitutes for this device assessment.

For an added node, repeat package/account/path/SSH/hardware preparation on its
computer, assign a unique persistent identity, and add the matching retrieval
endpoint, shared-file `external_dependents` AcquisitionNode participant and
Controller `known_nodes` entry. Plan affected service restarts
only after existing cleanup, preservation and maintenance obligations permit them;
endpoint-file edits also require restarting the shared pair. Repeat retrieval and
communication checks and the recommended device check. Do not restart unrelated
nodes, interrupt their acquisition, or treat a Controller restart as a Stop command.
Controller must restart to load registration changes and use existing current
readiness/reconciliation, not runtime registration or polling. If a safe maintenance
window is unavailable, defer the change rather than force termination.

For replacement, do not reuse an identity while the old node may still be active
or has unresolved reservations/artifact obligations. Retire it through existing
maintenance and preserve its scientific files, manifests and historical retrieval
access. If a new host/path cannot provide access to the old node-owned artifacts,
use a new persistent identity and retain the old endpoint as needed; do not redirect
historical retrieval silently. Host replacement requires newly verified host-key
trust. Do not manually repair journals, rewrite history or invent migration/recovery
semantics as part of installation. Retain operator notes of configuration choices
and results; actual network, SSH, hardware, signals and complete deployment remain
laboratory verification, not claims of W067 validation.

## Accepted Manual Procedure

1. Install the common software package and dependencies needed by the chosen
   supported devices/services. Select the service role explicitly at launch;
   configuration does not implicitly start services. Use the existing CLI and
   deployment files in the manual runbook below.
2. Create installation-local configuration outside the Git repository from
   committed templates/definitions. Keep NATS/service storage/retrieval settings
   distinct from node hardware settings. Credentials and private keys stay outside
   Git and portable Session evidence.
3. Assign the node's persistent unique identity, identify installed devices,
   select adapters explicitly, and configure their physical connections and
   node-owned scientific storage. Do not infer hardware through discovery.
4. Configure key-based SSH/SFTP access and the StorageManager mapping from logical
   node identity to endpoint/authentication references. Verify connectivity,
   retrieve a small dummy file, and confirm retrieved bytes match the source.
   Required retrieval setup must succeed before the node is fully installed.
5. Add the identity to Controller's local known-node list and restart Controller
   to load it. Report duplicate identities as conflicts; do not launch against
   ambiguous identity. Coordinate restarts between Experiments without bypassing
   existing active-acquisition safeguards.
6. Start Controller, SynchronizationManager, and nodes independently, and start
   Ingestor and StorageManager together in their combined process. Verify node NATS connectivity and
   Controller-to-node readiness request/response through existing communication.
   Historical announcements are not current readiness; missing replies mean
   unknown availability, not confirmed failure or stopped acquisition. Use the
   explicit `verify-node` command above with Controller's deployment file to check
   one registered node without starting another Controller or running reconciliation.
7. Strongly recommend a device-appropriate acquisition smoke check: communicate,
   acquire representative data, inspect output/local persistence, stop safely,
   release resources, and record results. This is not a mandatory runtime gate,
   commissioning certificate, or universal acquisition-test interface.

Installation changes require service restart; live reload/registration is not
required. AcquisitionNode startup supports both a default local configuration
location and an explicit path: the flag-only path defaults to
`~/.config/lab-sync-acquisition/acquisition-node.json`, or accepts `--config PATH`.
File mode instead requires `node_config` in `--deployment-config PATH` and cannot
be mixed with `--config`. Future setup utilities must use the same
runtime file-loading/validation mechanism; no interactive installer is required.

Valid configuration is not proof of hardware readiness. Invalid/missing node
configuration must diagnose the problem and prevent acquisition. Existing readiness
reports actual hardware/service conditions. StorageManager validates local retrieval
configuration at startup but checks node connectivity when retrieval is requested;
temporarily offline nodes do not block its startup. Installation checks do not
require continuously reachable SSH/SFTP during scientific Sessions. NATS connection
alone does not establish durable Ingestor acceptance or Q019 completeness.

## Current Reusable Interfaces And Gaps

| Boundary | Existing foundation | Missing integration |
| --- | --- | --- |
| Package/launch | W061-W063 common explicit-role entry point; W064 integrates general service files with the same launchers | Complete deployment integration and verification |
| Local configuration | W064 JSON loader/templates, startup validation; W063 node hardware loader/default and explicit paths; W068 external-dependent composition, instance-confirmation and ordinary continuation CLOSED after independent manual validation/audit | Actual provisioning and remaining deployment integration |
| Node/device setup | Existing declarations/adapters and W063 file-to-object construction; W064 reuses hardware prevalidation | Additional supported adapters as required by deployments |
| Operator parameters | W069 CLOSED: adapter-defined constraints, existing node/NATS inventory exposure, Controller readback and validated partial Session overrides after independent validation/audit | Actual device and deployment verification |
| Readiness/startup | Existing reports, NATS requests/announcements and reconciliation consume W064 configured known-node identities; W066 explicit installation `verify-node` using existing readiness requests is CLOSED after independent validation and final re-audit PASS | Applicable manual installation integration and live deployment verification |
| Scientific retrieval | Existing endpoint mapping/pull and host-key checks; W064 local validation; W065 explicit installation dummy retrieval and exact comparison CLOSED after independent validation/audit PASS with simulated SSH/SFTP | Actual installation verification and live deployment validation |

Current demos and optional manual hardware checks are not a general installer.
Concrete camera configuration is an adapter example, not the generic parameter
contract. No principal-service package split, registry, database, plugin framework,
GUI, supervision, automatic discovery, or new readiness state is needed here.

Local development archival/collection and maintenance preservation use actual
Ingestor/StorageManager collaborators, including synchronous owner guards. Remote
single-Session collection/closure are validated in W058/W059; distributed active
Session closeout and independent release are validated and closed in W060,
described below. Decision 376 permits local Ingestor-StorageManager calls but
requires NATS for Controller and other process-crossing access. Broader remote
maintenance/recovery and deployment adaptation remain pending. Establish the
necessary service-owned NATS interfaces before
enabling launch paths that depend on them. Missing responses, failures, and
timeouts must remain unconfirmed; retries must retain existing identity,
durability, idempotency, and recovery protections.

## Cross-Service Implementation Boundaries

This source assessment groups current interactions by receiving owner; it does
not approve new command names, payload schemas, distributed locks, or a generic
remote-object subsystem. Reuse `RuntimeParticipant`, `RuntimeCommandMessage`,
`RuntimeCommandResultMessage`, existing routing/streams, and
`NatsControllerCommunication.request_command()`/group outcomes. These already
correlate requester, receiving identity, Session, and command, with bounded result
waiting. Existing publication does not itself confirm receiver execution.

The call-path descriptions below identify existing owner responsibilities, not
separate processes for the combined pair. Ingestor-to-StorageManager and
StorageManager-to-Ingestor readback, release guards, compilation, and recovery
inputs may remain local under Decision 376. Only external callers require NATS
adaptation; do not replace permitted local synchronization with remote requests.

### Operational Evidence And Owner Readback

Slice 3B removes the W051/W052 scientific-envelope writers, correlated-write
APIs and NATS dispatch. Their historical validation and audit outcomes remain
unchanged in the validated-workflow records; they do not require obsolete code.
Construct `PersistentStorageManager(storage_root, ...)` with a directory, not
an envelope-record filename. Ingestor may hold that existing owner locally under
Decision 376; it does not instantiate a second StorageManager.

- `InMemoryIngestor.receive_runtime_evidence()` retains operational messages and
  manifests with existing journal-before-ACK, identity/deduplication and restart
  semantics. `compile_durable_session_evidence(session_id)` returns journal-verified
  persistent evidence, complete operational intake audit and the manifest handoff,
  not scientific observations or an archival-completion claim.
- `NatsIngestorCommunication` retains `compile_session_evidence` and
  `verify_acquisition_receipt` requests; the latter delegates to W041 owner proof.
- `NatsStorageManagerCommunication` retains readiness and
  `read_session_preservation`; no envelope persistence/readback command remains.
  Maintenance/recovery still requires the existing authorized owner interface.
- `NatsControllerCommunication.request_persistence_command(...)` retains scoped
  readback, fresh-only replies and per-attempt nonce correlation. Missing replies
  and failed readback never establish preservation or authorize release.

Controller's Session Records retain configuration/lifecycle/Experiment outcomes,
not copies of the operational Evidence Archive. Completion and release compare
current persistent operational evidence and the complete intake audit with exact
owner-side archival readback under existing guards. Kill obligations apply even
with no intake or unavailable archival confirmation; manifest handoff coverage
and terminal-state checks remain mandatory. Stage A/B, authorized recovery and
permanent immutability are not replaced by transport acknowledgments.

W054 records independent validation and corrective re-audit PASS for this bounded
replacement; W055 separately records final Decision 377-378 implementation
acceptance, not deployment certification.
Controller release holds intake -> preservation locks through final checks and
binding retirement, never across unsubscription awaits. Later accepted intake
remains Ingestor-owned and blocks release until current preservation is confirmed;
existing Stage A reconciliation is limited to accepted lifecycle boundaries and
cannot rewrite Stage B history or closed archives. Cross-process Controller
closeout, maintenance/recovery and release adaptation, shared-process bootstrap,
role launching and installation checks remain pending. No live deployment,
hardware or independent power-loss guarantee is established here. Q019 remains
CLOSED; Q022, Q024, Phase 16 and M015 remain OPEN.

### Acquisition Commands And Experiment Context

**Controller -> AcquisitionNode:** The original local `start_session()`,
`run_one_iteration()`, `stop_session()` and Experiment APIs remain in-process
development workflows. Launched Session startup/stop reuse existing NATS node
commands; Slice 2 adds actively used launched Experiment context/health activation
and finalization, synchronization readiness and current timing readback. Health
assignments in `start_launched_experiment` are keyed explicitly by node identity,
not broadcast across nodes or inferred from scientific product contents.
Canonical Experiment start precedes context delivery, and unsuccessful/cancelled
delivery retains terminal outcome and cleanup uncertainty separately. Remaining
broader closeout/release and external recovery adaptation stays outside this slice.
The node retains
Session-keyed reservations, terminal Experiment/file protections, device safety,
and W042 publication-before-success with concurrency-safe evidence cursors. A
timeout cannot prove cleanup or reservation release. Depends on receiving/timing
interfaces below, not creation of node collaborators in Controller.

### Sustained Acquisition Execution (G3 Closed)

The independent AcquisitionNode launcher enables sustained execution in its
existing NATS adapter before command admission. Session runtime startup alone
does not imply recording: an active Experiment must select scientific outputs.
After `start_launched_experiment()` activates that context, one node-local task
repeatedly calls the existing `AcquisitionNode.run_one_iteration()`; the PC does
not send an iteration command for each frame. Repeated activation or scheduler
enable does not create another recording task. An Experiment without scientific
outputs remains idle. Finalizing an Experiment ends its task; later activation
can begin another task while the Session runtime stays operational.

Direct bounded Python callers retain the existing iteration API. A manually
composed NATS service enables the same behavior with
`await handler.start_acquisition_execution()` before admission. Its maintenance
resource-cleanup callback calls `await handler.stop_acquisition_execution()`
after the owner's device cleanup. Disabling the scheduler alone is not device
cleanup, finalization, Session completion, or service retirement.

Controller disconnection is not a stop trigger. Frames, timestamps, mapping
provenance, and health evidence use the existing local scientific and operational
paths. Publication failure retains existing evidence/cursors without stopping
acquisition solely for that reason. A collection/storage failure follows the
node's failure-evidence contract and attempts existing runtime stop/finalization;
it does not independently transition the Controller's Session lifecycle.
Blocked maintenance leaves existing acquisition obligations operational; Cancel
does not authorize Kill. Authorized runtime stop/finalization quiesces execution,
and service cleanup disables and joins the task before retirement can complete.

Iterations remain bounded synchronous calls on the node service event loop and
yield between collections. This adds no configured sampling cadence or read
timeout: camera settings, `frames_per_collect`, and existing persistence batching
remain authoritative. A blocking device read or evidence-publication wait can
delay progress; no hard real-time or lossless-camera guarantee is established.
G3 is CLOSED within its validated software scope after 26 implementation checks,
5/5 independent ICC IPython checks and separate independent Codex audit PASS with
no confirmed P0-P3 findings. The audit passed 15 automated checks and two adversarial
workflows; these are separate stages, not additive totals. Three end-to-end
distributed closeout checks remain blocked by Windows hard-link permissions and
are not claimed as passing. No live PC-Jetson deployment, live NATS/JetStream,
physical camera recording/performance, OS-signal, power-loss or normal Windows
asynchronous scheduling validation is established. See
[G3 closure](validated_workflows.md#g3---sustained-acquisition-execution) for the
complete evidence record. G2/G4/G5 are not completed by G3; Q022, Q024, M015 and
Phase 16 remain OPEN.

### Timing And Synchronization

**Accepted target (Decisions 379-381; not implemented by documentation
synchronization):** SynchronizationManager establishes node-specific mappings
from sufficient measured cross-clock exchanges accounting for network delay,
variability and uncertainty. An initial mapping may use an explicit,
conservatively bounded clock-rate assumption without prior drift estimation.
Only SynchronizationManager determines validity, refinement and replacement;
periodic quality checks are distinct from complete resynchronization.

AcquisitionNode applies the authorized affine mapping locally:
`session_time = session_anchor + scale * (node_local_time - local_anchor)`.
Experiment Time derives from Session Time. Mapping changes apply atomically and
prospectively. Existing scientific observations/artifacts retain required Session,
Experiment, node-local, available device-native and timestamp-quality information;
mapping history and each node-local activation boundary support reconstruction
without requiring a mapping ID on every observation. Scientific observations and
their metadata remain local under Decisions 377-378.

Acceptable synchronization is required at Session acquisition readiness and before
each Experiment. Cadence and quality thresholds are configurable. Temporary
degradation preserves local timing, mapping provenance and explicit degraded
timestamp status; existing TimingQualityPolicy interpretation and Controller
authority determine consequences, not automatic acquisition termination. Reuse
existing NATS, schemas, evidence and storage contracts; do not assume shared
clocks, substitute message arrival time or issue per-observation network timestamp
requests. Q006/Q018 retain advanced algorithms, hardware synchronization and
offline refinement, except for the minimum demonstrably valid measurement method
required for this implementation. No additional clock authority or service is
introduced.

**Slice 2 implementation (complete; independent validation and audit PASS, W056):**

Construct remote nodes with `synchronization_source_id` and no local
SynchronizationManager. Set `SessionConfig.synchronization_configuration` to the
plain-data form of `SynchronizationConfiguration(exchanges, initial_scale,
clock_rate_error_bound, max_uncertainty_s, max_mapping_age_s,
assessment_interval_s, result_window_s, quality_interpretation)`; all values are
explicit, with no scientific timing defaults. `clock_rate_error_bound` bounds
absolute error in Session-seconds per node-local second relative to initial_scale.
The supported degraded-condition policy uses the configured interpretation label;
Controller records its corresponding decision without autonomous termination.

`Controller.start_launched_session()` uses the configured synchronization
participant over NATS before node acquisition. SynchronizationManager starts its
single clock once and intersects causal bounds from multiple timestamped exchanges,
including platform clock resolution and the explicit rate bound, without assuming
symmetric delay. Node-local validity deadlines bound continued use without
per-observation network requests. `assess_synchronization` retains the mapping;
`resynchronize` is an explicit measured replacement request. Periodic assessments
are cancelled on timing closeout/adapter close, not converted into automatic
acquisition termination or recovery.

Use `Controller.start_launched_experiment(...)` and
`stop_launched_experiment(...)` for launched distributed execution. They use
existing product preparation plus NATS context/health activation and scientific
finalization; applicable node evidence is published before successful results.
Canonical lifecycle remains Controller/Session-owned. Each observation uses its
node-local timestamp and applicable activation boundary; native timing remains
separate. New operational mapping activation and quality records use existing
RuntimeEvidenceMessage retention/publication and archival pathways, not scientific
payload forwarding or a new evidence transport.

Node-local quality application boundaries and owner-issued expiry remain retained
as timing-quality runtime evidence, so buffered observations keep acquisition-time
quality across later degradation, reassessment or remapping. Transient periodic
assessment/publication failures retain evidence and resume at the configured
cadence; explicit timing closeout and transport shutdown still cancel assessment.

Command identity and Session scope are admitted before stop cancellation.
Rejected commands cannot cancel monitoring; duplicate stops preserve identity.
Cancellation is awaited outside the runtime lock, before closeout evidence
publication. Failed publication remains unconfirmed and retained for retry.

The optional cross-process developer test uses actual local JetStream with
SynchronizationManager and AcquisitionNode in separate spawned processes. Other
focused workflows use broker doubles and real domain owners. W056 separately
records independent user-run IPython validation and final read-only audit PASS,
including actual local JetStream verification. Neither establishes hardware timing,
multi-host accuracy, power-loss recovery or advanced synchronization guarantees.
W001-W055 remain unchanged; Q006/Q018 remain OPEN; Q019 remains CLOSED and Q022 OPEN.

**Remaining adaptation outside this slice:**

The established in-process APIs continue to use explicit local collaborators for
development/testing; the launched distributed timing/Experiment path above does
not depend on those objects. Broader Controller closeout and deployment bootstrap
remain outside this implementation.
**SynchronizationManager -> Ingestor/StorageManager:** `release_session()` and
`reconcile_timing()` inspect accepted mapping evidence, journal durability, and
framework archival through direct owners. Missing NATS evidence readback and
acceptance/preservation checks depend on the evidence-owner interfaces below.
Retain historical mappings, uncertainty, and the prohibition on untrustworthy
active-Session clock restoration. Local timing helpers are not new services.

### Producer Intake And Publication Confirmation

Decision 377 removes routine scientific envelope delivery and its additional
intake-correlation requirement. Existing RuntimeEvidenceMessage identity,
journal-before-ACK and restart-safe deduplication remain mandatory. Evidence
acceptance, StorageManager persistence confirmation and archival completion
remain distinct.

**AcquisitionNode/Controller/other producers -> Ingestor:** W053 removes node
scientific-envelope production/forwarding. Node `_retain_runtime_evidence()` and
`_record_artifact_manifest()` retain messages before optional development-time
local intake; the NATS node adapter publishes operational evidence/manifests
before applicable command results. Controller decision and
Experiment-rejection evidence also use direct `receive_runtime_evidence()`.
Manifest recovery calls `has_durable_runtime_evidence()` on the same object.
Reuse existing evidence publication/subscription, producer retention and correlated
commands/results. Slice 3 is CLOSED in W057 after independent IPython validation
and read-only audit PASS of 880b108, with no confirmed P0-P3 findings. It extends scoped readback with
`read_runtime_evidence_acceptance`, using `request_persistence_command` and payload
`{"evidence": message.to_dict()}`. Ingestor checks exact current journal coverage
under its existing history guard and returns `durable_acceptance_confirmed` plus
the evidence identity and per-attempt nonce. Missing, stale or timed-out replies
are not confirmation. This is acceptance readback, not complete W041 receipt,
StorageManager persistence or archival confirmation. It does not append evidence.

Intake validates the delivered NATS subject against the evidence Session, source
and type before acceptance, and confirms journal-backed acceptance before Session
ACK. Optional callback cancellation leaves durable intake available for broker
redelivery; identical redelivery does not append another accepted message or rerun
the optional callback. Producers retain unconfirmed publication identities and
reuse existing publication cursors and JetStream durability, not a second intake
transport. Subject consistency is not cryptographic sender authentication; broker
access control remains a deployment responsibility.

Developer verification includes a local JetStream receiver in a separate process,
offline publication, lost publication confirmation, restart and exact acceptance
readback; focused doubles cover journal failure, misrouting, callback cancellation,
duplicate/conflicting content and stale/missing replies. W057 records developer
52-test and nine-check runs, independent IPython PASS, and final audit PASS with
50 tests and three probes; these overlapping counts are not additive. Optional
callbacks are not a durable retry queue. Multi-host, hardware and power-loss
guarantees remain unverified. Neither publication nor acceptance authorizes
scientific-artifact release.
Remaining cross-owner recovery/Controller orchestration is not adapted by this
bounded change, and scientific-envelope delivery is not reintroduced.
Preserve applicable failure reporting, stable evidence identity,
same-content deduplication, retained-manifest retry, and journal-before-ACK.
Publication confirmation, Ingestor acceptance, and complete receipt remain distinct.
Depends on owner runtime-evidence validation and local scientific persistence;
do not turn Ingestor's internal framework partition into another service owner.

### Historical Session Record Interpretation

Existing historical Session Records may contain scientific envelopes and their
intake audit. StorageManager validates those fields when present, rejecting
incomplete or cross-Session information before preservation/collection confirmation.
It does not rewrite them, reconstruct envelope objects, or provide legacy intake,
transport or append APIs. New records use the retained Session/Experiment and
operational archive contracts, without obsolete scientific-envelope fields.

### Receipt, Compilation, And Kill Obligations

**Controller -> Ingestor:** `normal_stop_session()` and
`archive_acquisition_evidence()` require a local `NatsIngestorCommunication`
instance and matching Ingestor object. `_preserve_kill_closeout()` admits Kill
handoff obligations and reads current journal-backed operational evidence and
its complete intake audit. Reuse Ingestor's existing W041
`verify_acquisition_evidence_receipt()`, journal verification, persistent
compilation, and handoff compiler inside the receiving service. Missing NATS
operations expose their owner-confirmed results and admit obligations before
asynchronous shutdown, including empty intake. Preserve marker identity/sequence,
receiving origin, intact history, contiguous ACK proof, journal-before-ACK,
Session isolation, and explicit Kill incompleteness. Missing/invalid proof is not
complete receipt. Depends on producer/record intake; no Controller-owned consumer
or receipt reconstruction is needed.

### Stage A, Session Records, Handoff, And Binding Release

**Accepted contract (Decision 382; bounded implementation CLOSED in W060):** The Normal Stop
marker is last-call after required producer-publication confirmations. Ingestor
independently proves complete durable receipt through the marker, including the
full publication interval, contiguous JetStream receiving progress and journal
consistency, before establishing final acquisition intake. After finalization,
subsequent acquisition deliveries, including duplicates, are rejected/discarded
without changing finalized Stage A evidence, audit or final Session Record.
StorageManager verifies durable corresponding complete Stage A products and the
applicable handoff. Together these establish acquisition-preservation eligibility,
not automatic Session completion or release.

Controller retains lifecycle authority and requires all existing lifecycle,
cleanup and safety obligations plus a correctly correlated owner preservation
result. Publication/ACK alone is insufficient. Existing NATS/JetStream and durable
Session products/journals/readback/recovery must preserve independently verifiable
eligibility across restart; missing, delayed, duplicated, cancelled or superseded
confirmations cannot authorize an inappropriate transition. Do not rewrite
finalized evidence or unnecessarily repeat confirmed Stage A. Each service
independently releases under Decision 313; Stage A does not confirm remote cleanup
or hardware safety. Kill partial-preservation/recovery and later Stage B/explicit
permanent closure remain separate. No new reliability subsystem, transaction
coordinator, registry or Session state is authorized.

**Validated implementation - remote closeout (W060):** A Controller with no local
Ingestor/StorageManager references uses its launched NATS communication plus an
explicit `storage_participant` for `normal_stop_session()` or authorized
`kill_session()`. The receiving Ingestor adapter offers `admit_session_kill`,
`preserve_session_acquisition`, `read_session_closeout`,
`preserve_session_terminal_record` and `release_session`. These use fresh-only
commands, complete scoped durable result history, per-attempt nonce/request
correlation and current owner readback; missing responses never confirm success.

Ingestor stores Kill admission or exact normal finality in its existing recovery
journal. Normal finality follows W041 receipt verification and freezes evidence
identities, marker receipt and the complete audit. Restart retains that audit
instead of generating replacement recovery entries. Later deliveries are discarded
without changing the frozen interval. Ingestor calls its paired StorageManager's
existing writers and guards locally, and reconciles archive evidence, audit,
Session Record, handoff and marker provenance. Partial Kill never claims complete
receipt. Changed intake cannot silently replace historical preservation.

Session finality does not close framework intake: Session-independent messages
still route to the configured framework journal. Early Controller closeout
association protects cancellation without rejecting in-flight health decisions.
Controller verifies their publication before creating the last-call marker; new
health decisions are rejected once that marker exists.

Controller completes only after confirmed normal preservation and its own cleanup
requirements, then preserves terminal lifecycle. Release separately rechecks the
terminal record, obtains SynchronizationManager's guarded timing-evidence release,
applicable node reservation release, and Ingestor release. Uncertainty retains the
Controller binding and obligations. `reconcile_session_closeout()` reads a known
saved scope after restart without restoring application state or a live clock.
Saved readback requires the existing configured journal root and durable products;
interrupted products still require existing authorized recovery. Local development
interfaces remain available and do not require a NATS round trip inside the shared
Ingestor/StorageManager process. Stage B, permanent closure and general service
maintenance remain separate. W060 closes this bounded implementation after
independent user-run validation and independent audits. Its separate validation
sets are 9/9 finalized intake, 7/7 simulated distributed closeout, 4/4 real
JetStream infrastructure, 3/3 separate-process closeout, 8/8 original-correction
and 6/6 subscription-release regressions; overlapping counts are not additive.
Earlier sandbox-blocked execution is not a claimed pass. Final controlled
nats-py 2.16.0 cancellation probes found no reproducible defect, but Windows
asyncio socket-pair startup prevented live task-level cancellation verification.
No multi-host, physical hardware/SFTP or power-loss validation is claimed.

Remote preservation readback includes the exact validated archive runtime
evidence. Controller checks its currently retained evidence against that readback
before release, across asynchronous participant/subscription steps, and against
fresh owner readback immediately before retirement. Missing coverage or cancelled
confirmation retains the binding and evidence. Newly retained post-finality
rejection evidence is not silently discarded, reclassified as framework evidence,
or appended to immutable Stage A by this correction; it blocks release unless
applicable preservation obligations can be authoritatively established.
Successful unsubscribe progress is removed immediately from pending release work;
failed or unconfirmed operations remain pending. Failed final readback retains
the Controller binding without restoring completed unsubscribe obligations, so
explicit retry obtains fresh preservation confirmation without duplicate removal.

### Partial-Handoff Refresh And Authorized Recovery Inputs

**StorageManager -> Ingestor:** `refresh_partial_artifact_collection_handoff()`
directly reads journal-backed compilations, handoff contents, administrator
authorization, and actual scientific-recovery evidence. Archive/transfer recovery
also reads trusted compilation/manifests through maintenance's Ingestor object.
Reuse existing compilers/acceptance verification and the already routed
obligation-scoped recovery commands. Missing NATS readback must establish exact
scope and trustworthy inputs before StorageManager acts under its own preservation
and collection guards. Preserve prior evidence/audit prefixes, authorization and
execution correlation, refusal of ambiguous inputs, no automatic refetch, and
handoff immutability once any collection attempt begins. Depends on evidence
confirmation and maintenance authorization interfaces, not an unrestricted
replacement-handoff operation.

### Saved-Session Collection And Permanent Closure

**Controller -> StorageManager:** Existing local single/multi-Session collection calls
`get_saved_session_collection_status()` and `collect_saved_artifacts()`; listing,
handoff readback, and `close_session_evidence_archive()` are local StorageManager
APIs; W058 adds bounded remote single-Session collection as described below.
Remote enumeration/batch remain unimplemented; explicit closure is exposed by
the Slice 5 implementation below. StorageManager independently enumerates/validates saved
products, rechecks eligibility/availability under collection guards, and retains
stable per-Session evidence IDs and durable outcomes before direct Stage B archival.
Do not send Stage B evidence through Ingestor merely to archive it. Preserve
failure isolation, per-Session results, aggregate reporting, authorized interrupted
write recovery without refetch, and separate explicit permanent closure with
restart-safe immutability. Existing SSH/SFTP file retrieval remains a
StorageManager persistence mechanism under Decision 373, not a Python call to an
AcquisitionNode service owner. Depends on preserved baselines/handoffs, but not
restoration of old Session runtime bindings.

**Current bounded Slice 4 implementation (CLOSED, W058; independent validation
and final audit PASS of d788d2e):** Controller can explicitly request one saved Session's
collection with `await collect_saved_session_artifacts_remote(session_id,
evidence_id=..., communication=..., storage_participant=..., result_window_s=...)`
without local Ingestor or StorageManager references. The existing
`request_persistence_command` supports StorageManager operations
`get_saved_session_collection_status` (nonce only) and `collect_saved_artifacts`
(stable `evidence_id` plus nonce). Collection command identity is the compact JSON
encoding of `[session_id, evidence_id]`, checked by the owner; the Controller
builds it automatically. The receiving service does not cache a successful
collection flag: StorageManager revalidates eligibility, preservation, closure
and handoff under existing collection guards, and exact durable collection
evidence supports retries after lost replies and restart without refetching.

The rejected-command replay correction admits only fresh StorageManager commands
at subscription startup, rather than replaying retained command history. Commands
published while this owner is offline remain unconfirmed and require an explicit
retry. Other participant adapters retain their existing delivery policy.
For collection, the existing `request_nonce` distinguishes each explicit attempt
from delivery of an older attempt with the same Session/evidence command identity.
The adapter serializes collection attempt resolution through result publication,
reuses exact matching results from durable `LAB_COMMAND_RESULTS`, and retains an
unpublished result in memory until publication succeeds. Thus a rejected attempt
does not become executable when eligibility changes. An explicit API retry has
a fresh nonce, revalidates current owner guards, and can reuse the already durable
collection outcome. No operator API, new persistence store or recovery workflow
is introduced.

Result-history readback requires intact file-backed retained history and rejects
unavailable, malformed or detectably incomplete history before collection; the
scan rechecks stream continuity before admitting work. This conservative check
and linear result-history scan are operational limitations, not new power-loss or
broker-history restoration guarantees. Existing storage locks are never held
across NATS readback. All three replay/correlation P2 findings are resolved and
independently verified; W058 preserves the failed audits and corrective history.

Persisted collection-result correlation is validated before an attempt can be
treated as unrelated or absent: required result fields/types, nonempty identities
and nonce, final status/success consistency, subject/body Session/source/operation,
and canonical Session/evidence command identity. Payload Session/status and any
collection evidence must agree with those identities; success requires confirmed
collection preservation. Every record in the scoped scan is checked, even after
finding a matching attempt, and conflicting resolutions fail closed. Within the
Session/owner/operation scope, the nonce identifies the attempt: differing command
or destination identities for that nonce block admission rather than making the
attempt appear absent. Valid
unrelated attempts remain isolated; other Sessions remain outside the scoped
readback. Invalid history blocks collection without rewriting the offending
records or producing new collection evidence. A normal failed command reply may
still be appended to the existing NATS result stream; it is not history repair.

Results retain eligibility/availability information and actual collection outcomes,
including scientific retrieval failures whose evidence was durably preserved.
Controller reports success only for the matching Session/evidence identity with
confirmed collection-evidence archival and successful scientific collection.
Missing or stale replies remain unconfirmed. Publication, intake acceptance,
W041 receipt, Stage A preservation and release authorization are not substituted
for this collection result. No automatic collection or permanent closure occurs.
Stage B evidence remains directly archived by StorageManager, not sent via NATS
to Ingestor. Existing local APIs remain usable for in-process workflows.

Developer coverage includes real local JetStream with Controller and the combined
Ingestor/StorageManager test process separated, simulated SFTP, overlapping
requests and owner restart. This is not live SSH, hardware, multi-host or power-loss
validation. This subset does not adapt active Session Stop/Kill, Stage A/handoff
creation, completion/release, remote saved-Session enumeration/batch selection,
permanent closure or maintenance/recovery orchestration.

### Explicit Remote Saved-Session Archive Closure (Closed, W059)

The bounded implementation exposes the existing permanent Evidence Archive
closure operation, not general Session lifecycle closeout. Call
`await controller.close_saved_session_archive_remote(session_id,
communication=..., storage_participant=..., result_window_s=...)` only as a
separate explicit operator request. No local Controller Ingestor/StorageManager
reference is needed. This bounded Slice 5 is CLOSED in W059 after independent
IPython validation and final focused audit PASS of 31b2c7e, with no confirmed
P0-P3 findings after the cached-success history-validation P2 correction.

`close_session_evidence_archive` uses existing NATS command/results, canonical
compact JSON `[session_id, "close_session_evidence_archive"]` command identity
and fresh per-attempt nonce. This operation creates no new evidence ID or closure
file: StorageManager records closure only in `compilation_summary.json`, through
its existing locked, durable write/readback method. Its existing Stage A/B,
handoff, audit, final-record and unresolved-write checks remain authoritative.
Failed or unknown artifact outcomes do not block closure when durably recorded;
collection success is neither required nor a substitute for archive consistency.
Collection eligibility is not a new lifecycle gate for permanent closure.

The shared saved-Session command admission path retains fresh-only subscriptions,
full operation-scoped history validation, same-nonce identity conflict rejection
and serialization through result publication. Historical rejections cannot become
new executions; explicit API retries use fresh nonces. Successful closure responses
retained after failed/cancelled publication pass the same complete history scan
before reuse; disagreement with a persisted resolution is unconfirmed, not ignored.
Retained rejections remain rejected. Repeated successful closure
requires current owner readback matching the retained/historical closed summary,
then invokes the existing idempotent closure confirmation without rewriting closed
products. Missing or corrupt current preservation invalidates success, including
after cancelled/failed reply publication. Pending replies remain in memory, not a
new durable command store. Missing replies leave the Controller outcome unconfirmed.

Success includes `closure_outcome` from StorageManager and its verified current
`compilation_summary`; Controller checks Session identity, `archive_closed=True`
and `archival_confirmed=True`. It does not complete an active Session, collect
artifacts, release bindings/hardware, or authorize recovery. Local closure
preconditions are unchanged. Full Normal Stop/Kill, Stage A/handoff orchestration,
enumeration/batch closeout, broader maintenance/recovery and role bootstrap remain
outside this boundary. Retained history must be intact and scanning is linear;
simulated SFTP/local JetStream testing does not establish hardware, multi-host or
power-loss guarantees. W059 records the original 67 developer tests and 4/4
independent IPython checks, initial audit FAIL, correction IPython 3/3 PASS and
final audit PASS. Corrective runtime attempts, including six audit tests, stalled
inside the sandbox without results; no automated correction passes are claimed.
Counts are not additive. Q022 remains OPEN; W001-W058 history is unchanged.

### Framework Maintenance, Recovery, And Reconciliation

**LLC clarification under Decisions 311, 316, 319 and 324:** Before orderly
retirement each service closes new-work admission, resolves its obligations and
establishes a complete stable boundary for its required evidence. Authoritative
Ingestor acceptance and StorageManager preservation must cover that boundary.
The boundary is service-specific: unrelated producers may continue, and their
later evidence does not invalidate this confirmation. Local admission and
retirement guards still apply; a transport ACK is not preservation. This requires
no global archive freeze, new lifecycle state or separate reliability subsystem.

**Each service's maintenance interface -> Ingestor/StorageManager:**
W063 now implements the producer-specific startup/Stop preservation path through
`preserve_service_evidence`, retaining local owner locks and remote source-boundary
verification. The earlier direct-call dependency assessment below still applies
to broader maintenance/recovery operations not adapted by this slice.
`_preserve_message()`, `_require_recovery_authorization()`, retirement guards,
and owner diagnostics directly await journal acceptance, inspect archive safety,
compile/write/read archives, and share intake/persistence locks. Controller
`reconcile_outcomes()` and SynchronizationManager `reconcile_timing()` also use
direct acceptance/archival readback. Reuse fresh readiness subscriptions, startup
reconciliation, bounded correlated maintenance/recovery commands, retained
producer evidence, and existing owner-local recovery/preservation methods.
Missing NATS requests must distinguish publication, durable acceptance, current
archival, actual execution, and remaining obligations. Decision 347 requires
authorization and attempt acceptance before repair, without circular dependence
on successful repair of the unavailable archive. Unsafe archives cannot be
silently repaired by startup. Owner admission/retirement checks must remain
effective across asynchronous callbacks; prepared retirement requires complete
evidence and audit coverage without a new post-Ingestor dependency. Cross-service
dependent callbacks and Controller shutdown's direct owner-identity checks also
need owner-reported confirmations, not assumed shared objects. Depends on the
evidence/persistence interfaces before independent-role startup is fully enabled.

## Recommended Implementation Order

Completed prerequisites are identified by their validated workflows below.
Remaining items are proposed implementation boundaries, not additional accepted
architecture or claims of implementation/validation:

1. The bounded routine observation/metadata routing and node lifecycle/health
   preservation prerequisite is complete with correction, independent validation
   and final re-audit PASS (W053). Owner-level envelope removal and closeout
   reconciliation are complete after correction, independent validation and
   corrective re-audit PASS (W054), retaining required historical interpretation.
   The combined Decision 377-378 replacement is now accepted in W055 after
   functional audit PASS and targeted correction of its sole clean-replacement
   P3; no further independent re-audit was required by the user and ICC for that
   test-only cleanup. AcquisitionNode-to-Ingestor durable operational evidence
   intake and exact journal-backed acceptance readback are complete in W057 after
   independent validation and audit PASS. Existing receipt/compilation interfaces
   are preserved; broader Controller/recovery/deployment adaptation remains open.
2. Acquisition/Experiment and distributed synchronization runtime integration is
   complete in W056 after corrections, independent manual validation and final
   audit PASS. It reuses existing node commands with local scientific timing,
   context/finalization and publication-before-completion. This does not close
   broader deployment obligations; operational-evidence transport is separately
   closed in W057.
3. Bounded remote single saved-Session collection is CLOSED in W058 after
   independent validation and final audit PASS. Explicit remote permanent closure
   of one saved Evidence Archive is CLOSED in W059 after correction, independent
   validation and focused audit PASS. Q019 Controller Normal Stop/Kill,
   Stage A/handoff and completion/release are CLOSED in W060 after independent
   validation and audits confirmed the original three P2 corrections and the
   subsequent subscription-retry correction (see the Stage A section above).
   Saved-Session enumeration/batch collection and batch closeout remain outside
   that implementation. W060 does not close broader deployment obligations.
4. Adapt framework startup evidence, reconciliation, maintenance and authorized
   recovery, including partial-handoff refresh and prepared retirement. Test
   durable authorization/attempt before action, missing results, failed cleanup,
   corrupted archives, pre-collection refresh, and no post-retirement self-write.
5. Enable configuration/explicit-role bootstrap only after its required remote
   interfaces exist; wire local known identities, adapters, validated paths and
   retrieval settings, then installation checks. Configuration parsing/templates
   can be prepared independently, but may not implicitly instantiate other owners.
   Validate role isolation, invalid files, offline nodes, fresh readiness,
   Controller restart reconciliation, and verified installation dummy retrieval.

The former ownership/transport question is resolved. The principal implementation
risk is preserving current cross-owner coverage and admission guarantees across
network suspension: local locks must remain local, and cached confirmations must
not replace final owner verification. Any essential guarantee that cannot be
satisfied within existing contracts must return through ICC for clarification;
this assessment does not select a distributed transaction or new recovery system.

## Validation Boundaries

Future implementation needs focused software tests of configuration loading,
role selection, explicit identities/adapter construction, parameter constraints and
successive Session isolation, startup/readiness communication, and installation
dummy retrieval. Test invalid configuration, ambiguous known identities, offline
nodes, mismatched dummy contents, and failure diagnostics without manufacturing
scientific readiness or evidence acceptance.

Independent manual validation and source audit follow implementation under the
authoritative workflow. Real deployment/device validation remains separately
identified. Q019 is CLOSED; Q022, Q024, Phase 16, and M015 remain OPEN. Historical
validated workflows and existing service ownership/safety contracts are unchanged.
