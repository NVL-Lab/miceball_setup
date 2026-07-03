import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    DeviceAdapter,
    DeviceDeclaration,
    DeviceManager,
    DeviceReadiness,
    InMemoryIngestor,
    InMemoryStorageManager,
    Session,
    SessionConfig,
    SessionLifecycleError,
    SessionState,
    ServiceReadiness,
    SynchronizationManager,
)
from tests.fakes import ReadyFakeAdapter


def config() -> SessionConfig:
    return SessionConfig(
        selected_devices=[],
        storage_location="placeholder://session",
        protocol_plan={"name": "no-op"},
        error_evidence_location="placeholder://errors",
    )


def device_declaration() -> DeviceDeclaration:
    return DeviceDeclaration(
        device_id="camera-001",
        device_type="camera",
        enabled=True,
        required=True,
        declared_capabilities=["produces_stream"],
    )


def running_session() -> Session:
    session = Session(session_id="session-001", configuration=config())
    session.initialize()
    session.start()
    return session


def device_readiness(
    device_id: str,
    *,
    required: bool,
    ready: bool,
    reason: str = "ready",
) -> DeviceReadiness:
    return DeviceReadiness(
        device_id=device_id,
        required=required,
        ready=ready,
        reason=reason,
        capabilities_available=["reports_health"],
    )


class SessionLifecycleTests(unittest.TestCase):
    def test_valid_lifecycle_completion(self) -> None:
        session = running_session()

        session.stop(reason="normal stop")
        session.complete(reason="normal completion")

        self.assertIs(session.current_state, SessionState.COMPLETED)
        self.assertEqual(
            [transition.to_state for transition in session.transition_history],
            [
                SessionState.INITIALIZED,
                SessionState.RUNNING,
                SessionState.STOPPING,
                SessionState.COMPLETED,
            ],
        )
        self.assertIsNotNone(session.final_status)
        self.assertEqual(session.final_status["state"], "completed")
        self.assertEqual(session.final_status["reason"], "normal completion")
        self.assertTrue(session.final_status["cleanup_occurred"])

    def test_empty_selected_devices_is_allowed(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        session.initialize()

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        checks = {
            (check.name, check.status, check.reason)
            for check in session.readiness_checks
        }
        self.assertIn(
            ("selected_devices_declared", "PASS", "selected_devices_declared"),
            checks,
        )

    def test_session_preserves_accepted_run_configuration(self) -> None:
        declaration = device_declaration()
        accepted_config = SessionConfig(
            session_id="session-001",
            selected_devices=[declaration],
            session_parameters={"experimenter": "test-user"},
            device_configurations={
                "camera-001": {
                    "exposure_ms": 5,
                    "frame_rate_hz": 30,
                },
            },
            synchronization_configuration={"clock": "phase1_monotonic"},
            acquisition_configuration={"bounded_iterations": 3},
            ingestion_configuration={"mode": "in_memory"},
            storage_configuration={"mode": "in_memory"},
            storage_location="placeholder://session",
            protocol_plan={"name": "no-op"},
            error_evidence_location="placeholder://errors",
            protocol_reference="protocol://no-op",
        )
        session = Session(session_id="session-001", configuration=accepted_config)

        session.initialize()

        self.assertIs(session.configuration, accepted_config)
        self.assertEqual(
            session.configuration.to_dict()["error_evidence_location"],
            "placeholder://errors",
        )
        self.assertIs(session.configuration.selected_devices[0], declaration)
        self.assertEqual(
            session.configuration.device_configurations["camera-001"],
            {
                "exposure_ms": 5,
                "frame_rate_hz": 30,
            },
        )
        self.assertEqual(declaration.device_id, "camera-001")
        self.assertEqual(declaration.device_type, "camera")
        self.assertTrue(declaration.enabled)
        self.assertTrue(declaration.required)
        self.assertEqual(declaration.declared_capabilities, ("produces_stream",))
        self.assertFalse(hasattr(declaration, "exposure_ms"))
        self.assertFalse(hasattr(declaration, "frame_rate_hz"))
        self.assertIs(session.current_state, SessionState.INITIALIZED)

    def test_valid_device_declaration_passes_initialization(self) -> None:
        declaration = device_declaration()
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[declaration],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        session.initialize()

        self.assertEqual(declaration.declared_capabilities, ("produces_stream",))
        self.assertIs(session.current_state, SessionState.INITIALIZED)
        checks = {
            (check.name, check.status, check.reason)
            for check in session.readiness_checks
        }
        self.assertIn(
            ("selected_devices[0].device_id_exists", "PASS", "device_id_declared"),
            checks,
        )
        self.assertIn(
            (
                "selected_devices[0].device_type_exists",
                "PASS",
                "device_type_declared",
            ),
            checks,
        )
        self.assertIn(
            (
                "selected_devices[0].enabled_is_boolean",
                "PASS",
                "enabled_declared_as_boolean",
            ),
            checks,
        )
        self.assertIn(
            (
                "selected_devices[0].required_is_boolean",
                "PASS",
                "required_declared_as_boolean",
            ),
            checks,
        )
        self.assertIn(
            (
                "selected_devices[0].declared_capabilities_declared",
                "PASS",
                "declared_capabilities_declared",
            ),
            checks,
        )

    def test_missing_device_id_fails_initialization(self) -> None:
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[
                    DeviceDeclaration(
                        device_id="",
                        device_type="camera",
                        enabled=True,
                        required=True,
                        declared_capabilities=[],
                    )
                ],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        with self.assertRaises(SessionLifecycleError):
            session.initialize()

        self.assertIn(
            "selected_devices[0].device_id_exists",
            [check.name for check in session.readiness_checks if check.status == "FAIL"],
        )
        self.assertIs(session.current_state, SessionState.CREATED)

    def test_missing_device_type_fails_initialization(self) -> None:
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[
                    DeviceDeclaration(
                        device_id="camera-001",
                        device_type=None,
                        enabled=True,
                        required=True,
                        declared_capabilities=[],
                    )
                ],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        with self.assertRaises(SessionLifecycleError):
            session.initialize()

        self.assertIn(
            "selected_devices[0].device_type_exists",
            [check.name for check in session.readiness_checks if check.status == "FAIL"],
        )
        self.assertIs(session.current_state, SessionState.CREATED)

    def test_empty_declared_capabilities_is_allowed(self) -> None:
        declaration = DeviceDeclaration(
            device_id="camera-001",
            device_type="camera",
            enabled=True,
            required=True,
            declared_capabilities=[],
        )
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[declaration],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        session.initialize()

        self.assertEqual(declaration.declared_capabilities, ())
        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertIn(
            "selected_devices[0].declared_capabilities_declared",
            [check.name for check in session.readiness_checks if check.status == "PASS"],
        )

    def test_missing_declared_capabilities_fails_initialization(self) -> None:
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[
                    DeviceDeclaration(
                        device_id="camera-001",
                        device_type="camera",
                        enabled=True,
                        required=True,
                        declared_capabilities=None,
                    )
                ],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        with self.assertRaises(SessionLifecycleError):
            session.initialize()

        self.assertIn(
            "selected_devices[0].declared_capabilities_declared",
            [check.name for check in session.readiness_checks if check.status == "FAIL"],
        )
        self.assertIs(session.current_state, SessionState.CREATED)

    def test_invalid_enabled_or_required_type_fails_initialization(self) -> None:
        cases = [
            (
                DeviceDeclaration(
                    device_id="camera-001",
                    device_type="camera",
                    enabled="yes",
                    required=True,
                    declared_capabilities=[],
                ),
                "selected_devices[0].enabled_is_boolean",
            ),
            (
                DeviceDeclaration(
                    device_id="camera-001",
                    device_type="camera",
                    enabled=True,
                    required="yes",
                    declared_capabilities=[],
                ),
                "selected_devices[0].required_is_boolean",
            ),
        ]

        for declaration, expected_failure in cases:
            with self.subTest(expected_failure=expected_failure):
                session = Session(
                    session_id="session-001",
                    configuration=SessionConfig(
                        selected_devices=[declaration],
                        storage_location="placeholder://session",
                        protocol_plan={"name": "no-op"},
                        error_evidence_location="placeholder://errors",
                    ),
                )

                with self.assertRaises(SessionLifecycleError):
                    session.initialize()

                self.assertIn(
                    expected_failure,
                    [
                        check.name
                        for check in session.readiness_checks
                        if check.status == "FAIL"
                    ],
                )
                self.assertIs(session.current_state, SessionState.CREATED)

    def test_new_session_starts_created(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        self.assertIs(session.current_state, SessionState.CREATED)
        self.assertEqual(session.transition_history, ())
        self.assertEqual(session.readiness_checks, ())

    def test_session_exposes_lifecycle_evidence_as_read_only_history(self) -> None:
        session = running_session()

        with self.assertRaises(AttributeError):
            session.transition_history = ()
        with self.assertRaises(AttributeError):
            session.readiness_checks = ()

    def test_invalid_transition_rejection(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        with self.assertRaises(SessionLifecycleError):
            session.start()
        self.assertEqual(session.readiness_checks, ())

    def test_initialize_fails_when_required_declarations_are_missing(self) -> None:
        cases = [
            ("", config(), "session_id_exists"),
            ("session-001", None, "configuration_exists"),
            (
                "session-001",
                SessionConfig(
                    selected_devices=None,
                    storage_location="placeholder://session",
                    protocol_plan={"name": "no-op"},
                    error_evidence_location="placeholder://errors",
                ),
                "selected_devices_declared",
            ),
            (
                "session-001",
                SessionConfig(
                    selected_devices=[],
                    storage_location=None,
                    protocol_plan={"name": "no-op"},
                    error_evidence_location="placeholder://errors",
                ),
                "storage_location_declared",
            ),
            (
                "session-001",
                SessionConfig(
                    selected_devices=[],
                    storage_location="placeholder://session",
                    protocol_plan=None,
                    error_evidence_location="placeholder://errors",
                ),
                "protocol_plan_declared",
            ),
        ]

        for session_id, session_config, missing_check in cases:
            with self.subTest(missing_check=missing_check):
                session = Session(session_id=session_id, configuration=session_config)

                with self.assertRaises(SessionLifecycleError):
                    session.initialize()

                failed_checks = [
                    check.name
                    for check in session.readiness_checks
                    if check.status == "FAIL"
                ]
                self.assertIn(missing_check, failed_checks)
                self.assertIs(session.current_state, SessionState.CREATED)

    def test_initialize_records_declaration_readiness_checks(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        session.initialize()

        checks = {
            (check.name, check.status, check.reason)
            for check in session.readiness_checks
        }

        self.assertIn(("session_id_exists", "PASS", "session_id_declared"), checks)
        self.assertIn(
            ("selected_devices_declared", "PASS", "selected_devices_declared"),
            checks,
        )

    def test_start_requires_initialized_session_without_adding_readiness_checks(
        self,
    ) -> None:
        session = Session(session_id="session-001", configuration=config())
        session.initialize()
        readiness_checks = session.readiness_checks

        session.start()

        self.assertIs(session.current_state, SessionState.RUNNING)
        self.assertEqual(session.readiness_checks, readiness_checks)

    def test_required_ready_device_allows_initialization(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        session.initialize(
            device_readiness_summary=[
                device_readiness("camera-001", required=True, ready=True)
            ]
        )

        self.assertIs(session.current_state, SessionState.INITIALIZED)

    def test_required_not_ready_device_blocks_initialization(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        with self.assertRaises(SessionLifecycleError):
            session.initialize(
                device_readiness_summary=[
                    device_readiness(
                        "camera-001",
                        required=True,
                        ready=False,
                        reason="camera warming up",
                    )
                ]
            )

        self.assertIs(session.current_state, SessionState.CREATED)
        self.assertEqual(session.device_readiness_summary[0].device_id, "camera-001")
        self.assertFalse(session.device_readiness_summary[0].ready)

    def test_optional_not_ready_device_does_not_block_initialization(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        session.initialize(
            device_readiness_summary=[
                device_readiness(
                    "auxiliary-camera-001",
                    required=False,
                    ready=False,
                    reason="optional device offline",
                )
            ]
        )

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertFalse(session.device_readiness_summary[0].ready)
        self.assertFalse(session.device_readiness_summary[0].required)

    def test_session_records_device_readiness_summary(self) -> None:
        session = Session(session_id="session-001", configuration=config())
        summary = [
            device_readiness(
                "camera-001",
                required=True,
                ready=True,
                reason="ready",
            )
        ]

        session.initialize(device_readiness_summary=summary)

        recorded = session.device_readiness_summary[0]
        self.assertEqual(recorded.device_id, "camera-001")
        self.assertTrue(recorded.required)
        self.assertTrue(recorded.ready)
        self.assertEqual(recorded.reason, "ready")
        self.assertEqual(recorded.capabilities_available, ("reports_health",))

    def test_session_initialization_uses_supplied_readiness_without_live_adapters(
        self,
    ) -> None:
        session = Session(session_id="session-001", configuration=config())

        session.initialize(
            device_readiness_summary=[
                device_readiness("camera-001", required=True, ready=True)
            ]
        )

        self.assertIs(session.current_state, SessionState.INITIALIZED)

    def test_session_initialization_does_not_call_device_adapter_methods(self) -> None:
        class FailingAdapter(DeviceAdapter):
            def check_ready(self):
                raise AssertionError("Session should not call adapter methods")

        adapter = FailingAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=[],
            required=True,
        )
        session = Session(session_id="session-001", configuration=config())

        session.initialize(
            device_readiness_summary=[
                device_readiness(adapter.device_id, required=True, ready=True)
            ]
        )

        self.assertIs(session.current_state, SessionState.INITIALIZED)

    def test_session_does_not_bind_declarations_to_readiness_records(self) -> None:
        declaration = DeviceDeclaration(
            device_id="declared-camera-001",
            device_type="camera",
            enabled=True,
            required=True,
            declared_capabilities=[],
        )
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[declaration],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
                error_evidence_location="placeholder://errors",
            ),
        )

        session.initialize(
            device_readiness_summary=[
                device_readiness("adapter-camera-001", required=True, ready=True)
            ]
        )

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertEqual(
            session.device_readiness_summary[0].device_id,
            "adapter-camera-001",
        )

    def test_device_manager_readiness_output_can_initialize_session(self) -> None:
        adapter = ReadyFakeAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=["reports_health"],
            required=True,
        )
        manager = DeviceManager(adapters=[adapter])
        manager.initialize_all(config={})
        readiness_summary = manager.check_readiness()
        session = Session(session_id="session-001", configuration=config())

        session.initialize(device_readiness_summary=readiness_summary)

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertIs(session.device_readiness_summary[0], readiness_summary.results[0])

    def test_required_not_ready_from_device_manager_blocks_initialization(self) -> None:
        adapter = DeviceAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=["reports_health"],
            required=True,
        )
        manager = DeviceManager(adapters=[adapter])
        manager.initialize_all(config={})
        readiness_summary = manager.check_readiness()
        session = Session(session_id="session-001", configuration=config())

        with self.assertRaises(SessionLifecycleError):
            session.initialize(device_readiness_summary=readiness_summary)

        self.assertIs(session.current_state, SessionState.CREATED)
        self.assertIs(session.device_readiness_summary[0], readiness_summary.results[0])

    def test_optional_not_ready_from_device_manager_does_not_block_initialization(
        self,
    ) -> None:
        adapter = DeviceAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=["reports_health"],
            required=False,
        )
        manager = DeviceManager(adapters=[adapter])
        manager.initialize_all(config={})
        readiness_summary = manager.check_readiness()
        session = Session(session_id="session-001", configuration=config())

        session.initialize(device_readiness_summary=readiness_summary)

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertFalse(session.device_readiness_summary[0].required)
        self.assertFalse(session.device_readiness_summary[0].ready)

    def test_services_report_readiness_for_session_initialization(self) -> None:
        ingestor = InMemoryIngestor()
        storage = InMemoryStorageManager()

        ingestor_readiness = ingestor.check_ready()
        storage_readiness = storage.check_ready()

        self.assertEqual(ingestor_readiness.component_id, "ingestor")
        self.assertEqual(ingestor_readiness.component_type, "ingestor")
        self.assertTrue(ingestor_readiness.required)
        self.assertTrue(ingestor_readiness.ready)
        self.assertEqual(storage_readiness.component_id, "storage")
        self.assertEqual(storage_readiness.component_type, "storage_manager")
        self.assertTrue(storage_readiness.required)
        self.assertTrue(storage_readiness.ready)

    def test_required_ready_services_allow_initialization_without_record_flow(
        self,
    ) -> None:
        ingestor = InMemoryIngestor()
        storage = InMemoryStorageManager()
        service_readiness = [ingestor.check_ready(), storage.check_ready()]
        session = Session(session_id="session-001", configuration=config())

        session.initialize(service_readiness=service_readiness)

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertEqual(session.service_readiness_checks, tuple(service_readiness))
        self.assertEqual(ingestor.accepted_envelopes, ())
        self.assertEqual(ingestor.ingest_audit, ())
        self.assertEqual(storage.stored_envelopes, ())

    def test_required_not_ready_service_blocks_initialization(self) -> None:
        session = Session(session_id="session-001", configuration=config())
        service_readiness = [
            ServiceReadiness(
                component_id="storage",
                component_type="storage_manager",
                required=True,
                ready=False,
                reason="storage unavailable",
            )
        ]

        with self.assertRaises(SessionLifecycleError):
            session.initialize(service_readiness=service_readiness)

        self.assertIs(session.current_state, SessionState.CREATED)
        self.assertEqual(session.service_readiness_checks, tuple(service_readiness))

    def test_session_uses_service_readiness_without_service_internals(self) -> None:
        session = Session(session_id="session-001", configuration=config())
        service_readiness = [
            ServiceReadiness(
                component_id="ingestor",
                component_type="ingestor",
                required=True,
                ready=True,
                reason="ready",
            ),
            ServiceReadiness(
                component_id="storage",
                component_type="storage_manager",
                required=True,
                ready=True,
                reason="ready",
            ),
        ]

        session.initialize(service_readiness=service_readiness)

        self.assertIs(session.current_state, SessionState.INITIALIZED)
        self.assertEqual(session.service_readiness_checks, tuple(service_readiness))

    def test_session_initializes_with_device_and_service_readiness_including_synchronization(
        self,
    ) -> None:
        adapter = ReadyFakeAdapter(
            device_id="camera-001",
            device_type="camera",
            declared_capabilities=["reports_health"],
            required=True,
        )
        manager = DeviceManager(adapters=[adapter])
        ingestor = InMemoryIngestor()
        storage = InMemoryStorageManager()
        synchronization = SynchronizationManager()
        manager.initialize_all(config={})
        device_readiness_summary = manager.check_readiness()
        service_readiness = [
            ingestor.check_ready(),
            storage.check_ready(),
            synchronization.check_ready(),
        ]
        session = Session(session_id="session-001", configuration=config())

        session.initialize(
            device_readiness_summary=device_readiness_summary,
            service_readiness=service_readiness,
        )
        session.start()

        self.assertIs(session.current_state, SessionState.RUNNING)
        self.assertEqual(
            session.device_readiness_summary,
            device_readiness_summary.results,
        )
        self.assertEqual(session.service_readiness_checks, tuple(service_readiness))
        synchronization_readiness = session.service_readiness_checks[2]
        self.assertEqual(synchronization_readiness.component_id, "synchronization")
        self.assertEqual(
            synchronization_readiness.component_type,
            "synchronization_manager",
        )
        self.assertTrue(synchronization_readiness.required)
        self.assertTrue(synchronization_readiness.ready)
        self.assertFalse(synchronization.is_running)

        session_time_s = synchronization.start()

        self.assertEqual(session_time_s, 0.0)
        self.assertTrue(synchronization.is_running)

    def test_required_not_ready_synchronization_blocks_initialization(self) -> None:
        session = Session(session_id="session-001", configuration=config())
        service_readiness = [
            ServiceReadiness(
                component_id="synchronization",
                component_type="synchronization_manager",
                required=True,
                ready=False,
                reason="session clock unavailable",
            )
        ]

        with self.assertRaises(SessionLifecycleError):
            session.initialize(service_readiness=service_readiness)

        self.assertIs(session.current_state, SessionState.CREATED)
        self.assertEqual(session.service_readiness_checks, tuple(service_readiness))

    def test_abort_path_records_final_state(self) -> None:
        session = running_session()

        session.stop(reason="user requested abort")
        session.abort(reason="user requested abort")

        self.assertIs(session.current_state, SessionState.ABORTED)
        self.assertIsNotNone(session.final_status)
        self.assertEqual(session.final_status["state"], "aborted")
        self.assertEqual(session.final_status["reason"], "user requested abort")
        self.assertTrue(session.final_status["cleanup_occurred"])

    def test_failure_path_records_final_state(self) -> None:
        session = running_session()

        session.stop(reason="fatal failure")
        session.fail(reason="fatal failure")

        self.assertIs(session.current_state, SessionState.FAILED)
        self.assertIsNotNone(session.final_status)
        self.assertEqual(session.final_status["state"], "failed")
        self.assertEqual(session.final_status["reason"], "fatal failure")
        self.assertTrue(session.final_status["cleanup_occurred"])

    def test_cleanup_happens_before_terminal_state(self) -> None:
        terminal_finishers = [
            (Session.complete, SessionState.COMPLETED),
            (Session.fail, SessionState.FAILED),
            (Session.abort, SessionState.ABORTED),
        ]

        for finish, terminal_state in terminal_finishers:
            with self.subTest(finish=finish.__name__):
                session = running_session()

                session.stop()
                finish(session)

                terminal_transition = session.transition_history[-1]
                self.assertIs(terminal_transition.to_state, terminal_state)
                self.assertTrue(session.cleanup_occurred)
                self.assertIsNotNone(session.cleanup_sequence)
                self.assertIsNotNone(session.final_status)
                self.assertLess(session.cleanup_sequence, session.final_status["sequence"])
                self.assertLess(session.final_status["sequence"], terminal_transition.sequence)

    def test_terminal_states_reject_future_transitions(self) -> None:
        terminal_finishers = [
            Session.complete,
            Session.fail,
            Session.abort,
        ]

        for finish in terminal_finishers:
            with self.subTest(finish=finish.__name__):
                session = running_session()
                session.stop()
                finish(session)

                lifecycle_operations = [
                    Session.initialize,
                    Session.start,
                    Session.stop,
                    Session.complete,
                    Session.fail,
                    Session.abort,
                ]
                for operation in lifecycle_operations:
                    with self.subTest(
                        finish=finish.__name__,
                        operation=operation.__name__,
                    ):
                        with self.assertRaises(SessionLifecycleError):
                            operation(session)


if __name__ == "__main__":
    unittest.main()


