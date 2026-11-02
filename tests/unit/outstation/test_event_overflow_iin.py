"""IIN2.3 EVENT_BUFFER_OVERFLOW is cleared once the remaining events are reported.

The IIN bits are IEEE 1815-2012 Table 4-14.
"""

from dnp3.application.builder import build_class_poll
from dnp3.core.flags import IIN
from dnp3.database import Database, EventClass
from dnp3.database.event_buffer import EventBuffer, EventBufferConfig
from dnp3.database.point import BinaryInputConfig
from dnp3.outstation.outstation import Outstation


def _overflowed_outstation(event_class: EventClass = EventClass.CLASS_1) -> Outstation:
    """An outstation whose buffer (three events per class) lost events of `event_class`."""
    database = Database()
    database.add_binary_input(0, BinaryInputConfig(event_class=event_class))
    database.update_binary_input(0, value=False)
    database.event_buffer = EventBuffer(
        config=EventBufferConfig(max_binary_events=1, max_analog_events=1, max_counter_events=1)
    )
    for i in range(10):
        database.update_binary_input(0, value=bool(i % 2))
    assert database.event_buffer.has_overflow
    return Outstation(database=database)


def _poll_iin(outstation: Outstation, seq: int, **classes: bool) -> IIN:
    request = build_class_poll(seq=seq, **classes)
    responses = outstation.process_request(request.to_bytes())
    return responses[-1].header.iin


class TestEventOverflowIin:
    """IIN2.3 is reported once more with the remaining events, then cleared."""

    def test_overflow_reported_with_remaining_events(self) -> None:
        outstation = _overflowed_outstation()
        assert IIN.EVENT_BUFFER_OVERFLOW in _poll_iin(outstation, 0)

    def test_overflow_cleared_after_events_reported(self) -> None:
        outstation = _overflowed_outstation()
        _poll_iin(outstation, 0)
        assert IIN.EVENT_BUFFER_OVERFLOW not in _poll_iin(outstation, 1)
        assert IIN.EVENT_BUFFER_OVERFLOW not in outstation.iin
        assert not outstation.database.event_buffer.has_overflow

    def test_overflow_kept_while_overflowed_class_not_read(self) -> None:
        outstation = _overflowed_outstation(EventClass.CLASS_1)
        assert IIN.EVENT_BUFFER_OVERFLOW in _poll_iin(outstation, 0, class_1=False, class_2=True, class_3=True)
        assert IIN.EVENT_BUFFER_OVERFLOW in _poll_iin(outstation, 1, class_1=False, class_2=True, class_3=True)
        assert IIN.EVENT_BUFFER_OVERFLOW in _poll_iin(outstation, 2, class_1=True, class_2=False, class_3=False)
        assert IIN.EVENT_BUFFER_OVERFLOW not in _poll_iin(outstation, 3)

    def test_overflow_set_again_by_a_new_overflow(self) -> None:
        outstation = _overflowed_outstation()
        _poll_iin(outstation, 0)
        assert IIN.EVENT_BUFFER_OVERFLOW not in _poll_iin(outstation, 1)
        for i in range(10):
            outstation.database.update_binary_input(0, value=bool(i % 2))
        assert IIN.EVENT_BUFFER_OVERFLOW in _poll_iin(outstation, 2)
        assert IIN.EVENT_BUFFER_OVERFLOW not in _poll_iin(outstation, 3)

    def test_unsolicited_response_reports_then_clears_overflow(self) -> None:
        outstation = _overflowed_outstation()
        outstation._state.unsolicited.enable_class(1)
        response = outstation.generate_unsolicited()
        assert response is not None
        assert IIN.EVENT_BUFFER_OVERFLOW in response.header.iin
        assert IIN.EVENT_BUFFER_OVERFLOW not in outstation.iin
