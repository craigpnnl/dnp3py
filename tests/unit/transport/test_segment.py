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
        """First segment: FIR=1, FIN=0, SEQ=0 -> 0x80."""
        header = TransportHeader(fir=True, fin=False, seq=0)
        assert header.to_byte() == 0x80

    def test_final_segment_byte(self) -> None:
        """Final segment: FIR=0, FIN=1, SEQ=5 -> 0x45."""
        header = TransportHeader(fir=False, fin=True, seq=5)
        assert header.to_byte() == 0x45

    def test_only_segment_byte(self) -> None:
        """Only segment: FIR=1, FIN=1, SEQ=0 -> 0xC0."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        assert header.to_byte() == 0xC0

    def test_middle_segment_byte(self) -> None:
        """Middle segment: FIR=0, FIN=0, SEQ=10 -> 0x0A."""
        header = TransportHeader(fir=False, fin=False, seq=10)
        assert header.to_byte() == 0x0A

    def test_max_sequence_byte(self) -> None:
        """Max sequence: FIR=1, FIN=1, SEQ=63 -> 0xFF."""
        header = TransportHeader(fir=True, fin=True, seq=63)
        assert header.to_byte() == 0xFF

    def test_to_bytes(self) -> None:
        """to_bytes returns single byte."""
        header = TransportHeader(fir=True, fin=True, seq=0)
        data = header.to_bytes()
        assert len(data) == 1
        assert data == b"\xc0"


class TestTransportHeaderParsing:
    """Tests for parsing TransportHeader from bytes."""

    def test_parse_first_segment(self) -> None:
        """Parse 0x80 -> FIR=1, FIN=0, SEQ=0."""
        header = TransportHeader.from_byte(0x80)
        assert header.fir is True
        assert header.fin is False
        assert header.seq == 0

    def test_parse_final_segment(self) -> None:
        """Parse 0x45 -> FIR=0, FIN=1, SEQ=5."""
        header = TransportHeader.from_byte(0x45)
        assert header.fir is False
        assert header.fin is True
        assert header.seq == 5

    def test_parse_only_segment(self) -> None:
        """Parse 0xC0 -> FIR=1, FIN=1, SEQ=0."""
        header = TransportHeader.from_byte(0xC0)
        assert header.fir is True
        assert header.fin is True
        assert header.seq == 0

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
        """Parse segment with only header."""
        segment = TransportSegment.from_bytes(b"\x80")
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
