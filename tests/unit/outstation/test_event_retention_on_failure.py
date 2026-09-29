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

import dataclasses
from collections.abc import Sequence

import pytest

from dnp3.application.builder import build_all_objects_request, build_class_poll, build_read_request
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.database import Database, DatabaseConfig, Event, EventClass
from dnp3.database.point import AnalogInputConfig, BinaryInputConfig, CounterConfig
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


def _find_object_blocks(responses: Sequence[ResponseFragment], group: int, variation: int) -> list[ObjectBlock]:
    """Return every matching ObjectBlock across all fragments, in order.

    Unlike _find_block, keeps the header (qualifier included), needed when
    events may be split across more than one block or fragment.
    """
    return [
        obj
        for frag in responses
        for obj in frag.objects
        if obj.header.group == group and obj.header.variation == variation
    ]


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


def _decode_binary_events(block_data: bytes, *, qualifier: int = 0x17) -> list[int]:
    """Decode a g2v1 event block into a list of indexes.

    qualifier 0x17 is a 1-byte count and 1-byte index (every index < 256);
    qualifier 0x28 is 2-byte count and 2-byte index, used once an index in
    the block reaches 256 (IEEE 1815-2012 4.2.2.5, Table 4-11).
    """
    index_size = 1 if qualifier == 0x17 else 2
    count = int.from_bytes(block_data[:index_size], "little")
    record_size = index_size + 1  # index, then 1 fixed flags byte
    offset = index_size
    indexes = []
    for _ in range(count):
        indexes.append(int.from_bytes(block_data[offset : offset + index_size], "little"))
        offset += record_size
    return indexes


def _decode_counter_events(block_data: bytes) -> list[tuple[int, int]]:
    """Decode a g22v5 (qualifier 0x17, 1-byte index) event block into (index, value) pairs."""
    count = block_data[0]
    events = []
    offset = 1
    for _ in range(count):
        index = block_data[offset]
        value = int.from_bytes(block_data[offset + 2 : offset + 6], "little", signed=False)
        events.append((index, value))
        offset += 12  # 1 index + 1 flags + 4 value + 6 timestamp
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

    def test_two_enabled_classes_both_reach_zero(self) -> None:
        """The single-class success test above cannot catch a mutant that
        keeps only the last enabled class's keys for removal (overwriting
        seen_keys instead of updating it): with one class enabled, last is
        the only one. Two enabled classes, both with events, distinguish
        them.
        """
        outstation = _one_class2_analog_event(value=9.0)
        db = outstation.database
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation._state.unsolicited.class_1_enabled = True
        outstation._state.unsolicited.class_2_enabled = True

        response = outstation.generate_unsolicited()

        assert response is not None
        assert db.event_buffer.class1.count == 0
        assert db.event_buffer.class2.count == 0


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


class TestOneEventIsNotEncodedTwice:
    """A request naming one class through two blocks encodes each event once (#46).

    Before this fix, reading no longer removed events, so a request naming
    the same class through two blocks (the same class-poll block twice, or
    g2v0 alongside g60v2) read and encoded the still-buffered event a
    second time.
    """

    def test_repeated_class_poll_encodes_the_class_once(self) -> None:
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation = Outstation(database=db)

        request = build_class_poll(class_1=True, class_2=False, class_3=False, seq=0)
        doubled = dataclasses.replace(request, objects=tuple(request.objects) * 2)
        responses = outstation.process_request(doubled.to_bytes())

        matching_blocks = [o for f in responses for o in f.objects if o.header.group == 2]
        assert len(matching_blocks) == 1
        assert _decode_binary_events(bytes(matching_blocks[0].data)) == [0]
        assert db.event_buffer.class1.count == 0

    def test_g2v0_plus_g60v2_encodes_the_class_once(self) -> None:
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation = Outstation(database=db)

        g2_all = build_all_objects_request(function=FunctionCode.READ, group=2, variation=0, seq=0)
        class1_poll = build_class_poll(class_1=True, class_2=False, class_3=False, seq=0)
        combined = RequestFragment(
            header=class1_poll.header,
            objects=tuple(g2_all.objects) + tuple(class1_poll.objects),
        )
        responses = outstation.process_request(combined.to_bytes())

        matching_blocks = [o for f in responses for o in f.objects if o.header.group == 2]
        assert len(matching_blocks) == 1
        assert _decode_binary_events(bytes(matching_blocks[0].data)) == [0]
        assert db.event_buffer.class1.count == 0

    def test_g60v2_plus_g2v0_encodes_the_class_once(self) -> None:
        """The reverse block order from test_g2v0_plus_g60v2_encodes_the_class_once.

        A mutant where the g2/g32/g22 readers ignore seen_keys (always
        reading unfiltered) passes with g2v0 first, since nothing has been
        read yet to ignore. Reading g60v2 first populates seen_keys, and a
        g2v0 reader that then ignores it re-reads and re-encodes the same
        event, which this order catches and the other does not.
        """
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)
        outstation = Outstation(database=db)

        class1_poll = build_class_poll(class_1=True, class_2=False, class_3=False, seq=0)
        g2_all = build_all_objects_request(function=FunctionCode.READ, group=2, variation=0, seq=0)
        combined = RequestFragment(
            header=class1_poll.header,
            objects=tuple(class1_poll.objects) + tuple(g2_all.objects),
        )
        responses = outstation.process_request(combined.to_bytes())

        matching_blocks = [o for f in responses for o in f.objects if o.header.group == 2]
        assert len(matching_blocks) == 1
        assert _decode_binary_events(bytes(matching_blocks[0].data)) == [0]
        assert db.event_buffer.class1.count == 0

    def test_300_event_repeated_class_poll_fits_in_one_fragment_as_at_base(self) -> None:
        db = Database(config=DatabaseConfig(max_binary_inputs=310))
        for i in range(300):
            db.add_binary_input(i, BinaryInputConfig(event_class=EventClass.CLASS_1), value=False)
        for i in range(300):
            db.update_binary_input(i, value=True)
        outstation = Outstation(database=db)

        request = build_class_poll(class_1=True, class_2=False, class_3=False, seq=0)
        doubled = dataclasses.replace(request, objects=tuple(request.objects) * 2)
        responses = outstation.process_request(doubled.to_bytes())

        # 600 events (the duplicate) still fits one fragment at the default
        # max_fragment_size, so the fragment count alone cannot prove no
        # duplication happened; count the decoded events themselves. Indexes
        # reach 300, past the 1-byte qualifier's 256 ceiling, so the block's
        # own qualifier decides how _decode_binary_events reads it.
        matching_blocks = _find_object_blocks(responses, group=2, variation=1)
        decoded_indexes = [
            index
            for block in matching_blocks
            for index in _decode_binary_events(bytes(block.data), qualifier=block.header.qualifier)
        ]
        assert len(decoded_indexes) == 300
        assert sorted(decoded_indexes) == list(range(300))
        assert len(responses) == 1  # as at base: 300 events, encoded once, fit one fragment
        assert db.event_buffer.class1.count == 0


class TestMultiClassReadEmptiesEveryClass:
    """A poll or read naming several classes, or several event groups, empties every one (#46).

    A mutant that removes only the last block's serials, or that drops
    class 3 (g60v4) or g22 serials specifically, passes a single-class
    test but fails these.
    """

    @staticmethod
    def _seeded_database() -> Database:
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0))
        db.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3, deadband=0))
        db.update_binary_input(0, value=True)
        db.update_analog_input(0, value=5.0, quality=ONLINE)
        db.update_counter(0, value=7)
        return db

    def _assert_all_three_present_and_emptied(self, db: Database, responses: Sequence[ResponseFragment]) -> None:
        bi_block = _find_block(responses, group=2, variation=1)
        ai_block = _find_block(responses, group=32, variation=1)
        ctr_block = _find_block(responses, group=22, variation=5)
        assert bi_block is not None
        assert ai_block is not None
        assert ctr_block is not None
        assert _decode_binary_events(bi_block) == [0]
        assert _decode_analog_events(ai_block) == [(0, 5)]
        assert _decode_counter_events(ctr_block) == [(0, 7)]
        assert db.event_buffer.class1.count == 0
        assert db.event_buffer.class2.count == 0
        assert db.event_buffer.class3.count == 0

    def test_class_1_2_3_poll_empties_all_three_classes(self) -> None:
        db = self._seeded_database()
        outstation = Outstation(database=db)

        request = build_class_poll(class_1=True, class_2=True, class_3=True, seq=0)
        responses = outstation.process_request(request.to_bytes())

        self._assert_all_three_present_and_emptied(db, responses)

    def test_g2_g32_g22_read_empties_all_three_classes(self) -> None:
        db = self._seeded_database()
        outstation = Outstation(database=db)

        g2 = build_all_objects_request(function=FunctionCode.READ, group=2, variation=0, seq=0)
        g32 = build_all_objects_request(function=FunctionCode.READ, group=32, variation=0, seq=0)
        g22 = build_all_objects_request(function=FunctionCode.READ, group=22, variation=0, seq=0)
        combined = build_read_request(objects=tuple(g2.objects) + tuple(g32.objects) + tuple(g22.objects), seq=0)
        responses = outstation.process_request(combined.to_bytes())

        self._assert_all_three_present_and_emptied(db, responses)
