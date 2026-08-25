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
        self.counters: dict[int, int] = {}

    def on_binary_input(self, values, info: ResponseInfo) -> None:
        self.binary_inputs.update({v.index: v.value for v in values})

    def on_binary_output(self, values, info: ResponseInfo) -> None:
        self.binary_outputs.update({v.index: v.value for v in values})

    def on_analog_input(self, values, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})

    def on_counter(self, values, info: ResponseInfo) -> None:
        self.counters.update({v.index: v.value for v in values})


def indexed_values(values) -> dict[int, object]:
    """Collapse a parsed value list to {index: value} for comparison."""
    return {v.index: v.value for v in values}


class TestBinaryEventCountQualifiers:
    """Group 2 binary events use count + per-object index prefixes."""

    def test_uint8_count_uint8_index_g2v1(self) -> None:
        """Qualifier 0x17: 1-byte count, 1-byte index prefix per object."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        # count=3, then (index, flags) per event: non-consecutive indices.
        data = bytes([0x03, 0x00, FLAGS_ON, 0x01, FLAGS_OFF, 0x02, FLAGS_ON])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 1: False, 2: True}

    def test_uint8_count_honours_sparse_indices(self) -> None:
        """Index prefixes are read, not assumed consecutive from zero."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        data = bytes([0x02, 0x07, FLAGS_ON, 0x2A, FLAGS_OFF])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {7: True, 42: False}

    def test_uint16_count_uint16_index_g2v1(self) -> None:
        """Qualifier 0x28: 2-byte count, 2-byte index prefix per object."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x28)
        data = (
            (2).to_bytes(2, "little")
            + (5).to_bytes(2, "little")
            + bytes([FLAGS_ON])
            + (9).to_bytes(2, "little")
            + bytes([FLAGS_OFF])
        )
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {5: True, 9: False}

    def test_g2v2_absolute_timestamp_is_skipped(self) -> None:
        """g2v2 carries a 48-bit timestamp after the flags byte (7 bytes total)."""
        master = Master()
        header = ObjectHeader(group=2, variation=2, qualifier=0x17)
        data = bytes([0x02]) + bytes([0x00, FLAGS_ON]) + bytes(6) + bytes([0x01, FLAGS_OFF]) + bytes(6)
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 1: False}

    def test_g2v3_relative_timestamp_is_skipped(self) -> None:
        """g2v3 carries a 16-bit relative time after the flags byte (3 bytes)."""
        master = Master()
        header = ObjectHeader(group=2, variation=3, qualifier=0x17)
        data = bytes([0x01, 0x04, FLAGS_ON]) + (1234).to_bytes(2, "little")
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {4: True}

    def test_count_limits_objects_parsed(self) -> None:
        """A count smaller than the available data bounds the object loop."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        # count=1, but two objects' worth of bytes follow.
        data = bytes([0x01, 0x00, FLAGS_ON, 0x01, FLAGS_OFF])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True}

    def test_binary_output_events_g11v1(self) -> None:
        """Group 11 binary output events use the same count qualifiers."""
        master = Master()
        header = ObjectHeader(group=11, variation=1, qualifier=0x17)
        data = bytes([0x02, 0x00, FLAGS_ON, 0x03, FLAGS_OFF])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 3: False}


class TestBinaryEventVariationIsNotPacked:
    """Variation 1 means packed only for group 1 — never for event groups."""

    def test_g2v1_is_flags_per_point_not_packed_bits(self) -> None:
        """g2v1 is one flags byte per point; treating it as packed fabricates points."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x00)
        data = bytes([0, 1, FLAGS_ON, FLAGS_OFF])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 1: False}

    def test_g1v1_remains_packed(self) -> None:
        """Group 1 variation 1 is genuinely packed: 1 bit per point."""
        master = Master()
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        data = bytes([0, 7, 0b10101010])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

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
        master = Master()
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        # Range 0-2 in a byte whose upper bits are set: only 3 points are real.
        data = bytes([0, 2, 0b11111101])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 1: False, 2: True}


class TestAnalogEventCountQualifiers:
    """Group 32 analog events, including timestamped and float variations."""

    def test_g32v1_count_qualifier(self) -> None:
        """One real analog event stays one point with its stored value."""
        master = Master()
        header = ObjectHeader(group=32, variation=1, qualifier=0x17)
        data = bytes([0x01, 0x00, 0x01]) + struct.pack("<i", 2401)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: 2401.0}

    def test_g32v3_with_timestamp(self) -> None:
        """g32v3 is flags + 32-bit value + 48-bit timestamp (11 bytes)."""
        master = Master()
        header = ObjectHeader(group=32, variation=3, qualifier=0x17)
        data = bytes([0x01, 0x05, 0x01]) + struct.pack("<i", -1500) + bytes(6)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {5: -1500.0}

    def test_g32v5_float_event(self) -> None:
        """g32v5 carries a float32 payload."""
        master = Master()
        header = ObjectHeader(group=32, variation=5, qualifier=0x17)
        data = bytes([0x01, 0x02, 0x01]) + struct.pack("<f", 2401.7)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert values[0].index == 2
        assert values[0].value == pytest.approx(2401.7, abs=1e-3)

    def test_counter_event_g22v1_count_qualifier(self) -> None:
        """Group 22 counter events use count qualifiers too."""
        master = Master()
        header = ObjectHeader(group=22, variation=1, qualifier=0x17)
        data = bytes([0x01, 0x03, 0x01]) + struct.pack("<I", 123456)
        values = master._parse_counter_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {3: 123456}


class TestAnalogFloatVariations:
    """Static float variations must not be dropped or truncated."""

    def test_g30v5_float32_preserves_fraction(self) -> None:
        master = Master()
        header = ObjectHeader(group=30, variation=5, qualifier=0x00)
        data = bytes([0, 0, 0x01]) + struct.pack("<f", 2401.7)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert values[0].index == 0
        assert values[0].value == pytest.approx(2401.7, abs=1e-3)

    def test_g30v6_double64_preserves_fraction(self) -> None:
        master = Master()
        header = ObjectHeader(group=30, variation=6, qualifier=0x00)
        data = bytes([0, 0, 0x01]) + struct.pack("<d", -15.25)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: -15.25}

    def test_g30v5_multiple_points(self) -> None:
        master = Master()
        header = ObjectHeader(group=30, variation=5, qualifier=0x00)
        data = bytes([0, 1]) + bytes([0x01]) + struct.pack("<f", 1.5) + bytes([0x01]) + struct.pack("<f", -2.5)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: 1.5, 1: -2.5}

    def test_unsupported_variation_still_returns_empty(self) -> None:
        """An unknown variation yields nothing rather than garbage."""
        master = Master()
        header = ObjectHeader(group=30, variation=100, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0, 0, 0x01, 0x02, 0x03]))

        assert master._parse_analog_values(block) == []


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

    def test_unregistered_group_block_still_parses(self) -> None:
        """Group 40 has no registry entry, so its size is unknown.

        The block must still be delimited and its value decoded from the
        variation, rather than the unknown size collapsing it to empty.
        """
        master = Master()
        header = ObjectHeader(group=40, variation=2, qualifier=0x00)
        data = bytes([0, 0, 0x01]) + struct.pack("<h", 777)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: 777.0}

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
        master = Master()
        header = ObjectHeader(group=1, variation=2, qualifier=0x0C)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, FLAGS_ON]))

        assert master._parse_binary_values(block) == []

    def test_size_prefix_yields_no_values(self) -> None:
        """Size prefixes (0x40+) describe variable-format objects we do not parse."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x47)
        block = ObjectBlock(header=header, data=bytes([0x01, 0x01, FLAGS_ON]))

        assert master._parse_binary_values(block) == []

    def test_truncated_count_field_yields_no_values(self) -> None:
        """A 2-byte count field needs 2 bytes."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x28)
        block = ObjectBlock(header=header, data=bytes([0x01]))

        assert master._parse_binary_values(block) == []

    def test_truncated_start_stop_yields_no_values(self) -> None:
        master = Master()
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00]))

        assert master._parse_binary_values(block) == []

    def test_truncated_object_payload_stops_early(self) -> None:
        """A count promising three objects with two present yields two."""
        master = Master()
        header = ObjectHeader(group=2, variation=1, qualifier=0x17)
        data = bytes([0x03, 0x00, FLAGS_ON, 0x01, FLAGS_OFF])
        values = master._parse_binary_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: True, 1: False}

    def test_unsupported_binary_variation_yields_no_values(self) -> None:
        master = Master()
        header = ObjectHeader(group=1, variation=99, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, FLAGS_ON]))

        assert master._parse_binary_values(block) == []

    def test_unsupported_counter_variation_yields_no_values(self) -> None:
        master = Master()
        header = ObjectHeader(group=20, variation=99, qualifier=0x00)
        block = ObjectBlock(header=header, data=bytes([0x00, 0x00, 0x01, 0x02]))

        assert master._parse_counter_values(block) == []

    def test_empty_blocks_yield_no_values(self) -> None:
        master = Master()
        for group, variation in ((1, 2), (30, 1), (20, 1)):
            header = ObjectHeader(group=group, variation=variation, qualifier=0x00)
            block = ObjectBlock(header=header, data=b"")
            assert master._parse_binary_values(block) == []
            assert master._parse_analog_values(block) == []
            assert master._parse_counter_values(block) == []

    def test_counter_event_with_timestamp_g22v5(self) -> None:
        """g22v5 is flags + 32-bit value + 48-bit timestamp."""
        master = Master()
        header = ObjectHeader(group=22, variation=5, qualifier=0x17)
        data = bytes([0x01, 0x02, 0x01]) + struct.pack("<I", 4242) + bytes(6)
        values = master._parse_counter_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {2: 4242}

    def test_counter_no_flags_variation_g20v5(self) -> None:
        """g20v5 has no quality byte; quality defaults to online."""
        master = Master()
        header = ObjectHeader(group=20, variation=5, qualifier=0x00)
        data = bytes([0x00, 0x00]) + struct.pack("<I", 7)
        values = master._parse_counter_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: 7}
        assert values[0].quality == QUALITY_ONLINE

    def test_analog_no_flags_variation_g30v3(self) -> None:
        master = Master()
        header = ObjectHeader(group=30, variation=3, qualifier=0x00)
        data = bytes([0x00, 0x00]) + struct.pack("<i", -9)
        values = master._parse_analog_values(ObjectBlock(header=header, data=data))

        assert indexed_values(values) == {0: -9.0}
        assert values[0].quality == QUALITY_ONLINE
