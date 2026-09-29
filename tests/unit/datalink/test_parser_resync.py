"""Tests for iterative CRC-failure resynchronization (issue #64).

`FrameParser._try_parse_frame` used to recover from a bad CRC by discarding
one byte and calling itself. Each skipped byte cost a stack frame, so a
peer sending a few KB of unparseable bytes could raise `RecursionError` out
of the public `feed()` API. These tests prove the parser stays iterative and
still delivers every valid frame.
"""

from dnp3.datalink.control import ControlByte
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser


class TestFrameParserResyncNoRecursionError:
    """Garbage well past the old recursion limit must not raise."""

    def test_long_garbage_then_valid_frame_is_delivered(self) -> None:
        """64 KB of repeated start bytes (bad header CRC every time) yields
        no frame and raises nothing; a valid frame fed right after is still
        delivered, byte for byte."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"after garbage",
        )
        garbage = b"\x05\x64" * 32768  # 64 KB, well past the ~2 KB old limit
        data = garbage + frame.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(data))

        assert len(frames) == 1
        assert frames[0].header.destination == 1
        assert frames[0].header.source == 2
        assert frames[0].header.control == ControlByte.from_int(0xC4)
        assert frames[0].user_data == b"after garbage"

    def test_garbage_only_yields_no_frames_and_raises_nothing(self) -> None:
        """64 KB of garbage with no valid frame anywhere returns an empty
        frame list rather than raising."""
        parser = FrameParser()
        frames = list(parser.feed(b"\x05\x64" * 32768))
        assert frames == []


class TestFrameParserResyncIsNotRecursive:
    """Each CRC-failure branch must not call `_try_parse_frame` from within
    itself. Proven by wrapping the method and counting nested (not
    sequential) invocations: a call that returns before the next one starts
    keeps the count at 1; a self-call raises it to 2. This kills a mutant
    that restores either `return self._try_parse_frame()` site without
    needing to reconstruct thousands of bytes of input."""

    @staticmethod
    def _max_nesting_depth(parser: FrameParser, data: bytes) -> int:
        original = FrameParser._try_parse_frame
        depth = 0
        max_depth = 0

        def wrapped(self: FrameParser) -> DataLinkFrame | None:
            nonlocal depth, max_depth
            depth += 1
            max_depth = max(max_depth, depth)
            try:
                return original(self)
            finally:
                depth -= 1

        FrameParser._try_parse_frame = wrapped  # type: ignore[method-assign]
        try:
            list(parser.feed(data))
        finally:
            FrameParser._try_parse_frame = original  # type: ignore[method-assign]
        return max_depth

    def test_header_crc_failure_does_not_nest(self) -> None:
        """A single bad header CRC, with no further start bytes to hunt,
        must resolve within one call to `_try_parse_frame`."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"x",
        )
        bad = bytearray(frame.to_bytes())
        bad[8] ^= 0xFF  # corrupt the header CRC; no start bytes follow

        max_depth = self._max_nesting_depth(FrameParser(), bytes(bad))
        assert max_depth == 1

    def test_data_block_crc_failure_does_not_nest(self) -> None:
        """A single bad data-block CRC, with no further start bytes to
        hunt, must resolve within one call to `_try_parse_frame`."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"0123456789ABCDEF",  # 16 bytes: one full data block
        )
        bad = bytearray(frame.to_bytes())
        bad[-1] ^= 0xFF  # corrupt the data block CRC; no start bytes follow

        max_depth = self._max_nesting_depth(FrameParser(), bytes(bad))
        assert max_depth == 1


class TestFrameParserResyncAcrossChunks:
    """Resynchronization still works when garbage arrives split across
    multiple feed() calls, and valid input is unaffected."""

    def test_garbage_split_across_feeds_then_valid_frame(self) -> None:
        """Garbage fed in two chunks resynchronizes the same as one chunk;
        the frame after it is delivered byte for byte."""
        frame = DataLinkFrame.build(
            destination=5,
            source=6,
            control=ControlByte.from_int(0xC3),
            user_data=b"split garbage",
        )
        garbage = b"\x05\x64" * 4096  # 8 KB, well past the old ~2 KB limit
        midpoint = len(garbage) // 2

        parser = FrameParser()
        frames1 = list(parser.feed(garbage[:midpoint]))
        frames2 = list(parser.feed(garbage[midpoint:] + frame.to_bytes()))

        assert frames1 == []
        assert len(frames2) == 1
        assert frames2[0].user_data == b"split garbage"
