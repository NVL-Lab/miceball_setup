"""Device declaration records used by session configuration."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
from math import ceil, isfinite
from typing import Any, Iterable


@dataclass(frozen=True)
class ScientificProductDeclaration:
    """Available scientific product and its declared persistence requirements."""

    data_product_id: str
    product_type: str
    schema: dict[str, Any]
    storage_format: str
    expected_data_size_bytes: int | None = None
    expected_acquisition_rate_hz: float | None = None
    storage_requirements: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        for name in ("data_product_id", "product_type", "storage_format"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.schema, dict):
            raise TypeError("schema must be a plain-data dictionary")
        if self.storage_requirements is not None and not isinstance(
            self.storage_requirements, dict
        ):
            raise TypeError("storage_requirements must be a plain-data dictionary")
        if self.expected_data_size_bytes is not None and (
            type(self.expected_data_size_bytes) is not int
            or self.expected_data_size_bytes < 0
        ):
            raise ValueError("expected_data_size_bytes must be a nonnegative integer")
        if self.expected_acquisition_rate_hz is not None and (
            type(self.expected_acquisition_rate_hz) not in (int, float)
            or self.expected_acquisition_rate_hz < 0
        ):
            raise ValueError("expected_acquisition_rate_hz must be nonnegative")
        json.dumps(self.to_dict(), allow_nan=False)
        object.__setattr__(self, "schema", deepcopy(self.schema))
        object.__setattr__(self, "storage_requirements", deepcopy(self.storage_requirements))

    def to_dict(self) -> dict[str, Any]:
        """Return the complete plain-data declaration without invented estimates."""
        return {
            "data_product_id": self.data_product_id,
            "product_type": self.product_type,
            "schema": deepcopy(self.schema),
            "storage_format": self.storage_format,
            "expected_data_size_bytes": self.expected_data_size_bytes,
            "expected_acquisition_rate_hz": self.expected_acquisition_rate_hz,
            "storage_requirements": deepcopy(self.storage_requirements),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScientificProductDeclaration:
        """Reconstruct a scientific product declaration from plain data."""
        return cls(**data)

    def estimate_storage_bytes(self, duration_s: float, parameters: dict[str, Any]) -> int:
        """Use explicitly declared encoded-size bounds, never legacy expected-size guesses."""
        bounds = (self.storage_requirements or {}).get("capacity_estimate")
        if not isinstance(bounds, dict):
            raise ValueError("An explicit recording budget or declared capacity_estimate is required")
        fixed = bounds.get("fixed_bytes")
        per_observation = bounds.get("bytes_per_observation")
        rate = parameters.get("fps")
        batch = parameters.get("frames_per_collect")
        if (type(fixed) is not int or fixed < 0 or type(per_observation) is not int or per_observation <= 0
                or type(rate) not in (int, float) or not isfinite(rate) or rate <= 0
                or type(batch) is not int or batch < 1):
            raise ValueError("Complete encoded-size bounds and selected rate/batch are required")
        if self.storage_format != "hdf5" or self.product_type != "camera_frames":
            raise ValueError("This product requires an explicit recording byte budget")
        import numpy as np
        shape = self.schema.get("frame_shape")
        if (not isinstance(shape, list) or len(shape) not in (2, 3)
                or any(type(n) is not int or n <= 0 for n in shape)):
            raise ValueError("Explicit stored frame dimensions are required")
        dtype = np.dtype(self.schema["frame_dtype"])
        raw = int(np.prod(shape)) * dtype.itemsize
        if dtype.hasobject or per_observation < raw:
            raise ValueError("Declared encoded-size bound cannot be smaller than the raw frame")
        if (parameters.get("frame_width") not in (None, shape[1])
                or parameters.get("frame_height") not in (None, shape[0])):
            raise ValueError("Selected resolution differs from the declared stored representation")
        # Include the bounded collection already in flight when the deadline arrives.
        return fixed + (ceil(duration_s * rate) + batch) * per_observation


@dataclass(frozen=True)
class DeviceDeclaration:
    """Persistent configuration declaration for an intended session device."""

    device_id: str | None
    device_type: str | None
    enabled: bool
    required: bool
    declared_capabilities: tuple[str, ...] | None
    scientific_products: tuple[ScientificProductDeclaration, ...] = ()

    def __init__(
        self,
        device_id: str | None,
        device_type: str | None,
        enabled: bool,
        required: bool,
        declared_capabilities: Iterable[str] | None,
        scientific_products: Iterable[ScientificProductDeclaration] = (),
    ) -> None:
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "device_type", device_type)
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "required", required)
        if declared_capabilities is None:
            capabilities = None
        else:
            capabilities = tuple(declared_capabilities)
        object.__setattr__(self, "declared_capabilities", capabilities)
        products = tuple(scientific_products)
        if any(not isinstance(product, ScientificProductDeclaration) for product in products):
            raise TypeError("scientific_products must contain ScientificProductDeclaration objects")
        if len({product.data_product_id for product in products}) != len(products):
            raise ValueError("Duplicate scientific product identity within device declaration")
        object.__setattr__(self, "scientific_products", products)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-like plain-data representation."""

        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "enabled": self.enabled,
            "required": self.required,
            "scientific_products": [product.to_dict() for product in self.scientific_products],
            "declared_capabilities": (
                list(self.declared_capabilities)
                if self.declared_capabilities is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceDeclaration:
        """Reconstruct a device declaration, including any declared products."""
        return cls(
            device_id=data["device_id"],
            device_type=data["device_type"],
            enabled=data["enabled"],
            required=data["required"],
            declared_capabilities=data["declared_capabilities"],
            scientific_products=tuple(
                ScientificProductDeclaration.from_dict(product)
                for product in data.get("scientific_products", ())
            ),
        )
