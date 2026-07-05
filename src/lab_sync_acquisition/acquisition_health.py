"""Plain-data acquisition-health policy definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


_CONSEQUENCE_LABELS = {
    "informational",
    "warning",
    "recoverable_failure",
    "experiment_failure",
    "session_failure",
}


@dataclass(frozen=True)
class HealthInterpretationEvidence:
    """Plain-data policy interpretation of one health observation."""

    originating_observation_id: str
    experiment_id: str
    live_source_id: str
    expected_participant_id: str
    observation_type: str
    acquisition_health_policy: str
    interpretation_label: str
    required: bool
    session_time_s: float | None
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            self.interpretation_label not in _CONSEQUENCE_LABELS
            and self.interpretation_label != "uninterpreted"
        ):
            raise ValueError(
                "Unsupported acquisition-health interpretation label: "
                + self.interpretation_label
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "originating_observation_id": self.originating_observation_id,
            "experiment_id": self.experiment_id,
            "live_source_id": self.live_source_id,
            "expected_participant_id": self.expected_participant_id,
            "observation_type": self.observation_type,
            "acquisition_health_policy": self.acquisition_health_policy,
            "interpretation_label": self.interpretation_label,
            "required": self.required,
            "session_time_s": self.session_time_s,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthInterpretationEvidence:
        """Reconstruct interpretation evidence from plain data."""

        return cls(
            originating_observation_id=data["originating_observation_id"],
            experiment_id=data["experiment_id"],
            live_source_id=data["live_source_id"],
            expected_participant_id=data["expected_participant_id"],
            observation_type=data["observation_type"],
            acquisition_health_policy=data["acquisition_health_policy"],
            interpretation_label=data["interpretation_label"],
            required=data["required"],
            session_time_s=data["session_time_s"],
            details=dict(data["details"]),
        )


@dataclass(frozen=True)
class AcquisitionHealthPolicy:
    """Plain-data health evaluation and interpretation definition."""

    policy_id: str
    evaluation_rules: Mapping[str, Mapping[str, Any]]
    interpretation: Mapping[str, str]

    def __post_init__(self) -> None:
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
            "evaluation_rules",
            MappingProxyType(
                {
                    rule_name: MappingProxyType(dict(parameters))
                    for rule_name, parameters in self.evaluation_rules.items()
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
            "evaluation_rules": {
                rule_name: dict(parameters)
                for rule_name, parameters in self.evaluation_rules.items()
            },
            "interpretation": dict(self.interpretation),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcquisitionHealthPolicy:
        """Reconstruct a policy from plain data."""

        return cls(
            policy_id=data["policy_id"],
            evaluation_rules={
                rule_name: dict(parameters)
                for rule_name, parameters in data["evaluation_rules"].items()
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
