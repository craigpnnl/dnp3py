"""Every qualifier octet against IEEE 1815-2012 Table 4-6.

Table 4-6 defines 19 valid (prefix, range) combinations. Every other octet,
including one with the reserved bit set (4.2.2.7.3.1), is not a defined
qualifier: parsing must stop rather than accept it (#112). The valid sweep
runs on both the request path (`frame_request_object_blocks`, header-only,
so a valid code needs no object value bytes) and the response path
(`frame_response_object_blocks`, which needs a real g30v1 value per object).
"""

import pytest

from dnp3.application.fragment import ObjectBlock, Truncation, TruncationReason
from dnp3.application.parser import frame_request_object_blocks, frame_response_object_blocks
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import FunctionCode

# IEEE 1815-2012 Table 4-6: the only qualifier octets a conforming header may carry.
_VALID_QUALIFIERS = frozenset(
    {
        0x00,
        0x01,
        0x02,
        0x06,
        0x07,
        0x08,
        0x09,
        0x17,
        0x18,
        0x19,
        0x27,
        0x28,
        0x29,
        0x37,
        0x38,
        0x39,
        0x4B,
        0x5B,
        0x6B,
    }
)

# One well-formed g30v1 header-only frame per valid qualifier: a start-stop or count
# range of 1 object at index/start 7, with an index list where the prefix needs one.
# 0x4B/0x5B/0x6B carry no range data (free-format is a library gap, not a wire rule).
_VALID_FRAMES = {
    0x00: bytes([0x1E, 0x01, 0x00, 0x07, 0x07]),
    0x01: bytes([0x1E, 0x01, 0x01, 0x07, 0x00, 0x07, 0x00]),
    0x02: bytes([0x1E, 0x01, 0x02, 0x07, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00]),
    0x06: bytes([0x1E, 0x01, 0x06]),
    0x07: bytes([0x1E, 0x01, 0x07, 0x01]),
    0x08: bytes([0x1E, 0x01, 0x08, 0x01, 0x00]),
    0x09: bytes([0x1E, 0x01, 0x09, 0x01, 0x00, 0x00, 0x00]),
    0x17: bytes([0x1E, 0x01, 0x17, 0x01, 0x07]),
    0x18: bytes([0x1E, 0x01, 0x18, 0x01, 0x00, 0x07]),
    0x19: bytes([0x1E, 0x01, 0x19, 0x01, 0x00, 0x00, 0x00, 0x07]),
    0x27: bytes([0x1E, 0x01, 0x27, 0x01, 0x07, 0x00]),
    0x28: bytes([0x1E, 0x01, 0x28, 0x01, 0x00, 0x07, 0x00]),
    0x29: bytes([0x1E, 0x01, 0x29, 0x01, 0x00, 0x00, 0x00, 0x07, 0x00]),
    0x37: bytes([0x1E, 0x01, 0x37, 0x01, 0x07, 0x00, 0x00, 0x00]),
    0x38: bytes([0x1E, 0x01, 0x38, 0x01, 0x00, 0x07, 0x00, 0x00, 0x00]),
    0x39: bytes([0x1E, 0x01, 0x39, 0x01, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00]),
    0x4B: bytes([0x1E, 0x01, 0x4B]),
    0x5B: bytes([0x1E, 0x01, 0x5B]),
    0x6B: bytes([0x1E, 0x01, 0x6B]),
}

# Free-format size prefixes are valid per Table 4-6 but this library cannot size them
# yet (UNSUPPORTED_RANGE, the same gap as a virtual-address range): a library gap, not
# a refused qualifier, so it must never surface as RESERVED_QUALIFIER or SIZE_PREFIX.
_FREE_FORMAT = frozenset({0x4B, 0x5B, 0x6B})

# g30v1 object value (A.14.1: flag, INT32 little-endian), the same encoding as _G7 in
# test_parser.py. A response block needs one of these per object; a request's header-only
# framing (READ) does not.
_G30V1_VALUE = bytes([0x01, 0xC8, 0x00, 0x00, 0x00])

# The response-path frame per valid qualifier: the request frame plus one object's value,
# except ALL_OBJECTS (no range, no objects) and the free-format codes (never reach an
# object length: they stop at UNSUPPORTED_RANGE before any value bytes would be read).
_VALID_RESPONSE_FRAMES = {
    qualifier: frame if qualifier == 0x06 or qualifier in _FREE_FORMAT else frame + _G30V1_VALUE
    for qualifier, frame in _VALID_FRAMES.items()
}


def _block(wire: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader.from_bytes(wire), data=wire[3:])


def _expected_reason(qualifier: int) -> TruncationReason:
    """Classify a refused qualifier from IEEE 1815-2012 directly (Tables 4-4, 4-5,
    4-6 and 4.2.2.7.3.1), independent of the parser under test.
    """
    if qualifier & 0x80:
        return TruncationReason.RESERVED_QUALIFIER
    prefix = (qualifier >> 4) & 0x07
    range_code = qualifier & 0x0F
    if prefix == 0x07 or range_code in {0x0A, 0x0C, 0x0D, 0x0E, 0x0F}:
        return TruncationReason.RESERVED_QUALIFIER
    if prefix in {0x01, 0x02, 0x03} and range_code not in {0x07, 0x08, 0x09}:
        return TruncationReason.RESERVED_QUALIFIER
    if range_code in {0x03, 0x04, 0x05, 0x0B}:
        return TruncationReason.UNSUPPORTED_RANGE
    # range in {0, 1, 2, 6, 7, 8, 9}: a size prefix (4 to 6) has no width for these.
    return TruncationReason.SIZE_PREFIX


@pytest.mark.parametrize("qualifier", sorted(_VALID_QUALIFIERS), ids=lambda q: f"0x{q:02X}")
def test_every_table_4_6_qualifier_is_accepted_on_the_request_path(qualifier: int) -> None:
    frame = _VALID_FRAMES[qualifier]

    blocks, truncation = frame_request_object_blocks(FunctionCode.READ, frame)

    if qualifier in _FREE_FORMAT:
        assert blocks == []
        assert truncation == Truncation(TruncationReason.UNSUPPORTED_RANGE, 0, 30, 1, qualifier)
    else:
        assert blocks == [_block(frame)]
        assert truncation is None


@pytest.mark.parametrize("qualifier", sorted(_VALID_QUALIFIERS), ids=lambda q: f"0x{q:02X}")
def test_every_table_4_6_qualifier_is_accepted_on_the_response_path(qualifier: int) -> None:
    frame = _VALID_RESPONSE_FRAMES[qualifier]

    blocks, truncation = frame_response_object_blocks(frame)

    if qualifier in _FREE_FORMAT:
        assert blocks == []
        assert truncation == Truncation(TruncationReason.UNSUPPORTED_RANGE, 0, 30, 1, qualifier)
    else:
        assert blocks == [_block(frame)]
        assert truncation is None


@pytest.mark.parametrize("qualifier", [q for q in range(256) if q not in _VALID_QUALIFIERS], ids=lambda q: f"0x{q:02X}")
def test_every_other_qualifier_is_refused(qualifier: int) -> None:
    """No object header carrying this octet frames, whatever group or variation it names."""
    blocks, truncation = frame_request_object_blocks(FunctionCode.READ, bytes([0x1E, 0x01, qualifier]))

    assert blocks == []
    assert truncation == Truncation(_expected_reason(qualifier), 0, 30, 1, qualifier)


def test_a_refused_qualifier_keeps_the_block_framed_before_it() -> None:
    """#112: the blocks before a refused qualifier are returned, not discarded."""
    leading = bytes([0x1E, 0x01, 0x06])  # g30v1, all-objects: frames with no range data.
    data = leading + bytes([0x1E, 0x01, 0x16])  # index prefix with all-objects: not in Table 4-6.

    blocks, truncation = frame_request_object_blocks(FunctionCode.READ, data)

    assert blocks == [_block(leading)]
    assert truncation == Truncation(TruncationReason.RESERVED_QUALIFIER, 3, 30, 1, 0x16)


def test_reserved_bit_is_refused_independently_of_the_seven_bits_below_it() -> None:
    """4.2.2.7.3.1: bit 7 is reserved, so setting it on an otherwise-valid octet still refuses."""
    blocks, truncation = frame_request_object_blocks(FunctionCode.READ, bytes([0x1E, 0x01, 0x86]))

    assert blocks == []
    assert truncation == Truncation(TruncationReason.RESERVED_QUALIFIER, 0, 30, 1, 0x86)
