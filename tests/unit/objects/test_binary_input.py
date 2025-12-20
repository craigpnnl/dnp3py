"""Tests for Binary Input objects (Groups 1 and 2)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import BinaryQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import EventObject, StaticObject
from dnp3.objects.binary_input import (
    BINARY_INPUT_EVENT_GROUP,
    BINARY_INPUT_STATIC_GROUP,
    STATE_BIT,
    BinaryInputEvent,
    BinaryInputEventRelativeTime,
    BinaryInputEventTime,
    BinaryInputFlags,
)

# Quality flags valid for binary input (bits 0-6 only, not STATE bit 7)
VALID_QUALITY_FLAGS = [q for q in BinaryQuality if q != BinaryQuality.STATE and q.value <= 0x7F]


class TestConstants:
    """Tests for binary input constants."""

    def test_static_group(self) -> None:
        """Static group is 1."""
        assert BINARY_INPUT_STATIC_GROUP == 1

    def test_event_group(self) -> None:
        """Event group is 2."""
        assert BINARY_INPUT_EVENT_GROUP == 2

    def test_state_bit(self) -> None:
        """State bit is 0x80."""
        assert STATE_BIT == 0x80


class TestBinaryInputFlags:
    """Tests for BinaryInputFlags (g1v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryInputFlags.GROUP == 1
        assert BinaryInputFlags.VARIATION == 2

    def test_size(self) -> None:
        """Size is 1 byte."""
        assert BinaryInputFlags.SIZE == 1

    def test_is_static_object(self) -> None:
        """BinaryInputFlags is a StaticObject."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=False)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic binary input with flags."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=True)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_state_false(self) -> None:
        """Binary input with state False."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=False)
        assert obj.state is False

    def test_to_bytes_state_false(self) -> None:
        """Serialize with state=False."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=False)
        data = obj.to_bytes()
        assert data == bytes([0x01])  # ONLINE=0x01, state=0

    def test_to_bytes_state_true(self) -> None:
        """Serialize with state=True."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=True)
        data = obj.to_bytes()
        assert data == bytes([0x81])  # ONLINE=0x01 | STATE=0x80

    def test_to_bytes_multiple_quality_flags(self) -> None:
        """Serialize with multiple quality flags."""
        quality = BinaryQuality.ONLINE | BinaryQuality.RESTART
        obj = BinaryInputFlags(quality=quality, state=True)
        data = obj.to_bytes()
        # ONLINE=0x01, RESTART=0x02, STATE=0x80 -> 0x83
        assert data == bytes([0x83])

    def test_from_bytes_state_false(self) -> None:
        """Parse with state=False."""
        obj = BinaryInputFlags.from_bytes(bytes([0x01]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is False

    def test_from_bytes_state_true(self) -> None:
        """Parse with state=True."""
        obj = BinaryInputFlags.from_bytes(bytes([0x81]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_from_bytes_multiple_quality_flags(self) -> None:
        """Parse with multiple quality flags."""
        obj = BinaryInputFlags.from_bytes(bytes([0x83]))
        expected_quality = BinaryQuality.ONLINE | BinaryQuality.RESTART
        assert obj.quality == expected_quality
        assert obj.state is True

    def test_from_bytes_empty_raises(self) -> None:
        """Empty data raises error."""
        with pytest.raises(ValueError, match="requires 1 byte"):
            BinaryInputFlags.from_bytes(b"")

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = BinaryInputFlags(quality=BinaryQuality.ONLINE | BinaryQuality.LOCAL_FORCED, state=True)
        data = original.to_bytes()
        parsed = BinaryInputFlags.from_bytes(data)
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool) -> None:
        """Property: roundtrip preserves all values."""
        original = BinaryInputFlags(quality=quality, state=state)
        parsed = BinaryInputFlags.from_bytes(original.to_bytes())
        assert parsed == original

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=False)
        assert obj.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        obj = BinaryInputFlags(quality=BinaryQuality(0), state=False)
        assert obj.is_online is False

    def test_immutable(self) -> None:
        """BinaryInputFlags is immutable."""
        obj = BinaryInputFlags(quality=BinaryQuality.ONLINE, state=False)
        with pytest.raises(AttributeError):
            obj.state = True  # type: ignore[misc]


class TestBinaryInputEvent:
    """Tests for BinaryInputEvent (g2v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryInputEvent.GROUP == 2
        assert BinaryInputEvent.VARIATION == 1

    def test_size(self) -> None:
        """Size is 1 byte."""
        assert BinaryInputEvent.SIZE == 1

    def test_is_event_object(self) -> None:
        """BinaryInputEvent is an EventObject."""
        obj = BinaryInputEvent(quality=BinaryQuality.ONLINE, state=False)
        assert isinstance(obj, EventObject)

    def test_create_basic(self) -> None:
        """Create basic binary input event."""
        obj = BinaryInputEvent(quality=BinaryQuality.ONLINE, state=True)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_to_bytes_state_false(self) -> None:
        """Serialize with state=False."""
        obj = BinaryInputEvent(quality=BinaryQuality.ONLINE, state=False)
        data = obj.to_bytes()
        assert data == bytes([0x01])

    def test_to_bytes_state_true(self) -> None:
        """Serialize with state=True."""
        obj = BinaryInputEvent(quality=BinaryQuality.ONLINE, state=True)
        data = obj.to_bytes()
        assert data == bytes([0x81])

    def test_from_bytes_state_false(self) -> None:
        """Parse with state=False."""
        obj = BinaryInputEvent.from_bytes(bytes([0x01]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is False

    def test_from_bytes_state_true(self) -> None:
        """Parse with state=True."""
        obj = BinaryInputEvent.from_bytes(bytes([0x81]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_from_bytes_empty_raises(self) -> None:
        """Empty data raises error."""
        with pytest.raises(ValueError, match="requires 1 byte"):
            BinaryInputEvent.from_bytes(b"")

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = BinaryInputEvent(quality=BinaryQuality.ONLINE, state=True)
        parsed = BinaryInputEvent.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool) -> None:
        """Property: roundtrip preserves all values."""
        original = BinaryInputEvent(quality=quality, state=state)
        parsed = BinaryInputEvent.from_bytes(original.to_bytes())
        assert parsed == original


class TestBinaryInputEventTime:
    """Tests for BinaryInputEventTime (g2v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryInputEventTime.GROUP == 2
        assert BinaryInputEventTime.VARIATION == 2

    def test_size(self) -> None:
        """Size is 7 bytes."""
        assert BinaryInputEventTime.SIZE == 7

    def test_is_event_object(self) -> None:
        """BinaryInputEventTime is an EventObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = BinaryInputEventTime(quality=BinaryQuality.ONLINE, state=False, timestamp=ts)
        assert isinstance(obj, EventObject)

    def test_create_basic(self) -> None:
        """Create binary input event with time."""
        ts = DNP3Timestamp(milliseconds=1000)
        obj = BinaryInputEventTime(quality=BinaryQuality.ONLINE, state=True, timestamp=ts)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.timestamp == ts

    def test_to_bytes(self) -> None:
        """Serialize event with timestamp."""
        ts = DNP3Timestamp(milliseconds=0x0102030405)
        obj = BinaryInputEventTime(quality=BinaryQuality.ONLINE, state=True, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 7
        assert data[0] == 0x81  # ONLINE | STATE
        # Timestamp bytes in little-endian
        assert data[1:7] == bytes([0x05, 0x04, 0x03, 0x02, 0x01, 0x00])

    def test_from_bytes(self) -> None:
        """Parse event with timestamp."""
        data = bytes([0x81, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00])
        obj = BinaryInputEventTime.from_bytes(data)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.timestamp.milliseconds == 0x0102030405

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 7 bytes"):
            BinaryInputEventTime.from_bytes(bytes([0x81, 0x00, 0x00]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        ts = DNP3Timestamp(milliseconds=1234567890)
        original = BinaryInputEventTime(
            quality=BinaryQuality.ONLINE | BinaryQuality.CHATTER_FILTER,
            state=False,
            timestamp=ts,
        )
        parsed = BinaryInputEventTime.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = BinaryInputEventTime(quality=quality, state=state, timestamp=ts)
        parsed = BinaryInputEventTime.from_bytes(original.to_bytes())
        assert parsed == original


class TestBinaryInputEventRelativeTime:
    """Tests for BinaryInputEventRelativeTime (g2v3)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryInputEventRelativeTime.GROUP == 2
        assert BinaryInputEventRelativeTime.VARIATION == 3

    def test_size(self) -> None:
        """Size is 3 bytes."""
        assert BinaryInputEventRelativeTime.SIZE == 3

    def test_is_event_object(self) -> None:
        """BinaryInputEventRelativeTime is an EventObject."""
        obj = BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=False, relative_time_ms=0)
        assert isinstance(obj, EventObject)

    def test_create_basic(self) -> None:
        """Create binary input event with relative time."""
        obj = BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=True, relative_time_ms=1000)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.relative_time_ms == 1000

    def test_relative_time_zero(self) -> None:
        """Relative time 0 is valid."""
        obj = BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=False, relative_time_ms=0)
        assert obj.relative_time_ms == 0

    def test_relative_time_max(self) -> None:
        """Relative time 65535 is valid."""
        obj = BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=False, relative_time_ms=65535)
        assert obj.relative_time_ms == 65535

    def test_relative_time_negative_raises(self) -> None:
        """Negative relative time raises error."""
        with pytest.raises(ValueError, match="out of range"):
            BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=False, relative_time_ms=-1)

    def test_relative_time_too_large_raises(self) -> None:
        """Relative time > 65535 raises error."""
        with pytest.raises(ValueError, match="out of range"):
            BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=False, relative_time_ms=65536)

    def test_to_bytes(self) -> None:
        """Serialize event with relative time."""
        obj = BinaryInputEventRelativeTime(quality=BinaryQuality.ONLINE, state=True, relative_time_ms=0x1234)
        data = obj.to_bytes()
        assert len(data) == 3
        assert data[0] == 0x81  # ONLINE | STATE
        # Relative time in little-endian
        assert data[1:3] == bytes([0x34, 0x12])

    def test_from_bytes(self) -> None:
        """Parse event with relative time."""
        data = bytes([0x81, 0x34, 0x12])
        obj = BinaryInputEventRelativeTime.from_bytes(data)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.relative_time_ms == 0x1234

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 3 bytes"):
            BinaryInputEventRelativeTime.from_bytes(bytes([0x81]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = BinaryInputEventRelativeTime(
            quality=BinaryQuality.ONLINE | BinaryQuality.RESTART,
            state=True,
            relative_time_ms=30000,
        )
        parsed = BinaryInputEventRelativeTime.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
        st.integers(min_value=0, max_value=65535),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool, relative_ms: int) -> None:
        """Property: roundtrip preserves all values."""
        original = BinaryInputEventRelativeTime(quality=quality, state=state, relative_time_ms=relative_ms)
        parsed = BinaryInputEventRelativeTime.from_bytes(original.to_bytes())
        assert parsed == original
