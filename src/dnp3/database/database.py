"""DNP3 Outstation Database.

The database stores all point values and generates events on value changes.
Events are stored in the event buffer until read by the master.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.event_buffer import (
    EventBuffer,
    EventBufferConfig,
    EventType,
)
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
)


@dataclass
class DatabaseConfig:
    """Configuration for the outstation database.

    Attributes:
        max_binary_inputs: Maximum number of binary input points.
        max_binary_outputs: Maximum number of binary output points.
        max_analog_inputs: Maximum number of analog input points.
        max_counters: Maximum number of counter points.
        max_frozen_counters: Maximum number of frozen counter points.
        event_buffer_config: Configuration for event buffer.
    """

    max_binary_inputs: int = 100
    max_binary_outputs: int = 100
    max_analog_inputs: int = 100
    max_counters: int = 100
    max_frozen_counters: int = 100
    event_buffer_config: EventBufferConfig = field(default_factory=EventBufferConfig)


@dataclass
class Database:
    """DNP3 Outstation point database.

    Stores all point values and automatically generates events
    when values change.

    Attributes:
        config: Database configuration.
        binary_inputs: Binary input points by index.
        binary_outputs: Binary output points by index.
        analog_inputs: Analog input points by index.
        counters: Counter points by index.
        frozen_counters: Frozen counter points by index.
        event_buffer: Event buffer for storing generated events.
    """

    config: DatabaseConfig = field(default_factory=DatabaseConfig)
    binary_inputs: dict[int, BinaryInputPoint] = field(default_factory=dict)
    binary_outputs: dict[int, BinaryOutputPoint] = field(default_factory=dict)
    analog_inputs: dict[int, AnalogInputPoint] = field(default_factory=dict)
    counters: dict[int, CounterPoint] = field(default_factory=dict)
    frozen_counters: dict[int, FrozenCounterPoint] = field(default_factory=dict)
    event_buffer: EventBuffer = field(default_factory=EventBuffer)

    def __post_init__(self) -> None:
        """Initialize event buffer with config."""
        self.event_buffer = EventBuffer(config=self.config.event_buffer_config)

    # Point addition methods

    def add_binary_input(
        self,
        index: int,
        config: BinaryInputConfig | None = None,
        value: bool = False,
        quality: BinaryQuality = BinaryQuality.RESTART,
    ) -> BinaryInputPoint:
        """Add a binary input point.

        Args:
            index: Point index (must be unique).
            config: Point configuration.
            value: Initial value.
            quality: Initial quality.

        Returns:
            The created point.

        Raises:
            ValueError: If index already exists or exceeds max.
        """
        if index in self.binary_inputs:
            msg = f"Binary input index {index} already exists"
            raise ValueError(msg)
        if len(self.binary_inputs) >= self.config.max_binary_inputs:
            msg = f"Maximum binary inputs ({self.config.max_binary_inputs}) exceeded"
            raise ValueError(msg)

        point = BinaryInputPoint(
            index=index,
            config=config or BinaryInputConfig(),
            value=value,
            quality=quality,
        )
        self.binary_inputs[index] = point
        return point

    def add_binary_output(
        self,
        index: int,
        config: BinaryOutputConfig | None = None,
        value: bool = False,
        quality: BinaryQuality = BinaryQuality.RESTART,
    ) -> BinaryOutputPoint:
        """Add a binary output point.

        Args:
            index: Point index (must be unique).
            config: Point configuration.
            value: Initial value.
            quality: Initial quality.

        Returns:
            The created point.

        Raises:
            ValueError: If index already exists or exceeds max.
        """
        if index in self.binary_outputs:
            msg = f"Binary output index {index} already exists"
            raise ValueError(msg)
        if len(self.binary_outputs) >= self.config.max_binary_outputs:
            msg = f"Maximum binary outputs ({self.config.max_binary_outputs}) exceeded"
            raise ValueError(msg)

        point = BinaryOutputPoint(
            index=index,
            config=config or BinaryOutputConfig(),
            value=value,
            quality=quality,
        )
        self.binary_outputs[index] = point
        return point

    def add_analog_input(
        self,
        index: int,
        config: AnalogInputConfig | None = None,
        value: float = 0.0,
        quality: AnalogQuality = AnalogQuality.RESTART,
    ) -> AnalogInputPoint:
        """Add an analog input point.

        Args:
            index: Point index (must be unique).
            config: Point configuration.
            value: Initial value.
            quality: Initial quality.

        Returns:
            The created point.

        Raises:
            ValueError: If index already exists or exceeds max.
        """
        if index in self.analog_inputs:
            msg = f"Analog input index {index} already exists"
            raise ValueError(msg)
        if len(self.analog_inputs) >= self.config.max_analog_inputs:
            msg = f"Maximum analog inputs ({self.config.max_analog_inputs}) exceeded"
            raise ValueError(msg)

        point = AnalogInputPoint(
            index=index,
            config=config or AnalogInputConfig(),
            value=value,
            quality=quality,
        )
        self.analog_inputs[index] = point
        return point

    def add_counter(
        self,
        index: int,
        config: CounterConfig | None = None,
        value: int = 0,
        quality: CounterQuality = CounterQuality.RESTART,
    ) -> CounterPoint:
        """Add a counter point.

        Args:
            index: Point index (must be unique).
            config: Point configuration.
            value: Initial value.
            quality: Initial quality.

        Returns:
            The created point.

        Raises:
            ValueError: If index already exists or exceeds max.
        """
        if index in self.counters:
            msg = f"Counter index {index} already exists"
            raise ValueError(msg)
        if len(self.counters) >= self.config.max_counters:
            msg = f"Maximum counters ({self.config.max_counters}) exceeded"
            raise ValueError(msg)

        point = CounterPoint(
            index=index,
            config=config or CounterConfig(),
            value=value,
            quality=quality,
        )
        self.counters[index] = point
        return point

    def add_frozen_counter(
        self,
        index: int,
        config: CounterConfig | None = None,
        value: int = 0,
        quality: CounterQuality = CounterQuality.RESTART,
    ) -> FrozenCounterPoint:
        """Add a frozen counter point.

        Args:
            index: Point index (must be unique).
            config: Point configuration.
            value: Initial value.
            quality: Initial quality.

        Returns:
            The created point.

        Raises:
            ValueError: If index already exists or exceeds max.
        """
        if index in self.frozen_counters:
            msg = f"Frozen counter index {index} already exists"
            raise ValueError(msg)
        if len(self.frozen_counters) >= self.config.max_frozen_counters:
            msg = f"Maximum frozen counters ({self.config.max_frozen_counters}) exceeded"
            raise ValueError(msg)

        point = FrozenCounterPoint(
            index=index,
            config=config or CounterConfig(),
            value=value,
            quality=quality,
        )
        self.frozen_counters[index] = point
        return point

    # Point update methods (with automatic event generation)

    def update_binary_input(
        self,
        index: int,
        value: bool,
        quality: BinaryQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update a binary input point.

        Args:
            index: Point index.
            value: New value.
            quality: New quality (defaults to ONLINE).
            timestamp: Update timestamp.

        Returns:
            True if an event was generated.

        Raises:
            KeyError: If point does not exist.
        """
        point = self.binary_inputs[index]
        if point.update(value, quality, timestamp):
            self.event_buffer.add_binary_event(
                event_class=point.config.event_class,
                index=index,
                value=point.value,
                quality=point.quality,
                timestamp=timestamp,
                event_type=EventType.BINARY_INPUT,
            )
            return True
        return False

    def update_binary_output(
        self,
        index: int,
        value: bool,
        quality: BinaryQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update a binary output point.

        Args:
            index: Point index.
            value: New value.
            quality: New quality (defaults to ONLINE).
            timestamp: Update timestamp.

        Returns:
            True if an event was generated.

        Raises:
            KeyError: If point does not exist.
        """
        point = self.binary_outputs[index]
        if point.update(value, quality, timestamp):
            self.event_buffer.add_binary_event(
                event_class=point.config.event_class,
                index=index,
                value=point.value,
                quality=point.quality,
                timestamp=timestamp,
                event_type=EventType.BINARY_OUTPUT,
            )
            return True
        return False

    def update_analog_input(
        self,
        index: int,
        value: float,
        quality: AnalogQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update an analog input point.

        Args:
            index: Point index.
            value: New value.
            quality: New quality (defaults to ONLINE).
            timestamp: Update timestamp.

        Returns:
            True if an event was generated (exceeds deadband).

        Raises:
            KeyError: If point does not exist.
        """
        point = self.analog_inputs[index]
        if point.update(value, quality, timestamp):
            self.event_buffer.add_analog_event(
                event_class=point.config.event_class,
                index=index,
                value=point.value,
                quality=point.quality,
                timestamp=timestamp,
            )
            return True
        return False

    def update_counter(
        self,
        index: int,
        value: int,
        quality: CounterQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Update a counter point.

        Args:
            index: Point index.
            value: New value.
            quality: New quality (defaults to ONLINE).
            timestamp: Update timestamp.

        Returns:
            True if an event was generated (exceeds deadband).

        Raises:
            KeyError: If point does not exist.
            ValueError: If value is out of range.
        """
        point = self.counters[index]
        if point.update(value, quality, timestamp):
            self.event_buffer.add_counter_event(
                event_class=point.config.event_class,
                index=index,
                value=point.value,
                quality=point.quality,
                timestamp=timestamp,
                event_type=EventType.COUNTER,
            )
            return True
        return False

    def increment_counter(
        self,
        index: int,
        amount: int = 1,
        quality: CounterQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Increment a counter point.

        Args:
            index: Point index.
            amount: Amount to increment.
            quality: New quality.
            timestamp: Update timestamp.

        Returns:
            True if an event was generated.

        Raises:
            KeyError: If point does not exist.
        """
        point = self.counters[index]
        if point.increment(amount, quality, timestamp):
            self.event_buffer.add_counter_event(
                event_class=point.config.event_class,
                index=index,
                value=point.value,
                quality=point.quality,
                timestamp=timestamp,
                event_type=EventType.COUNTER,
            )
            return True
        return False

    def freeze_counter(
        self,
        counter_index: int,
        frozen_index: int | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        """Freeze a counter to its frozen counterpart.

        Args:
            counter_index: Index of counter to freeze.
            frozen_index: Index of frozen counter (defaults to same as counter).
            timestamp: Freeze timestamp.

        Returns:
            True if an event was generated.

        Raises:
            KeyError: If counter or frozen counter does not exist.
        """
        if frozen_index is None:
            frozen_index = counter_index

        counter = self.counters[counter_index]
        frozen = self.frozen_counters[frozen_index]

        if frozen.freeze(counter, timestamp):
            self.event_buffer.add_counter_event(
                event_class=frozen.config.event_class,
                index=frozen_index,
                value=frozen.value,
                quality=frozen.quality,
                timestamp=timestamp,
                event_type=EventType.FROZEN_COUNTER,
            )
            return True
        return False

    # Bulk operations

    def transaction(self, callback: Callable[["Database"], None]) -> None:
        """Execute multiple updates in a transaction.

        This is a convenience method that doesn't provide actual
        transaction semantics, but groups updates logically.

        Args:
            callback: Function to execute with database reference.
        """
        callback(self)

    # Point access methods

    def get_binary_input(self, index: int) -> BinaryInputPoint | None:
        """Get a binary input point by index."""
        return self.binary_inputs.get(index)

    def get_binary_output(self, index: int) -> BinaryOutputPoint | None:
        """Get a binary output point by index."""
        return self.binary_outputs.get(index)

    def get_analog_input(self, index: int) -> AnalogInputPoint | None:
        """Get an analog input point by index."""
        return self.analog_inputs.get(index)

    def get_counter(self, index: int) -> CounterPoint | None:
        """Get a counter point by index."""
        return self.counters.get(index)

    def get_frozen_counter(self, index: int) -> FrozenCounterPoint | None:
        """Get a frozen counter point by index."""
        return self.frozen_counters.get(index)

    # Range access methods

    def get_binary_inputs_range(self, start: int, stop: int) -> list[BinaryInputPoint]:
        """Get binary inputs in index range [start, stop].

        Args:
            start: First index (inclusive).
            stop: Last index (inclusive).

        Returns:
            List of points in range (may be sparse).
        """
        return [point for index, point in sorted(self.binary_inputs.items()) if start <= index <= stop]

    def get_binary_outputs_range(self, start: int, stop: int) -> list[BinaryOutputPoint]:
        """Get binary outputs in index range [start, stop]."""
        return [point for index, point in sorted(self.binary_outputs.items()) if start <= index <= stop]

    def get_analog_inputs_range(self, start: int, stop: int) -> list[AnalogInputPoint]:
        """Get analog inputs in index range [start, stop]."""
        return [point for index, point in sorted(self.analog_inputs.items()) if start <= index <= stop]

    def get_counters_range(self, start: int, stop: int) -> list[CounterPoint]:
        """Get counters in index range [start, stop]."""
        return [point for index, point in sorted(self.counters.items()) if start <= index <= stop]

    def get_frozen_counters_range(self, start: int, stop: int) -> list[FrozenCounterPoint]:
        """Get frozen counters in index range [start, stop]."""
        return [point for index, point in sorted(self.frozen_counters.items()) if start <= index <= stop]

    # Class data access (all static data)

    def get_all_binary_inputs(self) -> list[BinaryInputPoint]:
        """Get all binary input points sorted by index."""
        return [point for _, point in sorted(self.binary_inputs.items())]

    def get_all_binary_outputs(self) -> list[BinaryOutputPoint]:
        """Get all binary output points sorted by index."""
        return [point for _, point in sorted(self.binary_outputs.items())]

    def get_all_analog_inputs(self) -> list[AnalogInputPoint]:
        """Get all analog input points sorted by index."""
        return [point for _, point in sorted(self.analog_inputs.items())]

    def get_all_counters(self) -> list[CounterPoint]:
        """Get all counter points sorted by index."""
        return [point for _, point in sorted(self.counters.items())]

    def get_all_frozen_counters(self) -> list[FrozenCounterPoint]:
        """Get all frozen counter points sorted by index."""
        return [point for _, point in sorted(self.frozen_counters.items())]

    # Count properties

    @property
    def binary_input_count(self) -> int:
        """Number of binary input points."""
        return len(self.binary_inputs)

    @property
    def binary_output_count(self) -> int:
        """Number of binary output points."""
        return len(self.binary_outputs)

    @property
    def analog_input_count(self) -> int:
        """Number of analog input points."""
        return len(self.analog_inputs)

    @property
    def counter_count(self) -> int:
        """Number of counter points."""
        return len(self.counters)

    @property
    def frozen_counter_count(self) -> int:
        """Number of frozen counter points."""
        return len(self.frozen_counters)

    @property
    def total_point_count(self) -> int:
        """Total number of points across all types."""
        return (
            self.binary_input_count
            + self.binary_output_count
            + self.analog_input_count
            + self.counter_count
            + self.frozen_counter_count
        )

    # Event class data access

    def get_class_binary_inputs(self, event_class: EventClass) -> list[BinaryInputPoint]:
        """Get binary inputs assigned to event class."""
        return [point for point in self.get_all_binary_inputs() if point.config.event_class == event_class]

    def get_class_binary_outputs(self, event_class: EventClass) -> list[BinaryOutputPoint]:
        """Get binary outputs assigned to event class."""
        return [point for point in self.get_all_binary_outputs() if point.config.event_class == event_class]

    def get_class_analog_inputs(self, event_class: EventClass) -> list[AnalogInputPoint]:
        """Get analog inputs assigned to event class."""
        return [point for point in self.get_all_analog_inputs() if point.config.event_class == event_class]

    def get_class_counters(self, event_class: EventClass) -> list[CounterPoint]:
        """Get counters assigned to event class."""
        return [point for point in self.get_all_counters() if point.config.event_class == event_class]

    def get_class_frozen_counters(self, event_class: EventClass) -> list[FrozenCounterPoint]:
        """Get frozen counters assigned to event class."""
        return [point for point in self.get_all_frozen_counters() if point.config.event_class == event_class]

    # Utility methods

    def clear_all_points(self) -> None:
        """Remove all points from the database."""
        self.binary_inputs.clear()
        self.binary_outputs.clear()
        self.analog_inputs.clear()
        self.counters.clear()
        self.frozen_counters.clear()

    def clear_events(self) -> int:
        """Clear all events from the event buffer.

        Returns:
            Number of events cleared.
        """
        return self.event_buffer.clear_all()
