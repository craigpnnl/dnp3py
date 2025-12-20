"""Command operations for DNP3 master.

Provides classes for building and executing control commands
including SELECT, OPERATE, and DIRECT_OPERATE.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto

from dnp3.application.builder import (
    build_direct_operate_request,
    build_operate_request,
    build_select_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import ControlCode

# CROB group/variation
CROB_GROUP = 12
CROB_VARIATION = 1

# Analog output group/variation
ANALOG_OUTPUT_GROUP = 41
ANALOG_OUTPUT_16_VARIATION = 2  # 16-bit
ANALOG_OUTPUT_32_VARIATION = 1  # 32-bit
ANALOG_OUTPUT_FLOAT_VARIATION = 3  # Single float
ANALOG_OUTPUT_DOUBLE_VARIATION = 4  # Double float

# Qualifier constants
QUALIFIER_1BYTE_INDEX = 0x17  # 1-byte count, 1-byte index prefix
QUALIFIER_2BYTE_INDEX = 0x28  # 2-byte count, 2-byte index prefix
MAX_1BYTE_INDEX = 255  # Maximum index for 1-byte qualifier


class ControlMode(Enum):
    """Mode of control operation."""

    SELECT_BEFORE_OPERATE = auto()  # Two-step: SELECT then OPERATE
    DIRECT_OPERATE = auto()  # Single-step operation
    DIRECT_OPERATE_NO_ACK = auto()  # No acknowledgment


@dataclass(frozen=True)
class ControlOperation:
    """A control operation to perform.

    Attributes:
        index: Point index.
        control_code: Control code for binary outputs.
        count: Operation count.
        on_time: On time in milliseconds.
        off_time: Off time in milliseconds.
        analog_value: Value for analog outputs.
        is_analog: True if this is an analog output.
    """

    index: int
    control_code: ControlCode = ControlCode.LATCH_ON
    count: int = 1
    on_time: int = 0
    off_time: int = 0
    analog_value: float = 0.0
    is_analog: bool = False


@dataclass
class CommandTask(ABC):
    """Base class for command tasks.

    Attributes:
        operations: List of control operations.
        mode: Control mode.
    """

    operations: list[ControlOperation] = field(default_factory=list)
    mode: ControlMode = ControlMode.SELECT_BEFORE_OPERATE

    @abstractmethod
    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build the command request.

        Args:
            seq: Sequence number for request.

        Returns:
            Request fragment for this command.
        """
        ...

    def add_operation(self, operation: ControlOperation) -> None:
        """Add an operation to this command.

        Args:
            operation: Control operation to add.
        """
        self.operations.append(operation)


@dataclass
class SelectTask(CommandTask):
    """SELECT request for select-before-operate.

    First step of two-step control operation.
    """

    mode: ControlMode = field(default=ControlMode.SELECT_BEFORE_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build SELECT request."""
        blocks = self._build_control_blocks()
        return build_select_request(objects=tuple(blocks), seq=seq)

    def _build_control_blocks(self) -> list[ObjectBlock]:
        """Build object blocks for control operations."""
        blocks: list[ObjectBlock] = []

        # Group by type
        binary_ops = [op for op in self.operations if not op.is_analog]
        analog_ops = [op for op in self.operations if op.is_analog]

        if binary_ops:
            blocks.append(self._build_crob_block(binary_ops))

        if analog_ops:
            blocks.append(self._build_analog_block(analog_ops))

        return blocks

    def _build_crob_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build CROB object block."""
        # Qualifier: 1-byte count, 1-byte index prefix
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )

        data = bytearray()
        # Count
        data.append(len(operations))

        for op in operations:
            # Index (1 or 2 bytes)
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            # CROB: control code (1) + count (1) + on_time (4) + off_time (4) + status (1)
            data.append(int(op.control_code))
            data.append(op.count)
            data.extend(op.on_time.to_bytes(4, "little"))
            data.extend(op.off_time.to_bytes(4, "little"))
            data.append(0)  # Status (request)

        header = ObjectHeader(
            group=CROB_GROUP,
            variation=CROB_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))

    def _build_analog_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build analog output object block."""
        # Use 32-bit integer by default
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )

        data = bytearray()
        # Count
        data.append(len(operations))

        for op in operations:
            # Index
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            # Value (32-bit signed) + status
            int_value = int(op.analog_value)
            data.extend(int_value.to_bytes(4, "little", signed=True))
            data.append(0)  # Status

        header = ObjectHeader(
            group=ANALOG_OUTPUT_GROUP,
            variation=ANALOG_OUTPUT_32_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))


@dataclass
class OperateTask(CommandTask):
    """OPERATE request for select-before-operate.

    Second step of two-step control operation.
    """

    mode: ControlMode = field(default=ControlMode.SELECT_BEFORE_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build OPERATE request."""
        blocks = self._build_control_blocks()
        return build_operate_request(objects=tuple(blocks), seq=seq)

    def _build_control_blocks(self) -> list[ObjectBlock]:
        """Build object blocks for control operations."""
        # Same as SelectTask
        blocks: list[ObjectBlock] = []
        binary_ops = [op for op in self.operations if not op.is_analog]
        analog_ops = [op for op in self.operations if op.is_analog]

        if binary_ops:
            blocks.append(self._build_crob_block(binary_ops))
        if analog_ops:
            blocks.append(self._build_analog_block(analog_ops))

        return blocks

    def _build_crob_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build CROB object block."""
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )
        data = bytearray()
        data.append(len(operations))

        for op in operations:
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            data.append(int(op.control_code))
            data.append(op.count)
            data.extend(op.on_time.to_bytes(4, "little"))
            data.extend(op.off_time.to_bytes(4, "little"))
            data.append(0)

        header = ObjectHeader(
            group=CROB_GROUP,
            variation=CROB_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))

    def _build_analog_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build analog output object block."""
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )
        data = bytearray()
        data.append(len(operations))

        for op in operations:
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            int_value = int(op.analog_value)
            data.extend(int_value.to_bytes(4, "little", signed=True))
            data.append(0)

        header = ObjectHeader(
            group=ANALOG_OUTPUT_GROUP,
            variation=ANALOG_OUTPUT_32_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))


@dataclass
class DirectOperateTask(CommandTask):
    """DIRECT_OPERATE request for single-step control.

    Performs operation without prior SELECT.
    """

    mode: ControlMode = field(default=ControlMode.DIRECT_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build DIRECT_OPERATE request."""
        blocks = self._build_control_blocks()
        return build_direct_operate_request(objects=tuple(blocks), seq=seq)

    def _build_control_blocks(self) -> list[ObjectBlock]:
        """Build object blocks for control operations."""
        blocks: list[ObjectBlock] = []
        binary_ops = [op for op in self.operations if not op.is_analog]
        analog_ops = [op for op in self.operations if op.is_analog]

        if binary_ops:
            blocks.append(self._build_crob_block(binary_ops))
        if analog_ops:
            blocks.append(self._build_analog_block(analog_ops))

        return blocks

    def _build_crob_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build CROB object block."""
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )
        data = bytearray()
        data.append(len(operations))

        for op in operations:
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            data.append(int(op.control_code))
            data.append(op.count)
            data.extend(op.on_time.to_bytes(4, "little"))
            data.extend(op.off_time.to_bytes(4, "little"))
            data.append(0)

        header = ObjectHeader(
            group=CROB_GROUP,
            variation=CROB_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))

    def _build_analog_block(self, operations: list[ControlOperation]) -> ObjectBlock:
        """Build analog output object block."""
        qualifier = (
            QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX
        )
        data = bytearray()
        data.append(len(operations))

        for op in operations:
            if qualifier == QUALIFIER_1BYTE_INDEX:
                data.append(op.index)
            else:
                data.extend(op.index.to_bytes(2, "little"))

            int_value = int(op.analog_value)
            data.extend(int_value.to_bytes(4, "little", signed=True))
            data.append(0)

        header = ObjectHeader(
            group=ANALOG_OUTPUT_GROUP,
            variation=ANALOG_OUTPUT_32_VARIATION,
            qualifier=qualifier,
        )
        return ObjectBlock(header=header, data=bytes(data))


class CommandBuilder:
    """Builder for creating control commands.

    Provides a fluent interface for building control operations.
    """

    def __init__(self) -> None:
        """Initialize the builder."""
        self._operations: list[ControlOperation] = []

    def add_crob(
        self,
        index: int,
        code: ControlCode,
        count: int = 1,
        on_time: int = 0,
        off_time: int = 0,
    ) -> "CommandBuilder":
        """Add a CROB operation.

        Args:
            index: Point index.
            code: Control code.
            count: Operation count.
            on_time: On time in milliseconds.
            off_time: Off time in milliseconds.

        Returns:
            Self for chaining.
        """
        self._operations.append(
            ControlOperation(
                index=index,
                control_code=code,
                count=count,
                on_time=on_time,
                off_time=off_time,
                is_analog=False,
            )
        )
        return self

    def add_analog(self, index: int, value: float) -> "CommandBuilder":
        """Add an analog output operation.

        Args:
            index: Point index.
            value: Analog value.

        Returns:
            Self for chaining.
        """
        self._operations.append(
            ControlOperation(
                index=index,
                analog_value=value,
                is_analog=True,
            )
        )
        return self

    def latch_on(self, index: int) -> "CommandBuilder":
        """Add a latch-on operation.

        Args:
            index: Point index.

        Returns:
            Self for chaining.
        """
        return self.add_crob(index, ControlCode.LATCH_ON)

    def latch_off(self, index: int) -> "CommandBuilder":
        """Add a latch-off operation.

        Args:
            index: Point index.

        Returns:
            Self for chaining.
        """
        return self.add_crob(index, ControlCode.LATCH_OFF)

    def pulse_on(self, index: int, on_time: int = 1000, off_time: int = 0, count: int = 1) -> "CommandBuilder":
        """Add a pulse-on operation.

        Args:
            index: Point index.
            on_time: On time in milliseconds.
            off_time: Off time in milliseconds.
            count: Number of pulses.

        Returns:
            Self for chaining.
        """
        return self.add_crob(index, ControlCode.PULSE_ON, count, on_time, off_time)

    def pulse_off(self, index: int, on_time: int = 0, off_time: int = 1000, count: int = 1) -> "CommandBuilder":
        """Add a pulse-off operation.

        Args:
            index: Point index.
            on_time: On time in milliseconds.
            off_time: Off time in milliseconds.
            count: Number of pulses.

        Returns:
            Self for chaining.
        """
        return self.add_crob(index, ControlCode.PULSE_OFF, count, on_time, off_time)

    def build_select(self) -> SelectTask:
        """Build a SELECT task.

        Returns:
            SelectTask with all operations.
        """
        task = SelectTask()
        task.operations = self._operations.copy()
        return task

    def build_operate(self) -> OperateTask:
        """Build an OPERATE task.

        Returns:
            OperateTask with all operations.
        """
        task = OperateTask()
        task.operations = self._operations.copy()
        return task

    def build_direct_operate(self) -> DirectOperateTask:
        """Build a DIRECT_OPERATE task.

        Returns:
            DirectOperateTask with all operations.
        """
        task = DirectOperateTask()
        task.operations = self._operations.copy()
        return task

    def clear(self) -> "CommandBuilder":
        """Clear all operations.

        Returns:
            Self for chaining.
        """
        self._operations.clear()
        return self
