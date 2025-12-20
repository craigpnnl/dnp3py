"""Counter objects per IEEE 1815-2012.

Group 20: Counter Static
- Variation 1: 32-bit with flag (5 bytes)
- Variation 2: 16-bit with flag (3 bytes)
- Variation 5: 32-bit without flag (4 bytes)
- Variation 6: 16-bit without flag (2 bytes)

Group 21: Frozen Counter
- Variation 1: 32-bit with flag (5 bytes)
- Variation 2: 16-bit with flag (3 bytes)
- Variation 5: 32-bit with flag and time (11 bytes)
- Variation 6: 16-bit with flag and time (9 bytes)

Group 22: Counter Event
- Variation 1: 32-bit with flag (5 bytes)
- Variation 2: 16-bit with flag (3 bytes)
- Variation 5: 32-bit with flag and time (11 bytes)
- Variation 6: 16-bit with flag and time (9 bytes)
"""

from dataclasses import dataclass
from typing import ClassVar

from dnp3.core.flags import CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import (
    SIZE_2_BYTES,
    SIZE_4_BYTES,
    SIZE_5_BYTES,
    SIZE_9_BYTES,
    SIZE_11_BYTES,
    EventObject,
    StaticObject,
)
from dnp3.objects.registry import register

# Group numbers
COUNTER_STATIC_GROUP = 20
FROZEN_COUNTER_GROUP = 21
COUNTER_EVENT_GROUP = 22

# Size constants
SIZE_3_BYTES = 3


@register
@dataclass(frozen=True, slots=True)
class Counter32(StaticObject):
    """Counter 32-bit with flag (g20v1).

    5 bytes: 1 byte quality flags + 4 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 32-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_STATIC_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Counter32":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Counter 32-bit requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:5], "little")
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class Counter16(StaticObject):
    """Counter 16-bit with flag (g20v2).

    3 bytes: 1 byte quality flags + 2 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 16-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_STATIC_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_3_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Counter16":
        """Parse from 3 bytes."""
        if len(data) < SIZE_3_BYTES:
            msg = f"Counter 16-bit requires {SIZE_3_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:3], "little")
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class Counter32NoFlag(StaticObject):
    """Counter 32-bit without flag (g20v5).

    4 bytes: 4 byte unsigned value.

    Attributes:
        value: 32-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_STATIC_GROUP
    VARIATION: ClassVar[int] = 5
    SIZE: ClassVar[int] = SIZE_4_BYTES

    value: int

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 4 bytes."""
        return self.value.to_bytes(4, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Counter32NoFlag":
        """Parse from 4 bytes."""
        if len(data) < SIZE_4_BYTES:
            msg = f"Counter 32-bit requires {SIZE_4_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        value = int.from_bytes(data[0:4], "little")
        return cls(value=value)


@register
@dataclass(frozen=True, slots=True)
class Counter16NoFlag(StaticObject):
    """Counter 16-bit without flag (g20v6).

    2 bytes: 2 byte unsigned value.

    Attributes:
        value: 16-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_STATIC_GROUP
    VARIATION: ClassVar[int] = 6
    SIZE: ClassVar[int] = SIZE_2_BYTES

    value: int

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 2 bytes."""
        return self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Counter16NoFlag":
        """Parse from 2 bytes."""
        if len(data) < SIZE_2_BYTES:
            msg = f"Counter 16-bit requires {SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        value = int.from_bytes(data[0:2], "little")
        return cls(value=value)


# Frozen Counter objects


@register
@dataclass(frozen=True, slots=True)
class FrozenCounter32(StaticObject):
    """Frozen Counter 32-bit with flag (g21v1).

    5 bytes: 1 byte quality flags + 4 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 32-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = FROZEN_COUNTER_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "FrozenCounter32":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Frozen counter 32-bit requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:5], "little")
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class FrozenCounter16(StaticObject):
    """Frozen Counter 16-bit with flag (g21v2).

    3 bytes: 1 byte quality flags + 2 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 16-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = FROZEN_COUNTER_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_3_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "FrozenCounter16":
        """Parse from 3 bytes."""
        if len(data) < SIZE_3_BYTES:
            msg = f"Frozen counter 16-bit requires {SIZE_3_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:3], "little")
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & CounterQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class FrozenCounter32Time(StaticObject):
    """Frozen Counter 32-bit with flag and time (g21v5).

    11 bytes: 1 byte flags + 4 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 32-bit unsigned counter value.
        timestamp: Time when counter was frozen.
    """

    GROUP: ClassVar[int] = FROZEN_COUNTER_GROUP
    VARIATION: ClassVar[int] = 5
    SIZE: ClassVar[int] = SIZE_11_BYTES

    quality: CounterQuality
    value: int
    timestamp: DNP3Timestamp

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 11 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little") + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "FrozenCounter32Time":
        """Parse from 11 bytes."""
        if len(data) < SIZE_11_BYTES:
            msg = f"Frozen counter 32-bit with time requires {SIZE_11_BYTES} bytes"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:5], "little")
        timestamp = DNP3Timestamp.from_bytes(data[5:11])
        return cls(quality=quality, value=value, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class FrozenCounter16Time(StaticObject):
    """Frozen Counter 16-bit with flag and time (g21v6).

    9 bytes: 1 byte flags + 2 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 16-bit unsigned counter value.
        timestamp: Time when counter was frozen.
    """

    GROUP: ClassVar[int] = FROZEN_COUNTER_GROUP
    VARIATION: ClassVar[int] = 6
    SIZE: ClassVar[int] = SIZE_9_BYTES

    quality: CounterQuality
    value: int
    timestamp: DNP3Timestamp

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 9 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little") + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "FrozenCounter16Time":
        """Parse from 9 bytes."""
        if len(data) < SIZE_9_BYTES:
            msg = f"Frozen counter 16-bit with time requires {SIZE_9_BYTES} bytes"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:3], "little")
        timestamp = DNP3Timestamp.from_bytes(data[3:9])
        return cls(quality=quality, value=value, timestamp=timestamp)


# Counter Event objects


@register
@dataclass(frozen=True, slots=True)
class CounterEvent32(EventObject):
    """Counter Event 32-bit with flag (g22v1).

    5 bytes: 1 byte quality flags + 4 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 32-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_EVENT_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "CounterEvent32":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Counter event 32-bit requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:5], "little")
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class CounterEvent16(EventObject):
    """Counter Event 16-bit with flag (g22v2).

    3 bytes: 1 byte quality flags + 2 byte unsigned value.

    Attributes:
        quality: Quality flags.
        value: 16-bit unsigned counter value.
    """

    GROUP: ClassVar[int] = COUNTER_EVENT_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_3_BYTES

    quality: CounterQuality
    value: int

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "CounterEvent16":
        """Parse from 3 bytes."""
        if len(data) < SIZE_3_BYTES:
            msg = f"Counter event 16-bit requires {SIZE_3_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:3], "little")
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class CounterEvent32Time(EventObject):
    """Counter Event 32-bit with flag and time (g22v5).

    11 bytes: 1 byte flags + 4 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 32-bit unsigned counter value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = COUNTER_EVENT_GROUP
    VARIATION: ClassVar[int] = 5
    SIZE: ClassVar[int] = SIZE_11_BYTES

    quality: CounterQuality
    value: int
    timestamp: DNP3Timestamp

    MAX_VALUE: ClassVar[int] = 2**32 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 11 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little") + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "CounterEvent32Time":
        """Parse from 11 bytes."""
        if len(data) < SIZE_11_BYTES:
            msg = f"Counter event 32-bit with time requires {SIZE_11_BYTES} bytes"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:5], "little")
        timestamp = DNP3Timestamp.from_bytes(data[5:11])
        return cls(quality=quality, value=value, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class CounterEvent16Time(EventObject):
    """Counter Event 16-bit with flag and time (g22v6).

    9 bytes: 1 byte flags + 2 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 16-bit unsigned counter value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = COUNTER_EVENT_GROUP
    VARIATION: ClassVar[int] = 6
    SIZE: ClassVar[int] = SIZE_9_BYTES

    quality: CounterQuality
    value: int
    timestamp: DNP3Timestamp

    MAX_VALUE: ClassVar[int] = 2**16 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not 0 <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range (0 to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 9 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little") + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "CounterEvent16Time":
        """Parse from 9 bytes."""
        if len(data) < SIZE_9_BYTES:
            msg = f"Counter event 16-bit with time requires {SIZE_9_BYTES} bytes"
            raise ValueError(msg)
        quality = CounterQuality(data[0])
        value = int.from_bytes(data[1:3], "little")
        timestamp = DNP3Timestamp.from_bytes(data[3:9])
        return cls(quality=quality, value=value, timestamp=timestamp)
