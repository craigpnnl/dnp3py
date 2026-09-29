"""#82: a WRITE request carrying a g110 or g111 block now frames, sharing
the same ``layout_for`` lookup a response uses (``_lookup_data_length``
serves both ``frame_response_object_blocks`` and ``frame_request_object_blocks``
for any function outside the header-only set, and WRITE is not header-only).
Bytes built from the clause, not the library's own encoder.
"""

from dnp3.application.parser import frame_request_object_blocks
from dnp3.core.enums import FunctionCode

# g110v2 (A.41.1): qualifier 0x17 (1-byte count, 1-byte index), one object,
# index 0, 2-octet payload (OSTR2).
_G110V2 = bytes([110, 2, 0x17, 1, 0]) + bytes([0xAA, 0xBB])
# g80v1 (A.28.1): clear DEVICE_RESTART, start-stop 7..7, one octet.
_G80V1 = bytes([80, 1, 0x00, 7, 7, 0x00])


class TestOctetStringWriteFraming:
    """A WRITE of g110v2 or g111v2 reaches the block after it, where the
    base parser lost it to an unknown-width truncation.
    """

    def test_write_of_g110v2_then_g80v1_frames_both(self) -> None:
        data = _G110V2 + _G80V1

        blocks, truncation = frame_request_object_blocks(FunctionCode.WRITE, data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(110, 2), (80, 1)]

    def test_write_of_g111v2_then_g80v1_frames_both(self) -> None:
        g111v2 = bytes([111, 2, 0x17, 1, 0]) + bytes([0xCC, 0xDD])
        data = g111v2 + _G80V1

        blocks, truncation = frame_request_object_blocks(FunctionCode.WRITE, data)

        assert truncation is None
        assert [(b.header.group, b.header.variation) for b in blocks] == [(111, 2), (80, 1)]
