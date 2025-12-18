"""Tests for point definitions."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.point import (
    AnalogInputConfig,
    AnalogInputPoint,
    BinaryInputConfig,
    BinaryInputPoint,
    BinaryOutputConfig,
    BinaryOutputPoint,
    CounterConfig,
    CounterPoint,
    EventClass,
    FrozenCounterPoint,
    PointConfig,
)


class TestEventClass:
    """Tests for EventClass enum."""

    def test_none_is_zero(self) -> None:
        """NONE is 0."""
        assert EventClass.NONE == 0

    def test_class_values(self) -> None:
        """Class values are 1, 2, 3."""
        assert EventClass.CLASS_1 == 1
        assert EventClass.CLASS_2 == 2
        assert EventClass.CLASS_3 == 3


class TestPointConfig:
    """Tests for PointConfig base class."""

    def test_default_event_class(self) -> None:
        """Default event class is CLASS_1."""
        config = PointConfig()
        assert config.event_class == EventClass.CLASS_1

    def test_custom_event_class(self) -> None:
        """Can set custom event class."""
        config = PointConfig(event_class=EventClass.CLASS_3)
        assert config.event_class == EventClass.CLASS_3


class TestBinaryInputConfig:
    """Tests for BinaryInputConfig."""

    def test_inherits_point_config(self) -> None:
        """BinaryInputConfig inherits from PointConfig."""
        config = BinaryInputConfig()
        assert isinstance(config, PointConfig)

    def test_default_event_class(self) -> None:
        """Default event class is CLASS_1."""
        config = BinaryInputConfig()
        assert config.event_class == EventClass.CLASS_1


class TestAnalogInputConfig:
    """Tests for AnalogInputConfig."""

    def test_default_deadband(self) -> None:
        """Default deadband is 0."""
        config = AnalogInputConfig()
        assert config.deadband == 0.0

    def test_custom_deadband(self) -> None:
        """Can set custom deadband."""
        config = AnalogInputConfig(deadband=5.0)
        assert config.deadband == 5.0


class TestCounterConfig:
    """Tests for CounterConfig."""

    def test_default_deadband(self) -> None:
        """Default deadband is 0."""
        config = CounterConfig()
        assert config.deadband == 0

    def test_custom_deadband(self) -> None:
        """Can set custom deadband."""
        config = CounterConfig(deadband=10)
        assert config.deadband == 10


class TestBinaryInputPoint:
    """Tests for BinaryInputPoint."""

    def test_create_with_defaults(self) -> None:
        """Create point with default values."""
        point = BinaryInputPoint(index=0)
        assert point.index == 0
        assert point.value is False
        assert point.quality == BinaryQuality.RESTART
        assert point.timestamp is None

    def test_create_with_values(self) -> None:
        """Create point with specific values."""
        ts = DNP3Timestamp(milliseconds=1000)
        point = BinaryInputPoint(
            index=5,
            value=True,
            quality=BinaryQuality.ONLINE,
            timestamp=ts,
        )
        assert point.index == 5
        assert point.value is True
        assert point.quality == BinaryQuality.ONLINE
        assert point.timestamp == ts

    def test_update_value_generates_event(self) -> None:
        """Update with value change generates event."""
        point = BinaryInputPoint(index=0, value=False)
        result = point.update(value=True)
        assert result is True
        assert point.value is True

    def test_update_same_value_no_event(self) -> None:
        """Update with same value does not generate event."""
        point = BinaryInputPoint(index=0, value=True, quality=BinaryQuality.ONLINE)
        result = point.update(value=True, quality=BinaryQuality.ONLINE)
        assert result is False

    def test_update_quality_change_generates_event(self) -> None:
        """Update with quality change generates event."""
        point = BinaryInputPoint(index=0, value=True, quality=BinaryQuality.ONLINE)
        result = point.update(value=True, quality=BinaryQuality.COMM_LOST)
        assert result is True

    def test_update_sets_online_by_default(self) -> None:
        """Update sets ONLINE quality by default."""
        point = BinaryInputPoint(index=0)
        point.update(value=True)
        assert point.quality == BinaryQuality.ONLINE

    def test_update_with_timestamp(self) -> None:
        """Update stores timestamp."""
        point = BinaryInputPoint(index=0)
        ts = DNP3Timestamp(milliseconds=5000)
        point.update(value=True, timestamp=ts)
        assert point.timestamp == ts

    def test_no_event_when_class_none(self) -> None:
        """No event when event class is NONE."""
        config = BinaryInputConfig(event_class=EventClass.NONE)
        point = BinaryInputPoint(index=0, value=False, config=config)
        result = point.update(value=True)
        assert result is False

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        point = BinaryInputPoint(index=0, quality=BinaryQuality.ONLINE)
        assert point.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        point = BinaryInputPoint(index=0, quality=BinaryQuality.RESTART)
        assert point.is_online is False


class TestBinaryOutputPoint:
    """Tests for BinaryOutputPoint."""

    def test_create_with_defaults(self) -> None:
        """Create point with default values."""
        point = BinaryOutputPoint(index=0)
        assert point.index == 0
        assert point.value is False
        assert point.quality == BinaryQuality.RESTART

    def test_update_value_generates_event(self) -> None:
        """Update with value change generates event."""
        point = BinaryOutputPoint(index=0, value=False)
        result = point.update(value=True)
        assert result is True
        assert point.value is True

    def test_update_same_value_no_event(self) -> None:
        """Update with same value does not generate event."""
        point = BinaryOutputPoint(index=0, value=True, quality=BinaryQuality.ONLINE)
        result = point.update(value=True, quality=BinaryQuality.ONLINE)
        assert result is False

    def test_no_event_when_class_none(self) -> None:
        """No event when event class is NONE."""
        config = BinaryOutputConfig(event_class=EventClass.NONE)
        point = BinaryOutputPoint(index=0, value=False, config=config)
        result = point.update(value=True)
        assert result is False


class TestAnalogInputPoint:
    """Tests for AnalogInputPoint."""

    def test_create_with_defaults(self) -> None:
        """Create point with default values."""
        point = AnalogInputPoint(index=0)
        assert point.index == 0
        assert point.value == 0.0
        assert point.quality == AnalogQuality.RESTART
        assert point.last_event_value == 0.0

    def test_update_generates_event_no_deadband(self) -> None:
        """Update generates event with zero deadband."""
        point = AnalogInputPoint(index=0)
        result = point.update(value=10.0)
        assert result is True
        assert point.value == 10.0

    def test_update_within_deadband_no_event(self) -> None:
        """Update within deadband does not generate event."""
        config = AnalogInputConfig(deadband=5.0)
        point = AnalogInputPoint(index=0, value=10.0, config=config)
        point.last_event_value = 10.0
        result = point.update(value=12.0)  # Change of 2, less than deadband of 5
        assert result is False

    def test_update_exceeds_deadband_generates_event(self) -> None:
        """Update exceeding deadband generates event."""
        config = AnalogInputConfig(deadband=5.0)
        point = AnalogInputPoint(index=0, value=10.0, config=config)
        point.last_event_value = 10.0
        result = point.update(value=16.0)  # Change of 6, exceeds deadband of 5
        assert result is True
        assert point.last_event_value == 16.0

    def test_deadband_uses_absolute_value(self) -> None:
        """Deadband check uses absolute value of change."""
        config = AnalogInputConfig(deadband=5.0)
        point = AnalogInputPoint(index=0, value=10.0, config=config)
        point.last_event_value = 10.0
        result = point.update(value=4.0)  # Change of -6, absolute value exceeds deadband
        assert result is True

    def test_update_sets_online_by_default(self) -> None:
        """Update sets ONLINE quality by default."""
        point = AnalogInputPoint(index=0)
        point.update(value=10.0)
        assert point.quality == AnalogQuality.ONLINE

    def test_no_event_when_class_none(self) -> None:
        """No event when event class is NONE."""
        config = AnalogInputConfig(event_class=EventClass.NONE)
        point = AnalogInputPoint(index=0, config=config)
        result = point.update(value=100.0)
        assert result is False

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        point = AnalogInputPoint(index=0, quality=AnalogQuality.ONLINE)
        assert point.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        point = AnalogInputPoint(index=0, quality=AnalogQuality.RESTART)
        assert point.is_online is False

    @given(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e10, max_value=1e10))
    def test_update_stores_value(self, value: float) -> None:
        """Update stores any valid float value."""
        point = AnalogInputPoint(index=0)
        point.update(value=value)
        assert point.value == value


class TestCounterPoint:
    """Tests for CounterPoint."""

    def test_create_with_defaults(self) -> None:
        """Create point with default values."""
        point = CounterPoint(index=0)
        assert point.index == 0
        assert point.value == 0
        assert point.quality == CounterQuality.RESTART
        assert point.last_event_value == 0

    def test_update_generates_event_no_deadband(self) -> None:
        """Update generates event with zero deadband."""
        point = CounterPoint(index=0)
        result = point.update(value=100)
        assert result is True
        assert point.value == 100

    def test_update_within_deadband_no_event(self) -> None:
        """Update within deadband does not generate event."""
        config = CounterConfig(deadband=10)
        point = CounterPoint(index=0, value=100, config=config)
        point.last_event_value = 100
        result = point.update(value=105)  # Change of 5, less than deadband of 10
        assert result is False

    def test_update_exceeds_deadband_generates_event(self) -> None:
        """Update exceeding deadband generates event."""
        config = CounterConfig(deadband=10)
        point = CounterPoint(index=0, value=100, config=config)
        point.last_event_value = 100
        result = point.update(value=115)  # Change of 15, exceeds deadband of 10
        assert result is True
        assert point.last_event_value == 115

    def test_update_negative_raises(self) -> None:
        """Update with negative value raises error."""
        point = CounterPoint(index=0)
        with pytest.raises(ValueError, match="out of range"):
            point.update(value=-1)

    def test_update_too_large_raises(self) -> None:
        """Update with value too large raises error."""
        point = CounterPoint(index=0)
        with pytest.raises(ValueError, match="out of range"):
            point.update(value=2**32)

    def test_update_max_value_valid(self) -> None:
        """Update with max value is valid."""
        point = CounterPoint(index=0)
        point.update(value=2**32 - 1)
        assert point.value == 2**32 - 1

    def test_increment_basic(self) -> None:
        """Increment increases counter value."""
        point = CounterPoint(index=0, value=100)
        point.increment()
        assert point.value == 101

    def test_increment_by_amount(self) -> None:
        """Increment by specific amount."""
        point = CounterPoint(index=0, value=100)
        point.increment(amount=10)
        assert point.value == 110

    def test_increment_wraps_at_max(self) -> None:
        """Increment wraps around at max value."""
        point = CounterPoint(index=0, value=2**32 - 1)
        point.increment(amount=2)
        assert point.value == 1

    def test_increment_generates_event(self) -> None:
        """Increment can generate event."""
        point = CounterPoint(index=0, value=0)
        result = point.increment(amount=100)
        assert result is True

    def test_no_event_when_class_none(self) -> None:
        """No event when event class is NONE."""
        config = CounterConfig(event_class=EventClass.NONE)
        point = CounterPoint(index=0, config=config)
        result = point.update(value=100)
        assert result is False

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        point = CounterPoint(index=0, quality=CounterQuality.ONLINE)
        assert point.is_online is True


class TestFrozenCounterPoint:
    """Tests for FrozenCounterPoint."""

    def test_create_with_defaults(self) -> None:
        """Create point with default values."""
        point = FrozenCounterPoint(index=0)
        assert point.index == 0
        assert point.value == 0
        assert point.quality == CounterQuality.RESTART

    def test_freeze_copies_counter_value(self) -> None:
        """Freeze copies counter's current value."""
        counter = CounterPoint(index=0, value=12345, quality=CounterQuality.ONLINE)
        frozen = FrozenCounterPoint(index=0)
        frozen.freeze(counter)
        assert frozen.value == 12345
        assert frozen.quality == CounterQuality.ONLINE

    def test_freeze_stores_timestamp(self) -> None:
        """Freeze stores timestamp."""
        counter = CounterPoint(index=0, value=100)
        frozen = FrozenCounterPoint(index=0)
        ts = DNP3Timestamp(milliseconds=5000)
        frozen.freeze(counter, timestamp=ts)
        assert frozen.timestamp == ts

    def test_freeze_generates_event_on_change(self) -> None:
        """Freeze generates event when value changes."""
        counter = CounterPoint(index=0, value=100)
        frozen = FrozenCounterPoint(index=0, value=50)
        result = frozen.freeze(counter)
        assert result is True

    def test_freeze_no_event_same_value(self) -> None:
        """Freeze does not generate event when value same."""
        counter = CounterPoint(index=0, value=100)
        frozen = FrozenCounterPoint(index=0, value=100)
        result = frozen.freeze(counter)
        assert result is False

    def test_freeze_no_event_when_class_none(self) -> None:
        """Freeze does not generate event when class is NONE."""
        config = CounterConfig(event_class=EventClass.NONE)
        counter = CounterPoint(index=0, value=100)
        frozen = FrozenCounterPoint(index=0, value=50, config=config)
        result = frozen.freeze(counter)
        assert result is False

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        point = FrozenCounterPoint(index=0, quality=CounterQuality.ONLINE)
        assert point.is_online is True
