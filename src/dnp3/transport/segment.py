"""Transport Layer segments per IEEE 1815-2012 Clause 8.

Transport header byte layout:
- Bit 7: FIR (first segment of fragment)
- Bit 6: FIN (final segment of fragment)
- Bits 5-0: SEQ (sequence number, 0-63)

Maximum segment payload is 249 bytes (data link user data - 1 byte header).
"""

from dataclasses import dataclass

# Bit positions and masks
_FIR_BIT = 0x80
_FIN_BIT = 0x40
_SEQ_MASK = 0x3F

# Transport layer constants
MAX_SEQUENCE = 63
MAX_PAYLOAD_SIZE = 249  # Data link user data (250) - transport header (1)
HEADER_SIZE = 1


def _next_sequence(seq: int) -> int:
    """Calculate next sequence number (wraps at 64).

    Args:
        seq: Current sequence number (0-63).

    Returns:
        Next sequence number.
    """
    return (seq + 1) & _SEQ_MASK


@dataclass(frozen=True, slots=True)
class TransportHeader:
    """Transport layer header.

    Attributes:
        fir: First segment flag (True if first segment of fragment).
        fin: Final segment flag (True if last segment of fragment).
        seq: Sequence number (0-63).
    """

    fir: bool
    fin: bool
    seq: int

    def __post_init__(self) -> None:
        """Validate sequence number range."""
        if not 0 <= self.seq <= MAX_SEQUENCE:
            msg = f"Sequence number {self.seq} out of range (0-{MAX_SEQUENCE})"
            raise ValueError(msg)

    def to_byte(self) -> int:
        """Serialize to single byte.

        Returns:
            8-bit transport header value.
        """
        value = self.seq & _SEQ_MASK
        if self.fir:
            value |= _FIR_BIT
        if self.fin:
            value |= _FIN_BIT
        return value

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            1-byte transport header.
        """
        return bytes([self.to_byte()])

    @classmethod
    def from_byte(cls, value: int) -> "TransportHeader":
        """Parse from single byte.

        Args:
            value: 8-bit transport header value.

        Returns:
            TransportHeader instance.
        """
        return cls(
            fir=bool(value & _FIR_BIT),
            fin=bool(value & _FIN_BIT),
            seq=value & _SEQ_MASK,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "TransportHeader":
        """Parse from bytes.

        Args:
            data: At least 1 byte of data.

        Returns:
            TransportHeader instance.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            msg = "Cannot parse transport header from empty data"
            raise ValueError(msg)
        return cls.from_byte(data[0])

    @property
    def is_first(self) -> bool:
        """Check if this is the first segment of a fragment."""
        return self.fir

    @property
    def is_final(self) -> bool:
        """Check if this is the final segment of a fragment."""
        return self.fin

    @property
    def is_only(self) -> bool:
        """Check if this is the only segment (FIR and FIN both set)."""
        return self.fir and self.fin


@dataclass(frozen=True, slots=True)
class TransportSegment:
    """Transport layer segment.

    A segment consists of a transport header and payload data.
    Maximum payload size is 249 bytes.

    Attributes:
        header: Transport header.
        payload: Segment payload data.
    """

    header: TransportHeader
    payload: bytes

    def __post_init__(self) -> None:
        """Validate payload size."""
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            msg = f"Payload size {len(self.payload)} exceeds maximum {MAX_PAYLOAD_SIZE}"
            raise ValueError(msg)

    @classmethod
    def build(
        cls,
        fir: bool,
        fin: bool,
        seq: int,
        payload: bytes,
    ) -> "TransportSegment":
        """Build a segment from components.

        Args:
            fir: First segment flag.
            fin: Final segment flag.
            seq: Sequence number (0-63).
            payload: Segment payload.

        Returns:
            TransportSegment instance.
        """
        header = TransportHeader(fir=fir, fin=fin, seq=seq)
        return cls(header=header, payload=payload)

    def to_bytes(self) -> bytes:
        """Serialize segment to bytes.

        Returns:
            Header byte followed by payload.
        """
        return self.header.to_bytes() + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "TransportSegment":
        """Parse segment from bytes.

        Args:
            data: At least 1 byte (header + optional payload).

        Returns:
            TransportSegment instance.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            msg = "Cannot parse transport segment from empty data"
            raise ValueError(msg)
        header = TransportHeader.from_byte(data[0])
        payload = data[1:]
        return cls(header=header, payload=payload)

    @property
    def is_first(self) -> bool:
        """Check if this is the first segment of a fragment."""
        return self.header.is_first

    @property
    def is_final(self) -> bool:
        """Check if this is the final segment of a fragment."""
        return self.header.is_final

    @property
    def is_only(self) -> bool:
        """Check if this is the only segment."""
        return self.header.is_only

    @property
    def sequence(self) -> int:
        """Get segment sequence number."""
        return self.header.seq
