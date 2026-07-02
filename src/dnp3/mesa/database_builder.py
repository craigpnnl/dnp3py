"""Build a dnp3py Database and AnalogOutputStore from a PICS profile.

Iterates the point sections in a :class:`PicsProfile` and populates a
:class:`Database` (for BI, BO, AI) and an :class:`AnalogOutputStore` (for AO).
All points are set to ONLINE quality on creation.

The load-bearing step is AI scaling: ``AiPoint.value`` is in engineering units,
but the DNP3 wire and the database carry the transmission integer. Each AI value
is scaled engineering -> transmission (with the engineering value clamped to the
point's declared range first) before it reaches ``add_analog_input``. Every AI
point across base, equipment, curves, and schedules is registered so no point is
silently dropped.

CTR database registration (counter objects) is wired in a later PR; the model
already carries the CTR points so they are not lost here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    Database,
    DatabaseConfig,
)
from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue
from dnp3.mesa.profile import AiPoint, PicsProfile, PointType
from dnp3.mesa.scaling import engineering_to_transmission

__all__ = ["build_database"]

# Headroom added to max index so DatabaseConfig limits are not too tight.
_HEADROOM = 10


class _HasIndex(Protocol):
    # Read-only so the frozen point dataclasses satisfy the protocol; a mutable
    # attribute would make the protocol invariant and reject them.
    @property
    def point_index(self) -> int: ...


_IndexedT = TypeVar("_IndexedT", bound=_HasIndex)


def _dedup_by_index(points: Iterable[_IndexedT]) -> list[_IndexedT]:
    """Keep the first point per ``point_index``, preserving order.

    Multiplexed sub-groups (curves, schedules) overlay the same DNP3 index range,
    so the same index appears more than once. A DNP3 index is one physical
    address; the first occurrence is registered and the rest are the multiplexed
    overlays handled by the selector protocol in a later PR.
    """
    seen: set[int] = set()
    out: list[_IndexedT] = []
    for point in points:
        if point.point_index not in seen:
            seen.add(point.point_index)
            out.append(point)
    return out


def _clamp_engineering(point: AiPoint) -> float:
    """Clamp an AI point's engineering value to its declared engineering range.

    The declared range is expressed in transmission integers (minimum/maximum);
    the engineering bounds are ``bound * multiplier + offset``. A negative
    multiplier flips the ordering, so the bounds are sorted before clamping.
    mesa-tool clamps the value at load; dnp3py clamps here so the stored
    transmission integer stays within the point's range.
    """
    eng_a = point.minimum * point.multiplier + point.offset
    eng_b = point.maximum * point.multiplier + point.offset
    low, high = (eng_a, eng_b) if eng_a <= eng_b else (eng_b, eng_a)
    return min(max(point.value, low), high)


def _scaled_transmission(point: AiPoint) -> int:
    """Scale an AI point's engineering value to its transmission integer."""
    engineering = _clamp_engineering(point)
    return engineering_to_transmission(engineering, point.multiplier, point.offset)


def build_database(
    profile: PicsProfile,
    excluded_indices: dict[PointType, set[int]] | None = None,
) -> tuple[Database, AnalogOutputStore]:
    """Build a dnp3py Database and AnalogOutputStore from a PICS profile.

    Binary and analog input points go into the Database; analog output points
    go into the AnalogOutputStore. AI values are scaled engineering ->
    transmission before storage.

    Args:
        profile: A fully loaded :class:`PicsProfile`.
        excluded_indices: Optional dict mapping :class:`PointType` to a set of
            point indices to skip.

    Returns:
        A ``(Database, AnalogOutputStore)`` tuple.
    """
    if excluded_indices is None:
        excluded_indices = {}

    def _is_excluded(point_type: PointType, index: int) -> bool:
        return index in excluded_indices.get(point_type, set())

    bi_points = _dedup_by_index(
        p for p in profile.bi.all_points() if not _is_excluded(PointType.BINARY_INPUT, p.point_index)
    )
    bo_points = _dedup_by_index(
        p for p in profile.bo.all_points() if not _is_excluded(PointType.BINARY_OUTPUT, p.point_index)
    )
    # Curves and schedules multiplex several logical point sets onto one DNP3
    # index range (the four curves in full.json all share indices 329+). A DNP3
    # index is a single physical address, so each unique index is registered
    # once here (the first occurrence). Which multiplexed curve/schedule a read
    # exposes is the selector protocol wired in a later PR; this cut only needs
    # every index to exist so no point is dropped. This matches mesa-tool's
    # ProfileIndex, which keys its AI map by point index.
    ai_points = _dedup_by_index(
        p for p in profile.ai.all_points_full() if not _is_excluded(PointType.ANALOG_INPUT, p.point_index)
    )
    ao_points = _dedup_by_index(
        p for p in profile.ao.all_points() if not _is_excluded(PointType.ANALOG_OUTPUT, p.point_index)
    )

    config = DatabaseConfig(
        max_binary_inputs=len(bi_points) + _HEADROOM,
        max_binary_outputs=len(bo_points) + _HEADROOM,
        max_analog_inputs=len(ai_points) + _HEADROOM,
    )
    database = Database(config=config)

    # --- Binary Inputs --------------------------------------------------
    # PicsProfile BI points carry no runtime value; they start de-asserted.
    for bi in bi_points:
        database.add_binary_input(
            index=bi.point_index,
            config=BinaryInputConfig(),
            value=False,
            quality=BinaryQuality.ONLINE,
        )

    # --- Binary Outputs -------------------------------------------------
    for bo in bo_points:
        database.add_binary_output(
            index=bo.point_index,
            config=BinaryOutputConfig(),
            value=False,
            quality=BinaryQuality.ONLINE,
        )

    # --- Analog Inputs (engineering -> transmission integer) -----------
    for ai in ai_points:
        database.add_analog_input(
            index=ai.point_index,
            config=AnalogInputConfig(deadband=0.0),
            value=_scaled_transmission(ai),
            quality=AnalogQuality.ONLINE,
        )

    # --- Analog Outputs (into store, not database) ----------------------
    # AO points carry no runtime value in PicsProfile; the store's initial
    # transmission value is the point's minimum, a guaranteed in-range integer.
    ao_store = AnalogOutputStore()
    for ao in ao_points:
        ao_store.add(
            AnalogOutputValue(
                index=ao.point_index,
                value=float(ao.minimum),
                minimum=float(ao.minimum),
                maximum=float(ao.maximum),
                multiplier=ao.multiplier,
                offset=ao.offset,
                units=ao.units,
                description=ao.name,
            ),
        )

    return database, ao_store
