"""Binary Output objects per IEEE 1815-2012.

Group 10: Binary Output Status
- Variation 1: Packed format (1 bit per point)
- Variation 2: With flags (1 byte per point)

Group 11: Binary Output Event
- Variation 1: Without time (1 byte flags)
- Variation 2: With time (7 bytes: flags + 6-byte timestamp)

Group 12: Control Relay Output Block (CROB)
- Variation 1: Standard CROB (11 bytes)
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import ClassVar

from dnp3.core.flags import BinaryQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import (
    SIZE_1_BYTE,
    SIZE_7_BYTES,
    SIZE_11_BYTES,
    EventObject,
    StaticObject,
)
from dnp3.objects.registry import register

# Group numbers
BINARY_OUTPUT_STATIC_GROUP = 10
BINARY_OUTPUT_EVENT_GROUP = 11
CROB_GROUP = 12

# Timestamp size
TIMESTAMP_SIZE = 6

# State bit mask
STATE_BIT = 0x80


class ControlCode(IntFlag):
    """Control operation code (Table 4-1).

    Bits 0-3: Operation type
    Bits 4-5: Trip-Close code
    Bit 6: Queue
    Bit 7: Clear
    """

    # Operation types (bits 0-3)
    NUL = 0x00  # No operation
    PULSE_ON = 0x01  # Pulse output on
    PULSE_OFF = 0x02  # Pulse output off
    LATCH_ON = 0x03  # Latch output on
    LATCH_OFF = 0x04  # Latch output off

    # Trip-Close codes (bits 4-5)
    TC_NUL = 0x00  # No trip-close
    TC_CLOSE = 0x10  # Close
    TC_TRIP = 0x20  # Trip
    TC_RESERVED = 0x30  # Reserved

    # Modifiers (bits 6-7)
    QUEUE = 0x40  # Queue operation
    CLEAR = 0x80  # Clear queued operations


class CommandStatus(IntEnum):
    """Command status codes (Table 4-2)."""

    SUCCESS = 0  # Command succeeded
    TIMEOUT = 1  # Command timed out
    NO_SELECT = 2  # No matching SELECT
    FORMAT_ERROR = 3  # Format error in control
    NOT_SUPPORTED = 4  # Control not supported
    ALREADY_ACTIVE = 5  # Control already active
    HARDWARE_ERROR = 6  # Hardware error
    LOCAL = 7  # Local control in effect
    TOO_MANY_OPS = 8  # Too many operations
    NOT_AUTHORIZED = 9  # Not authorized
    AUTOMATION_INHIBIT = 10  # Automation inhibit
    PROCESSING_LIMITED = 11  # Processing capacity limited
    OUT_OF_RANGE = 12  # Parameter out of range
    DOWNSTREAM_LOCAL = 13  # Downstream device in local
    ALREADY_COMPLETE = 14  # Operation already complete
    BLOCKED = 15  # Operation blocked
    CANCELLED = 16  # Operation cancelled
    BLOCKED_OTHER_MASTER = 17  # Blocked by other master
    DOWNSTREAM_FAIL = 18  # Downstream device failed
    NON_PARTICIPATING = 126  # Non-participating point
    UNDEFINED = 127  # Undefined error


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
class BinaryOutputFlags(StaticObject):
    """Binary Output with flags (g10v2).

    Each point is 1 byte containing quality flags and state.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
    """

    GROUP: ClassVar[int] = BINARY_OUTPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_1_BYTE

    quality: BinaryQuality
    state: bool

    def to_bytes(self) -> bytes:
        """Serialize to 1 byte."""
        return bytes([_build_flags(self.quality, self.state)])

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryOutputFlags":
        """Parse from 1 byte."""
        if len(data) < SIZE_1_BYTE:
            msg = f"Binary output requires {SIZE_1_BYTE} byte, got {len(data)}"
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
class BinaryOutputEvent(EventObject):
    """Binary Output Event without time (g11v1).

    Each event is 1 byte containing quality flags and state.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
    """

    GROUP: ClassVar[int] = BINARY_OUTPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_1_BYTE

    quality: BinaryQuality
    state: bool

    def to_bytes(self) -> bytes:
        """Serialize to 1 byte."""
        return bytes([_build_flags(self.quality, self.state)])

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryOutputEvent":
        """Parse from 1 byte."""
        if len(data) < SIZE_1_BYTE:
            msg = f"Binary output event requires {SIZE_1_BYTE} byte, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        return cls(quality=quality, state=state)


@register
@dataclass(frozen=True, slots=True)
class BinaryOutputEventTime(EventObject):
    """Binary Output Event with absolute time (g11v2).

    Each event is 7 bytes: 1 byte flags + 6 byte timestamp.

    Attributes:
        quality: Quality flags (bits 0-6).
        state: Binary state (bit 7): False=off, True=on.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = BINARY_OUTPUT_EVENT_GROUP
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
    def from_bytes(cls, data: bytes) -> "BinaryOutputEventTime":
        """Parse from 7 bytes."""
        if len(data) < SIZE_7_BYTES:
            msg = f"Binary output event with time requires {SIZE_7_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        flags = data[0]
        quality = BinaryQuality(flags & 0x7F)
        state = _extract_state(flags)
        timestamp = DNP3Timestamp.from_bytes(data[1:7])
        return cls(quality=quality, state=state, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class CROB(StaticObject):
    """Control Relay Output Block (g12v1).

    11-byte control command for binary output.

    Attributes:
        control_code: Control operation type.
        count: Number of times to execute.
        on_time_ms: Duration of ON state in milliseconds.
        off_time_ms: Duration of OFF state in milliseconds.
        status: Command status (typically 0 for requests).
    """

    GROUP: ClassVar[int] = CROB_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_11_BYTES

    control_code: ControlCode
    count: int
    on_time_ms: int
    off_time_ms: int
    status: CommandStatus

    # Constants
    MAX_COUNT: ClassVar[int] = 255
    MAX_TIME_MS: ClassVar[int] = 0xFFFFFFFF

    def __post_init__(self) -> None:
        """Validate CROB fields."""
        if not 0 <= self.count <= self.MAX_COUNT:
            msg = f"Count {self.count} out of range (0-{self.MAX_COUNT})"
            raise ValueError(msg)
        if not 0 <= self.on_time_ms <= self.MAX_TIME_MS:
            msg = f"On time {self.on_time_ms} out of range (0-{self.MAX_TIME_MS})"
            raise ValueError(msg)
        if not 0 <= self.off_time_ms <= self.MAX_TIME_MS:
            msg = f"Off time {self.off_time_ms} out of range (0-{self.MAX_TIME_MS})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 11 bytes.

        Format: control(1) + count(1) + on_time(4) + off_time(4) + status(1)
        """
        return (
            bytes([int(self.control_code), self.count])
            + self.on_time_ms.to_bytes(4, byteorder="little")
            + self.off_time_ms.to_bytes(4, byteorder="little")
            + bytes([int(self.status)])
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "CROB":
        """Parse from 11 bytes."""
        if len(data) < SIZE_11_BYTES:
            msg = f"CROB requires {SIZE_11_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        control_code = ControlCode(data[0])
        count = data[1]
        on_time_ms = int.from_bytes(data[2:6], byteorder="little")
        off_time_ms = int.from_bytes(data[6:10], byteorder="little")
        status = CommandStatus(data[10])
        return cls(
            control_code=control_code,
            count=count,
            on_time_ms=on_time_ms,
            off_time_ms=off_time_ms,
            status=status,
        )

    @classmethod
    def pulse_on(
        cls,
        on_time_ms: int = 1000,
        off_time_ms: int = 0,
        count: int = 1,
    ) -> "CROB":
        """Create a pulse-on CROB command."""
        return cls(
            control_code=ControlCode.PULSE_ON,
            count=count,
            on_time_ms=on_time_ms,
            off_time_ms=off_time_ms,
            status=CommandStatus.SUCCESS,
        )

    @classmethod
    def pulse_off(
        cls,
        on_time_ms: int = 0,
        off_time_ms: int = 1000,
        count: int = 1,
    ) -> "CROB":
        """Create a pulse-off CROB command."""
        return cls(
            control_code=ControlCode.PULSE_OFF,
            count=count,
            on_time_ms=on_time_ms,
            off_time_ms=off_time_ms,
            status=CommandStatus.SUCCESS,
        )

    @classmethod
    def latch_on(cls) -> "CROB":
        """Create a latch-on CROB command."""
        return cls(
            control_code=ControlCode.LATCH_ON,
            count=1,
            on_time_ms=0,
            off_time_ms=0,
            status=CommandStatus.SUCCESS,
        )

    @classmethod
    def latch_off(cls) -> "CROB":
        """Create a latch-off CROB command."""
        return cls(
            control_code=ControlCode.LATCH_OFF,
            count=1,
            on_time_ms=0,
            off_time_ms=0,
            status=CommandStatus.SUCCESS,
        )
