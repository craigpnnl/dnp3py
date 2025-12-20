"""Analog Input objects per IEEE 1815-2012.

Group 30: Analog Input Static
- Variation 1: 32-bit with flag (5 bytes)
- Variation 2: 16-bit with flag (3 bytes)
- Variation 3: 32-bit without flag (4 bytes)
- Variation 4: 16-bit without flag (2 bytes)
- Variation 5: Single-precision float with flag (5 bytes)
- Variation 6: Double-precision float with flag (9 bytes)

Group 32: Analog Input Event
- Variation 1: 32-bit without time (5 bytes)
- Variation 2: 16-bit without time (3 bytes)
- Variation 3: 32-bit with time (11 bytes)
- Variation 4: 16-bit with time (9 bytes)
- Variation 5: Single-precision float without time (5 bytes)
- Variation 6: Double-precision float without time (9 bytes)
- Variation 7: Single-precision float with time (11 bytes)
- Variation 8: Double-precision float with time (15 bytes)
"""

import struct
from dataclasses import dataclass
from typing import ClassVar

from dnp3.core.flags import AnalogQuality
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
ANALOG_INPUT_STATIC_GROUP = 30
ANALOG_INPUT_EVENT_GROUP = 32

# Timestamp size
TIMESTAMP_SIZE = 6

# Size constants for analog objects
SIZE_3_BYTES = 3
SIZE_15_BYTES = 15


@register
@dataclass(frozen=True, slots=True)
class AnalogInput32(StaticObject):
    """Analog Input 32-bit with flag (g30v1).

    5 bytes: 1 byte quality flags + 4 byte signed value.

    Attributes:
        quality: Quality flags.
        value: 32-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: AnalogQuality
    value: int

    MIN_VALUE: ClassVar[int] = -(2**31)
    MAX_VALUE: ClassVar[int] = 2**31 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInput32":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Analog input 32-bit requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:5], "little", signed=True)
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & AnalogQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class AnalogInput16(StaticObject):
    """Analog Input 16-bit with flag (g30v2).

    3 bytes: 1 byte quality flags + 2 byte signed value.

    Attributes:
        quality: Quality flags.
        value: 16-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_3_BYTES

    quality: AnalogQuality
    value: int

    MIN_VALUE: ClassVar[int] = -(2**15)
    MAX_VALUE: ClassVar[int] = 2**15 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInput16":
        """Parse from 3 bytes."""
        if len(data) < SIZE_3_BYTES:
            msg = f"Analog input 16-bit requires {SIZE_3_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:3], "little", signed=True)
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & AnalogQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class AnalogInput32NoFlag(StaticObject):
    """Analog Input 32-bit without flag (g30v3).

    4 bytes: 4 byte signed value.

    Attributes:
        value: 32-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 3
    SIZE: ClassVar[int] = SIZE_4_BYTES

    value: int

    MIN_VALUE: ClassVar[int] = -(2**31)
    MAX_VALUE: ClassVar[int] = 2**31 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 4 bytes."""
        return self.value.to_bytes(4, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInput32NoFlag":
        """Parse from 4 bytes."""
        if len(data) < SIZE_4_BYTES:
            msg = f"Analog input 32-bit requires {SIZE_4_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        value = int.from_bytes(data[0:4], "little", signed=True)
        return cls(value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInput16NoFlag(StaticObject):
    """Analog Input 16-bit without flag (g30v4).

    2 bytes: 2 byte signed value.

    Attributes:
        value: 16-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 4
    SIZE: ClassVar[int] = SIZE_2_BYTES

    value: int

    MIN_VALUE: ClassVar[int] = -(2**15)
    MAX_VALUE: ClassVar[int] = 2**15 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 2 bytes."""
        return self.value.to_bytes(2, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInput16NoFlag":
        """Parse from 2 bytes."""
        if len(data) < SIZE_2_BYTES:
            msg = f"Analog input 16-bit requires {SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        value = int.from_bytes(data[0:2], "little", signed=True)
        return cls(value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputFloat(StaticObject):
    """Analog Input single-precision float with flag (g30v5).

    5 bytes: 1 byte quality flags + 4 byte float.

    Attributes:
        quality: Quality flags.
        value: Single-precision floating-point value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 5
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: AnalogQuality
    value: float

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<f", self.value)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputFloat":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Analog input float requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<f", data[1:5])
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & AnalogQuality.ONLINE)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputDouble(StaticObject):
    """Analog Input double-precision float with flag (g30v6).

    9 bytes: 1 byte quality flags + 8 byte double.

    Attributes:
        quality: Quality flags.
        value: Double-precision floating-point value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_STATIC_GROUP
    VARIATION: ClassVar[int] = 6
    SIZE: ClassVar[int] = SIZE_9_BYTES

    quality: AnalogQuality
    value: float

    def to_bytes(self) -> bytes:
        """Serialize to 9 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<d", self.value)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputDouble":
        """Parse from 9 bytes."""
        if len(data) < SIZE_9_BYTES:
            msg = f"Analog input double requires {SIZE_9_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<d", data[1:9])
        return cls(quality=quality, value=value)

    @property
    def is_online(self) -> bool:
        """Check if point is online."""
        return bool(self.quality & AnalogQuality.ONLINE)


# Event objects


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEvent32(EventObject):
    """Analog Input Event 32-bit without time (g32v1).

    5 bytes: 1 byte quality flags + 4 byte signed value.

    Attributes:
        quality: Quality flags.
        value: 32-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: AnalogQuality
    value: int

    MIN_VALUE: ClassVar[int] = -(2**31)
    MAX_VALUE: ClassVar[int] = 2**31 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEvent32":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Analog input event 32-bit requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:5], "little", signed=True)
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEvent16(EventObject):
    """Analog Input Event 16-bit without time (g32v2).

    3 bytes: 1 byte quality flags + 2 byte signed value.

    Attributes:
        quality: Quality flags.
        value: 16-bit signed analog value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = SIZE_3_BYTES

    quality: AnalogQuality
    value: int

    MIN_VALUE: ClassVar[int] = -(2**15)
    MAX_VALUE: ClassVar[int] = 2**15 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 3 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little", signed=True)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEvent16":
        """Parse from 3 bytes."""
        if len(data) < SIZE_3_BYTES:
            msg = f"Analog input event 16-bit requires {SIZE_3_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:3], "little", signed=True)
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEvent32Time(EventObject):
    """Analog Input Event 32-bit with time (g32v3).

    11 bytes: 1 byte flags + 4 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 32-bit signed analog value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 3
    SIZE: ClassVar[int] = SIZE_11_BYTES

    quality: AnalogQuality
    value: int
    timestamp: DNP3Timestamp

    MIN_VALUE: ClassVar[int] = -(2**31)
    MAX_VALUE: ClassVar[int] = 2**31 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 11 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(4, "little", signed=True) + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEvent32Time":
        """Parse from 11 bytes."""
        if len(data) < SIZE_11_BYTES:
            msg = f"Analog input event 32-bit with time requires {SIZE_11_BYTES} bytes"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:5], "little", signed=True)
        timestamp = DNP3Timestamp.from_bytes(data[5:11])
        return cls(quality=quality, value=value, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEvent16Time(EventObject):
    """Analog Input Event 16-bit with time (g32v4).

    9 bytes: 1 byte flags + 2 byte value + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: 16-bit signed analog value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 4
    SIZE: ClassVar[int] = SIZE_9_BYTES

    quality: AnalogQuality
    value: int
    timestamp: DNP3Timestamp

    MIN_VALUE: ClassVar[int] = -(2**15)
    MAX_VALUE: ClassVar[int] = 2**15 - 1

    def __post_init__(self) -> None:
        """Validate value range."""
        if not self.MIN_VALUE <= self.value <= self.MAX_VALUE:
            msg = f"Value {self.value} out of range ({self.MIN_VALUE} to {self.MAX_VALUE})"
            raise ValueError(msg)

    def to_bytes(self) -> bytes:
        """Serialize to 9 bytes."""
        return bytes([int(self.quality)]) + self.value.to_bytes(2, "little", signed=True) + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEvent16Time":
        """Parse from 9 bytes."""
        if len(data) < SIZE_9_BYTES:
            msg = f"Analog input event 16-bit with time requires {SIZE_9_BYTES} bytes"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        value = int.from_bytes(data[1:3], "little", signed=True)
        timestamp = DNP3Timestamp.from_bytes(data[3:9])
        return cls(quality=quality, value=value, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEventFloat(EventObject):
    """Analog Input Event single-precision float without time (g32v5).

    5 bytes: 1 byte quality flags + 4 byte float.

    Attributes:
        quality: Quality flags.
        value: Single-precision floating-point value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 5
    SIZE: ClassVar[int] = SIZE_5_BYTES

    quality: AnalogQuality
    value: float

    def to_bytes(self) -> bytes:
        """Serialize to 5 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<f", self.value)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEventFloat":
        """Parse from 5 bytes."""
        if len(data) < SIZE_5_BYTES:
            msg = f"Analog input event float requires {SIZE_5_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<f", data[1:5])
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEventDouble(EventObject):
    """Analog Input Event double-precision float without time (g32v6).

    9 bytes: 1 byte quality flags + 8 byte double.

    Attributes:
        quality: Quality flags.
        value: Double-precision floating-point value.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 6
    SIZE: ClassVar[int] = SIZE_9_BYTES

    quality: AnalogQuality
    value: float

    def to_bytes(self) -> bytes:
        """Serialize to 9 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<d", self.value)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEventDouble":
        """Parse from 9 bytes."""
        if len(data) < SIZE_9_BYTES:
            msg = f"Analog input event double requires {SIZE_9_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<d", data[1:9])
        return cls(quality=quality, value=value)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEventFloatTime(EventObject):
    """Analog Input Event single-precision float with time (g32v7).

    11 bytes: 1 byte flags + 4 byte float + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: Single-precision floating-point value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 7
    SIZE: ClassVar[int] = SIZE_11_BYTES

    quality: AnalogQuality
    value: float
    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 11 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<f", self.value) + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEventFloatTime":
        """Parse from 11 bytes."""
        if len(data) < SIZE_11_BYTES:
            msg = f"Analog input event float with time requires {SIZE_11_BYTES} bytes"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<f", data[1:5])
        timestamp = DNP3Timestamp.from_bytes(data[5:11])
        return cls(quality=quality, value=value, timestamp=timestamp)


@register
@dataclass(frozen=True, slots=True)
class AnalogInputEventDoubleTime(EventObject):
    """Analog Input Event double-precision float with time (g32v8).

    15 bytes: 1 byte flags + 8 byte double + 6 byte timestamp.

    Attributes:
        quality: Quality flags.
        value: Double-precision floating-point value.
        timestamp: Time when event occurred.
    """

    GROUP: ClassVar[int] = ANALOG_INPUT_EVENT_GROUP
    VARIATION: ClassVar[int] = 8
    SIZE: ClassVar[int] = SIZE_15_BYTES

    quality: AnalogQuality
    value: float
    timestamp: DNP3Timestamp

    def to_bytes(self) -> bytes:
        """Serialize to 15 bytes."""
        return bytes([int(self.quality)]) + struct.pack("<d", self.value) + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes) -> "AnalogInputEventDoubleTime":
        """Parse from 15 bytes."""
        if len(data) < SIZE_15_BYTES:
            msg = f"Analog input event double with time requires {SIZE_15_BYTES} bytes"
            raise ValueError(msg)
        quality = AnalogQuality(data[0])
        (value,) = struct.unpack("<d", data[1:9])
        timestamp = DNP3Timestamp.from_bytes(data[9:15])
        return cls(quality=quality, value=value, timestamp=timestamp)
