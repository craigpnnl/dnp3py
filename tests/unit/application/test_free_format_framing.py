"""#82 slice A: size-prefixed free-format blocks (qualifier 0x4B, 0x5B or 0x6B).

IEEE 1815-2012 Table 4-5 row B: the range field is a 1-octet object count.
Table 4-6: 0x4B/0x5B/0x6B are the only valid pairings for range code 0xB, one
per prefix width (Table 4-4: 1, 2 and 4-octet object size). Each object then
carries its own size field ahead of its data, since the group has no fixed or
registry width (4.2.2.7.3.3, range specifier code 0xB). Proved with g70
(A.27.1): objects are walked to find the next header, not decoded, so an
arbitrary payload of the declared length is enough.

Bytes built from the clauses, not from this library's own encoder, matching
the shape ``test_nonmeasurement_widths.py`` and
``test_octet_string_request_framing.py`` already use.
"""

import pytest

from dnp3.application.fragment import Truncation, TruncationReason
from dnp3.application.parser import (
    frame_request_object_blocks,
    frame_response_object_blocks,
    parse_response_object_blocks,
)
from dnp3.core.enums import FunctionCode
from dnp3.objects import AnalogInput32

# g30v1 (A.14.1: flag, INT32 little-endian), start-stop 0..0, ONLINE, value 42.
_G30V1_TAIL = bytes([0x1E, 0x01, 0x00, 0x00, 0x00]) + bytes([0x01]) + (42).to_bytes(4, "little", signed=True)
_G30V1_VALUE = 42

# g80v1 (A.28.1): clear DEVICE_RESTART, start-stop 7..7, one octet. Header-only
# functions never reach this; WRITE carries it so the request path is proved.
_G80V1 = bytes([80, 1, 0x00, 7, 7, 0x00])

# Qualifier 0x4B/0x5B/0x6B -> its per-object size field width in octets (Table 4-4).
_SIZE_FIELD_WIDTHS = {0x4B: 1, 0x5B: 2, 0x6B: 4}


def _decode_g30v1(data: bytes) -> AnalogInput32:
    """Decode the g30v1 object out of a start-stop block's data (2-byte range, then object)."""
    return AnalogInput32.from_bytes(data[2:])


def _sized_object(width: int, payload: bytes) -> bytes:
    """One free-format object: its own size field, then its payload."""
    return len(payload).to_bytes(width, byteorder="little") + payload


class TestG70BlockFramesAndStepsOver:
    """A g70 block under each qualifier width is bounded and the g30v1 block after it
    is reached intact, on the response path.
    """

    def test_block_then_g30v1(self) -> None:
        for qualifier, width in sorted(_SIZE_FIELD_WIDTHS.items()):
            payload = bytes([0xAA, 0xBB, 0xCC])
            count = bytes([1])
            obj = _sized_object(width, payload)
            data = bytes([70, 1, qualifier]) + count + obj + _G30V1_TAIL

            blocks = parse_response_object_blocks(data)

            assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)], (
                f"qualifier 0x{qualifier:02X}"
            )
            assert blocks[0].data == count + obj, f"qualifier 0x{qualifier:02X}"
            assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE, f"qualifier 0x{qualifier:02X}"

    def test_zero_length_object_frames_and_steps_over(self) -> None:
        count = bytes([1])
        obj = _sized_object(1, b"")
        data = bytes([70, 1, 0x4B]) + count + obj + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)]
        assert blocks[0].data == count + obj
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE

    def test_multiple_objects_walks_each_and_reaches_the_tail(self) -> None:
        first = _sized_object(1, bytes([0x01, 0x02]))
        second = _sized_object(1, bytes([0x03, 0x04, 0x05]))
        count = bytes([2])
        data = bytes([70, 1, 0x4B]) + count + first + second + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)]
        assert blocks[0].data == count + first + second
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE

    def test_count_zero_frames_an_empty_block(self) -> None:
        """Count 0 is a valid free-format block with no objects: the loop must
        run zero times, not be floored to one.
        """
        count = bytes([0])
        data = bytes([70, 1, 0x4B]) + count + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)]
        assert blocks[0].data == count
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE

    def test_zero_length_object_as_the_last_block(self) -> None:
        """A zero-length object whose size field exactly exhausts the data must
        still frame: the bounds check must not fire on an exact fit.
        """
        count = bytes([1])
        obj = _sized_object(1, b"")
        data = bytes([70, 1, 0x4B]) + count + obj

        blocks, truncation = frame_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1)]
        assert blocks[0].data == count + obj
        assert truncation is None


class TestFreeFormatObjectSizeUsesTheFullSizeField:
    """A declared size that does not fit in one octet must be read from the
    whole size field, not just its low byte (or, for 0x6B, its low 2 octets).
    """

    def test_0x5b_size_over_255(self) -> None:
        payload = bytes([0xAB]) * 300  # 300 needs both octets of the 2-octet field
        count = bytes([1])
        obj = _sized_object(2, payload)
        data = bytes([70, 1, 0x5B]) + count + obj + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)]
        assert blocks[0].data == count + obj
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE

    def test_0x6b_size_over_65535(self) -> None:
        payload = bytes([0xCD]) * 65536  # needs all 4 octets, not just the low 2
        count = bytes([1])
        obj = _sized_object(4, payload)
        data = bytes([70, 1, 0x6B]) + count + obj + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (30, 1)]
        assert blocks[0].data == count + obj
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE


class TestFreeFormatTruncation:
    """A count, a size field, or a declared payload running past the end stops the
    block, and every block before it stays framed.
    """

    def test_missing_count_field(self) -> None:
        data = bytes([70, 1, 0x4B])  # header only, no 1-octet count field

        blocks, truncation = frame_response_object_blocks(data)

        assert blocks == []
        assert truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 70, 1, 0x4B)

    def test_truncated_size_field(self) -> None:
        count = bytes([1])
        data = bytes([70, 1, 0x5B]) + count + bytes([0x03])  # 0x5B needs a 2-octet size field, gives 1

        blocks, truncation = frame_response_object_blocks(data)

        assert blocks == []
        assert truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 70, 1, 0x5B)

    def test_truncated_size_field_whose_present_octets_are_zero(self) -> None:
        """The bounds check must run before the octets are read: a truncated
        size field must stop the block even when its present bytes are zero,
        which would otherwise read as a (wrong) zero-length object.
        """
        count = bytes([1])
        data_5b = bytes([70, 1, 0x5B]) + count + bytes([0x00])  # needs 2 octets, gives 1
        data_6b = bytes([70, 1, 0x6B]) + count + bytes([0x00, 0x00, 0x00])  # needs 4 octets, gives 3

        blocks_5b, truncation_5b = frame_response_object_blocks(data_5b)
        blocks_6b, truncation_6b = frame_response_object_blocks(data_6b)

        assert blocks_5b == []
        assert truncation_5b == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 70, 1, 0x5B)
        assert blocks_6b == []
        assert truncation_6b == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 70, 1, 0x6B)

    def test_oversized_declared_size(self) -> None:
        count = bytes([1])
        obj = (10).to_bytes(1, "little") + bytes([0xAA, 0xBB])  # declares 10 octets, only 2 remain
        data = bytes([70, 1, 0x4B]) + count + obj

        blocks, truncation = frame_response_object_blocks(data)

        assert blocks == []
        assert truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, 0, 70, 1, 0x4B)

    def test_earlier_block_stays_framed_ahead_of_a_truncated_one(self) -> None:
        leading = _G30V1_TAIL
        count = bytes([1])
        truncated = bytes([70, 1, 0x4B]) + count + bytes([0x05]) + bytes([0xAA])  # declares 5, gives 1
        data = leading + truncated

        blocks, truncation = frame_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(30, 1)]
        assert truncation == Truncation(TruncationReason.DATA_SHORTER_THAN_DECLARED, len(leading), 70, 1, 0x4B)


class TestSizePrefixWithoutFreeFormatRangeUnchanged:
    """A size prefix paired with any range code other than 0xB is still a Table 4-6
    shaded cell (SIZE_PREFIX), exactly as at base.
    """

    def test_0x57_still_size_prefix(self) -> None:
        # 0x57: prefix 5 (UINT16_SIZE), range 7 (UINT8_COUNT). Table 4-6 shades this
        # cell; the gate fires from the header alone, before any range or object data.
        data = bytes([70, 1, 0x57])

        blocks, truncation = frame_response_object_blocks(data)

        assert blocks == []
        assert truncation == Truncation(TruncationReason.SIZE_PREFIX, 0, 70, 1, 0x57)


def _g83v1_pro() -> bytes:
    """g83v1 (A.31.1.2.2): VSTR4 vendor code, UINT16 identifier, UINT16 length, data."""
    vendor = b"TEST"
    identifier = (1).to_bytes(2, "little")
    payload = bytes([0xAA, 0xBB, 0xCC])
    length = len(payload).to_bytes(2, "little")
    return vendor + identifier + length + payload


def _descriptor_element(descriptor_code: int) -> bytes:
    """One data set descriptor element (A.32.1.2.2 g85v1 / A.33.1.2.2 g86v1), no ancillary value."""
    return bytes([3, descriptor_code, 0, 0])


def _g86v3_point_index() -> bytes:
    """g86v3 (A.33.3.2.2): UINT8 length, data set identifier, one point-index element."""
    identifier = bytes([0x01])
    element = bytes([2, 30, 0x00])  # element length, point type (group 30), point index
    return bytes([len(identifier)]) + identifier + element


def _g87_or_g88_snapshot(identifier: int) -> bytes:
    """A.34.1.2.2 (g87v1) / A.35.1.2.2 (g88v1): id length, id, time length (6), 6-octet
    time, zero data elements (the set-of-n is not decoded here, so n=0 is a valid object).
    """
    id_bytes = bytes([identifier])
    return bytes([len(id_bytes)]) + id_bytes + bytes([6]) + bytes(6)


def _g120v1_challenge() -> bytes:
    """g120v1 (A.45.1.2.2): CSQ, USR, MAC algorithm, reason, then challenge data
    (minimum 4 octets). A.45.1.2.3 mandates qualifier 0x5B.
    """
    csq = (1).to_bytes(4, "little")
    usr = (0).to_bytes(2, "little")
    return csq + usr + bytes([1, 0]) + bytes([0xDE, 0xAD, 0xBE, 0xEF])


def _g120v2_reply() -> bytes:
    """g120v2 (A.45.2.2.2): CSQ, USR, then a MAC value sized by the object prefix.
    A.45.2.2.3 mandates qualifier 0x5B.
    """
    csq = (1).to_bytes(4, "little")
    usr = (0).to_bytes(2, "little")
    return csq + usr + bytes([0x11, 0x22, 0x33, 0x44])


_FREE_FORMAT_ROWS = [
    pytest.param(83, 1, _g83v1_pro(), id="g83v1"),
    pytest.param(85, 1, _descriptor_element(1), id="g85v1"),
    pytest.param(86, 1, _descriptor_element(2), id="g86v1"),
    pytest.param(86, 3, _g86v3_point_index(), id="g86v3"),
    pytest.param(87, 1, _g87_or_g88_snapshot(1), id="g87v1"),
    pytest.param(88, 1, _g87_or_g88_snapshot(2), id="g88v1"),
    pytest.param(120, 1, _g120v1_challenge(), id="g120v1"),
    pytest.param(120, 2, _g120v2_reply(), id="g120v2"),
]


class TestOtherFreeFormatGroupsFrameAndStepOver:
    """Every group whose range code 0xB pairs with a size-prefix qualifier
    (Table 4-6) frames the same way, regardless of group: the walking loop
    never decodes the object, so a payload built by hand from its own Annex A
    clause frames identically to g70 (TestG70BlockFramesAndStepsOver). 0x5B
    (Table 4-7 preferred; mandatory for g120 per A.45.1.2.3 / A.45.2.2.3).
    """

    @pytest.mark.parametrize("group,variation,obj", _FREE_FORMAT_ROWS)
    def test_block_then_g30v1(self, group: int, variation: int, obj: bytes) -> None:
        count = bytes([1])
        sized = _sized_object(2, obj)
        data = bytes([group, variation, 0x5B]) + count + sized + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(group, variation), (30, 1)]
        assert blocks[0].data == count + sized
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE


class TestFreeFormatRequestPath:
    """A WRITE carrying a free-format block frames it the same way as a response:
    the new branch sits ahead of both length-lookup functions in the shared loop.
    """

    def test_write_of_g70_then_g80v1_frames_both(self) -> None:
        payload = bytes([0xAA, 0xBB, 0xCC])
        count = bytes([1])
        obj = _sized_object(1, payload)
        data = bytes([70, 1, 0x4B]) + count + obj + _G80V1

        blocks, truncation = frame_request_object_blocks(FunctionCode.WRITE, data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(70, 1), (80, 1)]
        assert blocks[0].data == count + obj
