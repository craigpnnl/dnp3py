"""MESA entity model.

Groups profile equipment points into logical entities (meters, DERs, inverters,
batteries). Under the PICS profile format each equipment instance is an explicit
struct in the ``BI``/``AO``/``AI`` sections (``BinaryInputs.equipment`` etc.), so
an entity is the union of one instance's points across the sections, addressed by
its 1-based instance number.

Note: the full CLI entity-override reinterpretation onto ``KeySheet`` counts is a
later-PR concern. This module provides the minimal equipment-instance grouping
and count-based exclusion needed for the outstation to build against the new
model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from dnp3.mesa.profile import EquipmentGroup, PicsProfile, PointType

__all__ = [
    "Entity",
    "EntityType",
    "build_entities",
    "compute_excluded_indices",
]


class EntityType(Enum):
    """Logical entity types found in MESA profiles."""

    BATTERY = "BATTERY"
    DER = "DER"
    INVERTER = "INVERTER"
    METER = "METER"

    @classmethod
    def from_profile_string(cls, s: str) -> EntityType:
        """Convert a profile-level entity type string to an enum member.

        Raises:
            ValueError: If *s* is not a recognised entity string.
        """
        try:
            return _PROFILE_STRING_MAP[s]
        except KeyError:
            msg = f"Unknown entity type string: {s!r}"
            raise ValueError(msg) from None


_PROFILE_STRING_MAP: dict[str, EntityType] = {
    "Meter": EntityType.METER,
    "DER_Unit": EntityType.DER,
    "Inverter": EntityType.INVERTER,
    "Battery": EntityType.BATTERY,
}

# Map the profile equipment-group key (plural) to its EntityType.
_GROUP_KIND_TO_TYPE: dict[str, EntityType] = {
    "meters": EntityType.METER,
    "ders": EntityType.DER,
    "inverters": EntityType.INVERTER,
    "batteries": EntityType.BATTERY,
}


@dataclass
class Entity:
    """A single logical entity with its associated DNP3 point indices."""

    entity_type: EntityType
    entity_number: int
    point_indices: dict[PointType, list[int]] = field(default_factory=dict)


def _iter_instances(
    profile: PicsProfile,
) -> list[tuple[str, int, PointType, EquipmentGroup]]:
    """Return (group_kind, instance_number, section_point_type, group) tuples.

    Instances are numbered per (kind, section) in profile order, 1-based. The
    same instance number across sections denotes the same physical entity.
    """
    out: list[tuple[str, int, PointType, EquipmentGroup]] = []
    for section_pt, groups in (
        (PointType.BINARY_INPUT, profile.bi.equipment),
        (PointType.ANALOG_OUTPUT, profile.ao.equipment),
        (PointType.ANALOG_INPUT, profile.ai.equipment),
    ):
        per_kind_counter: dict[str, int] = defaultdict(int)
        for group in groups:
            per_kind_counter[group.kind] += 1
            out.append((group.kind, per_kind_counter[group.kind], section_pt, group))
    return out


def _allowed_count(kind: str, overrides: dict[str, int] | None) -> int | None:
    """Return the max allowed instance count for *kind*, or None (unlimited)."""
    if overrides is None:
        return None
    return overrides.get(kind)


def compute_excluded_indices(
    profile: PicsProfile,
    overrides: dict[str, int] | None = None,
) -> dict[PointType, set[int]]:
    """Compute point indices excluded because their equipment instance is over
    the allowed count.

    Args:
        profile: A loaded :class:`PicsProfile`.
        overrides: Optional dict mapping group keys (``"meters"``, ``"ders"``,
            ``"inverters"``, ``"batteries"``) to a maximum instance count. An
            instance whose 1-based number exceeds the count is excluded.

    Returns:
        A dict mapping :class:`PointType` to the set of excluded indices. Empty
        when *overrides* is None.
    """
    if overrides is None:
        return {}

    excluded: dict[PointType, set[int]] = {}
    for kind, instance_number, section_pt, group in _iter_instances(profile):
        allowed = _allowed_count(kind, overrides)
        if allowed is not None and instance_number > allowed:
            for point in group.points:
                excluded.setdefault(section_pt, set()).add(point.point_index)
    return excluded


def build_entities(
    profile: PicsProfile,
    overrides: dict[str, int] | None = None,
) -> list[Entity]:
    """Build entity objects from a loaded PICS profile.

    Args:
        profile: A loaded :class:`PicsProfile`.
        overrides: Optional dict mapping group keys to a maximum instance count.

    Returns:
        Sorted list of :class:`Entity` instances (by type value then number).
    """
    grouped: dict[tuple[EntityType, int], dict[PointType, list[int]]] = defaultdict(
        lambda: defaultdict(list),
    )

    for kind, instance_number, section_pt, group in _iter_instances(profile):
        allowed = _allowed_count(kind, overrides)
        if allowed is not None and instance_number > allowed:
            continue
        entity_type = _GROUP_KIND_TO_TYPE[kind]
        indices = grouped[(entity_type, instance_number)][section_pt]
        indices.extend(point.point_index for point in group.points)

    entities = [
        Entity(
            entity_type=etype,
            entity_number=number,
            point_indices=dict(indices_map),
        )
        for (etype, number), indices_map in grouped.items()
    ]
    entities.sort(key=lambda e: (e.entity_type.value, e.entity_number))
    return entities
