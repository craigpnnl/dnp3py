"""Core utilities for DNP3 protocol."""

from dnp3.core.crc import append_crc, compute_crc, verify_crc
from dnp3.core.enums import (
    CommandStatus,
    ControlCode,
    FunctionCode,
    LinkFunctionCode,
    QualifierCode,
)
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
from dnp3.core.flags import (
    IIN,
    AnalogQuality,
    BinaryQuality,
    CounterQuality,
    DoubleBitQuality,
    DoubleBitState,
)
from dnp3.core.timestamp import TIMESTAMP_SIZE, DNP3Timestamp
from dnp3.core.types import (
    BROADCAST_ADDRESS,
    MAX_ADDRESS,
    Address,
    AppSequence,
    LinkAddresses,
    PointIndex,
    TransportSequence,
)

__all__ = [
    "BROADCAST_ADDRESS",
    "IIN",
    "MAX_ADDRESS",
    "TIMESTAMP_SIZE",
    "Address",
    "AnalogQuality",
    "AppSequence",
    "ApplicationError",
    "BinaryQuality",
    "CRCError",
    "ChannelError",
    "CommandError",
    "CommandStatus",
    "ConfigError",
    "ControlCode",
    "CounterQuality",
    "DNP3Error",
    "DNP3Timestamp",
    "DoubleBitQuality",
    "DoubleBitState",
    "FrameError",
    "FunctionCode",
    "LinkAddresses",
    "LinkFunctionCode",
    "ParseError",
    "PointIndex",
    "QualifierCode",
    "TimeoutError",
    "TransportError",
    "TransportSequence",
    "append_crc",
    "compute_crc",
    "verify_crc",
]
