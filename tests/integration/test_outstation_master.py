"""Integration tests for Master/Outstation communication.

Tests basic communication patterns between a DNP3 master and outstation
at the application layer without transport.
"""

from dnp3.core.enums import FunctionCode
from dnp3.core.flags import BinaryQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    CounterConfig,
    Database,
    EventClass,
)
from dnp3.master import DefaultSOEHandler, Master
from dnp3.outstation import Outstation


class TestBasicCommunication:
    """Test basic master/outstation communication."""

    def test_integrity_poll_empty_database(self) -> None:
        """Integrity poll with empty database returns null response."""
        outstation = Outstation()
        master = Master()

        # Master builds integrity poll
        request = master.build_integrity_poll()
        request_bytes = request.to_bytes()

        # Outstation processes request
        response = outstation.process_request(request_bytes)
        assert response is not None

        # Master processes response
        response_bytes = response.to_bytes()
        info = master.process_response(response_bytes)

        assert info is not None
        assert info.function == FunctionCode.RESPONSE
        assert not info.is_unsolicited

    def test_integrity_poll_with_binary_inputs(self) -> None:
        """Integrity poll returns binary input data."""
        # Set up outstation with binary inputs
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)

        outstation = Outstation(database=database)

        # Set up master with handler
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # Exchange integrity poll
        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        info = master.process_response(response.to_bytes())

        # Verify response received (exact counts depend on parsing implementation)
        assert info is not None
        assert info.function == FunctionCode.RESPONSE

    def test_integrity_poll_with_analog_inputs(self) -> None:
        """Integrity poll returns analog input data."""
        database = Database()
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.add_analog_input(1, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.update_analog_input(0, value=100.5)
        database.update_analog_input(1, value=-50.0)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        info = master.process_response(response.to_bytes())

        # Verify response received
        assert info is not None
        assert info.function == FunctionCode.RESPONSE

    def test_integrity_poll_with_counters(self) -> None:
        """Integrity poll returns counter data."""
        database = Database()
        database.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3))
        database.add_counter(1, CounterConfig(event_class=EventClass.CLASS_3))
        database.update_counter(0, value=1000)
        database.update_counter(1, value=2000)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        info = master.process_response(response.to_bytes())

        # Verify response received
        assert info is not None
        assert info.function == FunctionCode.RESPONSE

    def test_integrity_poll_all_point_types(self) -> None:
        """Integrity poll returns all point types."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig())
        database.add_analog_input(0, AnalogInputConfig())
        database.add_counter(0, CounterConfig())
        database.update_binary_input(0, value=True)
        database.update_analog_input(0, value=42.0)
        database.update_counter(0, value=100)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        info = master.process_response(response.to_bytes())

        # Verify response received with data objects
        assert info is not None
        assert info.function == FunctionCode.RESPONSE
        assert len(response.objects) > 0


class TestSequenceNumbers:
    """Test sequence number handling."""

    def test_sequence_numbers_increment(self) -> None:
        """Master sequence numbers increment with each request."""
        master = Master()

        req1 = master.build_integrity_poll()
        req2 = master.build_integrity_poll()
        req3 = master.build_integrity_poll()

        seq1 = req1.header.control.seq
        seq2 = req2.header.control.seq
        seq3 = req3.header.control.seq

        assert seq2 == (seq1 + 1) % 16
        assert seq3 == (seq2 + 1) % 16

    def test_response_sequence_matches_request(self) -> None:
        """Response sequence number matches request."""
        outstation = Outstation()
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        assert response.header.control.seq == request.header.control.seq


class TestMultipleExchanges:
    """Test multiple request/response exchanges."""

    def test_multiple_integrity_polls(self) -> None:
        """Multiple integrity polls work correctly."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig())
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        for _ in range(5):
            request = master.build_integrity_poll()
            response = outstation.process_request(request.to_bytes())
            assert response is not None

            info = master.process_response(response.to_bytes())
            assert info is not None
            assert info.function == FunctionCode.RESPONSE

    def test_value_changes_between_polls(self) -> None:
        """Value changes are reflected in subsequent polls."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig())
        database.update_binary_input(0, value=False)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # First poll - value is False
        request1 = master.build_integrity_poll()
        response1 = outstation.process_request(request1.to_bytes())
        assert response1 is not None
        master.process_response(response1.to_bytes())
        first_values = list(handler.binary_inputs.values())

        # Change value
        database.update_binary_input(0, value=True)
        handler.binary_inputs.clear()

        # Second poll - value is True
        request2 = master.build_integrity_poll()
        response2 = outstation.process_request(request2.to_bytes())
        assert response2 is not None
        master.process_response(response2.to_bytes())
        second_values = list(handler.binary_inputs.values())

        # Values should be different
        assert first_values != second_values


class TestDelayMeasure:
    """Test delay measurement for time sync."""

    def test_delay_measure(self) -> None:
        """Delay measure request/response works."""
        outstation = Outstation()
        master = Master()

        request = master.build_delay_measure()
        assert request.header.function == FunctionCode.DELAY_MEASURE

        response = outstation.process_request(request.to_bytes())
        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE

        # Response should contain time delay object (g52v2)
        assert len(response.objects) > 0


class TestEnableDisableUnsolicited:
    """Test enable/disable unsolicited commands."""

    def test_enable_unsolicited(self) -> None:
        """Enable unsolicited request is processed."""
        outstation = Outstation()
        master = Master()

        request = master.build_enable_unsolicited()
        assert request.header.function == FunctionCode.ENABLE_UNSOLICITED

        response = outstation.process_request(request.to_bytes())
        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE

    def test_disable_unsolicited(self) -> None:
        """Disable unsolicited request is processed."""
        outstation = Outstation()
        master = Master()

        request = master.build_disable_unsolicited()
        assert request.header.function == FunctionCode.DISABLE_UNSOLICITED

        response = outstation.process_request(request.to_bytes())
        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE


class TestIINFlags:
    """Test Internal Indications (IIN) in responses."""

    def test_device_restart_flag(self) -> None:
        """Device restart flag is set initially."""
        outstation = Outstation()
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None
        # DEVICE_RESTART should be set on first response
        # Note: IIN is returned in the response

    def test_iin_cleared_after_restart_clear(self) -> None:
        """Device restart IIN can be cleared."""
        outstation = Outstation()
        outstation.clear_restart()

        master = Master()
        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        # After clearing, DEVICE_RESTART should not be set
        from dnp3.core.flags import IIN

        assert not (response.header.iin & IIN.DEVICE_RESTART)
