"""Write demo acquisition envelopes to a local JSONL handoff file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import AcquisitionRecordEnvelope


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write plain-data acquisition envelopes to a JSONL handoff file."
    )
    parser.add_argument(
        "handoff_path",
        help="Output JSONL handoff path.",
    )
    args = parser.parse_args()

    handoff_path = Path(args.handoff_path)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

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

    with handoff_path.open("w", encoding="utf-8") as handoff_file:
        for envelope in envelopes:
            handoff_file.write(json.dumps(envelope.to_dict()))
            handoff_file.write("\n")

    print(f"wrote_handoff_envelopes={len(envelopes)}")
    print(f"handoff_path={handoff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
