"""Tests for the main database module."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.flags import BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.database import Database, DatabaseConfig
from dnp3.database.event_buffer import (
    AnalogEvent,
    BinaryEvent,
    CounterEvent,
    EventBufferConfig,
    EventType,
)
from dnp3.database.point import (
    AnalogInputConfig,
    BinaryInputConfig,
    CounterConfig,
    EventClass,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_default_values(self) -> None:
        """Default config has sensible limits."""
        config = DatabaseConfig()
        assert config.max_binary_inputs == 100
        assert config.max_binary_outputs == 100
        assert config.max_analog_inputs == 100
        assert config.max_counters == 100
        assert config.max_frozen_counters == 100

    def test_custom_values(self) -> None:
        """Can set custom limits."""
        config = DatabaseConfig(
            max_binary_inputs=50,
            max_analog_inputs=200,
        )
        assert config.max_binary_inputs == 50
        assert config.max_analog_inputs == 200

    def test_includes_event_buffer_config(self) -> None:
        """DatabaseConfig includes event buffer config."""
        event_config = EventBufferConfig(max_binary_events=500)
        config = DatabaseConfig(event_buffer_config=event_config)
        assert config.event_buffer_config.max_binary_events == 500


class TestDatabaseCreation:
    """Tests for database creation."""

    def test_create_empty_database(self) -> None:
        """Create empty database with default config."""
        db = Database()
        assert db.binary_input_count == 0
        assert db.binary_output_count == 0
        assert db.analog_input_count == 0
        assert db.counter_count == 0
        assert db.frozen_counter_count == 0
        assert db.total_point_count == 0

    def test_create_with_config(self) -> None:
        """Create database with custom config."""
        config = DatabaseConfig(max_binary_inputs=10)
        db = Database(config=config)
        assert db.config.max_binary_inputs == 10


class TestBinaryInputOperations:
    """Tests for binary input operations."""

    def test_add_binary_input(self) -> None:
        """Add a binary input point."""
        db = Database()
        point = db.add_binary_input(index=0)
        assert point.index == 0
        assert point.value is False
        assert point.quality == BinaryQuality.RESTART
        assert db.binary_input_count == 1

    def test_add_binary_input_with_config(self) -> None:
        """Add binary input with custom config."""
        db = Database()
        config = BinaryInputConfig(event_class=EventClass.CLASS_2)
        point = db.add_binary_input(index=5, config=config)
        assert point.config.event_class == EventClass.CLASS_2

    def test_add_binary_input_with_initial_value(self) -> None:
        """Add binary input with initial value."""
        db = Database()
        point = db.add_binary_input(index=0, value=True, quality=BinaryQuality.ONLINE)
        assert point.value is True
        assert point.quality == BinaryQuality.ONLINE

    def test_add_duplicate_index_raises(self) -> None:
        """Adding duplicate index raises error."""
        db = Database()
        db.add_binary_input(index=0)
        with pytest.raises(ValueError, match="already exists"):
            db.add_binary_input(index=0)

    def test_add_exceeds_max_raises(self) -> None:
        """Adding more than max raises error."""
        config = DatabaseConfig(max_binary_inputs=2)
        db = Database(config=config)
        db.add_binary_input(index=0)
        db.add_binary_input(index=1)
        with pytest.raises(ValueError, match="Maximum binary inputs"):
            db.add_binary_input(index=2)

    def test_update_binary_input_generates_event(self) -> None:
        """Updating binary input generates event."""
        db = Database()
        db.add_binary_input(index=0)
        result = db.update_binary_input(index=0, value=True)
        assert result is True
        assert db.event_buffer.class1.count == 1

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], BinaryEvent)
        assert events[0].index == 0
        assert events[0].value is True

    def test_update_binary_input_same_value_no_event(self) -> None:
        """Updating with same value generates no event."""
        db = Database()
        db.add_binary_input(index=0, value=True, quality=BinaryQuality.ONLINE)
        result = db.update_binary_input(index=0, value=True, quality=BinaryQuality.ONLINE)
        assert result is False
        assert db.event_buffer.total_count == 0

    def test_update_binary_input_with_timestamp(self) -> None:
        """Update includes timestamp in event."""
        db = Database()
        db.add_binary_input(index=0)
        ts = DNP3Timestamp(milliseconds=5000)
        db.update_binary_input(index=0, value=True, timestamp=ts)

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert events[0].timestamp == ts

    def test_update_nonexistent_raises(self) -> None:
        """Updating nonexistent point raises error."""
        db = Database()
        with pytest.raises(KeyError):
            db.update_binary_input(index=0, value=True)

    def test_get_binary_input(self) -> None:
        """Get binary input by index."""
        db = Database()
        db.add_binary_input(index=5)
        point = db.get_binary_input(5)
        assert point is not None
        assert point.index == 5

    def test_get_binary_input_nonexistent(self) -> None:
        """Get nonexistent binary input returns None."""
        db = Database()
        assert db.get_binary_input(0) is None

    def test_get_binary_inputs_range(self) -> None:
        """Get binary inputs in range."""
        db = Database()
        for i in range(10):
            db.add_binary_input(index=i)

        points = db.get_binary_inputs_range(3, 7)
        assert len(points) == 5
        assert [p.index for p in points] == [3, 4, 5, 6, 7]

    def test_get_all_binary_inputs(self) -> None:
        """Get all binary inputs sorted."""
        db = Database()
        db.add_binary_input(index=5)
        db.add_binary_input(index=2)
        db.add_binary_input(index=8)

        points = db.get_all_binary_inputs()
        assert [p.index for p in points] == [2, 5, 8]


class TestBinaryOutputOperations:
    """Tests for binary output operations."""

    def test_add_binary_output(self) -> None:
        """Add a binary output point."""
        db = Database()
        point = db.add_binary_output(index=0)
        assert point.index == 0
        assert db.binary_output_count == 1

    def test_update_binary_output_generates_event(self) -> None:
        """Updating binary output generates event."""
        db = Database()
        db.add_binary_output(index=0)
        result = db.update_binary_output(index=0, value=True)
        assert result is True

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], BinaryEvent)
        assert events[0].event_type == EventType.BINARY_OUTPUT

    def test_add_duplicate_index_raises(self) -> None:
        """Adding duplicate index raises error."""
        db = Database()
        db.add_binary_output(index=0)
        with pytest.raises(ValueError, match="already exists"):
            db.add_binary_output(index=0)

    def test_add_exceeds_max_raises(self) -> None:
        """Adding more than max raises error."""
        config = DatabaseConfig(max_binary_outputs=1)
        db = Database(config=config)
        db.add_binary_output(index=0)
        with pytest.raises(ValueError, match="Maximum binary outputs"):
            db.add_binary_output(index=1)


class TestAnalogInputOperations:
    """Tests for analog input operations."""

    def test_add_analog_input(self) -> None:
        """Add an analog input point."""
        db = Database()
        point = db.add_analog_input(index=0)
        assert point.index == 0
        assert point.value == 0.0
        assert db.analog_input_count == 1

    def test_add_analog_input_with_deadband(self) -> None:
        """Add analog input with deadband config."""
        db = Database()
        config = AnalogInputConfig(deadband=5.0)
        point = db.add_analog_input(index=0, config=config)
        assert point.config.deadband == 5.0

    def test_update_analog_input_generates_event(self) -> None:
        """Updating analog input generates event."""
        db = Database()
        db.add_analog_input(index=0)
        result = db.update_analog_input(index=0, value=100.0)
        assert result is True

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], AnalogEvent)
        assert events[0].value == 100.0

    def test_update_within_deadband_no_event(self) -> None:
        """Update within deadband generates no event."""
        db = Database()
        config = AnalogInputConfig(deadband=10.0)
        db.add_analog_input(index=0, config=config, value=100.0)
        # Set last_event_value
        point = db.get_analog_input(0)
        assert point is not None
        point.last_event_value = 100.0

        result = db.update_analog_input(index=0, value=105.0)  # Within deadband
        assert result is False
        assert db.event_buffer.total_count == 0

    def test_update_exceeds_deadband_generates_event(self) -> None:
        """Update exceeding deadband generates event."""
        db = Database()
        config = AnalogInputConfig(deadband=10.0)
        db.add_analog_input(index=0, config=config, value=100.0)
        point = db.get_analog_input(0)
        assert point is not None
        point.last_event_value = 100.0

        result = db.update_analog_input(index=0, value=115.0)  # Exceeds deadband
        assert result is True
        assert db.event_buffer.total_count == 1

    def test_add_duplicate_index_raises(self) -> None:
        """Adding duplicate index raises error."""
        db = Database()
        db.add_analog_input(index=0)
        with pytest.raises(ValueError, match="already exists"):
            db.add_analog_input(index=0)

    def test_add_exceeds_max_raises(self) -> None:
        """Adding more than max raises error."""
        config = DatabaseConfig(max_analog_inputs=1)
        db = Database(config=config)
        db.add_analog_input(index=0)
        with pytest.raises(ValueError, match="Maximum analog inputs"):
            db.add_analog_input(index=1)


class TestCounterOperations:
    """Tests for counter operations."""

    def test_add_counter(self) -> None:
        """Add a counter point."""
        db = Database()
        point = db.add_counter(index=0)
        assert point.index == 0
        assert point.value == 0
        assert db.counter_count == 1

    def test_update_counter_generates_event(self) -> None:
        """Updating counter generates event."""
        db = Database()
        db.add_counter(index=0)
        result = db.update_counter(index=0, value=100)
        assert result is True

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], CounterEvent)
        assert events[0].value == 100
        assert events[0].event_type == EventType.COUNTER

    def test_increment_counter(self) -> None:
        """Increment counter value."""
        db = Database()
        db.add_counter(index=0, value=100)
        db.increment_counter(index=0, amount=50)

        point = db.get_counter(0)
        assert point is not None
        assert point.value == 150

    def test_increment_generates_event(self) -> None:
        """Increment generates event."""
        db = Database()
        db.add_counter(index=0)
        result = db.increment_counter(index=0, amount=100)
        assert result is True
        assert db.event_buffer.total_count == 1

    def test_add_duplicate_index_raises(self) -> None:
        """Adding duplicate index raises error."""
        db = Database()
        db.add_counter(index=0)
        with pytest.raises(ValueError, match="already exists"):
            db.add_counter(index=0)

    def test_add_exceeds_max_raises(self) -> None:
        """Adding more than max raises error."""
        config = DatabaseConfig(max_counters=1)
        db = Database(config=config)
        db.add_counter(index=0)
        with pytest.raises(ValueError, match="Maximum counters"):
            db.add_counter(index=1)


class TestFrozenCounterOperations:
    """Tests for frozen counter operations."""

    def test_add_frozen_counter(self) -> None:
        """Add a frozen counter point."""
        db = Database()
        point = db.add_frozen_counter(index=0)
        assert point.index == 0
        assert point.value == 0
        assert db.frozen_counter_count == 1

    def test_freeze_counter(self) -> None:
        """Freeze a counter to its frozen counterpart."""
        db = Database()
        db.add_counter(index=0, value=12345, quality=CounterQuality.ONLINE)
        db.add_frozen_counter(index=0)

        result = db.freeze_counter(counter_index=0)
        assert result is True

        frozen = db.get_frozen_counter(0)
        assert frozen is not None
        assert frozen.value == 12345
        assert frozen.quality == CounterQuality.ONLINE

    def test_freeze_generates_event(self) -> None:
        """Freeze generates event."""
        db = Database()
        db.add_counter(index=0, value=100)
        db.add_frozen_counter(index=0)

        db.freeze_counter(counter_index=0)

        events = db.event_buffer.get_class_events(EventClass.CLASS_1)
        assert len(events) == 1
        assert isinstance(events[0], CounterEvent)
        assert events[0].event_type == EventType.FROZEN_COUNTER

    def test_freeze_with_timestamp(self) -> None:
        """Freeze includes timestamp."""
        db = Database()
        db.add_counter(index=0, value=100)
        db.add_frozen_counter(index=0)

        ts = DNP3Timestamp(milliseconds=5000)
        db.freeze_counter(counter_index=0, timestamp=ts)

        frozen = db.get_frozen_counter(0)
        assert frozen is not None
        assert frozen.timestamp == ts

    def test_freeze_different_indices(self) -> None:
        """Freeze counter to different frozen counter index."""
        db = Database()
        db.add_counter(index=5, value=500)
        db.add_frozen_counter(index=10)

        db.freeze_counter(counter_index=5, frozen_index=10)

        frozen = db.get_frozen_counter(10)
        assert frozen is not None
        assert frozen.value == 500

    def test_add_duplicate_index_raises(self) -> None:
        """Adding duplicate index raises error."""
        db = Database()
        db.add_frozen_counter(index=0)
        with pytest.raises(ValueError, match="already exists"):
            db.add_frozen_counter(index=0)

    def test_add_exceeds_max_raises(self) -> None:
        """Adding more than max raises error."""
        config = DatabaseConfig(max_frozen_counters=1)
        db = Database(config=config)
        db.add_frozen_counter(index=0)
        with pytest.raises(ValueError, match="Maximum frozen counters"):
            db.add_frozen_counter(index=1)


class TestEventClassAccess:
    """Tests for event class data access."""

    def test_get_class_binary_inputs(self) -> None:
        """Get binary inputs by event class."""
        db = Database()
        db.add_binary_input(index=0, config=BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.add_binary_input(index=1, config=BinaryInputConfig(event_class=EventClass.CLASS_2))
        db.add_binary_input(index=2, config=BinaryInputConfig(event_class=EventClass.CLASS_1))

        class1_points = db.get_class_binary_inputs(EventClass.CLASS_1)
        assert len(class1_points) == 2
        assert [p.index for p in class1_points] == [0, 2]

    def test_get_class_analog_inputs(self) -> None:
        """Get analog inputs by event class."""
        db = Database()
        db.add_analog_input(index=0, config=AnalogInputConfig(event_class=EventClass.CLASS_3))
        db.add_analog_input(index=1, config=AnalogInputConfig(event_class=EventClass.CLASS_3))

        class3_points = db.get_class_analog_inputs(EventClass.CLASS_3)
        assert len(class3_points) == 2

    def test_get_class_counters(self) -> None:
        """Get counters by event class."""
        db = Database()
        db.add_counter(index=0, config=CounterConfig(event_class=EventClass.CLASS_2))

        class2_points = db.get_class_counters(EventClass.CLASS_2)
        assert len(class2_points) == 1


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_total_point_count(self) -> None:
        """total_point_count sums all types."""
        db = Database()
        db.add_binary_input(index=0)
        db.add_binary_output(index=0)
        db.add_analog_input(index=0)
        db.add_counter(index=0)
        db.add_frozen_counter(index=0)

        assert db.total_point_count == 5

    def test_clear_all_points(self) -> None:
        """clear_all_points removes all points."""
        db = Database()
        db.add_binary_input(index=0)
        db.add_analog_input(index=0)

        db.clear_all_points()
        assert db.total_point_count == 0

    def test_clear_events(self) -> None:
        """clear_events clears event buffer."""
        db = Database()
        db.add_binary_input(index=0)
        db.update_binary_input(index=0, value=True)

        count = db.clear_events()
        assert count == 1
        assert db.event_buffer.total_count == 0

    def test_transaction(self) -> None:
        """Transaction groups updates."""
        db = Database()
        db.add_binary_input(index=0)
        db.add_binary_input(index=1)

        def do_updates(database: Database) -> None:
            database.update_binary_input(index=0, value=True)
            database.update_binary_input(index=1, value=True)

        db.transaction(do_updates)

        assert db.get_binary_input(0) is not None
        assert db.get_binary_input(0).value is True
        assert db.get_binary_input(1) is not None
        assert db.get_binary_input(1).value is True
        assert db.event_buffer.total_count == 2


class TestPropertyBased:
    """Property-based tests for database."""

    @given(st.lists(st.integers(min_value=0, max_value=999), min_size=0, max_size=50, unique=True))
    def test_add_many_binary_inputs(self, indices: list[int]) -> None:
        """Can add many binary inputs with unique indices."""
        db = Database()
        for index in indices:
            db.add_binary_input(index=index)
        assert db.binary_input_count == len(indices)

    @given(
        st.lists(
            st.tuples(st.integers(min_value=0, max_value=99), st.booleans()),
            min_size=1,
            max_size=20,
        )
    )
    def test_updates_generate_correct_event_count(self, updates: list[tuple[int, bool]]) -> None:
        """Updates generate correct number of events."""
        db = Database()
        # Add all unique indices first
        unique_indices = {index for index, _ in updates}
        for index in unique_indices:
            db.add_binary_input(index=index)

        # Track expected events
        expected_events = 0
        point_states: dict[int, tuple[bool, BinaryQuality]] = {}
        for index in unique_indices:
            point_states[index] = (False, BinaryQuality.RESTART)

        for index, value in updates:
            old_value, old_quality = point_states[index]
            new_quality = BinaryQuality.ONLINE
            if old_value != value or old_quality != new_quality:
                expected_events += 1
            point_states[index] = (value, new_quality)
            db.update_binary_input(index=index, value=value)

        assert db.event_buffer.total_count == expected_events

    @given(st.integers(min_value=0, max_value=100))
    def test_range_queries_return_correct_count(self, count: int) -> None:
        """Range queries return correct results."""
        db = Database()
        for i in range(count):
            db.add_binary_input(index=i)

        if count > 0:
            mid = count // 2
            points = db.get_binary_inputs_range(0, mid)
            assert len(points) == mid + 1
