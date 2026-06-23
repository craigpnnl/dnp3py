"""MESA profile loader.

Reads a MESA-ESS JSON profile and produces immutable dataclass
representations of the four DNP3 point sections (BO, BI, AO, AI).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# PointType enum
# ---------------------------------------------------------------------------


class PointType(Enum):
    """DNP3 point type prefixes used in MESA profiles."""

    BINARY_OUTPUT = "BO"
    BINARY_INPUT = "BI"
    ANALOG_OUTPUT = "AO"
    ANALOG_INPUT = "AI"


_PREFIX_MAP: dict[str, PointType] = {pt.value: pt for pt in PointType}
_INDEX_RE = re.compile(r"^(BO|BI|AO|AI)(\d+)$")


def parse_index(index_str: str) -> tuple[PointType, int]:
    """Parse a string like ``'BO0'`` into a ``(PointType, int)`` tuple.

    Raises:
        ValueError: If *index_str* does not match the expected pattern.
    """
    m = _INDEX_RE.match(index_str)
    if m is None:
        msg = f"Invalid index string: {index_str!r}"
        raise ValueError(msg)
    return _PREFIX_MAP[m.group(1)], int(m.group(2))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfilePoint:
    """A single point parsed from a MESA profile section."""

    point_type: PointType
    index: int
    description: str
    uid: str
    purpose: str
    value: int | float
    supported: bool
    associated_index: str | None = None
    ieee_1815_2: bool | None = None
    ieee_1547_1: bool | None = None
    entity_number: int | None = None
    entity_type: str | None = None
    entity_index_offset: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    multiplier: float | None = None
    offset: float | None = None
    units: str | None = None
    event_class: int | None = None


@dataclass(frozen=True)
class ProfileSection:
    """One of the four point-type sections in a MESA profile."""

    offsets: dict[str, int]
    points: list[ProfilePoint] = field(default_factory=list)


@dataclass(frozen=True)
class Profile:
    """Complete MESA profile containing all four DNP3 sections."""

    entities: dict[str, int]
    binary_outputs: ProfileSection
    binary_inputs: ProfileSection
    analog_outputs: ProfileSection
    analog_inputs: ProfileSection


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_OPTIONAL_FIELDS = frozenset(
    {
        "associated_index",
        "ieee_1815_2",
        "ieee_1547_1",
        "entity_number",
        "entity_type",
        "entity_index_offset",
        "minimum",
        "maximum",
        "multiplier",
        "offset",
        "units",
        "event_class",
    }
)


def _parse_section(section_data: dict) -> ProfileSection:
    """Build a :class:`ProfileSection` from a raw JSON dict."""
    offsets: dict[str, int] = section_data.get("offsets", {})
    raw_points: list[dict] = section_data.get("points", [])
    points: list[ProfilePoint] = []

    for raw in raw_points:
        if not raw.get("supported", False):
            continue

        point_type, numeric_index = parse_index(raw["index"])

        kwargs: dict = {
            "point_type": point_type,
            "index": numeric_index,
            "description": raw["description"],
            "uid": raw["uid"],
            "purpose": raw["purpose"],
            "value": raw["value"],
            "supported": raw["supported"],
        }

        for key in _OPTIONAL_FIELDS:
            if key in raw:
                kwargs[key] = raw[key]

        points.append(ProfilePoint(**kwargs))

    return ProfileSection(offsets=offsets, points=points)


def load_profile(path: Path) -> Profile:
    """Load a MESA profile from a JSON file.

    Args:
        path: Filesystem path to the JSON profile.

    Returns:
        A fully populated :class:`Profile`.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)

    return Profile(
        entities=data.get("entities", {}),
        binary_outputs=_parse_section(data.get("binary_outputs", {})),
        binary_inputs=_parse_section(data.get("binary_inputs", {})),
        analog_outputs=_parse_section(data.get("analog_outputs", {})),
        analog_inputs=_parse_section(data.get("analog_inputs", {})),
    )
