"""Values reach the handler in the order their objects appear in the response fragment.

IEEE 1815-2012 5.1.5.1.3 has the master process objects in fragment order, and
5.1.5.1.1 has binary and double-bit events interleaved in time order even when
no time is reported. Consecutive blocks of one point kind share one callback;
a change of kind starts the next one. Every response is built by hand and run
through ``Master.process_response``.
"""

import struct
from datetime import UTC, datetime, timedelta

from dnp3.core.flags import DoubleBitState
from dnp3.master import DoubleBitInputHandler, DoubleBitValue, Master
from dnp3.master.handler import AnalogValue, BinaryValue, CounterValue, ResponseInfo, SOEHandler
from tests.unit.master.delivery import RecordingHandler

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices. 0x17: 1-octet count, 1-octet index prefix.
RANGE_8 = 0x00
COUNT_8_INDEX_8 = 0x17

ONLINE = 0x01
# Online with the state bit (binary, bit 7) or DETERMINED_ON state bits (double-bit, bits 7 and 6).
ONLINE_ON = 0x81
# Online with DETERMINED_OFF state bits for a double-bit flag octet.
ONLINE_DBI_OFF = 0x41

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_BASE_MS = 1_700_000_000_000


def _event_ms(minutes: int, seconds: int) -> int:
    return _BASE_MS + (minutes * 60 + seconds) * 1000


def _time(ms: int) -> bytes:
    return ms.to_bytes(6, "little")


def _at(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


class OrderRecorder(RecordingHandler):
    """Records every callback, double-bit included, in one list in call order."""

    def __init__(self) -> None:
        super().__init__()
        self.sequence: list[tuple[str, list[object]]] = []

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        super().on_binary_input(values, info)
        self.sequence.append(("on_binary_input", list(values)))

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        super().on_analog_input(values, info)
        self.sequence.append(("on_analog_input", list(values)))

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        super().on_counter(values, info)
        self.sequence.append(("on_counter", list(values)))

    def on_double_bit_input(self, values: list[DoubleBitValue], info: ResponseInfo) -> None:
        self.sequence.append(("on_double_bit_input", list(values)))


def _events(group: int, variation: int, *objects: tuple[int, bytes]) -> bytes:
    """One count-and-prefix header carrying (index, object octets) pairs."""
    body = bytes([group, variation, COUNT_8_INDEX_8, len(objects)])
    for index, octets in objects:
        body += bytes([index]) + octets
    return body


def _range(group: int, variation: int, start: int, stop: int, objects: bytes) -> bytes:
    return bytes([group, variation, RANGE_8, start, stop]) + objects


def _process(handler: SOEHandler, body: bytes) -> None:
    master = Master(handler=handler)
    assert master.process_response(RESPONSE_HEADER + body) is not None


class TestMixedKindsKeepWireOrder:
    def test_binary_and_double_bit_events_interleave_as_in_table_5_3(self) -> None:
        # The response column of IEEE 1815-2012 Table 5-3: five headers, two of g2v1,
        # because the time sequence splits them.
        dbi10, bi2, dbi12 = _event_ms(2, 34), _event_ms(2, 50), _event_ms(2, 51)
        body = (
            _events(4, 2, (10, bytes([ONLINE_ON]) + _time(dbi10)))
            + _events(2, 1, (14, bytes([ONLINE])), (25, bytes([ONLINE_ON])))
            + _events(2, 2, (2, bytes([ONLINE_ON]) + _time(bi2)))
            + _events(4, 2, (12, bytes([ONLINE_DBI_OFF]) + _time(dbi12)))
            + _events(2, 1, (25, bytes([ONLINE])), (14, bytes([ONLINE_ON])), (25, bytes([ONLINE_ON])))
        )
        handler = OrderRecorder()

        _process(handler, body)

        assert handler.sequence == [
            (
                "on_double_bit_input",
                [DoubleBitValue(index=10, state=DoubleBitState.ON, quality=ONLINE, timestamp=_at(dbi10))],
            ),
            (
                "on_binary_input",
                [
                    BinaryValue(index=14, value=False, quality=ONLINE),
                    BinaryValue(index=25, value=True, quality=ONLINE),
                    BinaryValue(index=2, value=True, quality=ONLINE, timestamp=_at(bi2)),
                ],
            ),
            (
                "on_double_bit_input",
                [DoubleBitValue(index=12, state=DoubleBitState.OFF, quality=ONLINE, timestamp=_at(dbi12))],
            ),
            (
                "on_binary_input",
                [
                    BinaryValue(index=25, value=False, quality=ONLINE),
                    BinaryValue(index=14, value=True, quality=ONLINE),
                    BinaryValue(index=25, value=True, quality=ONLINE),
                ],
            ),
        ]

    def test_binary_analog_and_counter_blocks_are_delivered_in_block_order(self) -> None:
        body = (
            _events(2, 1, (1, bytes([ONLINE_ON])))
            + _events(32, 1, (5, bytes([ONLINE]) + struct.pack("<i", -500)))
            + _events(2, 1, (2, bytes([ONLINE])))
            + _events(22, 1, (7, bytes([ONLINE]) + struct.pack("<I", 700)))
            + _events(32, 1, (6, bytes([ONLINE]) + struct.pack("<i", 600)))
            + _events(2, 1, (3, bytes([ONLINE_ON])))
        )
        handler = OrderRecorder()

        _process(handler, body)

        assert handler.sequence == [
            ("on_binary_input", [BinaryValue(index=1, value=True, quality=ONLINE)]),
            ("on_analog_input", [AnalogValue(index=5, value=-500.0, quality=ONLINE)]),
            ("on_binary_input", [BinaryValue(index=2, value=False, quality=ONLINE)]),
            ("on_counter", [CounterValue(index=7, value=700, quality=ONLINE)]),
            ("on_analog_input", [AnalogValue(index=6, value=600.0, quality=ONLINE)]),
            ("on_binary_input", [BinaryValue(index=3, value=True, quality=ONLINE)]),
        ]

    def test_handler_without_double_bit_callback_gets_its_other_runs_in_order(self) -> None:
        handler = RecordingHandler()
        assert not isinstance(handler, DoubleBitInputHandler)
        body = (
            _range(1, 2, 0, 0, bytes([ONLINE_ON]))
            + _range(3, 2, 0, 0, bytes([ONLINE_ON]))
            + _range(30, 1, 4, 4, bytes([ONLINE]) + struct.pack("<i", 40))
            + _range(1, 2, 1, 1, bytes([ONLINE]))
        )

        _process(handler, body)

        assert handler.calls == [
            ("on_binary_input", [BinaryValue(index=0, value=True, quality=ONLINE)]),
            ("on_analog_input", [AnalogValue(index=4, value=40.0, quality=ONLINE)]),
            ("on_binary_input", [BinaryValue(index=1, value=False, quality=ONLINE)]),
        ]


class TestRunsOfOneKind:
    def test_single_kind_response_makes_exactly_one_call(self) -> None:
        # Static and event blocks of one kind, with and without time, still share one call.
        bi9 = _event_ms(3, 5)
        body = (
            _events(2, 1, (9, bytes([ONLINE_ON])))
            + _range(1, 2, 0, 1, bytes([ONLINE, ONLINE_ON]))
            + _events(2, 2, (4, bytes([ONLINE]) + _time(bi9)))
        )
        handler = OrderRecorder()

        _process(handler, body)

        assert handler.sequence == [
            (
                "on_binary_input",
                [
                    BinaryValue(index=9, value=True, quality=ONLINE),
                    BinaryValue(index=0, value=False, quality=ONLINE),
                    BinaryValue(index=1, value=True, quality=ONLINE),
                    BinaryValue(index=4, value=False, quality=ONLINE, timestamp=_at(bi9)),
                ],
            ),
        ]

    def test_blocks_with_no_delivery_do_not_split_a_run(self) -> None:
        # g34v1 (analog deadband) and g50v1 (absolute time) are framed but not delivered.
        body = (
            _range(30, 1, 0, 0, bytes([ONLINE]) + struct.pack("<i", 10))
            + _range(34, 1, 0, 0, struct.pack("<H", 100))
            + _range(30, 1, 1, 1, bytes([ONLINE]) + struct.pack("<i", 11))
            + (bytes([50, 1, 0x07, 1]) + _time(_BASE_MS))
            + _range(30, 1, 2, 2, bytes([ONLINE]) + struct.pack("<i", 12))
        )
        handler = OrderRecorder()

        _process(handler, body)

        assert handler.sequence == [
            (
                "on_analog_input",
                [
                    AnalogValue(index=0, value=10.0, quality=ONLINE),
                    AnalogValue(index=1, value=11.0, quality=ONLINE),
                    AnalogValue(index=2, value=12.0, quality=ONLINE),
                ],
            ),
        ]
