"""Absolute event timestamps delivered through the master's shared decode path.

Refs #81. IEEE 1815-2012 11.3: DNP3TIME is a UINT48 count of milliseconds
since 1970-01-01 00:00:00 UTC, little-endian. Every layout row whose time
field is absolute carries the same trailing 6 octets after its flag and
value fields, so one test per delivered pair exercises the shared decode
path once, end to end through Master.process_response.
"""

import struct
from datetime import UTC, datetime, timedelta

import pytest

from dnp3.master.handler import DefaultSOEHandler
from dnp3.master.master import Master

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# A count above 2^32 ms (4294967296): exercises the full 48-bit field, not
# just its low 32 bits, so a decoder that truncates to 32 bits is caught.
_MS = 1_700_000_000_123
_TIME = _MS.to_bytes(6, "little")
_EXPECTED = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=_MS)

FLAGS_ON = 0x81  # bit 7 = state, bit 0 = online: binary points only.
FLAGS = 0x01  # online, no state bit: every other point kind.


def _event_response(group: int, variation: int, index: int, value: bytes, flags: int) -> bytes:
    """One event object: qualifier 0x17 (1-byte count, 1-byte index prefix)."""
    header = bytes([group, variation, 0x17])
    body = bytes([0x01, index, flags]) + value + _TIME
    return RESPONSE_HEADER + header + body


# (group, variation, clause, handler attribute, value bytes, flags octet).
# g2v2 and g11v2 carry no separate value field: the state lives in the flag
# octet itself, as g1v2/g2v1 already do.
_ABSOLUTE_TIME_PAIRS = [
    (2, 2, "A.3.2", "binary_inputs", b"", FLAGS_ON),
    (11, 2, "A.7.2", "binary_outputs", b"", FLAGS_ON),
    (21, 5, "A.11.5", "frozen_counters", struct.pack("<I", 0x12345678), FLAGS),
    (21, 6, "A.11.6", "frozen_counters", struct.pack("<H", 0x1234), FLAGS),
    (22, 5, "A.12.5", "counters", struct.pack("<I", 4242), FLAGS),
    (22, 6, "A.12.6", "counters", struct.pack("<H", 42), FLAGS),
    (32, 3, "A.16.3", "analog_inputs", struct.pack("<i", -1500), FLAGS),
    (32, 4, "A.16.4", "analog_inputs", struct.pack("<h", -15), FLAGS),
    (32, 7, "A.16.7", "analog_inputs", struct.pack("<f", 2401.5), FLAGS),
    (32, 8, "A.16.8", "analog_inputs", struct.pack("<d", -15.25), FLAGS),
    (42, 3, "A.21.3", "analog_outputs", struct.pack("<i", 100), FLAGS),
    (42, 4, "A.21.4", "analog_outputs", struct.pack("<h", -7), FLAGS),
    (42, 7, "A.21.7", "analog_outputs", struct.pack("<f", 3.5), FLAGS),
    (42, 8, "A.21.8", "analog_outputs", struct.pack("<d", 9.75), FLAGS),
]


@pytest.mark.parametrize(
    ("group", "variation", "clause", "attr", "value", "flags"),
    _ABSOLUTE_TIME_PAIRS,
    ids=[f"g{g}v{v}" for g, v, *_ in _ABSOLUTE_TIME_PAIRS],
)
def test_absolute_time_delivered(
    *,
    group: int,
    variation: int,
    clause: str,
    attr: str,
    value: bytes,
    flags: int,
) -> None:
    """Every delivered absolute-time pair decodes its trailing DNP3TIME exactly."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    data = _event_response(group, variation, index=1, value=value, flags=flags)

    info = master.process_response(data)

    assert info is not None
    values = getattr(handler, attr)
    assert values[1].timestamp == _EXPECTED, clause


def test_no_time_row_stays_none() -> None:
    """g2v1 (A.3.1) carries no time field: timestamp stays None."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    data = _event_response(2, 1, index=1, value=b"", flags=FLAGS_ON)

    master.process_response(data)

    assert handler.binary_inputs[1].timestamp is None


def test_relative_time_row_stays_none() -> None:
    """g2v3 (A.3.3) carries relative time, not absolute: timestamp stays None."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    header = bytes([2, 3, 0x17])
    body = bytes([0x01, 1, FLAGS_ON]) + (1234).to_bytes(2, "little")
    data = RESPONSE_HEADER + header + body

    master.process_response(data)

    assert handler.binary_inputs[1].timestamp is None


def test_time_field_beyond_datetime_range_yields_none_not_a_crash() -> None:
    """A 48-bit value past year 9999 (the wire field allows one) leaves timestamp None.

    The value and flags of the same object still deliver: an unrepresentable
    time field must not cost the rest of the object.
    """
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    huge_time = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])  # far beyond datetime.MAXYEAR
    header = bytes([32, 3, 0x17])
    body = bytes([0x01, 1, FLAGS]) + struct.pack("<i", -1500) + huge_time
    data = RESPONSE_HEADER + header + body

    info = master.process_response(data)

    assert info is not None
    value = handler.analog_inputs[1]
    assert value.value == -1500.0
    assert value.timestamp is None


# The last millisecond datetime can represent (9999-12-31 23:59:59.999 UTC)
# and the first one it cannot, one ms later.
_MAX_MS = 253_402_300_799_999
_OVER_MAX_MS = _MAX_MS + 1


def test_time_field_at_max_datetime_value() -> None:
    """The last representable millisecond decodes exactly, not just as non-None."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    header = bytes([32, 3, 0x17])
    body = bytes([0x01, 1, FLAGS]) + struct.pack("<i", -1500) + _MAX_MS.to_bytes(6, "little")
    data = RESPONSE_HEADER + header + body

    master.process_response(data)

    assert handler.analog_inputs[1].timestamp == datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)


def test_time_field_one_ms_past_max_yields_none() -> None:
    """One millisecond past the last representable one yields None, value still delivered."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    header = bytes([32, 3, 0x17])
    body = bytes([0x01, 1, FLAGS]) + struct.pack("<i", -1500) + _OVER_MAX_MS.to_bytes(6, "little")
    data = RESPONSE_HEADER + header + body

    master.process_response(data)

    value = handler.analog_inputs[1]
    assert value.value == -1500.0
    assert value.timestamp is None
