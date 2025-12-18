"""Custom exceptions for DNP3 protocol errors."""


class DNP3Error(Exception):
    """Base exception for all DNP3-related errors."""


class CRCError(DNP3Error):
    """CRC validation failed."""


class ParseError(DNP3Error):
    """Failed to parse DNP3 message."""


class FrameError(ParseError):
    """Error in data link frame structure."""


class TransportError(ParseError):
    """Error in transport layer segment."""


class ApplicationError(ParseError):
    """Error in application layer message."""


class TimeoutError(DNP3Error):
    """Operation timed out."""


class ChannelError(DNP3Error):
    """Communication channel error."""


class CommandError(DNP3Error):
    """Control command operation failed."""


class ConfigError(DNP3Error):
    """Configuration error."""
