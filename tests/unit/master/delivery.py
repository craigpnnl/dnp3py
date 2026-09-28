"""Run object blocks through the master's response decode and record what reaches the handler."""

from collections.abc import Sequence

from dnp3.application.fragment import ObjectBlock
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN
from dnp3.master.handler import AnalogValue, BinaryValue, CounterValue, ResponseInfo
from dnp3.master.master import Master

PointValue = BinaryValue | AnalogValue | CounterValue


class RecordingHandler:
    """Records each callback as (name, values), in call order.

    Deliberately not a subclass of SOEHandler, so the master must call the
    instance's own methods rather than the protocol's.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[PointValue]]] = []

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self.calls.append(("on_binary_input", list(values)))

    def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        self.calls.append(("on_binary_output", list(values)))

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self.calls.append(("on_analog_input", list(values)))

    def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        self.calls.append(("on_analog_output", list(values)))

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.calls.append(("on_counter", list(values)))

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.calls.append(("on_frozen_counter", list(values)))


def response_info() -> ResponseInfo:
    return ResponseInfo(function=FunctionCode.RESPONSE, iin=IIN(0), sequence=1)


def dispatch(blocks: Sequence[ObjectBlock]) -> list[tuple[str, list[PointValue]]]:
    """Every callback the master makes for a response carrying these blocks."""
    handler = RecordingHandler()
    Master(handler=handler)._parse_response_objects(blocks, response_info())
    return handler.calls


def delivered(block: ObjectBlock, callback: str) -> list[PointValue]:
    """The values one block delivers on ``callback``, failing if any other callback fires."""
    calls = dispatch([block])
    stray = [name for name, _ in calls if name != callback]
    assert not stray, f"block delivered on {stray}, expected only {callback}"
    return [value for _, values in calls for value in values]
