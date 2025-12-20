"""Binary Input objects per IEEE 1815-2012.

Group 1: Binary Input Static
- Variation 1: Packed format (1 bit per point)
- Variation 2: With flags (1 byte per point)

Group 2: Binary Input Event
- Variation 1: Without time (1 byte flags)
- Variation 2: With absolute time (7 bytes: flags + 6-byte timestamp)
- Variation 3: With relative time (3 bytes: flags + 2-byte relative time)
"""

from dataclasses import dataclass
from typing import ClassVar

from dnp3.core.flags import BinaryQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import (
    QUALITY_SIZE,
    SIZE_1_BYTE,
    SIZE_7_BYTES,
    EventObject,
    StaticObject,
)
from dnp3.objects.registry import register

# Group numbers
BINARY_INPUT_STATIC_GROUP = 1
BINARY_INPUT_EVENT_GROUP = 2

# Timestamp size
TIMESTAMP_SIZE = 6
RELATIVE_TIME_SIZE = 2

# State bit mask
STATE_BIT = 0x80


def _extract_state(flags: int) -> bool:
    """Extract binary state from flags byte."""
    return bool(flags & STATE_BIT)


def _build_flags(quality: BinaryQuality, state: bool) -> int:
    """Build flags byte from quality and state."""
    flags = int(quality)
    if state:
        flags |= STATE_BIT
    return flags


@register
@dataclass(frozen=True, slots=True)
class BinaryInputFlags(StaticObject):
    """Binary Input with flags (g1v2).

    Each point is 1 byte containing quality flags and state.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
    """

    GROUP: ClassVar[int] = BINARY_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_1_BYTE

    quality: BinaryQuality
    state: bool

    def to_bytes(self) -> bytes:
        """Serialize to 1 byte."""
        return bytes([_build_flags(self.quality, self.state)])

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryInputFlags":
        """Parse from 1 byte."""
        if len(data) < SIZE_1_BYTE:
            msg = f"Binary input requires {SIZE_1_BYTE} byte, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        return cls(quality=quality, state=state)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & BinaryQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class BinaryInputEvent(EventObject):
    """Binary Input Event without time (g2v1).

    Each event is 1 byte containing quality flags and state.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
    """

    GROUP: ClassVar[int] = BINARY_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_1_BYTE

    quality: BinaryQuality
    state: bool

    def to_bytes(self) -> bytes:
        """Serialize to 1 byte."""
        return bytes([_build_flags(self.quality, self.state)])

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryInputEvent":
        """Parse from 1 byte."""
        if len(data) < SIZE_1_BYTE:
            msg = f"Binary input event requires {SIZE_1_BYTE} byte, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        return cls(quality=quality, state=state)


@register
@dataclass(frozen=True, slots=True)
class BinaryInputEventTime(EventObject):
    """Binary Input Event with absolute time (g2v2).

    Each event is 7 bytes: 1 byte flags + 6 byte timestamp.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = BINARY_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_7_BYTES

    quality: BinaryQuality
    state: bool
    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 7 bytes."""
        flags_byte = bytes([_build_flags(self.quality, self.state)])
        return flags_byte + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryInputEventTime":
        """Parse from 7 bytes."""
        if len(data) < SIZE_7_BYTES:
            msg = f"Binary input event with time requires {SIZE_7_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        timestamp = DNP3Timestamp.from_bytes(data[1:7])
        return cls(quality=quality, state=state, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class BinaryInputEventRelativeTime(EventObject):
    """Binary Input Event with relative time (g2v3).

    Each event is 3 bytes: 1 byte flags + 2 byte relative time.
    Relative time is milliseconds since CTO (Common Time of Occurrence).

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
        relative_time_ms: Milliseconds since CTO (0-65535).
    """

    GROUP: ClassVar[int] = BINARY_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 3
    SIZE: ClassVar[int] = QUALITY_SIZE + RELATIVE_TIME_SIZE

    quality: BinaryQuality
    state: bool
    relative_time_ms: int

    def __post_init__(self) -> None:
        """Validate relative time range."""
        max_relative_time = 65535
        if not 0 <= self.relative_time_ms <= max_relative_time:
            msg = f"Relative time {self.relative_time_ms} out of range (0-{max_relative_time})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        flags_byte = bytes([_build_flags(self.quality, self.state)])
        time_bytes = self.relative_time_ms.to_bytes(2, byteorder="little")
        return flags_byte + time_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryInputEventRelativeTime":
        """Parse from 3 bytes."""
        required = QUALITY_SIZE + RELATIVE_TIME_SIZE
        if len(data) < required:
            msg = f"Binary input event with relative time requires {required} bytes, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        relative_time_ms = int.from_bytes(data[1:3], byteorder="little")
        return cls(quality=quality, state=state, relative_time_ms=relative_time_ms)
