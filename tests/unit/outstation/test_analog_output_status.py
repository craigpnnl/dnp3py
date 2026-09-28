"""Tests for outstation Group 40 (Analog Output Status) READ and Class 0.

IEEE 1815-2012 4.2.2.7.2.1: a g40v0 read (and Class 0) answers in the
configured default variation, g40v2 per Clause 14 Table 14-3 for a Level 2
outstation. 11.6.1.1 rules 2 and 3 govern the clamp and OVER_RANGE
behaviour asserted here.
"""

import math
import struct

import pytest

from dnp3.application.builder import build_integrity_poll, build_read_request
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.qualifiers import ObjectHeader, PrefixCode, RangeCode
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import GROUP_ANALOG_OUTPUT_STATUS, Outstation

ONLINE = AnalogQuality.ONLINE
OVER_RANGE_FLAG = int(AnalogQuality.ONLINE | AnalogQuality.OVER_RANGE)


def _read_group40(outstation: Outstation, variation: int) -> ResponseFragment:
    """Send a g40 READ of the given variation and return the response."""
    header = ObjectHeader.build(
        group=GROUP_ANALOG_OUTPUT_STATUS,
        variation=variation,
        prefix=PrefixCode.NONE,
        range_code=RangeCode.ALL_OBJECTS,
    )
    block = ObjectBlock(header=header)
    request = build_read_request(objects=(block,))
    responses = outstation.process_request(request.to_bytes())
    assert len(responses) == 1
    return responses[0]


def _g40_blocks(response: ResponseFragment) -> list[ObjectBlock]:
    return [b for b in response.objects if b.header.group == GROUP_ANALOG_OUTPUT_STATUS]


class TestVariationZeroDefault:
    """Variation 0 answers in the configured default variation (g40v2)."""

    def test_variation_zero_answers_g40v2_by_default(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=100.0, quality=ONLINE)

        response = _read_group40(outstation, variation=0)
        blocks = _g40_blocks(response)

        assert len(blocks) == 1
        assert blocks[0].header.variation == 2
        assert blocks[0].header.qualifier == 0x00
        assert blocks[0].data[0] == 0, "start index must be 0"
        assert blocks[0].data[1] == 0, "stop index must be 0"
        assert blocks[0].data[2:5] == bytes([int(ONLINE)]) + struct.pack("<h", 100)
        assert IIN.OBJECT_UNKNOWN not in response.header.iin


class TestExplicitVariations:
    """Variations 1-4 are served exactly as requested."""

    def test_v1_32bit_signed(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=-70000.0, quality=ONLINE)

        response = _read_group40(outstation, variation=1)
        blocks = _g40_blocks(response)

        assert len(blocks) == 1
        assert blocks[0].header.variation == 1
        assert blocks[0].data[2:7] == bytes([int(ONLINE)]) + struct.pack("<i", -70000)

    def test_v2_16bit_signed(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=-50.0, quality=ONLINE)

        response = _read_group40(outstation, variation=2)
        blocks = _g40_blocks(response)

        assert len(blocks) == 1
        assert blocks[0].header.variation == 2
        assert blocks[0].data[2:5] == bytes([int(ONLINE)]) + struct.pack("<h", -50)

    def test_v3_float32(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=3.5, quality=ONLINE)

        response = _read_group40(outstation, variation=3)
        blocks = _g40_blocks(response)

        assert len(blocks) == 1
        assert blocks[0].header.variation == 3
        assert blocks[0].data[2:7] == bytes([int(ONLINE)]) + struct.pack("<f", 3.5)

    def test_v4_float64(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=3.5, quality=ONLINE)

        response = _read_group40(outstation, variation=4)
        blocks = _g40_blocks(response)

        assert len(blocks) == 1
        assert blocks[0].header.variation == 4
        assert blocks[0].data[2:11] == bytes([int(ONLINE)]) + struct.pack("<d", 3.5)


class TestUnknownVariation:
    def test_variation_five_is_object_unknown(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=1.0, quality=ONLINE)

        response = _read_group40(outstation, variation=5)

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert _g40_blocks(response) == []


class TestEmptyDatabase:
    def test_no_points_gives_no_block_and_iin_zero(self) -> None:
        outstation = Outstation()

        response = _read_group40(outstation, variation=0)

        assert _g40_blocks(response) == []
        assert IIN.OBJECT_UNKNOWN not in response.header.iin

    def test_unknown_variation_is_object_unknown_even_with_empty_database(self) -> None:
        """An empty database must not swallow the unknown-variation error."""
        outstation = Outstation()

        response = _read_group40(outstation, variation=5)

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert _g40_blocks(response) == []


class TestClampAndOverRangeV2:
    """16-bit (v2) clamp and OVER_RANGE at its signed limits and at infinity."""

    def test_32767_is_in_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=32767.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:5] == struct.pack("<h", 32767)

    def test_32768_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=32768.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:5] == struct.pack("<h", 32767)

    def test_negative_32768_is_in_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=-32768.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:5] == struct.pack("<h", -32768)

    def test_negative_32769_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=-32769.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:5] == struct.pack("<h", -32768)

    def test_positive_infinity_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float("inf"), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:5] == struct.pack("<h", 32767)

    def test_negative_infinity_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float("-inf"), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=2))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:5] == struct.pack("<h", -32768)


class TestClampAndOverRangeV1:
    """32-bit (v1) clamp and OVER_RANGE at its signed limits and at infinity."""

    INT32_MAX = 2**31 - 1
    INT32_MIN = -(2**31)

    def test_int32_max_is_in_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float(self.INT32_MAX), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=1))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:7] == struct.pack("<i", self.INT32_MAX)

    def test_above_int32_max_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float(self.INT32_MAX) + 1.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=1))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<i", self.INT32_MAX)

    def test_int32_min_is_in_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float(self.INT32_MIN), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=1))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:7] == struct.pack("<i", self.INT32_MIN)

    def test_below_int32_min_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float(self.INT32_MIN) - 1.0, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=1))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<i", self.INT32_MIN)

    def test_infinity_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float("inf"), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=1))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<i", self.INT32_MAX)


class TestClampFloatVariations:
    """v3 (float32) clamps a too-large finite value; infinity packs as-is."""

    FLOAT32_MAX = struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]

    def test_float32_max_is_in_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=self.FLOAT32_MAX, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=3))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:7] == struct.pack("<f", self.FLOAT32_MAX)

    def test_just_above_float32_max_clamps_over_range(self) -> None:
        just_above = math.nextafter(self.FLOAT32_MAX, math.inf)
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=just_above, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=3))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<f", self.FLOAT32_MAX)

    def test_huge_finite_value_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=1e40, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=3))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<f", self.FLOAT32_MAX)

    def test_negative_huge_finite_value_clamps_over_range(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=-1e40, quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=3))
        assert blocks[0].data[2] == OVER_RANGE_FLAG
        assert blocks[0].data[3:7] == struct.pack("<f", -self.FLOAT32_MAX)

    def test_positive_infinity_is_not_over_range(self) -> None:
        """Infinity is a representable binary32 value, so it packs unclamped."""
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float("inf"), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=3))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:7] == struct.pack("<f", float("inf"))

    def test_v4_positive_infinity_is_not_over_range(self) -> None:
        """Infinity is a representable binary64 value, so it packs unclamped."""
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=float("inf"), quality=ONLINE)
        blocks = _g40_blocks(_read_group40(outstation, variation=4))
        assert blocks[0].data[2] == int(ONLINE)
        assert blocks[0].data[3:11] == struct.pack("<d", float("inf"))


class TestConfigDefaultVariation:
    def test_config_default_1_changes_variation_zero_answer(self) -> None:
        config = OutstationConfig(analog_output_static_variation=1)
        outstation = Outstation(config=config)
        outstation.database.add_analog_output(0, value=42.0, quality=ONLINE)

        response = _read_group40(outstation, variation=0)
        blocks = _g40_blocks(response)

        assert blocks[0].header.variation == 1
        assert blocks[0].data[2:7] == bytes([int(ONLINE)]) + struct.pack("<i", 42)

    @pytest.mark.parametrize("value", [0, 3, 4, 5, -1])
    def test_config_refuses_variation_other_than_1_or_2(self, value: int) -> None:
        with pytest.raises(ValueError, match="Analog output static variation"):
            OutstationConfig(analog_output_static_variation=value)

    @pytest.mark.parametrize("value", [2.0, 1.0, True, False])
    def test_config_refuses_non_int_variation(self, value: float) -> None:
        """A float or bool equal to 1 or 2 is still refused: the setting is int-only."""
        with pytest.raises(ValueError, match="Analog output static variation"):
            OutstationConfig(analog_output_static_variation=value)  # type: ignore[arg-type]


class TestClass0:
    def test_class_0_includes_g40_block_after_analog_inputs(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_input(0, value=1.0)
        outstation.database.add_analog_output(0, value=99.0, quality=ONLINE)

        response = outstation.process_request(build_integrity_poll().to_bytes())[0]

        ai_indices = [i for i, b in enumerate(response.objects) if b.header.group == 30]
        ao_blocks = _g40_blocks(response)
        assert len(ao_blocks) == 1
        ao_indices = [i for i, b in enumerate(response.objects) if b.header.group == GROUP_ANALOG_OUTPUT_STATUS]
        assert ai_indices and ao_indices
        assert ao_indices[0] > ai_indices[-1], "g40 block must come after analog input blocks"
        assert ao_blocks[0].header.variation == 2
        assert ao_blocks[0].data[2:5] == bytes([int(ONLINE)]) + struct.pack("<h", 99)

    def test_class_0_with_config_variation_1_serves_g40v1(self) -> None:
        config = OutstationConfig(analog_output_static_variation=1)
        outstation = Outstation(config=config)
        outstation.database.add_analog_output(0, value=99.0, quality=ONLINE)

        response = outstation.process_request(build_integrity_poll().to_bytes())[0]

        ao_blocks = _g40_blocks(response)
        assert len(ao_blocks) == 1
        assert ao_blocks[0].header.variation == 1
        assert ao_blocks[0].data[2:7] == bytes([int(ONLINE)]) + struct.pack("<i", 99)

    def test_class_0_no_ao_points_no_g40_block(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_input(0, value=1.0)

        response = outstation.process_request(build_integrity_poll().to_bytes())[0]

        assert _g40_blocks(response) == []


class TestSparseIndices:
    def test_sparse_indices_yield_two_blocks_with_exact_bytes(self) -> None:
        outstation = Outstation()
        outstation.database.add_analog_output(0, value=100.0, quality=ONLINE)
        outstation.database.add_analog_output(5, value=-50.0, quality=ONLINE)

        response = _read_group40(outstation, variation=0)
        blocks = _g40_blocks(response)

        assert len(blocks) == 2
        assert blocks[0].data[0] == 0
        assert blocks[0].data[1] == 0
        assert blocks[0].data[2:5] == bytes([int(ONLINE)]) + struct.pack("<h", 100)
        assert blocks[1].data[0] == 5
        assert blocks[1].data[1] == 5
        assert blocks[1].data[2:5] == bytes([int(ONLINE)]) + struct.pack("<h", -50)
