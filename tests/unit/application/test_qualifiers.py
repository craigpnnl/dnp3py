"""Tests for object headers and qualifiers."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.application.qualifiers import (
    PREFIX_1_BYTE_INDEX,
    PREFIX_1_BYTE_SIZE,
    PREFIX_2_BYTE_INDEX,
    PREFIX_2_BYTE_SIZE,
    PREFIX_4_BYTE_INDEX,
    PREFIX_4_BYTE_SIZE,
    PREFIX_MASK,
    PREFIX_NONE,
    RANGE_MASK,
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
    get_prefix_size,
    get_range_size,
)


class TestPrefixConstants:
    """Tests for prefix byte constants."""

    def test_prefix_none(self) -> None:
        """No prefix is 0x00."""
        assert PREFIX_NONE == 0x00

    def test_prefix_1_byte_index(self) -> None:
        """1-byte index prefix is 0x10."""
        assert PREFIX_1_BYTE_INDEX == 0x10

    def test_prefix_2_byte_index(self) -> None:
        """2-byte index prefix is 0x20."""
        assert PREFIX_2_BYTE_INDEX == 0x20

    def test_prefix_4_byte_index(self) -> None:
        """4-byte index prefix is 0x30."""
        assert PREFIX_4_BYTE_INDEX == 0x30

    def test_prefix_1_byte_size(self) -> None:
        """1-byte size prefix is 0x40."""
        assert PREFIX_1_BYTE_SIZE == 0x40

    def test_prefix_2_byte_size(self) -> None:
        """2-byte size prefix is 0x50."""
        assert PREFIX_2_BYTE_SIZE == 0x50

    def test_prefix_4_byte_size(self) -> None:
        """4-byte size prefix is 0x60."""
        assert PREFIX_4_BYTE_SIZE == 0x60

    def test_prefix_mask(self) -> None:
        """Prefix mask is 0x70."""
        assert PREFIX_MASK == 0x70

    def test_range_mask(self) -> None:
        """Range mask is 0x0F."""
        assert RANGE_MASK == 0x0F


class TestPrefixCode:
    """Tests for PrefixCode enum."""

    def test_none_value(self) -> None:
        """NONE is 0."""
        assert PrefixCode.NONE == 0

    def test_uint8_index_value(self) -> None:
        """UINT8_INDEX is 1."""
        assert PrefixCode.UINT8_INDEX == 1

    def test_uint16_index_value(self) -> None:
        """UINT16_INDEX is 2."""
        assert PrefixCode.UINT16_INDEX == 2

    def test_uint32_index_value(self) -> None:
        """UINT32_INDEX is 3."""
        assert PrefixCode.UINT32_INDEX == 3

    def test_uint8_size_value(self) -> None:
        """UINT8_SIZE is 4."""
        assert PrefixCode.UINT8_SIZE == 4

    def test_uint16_size_value(self) -> None:
        """UINT16_SIZE is 5."""
        assert PrefixCode.UINT16_SIZE == 5

    def test_uint32_size_value(self) -> None:
        """UINT32_SIZE is 6."""
        assert PrefixCode.UINT32_SIZE == 6


class TestRangeCode:
    """Tests for RangeCode enum."""

    def test_uint8_start_stop(self) -> None:
        """UINT8_START_STOP is 0x00."""
        assert RangeCode.UINT8_START_STOP == 0x00

    def test_uint16_start_stop(self) -> None:
        """UINT16_START_STOP is 0x01."""
        assert RangeCode.UINT16_START_STOP == 0x01

    def test_uint32_start_stop(self) -> None:
        """UINT32_START_STOP is 0x02."""
        assert RangeCode.UINT32_START_STOP == 0x02

    def test_all_objects(self) -> None:
        """ALL_OBJECTS is 0x06."""
        assert RangeCode.ALL_OBJECTS == 0x06

    def test_uint8_count(self) -> None:
        """UINT8_COUNT is 0x07."""
        assert RangeCode.UINT8_COUNT == 0x07

    def test_uint16_count(self) -> None:
        """UINT16_COUNT is 0x08."""
        assert RangeCode.UINT16_COUNT == 0x08

    def test_uint32_count(self) -> None:
        """UINT32_COUNT is 0x09."""
        assert RangeCode.UINT32_COUNT == 0x09


class TestObjectHeaderCreation:
    """Tests for creating ObjectHeader instances."""

    def test_create_basic_header(self) -> None:
        """Create a basic object header."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        assert header.group == 1
        assert header.variation == 2
        assert header.qualifier == 0x00

    def test_create_with_build(self) -> None:
        """Create header using build() factory."""
        header = ObjectHeader.build(
            group=30,
            variation=1,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.UINT8_START_STOP,
        )
        assert header.group == 30
        assert header.variation == 1
        assert header.qualifier == 0x00

    def test_build_with_prefix(self) -> None:
        """Build header with index prefix."""
        header = ObjectHeader.build(
            group=2,
            variation=2,
            prefix=PrefixCode.UINT8_INDEX,
            range_code=RangeCode.UINT8_COUNT,
        )
        # Qualifier = (prefix << 4) | range_code = (1 << 4) | 7 = 0x17
        assert header.qualifier == 0x17

    def test_group_out_of_range_negative(self) -> None:
        """Negative group raises error."""
        with pytest.raises(ValueError, match=r"Group.*out of range"):
            ObjectHeader(group=-1, variation=0, qualifier=0)

    def test_group_out_of_range_too_large(self) -> None:
        """Group > 255 raises error."""
        with pytest.raises(ValueError, match=r"Group.*out of range"):
            ObjectHeader(group=256, variation=0, qualifier=0)

    def test_variation_out_of_range_negative(self) -> None:
        """Negative variation raises error."""
        with pytest.raises(ValueError, match=r"Variation.*out of range"):
            ObjectHeader(group=0, variation=-1, qualifier=0)

    def test_variation_out_of_range_too_large(self) -> None:
        """Variation > 255 raises error."""
        with pytest.raises(ValueError, match=r"Variation.*out of range"):
            ObjectHeader(group=0, variation=256, qualifier=0)

    def test_qualifier_out_of_range_negative(self) -> None:
        """Negative qualifier raises error."""
        with pytest.raises(ValueError, match=r"Qualifier.*out of range"):
            ObjectHeader(group=0, variation=0, qualifier=-1)

    def test_qualifier_out_of_range_too_large(self) -> None:
        """Qualifier > 255 raises error."""
        with pytest.raises(ValueError, match=r"Qualifier.*out of range"):
            ObjectHeader(group=0, variation=0, qualifier=256)


class TestObjectHeaderSerialization:
    """Tests for serializing ObjectHeader to bytes."""

    def test_serialize_basic(self) -> None:
        """Serialize basic header."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        data = header.to_bytes()
        assert data == b"\x01\x02\x00"

    def test_serialize_with_qualifier(self) -> None:
        """Serialize header with qualifier."""
        header = ObjectHeader(group=30, variation=1, qualifier=0x17)
        data = header.to_bytes()
        assert data == b"\x1e\x01\x17"

    def test_serialize_max_values(self) -> None:
        """Serialize header with max values."""
        header = ObjectHeader(group=255, variation=255, qualifier=255)
        data = header.to_bytes()
        assert data == b"\xff\xff\xff"


class TestObjectHeaderParsing:
    """Tests for parsing ObjectHeader from bytes."""

    def test_parse_basic(self) -> None:
        """Parse basic header."""
        header = ObjectHeader.from_bytes(b"\x01\x02\x00")
        assert header.group == 1
        assert header.variation == 2
        assert header.qualifier == 0x00

    def test_parse_with_qualifier(self) -> None:
        """Parse header with qualifier."""
        header = ObjectHeader.from_bytes(b"\x1e\x01\x17")
        assert header.group == 30
        assert header.variation == 1
        assert header.qualifier == 0x17

    def test_parse_too_short_raises(self) -> None:
        """Too short data raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            ObjectHeader.from_bytes(b"\x01\x02")

    def test_parse_empty_raises(self) -> None:
        """Empty data raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            ObjectHeader.from_bytes(b"")

    @given(
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
    )
    def test_roundtrip(self, group: int, variation: int, qualifier: int) -> None:
        """Roundtrip: to_bytes -> from_bytes preserves values."""
        original = ObjectHeader(group=group, variation=variation, qualifier=qualifier)
        data = original.to_bytes()
        parsed = ObjectHeader.from_bytes(data)
        assert parsed == original


class TestObjectHeaderProperties:
    """Tests for ObjectHeader properties."""

    def test_prefix_code_none(self) -> None:
        """Get prefix code NONE."""
        header = ObjectHeader.build(group=1, variation=1, prefix=PrefixCode.NONE, range_code=RangeCode.UINT8_START_STOP)
        assert header.prefix_code == PrefixCode.NONE

    def test_prefix_code_uint8_index(self) -> None:
        """Get prefix code UINT8_INDEX."""
        header = ObjectHeader.build(
            group=1,
            variation=1,
            prefix=PrefixCode.UINT8_INDEX,
            range_code=RangeCode.UINT8_COUNT,
        )
        assert header.prefix_code == PrefixCode.UINT8_INDEX

    def test_range_code_start_stop(self) -> None:
        """Get range code UINT8_START_STOP."""
        header = ObjectHeader.build(group=1, variation=1, prefix=PrefixCode.NONE, range_code=RangeCode.UINT8_START_STOP)
        assert header.range_code == RangeCode.UINT8_START_STOP

    def test_range_code_count(self) -> None:
        """Get range code UINT8_COUNT."""
        header = ObjectHeader.build(group=1, variation=1, prefix=PrefixCode.NONE, range_code=RangeCode.UINT8_COUNT)
        assert header.range_code == RangeCode.UINT8_COUNT

    def test_has_prefix_false(self) -> None:
        """has_prefix is False when no prefix."""
        header = ObjectHeader.build(group=1, variation=1, prefix=PrefixCode.NONE)
        assert header.has_prefix is False

    def test_has_prefix_true(self) -> None:
        """has_prefix is True when prefix exists."""
        header = ObjectHeader.build(group=1, variation=1, prefix=PrefixCode.UINT8_INDEX)
        assert header.has_prefix is True


class TestStartStopRangeCreation:
    """Tests for creating StartStopRange instances."""

    def test_create_basic(self) -> None:
        """Create basic start-stop range."""
        r = StartStopRange(start=0, stop=9)
        assert r.start == 0
        assert r.stop == 9

    def test_count_property(self) -> None:
        """Count property gives number of objects."""
        r = StartStopRange(start=0, stop=9)
        assert r.count == 10

    def test_count_single_object(self) -> None:
        """Single object range has count 1."""
        r = StartStopRange(start=5, stop=5)
        assert r.count == 1


class TestStartStopRangeSerialization:
    """Tests for serializing StartStopRange."""

    def test_to_bytes_1(self) -> None:
        """Serialize as 1-byte start/stop."""
        r = StartStopRange(start=0, stop=9)
        assert r.to_bytes_1() == b"\x00\x09"

    def test_to_bytes_1_max(self) -> None:
        """Serialize max values as 1-byte."""
        r = StartStopRange(start=255, stop=255)
        assert r.to_bytes_1() == b"\xff\xff"

    def test_to_bytes_2(self) -> None:
        """Serialize as 2-byte start/stop."""
        r = StartStopRange(start=0, stop=1000)
        # 1000 = 0x03E8 -> little endian: E8 03
        assert r.to_bytes_2() == b"\x00\x00\xe8\x03"

    def test_to_bytes_2_max(self) -> None:
        """Serialize max values as 2-byte."""
        r = StartStopRange(start=65535, stop=65535)
        assert r.to_bytes_2() == b"\xff\xff\xff\xff"

    def test_to_bytes_4(self) -> None:
        """Serialize as 4-byte start/stop."""
        r = StartStopRange(start=0, stop=100000)
        # 100000 = 0x000186A0 -> little endian: A0 86 01 00
        assert r.to_bytes_4() == b"\x00\x00\x00\x00\xa0\x86\x01\x00"


class TestStartStopRangeParsing:
    """Tests for parsing StartStopRange."""

    def test_from_bytes_1(self) -> None:
        """Parse 1-byte start/stop."""
        r = StartStopRange.from_bytes_1(b"\x00\x09")
        assert r.start == 0
        assert r.stop == 9

    def test_from_bytes_1_too_short(self) -> None:
        """1-byte parsing with too short data raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            StartStopRange.from_bytes_1(b"\x00")

    def test_from_bytes_2(self) -> None:
        """Parse 2-byte start/stop."""
        r = StartStopRange.from_bytes_2(b"\x00\x00\xe8\x03")
        assert r.start == 0
        assert r.stop == 1000

    def test_from_bytes_2_too_short(self) -> None:
        """2-byte parsing with too short data raises error."""
        with pytest.raises(ValueError, match="requires 4 bytes"):
            StartStopRange.from_bytes_2(b"\x00\x00\x00")

    def test_from_bytes_4(self) -> None:
        """Parse 4-byte start/stop."""
        r = StartStopRange.from_bytes_4(b"\x00\x00\x00\x00\xa0\x86\x01\x00")
        assert r.start == 0
        assert r.stop == 100000

    def test_from_bytes_4_too_short(self) -> None:
        """4-byte parsing with too short data raises error."""
        with pytest.raises(ValueError, match="requires 8 bytes"):
            StartStopRange.from_bytes_4(b"\x00\x00\x00\x00\x00\x00\x00")

    @given(st.integers(min_value=0, max_value=255), st.integers(min_value=0, max_value=255))
    def test_roundtrip_1(self, start: int, stop: int) -> None:
        """Roundtrip 1-byte: to_bytes_1 -> from_bytes_1."""
        original = StartStopRange(start=start, stop=stop)
        data = original.to_bytes_1()
        parsed = StartStopRange.from_bytes_1(data)
        assert parsed == original

    @given(st.integers(min_value=0, max_value=65535), st.integers(min_value=0, max_value=65535))
    def test_roundtrip_2(self, start: int, stop: int) -> None:
        """Roundtrip 2-byte: to_bytes_2 -> from_bytes_2."""
        original = StartStopRange(start=start, stop=stop)
        data = original.to_bytes_2()
        parsed = StartStopRange.from_bytes_2(data)
        assert parsed == original


class TestCountRangeCreation:
    """Tests for creating CountRange instances."""

    def test_create_basic(self) -> None:
        """Create basic count range."""
        r = CountRange(count=10)
        assert r.count == 10


class TestCountRangeSerialization:
    """Tests for serializing CountRange."""

    def test_to_bytes_1(self) -> None:
        """Serialize as 1-byte count."""
        r = CountRange(count=10)
        assert r.to_bytes_1() == b"\x0a"

    def test_to_bytes_1_max(self) -> None:
        """Serialize max value as 1-byte."""
        r = CountRange(count=255)
        assert r.to_bytes_1() == b"\xff"

    def test_to_bytes_2(self) -> None:
        """Serialize as 2-byte count."""
        r = CountRange(count=1000)
        assert r.to_bytes_2() == b"\xe8\x03"

    def test_to_bytes_2_max(self) -> None:
        """Serialize max value as 2-byte."""
        r = CountRange(count=65535)
        assert r.to_bytes_2() == b"\xff\xff"

    def test_to_bytes_4(self) -> None:
        """Serialize as 4-byte count."""
        r = CountRange(count=100000)
        assert r.to_bytes_4() == b"\xa0\x86\x01\x00"


class TestCountRangeParsing:
    """Tests for parsing CountRange."""

    def test_from_bytes_1(self) -> None:
        """Parse 1-byte count."""
        r = CountRange.from_bytes_1(b"\x0a")
        assert r.count == 10

    def test_from_bytes_1_empty(self) -> None:
        """1-byte parsing with empty data raises error."""
        with pytest.raises(ValueError, match="requires 1 byte"):
            CountRange.from_bytes_1(b"")

    def test_from_bytes_2(self) -> None:
        """Parse 2-byte count."""
        r = CountRange.from_bytes_2(b"\xe8\x03")
        assert r.count == 1000

    def test_from_bytes_2_too_short(self) -> None:
        """2-byte parsing with too short data raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            CountRange.from_bytes_2(b"\x00")

    def test_from_bytes_4(self) -> None:
        """Parse 4-byte count."""
        r = CountRange.from_bytes_4(b"\xa0\x86\x01\x00")
        assert r.count == 100000

    def test_from_bytes_4_too_short(self) -> None:
        """4-byte parsing with too short data raises error."""
        with pytest.raises(ValueError, match="requires 4 bytes"):
            CountRange.from_bytes_4(b"\x00\x00\x00")

    @given(st.integers(min_value=0, max_value=255))
    def test_roundtrip_1(self, count: int) -> None:
        """Roundtrip 1-byte: to_bytes_1 -> from_bytes_1."""
        original = CountRange(count=count)
        data = original.to_bytes_1()
        parsed = CountRange.from_bytes_1(data)
        assert parsed == original

    @given(st.integers(min_value=0, max_value=65535))
    def test_roundtrip_2(self, count: int) -> None:
        """Roundtrip 2-byte: to_bytes_2 -> from_bytes_2."""
        original = CountRange(count=count)
        data = original.to_bytes_2()
        parsed = CountRange.from_bytes_2(data)
        assert parsed == original


class TestGetRangeSize:
    """Tests for get_range_size helper."""

    def test_uint8_start_stop(self) -> None:
        """UINT8_START_STOP is 2 bytes."""
        assert get_range_size(RangeCode.UINT8_START_STOP) == 2

    def test_uint16_start_stop(self) -> None:
        """UINT16_START_STOP is 4 bytes."""
        assert get_range_size(RangeCode.UINT16_START_STOP) == 4

    def test_uint32_start_stop(self) -> None:
        """UINT32_START_STOP is 8 bytes."""
        assert get_range_size(RangeCode.UINT32_START_STOP) == 8

    def test_all_objects(self) -> None:
        """ALL_OBJECTS is 0 bytes."""
        assert get_range_size(RangeCode.ALL_OBJECTS) == 0

    def test_uint8_count(self) -> None:
        """UINT8_COUNT is 1 byte."""
        assert get_range_size(RangeCode.UINT8_COUNT) == 1

    def test_uint16_count(self) -> None:
        """UINT16_COUNT is 2 bytes."""
        assert get_range_size(RangeCode.UINT16_COUNT) == 2

    def test_uint32_count(self) -> None:
        """UINT32_COUNT is 4 bytes."""
        assert get_range_size(RangeCode.UINT32_COUNT) == 4


class TestGetPrefixSize:
    """Tests for get_prefix_size helper."""

    def test_none(self) -> None:
        """NONE is 0 bytes."""
        assert get_prefix_size(PrefixCode.NONE) == 0

    def test_uint8_index(self) -> None:
        """UINT8_INDEX is 1 byte."""
        assert get_prefix_size(PrefixCode.UINT8_INDEX) == 1

    def test_uint16_index(self) -> None:
        """UINT16_INDEX is 2 bytes."""
        assert get_prefix_size(PrefixCode.UINT16_INDEX) == 2

    def test_uint32_index(self) -> None:
        """UINT32_INDEX is 4 bytes."""
        assert get_prefix_size(PrefixCode.UINT32_INDEX) == 4

    def test_uint8_size(self) -> None:
        """UINT8_SIZE is 1 byte."""
        assert get_prefix_size(PrefixCode.UINT8_SIZE) == 1

    def test_uint16_size(self) -> None:
        """UINT16_SIZE is 2 bytes."""
        assert get_prefix_size(PrefixCode.UINT16_SIZE) == 2

    def test_uint32_size(self) -> None:
        """UINT32_SIZE is 4 bytes."""
        assert get_prefix_size(PrefixCode.UINT32_SIZE) == 4
