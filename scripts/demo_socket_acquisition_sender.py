"""Send demo acquisition envelopes to a localhost receiver."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import AcquisitionRecordEnvelope


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send newline-delimited acquisition envelopes over localhost."
    )
    parser.add_argument("host", help="Receiver host, for example 127.0.0.1.")
    parser.add_argument("port", type=int, help="Receiver TCP port.")
    args = parser.parse_args()

    envelopes = [
        AcquisitionRecordEnvelope(
            session_id="demo-session-001",
            source_device_id="acquisition_node",
            record_kind="event",
            records=[
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_start",
                    "session_time_s": 0.0,
                }
            ],
        ),
        AcquisitionRecordEnvelope(
            session_id="demo-session-001",
            source_device_id="fake_camera_001",
            record_kind="camera_stream",
            records=[
                {
                    "frame_index": 0,
                    "pixel_mean": 12.5,
                    "session_time_s": 0.1,
                },
                {
                    "frame_index": 1,
                    "pixel_mean": 12.8,
                    "session_time_s": 0.2,
                },
            ],
        ),
        AcquisitionRecordEnvelope(
            session_id="demo-session-001",
            source_device_id="fake_lick_sensor_001",
            record_kind="lick_event",
            records=[
                {
                    "event_category": "behavior",
                    "event_type": "lick",
                    "session_time_s": 0.25,
                }
            ],
        ),
        AcquisitionRecordEnvelope(
            session_id="demo-session-001",
            source_device_id="acquisition_node",
            record_kind="event",
            records=[
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_stop",
                    "session_time_s": 0.3,
                }
            ],
        ),
    ]

    with socket.create_connection((args.host, args.port), timeout=5) as client_socket:
        writer = client_socket.makefile("w", encoding="utf-8", newline="\n")
        for envelope in envelopes:
            writer.write(json.dumps(envelope.to_dict()))
            writer.write("\n")
        writer.flush()

    print(f"envelopes_sent={len(envelopes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
