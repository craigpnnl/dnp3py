"""Tests for Analog Input objects (Groups 30 and 32)."""

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import AnalogQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.analog_input import (
    ANALOG_INPUT_EVENT_GROUP,
    ANALOG_INPUT_STATIC_GROUP,
    AnalogInput16,
    AnalogInput16NoFlag,
    AnalogInput32,
    AnalogInput32NoFlag,
    AnalogInputDouble,
    AnalogInputEvent16,
    AnalogInputEvent16Time,
    AnalogInputEvent32,
    AnalogInputEvent32Time,
    AnalogInputEventDouble,
    AnalogInputEventDoubleTime,
    AnalogInputEventFloat,
    AnalogInputEventFloatTime,
    AnalogInputFloat,
)
from dnp3.objects.base import EventObject, StaticObject


class TestConstants:
    """Tests for analog input constants."""

    def test_static_group(self) -> None:
        """Static group is 30."""
        assert ANALOG_INPUT_STATIC_GROUP == 30

    def test_event_group(self) -> None:
        """Event group is 32."""
        assert ANALOG_INPUT_EVENT_GROUP == 32


class TestAnalogInput32:
    """Tests for AnalogInput32 (g30v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInput32.GROUP == 30
        assert AnalogInput32.VARIATION == 1

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert AnalogInput32.SIZE == 5

    def test_is_static_object(self) -> None:
        """AnalogInput32 is a StaticObject."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=0)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic analog input."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=12345)
        assert obj.quality == AnalogQuality.ONLINE
        assert obj.value == 12345

    def test_value_min(self) -> None:
        """Minimum value is valid."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=-(2**31))
        assert obj.value == -(2**31)

    def test_value_max(self) -> None:
        """Maximum value is valid."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=2**31 - 1)
        assert obj.value == 2**31 - 1

    def test_value_too_small_raises(self) -> None:
        """Value below minimum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            AnalogInput32(quality=AnalogQuality.ONLINE, value=-(2**31) - 1)

    def test_value_too_large_raises(self) -> None:
        """Value above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            AnalogInput32(quality=AnalogQuality.ONLINE, value=2**31)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=0x12345678)
        data = obj.to_bytes()
        assert len(data) == 5
        assert data[0] == 0x01  # ONLINE
        assert data[1:] == bytes([0x78, 0x56, 0x34, 0x12])

    def test_to_bytes_negative(self) -> None:
        """Serialize negative value."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=-1)
        data = obj.to_bytes()
        assert data[1:] == bytes([0xFF, 0xFF, 0xFF, 0xFF])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x01, 0x78, 0x56, 0x34, 0x12])
        obj = AnalogInput32.from_bytes(data)
        assert obj.quality == AnalogQuality.ONLINE
        assert obj.value == 0x12345678

    def test_from_bytes_negative(self) -> None:
        """Parse negative value."""
        data = bytes([0x01, 0xFF, 0xFF, 0xFF, 0xFF])
        obj = AnalogInput32.from_bytes(data)
        assert obj.value == -1

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            AnalogInput32.from_bytes(bytes([0x01, 0x00]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = AnalogInput32(quality=AnalogQuality.ONLINE | AnalogQuality.OVER_RANGE, value=-100000)
        parsed = AnalogInput32.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**31), max_value=2**31 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = AnalogInput32(quality=quality, value=value)
        parsed = AnalogInput32.from_bytes(original.to_bytes())
        assert parsed == original

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        obj = AnalogInput32(quality=AnalogQuality.ONLINE, value=0)
        assert obj.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        obj = AnalogInput32(quality=AnalogQuality(0), value=0)
        assert obj.is_online is False


class TestAnalogInput16:
    """Tests for AnalogInput16 (g30v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInput16.GROUP == 30
        assert AnalogInput16.VARIATION == 2

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert AnalogInput16.SIZE == 3

    def test_is_static_object(self) -> None:
        """AnalogInput16 is a StaticObject."""
        obj = AnalogInput16(quality=AnalogQuality.ONLINE, value=0)
        assert isinstance(obj, StaticObject)

    def test_value_min(self) -> None:
        """Minimum value is valid."""
        obj = AnalogInput16(quality=AnalogQuality.ONLINE, value=-(2**15))
        assert obj.value == -(2**15)

    def test_value_max(self) -> None:
        """Maximum value is valid."""
        obj = AnalogInput16(quality=AnalogQuality.ONLINE, value=2**15 - 1)
        assert obj.value == 2**15 - 1

    def test_value_too_small_raises(self) -> None:
        """Value below minimum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            AnalogInput16(quality=AnalogQuality.ONLINE, value=-(2**15) - 1)

    def test_value_too_large_raises(self) -> None:
        """Value above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            AnalogInput16(quality=AnalogQuality.ONLINE, value=2**15)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInput16(quality=AnalogQuality.ONLINE, value=0x1234)
        data = obj.to_bytes()
        assert len(data) == 3
        assert data[0] == 0x01
        assert data[1:] == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x01, 0x34, 0x12])
        obj = AnalogInput16.from_bytes(data)
        assert obj.value == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            AnalogInput16.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**15), max_value=2**15 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = AnalogInput16(quality=quality, value=value)
        parsed = AnalogInput16.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInput32NoFlag:
    """Tests for AnalogInput32NoFlag (g30v3)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInput32NoFlag.GROUP == 30
        assert AnalogInput32NoFlag.VARIATION == 3

    def test_size(self) -> None:
        """Size is 4 bytes."""
        assert AnalogInput32NoFlag.SIZE == 4

    def test_is_static_object(self) -> None:
        """AnalogInput32NoFlag is a StaticObject."""
        obj = AnalogInput32NoFlag(value=0)
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInput32NoFlag(value=0x12345678)
        data = obj.to_bytes()
        assert len(data) == 4
        assert data == bytes([0x78, 0x56, 0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x78, 0x56, 0x34, 0x12])
        obj = AnalogInput32NoFlag.from_bytes(data)
        assert obj.value == 0x12345678

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 4 bytes"):
            AnalogInput32NoFlag.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=-(2**31), max_value=2**31 - 1))
    def test_roundtrip_hypothesis(self, value: int) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInput32NoFlag(value=value)
        parsed = AnalogInput32NoFlag.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInput16NoFlag:
    """Tests for AnalogInput16NoFlag (g30v4)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInput16NoFlag.GROUP == 30
        assert AnalogInput16NoFlag.VARIATION == 4

    def test_size(self) -> None:
        """Size is 2 bytes."""
        assert AnalogInput16NoFlag.SIZE == 2

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInput16NoFlag(value=0x1234)
        data = obj.to_bytes()
        assert data == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x34, 0x12])
        obj = AnalogInput16NoFlag.from_bytes(data)
        assert obj.value == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            AnalogInput16NoFlag.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=-(2**15), max_value=2**15 - 1))
    def test_roundtrip_hypothesis(self, value: int) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInput16NoFlag(value=value)
        parsed = AnalogInput16NoFlag.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInputFloat:
    """Tests for AnalogInputFloat (g30v5)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputFloat.GROUP == 30
        assert AnalogInputFloat.VARIATION == 5

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert AnalogInputFloat.SIZE == 5

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInputFloat(quality=AnalogQuality.ONLINE, value=3.14)
        data = obj.to_bytes()
        assert len(data) == 5
        assert data[0] == 0x01
        # Verify it's valid IEEE 754 float
        (parsed_float,) = struct.unpack("<f", data[1:5])
        assert abs(parsed_float - 3.14) < 0.001

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        float_bytes = struct.pack("<f", 3.14)
        data = bytes([0x01]) + float_bytes
        obj = AnalogInputFloat.from_bytes(data)
        assert obj.quality == AnalogQuality.ONLINE
        assert abs(obj.value - 3.14) < 0.001

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            AnalogInputFloat.from_bytes(bytes([0x01, 0x00]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = AnalogInputFloat(quality=AnalogQuality.ONLINE, value=123.456)
        parsed = AnalogInputFloat.from_bytes(original.to_bytes())
        assert parsed.quality == original.quality
        # Float comparison with tolerance
        assert abs(parsed.value - original.value) < 0.001

    @given(st.floats(allow_nan=False, allow_infinity=False, width=32))
    def test_roundtrip_hypothesis(self, value: float) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInputFloat(quality=AnalogQuality.ONLINE, value=value)
        parsed = AnalogInputFloat.from_bytes(original.to_bytes())
        assert parsed.value == original.value


class TestAnalogInputDouble:
    """Tests for AnalogInputDouble (g30v6)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputDouble.GROUP == 30
        assert AnalogInputDouble.VARIATION == 6

    def test_size(self) -> None:
        """Size is 9 bytes."""
        assert AnalogInputDouble.SIZE == 9

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInputDouble(quality=AnalogQuality.ONLINE, value=3.14159265359)
        data = obj.to_bytes()
        assert len(data) == 9
        assert data[0] == 0x01

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        double_bytes = struct.pack("<d", 3.14159265359)
        data = bytes([0x01]) + double_bytes
        obj = AnalogInputDouble.from_bytes(data)
        assert obj.quality == AnalogQuality.ONLINE
        assert abs(obj.value - 3.14159265359) < 1e-10

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 9 bytes"):
            AnalogInputDouble.from_bytes(bytes([0x01, 0x00]))

    @given(st.floats(allow_nan=False, allow_infinity=False))
    def test_roundtrip_hypothesis(self, value: float) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInputDouble(quality=AnalogQuality.ONLINE, value=value)
        parsed = AnalogInputDouble.from_bytes(original.to_bytes())
        assert parsed.value == original.value


class TestAnalogInputEvent32:
    """Tests for AnalogInputEvent32 (g32v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEvent32.GROUP == 32
        assert AnalogInputEvent32.VARIATION == 1

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert AnalogInputEvent32.SIZE == 5

    def test_is_event_object(self) -> None:
        """AnalogInputEvent32 is an EventObject."""
        obj = AnalogInputEvent32(quality=AnalogQuality.ONLINE, value=0)
        assert isinstance(obj, EventObject)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = AnalogInputEvent32(quality=AnalogQuality.ONLINE, value=12345)
        data = obj.to_bytes()
        assert len(data) == 5

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x01, 0x39, 0x30, 0x00, 0x00])  # 12345 in little-endian
        obj = AnalogInputEvent32.from_bytes(data)
        assert obj.value == 12345

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            AnalogInputEvent32.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**31), max_value=2**31 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = AnalogInputEvent32(quality=quality, value=value)
        parsed = AnalogInputEvent32.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInputEvent16:
    """Tests for AnalogInputEvent16 (g32v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEvent16.GROUP == 32
        assert AnalogInputEvent16.VARIATION == 2

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert AnalogInputEvent16.SIZE == 3

    def test_is_event_object(self) -> None:
        """AnalogInputEvent16 is an EventObject."""
        obj = AnalogInputEvent16(quality=AnalogQuality.ONLINE, value=0)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            AnalogInputEvent16.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**15), max_value=2**15 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = AnalogInputEvent16(quality=quality, value=value)
        parsed = AnalogInputEvent16.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInputEvent32Time:
    """Tests for AnalogInputEvent32Time (g32v3)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEvent32Time.GROUP == 32
        assert AnalogInputEvent32Time.VARIATION == 3

    def test_size(self) -> None:
        """Size is 11 bytes."""
        assert AnalogInputEvent32Time.SIZE == 11

    def test_is_event_object(self) -> None:
        """AnalogInputEvent32Time is an EventObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = AnalogInputEvent32Time(quality=AnalogQuality.ONLINE, value=0, timestamp=ts)
        assert isinstance(obj, EventObject)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        ts = DNP3Timestamp(milliseconds=1000)
        obj = AnalogInputEvent32Time(quality=AnalogQuality.ONLINE, value=12345, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 11

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        # quality + value(4) + timestamp(6)
        value_bytes = (12345).to_bytes(4, "little", signed=True)
        ts_bytes = (1000).to_bytes(6, "little")
        data = bytes([0x01]) + value_bytes + ts_bytes
        obj = AnalogInputEvent32Time.from_bytes(data)
        assert obj.value == 12345
        assert obj.timestamp.milliseconds == 1000

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            AnalogInputEvent32Time.from_bytes(bytes([0x01, 0x00, 0x00]))

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**31), max_value=2**31 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = AnalogInputEvent32Time(quality=quality, value=value, timestamp=ts)
        parsed = AnalogInputEvent32Time.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInputEvent16Time:
    """Tests for AnalogInputEvent16Time (g32v4)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEvent16Time.GROUP == 32
        assert AnalogInputEvent16Time.VARIATION == 4

    def test_size(self) -> None:
        """Size is 9 bytes."""
        assert AnalogInputEvent16Time.SIZE == 9

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 9 bytes"):
            AnalogInputEvent16Time.from_bytes(bytes([0x01, 0x00]))

    @given(
        st.sampled_from(list(AnalogQuality)),
        st.integers(min_value=-(2**15), max_value=2**15 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: AnalogQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = AnalogInputEvent16Time(quality=quality, value=value, timestamp=ts)
        parsed = AnalogInputEvent16Time.from_bytes(original.to_bytes())
        assert parsed == original


class TestAnalogInputEventFloat:
    """Tests for AnalogInputEventFloat (g32v5)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEventFloat.GROUP == 32
        assert AnalogInputEventFloat.VARIATION == 5

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert AnalogInputEventFloat.SIZE == 5

    def test_is_event_object(self) -> None:
        """AnalogInputEventFloat is an EventObject."""
        obj = AnalogInputEventFloat(quality=AnalogQuality.ONLINE, value=0.0)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            AnalogInputEventFloat.from_bytes(bytes([0x01]))

    @given(st.floats(allow_nan=False, allow_infinity=False, width=32))
    def test_roundtrip_hypothesis(self, value: float) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInputEventFloat(quality=AnalogQuality.ONLINE, value=value)
        parsed = AnalogInputEventFloat.from_bytes(original.to_bytes())
        assert parsed.value == original.value


class TestAnalogInputEventDouble:
    """Tests for AnalogInputEventDouble (g32v6)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEventDouble.GROUP == 32
        assert AnalogInputEventDouble.VARIATION == 6

    def test_size(self) -> None:
        """Size is 9 bytes."""
        assert AnalogInputEventDouble.SIZE == 9

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 9 bytes"):
            AnalogInputEventDouble.from_bytes(bytes([0x01]))

    @given(st.floats(allow_nan=False, allow_infinity=False))
    def test_roundtrip_hypothesis(self, value: float) -> None:
        """Property: roundtrip preserves value."""
        original = AnalogInputEventDouble(quality=AnalogQuality.ONLINE, value=value)
        parsed = AnalogInputEventDouble.from_bytes(original.to_bytes())
        assert parsed.value == original.value


class TestAnalogInputEventFloatTime:
    """Tests for AnalogInputEventFloatTime (g32v7)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEventFloatTime.GROUP == 32
        assert AnalogInputEventFloatTime.VARIATION == 7

    def test_size(self) -> None:
        """Size is 11 bytes."""
        assert AnalogInputEventFloatTime.SIZE == 11

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            AnalogInputEventFloatTime.from_bytes(bytes([0x01]))

    @given(
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, value: float, ms: int) -> None:
        """Property: roundtrip preserves value."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = AnalogInputEventFloatTime(quality=AnalogQuality.ONLINE, value=value, timestamp=ts)
        parsed = AnalogInputEventFloatTime.from_bytes(original.to_bytes())
        assert parsed.value == original.value
        assert parsed.timestamp == original.timestamp


class TestAnalogInputEventDoubleTime:
    """Tests for AnalogInputEventDoubleTime (g32v8)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert AnalogInputEventDoubleTime.GROUP == 32
        assert AnalogInputEventDoubleTime.VARIATION == 8

    def test_size(self) -> None:
        """Size is 15 bytes."""
        assert AnalogInputEventDoubleTime.SIZE == 15

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 15 bytes"):
            AnalogInputEventDoubleTime.from_bytes(bytes([0x01]))

    @given(
        st.floats(allow_nan=False, allow_infinity=False),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, value: float, ms: int) -> None:
        """Property: roundtrip preserves value."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = AnalogInputEventDoubleTime(quality=AnalogQuality.ONLINE, value=value, timestamp=ts)
        parsed = AnalogInputEventDoubleTime.from_bytes(original.to_bytes())
        assert parsed.value == original.value
        assert parsed.timestamp == original.timestamp
