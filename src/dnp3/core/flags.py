"""Quality flags and Internal Indications (IIN) per IEEE 1815-2012."""

from enum import IntEnum, IntFlag


class BinaryQuality(IntFlag):
    """Binary point quality flags (Table 4-7).

    Single byte with quality indicators and state bit.
    """

    ONLINE = 0x01  # Point is online
    RESTART = 0x02  # Point value has not been updated since restart
    COMM_LOST = 0x04  # Communications with the source device are lost
    REMOTE_FORCED = 0x08  # Value is being forced by another master
    LOCAL_FORCED = 0x10  # Value is being forced by local operation
    CHATTER_FILTER = 0x20  # Point is in chatter filter mode
    RESERVED = 0x40  # Reserved bit
    STATE = 0x80  # Binary state (0=off, 1=on)


class AnalogQuality(IntFlag):
    """Analog point quality flags (Table 4-8).

    Single byte with quality indicators.
    """

    ONLINE = 0x01  # Point is online
    RESTART = 0x02  # Point value has not been updated since restart
    COMM_LOST = 0x04  # Communications with the source device are lost
    REMOTE_FORCED = 0x08  # Value is being forced by another master
    LOCAL_FORCED = 0x10  # Value is being forced by local operation
    OVER_RANGE = 0x20  # Value exceeds valid range
    REFERENCE_ERR = 0x40  # Reference check failure
    RESERVED = 0x80  # Reserved bit


class CounterQuality(IntFlag):
    """Counter point quality flags (Table 4-9).

    Single byte with quality indicators.
    """

    ONLINE = 0x01  # Point is online
    RESTART = 0x02  # Point value has not been updated since restart
    COMM_LOST = 0x04  # Communications with the source device are lost
    REMOTE_FORCED = 0x08  # Value is being forced by another master
    LOCAL_FORCED = 0x10  # Value is being forced by local operation
    ROLLOVER = 0x20  # Counter has rolled over
    DISCONTINUITY = 0x40  # Counter value has changed discontinuously
    RESERVED = 0x80  # Reserved bit


class DoubleBitState(IntEnum):
    """Double-bit binary states (Table 4-10).

    2-bit value representing 4 possible states.
    """

    INTERMEDIATE = 0  # Transitioning between states
    OFF = 1  # Determined off state
    ON = 2  # Determined on state
    INDETERMINATE = 3  # Abnormal or custom state


class DoubleBitQuality(IntFlag):
    """Double-bit binary quality flags (Table 4-10).

    Single byte with quality indicators and 2-bit state.
    """

    ONLINE = 0x01
    RESTART = 0x02
    COMM_LOST = 0x04
    REMOTE_FORCED = 0x08
    LOCAL_FORCED = 0x10
    CHATTER_FILTER = 0x20
    STATE_BIT_0 = 0x40  # Low bit of state
    STATE_BIT_1 = 0x80  # High bit of state


IIN_SIZE = 2  # IIN is 2 bytes


class IIN(IntFlag):
    """Internal Indications (IIN) - 2 bytes in response header (Table 4-4).

    IIN1 (low byte): bits 0-7
    IIN2 (high byte): bits 8-15
    """

    # IIN1 bits (low byte)
    BROADCAST = 0x0001  # Message was broadcast
    CLASS_1_EVENTS = 0x0002  # Class 1 events available
    CLASS_2_EVENTS = 0x0004  # Class 2 events available
    CLASS_3_EVENTS = 0x0008  # Class 3 events available
    NEED_TIME = 0x0010  # Time synchronization required
    LOCAL_CONTROL = 0x0020  # Some outputs are in local control
    DEVICE_TROUBLE = 0x0040  # Device has abnormal condition
    DEVICE_RESTART = 0x0080  # Device has restarted

    # IIN2 bits (high byte)
    NO_FUNC_CODE_SUPPORT = 0x0100  # Function code not supported
    OBJECT_UNKNOWN = 0x0200  # Requested object is unknown
    PARAMETER_ERROR = 0x0400  # Parameter error in request
    EVENT_BUFFER_OVERFLOW = 0x0800  # Event buffer overflow
    ALREADY_EXECUTING = 0x1000  # Operation already in progress
    CONFIG_CORRUPT = 0x2000  # Configuration is corrupt
    RESERVED_2 = 0x4000  # Reserved
    RESERVED_1 = 0x8000  # Reserved

    def to_bytes(self) -> bytes:  # type: ignore[override]
        """Serialize IIN to 2 bytes (IIN1, IIN2).

        Returns:
            2-byte IIN value (little-endian: IIN1 first, IIN2 second).
        """
        return int(self).to_bytes(2, byteorder="little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "IIN":  # type: ignore[override]
        """Parse IIN from 2 bytes.

        Args:
            data: 2 bytes (IIN1, IIN2).

        Returns:
            IIN instance.

        Raises:
            ValueError: If data is too short.
        """
        if len(data) < IIN_SIZE:
            msg = f"IIN requires {IIN_SIZE} bytes, got {len(data)}"
            raise ValueError(msg)
        value = int.from_bytes(data[:2], byteorder="little")
        return cls(value)
