"""Command handler protocol for outstation control operations.

Defines the interface for handling control commands from a master station.
Users implement this protocol to respond to SELECT/OPERATE/DIRECT_OPERATE.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dnp3.core.enums import CommandStatus, ControlCode


@dataclass(frozen=True)
class CommandResult:
    """Result of a control command operation.

    Attributes:
        status: Status code indicating success or failure reason.
        message: Optional message for logging/debugging.
    """

    status: CommandStatus
    message: str = ""

    @classmethod
    def success(cls, message: str = "") -> "CommandResult":
        """Create a successful result."""
        return cls(status=CommandStatus.SUCCESS, message=message)

    @classmethod
    def not_supported(cls, message: str = "") -> "CommandResult":
        """Create a not-supported result."""
        return cls(status=CommandStatus.NOT_SUPPORTED, message=message)

    @classmethod
    def format_error(cls, message: str = "") -> "CommandResult":
        """Create a format error result."""
        return cls(status=CommandStatus.FORMAT_ERROR, message=message)

    @classmethod
    def hardware_error(cls, message: str = "") -> "CommandResult":
        """Create a hardware error result."""
        return cls(status=CommandStatus.HARDWARE_ERROR, message=message)

    @classmethod
    def local(cls, message: str = "") -> "CommandResult":
        """Create a local control result (output in local mode)."""
        return cls(status=CommandStatus.LOCAL, message=message)

    @classmethod
    def blocked(cls, message: str = "") -> "CommandResult":
        """Create a blocked result."""
        return cls(status=CommandStatus.BLOCKED, message=message)

    @classmethod
    def out_of_range(cls, message: str = "") -> "CommandResult":
        """Create an out-of-range result."""
        return cls(status=CommandStatus.OUT_OF_RANGE, message=message)

    @property
    def is_success(self) -> bool:
        """Check if command was successful."""
        return self.status == CommandStatus.SUCCESS


@runtime_checkable
class CommandHandler(Protocol):
    """Protocol for handling control commands.

    Implement this protocol to handle control operations from the master.
    The outstation will call these methods when processing control requests.
    """

    def select_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Handle SELECT for a binary output (CROB).

        Called when master sends SELECT for a control point.
        Validate that the operation can be performed without executing it.

        Args:
            index: Point index.
            code: Control code (LATCH_ON, LATCH_OFF, PULSE_ON, etc.).
            count: Number of times to execute (for pulsed operations).
            on_time: On time in milliseconds (for pulsed operations).
            off_time: Off time in milliseconds (for pulsed operations).

        Returns:
            CommandResult indicating if the operation can proceed.
        """
        ...

    def operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
        select_sequence: int,
    ) -> CommandResult:
        """Handle OPERATE for a binary output (CROB).

        Called when master sends OPERATE after a successful SELECT.
        Execute the control operation.

        Args:
            index: Point index.
            code: Control code (LATCH_ON, LATCH_OFF, PULSE_ON, etc.).
            count: Number of times to execute.
            on_time: On time in milliseconds.
            off_time: Off time in milliseconds.
            select_sequence: Sequence number from SELECT (for verification).

        Returns:
            CommandResult indicating success or failure.
        """
        ...

    def direct_operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Handle DIRECT_OPERATE for a binary output (CROB).

        Called when master sends DIRECT_OPERATE (no SELECT required).
        Validate and execute the control operation in one step.

        Args:
            index: Point index.
            code: Control code.
            count: Number of times to execute.
            on_time: On time in milliseconds.
            off_time: Off time in milliseconds.

        Returns:
            CommandResult indicating success or failure.
        """
        ...

    def select_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Handle SELECT for an analog output.

        Args:
            index: Point index.
            value: Analog value to set.

        Returns:
            CommandResult indicating if the operation can proceed.
        """
        ...

    def operate_analog_output(
        self,
        index: int,
        value: float,
        select_sequence: int,
    ) -> CommandResult:
        """Handle OPERATE for an analog output.

        Args:
            index: Point index.
            value: Analog value to set.
            select_sequence: Sequence number from SELECT.

        Returns:
            CommandResult indicating success or failure.
        """
        ...

    def direct_operate_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Handle DIRECT_OPERATE for an analog output.

        Args:
            index: Point index.
            value: Analog value to set.

        Returns:
            CommandResult indicating success or failure.
        """
        ...

    def cold_restart(self) -> int | None:
        """Handle COLD_RESTART request.

        Returns:
            Delay in milliseconds before restart, or None if not supported.
        """
        ...

    def warm_restart(self) -> int | None:
        """Handle WARM_RESTART request.

        Returns:
            Delay in milliseconds before restart, or None if not supported.
        """
        ...

    def freeze_counters(
        self,
        start: int,
        stop: int,
        clear: bool,
    ) -> CommandResult:
        """Handle FREEZE or FREEZE_CLEAR request.

        Args:
            start: First counter index.
            stop: Last counter index (inclusive).
            clear: Whether to clear counters after freezing.

        Returns:
            CommandResult indicating success or failure.
        """
        ...


class DefaultCommandHandler:
    """Default command handler that rejects all operations.

    Use as a base class and override methods for supported operations.
    """

    def select_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Reject binary output SELECT."""
        return CommandResult.not_supported(f"Binary output {index} not supported")

    def operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
        select_sequence: int,
    ) -> CommandResult:
        """Reject binary output OPERATE."""
        return CommandResult.not_supported(f"Binary output {index} not supported")

    def direct_operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Reject binary output DIRECT_OPERATE."""
        return CommandResult.not_supported(f"Binary output {index} not supported")

    def select_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Reject analog output SELECT."""
        return CommandResult.not_supported(f"Analog output {index} not supported")

    def operate_analog_output(
        self,
        index: int,
        value: float,
        select_sequence: int,
    ) -> CommandResult:
        """Reject analog output OPERATE."""
        return CommandResult.not_supported(f"Analog output {index} not supported")

    def direct_operate_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Reject analog output DIRECT_OPERATE."""
        return CommandResult.not_supported(f"Analog output {index} not supported")

    def cold_restart(self) -> int | None:
        """Cold restart not supported."""
        return None

    def warm_restart(self) -> int | None:
        """Warm restart not supported."""
        return None

    def freeze_counters(
        self,
        start: int,
        stop: int,
        clear: bool,
    ) -> CommandResult:
        """Reject freeze counters."""
        return CommandResult.not_supported(f"Freeze counters {start}-{stop} not supported")
