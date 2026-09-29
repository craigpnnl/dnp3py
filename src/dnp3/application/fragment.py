"""Application layer fragment handling per IEEE 1815-2012.

A fragment (APDU - Application Protocol Data Unit) contains:
- Application header (request or response)
- Zero or more object headers with associated data

Maximum fragment size is typically 2048 bytes for Level 2 devices.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from dnp3.application.header import (
    REQUEST_HEADER_SIZE,
    RESPONSE_HEADER_SIZE,
    RequestHeader,
    ResponseHeader,
)
from dnp3.application.qualifiers import OBJECT_HEADER_SIZE, ObjectHeader

if TYPE_CHECKING:
    from collections.abc import Sequence

# Fragment size limits (IEEE 1815-2012)
MIN_FRAGMENT_SIZE = 249  # Minimum supported fragment size
DEFAULT_MAX_FRAGMENT_SIZE = 2048  # Default maximum fragment size
MAX_FRAGMENT_SIZE = 65535  # Absolute maximum (transport layer limit)


@dataclass(frozen=True, slots=True)
class ObjectBlock:
    """A block of objects with a common header.

    Attributes:
        header: Object header describing the objects.
        data: Raw object data (may be empty for requests like READ).
    """

    header: ObjectHeader
    data: bytes = b""

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            Object header followed by data.
        """
        return self.header.to_bytes() + self.data

    @property
    def size(self) -> int:
        """Total size in bytes."""
        return OBJECT_HEADER_SIZE + len(self.data)


class TruncationReason(Enum):
    """Why object parsing stopped before the end of the object data."""

    # Gaps in this library: the frame may be valid, but this library cannot size it.
    UNKNOWN_WIDTH = "unknown_width"  # no layout row and no usable registered size
    # Range codes 3 to 5 (virtual addresses) and 0xB (variable format, valid as 0x4B, 0x5B and 0x6B).
    UNSUPPORTED_RANGE = "unsupported_range"

    # Invalid frames (IEEE 1815-2012 Tables 4-4 to 4-6).
    SIZE_PREFIX = "size_prefix"  # prefix codes 4 to 6 with a start-stop, all-objects or count range
    RESERVED_QUALIFIER = "reserved_qualifier"  # the Res bit, prefix code 7, range code 0xA or 0xC to 0xF,
    # or an index prefix (1 to 3) with a range that is not a count range
    PACKED_WITH_INDEX_PREFIX = "packed_with_index_prefix"  # A.2.1 packs only over a contiguous range
    RANGE_NAMES_NO_OBJECT = "range_names_no_object"  # start-stop range with stop below start
    DATA_SHORTER_THAN_DECLARED = "data_shorter_than_declared"  # range field or object data past the end
    TRAILING_OCTETS = "trailing_octets"  # 1 or 2 octets left, too few for an object header


@dataclass(frozen=True, slots=True)
class Truncation:
    """Where and why object parsing stopped.

    The stopping block is not among the parsed blocks; the blocks before it are.
    An over-declared count whose data still fits inside the fragment frames as a
    valid block and cannot be detected (IEEE 1815-2012 4.2.2.7: object headers
    carry no length).

    Attributes:
        reason: Why parsing stopped.
        offset: Index of the stopping block's first octet within the object data,
            which starts after the request or response header.
        group: The stopping block's group, or None for TRAILING_OCTETS.
        variation: The stopping block's variation, or None for TRAILING_OCTETS.
        qualifier: The stopping block's qualifier, or None for TRAILING_OCTETS.
    """

    reason: TruncationReason
    offset: int
    group: int | None = None
    variation: int | None = None
    qualifier: int | None = None


@dataclass(frozen=True, slots=True)
class RequestFragment:
    """Application layer request fragment.

    Attributes:
        header: Request header (2 bytes).
        objects: List of object blocks.
        truncation: Set when parsing stopped before the end of the object data.
            ``to_bytes()`` then does not reproduce the parsed input.
    """

    header: RequestHeader
    objects: "Sequence[ObjectBlock]" = field(default_factory=tuple)
    truncation: Truncation | None = None

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            Complete fragment as bytes.
        """
        result = self.header.to_bytes()
        for obj in self.objects:
            result += obj.to_bytes()
        return result

    @property
    def size(self) -> int:
        """Total size in bytes."""
        return REQUEST_HEADER_SIZE + sum(obj.size for obj in self.objects)

    @property
    def is_first(self) -> bool:
        """Check if this is the first fragment."""
        return self.header.control.fir

    @property
    def is_final(self) -> bool:
        """Check if this is the final fragment."""
        return self.header.control.fin

    @property
    def is_only(self) -> bool:
        """Check if this is the only fragment."""
        return self.header.control.is_only

    @property
    def sequence(self) -> int:
        """Get the sequence number."""
        return self.header.control.seq


@dataclass(frozen=True, slots=True)
class ResponseFragment:
    """Application layer response fragment.

    Attributes:
        header: Response header (4 bytes).
        objects: List of object blocks.
        truncation: Set when parsing stopped before the end of the object data.
            ``to_bytes()`` then does not reproduce the parsed input.
    """

    header: ResponseHeader
    objects: "Sequence[ObjectBlock]" = field(default_factory=tuple)
    truncation: Truncation | None = None

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            Complete fragment as bytes.
        """
        result = self.header.to_bytes()
        for obj in self.objects:
            result += obj.to_bytes()
        return result

    @property
    def size(self) -> int:
        """Total size in bytes."""
        return RESPONSE_HEADER_SIZE + sum(obj.size for obj in self.objects)

    @property
    def is_first(self) -> bool:
        """Check if this is the first fragment."""
        return self.header.control.fir

    @property
    def is_final(self) -> bool:
        """Check if this is the final fragment."""
        return self.header.control.fin

    @property
    def is_only(self) -> bool:
        """Check if this is the only fragment."""
        return self.header.control.is_only

    @property
    def sequence(self) -> int:
        """Get the sequence number."""
        return self.header.control.seq

    @property
    def is_unsolicited(self) -> bool:
        """Check if this is an unsolicited response."""
        return self.header.control.uns


def fragment_fits(current_size: int, addition_size: int, max_size: int) -> bool:
    """Check if adding data would exceed fragment size limit.

    Args:
        current_size: Current fragment size in bytes.
        addition_size: Size of data to add in bytes.
        max_size: Maximum fragment size.

    Returns:
        True if the addition fits, False otherwise.
    """
    return current_size + addition_size <= max_size


def calculate_available_space(
    header_size: int,
    objects: "Sequence[ObjectBlock]",
    max_size: int,
) -> int:
    """Calculate available space for more objects.

    Args:
        header_size: Size of the application header.
        objects: Existing object blocks.
        max_size: Maximum fragment size.

    Returns:
        Available bytes for additional data.
    """
    used = header_size + sum(obj.size for obj in objects)
    return max(0, max_size - used)
