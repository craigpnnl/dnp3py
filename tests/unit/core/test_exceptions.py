"""Tests for custom exceptions."""

import pytest

from dnp3.core.exceptions import (
    ApplicationError,
    ChannelError,
    CommandError,
    ConfigError,
    CRCError,
    DNP3Error,
    FrameError,
    ParseError,
    TimeoutError,
    TransportError,
)


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_dnp3_error_is_exception(self) -> None:
        """DNP3Error inherits from Exception."""
        assert issubclass(DNP3Error, Exception)

    def test_crc_error_inherits_dnp3_error(self) -> None:
        """CRCError inherits from DNP3Error."""
        assert issubclass(CRCError, DNP3Error)

    def test_parse_error_inherits_dnp3_error(self) -> None:
        """ParseError inherits from DNP3Error."""
        assert issubclass(ParseError, DNP3Error)

    def test_frame_error_inherits_parse_error(self) -> None:
        """FrameError inherits from ParseError."""
        assert issubclass(FrameError, ParseError)

    def test_transport_error_inherits_parse_error(self) -> None:
        """TransportError inherits from ParseError."""
        assert issubclass(TransportError, ParseError)

    def test_application_error_inherits_parse_error(self) -> None:
        """ApplicationError inherits from ParseError."""
        assert issubclass(ApplicationError, ParseError)

    def test_timeout_error_inherits_dnp3_error(self) -> None:
        """TimeoutError inherits from DNP3Error."""
        assert issubclass(TimeoutError, DNP3Error)

    def test_channel_error_inherits_dnp3_error(self) -> None:
        """ChannelError inherits from DNP3Error."""
        assert issubclass(ChannelError, DNP3Error)

    def test_command_error_inherits_dnp3_error(self) -> None:
        """CommandError inherits from DNP3Error."""
        assert issubclass(CommandError, DNP3Error)

    def test_config_error_inherits_dnp3_error(self) -> None:
        """ConfigError inherits from DNP3Error."""
        assert issubclass(ConfigError, DNP3Error)


class TestExceptionInstantiation:
    """Tests for exception creation."""

    def test_raise_crc_error(self) -> None:
        """CRCError can be raised and caught."""
        with pytest.raises(CRCError):
            raise CRCError("Invalid CRC")

    def test_raise_frame_error(self) -> None:
        """FrameError can be raised and caught."""
        with pytest.raises(FrameError):
            raise FrameError("Invalid frame")

    def test_catch_parse_error_catches_frame_error(self) -> None:
        """ParseError catch block catches FrameError."""
        with pytest.raises(ParseError):
            raise FrameError("Invalid frame")

    def test_catch_dnp3_error_catches_all(self) -> None:
        """DNP3Error catch block catches all custom exceptions."""
        with pytest.raises(DNP3Error):
            raise CRCError("CRC failed")

        with pytest.raises(DNP3Error):
            raise FrameError("Frame error")

        with pytest.raises(DNP3Error):
            raise TimeoutError("Timeout")
