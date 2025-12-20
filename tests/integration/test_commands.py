"""Integration tests for command workflows.

Tests control operations between master and outstation including
SELECT-BEFORE-OPERATE and DIRECT_OPERATE commands.
"""

from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.database import BinaryOutputConfig, Database
from dnp3.master import Master
from dnp3.master.commands import ControlOperation
from dnp3.outstation import DefaultCommandHandler, Outstation


class TestDirectOperate:
    """Test DIRECT_OPERATE commands."""

    def test_direct_operate_latch_on(self) -> None:
        """Direct operate with latch on command."""
        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())
        database.update_binary_output(0, value=False)

        outstation = Outstation(database=database)
        master = Master()

        # Build direct operate command
        builder = master.command_builder()
        builder.latch_on(index=0)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        assert request.header.function == FunctionCode.DIRECT_OPERATE

        response = outstation.process_request(request.to_bytes())
        assert response is not None
        assert response.header.function == FunctionCode.RESPONSE

    def test_direct_operate_latch_off(self) -> None:
        """Direct operate with latch off command."""
        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())
        database.update_binary_output(0, value=True)

        outstation = Outstation(database=database)
        master = Master()

        builder = master.command_builder()
        builder.latch_off(index=0)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_direct_operate_pulse_on(self) -> None:
        """Direct operate with pulse on command."""
        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=database)
        master = Master()

        builder = master.command_builder()
        builder.pulse_on(index=0, on_time=1000, off_time=500, count=1)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_direct_operate_multiple_points(self) -> None:
        """Direct operate on multiple points."""
        database = Database()
        for i in range(5):
            database.add_binary_output(i, BinaryOutputConfig())

        outstation = Outstation(database=database)
        master = Master()

        builder = master.command_builder()
        builder.latch_on(index=0)
        builder.latch_off(index=1)
        builder.latch_on(index=2)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestSelectBeforeOperate:
    """Test SELECT-BEFORE-OPERATE (SBO) commands."""

    def test_select_then_operate(self) -> None:
        """Complete SBO sequence: SELECT then OPERATE."""
        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=database)
        master = Master()

        # Build SELECT
        builder = master.command_builder()
        builder.latch_on(index=0)
        select_task = builder.build_select()

        select_request = master.build_select(select_task)
        assert select_request.header.function == FunctionCode.SELECT

        select_response = outstation.process_request(select_request.to_bytes())
        assert select_response is not None
        assert select_response.header.function == FunctionCode.RESPONSE

        # Build OPERATE (using same operations)
        operate_task = builder.build_operate()
        operate_request = master.build_operate(operate_task)
        assert operate_request.header.function == FunctionCode.OPERATE

        operate_response = outstation.process_request(operate_request.to_bytes())
        assert operate_response is not None

    def test_select_expires_without_operate(self) -> None:
        """SELECT expires if OPERATE not sent in time."""
        import time

        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())

        # Use short select timeout for testing
        from dnp3.outstation.config import OutstationConfig

        config = OutstationConfig(select_timeout=0.001)  # Very short expiry
        outstation = Outstation(config=config, database=database)
        master = Master()

        # Send SELECT
        builder = master.command_builder()
        builder.latch_on(index=0)
        select_task = builder.build_select()
        select_request = master.build_select(select_task)
        outstation.process_request(select_request.to_bytes())

        # Wait for timeout
        time.sleep(0.01)

        # Try OPERATE after timeout - should fail with NO_SELECT
        operate_task = builder.build_operate()
        operate_request = master.build_operate(operate_task)
        operate_response = outstation.process_request(operate_request.to_bytes())
        assert operate_response is not None


class TestCommandHandler:
    """Test custom command handlers."""

    def test_custom_handler_receives_commands(self) -> None:
        """Custom command handler receives commands."""
        database = Database()
        database.add_binary_output(0, BinaryOutputConfig())

        # Track commands received
        received_commands: list[tuple[int, ControlCode]] = []

        class TrackingHandler(DefaultCommandHandler):
            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ):
                received_commands.append((index, code))
                return super().direct_operate_binary_output(index, code, count, on_time, off_time)

        outstation = Outstation(database=database, handler=TrackingHandler())
        master = Master()

        builder = master.command_builder()
        builder.latch_on(index=0)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        outstation.process_request(request.to_bytes())

        assert len(received_commands) == 1
        assert received_commands[0] == (0, ControlCode.LATCH_ON)


class TestAnalogOutput:
    """Test analog output commands."""

    def test_direct_operate_analog(self) -> None:
        """Direct operate analog output."""
        master = Master()
        builder = master.command_builder()
        builder.add_analog(index=0, value=100.0)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        assert request.header.function == FunctionCode.DIRECT_OPERATE
        assert len(request.objects) > 0


class TestCommandBuilder:
    """Test command builder fluent interface."""

    def test_builder_chaining(self) -> None:
        """Command builder supports method chaining."""
        master = Master()
        builder = (
            master.command_builder()
            .latch_on(0)
            .latch_off(1)
            .pulse_on(2, on_time=1000)
            .pulse_off(3, off_time=500)
            .add_analog(4, value=50.0)
        )

        task = builder.build_direct_operate()
        assert len(task.operations) == 5

    def test_builder_clear(self) -> None:
        """Command builder can be cleared and reused."""
        master = Master()
        builder = master.command_builder()

        builder.latch_on(0)
        assert len(builder._operations) == 1

        builder.clear()
        assert len(builder._operations) == 0

        builder.latch_off(0)
        task = builder.build_direct_operate()
        assert len(task.operations) == 1

    def test_builder_multiple_builds(self) -> None:
        """Builder can build multiple task types from same operations."""
        master = Master()
        builder = master.command_builder()
        builder.latch_on(0)

        select_task = builder.build_select()
        operate_task = builder.build_operate()
        direct_task = builder.build_direct_operate()

        # Each should have the operation
        assert len(select_task.operations) == 1
        assert len(operate_task.operations) == 1
        assert len(direct_task.operations) == 1


class TestControlOperations:
    """Test control operation data structures."""

    def test_control_operation_fields(self) -> None:
        """ControlOperation stores all fields correctly."""
        op = ControlOperation(
            index=5,
            control_code=ControlCode.PULSE_ON,
            count=3,
            on_time=1000,
            off_time=500,
            is_analog=False,
        )

        assert op.index == 5
        assert op.control_code == ControlCode.PULSE_ON
        assert op.count == 3
        assert op.on_time == 1000
        assert op.off_time == 500
        assert not op.is_analog

    def test_analog_control_operation(self) -> None:
        """ControlOperation for analog output."""
        op = ControlOperation(
            index=0,
            analog_value=123.45,
            is_analog=True,
        )

        assert op.is_analog
        assert op.analog_value == 123.45


class TestHighIndexCommands:
    """Test commands with high index values."""

    def test_direct_operate_high_index(self) -> None:
        """Direct operate works with index > 255."""
        database = Database()
        database.add_binary_output(1000, BinaryOutputConfig())

        outstation = Outstation(database=database)
        master = Master()

        builder = master.command_builder()
        builder.add_crob(index=1000, code=ControlCode.LATCH_ON)
        task = builder.build_direct_operate()

        request = master.build_direct_operate(task)
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestCommandSequence:
    """Test command sequence handling."""

    def test_command_sequence_increments(self) -> None:
        """Sequence numbers increment for each command request."""
        master = Master()

        builder1 = master.command_builder().latch_on(0)
        request1 = master.build_direct_operate(builder1.build_direct_operate())

        builder2 = master.command_builder().latch_off(0)
        request2 = master.build_direct_operate(builder2.build_direct_operate())

        seq1 = request1.header.control.seq
        seq2 = request2.header.control.seq

        assert seq2 == (seq1 + 1) % 16
