"""Fragment segmentation for transport layer.

Splits application layer fragments into transport segments for transmission
over the data link layer.
"""

from collections.abc import Iterator

from dnp3.transport.segment import MAX_PAYLOAD_SIZE, MAX_SEQUENCE, TransportSegment


def _split_into_chunks(data: bytes, chunk_size: int) -> Iterator[bytes]:
    """Split data into chunks of specified size.

    Args:
        data: Data to split.
        chunk_size: Maximum chunk size.

    Yields:
        Chunks of data, each at most chunk_size bytes.
    """
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def segment_fragment(fragment: bytes, start_seq: int = 0) -> Iterator[TransportSegment]:
    """Segment a fragment into transport segments.

    Args:
        fragment: Application layer fragment data.
        start_seq: Starting sequence number (0-63).

    Yields:
        TransportSegment instances for transmission.

    Raises:
        ValueError: If start_seq is out of range.
    """
    if not 0 <= start_seq <= MAX_SEQUENCE:
        msg = f"Start sequence {start_seq} out of range (0-{MAX_SEQUENCE})"
        raise ValueError(msg)

    if not fragment:
        # Empty fragment produces single segment with FIR and FIN set
        yield TransportSegment.build(fir=True, fin=True, seq=start_seq, payload=b"")
        return

    chunks = list(_split_into_chunks(fragment, MAX_PAYLOAD_SIZE))
    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        is_first = i == 0
        is_last = i == total_chunks - 1
        seq = (start_seq + i) & 0x3F  # Wrap at 64

        yield TransportSegment.build(
            fir=is_first,
            fin=is_last,
            seq=seq,
            payload=chunk,
        )


def segment_count(fragment_size: int) -> int:
    """Calculate number of segments needed for a fragment.

    Args:
        fragment_size: Size of fragment in bytes.

    Returns:
        Number of transport segments required.
    """
    if fragment_size == 0:
        return 1
    return (fragment_size + MAX_PAYLOAD_SIZE - 1) // MAX_PAYLOAD_SIZE


class Segmenter:
    """Stateful fragment segmenter.

    Tracks sequence numbers across multiple fragments.
    """

    def __init__(self, start_seq: int = 0) -> None:
        """Initialize segmenter.

        Args:
            start_seq: Initial sequence number (0-{MAX_SEQUENCE}).
        """
        if not 0 <= start_seq <= MAX_SEQUENCE:
            msg = f"Start sequence {start_seq} out of range (0-{MAX_SEQUENCE})"
            raise ValueError(msg)
        self._seq = start_seq

    @property
    def sequence(self) -> int:
        """Current sequence number."""
        return self._seq

    def segment(self, fragment: bytes) -> list[TransportSegment]:
        """Segment a fragment and update sequence counter.

        Args:
            fragment: Application layer fragment data.

        Returns:
            List of transport segments.
        """
        segments = list(segment_fragment(fragment, self._seq))
        # Update sequence for next fragment
        self._seq = (self._seq + len(segments)) & 0x3F
        return segments

    def reset(self, seq: int = 0) -> None:
        """Reset sequence counter.

        Args:
            seq: New sequence number (0-{MAX_SEQUENCE}).
        """
        if not 0 <= seq <= MAX_SEQUENCE:
            msg = f"Sequence {seq} out of range (0-{MAX_SEQUENCE})"
            raise ValueError(msg)
        self._seq = seq
