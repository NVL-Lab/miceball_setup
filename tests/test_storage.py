import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    AcquisitionNode,
    AcquisitionRecordEnvelope,
    DeviceAdapterState,
    DeviceDeclaration,
    DeviceManager,
    InMemoryIngestor,
    PersistentStorageManager,
    RuntimeEvidenceMessage,
    Session,
    SessionConfig,
    SessionState,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter

import json


class SessionRecordFakeAdapter(ReadyFakeAdapter):
    """Test-only adapter that exposes one fake stream batch."""

    def __init__(self, *args, records):
        super().__init__(*args)
        self._records = tuple(records)
        self._collected = False

    def collect_records(self):
        if self.state is not DeviceAdapterState.RUNNING:
            raise RuntimeError("Session record fake requires a running adapter")
        if self._collected:
            return {
                "record_kind": "tiny_stream",
                "records": (),
            }
        self._collected = True
        return {
            "record_kind": "tiny_stream",
            "records": self._records,
        }


class PersistentStorageManagerTests(unittest.TestCase):
    def test_phase13_initial_session_record_writes_accepted_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            storage = PersistentStorageManager(root / "accepted_records.jsonl")

            path = storage.write_initial_session_record(
                "session-001",
                **self._minimal_session_record_evidence("session-001"),
            )
            record = storage.read_session_record(path)

            self.assertEqual(
                path,
                root / "session_session-001" / "session_record_initial.json",
            )
            self.assertTrue(path.exists())
            self.assertEqual(
                record["accepted_session_config"]["session_id"],
                "session-001",
            )
            self.assertIsNone(record["final_session_status"])

    def test_phase13_final_session_record_writes_accepted_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            storage = PersistentStorageManager(root / "accepted_records.jsonl")

            evidence = self._minimal_session_record_evidence("session-001")
            evidence["final_session_status"] = {"state": "completed"}
            path = storage.write_final_session_record("session-001", **evidence)
            record = storage.read_session_record(path)

            self.assertEqual(
                path,
                root / "session_session-001" / "session_record_final.json",
            )
            self.assertTrue(path.exists())
            self.assertEqual(record["final_session_status"], {"state": "completed"})

    def test_phase13_evidence_archive_writes_accepted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            storage = PersistentStorageManager(root / "accepted_records.jsonl")
            ingestor = InMemoryIngestor()
            nonpersistent = RuntimeEvidenceMessage(
                evidence_id="evidence-nonpersistent",
                session_id="session-001",
                evidence_type="health_interpretation",
                source_id="node-001",
                payload={"interpretation_label": "warning"},
            )
            persistent = RuntimeEvidenceMessage(
                evidence_id="evidence-persistent",
                session_id="session-001",
                evidence_type="runtime_note",
                source_id="node-001",
                payload={"note": "included by Ingestor flag, not type"},
                is_persistent=True,
            )
            first_audit = ingestor.receive_runtime_evidence(nonpersistent)
            second_audit = ingestor.receive_runtime_evidence(persistent)

            paths = storage.write_evidence_archive(
                "session-001",
                ingestor.compile_persistent_runtime_evidence(),
            )

            expected_directory = root / "session_session-001" / "evidence"
            self.assertEqual(
                paths,
                {
                    "runtime_evidence": expected_directory
                    / "runtime_evidence.jsonl",
                    "ingest_audit": expected_directory / "ingest_audit.jsonl",
                    "compilation_summary": expected_directory
                    / "compilation_summary.json",
                },
            )
            runtime_evidence_lines = self._read_jsonl(
                paths["runtime_evidence"]
            )
            ingest_audit_lines = self._read_jsonl(paths["ingest_audit"])
            compilation_summary = json.loads(
                paths["compilation_summary"].read_text(encoding="utf-8")
            )

            self.assertEqual(runtime_evidence_lines, [persistent.to_dict()])
            self.assertEqual(
                ingest_audit_lines,
                [first_audit.to_dict(), second_audit.to_dict()],
            )
            self.assertEqual(
                compilation_summary,
                {
                    "session_id": "session-001",
                    "runtime_evidence_count": 1,
                    "ingest_audit_count": 2,
                    "runtime_evidence_ids": ["evidence-persistent"],
                    "ingest_audit_evidence_ids": [
                        "evidence-nonpersistent",
                        "evidence-persistent",
                    ],
                },
            )

    def test_phase13_archive_does_not_inspect_evidence_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            storage = PersistentStorageManager(root / "accepted_records.jsonl")
            surprising_persistent = RuntimeEvidenceMessage(
                evidence_id="evidence-surprising",
                session_id="session-001",
                evidence_type="not_a_mandatory_category",
                source_id="node-001",
                payload={},
                is_persistent=True,
            )

            paths = storage.write_evidence_archive(
                "session-001",
                {
                    "runtime_evidence": (surprising_persistent,),
                    "ingest_audit": (),
                },
            )

            self.assertEqual(
                self._read_jsonl(paths["runtime_evidence"]),
                [surprising_persistent.to_dict()],
            )

    def test_persistent_storage_writes_and_reads_accepted_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            records_path = Path(temporary_directory) / "accepted_records.jsonl"
            storage = PersistentStorageManager(records_path=records_path)
            ingestor = InMemoryIngestor(storage_manager=storage)
            envelope = AcquisitionRecordEnvelope(
                session_id="session-001",
                source_device_id="adapter-camera-001",
                record_kind="tiny_stream",
                records=[
                    {
                        "device_time_s": 100.0,
                        "session_time_s": 0.5,
                        "value": 10,
                    }
                ],
            )

            readiness = storage.check_ready()
            audit = ingestor.receive_envelope(envelope)
            read_back = storage.read_envelopes()

            self.assertEqual(storage.records_path, records_path)
            self.assertEqual(readiness.component_id, "storage")
            self.assertEqual(readiness.component_type, "storage_manager")
            self.assertTrue(readiness.required)
            self.assertTrue(readiness.ready)
            self.assertTrue(audit.accepted)
            self.assertEqual(len(ingestor.ingest_audit), 1)
            self.assertEqual(ingestor.accepted_envelopes, (envelope,))
            self.assertEqual(len(read_back), 1)
            self.assertEqual(read_back[0].session_id, "session-001")
            self.assertEqual(read_back[0].source_device_id, "adapter-camera-001")
            self.assertEqual(read_back[0].record_kind, "tiny_stream")
            self.assertEqual(
                read_back[0].records,
                (
                    {
                        "device_time_s": 100.0,
                        "session_time_s": 0.5,
                        "value": 10,
                    },
                ),
            )
            self.assertEqual(storage.stored_envelopes, read_back)
            self.assertEqual(
                storage.get_envelopes_for_session("session-001"),
                read_back,
            )
            self.assertEqual(
                storage.get_envelopes_for_source("adapter-camera-001"),
                read_back,
            )

            lines = records_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertNotIn("ingest_order", lines[0])
            self.assertNotIn("ingest_received_at", lines[0])

    def test_completed_session_can_write_and_read_v1_session_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            records_path = root / "accepted_records.jsonl"
            session_record_path = root / "session_record.json"
            declaration = DeviceDeclaration(
                device_id="declared-camera-001",
                device_type="camera",
                enabled=True,
                required=True,
                declared_capabilities=["tiny_stream"],
            )
            configuration = SessionConfig(
                session_id="session-001",
                selected_devices=[declaration],
                storage_location="placeholder://session",
                protocol_plan={"name": "session-record-v1"},
                error_evidence_location="placeholder://errors",
                session_parameters={"operator": "test-user"},
                device_configurations={
                    "declared-camera-001": {"exposure_ms": 5}
                },
                synchronization_configuration={"clock": "phase1-monotonic"},
                acquisition_configuration={"iterations": 1},
                ingestion_configuration={"mode": "in-memory"},
                storage_configuration={"backend": "jsonl"},
                protocol_reference="protocol://session-record-v1",
            )
            session = Session(
                session_id="session-001",
                configuration=configuration,
            )
            payload_rows = (
                {"device_time_s": 100.0, "value": 10},
                {"device_time_s": 100.1, "value": 11},
            )
            adapter = SessionRecordFakeAdapter(
                "adapter-camera-001",
                "camera",
                ["tiny_stream"],
                True,
                records=payload_rows,
            )
            manager = DeviceManager(adapters=[adapter])
            synchronization = SynchronizationManager()
            storage = PersistentStorageManager(records_path=records_path)
            ingestor = InMemoryIngestor(storage_manager=storage)
            acquisition_node = AcquisitionNode(
                session_id=session.session_id,
                device_manager=manager,
                synchronization_manager=synchronization,
                ingestor=ingestor,
                error_evidence_location=str(temporary_directory),
            )

            manager.initialize_all(config={"mode": "session-record-v1"})
            acquisition_readiness = acquisition_node.check_ready()
            session.initialize(
                device_readiness_summary=acquisition_readiness[
                    "device_readiness"
                ],
                service_readiness=(
                    *acquisition_readiness["service_readiness"],
                    storage.check_ready(),
                ),
            )
            session.start()
            acquisition_node.start_acquisition()
            acquisition_node.run_one_iteration()
            acquisition_node.stop_acquisition()
            session.stop(reason="session record v1 complete")
            session.complete(reason="session record v1 complete")

            accepted_envelopes = storage.read_envelopes()
            storage.write_session_record(
                session_record_path,
                accepted_session_config=session.configuration,
                lifecycle_evidence=session.transition_history,
                readiness_evidence=session.readiness_checks,
                device_readiness_evidence=session.device_readiness_summary,
                service_readiness_evidence=session.service_readiness_checks,
                accepted_acquisition_envelopes=accepted_envelopes,
                ingest_audit_records=ingestor.ingest_audit,
                final_session_status=session.final_status,
                cleanup_evidence={
                    "cleanup_occurred": session.cleanup_occurred,
                    "cleanup_sequence": session.cleanup_sequence,
                },
            )
            session_record = storage.read_session_record(session_record_path)

            self.assertIs(session.current_state, SessionState.COMPLETED)
            self.assertTrue(session_record_path.exists())
            self.assertEqual(
                session_record["accepted_session_config"]["session_id"],
                "session-001",
            )
            self.assertEqual(
                session_record["accepted_session_config"]["selected_devices"][0],
                {
                    "device_id": "declared-camera-001",
                    "device_type": "camera",
                    "enabled": True,
                    "required": True,
                    "declared_capabilities": ["tiny_stream"],
                },
            )
            self.assertEqual(
                session_record["accepted_session_config"][
                    "device_configurations"
                ],
                {"declared-camera-001": {"exposure_ms": 5}},
            )
            self.assertEqual(
                [
                    transition["to_state"]
                    for transition in session_record[
                        "session_lifecycle_evidence"
                    ]
                ],
                ["initialized", "running", "stopping", "completed"],
            )
            self.assertTrue(
                any(
                    check["name"] == "session_id_exists"
                    and check["status"] == "PASS"
                    for check in session_record["readiness_evidence"]
                )
            )
            self.assertEqual(
                session_record["device_readiness_evidence"],
                [
                    {
                        "device_id": "adapter-camera-001",
                        "required": True,
                        "ready": True,
                        "reason": "ready",
                        "capabilities_available": ["tiny_stream"],
                    }
                ],
            )
            self.assertEqual(
                [
                    readiness["component_id"]
                    for readiness in session_record[
                        "service_readiness_evidence"
                    ]
                ],
                ["synchronization", "ingestor", "failure_evidence", "storage"],
            )
            self.assertEqual(
                len(session_record["accepted_acquisition_envelopes"]),
                3,
            )
            event_envelopes = [
                envelope
                for envelope in session_record[
                    "accepted_acquisition_envelopes"
                ]
                if envelope["record_kind"] == "event"
            ]
            stream_envelopes = [
                envelope
                for envelope in session_record[
                    "accepted_acquisition_envelopes"
                ]
                if envelope["record_kind"] == "tiny_stream"
            ]
            self.assertEqual(
                event_envelopes[0]["records"][0],
                {
                    "event_category": "session_lifecycle",
                    "event_type": "session_start",
                    "session_time_s": 0.0,
                },
            )
            self.assertEqual(
                event_envelopes[1]["records"][0]["event_type"],
                "session_stop",
            )
            stored_stream_rows = stream_envelopes[0]["records"]
            self.assertEqual(
                [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {
                            "session_time_s",
                            "acquisition_node_local_time_s",
                            "timestamp_status",
                        }
                    }
                    for row in stored_stream_rows
                ],
                list(payload_rows),
            )
            self.assertTrue(
                all("session_time_s" in row for row in stored_stream_rows)
            )
            self.assertTrue(
                all(
                    isinstance(row["acquisition_node_local_time_s"], float)
                    and row["timestamp_status"] == "runtime_timestamped"
                    for row in stored_stream_rows
                )
            )
            self.assertEqual(
                len(session_record["ingest_audit_records"]),
                len(session_record["accepted_acquisition_envelopes"]),
            )
            self.assertTrue(
                all(
                    audit["accepted"]
                    for audit in session_record["ingest_audit_records"]
                )
            )
            self.assertEqual(
                session_record["final_session_status"]["state"],
                "completed",
            )
            self.assertTrue(
                session_record["final_session_status"]["cleanup_occurred"]
            )
            self.assertEqual(
                session_record["cleanup_evidence"],
                {
                    "cleanup_occurred": True,
                    "cleanup_sequence": session.cleanup_sequence,
                },
            )
            self.assertEqual(session_record["warnings_or_failures"], [])

    @staticmethod
    def _minimal_session_record_evidence(session_id):
        return {
            "accepted_session_config": {"session_id": session_id},
            "lifecycle_evidence": (),
            "readiness_evidence": (),
            "device_readiness_evidence": (),
            "service_readiness_evidence": (),
            "accepted_acquisition_envelopes": (),
            "ingest_audit_records": (),
            "final_session_status": None,
            "cleanup_evidence": {},
        }

    @staticmethod
    def _read_jsonl(path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()


