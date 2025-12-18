"""Protocol enumerations per IEEE 1815-2012."""

from enum import IntEnum

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


class ControlCode(IntEnum):
    """Control relay output block (CROB) control codes (Table 4-6)."""

    NUL = 0x00
    PULSE_ON = 0x01
    PULSE_OFF = 0x02
    LATCH_ON = 0x03
    LATCH_OFF = 0x04
    CLOSE_PULSE_ON = 0x41
    TRIP_PULSE_ON = 0x81
