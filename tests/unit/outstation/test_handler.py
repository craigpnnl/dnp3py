"""Tests for outstation command handler."""

import pytest

from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.outstation.handler import CommandHandler, CommandResult, DefaultCommandHandler


class TestCommandResult:
    """Tests for CommandResult."""

    def test_create_with_status(self) -> None:
        """Can create with status."""
        result = CommandResult(status=CommandStatus.SUCCESS)
        assert result.status == CommandStatus.SUCCESS
        assert result.message == ""

    def test_create_with_message(self) -> None:
        """Can create with message."""
        result = CommandResult(status=CommandStatus.HARDWARE_ERROR, message="Motor fault")
        assert result.status == CommandStatus.HARDWARE_ERROR
        assert result.message == "Motor fault"

    def test_success_factory(self) -> None:
        """success() creates successful result."""
        result = CommandResult.success()
        assert result.status == CommandStatus.SUCCESS
        assert result.is_success is True

    def test_success_with_message(self) -> None:
        """success() can include message."""
        result = CommandResult.success("Operation complete")
        assert result.message == "Operation complete"

    def test_not_supported_factory(self) -> None:
        """not_supported() creates not-supported result."""
        result = CommandResult.not_supported()
        assert result.status == CommandStatus.NOT_SUPPORTED
        assert result.is_success is False

    def test_format_error_factory(self) -> None:
        """format_error() creates format error result."""
        result = CommandResult.format_error()
        assert result.status == CommandStatus.FORMAT_ERROR
        assert result.is_success is False

    def test_hardware_error_factory(self) -> None:
        """hardware_error() creates hardware error result."""
        result = CommandResult.hardware_error()
        assert result.status == CommandStatus.HARDWARE_ERROR
        assert result.is_success is False

    def test_local_factory(self) -> None:
        """local() creates local control result."""
        result = CommandResult.local()
        assert result.status == CommandStatus.LOCAL
        assert result.is_success is False

    def test_blocked_factory(self) -> None:
        """blocked() creates blocked result."""
        result = CommandResult.blocked()
        assert result.status == CommandStatus.BLOCKED
        assert result.is_success is False

    def test_out_of_range_factory(self) -> None:
        """out_of_range() creates out-of-range result."""
        result = CommandResult.out_of_range()
        assert result.status == CommandStatus.OUT_OF_RANGE
        assert result.is_success is False

    def test_is_success_true(self) -> None:
        """is_success returns True for SUCCESS."""
        result = CommandResult(status=CommandStatus.SUCCESS)
        assert result.is_success is True

    def test_is_success_false(self) -> None:
        """is_success returns False for non-SUCCESS."""
        result = CommandResult(status=CommandStatus.TIMEOUT)
        assert result.is_success is False

    def test_immutable(self) -> None:
        """Result is immutable (frozen)."""
        result = CommandResult.success()
        with pytest.raises(AttributeError):
            result.status = CommandStatus.TIMEOUT  # type: ignore[misc]


class TestDefaultCommandHandler:
    """Tests for DefaultCommandHandler."""

    def test_select_binary_output_rejects(self) -> None:
        """Default handler rejects binary output SELECT."""
        handler = DefaultCommandHandler()
        result = handler.select_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_operate_binary_output_rejects(self) -> None:
        """Default handler rejects binary output OPERATE."""
        handler = DefaultCommandHandler()
        result = handler.operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
            select_sequence=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_direct_operate_binary_output_rejects(self) -> None:
        """Default handler rejects binary output DIRECT_OPERATE."""
        handler = DefaultCommandHandler()
        result = handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_select_analog_output_rejects(self) -> None:
        """Default handler rejects analog output SELECT."""
        handler = DefaultCommandHandler()
        result = handler.select_analog_output(index=0, value=100.0)
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_operate_analog_output_rejects(self) -> None:
        """Default handler rejects analog output OPERATE."""
        handler = DefaultCommandHandler()
        result = handler.operate_analog_output(index=0, value=100.0, select_sequence=0)
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_direct_operate_analog_output_rejects(self) -> None:
        """Default handler rejects analog output DIRECT_OPERATE."""
        handler = DefaultCommandHandler()
        result = handler.direct_operate_analog_output(index=0, value=100.0)
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_cold_restart_returns_none(self) -> None:
        """Default handler returns None for cold restart."""
        handler = DefaultCommandHandler()
        result = handler.cold_restart()
        assert result is None

    def test_warm_restart_returns_none(self) -> None:
        """Default handler returns None for warm restart."""
        handler = DefaultCommandHandler()
        result = handler.warm_restart()
        assert result is None

    def test_freeze_counters_rejects(self) -> None:
        """Default handler rejects freeze counters."""
        handler = DefaultCommandHandler()
        result = handler.freeze_counters(start=0, stop=10, clear=False)
        assert result.status == CommandStatus.NOT_SUPPORTED


class TestCommandHandlerProtocol:
    """Tests for CommandHandler protocol."""

    def test_default_handler_matches_protocol(self) -> None:
        """DefaultCommandHandler matches CommandHandler protocol."""
        handler = DefaultCommandHandler()
        assert isinstance(handler, CommandHandler)

    def test_custom_handler_matches_protocol(self) -> None:
        """Custom handler can match CommandHandler protocol."""

        class CustomHandler:
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
                return CommandResult.success()

            def direct_operate_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                return CommandResult.success()

            def select_analog_output(
                self,
                index: int,
                value: float,
            ) -> CommandResult:
                return CommandResult.success()

            def operate_analog_output(
                self,
                index: int,
                value: float,
                select_sequence: int,
            ) -> CommandResult:
                return CommandResult.success()

            def direct_operate_analog_output(
                self,
                index: int,
                value: float,
            ) -> CommandResult:
                return CommandResult.success()

            def cold_restart(self) -> int | None:
                return 1000

            def warm_restart(self) -> int | None:
                return 500

            def freeze_counters(
                self,
                start: int,
                stop: int,
                clear: bool,
            ) -> CommandResult:
                return CommandResult.success()

        handler = CustomHandler()
        assert isinstance(handler, CommandHandler)


class TestCustomHandler:
    """Tests for custom command handler implementation."""

    def test_custom_handler_select(self) -> None:
        """Custom handler can implement SELECT."""

        class MyHandler(DefaultCommandHandler):
            def select_binary_output(
                self,
                index: int,
                code: ControlCode,
                count: int,
                on_time: int,
                off_time: int,
            ) -> CommandResult:
                if index < 10:
                    return CommandResult.success()
                return CommandResult.out_of_range()

        handler = MyHandler()
        assert handler.select_binary_output(0, ControlCode.LATCH_ON, 1, 0, 0).is_success
        assert not handler.select_binary_output(10, ControlCode.LATCH_ON, 1, 0, 0).is_success

    def test_custom_handler_restart(self) -> None:
        """Custom handler can implement restart."""

        class MyHandler(DefaultCommandHandler):
            def cold_restart(self) -> int | None:
                return 5000  # 5 second delay

            def warm_restart(self) -> int | None:
                return 1000  # 1 second delay

        handler = MyHandler()
        assert handler.cold_restart() == 5000
        assert handler.warm_restart() == 1000
