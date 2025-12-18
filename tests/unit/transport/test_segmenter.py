"""Tests for transport layer segmentation."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.transport.segment import MAX_PAYLOAD_SIZE
from dnp3.transport.segmenter import Segmenter, segment_count, segment_fragment


class TestSegmentFragment:
    """Tests for segment_fragment function."""

    def test_empty_fragment(self) -> None:
        """Empty fragment produces single segment with FIR and FIN."""
        segments = list(segment_fragment(b""))
        assert len(segments) == 1
        assert segments[0].is_first is True
        assert segments[0].is_final is True
        assert segments[0].payload == b""

    def test_small_fragment(self) -> None:
        """Small fragment fits in single segment."""
        segments = list(segment_fragment(b"hello"))
        assert len(segments) == 1
        assert segments[0].is_first is True
        assert segments[0].is_final is True
        assert segments[0].payload == b"hello"

    def test_max_single_segment(self) -> None:
        """Fragment at max payload size fits in single segment."""
        data = bytes(MAX_PAYLOAD_SIZE)
        segments = list(segment_fragment(data))
        assert len(segments) == 1
        assert segments[0].payload == data

    def test_two_segments(self) -> None:
        """Fragment slightly over max size needs two segments."""
        data = bytes(MAX_PAYLOAD_SIZE + 1)
        segments = list(segment_fragment(data))

        assert len(segments) == 2
        assert segments[0].is_first is True
        assert segments[0].is_final is False
        assert len(segments[0].payload) == MAX_PAYLOAD_SIZE

        assert segments[1].is_first is False
        assert segments[1].is_final is True
        assert len(segments[1].payload) == 1

    def test_three_segments(self) -> None:
        """Fragment needing three segments."""
        data = bytes(MAX_PAYLOAD_SIZE * 2 + 50)
        segments = list(segment_fragment(data))

        assert len(segments) == 3
        assert segments[0].is_first is True
        assert segments[0].is_final is False
        assert segments[1].is_first is False
        assert segments[1].is_final is False
        assert segments[2].is_first is False
        assert segments[2].is_final is True

    def test_sequence_numbers(self) -> None:
        """Segments have consecutive sequence numbers."""
        data = bytes(MAX_PAYLOAD_SIZE * 3)
        segments = list(segment_fragment(data, start_seq=0))

        assert segments[0].sequence == 0
        assert segments[1].sequence == 1
        assert segments[2].sequence == 2

    def test_start_sequence(self) -> None:
        """Segmentation starts from given sequence number."""
        segments = list(segment_fragment(b"test", start_seq=10))
        assert segments[0].sequence == 10

    def test_sequence_wraps(self) -> None:
        """Sequence numbers wrap at 64."""
        data = bytes(MAX_PAYLOAD_SIZE * 3)
        segments = list(segment_fragment(data, start_seq=62))

        assert segments[0].sequence == 62
        assert segments[1].sequence == 63
        assert segments[2].sequence == 0  # Wrapped

    def test_start_sequence_invalid_negative(self) -> None:
        """Negative start sequence raises error."""
        with pytest.raises(ValueError, match="out of range"):
            list(segment_fragment(b"test", start_seq=-1))

    def test_start_sequence_invalid_too_large(self) -> None:
        """Start sequence > 63 raises error."""
        with pytest.raises(ValueError, match="out of range"):
            list(segment_fragment(b"test", start_seq=64))

    def test_data_integrity(self) -> None:
        """All data is preserved in segments."""
        data = b"Hello, DNP3 transport layer!"
        segments = list(segment_fragment(data))
        reassembled = b"".join(s.payload for s in segments)
        assert reassembled == data

    def test_large_data_integrity(self) -> None:
        """Large data is correctly split and preserved."""
        data = bytes(range(256)) * 10  # 2560 bytes
        segments = list(segment_fragment(data))
        reassembled = b"".join(s.payload for s in segments)
        assert reassembled == data


class TestSegmentCount:
    """Tests for segment_count function."""

    def test_zero_bytes(self) -> None:
        """Zero bytes requires one segment."""
        assert segment_count(0) == 1

    def test_one_byte(self) -> None:
        """One byte requires one segment."""
        assert segment_count(1) == 1

    def test_max_single_segment(self) -> None:
        """Max payload size requires one segment."""
        assert segment_count(MAX_PAYLOAD_SIZE) == 1

    def test_one_over_max(self) -> None:
        """One byte over max requires two segments."""
        assert segment_count(MAX_PAYLOAD_SIZE + 1) == 2

    def test_two_full_segments(self) -> None:
        """Two full segments worth of data."""
        assert segment_count(MAX_PAYLOAD_SIZE * 2) == 2

    def test_partial_third_segment(self) -> None:
        """Two full segments plus partial third."""
        assert segment_count(MAX_PAYLOAD_SIZE * 2 + 1) == 3

    @given(st.integers(min_value=0, max_value=10000))
    def test_matches_actual_segments(self, size: int) -> None:
        """Count matches actual segment generation."""
        data = bytes(size)
        segments = list(segment_fragment(data))
        assert len(segments) == segment_count(size)


class TestSegmenter:
    """Tests for Segmenter class."""

    def test_initial_sequence(self) -> None:
        """Segmenter starts at specified sequence."""
        segmenter = Segmenter(start_seq=5)
        assert segmenter.sequence == 5

    def test_default_sequence(self) -> None:
        """Default sequence is 0."""
        segmenter = Segmenter()
        assert segmenter.sequence == 0

    def test_invalid_start_sequence(self) -> None:
        """Invalid start sequence raises error."""
        with pytest.raises(ValueError, match="out of range"):
            Segmenter(start_seq=64)

    def test_segment_updates_sequence(self) -> None:
        """Segmenting updates sequence counter."""
        segmenter = Segmenter(start_seq=0)
        segmenter.segment(b"hello")
        assert segmenter.sequence == 1  # One segment, sequence advances by 1

    def test_segment_multiple_fragments(self) -> None:
        """Multiple fragments have consecutive sequences."""
        segmenter = Segmenter()

        segments1 = segmenter.segment(b"first")
        assert segments1[0].sequence == 0

        segments2 = segmenter.segment(b"second")
        assert segments2[0].sequence == 1

        segments3 = segmenter.segment(b"third")
        assert segments3[0].sequence == 2

    def test_segment_wraps_sequence(self) -> None:
        """Sequence wraps at 64."""
        segmenter = Segmenter(start_seq=63)
        segmenter.segment(b"first")
        assert segmenter.sequence == 0  # Wrapped

    def test_large_fragment_advances_by_count(self) -> None:
        """Large fragment advances sequence by segment count."""
        segmenter = Segmenter(start_seq=0)
        # Create fragment requiring 3 segments
        data = bytes(MAX_PAYLOAD_SIZE * 2 + 50)
        segmenter.segment(data)
        assert segmenter.sequence == 3

    def test_reset(self) -> None:
        """Reset clears sequence to specified value."""
        segmenter = Segmenter(start_seq=10)
        segmenter.segment(b"data")
        segmenter.reset(0)
        assert segmenter.sequence == 0

    def test_reset_to_value(self) -> None:
        """Reset to specific value."""
        segmenter = Segmenter()
        segmenter.reset(42)
        assert segmenter.sequence == 42

    def test_reset_invalid(self) -> None:
        """Reset to invalid value raises error."""
        segmenter = Segmenter()
        with pytest.raises(ValueError, match="out of range"):
            segmenter.reset(64)

    def test_segment_returns_list(self) -> None:
        """Segment returns list (not iterator)."""
        segmenter = Segmenter()
        result = segmenter.segment(b"test")
        assert isinstance(result, list)
        assert len(result) == 1
