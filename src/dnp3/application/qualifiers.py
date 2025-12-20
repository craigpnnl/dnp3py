"""Object headers and qualifiers per IEEE 1815-2012 Clause 4.2.

Object header structure:
- Group (1 byte): Object group number
- Variation (1 byte): Object variation number
- Qualifier (1 byte): Specifies range/index format

Qualifier code layout (3-bit prefix + 4-bit range specifier):
- Bits 7: Reserved
- Bits 6-4: Prefix code (0=none, 1=1-byte index, 2=2-byte index, etc.)
- Bits 3-0: Range specifier code
"""

from dataclasses import dataclass
from enum import IntEnum

# Prefix codes (bits 6-4 of qualifier byte)
PREFIX_NONE = 0x00
PREFIX_1_BYTE_INDEX = 0x10
PREFIX_2_BYTE_INDEX = 0x20
PREFIX_4_BYTE_INDEX = 0x30
PREFIX_1_BYTE_SIZE = 0x40
PREFIX_2_BYTE_SIZE = 0x50
PREFIX_4_BYTE_SIZE = 0x60

# Masks for qualifier byte
PREFIX_MASK = 0x70
RANGE_MASK = 0x0F

# Object header constants
OBJECT_HEADER_SIZE = 3
MAX_BYTE_VALUE = 255

# Range data sizes (for parsing)
RANGE_SIZE_1_BYTE = 1
RANGE_SIZE_2_BYTES = 2
RANGE_SIZE_4_BYTES = 4
RANGE_SIZE_8_BYTES = 8


class PrefixCode(IntEnum):
    """Object prefix codes (Table 4-3).

    Defines how each object in the range is prefixed.
    """

    NONE = 0
    UINT8_INDEX = 1
    UINT16_INDEX = 2
    UINT32_INDEX = 3
    UINT8_SIZE = 4
    UINT16_SIZE = 5
    UINT32_SIZE = 6


class RangeCode(IntEnum):
    """Range specifier codes (Table 4-2).

    Defines how the range of objects is specified.
    """

    # Start-stop range (indices)
    UINT8_START_STOP = 0x00
    UINT16_START_STOP = 0x01
    UINT32_START_STOP = 0x02

    # Reserved
    RESERVED_3 = 0x03
    RESERVED_4 = 0x04
    RESERVED_5 = 0x05

    # All objects (no range data)
    ALL_OBJECTS = 0x06

    # Count (quantity)
    UINT8_COUNT = 0x07
    UINT16_COUNT = 0x08
    UINT32_COUNT = 0x09

    # Reserved
    RESERVED_A = 0x0A

    # Virtual address
    VIRTUAL_ADDRESS = 0x0B

    # Free format with count
    FREE_FORMAT = 0x0B


def _encode_qualifier(prefix: PrefixCode, range_code: RangeCode) -> int:
    """Encode qualifier byte from prefix and range codes.

    Args:
        prefix: Object prefix code.
        range_code: Range specifier code.

    Returns:
        Qualifier byte value.
    """
    return (prefix.value << 4) | range_code.value


def _decode_qualifier(qualifier: int) -> tuple[PrefixCode, RangeCode]:
    """Decode qualifier byte into prefix and range codes.

    Args:
        qualifier: Qualifier byte value.

    Returns:
        Tuple of (PrefixCode, RangeCode).
    """
    prefix = PrefixCode((qualifier >> 4) & 0x07)
    range_code = RangeCode(qualifier & 0x0F)
    return prefix, range_code


@dataclass(frozen=True, slots=True)
class ObjectHeader:
    """Object header identifying group, variation, and qualifier.

    Attributes:
        group: Object group number (1 byte).
        variation: Object variation number (1 byte).
        qualifier: Qualifier code (1 byte).
    """

    group: int
    variation: int
    qualifier: int

    def __post_init__(self) -> None:
        """Validate field ranges."""
        if not 0 <= self.group <= MAX_BYTE_VALUE:
            msg = f"Group {self.group} out of range (0-{MAX_BYTE_VALUE})"
            raise ValueError(msg)
        if not 0 <= self.variation <= MAX_BYTE_VALUE:
            msg = f"Variation {self.variation} out of range (0-{MAX_BYTE_VALUE})"
            raise ValueError(msg)
        if not 0 <= self.qualifier <= MAX_BYTE_VALUE:
            msg = f"Qualifier {self.qualifier} out of range (0-{MAX_BYTE_VALUE})"
            raise ValueError(msg)

    @classmethod
    def build(
        cls,
        group: int,
        variation: int,
        prefix: PrefixCode = PrefixCode.NONE,
        range_code: RangeCode = RangeCode.UINT8_START_STOP,
    ) -> "ObjectHeader":
        """Build an object header from components.

        Args:
            group: Object group number.
            variation: Object variation number.
            prefix: Object prefix code.
            range_code: Range specifier code.

        Returns:
            ObjectHeader instance.
        """
        qualifier = _encode_qualifier(prefix, range_code)
        return cls(group=group, variation=variation, qualifier=qualifier)

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            3-byte object header.
        """
        return bytes([self.group, self.variation, self.qualifier])

    @classmethod
    def from_bytes(cls, data: bytes) -> "ObjectHeader":
        """Parse from bytes.

        Args:
            data: At least 3 bytes.

        Returns:
            ObjectHeader instance.

        Raises:
            ValueError: If data is too short.
        """
        if len(data) < OBJECT_HEADER_SIZE:
            msg = f"Object header requires {OBJECT_HEADER_SIZE} bytes, got {len(data)}"
            raise ValueError(msg)
        return cls(group=data[0], variation=data[1], qualifier=data[2])

    @property
    def prefix_code(self) -> PrefixCode:
        """Get the prefix code from qualifier."""
        return PrefixCode((self.qualifier >> 4) & 0x07)

    @property
    def range_code(self) -> RangeCode:
        """Get the range code from qualifier."""
        return RangeCode(self.qualifier & 0x0F)

    @property
    def has_prefix(self) -> bool:
        """Check if objects have a prefix."""
        return self.prefix_code != PrefixCode.NONE


@dataclass(frozen=True, slots=True)
class StartStopRange:
    """Start-stop range specifier.

    Attributes:
        start: Start index.
        stop: Stop index (inclusive).
    """

    start: int
    stop: int

    @property
    def count(self) -> int:
        """Number of objects in range."""
        return self.stop - self.start + 1

    def to_bytes_1(self) -> bytes:
        """Serialize as 1-byte start/stop.

        Returns:
            2 bytes (start, stop).
        """
        return bytes([self.start & 0xFF, self.stop & 0xFF])

    def to_bytes_2(self) -> bytes:
        """Serialize as 2-byte start/stop.

        Returns:
            4 bytes (start_lo, start_hi, stop_lo, stop_hi).
        """
        return self.start.to_bytes(2, byteorder="little") + self.stop.to_bytes(2, byteorder="little")

    def to_bytes_4(self) -> bytes:
        """Serialize as 4-byte start/stop.

        Returns:
            8 bytes.
        """
        return self.start.to_bytes(4, byteorder="little") + self.stop.to_bytes(4, byteorder="little")

    @classmethod
    def from_bytes_1(cls, data: bytes) -> "StartStopRange":
        """Parse from 1-byte start/stop.

        Args:
            data: At least 2 bytes.

        Returns:
            StartStopRange instance.
        """
        if len(data) < RANGE_SIZE_2_BYTES:
            msg = f"1-byte start/stop requires {RANGE_SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        return cls(start=data[0], stop=data[1])

    @classmethod
    def from_bytes_2(cls, data: bytes) -> "StartStopRange":
        """Parse from 2-byte start/stop.

        Args:
            data: At least 4 bytes.

        Returns:
            StartStopRange instance.
        """
        if len(data) < RANGE_SIZE_4_BYTES:
            msg = f"2-byte start/stop requires {RANGE_SIZE_4_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        start = int.from_bytes(data[0:2], byteorder="little")
        stop = int.from_bytes(data[2:4], byteorder="little")
        return cls(start=start, stop=stop)

    @classmethod
    def from_bytes_4(cls, data: bytes) -> "StartStopRange":
        """Parse from 4-byte start/stop.

        Args:
            data: At least 8 bytes.

        Returns:
            StartStopRange instance.
        """
        if len(data) < RANGE_SIZE_8_BYTES:
            msg = f"4-byte start/stop requires {RANGE_SIZE_8_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        start = int.from_bytes(data[0:4], byteorder="little")
        stop = int.from_bytes(data[4:8], byteorder="little")
        return cls(start=start, stop=stop)


@dataclass(frozen=True, slots=True)
class CountRange:
    """Count range specifier.

    Attributes:
        count: Number of objects.
    """

    count: int

    def to_bytes_1(self) -> bytes:
        """Serialize as 1-byte count."""
        return bytes([self.count & 0xFF])

    def to_bytes_2(self) -> bytes:
        """Serialize as 2-byte count."""
        return self.count.to_bytes(2, byteorder="little")

    def to_bytes_4(self) -> bytes:
        """Serialize as 4-byte count."""
        return self.count.to_bytes(4, byteorder="little")

    @classmethod
    def from_bytes_1(cls, data: bytes) -> "CountRange":
        """Parse from 1-byte count."""
        if len(data) < RANGE_SIZE_1_BYTE:
            msg = f"1-byte count requires {RANGE_SIZE_1_BYTE} byte"
            raise ValueError(msg)
        return cls(count=data[0])

    @classmethod
    def from_bytes_2(cls, data: bytes) -> "CountRange":
        """Parse from 2-byte count."""
        if len(data) < RANGE_SIZE_2_BYTES:
            msg = f"2-byte count requires {RANGE_SIZE_2_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        return cls(count=int.from_bytes(data[0:2], byteorder="little"))

    @classmethod
    def from_bytes_4(cls, data: bytes) -> "CountRange":
        """Parse from 4-byte count."""
        if len(data) < RANGE_SIZE_4_BYTES:
            msg = f"4-byte count requires {RANGE_SIZE_4_BYTES} bytes, got {len(data)}"
            raise ValueError(msg)
        return cls(count=int.from_bytes(data[0:4], byteorder="little"))


def get_range_size(range_code: RangeCode) -> int:
    """Get the size of range data in bytes for a range code.

    Args:
        range_code: Range specifier code.

    Returns:
        Size of range data in bytes.
    """
    sizes = {
        RangeCode.UINT8_START_STOP: 2,
        RangeCode.UINT16_START_STOP: 4,
        RangeCode.UINT32_START_STOP: 8,
        RangeCode.ALL_OBJECTS: 0,
        RangeCode.UINT8_COUNT: 1,
        RangeCode.UINT16_COUNT: 2,
        RangeCode.UINT32_COUNT: 4,
    }
    return sizes.get(range_code, 0)


def get_prefix_size(prefix_code: PrefixCode) -> int:
    """Get the size of prefix data in bytes for a prefix code.

    Args:
        prefix_code: Object prefix code.

    Returns:
        Size of prefix data in bytes per object.
    """
    sizes = {
        PrefixCode.NONE: 0,
        PrefixCode.UINT8_INDEX: 1,
        PrefixCode.UINT16_INDEX: 2,
        PrefixCode.UINT32_INDEX: 4,
        PrefixCode.UINT8_SIZE: 1,
        PrefixCode.UINT16_SIZE: 2,
        PrefixCode.UINT32_SIZE: 4,
    }
    return sizes.get(prefix_code, 0)
