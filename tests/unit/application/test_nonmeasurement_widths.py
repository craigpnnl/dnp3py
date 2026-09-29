"""Framing tests for #82's fixed-width non-measurement objects.

Each new layout row (g86v2, g101v1-3, g102v1, g120v3, g121v1, g122v1-2) is
proved by the same shape the library already uses for a measurement group:
one block of that group, followed by a g30v1 block, both framed and the
g30v1 value delivered intact. Widths are IEEE 1815-2012 Annex A, cited beside
each row; see the width table in the issue's linked plan for the clause
numbers this test file assumes.
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
            (101, 1, 4),  # A.39.1: BCD4
            (101, 2, 8),  # A.39.2: BCD8
            (101, 3, 16),  # A.39.3: BCD16
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
    def test_block_then_g30v1(
        self, group: int, variation: int, width: int, framing: tuple[int, bytes, bytes]
    ) -> None:
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
