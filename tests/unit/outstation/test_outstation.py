"""Tests for main Outstation class."""

from dnp3.application.builder import (
    build_class_poll,
    build_delay_measure_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
    build_integrity_poll,
    build_read_request,
)
from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader, PrefixCode, RangeCode
from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.core.flags import IIN
from dnp3.database import Database, EventClass
from dnp3.database.point import BinaryInputConfig
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation
from dnp3.outstation.state import OutstationState


class TestOutstationCreation:
    """Tests for Outstation creation."""

    def test_default_creation(self) -> None:
        """Can create with defaults."""
        outstation = Outstation()
        assert outstation.config is not None
        assert outstation.database is not None
        assert outstation.handler is not None

    def test_custom_config(self) -> None:
        """Can create with custom config."""
        config = OutstationConfig(address=10)
        outstation = Outstation(config=config)
        assert outstation.config.address == 10

    def test_custom_database(self) -> None:
        """Can create with custom database."""
        database = Database()
        database.add_binary_input(0)
        outstation = Outstation(database=database)
        assert outstation.database.binary_input_count == 1

    def test_custom_handler(self) -> None:
        """Can create with custom handler."""
        handler = DefaultCommandHandler()
        outstation = Outstation(handler=handler)
        assert outstation.handler is handler

    def test_initial_state_is_idle(self) -> None:
        """Initial state is IDLE."""
        outstation = Outstation()
        assert outstation.state == OutstationState.IDLE

    def test_initial_iin_has_device_restart(self) -> None:
        """Initial IIN has DEVICE_RESTART flag."""
        outstation = Outstation()
        assert IIN.DEVICE_RESTART in outstation.iin

    def test_initial_iin_has_need_time(self) -> None:
        """Initial IIN has NEED_TIME flag if configured."""
        config = OutstationConfig(time_sync_required=True)
        outstation = Outstation(config=config)
        assert IIN.NEED_TIME in outstation.iin

    def test_initial_iin_no_need_time(self) -> None:
        """Initial IIN has no NEED_TIME flag if not configured."""
        config = OutstationConfig(time_sync_required=False)
        outstation = Outstation(config=config)
        assert IIN.NEED_TIME not in outstation.iin


class TestReadRequests:
    """Tests for READ request handling."""

    def test_read_empty_database(self) -> None:
        """READ returns empty response for empty database."""
        outstation = Outstation()
        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert response.header.function == FunctionCode.RESPONSE

    def test_read_binary_inputs(self) -> None:
        """READ returns binary inputs."""
        outstation = Outstation()
        outstation.database.add_binary_input(0, value=True)
        outstation.database.add_binary_input(1, value=False)

        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0

    def test_read_class_0(self) -> None:
        """READ Class 0 returns all static data."""
        outstation = Outstation()
        outstation.database.add_binary_input(0)
        outstation.database.add_analog_input(0)

        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        # Should have objects for both point types
        assert len(response.objects) >= 2

    def test_read_class_1_events(self) -> None:
        """READ Class 1 returns Class 1 events."""
        outstation = Outstation()
        config = BinaryInputConfig(event_class=EventClass.CLASS_1)
        outstation.database.add_binary_input(0, config=config, value=False)
        # Generate an event
        outstation.database.update_binary_input(0, value=True)

        request = build_class_poll(class_1=True, class_2=False, class_3=False)
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]

    def test_read_unknown_object(self) -> None:
        """READ unknown object returns OBJECT_UNKNOWN IIN."""
        outstation = Outstation()

        # Create request with unknown group
        header = ObjectHeader.build(
            group=99,  # Unknown group
            variation=1,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        block = ObjectBlock(header=header)
        request = build_read_request(objects=(block,))

        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert IIN.OBJECT_UNKNOWN in response.header.iin


class TestWriteRequests:
    """Tests for WRITE request handling."""

    def test_write_returns_null_response(self) -> None:
        """WRITE returns null response."""
        outstation = Outstation()

        # Build simple WRITE request
        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=())

        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert response.header.function == FunctionCode.RESPONSE


class TestDelayMeasure:
    """Tests for DELAY_MEASURE handling."""

    def test_delay_measure_returns_time_delay(self) -> None:
        """DELAY_MEASURE returns time delay object."""
        outstation = Outstation()
        request = build_delay_measure_request()

        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0
        # Should be g52v2 (time delay fine)
        assert response.objects[0].header.group == 52
        assert response.objects[0].header.variation == 2

    def test_delay_measure_clears_need_time(self) -> None:
        """DELAY_MEASURE clears NEED_TIME IIN."""
        config = OutstationConfig(time_sync_required=True)
        outstation = Outstation(config=config)

        assert IIN.NEED_TIME in outstation.iin

        request = build_delay_measure_request()
        outstation.process_request(request.to_bytes())

        assert IIN.NEED_TIME not in outstation.iin


class TestUnsolicitedControl:
    """Tests for unsolicited response control."""

    def test_enable_unsolicited_class_1(self) -> None:
        """ENABLE_UNSOLICITED enables Class 1."""
        outstation = Outstation()
        request = build_enable_unsolicited_request(class_1=True, class_2=False, class_3=False)

        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert outstation._state.unsolicited.class_1_enabled is True
        assert outstation._state.unsolicited.class_2_enabled is False
        assert outstation._state.unsolicited.class_3_enabled is False

    def test_enable_unsolicited_all_classes(self) -> None:
        """ENABLE_UNSOLICITED enables all classes."""
        outstation = Outstation()
        request = build_enable_unsolicited_request(class_1=True, class_2=True, class_3=True)

        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert outstation._state.unsolicited.class_1_enabled is True
        assert outstation._state.unsolicited.class_2_enabled is True
        assert outstation._state.unsolicited.class_3_enabled is True

    def test_disable_unsolicited(self) -> None:
        """DISABLE_UNSOLICITED disables classes."""
        outstation = Outstation()
        # First enable
        enable_req = build_enable_unsolicited_request()
        outstation.process_request(enable_req.to_bytes())

        # Then disable
        request = build_disable_unsolicited_request(class_1=True, class_2=True, class_3=True)
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert outstation._state.unsolicited.class_1_enabled is False
        assert outstation._state.unsolicited.class_2_enabled is False
        assert outstation._state.unsolicited.class_3_enabled is False


class TestGenerateUnsolicited:
    """Tests for unsolicited response generation."""

    def test_no_unsolicited_when_disabled(self) -> None:
        """No unsolicited when all classes disabled."""
        outstation = Outstation()
        # Add some events
        config = BinaryInputConfig(event_class=EventClass.CLASS_1)
        outstation.database.add_binary_input(0, config=config)
        outstation.database.update_binary_input(0, value=True)

        response = outstation.generate_unsolicited()
        assert response is None

    def test_unsolicited_when_enabled(self) -> None:
        """Unsolicited generated when class enabled and events pending."""
        outstation = Outstation()
        config = BinaryInputConfig(event_class=EventClass.CLASS_1)
        outstation.database.add_binary_input(0, config=config)
        outstation.database.update_binary_input(0, value=True)

        # Enable unsolicited
        outstation._state.unsolicited.class_1_enabled = True

        response = outstation.generate_unsolicited()
        assert response is not None
        assert response.header.function == FunctionCode.UNSOLICITED_RESPONSE

    def test_no_unsolicited_when_no_events(self) -> None:
        """No unsolicited when no events pending."""
        outstation = Outstation()
        outstation._state.unsolicited.class_1_enabled = True

        response = outstation.generate_unsolicited()
        assert response is None


class TestIINFlags:
    """Tests for IIN flag management."""

    def test_iin_updates_with_events(self) -> None:
        """IIN event flags update based on event buffer."""
        outstation = Outstation()
        config = BinaryInputConfig(event_class=EventClass.CLASS_1)
        outstation.database.add_binary_input(0, config=config)

        # No events initially
        assert IIN.CLASS_1_EVENTS not in outstation.iin

        # Generate event
        outstation.database.update_binary_input(0, value=True)

        # Now should have CLASS_1_EVENTS
        assert IIN.CLASS_1_EVENTS in outstation.iin

    def test_clear_restart(self) -> None:
        """clear_restart clears DEVICE_RESTART flag."""
        outstation = Outstation()
        assert IIN.DEVICE_RESTART in outstation.iin

        outstation.clear_restart()

        assert IIN.DEVICE_RESTART not in outstation.iin


class TestSelectBeforeOperate:
    """Tests for SELECT-BEFORE-OPERATE handling."""

    def test_select_stores_state(self) -> None:
        """SELECT stores state for later OPERATE."""

        class TestHandler(DefaultCommandHandler):
            def select_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                if index == 0:
                    return CommandResult.success()
                return CommandResult.not_supported()

        outstation = Outstation(handler=TestHandler())

        # Build SELECT request for CROB
        # CROB format: control(1) + count(1) + on_time(4) + off_time(4) + status(1)
        crob_data = bytes(
            [
                1,  # count
                0,  # index
                0x03,  # control code (LATCH_ON)
                1,  # count
                0,
                0,
                0,
                0,  # on_time
                0,
                0,
                0,
                0,  # off_time
                0,  # status
            ]
        )
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=crob_data)

        from dnp3.application.builder import build_select_request

        request = build_select_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        # Check that select state was stored
        assert outstation._state.get_select(0) is not None


class TestRestartHandling:
    """Tests for restart request handling."""

    def test_cold_restart_not_supported(self) -> None:
        """Cold restart returns NO_FUNC_CODE_SUPPORT when handler returns None."""
        outstation = Outstation()

        from dnp3.application.builder import build_cold_restart_request

        request = build_cold_restart_request()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert IIN.NO_FUNC_CODE_SUPPORT in response.header.iin

    def test_cold_restart_supported(self) -> None:
        """Cold restart returns time delay when handler supports it."""

        class RestartHandler(DefaultCommandHandler):
            def cold_restart(self) -> int | None:
                return 5000  # 5 second delay

        outstation = Outstation(handler=RestartHandler())

        from dnp3.application.builder import build_cold_restart_request

        request = build_cold_restart_request()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert IIN.NO_FUNC_CODE_SUPPORT not in response.header.iin
        assert len(response.objects) > 0
        assert response.objects[0].header.group == 52  # Time delay

    def test_warm_restart_supported(self) -> None:
        """Warm restart returns time delay when handler supports it."""

        class RestartHandler(DefaultCommandHandler):
            def warm_restart(self) -> int | None:
                return 1000

        outstation = Outstation(handler=RestartHandler())

        from dnp3.application.builder import build_warm_restart_request

        request = build_warm_restart_request()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert IIN.NO_FUNC_CODE_SUPPORT not in response.header.iin


class TestUnsupportedFunctionCodes:
    """Tests for unsupported function code handling."""

    def test_unsupported_function_code(self) -> None:
        """Unsupported function code returns NO_FUNC_CODE_SUPPORT IIN."""
        outstation = Outstation()

        # Build request with unsupported function code
        from dnp3.application.header import RequestHeader

        header = RequestHeader.build(function=FunctionCode.OPEN_FILE)
        from dnp3.application.fragment import RequestFragment

        request = RequestFragment(header=header)
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert IIN.NO_FUNC_CODE_SUPPORT in response.header.iin


class TestParseError:
    """Tests for parse error handling."""

    def test_malformed_request(self) -> None:
        """Malformed request returns PARAMETER_ERROR IIN."""
        outstation = Outstation()

        # Send garbage bytes
        responses = outstation.process_request(b"\x00")

        assert len(responses) > 0
        response = responses[0]
        assert IIN.PARAMETER_ERROR in response.header.iin


class TestEventClearOnRead:
    """Tests for event clearing when read."""

    def test_events_cleared_after_read(self) -> None:
        """Events are cleared after being read."""
        outstation = Outstation()
        config = BinaryInputConfig(event_class=EventClass.CLASS_1)
        outstation.database.add_binary_input(0, config=config)
        outstation.database.update_binary_input(0, value=True)

        # Verify event exists
        assert outstation.database.event_buffer.class1.count > 0

        # Read Class 1 events
        request = build_class_poll(class_1=True, class_2=False, class_3=False)
        outstation.process_request(request.to_bytes())

        # Events should be cleared
        assert outstation.database.event_buffer.class1.count == 0


class TestMultiplePointTypes:
    """Tests for reading multiple point types."""

    def test_read_all_point_types(self) -> None:
        """Can read all point types in integrity poll."""
        outstation = Outstation()
        outstation.database.add_binary_input(0, value=True)
        outstation.database.add_binary_output(0, value=False)
        outstation.database.add_analog_input(0, value=100.5)
        outstation.database.add_counter(0, value=1000)

        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        # Should have objects for each point type
        assert len(response.objects) >= 4


class TestDirectOperateResponse:
    """Tests for DIRECT_OPERATE response format compliance.

    Per IEEE 1815-2012, DIRECT_OPERATE responses must echo back the
    command objects with a status field in each, not return a null response.
    """

    def test_direct_operate_crob_returns_echoed_objects(self) -> None:
        """DIRECT_OPERATE with CROB echoes back command objects with status."""

        class AcceptHandler(DefaultCommandHandler):
            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                return CommandResult.success()

        outstation = Outstation(handler=AcceptHandler())
        outstation.database.add_binary_output(0, value=False)

        # Build CROB data: count(1) + [index(1) + CROB(11)] ...
        # CROB: control_code(1) + count(1) + on_time(4) + off_time(4) + status(1)
        crob_data = bytes(
            [
                1,  # count = 1 object
                0,  # index = 0
                0x03,  # control code = LATCH_ON
                1,  # operation count
                0,
                0,
                0,
                0,  # on_time = 0
                0,
                0,
                0,
                0,  # off_time = 0
                0,  # status (in request, always 0)
            ]
        )
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=crob_data)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert response.header.function == FunctionCode.RESPONSE
        # Response MUST contain echoed command objects, not be empty
        assert len(response.objects) > 0, "DIRECT_OPERATE response must echo command objects"
        # The echoed object block should be Group 12 Variation 1
        resp_block = response.objects[0]
        assert resp_block.header.group == 12
        assert resp_block.header.variation == 1

    def test_direct_operate_crob_echoes_success_status(self) -> None:
        """DIRECT_OPERATE echoed CROB contains SUCCESS status byte."""

        class AcceptHandler(DefaultCommandHandler):
            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                return CommandResult.success()

        outstation = Outstation(handler=AcceptHandler())
        outstation.database.add_binary_output(0, value=False)

        crob_data = bytes(
            [
                1,
                0,
                0x03,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=crob_data)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        # Parse response: count(1) + index(1) + CROB(11)
        # CROB status byte is at offset: 1 (count) + 1 (index) + 10 (crob fields) = byte 12
        assert len(resp_data) >= 13, f"Response data too short: {len(resp_data)} bytes"
        status_byte = resp_data[12]  # Last byte of CROB is status
        assert status_byte == 0, f"Expected SUCCESS (0), got status={status_byte}"

    def test_direct_operate_crob_not_supported_status(self) -> None:
        """DIRECT_OPERATE echoed CROB contains NOT_SUPPORTED status when rejected."""
        # DefaultCommandHandler rejects all operations
        outstation = Outstation()
        outstation.database.add_binary_output(0, value=False)

        crob_data = bytes(
            [
                1,
                0,
                0x03,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=crob_data)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        assert len(resp_data) >= 13
        status_byte = resp_data[12]
        from dnp3.core.enums import CommandStatus

        assert (
            status_byte == CommandStatus.NOT_SUPPORTED
        ), f"Expected NOT_SUPPORTED ({CommandStatus.NOT_SUPPORTED}), got status={status_byte}"


class TestDirectOperateAnalogOutput:
    """Tests for DIRECT_OPERATE with Analog Output (Group 41)."""

    def test_direct_operate_analog_output_returns_echoed_objects(self) -> None:
        """DIRECT_OPERATE with Group 41 Var 1 echoes back with status."""

        class AcceptAOHandler(DefaultCommandHandler):
            def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
                return CommandResult.success()

        outstation = Outstation(handler=AcceptAOHandler())
        outstation.database.add_analog_input(0, value=0.0)

        # Build AO data: count(1) + [index(1) + value(4) + status(1)]
        ao_data = bytearray()
        ao_data.append(1)  # count = 1
        ao_data.append(0)  # index = 0
        ao_data.extend((100).to_bytes(4, "little", signed=True))  # value = 100
        ao_data.append(0)  # status (request)

        header = ObjectHeader(group=41, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=bytes(ao_data))

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0, "AO DIRECT_OPERATE must echo objects"
        resp_block = response.objects[0]
        assert resp_block.header.group == 41
        assert resp_block.header.variation == 1

    def test_direct_operate_analog_output_success_status(self) -> None:
        """DIRECT_OPERATE AO echoes SUCCESS status byte and calls handler."""
        handler_called = False

        class AcceptAOHandler(DefaultCommandHandler):
            def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
                nonlocal handler_called
                handler_called = True
                return CommandResult.success()

        outstation = Outstation(handler=AcceptAOHandler())
        outstation.database.add_analog_input(0, value=0.0)

        ao_data = bytearray()
        ao_data.append(1)
        ao_data.append(0)
        ao_data.extend((100).to_bytes(4, "little", signed=True))
        ao_data.append(0)

        header = ObjectHeader(group=41, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=bytes(ao_data))

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert handler_called, "direct_operate_analog_output handler must be called"
        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        # count(1) + index(1) + value(4) + status(1) = 7 bytes
        assert len(resp_data) >= 7
        status_byte = resp_data[6]  # status byte at end
        assert status_byte == 0, f"Expected SUCCESS (0), got {status_byte}"

    def test_direct_operate_analog_output_not_supported(self) -> None:
        """DIRECT_OPERATE AO echoes NOT_SUPPORTED when handler rejects."""
        # DefaultCommandHandler rejects all
        outstation = Outstation()

        ao_data = bytearray()
        ao_data.append(1)
        ao_data.append(0)
        ao_data.extend((100).to_bytes(4, "little", signed=True))
        ao_data.append(0)

        header = ObjectHeader(group=41, variation=1, qualifier=0x17)
        block = ObjectBlock(header=header, data=bytes(ao_data))

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        assert len(resp_data) >= 7
        status_byte = resp_data[6]
        from dnp3.core.enums import CommandStatus

        assert (
            status_byte == CommandStatus.NOT_SUPPORTED
        ), f"Expected NOT_SUPPORTED ({CommandStatus.NOT_SUPPORTED}), got {status_byte}"


class TestWriteIINRestart:
    """Tests for WRITE Group 80 Variation 1 to clear DEVICE_RESTART.

    Per IEEE 1815-2012, a WRITE with g80v1 index 7 value 0 clears
    the DEVICE_RESTART bit in IIN.
    """

    def test_iin_has_restart_initially(self) -> None:
        """Outstation has DEVICE_RESTART set after creation."""
        outstation = Outstation()
        assert IIN.DEVICE_RESTART in outstation.iin

    def test_write_g80v1_clears_restart_bit(self) -> None:
        """WRITE g80v1 index 7 value 0 clears DEVICE_RESTART in IIN."""
        outstation = Outstation()
        assert IIN.DEVICE_RESTART in outstation.iin

        # Build WRITE request with Group 80 Variation 1
        # g80v1 is Internal Indications - single bit objects
        # We need to write index 7 (DEVICE_RESTART) with value 0
        # Qualifier 0x00 = start-stop range, 1-byte indices
        # Start = 7, Stop = 7, data = 1 byte with bit value 0
        g80v1_header = ObjectHeader(group=80, variation=1, qualifier=0x00)
        # Range: start=7, stop=7 (1 byte each), data: 1 byte with value 0
        range_data = bytes([7, 7])  # start=7, stop=7
        bit_data = bytes([0x00])  # clear the bit
        block = ObjectBlock(header=g80v1_header, data=range_data + bit_data)

        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert response.header.function == FunctionCode.RESPONSE
        # After processing, DEVICE_RESTART should be cleared
        assert (
            IIN.DEVICE_RESTART not in outstation.iin
        ), "DEVICE_RESTART should be cleared after WRITE g80v1 index 7 value 0"

    def test_write_g80v1_response_has_no_objects(self) -> None:
        """WRITE g80v1 response has no objects (null response body)."""
        outstation = Outstation()

        g80v1_header = ObjectHeader(group=80, variation=1, qualifier=0x00)
        range_data = bytes([7, 7])
        bit_data = bytes([0x00])
        block = ObjectBlock(header=g80v1_header, data=range_data + bit_data)

        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=(block,))
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) > 0
        response = responses[0]
        assert len(response.objects) == 0, "WRITE response should have no objects"

    def test_write_g80v1_does_not_clear_other_iin_bits(self) -> None:
        """WRITE g80v1 only clears DEVICE_RESTART, not other IIN bits."""
        config = OutstationConfig(time_sync_required=True)
        outstation = Outstation(config=config)

        assert IIN.DEVICE_RESTART in outstation.iin
        assert IIN.NEED_TIME in outstation.iin

        g80v1_header = ObjectHeader(group=80, variation=1, qualifier=0x00)
        range_data = bytes([7, 7])
        bit_data = bytes([0x00])
        block = ObjectBlock(header=g80v1_header, data=range_data + bit_data)

        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=(block,))
        outstation.process_request(request.to_bytes())

        assert IIN.DEVICE_RESTART not in outstation.iin
        # NEED_TIME should still be set
        assert IIN.NEED_TIME in outstation.iin
