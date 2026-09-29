"""Wire layout of each DNP3 object group and variation, per IEEE 1815-2012 Annex A.

One table describes how a response object sits on the wire, so a block's length
and a point's value are read from the same definition.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

__all__ = [
    "LAYOUTS",
    "PointKind",
    "TimeKind",
    "ValueCodec",
    "WireLayout",
    "data_length",
    "layout_for",
    "object_width",
]


class PointKind(Enum):
    """The kind of point an object reports."""

    BINARY_INPUT = "binary_input"
    DOUBLE_BIT_INPUT = "double_bit_input"
    BINARY_OUTPUT = "binary_output"
    BINARY_COMMAND = "binary_command"
    BINARY_COMMAND_EVENT = "binary_command_event"
    COUNTER = "counter"
    FROZEN_COUNTER = "frozen_counter"
    ANALOG_INPUT = "analog_input"
    ANALOG_OUTPUT = "analog_output"
    ANALOG_COMMAND = "analog_command"
    ANALOG_COMMAND_EVENT = "analog_command_event"
    FROZEN_ANALOG_INPUT = "frozen_analog_input"
    ANALOG_DEADBAND = "analog_deadband"
    TIME = "time"
    TIME_DELAY = "time_delay"
    CLASS = "class"
    INTERNAL_INDICATION = "internal_indication"
    DATA_SET_CHARACTERISTICS = "data_set_characteristics"
    BCD_INTEGER = "bcd_integer"
    UNSIGNED_INTEGER = "unsigned_integer"
    AUTHENTICATION = "authentication"
    SECURITY_STATISTIC = "security_statistic"
    OCTET_STRING = "octet_string"


class ValueCodec(Enum):
    """How the value field of an object is encoded (little-endian, IEEE 1815-2012 11.3)."""

    NONE = "none"
    PACKED = "packed"
    FLAG_STATE = "flag_state"
    INT = "int"
    UINT = "uint"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    RECORD = "record"
    OCTET_STRING = "octet_string"


class TimeKind(Enum):
    """The time field that trails an object's value."""

    NONE = 0
    RELATIVE = 2
    ABSOLUTE = 6

    @property
    def octets(self) -> int:
        """Octets the time field occupies."""
        return self.value


@dataclass(frozen=True, slots=True)
class WireLayout:
    """Layout of one object on the wire.

    Attributes:
        point_kind: The kind of point the object reports.
        width: Octets per object excluding any index prefix; 0 for a packed layout.
        bits_per_point: Bits per point for a packed layout; 0 when octet-aligned.
        has_flags: Whether a flag octet leads the object.
        codec: Encoding of the value field.
        time: The time field that trails the value.
    """

    point_kind: PointKind
    width: int
    bits_per_point: int
    has_flags: bool
    codec: ValueCodec
    time: TimeKind

    def __post_init__(self) -> None:
        """Refuse a layout no Annex A object could have."""
        if self.bits_per_point < 0:
            msg = f"bits per point must be non-negative, got {self.bits_per_point}"
            raise ValueError(msg)
        if self.bits_per_point:
            if self.width or self.has_flags or self.time is not TimeKind.NONE:
                msg = "a packed layout has no octet width, flags or time"
                raise ValueError(msg)
        elif self.value_width < 0:
            msg = f"width {self.width} is smaller than its flag and time fields"
            raise ValueError(msg)

    @property
    def is_packed(self) -> bool:
        """Whether points are bit-packed rather than octet-aligned."""
        return self.bits_per_point > 0

    @property
    def value_width(self) -> int:
        """Octets between the flag octet and the time field."""
        return self.width - int(self.has_flags) - self.time.octets


def _packed(kind: PointKind, bits: int) -> WireLayout:
    return WireLayout(kind, 0, bits, False, ValueCodec.PACKED, TimeKind.NONE)


def _octets(
    kind: PointKind,
    value_width: int,
    codec: ValueCodec,
    *,
    flags: bool = True,
    time: TimeKind = TimeKind.NONE,
) -> WireLayout:
    return WireLayout(kind, int(flags) + value_width + time.octets, 0, flags, codec, time)


_BI = PointKind.BINARY_INPUT
_BO = PointKind.BINARY_OUTPUT
_DBI = PointKind.DOUBLE_BIT_INPUT
_CT = PointKind.COUNTER
_FC = PointKind.FROZEN_COUNTER
_AI = PointKind.ANALOG_INPUT
_AO = PointKind.ANALOG_OUTPUT
_FAI = PointKind.FROZEN_ANALOG_INPUT
_ABS = TimeKind.ABSOLUTE
_REL = TimeKind.RELATIVE
_INT = ValueCodec.INT
_UINT = ValueCodec.UINT
_F32 = ValueCodec.FLOAT32
_F64 = ValueCodec.FLOAT64
_STATE = ValueCodec.FLAG_STATE
_REC = ValueCodec.RECORD

# Keyed by (group, variation); the comment on each group names its Annex A clause.
_TABLE: dict[tuple[int, int], WireLayout] = {
    # A.2
    (1, 1): _packed(_BI, 1),
    (1, 2): _octets(_BI, 0, _STATE),
    # A.3
    (2, 1): _octets(_BI, 0, _STATE),
    (2, 2): _octets(_BI, 0, _STATE, time=_ABS),
    (2, 3): _octets(_BI, 0, _STATE, time=TimeKind.RELATIVE),
    # A.4
    (3, 1): _packed(PointKind.DOUBLE_BIT_INPUT, 2),
    (3, 2): _octets(_DBI, 0, _STATE),
    # A.5
    (4, 1): _octets(_DBI, 0, _STATE),
    (4, 2): _octets(_DBI, 0, _STATE, time=_ABS),
    (4, 3): _octets(_DBI, 0, _STATE, time=_REL),
    # A.6
    (10, 1): _packed(_BO, 1),
    (10, 2): _octets(_BO, 0, _STATE),
    # A.7
    (11, 1): _octets(_BO, 0, _STATE),
    (11, 2): _octets(_BO, 0, _STATE, time=_ABS),
    # A.8.1: control code, count, on-time, off-time, status.
    (12, 1): _octets(PointKind.BINARY_COMMAND, 11, ValueCodec.RECORD, flags=False),
    # A.9: status code, commanded state.
    (13, 1): _octets(PointKind.BINARY_COMMAND_EVENT, 1, _REC, flags=False),
    (13, 2): _octets(PointKind.BINARY_COMMAND_EVENT, 1, _REC, flags=False, time=_ABS),
    # A.10. v3, v4, v7, v8 are delta variations, obsolete per the standard but still
    # on the wire; each has the same flag/width/time shape as its plain sibling.
    (20, 1): _octets(_CT, 4, _UINT),
    (20, 2): _octets(_CT, 2, _UINT),
    (20, 3): _octets(_CT, 4, _UINT),
    (20, 4): _octets(_CT, 2, _UINT),
    (20, 5): _octets(_CT, 4, _UINT, flags=False),
    (20, 6): _octets(_CT, 2, _UINT, flags=False),
    (20, 7): _octets(_CT, 4, _UINT, flags=False),
    (20, 8): _octets(_CT, 2, _UINT, flags=False),
    # A.11: v1-v4 share g20v1-v4's flag/width shape; v5-v8 add a DNP3TIME field
    # g20 never has; v9-v12 share g20v5-v8's without-flag, no-time shape.
    (21, 1): _octets(_FC, 4, _UINT),
    (21, 2): _octets(_FC, 2, _UINT),
    (21, 3): _octets(_FC, 4, _UINT),
    (21, 4): _octets(_FC, 2, _UINT),
    (21, 5): _octets(_FC, 4, _UINT, time=_ABS),
    (21, 6): _octets(_FC, 2, _UINT, time=_ABS),
    (21, 7): _octets(_FC, 4, _UINT, time=_ABS),
    (21, 8): _octets(_FC, 2, _UINT, time=_ABS),
    (21, 9): _octets(_FC, 4, _UINT, flags=False),
    (21, 10): _octets(_FC, 2, _UINT, flags=False),
    (21, 11): _octets(_FC, 4, _UINT, flags=False),
    (21, 12): _octets(_FC, 2, _UINT, flags=False),
    # A.12: v3, v4, v7, v8 are delta variations of v1, v2, v5, v6.
    (22, 1): _octets(_CT, 4, _UINT),
    (22, 2): _octets(_CT, 2, _UINT),
    (22, 3): _octets(_CT, 4, _UINT),
    (22, 4): _octets(_CT, 2, _UINT),
    (22, 5): _octets(_CT, 4, _UINT, time=_ABS),
    (22, 6): _octets(_CT, 2, _UINT, time=_ABS),
    (22, 7): _octets(_CT, 4, _UINT, time=_ABS),
    (22, 8): _octets(_CT, 2, _UINT, time=_ABS),
    # A.13: v3/v4/v7/v8 are the delta variations (obsolete per A.13.3.2.3); the
    # standard gives them the same field widths and time field as v1/v2/v5/v6.
    # Bit 6 of the flag octet differs: DISCONTINUITY on v1/v5/v6, reserved on v3/v7.
    (23, 1): _octets(_FC, 4, _UINT),
    (23, 2): _octets(_FC, 2, _UINT),
    (23, 3): _octets(_FC, 4, _UINT),
    (23, 4): _octets(_FC, 2, _UINT),
    (23, 5): _octets(_FC, 4, _UINT, time=_ABS),
    (23, 6): _octets(_FC, 2, _UINT, time=_ABS),
    (23, 7): _octets(_FC, 4, _UINT, time=_ABS),
    (23, 8): _octets(_FC, 2, _UINT, time=_ABS),
    # A.14
    (30, 1): _octets(_AI, 4, _INT),
    (30, 2): _octets(_AI, 2, _INT),
    (30, 3): _octets(_AI, 4, _INT, flags=False),
    (30, 4): _octets(_AI, 2, _INT, flags=False),
    (30, 5): _octets(_AI, 4, _F32),
    (30, 6): _octets(_AI, 8, _F64),
    # A.15
    (31, 1): _octets(_FAI, 4, _INT),
    (31, 2): _octets(_FAI, 2, _INT),
    (31, 3): _octets(_FAI, 4, _INT, time=_ABS),
    (31, 4): _octets(_FAI, 2, _INT, time=_ABS),
    (31, 5): _octets(_FAI, 4, _INT, flags=False),
    (31, 6): _octets(_FAI, 2, _INT, flags=False),
    (31, 7): _octets(_FAI, 4, _F32),
    (31, 8): _octets(_FAI, 8, _F64),
    # A.16
    (32, 1): _octets(_AI, 4, _INT),
    (32, 2): _octets(_AI, 2, _INT),
    (32, 3): _octets(_AI, 4, _INT, time=_ABS),
    (32, 4): _octets(_AI, 2, _INT, time=_ABS),
    (32, 5): _octets(_AI, 4, _F32),
    (32, 6): _octets(_AI, 8, _F64),
    (32, 7): _octets(_AI, 4, _F32, time=_ABS),
    (32, 8): _octets(_AI, 8, _F64, time=_ABS),
    # A.17
    (33, 1): _octets(_FAI, 4, _INT),
    (33, 2): _octets(_FAI, 2, _INT),
    (33, 3): _octets(_FAI, 4, _INT, time=_ABS),
    (33, 4): _octets(_FAI, 2, _INT, time=_ABS),
    (33, 5): _octets(_FAI, 4, _F32),
    (33, 6): _octets(_FAI, 8, _F64),
    (33, 7): _octets(_FAI, 4, _F32, time=_ABS),
    # A.17.8's formal structure prints FLT32; FLT64 follows its own description
    # ("double-precision") and value range, and matches every sibling row.
    (33, 8): _octets(_FAI, 8, _F64, time=_ABS),
    # A.18: deadband value alone, no flags.
    (34, 1): _octets(PointKind.ANALOG_DEADBAND, 2, _UINT, flags=False),
    (34, 2): _octets(PointKind.ANALOG_DEADBAND, 4, _UINT, flags=False),
    (34, 3): _octets(PointKind.ANALOG_DEADBAND, 4, _F32, flags=False),
    # A.19
    (40, 1): _octets(_AO, 4, _INT),
    (40, 2): _octets(_AO, 2, _INT),
    (40, 3): _octets(_AO, 4, _F32),
    (40, 4): _octets(_AO, 8, _F64),
    # A.20: requested value plus control status octet, one 5/3/5/9-octet record.
    (41, 1): _octets(PointKind.ANALOG_COMMAND, 5, _REC, flags=False),
    (41, 2): _octets(PointKind.ANALOG_COMMAND, 3, _REC, flags=False),
    (41, 3): _octets(PointKind.ANALOG_COMMAND, 5, _REC, flags=False),
    (41, 4): _octets(PointKind.ANALOG_COMMAND, 9, _REC, flags=False),
    # A.21
    (42, 1): _octets(_AO, 4, _INT),
    (42, 2): _octets(_AO, 2, _INT),
    (42, 3): _octets(_AO, 4, _INT, time=_ABS),
    (42, 4): _octets(_AO, 2, _INT, time=_ABS),
    (42, 5): _octets(_AO, 4, _F32),
    (42, 6): _octets(_AO, 8, _F64),
    (42, 7): _octets(_AO, 4, _F32, time=_ABS),
    (42, 8): _octets(_AO, 8, _F64, time=_ABS),
    # A.22: status octet plus commanded value, one 5/3/5/9-octet record before time.
    (43, 1): _octets(PointKind.ANALOG_COMMAND_EVENT, 5, _REC, flags=False),
    (43, 2): _octets(PointKind.ANALOG_COMMAND_EVENT, 3, _REC, flags=False),
    (43, 3): _octets(PointKind.ANALOG_COMMAND_EVENT, 5, _REC, flags=False, time=_ABS),
    (43, 4): _octets(PointKind.ANALOG_COMMAND_EVENT, 3, _REC, flags=False, time=_ABS),
    (43, 5): _octets(PointKind.ANALOG_COMMAND_EVENT, 5, _REC, flags=False),
    (43, 6): _octets(PointKind.ANALOG_COMMAND_EVENT, 9, _REC, flags=False),
    (43, 7): _octets(PointKind.ANALOG_COMMAND_EVENT, 5, _REC, flags=False, time=_ABS),
    (43, 8): _octets(PointKind.ANALOG_COMMAND_EVENT, 9, _REC, flags=False, time=_ABS),
    # A.23 and A.24: a DNP3TIME (UINT48) is the whole object.
    (50, 1): _octets(PointKind.TIME, 6, _UINT, flags=False),
    (50, 3): _octets(PointKind.TIME, 6, _UINT, flags=False),
    (51, 1): _octets(PointKind.TIME, 6, _UINT, flags=False),
    (51, 2): _octets(PointKind.TIME, 6, _UINT, flags=False),
    # A.25
    (52, 1): _octets(PointKind.TIME_DELAY, 2, _UINT, flags=False),
    (52, 2): _octets(PointKind.TIME_DELAY, 2, _UINT, flags=False),
    # A.26: class objects carry no object data.
    (60, 1): _octets(PointKind.CLASS, 0, ValueCodec.NONE, flags=False),
    (60, 2): _octets(PointKind.CLASS, 0, ValueCodec.NONE, flags=False),
    (60, 3): _octets(PointKind.CLASS, 0, ValueCodec.NONE, flags=False),
    (60, 4): _octets(PointKind.CLASS, 0, ValueCodec.NONE, flags=False),
    # A.28.1: one bit per internal indication, written to clear DEVICE_RESTART.
    (80, 1): _packed(PointKind.INTERNAL_INDICATION, 1),
    # A.33.2: BSTR4 characteristics octet, no flags, no time. Framed and
    # stepped over only (#82): no decoder reads the RD/WR/ST/EV/DF bits yet.
    (86, 2): _octets(PointKind.DATA_SET_CHARACTERISTICS, 1, _REC, flags=False),
    # A.39.1-3: BCD value alone, no flags. Not a binary UINT, so RECORD rather
    # than UINT: framed and stepped over only, per #82.
    (101, 1): _octets(PointKind.BCD_INTEGER, 2, _REC, flags=False),
    (101, 2): _octets(PointKind.BCD_INTEGER, 4, _REC, flags=False),
    (101, 3): _octets(PointKind.BCD_INTEGER, 8, _REC, flags=False),
    # A.40.1: UINT8 value alone, no flags.
    (102, 1): _octets(PointKind.UNSIGNED_INTEGER, 1, _UINT, flags=False),
    # A.45.3: UINT32 Challenge Sequence Number + UINT16 User Number, no flags.
    (120, 3): _octets(PointKind.AUTHENTICATION, 6, _REC, flags=False),
    # A.46.1, A.47.1-2: flag octet, UINT16 association ID, UINT32 count value,
    # v2 adds a DNP3TIME. Static and event share one PointKind, as COUNTER and
    # FROZEN_COUNTER do above.
    (121, 1): _octets(PointKind.SECURITY_STATISTIC, 6, _REC),
    (122, 1): _octets(PointKind.SECURITY_STATISTIC, 6, _REC),
    (122, 2): _octets(PointKind.SECURITY_STATISTIC, 6, _REC, time=_ABS),
}

LAYOUTS: Mapping[tuple[int, int], WireLayout] = MappingProxyType(_TABLE)

# Groups whose width is the variation number itself (OSTRn), not a table row:
# g110 octet strings (A.41.1) and g111 octet string events (A.42.1). Variation
# 0 is request-only in both (Table 12-30) and is excluded here.
_OCTET_STRING_GROUPS = frozenset({110, 111})


def _octet_string_layout(variation: int) -> WireLayout:
    # A.41.1.2.2 / A.42.1.2.2: OSTRn is n octets of value, no flags, no time.
    return WireLayout(PointKind.OCTET_STRING, variation, 0, False, ValueCodec.OCTET_STRING, TimeKind.NONE)


def layout_for(group: int, variation: int) -> WireLayout | None:
    """Return the layout of a group and variation, or None if it has none."""
    if group in _OCTET_STRING_GROUPS and variation != 0:
        return _octet_string_layout(variation)
    return LAYOUTS.get((group, variation))


def object_width(group: int, variation: int) -> int | None:
    """Octets per object excluding any index prefix, or None if unknown or packed."""
    layout = layout_for(group, variation)
    if layout is None or layout.is_packed:
        return None
    return layout.width


def data_length(layout: WireLayout, count: int, prefix_width: int) -> int | None:
    """Octets of object data for ``count`` objects, each led by a ``prefix_width`` index.

    A packed layout with an index prefix gives None, checked before the count, so
    even a count of 0 gives None: IEEE 1815-2012 A.2.1 and A.4.1 define packing
    only over a contiguous index range. Otherwise a count of 0 gives 0.
    """
    if count < 0 or prefix_width < 0:
        msg = f"count and prefix width must be non-negative, got {count} and {prefix_width}"
        raise ValueError(msg)
    if layout.is_packed:
        if prefix_width:
            return None
        return (count * layout.bits_per_point + 7) // 8
    return (prefix_width + layout.width) * count
