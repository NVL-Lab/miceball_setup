# Destructive Disposable Deployment Test Reset

## Scope and mandatory precautions

**This permanently deletes scientific and operational history. It is only for an
explicitly authorized disposable test deployment.** It is not production recovery,
formal service retirement, an implemented factory reset, or a solution to historical
processing problems. It is not an exhaustive inventory of persistent state.

Before future reuse (additional precautions, not claims about the historical run):

- Obtain explicit authorization for the exact computers, account and data removed.
  Back up and verify any scientific data, evidence, catalogs or other records that
  must survive. If preservation obligations remain, do not substitute this reset
  for their accepted completion or recovery workflow.
- Verify actual configuration paths, scientific destinations, journal/archive
  locations, GUI catalog and NATS account/store directory. Inspect other configured
  destinations and hidden files; the paths below are installation-specific.
- Verify mounts and resolved paths before deletion. Stop if a mount is absent,
  a path resolves elsewhere, or unrelated data shares the scope. Never delete an
  entire JetStream account containing unrelated streams, consumers or KV stores.
- Confirm all affected processes and NATS are stopped. Preserve installation,
  credentials, JSON configuration/backups, hardware/network settings, directories,
  ownership and permissions. Inspect what remains before restarting.
- Account deletion also removes Controller authority infrastructure. Reinitialize
  required resources before service startup; provisioning does not acquire authority.

Existing preservation/recovery contracts remain authoritative: Decisions 276-280,
349/354, 390/393, 436 and 443. Decisions 445 and 453 preserve authentication and
installer boundaries. None authorizes a general reset mechanism. See unresolved
[Q035](open_questions.md#q035-framework-factory-reset-and-clean-deployment-reinitialization).

## November 24, 2026 deployment evidence

The following observations and actions were reported by Deployment from the
distributed Ubuntu/Jetson installation; they were not rerun for this documentation.

Before reset: repeated NATS slow-consumer disconnects, `ConnectionResetError`,
`DurablePublicationError`, mostly unconfirmed readiness, and repeated
SynchronizationManager registration command reception occurred without an active
Session. Incoming NATS traffic to the paired Ingestor/StorageManager process was
approximately **63 MB/min**. Broker history contained approximately **285,006**
command/result/evidence messages and **1.15 GB** of persistent storage; the Ingestor
framework journal was approximately **333 MB**, its checkpoint **16 MB**.

An active framework evidence consumer with delivery policy `all` reported:

| Measurement | Value |
| --- | ---: |
| Deliveries | 46,260 |
| Consumer acknowledgment floor | 388 |
| Pending messages | 14,647 |
| Acknowledgment-pending messages | 1,000 |
| Redelivered messages | 988 |

Historical Session consumers had **57,289** combined pending messages. A separate
measurement recorded only approximately **20 KB/min** of new persistent stream
growth. These observations suggest excessive historical delivery or processing;
they do not establish the precise implementation cause.

After the authorized clean reset, Ingestor/StorageManager started substantially
faster, all five services reached Ready, and no slow-consumer errors were observed
during clean startup. A healthy 60-second idle window recorded approximately
**389 KB** broker-to-framework traffic and **382 messages**, with no lost connections.
A separate healthy idle measurement recorded:

| Stream | New messages/min | Additional bytes/min |
| --- | ---: | ---: |
| LAB_COMMANDS | 24 | 9,492 |
| LAB_COMMAND_RESULTS | 24 | 37,674 |
| LAB_EVIDENCE | 0 | 0 |
| Total | 48 | 47,166 |

Persistent command/result accumulation therefore continues without an active
Session or experimenter interaction. LLC is discussing both persistent operational
history accumulation and excessive historical delivery/processing/recovery.
Neither is resolved; implementation corrections await LLC instructions. The reset
was a temporary diagnostic workaround, not proof of long-duration stability.

## Historical reset and prerequisites for reuse

### A. Stop processes

Deployment used Ctrl+C in this order: GUI (Ubuntu), Controller (Ubuntu),
AcquisitionNode (Jetson), SynchronizationManager (Ubuntu), then paired
Ingestor/StorageManager (Ubuntu). It then ran on Ubuntu:

```bash
sudo systemctl stop nats-server
pgrep -af 'lab_sync_acquisition|miceball-gui'
systemctl is-active nats-server
```

On Jetson:

```bash
pgrep -af lab_sync_acquisition
```

No matching framework processes remained; NATS reported inactive. This destructive
test reset did not validate formal service retirement. Future reuse must also check
for differently named processes and all other clients writing the affected state.

### B. Verify actual paths and mounts

Ubuntu paths inspected: `/mnt/miceball-data`,
`~/.config/lab-sync-acquisition/data`,
`~/.config/lab-sync-acquisition/gui-catalog.sqlite3`, and
`/var/lib/nats/jetstream/jetstream/LAB`.
Jetson paths inspected: `/mnt/ball-ssd/miceball-data` and
`/mnt/ball-ssd/miceball-errors`.

```bash
findmnt /mnt/ball-ssd
```

The Jetson mount was ext4 on `/dev/nvme0n1p1`. This historical result is not a
substitute for verifying the current mount and configured locations before reuse.

### C. Clear Jetson history

Historical commands (destructive; use only after the precautions above):

```bash
rm -rf /mnt/ball-ssd/miceball-data/*
rm -rf /mnt/ball-ssd/miceball-errors/*
```

Both directories were subsequently verified empty. Directories, ownership,
permissions, mount configuration, `lost+found` and the unidentified `old` directory
were preserved. Wildcards do not include hidden files; inspect for additional state
and do not delete unidentified directories by inference.

### D. Clear Ubuntu history

Historically, Deployment changed into each root then removed `artifacts/*`,
`journals/*`, `records/*`, `framework.jsonl` and `framework.jsonl.checkpoint.json`.
For reuse, the equivalent commands below use **guarded directory changes** so a
failed `cd` cannot delete relative paths in an unintended directory:

```bash
(cd /mnt/miceball-data && rm -rf artifacts/* journals/* records/* && rm -f framework.jsonl framework.jsonl.checkpoint.json)
(cd "$HOME/.config/lab-sync-acquisition/data" && rm -rf artifacts/* journals/* records/* && rm -f framework.jsonl framework.jsonl.checkpoint.json)
```

Both locations were inspected afterwards. Directory structure, ownership,
permissions and filesystem `lost+found` were preserved. The original wildcards did
not include hidden files. Inspection for other historical state remains necessary.

### E. Clear GUI catalog

Historical command:

```bash
rm -f ~/.config/lab-sync-acquisition/gui-catalog.sqlite3*
```

The catalog was removed; configuration JSON files and backups were preserved.
This can permanently remove experimenter-facing history and saved configuration
records. For future reuse, inspect every file matched by this prefix before
authorizing deletion, including SQLite sidecars. Normal updates must preserve the
catalog; this was an explicitly destructive exception.

### F. Clear NATS account history

With NATS stopped and the account verified as disposable, the successful command was:

```bash
sudo rm -rf /var/lib/nats/jetstream/jetstream/LAB
sudo ls -lah /var/lib/nats/jetstream/jetstream
```

The parent was subsequently empty; approximately 1.1 GB was removed. An earlier
wildcard attempt failed because the invoking shell could not expand the protected
directory. Do not use that failed approach. The successful command removes **all
JetStream state for LAB**, not only framework evidence. Never use it on a shared
account with unrelated data. NATS installation, authentication configuration and
persistent parent-directory permissions were preserved.

### G. Restart NATS

Historical commands:

```bash
sudo systemctl start nats-server
systemctl is-active nats-server
sudo journalctl -u nats-server -n 25 --no-pager
```

NATS 2.10.7 started with existing configuration and no historical stream restoration.
A preexisting systemd changed-unit warning remained; no daemon reload or
configuration correction was performed.

### H. Recreate Controller authority infrastructure

Existing Controller configuration identified account `LAB`, bucket
`CONTROLLER_AUTHORITY`, and shared claim key `miceball-controller`. Deployment used
its Python environment, `nats-py`, and credentials from `controller.json` to create:

```python
await js.create_key_value(KeyValueConfig(
    bucket=cfg["controller_claim_bucket"],
    storage=StorageType.FILE,
    history=1,
    replicas=1
))
```

The bucket was verified file-backed, non-expiring, without global message/byte
eviction limits, with zero messages and consumers. The original history depth was
not recovered; history 1 and one replica were selected for this single-broker test.
No claim was acquired.

**Reconstructed provisioning procedure, not the recovered historical command:**
after explicit authorization and confirmed account deletion, run the following
from the checkout using its existing environment. It reuses the authoritative
Controller configuration loader and Decision 445 authentication helper. It must
not be used to replace, clear or repair an existing bucket. No credentials are
printed or supplied on the command line. Connection/provisioning errors report
only their class, not SDK exception text or tracebacks.

```bash
.venv/bin/python - <<'PY'
import asyncio
import json
from pathlib import Path
from nats.aio.client import Client
from nats.js.api import KeyValueConfig, StorageType
from nats.js.errors import BucketNotFoundError
from lab_sync_acquisition.deployment_configuration import load_service_configuration
from lab_sync_acquisition.nats_configuration import AUTH_FIELDS, nats_connect_options, report_nats_error
from lab_sync_acquisition.controller_authority import open_controller_claim_store

async def provision():
    nc = Client()
    try:
        cfg = load_service_configuration(
            Path.home() / '.config/lab-sync-acquisition/controller.json', 'controller')
        options = nats_connect_options(cfg['servers'], **{
            k: cfg[k] for k in AUTH_FIELDS if k in cfg})
        await nc.connect(**options, allow_reconnect=False, error_cb=report_nats_error)
        reply = await nc.request('$SYS.REQ.USER.INFO', b'', timeout=10)
        identity = json.loads(reply.data)
        if identity.get('error') or identity.get('data', {}).get('account') != cfg['controller_claim_account']:
            raise RuntimeError('Account unverified')
        js = nc.jetstream()
        try:
            await js.key_value(cfg['controller_claim_bucket'])
        except BucketNotFoundError:
            pass
        else:
            raise RuntimeError('Existing bucket must not be replaced')
        kv = await js.create_key_value(KeyValueConfig(
            bucket=cfg['controller_claim_bucket'], storage=StorageType.FILE,
            history=1, replicas=1))
        # Use the runtime authority-store checks without acquiring a claim.
        class ConnectionView:
            connected = nc.is_connected
            _client = nc
            _jetstream = js
        await open_controller_claim_store(ConnectionView(),
            account=cfg['controller_claim_account'], bucket=cfg['controller_claim_bucket'],
            key=cfg['controller_claim_key'], timeout_s=10)
        info = (await kv.status()).stream_info
        if info.state.messages != 0 or info.state.consumer_count != 0:
            raise RuntimeError('New bucket is not empty')
        print('Empty Controller authority bucket verified; no claim acquired')
    except Exception as error:
        print('Provisioning unconfirmed (' + type(error).__name__ + '); inspect before any retry')
        return False
    finally:
        try:
            await nc.close()
        except Exception:
            print('Connection cleanup unconfirmed')
            return False
    return True

raise SystemExit(0 if asyncio.run(provision()) else 1)
PY
```

This reconstruction was source-checked, not executed. The existing runtime check
requires the actual authenticated account, file storage, limits retention, no
expiration/global eviction, no mirror/sources/subject transform, acknowledgments
enabled and an unsealed stream. A failed or interrupted creation may leave a
bucket: inspect it rather than automatically repeating or deleting it. Broker
permissions/account-info access are external prerequisites. Provisioning grants no
Controller ownership; normal startup must still acquire the exclusive claim.

### I. Restart framework services

Historical order: paired Ingestor/StorageManager (Ubuntu), SynchronizationManager
(Ubuntu), AcquisitionNode (Jetson), Controller (Ubuntu), GUI (Ubuntu). Use the
[service startup runbook](installation_and_deployment.md#windows-cmd-deployment-quick-runbook)
with platform-appropriate shell syntax and the
[validated Ubuntu GUI command](installation_and_deployment.md#validated-ubuntu-gui-launch),
plus the existing AcquisitionNode deployment instructions. All five services
eventually reported Ready with current communication confirmed. This does not
prove recovery of the intentionally deleted evidence.

## Remaining status

Clean startup and short healthy idle operation were physically demonstrated;
long-duration stability was not. Pending connected GUI correction validation may
resume on the healthy deployment. Connected Device Validation under Q030 remains
deferred; StorageManager corrections are paused; graphical installer implementation
is deferred. G2 and Phase 16 remain CLOSED. No broader deployment, recovery or
installation question is closed. A future reset design must account for evolving
components rather than hard-code this historical list of paths.
