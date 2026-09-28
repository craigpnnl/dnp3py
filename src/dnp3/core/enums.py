"""Protocol enumerations per IEEE 1815-2012."""

from enum import IntEnum
from typing import ClassVar

# Response function codes start at this value
_RESPONSE_CODE_MIN = 0x80


class FunctionCode(IntEnum):
    """Application layer function codes (Clause 4).

    Request codes: 0x00 - 0x21
    Response codes: 0x81 - 0x83
    """

    # Confirmation
    CONFIRM = 0x00

    # Read/Write
    READ = 0x01
    WRITE = 0x02

    # Control operations
    SELECT = 0x03
    OPERATE = 0x04
    DIRECT_OPERATE = 0x05
    DIRECT_OPERATE_NO_ACK = 0x06

    # Freeze operations
    IMMEDIATE_FREEZE = 0x07
    IMMEDIATE_FREEZE_NO_ACK = 0x08
    FREEZE_CLEAR = 0x09
    FREEZE_CLEAR_NO_ACK = 0x0A
    FREEZE_AT_TIME = 0x0B
    FREEZE_AT_TIME_NO_ACK = 0x0C

    # Restart operations
    COLD_RESTART = 0x0D
    WARM_RESTART = 0x0E

    # Initialization
    INITIALIZE_DATA = 0x0F
    INITIALIZE_APPLICATION = 0x10
    START_APPLICATION = 0x11
    STOP_APPLICATION = 0x12

    # Configuration
    SAVE_CONFIGURATION = 0x13

    # Unsolicited control
    ENABLE_UNSOLICITED = 0x14
    DISABLE_UNSOLICITED = 0x15

    # Class assignment
    ASSIGN_CLASS = 0x16

    # Time sync
    DELAY_MEASURE = 0x17
    RECORD_CURRENT_TIME = 0x18

    # File operations
    OPEN_FILE = 0x19
    CLOSE_FILE = 0x1A
    DELETE_FILE = 0x1B
    GET_FILE_INFO = 0x1C
    AUTHENTICATE_FILE = 0x1D
    ABORT_FILE = 0x1E

    # Response codes (0x81+)
    RESPONSE = 0x81
    UNSOLICITED_RESPONSE = 0x82
    AUTHENTICATE_RESPONSE = 0x83

    def is_response(self) -> bool:
        """Check if this is a response function code."""
        return self.value >= _RESPONSE_CODE_MIN


class LinkFunctionCode(IntEnum):
    """Data link layer function codes (Clause 9).

    Primary station codes (PRM=1): 0-4, 9
    Secondary station codes (PRM=0): 0-1, 11, 15

    Values collide across the PRM bit: PRI_RESET_LINK_STATE and SEC_ACK are
    both 0, and PRI_RESET_USER_PROCESS and SEC_NACK are both 1. A raw
    function-code value is ambiguous on its own; always check PRM first to
    pick the primary or secondary interpretation before matching a code.
    """

    # Primary station function codes (PRM=1)
    PRI_RESET_LINK_STATE = 0
    PRI_RESET_USER_PROCESS = 1
    PRI_TEST_LINK_STATE = 2
    PRI_CONFIRMED_USER_DATA = 3
    PRI_UNCONFIRMED_USER_DATA = 4
    PRI_REQUEST_LINK_STATUS = 9

    # Secondary station function codes (PRM=0)
    SEC_ACK = 0
    SEC_NACK = 1
    SEC_LINK_STATUS = 11
    SEC_NOT_SUPPORTED = 15


class QualifierCode(IntEnum):
    """Object header qualifier codes (Clause 4.2.2).

    Defines how objects are indexed/counted in messages.
    """

    # Start-stop range specifiers
    UINT8_START_STOP = 0x00
    UINT16_START_STOP = 0x01
    UINT32_START_STOP = 0x02

    # No range (all objects)
    ALL_OBJECTS = 0x06

    # Count specifiers
    UINT8_COUNT = 0x07
    UINT16_COUNT = 0x08
    UINT32_COUNT = 0x09

    # Count with index prefix
    UINT8_COUNT_UINT8_INDEX = 0x17
    UINT16_COUNT_UINT16_INDEX = 0x28
    UINT32_COUNT_UINT32_INDEX = 0x39

    # Variable format
    UINT8_COUNT_UINT8_SIZE = 0x4B
    UINT16_COUNT_UINT16_SIZE = 0x5B

    # Free format (single object)
    FREE_FORMAT_UINT16 = 0x5B


class CommandStatus(IntEnum):
    """Control command status codes (Table 4-5).

    Returned in response to control operations.
    """

    SUCCESS = 0
    TIMEOUT = 1
    NO_SELECT = 2
    FORMAT_ERROR = 3
    NOT_SUPPORTED = 4
    ALREADY_ACTIVE = 5
    HARDWARE_ERROR = 6
    LOCAL = 7
    TOO_MANY_OBJS = 8
    NOT_AUTHORIZED = 9
    AUTOMATION_INHIBIT = 10
    PROCESSING_LIMITED = 11
    OUT_OF_RANGE = 12
    DOWNSTREAM_LOCAL = 13
    ALREADY_COMPLETE = 14
    BLOCKED = 15
    CANCELLED = 16
    BLOCKED_OTHER_MASTER = 17
    DOWNSTREAM_FAIL = 18
    NON_PARTICIPATING = 126
    UNDEFINED = 127

    def is_success(self) -> bool:
        """Check if this status indicates success."""
        return self == CommandStatus.SUCCESS


class TripCloseCode(IntEnum):
    """g12v1 Trip-Close Code field, bits 7-6 of the control octet (A.8.1.2.2)."""

    NUL = 0
    CLOSE = 1
    TRIP = 2
    RESERVED = 3


class OperationType(IntEnum):
    """g12v1 Operation Type field, bits 3-0 of the control octet (A.8.1.2.2).

    Values 5 to 15 are undefined.
    """

    NUL = 0
    PULSE_ON = 1
    PULSE_OFF = 2
    LATCH_ON = 3
    LATCH_OFF = 4


_OP_TYPE_MASK = 0x0F
_QUEUE_BIT = 0x10
_CLEAR_BIT = 0x20
_TCC_SHIFT = 6
_OCTET_MAX = 0xFF


class ControlCode(int):
    """g12v1 control-code octet (IEEE 1815-2012 A.8.1.2).

    The value is the whole wire octet: TCC in bits 7-6, Clear in bit 5, Queue in
    bit 4 and Op Type in bits 3-0. Equality therefore compares every field, which
    the exact-octet SELECT versus OPERATE match of 4.4.4.3 requires.

    ``ControlCode(octet)`` decodes an octet and ``int(code)`` encodes it;
    :meth:`from_fields` builds one from its fields.

    Raises:
        ValueError: The value is not one octet, or its Op Type is undefined (5-15).
    """

    __slots__ = ()

    NUL: ClassVar["ControlCode"]
    PULSE_ON: ClassVar["ControlCode"]
    PULSE_OFF: ClassVar["ControlCode"]
    LATCH_ON: ClassVar["ControlCode"]
    LATCH_OFF: ClassVar["ControlCode"]
    CLOSE_PULSE_ON: ClassVar["ControlCode"]
    TRIP_PULSE_ON: ClassVar["ControlCode"]

    def __new__(cls, octet: int) -> "ControlCode":
        """Decode a control-code octet."""
        if not 0 <= octet <= _OCTET_MAX:
            msg = f"Control code {octet} is not one octet (0-255)"
            raise ValueError(msg)
        if octet & _OP_TYPE_MASK > OperationType.LATCH_OFF:
            msg = f"Control code 0x{octet:02X} has undefined Op Type {octet & _OP_TYPE_MASK}"
            raise ValueError(msg)
        return super().__new__(cls, octet)

    @classmethod
    def from_fields(
        cls,
        op_type: OperationType,
        *,
        tcc: TripCloseCode = TripCloseCode.NUL,
        clear: bool = False,
        queue: bool = False,
    ) -> "ControlCode":
        """Encode a control code from its fields."""
        octet = (tcc << _TCC_SHIFT) | (_CLEAR_BIT if clear else 0) | (_QUEUE_BIT if queue else 0) | op_type
        return cls(octet)

    @property
    def op_type(self) -> OperationType:
        """Operation Type field."""
        return OperationType(self & _OP_TYPE_MASK)

    @property
    def queue(self) -> bool:
        """Queue field. Obsolete: an outstation answers a set bit with NOT_SUPPORTED."""
        return bool(self & _QUEUE_BIT)

    @property
    def clear(self) -> bool:
        """Clear field: cancel in-progress and pending commands for the index."""
        return bool(self & _CLEAR_BIT)

    @property
    def tcc(self) -> TripCloseCode:
        """Trip-Close Code field."""
        return TripCloseCode(self >> _TCC_SHIFT)

    @property
    def value(self) -> int:
        """The wire octet, kept for callers written against the former IntEnum."""
        return int(self)

    @property
    def name(self) -> str:
        """Constant name, with ``|QUEUE`` and ``|CLEAR`` appended for those bits."""
        base = int(self) & ~(_QUEUE_BIT | _CLEAR_BIT)
        parts = [_CONTROL_CODE_NAMES.get(base, f"{self.tcc.name}_{self.op_type.name}")]
        if self.queue:
            parts.append("QUEUE")
        if self.clear:
            parts.append("CLEAR")
        return "|".join(parts)

    def __repr__(self) -> str:
        """Show the decoded name and the octet."""
        return f"<ControlCode.{self.name}: 0x{int(self):02X}>"


ControlCode.NUL = ControlCode(0x00)
ControlCode.PULSE_ON = ControlCode(0x01)
ControlCode.PULSE_OFF = ControlCode(0x02)
ControlCode.LATCH_ON = ControlCode(0x03)
ControlCode.LATCH_OFF = ControlCode(0x04)
ControlCode.CLOSE_PULSE_ON = ControlCode(0x41)
ControlCode.TRIP_PULSE_ON = ControlCode(0x81)

_CONTROL_CODE_NAMES: dict[int, str] = {
    0x00: "NUL",
    0x01: "PULSE_ON",
    0x02: "PULSE_OFF",
    0x03: "LATCH_ON",
    0x04: "LATCH_OFF",
    0x41: "CLOSE_PULSE_ON",
    0x81: "TRIP_PULSE_ON",
}
