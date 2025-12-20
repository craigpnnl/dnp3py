"""Event buffer for DNP3 outstation.

The event buffer stores events until they are read and confirmed by the master.
Events are organized by class (1, 2, 3) for priority-based retrieval.
"""

from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TypeVar

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.point import EventClass

# Type variable for event data
T = TypeVar("T")


class EventType(IntEnum):
    """Event types for the buffer."""

    BINARY_INPUT = 1
    BINARY_OUTPUT = 2
    ANALOG_INPUT = 3
    COUNTER = 4
    FROZEN_COUNTER = 5


@dataclass(frozen=True)
class BinaryEvent:
    """Binary input/output event.

    Attributes:
        index: Point index.
        value: Binary state at time of event.
        quality: Quality flags at time of event.
        timestamp: Time of event (optional).
        event_type: Type of binary event.
    """

    index: int
    value: bool
    quality: BinaryQuality
    timestamp: DNP3Timestamp | None = None
    event_type: EventType = EventType.BINARY_INPUT


@dataclass(frozen=True)
class AnalogEvent:
    """Analog input event.

    Attributes:
        index: Point index.
        value: Analog value at time of event.
        quality: Quality flags at time of event.
        timestamp: Time of event (optional).
    """

    index: int
    value: float
    quality: AnalogQuality
    timestamp: DNP3Timestamp | None = None


@dataclass(frozen=True)
class CounterEvent:
    """Counter event.

    Attributes:
        index: Point index.
        value: Counter value at time of event.
        quality: Quality flags at time of event.
        timestamp: Time of event (optional).
        event_type: Type of counter event (counter or frozen).
    """

    index: int
    value: int
    quality: CounterQuality
    timestamp: DNP3Timestamp | None = None
    event_type: EventType = EventType.COUNTER


# Union of all event types
Event = BinaryEvent | AnalogEvent | CounterEvent


@dataclass
class EventBufferConfig:
    """Configuration for event buffer.

    Attributes:
        max_binary_events: Maximum binary events per class.
        max_analog_events: Maximum analog events per class.
        max_counter_events: Maximum counter events per class.
    """

    max_binary_events: int = 100
    max_analog_events: int = 100
    max_counter_events: int = 100


@dataclass
class ClassBuffer:
    """Buffer for a single event class.

    Attributes:
        events: Queue of events.
        max_size: Maximum number of events.
        overflow_count: Number of events dropped due to overflow.
    """

    events: deque[Event] = field(default_factory=deque)
    max_size: int = 100
    overflow_count: int = 0

    def add(self, event: Event) -> bool:
        """Add event to buffer.

        Args:
            event: Event to add.

        Returns:
            True if event was added, False if dropped due to overflow.
        """
        if len(self.events) >= self.max_size:
            # Buffer full - drop oldest event
            self.events.popleft()
            self.overflow_count += 1

        self.events.append(event)
        return True

    def pop(self) -> Event | None:
        """Remove and return oldest event.

        Returns:
            Oldest event, or None if buffer empty.
        """
        if self.events:
            return self.events.popleft()
        return None

    def peek(self) -> Event | None:
        """Return oldest event without removing.

        Returns:
            Oldest event, or None if buffer empty.
        """
        if self.events:
            return self.events[0]
        return None

    def clear(self) -> int:
        """Clear all events.

        Returns:
            Number of events cleared.
        """
        count = len(self.events)
        self.events.clear()
        return count

    @property
    def count(self) -> int:
        """Number of events in buffer."""
        return len(self.events)

    @property
    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return len(self.events) == 0

    @property
    def has_overflow(self) -> bool:
        """Check if overflow has occurred."""
        return self.overflow_count > 0

    def reset_overflow(self) -> int:
        """Reset overflow counter.

        Returns:
            Previous overflow count.
        """
        count = self.overflow_count
        self.overflow_count = 0
        return count


@dataclass
class EventBuffer:
    """Event buffer with class-based storage.

    Events are stored in separate buffers by class (1, 2, 3).
    Class 1 events are highest priority, Class 3 lowest.

    Attributes:
        config: Buffer configuration.
        class1: Class 1 event buffer.
        class2: Class 2 event buffer.
        class3: Class 3 event buffer.
    """

    config: EventBufferConfig = field(default_factory=EventBufferConfig)
    class1: ClassBuffer = field(default_factory=ClassBuffer)
    class2: ClassBuffer = field(default_factory=ClassBuffer)
    class3: ClassBuffer = field(default_factory=ClassBuffer)

    def __post_init__(self) -> None:
        """Initialize class buffers with config."""
        # Set max sizes based on config (sum of all event types)
        total_max = self.config.max_binary_events + self.config.max_analog_events + self.config.max_counter_events
        self.class1.max_size = total_max
        self.class2.max_size = total_max
        self.class3.max_size = total_max

    def add_binary_event(
        self,
        event_class: EventClass,
        index: int,
        value: bool,
        quality: BinaryQuality,
        timestamp: DNP3Timestamp | None = None,
        event_type: EventType = EventType.BINARY_INPUT,
    ) -> bool:
        """Add a binary event.

        Args:
            event_class: Event class (1, 2, or 3).
            index: Point index.
            value: Binary state.
            quality: Quality flags.
            timestamp: Event timestamp.
            event_type: Type of binary event.

        Returns:
            True if event was added, False if class is NONE.
        """
        if event_class == EventClass.NONE:
            return False

        event = BinaryEvent(
            index=index,
            value=value,
            quality=quality,
            timestamp=timestamp,
            event_type=event_type,
        )
        return self._add_to_class(event_class, event)

    def add_analog_event(
        self,
        event_class: EventClass,
        index: int,
        value: float,
        quality: AnalogQuality,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Add an analog event.

        Args:
            event_class: Event class (1, 2, or 3).
            index: Point index.
            value: Analog value.
            quality: Quality flags.
            timestamp: Event timestamp.

        Returns:
            True if event was added, False if class is NONE.
        """
        if event_class == EventClass.NONE:
            return False

        event = AnalogEvent(
            index=index,
            value=value,
            quality=quality,
            timestamp=timestamp,
        )
        return self._add_to_class(event_class, event)

    def add_counter_event(
        self,
        event_class: EventClass,
        index: int,
        value: int,
        quality: CounterQuality,
        timestamp: DNP3Timestamp | None = None,
        event_type: EventType = EventType.COUNTER,
    ) -> bool:
        """Add a counter event.

        Args:
            event_class: Event class (1, 2, or 3).
            index: Point index.
            value: Counter value.
            quality: Quality flags.
            timestamp: Event timestamp.
            event_type: Type of counter event.

        Returns:
            True if event was added, False if class is NONE.
        """
        if event_class == EventClass.NONE:
            return False

        event = CounterEvent(
            index=index,
            value=value,
            quality=quality,
            timestamp=timestamp,
            event_type=event_type,
        )
        return self._add_to_class(event_class, event)

    def _add_to_class(self, event_class: EventClass, event: Event) -> bool:
        """Add event to appropriate class buffer.

        Args:
            event_class: Target event class.
            event: Event to add.

        Returns:
            True if event was added.
        """
        buffer = self._get_buffer(event_class)
        if buffer is not None:
            return buffer.add(event)
        return False

    def _get_buffer(self, event_class: EventClass) -> ClassBuffer | None:
        """Get buffer for event class.

        Args:
            event_class: Event class.

        Returns:
            Buffer for the class, or None if NONE.
        """
        if event_class == EventClass.CLASS_1:
            return self.class1
        if event_class == EventClass.CLASS_2:
            return self.class2
        if event_class == EventClass.CLASS_3:
            return self.class3
        return None

    def get_class_events(self, event_class: EventClass) -> list[Event]:
        """Get all events for a class without removing them.

        Args:
            event_class: Event class.

        Returns:
            List of events in the class.
        """
        buffer = self._get_buffer(event_class)
        if buffer is not None:
            return list(buffer.events)
        return []

    def pop_class_events(self, event_class: EventClass, max_count: int = 0) -> list[Event]:
        """Remove and return events for a class.

        Args:
            event_class: Event class.
            max_count: Maximum events to return (0 = all).

        Returns:
            List of events removed from the class.
        """
        buffer = self._get_buffer(event_class)
        if buffer is None:
            return []

        events: list[Event] = []
        count = 0
        while not buffer.is_empty:
            if max_count > 0 and count >= max_count:
                break
            event = buffer.pop()
            if event is not None:
                events.append(event)
                count += 1
        return events

    def clear_class(self, event_class: EventClass) -> int:
        """Clear all events for a class.

        Args:
            event_class: Event class to clear.

        Returns:
            Number of events cleared.
        """
        buffer = self._get_buffer(event_class)
        if buffer is not None:
            return buffer.clear()
        return 0

    def clear_all(self) -> int:
        """Clear all events from all classes.

        Returns:
            Total number of events cleared.
        """
        return self.class1.clear() + self.class2.clear() + self.class3.clear()

    def get_class_count(self, event_class: EventClass) -> int:
        """Get event count for a class.

        Args:
            event_class: Event class.

        Returns:
            Number of events in the class.
        """
        buffer = self._get_buffer(event_class)
        if buffer is not None:
            return buffer.count
        return 0

    @property
    def total_count(self) -> int:
        """Total events across all classes."""
        return self.class1.count + self.class2.count + self.class3.count

    @property
    def has_class1_events(self) -> bool:
        """Check if Class 1 events available."""
        return not self.class1.is_empty

    @property
    def has_class2_events(self) -> bool:
        """Check if Class 2 events available."""
        return not self.class2.is_empty

    @property
    def has_class3_events(self) -> bool:
        """Check if Class 3 events available."""
        return not self.class3.is_empty

    @property
    def has_overflow(self) -> bool:
        """Check if any class has overflow."""
        return self.class1.has_overflow or self.class2.has_overflow or self.class3.has_overflow

    def get_overflow_counts(self) -> dict[EventClass, int]:
        """Get overflow counts by class.

        Returns:
            Dictionary mapping class to overflow count.
        """
        return {
            EventClass.CLASS_1: self.class1.overflow_count,
            EventClass.CLASS_2: self.class2.overflow_count,
            EventClass.CLASS_3: self.class3.overflow_count,
        }
