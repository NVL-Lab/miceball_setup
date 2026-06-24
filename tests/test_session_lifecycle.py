import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from lab_sync_acquisition import (
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
        self.assertEqual(
            session.final_status,
            {
                "state": "completed",
                "reason": "normal completion",
                "cleanup_occurred": True,
            },
        )

    def test_invalid_transition_rejection(self) -> None:
        session = Session(session_id="session-001", configuration=config())

        with self.assertRaises(SessionLifecycleError):
            session.start()
        self.assertEqual(session.readiness_checks, [])

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
        self.assertEqual(
            session.final_status,
            {
                "state": "aborted",
                "reason": "user requested abort",
                "cleanup_occurred": True,
            },
        )

    def test_failure_path_records_final_state(self) -> None:
        session = running_session()

        session.stop(reason="fatal failure")
        session.fail(reason="fatal failure")

        self.assertIs(session.current_state, SessionState.FAILED)
        self.assertEqual(
            session.final_status,
            {
                "state": "failed",
                "reason": "fatal failure",
                "cleanup_occurred": True,
            },
        )

    def test_cleanup_happens_before_terminal_state(self) -> None:
        session = running_session()

        session.stop()
        session.complete()

        terminal_transition = session.transition_history[-1]
        self.assertTrue(session.cleanup_occurred)
        self.assertIsNotNone(session.cleanup_sequence)
        self.assertLess(session.cleanup_sequence, terminal_transition.sequence)

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

                with self.assertRaises(SessionLifecycleError):
                    session.stop()


if __name__ == "__main__":
    unittest.main()
