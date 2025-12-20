"""Stateful byte stream parser for data link frames.

The parser handles:
- Hunting for start bytes (0x05 0x64)
- Buffering partial frames
- CRC validation
- Recovery from corrupted frames
"""

from collections.abc import Iterator
from enum import Enum, auto

from dnp3.core.crc import compute_crc
from dnp3.datalink.frame import (
    DATA_BLOCK_SIZE,
    HEADER_SIZE,
    HEADER_SIZE_NO_CRC,
    DataLinkFrame,
    DataLinkHeader,
)

# Start byte values (0x05 0x64)
_START_BYTE_0 = 0x05
_START_BYTE_1 = 0x64


class _ParserState(Enum):
    """Internal parser state."""

    HUNTING = auto()  # Looking for start bytes
    HEADER = auto()  # Collecting header bytes
    DATA = auto()  # Collecting data blocks


def _calculate_frame_size(user_data_length: int) -> int:
    """Calculate total frame size including all CRCs.

    Args:
        user_data_length: Number of user data bytes.

    Returns:
        Total frame size in bytes.
    """
    if user_data_length == 0:
        return HEADER_SIZE

    # Calculate number of full blocks and remaining bytes
    full_blocks = user_data_length // DATA_BLOCK_SIZE
    remainder = user_data_length % DATA_BLOCK_SIZE

    # Each block has 2-byte CRC
    data_size = full_blocks * (DATA_BLOCK_SIZE + 2)
    if remainder > 0:
        data_size += remainder + 2

    return HEADER_SIZE + data_size


def _find_start_bytes(data: bytes | bytearray, start: int = 0) -> int:
    """Find position of start bytes in data.

    Args:
        data: Byte buffer to search.
        start: Starting position.

    Returns:
        Position of start bytes, or -1 if not found.
    """
    pos = start
    while pos <= len(data) - 2:
        if data[pos] == _START_BYTE_0 and data[pos + 1] == _START_BYTE_1:
            return pos
        pos += 1
    return -1


def _validate_header_crc(header_bytes: bytes) -> bool:
    """Validate header CRC.

    Args:
        header_bytes: 10-byte header including CRC.

    Returns:
        True if CRC is valid.
    """
    data = header_bytes[:HEADER_SIZE_NO_CRC]
    crc = int.from_bytes(header_bytes[8:10], byteorder="little")
    return compute_crc(data) == crc


def _validate_data_block_crc(block: bytes) -> bool:
    """Validate a data block's CRC.

    Args:
        block: Data block with 2-byte CRC appended.

    Returns:
        True if CRC is valid.
    """
    data = block[:-2]
    crc = int.from_bytes(block[-2:], byteorder="little")
    return compute_crc(data) == crc


def _extract_user_data(data: bytes, user_data_length: int) -> bytes | None:
    """Extract and validate user data from data blocks.

    Args:
        data: Raw data blocks with CRCs.
        user_data_length: Expected user data length.

    Returns:
        Extracted user data, or None if CRC validation fails.
    """
    if user_data_length == 0:
        return b""

    result = bytearray()
    remaining = user_data_length
    pos = 0

    while remaining > 0:
        block_size = min(remaining, DATA_BLOCK_SIZE)
        block_end = pos + block_size + 2  # Include CRC

        if block_end > len(data):
            return None

        block = data[pos:block_end]
        if not _validate_data_block_crc(block):
            return None

        result.extend(block[:-2])
        remaining -= block_size
        pos = block_end

    return bytes(result)


class FrameParser:
    """Stateful byte stream parser for data link frames.

    The parser maintains an internal buffer and yields complete frames
    as they become available. It handles:
    - Partial frames split across multiple feed() calls
    - Garbage bytes between frames
    - CRC validation with automatic recovery

    Example:
        parser = FrameParser()
        for chunk in stream:
            for frame in parser.feed(chunk):
                process(frame)
    """

    def __init__(self) -> None:
        """Initialize parser in hunting state."""
        self._buffer = bytearray()
        self._state = _ParserState.HUNTING

    @property
    def bytes_buffered(self) -> int:
        """Number of bytes currently buffered."""
        return len(self._buffer)

    def reset(self) -> None:
        """Reset parser to initial state, clearing buffer."""
        self._buffer.clear()
        self._state = _ParserState.HUNTING

    def feed(self, data: bytes) -> Iterator[DataLinkFrame]:
        """Feed bytes to the parser and yield complete frames.

        Args:
            data: Bytes to process.

        Returns:
            Iterator over complete DataLinkFrame instances.
        """
        self._buffer.extend(data)

        frames: list[DataLinkFrame] = []
        while True:
            frame = self._try_parse_frame()
            if frame is None:
                break
            frames.append(frame)
        return iter(frames)

    def _try_parse_frame(self) -> DataLinkFrame | None:
        """Try to parse a complete frame from the buffer.

        Returns:
            A DataLinkFrame if one is complete, None otherwise.
        """
        # Hunt for start bytes
        start_pos = _find_start_bytes(self._buffer)
        if start_pos == -1:
            # No start bytes found, keep last byte in case it's the first start byte
            if len(self._buffer) > 0 and self._buffer[-1] == _START_BYTE_0:
                self._buffer = bytearray([_START_BYTE_0])
            else:
                self._buffer.clear()
            return None

        # Discard bytes before start
        if start_pos > 0:
            del self._buffer[:start_pos]

        # Need at least header
        if len(self._buffer) < HEADER_SIZE:
            return None

        # Validate header CRC
        if not _validate_header_crc(bytes(self._buffer[:HEADER_SIZE])):
            # Bad CRC - skip first byte and hunt again
            del self._buffer[0]
            return self._try_parse_frame()

        # Parse header to get expected frame size
        header = DataLinkHeader.from_bytes(bytes(self._buffer[:HEADER_SIZE_NO_CRC]))
        frame_size = _calculate_frame_size(header.user_data_length)

        # Wait for complete frame
        if len(self._buffer) < frame_size:
            return None

        # Extract and validate data blocks
        data_start = HEADER_SIZE
        data_bytes = bytes(self._buffer[data_start:frame_size])
        user_data = _extract_user_data(data_bytes, header.user_data_length)

        if user_data is None:
            # Data block CRC failed - skip first byte and hunt again
            del self._buffer[0]
            return self._try_parse_frame()

        # Success - consume frame from buffer and return
        del self._buffer[:frame_size]
        return DataLinkFrame(header=header, user_data=user_data)
