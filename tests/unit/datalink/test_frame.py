"""Tests for data link frame format."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.datalink.control import ControlByte
from dnp3.datalink.frame import (
    DATA_BLOCK_SIZE,
    HEADER_SIZE,
    MAX_USER_DATA_LENGTH,
    START_BYTES,
    DataLinkFrame,
    DataLinkHeader,
)


class TestConstants:
    """Tests for frame constants."""

    def test_start_bytes(self) -> None:
        """Start bytes are 0x05 0x64."""
        assert START_BYTES == b"\x05\x64"

    def test_header_size(self) -> None:
        """Header size is 10 bytes (including CRC)."""
        assert HEADER_SIZE == 10

    def test_data_block_size(self) -> None:
        """Data block size is 16 bytes."""
        assert DATA_BLOCK_SIZE == 16

    def test_max_user_data_length(self) -> None:
        """Maximum user data is 250 bytes."""
        assert MAX_USER_DATA_LENGTH == 250


class TestDataLinkHeader:
    """Tests for DataLinkHeader dataclass."""

    def test_create_header(self) -> None:
        """Create a data link header."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(
            length=5,
            control=ctrl,
            destination=1,
            source=2,
        )
        assert header.length == 5
        assert header.control == ctrl
        assert header.destination == 1
        assert header.source == 2

    def test_header_to_bytes(self) -> None:
        """Serialize header to bytes (without CRC)."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(
            length=5,
            control=ctrl,
            destination=1,
            source=2,
        )
        data = header.to_bytes_without_crc()
        # Start(2) + Length(1) + Control(1) + Dest(2) + Source(2) = 8 bytes
        assert len(data) == 8
        assert data[0:2] == START_BYTES
        assert data[2] == 5  # length
        assert data[3] == 0xC4  # control
        assert data[4:6] == b"\x01\x00"  # destination (little-endian)
        assert data[6:8] == b"\x02\x00"  # source (little-endian)

    def test_header_from_bytes(self) -> None:
        """Parse header from bytes (without CRC)."""
        data = b"\x05\x64\x05\xc4\x01\x00\x02\x00"
        header = DataLinkHeader.from_bytes(data)
        assert header.length == 5
        assert header.control.to_int() == 0xC4
        assert header.destination == 1
        assert header.source == 2

    def test_header_with_large_addresses(self) -> None:
        """Header with maximum addresses."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(
            length=10,
            control=ctrl,
            destination=0xFFFF,
            source=0xFFFE,
        )
        data = header.to_bytes_without_crc()
        parsed = DataLinkHeader.from_bytes(data)
        assert parsed.destination == 0xFFFF
        assert parsed.source == 0xFFFE

    def test_header_user_data_length(self) -> None:
        """User data length property."""
        ctrl = ControlByte.from_int(0xC4)
        # length field = user_data_length + 5
        header = DataLinkHeader(length=15, control=ctrl, destination=1, source=2)
        assert header.user_data_length == 10


class TestDataLinkFrame:
    """Tests for DataLinkFrame dataclass."""

    def test_create_frame_no_data(self) -> None:
        """Create frame without user data."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(length=5, control=ctrl, destination=1, source=2)
        frame = DataLinkFrame(header=header, user_data=b"")
        assert frame.header == header
        assert frame.user_data == b""

    def test_create_frame_with_data(self) -> None:
        """Create frame with user data."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(length=15, control=ctrl, destination=1, source=2)
        frame = DataLinkFrame(header=header, user_data=b"0123456789")
        assert len(frame.user_data) == 10

    def test_frame_equality(self) -> None:
        """Frames with same content are equal."""
        ctrl = ControlByte.from_int(0xC4)
        header = DataLinkHeader(length=5, control=ctrl, destination=1, source=2)
        frame1 = DataLinkFrame(header=header, user_data=b"")
        frame2 = DataLinkFrame(header=header, user_data=b"")
        assert frame1 == frame2


class TestDataLinkFrameBuilder:
    """Tests for building frames."""

    def test_build_simple_frame(self) -> None:
        """Build a simple frame from components."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"",
        )
        assert frame.header.destination == 1
        assert frame.header.source == 2
        assert frame.header.length == 5
        assert frame.user_data == b""

    def test_build_frame_with_data(self) -> None:
        """Build frame with user data."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"hello",
        )
        assert frame.header.length == 10  # 5 + 5 bytes of data
        assert frame.user_data == b"hello"

    def test_build_frame_max_data(self) -> None:
        """Build frame with maximum user data."""
        data = bytes(range(250))
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=data,
        )
        assert frame.header.length == 255  # 5 + 250
        assert frame.user_data == data

    def test_build_frame_too_much_data(self) -> None:
        """Building frame with too much data raises error."""
        data = bytes(251)  # One byte over max
        with pytest.raises(ValueError, match="exceeds maximum"):
            DataLinkFrame.build(
                destination=1,
                source=2,
                control=ControlByte.from_int(0xC4),
                user_data=data,
            )


class TestDataLinkFrameSerialization:
    """Tests for frame serialization to bytes."""

    def test_serialize_empty_frame(self) -> None:
        """Serialize frame without user data."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"",
        )
        data = frame.to_bytes()
        # Header(8) + HeaderCRC(2) = 10 bytes
        assert len(data) == 10
        # Check start bytes
        assert data[0:2] == START_BYTES

    def test_serialize_frame_with_small_data(self) -> None:
        """Serialize frame with small user data (< 16 bytes)."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"hello",
        )
        data = frame.to_bytes()
        # Header(8) + HeaderCRC(2) + Data(5) + DataCRC(2) = 17 bytes
        assert len(data) == 17

    def test_serialize_frame_with_exactly_one_block(self) -> None:
        """Serialize frame with exactly 16 bytes of data."""
        user_data = b"0123456789ABCDEF"
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=user_data,
        )
        data = frame.to_bytes()
        # Header(8) + HeaderCRC(2) + Data(16) + DataCRC(2) = 28 bytes
        assert len(data) == 28

    def test_serialize_frame_with_two_blocks(self) -> None:
        """Serialize frame with data spanning two blocks."""
        user_data = b"0123456789ABCDEF" + b"extra"  # 21 bytes
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=user_data,
        )
        data = frame.to_bytes()
        # Header(8) + HeaderCRC(2) + Block1(16) + CRC1(2) + Block2(5) + CRC2(2) = 35 bytes
        assert len(data) == 35


class TestDataLinkFrameDeserialization:
    """Tests for frame deserialization from bytes."""

    def test_deserialize_empty_frame(self) -> None:
        """Deserialize frame without user data."""
        frame = DataLinkFrame.build(
            destination=1,
            source=2,
            control=ControlByte.from_int(0xC4),
            user_data=b"",
        )
        serialized = frame.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)
        assert parsed.header.destination == 1
        assert parsed.header.source == 2
        assert parsed.header.control.to_int() == 0xC4
        assert parsed.user_data == b""

    def test_deserialize_frame_with_data(self) -> None:
        """Deserialize frame with user data."""
        frame = DataLinkFrame.build(
            destination=100,
            source=200,
            control=ControlByte.from_int(0xF3),
            user_data=b"test data",
        )
        serialized = frame.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)
        assert parsed.header.destination == 100
        assert parsed.header.source == 200
        assert parsed.header.control.to_int() == 0xF3
        assert parsed.user_data == b"test data"

    @given(
        destination=st.integers(min_value=0, max_value=0xFFFF),
        source=st.integers(min_value=0, max_value=0xFFFF),
        control=st.integers(min_value=0, max_value=0xFF),
        user_data=st.binary(min_size=0, max_size=MAX_USER_DATA_LENGTH),
    )
    def test_roundtrip(self, destination: int, source: int, control: int, user_data: bytes) -> None:
        """Roundtrip: build -> serialize -> deserialize preserves data."""
        frame = DataLinkFrame.build(
            destination=destination,
            source=source,
            control=ControlByte.from_int(control),
            user_data=user_data,
        )
        serialized = frame.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)
        assert parsed.header.destination == destination
        assert parsed.header.source == source
        assert parsed.header.control.to_int() == control
        assert parsed.user_data == user_data
