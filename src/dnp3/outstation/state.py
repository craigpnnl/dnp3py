"""Outstation state machine per IEEE 1815-2012.

Tracks outstation state including sequence numbers, select-before-operate
state, unsolicited response state, and IIN flags.
"""

import time
from dataclasses import dataclass, field, replace
from enum import Enum, auto

from dnp3.application.fragment import ResponseFragment
from dnp3.core.enums import ControlCode
from dnp3.core.flags import IIN
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId

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
        control_code: Control-code octet for binary output.
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

        The control code is compared as the whole octet, so TCC, Clear and
        Queue must match as well as Op Type (IEEE 1815-2012 4.4.4.3).

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


PointKey = tuple[int, int]
"""(object group, point index) of a selected point."""

CROB_GROUP = 12


@dataclass
class PeerSelection:
    """One peer's selection in effect: the SELECT request and the points it armed.

    A peer has at most one, since IEEE 1815-2012 Table 4-9 judges the peer's
    next request against the whole SELECT request, not against one point.

    Attributes:
        sequence: Application sequence number of the SELECT.
        body: Octets after the function code of the SELECT. None when the
            selection was stored without a request, which no request matches.
        response: Response sent to the SELECT, repeated on a valid retry.
        started: time.monotonic() when the selection began.
        points: Selected points by (group, index).
        cancelled: True when a non-zero status in the SELECT cancelled its
            points (IEEE 1815-2012 4.4.4.3 Rule 3). The record stays, with no
            points, so a retry repeats the response.
    """

    sequence: int
    body: bytes | None
    response: ResponseFragment | None
    started: float
    points: dict[PointKey, SelectState] = field(default_factory=dict)
    cancelled: bool = False


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
    # Keyed by peer so one master can never operate, overwrite or clear
    # another master's selection.
    selections: dict[PeerId, PeerSelection] = field(default_factory=dict)
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

    def add_select(self, select: SelectState, *, peer: PeerId = UNSPECIFIED_PEER, group: int = CROB_GROUP) -> None:
        """Add a point to a peer's selection, replacing any entry for the same point.

        Opens a selection for the peer if it has none, taking its sequence
        and start time from ``select``. A point added to a selection begun for
        a SELECT request is stored with that selection's start time, so every
        point expires on the one timer the SELECT started.

        Args:
            select: The select state to add.
            peer: The peer that made the selection.
            group: Object group of the selected point.
        """
        selection = self.selections.get(peer)
        if selection is None:
            selection = PeerSelection(sequence=select.sequence, body=None, response=None, started=select.timestamp)
            self.selections[peer] = selection
        elif selection.body is not None:
            select = replace(select, timestamp=selection.started)
        selection.points[(group, select.index)] = select

    def get_select(self, index: int, *, peer: PeerId = UNSPECIFIED_PEER, group: int = CROB_GROUP) -> SelectState | None:
        """Get a peer's SELECT state for a point.

        Args:
            index: Point index.
            peer: The peer whose selection to return.
            group: Object group of the point.

        Returns:
            SelectState if found, None otherwise.
        """
        selection = self.selections.get(peer)
        if selection is None:
            return None
        return selection.points.get((group, index))

    def remove_select(self, index: int, *, peer: PeerId = UNSPECIFIED_PEER, group: int = CROB_GROUP) -> None:
        """Remove a peer's SELECT state for a point, ending the selection if it was the last.

        Args:
            index: Point index.
            peer: The peer whose selection to remove.
            group: Object group of the point.
        """
        selection = self.selections.get(peer)
        if selection is None:
            return
        selection.points.pop((group, index), None)
        if not selection.points:
            del self.selections[peer]

    def held_by_other_peer(self, index: int, peer: PeerId, timeout: float, *, group: int = CROB_GROUP) -> bool:
        """Check whether a peer other than ``peer`` holds an unexpired selection on a point.

        Args:
            index: Point index.
            peer: The peer asking.
            timeout: Selection timeout in seconds.
            group: Object group of the point.

        Returns:
            True if another peer's selection on the point has not expired.
        """
        for holder, selection in self.selections.items():
            if holder == peer:
                continue
            select = selection.points.get((group, index))
            if select is not None and not select.is_expired(timeout):
                return True
        return False

    def release_connection(self, connection: int) -> None:
        """Remove every selection made by any peer on a transport connection.

        Args:
            connection: The connection id carried in each peer's PeerId.
        """
        released = [peer for peer in self.selections if peer.connection == connection]
        for peer in released:
            del self.selections[peer]

    def clear_expired_selects(self, timeout: float) -> None:
        """Clear all expired SELECT states, for every peer.

        Args:
            timeout: Selection timeout in seconds.
        """
        for peer, selection in list(self.selections.items()):
            expired = [key for key, select in selection.points.items() if select.is_expired(timeout)]
            for key in expired:
                del selection.points[key]
            # A selection begun for a SELECT still being processed has no points yet. A cancelled
            # one has none left to expire, so it ends on the timer its SELECT started.
            cancelled_expired = selection.cancelled and time.monotonic() - selection.started > timeout
            if (expired and not selection.points) or cancelled_expired:
                del self.selections[peer]

    def selection_of(self, peer: PeerId) -> PeerSelection | None:
        """Return the selection a peer has in effect, if any.

        Args:
            peer: The peer asking.

        Returns:
            The peer's selection, or None.
        """
        return self.selections.get(peer)

    def begin_selection(self, peer: PeerId, sequence: int, body: bytes) -> PeerSelection:
        """End any selection the peer holds and open an empty one for a SELECT request.

        Args:
            peer: The peer sending the SELECT.
            sequence: Application sequence number of the SELECT.
            body: Octets after the function code of the SELECT.

        Returns:
            The new selection.
        """
        selection = PeerSelection(sequence=sequence, body=body, response=None, started=time.monotonic())
        self.selections[peer] = selection
        return selection

    def set_response(self, peer: PeerId, response: ResponseFragment) -> None:
        """Record the response to a peer's SELECT, for repeating on a retry.

        Args:
            peer: The peer whose selection answered.
            response: The response sent.
        """
        selection = self.selections.get(peer)
        if selection is not None:
            selection.response = response

    def terminate(self, peer: PeerId) -> None:
        """End a peer's selection, every point of it.

        Args:
            peer: The peer whose selection ends.
        """
        self.selections.pop(peer, None)

    def cancel_points(self, peer: PeerId) -> None:
        """End every point of a peer's selection, as IEEE 1815-2012 4.4.4.3 Rule 3 requires.

        A selection begun for a SELECT request stays as a record with no points, so a
        retry of that request repeats its response rather than running again
        (Table 4-9). A selection stored without a request ends, as with terminate.

        Args:
            peer: The peer whose selection is cancelled.
        """
        selection = self.selections.get(peer)
        if selection is None or selection.body is None:
            self.selections.pop(peer, None)
            return
        selection.points.clear()
        selection.cancelled = True

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
