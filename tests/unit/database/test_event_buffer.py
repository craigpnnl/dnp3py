"""Tests for event buffer."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.event_buffer import (
    AnalogEvent,
    BinaryEvent,
    ClassBuffer,
    CounterEvent,
    EventBuffer,
    EventBufferConfig,
    EventType,
)
from dnp3.database.point import EventClass


class TestEventType:
    """Tests for EventType enum."""

    def test_binary_input_value(self) -> None:
        """BINARY_INPUT is 1."""
        assert EventType.BINARY_INPUT == 1

    def test_binary_output_value(self) -> None:
        """BINARY_OUTPUT is 2."""
        assert EventType.BINARY_OUTPUT == 2

    def test_analog_input_value(self) -> None:
        """ANALOG_INPUT is 3."""
        assert EventType.ANALOG_INPUT == 3

    def test_counter_value(self) -> None:
        """COUNTER is 4."""
        assert EventType.COUNTER == 4

    def test_frozen_counter_value(self) -> None:
        """FROZEN_COUNTER is 5."""
        assert EventType.FROZEN_COUNTER == 5


class TestBinaryEvent:
    """Tests for BinaryEvent dataclass."""

    def test_create_with_defaults(self) -> None:
        """Create event with default values."""
        event = BinaryEvent(index=0, value=True, quality=BinaryQuality.ONLINE)
        assert event.index == 0
        assert event.value is True
        assert event.quality == BinaryQuality.ONLINE
        assert event.timestamp is None
        assert event.event_type == EventType.BINARY_INPUT

    def test_create_with_timestamp(self) -> None:
        """Create event with timestamp."""
        ts = DNP3Timestamp(milliseconds=5000)
        event = BinaryEvent(index=5, value=False, quality=BinaryQuality.COMM_LOST, timestamp=ts)
        assert event.timestamp == ts

    def test_create_binary_output_event(self) -> None:
        """Create binary output event."""
        event = BinaryEvent(
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
            event_type=EventType.BINARY_OUTPUT,
        )
        assert event.event_type == EventType.BINARY_OUTPUT

    def test_is_frozen(self) -> None:
        """BinaryEvent is immutable."""
        event = BinaryEvent(index=0, value=True, quality=BinaryQuality.ONLINE)
        with pytest.raises(AttributeError):
            event.value = False  # type: ignore[misc]


class TestAnalogEvent:
    """Tests for AnalogEvent dataclass."""

    def test_create_with_defaults(self) -> None:
        """Create event with default values."""
        event = AnalogEvent(index=0, value=123.456, quality=AnalogQuality.ONLINE)
        assert event.index == 0
        assert event.value == 123.456
        assert event.quality == AnalogQuality.ONLINE
        assert event.timestamp is None

    def test_create_with_timestamp(self) -> None:
        """Create event with timestamp."""
        ts = DNP3Timestamp(milliseconds=10000)
        event = AnalogEvent(index=3, value=-50.0, quality=AnalogQuality.OVER_RANGE, timestamp=ts)
        assert event.timestamp == ts

    def test_is_frozen(self) -> None:
        """AnalogEvent is immutable."""
        event = AnalogEvent(index=0, value=0.0, quality=AnalogQuality.ONLINE)
        with pytest.raises(AttributeError):
            event.value = 100.0  # type: ignore[misc]


class TestCounterEvent:
    """Tests for CounterEvent dataclass."""

    def test_create_with_defaults(self) -> None:
        """Create event with default values."""
        event = CounterEvent(index=0, value=12345, quality=CounterQuality.ONLINE)
        assert event.index == 0
        assert event.value == 12345
        assert event.quality == CounterQuality.ONLINE
        assert event.timestamp is None
        assert event.event_type == EventType.COUNTER

    def test_create_frozen_counter_event(self) -> None:
        """Create frozen counter event."""
        event = CounterEvent(
            index=0,
            value=100,
            quality=CounterQuality.ONLINE,
            event_type=EventType.FROZEN_COUNTER,
        )
        assert event.event_type == EventType.FROZEN_COUNTER

    def test_create_with_timestamp(self) -> None:
        """Create event with timestamp."""
        ts = DNP3Timestamp(milliseconds=15000)
        event = CounterEvent(index=2, value=99999, quality=CounterQuality.ROLLOVER, timestamp=ts)
        assert event.timestamp == ts

    def test_is_frozen(self) -> None:
        """CounterEvent is immutable."""
        event = CounterEvent(index=0, value=0, quality=CounterQuality.ONLINE)
        with pytest.raises(AttributeError):
            event.value = 100  # type: ignore[misc]


class TestEventBufferConfig:
    """Tests for EventBufferConfig."""

    def test_default_values(self) -> None:
        """Default config has 100 events per type."""
        config = EventBufferConfig()
        assert config.max_binary_events == 100
        assert config.max_analog_events == 100
        assert config.max_counter_events == 100

    def test_custom_values(self) -> None:
        """Can set custom limits."""
        config = EventBufferConfig(max_binary_events=50, max_analog_events=200, max_counter_events=25)
        assert config.max_binary_events == 50
        assert config.max_analog_events == 200
        assert config.max_counter_events == 25


class TestClassBuffer:
    """Tests for ClassBuffer."""

    def test_create_empty(self) -> None:
        """New buffer is empty."""
        buffer = ClassBuffer()
        assert buffer.count == 0
        assert buffer.is_empty is True
        assert buffer.overflow_count == 0

    def test_add_event(self) -> None:
        """Add event to buffer."""
        buffer = ClassBuffer()
        event = BinaryEvent(index=0, value=True, quality=BinaryQuality.ONLINE)
        result = buffer.add(event)
        assert result is True
        assert buffer.count == 1
        assert buffer.is_empty is False

    def test_add_multiple_events(self) -> None:
        """Add multiple events maintains order."""
        buffer = ClassBuffer()
        events = [BinaryEvent(index=i, value=True, quality=BinaryQuality.ONLINE) for i in range(5)]
        for event in events:
            buffer.add(event)
        assert buffer.count == 5

    def test_pop_returns_oldest(self) -> None:
        """Pop returns oldest event."""
        buffer = ClassBuffer()
        event1 = BinaryEvent(index=1, value=True, quality=BinaryQuality.ONLINE)
        event2 = BinaryEvent(index=2, value=False, quality=BinaryQuality.ONLINE)
        buffer.add(event1)
        buffer.add(event2)

        popped = buffer.pop()
        assert popped == event1
        assert buffer.count == 1

    def test_pop_empty_returns_none(self) -> None:
        """Pop from empty buffer returns None."""
        buffer = ClassBuffer()
        assert buffer.pop() is None

    def test_peek_returns_oldest_without_removing(self) -> None:
        """Peek returns oldest without removing."""
        buffer = ClassBuffer()
        event = BinaryEvent(index=0, value=True, quality=BinaryQuality.ONLINE)
        buffer.add(event)

        peeked = buffer.peek()
        assert peeked == event
        assert buffer.count == 1  # Still there

    def test_peek_empty_returns_none(self) -> None:
        """Peek from empty buffer returns None."""
        buffer = ClassBuffer()
        assert buffer.peek() is None

    def test_clear_removes_all(self) -> None:
        """Clear removes all events."""
        buffer = ClassBuffer()
        for i in range(10):
            buffer.add(BinaryEvent(index=i, value=True, quality=BinaryQuality.ONLINE))

        count = buffer.clear()
        assert count == 10
        assert buffer.is_empty is True

    def test_overflow_drops_oldest(self) -> None:
        """Overflow drops oldest event."""
        buffer = ClassBuffer(max_size=3)
        events = [BinaryEvent(index=i, value=True, quality=BinaryQuality.ONLINE) for i in range(5)]
        for event in events:
            buffer.add(event)

        assert buffer.count == 3
        assert buffer.overflow_count == 2
        assert buffer.has_overflow is True

        # Oldest remaining should be index=2
        oldest = buffer.peek()
        assert oldest is not None
        assert oldest.index == 2

    def test_reset_overflow(self) -> None:
        """Reset overflow counter."""
        buffer = ClassBuffer(max_size=2)
        for i in range(5):
            buffer.add(BinaryEvent(index=i, value=True, quality=BinaryQuality.ONLINE))

        old_count = buffer.reset_overflow()
        assert old_count == 3
        assert buffer.overflow_count == 0
        assert buffer.has_overflow is False


class TestEventBuffer:
    """Tests for EventBuffer."""

    def test_create_with_defaults(self) -> None:
        """Create buffer with default config."""
        buffer = EventBuffer()
        assert buffer.total_count == 0
        assert buffer.has_class1_events is False
        assert buffer.has_class2_events is False
        assert buffer.has_class3_events is False

    def test_add_binary_event_class1(self) -> None:
        """Add binary event to class 1."""
        buffer = EventBuffer()
        result = buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        assert result is True
        assert buffer.has_class1_events is True
        assert buffer.class1.count == 1

    def test_add_binary_event_class2(self) -> None:
        """Add binary event to class 2."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_2,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        assert buffer.has_class2_events is True
        assert buffer.class2.count == 1

    def test_add_binary_event_class3(self) -> None:
        """Add binary event to class 3."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_3,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        assert buffer.has_class3_events is True
        assert buffer.class3.count == 1

    def test_add_binary_event_class_none_ignored(self) -> None:
        """Add binary event with class NONE is ignored."""
        buffer = EventBuffer()
        result = buffer.add_binary_event(
            event_class=EventClass.NONE,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        assert result is False
        assert buffer.total_count == 0

    def test_add_binary_event_with_timestamp(self) -> None:
        """Add binary event with timestamp."""
        buffer = EventBuffer()
        ts = DNP3Timestamp(milliseconds=5000)
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
            timestamp=ts,
        )
        events = buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], BinaryEvent)
        assert events[0].timestamp == ts

    def test_add_binary_output_event(self) -> None:
        """Add binary output event."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
            event_type=EventType.BINARY_OUTPUT,
        )
        events = buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], BinaryEvent)
        assert events[0].event_type == EventType.BINARY_OUTPUT

    def test_add_analog_event(self) -> None:
        """Add analog event."""
        buffer = EventBuffer()
        result = buffer.add_analog_event(
            event_class=EventClass.CLASS_2,
            index=5,
            value=123.456,
            quality=AnalogQuality.ONLINE,
        )
        assert result is True
        assert buffer.class2.count == 1

        events = buffer.get_class_events(EventClass.CLASS_2)
        assert len(events) == 1
        assert isinstance(events[0], AnalogEvent)
        assert events[0].value == 123.456

    def test_add_analog_event_class_none_ignored(self) -> None:
        """Add analog event with class NONE is ignored."""
        buffer = EventBuffer()
        result = buffer.add_analog_event(
            event_class=EventClass.NONE,
            index=0,
            value=100.0,
            quality=AnalogQuality.ONLINE,
        )
        assert result is False
        assert buffer.total_count == 0

    def test_add_counter_event(self) -> None:
        """Add counter event."""
        buffer = EventBuffer()
        result = buffer.add_counter_event(
            event_class=EventClass.CLASS_3,
            index=2,
            value=99999,
            quality=CounterQuality.ONLINE,
        )
        assert result is True
        assert buffer.class3.count == 1

        events = buffer.get_class_events(EventClass.CLASS_3)
        assert len(events) == 1
        assert isinstance(events[0], CounterEvent)
        assert events[0].value == 99999

    def test_add_frozen_counter_event(self) -> None:
        """Add frozen counter event."""
        buffer = EventBuffer()
        buffer.add_counter_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=500,
            quality=CounterQuality.ONLINE,
            event_type=EventType.FROZEN_COUNTER,
        )
        events = buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], CounterEvent)
        assert events[0].event_type == EventType.FROZEN_COUNTER

    def test_add_counter_event_class_none_ignored(self) -> None:
        """Add counter event with class NONE is ignored."""
        buffer = EventBuffer()
        result = buffer.add_counter_event(
            event_class=EventClass.NONE,
            index=0,
            value=100,
            quality=CounterQuality.ONLINE,
        )
        assert result is False
        assert buffer.total_count == 0

    def test_get_class_events_returns_copy(self) -> None:
        """get_class_events returns list copy."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        events = buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        # Original still has events
        assert buffer.class1.count == 1

    def test_get_class_events_empty(self) -> None:
        """get_class_events returns empty list for empty class."""
        buffer = EventBuffer()
        events = buffer.get_class_events(EventClass.CLASS_1)
        assert events == []

    def test_get_class_events_none_returns_empty(self) -> None:
        """get_class_events with NONE returns empty list."""
        buffer = EventBuffer()
        events = buffer.get_class_events(EventClass.NONE)
        assert events == []

    def test_pop_class_events_removes(self) -> None:
        """pop_class_events removes events."""
        buffer = EventBuffer()
        for i in range(5):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        events = buffer.pop_class_events(EventClass.CLASS_1)
        assert len(events) == 5
        assert buffer.class1.count == 0

    def test_pop_class_events_with_limit(self) -> None:
        """pop_class_events respects max_count."""
        buffer = EventBuffer()
        for i in range(10):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        events = buffer.pop_class_events(EventClass.CLASS_1, max_count=3)
        assert len(events) == 3
        assert buffer.class1.count == 7

    def test_pop_class_events_maintains_order(self) -> None:
        """pop_class_events returns oldest first."""
        buffer = EventBuffer()
        for i in range(5):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        events = buffer.pop_class_events(EventClass.CLASS_1, max_count=3)
        assert [e.index for e in events] == [0, 1, 2]

    def test_pop_class_events_none_returns_empty(self) -> None:
        """pop_class_events with NONE returns empty list."""
        buffer = EventBuffer()
        events = buffer.pop_class_events(EventClass.NONE)
        assert events == []

    def test_clear_class(self) -> None:
        """clear_class removes all events from class."""
        buffer = EventBuffer()
        for i in range(5):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        count = buffer.clear_class(EventClass.CLASS_1)
        assert count == 5
        assert buffer.class1.count == 0

    def test_clear_class_none_returns_zero(self) -> None:
        """clear_class with NONE returns 0."""
        buffer = EventBuffer()
        count = buffer.clear_class(EventClass.NONE)
        assert count == 0

    def test_clear_all(self) -> None:
        """clear_all removes events from all classes."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        buffer.add_analog_event(
            event_class=EventClass.CLASS_2,
            index=0,
            value=100.0,
            quality=AnalogQuality.ONLINE,
        )
        buffer.add_counter_event(
            event_class=EventClass.CLASS_3,
            index=0,
            value=500,
            quality=CounterQuality.ONLINE,
        )

        count = buffer.clear_all()
        assert count == 3
        assert buffer.total_count == 0

    def test_get_class_count(self) -> None:
        """get_class_count returns count for class."""
        buffer = EventBuffer()
        for i in range(7):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_2,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        assert buffer.get_class_count(EventClass.CLASS_1) == 0
        assert buffer.get_class_count(EventClass.CLASS_2) == 7
        assert buffer.get_class_count(EventClass.CLASS_3) == 0

    def test_get_class_count_none_returns_zero(self) -> None:
        """get_class_count with NONE returns 0."""
        buffer = EventBuffer()
        assert buffer.get_class_count(EventClass.NONE) == 0

    def test_total_count(self) -> None:
        """total_count sums all classes."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=1,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        buffer.add_analog_event(
            event_class=EventClass.CLASS_2,
            index=0,
            value=100.0,
            quality=AnalogQuality.ONLINE,
        )

        assert buffer.total_count == 3

    def test_has_overflow(self) -> None:
        """has_overflow detects any class overflow."""
        config = EventBufferConfig(max_binary_events=1, max_analog_events=1, max_counter_events=1)
        buffer = EventBuffer(config=config)

        # Add enough events to cause overflow (max_size = 3 per class)
        for i in range(10):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        assert buffer.has_overflow is True

    def test_get_overflow_counts(self) -> None:
        """get_overflow_counts returns counts by class."""
        config = EventBufferConfig(max_binary_events=1, max_analog_events=1, max_counter_events=1)
        buffer = EventBuffer(config=config)

        # Cause overflow in class 1 only
        for i in range(10):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        counts = buffer.get_overflow_counts()
        assert counts[EventClass.CLASS_1] > 0
        assert counts[EventClass.CLASS_2] == 0
        assert counts[EventClass.CLASS_3] == 0

    def test_mixed_event_types_in_buffer(self) -> None:
        """Buffer can hold mixed event types."""
        buffer = EventBuffer()
        buffer.add_binary_event(
            event_class=EventClass.CLASS_1,
            index=0,
            value=True,
            quality=BinaryQuality.ONLINE,
        )
        buffer.add_analog_event(
            event_class=EventClass.CLASS_1,
            index=1,
            value=50.0,
            quality=AnalogQuality.ONLINE,
        )
        buffer.add_counter_event(
            event_class=EventClass.CLASS_1,
            index=2,
            value=100,
            quality=CounterQuality.ONLINE,
        )

        events = buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 3
        assert isinstance(events[0], BinaryEvent)
        assert isinstance(events[1], AnalogEvent)
        assert isinstance(events[2], CounterEvent)


class TestEventBufferPropertyBased:
    """Property-based tests for EventBuffer."""

    @given(
        st.lists(
            st.tuples(
                st.sampled_from([EventClass.CLASS_1, EventClass.CLASS_2, EventClass.CLASS_3]),
                st.integers(min_value=0, max_value=65535),
                st.booleans(),
            ),
            min_size=0,
            max_size=50,
        )
    )
    def test_event_count_matches_added(self, events: list[tuple[EventClass, int, bool]]) -> None:
        """Total count matches number of events added."""
        buffer = EventBuffer()
        for event_class, index, value in events:
            buffer.add_binary_event(
                event_class=event_class,
                index=index,
                value=value,
                quality=BinaryQuality.ONLINE,
            )

        assert buffer.total_count == len(events)

    @given(
        st.lists(
            st.integers(min_value=0, max_value=65535),
            min_size=1,
            max_size=20,
        )
    )
    def test_pop_returns_fifo_order(self, indices: list[int]) -> None:
        """Events are returned in FIFO order."""
        buffer = EventBuffer()
        for index in indices:
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=index,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        popped = buffer.pop_class_events(EventClass.CLASS_1)
        popped_indices = [e.index for e in popped]
        assert popped_indices == indices

    @given(st.integers(min_value=1, max_value=10))
    def test_overflow_maintains_max_size(self, max_events: int) -> None:
        """Buffer never exceeds max size even with overflow."""
        config = EventBufferConfig(max_binary_events=max_events, max_analog_events=0, max_counter_events=0)
        buffer = EventBuffer(config=config)

        # Add many more events than max
        for i in range(max_events * 5):
            buffer.add_binary_event(
                event_class=EventClass.CLASS_1,
                index=i,
                value=True,
                quality=BinaryQuality.ONLINE,
            )

        assert buffer.class1.count == max_events
