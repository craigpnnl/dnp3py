"""Tests for application layer headers."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.application.header import (
    MAX_APP_SEQUENCE,
    REQUEST_HEADER_SIZE,
    RESPONSE_HEADER_SIZE,
    ApplicationControl,
    RequestHeader,
    ResponseHeader,
)
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN


class TestApplicationControlConstants:
    """Tests for application control constants."""

    def test_max_sequence(self) -> None:
        """Maximum sequence number is 15."""
        assert MAX_APP_SEQUENCE == 15

    def test_request_header_size(self) -> None:
        """Request header is 2 bytes."""
        assert REQUEST_HEADER_SIZE == 2

    def test_response_header_size(self) -> None:
        """Response header is 4 bytes."""
        assert RESPONSE_HEADER_SIZE == 4


class TestApplicationControlCreation:
    """Tests for creating ApplicationControl instances."""

    def test_create_first_fragment(self) -> None:
        """Create control for first fragment."""
        ac = ApplicationControl(fir=True, fin=False, con=False, uns=False, seq=0)
        assert ac.fir is True
        assert ac.fin is False
        assert ac.seq == 0

    def test_create_final_fragment(self) -> None:
        """Create control for final fragment."""
        ac = ApplicationControl(fir=False, fin=True, con=False, uns=False, seq=5)
        assert ac.fir is False
        assert ac.fin is True
        assert ac.seq == 5

    def test_create_only_fragment(self) -> None:
        """Create control for single fragment (FIR and FIN)."""
        ac = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0)
        assert ac.fir is True
        assert ac.fin is True

    def test_create_with_confirmation(self) -> None:
        """Create control with confirmation requested."""
        ac = ApplicationControl(fir=True, fin=True, con=True, uns=False, seq=0)
        assert ac.con is True

    def test_create_unsolicited(self) -> None:
        """Create control for unsolicited response."""
        ac = ApplicationControl(fir=True, fin=True, con=True, uns=True, seq=0)
        assert ac.uns is True

    def test_max_sequence_valid(self) -> None:
        """Maximum sequence number (15) is valid."""
        ac = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=15)
        assert ac.seq == 15

    def test_sequence_out_of_range_negative(self) -> None:
        """Negative sequence number raises error."""
        with pytest.raises(ValueError, match="out of range"):
            ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=-1)

    def test_sequence_out_of_range_too_large(self) -> None:
        """Sequence number > 15 raises error."""
        with pytest.raises(ValueError, match="out of range"):
            ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=16)


class TestApplicationControlSerialization:
    """Tests for serializing ApplicationControl to bytes."""

    def test_first_fragment_byte(self) -> None:
        """First fragment: FIR=1, FIN=0, SEQ=0 -> 0x80."""
        ac = ApplicationControl(fir=True, fin=False, con=False, uns=False, seq=0)
        assert ac.to_byte() == 0x80

    def test_final_fragment_byte(self) -> None:
        """Final fragment: FIR=0, FIN=1, SEQ=5 -> 0x45."""
        ac = ApplicationControl(fir=False, fin=True, con=False, uns=False, seq=5)
        assert ac.to_byte() == 0x45

    def test_only_fragment_byte(self) -> None:
        """Only fragment: FIR=1, FIN=1, SEQ=0 -> 0xC0."""
        ac = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0)
        assert ac.to_byte() == 0xC0

    def test_with_confirmation_byte(self) -> None:
        """With confirmation: FIR=1, FIN=1, CON=1, SEQ=0 -> 0xE0."""
        ac = ApplicationControl(fir=True, fin=True, con=True, uns=False, seq=0)
        assert ac.to_byte() == 0xE0

    def test_unsolicited_byte(self) -> None:
        """Unsolicited: FIR=1, FIN=1, CON=1, UNS=1, SEQ=0 -> 0xF0."""
        ac = ApplicationControl(fir=True, fin=True, con=True, uns=True, seq=0)
        assert ac.to_byte() == 0xF0

    def test_all_bits_set_byte(self) -> None:
        """All bits set: 0xFF."""
        ac = ApplicationControl(fir=True, fin=True, con=True, uns=True, seq=15)
        assert ac.to_byte() == 0xFF

    def test_to_bytes(self) -> None:
        """to_bytes returns single byte."""
        ac = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0)
        data = ac.to_bytes()
        assert len(data) == 1
        assert data == b"\xc0"


class TestApplicationControlParsing:
    """Tests for parsing ApplicationControl from bytes."""

    def test_parse_first_fragment(self) -> None:
        """Parse 0x80 -> FIR=1, FIN=0, SEQ=0."""
        ac = ApplicationControl.from_byte(0x80)
        assert ac.fir is True
        assert ac.fin is False
        assert ac.con is False
        assert ac.uns is False
        assert ac.seq == 0

    def test_parse_only_fragment(self) -> None:
        """Parse 0xC0 -> FIR=1, FIN=1, SEQ=0."""
        ac = ApplicationControl.from_byte(0xC0)
        assert ac.fir is True
        assert ac.fin is True
        assert ac.seq == 0

    def test_parse_with_confirmation(self) -> None:
        """Parse 0xE0 -> FIR=1, FIN=1, CON=1."""
        ac = ApplicationControl.from_byte(0xE0)
        assert ac.con is True

    def test_parse_unsolicited(self) -> None:
        """Parse 0xF0 -> UNS=1."""
        ac = ApplicationControl.from_byte(0xF0)
        assert ac.uns is True

    def test_parse_all_bits(self) -> None:
        """Parse 0xFF -> all bits set."""
        ac = ApplicationControl.from_byte(0xFF)
        assert ac.fir is True
        assert ac.fin is True
        assert ac.con is True
        assert ac.uns is True
        assert ac.seq == 15

    def test_from_bytes_empty_raises(self) -> None:
        """Empty bytes raises error."""
        with pytest.raises(ValueError, match="empty"):
            ApplicationControl.from_bytes(b"")

    @given(st.integers(min_value=0, max_value=255))
    def test_roundtrip(self, value: int) -> None:
        """Roundtrip: from_byte -> to_byte preserves value."""
        ac = ApplicationControl.from_byte(value)
        assert ac.to_byte() == value


class TestApplicationControlProperties:
    """Tests for ApplicationControl properties."""

    def test_is_first(self) -> None:
        """is_first property."""
        assert ApplicationControl.from_byte(0x80).is_first is True
        assert ApplicationControl.from_byte(0x40).is_first is False

    def test_is_final(self) -> None:
        """is_final property."""
        assert ApplicationControl.from_byte(0x40).is_final is True
        assert ApplicationControl.from_byte(0x80).is_final is False

    def test_is_only(self) -> None:
        """is_only property (FIR and FIN both set)."""
        assert ApplicationControl.from_byte(0xC0).is_only is True
        assert ApplicationControl.from_byte(0x80).is_only is False
        assert ApplicationControl.from_byte(0x40).is_only is False

    def test_confirms_requested(self) -> None:
        """confirms_requested property."""
        assert ApplicationControl.from_byte(0xE0).confirms_requested is True
        assert ApplicationControl.from_byte(0xC0).confirms_requested is False

    def test_is_unsolicited(self) -> None:
        """is_unsolicited property."""
        assert ApplicationControl.from_byte(0xF0).is_unsolicited is True
        assert ApplicationControl.from_byte(0xE0).is_unsolicited is False


class TestRequestHeaderCreation:
    """Tests for creating RequestHeader instances."""

    def test_build_read_request(self) -> None:
        """Build a READ request header."""
        header = RequestHeader.build(function=FunctionCode.READ)
        assert header.function == FunctionCode.READ
        assert header.control.fir is True
        assert header.control.fin is True
        assert header.control.seq == 0

    def test_build_with_sequence(self) -> None:
        """Build request with specific sequence."""
        header = RequestHeader.build(function=FunctionCode.READ, seq=5)
        assert header.control.seq == 5

    def test_build_with_confirmation(self) -> None:
        """Build request with confirmation requested."""
        header = RequestHeader.build(function=FunctionCode.WRITE, con=True)
        assert header.control.con is True

    def test_build_multi_fragment(self) -> None:
        """Build multi-fragment request."""
        header = RequestHeader.build(function=FunctionCode.WRITE, fir=True, fin=False)
        assert header.control.fir is True
        assert header.control.fin is False


class TestRequestHeaderSerialization:
    """Tests for serializing RequestHeader to bytes."""

    def test_serialize_read_request(self) -> None:
        """Serialize READ request."""
        header = RequestHeader.build(function=FunctionCode.READ)
        data = header.to_bytes()
        assert len(data) == 2
        assert data[0] == 0xC0  # FIR=1, FIN=1
        assert data[1] == 0x01  # READ

    def test_serialize_write_request(self) -> None:
        """Serialize WRITE request."""
        header = RequestHeader.build(function=FunctionCode.WRITE)
        data = header.to_bytes()
        assert data[1] == 0x02  # WRITE

    def test_serialize_with_sequence(self) -> None:
        """Serialize request with sequence."""
        header = RequestHeader.build(function=FunctionCode.READ, seq=10)
        data = header.to_bytes()
        assert data[0] == 0xCA  # FIR=1, FIN=1, SEQ=10


class TestRequestHeaderParsing:
    """Tests for parsing RequestHeader from bytes."""

    def test_parse_read_request(self) -> None:
        """Parse READ request."""
        header = RequestHeader.from_bytes(b"\xc0\x01")
        assert header.function == FunctionCode.READ
        assert header.control.fir is True
        assert header.control.fin is True

    def test_parse_write_request(self) -> None:
        """Parse WRITE request."""
        header = RequestHeader.from_bytes(b"\xc0\x02")
        assert header.function == FunctionCode.WRITE

    def test_parse_too_short_raises(self) -> None:
        """Too short data raises error."""
        with pytest.raises(ValueError, match="requires 2 bytes"):
            RequestHeader.from_bytes(b"\xc0")

    def test_parse_unknown_function_raises(self) -> None:
        """Unknown function code raises error."""
        with pytest.raises(ValueError, match="Unknown function code"):
            RequestHeader.from_bytes(b"\xc0\xff")

    def test_roundtrip(self) -> None:
        """Roundtrip: build -> to_bytes -> from_bytes."""
        original = RequestHeader.build(function=FunctionCode.SELECT, seq=7, con=True)
        data = original.to_bytes()
        parsed = RequestHeader.from_bytes(data)
        assert parsed.function == original.function
        assert parsed.control.seq == original.control.seq
        assert parsed.control.con == original.control.con


class TestResponseHeaderCreation:
    """Tests for creating ResponseHeader instances."""

    def test_build_response(self) -> None:
        """Build a RESPONSE header."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        assert header.function == FunctionCode.RESPONSE
        assert header.control.fir is True
        assert header.control.fin is True
        assert header.iin == IIN(0)

    def test_build_with_iin(self) -> None:
        """Build response with IIN flags."""
        iin = IIN.DEVICE_RESTART | IIN.NEED_TIME
        header = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=iin)
        assert header.iin == iin

    def test_build_unsolicited(self) -> None:
        """Build unsolicited response."""
        header = ResponseHeader.build(function=FunctionCode.UNSOLICITED_RESPONSE, uns=True, con=True)
        assert header.control.uns is True
        assert header.control.con is True


class TestResponseHeaderSerialization:
    """Tests for serializing ResponseHeader to bytes."""

    def test_serialize_response(self) -> None:
        """Serialize RESPONSE."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        data = header.to_bytes()
        assert len(data) == 4
        assert data[0] == 0xC0  # FIR=1, FIN=1
        assert data[1] == 0x81  # RESPONSE
        assert data[2:4] == b"\x00\x00"  # IIN = 0

    def test_serialize_with_iin(self) -> None:
        """Serialize response with IIN flags."""
        iin = IIN.DEVICE_RESTART
        header = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=iin)
        data = header.to_bytes()
        # DEVICE_RESTART is bit 7 of IIN1 (first byte)
        assert data[2] == 0x80


class TestResponseHeaderParsing:
    """Tests for parsing ResponseHeader from bytes."""

    def test_parse_response(self) -> None:
        """Parse RESPONSE."""
        header = ResponseHeader.from_bytes(b"\xc0\x81\x00\x00")
        assert header.function == FunctionCode.RESPONSE
        assert header.iin == IIN(0)

    def test_parse_with_iin(self) -> None:
        """Parse response with IIN flags."""
        header = ResponseHeader.from_bytes(b"\xc0\x81\x80\x00")
        assert header.iin & IIN.DEVICE_RESTART

    def test_parse_too_short_raises(self) -> None:
        """Too short data raises error."""
        with pytest.raises(ValueError, match="requires 4 bytes"):
            ResponseHeader.from_bytes(b"\xc0\x81\x00")

    def test_roundtrip(self) -> None:
        """Roundtrip: build -> to_bytes -> from_bytes."""
        iin = IIN.CLASS_1_EVENTS | IIN.NEED_TIME
        original = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=iin, seq=3, con=True)
        data = original.to_bytes()
        parsed = ResponseHeader.from_bytes(data)
        assert parsed.function == original.function
        assert parsed.iin == original.iin
        assert parsed.control.seq == original.control.seq


class TestResponseHeaderProperties:
    """Tests for ResponseHeader properties."""

    def test_has_events(self) -> None:
        """has_events property."""
        with_events = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=IIN.CLASS_1_EVENTS)
        without_events = ResponseHeader.build(function=FunctionCode.RESPONSE)

        assert with_events.has_events is True
        assert without_events.has_events is False

    def test_needs_time(self) -> None:
        """needs_time property."""
        needs = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=IIN.NEED_TIME)
        no_need = ResponseHeader.build(function=FunctionCode.RESPONSE)

        assert needs.needs_time is True
        assert no_need.needs_time is False

    def test_device_restart(self) -> None:
        """device_restart property."""
        restarted = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=IIN.DEVICE_RESTART)
        normal = ResponseHeader.build(function=FunctionCode.RESPONSE)

        assert restarted.device_restart is True
        assert normal.device_restart is False
