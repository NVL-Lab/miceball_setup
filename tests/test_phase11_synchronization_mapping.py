import tempfile
import unittest
from dataclasses import FrozenInstanceError

from lab_sync_acquisition import (
    AcquisitionNode,
    AcquisitionNodeLocalTimeReport,
    DeviceManager,
    InMemoryIngestor,
    MAPPING_UPDATE_EVIDENCE_TYPE,
    MappingUpdateEvidence,
    SynchronizationManager,
    SynchronizationMapping,
)
from tests.fakes import ReadyFakeAdapter


class MappingSliceAdapter(ReadyFakeAdapter):
    def __init__(self):
        super().__init__("source-001", "fake", ("stream",), True)
        self._records = ({"sample_index": 1},)

    def collect_records(self):
        records, self._records = self._records, ()
        return {"record_kind": "stream", "records": records}


class Phase11SynchronizationMappingTests(unittest.TestCase):
    def test_mapping_update_evidence_uses_explicit_runtime_evidence_type(self):
        manager = SynchronizationManager()
        manager.create_and_activate_mapping(
            "session-001", "node-001", 10.0, 10.5, 1.0, "initial"
        )
        evidence = manager.mapping_update_evidence[0]

        message = evidence.to_runtime_evidence_message(
            evidence_id="mapping-update-001",
            source_id="synchronization",
        )

        self.assertEqual(
            message.evidence_type,
            MAPPING_UPDATE_EVIDENCE_TYPE,
        )
        self.assertEqual(message.evidence_type, "mapping_update_evidence")
        self.assertEqual(message.payload, evidence.to_dict())
        self.assertEqual(message.session_id, evidence.session_id)
        self.assertEqual(message.source_id, "synchronization")

    def test_synchronization_mapping_round_trips_as_immutable_plain_data(self):
        mapping = self._mapping()

        self.assertEqual(
            SynchronizationMapping.from_dict(mapping.to_dict()),
            mapping,
        )
        with self.assertRaises(FrozenInstanceError):
            mapping.scale = 2.0

    def test_local_time_report_round_trips_without_becoming_observation_evidence(self):
        report = AcquisitionNodeLocalTimeReport(
            session_id="session-001",
            acquisition_node_id="node-001",
            acquisition_node_local_time_s=10.0,
            reported_reason="periodic",
            details={"sequence": 1},
        )

        self.assertEqual(
            AcquisitionNodeLocalTimeReport.from_dict(report.to_dict()),
            report,
        )
        self.assertNotIsInstance(report, MappingUpdateEvidence)

    def test_mapping_update_evidence_round_trips_with_optional_mappings(self):
        previous = self._mapping()
        replacement = SynchronizationMapping(
            **{
                **previous.to_dict(),
                "local_time_anchor_s": 20.0,
                "session_time_anchor_s": 20.5,
            }
        )
        evidence = MappingUpdateEvidence(
            session_id="session-001",
            acquisition_node_id="node-001",
            update_type="replaced",
            previous_mapping=previous,
            new_mapping=replacement,
            created_session_time_s=21.0,
            reason="new active mapping",
            details={"source": "manual-test"},
        )

        self.assertEqual(
            MappingUpdateEvidence.from_dict(evidence.to_dict()),
            evidence,
        )

    def test_synchronization_manager_owns_per_node_mapping_lifecycle(self):
        manager = SynchronizationManager()

        initial = manager.create_and_activate_mapping(
            "session-001", "node-001", 10.0, 10.5, 1.0, "initial"
        )
        other = manager.create_and_activate_mapping(
            "session-001", "node-002", 30.0, 30.5, 1.0, "initial"
        )
        replacement = manager.replace_active_mapping(
            "session-001", "node-001", 20.0, 20.5, 1.0, "periodic"
        )
        retired = manager.retire_active_mapping(
            "session-001", "node-001", "runtime complete"
        )

        self.assertIsNone(manager.get_active_mapping("session-001", "node-001"))
        self.assertIs(
            manager.get_active_mapping("session-001", "node-002"),
            other,
        )
        self.assertEqual(initial.local_time_anchor_s, 10.0)
        self.assertEqual(replacement.local_time_anchor_s, 20.0)
        self.assertEqual(
            [item.update_type for item in manager.mapping_update_evidence],
            ["created", "created", "replaced", "retired"],
        )
        self.assertIs(retired.previous_mapping, replacement)
        self.assertIsNone(retired.new_mapping)

    def test_acquisition_node_passively_replaces_mapping_without_row_identifier(self):
        adapter = MappingSliceAdapter()
        device_manager = DeviceManager((adapter,))
        synchronization = SynchronizationManager()
        ingestor = InMemoryIngestor()
        node = AcquisitionNode(
            session_id="session-001",
            node_id="node-001",
            device_manager=device_manager,
            synchronization_manager=synchronization,
            ingestor=ingestor,
            error_evidence_location=tempfile.gettempdir(),
        )
        initial = synchronization.create_and_activate_mapping(
            "session-001", "node-001", 10.0, 10.5, 1.0, "initial"
        )
        replacement = synchronization.replace_active_mapping(
            "session-001", "node-001", 20.0, 20.5, 1.0, "periodic"
        )

        node.receive_active_synchronization_mapping(initial)
        self.assertIs(node.status()["active_synchronization_mapping"], initial)
        node.receive_active_synchronization_mapping(replacement)
        self.assertIs(
            node.status()["active_synchronization_mapping"],
            replacement,
        )

        device_manager.initialize_all(config={})
        node.start_runtime()
        node.run_one_iteration()
        row = next(
            row
            for envelope in ingestor.accepted_envelopes
            if envelope.record_kind == "stream"
            for row in envelope.records
        )

        self.assertNotIn("mapping_id", row)
        self.assertNotIn("synchronization_mapping", row)
        self.assertIn("session_time_s", row)
        self.assertIn("acquisition_node_local_time_s", row)
        self.assertEqual(row["timestamp_status"], "runtime_timestamped")

        node.receive_active_synchronization_mapping(None)
        self.assertIsNone(node.status()["active_synchronization_mapping"])

    @staticmethod
    def _mapping():
        return SynchronizationMapping(
            session_id="session-001",
            acquisition_node_id="node-001",
            local_time_anchor_s=10.0,
            session_time_anchor_s=10.5,
            scale=1.0,
            created_session_time_s=0.0,
        )


if __name__ == "__main__":
    unittest.main()
