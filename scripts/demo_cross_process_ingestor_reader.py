"""Read demo handoff envelopes and persist accepted records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionRecordEnvelope,
    InMemoryIngestor,
    PersistentStorageManager,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read JSONL handoff envelopes into ingestor and storage."
    )
    parser.add_argument(
        "handoff_path",
        help="Input JSONL handoff path written by the acquisition-side demo.",
    )
    parser.add_argument(
        "accepted_records_path",
        help="Output JSONL path for accepted acquisition records.",
    )
    args = parser.parse_args()

    handoff_path = Path(args.handoff_path)
    accepted_records_path = Path(args.accepted_records_path)

    storage = PersistentStorageManager(records_path=accepted_records_path)
    ingestor = InMemoryIngestor(storage_manager=storage)

    handoff_count = 0
    with handoff_path.open("r", encoding="utf-8") as handoff_file:
        for line in handoff_file:
            if not line.strip():
                continue
            handoff_count += 1
            envelope = AcquisitionRecordEnvelope.from_dict(json.loads(line))
            ingestor.receive_envelope(envelope)

    accepted_count = len(storage.read_envelopes())
    audit_count = len(ingestor.ingest_audit)

    print(f"handoff_envelopes_read={handoff_count}")
    print(f"accepted_envelopes_stored={accepted_count}")
    print(f"ingest_audit_records={audit_count}")
    print(f"accepted_records_path={accepted_records_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
