"""Tests for Counter objects (Groups 20, 21, 22)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import EventObject, StaticObject
from dnp3.objects.counter import (
    COUNTER_EVENT_GROUP,
    COUNTER_STATIC_GROUP,
    FROZEN_COUNTER_GROUP,
    Counter16,
    Counter16NoFlag,
    Counter32,
    Counter32NoFlag,
    CounterEvent16,
    CounterEvent16Time,
    CounterEvent32,
    CounterEvent32Time,
    FrozenCounter16,
    FrozenCounter16Time,
    FrozenCounter32,
    FrozenCounter32Time,
)


class TestConstants:
    """Tests for counter constants."""

    def test_static_group(self) -> None:
        """Static group is 20."""
        assert COUNTER_STATIC_GROUP == 20

    def test_frozen_group(self) -> None:
        """Frozen counter group is 21."""
        assert FROZEN_COUNTER_GROUP == 21

    def test_event_group(self) -> None:
        """Event group is 22."""
        assert COUNTER_EVENT_GROUP == 22


class TestCounter32:
    """Tests for Counter32 (g20v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert Counter32.GROUP == 20
        assert Counter32.VARIATION == 1

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert Counter32.SIZE == 5

    def test_is_static_object(self) -> None:
        """Counter32 is a StaticObject."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=0)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic counter."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=12345)
        assert obj.quality == CounterQuality.ONLINE
        assert obj.value == 12345

    def test_value_zero(self) -> None:
        """Value 0 is valid."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=0)
        assert obj.value == 0

    def test_value_max(self) -> None:
        """Maximum value is valid."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=2**32 - 1)
        assert obj.value == 2**32 - 1

    def test_value_negative_raises(self) -> None:
        """Negative value raises error."""
        with pytest.raises(ValueError, match="out of range"):
            Counter32(quality=CounterQuality.ONLINE, value=-1)

    def test_value_too_large_raises(self) -> None:
        """Value above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            Counter32(quality=CounterQuality.ONLINE, value=2**32)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=0x12345678)
        data = obj.to_bytes()
        assert len(data) == 5
        assert data[0] == 0x01  # ONLINE
        assert data[1:] == bytes([0x78, 0x56, 0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x01, 0x78, 0x56, 0x34, 0x12])
        obj = Counter32.from_bytes(data)
        assert obj.quality == CounterQuality.ONLINE
        assert obj.value == 0x12345678

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            Counter32.from_bytes(bytes([0x01, 0x00]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**32 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = Counter32(quality=quality, value=value)
        parsed = Counter32.from_bytes(original.to_bytes())
        assert parsed == original

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        obj = Counter32(quality=CounterQuality.ONLINE, value=0)
        assert obj.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        obj = Counter32(quality=CounterQuality(0), value=0)
        assert obj.is_online is False


class TestCounter16:
    """Tests for Counter16 (g20v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert Counter16.GROUP == 20
        assert Counter16.VARIATION == 2

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert Counter16.SIZE == 3

    def test_value_max(self) -> None:
        """Maximum value is valid."""
        obj = Counter16(quality=CounterQuality.ONLINE, value=2**16 - 1)
        assert obj.value == 2**16 - 1

    def test_value_too_large_raises(self) -> None:
        """Value above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            Counter16(quality=CounterQuality.ONLINE, value=2**16)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = Counter16(quality=CounterQuality.ONLINE, value=0x1234)
        data = obj.to_bytes()
        assert len(data) == 3
        assert data[0] == 0x01
        assert data[1:] == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x01, 0x34, 0x12])
        obj = Counter16.from_bytes(data)
        assert obj.value == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            Counter16.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**16 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = Counter16(quality=quality, value=value)
        parsed = Counter16.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounter32NoFlag:
    """Tests for Counter32NoFlag (g20v5)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert Counter32NoFlag.GROUP == 20
        assert Counter32NoFlag.VARIATION == 5

    def test_size(self) -> None:
        """Size is 4 bytes."""
        assert Counter32NoFlag.SIZE == 4

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = Counter32NoFlag(value=0x12345678)
        data = obj.to_bytes()
        assert data == bytes([0x78, 0x56, 0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x78, 0x56, 0x34, 0x12])
        obj = Counter32NoFlag.from_bytes(data)
        assert obj.value == 0x12345678

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 4 bytes"):
            Counter32NoFlag.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=2**32 - 1))
    def test_roundtrip_hypothesis(self, value: int) -> None:
        """Property: roundtrip preserves value."""
        original = Counter32NoFlag(value=value)
        parsed = Counter32NoFlag.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounter16NoFlag:
    """Tests for Counter16NoFlag (g20v6)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert Counter16NoFlag.GROUP == 20
        assert Counter16NoFlag.VARIATION == 6

    def test_size(self) -> None:
        """Size is 2 bytes."""
        assert Counter16NoFlag.SIZE == 2

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = Counter16NoFlag(value=0x1234)
        data = obj.to_bytes()
        assert data == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x34, 0x12])
        obj = Counter16NoFlag.from_bytes(data)
        assert obj.value == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            Counter16NoFlag.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=2**16 - 1))
    def test_roundtrip_hypothesis(self, value: int) -> None:
        """Property: roundtrip preserves value."""
        original = Counter16NoFlag(value=value)
        parsed = Counter16NoFlag.from_bytes(original.to_bytes())
        assert parsed == original


class TestFrozenCounter32:
    """Tests for FrozenCounter32 (g21v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert FrozenCounter32.GROUP == 21
        assert FrozenCounter32.VARIATION == 1

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert FrozenCounter32.SIZE == 5

    def test_is_static_object(self) -> None:
        """FrozenCounter32 is a StaticObject."""
        obj = FrozenCounter32(quality=CounterQuality.ONLINE, value=0)
        assert isinstance(obj, StaticObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            FrozenCounter32.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**32 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = FrozenCounter32(quality=quality, value=value)
        parsed = FrozenCounter32.from_bytes(original.to_bytes())
        assert parsed == original


class TestFrozenCounter16:
    """Tests for FrozenCounter16 (g21v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert FrozenCounter16.GROUP == 21
        assert FrozenCounter16.VARIATION == 2

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert FrozenCounter16.SIZE == 3

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            FrozenCounter16.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**16 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = FrozenCounter16(quality=quality, value=value)
        parsed = FrozenCounter16.from_bytes(original.to_bytes())
        assert parsed == original


class TestFrozenCounter32Time:
    """Tests for FrozenCounter32Time (g21v5)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert FrozenCounter32Time.GROUP == 21
        assert FrozenCounter32Time.VARIATION == 5

    def test_size(self) -> None:
        """Size is 11 bytes."""
        assert FrozenCounter32Time.SIZE == 11

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        ts = DNP3Timestamp(milliseconds=1000)
        obj = FrozenCounter32Time(quality=CounterQuality.ONLINE, value=12345, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 11

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            FrozenCounter32Time.from_bytes(bytes([0x01, 0x00]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**32 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = FrozenCounter32Time(quality=quality, value=value, timestamp=ts)
        parsed = FrozenCounter32Time.from_bytes(original.to_bytes())
        assert parsed == original


class TestFrozenCounter16Time:
    """Tests for FrozenCounter16Time (g21v6)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert FrozenCounter16Time.GROUP == 21
        assert FrozenCounter16Time.VARIATION == 6

    def test_size(self) -> None:
        """Size is 9 bytes."""
        assert FrozenCounter16Time.SIZE == 9

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 9 bytes"):
            FrozenCounter16Time.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**16 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = FrozenCounter16Time(quality=quality, value=value, timestamp=ts)
        parsed = FrozenCounter16Time.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounterEvent32:
    """Tests for CounterEvent32 (g22v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert CounterEvent32.GROUP == 22
        assert CounterEvent32.VARIATION == 1

    def test_size(self) -> None:
        """Size is 5 bytes."""
        assert CounterEvent32.SIZE == 5

    def test_is_event_object(self) -> None:
        """CounterEvent32 is an EventObject."""
        obj = CounterEvent32(quality=CounterQuality.ONLINE, value=0)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 5 bytes"):
            CounterEvent32.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**32 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = CounterEvent32(quality=quality, value=value)
        parsed = CounterEvent32.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounterEvent16:
    """Tests for CounterEvent16 (g22v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert CounterEvent16.GROUP == 22
        assert CounterEvent16.VARIATION == 2

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert CounterEvent16.SIZE == 3

    def test_is_event_object(self) -> None:
        """CounterEvent16 is an EventObject."""
        obj = CounterEvent16(quality=CounterQuality.ONLINE, value=0)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            CounterEvent16.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**16 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int) -> None:
        """Property: roundtrip preserves all values."""
        original = CounterEvent16(quality=quality, value=value)
        parsed = CounterEvent16.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounterEvent32Time:
    """Tests for CounterEvent32Time (g22v5)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert CounterEvent32Time.GROUP == 22
        assert CounterEvent32Time.VARIATION == 5

    def test_size(self) -> None:
        """Size is 11 bytes."""
        assert CounterEvent32Time.SIZE == 11

    def test_is_event_object(self) -> None:
        """CounterEvent32Time is an EventObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = CounterEvent32Time(quality=CounterQuality.ONLINE, value=0, timestamp=ts)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            CounterEvent32Time.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**32 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = CounterEvent32Time(quality=quality, value=value, timestamp=ts)
        parsed = CounterEvent32Time.from_bytes(original.to_bytes())
        assert parsed == original


class TestCounterEvent16Time:
    """Tests for CounterEvent16Time (g22v6)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert CounterEvent16Time.GROUP == 22
        assert CounterEvent16Time.VARIATION == 6

    def test_size(self) -> None:
        """Size is 9 bytes."""
        assert CounterEvent16Time.SIZE == 9

    def test_is_event_object(self) -> None:
        """CounterEvent16Time is an EventObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = CounterEvent16Time(quality=CounterQuality.ONLINE, value=0, timestamp=ts)
        assert isinstance(obj, EventObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 9 bytes"):
            CounterEvent16Time.from_bytes(bytes([0x01]))

    @given(
        st.sampled_from(list(CounterQuality)),
        st.integers(min_value=0, max_value=2**16 - 1),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: CounterQuality, value: int, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = CounterEvent16Time(quality=quality, value=value, timestamp=ts)
        parsed = CounterEvent16Time.from_bytes(original.to_bytes())
        assert parsed == original
