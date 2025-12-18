"""Base classes for DNP3 objects per IEEE 1815-2012.

DNP3 objects are identified by group and variation numbers:
- Group: Defines the type of data (binary input, analog output, etc.)
- Variation: Defines the format/encoding of the data

Object categories:
- Static: Current point values (e.g., g1v1 Binary Input packed format)
- Event: Change events with optional timestamps (e.g., g2v1 Binary Input event)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from dnp3.core.timestamp import DNP3Timestamp

# Maximum byte value for group/variation validation
MAX_BYTE_VALUE = 255


@dataclass(frozen=True, slots=True)
class GroupVariation:
    """Identifies an object type by group and variation.

    Attributes:
        group: Object group number (1-120).
        variation: Object variation number (0-255).
    """

    group: int
    variation: int

    def __post_init__(self) -> None:
        """Validate group and variation ranges."""
        if not 0 <= self.group <= MAX_BYTE_VALUE:
            msg = f"Group {self.group} out of range (0-{MAX_BYTE_VALUE})"
            raise ValueError(msg)
        if not 0 <= self.variation <= MAX_BYTE_VALUE:
            msg = f"Variation {self.variation} out of range (0-{MAX_BYTE_VALUE})"
            raise ValueError(msg)

    def __str__(self) -> str:
        """Format as g{group}v{variation}."""
        return f"g{self.group}v{self.variation}"


class DNP3Object(ABC):
    """Base class for all DNP3 data objects.

    Each object type must define:
    - GROUP: Object group number
    - VARIATION: Object variation number
    - SIZE: Fixed size in bytes (or None for variable size)
    """

    GROUP: ClassVar[int]
    VARIATION: ClassVar[int]
    SIZE: ClassVar[int | None]

    @classmethod
    def group_variation(cls) -> GroupVariation:
        """Get the group/variation identifier."""
        return GroupVariation(group=cls.GROUP, variation=cls.VARIATION)

    @abstractmethod
    def to_bytes(self) -> bytes:
        """Serialize the object to bytes.

        Returns:
            Object data as bytes.
        """

    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes) -> "DNP3Object":
        """Parse an object from bytes.

        Args:
            data: Raw bytes containing the object.

        Returns:
            Parsed object instance.

        Raises:
            ValueError: If data is invalid or too short.
        """

    @classmethod
    def size(cls) -> int | None:
        """Get the fixed size of this object type.

        Returns:
            Size in bytes, or None if variable size.
        """
        return cls.SIZE


class StaticObject(DNP3Object):
    """Base class for static (current value) objects.

    Static objects represent the current state of a point.
    They are typically returned in response to READ requests.
    """


class EventObject(DNP3Object):
    """Base class for event objects.

    Event objects represent changes that occurred at a point.
    They may include timestamps and are buffered until read.
    """


@dataclass(frozen=True, slots=True)
class PointValue:
    """A point value with its index.

    Attributes:
        index: Point index (0-65535 typically).
        value: The data object.
    """

    index: int
    value: DNP3Object

    def __post_init__(self) -> None:
        """Validate index range."""
        if self.index < 0:
            msg = f"Point index {self.index} cannot be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TimestampedValue:
    """A value with timestamp.

    Attributes:
        value: The data value.
        timestamp: When the value was recorded.
    """

    value: DNP3Object
    timestamp: DNP3Timestamp


# Common size constants for object definitions
SIZE_1_BYTE = 1
SIZE_2_BYTES = 2
SIZE_4_BYTES = 4
SIZE_5_BYTES = 5
SIZE_6_BYTES = 6
SIZE_7_BYTES = 7
SIZE_8_BYTES = 8
SIZE_9_BYTES = 9
SIZE_11_BYTES = 11

# Quality flag byte size
QUALITY_SIZE = 1
