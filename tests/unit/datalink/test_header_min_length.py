"""Tests for the LENGTH field lower bound in DataLinkHeader.from_bytes
(issue #65). LENGTH counts the header's 5 octets at least (IEEE 1815-2012
9.2.4.1.2); a smaller value leaves no room for a full header.
FrameParser's resync loop skips a short header before it ever reaches
`DataLinkHeader.from_bytes`, but `DataLinkFrame.from_bytes` calls that
classmethod directly, so the header itself must refuse to represent a
shorter frame rather than compute a negative `user_data_length`.
"""

import pytest

from dnp3.core.crc import compute_crc
from dnp3.datalink.frame import DataLinkFrame, DataLinkHeader


def _header_bytes_no_crc(length: int) -> bytes:
    """8-byte header body (no CRC) with the given LENGTH field."""
    return bytes([0x05, 0x64, length, 0xC4, 0x04, 0x00, 0x01, 0x00])


class TestDataLinkHeaderFromBytesRejectsShortLength:
    @pytest.mark.parametrize("length", [0, 1, 2, 3, 4])
    def test_from_bytes_rejects_length_below_minimum(self, length: int) -> None:
        with pytest.raises(ValueError, match="LENGTH"):
            DataLinkHeader.from_bytes(_header_bytes_no_crc(length))

    def test_from_bytes_accepts_length_at_minimum(self) -> None:
        header = DataLinkHeader.from_bytes(_header_bytes_no_crc(5))
        assert header.length == 5
        assert header.user_data_length == 0


class TestDataLinkFrameFromBytesRejectsShortLength:
    """DataLinkFrame.from_bytes bypasses the parser entirely, so this is
    the second path issue #65 names into the same defect."""

    @pytest.mark.parametrize("length", [0, 1, 2, 3, 4])
    def test_frame_from_bytes_rejects_length_below_minimum(self, length: int) -> None:
        body = _header_bytes_no_crc(length)
        data = body + compute_crc(body).to_bytes(2, "little")

        with pytest.raises(ValueError, match="LENGTH"):
            DataLinkFrame.from_bytes(data)
