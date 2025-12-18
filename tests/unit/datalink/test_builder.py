"""Tests for data link frame builder."""

from dnp3.core.enums import LinkFunctionCode
from dnp3.datalink.builder import (
    build_ack,
    build_confirmed_user_data,
    build_link_status,
    build_nack,
    build_not_supported,
    build_primary_frame,
    build_request_link_status,
    build_reset_link_state,
    build_secondary_frame,
    build_test_link_state,
    build_unconfirmed_user_data,
)


class TestBuildPrimaryFrame:
    """Tests for generic primary frame builder."""

    def test_build_primary_frame_basic(self) -> None:
        """Build a basic primary frame."""
        frame = build_primary_frame(
            destination=1,
            source=2,
            function_code=LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA,
            dir_from_master=True,
        )
        assert frame.header.destination == 1
        assert frame.header.source == 2
        assert frame.header.control.prm is True
        assert frame.header.control.function_code == 4

    def test_build_primary_frame_with_data(self) -> None:
        """Build a primary frame with user data."""
        frame = build_primary_frame(
            destination=100,
            source=200,
            function_code=LinkFunctionCode.PRI_CONFIRMED_USER_DATA,
            dir_from_master=True,
            fcb=True,
            fcv=True,
            user_data=b"test data",
        )
        assert frame.user_data == b"test data"
        assert frame.header.control.fcb is True
        assert frame.header.control.fcv is True

    def test_build_primary_frame_from_outstation(self) -> None:
        """Build a primary frame from outstation (DIR=0)."""
        frame = build_primary_frame(
            destination=1,
            source=2,
            function_code=LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA,
            dir_from_master=False,
        )
        assert frame.header.control.dir_from_master is False


class TestBuildSecondaryFrame:
    """Tests for generic secondary frame builder."""

    def test_build_secondary_frame_basic(self) -> None:
        """Build a basic secondary frame."""
        frame = build_secondary_frame(
            destination=1,
            source=2,
            function_code=LinkFunctionCode.SEC_ACK,
            dir_from_master=False,
        )
        assert frame.header.control.prm is False
        assert frame.header.control.function_code == 0
        assert frame.user_data == b""

    def test_build_secondary_frame_with_dfc(self) -> None:
        """Build secondary frame with DFC bit set."""
        frame = build_secondary_frame(
            destination=1,
            source=2,
            function_code=LinkFunctionCode.SEC_ACK,
            dir_from_master=False,
            dfc=True,
        )
        # DFC uses FCB position in secondary frames
        assert frame.header.control.fcb is True


class TestBuildUnconfirmedUserData:
    """Tests for unconfirmed user data builder."""

    def test_build_from_master(self) -> None:
        """Build unconfirmed user data from master."""
        frame = build_unconfirmed_user_data(
            destination=10,
            source=1,
            dir_from_master=True,
            user_data=b"hello",
        )
        assert frame.header.destination == 10
        assert frame.header.source == 1
        assert frame.header.control.dir_from_master is True
        assert frame.header.control.prm is True
        assert frame.header.control.fcb is False
        assert frame.header.control.fcv is False
        assert frame.header.control.function_code == 4
        assert frame.user_data == b"hello"

    def test_build_from_outstation(self) -> None:
        """Build unconfirmed user data from outstation."""
        frame = build_unconfirmed_user_data(
            destination=1,
            source=10,
            dir_from_master=False,
            user_data=b"response",
        )
        assert frame.header.control.dir_from_master is False
        assert frame.user_data == b"response"

    def test_control_byte_value(self) -> None:
        """Verify control byte value for master unconfirmed data."""
        frame = build_unconfirmed_user_data(
            destination=1,
            source=2,
            dir_from_master=True,
            user_data=b"",
        )
        # DIR=1, PRM=1, FCB=0, FCV=0, FC=4 -> 0xC4
        assert frame.header.control.to_int() == 0xC4


class TestBuildConfirmedUserData:
    """Tests for confirmed user data builder."""

    def test_build_with_fcb_zero(self) -> None:
        """Build confirmed user data with FCB=0."""
        frame = build_confirmed_user_data(
            destination=10,
            source=1,
            dir_from_master=True,
            fcb=False,
            user_data=b"data",
        )
        assert frame.header.control.function_code == 3
        assert frame.header.control.fcb is False
        assert frame.header.control.fcv is True  # Always set for confirmed

    def test_build_with_fcb_one(self) -> None:
        """Build confirmed user data with FCB=1."""
        frame = build_confirmed_user_data(
            destination=10,
            source=1,
            dir_from_master=True,
            fcb=True,
            user_data=b"data",
        )
        assert frame.header.control.fcb is True
        assert frame.header.control.fcv is True

    def test_control_byte_value_fcb_one(self) -> None:
        """Verify control byte value with FCB=1."""
        frame = build_confirmed_user_data(
            destination=1,
            source=2,
            dir_from_master=True,
            fcb=True,
            user_data=b"",
        )
        # DIR=1, PRM=1, FCB=1, FCV=1, FC=3 -> 0xF3
        assert frame.header.control.to_int() == 0xF3


class TestBuildResetLinkState:
    """Tests for reset link state builder."""

    def test_build_reset_link_state(self) -> None:
        """Build reset link state frame."""
        frame = build_reset_link_state(
            destination=10,
            source=1,
            dir_from_master=True,
        )
        assert frame.header.control.function_code == 0
        assert frame.header.control.prm is True
        assert frame.user_data == b""

    def test_control_byte_value(self) -> None:
        """Verify control byte value for reset link state."""
        frame = build_reset_link_state(
            destination=1,
            source=2,
            dir_from_master=True,
        )
        # DIR=1, PRM=1, FCB=0, FCV=0, FC=0 -> 0xC0
        assert frame.header.control.to_int() == 0xC0


class TestBuildRequestLinkStatus:
    """Tests for request link status builder."""

    def test_build_request_link_status(self) -> None:
        """Build request link status frame."""
        frame = build_request_link_status(
            destination=10,
            source=1,
            dir_from_master=True,
        )
        assert frame.header.control.function_code == 9
        assert frame.header.control.prm is True
        assert frame.user_data == b""

    def test_control_byte_value(self) -> None:
        """Verify control byte value for request link status."""
        frame = build_request_link_status(
            destination=1,
            source=2,
            dir_from_master=True,
        )
        # DIR=1, PRM=1, FCB=0, FCV=0, FC=9 -> 0xC9
        assert frame.header.control.to_int() == 0xC9


class TestBuildTestLinkState:
    """Tests for test link state builder."""

    def test_build_test_link_state(self) -> None:
        """Build test link state frame."""
        frame = build_test_link_state(
            destination=10,
            source=1,
            dir_from_master=True,
            fcb=False,
        )
        assert frame.header.control.function_code == 2
        assert frame.header.control.fcv is True
        assert frame.user_data == b""

    def test_build_with_fcb_alternating(self) -> None:
        """Test FCB alternates between frames."""
        frame1 = build_test_link_state(destination=10, source=1, dir_from_master=True, fcb=False)
        frame2 = build_test_link_state(destination=10, source=1, dir_from_master=True, fcb=True)
        assert frame1.header.control.fcb is False
        assert frame2.header.control.fcb is True


class TestBuildAck:
    """Tests for ACK response builder."""

    def test_build_ack(self) -> None:
        """Build ACK response frame."""
        frame = build_ack(
            destination=1,
            source=10,
            dir_from_master=False,
        )
        assert frame.header.control.function_code == 0
        assert frame.header.control.prm is False
        assert frame.user_data == b""

    def test_build_ack_with_dfc(self) -> None:
        """Build ACK with DFC set."""
        frame = build_ack(
            destination=1,
            source=10,
            dir_from_master=False,
            dfc=True,
        )
        assert frame.header.control.fcb is True  # DFC uses FCB position

    def test_control_byte_value(self) -> None:
        """Verify control byte value for ACK from outstation."""
        frame = build_ack(destination=1, source=10, dir_from_master=False)
        # DIR=0, PRM=0, DFC=0, reserved=0, FC=0 -> 0x00
        assert frame.header.control.to_int() == 0x00


class TestBuildNack:
    """Tests for NACK response builder."""

    def test_build_nack(self) -> None:
        """Build NACK response frame."""
        frame = build_nack(
            destination=1,
            source=10,
            dir_from_master=False,
        )
        assert frame.header.control.function_code == 1
        assert frame.header.control.prm is False

    def test_control_byte_value(self) -> None:
        """Verify control byte value for NACK from outstation."""
        frame = build_nack(destination=1, source=10, dir_from_master=False)
        # DIR=0, PRM=0, DFC=0, reserved=0, FC=1 -> 0x01
        assert frame.header.control.to_int() == 0x01


class TestBuildLinkStatus:
    """Tests for link status response builder."""

    def test_build_link_status(self) -> None:
        """Build link status response frame."""
        frame = build_link_status(
            destination=1,
            source=10,
            dir_from_master=False,
        )
        assert frame.header.control.function_code == 11
        assert frame.header.control.prm is False

    def test_control_byte_value(self) -> None:
        """Verify control byte value for link status from outstation."""
        frame = build_link_status(destination=1, source=10, dir_from_master=False)
        # DIR=0, PRM=0, DFC=0, reserved=0, FC=11 -> 0x0B
        assert frame.header.control.to_int() == 0x0B


class TestBuildNotSupported:
    """Tests for not supported response builder."""

    def test_build_not_supported(self) -> None:
        """Build not supported response frame."""
        frame = build_not_supported(
            destination=1,
            source=10,
            dir_from_master=False,
        )
        assert frame.header.control.function_code == 15
        assert frame.header.control.prm is False

    def test_control_byte_value(self) -> None:
        """Verify control byte value for not supported from outstation."""
        frame = build_not_supported(destination=1, source=10, dir_from_master=False)
        # DIR=0, PRM=0, DFC=0, reserved=0, FC=15 -> 0x0F
        assert frame.header.control.to_int() == 0x0F


class TestBuilderRoundtrip:
    """Tests for building and parsing frames."""

    def test_unconfirmed_roundtrip(self) -> None:
        """Build, serialize, and parse unconfirmed data frame."""
        from dnp3.datalink.frame import DataLinkFrame

        original = build_unconfirmed_user_data(
            destination=100,
            source=200,
            dir_from_master=True,
            user_data=b"test payload",
        )
        serialized = original.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)

        assert parsed.header.destination == 100
        assert parsed.header.source == 200
        assert parsed.header.control.to_int() == original.header.control.to_int()
        assert parsed.user_data == b"test payload"

    def test_confirmed_roundtrip(self) -> None:
        """Build, serialize, and parse confirmed data frame."""
        from dnp3.datalink.frame import DataLinkFrame

        original = build_confirmed_user_data(
            destination=10,
            source=1,
            dir_from_master=True,
            fcb=True,
            user_data=b"important data",
        )
        serialized = original.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)

        assert parsed.header.control.to_int() == 0xF3
        assert parsed.user_data == b"important data"

    def test_ack_roundtrip(self) -> None:
        """Build, serialize, and parse ACK frame."""
        from dnp3.datalink.frame import DataLinkFrame

        original = build_ack(destination=1, source=10, dir_from_master=False)
        serialized = original.to_bytes()
        parsed = DataLinkFrame.from_bytes(serialized)

        assert parsed.header.control.to_int() == 0x00
        assert parsed.user_data == b""
