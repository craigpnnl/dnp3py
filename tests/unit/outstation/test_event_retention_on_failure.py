"""Fix #46: no event leaves the buffer until the response carrying it is built.

Before this fix, a class read or an unsolicited response removed events
from the buffer as it encoded each class, one at a time. A raise while
encoding a later block or a later class left an earlier class's events
gone even though the response meant to carry them was never sent to the
master. IEEE 1815-2012 4.1.6 ties removal to delivery, and 4.6.6 makes the
same promise for unsolicited reporting; this fix reads events by serial
instead of popping them, and removes only once the whole response has
been built without raising.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from dnp3.application.builder import build_class_poll
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.database import Database, Event, EventClass
from dnp3.database.point import AnalogInputConfig, BinaryInputConfig
from dnp3.outstation.outstation import Outstation

ONLINE = AnalogQuality.ONLINE


def _raise_on_analog_encode(self: Outstation, events: list[Event]) -> list[ObjectBlock]:
    msg = "boom: analog event encode"
    raise RuntimeError(msg)


def _one_class2_analog_event(index: int = 0, value: float = 5.0) -> Outstation:
    """A database with one CLASS_2 analog input whose one update buffered one event."""
    db = Database()
    db.add_analog_input(index, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0))
    db.update_analog_input(index, value=value, quality=ONLINE)
    return Outstation(database=db)


def _find_block(responses: Sequence[ResponseFragment], group: int, variation: int) -> bytes | None:
    """Return an object block's raw data from a list of ResponseFragment, or None."""
    for frag in responses:
        for obj in frag.objects:
            if obj.header.group == group and obj.header.variation == variation:
                return bytes(obj.data)
    return None


def _decode_analog_events(block_data: bytes) -> list[tuple[int, int]]:
    """Decode a g32v1 (qualifier 0x17, 1-byte index) event block into (index, value) pairs.

    Decodes the quality-plus-value bytes directly, not through
    AnalogInputEvent32 (the SUT's own encoder class), so a wrong byte
    layout in that class would not pass unnoticed here.
    """
    count = block_data[0]
    events = []
    offset = 1
    for _ in range(count):
        index = block_data[offset]
        value = int.from_bytes(block_data[offset + 2 : offset + 6], "little", signed=True)
        events.append((index, value))
        offset += 6
    return events


class TestReadEventsSurviveAFailedBuild:
    """A class poll whose event encoder raises leaves every buffered event in place."""

    def test_raise_on_encode_leaves_the_class_buffered_and_answers_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        outstation = _one_class2_analog_event()
        monkeypatch.setattr(Outstation, "_build_analog_event_blocks", _raise_on_analog_encode)

        request = build_class_poll(class_1=False, class_2=True, class_3=False, seq=4)
        responses = outstation.process_request(request.to_bytes())

        assert outstation.database.event_buffer.class2.count == 1
        assert len(responses) == 1
        assert responses[0].objects == ()
        assert IIN.CLASS_2_EVENTS in responses[0].header.iin
        assert IIN.PARAMETER_ERROR in responses[0].header.iin
        assert responses[0].header.control.seq == 4

    def test_later_block_raising_leaves_an_earlier_blocks_events_buffered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outstation = _one_class2_analog_event()
        db = outstation.database
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        assert db.event_buffer.class1.count == 1
        monkeypatch.setattr(Outstation, "_build_analog_event_blocks", _raise_on_analog_encode)

        # Class 1 block first, class 2 second; class 2's encoder raises.
        request = build_class_poll(class_1=True, class_2=True, class_3=False, seq=1)
        responses = outstation.process_request(request.to_bytes())

        assert db.event_buffer.class1.count == 1
        assert db.event_buffer.class2.count == 1
        assert len(responses) == 1
        assert responses[0].objects == ()

    def test_a_successful_poll_still_empties_the_class(self) -> None:
        db = Database()
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0))
        db.add_analog_input(1, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0))
        db.update_analog_input(0, value=5.0, quality=ONLINE)
        db.update_analog_input(1, value=7.0, quality=ONLINE)
        outstation = Outstation(database=db)
        assert db.event_buffer.class2.count == 2

        request = build_class_poll(class_1=False, class_2=True, class_3=False, seq=2)
        responses = outstation.process_request(request.to_bytes())

        block_data = _find_block(responses, group=32, variation=1)
        assert block_data is not None
        assert _decode_analog_events(block_data) == [(0, 5), (1, 7)]
        assert db.event_buffer.class2.count == 0
        assert IIN.CLASS_2_EVENTS not in responses[0].header.iin


class TestUnsolicitedEventsSurviveAFailedBuild:
    """generate_unsolicited applies the same read-then-remove ordering as a READ."""

    def test_raise_on_encode_leaves_the_class_buffered_and_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        outstation = _one_class2_analog_event()
        outstation._state.unsolicited.class_2_enabled = True
        monkeypatch.setattr(Outstation, "_build_analog_event_blocks", _raise_on_analog_encode)

        with pytest.raises(RuntimeError):
            outstation.generate_unsolicited()

        assert outstation.database.event_buffer.class2.count == 1

    def test_later_class_raising_leaves_an_earlier_classs_events_buffered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outstation = _one_class2_analog_event()
        db = outstation.database
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation._state.unsolicited.class_1_enabled = True
        outstation._state.unsolicited.class_2_enabled = True
        monkeypatch.setattr(Outstation, "_build_analog_event_blocks", _raise_on_analog_encode)

        with pytest.raises(RuntimeError):
            outstation.generate_unsolicited()

        assert db.event_buffer.class1.count == 1
        assert db.event_buffer.class2.count == 1

    def test_a_successful_call_still_empties_the_class(self) -> None:
        outstation = _one_class2_analog_event(value=9.0)
        outstation._state.unsolicited.class_2_enabled = True

        response = outstation.generate_unsolicited()

        assert response is not None
        block_data = _find_block([response], group=32, variation=1)
        assert block_data is not None
        assert _decode_analog_events(block_data) == [(0, 9)]
        assert outstation.database.event_buffer.class2.count == 0
        assert IIN.CLASS_2_EVENTS not in response.header.iin


class TestEventAddedDuringBuildSurvives:
    """Removal is by serial, so an event added mid-build is not swept up with it."""

    def test_event_added_while_encoding_is_not_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.add_binary_input(1, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation = Outstation(database=db)
        original_builder = Outstation._build_binary_event_blocks

        def _build_and_add_one(self: Outstation, events: list[Event]) -> list[ObjectBlock]:
            blocks = original_builder(self, events)
            db.update_binary_input(1, value=True)  # a point changes while this class is being encoded
            return blocks

        monkeypatch.setattr(Outstation, "_build_binary_event_blocks", _build_and_add_one)

        request = build_class_poll(class_1=True, class_2=False, class_3=False, seq=0)
        responses = outstation.process_request(request.to_bytes())

        block_data = _find_block(responses, group=2, variation=1)
        assert block_data is not None
        assert block_data[0] == 1  # only the original event was in this response
        assert block_data[1] == 0  # its index
        assert db.event_buffer.class1.count == 1  # the event added mid-build remains buffered
        remaining = db.event_buffer.class1.read_with_serials()
        assert remaining[0][1].index == 1
