"""Independent startup resumes through existing readiness and registration APIs."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lab_sync_acquisition import (AcquisitionNode, Controller, DeviceManager,
    RuntimeCommandMessage, RuntimeParticipant, ServiceMaintenanceInterface, SynchronizationManager)
from tests import test_service_startup as fixtures
from tests.fakes import ReadyFakeAdapter


class RegistrationTransport:
    def __init__(self):
        self.available = True
        self.identity = "ingestor-first"
        self.calls = []
        self.registering = asyncio.Event()
        self.release = None
        self.delay = 0
        self.discovery_gate = None
        self.discovering = asyncio.Event()

    async def request_persistence_command(self, participant, operation, session, payload, window, **kwargs):
        if not self.available:
            return None
        return SimpleNamespace(success=True, payload={"acceptance_confirmed": True, "archival_confirmed": True,
            "storage_participant": {"component_type": "storage_manager", "component_id": "storage"},
            "evidence": payload["evidence"]})

    async def request_maintenance_readback(self, participant, operation, payload, window):
        self.calls.append((operation, window))
        if operation == "preserve_service_evidence":
            return SimpleNamespace(success=False, reason="Fixture preservation unavailable", payload={})
        if operation == "read_operational_instance":
            self.discovering.set()
            if self.discovery_gate is not None:
                await self.discovery_gate.wait()
        await asyncio.sleep(self.delay)
        if not self.available:
            return None
        if operation == "read_operational_instance":
            return SimpleNamespace(success=True, payload={"operational_instance_id": self.identity})
        if operation == "register_operational_dependent":
            self.registering.set()
            if self.release is not None:
                await self.release.wait()
            return SimpleNamespace(success=True, payload={"registration": dict(payload)})
        raise AssertionError(operation)


class RegistrationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ServiceStartupTests.asyncSetUp
    interface = fixtures.ServiceStartupTests.interface
    communication = fixtures.ServiceStartupTests.communication

    def dependent(self, service=None, kind="synchronization_manager", window=.2, preservation_window=.01):
        self.transport = RegistrationTransport()
        self.service = service or SynchronizationManager()
        self.maintenance = ServiceMaintenanceInterface(self.service, RuntimeParticipant(kind, "sync"),
            ingestor=None, storage_manager=None, evidence_publisher=AsyncMock(),
            preservation_window_s=preservation_window, registration_window_s=window,
            close_resources=AsyncMock(return_value=True),
            dependency_participants=(RuntimeParticipant("ingestor", "ingestor"),),
            framework_ingestor=RuntimeParticipant("ingestor", "ingestor"),
            framework_storage=RuntimeParticipant("storage_manager", "storage"),
            framework_communication=self.transport)
        return self.communication(self.maintenance)

    async def test_absent_dependency_returns_and_completes_startup_without_restart(self):
        communication = self.dependent()
        self.transport.available = False
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            await communication.start()
        with self.assertRaisesRegex(RuntimeError, "registration"):
            self.service.prepare_session("blocked")
        self.assertFalse(self.maintenance.terminated)
        remote = self.interface(self.ingestor, RuntimeParticipant("ingestor", "ingestor"))
        returning = self.communication(remote)
        self.transport.identity = remote.operational_instance_id
        self.transport.available = True
        await returning.start()
        self.assertTrue(self.service.prepare_session("resumed").ready)
        self.assertEqual(sum(op == "register_operational_dependent" for op, _ in self.transport.calls), 1)

    async def test_missed_announcement_recovers_by_explicit_readiness_check(self):
        communication = self.dependent()
        self.transport.available = False
        with self.assertRaises(RuntimeError):
            await communication.start()
        remote = self.interface(self.ingestor, RuntimeParticipant("ingestor", "ingestor"))
        returning = self.communication(remote)
        await returning.subscribe_commands()
        self.transport.identity = remote.operational_instance_id
        self.transport.available = True
        report = await communication.check_dependency_readiness(remote.participant, .1)
        self.assertTrue(report.ready)
        self.assertTrue(self.service.prepare_session("resumed").ready)

    async def test_duplicate_announcements_and_concurrent_checks_keep_one_binding(self):
        communication = self.dependent()
        self.transport.available = False
        with self.assertRaises(RuntimeError):
            await communication.start()
        remote = self.interface(self.ingestor, RuntimeParticipant("ingestor", "ingestor"))
        returning = self.communication(remote)
        await returning.subscribe_commands()
        self.transport.identity = remote.operational_instance_id
        self.transport.available = True
        await returning.start()
        with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as capture:
            await asyncio.gather(remote.announce_readiness(startup=True),
                remote.announce_readiness(startup=True),
                communication.check_dependency_readiness(remote.participant, .5),
                communication.check_dependency_readiness(remote.participant, .5))
        self.assertFalse(any("registration.request" in line for line in capture.output),
            "Coalesced notifications do not produce duplicate registration diagnostics")
        self.assertEqual(sum(op == "register_operational_dependent" for op, _ in self.transport.calls), 1)
        self.assertTrue(self.service.prepare_session("same-binding").ready)

    async def test_duplicate_concurrent_notifications_share_registration(self):
        self.dependent()
        self.transport.release = asyncio.Event()
        attempts = [asyncio.create_task(self.maintenance.register_ingestor_dependency(refresh=False)) for _ in range(4)]
        await self.transport.registering.wait()
        self.transport.release.set()
        await asyncio.gather(*attempts)
        self.assertEqual(sum(op == "register_operational_dependent" for op, _ in self.transport.calls), 1)

    async def test_replacement_invalidates_admission_and_rejects_old_confirmation(self):
        self.dependent()
        self.transport.release = asyncio.Event()
        first = asyncio.create_task(self.maintenance.register_ingestor_dependency())
        await self.transport.registering.wait()
        self.assertTrue(self.maintenance.observe_ingestor_instance("ingestor-replacement"))
        self.transport.release.set()
        with self.assertRaisesRegex(RuntimeError, "superseded"):
            await first
        with self.assertRaisesRegex(RuntimeError, "registration"):
            self.service.prepare_session("blocked")
        self.transport.identity = "ingestor-replacement"
        await self.maintenance.register_ingestor_dependency()
        self.assertEqual(sum(op == "register_operational_dependent" for op, _ in self.transport.calls), 2)

    async def test_shutdown_preparation_rejects_late_registration(self):
        service = SynchronizationManager()
        service.start()
        self.dependent(service)
        self.transport.release = asyncio.Event()
        pending = asyncio.create_task(self.maintenance.register_ingestor_dependency())
        await self.transport.registering.wait()
        prepared = await self.maintenance.execute_command(RuntimeCommandMessage(
            "stop", None, "stop", "administrator", "sync",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"}))
        self.assertIsNotNone(prepared.payload.get("attempt"))
        self.assertEqual(prepared.payload.get("outcome"), "blocked")
        self.assertFalse(self.maintenance.terminated)
        self.transport.release.set()
        with self.assertRaisesRegex(RuntimeError, "Maintenance"):
            await pending
        with self.assertRaises(RuntimeError):
            self.service.prepare_session("blocked")

    async def test_overall_deadline_covers_both_requests_and_later_recovery(self):
        self.dependent(window=.4)
        self.transport.delay = .25
        with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as timeout:
            with self.assertRaises(TimeoutError):
                await self.maintenance.register_ingestor_dependency()
        self.assertTrue(any("error_type=TimeoutError" in line for line in timeout.output))
        discovery, registration = self.transport.calls
        self.assertLess(registration[1], discovery[1])
        self.assertLessEqual(discovery[1], .4)
        self.assertEqual(self.maintenance.preservation_window_s, .01)
        self.transport.delay = 0
        await self.maintenance.register_ingestor_dependency()

    async def test_stop_during_discovery_does_not_send_new_registration(self):
        service = SynchronizationManager()
        service.start()
        self.dependent(service)
        self.transport.discovery_gate = asyncio.Event()
        pending = asyncio.create_task(self.maintenance.register_ingestor_dependency())
        await self.transport.discovering.wait()
        result = await self.maintenance.execute_command(RuntimeCommandMessage(
            "stop", None, "stop", "administrator", "sync",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"}))
        self.assertEqual(result.payload["outcome"], "blocked")
        self.transport.discovery_gate.set()
        with self.assertRaisesRegex(RuntimeError, "Maintenance"):
            await pending
        self.assertFalse(any(op == "register_operational_dependent" for op, _ in self.transport.calls))

    async def test_controller_without_claim_cannot_register(self):
        self.dependent(Controller(), kind="controller")
        with self.assertRaisesRegex(RuntimeError, "claim"):
            await self.maintenance.register_ingestor_dependency()
        self.assertEqual(self.transport.calls, [])

    async def test_node_reservation_stays_blocked_until_registration(self):
        adapter = ReadyFakeAdapter(device_id="device", device_type="fake", required=True, declared_capabilities=())
        node = AcquisitionNode(device_manager=DeviceManager((adapter,)), synchronization_manager=SynchronizationManager(),
            ingestor=self.ingestor, node_id="node", role="acquisition", error_evidence_location=str(self.root / "errors"))
        self.dependent(node, "acquisition_node")
        with self.assertRaisesRegex(RuntimeError, "registration"):
            node.reserve("session")
        await self.maintenance.register_ingestor_dependency()
        self.assertTrue(node.reserve("session"))

    async def test_return_announcement_supersedes_a_wait_sent_before_ingestor_started(self):
        communication = self.dependent(window=2)
        self.transport.discovery_gate = asyncio.Event()
        startup = asyncio.create_task(communication.start())
        await self.transport.discovering.wait()
        remote = self.interface(self.ingestor, RuntimeParticipant("ingestor", "ingestor"))
        returning = self.communication(remote)
        self.transport.identity = remote.operational_instance_id
        self.transport.discovery_gate = None
        await returning.start()
        with self.assertRaisesRegex(RuntimeError, "superseded"):
            await startup
        self.assertTrue(self.service.prepare_session("recovered").ready)

    async def test_default_budget_does_not_change_preservation_window(self):
        self.dependent(window=180)
        await self.maintenance.register_ingestor_dependency()
        self.assertEqual(self.maintenance.registration_window_s, 180)
        self.assertTrue(all(0 < window <= 180 for _, window in self.transport.calls))
        self.assertEqual(self.maintenance.preservation_window_s, .01)

    async def test_registration_diagnostics_preserve_order_budget_and_safe_fields(self):
        self.dependent()
        with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as capture:
            await self.maintenance.register_ingestor_dependency()
        lines = capture.output
        stages = [line.split(":", 2)[-1].split()[0] for line in lines]
        self.assertEqual(stages, ["registration.request", "registration.response",
            "registration.request", "registration.response", "registration.confirmed"])
        self.assertTrue(any("elapsed_s=" in line for line in lines))
        self.assertTrue(any("budget_s=" in line for line in lines))
        self.assertTrue(any(self.maintenance.operational_instance_id in line for line in lines))
        self.transport.available = False
        with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as unknown:
            with self.assertRaises(RuntimeError):
                await self.maintenance.register_ingestor_dependency()
        self.assertIn("outcome=unconfirmed", "\n".join(unknown.output))
        self.assertNotIn("TimeoutError", "\n".join(unknown.output))

    async def test_rejection_diagnostics_do_not_expose_owner_exception_or_payload(self):
        self.dependent()
        secret = "nats://user:password@private-host/?token=private-token"
        replies = [SimpleNamespace(success=True, payload={"operational_instance_id": "owner"}),
                   SimpleNamespace(success=False, reason=secret, payload={"password": "private-token"})]
        with patch.object(self.transport, "request_maintenance_readback", side_effect=replies):
            with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as capture:
                with self.assertRaises(RuntimeError):
                    await self.maintenance.register_ingestor_dependency()
        output = "\n".join(capture.output)
        self.assertIn("outcome=rejected", output)
        for value in ("password", "private-token", "private-host", "nats://"):
            self.assertNotIn(value, output)

    async def test_response_diagnostic_follows_durability_without_claiming_requester_receipt(self):
        from lab_sync_acquisition import NatsCommunicationBoundary, RuntimeCommandResultMessage
        boundary = NatsCommunicationBoundary("ingestor", "ingestor", servers=("nats://isolated.invalid:4222",))
        response = RuntimeCommandResultMessage("result", "correlated-command", None, "ingestor", "sync",
            "succeeded", True, None, {"private_payload": "do-not-log"})
        async def durable(*args):
            self.assertFalse(any("response.published" in line for line in capture.output))
        with self.assertLogs("lab_sync_acquisition.deployment", level="INFO") as capture:
            with patch.object(boundary, "_publish_durable", side_effect=durable):
                await boundary.publish_command_result(response, "register_operational_dependent")
            with patch.object(boundary, "_publish_durable", side_effect=OSError("Unconfirmed publication")):
                with self.assertRaises(OSError):
                    await boundary.publish_command_result(response, "register_operational_dependent")
        self.assertEqual(len(capture.output), 1)
        self.assertIn("response.published", capture.output[0])
        self.assertIn("command_id=correlated-command", capture.output[0])
        self.assertNotIn("receipt", capture.output[0])
        self.assertNotIn("do-not-log", capture.output[0])

    async def test_authoritative_discovery_of_replacement_closes_admission_before_ack(self):
        self.dependent()
        await self.maintenance.register_ingestor_dependency()
        self.transport.identity = "replacement"
        self.transport.registering.clear()
        self.transport.release = asyncio.Event()
        pending = asyncio.create_task(self.maintenance.register_ingestor_dependency())
        await self.transport.registering.wait()
        with self.assertRaisesRegex(RuntimeError, "registration"):
            self.service.prepare_session("blocked")
        self.transport.release.set()
        await pending

    async def test_retirement_cannot_reactivate_and_keeps_release_window(self):
        self.dependent(preservation_window=.25)
        await self.maintenance.register_ingestor_dependency()
        result = await self.maintenance.execute_command(RuntimeCommandMessage(
            "stop", None, "stop", "administrator", "sync",
            {"stop_attempt_id": "attempt", "administrator_id": "operator"}))
        self.assertTrue(result.payload.get("termination_confirmed"), result.reason)
        self.assertFalse(self.maintenance.observe_ingestor_instance("late-owner"))
        with self.assertRaisesRegex(RuntimeError, "Maintenance"):
            await self.maintenance.register_ingestor_dependency()
        self.transport.identity = "returning-for-release"
        await self.maintenance.register_ingestor_dependency(retirement=True)
        self.assertTrue(all(window <= self.maintenance.preservation_window_s
                            for _, window in self.transport.calls[-2:]))
        with self.assertRaisesRegex(RuntimeError, "terminated"):
            self.service.prepare_session("never-reactivate")


if __name__ == "__main__":
    unittest.main()
