"""Framing tests for #82's non-measurement objects.

Each new layout row (g86v2, g101v1-3, g102v1, g120v3, g121v1, g122v1-2), and
g110/g111's variation-is-width special case, is proved by the same shape the
library already uses for a measurement group: one block of that group,
followed by a g30v1 block, both framed and the g30v1 value delivered intact.
Widths are IEEE 1815-2012 Annex A, cited beside each row or class.
"""

import pytest

from dnp3.application.parser import parse_response_object_blocks
from dnp3.objects import AnalogInput32
from dnp3.objects.layout import layout_for

# g30v1 (A.14.1: flag, INT32 little-endian), start-stop 0..0, ONLINE, value 42.
_G30V1_TAIL = bytes([0x1E, 0x01, 0x00, 0x00, 0x00]) + bytes([0x01]) + (42).to_bytes(4, "little", signed=True)
_G30V1_VALUE = 42


def _decode_g30v1(data: bytes) -> AnalogInput32:
    """Decode the g30v1 object out of a start-stop block's data (2-byte range, then object)."""
    return AnalogInput32.from_bytes(data[2:])


class TestFixedWidthRowsFrameAndStepOver:
    """A block of each new group is bounded and the g30v1 block after it is reached intact."""

    @pytest.mark.parametrize(
        ("group", "variation", "width"),
        [
            (86, 2, 1),  # A.33.2: BSTR4
            (101, 1, 2),  # A.39.1: BCD4, 4 digits, 2 octets
            (101, 2, 4),  # A.39.2: BCD8, 8 digits, 4 octets
            (101, 3, 8),  # A.39.3: BCD16, 16 digits, 8 octets
            (102, 1, 1),  # A.40.1: UINT8
            (120, 3, 6),  # A.45.3: UINT32 CSQ, UINT16 user number
            (121, 1, 7),  # A.46.1: flag, UINT16, UINT32
            (122, 1, 7),  # A.47.1: flag, UINT16, UINT32
            (122, 2, 13),  # A.47.2: as g122v1, plus DNP3TIME
        ],
    )
    @pytest.mark.parametrize(
        "framing",
        [(0x00, bytes([0x05, 0x06]), b""), (0x17, bytes([0x02]), bytes([0x09]))],
        ids=["start-stop", "count-index"],
    )
    def test_block_then_g30v1(self, group: int, variation: int, width: int, framing: tuple[int, bytes, bytes]) -> None:
        assert layout_for(group, variation) is not None, f"g{group}v{variation} has no layout row"
        qualifier, range_field, prefix = framing
        objects = b"".join(prefix + bytes(range(0x10 * n + 1, 0x10 * n + 1 + width)) for n in range(2))
        data = bytes([group, variation, qualifier]) + range_field + objects + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(group, variation), (30, 1)]
        assert blocks[0].data == range_field + objects
        assert blocks[1].data == _G30V1_TAIL[3:]
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE

    def test_control_group_zero_is_still_unsized(self) -> None:
        """g0v1 is outside this slice (its width is a per-object TLV, not a table row):

        it must still lose the g30v1 block after it, exactly as before this change.
        """
        data = bytes([0x00, 0x01, 0x00, 0x00, 0x00]) + bytes([0x02, 0x02, 0x05, 0xDC]) + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert blocks == []


class TestOctetStringGroupsFrameAndStepOver:
    """g110 (A.41.1) and g111 (A.42.1): width equals the variation number
    (OSTRn), computed at lookup time rather than read from a table row, so
    a block is still bounded and the g30v1 block after it is reached intact.
    Index-prefixed (qualifier 0x17): A.41.1.2.3 alone notes reading and
    writing an octet string by absolute (index) addressing; A.42.1.2.3 only
    lists g111's permitted function codes.
    """

    @pytest.mark.parametrize("group", [110, 111], ids=["g110", "g111"])
    @pytest.mark.parametrize("variation", [1, 5, 255])
    def test_block_then_g30v1(self, group: int, variation: int) -> None:
        assert layout_for(group, variation) is not None, f"g{group}v{variation} has no layout"
        qualifier = 0x17  # prefix code 1 (UINT8_INDEX), range code 7 (UINT8_COUNT)
        count = bytes([1])
        index = bytes([0x03])
        payload = bytes((n % 256) for n in range(1, 1 + variation))  # `variation` octets
        objects = index + payload
        data = bytes([group, variation, qualifier]) + count + objects + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(group, variation), (30, 1)]
        assert blocks[0].data == count + objects
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE


class TestG101V1HandEncoded:
    """A.39.1: BCD4 is 4 digits, one nibble per digit, 2 octets total.

    Built from literal BCD octets rather than derived from the row's own
    width, so a doubled width still fails this even though the width-derived
    parametrize case above cannot tell the two widths apart on its own.
    """

    def test_hand_encoded_bcd4_frames_and_steps_over(self) -> None:
        bcd_octets = bytes([0x34, 0x12])  # one BCD4 object, 4 digits, 2 octets (A.39.1)
        range_field = bytes([0x05, 0x05])  # start-stop 5..5: one object
        data = bytes([101, 1, 0x00]) + range_field + bcd_octets + _G30V1_TAIL

        blocks = parse_response_object_blocks(data)

        assert [(b.header.group, b.header.variation) for b in blocks] == [(101, 1), (30, 1)]
        assert blocks[0].data == range_field + bcd_octets
        assert _decode_g30v1(blocks[1].data).value == _G30V1_VALUE
