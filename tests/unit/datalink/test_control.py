"""Tests for data link control byte."""

from hypothesis import given
from hypothesis import strategies as st

from dnp3.datalink.control import ControlByte


class TestControlByteCreation:
    """Tests for creating ControlByte instances."""

    def test_create_primary_unconfirmed(self) -> None:
        """Create primary unconfirmed user data control byte."""
        ctrl = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=False,
            fcv=False,
            function_code=4,  # UNCONFIRMED_USER_DATA
        )
        assert ctrl.dir_from_master is True
        assert ctrl.prm is True
        assert ctrl.fcb is False
        assert ctrl.fcv is False
        assert ctrl.function_code == 4

    def test_create_secondary_ack(self) -> None:
        """Create secondary ACK control byte."""
        ctrl = ControlByte(
            dir_from_master=False,
            prm=False,
            fcb=False,
            fcv=False,
            function_code=0,  # ACK
        )
        assert ctrl.dir_from_master is False
        assert ctrl.prm is False
        assert ctrl.function_code == 0

    def test_create_primary_confirmed_with_fcb(self) -> None:
        """Create primary confirmed user data with FCB set."""
        ctrl = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=True,
            fcv=True,
            function_code=3,  # CONFIRMED_USER_DATA
        )
        assert ctrl.fcb is True
        assert ctrl.fcv is True
        assert ctrl.function_code == 3


class TestControlByteToInt:
    """Tests for serializing ControlByte to integer."""

    def test_primary_unconfirmed_from_master(self) -> None:
        """Primary unconfirmed from master: DIR=1, PRM=1, FC=4 -> 0xC4."""
        ctrl = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=False,
            fcv=False,
            function_code=4,
        )
        # DIR(1) PRM(1) FCB(0) FCV(0) FC(0100) = 1100_0100 = 0xC4
        assert ctrl.to_int() == 0xC4

    def test_primary_confirmed_with_fcb(self) -> None:
        """Primary confirmed with FCB: DIR=1, PRM=1, FCB=1, FCV=1, FC=3 -> 0xF3."""
        ctrl = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=True,
            fcv=True,
            function_code=3,
        )
        # DIR(1) PRM(1) FCB(1) FCV(1) FC(0011) = 1111_0011 = 0xF3
        assert ctrl.to_int() == 0xF3

    def test_secondary_ack_to_master(self) -> None:
        """Secondary ACK to master: DIR=0, PRM=0, FC=0 -> 0x00."""
        ctrl = ControlByte(
            dir_from_master=False,
            prm=False,
            fcb=False,
            fcv=False,
            function_code=0,
        )
        assert ctrl.to_int() == 0x00

    def test_secondary_link_status(self) -> None:
        """Secondary link status: DIR=0, PRM=0, FC=11 -> 0x0B."""
        ctrl = ControlByte(
            dir_from_master=False,
            prm=False,
            fcb=False,
            fcv=False,
            function_code=11,
        )
        assert ctrl.to_int() == 0x0B

    def test_primary_reset_link(self) -> None:
        """Primary reset link state: DIR=1, PRM=1, FC=0 -> 0xC0."""
        ctrl = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=False,
            fcv=False,
            function_code=0,
        )
        assert ctrl.to_int() == 0xC0


class TestControlByteFromInt:
    """Tests for parsing ControlByte from integer."""

    def test_parse_primary_unconfirmed(self) -> None:
        """Parse 0xC4 -> primary unconfirmed from master."""
        ctrl = ControlByte.from_int(0xC4)
        assert ctrl.dir_from_master is True
        assert ctrl.prm is True
        assert ctrl.fcb is False
        assert ctrl.fcv is False
        assert ctrl.function_code == 4

    def test_parse_primary_confirmed_with_fcb(self) -> None:
        """Parse 0xF3 -> primary confirmed with FCB."""
        ctrl = ControlByte.from_int(0xF3)
        assert ctrl.dir_from_master is True
        assert ctrl.prm is True
        assert ctrl.fcb is True
        assert ctrl.fcv is True
        assert ctrl.function_code == 3

    def test_parse_secondary_ack(self) -> None:
        """Parse 0x00 -> secondary ACK."""
        ctrl = ControlByte.from_int(0x00)
        assert ctrl.dir_from_master is False
        assert ctrl.prm is False
        assert ctrl.function_code == 0

    def test_parse_all_bits_set(self) -> None:
        """Parse 0xFF -> all bits set."""
        ctrl = ControlByte.from_int(0xFF)
        assert ctrl.dir_from_master is True
        assert ctrl.prm is True
        assert ctrl.fcb is True
        assert ctrl.fcv is True
        assert ctrl.function_code == 0x0F

    @given(st.integers(min_value=0, max_value=255))
    def test_roundtrip(self, value: int) -> None:
        """Roundtrip: from_int -> to_int preserves value."""
        ctrl = ControlByte.from_int(value)
        assert ctrl.to_int() == value


class TestControlByteProperties:
    """Tests for ControlByte helper properties."""

    def test_is_from_master_true(self) -> None:
        """Check is_from_master property when DIR=1."""
        ctrl = ControlByte.from_int(0xC4)
        assert ctrl.is_from_master is True

    def test_is_from_master_false(self) -> None:
        """Check is_from_master property when DIR=0."""
        ctrl = ControlByte.from_int(0x00)
        assert ctrl.is_from_master is False

    def test_is_primary_true(self) -> None:
        """Check is_primary property when PRM=1."""
        ctrl = ControlByte.from_int(0xC4)
        assert ctrl.is_primary is True

    def test_is_primary_false(self) -> None:
        """Check is_primary property when PRM=0."""
        ctrl = ControlByte.from_int(0x00)
        assert ctrl.is_primary is False


class TestControlByteEquality:
    """Tests for ControlByte equality."""

    def test_equal_instances(self) -> None:
        """Equal control bytes compare equal."""
        ctrl1 = ControlByte.from_int(0xC4)
        ctrl2 = ControlByte.from_int(0xC4)
        assert ctrl1 == ctrl2

    def test_unequal_instances(self) -> None:
        """Different control bytes compare not equal."""
        ctrl1 = ControlByte.from_int(0xC4)
        ctrl2 = ControlByte.from_int(0xC3)
        assert ctrl1 != ctrl2
