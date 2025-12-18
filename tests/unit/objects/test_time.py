"""Tests for Time objects (Groups 50, 51, 52)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import StaticObject
from dnp3.objects.time import (
    TIME_AND_DATE_GROUP,
    TIME_CTO_GROUP,
    TIME_DELAY_GROUP,
    TimeAndDate,
    TimeCTO,
    TimeCTOUnsync,
    TimeDelayCoarse,
    TimeDelayFine,
)


class TestConstants:
    """Tests for time constants."""

    def test_time_and_date_group(self) -> None:
        """Time and date group is 50."""
        assert TIME_AND_DATE_GROUP == 50

    def test_time_cto_group(self) -> None:
        """Time CTO group is 51."""
        assert TIME_CTO_GROUP == 51

    def test_time_delay_group(self) -> None:
        """Time delay group is 52."""
        assert TIME_DELAY_GROUP == 52


class TestTimeAndDate:
    """Tests for TimeAndDate (g50v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert TimeAndDate.GROUP == 50
        assert TimeAndDate.VARIATION == 1

    def test_size(self) -> None:
        """Size is 6 bytes."""
        assert TimeAndDate.SIZE == 6

    def test_is_static_object(self) -> None:
        """TimeAndDate is a StaticObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = TimeAndDate(timestamp=ts)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic time and date."""
        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = TimeAndDate(timestamp=ts)
        assert obj.timestamp == ts

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        ts = DNP3Timestamp(milliseconds=0x0102030405)
        obj = TimeAndDate(timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 6
        assert data == bytes([0x05, 0x04, 0x03, 0x02, 0x01, 0x00])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x05, 0x04, 0x03, 0x02, 0x01, 0x00])
        obj = TimeAndDate.from_bytes(data)
        assert obj.timestamp.milliseconds == 0x0102030405

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 6 bytes"):
            TimeAndDate.from_bytes(bytes([0x01, 0x00]))

    @given(st.integers(min_value=0, max_value=2**48 - 1))
    def test_roundtrip_hypothesis(self, ms: int) -> None:
        """Property: roundtrip preserves value."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = TimeAndDate(timestamp=ts)
        parsed = TimeAndDate.from_bytes(original.to_bytes())
        assert parsed == original


class TestTimeCTO:
    """Tests for TimeCTO (g51v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert TimeCTO.GROUP == 51
        assert TimeCTO.VARIATION == 1

    def test_size(self) -> None:
        """Size is 6 bytes."""
        assert TimeCTO.SIZE == 6

    def test_is_static_object(self) -> None:
        """TimeCTO is a StaticObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = TimeCTO(timestamp=ts)
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        ts = DNP3Timestamp(milliseconds=1000)
        obj = TimeCTO(timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 6

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        ts_bytes = (1000).to_bytes(6, "little")
        obj = TimeCTO.from_bytes(ts_bytes)
        assert obj.timestamp.milliseconds == 1000

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 6 bytes"):
            TimeCTO.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=2**48 - 1))
    def test_roundtrip_hypothesis(self, ms: int) -> None:
        """Property: roundtrip preserves value."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = TimeCTO(timestamp=ts)
        parsed = TimeCTO.from_bytes(original.to_bytes())
        assert parsed == original


class TestTimeCTOUnsync:
    """Tests for TimeCTOUnsync (g51v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert TimeCTOUnsync.GROUP == 51
        assert TimeCTOUnsync.VARIATION == 2

    def test_size(self) -> None:
        """Size is 6 bytes."""
        assert TimeCTOUnsync.SIZE == 6

    def test_is_static_object(self) -> None:
        """TimeCTOUnsync is a StaticObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = TimeCTOUnsync(timestamp=ts)
        assert isinstance(obj, StaticObject)

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 6 bytes"):
            TimeCTOUnsync.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=2**48 - 1))
    def test_roundtrip_hypothesis(self, ms: int) -> None:
        """Property: roundtrip preserves value."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = TimeCTOUnsync(timestamp=ts)
        parsed = TimeCTOUnsync.from_bytes(original.to_bytes())
        assert parsed == original


class TestTimeDelayCoarse:
    """Tests for TimeDelayCoarse (g52v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert TimeDelayCoarse.GROUP == 52
        assert TimeDelayCoarse.VARIATION == 1

    def test_size(self) -> None:
        """Size is 2 bytes."""
        assert TimeDelayCoarse.SIZE == 2

    def test_is_static_object(self) -> None:
        """TimeDelayCoarse is a StaticObject."""
        obj = TimeDelayCoarse(delay_seconds=0)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic coarse delay."""
        obj = TimeDelayCoarse(delay_seconds=100)
        assert obj.delay_seconds == 100

    def test_delay_zero(self) -> None:
        """Delay 0 is valid."""
        obj = TimeDelayCoarse(delay_seconds=0)
        assert obj.delay_seconds == 0

    def test_delay_max(self) -> None:
        """Maximum delay is valid."""
        obj = TimeDelayCoarse(delay_seconds=65535)
        assert obj.delay_seconds == 65535

    def test_delay_negative_raises(self) -> None:
        """Negative delay raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TimeDelayCoarse(delay_seconds=-1)

    def test_delay_too_large_raises(self) -> None:
        """Delay above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TimeDelayCoarse(delay_seconds=65536)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = TimeDelayCoarse(delay_seconds=0x1234)
        data = obj.to_bytes()
        assert data == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x34, 0x12])
        obj = TimeDelayCoarse.from_bytes(data)
        assert obj.delay_seconds == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            TimeDelayCoarse.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=65535))
    def test_roundtrip_hypothesis(self, delay: int) -> None:
        """Property: roundtrip preserves value."""
        original = TimeDelayCoarse(delay_seconds=delay)
        parsed = TimeDelayCoarse.from_bytes(original.to_bytes())
        assert parsed == original


class TestTimeDelayFine:
    """Tests for TimeDelayFine (g52v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert TimeDelayFine.GROUP == 52
        assert TimeDelayFine.VARIATION == 2

    def test_size(self) -> None:
        """Size is 2 bytes."""
        assert TimeDelayFine.SIZE == 2

    def test_is_static_object(self) -> None:
        """TimeDelayFine is a StaticObject."""
        obj = TimeDelayFine(delay_ms=0)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic fine delay."""
        obj = TimeDelayFine(delay_ms=1000)
        assert obj.delay_ms == 1000

    def test_delay_zero(self) -> None:
        """Delay 0 is valid."""
        obj = TimeDelayFine(delay_ms=0)
        assert obj.delay_ms == 0

    def test_delay_max(self) -> None:
        """Maximum delay is valid."""
        obj = TimeDelayFine(delay_ms=65535)
        assert obj.delay_ms == 65535

    def test_delay_negative_raises(self) -> None:
        """Negative delay raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TimeDelayFine(delay_ms=-1)

    def test_delay_too_large_raises(self) -> None:
        """Delay above maximum raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TimeDelayFine(delay_ms=65536)

    def test_to_bytes(self) -> None:
        """Serialize to bytes."""
        obj = TimeDelayFine(delay_ms=0x1234)
        data = obj.to_bytes()
        assert data == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse from bytes."""
        data = bytes([0x34, 0x12])
        obj = TimeDelayFine.from_bytes(data)
        assert obj.delay_ms == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            TimeDelayFine.from_bytes(bytes([0x01]))

    @given(st.integers(min_value=0, max_value=65535))
    def test_roundtrip_hypothesis(self, delay: int) -> None:
        """Property: roundtrip preserves value."""
        original = TimeDelayFine(delay_ms=delay)
        parsed = TimeDelayFine.from_bytes(original.to_bytes())
        assert parsed == original
