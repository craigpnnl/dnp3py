"""Master response handlers per IEEE 1815-2012.

Handlers for processing responses from outstations, including
static data, events, and command responses.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from dnp3.core.enums import CommandStatus, FunctionCode
from dnp3.core.flags import IIN


@dataclass(frozen=True)
class BinaryValue:
    """Binary input/output value from response.

    Attributes:
        index: Point index.
        value: Binary state (True=ON, False=OFF).
        quality: Quality flags.
        timestamp: Event timestamp if available.
    """

    index: int
    value: bool
    quality: int = 0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class AnalogValue:
    """Analog input/output value from response.

    Attributes:
        index: Point index.
        value: Analog value.
        quality: Quality flags.
        timestamp: Event timestamp if available.
    """

    index: int
    value: float
    quality: int = 0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class CounterValue:
    """Counter value from response.

    Attributes:
        index: Point index.
        value: Counter value.
        quality: Quality flags.
        timestamp: Event timestamp if available.
    """

    index: int
    value: int
    quality: int = 0
    timestamp: datetime | None = None


@dataclass(frozen=True)
class CommandResponse:
    """Response to a control command.

    Attributes:
        index: Point index.
        status: Command status.
        message: Optional status message.
    """

    index: int
    status: CommandStatus
    message: str = ""

    @property
    def is_success(self) -> bool:
        """Check if command was successful."""
        return self.status == CommandStatus.SUCCESS


@dataclass
class ResponseInfo:
    """Information about a response.

    Attributes:
        function: Response function code.
        iin: Internal indications.
        sequence: Application sequence number.
        is_unsolicited: True if this was an unsolicited response.
    """

    function: FunctionCode
    iin: IIN
    sequence: int
    is_unsolicited: bool = False


@runtime_checkable
class SOEHandler(Protocol):
    """Protocol for handling Sequence of Events (SOE) data.

    Implement this to receive data from polling and unsolicited responses.
    """

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        """Called when binary input values are received.

        Args:
            values: List of binary input values.
            info: Response information.
        """
        ...

    def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        """Called when binary output values are received.

        Args:
            values: List of binary output values.
            info: Response information.
        """
        ...

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        """Called when analog input values are received.

        Args:
            values: List of analog input values.
            info: Response information.
        """
        ...

    def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        """Called when analog output values are received.

        Args:
            values: List of analog output values.
            info: Response information.
        """
        ...

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        """Called when counter values are received.

        Args:
            values: List of counter values.
            info: Response information.
        """
        ...

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        """Called when frozen counter values are received.

        Args:
            values: List of frozen counter values.
            info: Response information.
        """
        ...


@runtime_checkable
class ResponseHandler(Protocol):
    """Protocol for handling general response events."""

    def on_response_received(self, info: ResponseInfo) -> None:
        """Called when any response is received.

        Args:
            info: Response information.
        """
        ...

    def on_response_timeout(self) -> None:
        """Called when a response timeout occurs."""
        ...

    def on_communication_error(self, error: Exception) -> None:
        """Called when a communication error occurs.

        Args:
            error: The exception that occurred.
        """
        ...


class DefaultSOEHandler:
    """Default SOE handler that stores received values.

    This handler stores the most recent values for each point type,
    which can be retrieved via the properties.
    """

    def __init__(self) -> None:
        """Initialize the handler."""
        self._binary_inputs: dict[int, BinaryValue] = {}
        self._binary_outputs: dict[int, BinaryValue] = {}
        self._analog_inputs: dict[int, AnalogValue] = {}
        self._analog_outputs: dict[int, AnalogValue] = {}
        self._counters: dict[int, CounterValue] = {}
        self._frozen_counters: dict[int, CounterValue] = {}
        self._last_response: ResponseInfo | None = None

    @property
    def binary_inputs(self) -> dict[int, BinaryValue]:
        """Get all binary input values by index."""
        return self._binary_inputs.copy()

    @property
    def binary_outputs(self) -> dict[int, BinaryValue]:
        """Get all binary output values by index."""
        return self._binary_outputs.copy()

    @property
    def analog_inputs(self) -> dict[int, AnalogValue]:
        """Get all analog input values by index."""
        return self._analog_inputs.copy()

    @property
    def analog_outputs(self) -> dict[int, AnalogValue]:
        """Get all analog output values by index."""
        return self._analog_outputs.copy()

    @property
    def counters(self) -> dict[int, CounterValue]:
        """Get all counter values by index."""
        return self._counters.copy()

    @property
    def frozen_counters(self) -> dict[int, CounterValue]:
        """Get all frozen counter values by index."""
        return self._frozen_counters.copy()

    @property
    def last_response(self) -> ResponseInfo | None:
        """Get the last response info received."""
        return self._last_response

    def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        """Store binary input values."""
        for value in values:
            self._binary_inputs[value.index] = value
        self._last_response = info

    def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
        """Store binary output values."""
        for value in values:
            self._binary_outputs[value.index] = value
        self._last_response = info

    def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        """Store analog input values."""
        for value in values:
            self._analog_inputs[value.index] = value
        self._last_response = info

    def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
        """Store analog output values."""
        for value in values:
            self._analog_outputs[value.index] = value
        self._last_response = info

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        """Store counter values."""
        for value in values:
            self._counters[value.index] = value
        self._last_response = info

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        """Store frozen counter values."""
        for value in values:
            self._frozen_counters[value.index] = value
        self._last_response = info

    def get_binary_input(self, index: int) -> BinaryValue | None:
        """Get a specific binary input value."""
        return self._binary_inputs.get(index)

    def get_binary_output(self, index: int) -> BinaryValue | None:
        """Get a specific binary output value."""
        return self._binary_outputs.get(index)

    def get_analog_input(self, index: int) -> AnalogValue | None:
        """Get a specific analog input value."""
        return self._analog_inputs.get(index)

    def get_analog_output(self, index: int) -> AnalogValue | None:
        """Get a specific analog output value."""
        return self._analog_outputs.get(index)

    def get_counter(self, index: int) -> CounterValue | None:
        """Get a specific counter value."""
        return self._counters.get(index)

    def get_frozen_counter(self, index: int) -> CounterValue | None:
        """Get a specific frozen counter value."""
        return self._frozen_counters.get(index)

    def clear(self) -> None:
        """Clear all stored values."""
        self._binary_inputs.clear()
        self._binary_outputs.clear()
        self._analog_inputs.clear()
        self._analog_outputs.clear()
        self._counters.clear()
        self._frozen_counters.clear()
        self._last_response = None
