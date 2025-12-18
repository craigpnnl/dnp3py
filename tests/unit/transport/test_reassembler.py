"""Tests for transport layer reassembly."""

import pytest

from dnp3.transport.reassembler import (
    ReassembledFragment,
    Reassembler,
    ReassemblyError,
    ReassemblyState,
)
from dnp3.transport.segment import TransportSegment


class TestReassembledFragment:
    """Tests for ReassembledFragment dataclass."""

    def test_create_fragment(self) -> None:
        """Create a reassembled fragment."""
        fragment = ReassembledFragment(data=b"test", segment_count=1)
        assert fragment.data == b"test"
        assert fragment.segment_count == 1


class TestReassemblerInitialization:
    """Tests for Reassembler initialization."""

    def test_initial_state(self) -> None:
        """Reassembler starts in IDLE state."""
        reassembler = Reassembler()
        assert reassembler.state == ReassemblyState.IDLE
        assert reassembler.bytes_buffered == 0
        assert reassembler.segments_buffered == 0

    def test_with_max_size(self) -> None:
        """Reassembler can be created with max size limit."""
        reassembler = Reassembler(max_fragment_size=1000)
        assert reassembler.state == ReassemblyState.IDLE


class TestReassemblerSingleSegment:
    """Tests for single-segment fragment reassembly."""

    def test_single_segment_fragment(self) -> None:
        """Single segment (FIR+FIN) produces complete fragment."""
        reassembler = Reassembler()
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"hello")

        result = reassembler.add(segment)

        assert result is not None
        assert result.data == b"hello"
        assert result.segment_count == 1
        assert reassembler.state == ReassemblyState.IDLE

    def test_empty_single_segment(self) -> None:
        """Empty single segment produces empty fragment."""
        reassembler = Reassembler()
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"")

        result = reassembler.add(segment)

        assert result is not None
        assert result.data == b""
        assert result.segment_count == 1


class TestReassemblerMultipleSegments:
    """Tests for multi-segment fragment reassembly."""

    def test_two_segment_fragment(self) -> None:
        """Two segments are reassembled correctly."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"hello")
        seg2 = TransportSegment.build(fir=False, fin=True, seq=1, payload=b"world")

        result1 = reassembler.add(seg1)
        assert result1 is None
        assert reassembler.state == ReassemblyState.ASSEMBLING

        result2 = reassembler.add(seg2)
        assert result2 is not None
        assert result2.data == b"helloworld"
        assert result2.segment_count == 2

    def test_three_segment_fragment(self) -> None:
        """Three segments are reassembled correctly."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=5, payload=b"one")
        seg2 = TransportSegment.build(fir=False, fin=False, seq=6, payload=b"two")
        seg3 = TransportSegment.build(fir=False, fin=True, seq=7, payload=b"three")

        reassembler.add(seg1)
        reassembler.add(seg2)
        result = reassembler.add(seg3)

        assert result is not None
        assert result.data == b"onetwothree"
        assert result.segment_count == 3

    def test_sequence_wraps(self) -> None:
        """Sequence numbers wrap correctly at 64."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=63, payload=b"a")
        seg2 = TransportSegment.build(fir=False, fin=True, seq=0, payload=b"b")

        reassembler.add(seg1)
        result = reassembler.add(seg2)

        assert result is not None
        assert result.data == b"ab"


class TestReassemblerSequenceErrors:
    """Tests for sequence error handling."""

    def test_sequence_gap(self) -> None:
        """Missing segment causes sequence error."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"a")
        seg3 = TransportSegment.build(fir=False, fin=True, seq=2, payload=b"c")  # Skip seq 1

        reassembler.add(seg1)

        with pytest.raises(ReassemblyError, match="Sequence error"):
            reassembler.add(seg3)

        # Reassembler should be reset
        assert reassembler.state == ReassemblyState.IDLE

    def test_duplicate_sequence(self) -> None:
        """Duplicate sequence number causes error."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"a")
        seg_dup = TransportSegment.build(fir=False, fin=False, seq=0, payload=b"b")

        reassembler.add(seg1)

        with pytest.raises(ReassemblyError, match="Sequence error"):
            reassembler.add(seg_dup)


class TestReassemblerIgnoredSegments:
    """Tests for ignored segments."""

    def test_non_fir_when_idle(self) -> None:
        """Non-FIR segment when idle is ignored."""
        reassembler = Reassembler()
        segment = TransportSegment.build(fir=False, fin=True, seq=5, payload=b"ignored")

        result = reassembler.add(segment)

        assert result is None
        assert reassembler.state == ReassemblyState.IDLE

    def test_middle_segment_when_idle(self) -> None:
        """Middle segment when idle is ignored."""
        reassembler = Reassembler()
        segment = TransportSegment.build(fir=False, fin=False, seq=10, payload=b"middle")

        result = reassembler.add(segment)

        assert result is None
        assert reassembler.state == ReassemblyState.IDLE


class TestReassemblerAbort:
    """Tests for fragment abort handling."""

    def test_new_fir_aborts_current(self) -> None:
        """New FIR segment aborts current fragment."""
        reassembler = Reassembler()

        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"first")
        seg2 = TransportSegment.build(fir=True, fin=True, seq=5, payload=b"new")

        reassembler.add(seg1)
        result = reassembler.add(seg2)

        # Should complete the new fragment, not the first
        assert result is not None
        assert result.data == b"new"

    def test_new_fir_starts_new_fragment(self) -> None:
        """New FIR starts new multi-segment fragment."""
        reassembler = Reassembler()

        # Start first fragment
        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"first")
        reassembler.add(seg1)

        # Start new fragment
        new_seg1 = TransportSegment.build(fir=True, fin=False, seq=10, payload=b"new")
        new_seg2 = TransportSegment.build(fir=False, fin=True, seq=11, payload=b"second")

        result1 = reassembler.add(new_seg1)
        assert result1 is None

        result2 = reassembler.add(new_seg2)
        assert result2 is not None
        assert result2.data == b"newsecond"


class TestReassemblerReset:
    """Tests for reset functionality."""

    def test_reset_clears_buffer(self) -> None:
        """Reset clears buffered data."""
        reassembler = Reassembler()
        segment = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"partial")

        reassembler.add(segment)
        assert reassembler.bytes_buffered > 0

        reassembler.reset()
        assert reassembler.bytes_buffered == 0
        assert reassembler.segments_buffered == 0
        assert reassembler.state == ReassemblyState.IDLE


class TestReassemblerMaxSize:
    """Tests for maximum fragment size handling."""

    def test_within_max_size(self) -> None:
        """Fragment within max size is accepted."""
        reassembler = Reassembler(max_fragment_size=100)
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"small")

        result = reassembler.add(segment)
        assert result is not None

    def test_exceeds_max_size(self) -> None:
        """Fragment exceeding max size causes error."""
        reassembler = Reassembler(max_fragment_size=10)

        seg1 = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"12345")
        # 6 more bytes = 11 total, exceeds limit of 10
        seg2 = TransportSegment.build(fir=False, fin=True, seq=1, payload=b"67890!")

        reassembler.add(seg1)

        with pytest.raises(ReassemblyError, match="exceeds maximum"):
            reassembler.add(seg2)

        # Reassembler should be reset
        assert reassembler.state == ReassemblyState.IDLE


class TestReassemblerIntegration:
    """Integration tests with segmenter."""

    def test_roundtrip(self) -> None:
        """Segments from segmenter reassemble correctly."""
        from dnp3.transport.segmenter import segment_fragment

        original = b"This is a test message for roundtrip verification."

        segments = list(segment_fragment(original))
        reassembler = Reassembler()

        result = None
        for segment in segments:
            result = reassembler.add(segment)

        assert result is not None
        assert result.data == original

    def test_large_roundtrip(self) -> None:
        """Large fragment roundtrip."""
        from dnp3.transport.segmenter import segment_fragment

        # Create data spanning multiple segments
        original = bytes(range(256)) * 5  # 1280 bytes

        segments = list(segment_fragment(original))
        assert len(segments) > 1  # Verify it needs multiple segments

        reassembler = Reassembler()
        result = None
        for segment in segments:
            result = reassembler.add(segment)

        assert result is not None
        assert result.data == original
        assert result.segment_count == len(segments)

    def test_multiple_fragments_roundtrip(self) -> None:
        """Multiple consecutive fragments reassemble correctly."""
        from dnp3.transport.segmenter import Segmenter

        segmenter = Segmenter()
        reassembler = Reassembler()

        fragments = [b"first fragment", b"second fragment", b"third fragment"]
        reassembled = []

        for original in fragments:
            segments = segmenter.segment(original)
            for segment in segments:
                result = reassembler.add(segment)
                if result is not None:
                    reassembled.append(result.data)

        assert reassembled == fragments
