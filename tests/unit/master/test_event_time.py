"""Event timestamps delivered through the master's shared decode path.

Refs #81. IEEE 1815-2012 11.3: DNP3TIME is a UINT48 count of milliseconds
since 1970-01-01 00:00:00 UTC, little-endian. Every layout row whose time
field is absolute carries the same trailing 6 octets after its flag and
value fields, so one test per delivered pair exercises the shared decode
path once, end to end through Master.process_response. Relative-time rows
carry a UINT16 offset from the preceding common time of occurrence.
"""

import struct
from datetime import UTC, datetime, timedelta

import pytest

from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.flags import DoubleBitState
from dnp3.master.handler import AnalogValue, BinaryValue, DefaultSOEHandler, ResponseInfo, SOEHandler
from dnp3.master.master import Master
from tests.unit.master.delivery import RecordingHandler, response_info

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
    assert info.relative_time_without_cto == 0


def test_no_time_row_stays_none() -> None:
    """g2v1 (A.3.1) carries no time field: timestamp stays None."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    data = _event_response(2, 1, index=1, value=b"", flags=FLAGS_ON)

    master.process_response(data)

    assert handler.binary_inputs[1].timestamp is None


# A.24.1 and A.24.2: a g51 common time of occurrence (CTO) is a DNP3TIME; each
# later relative-time object adds its UINT16 milliseconds (A.3.3, A.5.3) to the
# immediately preceding CTO. Qualifier 0x07 is a 1-octet count with no index
# prefix; 0x17 adds a 1-octet index prefix.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CTO_MS = 1_700_000_000_000
_CTO = _EPOCH + timedelta(milliseconds=_CTO_MS)


def _cto(ms: int, variation: int = 1) -> bytes:
    return bytes([51, variation, 0x07, 0x01]) + ms.to_bytes(6, "little")


def _relative(group: int, events: list[tuple[int, int, int]]) -> bytes:
    """A g2v3 or g4v3 block of (index, flags, relative ms) objects."""
    body = b"".join(bytes([index, flags]) + offset.to_bytes(2, "little") for index, flags, offset in events)
    return bytes([group, 3, 0x17, len(events)]) + body


def _process(objects: bytes, handler: SOEHandler) -> ResponseInfo:
    info = Master(handler=handler).process_response(RESPONSE_HEADER + objects)
    assert info is not None
    return info


def test_cto_then_binary_relative_events() -> None:
    """Each g2v3 object adds its own offset to the CTO; value and flags are untouched."""
    handler = DefaultSOEHandler()
    info = _process(_cto(_CTO_MS) + _relative(2, [(1, FLAGS_ON, 250), (2, 0x01, 1000)]), handler)

    first, second = handler.binary_inputs[1], handler.binary_inputs[2]
    assert (first.value, first.quality, first.timestamp) == (True, 0x01, _CTO + timedelta(milliseconds=250))
    assert (second.value, second.quality, second.timestamp) == (False, 0x01, _CTO + timedelta(milliseconds=1000))
    assert info.relative_time_without_cto == 0


def test_cto_then_double_bit_relative_event() -> None:
    """g4v3 (A.5.3): state in bits 7 and 6, flags in bits 0 to 5, then the offset."""
    handler = DefaultSOEHandler()
    info = _process(_cto(_CTO_MS) + _relative(4, [(3, 0x81, 42)]), handler)

    value = handler.double_bit_inputs[3]
    assert (value.state, value.quality) == (DoubleBitState.ON, 0x01)
    assert value.timestamp == _CTO + timedelta(milliseconds=42)
    assert info.relative_time_without_cto == 0


def test_each_cto_applies_to_the_objects_after_it() -> None:
    """A.24.1 figure: an object's time is relative to the immediately preceding CTO.

    The second CTO is earlier in time, so an object timed from the wrong CTO fails.
    A CTO between two same-kind blocks does not split their callback.
    """
    second_cto_ms = _CTO_MS - 60_000
    objects = (
        _cto(_CTO_MS) + _relative(2, [(1, FLAGS_ON, 10)]) + _cto(second_cto_ms) + _relative(2, [(2, FLAGS_ON, 20)])
    )
    recorder = RecordingHandler()

    info = _process(objects, recorder)

    assert [(name, [(v.index, v.timestamp) for v in values]) for name, values in recorder.calls] == [
        (
            "on_binary_input",
            [
                (1, _CTO + timedelta(milliseconds=10)),
                (2, _EPOCH + timedelta(milliseconds=second_cto_ms + 20)),
            ],
        ),
    ]
    assert info.relative_time_without_cto == 0


def test_relative_event_without_cto_has_no_timestamp_and_is_counted() -> None:
    """No CTO precedes the objects: no time is synthesized, and the response counts them."""
    handler = DefaultSOEHandler()
    info = _process(_relative(2, [(1, FLAGS_ON, 1234), (2, 0x01, 5)]), handler)

    assert handler.binary_inputs[1].timestamp is None
    assert handler.binary_inputs[2].timestamp is None
    assert handler.binary_inputs[1].value is True
    assert info.relative_time_without_cto == 2


def test_cto_applies_only_to_objects_after_it() -> None:
    """An object before the fragment's first CTO has no base; the one after it does."""
    handler = DefaultSOEHandler()
    objects = _relative(2, [(1, FLAGS_ON, 7)]) + _cto(_CTO_MS) + _relative(4, [(3, 0x81, 7)])

    info = _process(objects, handler)

    assert handler.binary_inputs[1].timestamp is None
    assert handler.double_bit_inputs[3].timestamp == _CTO + timedelta(milliseconds=7)
    assert info.relative_time_without_cto == 1


def test_cto_does_not_carry_into_the_next_fragment() -> None:
    """A CTO in one response is not the base for a relative object in the next."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    first = master.process_response(RESPONSE_HEADER + _cto(_CTO_MS) + _relative(2, [(1, FLAGS_ON, 1)]))
    second = master.process_response(RESPONSE_HEADER + _relative(2, [(2, FLAGS_ON, 1)]))

    assert first is not None
    assert second is not None
    assert handler.binary_inputs[1].timestamp == _CTO + timedelta(milliseconds=1)
    assert handler.binary_inputs[2].timestamp is None
    assert (first.relative_time_without_cto, second.relative_time_without_cto) == (0, 1)


def test_unsynchronized_cto_gives_the_same_arithmetic() -> None:
    """A.24.2: g51v2 differs from g51v1 only in the outstation's synchronization state."""
    handler = DefaultSOEHandler()
    info = _process(_cto(_CTO_MS, variation=2) + _relative(2, [(1, FLAGS_ON, 250)]), handler)

    assert handler.binary_inputs[1].timestamp == _CTO + timedelta(milliseconds=250)
    assert info.relative_time_without_cto == 0


def test_relative_offset_at_its_maximum() -> None:
    """The UINT16 offset is unsigned: 0xFFFF is 65535 ms after the CTO, not 1 ms before it."""
    handler = DefaultSOEHandler()
    _process(_cto(_CTO_MS) + _relative(2, [(1, FLAGS_ON, 0xFFFF)]), handler)

    assert handler.binary_inputs[1].timestamp == _CTO + timedelta(milliseconds=65535)


def test_unrepresentable_cto_is_not_replaced_by_an_earlier_one() -> None:
    """A CTO past year 9999 leaves its objects with no time, not the time of an older CTO."""
    handler = DefaultSOEHandler()
    past_year_9999 = int.from_bytes(bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]), "little")
    objects = _cto(_CTO_MS) + _cto(past_year_9999) + _relative(2, [(1, FLAGS_ON, 5)])

    info = _process(objects, handler)

    assert handler.binary_inputs[1].timestamp is None
    assert info.relative_time_without_cto == 1


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


def test_cto_header_with_no_objects_keeps_the_preceding_cto() -> None:
    """A g51 header with a count of 0 carries no CTO, so the one before it still applies."""
    handler = DefaultSOEHandler()
    empty_cto = bytes([51, 1, 0x07, 0x00])
    objects = _cto(_CTO_MS) + empty_cto + _relative(2, [(1, FLAGS_ON, 5)])

    info = _process(objects, handler)

    assert info.truncation is None
    assert handler.binary_inputs[1].timestamp == _CTO + timedelta(milliseconds=5)
    assert info.relative_time_without_cto == 0


def test_last_cto_of_a_multi_object_header_applies() -> None:
    """A g51 header of two objects: the second is the immediately preceding CTO.

    The second CTO is earlier in time, so an object timed from the first fails.
    """
    handler = DefaultSOEHandler()
    second_cto_ms = _CTO_MS - 60_000
    two_ctos = bytes([51, 1, 0x07, 0x02]) + _CTO_MS.to_bytes(6, "little") + second_cto_ms.to_bytes(6, "little")

    info = _process(two_ctos + _relative(2, [(1, FLAGS_ON, 5)]), handler)

    assert info.truncation is None
    assert handler.binary_inputs[1].timestamp == _EPOCH + timedelta(milliseconds=second_cto_ms + 5)
    assert info.relative_time_without_cto == 0


def test_unreadable_cto_is_not_replaced_by_an_earlier_one() -> None:
    """A g51 header whose range cannot be decoded (qualifier 0x06, no range) clears the CTO."""
    handler = DefaultSOEHandler()
    unreadable = bytes([51, 1, 0x06])
    objects = _cto(_CTO_MS) + unreadable + _relative(2, [(1, FLAGS_ON, 5)])

    info = _process(objects, handler)

    assert info.truncation is None
    assert handler.binary_inputs[1].timestamp is None
    assert info.relative_time_without_cto == 1


def test_cto_block_shorter_than_its_count_is_not_replaced_by_an_earlier_one() -> None:
    """A g51 block declaring one object with no data clears the CTO.

    The parser never frames such a block, so this builds the blocks directly.
    """
    recorder = RecordingHandler()
    blocks = [
        ObjectBlock(header=ObjectHeader(group=51, variation=1, qualifier=0x07), data=_cto(_CTO_MS)[3:]),
        ObjectBlock(header=ObjectHeader(group=51, variation=1, qualifier=0x07), data=bytes([0x01])),
        ObjectBlock(
            header=ObjectHeader(group=2, variation=3, qualifier=0x17), data=_relative(2, [(1, FLAGS_ON, 5)])[3:]
        ),
    ]
    info = response_info()

    Master(handler=recorder)._parse_response_objects(blocks, info)

    assert [(name, [(v.index, v.timestamp) for v in values]) for name, values in recorder.calls] == [
        ("on_binary_input", [(1, None)]),
    ]
    assert info.relative_time_without_cto == 1


class _CountAtCallback(RecordingHandler):
    """Records the relative_time_without_cto a callback sees when it runs."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[str, int]] = []

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self.seen.append(("on_binary_input", info.relative_time_without_cto))

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self.seen.append(("on_analog_input", info.relative_time_without_cto))


def test_callback_sees_the_count_so_far() -> None:
    """Each callback sees the objects counted up to and including its own run."""
    analog = bytes([30, 1, 0x17, 0x01, 0x07, 0x01]) + struct.pack("<i", 200)
    objects = _relative(2, [(1, FLAGS_ON, 5)]) + analog + _relative(2, [(2, FLAGS_ON, 5), (3, FLAGS_ON, 6)])
    handler = _CountAtCallback()

    info = _process(objects, handler)

    assert handler.seen == [("on_binary_input", 1), ("on_analog_input", 1), ("on_binary_input", 3)]
    assert info.relative_time_without_cto == 3


def test_relative_time_past_year_9999_has_no_timestamp_and_is_counted() -> None:
    """A CTO 1 s before the last representable instant plus 5000 ms: no time, no crash, counted."""
    handler = DefaultSOEHandler()
    objects = _cto(_MAX_MS - 999) + _relative(2, [(1, FLAGS_ON, 5000)])

    info = _process(objects, handler)

    assert handler.binary_inputs[1].timestamp is None
    assert handler.binary_inputs[1].value is True
    assert info.relative_time_without_cto == 1
