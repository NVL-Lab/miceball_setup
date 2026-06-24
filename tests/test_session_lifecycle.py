import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
    DeviceDeclaration,
    Session,
    SessionConfig,
    SessionLifecycleError,
    SessionState,
)


def config() -> SessionConfig:
    return SessionConfig(
        selected_devices=[],
        storage_location="placeholder://session",
        protocol_plan={"name": "no-op"},
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

    def test_valid_device_declaration_passes_initialization(self) -> None:
        declaration = device_declaration()
        session = Session(
            session_id="session-001",
            configuration=SessionConfig(
                selected_devices=[declaration],
                storage_location="placeholder://session",
                protocol_plan={"name": "no-op"},
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

    def test_new_session_always_starts_created(self) -> None:
        with self.assertRaises(TypeError):
            Session(
                session_id="session-001",
                configuration=config(),
                current_state=SessionState.RUNNING,
            )

        session = Session(session_id="session-001", configuration=config())
        self.assertIs(session.current_state, SessionState.CREATED)

    def test_lifecycle_histories_are_session_owned(self) -> None:
        with self.assertRaises(TypeError):
            Session(
                session_id="session-001",
                configuration=config(),
                transition_history=[],
            )

        with self.assertRaises(TypeError):
            Session(
                session_id="session-001",
                configuration=config(),
                readiness_checks=[],
            )

        session = running_session()
        with self.assertRaises(AttributeError):
            session.transition_history = ()
        with self.assertRaises(AttributeError):
            session.readiness_checks = ()
        with self.assertRaises(AttributeError):
            session.transition_history.append

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
                ),
                "selected_devices_declared",
            ),
            (
                "session-001",
                SessionConfig(
                    selected_devices=[],
                    storage_location=None,
                    protocol_plan={"name": "no-op"},
                ),
                "storage_location_declared",
            ),
            (
                "session-001",
                SessionConfig(
                    selected_devices=[],
                    storage_location="placeholder://session",
                    protocol_plan=None,
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

    def test_readiness_checks_are_recorded(self) -> None:
        session = running_session()

        checks = {
            (check.name, check.status, check.reason)
            for check in session.readiness_checks
        }

        self.assertIn(("session_id_exists", "PASS", "session_id_declared"), checks)
        self.assertIn(
            ("selected_devices_declared", "PASS", "selected_devices_declared"),
            checks,
        )
        self.assertIn(
            ("devices_required", "PASS", "out_of_scope_for_this_slice"),
            checks,
        )
        self.assertIn(
            ("ingestor_required", "PASS", "out_of_scope_for_this_slice"),
            checks,
        )
        self.assertIn(
            ("storage_required", "PASS", "out_of_scope_for_this_slice"),
            checks,
        )
        self.assertIn(
            ("synchronization_required", "PASS", "out_of_scope_for_this_slice"),
            checks,
        )
        self.assertIn(
            (
                "session_start_event_required",
                "PASS",
                "out_of_scope_for_this_slice",
            ),
            checks,
        )

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
