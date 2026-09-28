"""Tests for application layer parser."""

import pytest

from dnp3.application import parser
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
    parse_response_object_blocks,
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


class TestParseResponseObjectBlocks:
    """Tests for size-aware response block delimiting.

    `parse_response_object_blocks` bounds each block by its object width so the
    next block's header can be found. `parse_object_headers` (requests) must not
    do this, because a request carries no object data.
    """

    def test_two_blocks_are_delimited_by_object_size(self) -> None:
        """g1v2 with one point, then a g30v1 block, yields two blocks."""
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x00, 0x81]) + bytes(
            [0x1E, 0x01, 0x00, 0x00, 0x00, 0x01, 0x61, 0x09, 0x00, 0x00]
        )
        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(1, 2), (30, 1)]

    def test_unknown_group_absorbs_remainder(self) -> None:
        """A group/variation with no known width consumes the rest of the fragment.

        IEEE 1815-2012 A.14 defines g30v1 to g30v6 only, so g30v99 has no width; it
        takes the remaining bytes rather than guessing a boundary.
        """
        data = bytes([0x1E, 0x63, 0x00, 0x00, 0x00, 0x01, 0x09, 0x03]) + bytes([0x01, 0x02, 0x00, 0x00, 0x00, 0x81])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert (blocks[0].header.group, blocks[0].header.variation) == (30, 99)
        assert blocks[0].data == data[3:]

    def test_reserved_qualifier_stops_parsing_without_raising(self) -> None:
        """A reserved range code has no decodable width.

        Parsing stops and returns the blocks already found, rather than raising
        and discarding the whole response.
        """
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x00, 0x81]) + bytes([0x01, 0x02, 0x0C, 0x00, 0x00])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert blocks[0].header.group == 1

    def test_leading_reserved_qualifier_returns_empty(self) -> None:
        """A reserved qualifier in the first block yields no blocks, not an error."""
        assert parse_response_object_blocks(bytes([0x01, 0x02, 0x0C, 0x00, 0x00])) == []

    def test_short_object_data_keeps_block_and_stops(self) -> None:
        """A block declaring more points than it carries is kept, then parsing stops."""
        # g1v2 start=0 stop=4 declares 5 points but supplies 2 bytes.
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x04, 0x81, 0x01])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert blocks[0].header.group == 1
        assert blocks[0].data == bytes([0x00, 0x04, 0x81, 0x01])

    def test_partial_trailing_header_is_ignored(self) -> None:
        """Fewer than 3 trailing bytes cannot be a header and are dropped."""
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x00, 0x81]) + bytes([0x1E, 0x01])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1

    def test_empty_data_returns_empty(self) -> None:
        assert parse_response_object_blocks(b"") == []

    def test_all_objects_qualifier_block(self) -> None:
        """An ALL_OBJECTS response block carries no range data and no values."""
        blocks = parse_response_object_blocks(bytes([0x3C, 0x01, 0x06]))

        assert len(blocks) == 1
        assert blocks[0].header.group == 60

    def test_virtual_address_range_absorbs_remainder(self) -> None:
        """A range specifier with no defined width cannot bound the block."""
        data = bytes([0x01, 0x02, 0x0B, 0x00, 0x00, 0x81]) + bytes([0x1E, 0x01, 0x00, 0x00, 0x00])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert blocks[0].header.group == 1

    def test_size_prefix_absorbs_remainder(self) -> None:
        """Size-prefixed (variable-format) objects have no registry width."""
        data = bytes([0x02, 0x01, 0x47, 0x01, 0x01, 0x81]) + bytes([0x1E, 0x01, 0x00, 0x00, 0x00])
        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert blocks[0].header.group == 2


# A g30v1 block (A.14.1: flag, INT32) at index 0, placed after the block under test.
_G30V1_BLOCK = bytes([0x1E, 0x01, 0x00, 0x00, 0x00, 0x01, 0x61, 0x09, 0x00, 0x00])


class TestResponseBlocksFramedFromLayout:
    """Each response block is bounded by its own data length, so the block after it is found.

    Widths are the Annex A formal structures of IEEE 1815-2012, written as literals.
    """

    @pytest.mark.parametrize(
        ("group", "variation", "width"),
        [
            (40, 1, 5),  # A.19.1: flag, INT32
            (40, 2, 3),  # A.19.2: flag, INT16
            (40, 3, 5),  # A.19.3: flag, FLT32
            (40, 4, 9),  # A.19.4: flag, FLT64
            (42, 1, 5),  # A.21.1: flag, INT32
            (42, 2, 3),  # A.21.2: flag, INT16
            (42, 3, 11),  # A.21.3: flag, INT32, DNP3TIME
            (42, 4, 9),  # A.21.4: flag, INT16, DNP3TIME
            (42, 5, 5),  # A.21.5: flag, FLT32
            (42, 6, 9),  # A.21.6: flag, FLT64
            (42, 7, 11),  # A.21.7: flag, FLT32, DNP3TIME
            (42, 8, 15),  # A.21.8: flag, FLT64, DNP3TIME
        ],
    )
    @pytest.mark.parametrize(
        "framing",
        [(0x00, bytes([0x05, 0x06]), b""), (0x17, bytes([0x02]), bytes([0x09]))],
        ids=["start-stop", "count-index"],
    )
    def test_octet_aligned_block_then_g30v1(
        self, group: int, variation: int, width: int, framing: tuple[int, bytes, bytes]
    ) -> None:
        qualifier, range_field, prefix = framing
        objects = b"".join(prefix + bytes(range(0x10 * n + 1, 0x10 * n + 1 + width)) for n in range(2))
        data = bytes([group, variation, qualifier]) + range_field + objects + _G30V1_BLOCK

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(group, variation), (30, 1)]
        assert blocks[0].data == range_field + objects
        assert blocks[1].data == _G30V1_BLOCK[3:]

    @pytest.mark.parametrize(
        ("group", "variation", "stop", "octets"),
        [
            (1, 1, 17, 3),  # A.2.1: 18 points, 1 bit each, last octet padded
            (1, 1, 7, 1),  # 8 points fill one octet exactly
            (1, 1, 8, 2),  # 9 points spill one bit into a second octet
            (10, 1, 0, 1),  # A.6.1: 1 point, 1 bit
            (3, 1, 4, 2),  # A.4.1: 5 points, 2 bits each
            (3, 1, 3, 1),  # 4 points fill one octet exactly
        ],
    )
    def test_packed_block_then_g30v1(self, group: int, variation: int, stop: int, octets: int) -> None:
        packed = bytes([0xE4, 0x5A, 0x03])[:octets]
        data = bytes([group, variation, 0x00, 0x00, stop]) + packed + _G30V1_BLOCK

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(group, variation), (30, 1)]
        assert blocks[0].data == bytes([0x00, stop]) + packed
        assert blocks[1].data == _G30V1_BLOCK[3:]

    def test_packed_block_with_index_prefix_absorbs_remainder(self) -> None:
        """A.2.1 packs bits only over a contiguous range, so an index-prefixed g1v1 block has no length."""
        data = bytes([0x01, 0x01, 0x17, 0x02, 0x05, 0x81, 0x06, 0x01]) + _G30V1_BLOCK

        blocks = parse_response_object_blocks(data)

        assert len(blocks) == 1
        assert (blocks[0].header.group, blocks[0].header.variation) == (1, 1)
        assert blocks[0].data == data[3:]

    @pytest.mark.parametrize(
        "framing",
        [
            (0x00, bytes([0x00, 0x01]), b""),
            (0x17, bytes([0x02]), bytes([0x07])),
            (0x28, bytes([0x02, 0x00]), bytes([0x07, 0x01])),
        ],
        ids=["start-stop", "count-index8", "count-index16"],
    )
    def test_pair_without_layout_is_sized_by_the_registry(
        self, monkeypatch: pytest.MonkeyPatch, framing: tuple[int, bytes, bytes]
    ) -> None:
        """A registered object with no layout row is bounded by its registered size and index prefix."""
        _register_g99v1_width_2(monkeypatch)
        qualifier, range_field, prefix = framing
        objects = prefix + bytes([0xAB, 0xCD]) + prefix + bytes([0xEF, 0x12])
        data = bytes([0x63, 0x01, qualifier]) + range_field + objects + _G30V1_BLOCK

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(99, 1), (30, 1)]
        assert blocks[0].data == range_field + objects
        assert blocks[1].data == _G30V1_BLOCK[3:]


def _register_g99v1_width_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make g99v1, a pair with no layout row, a registered 2-octet object for one test."""
    sizes = {(99, 1): 2}
    monkeypatch.setattr(parser.registry, "get_size", lambda group, variation: sizes.get((group, variation)))


class TestStartStopRangeBelowOneObject:
    """IEEE 1815-2012 4.2.2.7.3.3: a start-stop range runs from the start index up to the stop index.

    Identical indexes name one object, so a stop index below the start index describes no
    object sequence at all, and the block's length cannot locate the next header.
    """

    @pytest.mark.parametrize(
        ("group", "variation", "tail"),
        [
            (30, 1, bytes([0x01, 0x61, 0x09, 0x00, 0x00])),
            (1, 1, bytes([0xFF])),
            (99, 1, bytes([0xAB, 0xCD, 0x00, 0x00, 0x00])),
        ],
        ids=["g30v1-layout", "g1v1-packed", "g99v1-registry"],
    )
    @pytest.mark.parametrize("stop", [0x04, 0x03], ids=["stop-is-start-minus-1", "stop-is-start-minus-2"])
    def test_block_before_is_kept_and_nothing_is_framed_from_the_malformed_block(
        self, monkeypatch: pytest.MonkeyPatch, group: int, variation: int, tail: bytes, stop: int
    ) -> None:
        _register_g99v1_width_2(monkeypatch)
        data = _G30V1_BLOCK + bytes([group, variation, 0x00, 0x05, stop]) + tail + _G30V1_BLOCK

        blocks = parse_response_object_blocks(data)

        assert (blocks[0].header.group, blocks[0].header.variation) == (30, 1)
        assert blocks[0].data == _G30V1_BLOCK[3:]
        assert {(b.header.group, b.header.variation) for b in blocks[1:]} <= {(group, variation)}
        assert len(blocks) <= 2

    def test_registry_length_refuses_a_negative_count(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            parser._fixed_width_length(2, -1, 0)

    def test_registry_length_refuses_a_negative_prefix_width(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            parser._fixed_width_length(2, 1, -1)
