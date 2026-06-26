"""Receive demo acquisition envelopes over localhost and persist accepted records."""

from __future__ import annotations

import argparse
import json
import socket
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
        description="Receive newline-delimited acquisition envelopes over localhost."
    )
    parser.add_argument("host", help="Localhost interface to bind, for example 127.0.0.1.")
    parser.add_argument("port", type=int, help="TCP port to listen on.")
    parser.add_argument(
        "accepted_records_path",
        help="Output JSONL path for accepted acquisition records.",
    )
    args = parser.parse_args()

    storage = PersistentStorageManager(records_path=Path(args.accepted_records_path))
    ingestor = InMemoryIngestor(storage_manager=storage)
    received_count = 0

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((args.host, args.port))
        server_socket.listen(1)
        bound_host, bound_port = server_socket.getsockname()
        print(f"listening={bound_host}:{bound_port}", flush=True)
        print(f"accepted_records_path={storage.records_path}", flush=True)

        connection, _address = server_socket.accept()
        with connection:
            reader = connection.makefile("r", encoding="utf-8")
            for line in reader:
                if not line.strip():
                    continue
                envelope = AcquisitionRecordEnvelope.from_dict(json.loads(line))
                ingestor.receive_envelope(envelope)
                received_count += 1

    accepted_count = len(storage.read_envelopes())
    audit_count = len(ingestor.ingest_audit)
    print(f"envelopes_received={received_count}")
    print(f"accepted_envelopes_stored={accepted_count}")
    print(f"ingest_audit_records={audit_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
