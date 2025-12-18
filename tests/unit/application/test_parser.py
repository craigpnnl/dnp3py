"""Tests for application layer parser."""

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader, ResponseHeader
from dnp3.application.parser import (
    RESPONSE_FUNCTION_CODES,
    ParsedRange,
    ParseError,
    is_request,
    is_response,
    parse_object_headers,
    parse_request,
    parse_request_header,
    parse_response,
    parse_response_header,
)
from dnp3.application.qualifiers import ObjectHeader, PrefixCode, RangeCode
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN


class TestResponseFunctionCodes:
    """Tests for RESPONSE_FUNCTION_CODES constant."""

    def test_contains_response(self) -> None:
        """RESPONSE is in set."""
        assert FunctionCode.RESPONSE in RESPONSE_FUNCTION_CODES

    def test_contains_unsolicited(self) -> None:
        """UNSOLICITED_RESPONSE is in set."""
        assert FunctionCode.UNSOLICITED_RESPONSE in RESPONSE_FUNCTION_CODES

    def test_does_not_contain_read(self) -> None:
        """READ is not in set."""
        assert FunctionCode.READ not in RESPONSE_FUNCTION_CODES


class TestParsedRange:
    """Tests for ParsedRange dataclass."""

    def test_create(self) -> None:
        """Create ParsedRange."""
        r = ParsedRange(start=0, stop=9, count=10, bytes_consumed=2)
        assert r.start == 0
        assert r.stop == 9
        assert r.count == 10
        assert r.bytes_consumed == 2


class TestParseRequestHeader:
    """Tests for parse_request_header function."""

    def test_parse_read_request(self) -> None:
        """Parse READ request header."""
        data = b"\xc0\x01"  # FIR=1, FIN=1, READ
        header, consumed = parse_request_header(data)
        assert header.function == FunctionCode.READ
        assert header.control.fir is True
        assert header.control.fin is True
        assert consumed == 2

    def test_parse_write_request(self) -> None:
        """Parse WRITE request header."""
        data = b"\xc0\x02"  # FIR=1, FIN=1, WRITE
        header, consumed = parse_request_header(data)
        assert header.function == FunctionCode.WRITE
        assert consumed == 2

    def test_parse_with_sequence(self) -> None:
        """Parse request with sequence number."""
        data = b"\xc5\x01"  # FIR=1, FIN=1, SEQ=5, READ
        header, consumed = parse_request_header(data)
        assert header.control.seq == 5
        assert consumed == 2

    def test_too_short_raises(self) -> None:
        """Too short data raises ParseError."""
        with pytest.raises(ParseError, match="requires 2 bytes"):
            parse_request_header(b"\xc0")

    def test_empty_raises(self) -> None:
        """Empty data raises ParseError."""
        with pytest.raises(ParseError, match="requires 2 bytes"):
            parse_request_header(b"")

    def test_unknown_function_raises(self) -> None:
        """Unknown function code raises ParseError."""
        with pytest.raises(ParseError, match="Unknown function code"):
            parse_request_header(b"\xc0\xff")


class TestParseResponseHeader:
    """Tests for parse_response_header function."""

    def test_parse_response(self) -> None:
        """Parse RESPONSE header."""
        data = b"\xc0\x81\x00\x00"  # FIR=1, FIN=1, RESPONSE, IIN=0
        header, consumed = parse_response_header(data)
        assert header.function == FunctionCode.RESPONSE
        assert header.iin == IIN(0)
        assert consumed == 4

    def test_parse_with_iin(self) -> None:
        """Parse response with IIN flags."""
        data = b"\xc0\x81\x80\x00"  # DEVICE_RESTART set
        header, consumed = parse_response_header(data)
        assert header.iin & IIN.DEVICE_RESTART
        assert consumed == 4

    def test_parse_unsolicited(self) -> None:
        """Parse unsolicited response."""
        data = b"\xf0\x82\x00\x00"  # UNS=1, UNSOLICITED_RESPONSE
        header, consumed = parse_response_header(data)
        assert header.function == FunctionCode.UNSOLICITED_RESPONSE
        assert header.control.uns is True
        assert consumed == 4

    def test_too_short_raises(self) -> None:
        """Too short data raises ParseError."""
        with pytest.raises(ParseError, match="requires 4 bytes"):
            parse_response_header(b"\xc0\x81\x00")


class TestParseObjectHeaders:
    """Tests for parse_object_headers function."""

    def test_empty_data(self) -> None:
        """Empty data returns empty list."""
        blocks = parse_object_headers(b"")
        assert blocks == []

    def test_single_header_all_objects(self) -> None:
        """Parse single header with ALL_OBJECTS qualifier."""
        # Group 1, Var 0, Qualifier 0x06 (ALL_OBJECTS)
        data = b"\x01\x00\x06"
        blocks = parse_object_headers(data)
        assert len(blocks) == 1
        assert blocks[0].header.group == 1
        assert blocks[0].header.variation == 0
        assert blocks[0].header.range_code == RangeCode.ALL_OBJECTS

    def test_single_header_start_stop(self) -> None:
        """Parse single header with 1-byte start-stop."""
        # Group 1, Var 2, Qualifier 0x00 (UINT8_START_STOP), Start=0, Stop=4
        data = b"\x01\x02\x00\x00\x04"
        blocks = parse_object_headers(data)
        assert len(blocks) == 1
        assert blocks[0].header.group == 1
        assert blocks[0].header.variation == 2
        # Data should include range specifier
        assert blocks[0].data == b"\x00\x04"

    def test_multiple_headers(self) -> None:
        """Parse multiple headers."""
        # Header 1: Group 1, Var 0, Qualifier 0x06 (ALL_OBJECTS)
        # Header 2: Group 2, Var 0, Qualifier 0x06 (ALL_OBJECTS)
        data = b"\x01\x00\x06\x02\x00\x06"
        blocks = parse_object_headers(data)
        assert len(blocks) == 2
        assert blocks[0].header.group == 1
        assert blocks[1].header.group == 2

    def test_insufficient_data_stops_parsing(self) -> None:
        """Insufficient data for next header stops parsing."""
        # Complete header + partial header
        data = b"\x01\x00\x06\x02\x00"
        blocks = parse_object_headers(data)
        assert len(blocks) == 1


class TestParseRequest:
    """Tests for parse_request function."""

    def test_parse_integrity_poll(self) -> None:
        """Parse integrity poll (READ class 0)."""
        # READ + Class 0 (Group 60 Var 1 ALL_OBJECTS)
        data = b"\xc0\x01\x3c\x01\x06"
        fragment = parse_request(data)
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.group == 60
        assert fragment.objects[0].header.variation == 1

    def test_parse_class_123_poll(self) -> None:
        """Parse event poll (READ class 1, 2, 3)."""
        # READ + Class 1 + Class 2 + Class 3
        data = b"\xc0\x01\x3c\x02\x06\x3c\x03\x06\x3c\x04\x06"
        fragment = parse_request(data)
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 3
        assert fragment.objects[0].header.variation == 2  # Class 1
        assert fragment.objects[1].header.variation == 3  # Class 2
        assert fragment.objects[2].header.variation == 4  # Class 3

    def test_parse_binary_input_read(self) -> None:
        """Parse READ for binary inputs 0-9."""
        # READ + Group 1 Var 2, start=0, stop=9
        data = b"\xc0\x01\x01\x02\x00\x00\x09"
        fragment = parse_request(data)
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.group == 1
        assert fragment.objects[0].header.variation == 2
        # Range data (start, stop)
        assert fragment.objects[0].data == b"\x00\x09"

    def test_properties(self) -> None:
        """Fragment properties work."""
        data = b"\xc5\x01"  # READ, SEQ=5
        fragment = parse_request(data)
        assert fragment.is_only is True
        assert fragment.sequence == 5


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_null_response(self) -> None:
        """Parse null response (no objects)."""
        data = b"\xc0\x81\x00\x00"
        fragment = parse_response(data)
        assert fragment.header.function == FunctionCode.RESPONSE
        assert len(fragment.objects) == 0

    def test_parse_with_iin(self) -> None:
        """Parse response with IIN flags."""
        data = b"\xc0\x81\x80\x00"  # DEVICE_RESTART
        fragment = parse_response(data)
        assert fragment.header.iin & IIN.DEVICE_RESTART

    def test_parse_with_objects(self) -> None:
        """Parse response with object data."""
        # RESPONSE + Group 1 Var 2 (binary with flags), start=0, stop=0
        data = b"\xc0\x81\x00\x00\x01\x02\x00\x00\x00"
        fragment = parse_response(data)
        assert fragment.header.function == FunctionCode.RESPONSE
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.group == 1

    def test_unsolicited_properties(self) -> None:
        """Unsolicited response properties work."""
        data = b"\xf0\x82\x00\x00"  # UNS=1, UNSOLICITED_RESPONSE
        fragment = parse_response(data)
        assert fragment.is_unsolicited is True


class TestIsRequest:
    """Tests for is_request function."""

    def test_read_is_request(self) -> None:
        """READ is a request."""
        data = b"\xc0\x01"  # READ
        assert is_request(data) is True

    def test_write_is_request(self) -> None:
        """WRITE is a request."""
        data = b"\xc0\x02"  # WRITE
        assert is_request(data) is True

    def test_response_is_not_request(self) -> None:
        """RESPONSE is not a request."""
        data = b"\xc0\x81\x00\x00"  # RESPONSE
        assert is_request(data) is False

    def test_unsolicited_is_not_request(self) -> None:
        """UNSOLICITED_RESPONSE is not a request."""
        data = b"\xf0\x82\x00\x00"  # UNSOLICITED_RESPONSE
        assert is_request(data) is False

    def test_too_short_returns_false(self) -> None:
        """Too short data returns False."""
        assert is_request(b"\xc0") is False
        assert is_request(b"") is False


class TestIsResponse:
    """Tests for is_response function."""

    def test_response_is_response(self) -> None:
        """RESPONSE is a response."""
        data = b"\xc0\x81\x00\x00"
        assert is_response(data) is True

    def test_unsolicited_is_response(self) -> None:
        """UNSOLICITED_RESPONSE is a response."""
        data = b"\xf0\x82\x00\x00"
        assert is_response(data) is True

    def test_read_is_not_response(self) -> None:
        """READ is not a response."""
        data = b"\xc0\x01"
        assert is_response(data) is False

    def test_write_is_not_response(self) -> None:
        """WRITE is not a response."""
        data = b"\xc0\x02"
        assert is_response(data) is False

    def test_too_short_returns_false(self) -> None:
        """Too short data returns False."""
        assert is_response(b"\xc0") is False
        assert is_response(b"") is False


class TestRoundtrip:
    """Tests for serialization/parsing roundtrips."""

    def test_request_roundtrip(self) -> None:
        """Request survives serialize/parse roundtrip."""
        header = RequestHeader.build(function=FunctionCode.READ, seq=7)
        obj_header = ObjectHeader.build(
            group=60,
            variation=1,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        block = ObjectBlock(header=obj_header)
        original = RequestFragment(header=header, objects=(block,))

        data = original.to_bytes()
        parsed = parse_request(data)

        assert parsed.header.function == original.header.function
        assert parsed.header.control.seq == original.header.control.seq
        assert len(parsed.objects) == len(original.objects)
        assert parsed.objects[0].header.group == original.objects[0].header.group

    def test_response_roundtrip(self) -> None:
        """Response survives serialize/parse roundtrip."""
        header = ResponseHeader.build(
            function=FunctionCode.RESPONSE,
            iin=IIN.DEVICE_RESTART,
            seq=3,
        )
        obj_header = ObjectHeader.build(
            group=1,
            variation=2,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.UINT8_START_STOP,
        )
        block = ObjectBlock(header=obj_header, data=b"\x00\x04")
        original = ResponseFragment(header=header, objects=(block,))

        data = original.to_bytes()
        parsed = parse_response(data)

        assert parsed.header.function == original.header.function
        assert parsed.header.iin == original.header.iin
        assert parsed.header.control.seq == original.header.control.seq
        assert len(parsed.objects) == len(original.objects)
