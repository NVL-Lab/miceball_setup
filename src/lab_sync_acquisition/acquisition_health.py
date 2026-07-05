"""Plain-data acquisition-health policy definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


_EVALUATION_FIELDS = (
    "first_record_grace_window_s",
    "max_gap_s",
    "minimum_rate_hz",
)
_CONSEQUENCE_LABELS = {
    "informational",
    "warning",
    "recoverable_failure",
    "experiment_failure",
    "session_failure",
}


@dataclass(frozen=True)
class AcquisitionHealthPolicy:
    """Plain-data health evaluation and interpretation definition."""

    policy_id: str
    evaluation: Mapping[str, float | None]
    interpretation: Mapping[str, str]

    def __post_init__(self) -> None:
        missing_fields = [
            field_name
            for field_name in _EVALUATION_FIELDS
            if field_name not in self.evaluation
        ]
        if missing_fields:
            raise ValueError(
                "AcquisitionHealthPolicy evaluation is missing fields: "
                + ", ".join(missing_fields)
            )

        unsupported_labels = sorted(
            {
                label
                for label in self.interpretation.values()
                if label not in _CONSEQUENCE_LABELS
            }
        )
        if unsupported_labels:
            raise ValueError(
                "Unsupported acquisition-health consequence labels: "
                + ", ".join(unsupported_labels)
            )

        object.__setattr__(
            self,
            "evaluation",
            MappingProxyType(
                {
                    field_name: self.evaluation[field_name]
                    for field_name in _EVALUATION_FIELDS
                }
            ),
        )
        object.__setattr__(
            self,
            "interpretation",
            MappingProxyType(dict(self.interpretation)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "policy_id": self.policy_id,
            "evaluation": {
                field_name: self.evaluation[field_name]
                for field_name in _EVALUATION_FIELDS
            },
            "interpretation": dict(self.interpretation),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcquisitionHealthPolicy:
        """Reconstruct a policy from plain data."""

        evaluation = data["evaluation"]
        return cls(
            policy_id=data["policy_id"],
            evaluation={
                field_name: evaluation[field_name]
                for field_name in _EVALUATION_FIELDS
            },
            interpretation=dict(data["interpretation"]),
        )

    def validate_supported_observations(
        self,
        supported_observations: Iterable[str],
    ) -> None:
        """Reject interpretation keys unsupported by a supplied evaluator."""

        supported = set(supported_observations)
        unsupported = sorted(set(self.interpretation) - supported)
        if unsupported:
            raise ValueError(
                "AcquisitionHealthPolicy references unsupported observations: "
                + ", ".join(unsupported)
            )
