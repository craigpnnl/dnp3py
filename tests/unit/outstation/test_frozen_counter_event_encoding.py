"""Frozen counter events are reported in group 23, counter events in group 22."""

from __future__ import annotations

from dnp3.application.builder import build_class_poll
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.database import CounterConfig, Database, EventClass
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import Outstation


def _poll(database: Database) -> list[ResponseFragment]:
    outstation = Outstation(config=OutstationConfig(time_sync_required=False), database=database)
    return outstation.process_request(build_class_poll(seq=1).to_bytes())


def _blocks(responses: list[ResponseFragment], group: int) -> list[ObjectBlock]:
    return [block for response in responses for block in response.objects if block.header.group == group]


def _database() -> Database:
    database = Database()
    database.add_counter(0, CounterConfig(event_class=EventClass.CLASS_1))
    database.add_frozen_counter(0, CounterConfig(event_class=EventClass.CLASS_1))
    return database


class TestFrozenCounterEventEncoding:
    def test_frozen_counter_event_is_g23v5(self) -> None:
        database = _database()
        database.update_counter(0, value=42)
        database.event_buffer.clear_all()
        database.freeze_counter(0)

        responses = _poll(database)

        assert _blocks(responses, 22) == []
        (frozen,) = _blocks(responses, 23)
        assert frozen.header.variation == 5
        # count 1, index 0, flags, 32-bit value, 48-bit time
        assert frozen.data[0] == 1
        assert frozen.data[1] == 0
        assert int.from_bytes(frozen.data[3:7], "little") == 42
        assert len(frozen.data) == 1 + 1 + 1 + 4 + 6

    def test_counter_and_frozen_counter_events_keep_their_groups(self) -> None:
        database = _database()
        database.update_counter(0, value=7)
        database.freeze_counter(0)

        responses = _poll(database)

        assert [(b.header.group, b.header.variation) for b in _blocks(responses, 22)] == [(22, 5)]
        assert [(b.header.group, b.header.variation) for b in _blocks(responses, 23)] == [(23, 5)]
