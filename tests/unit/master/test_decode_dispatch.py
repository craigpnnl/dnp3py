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
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN
from dnp3.master.handler import AnalogValue, BinaryValue, CounterValue, ResponseInfo
from dnp3.master.master import Master
from dnp3.objects.layout import LAYOUTS, PointKind

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices. 0x17: 1-octet count, 1-octet index prefix.
RANGE_8 = 0x00
COUNT_8_INDEX_8 = 0x17

# Non-zero time octets, so a decoder with the wrong stride reads a point from them.
TIME_OCTETS = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

PointValue = BinaryValue | AnalogValue | CounterValue

CALLBACK_BY_KIND = {
    PointKind.BINARY_INPUT: "on_binary_input",
    PointKind.BINARY_OUTPUT: "on_binary_output",
    PointKind.ANALOG_INPUT: "on_analog_input",
    PointKind.ANALOG_OUTPUT: "on_analog_output",
    PointKind.COUNTER: "on_counter",
    PointKind.FROZEN_COUNTER: "on_frozen_counter",
}


class RecordingHandler:
    """Records each callback as (name, values), in call order.

    Deliberately not a subclass of SOEHandler, so the master must call the
    instance's own methods rather than the protocol's.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[PointValue]]] = []

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self.calls.append(("on_binary_input", list(values)))

    def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self.calls.append(("on_binary_output", list(values)))

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self.calls.append(("on_analog_input", list(values)))

    def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self.calls.append(("on_analog_output", list(values)))

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.calls.append(("on_counter", list(values)))

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.calls.append(("on_frozen_counter", list(values)))


def _info() -> ResponseInfo:
    return ResponseInfo(function=FunctionCode.RESPONSE, iin=IIN(0), sequence=1)


def _block(group: int, variation: int, qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=group, variation=variation, qualifier=qualifier), data=data)


def _dispatch(*blocks: ObjectBlock) -> list[tuple[str, list[PointValue]]]:
    handler = RecordingHandler()
    master = Master(handler=handler)
    master._parse_response_objects(blocks, _info())
    return handler.calls


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


def _one_object(layout_width: int, *, has_flags: bool) -> bytes:
    """A single object of the given width: flag octet 0x01 if present, then zeros."""
    return (bytes([0x01]) if has_flags else b"") + bytes(layout_width - int(has_flags))


_DELIVERED_PAIRS = sorted(pair for pair, layout in LAYOUTS.items() if layout.point_kind in CALLBACK_BY_KIND)


class TestEveryDeliveredLayoutDecodes:
    """No layout row of a delivered kind is framed and then silently dropped."""

    def test_delivered_pairs_cover_every_delivered_kind(self) -> None:
        kinds = {LAYOUTS[pair].point_kind for pair in _DELIVERED_PAIRS}
        assert kinds == set(CALLBACK_BY_KIND)

    @pytest.mark.parametrize("pair", _DELIVERED_PAIRS, ids=lambda p: f"g{p[0]}v{p[1]}")
    def test_one_object_yields_one_value_on_the_kind_callback(self, pair: tuple[int, int]) -> None:
        layout = LAYOUTS[pair]
        if layout.is_packed:
            data = bytes([0, 0, 0x01])
        else:
            data = bytes([0, 0]) + _one_object(layout.width, has_flags=layout.has_flags)

        calls = _dispatch(_block(pair[0], pair[1], RANGE_8, data))

        assert len(calls) == 1
        name, values = calls[0]
        assert name == CALLBACK_BY_KIND[layout.point_kind]
        assert len(values) == 1
        assert values[0].index == 0


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
