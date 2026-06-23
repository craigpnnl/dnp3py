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
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.core.flags import IIN
from dnp3.database import Database, EventClass
from dnp3.database.point import BinaryInputConfig
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation, ParsedCrob, _contiguous_runs, _parse_crob_block
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
        assert len(response.objects) >= 4


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
        assert bi_blocks[0].header.qualifier == 0x00, (
            f"Expected qualifier 0x00 (1-byte start/stop), got 0x{bi_blocks[0].header.qualifier:02X}"
        )
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
            f"Expected qualifier 0x01 (2-byte start/stop) for index 256, got 0x{bi_blocks[0].header.qualifier:02X}"
        )
        # range_data is 4 bytes: start and stop both = 256 (little-endian)
        start = struct.unpack_from("<H", bi_blocks[0].data, 0)[0]
        stop = struct.unpack_from("<H", bi_blocks[0].data, 2)[0]
        assert start == 256, f"start must be 256, got {start}"
        assert stop == 256, f"stop must be 256, got {stop}"

    def test_analog_input_static_uses_start_stop_qualifier(self) -> None:
        """Analog input static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        # Use contiguous indices so a single block is emitted; sparse behaviour
        # is covered by TestSparseIndexStaticResponse.
        outstation.database.add_analog_input(0, value=42.0)
        outstation.database.add_analog_input(1, value=7.0)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        ai_blocks = [b for b in response.objects if b.header.group == 30]
        assert len(ai_blocks) == 1
        assert ai_blocks[0].header.qualifier == 0x00, (
            f"Expected qualifier 0x00, got 0x{ai_blocks[0].header.qualifier:02X}"
        )
        assert ai_blocks[0].data[0] == 0, "start index must be 0"
        assert ai_blocks[0].data[1] == 1, "stop index must be 1"

    def test_counter_static_uses_start_stop_qualifier(self) -> None:
        """Counter static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        # Contiguous indices; sparse behaviour is covered by TestSparseIndexStaticResponse.
        outstation.database.add_counter(0, value=100)
        outstation.database.add_counter(1, value=200)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        ctr_blocks = [b for b in response.objects if b.header.group == 20]
        assert len(ctr_blocks) == 1
        assert ctr_blocks[0].header.qualifier == 0x00, (
            f"Expected qualifier 0x00, got 0x{ctr_blocks[0].header.qualifier:02X}"
        )
        assert ctr_blocks[0].data[0] == 0
        assert ctr_blocks[0].data[1] == 1

    def test_binary_output_static_uses_start_stop_qualifier(self) -> None:
        """Binary output static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        # Contiguous indices; sparse behaviour is covered by TestSparseIndexStaticResponse.
        outstation.database.add_binary_output(0, value=False)
        outstation.database.add_binary_output(1, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bo_blocks = [b for b in response.objects if b.header.group == 10]
        assert len(bo_blocks) == 1
        assert bo_blocks[0].header.qualifier == 0x00, (
            f"Expected qualifier 0x00, got 0x{bo_blocks[0].header.qualifier:02X}"
        )
        assert bo_blocks[0].data[0] == 0
        assert bo_blocks[0].data[1] == 1


class TestCROBQualifierParsing:
    """Issue #6 Finding 3: CROB handlers must derive count/index width from qualifier.

    A qualifier 0x28 CROB carries a 2-byte count followed by 2-byte index prefixes.
    Hardcoding 1-byte reads misaligns every subsequent field so the command
    lands on the wrong point.
    """

    def _make_handler(self) -> tuple[DefaultCommandHandler, list[int]]:
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
            f"Expected LATCH_ON, got {received_codes}. A misaligned offset would produce a wrong control code."
        )


# ---------------------------------------------------------------------------
# Issue #6 review-round-2 regression tests
# ---------------------------------------------------------------------------


def _make_crob_block_raw(qualifier: int, payload: bytes) -> ObjectBlock:
    """Build a CROB ObjectBlock with a raw payload (for truncation and bad-code tests)."""
    header = ObjectHeader(group=12, variation=1, qualifier=qualifier)
    return ObjectBlock(header=header, data=payload)


class TestStaticQualifierBoundary:
    """Coverage gaps: boundary index 255 vs 256, empty list, frozen-counter builder."""

    def test_binary_input_stop_index_255_uses_1byte_qualifier(self) -> None:
        """Stop index exactly 255 must use qualifier 0x00 (1-byte start/stop).

        Only one point at index 255 is registered so the encoder emits a single
        block [255..255] with the 1-byte qualifier.
        """
        outstation = Outstation()
        outstation.database.add_binary_input(255, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1
        assert bi_blocks[0].header.qualifier == 0x00, (
            f"Stop index 255 must use 0x00 (1-byte), got 0x{bi_blocks[0].header.qualifier:02X}"
        )
        assert bi_blocks[0].data[0] == 255, "start must be 255"
        assert bi_blocks[0].data[1] == 255, "stop must be 255"

    def test_binary_input_stop_index_256_uses_2byte_qualifier(self) -> None:
        """Stop index 256 must use qualifier 0x01 (2-byte start/stop)."""
        outstation = Outstation()
        outstation.database.add_binary_input(256, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1
        assert bi_blocks[0].header.qualifier == 0x01, (
            f"Stop index 256 must use 0x01 (2-byte), got 0x{bi_blocks[0].header.qualifier:02X}"
        )

    def test_frozen_counter_static_uses_start_stop_qualifier(self) -> None:
        """Frozen counter static response uses qualifier 0x00 (1-byte start/stop)."""
        outstation = Outstation()
        # Contiguous indices; sparse behaviour is covered by TestSparseIndexStaticResponse.
        outstation.database.add_frozen_counter(0, value=10)
        outstation.database.add_frozen_counter(1, value=20)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        fc_blocks = [b for b in response.objects if b.header.group == 21]
        assert len(fc_blocks) == 1
        assert fc_blocks[0].header.qualifier == 0x00, (
            f"Expected qualifier 0x00, got 0x{fc_blocks[0].header.qualifier:02X}"
        )
        assert fc_blocks[0].data[0] == 0
        assert fc_blocks[0].data[1] == 1

    def test_empty_point_list_returns_no_block(self) -> None:
        """Static builder with no points returns empty list (exercises the guard branch)."""
        outstation = Outstation()
        # No binary inputs configured, so the builder receives an empty list.
        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert bi_blocks == [], "No g1 block expected when no binary inputs configured"


class TestCROBUnknownQualifier:
    """Fix A: unknown qualifier must return FORMAT_ERROR and produce PARAMETER_ERROR IIN.

    The test exercises _process_crob_* directly because the parser canonicalises
    incoming bytes and some invalid qualifier values are not safely round-trippable
    through the application-layer serializer (e.g. qualifier 0x06 = ALL_OBJECTS
    causes the parser to treat subsequent payload bytes as new object headers).
    The correct test surface is therefore: (1) the CROB processor returns
    FORMAT_ERROR for an unknown qualifier, and (2) _build_control_response maps
    FORMAT_ERROR to IIN.PARAMETER_ERROR.  Together those prove the full Fix-A
    signal chain without depending on an unparseable wire frame.
    """

    def _make_g12_block(self, qualifier: int) -> ObjectBlock:
        # Any non-empty payload so the length guard doesn't short-circuit.
        return _make_crob_block_raw(qualifier=qualifier, payload=bytes([1, 0, 0x03, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]))

    def test_direct_operate_unknown_qualifier_returns_format_error(self) -> None:
        """_process_crob_direct_operate returns FORMAT_ERROR for unknown qualifier 0x06."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        block = self._make_g12_block(qualifier=0x06)
        results = outstation._process_crob_direct_operate(block)

        assert len(results) == 1
        assert results[0][1] == CommandStatus.FORMAT_ERROR, f"Expected FORMAT_ERROR, got {results[0][1]}"

    def test_select_unknown_qualifier_returns_format_error(self) -> None:
        """_process_crob_select returns FORMAT_ERROR for unknown qualifier 0x06."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        block = self._make_g12_block(qualifier=0x06)
        results = outstation._process_crob_select(block, seq=0)

        assert len(results) == 1
        assert results[0][1] == CommandStatus.FORMAT_ERROR, f"Expected FORMAT_ERROR, got {results[0][1]}"

    def test_operate_unknown_qualifier_returns_format_error(self) -> None:
        """_process_crob_operate returns FORMAT_ERROR for unknown qualifier 0x06."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        block = self._make_g12_block(qualifier=0x06)
        results = outstation._process_crob_operate(block, seq=0)

        assert len(results) == 1
        assert results[0][1] == CommandStatus.FORMAT_ERROR, f"Expected FORMAT_ERROR, got {results[0][1]}"

    def test_build_control_response_maps_format_error_to_parameter_error_iin(self) -> None:
        """_build_control_response sets IIN.PARAMETER_ERROR when results contain FORMAT_ERROR.

        This is the IIN leg of Fix A: the FORMAT_ERROR result from unknown-qualifier
        detection propagates to IIN.PARAMETER_ERROR in the wire response.
        """
        from dnp3.application.builder import build_direct_operate_request
        from dnp3.application.parser import parse_request

        outstation = Outstation()
        # Build a minimal valid DIRECT_OPERATE request to extract a RequestFragment.
        valid_block = _make_crob_block(qualifier=0x17, index=0)
        raw_request = build_direct_operate_request(objects=(valid_block,))
        request = parse_request(raw_request.to_bytes())

        results = [(0, CommandStatus.FORMAT_ERROR)]
        response = outstation._build_control_response(request, results)

        assert IIN.PARAMETER_ERROR in response.header.iin, (
            f"FORMAT_ERROR result must produce IIN.PARAMETER_ERROR, got IIN=0x{int(response.header.iin):04X}"
        )


class TestCROBSelectOperate2ByteQualifier:
    """Fix coverage gap: SELECT and OPERATE with qualifier 0x28 and index > 255."""

    def test_select_2byte_qualifier_stores_correct_index(self) -> None:
        """SELECT with qualifier 0x28 stores the state for the addressed index (300)."""

        class AcceptAllHandler(DefaultCommandHandler):
            def select_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                return CommandResult.success()

        outstation = Outstation(handler=AcceptAllHandler())
        outstation.database.add_binary_output(300)

        block = _make_crob_block(qualifier=0x28, index=300)

        from dnp3.application.builder import build_select_request

        request = build_select_request(objects=(block,))
        outstation.process_request(request.to_bytes())

        # The state should be stored for index 300, not 300 % 256 = 44.
        assert outstation._state.get_select(300) is not None, "Select state for index 300 must be stored"
        assert outstation._state.get_select(44) is None, "No state for index 44 (wrong truncation)"

    def test_operate_2byte_qualifier_operates_correct_index(self) -> None:
        """OPERATE after SELECT with qualifier 0x28 executes at the correct index (300)."""
        operated: list[int] = []

        class RecordingHandler(DefaultCommandHandler):
            def select_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                return CommandResult.success()

            def operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
                select_sequence: int,
            ) -> CommandResult:
                operated.append(index)
                return CommandResult.success()

        outstation = Outstation(handler=RecordingHandler())
        outstation.database.add_binary_output(300)

        block = _make_crob_block(qualifier=0x28, index=300)

        from dnp3.application.builder import build_operate_request, build_select_request

        # SELECT first.
        sel_request = build_select_request(objects=(block,))
        outstation.process_request(sel_request.to_bytes())

        # Then OPERATE.
        op_request = build_operate_request(objects=(block,))
        outstation.process_request(op_request.to_bytes())

        assert operated == [300], f"Expected index 300 operated, got {operated}. Truncation to 1 byte would produce 44."


class TestCROBTruncatedBuffer:
    """Fix C: a truncated CROB buffer must surface PARAMETER_ERROR, not silent drop."""

    def test_truncated_0x28_buffer_sets_parameter_error(self) -> None:
        """CROB 0x28 with a buffer too short for even one full object sets PARAMETER_ERROR.

        Payload declares count=1 but provides fewer than 2 (index) + 11 (body) = 13
        bytes after the 2-byte count header, so the buffer is truncated.
        """
        outstation = Outstation()
        outstation.database.add_binary_output(300)

        # count=1 (2 bytes little-endian) + 5 bytes (short: needs 13 more)
        truncated_payload = struct.pack("<H", 1) + bytes(5)
        block = _make_crob_block_raw(qualifier=0x28, payload=truncated_payload)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert IIN.PARAMETER_ERROR in response.header.iin, (
            f"Truncated buffer must set PARAMETER_ERROR, got IIN=0x{int(response.header.iin):04X}"
        )

    def test_truncated_0x17_buffer_sets_parameter_error(self) -> None:
        """CROB 0x17 with a buffer too short for one object sets PARAMETER_ERROR."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        # count=1 (1 byte) + 3 bytes (short: needs 1 index + 11 body = 12 more)
        truncated_payload = bytes([1]) + bytes(3)
        block = _make_crob_block_raw(qualifier=0x17, payload=truncated_payload)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert IIN.PARAMETER_ERROR in response.header.iin, (
            f"Truncated 0x17 buffer must set PARAMETER_ERROR, got IIN=0x{int(response.header.iin):04X}"
        )


class TestCROBBadControlCode:
    """Fix B: an undefined control-code nibble must return FORMAT_ERROR and PARAMETER_ERROR IIN.

    Verified call-flow: ControlCode(undefined_nibble) raises ValueError inside the
    CROB object loop. That loop runs inside _process_crob_*, which is called by
    _handle_direct_operate / _handle_select / _handle_operate. Those are called from
    _process_request_fragment, which has NO outer try/except. The outer try/except in
    process_request at line 236 only wraps parse_request(), not _process_request_fragment.
    So Leon is correct: without the local catch added by Fix B, the ValueError would
    propagate out of process_request entirely (one-frame DoS). Fix B adds a per-object
    try/except around the ControlCode() call in all three CROB handlers.
    """

    def test_bad_control_code_does_not_raise(self) -> None:
        """An undefined nibble (0x05) must not raise from process_request."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        # nibble 0x05 is not a valid ControlCode
        bad_cc_byte = 0x05
        payload = bytes([1, 0, bad_cc_byte, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        block = _make_crob_block_raw(qualifier=0x17, payload=payload)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        # Must not raise ValueError.
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_bad_control_code_sets_parameter_error(self) -> None:
        """An undefined nibble (0x05) must produce IIN.PARAMETER_ERROR."""
        outstation = Outstation()
        outstation.database.add_binary_output(0)

        bad_cc_byte = 0x05
        payload = bytes([1, 0, bad_cc_byte, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        block = _make_crob_block_raw(qualifier=0x17, payload=payload)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert IIN.PARAMETER_ERROR in response.header.iin, (
            f"Bad control code must set PARAMETER_ERROR, got IIN=0x{int(response.header.iin):04X}"
        )


class TestContiguousRuns:
    """Unit tests for the _contiguous_runs helper.

    _contiguous_runs is the correctness kernel for sparse-index encoding:
    it must never group points from different gaps into the same ObjectBlock
    (which would imply non-existent intermediate objects on the wire).
    """

    class _Pt:
        """Minimal point stub for _contiguous_runs."""

        def __init__(self, index: int) -> None:
            self.index = index

    def _pts(self, *indices: int) -> list["TestContiguousRuns._Pt"]:
        return [self._Pt(i) for i in indices]

    def test_empty_list_returns_empty(self) -> None:
        """Empty input produces no runs."""
        assert _contiguous_runs([]) == []

    def test_single_point_is_one_run(self) -> None:
        """A single point is its own run."""
        runs = _contiguous_runs(self._pts(5))
        assert len(runs) == 1
        assert runs[0][0].index == 5

    def test_dense_range_is_one_run(self) -> None:
        """Contiguous indices 0,1,2 produce one run."""
        runs = _contiguous_runs(self._pts(0, 1, 2))
        assert len(runs) == 1
        assert [p.index for p in runs[0]] == [0, 1, 2]

    def test_sparse_indices_produce_multiple_runs(self) -> None:
        """Indices [0, 5, 10] contain two gaps so yield three runs."""
        runs = _contiguous_runs(self._pts(0, 5, 10))
        assert len(runs) == 3
        assert runs[0][0].index == 0
        assert runs[1][0].index == 5
        assert runs[2][0].index == 10

    def test_mixed_dense_and_sparse(self) -> None:
        """[0,1,5,6,10] yields three runs: [0,1], [5,6], [10]."""
        runs = _contiguous_runs(self._pts(0, 1, 5, 6, 10))
        assert len(runs) == 3
        assert [p.index for p in runs[0]] == [0, 1]
        assert [p.index for p in runs[1]] == [5, 6]
        assert [p.index for p in runs[2]] == [10]


class TestSparseIndexStaticResponse:
    """Task 1: static builders must not emit a bogus start/stop range that implies
    non-existent intermediate objects when the database holds sparse indices.

    Data-invariants Rule 1: the wire encoding must match the actual data.
    A start/stop range [0..10] implies 11 objects; if only 3 are serialized the
    master will misparse the rest of the APDU.
    """

    def test_binary_input_sparse_yields_multiple_blocks(self) -> None:
        """Binary inputs at [0, 5, 10] produce three separate ObjectBlocks.

        Each block covers exactly one contiguous run, so no range header falsely
        implies the existence of points 1-4 or 6-9.
        """
        outstation = Outstation()
        outstation.database.add_binary_input(0, value=True)
        outstation.database.add_binary_input(5, value=False)
        outstation.database.add_binary_input(10, value=True)

        request = build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 3, (
            f"Three sparse binary input points must produce 3 ObjectBlocks, got {len(bi_blocks)}"
        )
        # First block: range [0..0], one byte of data
        assert bi_blocks[0].header.qualifier == 0x00, "Block 0 must use qualifier 0x00"
        assert bi_blocks[0].data[0] == 0, "Block 0 start must be 0"
        assert bi_blocks[0].data[1] == 0, "Block 0 stop must be 0"
        # Second block: range [5..5]
        assert bi_blocks[1].header.qualifier == 0x00
        assert bi_blocks[1].data[0] == 5
        assert bi_blocks[1].data[1] == 5
        # Third block: range [10..10]
        assert bi_blocks[2].header.qualifier == 0x00
        assert bi_blocks[2].data[0] == 10
        assert bi_blocks[2].data[1] == 10

    def test_binary_input_contiguous_is_one_block(self) -> None:
        """Binary inputs at [0, 1, 2] (dense) still produce a single block."""
        outstation = Outstation()
        for i in range(3):
            outstation.database.add_binary_input(i)

        response = outstation.process_request(build_integrity_poll().to_bytes())
        assert response is not None
        bi_blocks = [b for b in response.objects if b.header.group == 1]
        assert len(bi_blocks) == 1, "Dense indices must produce exactly one block"
        assert bi_blocks[0].data[0] == 0
        assert bi_blocks[0].data[1] == 2

    def test_analog_input_sparse_yields_multiple_blocks(self) -> None:
        """Analog inputs at [3, 7] (gap at 4-6) produce two ObjectBlocks."""
        outstation = Outstation()
        outstation.database.add_analog_input(3, value=1.0)
        outstation.database.add_analog_input(7, value=2.0)

        response = outstation.process_request(build_integrity_poll().to_bytes())
        assert response is not None
        ai_blocks = [b for b in response.objects if b.header.group == 30]
        assert len(ai_blocks) == 2, (
            f"Two sparse analog inputs with a gap must produce 2 ObjectBlocks, got {len(ai_blocks)}"
        )
        assert ai_blocks[0].data[0] == 3
        assert ai_blocks[0].data[1] == 3
        assert ai_blocks[1].data[0] == 7
        assert ai_blocks[1].data[1] == 7

    def test_counter_sparse_yields_multiple_blocks(self) -> None:
        """Counters at [0, 2] (gap at 1) produce two ObjectBlocks."""
        outstation = Outstation()
        outstation.database.add_counter(0, value=10)
        outstation.database.add_counter(2, value=20)

        response = outstation.process_request(build_integrity_poll().to_bytes())
        assert response is not None
        ctr_blocks = [b for b in response.objects if b.header.group == 20]
        assert len(ctr_blocks) == 2, (
            f"Two sparse counters with a gap must produce 2 ObjectBlocks, got {len(ctr_blocks)}"
        )
        assert ctr_blocks[0].data[0] == 0
        assert ctr_blocks[0].data[1] == 0
        assert ctr_blocks[1].data[0] == 2
        assert ctr_blocks[1].data[1] == 2


class TestParseCrobBlock:
    """Unit tests for _parse_crob_block, the shared CROB-parse helper.

    These tests directly exercise the helper so each error path is covered
    without routing through the full process_request serialization pipeline.
    """

    def test_empty_data_returns_empty(self) -> None:
        """An ObjectBlock with no payload returns an empty list."""
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x17),
            data=b"",
        )
        assert _parse_crob_block(block) == []

    def test_unknown_qualifier_returns_format_error(self) -> None:
        """An unknown qualifier byte yields a single FORMAT_ERROR entry."""
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0xFF),
            data=bytes(20),
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        assert result[0].status == CommandStatus.FORMAT_ERROR
        assert result[0].control_code is None

    def test_truncated_count_field_returns_format_error(self) -> None:
        """A buffer shorter than the count field yields FORMAT_ERROR."""
        # 0x28 needs 2-byte count but we only supply 1 byte
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x28),
            data=bytes([1]),
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        assert result[0].status == CommandStatus.FORMAT_ERROR

    def test_valid_1byte_qualifier_parses_correctly(self) -> None:
        """A well-formed 0x17 CROB block yields one valid ParsedCrob."""
        # count=1, index=3, cc=LATCH_ON(3), op=1, on=1000, off=500, status=0
        payload = bytes(
            [
                1,  # count
                3,  # index
                0x03,  # control_code nibble = LATCH_ON
                1,  # op_count
                0xE8,
                0x03,
                0x00,
                0x00,  # on_time = 1000 ms
                0xF4,
                0x01,
                0x00,
                0x00,  # off_time = 500 ms
                0x00,  # status
            ]
        )
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x17),
            data=payload,
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        crob = result[0]
        assert crob.index == 3
        assert crob.control_code == ControlCode.LATCH_ON
        assert crob.op_count == 1
        assert crob.on_time == 1000
        assert crob.off_time == 500
        assert crob.status == CommandStatus.SUCCESS

    def test_undefined_control_code_nibble_yields_format_error(self) -> None:
        """Nibble 0x05 (undefined) must produce a FORMAT_ERROR ParsedCrob, not raise."""
        payload = bytes(
            [
                1,  # count
                7,  # index
                0x05,  # undefined nibble
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,  # remainder of CROB body
            ]
        )
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x17),
            data=payload,
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        assert result[0].index == 7
        assert result[0].status == CommandStatus.FORMAT_ERROR
        assert result[0].control_code is None

    def test_truncated_body_yields_format_error(self) -> None:
        """A buffer that declares count=1 but lacks the full CROB body yields FORMAT_ERROR."""
        payload = bytes([1, 3, 0x03, 1, 0])  # count=1, partial body
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x17),
            data=payload,
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        assert result[0].status == CommandStatus.FORMAT_ERROR

    def test_returns_parsed_crob_frozen_dataclass(self) -> None:
        """Each result is a ParsedCrob instance (frozen dataclass)."""
        payload = bytes([1, 0, 0x01, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        block = ObjectBlock(
            header=ObjectHeader(group=12, variation=1, qualifier=0x17),
            data=payload,
        )
        result = _parse_crob_block(block)
        assert len(result) == 1
        assert isinstance(result[0], ParsedCrob)


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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        assert len(resp_data) >= 13
        status_byte = resp_data[12]
        from dnp3.core.enums import CommandStatus

        assert status_byte == CommandStatus.NOT_SUPPORTED, (
            f"Expected NOT_SUPPORTED ({CommandStatus.NOT_SUPPORTED}), got status={status_byte}"
        )

    def test_direct_operate_crob_0x17_echoes_correct_index(self) -> None:
        """DIRECT_OPERATE with 0x17 CROB echoes the 1-byte index verbatim.

        Wire-level assertion: the echoed data byte at offset 1 must equal the
        requested index (5), not some truncated or shifted value.
        """

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
        outstation.database.add_binary_output(5, value=False)

        block = _make_crob_block(qualifier=0x17, index=5)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        # Layout: count(1) + index(1) + body(10) + status(1) = 13 bytes
        assert len(resp_data) >= 13, f"Response data too short: {len(resp_data)} bytes"
        echoed_index = resp_data[1]
        assert echoed_index == 5, f"Echoed index must be 5 (0x17 path), got {echoed_index}"
        # Status byte at offset 12 (count + index + 10 body bytes)
        assert resp_data[12] == int(CommandStatus.SUCCESS), f"Expected SUCCESS, got {resp_data[12]}"

    def test_direct_operate_crob_0x28_echoes_correct_index(self) -> None:
        """DIRECT_OPERATE with 0x28 CROB echoes the 2-byte index verbatim.

        Index 300 does not fit in one byte (300 % 256 = 44). The prior
        hardcoded 1-byte read in _echo_crob_block would echo index 44.
        This test confirms the fixed implementation echoes the full 2-byte
        little-endian index 300 at wire level.
        """

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
        outstation.database.add_binary_output(300, value=False)

        block = _make_crob_block(qualifier=0x28, index=300)

        from dnp3.application.builder import build_direct_operate_request

        request = build_direct_operate_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        # 0x28 layout: count(2) + index(2) + body(10) + status(1) = 15 bytes
        assert len(resp_data) >= 15, f"Response data too short for 0x28: {len(resp_data)} bytes"
        # Count field: 2 bytes little-endian at offset 0
        echoed_count = int.from_bytes(resp_data[0:2], "little")
        assert echoed_count == 1, f"Count must be 1, got {echoed_count}"
        # Index field: 2 bytes little-endian at offset 2
        echoed_index = int.from_bytes(resp_data[2:4], "little")
        assert echoed_index == 300, (
            f"Echoed index must be 300 (2-byte 0x28 path), got {echoed_index}. "
            "Value 44 would indicate the index was truncated to 1 byte."
        )
        # Status byte: at offset count(2) + index(2) + body(10) = 14
        assert resp_data[14] == int(CommandStatus.SUCCESS), f"Expected SUCCESS, got {resp_data[14]}"


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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert handler_called, "direct_operate_analog_output handler must be called"
        assert response is not None
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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert len(response.objects) > 0
        resp_data = response.objects[0].data
        assert len(resp_data) >= 7
        status_byte = resp_data[6]
        from dnp3.core.enums import CommandStatus

        assert status_byte == CommandStatus.NOT_SUPPORTED, (
            f"Expected NOT_SUPPORTED ({CommandStatus.NOT_SUPPORTED}), got {status_byte}"
        )


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
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE
        # After processing, DEVICE_RESTART should be cleared
        assert IIN.DEVICE_RESTART not in outstation.iin, (
            "DEVICE_RESTART should be cleared after WRITE g80v1 index 7 value 0"
        )

    def test_write_g80v1_response_has_no_objects(self) -> None:
        """WRITE g80v1 response has no objects (null response body)."""
        outstation = Outstation()

        g80v1_header = ObjectHeader(group=80, variation=1, qualifier=0x00)
        range_data = bytes([7, 7])
        bit_data = bytes([0x00])
        block = ObjectBlock(header=g80v1_header, data=range_data + bit_data)

        from dnp3.application.builder import build_write_request

        request = build_write_request(objects=(block,))
        response = outstation.process_request(request.to_bytes())

        assert response is not None
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
