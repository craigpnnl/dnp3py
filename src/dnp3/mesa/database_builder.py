"""Build a dnp3py Database and AnalogOutputStore from a PICS profile.

Iterates the point sections in a :class:`PicsProfile` and populates a
:class:`Database` (for BI, BO, AI, CTR) and an :class:`AnalogOutputStore`
(for AO). All points are set to ONLINE quality on creation.

The load-bearing step is AI scaling: ``AiPoint.value`` is in engineering units,
but the DNP3 wire and the database carry the transmission integer. Each AI value
is scaled engineering -> transmission (with the engineering value clamped to the
point's declared range first) before it reaches ``add_analog_input``. Every AI
point across base, equipment, curves, and schedules is registered so no point is
silently dropped.

CTR wiring: every :class:`CtrPoint` in :attr:`PicsProfile.ctr` is registered as
a 32-bit running counter (group 20, variation 1) via ``add_counter``. When
``frozen_counter_exists`` is true, an additional 32-bit frozen counter (group 21,
variation 1) is registered at the same index via ``add_frozen_counter``. Counter
values are unsigned 32-bit integers; DER energy counters (Wh/VAh) overflow 16
bits so the 32-bit variants are required (Vance domain guidance). Initial counter
value is 0 (PicsProfile carries no initial counter reading). Event class is
derived from the point's ``counter_event_class`` / ``frozen_counter_event_class``
string via :meth:`~dnp3.mesa.profile.EventClass.to_dnp3_class`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    CounterConfig,
    Database,
    DatabaseConfig,
)
from dnp3.database import (
    EventClass as DbEventClass,
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


def _assert_unique_by_index(points: Iterable[_IndexedT], label: str) -> list[_IndexedT]:
    """Collect *points* into a list, raising if any index appears more than once.

    For BI/BO/AO sections, every point should have a unique DNP3 index. A
    duplicate means the profile is internally inconsistent, not a known
    multiplexing pattern; raise rather than silently shadow.
    """
    seen: dict[int, int] = {}  # index -> position
    out: list[_IndexedT] = []
    for pos, point in enumerate(points):
        idx = point.point_index
        if idx in seen:
            msg = (
                f"{label}: duplicate point_index {idx} at positions "
                f"{seen[idx]} and {pos}; expected unique indices for this section"
            )
            raise ValueError(msg)
        seen[idx] = pos
        out.append(point)
    return out


def _dedup_ai_points(
    base_points: Iterable[AiPoint],
    overlay_points: Iterable[AiPoint],
) -> list[AiPoint]:
    """Merge base+equipment and curve/schedule AI points, deduplicating by index.

    Base points take priority. Within each pool, a duplicate index is handled
    as follows: base-pool duplicates raise via _assert_unique_by_index (a base
    profile collision is a hard consistency error). Overlay-pool duplicates are
    silently collapsed by keeping the first occurrence (first-wins), because the
    curve/schedule multiplexing intentionally maps multiple logical sets onto the
    same index range (for example, the four curves in full.json all share indices
    329+). Across pools, a base index always wins over an overlay index.
    """
    base_list = _assert_unique_by_index(base_points, label="AI base+equipment")

    # Overlay pool: allow cross-sub-group index overlap (multiplexing); raise on
    # same-sub-group duplicates. Collect all overlay points, deduplicate by
    # keeping first occurrence (mirrors mesa-tool ProfileIndex semantics).
    overlay_seen: set[int] = set()
    overlay_out: list[AiPoint] = []
    for point in overlay_points:
        if point.point_index not in overlay_seen:
            overlay_seen.add(point.point_index)
            overlay_out.append(point)

    # Merge: base indices win over overlay.
    base_seen = {p.point_index for p in base_list}
    result = list(base_list)
    for point in overlay_out:
        if point.point_index not in base_seen:
            result.append(point)
    return result


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

    bi_points = _assert_unique_by_index(
        (p for p in profile.bi.all_points() if not _is_excluded(PointType.BINARY_INPUT, p.point_index)),
        label="BI",
    )
    bo_points = _assert_unique_by_index(
        (p for p in profile.bo.all_points() if not _is_excluded(PointType.BINARY_OUTPUT, p.point_index)),
        label="BO",
    )
    ao_points = _assert_unique_by_index(
        (p for p in profile.ao.all_points() if not _is_excluded(PointType.ANALOG_OUTPUT, p.point_index)),
        label="AO",
    )
    # Curves and schedules multiplex several logical point sets onto one DNP3
    # index range (the four curves in full.json all share indices 329+). A DNP3
    # index is a single physical address, so each unique index is registered
    # once here (base wins; else first overlay). Which multiplexed curve/schedule
    # a read exposes is the selector protocol wired in a later PR. A collision
    # within the base+equipment pool is unexpected and raises with context.
    ai_points = _dedup_ai_points(
        base_points=(p for p in profile.ai.base_points() if not _is_excluded(PointType.ANALOG_INPUT, p.point_index)),
        overlay_points=(
            p
            for curve_points in (
                [ai for curve in profile.ai.curves for ai in curve.iter_points()],
                [ai for sched in profile.ai.schedules_bc for ai in sched.iter_points()],
                [ai for sched in profile.ai.schedules for ai in sched.iter_points()],
            )
            for p in curve_points
            if not _is_excluded(PointType.ANALOG_INPUT, p.point_index)
        ),
    )

    # CTR: collect all counter points from the profile. The excluded_indices
    # mechanism is available for COUNTER type if needed in a later PR (CLI
    # entity overrides); for now no CTR exclusions are applied.
    ctr_points = _assert_unique_by_index(profile.ctr, label="CTR")
    frozen_ctr_count = sum(1 for p in ctr_points if p.frozen_counter_exists)

    config = DatabaseConfig(
        max_binary_inputs=len(bi_points) + _HEADROOM,
        max_binary_outputs=len(bo_points) + _HEADROOM,
        max_analog_inputs=len(ai_points) + _HEADROOM,
        max_counters=len(ctr_points) + _HEADROOM,
        # max_frozen_counters is intentionally smaller than max_counters: only
        # CtrPoints with frozen_counter_exists=True register a frozen counter,
        # so the ceiling is the frozen subset, not all CTR points.
        max_frozen_counters=frozen_ctr_count + _HEADROOM,
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

    # --- Counters (32-bit running counter, group 20 variation 1) ----------
    # PicsProfile CTR points carry no initial value; counters start at 0.
    # Vance: use 32-bit variants only (DER energy Wh/VAh overflow 16 bits).
    # event_class is derived from the profile EventClass enum via to_dnp3_class,
    # which maps Class1 -> 1, Class2 -> 2, Class3 -> 3, None -> 0, matching the
    # database EventClass IntEnum (NONE=0, CLASS_1=1, CLASS_2=2, CLASS_3=3).
    for ctr in ctr_points:
        counter_event_class = DbEventClass(ctr.counter_event_class.to_dnp3_class())
        database.add_counter(
            index=ctr.point_index,
            config=CounterConfig(event_class=counter_event_class),
            value=0,
            quality=CounterQuality.ONLINE,
        )
        # frozen_counter_event_class is always present in the JSON schema but is
        # only meaningful when frozen_counter_exists is True. Guard explicitly so
        # a profile that sets frozen_counter_exists=False with a non-None event
        # class does not silently register an unwanted frozen counter.
        if ctr.frozen_counter_exists:
            frozen_event_class = DbEventClass(ctr.frozen_counter_event_class.to_dnp3_class())
            database.add_frozen_counter(
                index=ctr.point_index,
                config=CounterConfig(event_class=frozen_event_class),
                value=0,
                quality=CounterQuality.ONLINE,
            )

    return database, ao_store
