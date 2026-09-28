"""Double-bit binary inputs (g3v1, g3v2) and events (g4v1 to g4v3) through ``Master.process_response``.

Expected values come from IEEE 1815-2012: the state values from 11.9.6 and
Table 11-14 (p. 345), the g3v1 packing from A.4.1.2.2 (p. 493), the flag
octet from A.4.2.2.2 (p. 494) and the event layouts from A.5 (pp. 495-497).
Every response is built by hand.
"""

from datetime import UTC, datetime

import pytest

from dnp3.core.flags import DoubleBitState
from dnp3.master import DefaultSOEHandler, DoubleBitInputHandler, DoubleBitValue, Master
from dnp3.master.handler import BinaryValue, ResponseInfo, SOEHandler
from tests.unit.master.delivery import RecordingHandler

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices.
RANGE_8 = 0x00
# Qualifier 0x17: 1-octet count, 1-octet index prefix.
COUNT_8_INDEX_8 = 0x17

ONLINE = 0x01


class DoubleBitRecorder(RecordingHandler):
    """Records SOE callbacks as RecordingHandler does, and double-bit callbacks separately."""

    def __init__(self) -> None:
        super().__init__()
        self.double_bit_calls: list[list[DoubleBitValue]] = []

    def on_double_bit_input(self, values: list[DoubleBitValue], info: ResponseInfo) -> None:
        self.double_bit_calls.append(list(values))


def _range_block(group: int, variation: int, start: int, stop: int, objects: bytes) -> bytes:
    return bytes([group, variation, RANGE_8, start, stop]) + objects


def _process(handler: SOEHandler, body: bytes) -> None:
    master = Master(handler=handler)
    assert master.process_response(RESPONSE_HEADER + body) is not None


class TestG3v2FlagOctet:
    """A.4.2.2.2: flags in bits 0 to 5, the UINT2 state in bits 7 and 6."""

    @pytest.mark.parametrize(
        ("octet", "state"),
        [
            (0x01, DoubleBitState.INTERMEDIATE),  # state bits 00
            (0x41, DoubleBitState.OFF),  # state bits 01: DETERMINED_OFF
            (0x81, DoubleBitState.ON),  # state bits 10: DETERMINED_ON
            (0xC1, DoubleBitState.INDETERMINATE),  # state bits 11
        ],
        ids=["0x01", "0x41", "0x81", "0xC1"],
    )
    def test_state_bits_give_each_of_the_four_states(self, octet: int, state: DoubleBitState) -> None:
        handler = DoubleBitRecorder()

        _process(handler, _range_block(3, 2, 0, 0, bytes([octet])))

        assert handler.double_bit_calls == [[DoubleBitValue(index=0, state=state, quality=ONLINE)]]
        assert handler.calls == []

    def test_quality_keeps_the_six_flag_bits_and_drops_the_state(self) -> None:
        # 0xE3: state 11, CHATTER_FILTER (bit 5), RESTART (bit 1), ONLINE (bit 0).
        handler = DoubleBitRecorder()

        _process(handler, _range_block(3, 2, 7, 7, bytes([0xE3])))

        assert handler.double_bit_calls == [[DoubleBitValue(index=7, state=DoubleBitState.INDETERMINATE, quality=0x23)]]

    def test_index_prefixed_objects_take_their_own_index(self) -> None:
        handler = DoubleBitRecorder()
        body = bytes([3, 2, COUNT_8_INDEX_8, 2, 9, 0x81, 4, 0x41])

        _process(handler, body)

        assert handler.double_bit_calls == [
            [
                DoubleBitValue(index=9, state=DoubleBitState.ON, quality=ONLINE),
                DoubleBitValue(index=4, state=DoubleBitState.OFF, quality=ONLINE),
            ]
        ]


class TestG3v1Packed:
    """A.4.1.2.2: two bits per point, first point in bits 1 and 0, last octet padded."""

    def test_five_points_in_two_octets(self) -> None:
        # 0xE4 = 11 10 01 00 gives points 0 to 3 as 0, 1, 2, 3; 0x01 gives point 4 as 1.
        # 0xE4 is not a palindrome of pairs, so reading pairs from the top reads 3, 2, 1, 0.
        handler = DoubleBitRecorder()

        _process(handler, _range_block(3, 1, 0, 4, bytes([0xE4, 0x01])))

        expected_states = [
            DoubleBitState.INTERMEDIATE,
            DoubleBitState.OFF,
            DoubleBitState.ON,
            DoubleBitState.INDETERMINATE,
            DoubleBitState.OFF,
        ]
        assert handler.double_bit_calls == [
            [DoubleBitValue(index=i, state=s, quality=ONLINE) for i, s in enumerate(expected_states)]
        ]

    def test_indexes_start_at_the_range_start_and_padding_is_ignored(self) -> None:
        # Points 3 to 5; the last octet's unused pair is non-zero and still not a point.
        handler = DoubleBitRecorder()

        _process(handler, _range_block(3, 1, 3, 5, bytes([0b11_10_01_10])))

        assert handler.double_bit_calls == [
            [
                DoubleBitValue(index=3, state=DoubleBitState.ON, quality=ONLINE),
                DoubleBitValue(index=4, state=DoubleBitState.OFF, quality=ONLINE),
                DoubleBitValue(index=5, state=DoubleBitState.ON, quality=ONLINE),
            ]
        ]

    def test_index_prefixed_packed_block_delivers_nothing(self) -> None:
        # A.4.1 defines packing only over a contiguous index range.
        handler = DoubleBitRecorder()

        _process(handler, bytes([3, 1, COUNT_8_INDEX_8, 1, 5, 0x02]))

        assert handler.double_bit_calls == []


class TestG4Events:
    """A.5: the g3v2 flag octet, then DNP3TIME (g4v2) or a UINT16 relative time (g4v3)."""

    def test_g4v1_state_and_flags(self) -> None:
        # 0x63: state 01 (DETERMINED_OFF), CHATTER_FILTER, RESTART, ONLINE.
        handler = DoubleBitRecorder()

        _process(handler, bytes([4, 1, COUNT_8_INDEX_8, 2, 5, 0x63, 6, 0x81]))

        assert handler.double_bit_calls == [
            [
                DoubleBitValue(index=5, state=DoubleBitState.OFF, quality=0x23),
                DoubleBitValue(index=6, state=DoubleBitState.ON, quality=ONLINE),
            ]
        ]

    def test_g4v2_absolute_time(self) -> None:
        # DNP3TIME 1700000000123 ms, little-endian UINT48 (11.3): 2023-11-14 22:13:20.123 UTC.
        time_octets = bytes([0x7B, 0x68, 0xE5, 0xCF, 0x8B, 0x01])
        handler = DoubleBitRecorder()

        _process(handler, bytes([4, 2, COUNT_8_INDEX_8, 1, 9, 0xC1]) + time_octets)

        assert handler.double_bit_calls == [
            [
                DoubleBitValue(
                    index=9,
                    state=DoubleBitState.INDETERMINATE,
                    quality=ONLINE,
                    timestamp=datetime(2023, 11, 14, 22, 13, 20, 123000, tzinfo=UTC),
                )
            ]
        ]

    def test_g4v3_relative_time_gives_no_timestamp(self) -> None:
        # The UINT16 is relative to a CTO object, so it is not a time on its own;
        # the second object shows each one is 3 octets wide.
        handler = DoubleBitRecorder()

        _process(handler, bytes([4, 3, COUNT_8_INDEX_8, 2, 1, 0x81, 0x34, 0x12, 2, 0x41, 0xFF, 0xFF]))

        assert handler.double_bit_calls == [
            [
                DoubleBitValue(index=1, state=DoubleBitState.ON, quality=ONLINE, timestamp=None),
                DoubleBitValue(index=2, state=DoubleBitState.OFF, quality=ONLINE, timestamp=None),
            ]
        ]


class TestDelivery:
    """Double-bit values reach only a handler with the callback, beside other kinds."""

    def test_g3v2_then_g1v2_both_delivered(self) -> None:
        handler = DoubleBitRecorder()
        body = _range_block(3, 2, 0, 0, bytes([0x81])) + _range_block(1, 2, 0, 0, bytes([0x81]))

        _process(handler, body)

        assert handler.double_bit_calls == [[DoubleBitValue(index=0, state=DoubleBitState.ON, quality=ONLINE)]]
        assert handler.calls == [("on_binary_input", [BinaryValue(index=0, value=True, quality=ONLINE)])]

    def test_handler_without_the_callback_receives_nothing_and_does_not_raise(self) -> None:
        handler = RecordingHandler()
        assert not isinstance(handler, DoubleBitInputHandler)
        body = _range_block(3, 2, 0, 0, bytes([0x81])) + _range_block(1, 2, 0, 0, bytes([0x01]))

        _process(handler, body)

        assert handler.calls == [("on_binary_input", [BinaryValue(index=0, value=False, quality=ONLINE)])]

    def test_default_handler_stores_values_by_index(self) -> None:
        handler = DefaultSOEHandler()
        assert isinstance(handler, DoubleBitInputHandler)

        _process(handler, _range_block(3, 1, 0, 4, bytes([0xE4, 0x01])))

        stored = handler.double_bit_inputs
        assert sorted(stored) == [0, 1, 2, 3, 4]
        assert stored[3] == DoubleBitValue(index=3, state=DoubleBitState.INDETERMINATE, quality=ONLINE)
        assert handler.last_response is not None

        handler.clear()
        assert handler.double_bit_inputs == {}
