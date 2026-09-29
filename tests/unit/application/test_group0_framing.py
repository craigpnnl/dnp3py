"""#82 slice B: group 0 device-attribute blocks (A.1, Table 12-1).

Each attribute object is a UINT8 attribute data type code, a UINT8 length,
then `length` octets of value (A.1.1.2.2, and every other A.1 variation's
formal structure): width per object is 2 + length. Table 12-1 (12.1.2) is
the line this module follows: READ (function 1) carries no group 0 attribute
data, only qualifiers 00 and 06 with no object body; WRITE (function 2) and
RESPONSE (129) carry the TLV, under qualifier 00 (start-stop, no prefix) or
0x17 (UINT8 index prefix, UINT8 count).

Bytes built from the clauses and their worked examples (5.5.5 EX 5-10,
5.5.6.2 EX 5-11), not from this library's own encoder, matching the shape
``test_free_format_framing.py`` uses for g70.
"""

from dnp3.application.parser import (
    frame_request_object_blocks,
    frame_response_object_blocks,
    parse_request,
)
from dnp3.core.enums import FunctionCode

# g30v1 (A.14.1: flag, INT32 little-endian), start-stop 0..0, ONLINE, value 42.
_G30V1_TAIL = bytes([0x1E, 0x01, 0x00, 0x00, 0x00]) + bytes([0x01]) + (42).to_bytes(4, "little", signed=True)
_G30V1_VALUE = 42

# g80v1 (A.28.1): clear DEVICE_RESTART, start-stop 7..7, one octet. WRITE
# carries it (test_free_format_framing.py proves this object frames the same
# way for g70), so it needs no group 0 data of its own here.
_G80V1 = bytes([80, 1, 0x00, 7, 7, 0x00])

# EX 5-11 (5.5.6.2): 26 attribute variations the example outstation supports,
# as UINT8 variation/property pairs (the object's opaque list value).
_EX_5_11_PAIRS = (
    (0xD9, 0x00), (0xDA, 0x00), (0xDB, 0x00), (0xDC, 0x00),
    (0xDD, 0x00), (0xDE, 0x00), (0xDF, 0x00), (0xE0, 0x00),
    (0xE1, 0x00), (0xE2, 0x00), (0xE3, 0x00), (0xE4, 0x00),
    (0xE5, 0x00), (0xE6, 0x00), (0xE7, 0x00), (0xE8, 0x00),
    (0xE9, 0x00), (0xED, 0x00), (0xEE, 0x00), (0xEF, 0x00),
    (0xF0, 0x01), (0xF1, 0x00), (0xF8, 0x00), (0xF9, 0x00),
    (0xFA, 0x00), (0xFC, 0x00),
)  # fmt: skip
_EX_5_11_VALUE = bytes(b for pair in _EX_5_11_PAIRS for b in pair)


def _decode_g30v1(data: bytes) -> int:
    """Decode the g30v1 INT32 value out of a block's data (2-byte range, 1-byte flag, then value)."""
    return int.from_bytes(data[3:7], byteorder="little", signed=True)


class TestGroup0ResponseFramesPerObjectTLV:
    """A response's group 0 block is framed by its own TLV width, and the
    block after it (g30v1) is reached intact.
    """

    def test_ex_5_10_start_stop_then_g30v1(self) -> None:
        # 5.5.5 EX 5-10: g0v241 (max receive fragment size), qualifier 0x00,
        # index 0, type UINT(2) length 2 value 0x05DC (1500).
        header = bytes([0, 241, 0x00])
        obj_range = bytes([0x00, 0x00])
        tlv = bytes([0x02, 0x02, 0xDC, 0x05])
        data = header + obj_range + tlv + _G30V1_TAIL

        blocks, truncation = frame_response_object_blocks(data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(0, 241), (30, 1)]
        assert blocks[0].data == obj_range + tlv
        assert int.from_bytes(blocks[0].data[4:6], "little") == 1500
        assert _decode_g30v1(blocks[1].data) == _G30V1_VALUE

    def test_ex_5_11_index_prefix_then_g30v1(self) -> None:
        # 5.5.6.2 EX 5-11: g0v255 (list of supported variations), qualifier
        # 0x17, index 0, type U8BS8LIST(0xFE) length 0x34 (52) value the pairs.
        header = bytes([0, 255, 0x17])
        obj_range = bytes([0x01])  # count 1
        index_prefix = bytes([0x00])
        type_length = bytes([0xFE, 0x34])
        data = header + obj_range + index_prefix + type_length + _EX_5_11_VALUE + _G30V1_TAIL

        blocks, truncation = frame_response_object_blocks(data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(0, 255), (30, 1)]
        assert blocks[0].data == obj_range + index_prefix + type_length + _EX_5_11_VALUE
        assert _decode_g30v1(blocks[1].data) == _G30V1_VALUE

    def test_zero_length_value_then_g30v1(self) -> None:
        """A declared length of 0 must frame as a valid, empty-value object,
        not be treated as absent.
        """
        header = bytes([0, 217, 0x00])
        obj_range = bytes([0x00, 0x00])
        tlv = bytes([0x01, 0x00])  # type VSTR(1), length 0, no value octets
        data = header + obj_range + tlv + _G30V1_TAIL

        blocks, truncation = frame_response_object_blocks(data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(0, 217), (30, 1)]
        assert blocks[0].data == obj_range + tlv
        assert _decode_g30v1(blocks[1].data) == _G30V1_VALUE


class TestGroup0RequestPath:
    """Table 12-1: READ carries no group 0 attribute data; WRITE does."""

    def test_read_request_unchanged(self) -> None:
        # 5.5.6.2 EX 5-11's own request: READ of g0v255 from index 0, header-only.
        data = bytes([0xC3, 0x01]) + bytes([0, 255, 0x00]) + bytes([0x00, 0x00])

        fragment = parse_request(data)

        assert fragment.truncation is None
        assert [(b.header.group, b.header.variation) for b in fragment.objects] == [(0, 255)]
        assert fragment.objects[0].data == bytes([0x00, 0x00])  # range only, no TLV walked

    def test_write_carries_data_then_g80v1(self) -> None:
        # g0v240 (Maximum Transmit Fragment Size): Table 12-1 lists it writable.
        header = bytes([0, 240, 0x00])
        obj_range = bytes([0x00, 0x00])
        tlv = bytes([0x02, 0x02, 0x00, 0x08])  # type UINT(2), length 2, value 2048
        data = header + obj_range + tlv + _G80V1

        blocks, truncation = frame_request_object_blocks(FunctionCode.WRITE, data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(0, 240), (80, 1)]
        assert blocks[0].data == obj_range + tlv
