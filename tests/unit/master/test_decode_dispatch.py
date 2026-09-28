"""Tests for how the master routes decoded blocks to handler callbacks.

Each block is decoded by the point kind its (group, variation) layout names,
and each kind's values reach exactly one callback. Expected object bytes follow
the IEEE 1815-2012 Annex A formal structures (flag octet, little-endian value,
optional 6-octet DNP3TIME), built here with ``struct`` rather than the library's
encoders.
"""

import struct

import pytest

from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader
from dnp3.master.handler import AnalogValue, BinaryValue, CounterValue
from dnp3.master.master import Master
from dnp3.objects.layout import LAYOUTS, PointKind, ValueCodec, WireLayout
from tests.unit.master.delivery import PointValue, RecordingHandler, dispatch

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices. 0x17: 1-octet count, 1-octet index prefix.
RANGE_8 = 0x00
COUNT_8_INDEX_8 = 0x17

# Non-zero time octets, so a decoder with the wrong stride reads a point from them.
TIME_OCTETS = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

CALLBACK_BY_KIND = {
    PointKind.BINARY_INPUT: "on_binary_input",
    PointKind.BINARY_OUTPUT: "on_binary_output",
    PointKind.ANALOG_INPUT: "on_analog_input",
    PointKind.ANALOG_OUTPUT: "on_analog_output",
    PointKind.COUNTER: "on_counter",
    PointKind.FROZEN_COUNTER: "on_frozen_counter",
}


def _block(group: int, variation: int, qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=group, variation=variation, qualifier=qualifier), data=data)


def _dispatch(*blocks: ObjectBlock) -> list[tuple[str, list[PointValue]]]:
    return dispatch(blocks)


class TestRouting:
    """Every delivered kind reaches its own callback, in a fixed order."""

    def test_each_kind_reaches_its_callback_in_fixed_order(self) -> None:
        # Blocks arrive in the reverse of the callback order, which must not matter.
        calls = _dispatch(
            _block(21, 1, RANGE_8, bytes([4, 4, 0x01]) + struct.pack("<I", 21)),
            _block(20, 1, RANGE_8, bytes([3, 3, 0x01]) + struct.pack("<I", 20)),
            _block(40, 1, RANGE_8, bytes([2, 2, 0x01]) + struct.pack("<i", -40)),
            _block(30, 1, RANGE_8, bytes([1, 1, 0x01]) + struct.pack("<i", 30)),
            _block(10, 2, RANGE_8, bytes([6, 6, 0x81])),
            _block(1, 2, RANGE_8, bytes([5, 5, 0x01])),
        )

        assert calls == [
            ("on_binary_input", [BinaryValue(index=5, value=False, quality=0x01)]),
            ("on_binary_output", [BinaryValue(index=6, value=True, quality=0x01)]),
            ("on_analog_input", [AnalogValue(index=1, value=30.0, quality=0x01)]),
            ("on_analog_output", [AnalogValue(index=2, value=-40.0, quality=0x01)]),
            ("on_counter", [CounterValue(index=3, value=20, quality=0x01)]),
            ("on_frozen_counter", [CounterValue(index=4, value=21, quality=0x01)]),
        ]

    def test_static_and_event_blocks_of_one_kind_share_one_call_in_block_order(self) -> None:
        calls = _dispatch(
            _block(2, 1, COUNT_8_INDEX_8, bytes([1, 9, 0x81])),
            _block(22, 1, COUNT_8_INDEX_8, bytes([1, 7, 0x01]) + struct.pack("<I", 700)),
            _block(1, 2, RANGE_8, bytes([0, 0, 0x01])),
            _block(20, 5, RANGE_8, bytes([2, 2]) + struct.pack("<I", 200)),
        )

        assert calls == [
            (
                "on_binary_input",
                [BinaryValue(index=9, value=True, quality=0x01), BinaryValue(index=0, value=False, quality=0x01)],
            ),
            (
                "on_counter",
                [CounterValue(index=7, value=700, quality=0x01), CounterValue(index=2, value=200, quality=0x01)],
            ),
        ]

    @pytest.mark.parametrize(
        ("group", "variation", "data"),
        [
            (3, 1, bytes([0, 3, 0b01101100])),  # double-bit input, not delivered
            (12, 1, bytes([0, 0]) + bytes(11)),  # control relay output block
            (50, 1, bytes([0, 0]) + bytes(6)),  # absolute time
            (52, 2, bytes([0, 0]) + bytes(2)),  # time delay fine
            (60, 1, bytes([0, 0])),  # class 0
            (99, 1, bytes([0, 0, 0x01])),  # no layout at all
        ],
        ids=["g3v1", "g12v1", "g50v1", "g52v2", "g60v1", "g99v1"],
    )
    def test_block_whose_kind_has_no_delivery_invokes_no_callback(
        self, group: int, variation: int, data: bytes
    ) -> None:
        assert _dispatch(_block(group, variation, RANGE_8, data)) == []

    def test_undelivered_block_does_not_disturb_neighbours(self) -> None:
        calls = _dispatch(
            _block(1, 2, RANGE_8, bytes([0, 0, 0x81])),
            _block(3, 1, RANGE_8, bytes([0, 3, 0xFF])),
            _block(1, 2, RANGE_8, bytes([1, 1, 0x01])),
        )

        assert calls == [
            (
                "on_binary_input",
                [BinaryValue(index=0, value=True, quality=0x01), BinaryValue(index=1, value=False, quality=0x01)],
            ),
        ]

    def test_analog_output_status_reaches_handler_end_to_end(self) -> None:
        handler = RecordingHandler()
        master = Master(handler=handler)
        body = bytes([40, 2, RANGE_8, 0, 0, 0x01]) + struct.pack("<h", 777)

        assert master.process_response(RESPONSE_HEADER + body) is not None
        assert handler.calls == [("on_analog_output", [AnalogValue(index=0, value=777.0, quality=0x01)])]

    def test_g11v3_is_not_a_binary_output_event(self) -> None:
        # A.7 defines g11v1 and g11v2 only, so a flag octet and relative time here is not a point.
        assert _dispatch(_block(11, 3, COUNT_8_INDEX_8, bytes([1, 3, 0x81, 0x12, 0x34]))) == []

    @pytest.mark.parametrize("group", [1, 10], ids=["g1v1", "g10v1"])
    def test_packed_block_with_index_prefix_delivers_nothing(self, group: int) -> None:
        # A.2.1 and A.6.1 pack bits only over a contiguous range, so an index prefix leaves no bit layout.
        handler = RecordingHandler()
        master = Master(handler=handler)
        body = bytes([group, 1, COUNT_8_INDEX_8, 1, 5, 0xFF])

        assert master.process_response(RESPONSE_HEADER + body) is not None
        assert handler.calls == []


# Value octets per (codec, value width) and what they decode to: negative for signed codecs and
# above the signed range for unsigned ones, so a wrong width, sign or float format decodes otherwise.
_ROW_VALUES: dict[tuple[ValueCodec, int], tuple[bytes, float]] = {
    (ValueCodec.INT, 2): (struct.pack("<h", -1234), -1234),
    (ValueCodec.INT, 4): (struct.pack("<i", -100000), -100000),
    (ValueCodec.UINT, 2): (struct.pack("<H", 0xBEEF), 0xBEEF),
    (ValueCodec.UINT, 4): (struct.pack("<I", 0xDEADBEEF), 0xDEADBEEF),
    (ValueCodec.FLOAT32, 4): (struct.pack("<f", -2.25), -2.25),
    (ValueCodec.FLOAT64, 8): (struct.pack("<d", 2401.75), 2401.75),
}

# Flag octet: local forced and the state bit, which binary layouts report as the value. Online is
# clear, so a decoder that reads the online bit as state or defaults quality to online fails.
ROW_FLAGS = 0xA0
ROW_INDEX = 5


def _row_object(layout: WireLayout) -> tuple[bytes, PointValue]:
    """One object at ROW_INDEX with non-zero flags, value and time, and the value it must decode to."""
    kind = layout.point_kind
    if layout.is_packed:
        return bytes([0x01]), BinaryValue(index=ROW_INDEX, value=True, quality=0x01)
    if kind in {PointKind.BINARY_INPUT, PointKind.BINARY_OUTPUT}:
        return bytes([ROW_FLAGS]) + TIME_OCTETS[: layout.time.octets], BinaryValue(
            index=ROW_INDEX, value=True, quality=ROW_FLAGS & 0x7F
        )
    octets, value = _ROW_VALUES[(layout.codec, layout.value_width)]
    flags = bytes([ROW_FLAGS]) if layout.has_flags else b""
    quality = ROW_FLAGS if layout.has_flags else 0x01
    data = flags + octets + TIME_OCTETS[: layout.time.octets]
    if kind in {PointKind.ANALOG_INPUT, PointKind.ANALOG_OUTPUT}:
        return data, AnalogValue(index=ROW_INDEX, value=float(value), quality=quality)
    return data, CounterValue(index=ROW_INDEX, value=int(value), quality=quality)


_DELIVERED_PAIRS = sorted(pair for pair, layout in LAYOUTS.items() if layout.point_kind in CALLBACK_BY_KIND)


class TestEveryDeliveredLayoutDecodes:
    """No layout row of a delivered kind is framed and then silently dropped."""

    def test_delivered_pairs_cover_every_delivered_kind(self) -> None:
        kinds = {LAYOUTS[pair].point_kind for pair in _DELIVERED_PAIRS}
        assert kinds == set(CALLBACK_BY_KIND)

    @pytest.mark.parametrize("pair", _DELIVERED_PAIRS, ids=lambda p: f"g{p[0]}v{p[1]}")
    def test_one_object_yields_its_value_on_the_kind_callback(self, pair: tuple[int, int]) -> None:
        layout = LAYOUTS[pair]
        data, expected = _row_object(layout)

        calls = _dispatch(_block(pair[0], pair[1], RANGE_8, bytes([ROW_INDEX, ROW_INDEX]) + data))

        assert calls == [(CALLBACK_BY_KIND[layout.point_kind], [expected])]


class TestAnalogOutputValues:
    """Groups 40 (A.19) and 42 (A.21): flag octet, value, and for 42 v3, v4, v7, v8 a DNP3TIME.

    Two objects per block, so a wrong stride reads the second value from the
    first object's trailing octets.
    """

    @pytest.mark.parametrize(
        ("variation", "fmt", "first", "second"),
        [
            (1, "<i", -100000, 2401),  # A.19.1: INT32
            (2, "<h", -1234, 777),  # A.19.2: INT16
            (3, "<f", 1.5, -2.25),  # A.19.3: FLT32
            (4, "<d", -15.25, 2401.75),  # A.19.4: FLT64
        ],
    )
    def test_g40_status(self, variation: int, fmt: str, first: float, second: float) -> None:
        master = Master()
        data = bytes([3, 4, 0x01]) + struct.pack(fmt, first) + bytes([0x21]) + struct.pack(fmt, second)

        values = master._parse_analog_values(_block(40, variation, RANGE_8, data))

        assert values == [
            AnalogValue(index=3, value=first, quality=0x01),
            AnalogValue(index=4, value=second, quality=0x21),
        ]

    @pytest.mark.parametrize(
        ("variation", "fmt", "timed", "first", "second"),
        [
            (1, "<i", False, -100000, 2401),  # A.21.1
            (2, "<h", False, -1234, 777),  # A.21.2
            (3, "<i", True, -100000, 2401),  # A.21.3
            (4, "<h", True, -1234, 777),  # A.21.4
            (5, "<f", False, 1.5, -2.25),  # A.21.5
            (6, "<d", False, -15.25, 2401.75),  # A.21.6
            (7, "<f", True, 1.5, -2.25),  # A.21.7
            (8, "<d", True, -15.25, 2401.75),  # A.21.8
        ],
    )
    def test_g42_events(self, variation: int, fmt: str, timed: bool, first: float, second: float) -> None:
        master = Master()
        time = TIME_OCTETS if timed else b""
        data = (
            bytes([2, 9, 0x01]) + struct.pack(fmt, first) + time + bytes([0x42, 0x21]) + struct.pack(fmt, second) + time
        )

        values = master._parse_analog_values(_block(42, variation, COUNT_8_INDEX_8, data))

        assert values == [
            AnalogValue(index=9, value=first, quality=0x01),
            AnalogValue(index=0x42, value=second, quality=0x21),
        ]
