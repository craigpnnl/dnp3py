"""Command operations for DNP3 master.

Provides classes for building and executing control commands
including SELECT, OPERATE, and DIRECT_OPERATE.
"""

import struct
from abc import ABC, abstractmethod
from collections.abc import Callable
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

# How each g41 variation encodes its requested value (IEEE 1815-2012 A.20.1 to A.20.4):
# little-endian, the control status octet follows the value in the request.
_ANALOG_VALUE_FORMATS: dict[int, str] = {
    ANALOG_OUTPUT_32_VARIATION: "<i",
    ANALOG_OUTPUT_16_VARIATION: "<h",
    ANALOG_OUTPUT_FLOAT_VARIATION: "<f",
    ANALOG_OUTPUT_DOUBLE_VARIATION: "<d",
}
_INTEGER_ANALOG_VARIATIONS = frozenset({ANALOG_OUTPUT_32_VARIATION, ANALOG_OUTPUT_16_VARIATION})

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
        variation: Group 41 variation an analog value is sent as: 1 (INT32),
            2 (INT16), 3 (FLT32) or 4 (FLT64). Ignored for binary outputs.
    """

    index: int
    control_code: ControlCode = ControlCode.LATCH_ON
    count: int = 1
    on_time: int = 0
    off_time: int = 0
    analog_value: float = 0.0
    is_analog: bool = False
    variation: int = ANALOG_OUTPUT_32_VARIATION

    def __post_init__(self) -> None:
        """Refuse an analog variation A.20 does not define."""
        if self.is_analog and self.variation not in _ANALOG_VALUE_FORMATS:
            msg = f"Analog output variation {self.variation} is not one of {sorted(_ANALOG_VALUE_FORMATS)}"
            raise ValueError(msg)


def _qualifier_for(operations: list[ControlOperation]) -> int:
    """1-byte or 2-byte index prefix, by the largest index in the block."""
    return QUALIFIER_1BYTE_INDEX if max(op.index for op in operations) <= MAX_1BYTE_INDEX else QUALIFIER_2BYTE_INDEX


def _prefixed_records(operations: list[ControlOperation], encode: Callable[[ControlOperation], bytes]) -> bytes:
    """Count octet, then each operation's index prefix and encoded record."""
    qualifier = _qualifier_for(operations)
    data = bytearray()
    data.append(len(operations))
    for op in operations:
        if qualifier == QUALIFIER_1BYTE_INDEX:
            data.append(op.index)
        else:
            data.extend(op.index.to_bytes(2, "little"))
        data.extend(encode(op))
    return bytes(data)


def _encode_crob(op: ControlOperation) -> bytes:
    """g12v1 record: control code (1), count (1), on-time (4), off-time (4), status (1)."""
    return (
        bytes([int(op.control_code), op.count])
        + op.on_time.to_bytes(4, "little")
        + op.off_time.to_bytes(4, "little")
        + bytes([0])  # Status (request)
    )


def _encode_analog(op: ControlOperation) -> bytes:
    """g41 record: the requested value in the operation's variation, then a status octet.

    Integer variations truncate the value toward zero, as before variations were
    selectable; a value the variation cannot hold is refused rather than wrapped.

    Raises:
        ValueError: The value does not fit the variation's integer range.
    """
    value_format = _ANALOG_VALUE_FORMATS[op.variation]
    value: float | int = int(op.analog_value) if op.variation in _INTEGER_ANALOG_VARIATIONS else op.analog_value
    try:
        encoded = struct.pack(value_format, value)
    except (struct.error, OverflowError) as exc:
        msg = f"Analog value {op.analog_value!r} does not fit g41v{op.variation}: {exc}"
        raise ValueError(msg) from exc
    return encoded + bytes([0])  # Status (request)


def build_crob_block(operations: list[ControlOperation]) -> ObjectBlock:
    """Build one g12v1 object block holding every binary operation."""
    header = ObjectHeader(group=CROB_GROUP, variation=CROB_VARIATION, qualifier=_qualifier_for(operations))
    return ObjectBlock(header=header, data=_prefixed_records(operations, _encode_crob))


def build_analog_blocks(operations: list[ControlOperation]) -> list[ObjectBlock]:
    """Build one g41 object block per variation used by the analog operations.

    A block carries one variation (its header names it), so operations of
    different variations in one request become separate blocks, in order of
    first appearance.
    """
    by_variation: dict[int, list[ControlOperation]] = {}
    for op in operations:
        by_variation.setdefault(op.variation, []).append(op)
    return [
        ObjectBlock(
            header=ObjectHeader(group=ANALOG_OUTPUT_GROUP, variation=variation, qualifier=_qualifier_for(ops)),
            data=_prefixed_records(ops, _encode_analog),
        )
        for variation, ops in by_variation.items()
    ]


def build_control_blocks(operations: list[ControlOperation]) -> list[ObjectBlock]:
    """Object blocks for a command request: binary operations first, then analog, by variation."""
    blocks: list[ObjectBlock] = []
    binary_ops = [op for op in operations if not op.is_analog]
    analog_ops = [op for op in operations if op.is_analog]
    if binary_ops:
        blocks.append(build_crob_block(binary_ops))
    blocks.extend(build_analog_blocks(analog_ops))
    return blocks


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

    def _build_control_blocks(self) -> list[ObjectBlock]:
        """Build object blocks for control operations."""
        return build_control_blocks(self.operations)


@dataclass
class SelectTask(CommandTask):
    """SELECT request for select-before-operate.

    First step of two-step control operation.
    """

    mode: ControlMode = field(default=ControlMode.SELECT_BEFORE_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build SELECT request."""
        return build_select_request(objects=tuple(self._build_control_blocks()), seq=seq)


@dataclass
class OperateTask(CommandTask):
    """OPERATE request for select-before-operate.

    Second step of two-step control operation.
    """

    mode: ControlMode = field(default=ControlMode.SELECT_BEFORE_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build OPERATE request."""
        return build_operate_request(objects=tuple(self._build_control_blocks()), seq=seq)


@dataclass
class DirectOperateTask(CommandTask):
    """DIRECT_OPERATE request for single-step control.

    Performs operation without prior SELECT.
    """

    mode: ControlMode = field(default=ControlMode.DIRECT_OPERATE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build DIRECT_OPERATE request."""
        return build_direct_operate_request(objects=tuple(self._build_control_blocks()), seq=seq)


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

    def add_analog(self, index: int, value: float, variation: int = ANALOG_OUTPUT_32_VARIATION) -> "CommandBuilder":
        """Add an analog output operation.

        Args:
            index: Point index.
            value: Analog value.
            variation: Group 41 variation to send the value as: 1 (INT32, the
                default), 2 (INT16), 3 (FLT32) or 4 (FLT64).

        Returns:
            Self for chaining.

        Raises:
            ValueError: The variation is not one of the four A.20 defines.
        """
        self._operations.append(
            ControlOperation(
                index=index,
                analog_value=value,
                is_analog=True,
                variation=variation,
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
