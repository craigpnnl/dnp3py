"""Tests for transport layer segments."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.transport.segment import (
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    MAX_SEQUENCE,
    TransportHeader,
    TransportSegment,
)


class TestTransportHeaderConstants:
    """Tests for transport header constants."""

    def test_max_sequence(self) -> None:
        """Maximum sequence number is 63."""
        assert MAX_SEQUENCE == 63

    def test_max_payload_size(self) -> None:
        """Maximum payload size is 249 bytes."""
        assert MAX_PAYLOAD_SIZE == 249

    def test_header_size(self) -> None:
        """Header size is 1 byte."""
        assert HEADER_SIZE == 1


class TestTransportHeaderCreation:
    """Tests for creating TransportHeader instances."""

    def test_create_first_segment(self) -> None:
        """Create header for first segment."""
        header = TransportHeader(fir=True, fin=False, seq=0)
        assert header.fir is True
        assert header.fin is False
        assert header.seq == 0

    def test_create_final_segment(self) -> None:
        """Create header for final segment."""
        header = TransportHeader(fir=False, fin=True, seq=5)
        assert header.fir is False
        assert header.fin is True
        assert header.seq == 5

    def test_create_only_segment(self) -> None:
        """Create header for single segment (FIR and FIN)."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        assert header.fir is True
        assert header.fin is True

    def test_create_middle_segment(self) -> None:
        """Create header for middle segment."""
        header = TransportHeader(fir=False, fin=False, seq=10)
        assert header.fir is False
        assert header.fin is False

    def test_max_sequence_valid(self) -> None:
        """Maximum sequence number (63) is valid."""
        header = TransportHeader(fir=True, fin=True, seq=63)
        assert header.seq == 63

    def test_sequence_out_of_range_negative(self) -> None:
        """Negative sequence number raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TransportHeader(fir=True, fin=True, seq=-1)

    def test_sequence_out_of_range_too_large(self) -> None:
        """Sequence number > 63 raises error."""
        with pytest.raises(ValueError, match="out of range"):
            TransportHeader(fir=True, fin=True, seq=64)


class TestTransportHeaderSerialization:
    """Tests for serializing TransportHeader to bytes."""

    def test_first_segment_byte(self) -> None:
        """First segment: FIR=1, FIN=0, SEQ=0 -> 0x40 (FIR=bit6 per IEEE 1815-2012)."""
        header = TransportHeader(fir=True, fin=False, seq=0)
        assert header.to_byte() == 0x40

    def test_final_segment_byte(self) -> None:
        """Final segment: FIR=0, FIN=1, SEQ=5 -> 0x85 (FIN=bit7 per IEEE 1815-2012)."""
        header = TransportHeader(fir=False, fin=True, seq=5)
        assert header.to_byte() == 0x85

    def test_only_segment_byte(self) -> None:
        """Only segment: FIR=1, FIN=1, SEQ=0 -> 0xC0."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        assert header.to_byte() == 0xC0
        # Swap-guard: both-bits-set passes even with FIR/FIN swapped; a
        # FIR-only case distinguishes them (must be 0x40, not 0x80).
        assert TransportHeader(fir=True, fin=False, seq=0).to_byte() == 0x40

    def test_middle_segment_byte(self) -> None:
        """Middle segment: FIR=0, FIN=0, SEQ=10 -> 0x0A."""
        header = TransportHeader(fir=False, fin=False, seq=10)
        assert header.to_byte() == 0x0A

    def test_max_sequence_byte(self) -> None:
        """Max sequence: FIR=1, FIN=1, SEQ=63 -> 0xFF."""
        header = TransportHeader(fir=True, fin=True, seq=63)
        assert header.to_byte() == 0xFF
        # Swap-guard: FIN-only at max seq must be 0xBF (0x80 | 0x3F), not 0x7F.
        assert TransportHeader(fir=False, fin=True, seq=63).to_byte() == 0xBF

    def test_to_bytes(self) -> None:
        """to_bytes returns single byte."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        data = header.to_bytes()
        assert len(data) == 1
        assert data == b"\xc0"


class TestTransportHeaderParsing:
    """Tests for parsing TransportHeader from bytes."""

    def test_parse_first_segment(self) -> None:
        """Parse 0x40 -> FIR=1, FIN=0, SEQ=0 (FIR=bit6 per IEEE 1815-2012)."""
        header = TransportHeader.from_byte(0x40)
        assert header.fir is True
        assert header.fin is False
        assert header.seq == 0

    def test_parse_final_segment(self) -> None:
        """Parse 0x85 -> FIR=0, FIN=1, SEQ=5 (FIN=bit7 per IEEE 1815-2012)."""
        header = TransportHeader.from_byte(0x85)
        assert header.fir is False
        assert header.fin is True
        assert header.seq == 5

    def test_parse_only_segment(self) -> None:
        """Parse 0xC0 -> FIR=1, FIN=1, SEQ=0."""
        header = TransportHeader.from_byte(0xC0)
        assert header.fir is True
        assert header.fin is True
        assert header.seq == 0
        # Swap-guard: 0x40 must parse as FIR=True, FIN=False (not the reverse).
        fir_only = TransportHeader.from_byte(0x40)
        assert fir_only.fir is True
        assert fir_only.fin is False

    def test_parse_fin_only_swap_guard(self) -> None:
        """FIN-only swap-guard: 0x80 must parse as FIR=False, FIN=True, SEQ=0.

        Mirrors the FIR-only guard so a FIR/FIN bit-position swap fails
        parsing in both directions (IEEE 1815-2012 Clause 8).
        """
        fin_only = TransportHeader.from_byte(0x80)
        assert fin_only.fir is False
        assert fin_only.fin is True
        assert fin_only.seq == 0

    def test_parse_middle_segment(self) -> None:
        """Parse 0x0A -> FIR=0, FIN=0, SEQ=10."""
        header = TransportHeader.from_byte(0x0A)
        assert header.fir is False
        assert header.fin is False
        assert header.seq == 10

    def test_parse_max_value(self) -> None:
        """Parse 0xFF -> FIR=1, FIN=1, SEQ=63."""
        header = TransportHeader.from_byte(0xFF)
        assert header.fir is True
        assert header.fin is True
        assert header.seq == 63

    def test_from_bytes(self) -> None:
        """Parse from bytes object."""
        header = TransportHeader.from_bytes(b"\xc0")
        assert header.fir is True
        assert header.fin is True
        assert header.seq == 0

    def test_from_bytes_empty_raises(self) -> None:
        """Empty bytes raises error."""
        with pytest.raises(ValueError, match="empty"):
            TransportHeader.from_bytes(b"")

    @given(st.integers(min_value=0, max_value=255))
    def test_roundtrip(self, value: int) -> None:
        """Roundtrip: from_byte -> to_byte preserves value."""
        header = TransportHeader.from_byte(value)
        assert header.to_byte() == value


class TestTransportHeaderProperties:
    """Tests for TransportHeader properties."""

    def test_is_first(self) -> None:
        """is_first property."""
        assert TransportHeader(fir=True, fin=False, seq=0).is_first is True
        assert TransportHeader(fir=False, fin=True, seq=0).is_first is False

    def test_is_final(self) -> None:
        """is_final property."""
        assert TransportHeader(fir=False, fin=True, seq=0).is_final is True
        assert TransportHeader(fir=True, fin=False, seq=0).is_final is False

    def test_is_only(self) -> None:
        """is_only property (FIR and FIN both set)."""
        assert TransportHeader(fir=True, fin=True, seq=0).is_only is True
        assert TransportHeader(fir=True, fin=False, seq=0).is_only is False
        assert TransportHeader(fir=False, fin=True, seq=0).is_only is False
        assert TransportHeader(fir=False, fin=False, seq=0).is_only is False


class TestTransportSegmentCreation:
    """Tests for creating TransportSegment instances."""

    def test_create_segment(self) -> None:
        """Create a transport segment."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        segment = TransportSegment(header=header, payload=b"test")
        assert segment.header == header
        assert segment.payload == b"test"

    def test_build_segment(self) -> None:
        """Build segment from components."""
        segment = TransportSegment.build(fir=True, fin=True, seq=5, payload=b"data")
        assert segment.header.fir is True
        assert segment.header.fin is True
        assert segment.header.seq == 5
        assert segment.payload == b"data"

    def test_empty_payload(self) -> None:
        """Segment with empty payload is valid."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"")
        assert segment.payload == b""

    def test_max_payload(self) -> None:
        """Segment with maximum payload size is valid."""
        payload = bytes(MAX_PAYLOAD_SIZE)
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=payload)
        assert len(segment.payload) == MAX_PAYLOAD_SIZE

    def test_payload_too_large(self) -> None:
        """Payload exceeding maximum raises error."""
        payload = bytes(MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            TransportSegment.build(fir=True, fin=True, seq=0, payload=payload)


class TestTransportSegmentSerialization:
    """Tests for serializing TransportSegment to bytes."""

    def test_serialize_segment(self) -> None:
        """Serialize segment to bytes."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"test")
        data = segment.to_bytes()
        assert data == b"\xc0test"

    def test_serialize_empty_payload(self) -> None:
        """Serialize segment with empty payload."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"")
        data = segment.to_bytes()
        assert data == b"\xc0"
        assert len(data) == 1


class TestTransportSegmentParsing:
    """Tests for parsing TransportSegment from bytes."""

    def test_parse_segment(self) -> None:
        """Parse segment from bytes."""
        segment = TransportSegment.from_bytes(b"\xc0test")
        assert segment.header.fir is True
        assert segment.header.fin is True
        assert segment.header.seq == 0
        assert segment.payload == b"test"

    def test_parse_empty_payload(self) -> None:
        """Parse segment with only header: 0x40 = FIR=1, FIN=0 per IEEE 1815-2012."""
        segment = TransportSegment.from_bytes(b"\x40")
        assert segment.header.fir is True
        assert segment.header.fin is False
        assert segment.payload == b""

    def test_parse_empty_raises(self) -> None:
        """Empty bytes raises error."""
        with pytest.raises(ValueError, match="empty"):
            TransportSegment.from_bytes(b"")

    @given(
        fir=st.booleans(),
        fin=st.booleans(),
        seq=st.integers(min_value=0, max_value=63),
        payload=st.binary(max_size=MAX_PAYLOAD_SIZE),
    )
    def test_roundtrip(self, fir: bool, fin: bool, seq: int, payload: bytes) -> None:
        """Roundtrip: build -> to_bytes -> from_bytes preserves data."""
        original = TransportSegment.build(fir=fir, fin=fin, seq=seq, payload=payload)
        data = original.to_bytes()
        parsed = TransportSegment.from_bytes(data)
        assert parsed.header.fir == fir
        assert parsed.header.fin == fin
        assert parsed.header.seq == seq
        assert parsed.payload == payload


class TestTransportSegmentProperties:
    """Tests for TransportSegment properties."""

    def test_is_first(self) -> None:
        """is_first property delegates to header."""
        segment = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"")
        assert segment.is_first is True

    def test_is_final(self) -> None:
        """is_final property delegates to header."""
        segment = TransportSegment.build(fir=False, fin=True, seq=0, payload=b"")
        assert segment.is_final is True

    def test_is_only(self) -> None:
        """is_only property delegates to header."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=b"")
        assert segment.is_only is True

    def test_sequence(self) -> None:
        """sequence property returns header seq."""
        segment = TransportSegment.build(fir=True, fin=True, seq=42, payload=b"")
        assert segment.sequence == 42


class TestMultiFragmentFirFin:
    """Verify FIR and FIN bit semantics on a multi-segment exchange.

    IEEE 1815-2012 Clause 8: FIN occupies bit 7 (0x80), FIR occupies
    bit 6 (0x40).  On a three-segment fragment only the first segment has
    FIR set; only the last has FIN set; the middle segment has neither.
    This test exercises the case that actually distinguishes the two bits
    and would silently break if they were swapped.
    """

    def test_three_segment_wire_bytes(self) -> None:
        """Three-segment fragment: first=FIR only, middle=neither, last=FIN only."""
        first = TransportSegment.build(fir=True, fin=False, seq=0, payload=b"aaa")
        middle = TransportSegment.build(fir=False, fin=False, seq=1, payload=b"bbb")
        last = TransportSegment.build(fir=False, fin=True, seq=2, payload=b"ccc")

        # IEEE 1815-2012: FIR=bit6=0x40, FIN=bit7=0x80
        assert first.to_bytes()[0] == 0x40  # FIR only
        assert middle.to_bytes()[0] == 0x01  # neither flag, seq=1
        assert last.to_bytes()[0] == 0x82  # FIN only, seq=2

        # Full wire-format fixture: header byte + payload bytes for first segment.
        assert first.to_bytes() == b"\x40" + b"aaa"

        # Structural checks
        assert first.is_first and not first.is_final
        assert not middle.is_first and not middle.is_final
        assert last.is_final and not last.is_first

    def test_three_segment_roundtrip(self) -> None:
        """Roundtrip a three-segment sequence preserving FIR/FIN/seq."""
        segments = [
            TransportSegment.build(fir=True, fin=False, seq=0, payload=b"x" * 10),
            TransportSegment.build(fir=False, fin=False, seq=1, payload=b"y" * 10),
            TransportSegment.build(fir=False, fin=True, seq=2, payload=b"z" * 10),
        ]
        for original in segments:
            parsed = TransportSegment.from_bytes(original.to_bytes())
            assert parsed.header.fir == original.header.fir
            assert parsed.header.fin == original.header.fin
            assert parsed.header.seq == original.header.seq
            assert parsed.payload == original.payload
