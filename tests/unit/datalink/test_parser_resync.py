"""Tests for iterative CRC-failure resynchronization (issue #64).

`FrameParser._try_parse_frame` used to recover from a bad CRC by discarding
one byte and calling itself. Each skipped byte cost a stack frame, so a
peer sending a few KB of unparseable bytes could raise `RecursionError` out
of the public `feed()` API. These tests prove the parser stays iterative and
still delivers every valid frame.
"""

import threading

import pytest

from dnp3.core.crc import compute_crc
from dnp3.datalink.control import ControlByte
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser

# A mutant that stops the CRC-failure branches from discarding a byte
# makes feed() loop forever on unparseable input. Running feed() on a
# joined thread turns that into a fast test failure instead of a hung
# suite.
_HANG_BOUND_SECONDS = 5.0


def _feed_within_bound(parser: FrameParser, data: bytes) -> list[object]:
    frames: list[object] = []

    def run() -> None:
        frames.extend(parser.feed(data))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_HANG_BOUND_SECONDS)
    assert not thread.is_alive(), "feed() did not return within the bound; the loop stopped consuming bytes"
    return frames


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
        assert frames[0].to_bytes() == frame.to_bytes()

    def test_garbage_only_yields_no_frames_and_raises_nothing(self) -> None:
        """64 KB of garbage with no valid frame anywhere returns an empty
        frame list rather than raising."""
        parser = FrameParser()
        frames = list(parser.feed(b"\x05\x64" * 32768))
        assert frames == []

    def test_many_data_block_crc_failures_then_valid_frame(self) -> None:
        """3000 consecutive CRC-valid-header, bad-data-block frames, then
        one valid frame, must not raise: the old recursive fallback
        self-called once per skipped frame and blew the stack well before
        this count."""
        bad_frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"0123456789ABCDEF",
        )
        bad_bytes = bytearray(bad_frame.to_bytes())
        bad_bytes[-1] ^= 0xFF  # corrupt the data block CRC
        garbage = bytes(bad_bytes) * 3000

        good_frame = DataLinkFrame.build(
            destination=5,
            source=6,
            control=ControlByte.from_int(0xC3),
            user_data=b"still delivered",
        )

        parser = FrameParser()
        frames = list(parser.feed(garbage + good_frame.to_bytes()))

        assert len(frames) == 1
        assert frames[0].to_bytes() == good_frame.to_bytes()


class TestFrameParserResyncConsumesBytesOnCrcFailure:
    """Both CRC-failure branches (header and data block) must discard a
    byte before hunting again. A mutant that removes either discard makes
    feed() loop forever on unparseable input, so these tests run it on a
    bounded thread and fail fast rather than hang the whole suite."""

    def test_header_crc_failure_branch_consumes_bytes(self) -> None:
        """Bytes that never form a valid header must be fully consumed
        within the bound, yielding no frames."""
        garbage = b"\x05\x64" * 4096
        frames = _feed_within_bound(FrameParser(), garbage)
        assert frames == []

    def test_data_block_crc_failure_branch_consumes_bytes(self) -> None:
        """A frame with a bad data-block CRC and nothing valid after it
        must be fully consumed within the bound, yielding no frames."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"0123456789ABCDEF",
        )
        bad_bytes = bytearray(frame.to_bytes())
        bad_bytes[-1] ^= 0xFF  # corrupt the data block CRC

        frames = _feed_within_bound(FrameParser(), bytes(bad_bytes))
        assert frames == []


class TestFrameParserResyncDataBlockFailureKeepsHunting:
    """A bad data-block CRC must not stop the hunt within the same
    feed() call: the parser has to keep skipping bytes and looking for
    the next frame, not give up as soon as one bad block is seen."""

    def test_data_block_crc_failure_then_valid_frame_in_one_feed(self) -> None:
        """A frame with a bad data-block CRC directly followed by a
        valid frame, both in one feed() call, still yields the valid
        frame. Kills the mutant that returns from the data-block
        CRC-failure branch instead of continuing the hunt."""
        bad_frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"0123456789ABCDEF",  # one full 16-byte data block
        )
        bad_bytes = bytearray(bad_frame.to_bytes())
        bad_bytes[-1] ^= 0xFF  # corrupt the data block CRC

        good_frame = DataLinkFrame.build(
            destination=3,
            source=4,
            control=ControlByte.from_int(0xC3),
            user_data=b"good frame data",
        )

        parser = FrameParser()
        frames = list(parser.feed(bytes(bad_bytes) + good_frame.to_bytes()))

        assert len(frames) == 1
        assert frames[0].to_bytes() == good_frame.to_bytes()


class TestFrameParserResyncIsNotRecursive:
    """Each CRC-failure branch must not call `_try_parse_frame` from within
    itself. Proven by wrapping the method and counting nested (not
    sequential) invocations: a call that returns before the next one starts
    keeps the count at 1; a self-call raises it to 2. This kills a mutant
    that restores either `return self._try_parse_frame()` site with a
    single corrupted frame; it does not by itself prove the data-block path
    is free of RecursionError at the scale a real peer could send. See
    TestFrameParserResyncNoRecursionError for that end-to-end proof."""

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
        the frame after it is delivered byte for byte. The split lands at
        an odd offset so the feed() boundary falls between the two start
        bytes of a repeating garbage pair, not on a pair boundary."""
        frame = DataLinkFrame.build(
            destination=5,
            source=6,
            control=ControlByte.from_int(0xC3),
            user_data=b"split garbage",
        )
        garbage = b"\x05\x64" * 4096  # 8 KB, well past the old ~2 KB limit
        midpoint = (len(garbage) // 2) + 1  # odd: splits a 0x05 0x64 pair

        parser = FrameParser()
        frames1 = list(parser.feed(garbage[:midpoint]))
        frames2 = list(parser.feed(garbage[midpoint:] + frame.to_bytes()))

        assert frames1 == []
        assert len(frames2) == 1
        assert frames2[0].to_bytes() == frame.to_bytes()


class TestFrameParserResyncMinLengthField:
    """A LENGTH field below 5 is malformed: LENGTH counts the header's
    own 5 octets at least (IEEE 1815-2012 9.2.4.1.2). Issue #65:
    without a check, the resulting negative user_data_length reached
    `_calculate_frame_size` and produced a frame smaller than the 10-byte
    header itself. Built with raw bytes rather than `DataLinkHeader`,
    since `DataLinkHeader.from_bytes` now refuses to parse a LENGTH this
    short."""

    @staticmethod
    def _header_bytes(length: int) -> bytes:
        """A 10-byte header with a valid CRC and the given LENGTH."""
        body = bytes([0x05, 0x64, length, 0xC4, 0x04, 0x00, 0x01, 0x00])
        return body + compute_crc(body).to_bytes(2, "little")

    @pytest.mark.parametrize("length", [0, 1, 2, 3, 4])
    def test_length_below_minimum_then_valid_frame_in_one_feed(self, length: int) -> None:
        """A CRC-valid header with LENGTH 0-4, directly followed by a
        valid frame in the same feed() call, yields only the valid frame,
        byte for byte: the short header is skipped one byte at a time
        like a header CRC failure, never delivered."""
        good_frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"after short length",
        )

        parser = FrameParser()
        frames = list(parser.feed(self._header_bytes(length) + good_frame.to_bytes()))

        assert len(frames) == 1
        assert frames[0].to_bytes() == good_frame.to_bytes()

    def test_length_below_minimum_alone_yields_no_frame(self) -> None:
        """A CRC-valid header with LENGTH=0 and nothing after it yields no
        frame and raises nothing. The single skipped byte plus the 9
        remaining garbage bytes contain no further start-byte pair, so
        the whole short header is consumed and nothing is buffered."""
        parser = FrameParser()
        frames = list(parser.feed(self._header_bytes(0)))
        assert frames == []
        assert parser.bytes_buffered == 0

    @staticmethod
    def _overlapping_valid_frame(short_length: int) -> tuple[bytes, bytes]:
        """A LENGTH-invalid header whose own CONTROL/DEST/SRC/CRC bytes
        double as the start of a second, genuinely valid frame beginning
        3 bytes in. Returns (buffer, expected_frame_bytes): resync that
        skips exactly 1 byte finds and delivers the embedded frame byte
        for byte; resync that skips the whole 10-byte header consumes
        part of it and loses the frame."""
        embedded_control = 0xC4
        embedded_dest_lo = 0x01
        embedded_length = 5  # zero user data: smallest legal embedded frame

        # First 8 bytes of the short header: START, LENGTH (invalid),
        # then the embedded frame's own START/LENGTH/CONTROL/DEST_lo
        # occupying the short header's CONTROL..SRC_lo positions.
        prefix = bytes([0x05, 0x64, short_length, 0x05, 0x64, embedded_length, embedded_control, embedded_dest_lo])
        short_crc = compute_crc(prefix)
        crc_lo = short_crc & 0xFF
        crc_hi = (short_crc >> 8) & 0xFF

        # The short header's own CRC bytes double as the embedded frame's
        # DEST high byte and SRC low byte.
        embedded_dest = (crc_lo << 8) | embedded_dest_lo
        embedded_src_hi = 0x00
        embedded_src = (embedded_src_hi << 8) | crc_hi

        embedded_header_no_crc = (
            bytes([0x05, 0x64, embedded_length, embedded_control])
            + embedded_dest.to_bytes(2, "little")
            + embedded_src.to_bytes(2, "little")
        )
        embedded_crc = compute_crc(embedded_header_no_crc)
        expected_frame_bytes = embedded_header_no_crc + embedded_crc.to_bytes(2, "little")

        buffer = (
            prefix + short_crc.to_bytes(2, "little") + bytes([embedded_src_hi]) + embedded_crc.to_bytes(2, "little")
        )
        return buffer, expected_frame_bytes

    @pytest.mark.parametrize("short_length", [0, 4])
    def test_length_below_minimum_overlapping_valid_frame_is_delivered(self, short_length: int) -> None:
        """A real, CRC-valid frame can start inside the bytes of a
        rejected short header (offset 3 here). Resync must discard only
        the 1 byte the CRC-failure path discards, not the whole 10-byte
        header: deleting all 10 would consume the overlapping frame's
        first 7 bytes along with the invalid header and lose it. Kills a
        mutant that changes the LENGTH branch's `del self._buffer[0]` to
        delete HEADER_SIZE bytes."""
        buffer, expected_frame_bytes = self._overlapping_valid_frame(short_length)

        parser = FrameParser()
        frames = list(parser.feed(buffer))

        assert len(frames) == 1
        assert frames[0].to_bytes() == expected_frame_bytes
        assert parser.bytes_buffered == 0

    @pytest.mark.parametrize("length", [0, 4])
    @pytest.mark.parametrize("cut", range(1, 10))
    def test_length_below_minimum_split_across_feeds_yields_no_frame(self, cut: int, length: int) -> None:
        """A short header arriving split across two feed() calls, at
        every cut point from 1 to 9 bytes, yields no frame from either
        call and raises nothing. No shipped test split this case before:
        with the LENGTH guard removed, the second feed() call raises
        `DataLinkHeader.from_bytes`'s ValueError instead of resyncing."""
        header = self._header_bytes(length)

        parser = FrameParser()
        frames1 = list(parser.feed(header[:cut]))
        frames2 = list(parser.feed(header[cut:]))

        assert frames1 == []
        assert frames2 == []

    def test_length_at_minimum_still_delivers_empty_payload_frame(self) -> None:
        """LENGTH=5, the smallest legal value, is unaffected: it still
        parses to a frame with zero-length user data. Guards against a
        fix that rejects the boundary value along with the invalid ones."""
        parser = FrameParser()
        frames = list(parser.feed(self._header_bytes(5)))

        assert len(frames) == 1
        assert frames[0].header.length == 5
        assert frames[0].header.user_data_length == 0
        assert frames[0].user_data == b""
