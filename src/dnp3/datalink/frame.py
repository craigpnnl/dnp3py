"""Data Link Frame format per IEEE 1815-2012 Clause 9.

Frame structure:
- Start bytes: 0x05 0x64 (2 bytes)
- Length: 1 byte (user data length + 5)
- Control: 1 byte
- Destination: 2 bytes (little-endian)
- Source: 2 bytes (little-endian)
- Header CRC: 2 bytes
- Data blocks: 16 bytes each with 2-byte CRC (last block may be shorter)
"""

from collections.abc import Iterator
from dataclasses import dataclass

from dnp3.core.crc import append_crc, compute_crc
from dnp3.datalink.control import ControlByte

# Frame constants
START_BYTES = b"\x05\x64"
HEADER_SIZE = 10  # Start(2) + Length(1) + Control(1) + Dest(2) + Source(2) + CRC(2)
HEADER_SIZE_NO_CRC = 8
DATA_BLOCK_SIZE = 16
MAX_USER_DATA_LENGTH = 250
LENGTH_FIELD_OVERHEAD = 5  # Length field = user_data_length + 5


def _split_into_blocks(data: bytes) -> Iterator[bytes]:
    """Split data into blocks of DATA_BLOCK_SIZE."""
    for i in range(0, len(data), DATA_BLOCK_SIZE):
        yield data[i : i + DATA_BLOCK_SIZE]


@dataclass(frozen=True, slots=True)
class DataLinkHeader:
    """Data link frame header (without CRC).

    Attributes:
        length: Length field (user data length + 5)
        control: Control byte
        destination: Destination address (16-bit)
        source: Source address (16-bit)
    """

    length: int
    control: ControlByte
    destination: int
    source: int

    @property
    def user_data_length(self) -> int:
        """Calculate user data length from length field."""
        return self.length - LENGTH_FIELD_OVERHEAD

    def to_bytes_without_crc(self) -> bytes:
        """Serialize header without CRC.

        Returns:
            8-byte header (start + length + control + dest + source).
        """
        return (
            START_BYTES
            + bytes([self.length])
            + bytes([self.control.to_int()])
            + self.destination.to_bytes(2, byteorder="little")
            + self.source.to_bytes(2, byteorder="little")
        )

    def to_bytes(self) -> bytes:
        """Serialize header with CRC.

        Returns:
            10-byte header including CRC.
        """
        return append_crc(self.to_bytes_without_crc())

    @classmethod
    def from_bytes(cls, data: bytes) -> "DataLinkHeader":
        """Parse header from bytes (without CRC).

        Args:
            data: 8-byte header data.

        Returns:
            DataLinkHeader instance.
        """
        return cls(
            length=data[2],
            control=ControlByte.from_int(data[3]),
            destination=int.from_bytes(data[4:6], byteorder="little"),
            source=int.from_bytes(data[6:8], byteorder="little"),
        )


@dataclass(frozen=True, slots=True)
class DataLinkFrame:
    """Complete data link frame.

    Attributes:
        header: Frame header
        user_data: User data payload (0-250 bytes)
    """

    header: DataLinkHeader
    user_data: bytes

    @classmethod
    def build(
        cls,
        destination: int,
        source: int,
        control: ControlByte,
        user_data: bytes,
    ) -> "DataLinkFrame":
        """Build a frame from components.

        Args:
            destination: Destination address
            source: Source address
            control: Control byte
            user_data: User data payload

        Returns:
            DataLinkFrame instance.

        Raises:
            ValueError: If user data exceeds maximum length.
        """
        if len(user_data) > MAX_USER_DATA_LENGTH:
            msg = f"User data length {len(user_data)} exceeds maximum {MAX_USER_DATA_LENGTH}"
            raise ValueError(msg)

        header = DataLinkHeader(
            length=len(user_data) + LENGTH_FIELD_OVERHEAD,
            control=control,
            destination=destination,
            source=source,
        )
        return cls(header=header, user_data=user_data)

    def to_bytes(self) -> bytes:
        """Serialize frame to bytes with CRCs.

        Returns:
            Complete frame bytes including header CRC and data block CRCs.
        """
        result = bytearray(self.header.to_bytes())

        # Add data blocks with CRCs
        for block in _split_into_blocks(self.user_data):
            result.extend(append_crc(block))

        return bytes(result)

    @classmethod
    def from_bytes(cls, data: bytes) -> "DataLinkFrame":
        """Parse frame from bytes.

        Args:
            data: Complete frame bytes including CRCs.

        Returns:
            DataLinkFrame instance.

        Raises:
            ValueError: If CRC validation fails or frame is malformed.
        """
        # Verify and parse header
        header_data = data[:HEADER_SIZE_NO_CRC]
        header_crc = int.from_bytes(data[8:10], byteorder="little")
        if compute_crc(header_data) != header_crc:
            msg = "Header CRC validation failed"
            raise ValueError(msg)

        header = DataLinkHeader.from_bytes(header_data)

        # Extract and verify data blocks
        user_data = bytearray()
        remaining = header.user_data_length
        pos = HEADER_SIZE

        while remaining > 0:
            block_size = min(remaining, DATA_BLOCK_SIZE)
            block_end = pos + block_size + 2  # Include CRC

            block_data = data[pos : pos + block_size]
            block_crc = int.from_bytes(data[pos + block_size : block_end], byteorder="little")

            if compute_crc(block_data) != block_crc:
                msg = "Data block CRC validation failed"
                raise ValueError(msg)

            user_data.extend(block_data)
            remaining -= block_size
            pos = block_end

        return cls(header=header, user_data=bytes(user_data))
