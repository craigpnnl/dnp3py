"""Tests for application layer parser."""

import dataclasses

import pytest

import dnp3.application
from dnp3.application import parser
from dnp3.application.fragment import (
    ObjectBlock,
    RequestFragment,
    ResponseFragment,
    Truncation,
    TruncationReason,
)
from dnp3.application.header import RequestHeader, ResponseHeader
from dnp3.application.parser import (
    RESPONSE_FUNCTION_CODES,
    ParsedRange,
    ParseError,
    frame_response_object_blocks,
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

# Object bytes from IEEE 1815-2012, not from this library's encoders.
# g1v2 (A.2.2: flag octet, state in bit 7), start-stop 9..9, on.
_B1 = bytes.fromhex("01 02 00 09 09 81")
# g30v1 (A.14.1: flag, INT32 little-endian), count 1, index 7, value 200.
_G7 = bytes.fromhex("1E 01 17 01 07 01 C8 00 00 00")
_RESPONSE_HEADER = bytes([0xC0, 0x81, 0x00, 0x00])


def _block(wire: bytes) -> ObjectBlock:
    """The block a correct parser frames from exactly these wire bytes."""
    return ObjectBlock(header=ObjectHeader.from_bytes(wire), data=wire[3:])


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
        # RESPONSE + Group 1 Var 2 (binary with flags), start=0, stop=0, one flag octet
        data = b"\xc0\x81\x00\x00\x01\x02\x00\x00\x00\x81"
        fragment = parse_response(data)
        assert fragment.header.function == FunctionCode.RESPONSE
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.group == 1
        assert fragment.objects[0].data == b"\x00\x00\x81"

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
        # Range 0..4 and one g1v2 flag octet per point.
        block = ObjectBlock(header=obj_header, data=b"\x00\x04" + bytes([0x81, 0x01, 0x81, 0x01, 0x81]))
        original = ResponseFragment(header=header, objects=(block,))

        data = original.to_bytes()
        parsed = parse_response(data)

        assert parsed.header.function == original.header.function
        assert parsed.header.iin == original.header.iin
        assert parsed.header.control.seq == original.header.control.seq
        assert parsed.objects == original.objects
        assert parsed.truncation is None


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

    def test_leading_reserved_qualifier_returns_empty(self) -> None:
        """A reserved qualifier in the first block yields no blocks and a reason, not an error."""
        data = bytes([0x01, 0x02, 0x0C, 0x00, 0x00])

        assert frame_response_object_blocks(data) == (
            [],
            Truncation(TruncationReason.RESERVED_QUALIFIER, 0, 1, 2, 0x0C),
        )

    def test_short_object_data_drops_the_block_and_stops(self) -> None:
        """A block declaring more points than it carries is not returned, and parsing stops."""
        # g1v2 start=0 stop=4 declares 5 points but supplies 2 bytes.
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x04, 0x81, 0x01])

        assert frame_response_object_blocks(data) == (
            [],
            Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 1, 2, 0x00),
        )

    def test_partial_trailing_header_is_reported(self) -> None:
        """Fewer than 3 trailing bytes cannot be a header: they are not framed, and the stop is reported."""
        data = bytes([0x01, 0x02, 0x00, 0x00, 0x00, 0x81]) + bytes([0x1E, 0x01])

        assert frame_response_object_blocks(data) == (
            [ObjectBlock(header=ObjectHeader(1, 2, 0x00), data=bytes([0x00, 0x00, 0x81]))],
            Truncation(TruncationReason.TRAILING_OCTETS, 6),
        )

    def test_blocks_match_the_framed_blocks(self) -> None:
        data = _B1 + bytes([0x1E, 0x63, 0x00, 0x00, 0x00, 0x01, 0x64, 0x00, 0x00, 0x00]) + _G7

        assert parse_response_object_blocks(data) == frame_response_object_blocks(data)[0] == [_block(_B1)]

    def test_empty_data_returns_empty(self) -> None:
        assert parse_response_object_blocks(b"") == []

    def test_all_objects_qualifier_block(self) -> None:
        """An ALL_OBJECTS response block carries no range data and no values."""
        blocks = parse_response_object_blocks(bytes([0x3C, 0x01, 0x06]))

        assert len(blocks) == 1
        assert blocks[0].header.group == 60

    @pytest.mark.parametrize(("group", "variation"), [(30, 1), (200, 0)], ids=["g30v1-known", "g200v0-unknown"])
    def test_all_objects_block_with_index_prefix_frames_as_its_header(self, group: int, variation: int) -> None:
        header = bytes([group, variation, 0x16])

        assert frame_response_object_blocks(header + _G7) == ([_block(header), _block(_G7)], None)

    def test_all_objects_packed_block_with_index_prefix_stops(self) -> None:
        """IEEE 1815-2012 A.2.1 packs bits only over a contiguous range, so g1v1 with an index prefix has no length."""
        assert frame_response_object_blocks(bytes([0x01, 0x01, 0x16]) + _G7) == (
            [],
            Truncation(TruncationReason.PACKED_WITH_INDEX_PREFIX, 0, 1, 1, 0x16),
        )

    def test_all_objects_block_of_unknown_width_frames_as_its_header(self) -> None:
        """An ALL_OBJECTS block has no objects to size, so an unknown width does not stop framing."""
        data = bytes([0x1E, 0x63, 0x06]) + _G7

        assert frame_response_object_blocks(data) == ([_block(bytes([0x1E, 0x63, 0x06])), _block(_G7)], None)


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

        blocks, truncation = frame_response_object_blocks(data)

        assert blocks == [_block(_G30V1_BLOCK)]
        assert truncation == Truncation(TruncationReason.RANGE_NAMES_NO_OBJECT, 10, group, variation, 0x00)

    def test_registry_length_refuses_a_negative_count(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            parser._fixed_width_length(2, -1, 0)

    def test_registry_length_refuses_a_negative_width(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            parser._fixed_width_length(-1, 1, 0)

    def test_registry_length_refuses_a_negative_prefix_width(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            parser._fixed_width_length(2, 1, -1)


class TestResponseFramingStops:
    """Where a block cannot be framed, the blocks before it are returned, it is not, and the reason is given.

    Driven through `parse_response`, the path the master reads by. Offsets count from the first octet
    after the 4-octet response header.
    """

    @staticmethod
    def _parse(objects: bytes) -> ResponseFragment:
        return parse_response(_RESPONSE_HEADER + objects)

    def test_over_declared_count_returns_no_block_from_the_following_bytes(self) -> None:
        """Count 3 with one object present: the next block's bytes are never read as its objects (#103)."""
        fragment = self._parse(bytes.fromhex("1E 01 17 03 05 01 64 00 00 00") + _G7)

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 30, 1, 0x17)

    def test_over_declared_count_keeps_the_block_before(self) -> None:
        fragment = self._parse(_B1 + bytes.fromhex("1E 01 17 03 05 01 64 00 00 00") + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 6, 30, 1, 0x17)

    def test_misaligned_next_header_stops_at_the_unsizable_header(self) -> None:
        """Count 2 with one object present fits inside the fragment, so it frames; the named limit.

        The first block takes 12 octets of objects, the second object being the next block's
        first 6 octets, and the header found at offset 16 (g200v0) has no width.
        """
        objects = bytes.fromhex("1E 01 17 02 05 01 64 00 00 001E 01 17 01 07 01 C8 00 00 0001 02 00 09 09 81")

        fragment = self._parse(objects)

        assert fragment.objects == (_block(objects[:16]),)
        assert len(fragment.objects[0].data) == 1 + 12
        assert fragment.truncation == Truncation(TruncationReason.UNKNOWN_WIDTH, 16, 200, 0, 0x00)

    @pytest.mark.parametrize("stop", [0x04, 0x03], ids=["stop-is-start-minus-1", "stop-is-start-minus-2"])
    def test_start_stop_range_naming_no_object_is_dropped(self, stop: int) -> None:
        fragment = self._parse(_B1 + bytes([0x1E, 0x01, 0x00, 0x05, stop, 0x01, 0x10, 0x00, 0x00, 0x00]) + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.RANGE_NAMES_NO_OBJECT, 6, 30, 1, 0x00)

    def test_count_of_zero_is_not_refused(self) -> None:
        """Only a start-stop range can name no object; a count of 0 is a valid empty block."""
        empty = bytes([0x1E, 0x01, 0x17, 0x00])

        fragment = self._parse(empty + _G7)

        assert fragment.objects == (_block(empty), _block(_G7))
        assert fragment.truncation is None

    def test_request_headers_with_stop_below_start_do_not_raise(self) -> None:
        """A request carries no object data, so a start-stop range there is not checked for a length."""
        assert parse_object_headers(bytes([0x1E, 0x00, 0x00, 0x05, 0x03])) == [
            ObjectBlock(header=ObjectHeader(30, 0, 0x00), data=bytes([0x05, 0x03]))
        ]

    @pytest.mark.parametrize("qualifier", [0x03, 0x0B], ids=["virtual-address-1", "variable-format"])
    def test_unsupported_range_code_stops(self, qualifier: int) -> None:
        fragment = self._parse(_B1 + bytes([0x1E, 0x01, qualifier, 0x00, 0x00, 0x01, 0x64, 0x00, 0x00, 0x00]) + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.UNSUPPORTED_RANGE, 6, 30, 1, qualifier)

    def test_size_prefix_stops(self) -> None:
        fragment = self._parse(_B1 + bytes([0x02, 0x01, 0x47, 0x01, 0x01, 0x81]) + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.SIZE_PREFIX, 6, 2, 1, 0x47)

    @pytest.mark.parametrize(
        "qualifier",
        [0x0A, 0x0C, 0x0F, 0x70, 0x76],
        ids=["range-code-A", "range-code-C", "range-code-F", "prefix-code-7", "prefix-code-7-all-objects"],
    )
    def test_reserved_qualifier_stops(self, qualifier: int) -> None:
        fragment = self._parse(_B1 + bytes([0x01, 0x02, qualifier, 0x00, 0x00]))

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.RESERVED_QUALIFIER, 6, 1, 2, qualifier)

    def test_error_from_a_registered_size_is_not_reported_as_a_reserved_qualifier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_size(group: int, variation: int) -> int:
            raise ValueError("registered size failed")

        monkeypatch.setattr(parser.registry, "get_size", broken_size)

        with pytest.raises(ValueError, match="registered size failed"):
            self._parse(_B1 + bytes([0x63, 0x01, 0x00, 0x00, 0x00, 0xAB, 0xCD]))

    @pytest.mark.parametrize("size", [-1, -10])
    def test_negative_registered_size_stops(self, monkeypatch: pytest.MonkeyPatch, size: int) -> None:
        """A negative width gives no usable length, so no bytes are framed with the block."""
        monkeypatch.setattr(parser.registry, "get_size", lambda group, variation: size if group == 99 else None)

        fragment = self._parse(_B1 + bytes([0x63, 0x01, 0x00, 0x00, 0x00, 0xAB, 0xCD]) + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.UNKNOWN_WIDTH, 6, 99, 1, 0x00)

    def test_packed_block_with_index_prefix_stops(self) -> None:
        """IEEE 1815-2012 A.2.1 packs bits only over a contiguous range, so an index-prefixed g1v1 has no length."""
        fragment = self._parse(bytes([0x01, 0x01, 0x17, 0x02, 0x05, 0x81, 0x06, 0x01]) + _G7)

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.PACKED_WITH_INDEX_PREFIX, 0, 1, 1, 0x17)

    def test_unknown_variation_stops(self) -> None:
        """IEEE 1815-2012 A.14 defines g30v1 to g30v6 only, so g30v99 has no width."""
        fragment = self._parse(_B1 + bytes([0x1E, 0x63, 0x00, 0x00, 0x00, 0x01, 0x64, 0x00, 0x00, 0x00]) + _G7)

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.UNKNOWN_WIDTH, 6, 30, 99, 0x00)

    def test_short_last_block_is_dropped(self) -> None:
        """Start-stop 0..2 declares three g30v1 objects and one is present."""
        fragment = self._parse(_B1 + bytes([0x1E, 0x01, 0x00, 0x00, 0x02, 0x01, 0x64, 0x00, 0x00, 0x00]))

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 6, 30, 1, 0x00)

    def test_block_short_by_one_octet_is_dropped(self) -> None:
        fragment = self._parse(_B1 + bytes([0x1E, 0x01, 0x00, 0x00, 0x00, 0x01, 0x64, 0x00, 0x00]))

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 6, 30, 1, 0x00)

    def test_range_field_cut_short_stops(self) -> None:
        fragment = self._parse(bytes([0x01, 0x02, 0x00, 0x00]))

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 1, 2, 0x00)

    def test_trailing_octet_stops(self) -> None:
        fragment = self._parse(_B1 + bytes([0x1E]))

        assert fragment.objects == (_block(_B1),)
        assert fragment.truncation == Truncation(TruncationReason.TRAILING_OCTETS, 6)
        assert fragment.truncation.group is None

    def test_fully_framed_response_has_no_truncation(self) -> None:
        fragment = self._parse(_B1 + _G7)

        assert fragment.objects == (_block(_B1), _block(_G7))
        assert fragment.truncation is None


class TestTruncationType:
    def test_exported_from_the_application_package(self) -> None:
        assert dnp3.application.Truncation is Truncation
        assert dnp3.application.TruncationReason is TruncationReason
        assert {"Truncation", "TruncationReason"} <= set(dnp3.application.__all__)

    def test_is_frozen(self) -> None:
        truncation = Truncation(TruncationReason.TRAILING_OCTETS, 6)

        with pytest.raises(dataclasses.FrozenInstanceError):
            truncation.offset = 0  # type: ignore[misc]


# Request object blocks, built from IEEE 1815-2012 Annex A rather than this library's encoders.
# g12v1 (A.8.1), qualifier 0x17, one LATCH_ON object: code, count, on-time, off-time, status.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")


def _crob(index: int, count: int = 1) -> bytes:
    return bytes([0x0C, 0x01, 0x17, count, index]) + _CROB_BODY


# g41v1 (A.20.1: INT32, status), index 4, value 1000.
_G41V1 = bytes.fromhex("29 01 17 01 04 E8030000 00")
# g41v2 (A.20.2: INT16, status), index 3, value 100.
_G41V2 = bytes.fromhex("29 02 17 01 03 6400 00")
# g41v4 (A.20.4: FLT64, status), index 5, value 0.5.
_G41V4 = bytes.fromhex("29 04 17 01 05 000000000000E03F 00")
# g80v1 (A.28.1: one bit per indication), start-stop 7..7, bit clear.
_G80V1 = bytes.fromhex("50 01 00 07 07 00")
# g50v1 (A.23.1: DNP3TIME), count 1.
_G50V1 = bytes.fromhex("32 01 07 01 00E8764801 00")
_G60V1_ALL = bytes.fromhex("3C 01 06")

# Functions whose requests carry object headers but no object data (IEEE 1815-2012 4.4).
_HEADER_ONLY = frozenset(
    {
        FunctionCode.CONFIRM,
        FunctionCode.READ,
        FunctionCode.IMMEDIATE_FREEZE,
        FunctionCode.IMMEDIATE_FREEZE_NO_ACK,
        FunctionCode.FREEZE_CLEAR,
        FunctionCode.FREEZE_CLEAR_NO_ACK,
        FunctionCode.COLD_RESTART,
        FunctionCode.WARM_RESTART,
        FunctionCode.ENABLE_UNSOLICITED,
        FunctionCode.DISABLE_UNSOLICITED,
        FunctionCode.ASSIGN_CLASS,
        FunctionCode.DELAY_MEASURE,
        FunctionCode.RECORD_CURRENT_TIME,
    }
)
_REQUEST_FUNCTIONS = [fc for fc in FunctionCode if fc not in RESPONSE_FUNCTION_CODES]


def _request(function: FunctionCode, objects: bytes, seq: int = 3) -> RequestFragment:
    return parse_request(bytes([0xC0 | seq, function.value]) + objects)


class TestRequestBlocksAreFramedSeparately:
    """Each request object header gets its own block, sized by what the function carries."""

    @pytest.mark.parametrize(
        ("function", "wires"),
        [
            (FunctionCode.SELECT, [_crob(1), _crob(2)]),
            (FunctionCode.SELECT, [_crob(1), _G41V2]),
            (FunctionCode.OPERATE, [_G41V1, _G41V4]),
            (FunctionCode.DIRECT_OPERATE, [_crob(1), _crob(2)]),
            (FunctionCode.DIRECT_OPERATE_NO_ACK, [_G41V2, _crob(7)]),
            (FunctionCode.WRITE, [_G80V1, _G50V1]),
            (FunctionCode.WRITE, [_G50V1, _G80V1]),
        ],
        ids=[
            "select-two-crobs",
            "select-crob-and-g41v2",
            "operate-g41v1-and-g41v4",
            "direct-operate-two-crobs",
            "direct-operate-no-ack-g41v2-and-crob",
            "write-g80v1-then-g50v1",
            "write-g50v1-then-g80v1",
        ],
    )
    def test_object_blocks_are_each_sized_by_their_width(self, function: FunctionCode, wires: list[bytes]) -> None:
        fragment = _request(function, b"".join(wires))

        assert fragment.objects == tuple(_block(wire) for wire in wires)
        assert fragment.truncation is None

    def test_crob_block_data_is_its_count_index_and_eleven_octets(self) -> None:
        fragment = _request(FunctionCode.SELECT, _crob(1) + _crob(2))

        assert [block.data for block in fragment.objects] == [bytes([1, 1]) + _CROB_BODY, bytes([1, 2]) + _CROB_BODY]

    def test_ranged_read_of_two_groups_gives_each_its_range(self) -> None:
        fragment = _request(FunctionCode.READ, bytes.fromhex("01 02 00 00 01  1E 01 00 00 01"))

        assert [(b.header.group, b.header.variation, b.data) for b in fragment.objects] == [
            (1, 2, bytes([0x00, 0x01])),
            (30, 1, bytes([0x00, 0x01])),
        ]
        assert fragment.truncation is None

    def test_read_index_list_is_the_whole_block(self) -> None:
        fragment = _request(FunctionCode.READ, bytes.fromhex("01 02 17 03 01 04 09") + _G60V1_ALL)

        assert fragment.objects == (
            ObjectBlock(header=ObjectHeader(1, 2, 0x17), data=bytes([0x03, 0x01, 0x04, 0x09])),
            _block(_G60V1_ALL),
        )
        assert fragment.truncation is None

    def test_read_two_octet_index_list_is_sized_by_its_prefix(self) -> None:
        index_list = bytes.fromhex("1E 01 28 0200 0500 0001")

        fragment = _request(FunctionCode.READ, index_list + _G60V1_ALL)

        assert fragment.objects == (_block(index_list), _block(_G60V1_ALL))

    @pytest.mark.parametrize("function", _REQUEST_FUNCTIONS, ids=lambda fc: fc.name)
    def test_function_code_picks_header_only_or_object_framing(self, function: FunctionCode) -> None:
        """g1v2 index 5 then g60v1: header-only framing gives two blocks, object framing reads 0x3C as a value."""
        index_block = bytes.fromhex("01 02 17 01 05")

        fragment = _request(function, index_block + _G60V1_ALL)

        if function in _HEADER_ONLY:
            assert fragment.objects == (_block(index_block), _block(_G60V1_ALL))
            assert fragment.truncation is None
        else:
            assert fragment.objects == (_block(index_block + bytes([0x3C])),)
            assert fragment.truncation == Truncation(TruncationReason.TRAILING_OCTETS, 6)

    def test_header_only_start_stop_with_stop_below_start_is_its_range(self) -> None:
        fragment = _request(FunctionCode.READ, bytes([0x1E, 0x00, 0x00, 0x05, 0x03]) + _G60V1_ALL)

        assert fragment.objects == (_block(bytes([0x1E, 0x00, 0x00, 0x05, 0x03])), _block(_G60V1_ALL))
        assert fragment.truncation is None

    def test_parse_object_headers_consumes_the_index_list_only(self) -> None:
        assert parse_object_headers(bytes.fromhex("01 02 17 02 01 04") + _G60V1_ALL) == [
            _block(bytes.fromhex("01 02 17 02 01 04")),
            _block(_G60V1_ALL),
        ]

    def test_parse_object_headers_drops_what_cannot_be_framed(self) -> None:
        assert parse_object_headers(_G60V1_ALL + bytes([0x01, 0x02, 0x00, 0x00])) == [_block(_G60V1_ALL)]

    def test_request_with_no_objects_has_no_truncation(self) -> None:
        fragment = _request(FunctionCode.COLD_RESTART, b"")

        assert fragment.objects == ()
        assert fragment.truncation is None


class TestRequestFramingStops:
    """A request block that cannot be framed is absent, and so is every block after it.

    Offsets count from the first octet after the 2-octet request header.
    """

    def test_unknown_width_stops_at_the_unknown_block(self) -> None:
        """IEEE 1815-2012 Table 4-14 names g12v2 as an object this outstation does not know."""
        g12v2 = bytes([0x0C, 0x02, 0x17, 0x01, 0x02]) + _CROB_BODY

        fragment = _request(FunctionCode.SELECT, _crob(1) + g12v2 + _crob(3))

        assert fragment.objects == (_block(_crob(1)),)
        assert fragment.truncation == Truncation(TruncationReason.UNKNOWN_WIDTH, 16, 12, 2, 0x17)

    def test_last_block_declaring_more_objects_than_present_stops(self) -> None:
        fragment = _request(FunctionCode.SELECT, _crob(1) + _crob(2, count=2))

        assert fragment.objects == (_block(_crob(1)),)
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 16, 12, 1, 0x17)

    def test_reserved_qualifier_in_a_read_stops(self) -> None:
        fragment = _request(FunctionCode.READ, bytes.fromhex("01 02 00 00 01  1E 01 0A") + _G60V1_ALL)

        assert fragment.objects == (_block(bytes.fromhex("01 02 00 00 01")),)
        assert fragment.truncation == Truncation(TruncationReason.RESERVED_QUALIFIER, 5, 30, 1, 0x0A)

    def test_index_list_past_the_end_stops_a_read(self) -> None:
        fragment = _request(FunctionCode.READ, _G60V1_ALL + bytes.fromhex("01 02 17 03 01 04"))

        assert fragment.objects == (_block(_G60V1_ALL),)
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 3, 1, 2, 0x17)

    def test_range_field_cut_short_stops_a_read(self) -> None:
        fragment = _request(FunctionCode.READ, bytes([0x01, 0x02, 0x00, 0x00]))

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 1, 2, 0x00)

    @pytest.mark.parametrize("function", [FunctionCode.READ, FunctionCode.SELECT], ids=["read", "select"])
    @pytest.mark.parametrize(
        ("qualifier", "reason"),
        [(0x03, TruncationReason.UNSUPPORTED_RANGE), (0x47, TruncationReason.SIZE_PREFIX)],
        ids=["virtual-address-range", "size-prefix"],
    )
    def test_unsupported_qualifier_stops(
        self, function: FunctionCode, qualifier: int, reason: TruncationReason
    ) -> None:
        fragment = _request(function, bytes([0x0C, 0x01, qualifier, 0x01, 0x01]) + _CROB_BODY)

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(reason, 0, 12, 1, qualifier)

    def test_object_start_stop_naming_no_object_stops(self) -> None:
        fragment = _request(FunctionCode.SELECT, bytes([0x0C, 0x01, 0x00, 0x05, 0x04]) + _CROB_BODY)

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.RANGE_NAMES_NO_OBJECT, 0, 12, 1, 0x00)

    def test_packed_object_with_index_prefix_stops(self) -> None:
        fragment = _request(FunctionCode.WRITE, bytes.fromhex("50 01 17 01 07 00"))

        assert fragment.objects == ()
        assert fragment.truncation == Truncation(TruncationReason.PACKED_WITH_INDEX_PREFIX, 0, 80, 1, 0x17)

    @pytest.mark.parametrize("trailing", [bytes([0x01]), bytes([0x01, 0x02])], ids=["one", "two"])
    def test_trailing_octets_stop(self, trailing: bytes) -> None:
        fragment = _request(FunctionCode.READ, _G60V1_ALL + trailing)

        assert fragment.objects == (_block(_G60V1_ALL),)
        assert fragment.truncation == Truncation(TruncationReason.TRAILING_OCTETS, 3)
