"""MESA Analog Output store for DNP3 point management."""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["AnalogOutputStore", "AnalogOutputValue"]


@dataclass(frozen=True)
class AnalogOutputValue:
    """Immutable representation of a MESA analog output point."""

    index: int
    value: float
    minimum: float
    maximum: float
    multiplier: float = 1.0
    offset: float = 0.0
    units: str = ""
    description: str = ""


class AnalogOutputStore:
    """In-memory store for MESA analog output values, keyed by point index."""

    def __init__(self) -> None:
        self._store: dict[int, AnalogOutputValue] = {}

    def add(self, ao: AnalogOutputValue) -> None:
        """Add an analog output value. Raises ValueError if index already exists."""
        if ao.index in self._store:
            raise ValueError(f"Index {ao.index} already exists in store")
        self._store[ao.index] = ao

    def get(self, index: int) -> AnalogOutputValue | None:
        """Return the value at *index*, or ``None`` if not found."""
        return self._store.get(index)

    def set_value(self, index: int, value: float) -> AnalogOutputValue:
        """Set a new value for the point at *index*.

        Returns a new ``AnalogOutputValue`` with the updated value.
        Raises ``KeyError`` if the index is not found.
        Raises ``ValueError`` if *value* is outside [minimum, maximum].
        """
        ao = self._store.get(index)
        if ao is None:
            raise KeyError(index)
        if value < ao.minimum or value > ao.maximum:
            raise ValueError(f"Value {value} is outside [{ao.minimum}, {ao.maximum}]")
        updated = replace(ao, value=value)
        self._store[index] = updated
        return updated

    def get_all(self) -> list[AnalogOutputValue]:
        """Return all values sorted by index."""
        return sorted(self._store.values(), key=lambda ao: ao.index)

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, index: int) -> bool:
        return index in self._store
