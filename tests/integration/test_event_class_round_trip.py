"""End-to-end round trips that assert decoded values, not just exchange success.

The existing `test_outstation_master.py` cases deliberately avoid asserting
counts ("exact counts depend on parsing implementation"), which let the master
response-parser bugs pass CI. These tests pair a real `Outstation` with a real
`Master` and assert the master recovers exactly what the outstation stored, for
the configurations that used to fail silently:

* points configured with an event class, so an integrity poll returns event
  groups (2 / 32) with count qualifiers rather than static groups (1 / 30)
* databases holding several point types, so responses carry multiple blocks

Regression cover for the response-parsing bugs reported in issue #30.
"""

from dnp3.core.enums import FunctionCode
from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    CounterConfig,
    Database,
    EventClass,
)
from dnp3.master import Master
from dnp3.master.handler import ResponseInfo, SOEHandler
from dnp3.outstation import Outstation


class RecordingHandler(SOEHandler):
    """Records every delivered value, keyed by index."""

    def __init__(self) -> None:
        self.binary_inputs: dict[int, bool] = {}
        self.analog_inputs: dict[int, float] = {}
        self.counters: dict[int, int] = {}

    def on_binary_input(self, values, info: ResponseInfo) -> None:
        self.binary_inputs.update({v.index: v.value for v in values})

    def on_analog_input(self, values, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})

    def on_counter(self, values, info: ResponseInfo) -> None:
        self.counters.update({v.index: v.value for v in values})


def exchange(outstation: Outstation, master: Master, request) -> list[ResponseInfo]:
    """Run a request through the outstation and feed every response back."""
    infos = []
    for response in outstation.process_request(request.to_bytes()):
        info = master.process_response(response.to_bytes())
        assert info is not None, "master failed to parse an outstation response"
        infos.append(info)
    return infos


class TestEventClassIntegrityPoll:
    """EventClass.CLASS_1 is the ordinary SCADA configuration."""

    def test_binary_values_survive_event_class_poll(self) -> None:
        """Three event-class binaries decode to their stored states."""
        database = Database()
        for index in (0, 1, 2):
            database.add_binary_input(index, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_binary_input(2, value=True, quality=BinaryQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        infos = exchange(outstation, master, master.build_integrity_poll())

        assert infos and infos[0].function == FunctionCode.RESPONSE
        assert handler.binary_inputs == {0: True, 1: False, 2: True}

    def test_analog_value_is_not_fabricated_into_extra_points(self) -> None:
        """One stored analog stays one point, at its own index."""
        database = Database()
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1))
        database.update_analog_input(0, value=2401, quality=AnalogQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        exchange(outstation, master, master.build_integrity_poll())

        assert handler.analog_inputs == {0: 2401.0}

    def test_class_1_poll_after_update(self) -> None:
        """A class 1 poll returns the buffered events with correct values."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.CLASS_1))
        outstation = Outstation(database=database)

        handler = RecordingHandler()
        master = Master(handler=handler)

        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)

        exchange(outstation, master, master.build_class_poll(class_1=True))

        assert handler.binary_inputs == {0: True, 1: False}

    def test_sparse_indices_are_preserved(self) -> None:
        """Non-contiguous point indices survive the round trip."""
        database = Database()
        for index in (3, 17, 40):
            database.add_binary_input(index, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(3, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(17, value=False, quality=BinaryQuality.ONLINE)
        database.update_binary_input(40, value=True, quality=BinaryQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        exchange(outstation, master, master.build_integrity_poll())

        assert handler.binary_inputs == {3: True, 17: False, 40: True}


class TestMultiTypeIntegrityPoll:
    """A mixed database produces a multi-block response."""

    def test_binary_analog_and_counter_all_arrive(self) -> None:
        """No block is swallowed by the one before it."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.NONE))
        database.add_counter(0, CounterConfig(event_class=EventClass.NONE))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_analog_input(0, value=-1500, quality=AnalogQuality.ONLINE)
        database.update_counter(0, value=98765, quality=CounterQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        exchange(outstation, master, master.build_integrity_poll())

        assert handler.binary_inputs == {0: True, 1: False}
        assert handler.analog_inputs == {0: -1500.0}
        assert handler.counters == {0: 98765}

    def test_mixed_event_and_static_classes(self) -> None:
        """Event-class and static points in one database both decode."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.NONE))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_analog_input(0, value=750, quality=AnalogQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        exchange(outstation, master, master.build_integrity_poll())

        assert handler.binary_inputs == {0: True}
        assert handler.analog_inputs == {0: 750.0}

    def test_negative_analog_sign_is_preserved(self) -> None:
        """Signed decoding: a negative setpoint does not wrap to a large positive."""
        database = Database()
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.NONE))
        database.update_analog_input(0, value=-32768, quality=AnalogQuality.ONLINE)

        handler = RecordingHandler()
        master = Master(handler=handler)
        outstation = Outstation(database=database)

        exchange(outstation, master, master.build_integrity_poll())

        assert handler.analog_inputs == {0: -32768.0}
