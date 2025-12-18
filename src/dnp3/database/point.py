"""Point definitions for DNP3 database.

Points represent individual data points in the outstation database.
Each point has:
- An index (unique within its type)
- Current value and quality flags
- Event class assignment
- Type-specific configuration (deadbands, etc.)
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TypeVar

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp


class EventClass(IntEnum):
    """Event class assignment for points.

    Class 0: Static data only (no events)
    Class 1: High priority events
    Class 2: Medium priority events
    Class 3: Low priority events
    """

    NONE = 0  # No events generated (Class 0 only)
    CLASS_1 = 1
    CLASS_2 = 2
    CLASS_3 = 3


# Type variable for quality flags
Q = TypeVar("Q", BinaryQuality, AnalogQuality, CounterQuality)


@dataclass
class PointConfig:
    """Base configuration for all point types.

    Attributes:
        event_class: Event class for this point.
    """

    event_class: EventClass = EventClass.CLASS_1


@dataclass
class BinaryInputConfig(PointConfig):
    """Configuration for binary input points.

    Binary inputs generate events on any state change.
    """

    pass


@dataclass
class BinaryOutputConfig(PointConfig):
    """Configuration for binary output points."""

    pass


@dataclass
class AnalogInputConfig(PointConfig):
    """Configuration for analog input points.

    Attributes:
        deadband: Minimum change to generate event (absolute value).
    """

    deadband: float = 0.0


@dataclass
class CounterConfig(PointConfig):
    """Configuration for counter points.

    Attributes:
        deadband: Minimum change to generate event.
    """

    deadband: int = 0


@dataclass
class BinaryInputPoint:
    """Binary input point state.

    Attributes:
        index: Point index.
        value: Current binary state.
        quality: Quality flags.
        timestamp: Time of last update.
        config: Point configuration.
    """

    index: int
    value: bool = False
    quality: BinaryQuality = field(default_factory=lambda: BinaryQuality.RESTART)
    timestamp: DNP3Timestamp | None = None
    config: BinaryInputConfig = field(default_factory=BinaryInputConfig)

    def update(
        self,
        value: bool,
        quality: BinaryQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update point value.

        Args:
            value: New binary state.
            quality: New quality flags (defaults to ONLINE).
            timestamp: Time of update (optional).

        Returns:
            True if value changed and event should be generated.
        """
        if quality is None:
            quality = BinaryQuality.ONLINE

        changed = self.value != value or self.quality != quality
        self.value = value
        self.quality = quality
        self.timestamp = timestamp

        # Binary inputs generate events on any change
        return changed and self.config.event_class != EventClass.NONE

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & BinaryQuality.ONLINE)


@dataclass
class BinaryOutputPoint:
    """Binary output point state.

    Attributes:
        index: Point index.
        value: Current binary state.
        quality: Quality flags.
        timestamp: Time of last update.
        config: Point configuration.
    """

    index: int
    value: bool = False
    quality: BinaryQuality = field(default_factory=lambda: BinaryQuality.RESTART)
    timestamp: DNP3Timestamp | None = None
    config: BinaryOutputConfig = field(default_factory=BinaryOutputConfig)

    def update(
        self,
        value: bool,
        quality: BinaryQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update point value.

        Args:
            value: New binary state.
            quality: New quality flags (defaults to ONLINE).
            timestamp: Time of update (optional).

        Returns:
            True if value changed and event should be generated.
        """
        if quality is None:
            quality = BinaryQuality.ONLINE

        changed = self.value != value or self.quality != quality
        self.value = value
        self.quality = quality
        self.timestamp = timestamp

        return changed and self.config.event_class != EventClass.NONE

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & BinaryQuality.ONLINE)


@dataclass
class AnalogInputPoint:
    """Analog input point state.

    Attributes:
        index: Point index.
        value: Current analog value.
        quality: Quality flags.
        timestamp: Time of last update.
        config: Point configuration.
        last_event_value: Value at last event generation (for deadband).
    """

    index: int
    value: float = 0.0
    quality: AnalogQuality = field(default_factory=lambda: AnalogQuality.RESTART)
    timestamp: DNP3Timestamp | None = None
    config: AnalogInputConfig = field(default_factory=AnalogInputConfig)
    last_event_value: float = 0.0

    def update(
        self,
        value: float,
        quality: AnalogQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update point value.

        Args:
            value: New analog value.
            quality: New quality flags (defaults to ONLINE).
            timestamp: Time of update (optional).

        Returns:
            True if change exceeds deadband and event should be generated.
        """
        if quality is None:
            quality = AnalogQuality.ONLINE

        self.value = value
        self.quality = quality
        self.timestamp = timestamp

        if self.config.event_class == EventClass.NONE:
            return False

        # Check deadband
        change = abs(value - self.last_event_value)
        if change >= self.config.deadband:
            self.last_event_value = value
            return True

        return False

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & AnalogQuality.ONLINE)


@dataclass
class CounterPoint:
    """Counter point state.

    Attributes:
        index: Point index.
        value: Current counter value.
        quality: Quality flags.
        timestamp: Time of last update.
        config: Point configuration.
        last_event_value: Value at last event generation (for deadband).
    """

    index: int
    value: int = 0
    quality: CounterQuality = field(default_factory=lambda: CounterQuality.RESTART)
    timestamp: DNP3Timestamp | None = None
    config: CounterConfig = field(default_factory=CounterConfig)
    last_event_value: int = 0

    MAX_VALUE: int = 2**32 - 1

    def update(
        self,
        value: int,
        quality: CounterQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update point value.

        Args:
            value: New counter value.
            quality: New quality flags (defaults to ONLINE).
            timestamp: Time of update (optional).

        Returns:
            True if change exceeds deadband and event should be generated.

        Raises:
            ValueError: If value is out of range.
        """
        if not 0 <= value <= self.MAX_VALUE:
            msg = f"Counter value {value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

        if quality is None:
            quality = CounterQuality.ONLINE

        self.value = value
        self.quality = quality
        self.timestamp = timestamp

        if self.config.event_class == EventClass.NONE:
            return False

        # Check deadband
        change = abs(value - self.last_event_value)
        if change >= self.config.deadband:
            self.last_event_value = value
            return True

        return False

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)

    def increment(
        self,
        amount: int = 1,
        quality: CounterQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Increment counter value.

        Args:
            amount: Amount to increment by.
            quality: New quality flags.
            timestamp: Time of update.

        Returns:
            True if event should be generated.
        """
        new_value = (self.value + amount) % (self.MAX_VALUE + 1)
        return self.update(new_value, quality, timestamp)


@dataclass
class FrozenCounterPoint:
    """Frozen counter point state.

    Frozen counters capture a snapshot of a counter at a specific time.

    Attributes:
        index: Point index.
        value: Frozen counter value.
        quality: Quality flags.
        timestamp: Time when counter was frozen.
        config: Point configuration.
    """

    index: int
    value: int = 0
    quality: CounterQuality = field(default_factory=lambda: CounterQuality.RESTART)
    timestamp: DNP3Timestamp | None = None
    config: CounterConfig = field(default_factory=CounterConfig)

    MAX_VALUE: int = 2**32 - 1

    def freeze(
        self,
        counter: CounterPoint,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Freeze a counter's current value.

        Args:
            counter: Counter point to freeze.
            timestamp: Time of freeze operation.

        Returns:
            True if value changed and event should be generated.
        """
        changed = self.value != counter.value
        self.value = counter.value
        self.quality = counter.quality
        self.timestamp = timestamp

        return changed and self.config.event_class != EventClass.NONE

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)
