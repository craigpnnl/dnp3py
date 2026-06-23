"""Tests for main Outstation class."""

import struct

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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE

    def test_read_binary_inputs(self) -> None:
        """READ returns binary inputs."""
        outstation = Outstation()
        outstation.database.add_binary_input(0, value=True)
        outstation.database.add_binary_input(1, value=False)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert len(response.objects) > 0

    def test_read_class_0(self) -> None:
        """READ Class 0 returns all static data."""
        outstation = Outstation()
        outstation.database.add_binary_input(0)
        outstation.database.add_analog_input(0)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None

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

        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert IIN.OBJECT_UNKNOWN in response.header.iin


class TestWriteRequests:
    """Tests for WRITE request handling."""

    def test_write_returns_null_response(self) -> None:
        """WRITE returns null response."""
        outstation = Outstation()

        # Build simple WRITE request
        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=())

        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE


class TestDelayMeasure:
    """Tests for DELAY_MEASURE handling."""

    def test_delay_measure_returns_time_delay(self) -> None:
        """DELAY_MEASURE returns time delay object."""
        outstation = Outstation()
        request = build_delay_measure_request()

        response = outstation.process_request(request.to_bytes())

        assert response is not None
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

        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert outstation._state.unsolicited.class_1_enabled is True
        assert outstation._state.unsolicited.class_2_enabled is False
        assert outstation._state.unsolicited.class_3_enabled is False

    def test_enable_unsolicited_all_classes(self) -> None:
        """ENABLE_UNSOLICITED enables all classes."""
        outstation = Outstation()
        request = build_enable_unsolicited_request(class_1=True, class_2=True, class_3=True)

        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        # Check that select state was stored
        assert outstation._state.get_select(0) is not None


class TestRestartHandling:
    """Tests for restart request handling."""

    def test_cold_restart_not_supported(self) -> None:
        """Cold restart returns NO_FUNC_CODE_SUPPORT when handler returns None."""
        outstation = Outstation()

        from dnp3.application.builder import build_cold_restart_request

        request = build_cold_restart_request()
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert IIN.NO_FUNC_CODE_SUPPORT in response.header.iin

    def test_cold_restart_supported(self) -> None:
        """Cold restart returns time delay when handler supports it."""

        class RestartHandler(DefaultCommandHandler):
            def cold_restart(self) -> int | None:
                return 5000  # 5 second delay

        outstation = Outstation(handler=RestartHandler())

        from dnp3.application.builder import build_cold_restart_request

        request = build_cold_restart_request()
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert IIN.NO_FUNC_CODE_SUPPORT in response.header.iin


class TestParseError:
    """Tests for parse error handling."""

    def test_malformed_request(self) -> None:
        """Malformed request returns PARAMETER_ERROR IIN."""
        outstation = Outstation()

        # Send garbage bytes
        response = outstation.process_request(b"\x00")

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        # Should have objects for each point type


# ---------------------------------------------------------------------------
# Issue #6 regression tests
# ---------------------------------------------------------------------------


def _make_crob_block(qualifier: int, index: int) -> ObjectBlock:
    """Build a raw CROB ObjectBlock for the given qualifier and point index.

    qualifier 0x17: 1-byte count + 1-byte index prefix per object.
    qualifier 0x28: 2-byte count + 2-byte index prefix per object.

    CROB payload (11 bytes): control_code(1) + op_count(1) + on_time(4) +
    off_time(4) + status(1).
    """
    # LATCH_ON control code = 3
    control_code = 0x03
    op_count = 1
    on_time = 500  # ms
    off_time = 0

    if qualifier == 0x17:
        count_bytes = bytes([1])
        index_bytes = bytes([index & 0xFF])
    else:  # 0x28
        count_bytes = struct.pack("<H", 1)
        index_bytes = struct.pack("<H", index)

    crob_payload = bytes([control_code, op_count]) + struct.pack("<II", on_time, off_time) + bytes([0])

    data = count_bytes + index_bytes + crob_payload
    header = ObjectHeader(group=12, variation=1, qualifier=qualifier)
    return ObjectBlock(header=header, data=data)


class TestStaticResponseQualifiers:
    """Issue #6 Finding 1: static builders must emit start/stop range qualifiers.

    IEEE 1815-2012 requires static (Class-0) responses to use qualifier 0x00
    (1-byte start/stop) or 0x01 (2-byte start/stop), never 0x17/0x28 which are
    the count+index event forms.
    """

    def test_binary_input_static_uses_start_stop_qualifier_1byte(self) -> None:
        """Binary input static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        outstation.database.add_binary_input(0, value=True)
        outstation.database.add_binary_input(1, value=False)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1, "Expected exactly one g1v2 block"
        # Qualifier 0x00 = prefix NONE + range UINT8_START_STOP
        assert (
            bi_blocks[0].header.qualifier == 0x00
        ), f"Expected qualifier 0x00 (1-byte start/stop), got 0x{bi_blocks[0].header.qualifier:02X}"
        # range_data is 2 bytes: start=0, stop=1
        assert bi_blocks[0].data[0] == 0, "start index must be 0"
        assert bi_blocks[0].data[1] == 1, "stop index must be 1"

    def test_binary_input_static_qualifier_not_event_form(self) -> None:
        """Binary input static response must NOT emit 0x17 or 0x28."""
        outstation = Outstation()
        outstation.database.add_binary_input(5, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1
        qualifier = bi_blocks[0].header.qualifier
        assert qualifier not in (0x17, 0x28), f"Static response must not use event qualifier 0x{qualifier:02X}"

    def test_binary_input_static_uses_2byte_start_stop_for_large_index(self) -> None:
        """Binary input static response uses qualifier 0x01 (2-byte start/stop) for index > 255."""
        outstation = Outstation()
        outstation.database.add_binary_input(256, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1
        # Qualifier 0x01 = prefix NONE + range UINT16_START_STOP
        assert bi_blocks[0].header.qualifier == 0x01, (
            f"Expected qualifier 0x01 (2-byte start/stop) for index 256, " f"got 0x{bi_blocks[0].header.qualifier:02X}"
        )
        # range_data is 4 bytes: start and stop both = 256 (little-endian)
        start = struct.unpack_from("<H", bi_blocks[0].data, 0)[0]
        stop = struct.unpack_from("<H", bi_blocks[0].data, 2)[0]
        assert start == 256, f"start must be 256, got {start}"
        assert stop == 256, f"stop must be 256, got {stop}"

    def test_analog_input_static_uses_start_stop_qualifier(self) -> None:
        """Analog input static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        outstation.database.add_analog_input(0, value=42.0)
        outstation.database.add_analog_input(3, value=7.0)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        ai_blocks = [b for b in response.objects if b.header.group == 30]
        assert len(ai_blocks) == 1
        assert (
            ai_blocks[0].header.qualifier == 0x00
        ), f"Expected qualifier 0x00, got 0x{ai_blocks[0].header.qualifier:02X}"
        assert ai_blocks[0].data[0] == 0, "start index must be 0"
        assert ai_blocks[0].data[1] == 3, "stop index must be 3"

    def test_counter_static_uses_start_stop_qualifier(self) -> None:
        """Counter static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        outstation.database.add_counter(0, value=100)
        outstation.database.add_counter(2, value=200)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        ctr_blocks = [b for b in response.objects if b.header.group == 20]
        assert len(ctr_blocks) == 1
        assert (
            ctr_blocks[0].header.qualifier == 0x00
        ), f"Expected qualifier 0x00, got 0x{ctr_blocks[0].header.qualifier:02X}"
        assert ctr_blocks[0].data[0] == 0
        assert ctr_blocks[0].data[1] == 2

    def test_binary_output_static_uses_start_stop_qualifier(self) -> None:
        """Binary output static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        outstation.database.add_binary_output(0, value=False)
        outstation.database.add_binary_output(4, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bo_blocks = [b for b in response.objects if b.header.group == 10]
        assert len(bo_blocks) == 1
        assert (
            bo_blocks[0].header.qualifier == 0x00
        ), f"Expected qualifier 0x00, got 0x{bo_blocks[0].header.qualifier:02X}"
        assert bo_blocks[0].data[0] == 0
        assert bo_blocks[0].data[1] == 4


class TestCROBQualifierParsing:
    """Issue #6 Finding 3: CROB handlers must derive count/index width from qualifier.

    A qualifier 0x28 CROB carries a 2-byte count followed by 2-byte index prefixes.
    Hardcoding 1-byte reads misaligns every subsequent field so the command
    lands on the wrong point.
    """

    def _make_handler(self) -> "tuple[DefaultCommandHandler, list[int]]":
        """Return a handler that records which indices were directly operated."""
        operated: list[int] = []

        class RecordingHandler(DefaultCommandHandler):
            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                operated.append(index)
                return CommandResult.success()

        return RecordingHandler(), operated

    def test_crob_1byte_qualifier_0x17_operates_correct_index(self) -> None:
        """CROB with qualifier 0x17 (1-byte index) operates the exact point addressed."""
        handler, operated = self._make_handler()
        outstation = Outstation(handler=handler)
        outstation.database.add_binary_output(5)

        block = _make_crob_block(qualifier=0x17, index=5)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        outstation.process_request(request.to_bytes())

        assert operated == [5], f"Expected point index 5 operated, got {operated}"

    def test_crob_2byte_qualifier_0x28_operates_correct_index(self) -> None:
        """CROB with qualifier 0x28 (2-byte index) operates the exact point addressed.

        Index 300 does not fit in one byte; a 1-byte read would produce 300 % 256 = 44
        as the index, operating the wrong point.
        """
        handler, operated = self._make_handler()
        outstation = Outstation(handler=handler)
        outstation.database.add_binary_output(300)

        block = _make_crob_block(qualifier=0x28, index=300)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        outstation.process_request(request.to_bytes())

        assert operated == [300], (
            f"Expected point index 300 operated, got {operated}. "
            "A value of 44 indicates the 2-byte index was truncated to 1 byte."
        )

    def test_crob_2byte_qualifier_0x28_parses_control_code_correctly(self) -> None:
        """CROB with qualifier 0x28 parses the control code at the correct offset.

        When the index is 2 bytes wide, the control code byte lives 2 bytes after
        the count, not 1. Misalignment would deliver a garbled control code.
        """
        received_codes: list[ControlCode] = []

        class CodeRecordingHandler(DefaultCommandHandler):
            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                received_codes.append(code)
                return CommandResult.success()

        outstation = Outstation(handler=CodeRecordingHandler())
        outstation.database.add_binary_output(300)

        block = _make_crob_block(qualifier=0x28, index=300)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        outstation.process_request(request.to_bytes())

        # _make_crob_block sets control_code = 0x03 = LATCH_ON
        assert received_codes == [ControlCode.LATCH_ON], (
            f"Expected LATCH_ON, got {received_codes}. " "A misaligned offset would produce a wrong control code."
        )
