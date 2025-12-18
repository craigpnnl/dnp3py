"""Tests for data link frame parser."""

from dnp3.datalink.control import ControlByte
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser


class TestFrameParserBasic:
    """Basic frame parser tests."""

    def test_parser_initial_state(self) -> None:
        """Parser starts in initial state with empty buffer."""
        parser = FrameParser()
        assert parser.bytes_buffered == 0

    def test_parse_empty_frame(self) -> None:
        """Parse a complete frame without user data."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"",
        )
        serialized = frame.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(serialized))

        assert len(frames) == 1
        assert frames[0].header.destination == 1
        assert frames[0].header.source == 2

    def test_parse_frame_with_data(self) -> None:
        """Parse a complete frame with user data."""
        frame = DataLinkFrame.build(
            destination=100,
            source=200,
            control=ControlByte.from_int(0xF3),
            user_data=b"hello world",
        )
        serialized = frame.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(serialized))

        assert len(frames) == 1
        assert frames[0].user_data == b"hello world"


class TestFrameParserStreaming:
    """Tests for streaming/incremental parsing."""

    def test_parse_byte_by_byte(self) -> None:
        """Parse frame fed one byte at a time."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"test",
        )
        serialized = frame.to_bytes()

        parser = FrameParser()
        frames = []
        for byte in serialized:
            frames.extend(parser.feed(bytes([byte])))

        assert len(frames) == 1
        assert frames[0].user_data == b"test"

    def test_parse_two_frames(self) -> None:
        """Parse two consecutive frames."""
        frame1 = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"first",
        )
        frame2 = DataLinkFrame.build(
            destination=3,
            source=4,
            control=ControlByte.from_int(0xC3),
            user_data=b"second",
        )

        parser = FrameParser()
        frames = list(parser.feed(frame1.to_bytes() + frame2.to_bytes()))

        assert len(frames) == 2
        assert frames[0].user_data == b"first"
        assert frames[1].user_data == b"second"

    def test_parse_frames_with_garbage_between(self) -> None:
        """Parse frames with garbage bytes between them."""
        frame1 = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"one",
        )
        frame2 = DataLinkFrame.build(
            destination=3,
            source=4,
            control=ControlByte.from_int(0xC4),
            user_data=b"two",
        )

        # Insert garbage bytes between frames
        data = frame1.to_bytes() + b"\x00\x01\x02\x03" + frame2.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(data))

        assert len(frames) == 2
        assert frames[0].user_data == b"one"
        assert frames[1].user_data == b"two"

    def test_parse_with_leading_garbage(self) -> None:
        """Parse frame with garbage bytes at the start."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"data",
        )

        # Add garbage before the frame
        data = b"\xff\xfe\xfd\xfc" + frame.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(data))

        assert len(frames) == 1
        assert frames[0].user_data == b"data"


class TestFrameParserSplit:
    """Tests for handling split frames across multiple feed() calls."""

    def test_split_at_header(self) -> None:
        """Frame split in the middle of header."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"test",
        )
        serialized = frame.to_bytes()

        parser = FrameParser()
        # Feed first 5 bytes (partial header)
        frames1 = list(parser.feed(serialized[:5]))
        assert len(frames1) == 0
        assert parser.bytes_buffered > 0

        # Feed the rest
        frames2 = list(parser.feed(serialized[5:]))
        assert len(frames2) == 1
        assert frames2[0].user_data == b"test"

    def test_split_at_data(self) -> None:
        """Frame split in the middle of data block."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"0123456789ABCDEF",  # 16 bytes
        )
        serialized = frame.to_bytes()

        parser = FrameParser()
        # Feed header + partial data
        frames1 = list(parser.feed(serialized[:15]))
        assert len(frames1) == 0

        # Feed the rest
        frames2 = list(parser.feed(serialized[15:]))
        assert len(frames2) == 1


class TestFrameParserReset:
    """Tests for parser reset functionality."""

    def test_reset_clears_buffer(self) -> None:
        """Reset clears the internal buffer."""
        parser = FrameParser()
        parser.feed(b"\x05\x64\x05")  # Partial frame
        assert parser.bytes_buffered > 0

        parser.reset()
        assert parser.bytes_buffered == 0


class TestFrameParserErrors:
    """Tests for parser error handling."""

    def test_invalid_crc_skips_frame(self) -> None:
        """Invalid CRC causes parser to hunt for next frame."""
        frame1 = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"good",
        )
        frame2 = DataLinkFrame.build(
            destination=3,
            source=4,
            control=ControlByte.from_int(0xC4),
            user_data=b"also good",
        )

        # Corrupt the CRC of the first frame
        bad_frame = bytearray(frame1.to_bytes())
        bad_frame[8] ^= 0xFF  # Flip some bits in CRC

        data = bytes(bad_frame) + frame2.to_bytes()

        parser = FrameParser()
        frames = list(parser.feed(data))

        # Should skip the corrupted frame and parse the second one
        assert len(frames) == 1
        assert frames[0].user_data == b"also good"
