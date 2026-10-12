"""Informational reconciliation through retained public Controller workflows."""

import json
import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from lab_sync_acquisition import Controller, RuntimeEvidenceMessage, RuntimeParticipant, ServiceMaintenanceInterface, SessionConfig
from tests import test_framework_shutdown as shutdown_fixtures
from tests import test_storage as storage_fixtures
from tests import test_session_launch as launch_fixtures


class ControllerReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workflow = shutdown_fixtures.FrameworkShutdownTests("runTest")
        await self.workflow.asyncSetUp()
        self.addCleanup(self.workflow.temporary.cleanup)
        self.controller = self.workflow.controller
        self.storage = self.workflow.storage
        self.ingestor = self.workflow.ingestor
        self.root = self.workflow.root

    async def interrupted_shutdown(self, *, missing=False):
        if missing:
            self.workflow.interfaces["synchronization_manager"].close_resources = AsyncMock(return_value=True)
            publish = self.workflow.communication.request_command
            async def no_response(participant, operation, *args, **kwargs):
                if participant.component_type == "synchronization_manager" and operation == "stop":
                    return None
                return await publish(participant, operation, *args, **kwargs)
            self.workflow.communication.request_command = no_response
        else:
            self.workflow.interfaces["synchronization_manager"].close_resources = AsyncMock(return_value=False)
        result = await self.workflow.shutdown()
        self.assertFalse(result.succeeded)
        return result

    async def test_proven_participant_completion_and_partial_failure_are_separate(self):
        await self.interrupted_shutdown()
        commands = list(self.workflow.broker.commands)
        status = self.controller.get_status()
        result = await self.controller.reconcile_outcomes()
        attempt, = result["findings"]["framework_attempts"]
        outcomes = {p["participant"]["component_type"]: p for p in attempt["participant_outcomes"]}
        self.assertEqual(outcomes["acquisition_node"]["outcome"], "completed")
        self.assertTrue(outcomes["acquisition_node"]["archival_confirmed"])
        self.assertEqual(outcomes["synchronization_manager"]["outcome"], "failed")
        self.assertEqual(outcomes["storage_manager"]["outcome"], "unresolved")
        self.assertTrue(attempt["partial_completion"])
        self.assertTrue(result["archival_confirmed"])
        self.assertEqual(self.workflow.broker.commands, commands)
        self.assertEqual(self.controller.get_status(), status)

    async def test_missing_response_is_unresolved_not_failed_or_completed(self):
        await self.interrupted_shutdown(missing=True)
        result = await self.controller.reconcile_outcomes()
        entries = result["findings"]["framework_attempts"][0]["participant_outcomes"]
        sync = next(e for e in entries if e["participant"]["component_type"] == "synchronization_manager")
        self.assertEqual(sync["outcome"], "unresolved")
        self.assertIsNotNone(sync["command_id"])

    async def test_repeated_unchanged_reconciliation_does_not_publish_new_evidence(self):
        await self.interrupted_shutdown()
        first = await self.controller.reconcile_outcomes()
        journal = (self.root / "framework-journal.jsonl").read_bytes()
        second = await self.controller.reconcile_outcomes()
        self.assertTrue(second["unchanged"])
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual((self.root / "framework-journal.jsonl").read_bytes(), journal)
        self.assertEqual(len(self.controller.reconciliation_evidence), 1)

    async def test_conflicting_durable_participant_outcome_is_not_silently_completed(self):
        await self.interrupted_shutdown()
        evidence = next(m for m in reversed(self.workflow.archive())
            if m["source_id"] == "controller" and any(e.get("result")
                and e["result"]["payload"].get("termination_confirmed")
                for e in m["payload"].get("results", ())))
        payload = json.loads(json.dumps(evidence["payload"]))
        completed = next(e["result"] for e in payload["results"]
            if e.get("result") and e["result"]["payload"].get("termination_confirmed"))
        completed["success"] = False
        completed["status"] = "failed"
        self.ingestor.receive_runtime_evidence(RuntimeEvidenceMessage("conflicting-outcome", None,
            "service_maintenance_evidence", "controller", payload, True))
        self.storage.write_framework_evidence_archive(self.ingestor.compile_framework_runtime_evidence())
        result = await self.controller.reconcile_outcomes()
        node = next(e for e in result["findings"]["framework_attempts"][0]["participant_outcomes"]
            if e["participant"]["component_type"] == "acquisition_node")
        self.assertEqual(node["outcome"], "conflicting")
        self.assertTrue(result["findings"]["unresolved"])

    async def test_corrupted_archive_is_reported_and_not_repaired_by_reconciliation(self):
        await self.interrupted_shutdown()
        archive = self.root / "framework/evidence/runtime_evidence.jsonl"
        archive.write_bytes(b"corrupted archive")
        with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
            result = await self.controller.reconcile_outcomes()
        self.assertFalse(result["findings"]["preservation_confirmed"])
        self.assertFalse(result["archival_confirmed"])
        self.assertTrue(result["acceptance_confirmed"])
        self.assertTrue(result["preservation_warning"])
        self.assertEqual(archive.read_bytes(), b"corrupted archive")
        repeated = await self.controller.reconcile_outcomes()
        self.assertTrue(repeated["unchanged"])
        self.assertTrue(repeated["preservation_warning"])

    async def test_unrelated_session_does_not_leak_framework_or_current_session_outcomes(self):
        await self.interrupted_shutdown()
        self.assertTrue(self.controller.create_session(SessionConfig(session_id="session-b",
            selected_devices=(), storage_location=str(self.root), protocol_plan={},
            error_evidence_location=str(self.root / "errors"))).succeeded)
        state = self.controller.get_status()
        result = await self.controller.reconcile_outcomes(session_id="session-a")
        self.assertEqual(result["findings"]["framework_attempts"], [])
        self.assertEqual(result["findings"]["session_command_outcomes"], [])
        self.assertTrue(result["findings"]["unresolved"])
        self.assertEqual(self.controller.get_status(), state)

    async def test_session_confirmation_checks_current_bytes_not_cached_success(self):
        self.storage.write_evidence_archive("session-a", {"runtime_evidence": (), "ingest_audit": ()})
        self.storage.write_final_session_record("session-a",
            **storage_fixtures.PersistentStorageManagerTests._minimal_session_record_evidence("session-a"))
        self.assertIsNotNone(self.storage.get_session_preservation_confirmation("session-a"))
        path = self.root / "session_session-a/evidence/ingest_audit.jsonl"
        path.write_text('{"evidence_id":"not-written"}\n')
        self.assertIsNone(self.storage.get_session_preservation_confirmation("session-a"))
        result = await self.controller.reconcile_outcomes(session_id="session-a")
        self.assertFalse(result["findings"]["preservation_confirmed"])
        self.assertEqual(path.read_text(), '{"evidence_id":"not-written"}\n')

    async def test_corruption_during_findings_publication_is_not_silently_repaired(self):
        await self.interrupted_shutdown()
        interface = self.workflow.interfaces["controller"]
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def publish(message):
            entered.set()
            await proceed.wait()
            self.ingestor.receive_runtime_evidence(message)
        interface.evidence_publisher = publish
        task = asyncio.create_task(self.controller.reconcile_outcomes())
        path = self.root / "framework/evidence/ingest_audit.jsonl"
        try:
            await asyncio.wait_for(entered.wait(), 5)
            path.write_bytes(b"changed during publication")
            with self.assertLogs("lab_sync_acquisition.service_maintenance", level="WARNING"):
                proceed.set()
                result = await task
            self.assertFalse(result["archival_confirmed"])
            self.assertTrue(result["acceptance_confirmed"])
            self.assertTrue(result["preservation_warning"])
            self.assertEqual(path.read_bytes(), b"changed during publication")
        finally:
            proceed.set()
            await task

    async def test_session_launch_outcomes_are_read_without_authorization_or_operational_work(self):
        workflow = launch_fixtures.SessionLaunchTests("runTest")
        workflow.setUp()
        self.addCleanup(workflow.temporary.cleanup)
        workflow.ingestor.prepare_framework_evidence(workflow.root / "framework.jsonl")
        workflow.controller = Controller(ingestor=workflow.ingestor, storage_manager=self.storage,
                                         synchronization_manager=workflow.sync)
        ServiceMaintenanceInterface(workflow.controller, RuntimeParticipant("controller", "controller"),
            ingestor=workflow.ingestor, storage_manager=self.storage, preservation_window_s=0,
            close_resources=AsyncMock(return_value=True))
        await workflow.services()
        node, declaration, _ = await workflow.node()
        launched = await workflow.launch({"node-a": (declaration,)})
        self.assertTrue(launched.succeeded, launched.error)
        session_id = launched.details["session_id"]
        before = workflow.controller.get_status()
        commands = list(workflow.broker.commands)
        result = await workflow.controller.reconcile_outcomes(session_id=session_id)
        self.assertEqual(len(result["findings"]["session_participant_outcomes"]), 3)
        self.assertTrue(all(p["outcome"] == "completed" for p in result["findings"]["session_participant_outcomes"]))
        self.assertTrue(result["findings"]["received_command_results"])
        self.assertEqual(workflow.broker.commands, commands)
        self.assertEqual(workflow.controller.get_status(), before)
        self.assertTrue(node.abort_session_initialization(session_id))
        self.assertTrue(node.release_reservation(session_id))
