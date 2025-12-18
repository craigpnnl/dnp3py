"""Tests for protocol enumerations."""

from dnp3.core.enums import (
    CommandStatus,
    FunctionCode,
    LinkFunctionCode,
    QualifierCode,
)


class TestFunctionCode:
    """Tests for application layer function codes."""

    def test_read_value(self) -> None:
        """READ function code is 0x01."""
        assert FunctionCode.READ == 0x01

    def test_write_value(self) -> None:
        """WRITE function code is 0x02."""
        assert FunctionCode.WRITE == 0x02

    def test_select_value(self) -> None:
        """SELECT function code is 0x03."""
        assert FunctionCode.SELECT == 0x03

    def test_operate_value(self) -> None:
        """OPERATE function code is 0x04."""
        assert FunctionCode.OPERATE == 0x04

    def test_direct_operate_value(self) -> None:
        """DIRECT_OPERATE function code is 0x05."""
        assert FunctionCode.DIRECT_OPERATE == 0x05

    def test_response_value(self) -> None:
        """RESPONSE function code is 0x81."""
        assert FunctionCode.RESPONSE == 0x81

    def test_unsolicited_response_value(self) -> None:
        """UNSOLICITED_RESPONSE function code is 0x82."""
        assert FunctionCode.UNSOLICITED_RESPONSE == 0x82

    def test_is_response(self) -> None:
        """Check if function code is a response."""
        assert FunctionCode.RESPONSE.is_response()
        assert FunctionCode.UNSOLICITED_RESPONSE.is_response()
        assert not FunctionCode.READ.is_response()

    def test_from_int(self) -> None:
        """Create FunctionCode from integer."""
        fc = FunctionCode(0x01)
        assert fc == FunctionCode.READ


class TestLinkFunctionCode:
    """Tests for data link layer function codes."""

    def test_primary_reset_link(self) -> None:
        """Primary RESET_LINK_STATE is 0."""
        assert LinkFunctionCode.PRI_RESET_LINK_STATE == 0

    def test_primary_user_data(self) -> None:
        """Primary USER_DATA is 3."""
        assert LinkFunctionCode.PRI_CONFIRMED_USER_DATA == 3

    def test_primary_unconfirmed_data(self) -> None:
        """Primary UNCONFIRMED_USER_DATA is 4."""
        assert LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA == 4

    def test_secondary_ack(self) -> None:
        """Secondary ACK is 0."""
        assert LinkFunctionCode.SEC_ACK == 0

    def test_secondary_nack(self) -> None:
        """Secondary NACK is 1."""
        assert LinkFunctionCode.SEC_NACK == 1


class TestQualifierCode:
    """Tests for object header qualifier codes."""

    def test_start_stop_8bit(self) -> None:
        """8-bit start-stop qualifier is 0x00."""
        assert QualifierCode.UINT8_START_STOP == 0x00

    def test_start_stop_16bit(self) -> None:
        """16-bit start-stop qualifier is 0x01."""
        assert QualifierCode.UINT16_START_STOP == 0x01

    def test_count_8bit(self) -> None:
        """8-bit count qualifier is 0x07."""
        assert QualifierCode.UINT8_COUNT == 0x07

    def test_count_16bit(self) -> None:
        """16-bit count qualifier is 0x08."""
        assert QualifierCode.UINT16_COUNT == 0x08

    def test_all_objects(self) -> None:
        """ALL_OBJECTS qualifier is 0x06."""
        assert QualifierCode.ALL_OBJECTS == 0x06


class TestCommandStatus:
    """Tests for control command status codes."""

    def test_success(self) -> None:
        """SUCCESS status is 0."""
        assert CommandStatus.SUCCESS == 0

    def test_timeout(self) -> None:
        """TIMEOUT status is 1."""
        assert CommandStatus.TIMEOUT == 1

    def test_not_supported(self) -> None:
        """NOT_SUPPORTED status is 4."""
        assert CommandStatus.NOT_SUPPORTED == 4

    def test_is_success(self) -> None:
        """Check if status indicates success."""
        assert CommandStatus.SUCCESS.is_success()
        assert not CommandStatus.TIMEOUT.is_success()
