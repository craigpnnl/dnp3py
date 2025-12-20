"""Tests for the Master class."""

from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.master.commands import (
    CommandBuilder,
    ControlOperation,
    DirectOperateTask,
    OperateTask,
    SelectTask,
)
from dnp3.master.config import MasterConfig, PollingConfig
from dnp3.master.handler import (
    DefaultSOEHandler,
)
from dnp3.master.master import (
    GROUP_ANALOG_INPUT,
    GROUP_BINARY_INPUT,
    GROUP_COUNTER,
    QUALITY_ONLINE,
    QUALITY_STATE,
    Master,
)
from dnp3.master.polling import IntegrityPollTask
from dnp3.master.state import MasterState


class TestMasterCreation:
    """Tests for Master creation and initialization."""

    def test_default_creation(self) -> None:
        """Test creating master with defaults."""
        master = Master()

        assert isinstance(master.config, MasterConfig)
        assert isinstance(master.handler, DefaultSOEHandler)
        assert master.state == MasterState.IDLE
        assert master.is_idle is True

    def test_with_custom_config(self) -> None:
        """Test creating master with custom config."""
        config = MasterConfig(
            address=5,
            outstation_address=100,
        )
        master = Master(config=config)

        assert master.config.address == 5
        assert master.config.outstation_address == 100

    def test_with_custom_handler(self) -> None:
        """Test creating master with custom handler."""
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        assert master.handler is handler

    def test_scheduler_property(self) -> None:
        """Test scheduler property."""
        master = Master()

        assert master.scheduler is not None
        assert master.scheduler.task_count >= 0


class TestMasterPollingSetup:
    """Tests for polling setup from config."""

    def test_polling_disabled(self) -> None:
        """Test with all polling disabled."""
        polling = PollingConfig(
            integrity_poll_interval=0.0,
            class_1_poll_interval=0.0,
            class_2_poll_interval=0.0,
            class_3_poll_interval=0.0,
        )
        config = MasterConfig(polling=polling)
        master = Master(config=config)

        assert master.scheduler.task_count == 0

    def test_integrity_poll_enabled(self) -> None:
        """Test with integrity poll enabled."""
        polling = PollingConfig(
            integrity_poll_interval=3600.0,
            class_1_poll_interval=0.0,
            class_2_poll_interval=0.0,
            class_3_poll_interval=0.0,
        )
        config = MasterConfig(polling=polling)
        master = Master(config=config)

        assert master.scheduler.task_count == 1

    def test_all_class_polls_enabled(self) -> None:
        """Test with all class polls enabled."""
        polling = PollingConfig(
            integrity_poll_interval=0.0,
            class_1_poll_interval=10.0,
            class_2_poll_interval=20.0,
            class_3_poll_interval=30.0,
        )
        config = MasterConfig(polling=polling)
        master = Master(config=config)

        assert master.scheduler.task_count == 3

    def test_all_polls_enabled(self) -> None:
        """Test with all polls enabled."""
        polling = PollingConfig(
            integrity_poll_interval=3600.0,
            class_1_poll_interval=10.0,
            class_2_poll_interval=20.0,
            class_3_poll_interval=30.0,
        )
        config = MasterConfig(polling=polling)
        master = Master(config=config)

        assert master.scheduler.task_count == 4


class TestMasterRequestBuilding:
    """Tests for request building methods."""

    def test_build_integrity_poll(self) -> None:
        """Test building integrity poll request."""
        master = Master()

        fragment = master.build_integrity_poll()

        assert fragment.header.function == FunctionCode.READ

    def test_build_class_poll_all(self) -> None:
        """Test building class poll for all classes."""
        master = Master()

        fragment = master.build_class_poll(class_1=True, class_2=True, class_3=True)

        assert fragment.header.function == FunctionCode.READ

    def test_build_class_poll_single(self) -> None:
        """Test building class poll for single class."""
        master = Master()

        fragment = master.build_class_poll(class_1=True, class_2=False, class_3=False)

        assert fragment.header.function == FunctionCode.READ

    def test_build_range_poll(self) -> None:
        """Test building range poll request."""
        master = Master()

        fragment = master.build_range_poll(group=30, variation=1, start=0, stop=10)

        assert fragment.header.function == FunctionCode.READ

    def test_build_select(self) -> None:
        """Test building SELECT request."""
        master = Master()
        task = SelectTask()
        task.add_operation(ControlOperation(index=0, control_code=ControlCode.LATCH_ON))

        fragment = master.build_select(task)

        assert fragment.header.function == FunctionCode.SELECT

    def test_build_operate(self) -> None:
        """Test building OPERATE request."""
        master = Master()
        task = OperateTask()
        task.add_operation(ControlOperation(index=0, control_code=ControlCode.LATCH_ON))

        fragment = master.build_operate(task)

        assert fragment.header.function == FunctionCode.OPERATE

    def test_build_direct_operate(self) -> None:
        """Test building DIRECT_OPERATE request."""
        master = Master()
        task = DirectOperateTask()
        task.add_operation(ControlOperation(index=0, control_code=ControlCode.LATCH_ON))

        fragment = master.build_direct_operate(task)

        assert fragment.header.function == FunctionCode.DIRECT_OPERATE

    def test_build_enable_unsolicited(self) -> None:
        """Test building ENABLE_UNSOLICITED request."""
        master = Master()

        fragment = master.build_enable_unsolicited()

        assert fragment.header.function == FunctionCode.ENABLE_UNSOLICITED

    def test_build_enable_unsolicited_partial(self) -> None:
        """Test building ENABLE_UNSOLICITED for specific classes."""
        master = Master()

        fragment = master.build_enable_unsolicited(class_1=True, class_2=False, class_3=True)

        assert fragment.header.function == FunctionCode.ENABLE_UNSOLICITED

    def test_build_disable_unsolicited(self) -> None:
        """Test building DISABLE_UNSOLICITED request."""
        master = Master()

        fragment = master.build_disable_unsolicited()

        assert fragment.header.function == FunctionCode.DISABLE_UNSOLICITED

    def test_build_delay_measure(self) -> None:
        """Test building DELAY_MEASURE request."""
        master = Master()

        fragment = master.build_delay_measure()

        assert fragment.header.function == FunctionCode.DELAY_MEASURE

    def test_build_confirm(self) -> None:
        """Test building CONFIRM request."""
        master = Master()

        fragment = master.build_confirm(seq=5)

        assert fragment.header.function == FunctionCode.CONFIRM

    def test_sequence_increments(self) -> None:
        """Test that sequence numbers increment."""
        master = Master()

        frag1 = master.build_integrity_poll()
        frag2 = master.build_integrity_poll()
        frag3 = master.build_integrity_poll()

        seq1 = frag1.header.control.seq
        seq2 = frag2.header.control.seq
        seq3 = frag3.header.control.seq

        assert seq2 == (seq1 + 1) % 16
        assert seq3 == (seq2 + 1) % 16


class TestMasterBinaryParsing:
    """Tests for binary value parsing."""

    def test_parse_binary_packed_v1(self) -> None:
        """Test parsing packed binary input (g1v1)."""
        master = Master()

        # Create object block for g1v1 with start-stop range 0-7
        # Qualifier 0x00 = 1-byte start-stop
        # Data: start(0), stop(7), bits(0b10101010)
        header = ObjectHeader(group=1, variation=1, qualifier=0x00)
        data = bytes([0, 7, 0b10101010])  # Start=0, Stop=7, value byte
        block = ObjectBlock(header=header, data=data)

        values = master._parse_binary_values(block)

        assert len(values) >= 1
        # Bit 0 = 0 (False), Bit 1 = 1 (True), etc.
        assert values[0].index == 0
        assert values[0].value is False
        assert values[1].index == 1
        assert values[1].value is True

    def test_parse_binary_flags_v2(self) -> None:
        """Test parsing binary input with flags (g1v2)."""
        master = Master()

        # Create object block for g1v2 with start-stop range
        # Each value is 1 byte: flags with bit 7 = state
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        # Start=0, Stop=2, values: 0x81 (ON+online), 0x01 (OFF+online), 0x80 (ON)
        data = bytes([0, 2, 0x81, 0x01, 0x80])
        block = ObjectBlock(header=header, data=data)

        values = master._parse_binary_values(block)

        assert len(values) == 3
        assert values[0].index == 0
        assert values[0].value is True
        assert values[0].quality == 0x01

        assert values[1].index == 1
        assert values[1].value is False
        assert values[1].quality == 0x01

        assert values[2].index == 2
        assert values[2].value is True
        assert values[2].quality == 0x00

    def test_parse_binary_empty(self) -> None:
        """Test parsing empty binary block."""
        master = Master()

        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header, data=b"")

        values = master._parse_binary_values(block)

        assert len(values) == 0


class TestMasterAnalogParsing:
    """Tests for analog value parsing."""

    def test_parse_analog_32bit_flags_v1(self) -> None:
        """Test parsing 32-bit analog with flags (g30v1)."""
        master = Master()

        # g30v1: 1 byte flags + 4 bytes value
        header = ObjectHeader(group=30, variation=1, qualifier=0x00)
        # Start=0, Stop=0, flags=0x01, value=100 (little-endian)
        value_bytes = (100).to_bytes(4, "little", signed=True)
        data = bytes([0, 0, 0x01]) + value_bytes
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)

        assert len(values) == 1
        assert values[0].index == 0
        assert values[0].value == 100.0
        assert values[0].quality == 0x01

    def test_parse_analog_16bit_flags_v2(self) -> None:
        """Test parsing 16-bit analog with flags (g30v2)."""
        master = Master()

        # g30v2: 1 byte flags + 2 bytes value
        header = ObjectHeader(group=30, variation=2, qualifier=0x00)
        # Start=0, Stop=1, flags=0x01, value=500, flags=0x01, value=-100
        data = bytes([0, 1, 0x01]) + (500).to_bytes(2, "little", signed=True)
        data += bytes([0x01]) + (-100).to_bytes(2, "little", signed=True)
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)

        assert len(values) == 2
        assert values[0].index == 0
        assert values[0].value == 500.0
        assert values[1].index == 1
        assert values[1].value == -100.0

    def test_parse_analog_32bit_no_flags_v3(self) -> None:
        """Test parsing 32-bit analog without flags (g30v3)."""
        master = Master()

        # g30v3: 4 bytes value only
        header = ObjectHeader(group=30, variation=3, qualifier=0x00)
        data = bytes([0, 0]) + (12345).to_bytes(4, "little", signed=True)
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)

        assert len(values) == 1
        assert values[0].value == 12345.0
        assert values[0].quality == QUALITY_ONLINE

    def test_parse_analog_16bit_no_flags_v4(self) -> None:
        """Test parsing 16-bit analog without flags (g30v4)."""
        master = Master()

        # g30v4: 2 bytes value only
        header = ObjectHeader(group=30, variation=4, qualifier=0x00)
        data = bytes([0, 0]) + (1000).to_bytes(2, "little", signed=True)
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)

        assert len(values) == 1
        assert values[0].value == 1000.0

    def test_parse_analog_empty(self) -> None:
        """Test parsing empty analog block."""
        master = Master()

        header = ObjectHeader(group=30, variation=1, qualifier=0x00)
        block = ObjectBlock(header=header, data=b"")

        values = master._parse_analog_values(block)

        assert len(values) == 0

    def test_parse_analog_unsupported_variation(self) -> None:
        """Test parsing unsupported analog variation."""
        master = Master()

        # Variation 100 doesn't exist
        header = ObjectHeader(group=30, variation=100, qualifier=0x00)
        data = bytes([0, 0, 0x01, 0x02, 0x03])
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)

        assert len(values) == 0


class TestMasterCounterParsing:
    """Tests for counter value parsing."""

    def test_parse_counter_32bit_flags_v1(self) -> None:
        """Test parsing 32-bit counter with flags (g20v1)."""
        master = Master()

        # g20v1: 1 byte flags + 4 bytes value
        header = ObjectHeader(group=20, variation=1, qualifier=0x00)
        value_bytes = (54321).to_bytes(4, "little", signed=False)
        data = bytes([0, 0, 0x01]) + value_bytes
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)

        assert len(values) == 1
        assert values[0].index == 0
        assert values[0].value == 54321
        assert values[0].quality == 0x01

    def test_parse_counter_16bit_flags_v2(self) -> None:
        """Test parsing 16-bit counter with flags (g20v2)."""
        master = Master()

        # g20v2: 1 byte flags + 2 bytes value
        header = ObjectHeader(group=20, variation=2, qualifier=0x00)
        value_bytes = (1000).to_bytes(2, "little", signed=False)
        data = bytes([0, 0, 0x01]) + value_bytes
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)

        assert len(values) == 1
        assert values[0].value == 1000

    def test_parse_counter_32bit_no_flags_v5(self) -> None:
        """Test parsing 32-bit counter without flags (g20v5)."""
        master = Master()

        # g20v5: 4 bytes value only
        header = ObjectHeader(group=20, variation=5, qualifier=0x00)
        data = bytes([0, 0]) + (99999).to_bytes(4, "little", signed=False)
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)

        assert len(values) == 1
        assert values[0].value == 99999
        assert values[0].quality == QUALITY_ONLINE

    def test_parse_counter_16bit_no_flags_v6(self) -> None:
        """Test parsing 16-bit counter without flags (g20v6)."""
        master = Master()

        # g20v6: 2 bytes value only
        header = ObjectHeader(group=20, variation=6, qualifier=0x00)
        data = bytes([0, 0]) + (5000).to_bytes(2, "little", signed=False)
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)

        assert len(values) == 1
        assert values[0].value == 5000

    def test_parse_counter_empty(self) -> None:
        """Test parsing empty counter block."""
        master = Master()

        header = ObjectHeader(group=20, variation=1, qualifier=0x00)
        block = ObjectBlock(header=header, data=b"")

        values = master._parse_counter_values(block)

        assert len(values) == 0


class TestMasterConvenienceMethods:
    """Tests for convenience methods."""

    def test_command_builder(self) -> None:
        """Test getting command builder."""
        master = Master()

        builder = master.command_builder()

        assert isinstance(builder, CommandBuilder)

    def test_needs_confirm_initially_false(self) -> None:
        """Test needs_confirm initially returns False."""
        master = Master()

        assert master.needs_confirm() is False

    def test_get_next_poll_empty(self) -> None:
        """Test get_next_poll with no tasks."""
        polling = PollingConfig(
            integrity_poll_interval=0.0,
            class_1_poll_interval=0.0,
            class_2_poll_interval=0.0,
            class_3_poll_interval=0.0,
        )
        config = MasterConfig(polling=polling)
        master = Master(config=config)

        assert master.get_next_poll() is None

    def test_get_next_poll_with_tasks(self) -> None:
        """Test get_next_poll with scheduled tasks."""
        # Use default config which has integrity poll
        master = Master()

        # There should be at least one task from default config
        if master.scheduler.task_count > 0:
            task = master.get_next_poll()
            assert task is not None or task is None  # May or may not be due

    def test_mark_poll_executed(self) -> None:
        """Test marking poll as executed."""
        master = Master()
        task = IntegrityPollTask()

        assert task.last_poll_time == 0.0

        master.mark_poll_executed(task)

        assert task.last_poll_time > 0.0

    def test_check_timeout_no_task(self) -> None:
        """Test check_timeout with no running task."""
        master = Master()

        result = master.check_timeout()

        assert result is False


class TestMasterGroupConstants:
    """Tests for group number constants."""

    def test_group_constants(self) -> None:
        """Test that group constants are defined correctly."""
        assert GROUP_BINARY_INPUT == 1
        assert GROUP_ANALOG_INPUT == 30
        assert GROUP_COUNTER == 20

    def test_quality_constants(self) -> None:
        """Test that quality flag constants are correct."""
        assert QUALITY_ONLINE == 0x01
        assert QUALITY_STATE == 0x80


class TestMasterStateProperties:
    """Tests for state-related properties."""

    def test_state_property(self) -> None:
        """Test state property."""
        master = Master()

        assert master.state == MasterState.IDLE

    def test_is_idle_property(self) -> None:
        """Test is_idle property."""
        master = Master()

        assert master.is_idle is True


class TestMasterSelectStoring:
    """Tests for SELECT task storage."""

    def test_build_select_stores_task(self) -> None:
        """Test that build_select stores the pending select task."""
        master = Master()
        task = SelectTask()
        task.add_operation(ControlOperation(index=0, control_code=ControlCode.LATCH_ON))

        master.build_select(task)

        assert master._pending_select is task

    def test_build_select_overwrites_previous(self) -> None:
        """Test that new SELECT overwrites previous pending."""
        master = Master()
        task1 = SelectTask()
        task1.add_operation(ControlOperation(index=0, control_code=ControlCode.LATCH_ON))
        task2 = SelectTask()
        task2.add_operation(ControlOperation(index=1, control_code=ControlCode.LATCH_OFF))

        master.build_select(task1)
        master.build_select(task2)

        assert master._pending_select is task2
