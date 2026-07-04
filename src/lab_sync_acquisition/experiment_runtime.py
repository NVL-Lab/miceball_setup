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
