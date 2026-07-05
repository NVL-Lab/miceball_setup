"""Plain-data Experiment runtime declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExperimentRuntimeHealthMapping:
    """Explicit health assignment for one live source in an Experiment."""

    live_source_id: str
    expected_participant_id: str
    acquisition_health_policy: str
    required: bool
    expected_contribution: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "live_source_id": self.live_source_id,
            "expected_participant_id": self.expected_participant_id,
            "acquisition_health_policy": self.acquisition_health_policy,
            "required": self.required,
            "expected_contribution": self.expected_contribution,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRuntimeHealthMapping:
        """Reconstruct a mapping entry from plain data."""

        return cls(
            live_source_id=data["live_source_id"],
            expected_participant_id=data["expected_participant_id"],
            acquisition_health_policy=data["acquisition_health_policy"],
            required=data["required"],
            expected_contribution=data["expected_contribution"],
        )


@dataclass(frozen=True)
class ExperimentScopedHealthObservation:
    """Plain-data acquisition-health condition observed during an Experiment."""

    experiment_id: str
    live_source_id: str
    expected_participant_id: str
    expected_contribution: str
    acquisition_health_policy: str
    observation_type: str
    required: bool
    session_time_s: float | None
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "experiment_id": self.experiment_id,
            "live_source_id": self.live_source_id,
            "expected_participant_id": self.expected_participant_id,
            "expected_contribution": self.expected_contribution,
            "acquisition_health_policy": self.acquisition_health_policy,
            "observation_type": self.observation_type,
            "required": self.required,
            "session_time_s": self.session_time_s,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentScopedHealthObservation:
        """Reconstruct an observation from plain data."""

        return cls(
            experiment_id=data["experiment_id"],
            live_source_id=data["live_source_id"],
            expected_participant_id=data["expected_participant_id"],
            expected_contribution=data["expected_contribution"],
            acquisition_health_policy=data["acquisition_health_policy"],
            observation_type=data["observation_type"],
            required=data["required"],
            session_time_s=data["session_time_s"],
            details=dict(data["details"]),
        )
