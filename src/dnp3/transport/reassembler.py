"""Fragment reassembly from transport segments.

Reassembles transport segments into complete application layer fragments.
Handles sequence validation and out-of-order detection.
"""

from dataclasses import dataclass
from enum import Enum, auto

from dnp3.transport.segment import TransportSegment


class ReassemblyError(Exception):
    """Error during fragment reassembly."""


class ReassemblyState(Enum):
    """Current state of the reassembler."""

    IDLE = auto()  # Waiting for FIR segment
    ASSEMBLING = auto()  # Collecting segments


@dataclass(frozen=True, slots=True)
class ReassembledFragment:
    """A successfully reassembled fragment.

    Attributes:
        data: Complete fragment data.
        segment_count: Number of segments that made up the fragment.
    """

    data: bytes
    segment_count: int


def _next_expected_seq(current: int) -> int:
    """Calculate next expected sequence number.

    Args:
        current: Current sequence number.

    Returns:
        Next expected sequence (wraps at 64).
    """
    return (current + 1) & 0x3F


class Reassembler:
    """Stateful segment reassembler.

    Reassembles transport segments into application layer fragments.
    Validates sequence numbers and handles FIR/FIN flags.

    Example:
        reassembler = Reassembler()
        for segment in segments:
            result = reassembler.add(segment)
            if result is not None:
                process_fragment(result.data)
    """

    def __init__(self, max_fragment_size: int | None = None) -> None:
        """Initialize reassembler.

        Args:
            max_fragment_size: Optional maximum fragment size.
                If set, fragments larger than this will cause an error.
        """
        self._max_size = max_fragment_size
        self._buffer = bytearray()
        self._expected_seq: int | None = None
        self._segment_count = 0
        self._state = ReassemblyState.IDLE

    @property
    def state(self) -> ReassemblyState:
        """Current reassembler state."""
        return self._state

    @property
    def bytes_buffered(self) -> int:
        """Number of bytes currently buffered."""
        return len(self._buffer)

    @property
    def segments_buffered(self) -> int:
        """Number of segments received for current fragment."""
        return self._segment_count

    def reset(self) -> None:
        """Reset reassembler to initial state, discarding buffered data."""
        self._buffer.clear()
        self._expected_seq = None
        self._segment_count = 0
        self._state = ReassemblyState.IDLE

    def add(self, segment: TransportSegment) -> ReassembledFragment | None:
        """Add a segment to the reassembler.

        Args:
            segment: Transport segment to process.

        Returns:
            ReassembledFragment if a complete fragment is ready, None otherwise.

        Raises:
            ReassemblyError: If sequence error or other problem occurs.
        """
        if self._state == ReassemblyState.IDLE:
            return self._handle_idle(segment)
        return self._handle_assembling(segment)

    def _handle_idle(self, segment: TransportSegment) -> ReassembledFragment | None:
        """Handle segment when in IDLE state.

        Args:
            segment: Segment to process.

        Returns:
            ReassembledFragment if complete, None otherwise.
        """
        if not segment.is_first:
            # Ignore non-FIR segments when idle
            return None

        # Start new fragment
        self._buffer.clear()
        self._buffer.extend(segment.payload)
        self._segment_count = 1

        if segment.is_final:
            # Single segment fragment (FIR and FIN)
            return self._complete_fragment()

        # Multi-segment fragment starting
        self._expected_seq = _next_expected_seq(segment.sequence)
        self._state = ReassemblyState.ASSEMBLING
        return None

    def _handle_assembling(self, segment: TransportSegment) -> ReassembledFragment | None:
        """Handle segment when assembling a fragment.

        Args:
            segment: Segment to process.

        Returns:
            ReassembledFragment if complete, None otherwise.

        Raises:
            ReassemblyError: On sequence error.
        """
        if segment.is_first:
            # New fragment starting, abort current assembly
            self.reset()
            return self._handle_idle(segment)

        # Check sequence number
        if segment.sequence != self._expected_seq:
            msg = f"Sequence error: expected {self._expected_seq}, got {segment.sequence}"
            self.reset()
            raise ReassemblyError(msg)

        # Check size limit
        if self._max_size is not None and len(self._buffer) + len(segment.payload) > self._max_size:
            self.reset()
            msg = f"Fragment size exceeds maximum {self._max_size}"
            raise ReassemblyError(msg)

        # Add segment data
        self._buffer.extend(segment.payload)
        self._segment_count += 1
        self._expected_seq = _next_expected_seq(segment.sequence)

        if segment.is_final:
            return self._complete_fragment()

        return None

    def _complete_fragment(self) -> ReassembledFragment:
        """Complete current fragment and reset state.

        Returns:
            The completed fragment.
        """
        data = bytes(self._buffer)
        count = self._segment_count
        self.reset()
        return ReassembledFragment(data=data, segment_count=count)
