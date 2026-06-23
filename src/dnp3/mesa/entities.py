"""MESA entity model.

Groups profile points into logical entities (meters, DERs, inverters,
batteries) based on ``entity_type`` and ``entity_number`` annotations
in the profile JSON.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from dnp3.mesa.profile import PointType, Profile

# ---------------------------------------------------------------------------
# EntityType enum
# ---------------------------------------------------------------------------

_PROFILE_STRING_MAP: dict[str, EntityType] = {}


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


_PROFILE_STRING_MAP.update(
    {
        "Meter": EntityType.METER,
        "DER_Unit": EntityType.DER,
        "Inverter": EntityType.INVERTER,
        "Battery": EntityType.BATTERY,
    }
)

# Mapping from profile.entities keys to profile-string entity types
_ENTITIES_KEY_TO_PROFILE_STRING: dict[str, str] = {
    "meters": "Meter",
    "ders": "DER_Unit",
    "inverters": "Inverter",
    "batteries": "Battery",
}


# ---------------------------------------------------------------------------
# Entity dataclass
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """A single logical entity with its associated DNP3 point indices."""

    entity_type: EntityType
    entity_number: int
    point_indices: dict[PointType, list[int]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exclusion computation
# ---------------------------------------------------------------------------


def compute_excluded_indices(
    profile: Profile,
    overrides: dict[str, int] | None = None,
) -> dict[PointType, set[int]]:
    """Compute point indices that should be excluded based on entity overrides.

    Determines which ``(entity_type, entity_number)`` combinations exceed
    the allowed counts (from *overrides*, falling back to
    ``profile.entities``), then collects all point indices belonging to
    those excluded entities.

    Args:
        profile: A loaded :class:`Profile`.
        overrides: Optional dict mapping entity-count keys (``"meters"``,
            ``"ders"``, ``"inverters"``, ``"batteries"``) to maximum counts.
            When provided these replace the counts from ``profile.entities``.

    Returns:
        A dict mapping :class:`PointType` to a set of point indices that
        should be excluded from the database.  Returns an empty dict when
        no points need to be excluded.
    """
    if overrides is None:
        return {}

    counts_source = overrides

    # Resolve max allowed count per profile-string entity type
    max_counts: dict[str, int] = {}
    for key, profile_string in _ENTITIES_KEY_TO_PROFILE_STRING.items():
        if key in counts_source:
            max_counts[profile_string] = counts_source[key]
        elif key in profile.entities:
            max_counts[profile_string] = profile.entities[key]

    sections = [
        profile.binary_outputs,
        profile.binary_inputs,
        profile.analog_outputs,
        profile.analog_inputs,
    ]

    excluded: dict[PointType, set[int]] = {}

    for section in sections:
        for point in section.points:
            if point.entity_type is not None and point.entity_number is not None:
                allowed = max_counts.get(point.entity_type, 0)
                if point.entity_number > allowed:
                    excluded.setdefault(point.point_type, set()).add(point.index)

    return excluded


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_entities(
    profile: Profile,
    overrides: dict[str, int] | None = None,
) -> list[Entity]:
    """Build entity objects from a loaded MESA profile.

    Args:
        profile: A loaded :class:`Profile`.
        overrides: Optional dict mapping entity-count keys (``"meters"``,
            ``"ders"``, ``"inverters"``, ``"batteries"``) to maximum counts.
            When provided these replace the counts from ``profile.entities``.

    Returns:
        Sorted list of :class:`Entity` instances.
    """
    counts_source = overrides if overrides is not None else profile.entities

    # Resolve max allowed count per profile-string entity type
    max_counts: dict[str, int] = {}
    for key, profile_string in _ENTITIES_KEY_TO_PROFILE_STRING.items():
        if key in counts_source:
            max_counts[profile_string] = counts_source[key]
        elif key in profile.entities:
            max_counts[profile_string] = profile.entities[key]

    # Group points by (entity_type_string, entity_number)
    grouped: dict[tuple[str, int], dict[PointType, list[int]]] = defaultdict(
        lambda: defaultdict(list),
    )

    sections = [
        profile.binary_outputs,
        profile.binary_inputs,
        profile.analog_outputs,
        profile.analog_inputs,
    ]

    for section in sections:
        for point in section.points:
            if point.entity_type is not None and point.entity_number is not None:
                key = (point.entity_type, point.entity_number)
                grouped[key][point.point_type].append(point.index)

    # Build entities, filtering by allowed counts
    entities: list[Entity] = []
    for (etype_str, enum_num), indices_map in grouped.items():
        allowed = max_counts.get(etype_str, 0)
        if enum_num > allowed:
            continue

        entity_type = EntityType.from_profile_string(etype_str)
        entities.append(
            Entity(
                entity_type=entity_type,
                entity_number=enum_num,
                point_indices=dict(indices_map),
            ),
        )

    entities.sort(key=lambda e: (e.entity_type.value, e.entity_number))
    return entities
