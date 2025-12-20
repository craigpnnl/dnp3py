"""Outstation state machine per IEEE 1815-2012.

Tracks outstation state including sequence numbers, select-before-operate
state, unsolicited response state, and IIN flags.
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto

from dnp3.core.enums import ControlCode
from dnp3.core.flags import IIN

# Event class numbers (from EventClass enum)
_CLASS_1 = 1
_CLASS_2 = 2
_CLASS_3 = 3


class OutstationState(Enum):
    """High-level outstation states."""

    IDLE = auto()  # Waiting for requests
    PROCESSING = auto()  # Processing a request
    WAITING_CONFIRM = auto()  # Waiting for confirmation
    UNSOLICITED = auto()  # Sending unsolicited response


@dataclass
class SelectState:
    """State for a single SELECT-BEFORE-OPERATE sequence.

    Tracks the selected control operation until OPERATE is received
    or the selection times out.

    Attributes:
        index: Point index that was selected.
        is_binary: True for binary output, False for analog output.
        control_code: Control code for binary output.
        count: Count for binary output pulsed operations.
        on_time: On time for binary output.
        off_time: Off time for binary output.
        analog_value: Value for analog output.
        sequence: Application sequence number of SELECT request.
        timestamp: Time when SELECT was received.
    """

    index: int
    is_binary: bool
    control_code: ControlCode = ControlCode.NUL
    count: int = 1
    on_time: int = 0
    off_time: int = 0
    analog_value: float = 0.0
    sequence: int = 0
    timestamp: float = field(default_factory=time.monotonic)

    def is_expired(self, timeout: float) -> bool:
        """Check if the selection has expired.

        Args:
            timeout: Selection timeout in seconds.

        Returns:
            True if the selection has expired.
        """
        return (time.monotonic() - self.timestamp) > timeout

    def matches_binary(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> bool:
        """Check if OPERATE matches the SELECT for binary output.

        Args:
            index: Point index.
            code: Control code.
            count: Operation count.
            on_time: On time.
            off_time: Off time.

        Returns:
            True if the OPERATE matches the SELECT.
        """
        return (
            self.is_binary
            and self.index == index
            and self.control_code == code
            and self.count == count
            and self.on_time == on_time
            and self.off_time == off_time
        )

    def matches_analog(self, index: int, value: float) -> bool:
        """Check if OPERATE matches the SELECT for analog output.

        Args:
            index: Point index.
            value: Analog value.

        Returns:
            True if the OPERATE matches the SELECT.
        """
        return not self.is_binary and self.index == index and self.analog_value == value


@dataclass
class SequenceState:
    """Application layer sequence number state.

    Tracks sequence numbers for request/response matching.
    """

    last_request_seq: int = -1  # Last received request sequence (-1 = none)
    last_response_seq: int = 0  # Last sent response sequence
    unsolicited_seq: int = 0  # Current unsolicited sequence

    def next_response_seq(self) -> int:
        """Get and increment response sequence number.

        Returns:
            Next response sequence (0-15).
        """
        seq = self.last_response_seq
        self.last_response_seq = (self.last_response_seq + 1) % 16
        return seq

    def next_unsolicited_seq(self) -> int:
        """Get and increment unsolicited sequence number.

        Returns:
            Next unsolicited sequence (0-15).
        """
        seq = self.unsolicited_seq
        self.unsolicited_seq = (self.unsolicited_seq + 1) % 16
        return seq


@dataclass
class UnsolicitedState:
    """State for unsolicited response handling.

    Tracks whether unsolicited responses are enabled and
    manages the unsolicited response sequence.
    """

    class_1_enabled: bool = False
    class_2_enabled: bool = False
    class_3_enabled: bool = False
    startup_complete: bool = False
    pending_confirm: bool = False
    confirm_sequence: int = -1
    retry_count: int = 0
    last_send_time: float = 0.0

    def is_class_enabled(self, event_class: int) -> bool:
        """Check if a class is enabled for unsolicited.

        Args:
            event_class: Class number (1, 2, or 3).

        Returns:
            True if the class is enabled.
        """
        if event_class == _CLASS_1:
            return self.class_1_enabled
        if event_class == _CLASS_2:
            return self.class_2_enabled
        if event_class == _CLASS_3:
            return self.class_3_enabled
        return False

    def enable_class(self, event_class: int) -> None:
        """Enable a class for unsolicited responses.

        Args:
            event_class: Class number (1, 2, or 3).
        """
        if event_class == _CLASS_1:
            self.class_1_enabled = True
        elif event_class == _CLASS_2:
            self.class_2_enabled = True
        elif event_class == _CLASS_3:
            self.class_3_enabled = True

    def disable_class(self, event_class: int) -> None:
        """Disable a class for unsolicited responses.

        Args:
            event_class: Class number (1, 2, or 3).
        """
        if event_class == _CLASS_1:
            self.class_1_enabled = False
        elif event_class == _CLASS_2:
            self.class_2_enabled = False
        elif event_class == _CLASS_3:
            self.class_3_enabled = False


@dataclass
class OutstationStateManager:
    """Manages all outstation state.

    Combines sequence tracking, SELECT state, IIN flags, and
    unsolicited response state.
    """

    state: OutstationState = OutstationState.IDLE
    sequences: SequenceState = field(default_factory=SequenceState)
    unsolicited: UnsolicitedState = field(default_factory=UnsolicitedState)
    select_states: dict[int, SelectState] = field(default_factory=dict)
    iin: IIN = field(default_factory=lambda: IIN.DEVICE_RESTART)
    need_time: bool = True
    last_broadcast: bool = False

    def set_restart(self) -> None:
        """Set the device restart IIN flag."""
        self.iin |= IIN.DEVICE_RESTART

    def clear_restart(self) -> None:
        """Clear the device restart IIN flag."""
        self.iin &= ~IIN.DEVICE_RESTART

    def set_need_time(self) -> None:
        """Set the need time IIN flag."""
        self.iin |= IIN.NEED_TIME
        self.need_time = True

    def clear_need_time(self) -> None:
        """Clear the need time IIN flag."""
        self.iin &= ~IIN.NEED_TIME
        self.need_time = False

    def update_event_flags(
        self,
        class_1_events: bool,
        class_2_events: bool,
        class_3_events: bool,
    ) -> None:
        """Update IIN event flags based on event buffer state.

        Args:
            class_1_events: Whether Class 1 events are available.
            class_2_events: Whether Class 2 events are available.
            class_3_events: Whether Class 3 events are available.
        """
        if class_1_events:
            self.iin |= IIN.CLASS_1_EVENTS
        else:
            self.iin &= ~IIN.CLASS_1_EVENTS

        if class_2_events:
            self.iin |= IIN.CLASS_2_EVENTS
        else:
            self.iin &= ~IIN.CLASS_2_EVENTS

        if class_3_events:
            self.iin |= IIN.CLASS_3_EVENTS
        else:
            self.iin &= ~IIN.CLASS_3_EVENTS

    def set_event_overflow(self) -> None:
        """Set the event buffer overflow IIN flag."""
        self.iin |= IIN.EVENT_BUFFER_OVERFLOW

    def clear_event_overflow(self) -> None:
        """Clear the event buffer overflow IIN flag."""
        self.iin &= ~IIN.EVENT_BUFFER_OVERFLOW

    def add_select(self, select: SelectState) -> None:
        """Add a SELECT state.

        Args:
            select: The select state to add.
        """
        self.select_states[select.index] = select

    def get_select(self, index: int) -> SelectState | None:
        """Get SELECT state for a point index.

        Args:
            index: Point index.

        Returns:
            SelectState if found, None otherwise.
        """
        return self.select_states.get(index)

    def remove_select(self, index: int) -> None:
        """Remove SELECT state for a point index.

        Args:
            index: Point index.
        """
        self.select_states.pop(index, None)

    def clear_expired_selects(self, timeout: float) -> None:
        """Clear all expired SELECT states.

        Args:
            timeout: Selection timeout in seconds.
        """
        expired = [index for index, select in self.select_states.items() if select.is_expired(timeout)]
        for index in expired:
            del self.select_states[index]

    def get_current_iin(self) -> IIN:
        """Get the current IIN flags.

        Returns:
            Current IIN value.
        """
        return self.iin

    def set_error_iin(self, error: IIN) -> None:
        """Set an error IIN flag.

        Args:
            error: Error IIN flag to set.
        """
        self.iin |= error

    def clear_error_iin(self, error: IIN) -> None:
        """Clear an error IIN flag.

        Args:
            error: Error IIN flag to clear.
        """
        self.iin &= ~error
