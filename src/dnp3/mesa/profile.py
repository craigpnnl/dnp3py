"""MESA PICS profile model and loader.

dnp3py consumes mesa-tool's ``PicsProfile`` format natively (the serde structs
in ``backend/src/common/src/profile/profile.rs``). This module is the Python
twin of those structs: per-type frozen dataclasses (:class:`BoPoint`,
:class:`BiPoint`, :class:`AoPoint`, :class:`AiPoint`, :class:`CtrPoint`), the
functional/equipment sub-groups, and a hand-rolled boundary-validating loader.

Two invariants are load-bearing and enforced here:

- ``iec_61850_uid`` is stored verbatim. It already contains underscores inside
  dotted segments; no consumer parses it structurally, so any normalization
  would invent a transform that drifts from mesa-tool.
- No profile point is silently dropped, and no required field is silently
  defaulted. A missing required field, an unknown ``event_class`` string, or a
  zero multiplier raises with context rather than falling through.

Scaling of an ``AiPoint.value`` (engineering) to the transmission integer stored
in the DNP3 database is applied by :mod:`dnp3.mesa.database_builder`, not here:
the model stays a faithful twin of the JSON so a reviewer can diff the two.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypeVar

__all__ = [
    "AiCurve",
    "AiPoint",
    "AiSchedule",
    "AiScheduleBC",
    "AnalogInputs",
    "AnalogOutputs",
    "AoPoint",
    "BiPoint",
    "BinaryInputs",
    "BinaryOutputs",
    "BoPoint",
    "CtrPoint",
    "EquipmentGroup",
    "EventClass",
    "KeySheet",
    "PicsProfile",
    "PointType",
    "load_profile",
    "parse_assoc_index",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PointType(Enum):
    """DNP3 point type prefixes used in PICS profiles."""

    BINARY_OUTPUT = "BO"
    BINARY_INPUT = "BI"
    ANALOG_OUTPUT = "AO"
    ANALOG_INPUT = "AI"
    COUNTER = "CTR"


class EventClass(Enum):
    """DNP3 event class assignment for a point.

    Serialized in the profile as the exact strings ``"Class1"``, ``"Class2"``,
    ``"Class3"``, ``"None"``. :meth:`to_dnp3_class` maps to the DNP3 integer
    class used at database registration (Class1 -> 1, Class2 -> 2, Class3 -> 3,
    None -> 0).
    """

    CLASS1 = "Class1"
    CLASS2 = "Class2"
    CLASS3 = "Class3"
    NONE = "None"

    @classmethod
    def from_profile_string(cls, value: str) -> EventClass:
        """Parse a profile ``event_class`` string. Loud on an unknown value.

        Raises:
            ValueError: If *value* is not one of the four recognized strings.
        """
        try:
            return cls(value)
        except ValueError:
            msg = f"Unknown event_class {value!r} (expected Class1, Class2, Class3, or None)"
            raise ValueError(msg) from None

    def to_dnp3_class(self) -> int:
        """Map to the DNP3 integer event class (Class1 -> 1, ..., None -> 0)."""
        return _EVENT_CLASS_TO_INT[self]


_EVENT_CLASS_TO_INT: dict[EventClass, int] = {
    EventClass.CLASS1: 1,
    EventClass.CLASS2: 2,
    EventClass.CLASS3: 3,
    EventClass.NONE: 0,
}


# ---------------------------------------------------------------------------
# assoc index parsing ("AI29" -> 29, "BI11" -> 11)
# ---------------------------------------------------------------------------

_ASSOC_RE = re.compile(r"^(BO|BI|AO|AI|CTR)(\d+)$")


def parse_assoc_index(assoc: str) -> tuple[PointType, int]:
    """Parse an association string like ``"AI29"`` into ``(PointType, 29)``.

    Raises:
        ValueError: If *assoc* does not match the expected ``<PREFIX><N>`` form.
    """
    m = _ASSOC_RE.match(assoc)
    if m is None:
        msg = f"Invalid association index {assoc!r}"
        raise ValueError(msg)
    return PointType(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------------------
# Point dataclasses (mirror the PicsProfile serde structs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoPoint:
    """A binary output point."""

    point_index: int
    name: str
    state_0: str
    state_1: str
    iec_61850_uid: str
    purpose: str
    mandatory_1815: bool
    mandatory_1547: bool
    assoc_bi: str | None = None


@dataclass(frozen=True)
class BiPoint:
    """A binary input point."""

    point_index: int
    name: str
    event_class: EventClass
    state_0: str
    state_1: str
    iec_61850_uid: str
    purpose: str
    mandatory_1815: bool
    mandatory_1547: bool
    assoc_bo: str | None = None


@dataclass(frozen=True)
class AoPoint:
    """An analog output point.

    ``minimum`` / ``maximum`` are transmission integers; ``multiplier`` /
    ``offset`` are the affine-map metadata (never transmitted). A zero
    multiplier is rejected at load, matching mesa-tool's ``AoPointRaw`` guard.
    """

    point_index: int
    name: str
    minimum: int
    maximum: int
    multiplier: float
    offset: float
    units: str
    iec_61850_uid: str
    purpose: str
    mandatory_1815: bool
    mandatory_1547: bool
    assoc_ai: str | None = None


@dataclass(frozen=True)
class AiPoint:
    """An analog input point.

    ``value`` is in engineering units, as loaded from the profile. The database
    builder scales it to a transmission integer before storing it. ``minimum`` /
    ``maximum`` are transmission integers; ``multiplier`` / ``offset`` are the
    affine-map metadata. A zero multiplier is rejected at load.
    """

    point_index: int
    name: str
    event_class: EventClass
    minimum: int
    maximum: int
    multiplier: float
    offset: float
    units: str
    iec_61850_uid: str
    value: float
    purpose: str
    mandatory_1815: bool
    mandatory_1547: bool
    assoc_ao: str | None = None


@dataclass(frozen=True)
class CtrPoint:
    """A counter point."""

    point_index: int
    name: str
    counter_event_class: EventClass
    frozen_counter_exists: bool
    frozen_counter_event_class: EventClass
    iec_61850_uid: str
    purpose: str
    mandatory_1815: bool
    mandatory_1547: bool


# ---------------------------------------------------------------------------
# Functional and equipment sub-groups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentGroup:
    """One equipment instance (a meter, DER, inverter, or battery).

    mesa-tool models each instance as a named-field struct; dnp3py preserves the
    instance's points as an ordered tuple matching the struct's ``iter_points()``
    output (JSON key order). This flattens for the DNP3 database and drops no
    point, without transcribing every named field. ``kind`` is the top-level
    group name (``"meters"``, ``"ders"``, ``"inverters"``, ``"batteries"``).
    """

    kind: str
    points: tuple[BiPoint | AoPoint | AiPoint, ...]


@dataclass(frozen=True)
class AiCurve:
    """A curve functional group.

    ``header`` holds the per-curve metadata AI points (curve_type,
    number_of_points, x_units, y_units in JSON order); ``x_values`` /
    ``y_values`` are the parallel-indexed point arrays. The curve-edit selector
    lives in the base AO array, not here.
    """

    header: tuple[AiPoint, ...]
    x_values: tuple[AiPoint, ...]
    y_values: tuple[AiPoint, ...]

    def iter_points(self) -> Iterator[AiPoint]:
        """Yield every AI point in the curve (header then x then y)."""
        yield from self.header
        yield from self.x_values
        yield from self.y_values


@dataclass(frozen=True)
class AiScheduleBC:
    """A backward-compatible schedule functional group.

    ``header`` holds the per-schedule metadata AI points in JSON order; ``arrays``
    are the parallel-indexed point arrays.
    """

    header: tuple[AiPoint, ...]
    arrays: tuple[tuple[AiPoint, ...], ...]

    def iter_points(self) -> Iterator[AiPoint]:
        """Yield every AI point in the schedule (header then each array)."""
        yield from self.header
        for arr in self.arrays:
            yield from arr


@dataclass(frozen=True)
class AiSchedule:
    """An IEEE 1815.2 schedule functional group.

    ``header`` holds the per-schedule metadata AI points in JSON order; ``arrays``
    are the parallel-indexed point arrays.
    """

    header: tuple[AiPoint, ...]
    arrays: tuple[tuple[AiPoint, ...], ...]

    def iter_points(self) -> Iterator[AiPoint]:
        """Yield every AI point in the schedule (header then each array)."""
        yield from self.header
        for arr in self.arrays:
            yield from arr


# ---------------------------------------------------------------------------
# Section containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryOutputs:
    """All binary output points."""

    points: tuple[BoPoint, ...] = ()

    def all_points(self) -> list[BoPoint]:
        """Base BO points. BO has no equipment sub-groups."""
        return list(self.points)


@dataclass(frozen=True)
class BinaryInputs:
    """Binary input points, base plus equipment instances."""

    points: tuple[BiPoint, ...] = ()
    equipment: tuple[EquipmentGroup, ...] = ()

    def all_points(self) -> list[BiPoint]:
        """Base BI points followed by every equipment instance's points."""
        out: list[BiPoint] = list(self.points)
        for group in self.equipment:
            out.extend(p for p in group.points if isinstance(p, BiPoint))
        return out


@dataclass(frozen=True)
class AnalogOutputs:
    """Analog output points, base plus equipment instances (no DER group)."""

    points: tuple[AoPoint, ...] = ()
    equipment: tuple[EquipmentGroup, ...] = ()

    def all_points(self) -> list[AoPoint]:
        """Base AO points followed by every equipment instance's points."""
        out: list[AoPoint] = list(self.points)
        for group in self.equipment:
            out.extend(p for p in group.points if isinstance(p, AoPoint))
        return out


@dataclass(frozen=True)
class AnalogInputs:
    """Analog input points: base, equipment, curves, and schedules."""

    points: tuple[AiPoint, ...] = ()
    equipment: tuple[EquipmentGroup, ...] = ()
    curves: tuple[AiCurve, ...] = ()
    schedules_bc: tuple[AiScheduleBC, ...] = ()
    schedules: tuple[AiSchedule, ...] = ()

    def base_points(self) -> list[AiPoint]:
        """Base AI points plus equipment points (excludes curves/schedules)."""
        out: list[AiPoint] = list(self.points)
        for group in self.equipment:
            out.extend(p for p in group.points if isinstance(p, AiPoint))
        return out

    def all_points_full(self) -> list[AiPoint]:
        """Every AI point across base, equipment, curves, and schedules.

        Curve and schedule AI points are real points at their own indices; a
        base-only registration would silently drop them and corrupt the point
        map. This accessor is what the database builder registers.
        """
        out = self.base_points()
        for curve in self.curves:
            out.extend(curve.iter_points())
        for sched_bc in self.schedules_bc:
            out.extend(sched_bc.iter_points())
        for sched in self.schedules:
            out.extend(sched.iter_points())
        return out


# ---------------------------------------------------------------------------
# KeySheet (census / start-index metadata)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeySheet:
    """Index and count metadata for the point groups.

    ``max_points`` and the per-equipment AI counts are surfaced as typed fields
    for now; the full section-start detail is retained by the source JSON for
    the CLI entity-override work in a later PR.
    """

    max_points: int
    equipment_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PicsProfile:
    """Top-level PICS profile: the Python twin of mesa-tool's ``PicsProfile``."""

    key: KeySheet
    bo: BinaryOutputs
    bi: BinaryInputs
    ao: AnalogOutputs
    ai: AnalogInputs
    ctr: tuple[CtrPoint, ...]


# ---------------------------------------------------------------------------
# Loader: hand-rolled boundary validation (no third-party dependency)
# ---------------------------------------------------------------------------

# Equipment groups only ever hold BI, AO, or AI points (never BO), so the
# equipment-parse TypeVar is constrained to those three.
_EquipPointT = TypeVar("_EquipPointT", BiPoint, AoPoint, AiPoint)


def _require(raw: dict[str, object], key: str, context: str) -> object:
    """Return ``raw[key]`` or raise a KeyError naming the missing field."""
    if key not in raw:
        msg = f"{context}: missing required field {key!r}"
        raise KeyError(msg)
    return raw[key]


def _as_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{context}: expected an integer, got {value!r}"
        raise ValueError(msg)
    return value


def _as_float(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{context}: expected a number, got {value!r}"
        raise ValueError(msg)
    return float(value)


def _as_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        msg = f"{context}: expected a string, got {value!r}"
        raise ValueError(msg)
    return value


def _as_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        msg = f"{context}: expected a boolean, got {value!r}"
        raise ValueError(msg)
    return value


def _as_dict(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{context}: expected an object, got {type(value).__name__}"
        raise ValueError(msg)
    return value


def _as_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        msg = f"{context}: expected a list, got {type(value).__name__}"
        raise ValueError(msg)
    return value


def _as_point_list(value: object, context: str) -> list[dict[str, object]]:
    items = _as_list(value, context)
    for item in items:
        if not isinstance(item, dict):
            msg = f"{context}: expected a list of objects, got {type(item).__name__}"
            raise ValueError(msg)
    return items  # type: ignore[return-value]


def _opt_str(raw: dict[str, object], key: str, context: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return _as_str(value, f"{context}.{key}")


def _reject_zero_multiplier(multiplier: float, context: str) -> None:
    if multiplier == 0.0:
        msg = f"{context}: multiplier cannot be zero"
        raise ValueError(msg)


def _bo_point(raw: dict[str, object]) -> BoPoint:
    ctx = f"BO point {raw.get('point_index', '<unknown>')}"
    return BoPoint(
        point_index=_as_int(_require(raw, "point_index", ctx), ctx),
        name=_as_str(_require(raw, "name", ctx), ctx),
        state_0=_as_str(_require(raw, "state_0", ctx), ctx),
        state_1=_as_str(_require(raw, "state_1", ctx), ctx),
        iec_61850_uid=_as_str(_require(raw, "iec_61850_uid", ctx), ctx),
        purpose=_as_str(_require(raw, "purpose", ctx), ctx),
        mandatory_1815=_as_bool(_require(raw, "mandatory_1815", ctx), ctx),
        mandatory_1547=_as_bool(_require(raw, "mandatory_1547", ctx), ctx),
        assoc_bi=_opt_str(raw, "assoc_bi", ctx),
    )


def _bi_point(raw: dict[str, object]) -> BiPoint:
    ctx = f"BI point {raw.get('point_index', '<unknown>')}"
    return BiPoint(
        point_index=_as_int(_require(raw, "point_index", ctx), ctx),
        name=_as_str(_require(raw, "name", ctx), ctx),
        event_class=EventClass.from_profile_string(
            _as_str(_require(raw, "event_class", ctx), ctx),
        ),
        state_0=_as_str(_require(raw, "state_0", ctx), ctx),
        state_1=_as_str(_require(raw, "state_1", ctx), ctx),
        iec_61850_uid=_as_str(_require(raw, "iec_61850_uid", ctx), ctx),
        purpose=_as_str(_require(raw, "purpose", ctx), ctx),
        mandatory_1815=_as_bool(_require(raw, "mandatory_1815", ctx), ctx),
        mandatory_1547=_as_bool(_require(raw, "mandatory_1547", ctx), ctx),
        assoc_bo=_opt_str(raw, "assoc_bo", ctx),
    )


def _ao_point(raw: dict[str, object]) -> AoPoint:
    ctx = f"AO point {raw.get('point_index', '<unknown>')}"
    multiplier = _as_float(_require(raw, "multiplier", ctx), ctx)
    _reject_zero_multiplier(multiplier, ctx)
    return AoPoint(
        point_index=_as_int(_require(raw, "point_index", ctx), ctx),
        name=_as_str(_require(raw, "name", ctx), ctx),
        minimum=_as_int(_require(raw, "minimum", ctx), ctx),
        maximum=_as_int(_require(raw, "maximum", ctx), ctx),
        multiplier=multiplier,
        offset=_as_float(_require(raw, "offset", ctx), ctx),
        units=_as_str(_require(raw, "units", ctx), ctx),
        iec_61850_uid=_as_str(_require(raw, "iec_61850_uid", ctx), ctx),
        purpose=_as_str(_require(raw, "purpose", ctx), ctx),
        mandatory_1815=_as_bool(_require(raw, "mandatory_1815", ctx), ctx),
        mandatory_1547=_as_bool(_require(raw, "mandatory_1547", ctx), ctx),
        assoc_ai=_opt_str(raw, "assoc_ai", ctx),
    )


def _ai_point(raw: dict[str, object]) -> AiPoint:
    ctx = f"AI point {raw.get('point_index', '<unknown>')}"
    multiplier = _as_float(_require(raw, "multiplier", ctx), ctx)
    _reject_zero_multiplier(multiplier, ctx)
    return AiPoint(
        point_index=_as_int(_require(raw, "point_index", ctx), ctx),
        name=_as_str(_require(raw, "name", ctx), ctx),
        event_class=EventClass.from_profile_string(
            _as_str(_require(raw, "event_class", ctx), ctx),
        ),
        minimum=_as_int(_require(raw, "minimum", ctx), ctx),
        maximum=_as_int(_require(raw, "maximum", ctx), ctx),
        multiplier=multiplier,
        offset=_as_float(_require(raw, "offset", ctx), ctx),
        units=_as_str(_require(raw, "units", ctx), ctx),
        iec_61850_uid=_as_str(_require(raw, "iec_61850_uid", ctx), ctx),
        value=_as_float(_require(raw, "value", ctx), ctx),
        purpose=_as_str(_require(raw, "purpose", ctx), ctx),
        mandatory_1815=_as_bool(_require(raw, "mandatory_1815", ctx), ctx),
        mandatory_1547=_as_bool(_require(raw, "mandatory_1547", ctx), ctx),
        assoc_ao=_opt_str(raw, "assoc_ao", ctx),
    )


def _ctr_point(raw: dict[str, object]) -> CtrPoint:
    ctx = f"CTR point {raw.get('point_index', '<unknown>')}"
    return CtrPoint(
        point_index=_as_int(_require(raw, "point_index", ctx), ctx),
        name=_as_str(_require(raw, "name", ctx), ctx),
        counter_event_class=EventClass.from_profile_string(
            _as_str(_require(raw, "counter_event_class", ctx), ctx),
        ),
        frozen_counter_exists=_as_bool(_require(raw, "frozen_counter_exists", ctx), ctx),
        frozen_counter_event_class=EventClass.from_profile_string(
            _as_str(_require(raw, "frozen_counter_event_class", ctx), ctx),
        ),
        iec_61850_uid=_as_str(_require(raw, "iec_61850_uid", ctx), ctx),
        purpose=_as_str(_require(raw, "purpose", ctx), ctx),
        mandatory_1815=_as_bool(_require(raw, "mandatory_1815", ctx), ctx),
        mandatory_1547=_as_bool(_require(raw, "mandatory_1547", ctx), ctx),
    )


def _equipment_group(
    struct: dict[str, object],
    kind: str,
    parse_point: Callable[[dict[str, object]], _EquipPointT],
) -> EquipmentGroup:
    """Flatten one named-field equipment struct into an ordered point tuple.

    The struct's values are point objects in JSON key order, matching
    mesa-tool's ``iter_points()``. A non-object value is not expected and
    raises loudly rather than being skipped.
    """
    points: list[_EquipPointT] = []
    for field_name, raw_point in struct.items():
        ctx = f"{kind} equipment field {field_name!r}"
        if not isinstance(raw_point, dict):
            msg = f"{ctx}: expected a point object, got {type(raw_point).__name__}"
            raise ValueError(msg)
        points.append(parse_point(raw_point))
    return EquipmentGroup(kind=kind, points=tuple(points))


def _equipment_list(
    section: dict[str, object],
    key: str,
    kind: str,
    parse_point: Callable[[dict[str, object]], _EquipPointT],
) -> tuple[EquipmentGroup, ...]:
    raw_list = _as_list(section.get(key, []), f"{kind} group {key!r}")
    return tuple(_equipment_group(_as_dict(item, f"{kind}[{i}]"), kind, parse_point) for i, item in enumerate(raw_list))


def _header_points(
    raw: dict[str, object],
    keys: tuple[str, ...],
    context: str,
) -> tuple[AiPoint, ...]:
    return tuple(_ai_point(_as_dict(_require(raw, k, context), f"{context}.{k}")) for k in keys)


def _array_points(
    raw: dict[str, object],
    key: str,
    context: str,
) -> tuple[AiPoint, ...]:
    return tuple(_ai_point(p) for p in _as_point_list(_require(raw, key, context), f"{context}.{key}"))


def _parse_curve(raw: dict[str, object]) -> AiCurve:
    ctx = "AI curve"
    header = _header_points(raw, ("curve_type", "number_of_points", "x_units", "y_units"), ctx)
    return AiCurve(
        header=header,
        x_values=_array_points(raw, "x_values", ctx),
        y_values=_array_points(raw, "y_values", ctx),
    )


def _parse_schedule_bc(raw: dict[str, object]) -> AiScheduleBC:
    ctx = "AI schedule_bc"
    header_keys = (
        "identity",
        "priority",
        "schedule_type",
        "start_date",
        "start_time",
        "repeat_interval",
        "repeat_interval_units",
        "validation_status",
        "status",
        "number_of_points",
    )
    return AiScheduleBC(
        header=_header_points(raw, header_keys, ctx),
        arrays=(
            _array_points(raw, "time_offsets", ctx),
            _array_points(raw, "values", ctx),
        ),
    )


def _parse_schedule(raw: dict[str, object]) -> AiSchedule:
    ctx = "AI schedule"
    header_keys = (
        "identity",
        "priority",
        "start_date",
        "start_time",
        "stop_date",
        "stop_time",
        "repeat_interval",
        "repeat_interval_units",
        "validation_state",
        "status",
        "number_of_points",
    )
    return AiSchedule(
        header=_header_points(raw, header_keys, ctx),
        arrays=(
            _array_points(raw, "time_offsets", ctx),
            _array_points(raw, "action_types", ctx),
            _array_points(raw, "action_indexes", ctx),
            _array_points(raw, "values", ctx),
        ),
    )


def _parse_keysheet(raw: object) -> KeySheet:
    key = _as_dict(raw, "Key")
    max_points = _as_int(_require(key, "max_points", "Key"), "Key.max_points")
    counts: dict[str, int] = {}
    for group in ("meter", "der", "inverter", "battery"):
        group_raw = key.get(group)
        if isinstance(group_raw, dict):
            ai_info = group_raw.get("ai")
            if isinstance(ai_info, dict) and "count" in ai_info:
                counts[group] = _as_int(ai_info["count"], f"Key.{group}.ai.count")
    return KeySheet(max_points=max_points, equipment_counts=counts)


def load_profile(path: Path) -> PicsProfile:
    """Load a PICS profile from a JSON file.

    Args:
        path: Filesystem path to a mesa-tool PicsProfile JSON document.

    Returns:
        A fully populated :class:`PicsProfile`.

    Raises:
        FileNotFoundError: If *path* does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        KeyError: If a required top-level section or point field is absent.
        ValueError: If a field has the wrong type, an ``event_class`` string is
            unrecognized, or a multiplier is zero.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        msg = f"profile root must be a JSON object, got {type(data).__name__}"
        raise ValueError(msg)

    key = _parse_keysheet(_require(data, "Key", "profile"))

    bo_section = _as_dict(_require(data, "BO", "profile"), "BO")
    bo = BinaryOutputs(
        points=tuple(_bo_point(p) for p in _as_point_list(bo_section.get("points", []), "BO.points")),
    )

    bi_section = _as_dict(_require(data, "BI", "profile"), "BI")
    bi = BinaryInputs(
        points=tuple(_bi_point(p) for p in _as_point_list(bi_section.get("points", []), "BI.points")),
        equipment=(
            *_equipment_list(bi_section, "meters", "meters", _bi_point),
            *_equipment_list(bi_section, "ders", "ders", _bi_point),
            *_equipment_list(bi_section, "inverters", "inverters", _bi_point),
            *_equipment_list(bi_section, "batteries", "batteries", _bi_point),
        ),
    )

    ao_section = _as_dict(_require(data, "AO", "profile"), "AO")
    ao = AnalogOutputs(
        points=tuple(_ao_point(p) for p in _as_point_list(ao_section.get("points", []), "AO.points")),
        equipment=(
            *_equipment_list(ao_section, "meters", "meters", _ao_point),
            *_equipment_list(ao_section, "inverters", "inverters", _ao_point),
            *_equipment_list(ao_section, "batteries", "batteries", _ao_point),
        ),
    )

    ai_section = _as_dict(_require(data, "AI", "profile"), "AI")
    ai = AnalogInputs(
        points=tuple(_ai_point(p) for p in _as_point_list(ai_section.get("points", []), "AI.points")),
        equipment=(
            *_equipment_list(ai_section, "meters", "meters", _ai_point),
            *_equipment_list(ai_section, "ders", "ders", _ai_point),
            *_equipment_list(ai_section, "inverters", "inverters", _ai_point),
            *_equipment_list(ai_section, "batteries", "batteries", _ai_point),
        ),
        curves=tuple(
            _parse_curve(_as_dict(c, "AI.curves[]")) for c in _as_list(ai_section.get("curves", []), "AI.curves")
        ),
        schedules_bc=tuple(
            _parse_schedule_bc(_as_dict(s, "AI.schedules_bc[]"))
            for s in _as_list(ai_section.get("schedules_bc", []), "AI.schedules_bc")
        ),
        schedules=tuple(
            _parse_schedule(_as_dict(s, "AI.schedules[]"))
            for s in _as_list(ai_section.get("schedules", []), "AI.schedules")
        ),
    )

    ctr = tuple(_ctr_point(p) for p in _as_point_list(_require(data, "CTR", "profile"), "CTR"))

    return PicsProfile(key=key, bo=bo, bi=bi, ao=ao, ai=ai, ctr=ctr)
