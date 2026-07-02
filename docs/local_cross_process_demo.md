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

# Stronger Camera Adapter Socket Demo

The basic socket demo sends hard-coded envelope dictionaries. The stronger camera adapter demo proves that the live socket boundary can be fed by the real framework acquisition path:

```text
FakeCV2/OpenCVCameraAdapter
    -> DeviceManager
    -> AcquisitionNode
    -> newline-delimited JSON socket
    -> socket receiver
    -> InMemoryIngestor
    -> PersistentStorageManager
```

This still does not require a physical camera, Jetson, CSI hardware, GStreamer, or real OpenCV. The sender uses fake injected OpenCV input by default so the local development test can run anywhere.

The live socket carries only lightweight evidence:

* `session_start`
* camera frame metadata records
* `session_stop`

It does not carry image arrays, encoded image bytes, image files, video files, or file references.

## Windows PowerShell Camera Adapter Demo

Run these setup commands from the repository root:

```powershell
$python = "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe"
$demoDir = ".\tmp_socket_camera_demo"
New-Item -ItemType Directory -Force $demoDir
$accepted = Join-Path $demoDir "accepted_records.jsonl"
$hostName = "127.0.0.1"
$port = 8766
```

Shell 1, ingestion/storage-side receiver:

```powershell
& $python .\scripts\demo_socket_ingestor_receiver.py $hostName $port $accepted
```

Expected initial output:

```text
listening=127.0.0.1:8766
accepted_records_path=tmp_socket_camera_demo\accepted_records.jsonl
```

Leave Shell 1 running.

Shell 2, acquisition-side OpenCV camera sender:

```powershell
& $python .\scripts\demo_socket_opencv_camera_sender.py $hostName $port
```

Expected sender output:

```text
target=127.0.0.1:8766
envelopes_sent=3
camera_metadata_records_sent=2
```

After the sender closes the connection, Shell 1 should finish with:

```text
envelopes_received=3
accepted_envelopes_stored=3
ingest_audit_records=3
```

Inspect the stored accepted envelope JSONL:

```powershell
Get-Content $accepted
```

You should see three JSON lines:

* `session_start`
* `camera_frame_metadata`
* `session_stop`

The camera metadata rows include `frame_index`, `width`, `height`, `channels`, `dtype`, and `session_time_s`.

## Optional Real Laptop Webcam Sender

The same sender can use an installed real OpenCV build and laptop webcam while
preserving the metadata-only socket boundary. Keep the receiver command above
running in Shell 1, then run this in Shell 2:

```powershell
& $python .\scripts\demo_socket_opencv_camera_sender.py $hostName $port --real-cv2 --camera-source 0 --frames-per-collect 2 --width 640 --height 480 --fps 30
```

OpenCV's default capture backend is used unless `--api-preference` is supplied.
The sender transmits `session_start`, lightweight camera frame metadata, and
`session_stop`; it never transmits image arrays or encoded image bytes.

## Recorded Manual Hardware Validation

The real laptop webcam path has been run successfully as a manual hardware
validation using installed `cv2` and the MSMF capture backend. That run produced
and stored three envelopes (`session_start`, camera metadata, and
`session_stop`), sent two camera metadata records, and sent no image payloads.

This result is separate from W013 in `validated_workflows.md`. W013 is the
automated, deterministic FakeCV2 socket workflow; the MSMF result is manual
hardware evidence and is not required by the normal test suite or CI.

---

# Optional Real Camera Smoke Check

After validating the fake OpenCV socket workflow, an optional manual script can
exercise the same camera adapter against a real `cv2.VideoCapture` source. It
runs one bounded `DeviceManager`/`AcquisitionNode` iteration, prints lightweight
frame metadata, and releases the camera. It does not write or transmit image or
video payloads and is not part of the automated test suite.

From the repository root, camera index `0` with OpenCV's default backend:

```powershell
& "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe" .\scripts\manual_opencv_camera_smoke.py 0
```

Optional capture settings are explicit:

```powershell
& "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe" .\scripts\manual_opencv_camera_smoke.py 0 --api-preference 200 --frames-per-collect 3 --width 640 --height 480 --fps 30
```

The numeric API preference is passed directly to OpenCV. For example, OpenCV
commonly exposes `CAP_V4L2` as `200`, but the value should be confirmed in the
installed OpenCV build and target platform.

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

---

# Phase 2 Simulated Remote AcquisitionNode

This Phase 2 demo runs one explicitly identified, Jetson-like AcquisitionNode
process and one computer Ingestor process. It reuses the existing newline-
delimited JSON socket only as a provisional network handoff.

The remote sender records `node_id`, `session_id`, and role in node readiness,
and populates `source_node_id` in every acquisition envelope. If connection or
sending fails, it writes one local JSONL failure-evidence record, attempts
cleanup, and exits nonzero. It does not retry, replay, or buffer records.

Computer shell:

```powershell
$python = "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe"
$hostName = "0.0.0.0"
$port = 8767
$accepted = ".\tmp_remote_demo\accepted_records.jsonl"
& $python .\scripts\demo_socket_ingestor_receiver.py $hostName $port $accepted
```

Jetson or simulated Jetson shell, replacing `COMPUTER_IP` with the computer's
reachable address:

```powershell
$python = "C:\Users\Nuria\anaconda3\envs\miceball_setup\python.exe"
$failureEvidence = ".\tmp_remote_demo\sender_failures.jsonl"
& $python .\scripts\demo_remote_acquisition_node_sender.py COMPUTER_IP 8767 --node-id jetson-like-001 --session-id remote-session-001 --role acquisition_node --failure-evidence-path $failureEvidence
```

For a same-computer validation, use `127.0.0.1` for both receiver binding and
sender target. A successful run sends three envelopes: `session_start`, one
fake stream envelope, and `session_stop`.

---

# Recorded Jetson-to-Computer Validation

The Phase 2 remote workflow has been manually validated across two physical
machines. A Windows computer ran the socket receiver, `InMemoryIngestor`, and
`PersistentStorageManager`; an NVIDIA Jetson Orin running JetPack 6 / Jetson
Linux R36 ran the AcquisitionNode sender. Both machines used repository clones
and passed their automated tests before the manual run.

The Jetson connected to the Windows receiver over Wi-Fi and transferred
plain-data `AcquisitionRecordEnvelope` dictionaries. The run transmitted,
received, and stored three envelopes, created three ingest audit records,
preserved `source_node_id`, `session_id`, `source_device_id`, and Session Time,
and completed sender cleanup. The computer persisted the accepted envelopes as
JSONL.

This records a successful two-machine validation only. It does not define a
deployment model or final transport architecture.
