"""The master reports a response cut short and delivers nothing from a short block.

Object bytes are composed from IEEE 1815-2012, not from this library's encoders:
g30v1 from A.14.1 (flag, INT32), g1v2 from A.2.2 (flag octet, state bit 7),
g22v1 from A.12.1 (flag, UINT32), g3v1 from A.4.1 (packed 2-bit states),
little-endian per 11.3.4, and qualifiers from Tables 4-3 and 4-5.
"""

import logging

import pytest

from dnp3.application.fragment import ObjectBlock, Truncation, TruncationReason
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.flags import DoubleBitState
from dnp3.master.double_bit import DoubleBitValue
from dnp3.master.handler import AnalogValue, BinaryValue, CounterValue, ResponseInfo
from dnp3.master.master import Master
from tests.unit.master.delivery import RecordingHandler, delivered, response_info

# FIR+FIN, seq 0, RESPONSE, IIN 00 00.
RESPONSE_HEADER = bytes([0xC0, 0x81, 0x00, 0x00])

# g1v2, start-stop 9..9, flag 0x81: index 9 on, online.
B1 = bytes([0x01, 0x02, 0x00, 0x09, 0x09, 0x81])
# g30v1, count 1, 1-octet index 7, flag 0x01, value 200.
G7 = bytes([0x1E, 0x01, 0x17, 0x01, 0x07, 0x01, 0xC8, 0x00, 0x00, 0x00])
# g30v1, count 3, one object: index 5, flag 0x01, value 100.
OVER_DECLARED_G30 = bytes([0x1E, 0x01, 0x17, 0x03, 0x05, 0x01, 0x64, 0x00, 0x00, 0x00])

BINARY_9_ON = {9: (True, 0x01)}


class Recorder:
    """Records (index, value, quality) per callback, and every ResponseInfo passed."""

    def __init__(self) -> None:
        self.values: dict[str, list[tuple[int, object, int]]] = {}
        self.infos: list[ResponseInfo] = []

    def _record(
        self, name: str, values: list[BinaryValue] | list[AnalogValue] | list[CounterValue], info: ResponseInfo
    ) -> None:
        self.values.setdefault(name, []).extend((v.index, v.value, v.quality) for v in values)
        self.infos.append(info)

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self._record("binary_input", values, info)

    def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self._record("binary_output", values, info)

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self._record("analog_input", values, info)

    def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self._record("analog_output", values, info)

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self._record("counter", values, info)

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self._record("frozen_counter", values, info)


def process(objects: bytes, header: bytes = RESPONSE_HEADER) -> tuple[ResponseInfo, Recorder]:
    recorder = Recorder()
    info = Master(handler=recorder).process_response(header + objects)
    assert info is not None
    return info, recorder


def by_index(recorder: Recorder, name: str) -> dict[int, tuple[object, int]]:
    return {index: (value, quality) for index, value, quality in recorder.values.get(name, [])}


class TestDetectedFaultKeepsEarlierBlocks:
    """A block the parser cannot frame delivers nothing, and the caller is told why."""

    def test_over_declared_first_block(self) -> None:
        info, recorder = process(OVER_DECLARED_G30 + G7)

        assert recorder.values == {}
        assert info.truncation == Truncation(
            reason=TruncationReason.DATA_SHORTER_THAN_DECLARED, offset=0, group=30, variation=1, qualifier=0x17
        )

    def test_over_declared_after_a_valid_block(self) -> None:
        info, recorder = process(B1 + OVER_DECLARED_G30 + G7)

        assert recorder.values == {"binary_input": [(9, True, 0x01)]}
        expected = Truncation(
            reason=TruncationReason.DATA_SHORTER_THAN_DECLARED, offset=6, group=30, variation=1, qualifier=0x17
        )
        assert info.truncation == expected
        # The handler sees the same signal as the caller of process_response.
        assert [delivered_info.truncation for delivered_info in recorder.infos] == [expected]

    @pytest.mark.parametrize("stop", [0x04, 0x03], ids=["stop-is-start-minus-1", "stop-is-start-minus-2"])
    def test_range_names_no_object(self, stop: int) -> None:
        refused = bytes([0x1E, 0x01, 0x00, 0x05, stop, 0x01, 0x10, 0x00, 0x00, 0x00])
        info, recorder = process(B1 + refused + G7)

        assert by_index(recorder, "binary_input") == BINARY_9_ON
        assert set(recorder.values) == {"binary_input"}
        assert info.truncation == Truncation(
            reason=TruncationReason.RANGE_NAMES_NO_OBJECT, offset=6, group=30, variation=1, qualifier=0x00
        )

    def test_unknown_variation(self) -> None:
        """A.14 defines g30 variations 1 to 6 only."""
        unknown = bytes([0x1E, 0x63, 0x00, 0x00, 0x00, 0x01, 0x64, 0x00, 0x00, 0x00])
        info, recorder = process(B1 + unknown + G7)

        assert recorder.values == {"binary_input": [(9, True, 0x01)]}
        assert info.truncation == Truncation(
            reason=TruncationReason.UNKNOWN_WIDTH, offset=6, group=30, variation=99, qualifier=0x00
        )

    def test_short_last_block(self) -> None:
        short = bytes([0x1E, 0x01, 0x00, 0x00, 0x02, 0x01, 0x64, 0x00, 0x00, 0x00])
        info, recorder = process(B1 + short)

        assert recorder.values == {"binary_input": [(9, True, 0x01)]}
        assert info.truncation == Truncation(
            reason=TruncationReason.DATA_SHORTER_THAN_DECLARED, offset=6, group=30, variation=1, qualifier=0x00
        )

    def test_trailing_octets(self) -> None:
        # One octet is left after the last block, too few for an object header.
        info, recorder = process(B1 + bytes([0x1E]))

        assert recorder.values == {"binary_input": [(9, True, 0x01)]}
        assert info.truncation == Truncation(reason=TruncationReason.TRAILING_OCTETS, offset=6)
        assert (info.truncation.group, info.truncation.variation, info.truncation.qualifier) == (None, None, None)


class TestTruncationIsLogged:
    """A truncation is logged, because an unsolicited fragment's ResponseInfo may reach no caller."""

    def test_truncated_response_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="dnp3.master.master"):
            process(B1 + OVER_DECLARED_G30 + G7)

        warnings = [r for r in caplog.records if r.name == "dnp3.master.master" and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        for part in ("data_shorter_than_declared", "offset 6", "group 30", "variation 1", "qualifier 0x17"):
            assert part in message

    def test_complete_response_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        matching = bytes([0x1E, 0x01, 0x17, 0x01, 0x05, 0x01, 0x64, 0x00, 0x00, 0x00])
        with caplog.at_level(logging.DEBUG, logger="dnp3.master.master"):
            info, _ = process(matching + G7)

        assert info.truncation is None
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


class TestValidFramesUnchanged:
    """Frames the parser reads to the end deliver every value and carry no truncation."""

    def test_matching_count_delivers_both_blocks(self) -> None:
        matching = bytes([0x1E, 0x01, 0x17, 0x01, 0x05, 0x01, 0x64, 0x00, 0x00, 0x00])
        info, recorder = process(matching + G7)

        assert recorder.values == {"analog_input": [(5, 100.0, 0x01), (7, 200.0, 0x01)]}
        assert info.truncation is None

    def test_valid_three_point_frame(self) -> None:
        """A valid 3-point g30v1 block 0..2.

        These are also the bytes of a count-2 block whose over-declared data happens
        to fit inside the fragment, which no receiver can tell from a valid frame
        (4.2.2.7: object headers carry no length). Pinned so that no heuristic
        rejects a valid frame.
        """
        objects = bytes([0x1E, 0x01, 0x00, 0x00, 0x02, 0x01, 0x64, 0x00, 0x00, 0x00]) + bytes(
            [0x1E, 0x01, 0x00, 0x07, 0x07, 0x01, 0xC8, 0x00, 0x00, 0x00]
        )
        info, recorder = process(objects)

        assert recorder.values == {
            "analog_input": [(0, 100.0, 0x01), (1, 117899265.0, 0x1E), (2, 200.0, 0x01)],
        }
        assert info.truncation is None

    def test_ex_4_11_plus_counter_event(self) -> None:
        """EX 4-11 (clause 4, p. 44) response verbatim, plus one g22v1 block composed from A.12.1."""
        header = bytes([0xE3, 0x81, 0x06, 0x00])
        ex_4_11 = (
            bytes([0x02, 0x01, 0x17, 0x01, 0x14, 0x81])
            + bytes([0x02, 0x01, 0x17, 0x01, 0x05, 0x01])
            + bytes([0x20, 0x02, 0x17, 0x01, 0x0B, 0x20, 0xFF, 0xFF])
            + bytes([0x02, 0x01, 0x17, 0x01, 0x03, 0x81])
        )
        counter_event = bytes([0x16, 0x01, 0x17, 0x01, 0x02, 0x01, 0x78, 0x56, 0x34, 0x12])
        info, recorder = process(ex_4_11 + counter_event, header=header)

        assert recorder.values == {
            "binary_input": [(20, True, 0x01), (5, False, 0x01), (3, True, 0x01)],
            "analog_input": [(11, -1.0, 0x20)],
            "counter": [(2, 0x12345678, 0x01)],
        }
        assert info.truncation is None


class DoubleBitCollector(RecordingHandler):
    """Records double-bit callbacks, which only a handler with that method receives."""

    def __init__(self) -> None:
        super().__init__()
        self.double_bits: list[DoubleBitValue] = []

    def on_double_bit_input(self, values: list[DoubleBitValue], info: ResponseInfo) -> None:
        self.double_bits.extend(values)


def double_bits_delivered(block: ObjectBlock) -> list[DoubleBitValue]:
    handler = DoubleBitCollector()
    Master(handler=handler)._parse_response_objects([block], response_info())
    assert handler.calls == []
    return handler.double_bits


class TestShortBlockRefusedByDecoder:
    """A block handed to the master with less data than it declares delivers nothing.

    The parser never frames such a block, so these build the block directly.
    """

    def test_count_block_short_by_one_object(self) -> None:
        # g2v1, count 3, two (index, flag) objects present.
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=bytes([0x03, 0x00, 0x81, 0x01, 0x01]))

        assert delivered(block, "on_binary_input") == []

    def test_packed_block_short_by_one_octet(self) -> None:
        # g1v1, start-stop 0..17: 18 points need 3 octets, 2 present.
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x11, 0x0F, 0xAA]))

        assert delivered(block, "on_binary_input") == []

    def test_complete_blocks_deliver(self) -> None:
        """The same objects with a count and range that match their data are delivered."""
        count_block = ObjectBlock(
            header=ObjectHeader(group=2, variation=1, qualifier=0x17),
            data=bytes([0x02, 0x00, 0x81, 0x01, 0x01]),
        )
        packed_block = ObjectBlock(
            header=ObjectHeader(group=1, variation=1, qualifier=0x00),
            data=bytes([0x00, 0x0F, 0x0F, 0xAA]),
        )

        assert [(v.index, v.value) for v in delivered(count_block, "on_binary_input")] == [(0, True), (1, False)]
        packed = delivered(packed_block, "on_binary_input")
        assert [v.index for v in packed] == list(range(16))
        assert [v.value for v in packed] == [True] * 4 + [False] * 4 + [False, True] * 4

    def test_packed_double_bit_block_short_by_one_octet(self) -> None:
        # g3v1, start-stop 0..7: 8 two-bit points need 2 octets, 1 present.
        block = ObjectBlock(header=ObjectHeader(group=3, variation=1, qualifier=0x00), data=bytes([0x00, 0x07, 0xE4]))

        assert double_bits_delivered(block) == []

    def test_complete_packed_double_bit_block_delivers(self) -> None:
        # 0xE4 = 11 10 01 00: points in bits 1 and 0 first (A.4.1.2.2), so states 0, 1, 2, 3.
        block = ObjectBlock(
            header=ObjectHeader(group=3, variation=1, qualifier=0x00), data=bytes([0x00, 0x07, 0xE4, 0xE4])
        )

        states = [DoubleBitState(n) for n in (0, 1, 2, 3)] * 2
        assert double_bits_delivered(block) == [
            DoubleBitValue(index=index, state=state, quality=0x01) for index, state in enumerate(states)
        ]
