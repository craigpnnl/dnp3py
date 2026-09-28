"""Value-asserting tests for master response parsing.

These cover the input shapes that `test_master.py` does not: count qualifiers
(0x17 / 0x28) used by every event group, multi-block responses, timestamped
event variations, and float analog variations.

The distinction matters because the older tests assert only that parsing
*executes* (`len(values) >= 1`) on a single-block range-qualifier input. Every
assertion here is on the decoded index/value pair, so a parser that returns
confident wrong numbers fails instead of passing at 95% line coverage.

Regression cover for the response-parsing bugs reported in issue #30.
"""

import struct

import pytest

from dnp3.application.fragment import ObjectBlock
from dnp3.application.parser import parse_response
from dnp3.application.qualifiers import ObjectHeader
from dnp3.master.handler import ResponseInfo, SOEHandler
from dnp3.master.master import QUALITY_ONLINE, Master
from tests.unit.master.delivery import delivered, dispatch

# Flags byte: bit 7 = state, bit 0 = online.
FLAGS_ON = 0x81
FLAGS_OFF = 0x01

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])


class CollectingHandler(SOEHandler):
    """Records every value delivered, keyed by index, per data type."""

    def __init__(self) -> None:
        self.binary_inputs: dict[int, bool] = {}
        self.binary_outputs: dict[int, bool] = {}
        self.analog_inputs: dict[int, float] = {}
        self.analog_outputs: dict[int, float] = {}
        self.counters: dict[int, int] = {}
        self.frozen_counters: dict[int, int] = {}

    def on_binary_input(self, values, info: ResponseInfo) -> None:
        self.binary_inputs.update({v.index: v.value for v in values})

    def on_binary_output(self, values, info: ResponseInfo) -> None:
        self.binary_outputs.update({v.index: v.value for v in values})

    def on_analog_input(self, values, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})

    def on_analog_output(self, values, info: ResponseInfo) -> None:
        self.analog_outputs.update({v.index: v.value for v in values})

    def on_counter(self, values, info: ResponseInfo) -> None:
        self.counters.update({v.index: v.value for v in values})

    def on_frozen_counter(self, values, info: ResponseInfo) -> None:
        self.frozen_counters.update({v.index: v.value for v in values})


def indexed_values(values) -> dict[int, object]:
    """Collapse a parsed value list to {index: value} for comparison."""
    return {v.index: v.value for v in values}


class TestBinaryEventCountQualifiers:
    """Group 2 binary events use count + per-object index prefixes."""

    def test_uint8_count_uint8_index_g2v1(self) -> None:
        """Qualifier 0x17: 1-byte count, 1-byte index prefix per object."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        # count=3, then (index, flags) per event: non-consecutive indices.
        data = bytes([0x03, 0x00, FLAGS_ON, 0x01, FLAGS_OFF, 0x02, FLAGS_ON])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True, 1: False, 2: True}

    def test_uint8_count_honours_sparse_indices(self) -> None:
        """Index prefixes are read, not assumed consecutive from zero."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        data = bytes([0x02, 0x07, FLAGS_ON, 0x2A, FLAGS_OFF])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {7: True, 42: False}

    def test_uint16_count_uint16_index_g2v1(self) -> None:
        """Qualifier 0x28: 2-byte count, 2-byte index prefix per object."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x28)
        data = (
            (2).to_bytes(2, "little")
            + (5).to_bytes(2, "little")
            + bytes([FLAGS_ON])
            + (9).to_bytes(2, "little")
            + bytes([FLAGS_OFF])
        )
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {5: True, 9: False}

    def test_g2v2_absolute_timestamp_is_skipped(self) -> None:
        """g2v2 carries a 48-bit timestamp after the flags byte (7 bytes total)."""
        header = ObjectHeader(group=2, variation=2, qualifier=0x17)
        data = bytes([0x02]) + bytes([0x00, FLAGS_ON]) + bytes(6) + bytes([0x01, FLAGS_OFF]) + bytes(6)
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True, 1: False}

    def test_g2v3_relative_timestamp_is_skipped(self) -> None:
        """g2v3 carries a 16-bit relative time after the flags byte (3 bytes)."""
        header = ObjectHeader(group=2, variation=3, qualifier=0x17)
        data = bytes([0x01, 0x04, FLAGS_ON]) + (1234).to_bytes(2, "little")
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {4: True}

    def test_count_limits_objects_parsed(self) -> None:
        """A count smaller than the available data bounds the object loop."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        # count=1, but two objects' worth of bytes follow.
        data = bytes([0x01, 0x00, FLAGS_ON, 0x01, FLAGS_OFF])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True}

    def test_binary_output_events_g11v1(self) -> None:
        """Group 11 binary output events use the same count qualifiers."""
        header = ObjectHeader(group=11, variation=1, qualifier=0x17)
        data = bytes([0x02, 0x00, FLAGS_ON, 0x03, FLAGS_OFF])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_output")

        assert indexed_values(values) == {0: True, 3: False}


class TestBinaryEventVariationIsNotPacked:
    """Variation 1 means packed only for group 1 - never for event groups."""

    def test_g2v1_is_flags_per_point_not_packed_bits(self) -> None:
        """g2v1 is one flags byte per point; treating it as packed fabricates points."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x00)
        data = bytes([0, 1, FLAGS_ON, FLAGS_OFF])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True, 1: False}

    def test_g1v1_remains_packed(self) -> None:
        """Group 1 variation 1 is genuinely packed: 1 bit per point."""
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        data = bytes([0, 7, 0b10101010])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {
            0: False,
            1: True,
            2: False,
            3: True,
            4: False,
            5: True,
            6: False,
            7: True,
        }

    def test_g1v1_packed_respects_stop_index(self) -> None:
        """A packed block reports only the points the range declares."""
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        # Range 0-2 in a byte whose upper bits are set: only 3 points are real.
        data = bytes([0, 2, 0b11111101])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True, 1: False, 2: True}


class TestAnalogEventCountQualifiers:
    """Group 32 analog events, including timestamped and float variations."""

    def test_g32v1_count_qualifier(self) -> None:
        """One real analog event stays one point with its stored value."""
        header = ObjectHeader(group=32, variation=1, qualifier=0x17)
        data = bytes([0x01, 0x00, 0x01]) + struct.pack("<i", 2401)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert indexed_values(values) == {0: 2401.0}

    def test_g32v3_with_timestamp(self) -> None:
        """g32v3 is flags + 32-bit value + 48-bit timestamp (11 bytes)."""
        header = ObjectHeader(group=32, variation=3, qualifier=0x17)
        data = bytes([0x01, 0x05, 0x01]) + struct.pack("<i", -1500) + bytes(6)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert indexed_values(values) == {5: -1500.0}

    def test_g32v5_float_event(self) -> None:
        """g32v5 carries a float32 payload."""
        header = ObjectHeader(group=32, variation=5, qualifier=0x17)
        data = bytes([0x01, 0x02, 0x01]) + struct.pack("<f", 2401.7)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert values[0].index == 2
        assert values[0].value == pytest.approx(2401.7, abs=1e-3)

    def test_counter_event_g22v1_count_qualifier(self) -> None:
        """Group 22 counter events use count qualifiers too."""
        header = ObjectHeader(group=22, variation=1, qualifier=0x17)
        data = bytes([0x01, 0x03, 0x01]) + struct.pack("<I", 123456)
        values = delivered(ObjectBlock(header=header, data=data), "on_counter")

        assert indexed_values(values) == {3: 123456}


class TestAnalogFloatVariations:
    """Static float variations must not be dropped or truncated."""

    def test_g30v5_float32_preserves_fraction(self) -> None:
        header = ObjectHeader(group=30, variation=5, qualifier=0x00)
        data = bytes([0, 0, 0x01]) + struct.pack("<f", 2401.7)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert values[0].index == 0
        assert values[0].value == pytest.approx(2401.7, abs=1e-3)

    def test_g30v6_double64_preserves_fraction(self) -> None:
        header = ObjectHeader(group=30, variation=6, qualifier=0x00)
        data = bytes([0, 0, 0x01]) + struct.pack("<d", -15.25)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert indexed_values(values) == {0: -15.25}

    def test_g30v5_multiple_points(self) -> None:
        header = ObjectHeader(group=30, variation=5, qualifier=0x00)
        data = bytes([0, 1]) + bytes([0x01]) + struct.pack("<f", 1.5) + bytes([0x01]) + struct.pack("<f", -2.5)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert indexed_values(values) == {0: 1.5, 1: -2.5}

    def test_unsupported_variation_still_returns_empty(self) -> None:
        """An unknown variation yields nothing rather than garbage."""
        header = ObjectHeader(group=30, variation=100, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0, 0, 0x01, 0x02, 0x03]))

        assert delivered(block, "on_analog_input") == []


class TestMultiBlockResponses:
    """A response carrying N object blocks must yield N blocks."""

    def test_static_binary_and_analog_blocks(self) -> None:
        """g1v2 followed by g30v1: both blocks parse, neither absorbs the other."""
        body = (
            bytes([0x01, 0x02, 0x00, 0x00, 0x01, FLAGS_ON, FLAGS_OFF])
            + bytes([0x1E, 0x01, 0x00, 0x00, 0x00, 0x01])
            + struct.pack("<i", 2401)
        )
        fragment = parse_response(RESPONSE_HEADER + body)

        assert len(fragment.objects) == 2
        assert (fragment.objects[0].header.group, fragment.objects[0].header.variation) == (1, 2)
        assert (fragment.objects[1].header.group, fragment.objects[1].header.variation) == (30, 1)

    def test_multi_block_values_reach_handler(self) -> None:
        """End to end: both blocks' values arrive, with no fabricated points."""
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = (
            bytes([0x01, 0x02, 0x00, 0x00, 0x01, FLAGS_ON, FLAGS_OFF])
            + bytes([0x1E, 0x01, 0x00, 0x00, 0x00, 0x01])
            + struct.pack("<i", 2401)
        )

        assert master.process_response(RESPONSE_HEADER + body) is not None
        assert handler.binary_inputs == {0: True, 1: False}
        assert handler.analog_inputs == {0: 2401.0}

    def test_three_blocks_including_event_group(self) -> None:
        """Mixed static + event + counter blocks all survive."""
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = (
            bytes([0x01, 0x02, 0x00, 0x00, 0x00, FLAGS_ON])
            + bytes([0x02, 0x01, 0x17, 0x01, 0x04, FLAGS_OFF])
            + bytes([0x14, 0x01, 0x00, 0x00, 0x00, 0x01])
            + struct.pack("<I", 99)
        )
        fragment = parse_response(RESPONSE_HEADER + body)
        assert len(fragment.objects) == 3

        master.process_response(RESPONSE_HEADER + body)
        assert handler.binary_inputs == {0: True, 4: False}
        assert handler.counters == {0: 99}

    def test_trailing_garbage_does_not_corrupt_earlier_blocks(self) -> None:
        """A truncated trailing block leaves complete blocks intact."""
        body = (
            bytes([0x01, 0x02, 0x00, 0x00, 0x00, FLAGS_ON]) + bytes([0x1E])  # truncated next header
        )
        fragment = parse_response(RESPONSE_HEADER + body)

        assert len(fragment.objects) == 1
        assert fragment.objects[0].data == bytes([0x00, 0x00, FLAGS_ON])

    def test_unregistered_trailing_block_is_not_dropped(self) -> None:
        """A g40 block after a known block is reachable via its variation size."""
        body = (
            bytes([0x01, 0x02, 0x00, 0x00, 0x00, FLAGS_ON])
            + bytes([0x28, 0x02, 0x00, 0x00, 0x00, 0x01])
            + struct.pack("<h", 777)
        )
        fragment = parse_response(RESPONSE_HEADER + body)

        assert len(fragment.objects) == 2
        assert fragment.objects[1].header.group == 40


class TestMalformedBlocks:
    """Unsupported or truncated blocks yield nothing rather than garbage."""

    def test_reserved_range_code_yields_no_values(self) -> None:
        """A reserved range specifier (0x0C) is not decodable."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x0C)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, FLAGS_ON]))

        assert delivered(block, "on_binary_input") == []

    def test_size_prefix_yields_no_values(self) -> None:
        """Size prefixes (0x40+) describe variable-format objects we do not parse."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x47)
        block = ObjectBlock(header=header, data=bytes([0x01, 0x01, FLAGS_ON]))

        assert delivered(block, "on_binary_input") == []

    def test_truncated_count_field_yields_no_values(self) -> None:
        """A 2-byte count field needs 2 bytes."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x28)
        block = ObjectBlock(header=header, data=bytes([0x01]))

        assert delivered(block, "on_binary_input") == []

    def test_truncated_start_stop_yields_no_values(self) -> None:
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00]))

        assert delivered(block, "on_binary_input") == []

    def test_truncated_object_payload_stops_early(self) -> None:
        """A count promising three objects with two present yields two."""
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        data = bytes([0x03, 0x00, FLAGS_ON, 0x01, FLAGS_OFF])
        values = delivered(ObjectBlock(header=header, data=data), "on_binary_input")

        assert indexed_values(values) == {0: True, 1: False}

    def test_unsupported_binary_variation_yields_no_values(self) -> None:
        header = ObjectHeader(group=1, variation=99, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, FLAGS_ON]))

        assert delivered(block, "on_binary_input") == []

    def test_unsupported_counter_variation_yields_no_values(self) -> None:
        header = ObjectHeader(group=20, variation=99, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, 0x01, 0x02]))

        assert delivered(block, "on_counter") == []

    def test_empty_blocks_yield_no_values(self) -> None:
        for group, variation in ((1, 2), (30, 1), (20, 1)):
            header = ObjectHeader(group=group, variation=variation, qualifier=0x00)
            block = ObjectBlock(header=header, data=b"")
            assert dispatch([block]) == []

    def test_counter_event_with_timestamp_g22v5(self) -> None:
        """g22v5 is flags + 32-bit value + 48-bit timestamp."""
        header = ObjectHeader(group=22, variation=5, qualifier=0x17)
        data = bytes([0x01, 0x02, 0x01]) + struct.pack("<I", 4242) + bytes(6)
        values = delivered(ObjectBlock(header=header, data=data), "on_counter")

        assert indexed_values(values) == {2: 4242}

    def test_counter_no_flags_variation_g20v5(self) -> None:
        """g20v5 has no quality byte; quality defaults to online."""
        header = ObjectHeader(group=20, variation=5, qualifier=0x00)
        data = bytes([0x00, 0x00]) + struct.pack("<I", 7)
        values = delivered(ObjectBlock(header=header, data=data), "on_counter")

        assert indexed_values(values) == {0: 7}
        assert values[0].quality == QUALITY_ONLINE

    def test_analog_no_flags_variation_g30v3(self) -> None:
        header = ObjectHeader(group=30, variation=3, qualifier=0x00)
        data = bytes([0x00, 0x00]) + struct.pack("<i", -9)
        values = delivered(ObjectBlock(header=header, data=data), "on_analog_input")

        assert indexed_values(values) == {0: -9.0}
        assert values[0].quality == QUALITY_ONLINE


class TestFragmentFlags:
    """ResponseInfo carries the FIR/FIN/CON bits the app-control byte held.

    Regression cover for issue #57: these were parsed and discarded, so a
    caller could not tell a non-final fragment (awaiting CONFIRM) from a
    final one without re-parsing the header.
    """

    def test_non_final_fragment_reports_fin_false_con_true(self) -> None:
        """FIR=1, FIN=0, CON=1: first fragment of a multi-fragment transfer."""
        master = Master()
        control = 0xA1  # FIR|CON, seq=1
        header = bytes([control, 0x81, 0x00, 0x00])

        info = master.process_response(header)

        assert info is not None
        assert info.fir is True
        assert info.fin is False
        assert info.con is True

    def test_final_fragment_reports_fin_true(self) -> None:
        """FIR=0, FIN=1, CON=0: closing fragment of the same transfer."""
        master = Master()
        control = 0x42  # FIN, seq=2
        header = bytes([control, 0x81, 0x00, 0x00])

        info = master.process_response(header)

        assert info is not None
        assert info.fir is False
        assert info.fin is True
        assert info.con is False

    def test_single_fragment_response_reports_fir_and_fin_true(self) -> None:
        """FIR=1, FIN=1: the common single-fragment case."""
        master = Master()

        info = master.process_response(RESPONSE_HEADER)

        assert info is not None
        assert info.fir is True
        assert info.fin is True
        assert info.con is False


class TestFrozenCounterLayout:
    """g21v5/v6 (IEEE 1815-2012 A.11.5 p.529, A.11.6 p.531) are flag + value +
    6-octet DNP3TIME, distinct from the g20v5/v6 no-flag layout. Regression
    cover for craigpnnl/dnp3py#79.
    """

    # Non-zero, non-palindromic time octets so a wrong stride misreads point 1
    # from inside them (see the two-point tests below).
    _TIME_OCTETS = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])

    def test_g21v5_delivers_flag_as_quality_and_uint32_value(self) -> None:
        """A.11.5.2.2: BSTR8 flag, UINT32 count, DNP3TIME. 11.3.4: little-endian.

        Range 0..1 (two objects) exercises the 11-octet stride: a decoder
        missing timestamp_width reads point 1 out of point 0's time octets
        instead of its own flag and value.
        """
        header = ObjectHeader(group=21, variation=5, qualifier=0x00)
        data = (
            bytes([0x00, 0x01])
            + bytes([0x21])
            + struct.pack("<I", 0x12345678)
            + self._TIME_OCTETS
            + bytes([0x03])
            + struct.pack("<I", 0x87654321)
            + self._TIME_OCTETS
        )
        values = delivered(ObjectBlock(header=header, data=data), "on_frozen_counter")

        assert indexed_values(values) == {0: 0x12345678, 1: 0x87654321}
        assert values[0].quality == 0x21
        assert values[1].quality == 0x03
        # Known limitation (#81): time-of-occurrence is skipped, not decoded.
        assert values[0].timestamp is None
        assert values[1].timestamp is None

    def test_g21v6_delivers_flag_as_quality_and_uint16_value(self) -> None:
        """A.11.6.2.2: BSTR8 flag, UINT16 count, DNP3TIME. 11.3.4: little-endian.

        Range 0..1 (two objects) exercises the 9-octet stride: a decoder
        missing timestamp_width reads point 1 out of point 0's time octets
        instead of its own flag and value.
        """
        header = ObjectHeader(group=21, variation=6, qualifier=0x00)
        data = (
            bytes([0x00, 0x01])
            + bytes([0x21])
            + struct.pack("<H", 0x1234)
            + self._TIME_OCTETS
            + bytes([0x03])
            + struct.pack("<H", 0x4321)
            + self._TIME_OCTETS
        )
        values = delivered(ObjectBlock(header=header, data=data), "on_frozen_counter")

        assert indexed_values(values) == {0: 0x1234, 1: 0x4321}
        assert values[0].quality == 0x21
        assert values[1].quality == 0x03
        # Known limitation (#81): time-of-occurrence is skipped, not decoded.
        assert values[0].timestamp is None
        assert values[1].timestamp is None

    def test_g21v1_frozen_counter_32bit_with_flag_unchanged(self) -> None:
        """A.11.1: flag + UINT32, no time. Must not move when v5/v6 are fixed."""
        header = ObjectHeader(group=21, variation=1, qualifier=0x00)
        data = bytes([0x00, 0x00, 0x01]) + struct.pack("<I", 0x12345678)
        values = delivered(ObjectBlock(header=header, data=data), "on_frozen_counter")

        assert indexed_values(values) == {0: 0x12345678}
        assert values[0].quality == 0x01

    def test_g21v2_frozen_counter_16bit_with_flag_unchanged(self) -> None:
        """A.11.2: flag + UINT16, no time. Must not move when v5/v6 are fixed."""
        header = ObjectHeader(group=21, variation=2, qualifier=0x00)
        data = bytes([0x00, 0x00, 0x01]) + struct.pack("<H", 0x1234)
        values = delivered(ObjectBlock(header=header, data=data), "on_frozen_counter")

        assert indexed_values(values) == {0: 0x1234}
        assert values[0].quality == 0x01

    def test_g21v5_block_and_g30v1_block_both_delivered(self) -> None:
        """A g21v5 block followed by a g30v1 block delivers both (no absorption)."""
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = (
            bytes([21, 5, 0x00, 0, 0])
            + bytes([0x01])
            + struct.pack("<I", 0x12345678)
            + self._TIME_OCTETS
            + bytes([0x1E, 0x01, 0x00, 0, 0])
            + bytes([0x01])
            + struct.pack("<i", 2401)
        )
        fragment = parse_response(RESPONSE_HEADER + body)
        assert len(fragment.objects) == 2

        master.process_response(RESPONSE_HEADER + body)

        assert handler.frozen_counters == {0: 0x12345678}
        assert handler.analog_inputs == {0: 2401.0}


class TestBlockFollowingALayoutFramedBlock:
    """A packed or analog output block is bounded by its own length, so the block after it is delivered.

    Refs #74.
    """

    def test_ex_4_10_g1v1_then_ex_4_9_g30v4(self) -> None:
        """IEEE 1815-2012 EX 4-10 then EX 4-9 (p. 43), in one fragment.

        EX 4-10 prints qualifier 01 with the 2-octet range 00 11. Qualifier 01 needs a
        4-octet range, and only qualifier 00 gives 18 points in 3 data octets, so the
        test uses 00. Expected values are the example prose: indexes 0-3 are 1, 4-7
        are 0, 8-15 alternate starting at 0, 16 and 17 are 1; then 5000, 20000, -1200
        and 96 at indexes 4-7.
        """
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = bytes([0x01, 0x01, 0x00, 0x00, 0x11, 0x0F, 0xAA, 0x03]) + bytes(
            [0x1E, 0x04, 0x00, 0x04, 0x07, 0x88, 0x13, 0x20, 0x4E, 0x50, 0xFB, 0x60, 0x00]
        )

        assert master.process_response(RESPONSE_HEADER + body) is not None

        alternating = {index: index % 2 == 1 for index in range(8, 16)}
        assert handler.binary_inputs == {
            **dict.fromkeys(range(4), True),
            **dict.fromkeys(range(4, 8), False),
            **alternating,
            16: True,
            17: True,
        }
        assert handler.analog_inputs == {4: 5000.0, 5: 20000.0, 6: -1200.0, 7: 96.0}

    def test_g40v2_then_g30v1(self) -> None:
        """Composed from A.19.2 (flag, INT16) and A.14.1 (flag, INT32); 11.3.4 little-endian."""
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = bytes([0x28, 0x02, 0x00, 0x03, 0x04, 0x01, 0xFE, 0xFF, 0x01, 0x34, 0x12]) + bytes(
            [0x1E, 0x01, 0x00, 0x00, 0x00, 0x01, 0x60, 0x79, 0xFE, 0xFF]
        )

        assert master.process_response(RESPONSE_HEADER + body) is not None

        assert handler.analog_outputs == {3: -2.0, 4: 4660.0}
        assert handler.analog_inputs == {0: -100000.0}

    def test_g40v1_then_g30v1(self) -> None:
        """Composed from A.19.1 (flag, INT32) and A.14.1 (flag, INT32); 11.3.4 little-endian."""
        handler = CollectingHandler()
        master = Master(handler=handler)
        body = bytes([0x28, 0x01, 0x00, 0x00, 0x00, 0x01, 0x90, 0xEE, 0xFE, 0xFF]) + bytes(
            [0x1E, 0x01, 0x00, 0x02, 0x02, 0x01, 0x61, 0x09, 0x00, 0x00]
        )

        assert master.process_response(RESPONSE_HEADER + body) is not None

        assert handler.analog_outputs == {0: -70000.0}
        assert handler.analog_inputs == {2: 2401.0}
