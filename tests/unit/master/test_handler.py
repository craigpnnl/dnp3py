"""Tests for master response handlers."""

from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.enums import CommandStatus, FunctionCode
from dnp3.core.flags import IIN
from dnp3.master.handler import (
    AnalogValue,
    BinaryValue,
    CommandResponse,
    CounterValue,
    DefaultSOEHandler,
    ResponseHandler,
    ResponseInfo,
    SOEHandler,
)


class TestBinaryValue:
    """Tests for BinaryValue."""

    def test_creation(self) -> None:
        """Test creating a binary value."""
        value = BinaryValue(index=0, value=True)

        assert value.index == 0
        assert value.value is True
        assert value.quality == 0
        assert value.timestamp is None

    def test_with_quality(self) -> None:
        """Test binary value with quality flags."""
        value = BinaryValue(index=5, value=False, quality=0x01)

        assert value.index == 5
        assert value.value is False
        assert value.quality == 0x01

    def test_with_timestamp(self) -> None:
        """Test binary value with timestamp."""
        ts = datetime(2024, 1, 15, 12, 30, 45)
        value = BinaryValue(index=10, value=True, timestamp=ts)

        assert value.timestamp == ts

    def test_is_frozen(self) -> None:
        """Test that BinaryValue is immutable."""
        value = BinaryValue(index=0, value=True)
        with pytest.raises(AttributeError):
            value.value = False  # type: ignore[misc]

    @given(
        index=st.integers(min_value=0, max_value=65535),
        value=st.booleans(),
        quality=st.integers(min_value=0, max_value=255),
    )
    def test_property_based(self, index: int, value: bool, quality: int) -> None:
        """Test binary value with various values."""
        bv = BinaryValue(index=index, value=value, quality=quality)

        assert bv.index == index
        assert bv.value == value
        assert bv.quality == quality


class TestAnalogValue:
    """Tests for AnalogValue."""

    def test_creation(self) -> None:
        """Test creating an analog value."""
        value = AnalogValue(index=0, value=123.45)

        assert value.index == 0
        assert value.value == 123.45
        assert value.quality == 0
        assert value.timestamp is None

    def test_with_quality(self) -> None:
        """Test analog value with quality flags."""
        value = AnalogValue(index=5, value=-100.5, quality=0x02)

        assert value.index == 5
        assert value.value == -100.5
        assert value.quality == 0x02

    def test_with_timestamp(self) -> None:
        """Test analog value with timestamp."""
        ts = datetime(2024, 1, 15, 12, 30, 45)
        value = AnalogValue(index=10, value=0.0, timestamp=ts)

        assert value.timestamp == ts

    def test_is_frozen(self) -> None:
        """Test that AnalogValue is immutable."""
        value = AnalogValue(index=0, value=0.0)
        with pytest.raises(AttributeError):
            value.value = 1.0  # type: ignore[misc]

    @given(
        index=st.integers(min_value=0, max_value=65535),
        value=st.floats(allow_nan=False, allow_infinity=False),
        quality=st.integers(min_value=0, max_value=255),
    )
    def test_property_based(self, index: int, value: float, quality: int) -> None:
        """Test analog value with various values."""
        av = AnalogValue(index=index, value=value, quality=quality)

        assert av.index == index
        assert av.value == value
        assert av.quality == quality


class TestCounterValue:
    """Tests for CounterValue."""

    def test_creation(self) -> None:
        """Test creating a counter value."""
        value = CounterValue(index=0, value=12345)

        assert value.index == 0
        assert value.value == 12345
        assert value.quality == 0
        assert value.timestamp is None

    def test_with_quality(self) -> None:
        """Test counter value with quality flags."""
        value = CounterValue(index=5, value=0, quality=0x04)

        assert value.index == 5
        assert value.value == 0
        assert value.quality == 0x04

    def test_with_timestamp(self) -> None:
        """Test counter value with timestamp."""
        ts = datetime(2024, 1, 15, 12, 30, 45)
        value = CounterValue(index=10, value=999, timestamp=ts)

        assert value.timestamp == ts

    def test_is_frozen(self) -> None:
        """Test that CounterValue is immutable."""
        value = CounterValue(index=0, value=0)
        with pytest.raises(AttributeError):
            value.value = 1  # type: ignore[misc]

    @given(
        index=st.integers(min_value=0, max_value=65535),
        value=st.integers(min_value=0, max_value=2**32 - 1),
        quality=st.integers(min_value=0, max_value=255),
    )
    def test_property_based(self, index: int, value: int, quality: int) -> None:
        """Test counter value with various values."""
        cv = CounterValue(index=index, value=value, quality=quality)

        assert cv.index == index
        assert cv.value == value
        assert cv.quality == quality


class TestCommandResponse:
    """Tests for CommandResponse."""

    def test_success(self) -> None:
        """Test successful command response."""
        resp = CommandResponse(index=0, status=CommandStatus.SUCCESS)

        assert resp.index == 0
        assert resp.status == CommandStatus.SUCCESS
        assert resp.message == ""
        assert resp.is_success is True

    def test_failure(self) -> None:
        """Test failed command response."""
        resp = CommandResponse(
            index=5,
            status=CommandStatus.NOT_SUPPORTED,
            message="Operation not supported",
        )

        assert resp.index == 5
        assert resp.status == CommandStatus.NOT_SUPPORTED
        assert resp.message == "Operation not supported"
        assert resp.is_success is False

    def test_various_statuses(self) -> None:
        """Test various command statuses."""
        statuses = [
            CommandStatus.TIMEOUT,
            CommandStatus.NO_SELECT,
            CommandStatus.FORMAT_ERROR,
            CommandStatus.ALREADY_ACTIVE,
            CommandStatus.HARDWARE_ERROR,
            CommandStatus.LOCAL,
            CommandStatus.TOO_MANY_OBJS,
            CommandStatus.NOT_AUTHORIZED,
            CommandStatus.AUTOMATION_INHIBIT,
            CommandStatus.PROCESSING_LIMITED,
            CommandStatus.OUT_OF_RANGE,
            CommandStatus.DOWNSTREAM_LOCAL,
            CommandStatus.BLOCKED,
            CommandStatus.CANCELLED,
            CommandStatus.BLOCKED_OTHER_MASTER,
            CommandStatus.DOWNSTREAM_FAIL,
        ]

        for status in statuses:
            resp = CommandResponse(index=0, status=status)
            assert resp.is_success is False

    def test_is_frozen(self) -> None:
        """Test that CommandResponse is immutable."""
        resp = CommandResponse(index=0, status=CommandStatus.SUCCESS)
        with pytest.raises(AttributeError):
            resp.status = CommandStatus.TIMEOUT  # type: ignore[misc]


class TestResponseInfo:
    """Tests for ResponseInfo."""

    def test_creation(self) -> None:
        """Test creating response info."""
        iin = IIN(0)  # No flags set
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=iin,
            sequence=5,
        )

        assert info.function == FunctionCode.RESPONSE
        assert info.iin == iin
        assert info.sequence == 5
        assert info.is_unsolicited is False

    def test_unsolicited_response(self) -> None:
        """Test unsolicited response info."""
        iin = IIN(0)
        info = ResponseInfo(
            function=FunctionCode.UNSOLICITED_RESPONSE,
            iin=iin,
            sequence=3,
            is_unsolicited=True,
        )

        assert info.function == FunctionCode.UNSOLICITED_RESPONSE
        assert info.is_unsolicited is True

    def test_with_iin_flags(self) -> None:
        """Test response info with IIN flags."""
        iin = IIN.BROADCAST | IIN.CLASS_1_EVENTS | IIN.DEVICE_RESTART
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=iin,
            sequence=0,
        )

        assert IIN.BROADCAST in info.iin
        assert IIN.CLASS_1_EVENTS in info.iin
        assert IIN.DEVICE_RESTART in info.iin


class TestSOEHandlerProtocol:
    """Tests for SOEHandler protocol."""

    def test_protocol_check(self) -> None:
        """Test that DefaultSOEHandler implements SOEHandler."""
        handler = DefaultSOEHandler()
        assert isinstance(handler, SOEHandler)

    def test_custom_implementation(self) -> None:
        """Test custom SOE handler implementation."""

        class CustomHandler:
            def __init__(self) -> None:
                self.binary_calls: list[list[BinaryValue]] = []
                self.analog_calls: list[list[AnalogValue]] = []
                self.counter_calls: list[list[CounterValue]] = []

            def on_binary_input(self, values: list[BinaryValue], info: ResponseInfo) -> None:
                self.binary_calls.append(values)

            def on_binary_output(self, values: list[BinaryValue], info: ResponseInfo) -> None:
                pass

            def on_analog_input(self, values: list[AnalogValue], info: ResponseInfo) -> None:
                self.analog_calls.append(values)

            def on_analog_output(self, values: list[AnalogValue], info: ResponseInfo) -> None:
                pass

            def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
                self.counter_calls.append(values)

            def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
                pass

        handler = CustomHandler()
        assert isinstance(handler, SOEHandler)


class TestDefaultSOEHandler:
    """Tests for DefaultSOEHandler."""

    def test_initial_state(self) -> None:
        """Test initial handler state."""
        handler = DefaultSOEHandler()

        assert handler.binary_inputs == {}
        assert handler.binary_outputs == {}
        assert handler.analog_inputs == {}
        assert handler.analog_outputs == {}
        assert handler.counters == {}
        assert handler.frozen_counters == {}
        assert handler.last_response is None

    def test_on_binary_input(self) -> None:
        """Test handling binary input values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            BinaryValue(index=0, value=True),
            BinaryValue(index=1, value=False),
            BinaryValue(index=5, value=True, quality=0x01),
        ]

        handler.on_binary_input(values, info)

        assert len(handler.binary_inputs) == 3
        assert handler.binary_inputs[0].value is True
        assert handler.binary_inputs[1].value is False
        assert handler.binary_inputs[5].quality == 0x01
        assert handler.last_response == info

    def test_on_binary_output(self) -> None:
        """Test handling binary output values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            BinaryValue(index=0, value=True),
            BinaryValue(index=2, value=False),
        ]

        handler.on_binary_output(values, info)

        assert len(handler.binary_outputs) == 2
        assert handler.binary_outputs[0].value is True
        assert handler.binary_outputs[2].value is False

    def test_on_analog_input(self) -> None:
        """Test handling analog input values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            AnalogValue(index=0, value=100.5),
            AnalogValue(index=1, value=-50.25),
        ]

        handler.on_analog_input(values, info)

        assert len(handler.analog_inputs) == 2
        assert handler.analog_inputs[0].value == 100.5
        assert handler.analog_inputs[1].value == -50.25

    def test_on_analog_output(self) -> None:
        """Test handling analog output values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            AnalogValue(index=0, value=75.0),
        ]

        handler.on_analog_output(values, info)

        assert len(handler.analog_outputs) == 1
        assert handler.analog_outputs[0].value == 75.0

    def test_on_counter(self) -> None:
        """Test handling counter values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            CounterValue(index=0, value=12345),
            CounterValue(index=1, value=67890),
        ]

        handler.on_counter(values, info)

        assert len(handler.counters) == 2
        assert handler.counters[0].value == 12345
        assert handler.counters[1].value == 67890

    def test_on_frozen_counter(self) -> None:
        """Test handling frozen counter values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        values = [
            CounterValue(index=0, value=1000),
        ]

        handler.on_frozen_counter(values, info)

        assert len(handler.frozen_counters) == 1
        assert handler.frozen_counters[0].value == 1000

    def test_get_specific_values(self) -> None:
        """Test getting specific values by index."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        handler.on_binary_input([BinaryValue(index=5, value=True)], info)
        handler.on_binary_output([BinaryValue(index=3, value=False)], info)
        handler.on_analog_input([AnalogValue(index=2, value=50.0)], info)
        handler.on_analog_output([AnalogValue(index=1, value=25.0)], info)
        handler.on_counter([CounterValue(index=4, value=100)], info)
        handler.on_frozen_counter([CounterValue(index=6, value=200)], info)

        assert handler.get_binary_input(5) is not None
        assert handler.get_binary_input(5).value is True  # type: ignore[union-attr]
        assert handler.get_binary_input(0) is None

        assert handler.get_binary_output(3) is not None
        assert handler.get_binary_output(0) is None

        assert handler.get_analog_input(2) is not None
        assert handler.get_analog_input(2).value == 50.0  # type: ignore[union-attr]
        assert handler.get_analog_input(0) is None

        assert handler.get_analog_output(1) is not None
        assert handler.get_analog_output(0) is None

        assert handler.get_counter(4) is not None
        assert handler.get_counter(4).value == 100  # type: ignore[union-attr]
        assert handler.get_counter(0) is None

        assert handler.get_frozen_counter(6) is not None
        assert handler.get_frozen_counter(0) is None

    def test_update_existing_value(self) -> None:
        """Test that new values update existing ones."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        # Initial value
        handler.on_binary_input([BinaryValue(index=0, value=True)], info)
        assert handler.binary_inputs[0].value is True

        # Update value
        handler.on_binary_input([BinaryValue(index=0, value=False)], info)
        assert handler.binary_inputs[0].value is False

    def test_clear(self) -> None:
        """Test clearing all stored values."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        handler.on_binary_input([BinaryValue(index=0, value=True)], info)
        handler.on_analog_input([AnalogValue(index=0, value=100.0)], info)
        handler.on_counter([CounterValue(index=0, value=1000)], info)

        assert len(handler.binary_inputs) == 1
        assert len(handler.analog_inputs) == 1
        assert len(handler.counters) == 1
        assert handler.last_response is not None

        handler.clear()

        assert len(handler.binary_inputs) == 0
        assert len(handler.analog_inputs) == 0
        assert len(handler.counters) == 0
        assert handler.last_response is None

    def test_returns_copy_of_data(self) -> None:
        """Test that properties return copies, not references."""
        handler = DefaultSOEHandler()
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )

        handler.on_binary_input([BinaryValue(index=0, value=True)], info)

        # Get a copy
        bi_copy = handler.binary_inputs
        # Modify the copy
        bi_copy[99] = BinaryValue(index=99, value=False)

        # Original should be unchanged
        assert 99 not in handler.binary_inputs


class TestResponseHandlerProtocol:
    """Tests for ResponseHandler protocol."""

    def test_custom_implementation(self) -> None:
        """Test custom response handler implementation."""

        class CustomResponseHandler:
            def __init__(self) -> None:
                self.response_count = 0
                self.timeout_count = 0
                self.errors: list[Exception] = []

            def on_response_received(self, info: ResponseInfo) -> None:
                self.response_count += 1

            def on_response_timeout(self) -> None:
                self.timeout_count += 1

            def on_communication_error(self, error: Exception) -> None:
                self.errors.append(error)

        handler = CustomResponseHandler()
        assert isinstance(handler, ResponseHandler)

        # Test methods work
        info = ResponseInfo(
            function=FunctionCode.RESPONSE,
            iin=IIN(0),
            sequence=0,
        )
        handler.on_response_received(info)
        assert handler.response_count == 1

        handler.on_response_timeout()
        assert handler.timeout_count == 1

        handler.on_communication_error(TimeoutError("Test"))
        assert len(handler.errors) == 1
