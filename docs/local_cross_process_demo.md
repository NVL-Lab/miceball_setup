# Local Cross-Process Demo

This document describes the first live two-shell demo for the framework.

The previous JSONL file-handoff demo proved that `AcquisitionRecordEnvelope` objects can become plain data, be persisted, and be reconstructed by another process. That was useful, but it did not prove live process-to-process communication.

The localhost socket demo proves the next boundary:

```text
acquisition-side shell process
    sends newline-delimited JSON envelope dictionaries

localhost TCP socket
    carries plain data only

ingestion/storage-side shell process
    reconstructs AcquisitionRecordEnvelope objects
    sends them to InMemoryIngestor
    persists accepted envelopes through PersistentStorageManager
```

No live `DeviceAdapter`, `DeviceManager`, `AcquisitionNode`, or `Session` object crosses the process boundary.

This socket implementation is disposable demonstration code. It is not the final transport architecture.

---

# What This Proves

The demo proves that:

* acquisition-side code can send plain-data `AcquisitionRecordEnvelope` dictionaries over a live localhost socket
* a separate ingestion/storage process can receive newline-delimited JSON messages
* the receiving process can reconstruct `AcquisitionRecordEnvelope` objects through the public plain-data API
* `InMemoryIngestor` can receive the reconstructed envelopes and create ingest audit evidence
* `PersistentStorageManager` can write accepted envelopes to persistent JSONL storage
* every row can preserve `session_time_s` across a live process boundary

The demo sends:

* one `session_start` event envelope
* one fake camera stream envelope
* one fake lick event envelope
* one `session_stop` event envelope

---

# What This Does Not Prove

The demo does not define or validate:

* final transport architecture
* network protocol
* command protocol
* retry policy
* daemon behavior
* multi-client behavior
* concurrent acquisition loops
* Controller implementation
* Session lifecycle integration
* Jetson deployment
* real device behavior
* final folder layout
* manifest format
* Parquet storage
* NWB export
* reconstruction

The localhost socket is intentionally simple. It validates live transfer of plain-data envelopes before real transport is designed.

---

# Windows PowerShell Demo

Run these setup commands from the repository root:

```powershell
$python = "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe"
$demoDir = ".\tmp_socket_demo"
New-Item -ItemType Directory -Force $demoDir
$accepted = Join-Path $demoDir "accepted_records.jsonl"
$hostName = "127.0.0.1"
$port = 8765
```

Shell 1, ingestion/storage-side receiver:

```powershell
& $python .\scripts\demo_socket_ingestor_receiver.py $hostName $port $accepted
```

Expected initial output:

```text
listening=127.0.0.1:8765
accepted_records_path=tmp_socket_demo\accepted_records.jsonl
```

Leave Shell 1 running.

Shell 2, acquisition-side sender:

```powershell
& $python .\scripts\demo_socket_acquisition_sender.py $hostName $port
```

Expected sender output:

```text
envelopes_sent=4
```

After the sender closes the connection, Shell 1 should finish with:

```text
envelopes_received=4
accepted_envelopes_stored=4
ingest_audit_records=4
```

The exact displayed paths may differ depending on how PowerShell resolves them.

---

# Inspect The Output

The demo produces:

```text
tmp_socket_demo/
    accepted_records.jsonl
```

Inspect the stored accepted envelope JSONL:

```powershell
Get-Content $accepted
```

You should see four JSON lines:

* `session_start`
* fake camera stream records
* fake lick event record
* `session_stop`

Every row includes `session_time_s`.

---

# Roadmap Fit

This demo is a stepping stone toward Jetson and real-device deployment.

Future deployment may replace the localhost socket with a real transport. That future transport must still preserve the same architectural boundary:

```text
Acquisition side
    creates plain-data acquisition envelopes

Process or machine boundary
    moves plain data

Ingestor side
    reconstructs envelopes
    audits ingest
    forwards accepted envelopes to StorageManager
```

Transport choices should not redefine the acquisition record model.
