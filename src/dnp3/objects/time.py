"""Time objects per IEEE 1815-2012.

Group 50: Time and Date
- Variation 1: Absolute time (6 bytes)
- Variation 4: Indexed absolute time

Group 51: Time and Date CTO (Common Time of Occurrence)
- Variation 1: Absolute time CTO
- Variation 2: Unsynchronized CTO

Group 52: Time Delay
- Variation 1: Coarse time delay (2 bytes, seconds)
- Variation 2: Fine time delay (2 bytes, milliseconds)
"""

from dataclasses import dataclass
from typing import ClassVar

from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import SIZE_2_BYTES, SIZE_6_BYTES, StaticObject
from dnp3.objects.registry import register

# Group numbers
TIME_AND_DATE_GROUP = 50
TIME_CTO_GROUP = 51
TIME_DELAY_GROUP = 52

# Timestamp size
TIMESTAMP_SIZE = 6


@register
@dataclass(frozen=True, slots=True)
class TimeAndDate(StaticObject):
    """Time and Date (g50v1).

    6 bytes: 48-bit milliseconds since epoch.

    Attributes:
        timestamp: Absolute time value.
    """

    GROUP: ClassVar[int] = TIME_AND_DATE_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_6_BYTES

    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 6 bytes."""
        return self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "TimeAndDate":
        """Parse from 6 bytes."""
        if len(data) < SIZE_6_BYTES:
            msg = f"Time and date requires {SIZE_6_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        timestamp = DNP3Timestamp.from_bytes(data[:6])
        return cls(timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class TimeCTO(StaticObject):
    """Time and Date CTO - Common Time of Occurrence (g51v1).

    6 bytes: 48-bit milliseconds since epoch.
    Used as a reference time for relative time values.

    Attributes:
        timestamp: Absolute time value.
    """

    GROUP: ClassVar[int] = TIME_CTO_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_6_BYTES

    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 6 bytes."""
        return self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "TimeCTO":
        """Parse from 6 bytes."""
        if len(data) < SIZE_6_BYTES:
            msg = f"Time CTO requires {SIZE_6_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        timestamp = DNP3Timestamp.from_bytes(data[:6])
        return cls(timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class TimeCTOUnsync(StaticObject):
    """Unsynchronized Time and Date CTO (g51v2).

    6 bytes: 48-bit milliseconds since epoch.
    Indicates time source is not synchronized.

    Attributes:
        timestamp: Absolute time value (unsynchronized).
    """

    GROUP: ClassVar[int] = TIME_CTO_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_6_BYTES

    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 6 bytes."""
        return self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "TimeCTOUnsync":
        """Parse from 6 bytes."""
        if len(data) < SIZE_6_BYTES:
            msg = f"Unsync time CTO requires {SIZE_6_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        timestamp = DNP3Timestamp.from_bytes(data[:6])
        return cls(timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class TimeDelayCoarse(StaticObject):
    """Coarse Time Delay (g52v1).

    2 bytes: Delay in seconds.
    Used in delay measurement procedure.

    Attributes:
        delay_seconds: Delay value in seconds (0-65535).
    """

    GROUP: ClassVar[int] = TIME_DELAY_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_2_BYTES

    delay_seconds: int

    MAX_VALUE: ClassVar[int] = 65535

    def __post_init__(self) -> None:
        """Validate delay range."""
        if not 0 <= self.delay_seconds <= self.MAX_VALUE:
            msg = f"Delay {self.delay_seconds} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 2 bytes."""
        return self.delay_seconds.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "TimeDelayCoarse":
        """Parse from 2 bytes."""
        if len(data) < SIZE_2_BYTES:
            msg = f"Coarse time delay requires {SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        delay_seconds = int.from_bytes(data[:2], "little")
        return cls(delay_seconds=delay_seconds)


@register
@dataclass(frozen=True, slots=True)
class TimeDelayFine(StaticObject):
    """Fine Time Delay (g52v2).

    2 bytes: Delay in milliseconds.
    Used in delay measurement procedure.

    Attributes:
        delay_ms: Delay value in milliseconds (0-65535).
    """

    GROUP: ClassVar[int] = TIME_DELAY_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_2_BYTES

    delay_ms: int

    MAX_VALUE: ClassVar[int] = 65535

    def __post_init__(self) -> None:
        """Validate delay range."""
        if not 0 <= self.delay_ms <= self.MAX_VALUE:
            msg = f"Delay {self.delay_ms} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 2 bytes."""
        return self.delay_ms.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "TimeDelayFine":
        """Parse from 2 bytes."""
        if len(data) < SIZE_2_BYTES:
            msg = f"Fine time delay requires {SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        delay_ms = int.from_bytes(data[:2], "little")
        return cls(delay_ms=delay_ms)
